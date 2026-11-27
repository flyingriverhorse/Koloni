"""C2: a word written into a CLI's running turn comes to one outcome - taken, not sent or unknown -
said once, to whatever waits on it (`app.delivery`)."""

import asyncio

import pytest

from app.delivery import NOT_SENT, TAKEN, UNKNOWN, Deliveries, Delivery, steer_asked


def outcomes(*sent: Delivery) -> list:
    told: list = []
    for one in sent:
        one.then(told.append)
    return told


def test_words_are_matched_oldest_first_and_settled_once():
    deliveries = Deliveries()
    first, second = deliveries.sent("use blue"), deliveries.sent("use blue")
    told = outcomes(first, second)
    deliveries.took(text="use blue")  # (Claude Code's echo: its id is its own, not KOLONİ's)
    assert (first.outcome, second.outcome) == (TAKEN, None)
    assert deliveries.over() is True  # (one was still open)
    first.settle(NOT_SENT)  # (once: what came of it does not change)
    assert told == [TAKEN, UNKNOWN] and first.outcome == TAKEN


def test_one_sent_once_its_turn_is_over_is_not_sent_and_a_failing_listener_is_only_logged(
    caplog,
):
    deliveries = Deliveries()
    assert deliveries.over() is False
    late = deliveries.sent("too late")
    assert late.outcome == NOT_SENT and deliveries.open == []

    def broken(_outcome):
        raise RuntimeError("its chat is gone")

    late.then(broken)  # (told at once: it is known)
    assert "was not taken in" in caplog.text


async def writing(fails: bool = False):
    """A request's write, and its wait for an answer that its read loop hands on."""
    if fails:
        raise BrokenPipeError
    await asyncio.sleep(60)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("answer", "named", "outcome"),
    [
        ({"result": {"turnId": "t1"}}, None, TAKEN),  # (Codex's answer names its turn)
        ({"error": {"code": -32600, "message": "no active turn to steer"}}, None, NOT_SENT),
        ({"error": {"code": -32603, "message": "internal"}}, None, UNKNOWN),  # (not measured)
        ({"result": {"messageId": "m1"}}, "messageId", None),  # (Copilot's: once it shows it)
    ],
)
async def test_its_answer_as_it_is_read_settles_it_whenever_it_comes(answer, named, outcome):
    deliveries = Deliveries()
    sent = await steer_asked(deliveries, "use blue", writing(), 4, 0.01, named)
    assert sent.outcome is None  # (no answer in time: open)
    deliveries.answered(4, answer)
    assert sent.outcome == outcome
    if named:
        deliveries.took(key="m1")  # (its user.message naming that id)
        assert sent.outcome == TAKEN
    deliveries.over()


@pytest.mark.anyio
async def test_an_id_shown_before_its_answer_was_read_is_taken_once_it_is():
    deliveries = Deliveries()
    sent = await steer_asked(deliveries, "use blue", writing(), 5, 0.01, "messageId")
    deliveries.took(key="m7")  # (its user.message, read before the answer that names it)
    deliveries.answered(5, {"result": {"messageId": "m7"}})
    assert sent.outcome == TAKEN
    deliveries.over()


@pytest.mark.anyio
async def test_one_never_written_is_not_sent_and_one_never_answered_is_unknown():
    deliveries = Deliveries()
    broken = await steer_asked(deliveries, "a", writing(fails=True), 6, 1.0)
    never = await steer_asked(deliveries, "b", writing(), 7, 0.01)
    (asking,) = deliveries.asking
    assert (broken.outcome, never.outcome) == (NOT_SENT, None)
    assert deliveries.over() is True
    deliveries.answered(7, {"error": {"message": "it ended"}})  # (after its end: too late)
    await asyncio.wait({asking}, timeout=5)
    assert never.outcome == UNKNOWN and asking.cancelled()  # (its ask is not left at work)


@pytest.mark.anyio
async def test_ids_that_are_no_ids_are_no_sign_and_break_nothing():
    # (A CLI's line read as it came: a list or a map where an id stands must not end its run.)
    deliveries = Deliveries()
    sent = await steer_asked(deliveries, "use blue", writing(), 8, 0.01, "messageId")
    deliveries.answered([8], {"result": {"messageId": "m8"}})
    deliveries.took(key={"m": 8})
    deliveries.answered(8, {"result": {"messageId": ["m8"]}})
    deliveries.took(key=["m8"])
    assert sent.outcome is None and sent.key is None
    assert deliveries.over() is True and sent.outcome == UNKNOWN


@pytest.mark.anyio
async def test_an_empty_id_or_a_bool_for_a_number_is_no_sign():
    deliveries = Deliveries()
    deliveries.took(key="")  # (a user.message with no id: the prompt's, say)
    named = await steer_asked(deliveries, "use blue", writing(), 8, 0.01, "messageId")
    deliveries.answered(8, {"result": {"messageId": ""}})
    first = await steer_asked(deliveries, "y", writing(), 1, 0.01)
    deliveries.answered(True, {"result": {}})  # (JSON's true is no request's number)
    assert (named.outcome, named.key, first.outcome) == (None, None, None)
    deliveries.over()


def test_its_echo_is_taken_by_its_words_and_only_an_echo_is_kept_from_its_stream():
    deliveries = Deliveries()
    plain, blocks = deliveries.sent("use blue"), deliveries.sent("and green")
    echo = {"type": "user", "isReplay": True, "message": {"content": "use blue"}}
    assert deliveries.echoed([echo]) is True  # (not its stream's: the prompt again, long)
    listed = {**echo, "message": {"content": [{"type": "text", "text": "and green"}]}}
    assert deliveries.echoed([listed, {"type": "assistant"}]) is False  # (one of its stream's)
    assert deliveries.echoed([{"type": "user", "message": {"content": "use blue"}}]) is False
    assert (plain.outcome, blocks.outcome) == (TAKEN, TAKEN)
