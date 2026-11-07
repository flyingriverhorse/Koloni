"""Working copies that were kept, after the review of slice 19c: what Apply and Discard on a
kept card may do, what a kept copy's own folder is trusted with, and that one copy that
cannot be read never keeps the app from starting.
"""

import asyncio
import json
import os
import shutil
import threading

import pytest
from sqlalchemy import select

from app import copies
from app.agent import AgentRunner
from app.config import load_settings
from app.db.models import Agent, FileChange, Merge
from app.db.session import make_engine, make_session_factory, upgrade_db
from app.main import create_app
from tests.keyed import TestClient
from tests.test_chat_flow import text
from tests.test_claim_scenarios import calls, write
from tests.test_copy_later_scenarios import MAKES, again, interrupted
from tests.test_copy_runner import (
    ORIGIN,
    a_change,
    an_agent,
    at_work,
    card_of,
    kept_folders,
    on_record,
    short_name,
    unreadable_once,
)
from tests.test_copy_scenarios import files, one, run, seen
from tests.test_spawn import call, step
from tests.test_trigger_scenarios import allow, run_now, trigger

# --- what a decision on a kept card may do ---------------------------------------------------


def test_apply_on_a_card_that_is_only_to_discard_is_refused_and_deletes_nothing(
    settings_env, project_dir, monkeypatch
):
    """The copy could not be compared at the start, though what it was made from is there."""
    cid = interrupted(settings_env, project_dir)
    (folder,) = kept_folders(settings_env)
    unreadable_once(monkeypatch)
    with again(settings_env) as client:
        card = card_of(client, cid)
        assert card["status"] == "kept" and files(card) == {"a.txt": "refused"}
        assert client.post(f"/api/merges/{card['id']}/approve").status_code == 409
        assert (folder / "tree" / "a.txt").read_text(encoding="utf-8") == "A"
        assert not (project_dir / "a.txt").exists()
        assert card_of(client, cid)["status"] == "kept"
        assert client.post(f"/api/merges/{card['id']}/reject").status_code == 200
        assert kept_folders(settings_env) == []


def test_a_file_the_kept_copy_no_longer_changes_leaves_the_card_and_the_copy_is_done_with(
    settings_env, project_dir
):
    cid = interrupted(settings_env, project_dir)
    (folder,) = kept_folders(settings_env)
    with again(settings_env) as client:
        card = card_of(client, cid)
        assert files(card) == {"a.txt": "ready"}
        (folder / "tree" / "a.txt").unlink()            # since the card was shown
        said = client.post(f"/api/merges/{card['id']}/approve")
        assert said.status_code == 200 and said.json()["files"] == []
        assert said.json()["status"] == "discarded"
        assert not (project_dir / "a.txt").exists() and kept_folders(settings_env) == []


def test_after_a_restart_a_card_apply_took_nothing_of_is_as_it_was_shown_again(
    settings_env, project_dir
):
    """Apply took nothing and showed a file again (B-56): the copy stays, and so does the
    card as it was shown again; its Apply, with the user's word on that file, takes it."""
    cid = at_work(settings_env, project_dir, [
        step(write("a.txt", "A")), step(write("b.txt", "B", "w2"))])
    with again(settings_env) as client:
        card = card_of(client, cid)
        assert files(card) == {"a.txt": "ready", "b.txt": "ready"}
        (project_dir / "b.txt").write_text("THE USER'S OWN", encoding="utf-8")   # since
        assert client.post(f"/api/merges/{card['id']}/approve").status_code == 409
    with again(settings_env) as client:
        card = card_of(client, cid)
        assert files(card) == {"a.txt": "ready", "b.txt": "conflict"}
        assert not (project_dir / "a.txt").exists()
        said = client.post(f"/api/merges/{card['id']}/approve",
                           json={"choices": {"b.txt": "project"}, "shown": seen(card)})
        assert said.status_code == 200 and said.json()["status"] == "applied"
        assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"
        assert (project_dir / "b.txt").read_text(encoding="utf-8") == "THE USER'S OWN"
        assert kept_folders(settings_env) == []


def test_apply_for_a_turn_nobody_watched_looks_again_at_where_each_path_leads(
    settings_env, project_dir
):
    """A folder of the project became a link into a protected one after the card was shown:
    the file is refused, and its copy is not thrown away with an Apply that took nothing."""
    cid = at_work(settings_env, project_dir, [step(write("sub/new.txt", "x"))], unattended=True)
    (folder,) = kept_folders(settings_env)
    with again(settings_env) as client:
        card = card_of(client, cid)
        assert files(card) == {"sub/new.txt": "ready"}
        (project_dir / ".claude").mkdir()
        copies._link(project_dir / "sub", project_dir / ".claude")
        said = client.post(f"/api/merges/{card['id']}/approve")
        assert said.status_code == 409 and said.json()["detail"].startswith("sub/new.txt changed")
        said = card_of(client, cid)
        assert said["status"] == "kept" and files(said) == {"sub/new.txt": "refused"}
        assert "no trigger allows" in said["files"][0]["note"]
        assert list((project_dir / ".claude").iterdir()) == []
        assert (folder / "tree" / "sub" / "new.txt").read_text(encoding="utf-8") == "x"
        # nothing of it is left to apply: only to discard
        assert client.post(f"/api/merges/{card['id']}/approve").status_code == 409
        assert (folder / "tree" / "sub" / "new.txt").is_file()


def test_a_decision_on_one_kept_folder_leaves_the_records_of_the_agents_other_one(
    tmp_path, settings
):
    upgrade_db(settings.db_path)
    factory = make_session_factory(make_engine(settings.db_path))
    project = tmp_path / "proj"
    project.mkdir()
    first, second = (copies.make(project, settings.runtime_root, name) for name in ("x", "x-2"))
    (first.root / "a.txt").write_text("A", encoding="utf-8")
    (second.root / "b.txt").write_text("A", encoding="utf-8")   # as its record has it
    with factory() as s:
        on_record(s, project)
        an_agent(s, "x")
        a_change(s, "f1", "x", "a.txt")
        a_change(s, "f2", "x", "b.txt")
        s.commit()
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8790") as client:
        client.headers["Origin"] = ORIGIN
        with factory() as s:
            by_folder = {m.kept_in: m.id for m in s.scalars(select(Merge))}
        assert set(by_folder) == {str(first.root), str(second.root)}
        assert client.post(f"/api/merges/{by_folder[str(first.root)]}/reject").status_code == 200
        with factory() as s:
            assert {c.id: c.status for c in s.scalars(select(FileChange))} == {
                "f1": "rejected", "f2": "in_copy"}
        assert (second.root / "b.txt").read_text(encoding="utf-8") == "A"
        assert client.post(f"/api/merges/{by_folder[str(second.root)]}/approve").status_code == 200
        with factory() as s:
            assert s.get_one(FileChange, "f2").status == "applied"
        assert (project / "b.txt").read_text(encoding="utf-8") == "A"


def test_a_kept_card_is_decided_once_though_two_decisions_overlap(
    settings_env, project_dir, monkeypatch
):
    cid = interrupted(settings_env, project_dir)
    entered, go = threading.Event(), threading.Event()

    async def seen(self, ctx, paths):
        entered.set()
        while not go.is_set():
            await asyncio.sleep(0.01)

    monkeypatch.setattr(AgentRunner, "_seen_by_watchers", seen)
    with again(settings_env) as client:
        card, runner = card_of(client, cid), client.app.state.runner
        first = client.portal.start_task_soon(runner.decide_kept, card["id"], "approve")
        try:
            assert entered.wait(5)
            # the first is between its files and its record: a second finds nothing to decide
            assert client.portal.call(runner.decide_kept, card["id"], "reject") is False
            assert client.post(f"/api/merges/{card['id']}/reject").status_code == 409
        finally:
            go.set()
        assert first.result(5) is True
        assert card_of(client, cid)["status"] == "applied"
        assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"


# --- kept while the app runs -----------------------------------------------------------------


def test_a_copy_kept_by_an_error_is_shown_at_once_as_it_is_after_a_restart(
    make_client, wait_run, project_dir, monkeypatch
):
    """The copy and what it was made from are in hand: its card is not only to discard."""

    def record(self, *given):
        raise RuntimeError("the database is locked")

    monkeypatch.setattr(AgentRunner, "_record_merge", record)
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), text("A done")], permission_mode="ask")
    snap = wait_run(client, cid, run_id)
    (card,) = snap["merges"]
    assert card["status"] == "kept" and files(card) == {"a.txt": "ready"}
    assert "+A" in card["files"][0]["diff"]
    assert client.post(f"/api/merges/{card['id']}/approve").status_code == 200
    snap = client.get(f"/api/conversations/{cid}").json()
    assert snap["merges"][0]["status"] == "applied"
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"
    assert [f["status"] for f in snap["file_changes"]] == ["applied"]
    assert not copies.folder(client.app.state.settings.runtime_root).joinpath(
        card["agent_id"]).exists()


def test_nobody_watching_and_no_leave_to_write_the_agent_is_not_told_its_changes_are_taken(
    make_client, wait_run, project_dir
):
    (project_dir / "make.py").write_text("open('made.txt', 'w').write('m')\n", encoding="utf-8")
    client, model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "do it"}, "s")),
                 text("done")],
        "Coder": [step(run("python make.py")), text("A done")],
    })
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    made = trigger(client, pid, cid, permissions={
        "write": False, "commands": [allow(client, cid, "python make.py")], "agents": 1})
    snap = wait_run(client, cid, run_now(client, made["id"]), timeout=15)
    status, said = calls(snap, "Coder", "run_command")[0]
    assert status == "succeeded" and "you work in a copy of the project of your own" in said
    assert "taken into the project when" not in said
    assert ("this turn may not change the project: what you or your commands change in the "
            "copy is not taken into it. git does not work in the copy.") in said
    assert not (project_dir / "made.txt").exists()


# --- what a kept copy's folder is trusted with -----------------------------------------------


def forge(folder, more):
    """Rewrite what a copy says it was made from, as a command of its agent's could."""
    held = json.loads((folder / copies.BASE_FILE).read_text(encoding="utf-8"))
    held["files"].update(more)
    (folder / copies.BASE_FILE).write_text(json.dumps(held), encoding="utf-8")


def test_a_kept_copy_reaches_nothing_a_copy_at_work_could_not_whatever_its_base_says(
    tmp_path, project_dir
):
    (project_dir / ".git" / "hooks").mkdir(parents=True)
    (project_dir / ".git" / "config").write_text("[core]", encoding="utf-8")
    (project_dir / "node_modules" / "pkg").mkdir(parents=True)
    (project_dir / "node_modules" / "pkg" / "index.js").write_text("dep", encoding="utf-8")
    (project_dir / "build").mkdir()
    (project_dir / "build" / "out.js").write_text("built", encoding="utf-8")
    made = copies.make(project_dir, tmp_path / "runtime", "a1")
    (made.root / ".git" / "hooks").mkdir(parents=True)
    (made.root / ".git" / "hooks" / "pre-commit").write_text("#!/bin/sh", encoding="utf-8")
    copies.unlink(tmp_path / "runtime", "a1")           # kept: it has lost its links
    short = short_name(project_dir / "node_modules") if os.name == "nt" else None
    forge(made.root.parent, {
        ".git/config": "x", ".GIT/config": "x", ".git/hooks/pre-commit": "x",
        "node_modules/pkg/index.js": "x", "Node_Modules/pkg/index.js": "x",
        "sub/.venv/x.py": "x", "build/out.js": "x", "node_modules": "x",
        "../outside.txt": "x", "sub/../hello.py": "x", "./hello.py": "x", "/hello.py": "x",
        "sub\\x.py": "x", "C:/x.py": "x", "": "x", "sub//x.py": "x",
        **({f"{short}/pkg/index.js": "x"} if short else {}),
    })
    kept = copies.load(project_dir, tmp_path / "runtime", "a1")
    # (another name for a folder is known only by where it leads: `changes` looks there)
    assert set(kept.names.values()) == {"hello.py", *([f"{short}/pkg/index.js"] if short else [])}
    assert kept.changes() == []


def test_a_copy_does_not_take_a_file_into_a_shared_folder_by_its_short_name(tmp_path, project_dir):
    """A command put a folder of its own where the copy's link was, under another name for
    it: what is in it is not the project's to get."""
    (project_dir / "node_modules" / "pkg").mkdir(parents=True)
    short = short_name(project_dir / "node_modules") if os.name == "nt" else None
    if short is None:
        pytest.skip("the disk keeps no 8.3 names")
    made = copies.make(project_dir, tmp_path / "runtime", "a1")
    copies.unlink(tmp_path / "runtime", "a1")
    (made.root / short / "pkg").mkdir(parents=True)
    (made.root / short / "pkg" / "evil.js").write_text("x", encoding="utf-8")
    (made.root / "a.txt").write_text("A", encoding="utf-8")
    assert made.changes() == [("a.txt", "new", "ready")]


def test_a_copy_whose_tree_is_a_link_is_not_read(tmp_path, project_dir):
    made = copies.make(project_dir, tmp_path / "runtime", "a1")
    victim = tmp_path / "victim"
    victim.mkdir()
    shutil.rmtree(made.root)
    copies._link(made.root, victim)
    with pytest.raises(ValueError):
        copies.load(project_dir, tmp_path / "runtime", "a1")


def test_what_a_copy_was_made_from_is_not_parsed_beyond_a_size(tmp_path, project_dir, monkeypatch):
    copies.make(project_dir, tmp_path / "runtime", "a1")
    assert copies.load(project_dir, tmp_path / "runtime", "a1").names == {
        copies._key("hello.py"): "hello.py"}
    monkeypatch.setattr(copies, "MAX_BASE_BYTES", 10)
    with pytest.raises(ValueError):
        copies.load(project_dir, tmp_path / "runtime", "a1")


def test_after_a_restart_a_kept_copy_whose_tree_became_a_link_is_only_to_discard(
    settings_env, project_dir, tmp_path
):
    cid = interrupted(settings_env, project_dir)
    (folder,) = kept_folders(settings_env)
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "a.txt").write_text("THE SECRET", encoding="utf-8")
    shutil.rmtree(folder / "tree")
    copies._link(folder / "tree", victim)
    with again(settings_env) as client:
        card = card_of(client, cid)
        assert card["status"] == "kept" and files(card) == {"a.txt": "refused"}
        assert "SECRET" not in json.dumps(client.get(f"/api/conversations/{cid}").json())
        assert client.post(f"/api/merges/{card['id']}/approve").status_code == 409
        assert client.post(f"/api/merges/{card['id']}/reject").status_code == 200
        assert kept_folders(settings_env) == []
    assert (victim / "a.txt").read_text(encoding="utf-8") == "THE SECRET"
    assert not (project_dir / "a.txt").exists()


@pytest.mark.parametrize(
    "hostile", ["[" * 200000, '{"files": {"a.txt": 1}}', "\ud800"],
    ids=["too deep", "not digests", "not text"],
)
def test_a_base_that_cannot_be_read_never_keeps_the_app_from_starting(
    settings_env, project_dir, hostile
):
    cid = at_work(settings_env, project_dir, [step(run(MAKES))])
    (folder,) = kept_folders(settings_env)
    (folder / copies.BASE_FILE).write_text(hostile, encoding="utf-8", errors="surrogatepass")
    with again(settings_env) as client:
        card = card_of(client, cid)
        # (slice 19c, completed: such a copy is shown against the project alone)
        assert card["status"] == "kept" and files(card) == {"made.txt": "conflict"}
        assert card["kept_in"] == str(folder / "tree")
        assert (folder / "tree" / "made.txt").read_text(encoding="utf-8") == "by a command"
        assert client.post(f"/api/merges/{card['id']}/reject").status_code == 200
        assert kept_folders(settings_env) == [] and not (project_dir / "made.txt").exists()


def test_a_copy_nothing_is_on_record_of_is_kept_though_its_base_cannot_be_read(tmp_path, settings):
    """The process was killed, and only a command had written in the copy: it says what
    it was made from, so it was not thrown away - and is the user's to discard."""
    upgrade_db(settings.db_path)
    factory = make_session_factory(make_engine(settings.db_path))
    project = tmp_path / "proj"
    project.mkdir()
    made = copies.make(project, settings.runtime_root, "x")
    (made.root / "made.txt").write_text("by a command", encoding="utf-8")
    (made.root.parent / copies.BASE_FILE).write_text("[" * 200000, encoding="utf-8")
    with factory() as s:
        on_record(s, project)
        an_agent(s, "x", status="running")
        s.get_one(Agent, "x").copy = {"state": "own", "tree": str(made.root)}  # as it is made
        s.commit()
    create_app(settings)
    assert (made.root / "made.txt").read_text(encoding="utf-8") == "by a command"
    with factory() as s:
        (merge,) = s.scalars(select(Merge)).all()
        assert merge.status == "interrupted" and merge.kept_in == str(made.root)
        assert [(one["path"], one["state"]) for one in merge.files] == [("made.txt", "conflict")]


def test_after_a_restart_a_card_that_was_ready_is_not_once_nothing_vouches_for_its_files(
    settings_env, project_dir
):
    cid = interrupted(settings_env, project_dir)
    with again(settings_env) as client:
        assert files(card_of(client, cid)) == {"a.txt": "ready"}
    (folder,) = kept_folders(settings_env)
    (folder / copies.BASE_FILE).write_text("[" * 200000, encoding="utf-8")
    with again(settings_env) as client:
        assert files(card_of(client, cid)) == {"a.txt": "conflict"}
        assert (folder / "tree" / "a.txt").is_file()


def test_a_kept_file_with_no_diff_to_show_is_a_conflict_wherever_the_project_has_another(
    settings_env, project_dir
):
    """Its label is all the card says of it: that is not left to what the copy's folder
    says the file was."""
    (project_dir / "data.bin").write_bytes(b"\xfe1")
    over = "python -c \"open('data.bin','wb').write(bytes([254, 50]))\""
    cid = at_work(settings_env, project_dir, [step(run(over)), step(run(MAKES, "c2"))])
    with again(settings_env) as client:
        card = card_of(client, cid)
        assert files(card) == {"data.bin": "conflict", "made.txt": "ready"}
        assert card["files"][0]["diff"] is None
        (project_dir / "made.txt").write_text("THE USER'S OWN", encoding="utf-8")    # since
        # (slice 30: whose file is taken of such a one is the user's to say)
        assert client.post(f"/api/merges/{card['id']}/approve").status_code == 409
        # made.txt moved since: nothing is taken, and it is asked about
        assert client.post(f"/api/merges/{card['id']}/approve", json={
            "choices": {"data.bin": "agent"}, "shown": seen(card)}).status_code == 409
        card = card_of(client, cid)
        assert files(card) == {"data.bin": "conflict", "made.txt": "conflict"}
        assert (project_dir / "data.bin").read_bytes() == b"\xfe1"
        said = client.post(f"/api/merges/{card['id']}/approve", json={
            "choices": {"data.bin": "agent", "made.txt": "project"},
            "shown": seen(card)}).json()
        assert files(said) == {"data.bin": "applied", "made.txt": "refused"}
        assert (project_dir / "data.bin").read_bytes() == b"\xfe2"


# --- a kept copy with nothing to say what it was made from (slice 19c, completed) --------------


def lose_the_base(folder, how):
    if how is None:
        (folder / copies.BASE_FILE).unlink()
    else:
        (folder / copies.BASE_FILE).write_text(how, encoding="utf-8")


@pytest.mark.parametrize("how", [None, '{"files": {'], ids=["deleted", "corrupt"])
def test_a_kept_copy_without_its_base_is_shown_against_the_project_and_apply_deletes_nothing(
    settings_env, project_dir, how
):
    (project_dir / "same.txt").write_text("same", encoding="utf-8")
    (project_dir / "gone.txt").write_text("the project's", encoding="utf-8")
    cid = interrupted(settings_env, project_dir)
    (folder,) = kept_folders(settings_env)
    lose_the_base(folder, how)
    (folder / "tree" / "gone.txt").unlink()     # deleted in the copy - or never copied
    (folder / "tree" / "dist").mkdir()          # what a copy leaves out is not its to give
    (folder / "tree" / "dist" / "out.js").write_text("built", encoding="utf-8")
    (folder / "tree" / "node_modules" / "pkg").mkdir(parents=True)
    (folder / "tree" / "node_modules" / "pkg" / "evil.js").write_text("x", encoding="utf-8")
    (project_dir / "hello.py").write_text("print('the user')\n", encoding="utf-8")
    with again(settings_env) as client:
        card = card_of(client, cid)
        assert card["status"] == "kept" and card["kept_in"] == str(folder / "tree")
        # what the agent is on record with is offered, never as ready; what else differs
        # may be the user's own work since, and is not (tests/test_copy_second_review.py)
        assert files(card) == {"a.txt": "conflict", "hello.py": "left_out"}
        assert all(one["two_way"] for one in card["files"])
        new, changed = card["files"]
        assert "+A" in new["diff"] and changed["diff"] is None
        said = client.post(f"/api/merges/{card['id']}/approve")
        assert said.status_code == 200
        assert files(said.json()) == {"a.txt": "applied", "hello.py": "left_out"}
        assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"
        assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('the user')\n"
        assert (project_dir / "gone.txt").read_text(encoding="utf-8") == "the project's"
        assert not (project_dir / "dist").exists()
        assert not (project_dir / "node_modules").exists()
        # it still holds a file that was not offered: it goes when the user discards it
        assert said.json()["status"] == "kept" and len(kept_folders(settings_env)) == 1
        assert client.post(f"/api/merges/{card['id']}/approve").status_code == 409
        assert client.post(f"/api/merges/{card['id']}/reject").status_code == 200
        assert kept_folders(settings_env) == []
        assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('the user')\n"


def test_a_copy_laid_out_as_before_there_were_trees_can_be_applied(settings_env, project_dir):
    """Slice 19b put a copy's files directly in its folder, and wrote no base down."""
    cid = interrupted(settings_env, project_dir)
    (folder,) = kept_folders(settings_env)
    for entry in list((folder / "tree").iterdir()):
        shutil.move(str(entry), str(folder / entry.name))
    (folder / "tree").rmdir()
    (folder / copies.BASE_FILE).unlink()
    shutil.rmtree(folder / copies.BASE)     # (nor did it keep what each file was copied from)
    with make_session_factory(make_engine(load_settings(settings_env).db_path))() as s:
        # As slice 19b's own records had it: kept in the folder itself, and no tree on the
        # agent's row. (How a kept copy is laid out is what the records say.)
        (merge,) = s.scalars(select(Merge)).all()
        merge.status, merge.kept_in = "interrupted", str(folder)
        for agent in s.scalars(select(Agent).where(Agent.copy.is_not(None))):
            agent.copy = {"state": agent.copy["state"]}
        s.commit()
    with again(settings_env) as client:
        card = card_of(client, cid)
        assert card["status"] == "kept" and card["kept_in"] == str(folder)
        assert files(card) == {"a.txt": "conflict"} and card["files"][0]["two_way"]
        assert client.post(f"/api/merges/{card['id']}/approve").json()["status"] == "applied"
        assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"
        assert kept_folders(settings_env) == []   # nor a base written beside the copy's folder


def test_apply_on_a_two_way_card_writes_what_it_showed_and_discard_touches_nothing(
    settings_env, project_dir
):
    cid = interrupted(settings_env, project_dir)
    (folder,) = kept_folders(settings_env)
    lose_the_base(folder, None)
    with again(settings_env) as client:
        card = card_of(client, cid)
        assert files(card) == {"a.txt": "conflict"}
        (folder / "tree" / "a.txt").write_text("NOT WHAT WAS SHOWN", encoding="utf-8")
        assert client.post(f"/api/merges/{card['id']}/approve").status_code == 409
        said = card_of(client, cid)
        assert said["status"] == "kept" and files(said) == {"a.txt": "conflict"}
        assert "+NOT WHAT WAS SHOWN" in said["files"][0]["diff"] and said["files"][0]["two_way"]
        assert not (project_dir / "a.txt").exists() and len(kept_folders(settings_env)) == 1
        assert client.post(f"/api/merges/{card['id']}/reject").json()["status"] == "rejected"
        assert not (project_dir / "a.txt").exists() and kept_folders(settings_env) == []
        assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('hi')\n"


def test_a_two_way_card_of_a_turn_nobody_watched_still_does_not_give_its_protected_paths(
    settings_env, project_dir
):
    cid = at_work(settings_env, project_dir, [step(write("notes.txt", "seen"))], unattended=True)
    (folder,) = kept_folders(settings_env)
    (folder / "tree" / ".claude").mkdir()
    (folder / "tree" / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    lose_the_base(folder, None)
    with again(settings_env) as client:
        card = card_of(client, cid)
        assert files(card) == {".claude/settings.json": "refused", "notes.txt": "conflict"}
        assert "no trigger allows" in card["files"][0]["note"]
        assert client.post(f"/api/merges/{card['id']}/approve").status_code == 200
        assert (project_dir / "notes.txt").read_text(encoding="utf-8") == "seen"
        assert not (project_dir / ".claude").exists()


def test_a_watched_turns_kept_card_says_why_its_protected_path_is_asked_about(
    settings_env, project_dir
):
    cid = at_work(settings_env, project_dir, [step(write("notes.txt", "seen"))])
    (folder,) = kept_folders(settings_env)
    (folder / "tree" / ".claude").mkdir()
    (folder / "tree" / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    with again(settings_env) as client:
        card = card_of(client, cid)
        (asked,) = [f for f in card["files"] if f["path"] == ".claude/settings.json"]
        assert asked["state"] == "ready" and "at every permission level" in asked["note"]
        assert client.post(f"/api/merges/{card['id']}/approve").status_code == 200
        assert (project_dir / ".claude" / "settings.json").read_text(encoding="utf-8") == "{}"


def test_the_list_of_conversations_says_which_has_changes_kept_until_they_are_decided(
    settings_env, project_dir
):
    cid = interrupted(settings_env, project_dir)
    with again(settings_env) as client:
        pid = client.get(f"/api/conversations/{cid}").json()["conversation"]["project_id"]
        other = client.post(f"/api/projects/{pid}/conversations").json()
        assert "kept" not in other  # said by the list, which looks; nowhere else

        def listed():
            found = client.get(f"/api/projects/{pid}/conversations").json()
            return {one["id"]: one["kept"] for one in found}

        assert listed() == {cid: True, other["id"]: False}
        assert client.post(f"/api/merges/{card_of(client, cid)['id']}/reject").status_code == 200
        assert listed() == {cid: False, other["id"]: False}
