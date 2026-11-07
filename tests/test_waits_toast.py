"""K-bekleyen: one desktop notice when something starts to wait for the user, where the project
has desktop notifications on - and none for what was answered meanwhile."""

import asyncio

import pytest

import app.web
from app.agent.ctx import Ctx
from app.agent.tiers_mixin import WAITS_SECONDS
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_commands import cmd
from tests.test_agent_writes import wait_status
from tests.test_backlog_auto import until
from tests.test_chat_flow import text
from tests.test_lead_decides import CODER, OWN, ask, fire, held, lead_timers, question_of, says
from tests.test_spawn import call, step


@pytest.fixture
def shown(monkeypatch):
    said: list = []
    monkeypatch.setattr(app.web, "has_desktop", lambda: True)
    monkeypatch.setattr(app.web, "desktop", lambda title, text: said.append((title, text)))
    return said


def chat(client, project_dir, desktop=True, mode="ask"):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={"notify_desktop": desktop},
                        headers=OWN).status_code == 200
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={"permission_mode": mode}, headers=OWN)
    return pid, cid


def say(client, cid):
    return client.post(f"/api/conversations/{cid}/messages", json={"content": "sort it"},
                       headers=OWN).json()["run"]["id"]


def tell(client, clock, shown):
    (timer,) = until(lambda: lead_timers(clock, WAITS_SECONDS))  # (set once the Lead let go)
    clock.set.remove(timer)
    fire(client, timer)
    for _ in range(200):  # (shown off the event loop)
        if shown:
            break
        client.portal.call(asyncio.sleep, 0.01)
    return shown


def test_a_question_that_waits_is_told_once_on_the_desktop(make_client, wait_run, project_dir,
                                                         shown):
    client, _model = make_client([ask(), text("ok")])
    clock = held(client)
    pid, cid = chat(client, project_dir)
    run_id = say(client, cid)
    wait_status(client, cid, "waiting_approval")
    name = client.get(f"/api/projects/{pid}").json()["name"]
    assert tell(client, clock, shown) == [(f"KOLONİ — {name}", "Orchestrator asks you a question")]
    client.post(f"/api/questions/{question_of(client, cid)['id']}/answer",
                json={"answer": "by name"}, headers=OWN)
    wait_run(client, cid, run_id)
    assert len(shown) == 1


def test_a_command_card_says_who_waits_and_never_the_command(make_client, wait_run, project_dir,
                                                             shown):
    client, _model = make_client([step(call("run_command", {"command": "echo TOKEN=s3cret"}, "c")),
                                  text("ok")])
    clock = held(client)
    _pid, cid = chat(client, project_dir)
    run_id = say(client, cid)
    snap = wait_status(client, cid, "waiting_approval")
    ((_title, said),) = tell(client, clock, shown)
    assert said == "Orchestrator waits for you"
    client.post(f"/api/commands/{snap['commands'][0]['id']}/reject")
    wait_run(client, cid, run_id)


def test_with_the_setting_off_nothing_is_shown(make_client, wait_run, project_dir, shown):
    client, _model = make_client([ask(), text("ok")])
    clock = held(client)
    _pid, cid = chat(client, project_dir, desktop=False)
    run_id = say(client, cid)
    wait_status(client, cid, "waiting_approval")
    assert lead_timers(clock, WAITS_SECONDS) == []
    client.post(f"/api/questions/{question_of(client, cid)['id']}/answer",
                json={"answer": "by name"}, headers=OWN)
    wait_run(client, cid, run_id)
    assert shown == []


def test_cards_that_open_together_are_one_notice_and_an_answered_one_is_not_told(
        client, project_dir, shown):
    clock = held(client)
    _pid, cid = chat(client, project_dir)
    runner = client.app.state.runner
    asked: list[asyncio.Future] = []

    def open_cards(names):
        for name in names:
            asked.append(future := asyncio.get_running_loop().create_future())
            runner._tell_waits(Ctx(run_id="r", cid=cid, root=None, agent_id=name, role="Coder",
                                   tools=(), depth=1, name=name), future)

    client.portal.call(open_cards, ["Coder", "Tester", "Reviewer"])
    client.portal.call(asked[2].set_result, "approve")  # answered before the notice
    assert tell(client, clock, shown)[0][1] == "2 cards wait for you"
    shown.clear()
    client.portal.call(open_cards, ["Coder 2"])
    client.portal.call(asked[3].set_result, "approve")
    (timer,) = lead_timers(clock, WAITS_SECONDS)
    fire(client, timer)
    client.portal.call(asyncio.sleep, 0.05)
    assert shown == []


@pytest.mark.parametrize("lead_says, told", [("By date", []), ("by size", ["Coder asks you a question"])])
def test_at_full_auto_a_question_the_lead_takes_is_told_only_once_it_did_not_answer(
        make_client, wait_run, project_dir, shown, lead_says, told):
    client, model = make_client([CODER, ask(), says(lead_says), text("ok"), text("done")])
    clock = held(client)
    _pid, cid = chat(client, project_dir, mode="full_auto")
    run_id = say(client, cid)
    wait_status(client, cid, "waiting_approval")
    (waits,) = lead_timers(clock, WAITS_SECONDS)
    clock.set.remove(waits)
    fire(client, waits)  # (before the Lead has answered: not told)
    fire(client, lead_timers(clock, 0.0)[0])
    until(lambda: len(model.calls) == 3)
    if told:
        assert [said for _title, said in tell(client, clock, shown)] == told
        client.post(f"/api/questions/{question_of(client, cid)['id']}/answer",
                    json={"answer": "by date"}, headers=OWN)
    wait_run(client, cid, run_id)
    assert [said for _title, said in shown] == told


def test_a_question_the_lead_gave_up_before_its_notice_is_told_once(
        make_client, wait_run, project_dir, shown):
    client, model = make_client([CODER, ask(), says("by size"), text("ok"), text("done")])
    clock = held(client)
    _pid, cid = chat(client, project_dir, mode="full_auto")
    run_id = say(client, cid)
    wait_status(client, cid, "waiting_approval")
    fire(client, lead_timers(clock, 0.0)[0])  # (the Lead gives it up within the 2 s)
    until(lambda: len(model.calls) == 3 and not client.app.state.runner._lead_taking)
    assert [said for _title, said in tell(client, clock, shown)] == ["Coder asks you a question"]
    client.post(f"/api/questions/{question_of(client, cid)['id']}/answer",
                json={"answer": "by date"}, headers=OWN)
    wait_run(client, cid, run_id)


def test_a_keep_card_a_turn_waits_on_is_one_notice(make_client, wait_run, project_dir, shown):
    executor = ScriptedExecutor([Script(["ok\n"], writes={".claude/agents/a.md": "x"}),
                                 Script(["ok\n"])])
    client, _model = make_client([cmd("python make.py"), cmd("python next.py"), text("done")],
                                 executor=executor)
    clock = held(client)
    _pid, cid = chat(client, project_dir, mode="full_auto")
    run_id = say(client, cid)
    runner = client.app.state.runner
    until(lambda: sum(runner._asks.values()) == 2)  # its card, and the next command waiting on it
    assert [said for _title, said in tell(client, clock, shown)] == [
        "Orchestrator asks you a question"]
    client.post(f"/api/questions/{question_of(client, cid)['id']}/answer",
                json={"answer": "Take back"}, headers=OWN)
    wait_run(client, cid, run_id)
    assert len(shown) == 1
