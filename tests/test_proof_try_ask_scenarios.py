"""CL-329 I: a turn that changed a command-line tool and no test is asked for a test once; where
the Orchestrator answers with a reason (no call: its answer ends the turn), the live try was made
all the same - it comes before the ask now - and its row is said."""

import pytest

from app.agent.words import TEST_ASKED
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_writes import write
from tests.test_chat_flow import text
from tests.test_proof_end_scenarios import PASS, begin, texts
from tests.test_proof_try_scenarios import HELP, TOOL

pytestmark = pytest.mark.no_po

CHECK = "python check.py"


def test_a_tool_asked_for_a_test_answered_with_a_reason_is_still_tried(
    make_client, wait_run, project_dir
):
    executor = ScriptedExecutor([PASS, Script(["usage: tool [-h]\n", "  -h  help\n"])])
    client, model = make_client(
        [
            write("bin/tool.py", TOOL),
            text("done"),
            text("No test fits: it only parses its arguments."),
        ],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, check_command=CHECK)
    rows = texts(wait_run(client, cid, run_id))
    assert [line for line, _cwd in executor.started] == [CHECK, HELP]
    assert f"Tried {HELP}: exit 0, 2 lines" in rows, rows
    assert any(one.startswith("No new test: the Orchestrator said") for one in rows), rows
    asked = [str(m["content"]) for m in model.calls[-1] if m["role"] == "user"]
    assert any(TEST_ASKED.split("{files}")[1][:24] in one for one in asked), asked
