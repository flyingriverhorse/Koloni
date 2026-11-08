"""B-413 (REA's R219-R220, PLAN-T112-05: three teams, a room, messages between leads; the
Orchestrator ended on `step_limit` after the work was in the project): it had the app's 25 and
B-398's 8 for each led team - 49 - and spent them on its own work no count per team covers, with
no Continue card at depth 0. The Orchestrator now counts no steps of its own, anywhere: its loop
guard stops it (the same failure `signs.STOP_AT` times, `signs.IDLE_STOP` calls in a row that
bring nothing new), and a limit the user set - its role's, a trigger's - still holds. In a turn
the user started the guard asks on a card; elsewhere it ends with why, and a To-do run goes on."""

import json
import sys
from types import SimpleNamespace

import pytest

import app.web
from app import backlog, signs
from app.agent.limits_mixin import CIRCLING_WAIT
from app.config import load_settings
from app.main import create_app
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_backlog import setup as backlog_setup
from tests.test_backlog_auto import auto, tasks, worked
from tests.test_backlog_auto import until as task_until
from tests.test_chat_flow import start_in_mode, text
from tests.test_chat_teams_scenarios import teams_of
from tests.test_lead_decides import fire, lead_timers
from tests.test_parallel import until
from tests.test_recipe_run_scenarios import answer, asked
from tests.test_spawn import begin, call, role_id, step
from tests.test_team_requests_scenarios import agent
from tests.test_triggers import HeldClock, leave, run_now, run_of, trigger
from tests.test_triggers import setup as trigger_setup

OWN = {"Origin": "http://127.0.0.1:8790"}
THREE = ("Backend / API", "Web app", "Docs")
CIRCLES = f"{signs.CIRCLING}{signs.IDLE.format(count=signs.IDLE_STOP)}"
LOOP = signs.IDLE_STOP + 1  # (the first call is new; the next IDLE_STOP repeat it)
NUDGE = ("KOLONİ: you seem to go round in circles: list_dir again and again, with the same "
         "result, and nothing moved in between. Try a different approach, or report what you "
         "did and end.")


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


def test_a_looping_orchestrator_is_told_once_then_asked_on_a_card_go_on_then_stop_here(
        make_client, wait_run, project_dir):
    client, model = make_client([*circles(LOOP), *circles(LOOP, LOOP), *circles(LOOP, 2 * LOOP),
                                 text("never said")])
    clock = client.app.state.runner.call_later = HeldClock()
    cid, run_id = begin(client, project_dir, mode="full_auto")  # (the user's, at Full auto too)
    card = asked(until(client, cid, asked, timeout=20))
    # the first time it was told, and went on; the card is the second time
    assert len(model.calls) == 2 * LOOP and NUDGE in str(model.calls[LOOP])
    assert card["question"].startswith(
        "The Orchestrator has no step limit, and it seems to go round in circles: its last 10 "
        "calls each repeated one it had made, with the same result")
    assert card["options"] == ["Go on", "Stop here"]
    (timer,) = lead_timers(clock, CIRCLING_WAIT)
    answer(client, card, "Go on")  # (in time: its counts start again, and no second nudge)
    card = asked(until(client, cid, lambda s: (q := asked(s)) and q["id"] != card["id"],
                       timeout=20))
    assert timer.cancelled and len(model.calls) == 3 * LOOP
    answer(client, card, "Stop here")
    snap = wait_run(client, cid, run_id, timeout=20)
    assert (snap["runs"][0]["status"], snap["runs"][0]["error"]) == ("failed", CIRCLES)


def test_told_once_it_finds_another_way_and_ends_with_no_card(make_client, wait_run, project_dir):
    client, model = make_client([*circles(LOOP), *looks(3), text("found it another way")])
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id, timeout=20)
    assert (snap["runs"][0]["status"], snap["questions"]) == ("completed", [])
    assert NUDGE in str(model.calls[LOOP])


def test_nobody_answering_ends_the_turn_with_its_work_and_a_report_and_the_next_message_runs(
        make_client, wait_run, project_dir):
    wrote = step(call("write_file", {"path": "notes.txt", "content": "done"}, "w1"))
    client, _model = make_client([wrote, *circles(LOOP), *circles(LOOP, LOOP),
                                  text("never said"), text("the next one, done")])
    clock = client.app.state.runner.call_later = HeldClock()
    cid, run_id = start_in_mode(client, project_dir, "full_auto")  # (the Lead writes itself)
    card = asked(until(client, cid, asked, timeout=20))
    queued = client.post(f"/api/conversations/{cid}/messages", json={"content": "and then?"},
                         headers=OWN)
    assert queued.status_code in (200, 201, 202), queued.text
    (timer,) = lead_timers(clock, CIRCLING_WAIT)
    fire(client, timer)  # (ten minutes, and nobody answered)
    snap = wait_run(client, cid, run_id, timeout=20)
    first = next(r for r in snap["runs"] if r["id"] == run_id)
    # its work landed, so it is completed - not cancelled: what waits behind it goes on
    assert (first["status"], first["error"]) == ("completed", None)
    assert (project_dir / "notes.txt").read_text() == "done"
    assert next(q for q in snap["questions"] if q["id"] == card["id"])["answer"] == (
        "No answer in 10 minutes")
    said = [m["content"] for m in snap["messages"] if m["role"] == "koloni"]
    assert ("No answer in 10 minutes: the Orchestrator's turn ended here, its work kept. It had "
            "opened 0 agents and changed 1 file in the project; it got stuck repeating "
            "list_dir.") in said
    later = until(client, cid, lambda s: len(s["runs"]) == 2 and s, timeout=20)
    assert wait_run(client, cid, later["runs"][-1]["id"], timeout=20)["runs"][-1]["status"] == (
        "completed")


def test_the_card_that_it_seems_stuck_is_told_on_the_desktop(
        make_client, wait_run, project_dir, monkeypatch):
    shown = []
    monkeypatch.setattr(app.web, "has_desktop", lambda: True)
    monkeypatch.setattr(app.web, "desktop", lambda title, said: shown.append(said))
    client, _model = make_client([*circles(LOOP), *circles(LOOP, LOOP), text("never said")])
    client.headers.update(OWN)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={"notify_desktop": True}).status_code == 200
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    run_id = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "go"}).json()["run"]["id"]
    card = asked(until(client, cid, asked, timeout=20))
    until(client, cid, lambda _s: shown, timeout=20)
    assert shown == ["The Orchestrator seems stuck: it repeated list_dir with the same result. "
                     "Go on or Stop here in the chat; with no answer in 10 minutes its turn "
                     "ends, its work kept."]
    answer(client, card, "Stop here")
    wait_run(client, cid, run_id, timeout=20)


def test_stopped_after_the_turns_work_is_in_the_project_the_turn_is_completed(
        make_client, wait_run, project_dir):
    # (the live B-413: the work was in the project, and the turn ended red)
    wrote = step(call("write_file", {"path": "notes.txt", "content": "done"}, "w1"))
    client, _model = make_client([wrote, *circles(LOOP), *circles(LOOP, LOOP), text("never said")])
    cid, run_id = start_in_mode(client, project_dir, "full_auto")  # (the Lead writes itself)
    answer(client, asked(until(client, cid, asked, timeout=20)), "Stop here")
    snap = wait_run(client, cid, run_id, timeout=20)
    assert (project_dir / "notes.txt").read_text() == "done"
    assert (snap["runs"][0]["status"], snap["runs"][0]["error"]) == ("completed", None)
    assert [m["content"] for m in snap["messages"] if m["role"] == "koloni"] == [
        f"The Orchestrator ended after this turn's work was in the project: {CIRCLES}"]


def test_the_same_failure_five_times_stops_it_too(make_client, wait_run, project_dir):
    gone = [step(call("read_file", {"path": "gone.py"}, f"g{i}"))
            for i in range(2 * signs.STOP_AT)]  # (told once, then the card)
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
        lead=[opened, *circles(LOOP), *circles(LOOP, LOOP), text("never said")],
        permission_mode="ask")
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


def test_what_counts_as_a_repeat():
    counts = signs.Counts()
    room = ("wait_for_room", "{}", "nobody said anything new")
    for _ in range(3 * signs.IDLE_STOP):  # (a room at work for long: the same answer each time)
        counts.heard(*room, waited=True)
    assert counts.idle == 0
    for _ in range(3):  # (one back at once with the same words is a repeat)
        counts.heard(*room)
    assert counts.idle == 2
    counts.moved()
    for _ in range(11):  # (a fan-out of one call in one step is one)
        counts.heard("list_dir", "{}", "hello.py", step="m1")
    assert counts.idle == 0
    counts.heard("list_dir", "{}", "hello.py", step="m2")
    assert counts.idle == 1
    to_lead = json.dumps({"to": "Web app lead", "message": "how far?"})
    counts.wrote_to(to_lead)  # (to one it had not written to: a move)
    assert counts.idle == 0
    counts.heard("list_dir", "{}", "hello.py")
    counts.wrote_to(to_lead)  # (to the same one again: none)
    counts.heard("list_dir", "{}", "hello.py")
    assert counts.idle == 1


# --- the review's findings ------------------------------------------------------------------------


@pytest.mark.parametrize("how", ["stop_here", "nobody_answers"])
def test_its_end_after_work_landed_waits_for_nothing_and_asks_nothing_more(
        make_client, wait_run, project_dir, how):
    # (teams_mode "lead": "no team picked" would send it back for a step more; and nothing
    # resets its counts, so a second card would come)
    wrote = step(call("write_file", {"path": "notes.txt", "content": "done"}, "w1"))
    client, model = make_client([wrote, *circles(LOOP), *circles(LOOP, LOOP), *circles(5, 50),
                                 text("never said")])
    clock = client.app.state.runner.call_later = HeldClock()
    cid, run_id = begin(client, project_dir, mode="full_auto", lead_hands_code=False,
                        teams_mode="lead")
    card = asked(until(client, cid, asked, timeout=20))
    calls = len(model.calls)
    if how == "stop_here":
        answer(client, card, "Stop here")
    else:
        fire(client, lead_timers(clock, CIRCLING_WAIT)[0])
    snap = wait_run(client, cid, run_id, timeout=20)
    assert len(model.calls) == calls and len(snap["questions"]) == 1
    assert snap["runs"][0]["status"] == "completed"
    assert len([m for m in snap["messages"] if m["role"] == "koloni"]) == 1  # (one line of it)


def test_the_same_command_again_and_again_is_going_round(make_client, wait_run, project_dir):
    # (a command that succeeded is no move: it is judged by what it said)
    command = "cd" if sys.platform == "win32" else "pwd"
    runs = [step(call("run_command", {"command": command}, f"r{i}")) for i in range(3 * LOOP)]
    client, _model = make_client([*runs, text("never said")])
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    card = asked(until(client, cid, asked, timeout=60))
    assert "run_command" in card["question"] or "repeated" in card["question"]
    answer(client, card, "Stop here")
    assert wait_run(client, cid, run_id, timeout=20)["runs"][0]["status"] == "failed"


def test_a_todo_task_that_wrote_a_file_and_went_round_is_blocked_with_why(
        make_client, wait_run, project_dir, monkeypatch):
    from tests.test_backlog_symphony import full_auto

    monkeypatch.setattr(backlog, "MAX_PARALLEL", 1)
    wrote = step(call("write_file", {"path": "notes.txt", "content": "done"}, "w1"))
    # (its turn and its fix round each write and go round; nobody watches: no landed "completed")
    client, _model = make_client([wrote, *circles(LOOP), wrote, *circles(LOOP, LOOP),
                                  text("two done")])
    pid, _ = backlog_setup(client, project_dir, "one", "two")
    full_auto(client, pid)
    assert client.patch(f"/api/projects/{pid}", json={"lead_work": "itself"}).status_code == 200
    auto(client, pid, True)
    one = task_until(lambda: (t := tasks(client, pid)["one"])["status"] == "blocked" and t)
    assert one["stuck"] == CIRCLES
    task_until(lambda: tasks(client, pid)["two"]["conversation_id"])
    assert worked(client, wait_run, pid, "two")["status"] == "review"


def test_the_unattended_limits_are_settings_of_the_app(client):
    client.headers.update(OWN)
    assert client.get("/api/unattended").json() == {"stuck_minutes": 30, "turn_hours": 8}
    for wrong in ({"stuck_minutes": 4}, {"stuck_minutes": 1441}, {"turn_hours": 0},
                  {"turn_hours": 73}, {"turn_hours": "8"}):
        assert client.put("/api/unattended", json=wrong).status_code == 422
    assert client.put("/api/unattended", json={"stuck_minutes": 45}).json() == {
        "stuck_minutes": 45, "turn_hours": 8}
    assert client.put("/api/unattended", json={"turn_hours": None}).json() == {
        "stuck_minutes": 45, "turn_hours": None}  # (no ceiling)
    assert client.put("/api/unattended", json={"turn_hours": 5},
                      headers={"Origin": "http://evil.example"}).status_code == 403


def todo_held(make_client, project_dir, monkeypatch, *script):
    """A To-do run of two tasks, its clock held: (client, clock, pid)."""
    monkeypatch.setattr(backlog, "MAX_PARALLEL", 1)
    client, _model = make_client(list(script))
    clock = client.app.state.runner.call_later = HeldClock()
    pid, _ = backlog_setup(client, project_dir, "one", "two")
    return client, clock, pid


def first_run(client, pid):
    cid = tasks(client, pid)["one"]["conversation_id"]
    return cid, client.get(f"/api/conversations/{cid}").json()["runs"][-1]["id"]


def test_a_todo_task_that_keeps_changing_files_has_no_hour_its_clock_starts_again(
        make_client, wait_run, project_dir, monkeypatch):
    from tests.test_backlog_symphony import full_auto

    writes = [step(call("write_file", {"path": f"part{i}.txt", "content": str(i)}, f"w{i}"))
              for i in range(4)]
    client, clock, pid = todo_held(make_client, project_dir, monkeypatch, *writes,
                                   text("all four parts"), text("two done"))
    full_auto(client, pid)
    assert client.patch(f"/api/projects/{pid}", json={"lead_work": "itself"}).status_code == 200
    auto(client, pid, True)
    assert worked(client, wait_run, pid, "one")["status"] == "review"
    stuck = [t for t in clock.set if t.delay == 30 * 60]
    # its 30 minutes start again at each file it changed; no hour holds it, only the ceiling
    assert len([t for t in stuck if t.cancelled]) >= 4
    assert not [t for t in clock.set if t.delay == 60 * 60]
    assert [t.delay for t in clock.set if t.delay > 30 * 60] == [8 * 3600] * 2  # (one a task)


def test_nothing_moving_for_its_minutes_blocks_the_task_and_the_next_one_runs(
        make_client, wait_run, project_dir, monkeypatch):
    from app.agent.limits_mixin import NO_PROGRESS
    from tests.conftest import Gate

    turn, fix = Gate(), Gate()
    client, clock, pid = todo_held(make_client, project_dir, monkeypatch,
                                   turn.step(text("never said")), fix.step(text("never said")),
                                   text("two done"))
    auto(client, pid, True)
    ended: list[str] = []
    for held in (turn, fix):  # (its turn, then its fix round: nothing moves in either)
        held.wait_partial()
        cid = tasks(client, pid)["one"]["conversation_id"]
        (run_id,) = [r["id"] for r in client.get(f"/api/conversations/{cid}").json()["runs"]
                     if r["id"] not in ended]
        fire(client, lead_timers(clock, 30 * 60.0)[-1])
        run = next(r for r in wait_run(client, cid, run_id, timeout=20)["runs"]
                   if r["id"] == run_id)
        held.release()
        ended.append(run_id)
        assert (run["status"], run["error"]) == (
            "failed", NO_PROGRESS.format(minutes=30))  # (never cancelled: the run goes on)
    one = task_until(lambda: (t := tasks(client, pid)["one"])["status"] == "blocked" and t)
    assert one["stuck"] == NO_PROGRESS.format(minutes=30)
    task_until(lambda: tasks(client, pid)["two"]["conversation_id"])
    assert worked(client, wait_run, pid, "two")["status"] == "review"
    assert client.get(f"/api/projects/{pid}/backlog/auto").json()["on"] is True


def test_the_ceiling_the_user_set_stops_a_turn_that_keeps_making_moves(
        make_client, wait_run, project_dir, monkeypatch):
    from tests.conftest import Gate

    turn = Gate()
    client, clock, pid = todo_held(make_client, project_dir, monkeypatch,
                                   turn.step(text("never said")), text("fixed it"),
                                   text("two done"))
    assert client.put("/api/unattended", json={"stuck_minutes": 45, "turn_hours": 2}).status_code         == 200
    auto(client, pid, True)
    turn.wait_partial()
    cid, run_id = first_run(client, pid)
    assert lead_timers(clock, 45 * 60.0)  # (the minutes the user set)
    fire(client, lead_timers(clock, 2 * 3600.0)[0])  # (its moves kept its clock going: its hours)
    snap = wait_run(client, cid, run_id, timeout=20)
    turn.release()
    assert (snap["runs"][0]["status"], snap["runs"][0]["error"]) == (
        "failed", "stopped after 2 hours, the longest a To-do task's turn works: what it did is "
        "kept")
    task_until(lambda: tasks(client, pid)["one"]["status"] == "review")  # (its fix round)
    assert worked(client, wait_run, pid, "two")["status"] == "review"


def test_with_no_ceiling_a_todo_tasks_turn_has_none(make_client, wait_run, project_dir,
                                                     monkeypatch):
    client, clock, pid = todo_held(make_client, project_dir, monkeypatch, text("one done"),
                                   text("two done"))
    assert client.put("/api/unattended", json={"turn_hours": None}).status_code == 200
    auto(client, pid, True)
    assert worked(client, wait_run, pid, "one")["status"] == "review"
    assert not [t for t in clock.set if t.delay > 30 * 60]


def test_a_triggers_turn_longer_than_the_stuck_minutes_has_their_clock_too(
        make_client, wait_run, project_dir):
    client, _model, pid, cid = trigger_setup(make_client, project_dir, [text("looked")],
                                             permission_mode="full_auto")
    clock = client.app.state.runner.call_later = HeldClock()
    made = trigger(client, pid, cid, permissions=leave(),
                   budget={"steps": 15, "minutes": 60, "per_day": 24})
    wait_run(client, cid, run_now(client, made["id"]))
    assert sorted(t.delay for t in clock.set if t.delay >= 60 * 10) == [30 * 60, 60 * 60]
