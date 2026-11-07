"""K-r143: REA's R143 - an approved command in a continued turn, and the rest."""

import time
from dataclasses import replace

from app import model_native
from app.model_client import ModelUnavailable
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_commands import approve, cmd
from tests.test_agent_talk import message
from tests.test_agent_writes import wait_status
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import OWN, teams_of
from tests.test_claim_scenarios import write
from tests.test_native_agent import _roles_on, native_app, start  # noqa: F401  (a fixture)
from tests.test_parallel import until
from tests.test_recipe_ends_scenarios import SCRIPTS, build_then_test
from tests.test_recipe_run_scenarios import READY, answer, asked, manual, one_step, row
from tests.test_spawn import begin, call, spawn, step


def test_a_command_approved_in_a_continued_turn_runs(make_client, wait_run, project_dir):
    # B-357: the turn its Lead's message_agent gave it holds its turn's lock; the yes to its
    # command waited for that very lock - "approved", never run, the Lead waiting for good.
    executor = ScriptedExecutor([Script(["ok\n"], exit_code=0)])
    client, _model = make_client([
        spawn("Coder", "Add a notes file"),
        text("Nothing yet."),
        message("coder", "Now run the tests"),
        cmd("pytest -q"),
        text("They pass."),
        text("All done."),
    ], executor=executor)
    cid, run_id = begin(client, project_dir)
    snap = wait_status(client, cid, "waiting_approval")
    kid = snap["agents"][1]
    assert client.post(f"/api/agents/{kid['id']}/approve").status_code == 200
    for _ in range(250):  # (its first turn, then the Lead's message, then the card)
        snap = client.get(f"/api/conversations/{cid}").json()
        if snap["commands"]:
            break
        time.sleep(0.02)
    command = snap["commands"][0]
    assert approve(client, command["id"]).status_code == 200
    snap = wait_run(client, cid, run_id)
    assert snap["commands"][0]["status"] == "exited"
    assert snap["runs"][0]["status"] == "completed"


# --- B-357: a command of Codex's own is never at work for good -------------------------------


def test_a_command_codex_was_let_run_and_never_heard_of_again_ends_its_turn(
    native_app, wait_run, project_dir, monkeypatch  # noqa: F811
):
    monkeypatch.setattr(model_native, "NEVER_STARTED_SECONDS", 1.0)
    client, provider, _ = native_app([{"run": "pytest -q", "hold": 30}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert "never started" in snap["runs"][0]["error"]
    call = next(t for t in snap["tool_calls"] if t["name"] == "run_command")
    assert call["status"] == "failed" and "never started" in call["result"]
    assert snap["commands"][0]["status"] == "failed_to_start"


def test_a_command_of_codexs_at_work_past_the_bound_ends_its_turn(
    native_app, wait_run, project_dir, monkeypatch  # noqa: F811
):
    monkeypatch.setattr(model_native, "CALL_SECONDS", 1.5)
    client, provider, _ = native_app(
        [{"run": "pytest -q", "delta": "1 passed", "hold": 30}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert "still at work after 1.5 seconds" in snap["runs"][0]["error"]
    call = next(t for t in snap["tool_calls"] if t["name"] == "run_command")
    assert call["status"] == "failed"


def test_a_card_left_open_past_the_bound_does_not_end_codexs_turn(
    native_app, wait_run, project_dir, monkeypatch  # noqa: F811
):
    monkeypatch.setattr(model_native, "CALL_SECONDS", 1.0)
    client, provider, _ = native_app([{"run": "pytest -q", "output": "ok\n"}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider, mode="ask")
    asked_now = wait_status(client, cid, "waiting_approval")["commands"][0]
    time.sleep(3)  # (the user is thinking)
    client.post(f"/api/commands/{asked_now['id']}/approve", json={})
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]


def test_stop_on_a_command_of_codexs_own_ends_its_turn(
    native_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = native_app(
        [{"run": "pytest -q", "delta": "1 passed", "hold": 30}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    for _ in range(250):
        commands = client.get(f"/api/conversations/{cid}").json()["commands"]
        if commands and commands[0]["status"] == "running":
            break
        time.sleep(0.02)
    stop = client.post(f"/api/commands/{commands[0]['id']}/stop",
                       headers={"Origin": "http://127.0.0.1:8790"})
    assert stop.status_code == 200, stop.text
    snap = wait_run(client, cid, run_id, timeout=10)
    assert "you stopped its command" in str(snap["agents"][0]["error"]) + str(
        snap["runs"][0]["error"])
    assert snap["commands"][0]["status"] == "killed"


def test_codexs_commands_keep_their_temporary_files_in_the_scratch(
    native_app, wait_run, project_dir  # noqa: F811
):
    # B-358: its sandbox writes only in the folder it works in; tempfile went to %TEMP%.
    client, provider, _ = native_app([{"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    temp = project_dir / ".koloni" / "tmp"
    assert temp.is_dir()
    assert native_app.record()["temp"] == [str(temp)] * 3
    assert snap["tool_calls"] == []  # (KOLONİ's own making: nothing the CLI changed)


# --- B-356: a team that failed is not offered for Take in first ------------------------------


def test_ready_for_you_offers_ask_for_changes_first_where_a_team_failed(
    make_client, wait_run, project_dir
):
    client, _model = make_client({
        "Lead": [step(spawn("Web app lead", "the page", "l1").tool_calls[0],
                      spawn("Docs lead", "the words", "l2").tool_calls[0]), text("all done")],
        **SCRIPTS,
        "Web app lead": [spawn("Coder", "build a.py", "c"),
                         ModelUnavailable("model server returned 500: down")],
    })
    teams = teams_of(client)
    cid, run_id = manual(client, project_dir, (teams["Web app"], build_then_test(client)),
                         (teams["Docs"], one_step(client, "Just write", "Docs writer")))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    assert row(snap, 0)["status"] == "failed" and row(snap, 1)["status"] == "ready"
    card = asked(snap)
    assert card["options"] == ["Ask for changes", "Take in"]
    assert "Web app failed: its work is not finished." in card["question"]
    answer(client, card, "Ask for changes")
    snap = wait_run(client, cid, run_id)
    # (Ask for changes sends the ready teams back; the failed one stays failed.)
    assert row(snap, 0)["status"] == "failed"


# --- a team's lead has steps for each step of its recipe --------------------------------------


def test_a_team_lead_has_more_steps_for_each_step_of_its_recipe(make_client, wait_run, project_dir):
    looks = [step(call("list_dir", {"path": "."}, f"r{n}")) for n in range(4)]
    client, _model = make_client({
        "Lead": [step(spawn("Web app lead", "the page", "l1").tool_calls[0],
                      spawn("Docs lead", "the words", "l2").tool_calls[0]), text("all done")],
        **SCRIPTS,
        "Web app lead": [*looks, spawn("Coder", "build a.py", "c"), text("web done")],
    })
    runner = client.app.state.runner
    runner.settings = replace(runner.settings, max_steps=3)  # (six steps: past it, not past 3 + 4)
    teams = teams_of(client)
    cid, run_id = manual(client, project_dir, (teams["Web app"], one_step(client, "Just build", "Coder")),
                         (teams["Docs"], one_step(client, "Just write", "Docs writer")))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    lead = next(a for a in snap["agents"] if a["name"] == "Web app lead")
    assert lead["status"] == "completed", lead["error"]
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)


def test_an_agent_of_a_stopped_team_is_not_reachable_by_a_note(make_client, wait_run, project_dir, gate):
    # R143: "handed at its next step" to an agent that takes none.
    client, _model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Web app lead", "task": "the page"}, "l1"),
                      call("spawn_agent", {"role": "Docs lead", "task": "the words"}, "l2")),
                 text("one stopped")],
        "Web app lead": [spawn("Coder", "build a.py", "c"), text("never said")],
        "Docs lead": [spawn("Docs writer", "write b.md", "d"), text("docs done")],
        "Coder": [gate.step(step(write("a.py", "a\n"))), text("never said")],
        "Docs writer": [step(write("b.md", "b\n", id="w2")), text("written")],
    })
    teams = teams_of(client)
    cid, run_id = manual(client, project_dir,
                         (teams["Web app"], one_step(client, "Just build", "Coder")),
                         (teams["Docs"], one_step(client, "Just write", "Docs writer")))
    gate.wait_partial()
    runner = client.app.state.runner
    web_lead = next(c for c in runner._ctxs.values() if c.name == "Web app lead")

    def reached() -> list[tuple[str, str]]:
        return [(other.name, kind) for other, kind in runner._reachable(web_lead)]

    assert ("Coder", "note") in reached()
    stop = f"/api/conversations/{cid}/teams/{teams['Web app']['id']}/stop"
    assert client.post(stop, headers=OWN).status_code == 200
    assert "Coder" not in [name for name, _kind in reached()]
    gate.release()
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)


def test_codex_in_a_copy_gets_the_scratch_and_nothing_more_to_take_in(
    native_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _default = native_app(
        [{"write": "made.txt", "content": "new\n"}, {"say": "Made it."}],
        default_steps={"Lead": [step(call("spawn_agent", {"role": "Coder", "task": "make"}, "s")),
                                text("done")]})
    _roles_on(client, provider, "Coder")
    cid, run_id = start(client, project_dir, None)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert (project_dir / "made.txt").exists() and not (project_dir / ".koloni").exists()
    assert [c["path"] for c in snap["file_changes"]] == ["made.txt"]
    assert [m["status"] for m in snap["merges"]] in ([], ["applied"])


# --- B-355: the project's check runs before Take in at every level -------------------------


def test_a_recipes_take_in_at_auto_edit_runs_the_check_first_and_a_failing_one_is_a_card(
    make_client, wait_run, project_dir
):
    # PLAN-E2E-07: "Take in" on Ready for you at Auto-edit took a red suite in, check "not_run".
    client, _model = make_client({
        "Lead": [spawn("Coder", "build a.py", "c"), text("all done")],
        "Coder": [step(write("a.py", "a\n")), text("built")],
    })
    teams = teams_of(client)
    cid, run_id = manual(client, project_dir, (teams["Web app"], one_step(client, "Just build", "Coder")))
    pid = client.get("/api/projects").json()[0]["id"]
    assert client.patch(f"/api/projects/{pid}", json={
        "check_command": "python -c \"raise SystemExit(1)\""}, headers=OWN).status_code == 200
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    answer(client, asked(snap), "Take in")
    snap = until(client, cid, lambda s: [m["status"] for m in s["merges"]] == ["pending"]
                 and s["merges"][0]["check"]["state"] == "failed", timeout=20)
    assert not (project_dir / "a.py").exists()
    merge = snap["merges"][0]
    assert client.post(f"/api/merges/{merge['id']}/reject", headers=OWN).status_code == 200
    wait_run(client, cid, run_id)
    assert not (project_dir / "a.py").exists()
