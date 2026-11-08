"""B-413 (REA's R219-R220, PLAN-T112-05: three teams, a room, messages between leads; the
Orchestrator ended on `step_limit` after the work was in the project): it had the app's 25 and
B-398's 8 for each led team - 49 - and spent them on its own work no count per team covers, with
no Continue card at depth 0. The Orchestrator now counts no steps of its own, anywhere: its loop
guard stops it (the same failure `signs.STOP_AT` times, `signs.IDLE_STOP` calls in a row that
bring nothing new), and a limit the user set - its role's, a trigger's - still holds. In a turn
the user started the guard asks on a card; elsewhere it ends with why, and a To-do run goes on."""

import json
from types import SimpleNamespace

from app import backlog, signs
from app.config import load_settings
from app.main import create_app
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_backlog import setup as backlog_setup
from tests.test_backlog_auto import auto, tasks, worked
from tests.test_backlog_auto import until as task_until
from tests.test_chat_flow import start_in_mode, text
from tests.test_chat_teams_scenarios import teams_of
from tests.test_parallel import until
from tests.test_recipe_run_scenarios import answer, asked
from tests.test_spawn import begin, call, role_id, step
from tests.test_team_requests_scenarios import agent
from tests.test_triggers import leave, run_now, run_of, trigger
from tests.test_triggers import setup as trigger_setup

OWN = {"Origin": "http://127.0.0.1:8790"}
THREE = ("Backend / API", "Web app", "Docs")
CIRCLES = f"{signs.CIRCLING}{signs.IDLE.format(count=signs.IDLE_STOP)}"


def three_teams(client, project_dir, mode="ask"):
    teams = teams_of(client)
    return begin(client, project_dir, mode=mode, teams_mode="manual",
                 teams=[{"team_id": teams[name]["id"]} for name in THREE])


def looks(n, start=0):  # (each another call: none is the same as one before it)
    return [step(call("list_dir", {"path": f"nowhere{i}"}, f"k{i}"))
            for i in range(start, start + n)]


def circles(n, start=0):  # (the same call, with the same result, again and again)
    return [step(call("list_dir", {}, f"c{i}")) for i in range(start, start + n)]


# --- a long, honest turn: no count of steps ------------------------------------------------------


def test_the_orchestrator_of_three_led_teams_takes_60_steps_and_ends(
        make_client, wait_run, project_dir):
    client, model = make_client([*looks(60), text("looked everywhere")])
    cid, run_id = three_teams(client, project_dir)
    snap = wait_run(client, cid, run_id, timeout=30)
    assert agent(snap, "Lead")["status"] == "completed", agent(snap, "Lead")["error"]
    assert len(model.calls) == 61


class Looking(ScriptedModel):
    """A CLI session for the Lead: a message and a call of another path, 60 times."""

    session = True

    def __init__(self):
        super().__init__([])
        self.looked = 0

    async def run_session(self, model_id, messages, tools, call_tool, on_text, on_message=None,
                          effort=None, on_live=None):
        for i in range(60):
            await on_text(f"Looking at nowhere{i}.")
            await call_tool("list_dir", json.dumps({"path": f"nowhere{i}"}))
            self.looked += 1
        await on_text("looked everywhere")
        return SimpleNamespace(input_tokens=5, output_tokens=1, model=None)


def test_a_session_orchestrator_of_three_led_teams_takes_60_steps_and_ends(
        settings_env, wait_run, project_dir):
    cli = Looking()
    with TestClient(create_app(load_settings(settings_env), model=cli),
                    base_url="http://127.0.0.1:8790") as client:
        client.headers["Origin"] = OWN["Origin"]
        cid, run_id = three_teams(client, project_dir)
        snap = wait_run(client, cid, run_id, timeout=30)
    assert (snap["runs"][0]["status"], cli.looked) == ("completed", 60), snap["runs"][0]["error"]


def test_a_limit_the_user_set_on_the_lead_role_still_holds(make_client, wait_run, project_dir):
    client, model = make_client([*looks(10), text("never said")])
    client.headers["Origin"] = OWN["Origin"]
    assert client.patch(f"/api/roles/{role_id(client, 'Lead')}",
                        json={"max_steps": 6}).status_code == 200
    cid, run_id = begin(client, project_dir)
    snap = wait_run(client, cid, run_id, timeout=20)
    assert (snap["runs"][0]["error"], len(model.calls)) == (
        "stopped at its role's limit of 6 steps", 6)


# --- going round in circles ----------------------------------------------------------------------


def test_a_looping_orchestrator_is_asked_about_on_a_card_go_on_then_stop_here(
        make_client, wait_run, project_dir):
    first = signs.IDLE_STOP + 1  # (the first call is new; the next IDLE_STOP repeat it)
    client, model = make_client([*circles(first), *circles(first, first), text("never said")])
    cid, run_id = begin(client, project_dir, mode="full_auto")  # (the user's, at Full auto too)
    card = asked(until(client, cid, asked, timeout=20))
    assert card["question"].startswith(
        "The Orchestrator has no step limit, and it seems to go round in circles: its last 10 "
        "calls each repeated one it had made, with the same result")
    assert card["options"] == ["Go on", "Stop here"] and len(model.calls) == first
    answer(client, card, "Go on")  # (its counts start again: as many more before the next)
    card = asked(until(client, cid, lambda s: (q := asked(s)) and q["id"] != card["id"],
                       timeout=20))
    assert len(model.calls) == 2 * first
    answer(client, card, "Stop here")
    snap = wait_run(client, cid, run_id, timeout=20)
    assert (snap["runs"][0]["status"], snap["runs"][0]["error"]) == ("failed", CIRCLES)


def test_stopped_after_the_turns_work_is_in_the_project_the_turn_is_completed(
        make_client, wait_run, project_dir):
    # (the live B-413: the work was in the project, and the turn ended red)
    wrote = step(call("write_file", {"path": "notes.txt", "content": "done"}, "w1"))
    client, _model = make_client([wrote, *circles(signs.IDLE_STOP + 1), text("never said")])
    cid, run_id = start_in_mode(client, project_dir, "full_auto")  # (the Lead writes itself)
    answer(client, asked(until(client, cid, asked, timeout=20)), "Stop here")
    snap = wait_run(client, cid, run_id, timeout=20)
    assert (project_dir / "notes.txt").read_text() == "done"
    assert (snap["runs"][0]["status"], snap["runs"][0]["error"]) == ("completed", None)
    assert [m["content"] for m in snap["messages"] if m["role"] == "koloni"] == [
        f"The Orchestrator ended after this turn's work was in the project: {CIRCLES}"]


def test_the_same_failure_five_times_stops_it_too(make_client, wait_run, project_dir):
    gone = [step(call("read_file", {"path": "gone.py"}, f"g{i}")) for i in range(signs.STOP_AT)]
    client, _model = make_client([*gone, text("never said")])
    cid, run_id = begin(client, project_dir)
    card = asked(until(client, cid, asked, timeout=20))
    assert "read_file failed 5 times with the same arguments and the same error" in card["question"]
    answer(client, card, "Stop here")
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["error"].startswith(f"{signs.CIRCLING}read_file failed 5 times")


def test_a_looping_triggers_turn_ends_with_why_and_asks_nothing(
        make_client, wait_run, project_dir):
    client, model, pid, cid = trigger_setup(
        make_client, project_dir, [*circles(30), text("never said")],
        permission_mode="full_auto")
    made = trigger(client, pid, cid, permissions=leave(),
                   budget={"steps": 200, "minutes": 10, "per_day": 24})
    run_id = run_now(client, made["id"])
    snap = wait_run(client, cid, run_id, timeout=20)
    assert (run_of(snap, run_id)["status"], run_of(snap, run_id)["error"]) == ("failed", CIRCLES)
    assert snap["questions"] == [] and len(model.calls) == signs.IDLE_STOP + 1


# --- a To-do run: the task is blocked with why, and the next one runs -----------------------------


def test_a_looping_todo_task_is_blocked_with_why_and_the_next_task_runs(
        make_client, wait_run, project_dir, monkeypatch):
    monkeypatch.setattr(backlog, "MAX_PARALLEL", 1)
    loop = signs.IDLE_STOP + 1
    # (its turn, then its fix round, both going round; then the next task's long, honest turn)
    client, _model = make_client([*circles(loop), *circles(loop, loop), *looks(40),
                                  text("two done")])
    pid, _ = backlog_setup(client, project_dir, "one", "two")
    auto(client, pid, True)
    one = task_until(lambda: (t := tasks(client, pid)["one"])["status"] == "blocked" and t)
    assert one["stuck"] == CIRCLES
    task_until(lambda: tasks(client, pid)["two"]["conversation_id"])
    assert worked(client, wait_run, pid, "two")["status"] == "review"
    assert client.get(f"/api/projects/{pid}/backlog/auto").json()["on"] is True


def test_stopped_after_a_copy_was_taken_in_the_turn_is_completed(make_client, wait_run, project_dir):
    # (the live B-413's own path: a Coder's copy, its Take in, then the Orchestrator went round)
    from tests.test_claim_scenarios import write
    from tests.test_copy_scenarios import one

    opened = step(call("spawn_agent", {"role": "Coder", "task": "do it"}, "s"))
    client, _model, cid, run_id = one(
        make_client, project_dir, [step(write("a.txt", "A")), text("A done")],
        lead=[opened, *circles(signs.IDLE_STOP + 1), text("never said")], permission_mode="ask")
    card = until(client, cid, lambda s: [m for m in s["merges"] if m["status"] == "pending"],
                 timeout=20)["merges"][0]
    assert client.post(f"/api/merges/{card['id']}/approve").status_code == 200  # (Take in)
    answer(client, asked(until(client, cid, asked, timeout=20)), "Stop here")
    snap = wait_run(client, cid, run_id, timeout=20)
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"
    assert [m["status"] for m in snap["merges"]] == ["applied"]  # (by the copy's Take in)
    assert (snap["runs"][0]["status"], snap["runs"][0]["error"]) == ("completed", None)
    assert f"The Orchestrator ended after this turn's work was in the project: {CIRCLES}" in [
        m["content"] for m in snap["messages"] if m["role"] == "koloni"]


def test_a_wait_that_says_the_same_is_no_repeat():
    counts = signs.Counts()
    for _ in range(3 * signs.IDLE_STOP):  # (a team at work for hours: the same answer each time)
        counts.heard("wait_for_team", '{"team": "Backend / API"}', "still at work after 10 minutes")
    assert counts.idle == 0
    for _ in range(3):
        counts.heard("list_dir", "{}", "hello.py")
    assert counts.idle == 2
