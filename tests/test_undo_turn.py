"""Slice 50 beyond its acceptance set: several changes of one file in one turn, a turn still
running, a turn of another conversation, the turns a restore takes back (and one that ended
since it was looked at), a kept working copy discarded, a file another agent holds, a file
outside the project, and what is done but not on record to take back."""

import json
from types import SimpleNamespace

from sqlalchemy import select

from app import handoff, ledger, observer
from app.agent import AgentRunner
from app.db.models import Agent, FileChange, Merge, Message, ToolCall
from tests.test_agent_writes import edit, read, wait_status, write
from tests.test_chat_flow import start, text
from tests.test_claim_scenarios import write as copy_write
from tests.test_copy_later_scenarios import again
from tests.test_copy_runner import at_work, card_of, kept_folders
from tests.test_copy_scenarios import files
from tests.test_spawn import call, step

ORIGIN = {"Origin": "http://127.0.0.1:8790"}


def conversation(client, project_dir, mode="full_auto"):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    patched = client.patch(
        f"/api/conversations/{cid}",
        json={"permission_mode": mode, "lead_hands_code": False},  # the Lead writes itself
        headers=ORIGIN,
    )
    assert patched.status_code == 200, patched.text
    return pid, cid


def turn(client, wait_run, cid, words, **more):
    sent = client.post(f"/api/conversations/{cid}/messages", json={"content": words, **more})
    run_id = sent.json()["run"]["id"]
    wait_run(client, cid, run_id)
    return run_id


def test_several_changes_of_one_file_in_one_turn_are_undone_latest_first(
    make_client, wait_run, project_dir
):
    client, _model = make_client(
        [edit(old="hi", new="hello"), edit(old="hello", new="hey", id="w2"), text("done")]
    )
    _pid, cid = conversation(client, project_dir)
    run_id = turn(client, wait_run, cid, "change it twice")
    assert read(project_dir) == "print('hey')\n"

    ahead = client.get(f"/api/runs/{run_id}/undo").json()
    assert ahead["revert"] == ["hello.py", "hello.py"] and ahead["skip"] == []
    done = client.post(f"/api/runs/{run_id}/undo", headers=ORIGIN).json()
    assert done["revert"] == ["hello.py", "hello.py"] and done["skip"] == []
    assert done["note"] is None
    assert read(project_dir) == "print('hi')\n"
    statuses = {c["status"] for c in client.get(f"/api/conversations/{cid}").json()["file_changes"]}
    assert statuses == {"reverted"}


def test_a_running_turn_is_not_undone_until_it_is_stopped(make_client, project_dir):
    client, _model = make_client([write("a.txt", "one\n"), text("made a")])
    _pid, cid = conversation(client, project_dir, "ask")
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "make a"}).json()[
        "run"]["id"]
    wait_status(client, cid, "waiting_approval")

    for asked in (client.get(f"/api/runs/{run_id}/undo"),
                  client.post(f"/api/runs/{run_id}/undo", headers=ORIGIN),
                  client.get(f"/api/conversations/{cid}/restore", params={"before": run_id})):
        assert asked.status_code == 409 and "stop" in asked.json()["detail"]


def test_restore_is_only_of_a_turn_of_that_conversation(make_client, wait_run, project_dir):
    client, _model = make_client([text("hi"), text("hi")])
    cid, run_id = start(client, project_dir, "one")
    wait_run(client, cid, run_id)
    other, _ = start(client, project_dir, "two")
    assert client.get(f"/api/conversations/{other}/restore", params={"before": run_id}).status_code == 404
    assert client.get("/api/runs/nope/undo").status_code == 404


def test_restore_names_every_turn_it_takes_back_whatever_its_topic(make_client, wait_run, project_dir):
    client, _model = make_client([
        write("a.txt", "a\n"), text("made a"), write("b.txt", "b\n"), text("made b"),
        write("c.txt", "c\n"), text("made c"),
    ])
    _pid, cid = conversation(client, project_dir)
    turn(client, wait_run, cid, "make a")
    second = turn(client, wait_run, cid, "make b")
    third = turn(client, wait_run, cid, "something else: make c", new_topic=True)

    ahead = client.get(f"/api/conversations/{cid}/restore", params={"before": second}).json()
    # The topic's name is its first turn's ("make a"): each turn says its own request too (live:
    # "Open one Reviewer…: turn 3" for a turn that asked "eight").
    assert ahead["turns"] == [
        {"run_id": second, "topic": "make a", "turn": 2, "request": "make b"},
        {"run_id": third, "topic": "something else: make c", "turn": 1, "request": "something else: make c"},
    ]
    assert sorted(ahead["revert"]) == ["b.txt", "c.txt"]
    done = client.post(f"/api/conversations/{cid}/restore",
                       params={"before": second, "through": third}, headers=ORIGIN)
    assert done.status_code == 200, done.text
    assert sorted(done.json()["revert"]) == ["b.txt", "c.txt"] and read(project_dir, "a.txt") == "a\n"


def test_a_turn_that_ended_since_the_look_ahead_is_not_taken_back_unseen(
    make_client, wait_run, project_dir
):
    client, _model = make_client([write("a.txt", "a\n"), text("made a"), write("b.txt", "b\n"),
                                  text("made b")])
    _pid, cid = conversation(client, project_dir)
    first = turn(client, wait_run, cid, "make a")
    ahead = client.get(f"/api/conversations/{cid}/restore", params={"before": first}).json()
    assert [t["run_id"] for t in ahead["turns"]] == [first]
    second = turn(client, wait_run, cid, "make b")  # a trigger's, say, while the card is open

    stale = client.post(f"/api/conversations/{cid}/restore",
                        params={"before": first, "through": first}, headers=ORIGIN)
    assert stale.status_code == 409 and "look again" in stale.json()["detail"]
    assert read(project_dir, "a.txt") == "a\n" and read(project_dir, "b.txt") == "b\n"
    done = client.post(f"/api/conversations/{cid}/restore",
                       params={"before": first, "through": second}, headers=ORIGIN)
    assert sorted(done.json()["revert"]) == ["a.txt", "b.txt"]


def test_a_file_another_agent_holds_is_skipped_and_said(make_client, wait_run, project_dir):
    client, _model = make_client([write("a.txt", "a\n"), text("made a")])
    _pid, cid = conversation(client, project_dir)
    run_id = turn(client, wait_run, cid, "make a")
    client.app.state.runner.holds = lambda root, path: ("someone", "Coder")
    done = client.post(f"/api/runs/{run_id}/undo", headers=ORIGIN).json()
    assert done["revert"] == [] and done["skip"][0]["path"] == "a.txt"
    assert "Coder is changing a.txt now" in done["skip"][0]["why"]
    assert read(project_dir, "a.txt") == "a\n"


def test_a_change_outside_the_project_is_undone_where_it_is(
    make_client, wait_run, project_dir, tmp_path
):
    other = tmp_path / "other"
    other.mkdir()
    (other / "notes.md").write_text("other notes\n", encoding="utf-8")
    client, _model = make_client([
        step(call("write_file", {"path": str(other / "notes.md"), "content": "new\n"}, "w")),
        text("done")])
    pid, cid = conversation(client, project_dir, "auto_edit")
    client.patch(f"/api/conversations/{cid}", json={"also_in": [str(other)]}, headers=ORIGIN)
    run_id = turn(client, wait_run, cid, "go")
    assert (other / "notes.md").read_text(encoding="utf-8") == "new\n"
    done = client.post(f"/api/runs/{run_id}/undo", headers=ORIGIN).json()
    assert done["revert"] == [str(other / "notes.md")]
    assert (other / "notes.md").read_text(encoding="utf-8") == "other notes\n"


def test_a_kept_working_copy_is_discarded_and_what_it_had_applied_reverted(
    settings_env, project_dir, monkeypatch
):
    """The real Discard: the folder goes, its records are closed, and what was taken from it
    into the project is reverted with the rest."""
    cid = at_work(settings_env, project_dir, [
        step(copy_write("a.txt", "A")), step(copy_write("b.txt", "B", "w2"))])
    real = AgentRunner._apply_file

    def apply_file(self, ctx, copy, ws, path, together=False):
        # (held open by another program, say)
        return "could not be written" if path == "b.txt" else real(
            self, ctx, copy, ws, path, together)

    monkeypatch.setattr(AgentRunner, "_apply_file", apply_file)
    with again(settings_env) as client:
        card = card_of(client, cid)
        assert files(client.post(f"/api/merges/{card['id']}/approve").json()) == {
            "a.txt": "applied", "b.txt": "ready"}
        (folder,) = kept_folders(settings_env)
        run_id = card["run_id"]
        (project_dir / "b.txt").write_text("THE USER'S OWN", encoding="utf-8")   # meanwhile

        ahead = client.get(f"/api/runs/{run_id}/undo").json()
        assert ahead["copies"] == [{"folder": card["kept_in"], "files": ["b.txt"]}]
        assert ahead["revert"] == ["a.txt"] and folder.exists()
        done = client.post(f"/api/runs/{run_id}/undo", headers=ORIGIN).json()
        assert done["copies"] == ahead["copies"] and done["revert"] == ["a.txt"]
        assert kept_folders(settings_env) == []
        assert not (project_dir / "a.txt").exists()
        assert (project_dir / "b.txt").read_text(encoding="utf-8") == "THE USER'S OWN"
        with client.app.state.session_factory() as session:
            assert session.scalars(select(FileChange).where(FileChange.status == "in_copy")).all() == []


def test_a_kept_copy_that_is_not_discarded_is_said(make_client, wait_run, project_dir):
    client, _model = make_client([text("hi")])
    _pid, cid = conversation(client, project_dir)
    run_id = turn(client, wait_run, cid, "one")
    lead = client.get(f"/api/conversations/{cid}").json()["agents"][0]["id"]
    with client.app.state.session_factory() as session:
        session.add(Merge(run_id=run_id, agent_id=lead, status="interrupted", kept_in="kept",
                          files=[{"path": "c.txt", "state": "ready"}]))
        session.commit()

    async def decide_kept(merge_id, decision, choices=None):
        return False  # a decision on it is already under way

    client.app.state.runner.decide_kept = decide_kept
    done = client.post(f"/api/runs/{run_id}/undo", headers=ORIGIN).json()
    assert done["copies"] == [] and done["reject"] == []
    assert done["skip"] == [{"path": "c.txt",
                             "why": "its working copy was not discarded; decide it on its card"}]


def test_what_is_done_but_not_on_record_to_take_back_is_said(make_client, wait_run, project_dir):
    client, _model = make_client([text("hi")])
    _pid, cid = conversation(client, project_dir)
    run_id = turn(client, wait_run, cid, "one")
    snap = client.get(f"/api/conversations/{cid}").json()
    lead = snap["agents"][0]["id"]
    with client.app.state.session_factory() as session:
        message = session.scalars(select(Message).where(Message.run_id == run_id)).first()
        session.add_all([
            ToolCall(run_id=run_id, agent_id=lead, message_id=message.id, seq=90,
                     provider_call_id="n1", name="files_changed", arguments=json.dumps({"count": 3}),
                     status="succeeded", origin="cli",
                     result="3 more files changed at the same time; they are not recorded one by one"),
            ToolCall(run_id=run_id, agent_id=lead, message_id=message.id, seq=91,
                     provider_call_id="n2", name="write_file",
                     arguments=json.dumps({"path": "C:/elsewhere/x.txt"}), status="succeeded",
                     origin="cli", result="changed a file outside the project folder; KOLONİ keeps no copy"),
            Merge(run_id=run_id, agent_id=lead, status="applied", files=[],
                  commit={"state": "committed", "sha": "abc1234def", "message": "m"}),
        ])
        session.commit()
    ahead = client.get(f"/api/runs/{run_id}/undo").json()
    assert ahead["stays"] == [
        "3 more files changed at the same time; they are not recorded one by one",
        "C:/elsewhere/x.txt — changed a file outside the project folder; KOLONİ keeps no copy",
        "KOLONİ's commit abc1234 of what was taken stays in git history",
    ]


def test_a_write_into_the_scratch_is_undone_but_in_no_list_of_what_the_turn_changed(
    make_client, wait_run, project_dir
):
    """K-koloni-klasor: KOLONİ's own write into `.koloni/tmp/` stays on record for its undo,
    and is left out of what the turn is told as changed - the summariser's turn, the handoff's
    files, the record of the turn."""
    client, _model = make_client([
        write(".koloni/tmp/a.txt", "scratch\n"), write("src/b.py", "b = 1\n", id="w2"),
        text("done"),
    ])
    _pid, cid = conversation(client, project_dir)
    run_id = turn(client, wait_run, cid, "make b")
    assert (project_dir / ".koloni/tmp/a.txt").is_file() and (project_dir / "src/b.py").is_file()
    with client.app.state.session_factory() as session:
        lead = session.scalars(select(Agent).where(Agent.run_id == run_id)).one()
        said = AgentRunner._turn_in_words(session, SimpleNamespace(run_id=run_id, name=lead.name))
        assert 'Files changed in the turn: "src/b.py"' in said and "koloni" not in said
        assert handoff._files(session, str(project_dir), lead) == [
            '"src/b.py" (added, taken in; as it left it)']
        assert "koloni" not in (ledger.of_turn(session, run_id) or "")
        assert handoff.on_file(session, _pid, ".koloni/tmp/a.txt") is None
        record = observer.on_record(session, lead.id)
        assert "src/b.py" in record and ".koloni" not in record
    done = client.post(f"/api/runs/{run_id}/undo", headers=ORIGIN).json()
    assert sorted(done["revert"]) == [".koloni/tmp/a.txt", "src/b.py"]
    assert not (project_dir / ".koloni/tmp/a.txt").exists() and not (project_dir / "src/b.py").exists()
