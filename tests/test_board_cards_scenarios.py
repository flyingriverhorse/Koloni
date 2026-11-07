"""Slice 60b's acceptance set: the Board as cards in three columns. Written before the code.

The user: "Board, Tools, Memory, Usage must get better for the user". Design:
`tasarim/specs/2026-10-20-dilim-60-sayfalar-ve-model-gucu-design.md` (Board, and §3b), mockup
`tasarim/specs/60-ornekler/pages.html` (A).

Columns (frontend): At work · Waits for you (a decision, a question, changes to apply - and a
conversation whose last turn failed or was stopped, labelled so) · Done today (older under
"▸ N older"; a conversation that never ran is older too).

Contract (backend): a conversation's last turn on the board (`BoardTurn`) also says, for a card
of a finished one, how many agents it had, the model it ran on (provider and model as its Lead
ran), when it started, and its tokens (in + out as recorded; null when not known, never 0 made up).
"""

import pytest

from app.schemas import BoardTurn

if "agents" not in BoardTurn.model_fields:
    pytest.skip("slice 60b is not built yet", allow_module_level=True)  # written before the code

from tests.test_board_scenarios import board, go, on_board, project, talk  # noqa: E402
from tests.test_chat_flow import text  # noqa: E402


def test_a_finished_turn_says_its_agents_model_time_and_tokens(make_client, wait_run, project_dir):
    client, _model, pid = project(make_client, project_dir, [text("Done.", i=120, o=30)])
    cid = talk(client, pid)
    wait_run(client, cid, go(client, cid))
    turn = on_board(board(client, pid), cid)["turn"]
    assert turn["status"] == "completed"
    assert turn["agents"] == 1
    assert turn["started_at"] and turn["ended_at"]
    assert turn["tokens"] == 150
    assert "model_id" in turn and "provider_name" in turn  # null where not known


def test_a_conversation_that_never_ran_has_no_turn(make_client, project_dir):
    client, _model, pid = project(make_client, project_dir, [])
    cid = talk(client, pid)
    assert on_board(board(client, pid), cid)["turn"] is None
