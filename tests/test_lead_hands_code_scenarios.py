"""Slice 48's acceptance set: the Lead hands code to sub-agents. Written before the code.

The user found the Lead writing code itself where a Coder was there for it ("Do small jobs
yourself"). Per conversation, on by default: the Lead is not given the tools that change files and
is told to hand every change to files to a sub-agent; a sub-agent keeps its own tools. Switched
off, the Lead works as before.

Contract: `ConversationOut.lead_hands_code` (bool, true for a new conversation);
`ConversationPatch.lead_hands_code`.
"""

import json

import pytest

from app.schemas import ConversationOut

if "lead_hands_code" not in ConversationOut.model_fields:
    pytest.skip("slice 48 is not built yet", allow_module_level=True)  # written before the code

from tests.test_chat_flow import text  # noqa: E402
from tests.test_spawn import begin, call, names, spawn, step  # noqa: E402

WRITERS = {"write_file", "edit_file"}
TOLD = "hand every change to files to a sub-agent"


def test_on_by_default_the_lead_cannot_change_files_and_is_told_to_hand_them_on(
    make_client, wait_run, project_dir
):
    client, model = make_client(
        [
            spawn("Coder", "write calc.html"),
            step(call("write_file", {"path": "calc.html", "content": "<p>1+1</p>"})),
            text("written"),
            text("the Coder wrote it"),
        ]
    )
    cid, run_id = begin(client, project_dir, mode="full_auto", content="write calc.html")
    snap = wait_run(client, cid, run_id)
    assert snap["conversation"]["lead_hands_code"] is True
    assert not WRITERS & set(names(model.tool_args[0]))  # the Lead's
    assert TOLD in json.dumps(model.calls[0]).lower()
    assert set(names(model.tool_args[1])) >= WRITERS  # the Coder's: its own
    assert [c["path"] for c in snap["file_changes"]] == ["calc.html"]


def test_a_lead_that_writes_anyway_is_refused_and_nothing_is_written(
    make_client, wait_run, project_dir
):
    client, _model = make_client(
        [
            step(call("write_file", {"path": "calc.html", "content": "x"})),
            text("could not"),
        ]
    )
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    (tried,) = snap["tool_calls"]
    assert tried["status"] in ("failed", "denied")
    assert snap["file_changes"] == []


def test_switched_off_the_lead_works_as_before(make_client, wait_run, project_dir):
    client, model = make_client(
        [
            step(call("write_file", {"path": "calc.html", "content": "x"})),
            text("written"),
        ]
    )
    cid, run_id = begin(client, project_dir, mode="full_auto", lead_hands_code=False)
    snap = wait_run(client, cid, run_id)
    assert snap["conversation"]["lead_hands_code"] is False
    assert set(names(model.tool_args[0])) >= WRITERS
    assert TOLD not in json.dumps(model.calls[0]).lower()
    assert [c["path"] for c in snap["file_changes"]] == ["calc.html"]
