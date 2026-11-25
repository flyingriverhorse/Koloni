"""Y1: a model's streamed answer whose emoji is split between two pieces - its surrogate pair cut in
half, as a stream of UTF-16 pieces does - is one character again where it is kept; a half alone is
the replacement character, and the turn completes."""

import pytest

from app.agent.ctx import joined
from app.model_client import StepResult
from tests.test_chat_flow import start

HIGH, LOW = "\ud83d", "\ude00"  # (the halves of U+1F600)


def test_a_pair_split_between_two_pieces_is_joined():
    assert joined("abc" + HIGH, LOW + " done") == "abc\U0001f600 done"
    assert joined("abc", "def") == "abcdef" and joined("", LOW) == LOW


@pytest.mark.parametrize(
    ("pieces", "kept"),
    [
        (["abc" + HIGH, LOW + " done"], "abc\U0001f600 done"),
        (["abc" + HIGH, " done"], "abc\N{REPLACEMENT CHARACTER} done"),
    ],
    ids=["split", "alone"],
)
def test_the_answer_is_kept_whole_and_the_turn_completes(
    make_client, wait_run, project_dir, pieces, kept
):
    async def streamed(on_delta):
        for piece in pieces:
            await on_delta(piece)
        return StepResult("".join(pieces), [], 1, 1)

    client, _model = make_client([streamed])
    cid, run_id = start(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [m["content"] for m in snap["messages"] if m["role"] == "assistant"] == [kept]
