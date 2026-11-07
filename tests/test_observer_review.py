"""Slice 33a's review round: what differs every time - and only that - is left out of an
error; anything that moved in the turn starts a count again; only KOLONİ's own stops are
counted as such in the record; the record is made once a turn; a CLI that writes is not
quiet; a middle value stands only where every agent has it."""

from app import record as kept
from app import signs
from app.model_client import StepResult
from tests.test_chat_flow import text
from tests.test_observer_scenarios import SAME_FAILURE, agent, miss, record, spawn, told, watched
from tests.test_session_agent import session_app, start  # noqa: F401 - a fixture
from tests.test_spawn import begin
from tests.test_trigger_scenarios import finished, run_now, setup, trigger


def test_only_what_differs_every_time_is_left_out_of_an_error():
    alike = ["exit code 1 (0.3s)\n12:00:01 FAILED test_x in 0.31s (pid 4411)\n",
             "exit code 1 (1.2s)\n12:01:44.5 FAILED test_x in 30 ms (pid 4610)\n"]
    assert len({signs.same_error(error) for error in alike}) == 1
    for one, other in [
        ("test_case_1 assert 3 == 4", "test_case_2 assert 7 == 4"),
        ("3 failed, 2 passed", "1 failed, 4 passed"),
        ("exit code 1 (0.3s)\nboom", "exit code 2 (0.3s)\nboom"),
    ]:
        assert signs.same_error(one) != signs.same_error(other), (one, other)


def test_a_sub_agent_at_work_in_between_starts_the_count_again_and_the_sign_is_earlier(
    make_client, wait_run, project_dir
):
    model, snap = watched(make_client, wait_run, project_dir, {
        "Lead": [miss("a"), miss("b"), miss("c"), spawn("s"), miss("d"), miss("e"),
                 text("done")],
        "Coder": [text("I looked.")]})
    results = told(model)
    assert SAME_FAILURE.format(n=3) in results[2]
    # after the sub-agent: counted from one again, and nothing said at the second
    assert not any("times" in result for result in results[4:])
    sign = agent(snap)["sign"]
    assert sign["count"] == 3 and sign["text"].startswith(signs.EARLIER)


def test_a_sub_agent_stopped_at_five_unwatched_is_stopped_by_koloni_and_its_opener_hears_it_once(
    make_client, wait_run, project_dir
):
    client, model, pid, cid = setup(make_client, project_dir, {
        "Lead": [spawn("s"), text("It got stuck.")],
        "Coder": [*(miss(str(n)) for n in range(7)), text("never said")]})
    made = trigger(client, pid, cid, permissions={"write": False, "commands": [], "agents": 1})
    run_id = run_now(client, made["id"])
    snap = finished(client, wait_run, cid, run_id)
    coder = agent(snap, "Coder")
    assert coder["status"] == "failed" and SAME_FAILURE.format(n=5) in coder["error"]
    (result,) = told(model)
    assert result.count(SAME_FAILURE.format(n=5)) == 1
    ended = record(client)["Coder"]["ended"]
    assert (ended["stopped_by_koloni"], ended["failed"]) == (1, 0)


def test_the_record_is_made_once_a_turn(make_client, wait_run, project_dir, monkeypatch):
    made = []
    real = kept.as_it_began
    monkeypatch.setattr(kept, "as_it_began", lambda *given: made.append(1) or real(*given))
    _model, snap = watched(make_client, wait_run, project_dir, {
        "Lead": [miss("a"), miss("b"), text("done")]})
    assert snap["runs"][0]["status"] == "completed" and made == [1]


def test_a_middle_value_stands_only_where_every_agent_has_it(make_client, wait_run, project_dir):
    client, _model = make_client({"Lead": [StepResult("hello", [], None, None), text("again")]})
    cid, run_id = begin(client, project_dir, mode="full_auto")
    wait_run(client, cid, run_id)
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "and now?"})
    wait_run(client, cid, posted.json()["run"]["id"])
    lead = record(client)["Lead"]
    assert lead["agents"] == 2 and lead["input_tokens"] is None and lead["output_tokens"] is None


def test_a_session_that_only_writes_is_not_quiet_and_its_step_limit_is_koloni_s(
    session_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = session_app([{"say": "Let me think."}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["agents"][0]["last_event_at"] is not None

    session_app.rescript([{"call": "list_dir"} for _ in range(30)] + [{"hang": True}])
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "again"})
    snap = wait_run(client, cid, posted.json()["run"]["id"], timeout=30)
    assert snap["runs"][-1]["error"] == "step_limit"
    ended = record(client)["Lead"]["ended"]
    assert (ended["done"], ended["stopped_by_koloni"], ended["failed"]) == (1, 1, 0)
