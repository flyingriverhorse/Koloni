"""Slice 33b beyond its acceptance set: what the Observer is given of the work on record,
where what it spent goes, and that no agent is offered it as a role."""

import pytest
from sqlalchemy import select

from app import observer
from app.db.models import OwnRequest, Role
from app.model_client import ModelUnavailable
from app.room import member_model
from tests.conftest import Gate
from tests.test_chat_flow import text
from tests.test_claim_scenarios import write
from tests.test_observer_model_scenarios import (
    ORIGIN,
    REPORT,
    SAID,
    TASK,
    child_of,
    project,
    turn,
)
from tests.test_parallel import until
from tests.test_spawn import begin, call, reported, spawn, step


def test_it_sees_the_diff_and_the_check_and_what_it_spent_is_under_the_model_it_asked(
    make_client, wait_run, project_dir
):
    client, model = make_client([
        spawn("Coder", TASK),
        step(write("a.txt", "NEW-LINE")),
        text(REPORT),
        text(SAID, i=11, o=7),  # the observer
        text("Good."),
    ])
    pid = project(client, project_dir, observe_reports=True,
                  check_command="python -c \"print('CHECKED')\"")
    cid, run_id = turn(client, pid)
    snap = wait_run(client, cid, run_id, timeout=20)
    seen = model.calls[3][-1]["content"]
    assert "write_file (" in seen and "a.txt" in seen and "+NEW-LINE" in seen
    assert "CHECKED" in seen and "passed" in seen
    kid = child_of(snap)
    by = {"provider_name": kid["provider_name"], "model_id": kid["model_id"]}
    assert kid["observation"] == SAID and kid["observed_by"] == by
    assert (kid["input_tokens"], kid["output_tokens"]) == (5, 3 + 2)  # its own steps only
    with client.app.state.session_factory() as session:
        (own,) = session.scalars(select(OwnRequest))
        assert (own.agent_id, own.provider_name, own.input_tokens, own.output_tokens) == (
            kid["id"], kid["provider_name"], 11, 7)


def test_no_agent_is_offered_the_observer_and_its_role_saves_with_no_tools(
    make_client, wait_run, project_dir
):
    client, model = make_client([spawn("Observer", TASK), text("Then not.")])
    cid, run_id = turn(client, project(client, project_dir))
    snap = wait_run(client, cid, run_id)
    (spawn_tool,) = [t for t in model.tool_args[0] if t["function"]["name"] == "spawn_agent"]
    listed = spawn_tool["function"]["description"]
    assert "- Reviewer —" in listed and "Observer" not in listed
    # asked for by name all the same, it is no role an agent is opened in
    assert "unknown role: Observer" in model.calls[1][-1]["content"]
    assert [agent["depth"] for agent in snap["agents"]] == [0]

    roles = {r["name"]: r for r in client.get("/api/roles").json()}
    observer, reviewer = roles["Observer"], roles["Reviewer"]
    assert observer["tools"] == []
    saved = client.patch(f"/api/roles/{observer['id']}", json={"tools": [], "tier": "fast"},
                         headers={"Origin": ORIGIN})
    assert saved.status_code == 200 and saved.json()["tier"] == "fast"
    # any other role still needs a tool
    assert client.patch(f"/api/roles/{reviewer['id']}", json={"tools": []}).status_code == 422


# --- the review's fixes ---------------------------------------------------------------


def test_while_the_observer_is_asked_a_sibling_reaches_the_agent_only_with_a_note(
    make_client, wait_run, project_dir
):
    held, tester = Gate(), Gate()
    client, model = make_client({
        # (the Observer's request carries no agent's name: it is taken from the Lead's)
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "do A"}, "s1"),
                      call("spawn_agent", {"role": "Tester", "task": "do B"}, "s2")),
                 held.step(text(SAID)), text("Fine."), text("done")],
        "Coder": [text("A done")],
        "Tester": [tester.step(step(call("message_agent", {"to": "Coder", "message": "hi"}, "q"))),
                   text("B done")],
    })
    project(client, project_dir, observe_reports=True)
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_max_parallel=3)
    held.wait_partial()  # the Coder is done, and its observer is being asked
    tester.release()
    until(client, cid, lambda s: any(
        t["name"] == "message_agent" and t["status"] == "succeeded" for t in s["tool_calls"]))
    held.release()
    snap = wait_run(client, cid, run_id)
    (sent,) = [t for t in snap["tool_calls"] if t["name"] == "message_agent"]
    assert sent["result"].startswith("noted: Coder is at work")
    assert len(model.calls_of["Coder"]) == 1  # no turn of its own, on the observer's model
    assert {a["name"]: a["status"] for a in snap["agents"]} == {
        "Lead": "completed", "Coder": "completed", "Tester": "completed"}


def test_a_room_cannot_open_an_observer(client):
    with (client.app.state.session_factory() as session,
          pytest.raises(ValueError, match="unknown role: Observer")):
        member_model(session, None, "Observer", None, None)


def test_a_role_of_the_users_own_named_observer_is_not_the_observer(
    make_client, wait_run, project_dir
):
    client, model = make_client([spawn("Reviewer", TASK), text(REPORT), text("Good.")])
    with client.app.state.session_factory() as session:
        mine = session.scalars(select(Role).where(Role.name == "Observer")).one()
        mine.builtin, mine.tools = False, ["read_file"]  # as one made before 33b would be
        session.commit()
    pid = project(client, project_dir, observe_reports=True)
    cid, run_id = turn(client, pid)
    kid = child_of(wait_run(client, cid, run_id))
    assert (kid["observation"], kid["observation_note"]) == (None, observer.NO_OBSERVER)
    assert len(model.calls) == 3  # nobody else was asked
    assert "Observer" in [r["name"] for r in client.get("/api/roles").json()]


def test_an_observer_that_does_not_answer_in_time_is_not_waited_for(
    make_client, wait_run, project_dir, monkeypatch
):
    monkeypatch.setattr(observer, "SECONDS", 0.3)
    held = Gate()
    client, model = make_client([spawn("Reviewer", TASK), text(REPORT), held.step(text(SAID)),
                                 text("Good.")])
    pid = project(client, project_dir, observe_reports=True)
    cid, run_id = turn(client, pid)
    snap = wait_run(client, cid, run_id)
    held.release()
    kid = child_of(snap)
    assert kid["observation"] is None and kid["observation_note"] == observer.TIMED_OUT
    assert "did not answer within" in kid["observation_note"]
    assert reported(model.calls[3][-1]["content"]) == f"Reviewer finished.\n\n{REPORT}"


def test_a_failure_that_says_nothing_still_says_why(make_client, wait_run, project_dir):
    client, _model = make_client([spawn("Reviewer", TASK), text(REPORT), ModelUnavailable(""),
                                  text("Good.")])
    cid, run_id = turn(client, project(client, project_dir, observe_reports=True))
    kid = child_of(wait_run(client, cid, run_id))
    assert kid["observation_note"] == observer.FAILED.format(why=observer.FAILED_SILENTLY)


def test_stopped_while_it_is_asked_says_so(make_client, wait_run, project_dir):
    held = Gate()
    client, _model = make_client([spawn("Reviewer", TASK), text(REPORT), held.step(text(SAID))])
    cid, run_id = turn(client, project(client, project_dir, observe_reports=True))
    held.wait_partial()
    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 202
    snap = wait_run(client, cid, run_id)
    held.release()
    kid = child_of(snap)
    assert (kid["observation"], kid["observation_note"]) == (None, observer.STOPPED)


SECRET = "https://hooks.example.test/T0-SECRET-abcdef123456"


def test_what_the_agent_wrote_is_quoted_with_its_secrets_masked_and_the_diff_has_a_budget(
    make_client, wait_run, project_dir, monkeypatch
):
    monkeypatch.setattr(observer, "DIFF_CHARS", 45)  # a.txt's header and its first word
    client, model = make_client([
        spawn("Coder", TASK),
        step(write("a.txt", f"{SECRET} is where it posts", "w1"), write("b.txt", "B-LINE", "w2")),
        text(REPORT), text(SAID), text("Good."),
    ])
    pid = project(client, project_dir, observe_reports=True, notify_url=SECRET)
    cid, run_id = turn(client, pid)
    wait_run(client, cid, run_id, timeout=20)
    seen = model.calls[3][-1]["content"]
    assert SECRET not in seen and "***" in seen
    assert '"a.txt" (' in seen and "b.txt" not in seen  # the budget was spent on a.txt
    assert observer.CUT in seen


@pytest.mark.parametrize("said, kept", [
    ("One, e.g. this. Two. Three. Four.", "One, e.g. this. Two. Three."),
    ("Testler 3. adımda geçti. İki. Üç. Dört.", "Testler 3. adımda geçti. İki. Üç."),
    ("A. (B.) “C.” D.", "A. (B.) “C.”"),
])
def test_a_sentence_ends_only_where_the_next_begins_as_one(said, kept):
    assert observer.kept_of(said) == kept


def test_the_observers_role_takes_no_tools(client):
    observer_id = next(r["id"] for r in client.get("/api/roles").json() if r["name"] == "Observer")
    refused = client.patch(f"/api/roles/{observer_id}", json={"tools": ["read_file"]})
    assert refused.status_code == 422 and "no tools" in refused.json()["detail"]
