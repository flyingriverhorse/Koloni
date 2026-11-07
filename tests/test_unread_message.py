"""K-fikir-okunmamis: while a message of the user's waits behind the running turn, an agent's
ask_user opens no new question card - it is handed the message instead, once."""

from app.agent import USER_WROTE
from tests.test_agent_writes import wait_status
from tests.test_chat_flow import start_in_mode, text
from tests.test_spawn import call, step

ASK = step(call("ask_user", {"question": "Which colour?", "options": ["Red", "Blue"]}, "q1"))


def test_a_queued_message_is_handed_to_the_agent_in_place_of_its_question(
    make_client, wait_run, project_dir, gate
):
    client, _ = make_client([gate.step(ASK), text("blue it is"), text("done again")])
    cid, run_id = start_in_mode(client, project_dir, "ask")
    gate.wait_partial()
    queued = client.post(f"/api/conversations/{cid}/messages", json={"content": "make it blue"})
    assert queued.json()["run"]["status"] == "queued"
    gate.release()
    snap = wait_run(client, cid, run_id)
    assert snap["questions"] == []
    ((status, result),) = [(t["status"], t["result"]) for t in snap["tool_calls"]]
    assert status == "denied"
    assert result == USER_WROTE.format(words='"make it blue"')
    # Its own turn still comes after.
    assert wait_run(client, cid, queued.json()["run"]["id"])["runs"][-1]["status"] == "completed"


def test_with_no_message_waiting_the_question_is_a_card_as_before(
    make_client, wait_run, project_dir
):
    client, _ = make_client([ASK, text("done")])
    cid, run_id = start_in_mode(client, project_dir, "ask")
    (question,) = wait_status(client, cid, "waiting_approval")["questions"]
    assert question["question"] == "Which colour?"
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "Red"},
                headers={"Origin": "http://127.0.0.1:8790"})
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"


# --- B-359: ask_user does not offer a Take in card's own words while that card waits ----------

TAKE_IN = step(call("ask_user", {"question": "Take the Coder's work in? And HEAD?", "options": [
    "Take in, HEAD stays as it is", "Take in, and make HEAD match GET", "Discard the copy"]}, "q1"))


def test_card_words_are_matched_by_their_leading_words_only():
    from app.agent import CARD_ACTIONS

    for said in ("Take in, HEAD stays", "take it in", "Discard the copy", "Apply", "merge now"):
        assert CARD_ACTIONS.match(said), said
    for said in ("Red", "Takeaway", "Keep HEAD; take in later", "Applying a fix", "Do not merge"):
        assert not CARD_ACTIONS.match(said), said


def test_while_a_kept_copy_waits_its_take_in_is_not_asked_again(
    make_client, wait_run, project_dir, gate
):
    from app.agent import CARD_DECIDES
    from app.db.models import Agent, Merge

    client, _ = make_client([gate.step(TAKE_IN), text("asked only of HEAD")])
    cid, run_id = start_in_mode(client, project_dir, "auto_edit")
    gate.wait_partial()
    with client.app.state.session_factory() as session:
        lead = session.query(Agent).filter_by(run_id=run_id).one()
        session.add(Merge(run_id=run_id, agent_id=lead.id, status="interrupted", files=[],
                          kept_in=str(project_dir / "kept")))
        session.commit()
    gate.release()
    snap = wait_run(client, cid, run_id)
    assert snap["questions"] == []
    ((status, result),) = [(t["status"], t["result"]) for t in snap["tool_calls"]]
    assert (status, result) == ("denied", CARD_DECIDES)
    assert [m["status"] for m in snap["merges"]] == ["kept"]  # (as the page says it)


def test_after_the_user_rejected_this_turn_s_card_its_words_are_not_asked_again(
    make_client, wait_run, project_dir, gate
):
    # R154 (live): rejected, then the Lead asked ['Take in', 'Discard', 'Apply'] - and it was asked.
    from app.agent import CARD_DECIDES
    from app.db.models import Agent, Merge

    asks = step(call("ask_user", {"question": "And now?", "options": ["Take in", "Discard", "Apply"]}))
    client, _ = make_client([gate.step(asks), text("asked otherwise")])
    cid, run_id = start_in_mode(client, project_dir, "auto_edit")
    gate.wait_partial()
    with client.app.state.session_factory() as session:
        lead = session.query(Agent).filter_by(run_id=run_id).one()
        session.add(Merge(run_id=run_id, agent_id=lead.id, status="rejected", files=[]))
        session.commit()
    gate.release()
    snap = wait_run(client, cid, run_id)
    assert snap["questions"] == []
    assert [(t["status"], t["result"]) for t in snap["tool_calls"]] == [("denied", CARD_DECIDES)]


def test_with_no_card_waiting_take_in_words_are_a_question_as_any(
    make_client, wait_run, project_dir
):
    client, _ = make_client([TAKE_IN, text("done")])
    cid, run_id = start_in_mode(client, project_dir, "auto_edit")
    (question,) = wait_status(client, cid, "waiting_approval")["questions"]
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "Discard the copy"},
                headers={"Origin": "http://127.0.0.1:8790"})
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
