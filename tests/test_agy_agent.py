"""The agy CLI as a provider: it works with its own tools, and without a flag it only reads.

Everything here runs against a stand-in (tests/fake_agy_cli.py) that speaks the stream
measured from the real CLI on 7 Oct 2026; the real one is never started.
"""

import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest
from alembic import command

from app.catalog import models_for
from app.config import load_settings
from app.db.models import Provider
from app.main import create_app
from app.model_agy import AgyClient
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_agent_talk import message
from tests.test_agent_writes import wait_status
from tests.test_chat_flow import text
from tests.test_claude_native import ORIGIN
from tests.test_migration_0002 import _config
from tests.test_model_cli import alive, gone
from tests.test_spawn import role_id, spawn

# The catalogue's names for agy, offered between the user's list and agy's own (slice 59c).
KNOWN = [row["name"] for row in models_for("agy_cli")]

FAKE = [sys.executable, str(Path(__file__).with_name("fake_agy_cli.py"))]
SKIP = "--dangerously-skip-permissions"


def told_of_kolonis(prompt):
    """B-310: agy has KOLONİ's tools over its bridge, and is told of them by the koloni
    server's name."""
    assert 'The "koloni" MCP server' in prompt and "nothing here to reach" not in prompt


# --- the stream, one event at a time ---------------------------------------------------

STREAMS = Path(__file__).with_name("agy_streams")
REFUSAL = (
    'permission check failed for command "pytest": user denied permission to run command:\n'
    "pytest\nDo not attempt to circumvent this denial.")
UNSURE = "ended in an error; not known whether it ran"


def translator(reads=True):
    return AgyClient(None, "m", reads=reads)._translator()


def recorded(name):
    """A stream of the real CLI, as it was kept: one event on a line."""
    lines = (STREAMS / name).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def nested(name, **fields):
    """An event as the real CLI sends it: its fields in an object of its own name."""
    return {"event": name, name: fields}


def tool(state, name, index=None, **info):
    numbered = {} if index is None else {"step_index": index}
    return nested("step_update", **numbered, state=state, step_type="tool", tool_name=name,
                  tool_info={"name": name, **info})


def reply(state, index=1, **fields):
    return nested("step_update", step_index=index, state=state, step_type="agent_response",
                  **fields)


def result(**fields):
    return nested("result", status="SUCCESS", **fields)


def items(told):
    return [event["item"] for event in told if event["type"].startswith("item.")]


def words(told):
    return "".join(event["text"] for event in told if event["type"] == "text")


def test_the_real_stream_of_a_file_read_is_one_tool_one_answer_and_the_counts():
    translate = translator()
    events = recorded("reads_a_file.jsonl")
    told = [out for event in events for out in translate(event)]
    deltas = [event["step_update"]["text_delta"] for event in events
              if event["event"] == "step_update" and "text_delta" in event["step_update"]]
    assert told[0] == {"type": "model", "model": "gemini-3.8-flash-low"}
    started, done = items(told)
    assert started == {"type": "mcp_tool_call", "id": "agy_2", "server": "agy",
                       "tool": "view_file", "arguments": {"AbsolutePath": "C:\\proj\\hello.py"}}
    assert done == {**started, "status": "completed", "error": None,
                    "result": {"content": [{"type": "text", "text": "2 lines, 12 bytes"}]}}
    # the answer is what came in pieces: its ending once, and nothing from the result
    assert words(told) == "".join(deltas) and words(told).endswith("prints `hi`.\n")
    assert [event["type"] for event in told].count("text") == len(deltas)
    assert told[-1] == {"type": "turn.completed", "usage": {
        "input_tokens": 25911, "output_tokens": 189, "cached_input_tokens": 0}}
    # nothing holds the limit on silence off: no step is said to be "busy"
    assert not [event for event in told if event["type"] == "busy"]


def test_the_real_stream_of_a_refused_command_is_a_denied_step_and_no_words():
    translate = translator()
    told = [out for event in recorded("command_refused.jsonl") for out in translate(event)]
    started, refused, _note = items(told)
    assert (started["tool"], started["arguments"]) == (
        "run_command", {"CommandLine": "Get-ChildItem -Path ."})
    assert (refused["type"], refused["id"], refused["tool"], refused["status"]) == (
        "mcp_tool_call", "agy_2", "run_command", "denied")
    assert refused["arguments"] == {"CommandLine": "Get-ChildItem -Path ."}
    assert refused["error"]["message"].startswith(
        'permission check failed for command "Get-ChildItem -Path .": user denied permission')
    # it said nothing, and its result holds no answer: none is made up - KOLONİ says, in its
    # own name, what was refused before it ended so (B-317)
    assert words(told) == ""
    assert [item["type"] for item in items(told)] == ["mcp_tool_call"] * 2 + ["agent_message"]
    assert items(told)[-1]["text"] == (
        "KOLONİ: agy ended its turn without an answer, after it was refused `run_command: "
        "refused by agy`.")  # (not its words: they hold the command line)
    assert told[-1] == {"type": "turn.completed", "usage": {
        "input_tokens": 11708, "output_tokens": 125, "cached_input_tokens": 0}}


def test_init_names_the_model():
    assert translator()(nested("init", model="gemini-x", tools=[])) == [
        {"type": "model", "model": "gemini-x"}]
    assert translator()(nested("init")) == []
    # the real CLI keeps an event's fields in an object of its name: nothing else is read
    assert translator()({"event": "init", "model": "gemini-x"}) == []


def test_only_the_shape_the_real_cli_sends_is_read():
    translate = translator()
    assert translate({"event": "step_update", "step_type": "agent_response", "state": "ACTIVE",
                      "text_delta": "hi"}) == []
    assert translate({"event": "step_update", "step_type": "tool", "state": "DONE",
                      "tool_name": "list_dir", "tool_info": {"output": "hello.py"}}) == []
    (odd,) = translate({"event": "result", "status": "SUCCESS", "response": "hi"})
    assert odd["type"] == "error"  # a result that says nothing is not called a success


def test_text_deltas_are_the_agents_words_and_two_answers_are_two_paragraphs():
    translate = translator()
    assert translate(reply("DONE", 1, usage={"input_tokens": 9})) == []  # it chose a tool
    assert translate(reply("ACTIVE", 2, text_delta="It prints ")) == [
        {"type": "text", "text": "It prints "}]
    assert translate(reply("ACTIVE", 2, text_delta="hi.")) == [{"type": "text", "text": "hi."}]
    assert translate(reply("DONE", 2, text_delta="\n")) == [{"type": "text", "text": "\n"}]
    # the next answer is a new paragraph: one empty line, not two
    assert translate(reply("ACTIVE", 3, text_delta="Done.")) == [
        {"type": "text", "text": "\nDone."}]
    assert translate(reply("DONE", 3)) == []
    assert translate(reply("ACTIVE", 4, text_delta="And more.")) == [
        {"type": "text", "text": "\n\nAnd more."}]
    assert translate(nested("step_update", step_index=0, state="DONE",
                            step_type="user_input")) == []


def test_after_a_tool_an_answer_starts_without_an_empty_line():
    translate = translator()
    translate(reply("ACTIVE", 1, text_delta="Looking."))
    translate(reply("DONE", 1, text_delta="\n"))
    translate(tool("DONE", "view_file", 2, parameters={}, output="x"))
    assert translate(reply("ACTIVE", 3, text_delta="Found.")) == [
        {"type": "text", "text": "Found."}]


def test_a_delta_of_nothing_but_space_is_not_the_agent_speaking():
    translate = translator()
    assert translate(reply("ACTIVE", 1, text_delta="\n")) == []
    assert translate(reply("DONE", 1, text_delta=" \n")) == []
    # so the answer is the one the result carries, as it came
    assert translate(result(response="It prints hi.\n", usage={"input_tokens": 3})) == [
        {"type": "item.completed", "item": {"type": "agent_message", "text": "It prints hi.\n"}},
        {"type": "turn.completed", "usage": {"input_tokens": 3, "output_tokens": None}}]
    # space before the first word of an answer is kept with it
    translate = translator()
    assert translate(reply("ACTIVE", 1, text_delta="  ")) == []
    assert translate(reply("ACTIVE", 1, text_delta="hi")) == [{"type": "text", "text": "  hi"}]


def test_the_answer_is_the_deltas_or_the_result_never_both():
    usage = {"input_tokens": 2100, "output_tokens": 45, "cached_tokens": 7}
    done = {"type": "turn.completed", "usage": {"input_tokens": 2100, "output_tokens": 45}}
    assert translator()(result(response="hi", usage=usage)) == [
        {"type": "item.completed", "item": {"type": "agent_message", "text": "hi"}}, done]
    # no answer at all: none is made up
    assert translator()(result(response="", usage=usage)) == [done]
    assert translator()(result(response=" \n", usage=usage)) == [done]
    assert translator()(result(usage=usage)) == [done]
    translate = translator()
    translate(reply("ACTIVE", 1, text_delta="hi"))
    # what was said in deltas is not said a second time, whatever the result holds
    assert translate(result(response="hi there", usage=usage)) == [done]


def test_a_tool_of_its_own_starts_and_is_told_when_it_is_done():
    translate = translator()
    (on,) = translate(tool("ACTIVE", "view_file", 2, parameters={"AbsolutePath": "hello.py"}))
    assert on == {"type": "item.started", "item": {
        "type": "mcp_tool_call", "id": "agy_2", "server": "agy", "tool": "view_file",
        "arguments": {"AbsolutePath": "hello.py"}}}
    assert translate(tool("ACTIVE", "view_file", 2, parameters={})) == []  # said again
    (done,) = translate(tool("DONE", "view_file", 2, parameters={"AbsolutePath": "hello.py"},
                             output="print('hi')"))
    assert done == {"type": "item.completed", "item": {
        "type": "mcp_tool_call", "id": "agy_2", "server": "agy", "tool": "view_file",
        "arguments": {"AbsolutePath": "hello.py"}, "status": "completed", "error": None,
        "result": {"content": [{"type": "text", "text": "print('hi')"}]}}}


def test_two_tools_of_one_name_at_once_are_told_apart_by_their_step():
    translate = translator()
    first = items(translate(tool("ACTIVE", "view_file", 2, parameters={"AbsolutePath": "a"})))
    second = items(translate(tool("ACTIVE", "view_file", 3, parameters={"AbsolutePath": "b"})))
    assert (first[0]["id"], second[0]["id"]) == ("agy_2", "agy_3")
    (late,) = items(translate(tool("DONE", "view_file", 3, parameters={"AbsolutePath": "b"},
                                   output="B")))
    (early,) = items(translate(tool("ERROR", "view_file", 2, parameters={"AbsolutePath": "a"},
                                    error={"message": "no such file"})))
    assert (late["id"], late["arguments"], late["status"]) == (
        "agy_3", {"AbsolutePath": "b"}, "completed")
    assert (early["id"], early["arguments"], early["status"]) == (
        "agy_2", {"AbsolutePath": "a"}, "failed")


def test_a_step_said_to_be_done_twice_is_one_record():
    translate = translator()
    translate(tool("ACTIVE", "view_file", 2, parameters={}))
    assert len(items(translate(tool("DONE", "view_file", 2, parameters={}, output="x")))) == 1
    assert translate(tool("DONE", "view_file", 2, parameters={}, output="x")) == []
    assert translate(tool("ERROR", "view_file", 2, parameters={})) == []
    assert translate(tool("ACTIVE", "view_file", 2, parameters={})) == []
    # the same for a command, which is a record of another kind
    native = translator(reads=False)
    assert len(items(native(tool("DONE", "run_command", 4, parameters={}, output="")))) == 1
    assert native(tool("DONE", "run_command", 4, parameters={}, output="")) == []


def test_a_step_without_a_number_is_paired_by_the_tools_name():
    translate = translator()
    (on,) = items(translate(tool("ACTIVE", "list_dir", parameters={})))
    assert translate(tool("ACTIVE", "list_dir", parameters={})) == []
    (done,) = items(translate(tool("DONE", "list_dir", parameters={}, output="hello.py")))
    assert done["id"] == on["id"] and done["status"] == "completed"
    # one that was never said to start is still a record of its own
    (alone,) = items(translate(tool("DONE", "list_dir", parameters={}, output="x")))
    assert alone["id"] != on["id"]


def test_a_step_that_never_ends_is_not_told_as_done_and_holds_nothing_off():
    translate = translator()
    told = translate(tool("ACTIVE", "view_file", 2, parameters={}))
    assert [event["type"] for event in told] == ["item.started"]
    # the turn's end says nothing of it: what becomes of it is the runner's to write down
    assert translate(result(response="", usage={})) == [
        {"type": "turn.completed", "usage": {"input_tokens": None, "output_tokens": None}}]


def test_the_command_is_read_where_the_cli_was_measured_to_put_it():
    translate = translator(reads=False)

    def ran(index, **parameters):
        (item,) = items(translate(tool("DONE", "run_command", index, parameters=parameters,
                                       output="hi\n")))
        return item

    assert ran(1, CommandLine="python hello.py") == {
        "type": "command_execution", "id": "agy_1", "command": "python hello.py",
        "aggregated_output": "hi\n", "exit_code": None, "status": "completed"}
    assert ran(2, command="dir")["command"] == "dir"
    assert ran(3, CommandLine="dir /b", command="other")["command"] == "dir /b"
    # neither: its parameters are shown whole rather than a guess
    assert ran(4, line="dir")["command"] == '{"line": "dir"}'


def test_reading_only_a_step_is_refused_only_when_the_cli_says_it_refused():
    translate = translator()
    translate(tool("ACTIVE", "run_command", 2, parameters={"CommandLine": "pytest"}))
    (refused,) = items(translate(tool("ERROR", "run_command", 2,
                                      parameters={"CommandLine": "pytest"},
                                      error={"type": "TOOL_ERROR", "message": REFUSAL})))
    assert (refused["type"], refused["tool"], refused["status"]) == (
        "mcp_tool_call", "run_command", "denied")
    assert refused["error"] == {"message": REFUSAL}
    assert refused["arguments"] == {"CommandLine": "pytest"}
    (write,) = items(translate(tool(
        "ERROR", "write_to_file", 3, parameters={"TargetFile": "a.txt"},
        error={"message": "user denied permission to write"})))
    assert (write["type"], write["status"]) == ("mcp_tool_call", "denied")
    # a tool that only looks and fails is a failure, whatever it says
    (failed,) = items(translate(tool("ERROR", "view_file", 4, parameters={},
                                     error={"message": "permission denied: hello.py"})))
    assert (failed["status"], failed["error"]) == (
        "failed", {"message": "permission denied: hello.py"})


def test_reading_only_another_error_on_a_write_is_not_known_to_have_done_nothing():
    translate = translator()
    for index, name in enumerate(("write_to_file", "sed_file", "notebook_edit")):
        failed, look = items(translate(tool(
            "ERROR", name, index, parameters={"TargetFile": "a.txt"},
            error={"message": "Permission denied: a.txt is read-only"})))
        # not a refusal: it may have run. Failed, and the project is looked at.
        assert (failed["type"], failed["tool"], failed["status"]) == (
            "mcp_tool_call", name, "failed")
        assert failed["error"] == {
            "message": f"{UNSURE}: Permission denied: a.txt is read-only"}
        assert failed["arguments"] == {"TargetFile": "a.txt"}
        # (as a step that failed: what it names is looked for, and not said to have changed)
        assert look == {"type": "file_change", "id": failed["id"], "status": "failed",
                        "changes": [{"path": "a.txt"}]}
    failed, _look = items(translate(tool("ERROR", "write_to_file", 9, parameters={})))
    assert failed["error"] == {"message": UNSURE}


def test_reading_only_another_error_on_a_command_waits_for_what_the_result_says():
    def errored(translate, index, why="exit status 1"):
        return translate(tool("ERROR", "run_command", index,
                              parameters={"CommandLine": "pytest"}, error={"message": why}))

    # the result names a command among what it denied: that one was refused
    translate = translator()
    (held,) = errored(translate, 2)
    assert held["type"] == "item.started"  # not settled yet
    failed, look = held["item"]["pending"]  # what it is, should no result ever come
    assert (failed["type"], failed["status"], failed["error"]) == (
        "mcp_tool_call", "failed", {"message": f"{UNSURE}: exit status 1"})
    assert look == {"type": "file_change", "id": "agy_2", "status": "failed", "changes": []}
    told = translate(result(response="", usage={}, denied_actions=[
        {"action": "command", "display_name": "RunCommand"}]))
    refused, note = items(told)
    assert (refused["id"], refused["type"], refused["status"]) == (
        "agy_2", "mcp_tool_call", "denied")
    assert note["text"].endswith(  # (B-317: it said no word after it)
        "after it was refused `run_command: refused by agy`.")
    assert told[-1]["type"] == "turn.completed"

    # the result names none: it ended in an error, and may have run
    translate = translator()
    errored(translate, 2)
    told = translate(result(response="", usage={}))
    assert items(told) == [failed, look] and told[-1]["type"] == "turn.completed"

    # one denied action, already accounted for by the step that said so itself
    translate = translator()
    errored(translate, 2, REFUSAL)
    errored(translate, 3)
    told = translate(result(response="", usage={}, denied_actions=[
        {"action": "command", "display_name": "RunCommand"}]))
    assert [(item.get("id"), item["type"], item.get("status")) for item in items(told)] == [
        ("agy_3", "mcp_tool_call", "failed"), ("agy_3", "file_change", "failed"),
        (None, "agent_message", None)]

    # a result that is an error settles them too, before it fails the turn
    translate = translator()
    errored(translate, 2)
    told = translate(nested("result", status="ERROR", error="quota exhausted"))
    assert items(told) == [failed, look]
    assert told[-1] == {"type": "error", "message": "quota exhausted"}


def test_reading_only_a_command_or_a_write_that_was_done_is_on_record_as_done():
    # The user's own agy settings can give leave for more than the flag does.
    translate = translator()
    # (a command once its result names nothing it denied: B-317, 1.4.x says DONE of a refusal)
    (held,) = translate(tool("DONE", "run_command", 2,
                             parameters={"CommandLine": "python hello.py"}, output="hi\n"))
    assert held["type"] == "item.started"
    (ran,) = items(translate(result(response="ran", usage={})))[:1]
    assert (ran["type"], ran["command"], ran["status"]) == (
        "command_execution", "python hello.py", "completed")
    translate = translator()
    wrote, look = items(translate(tool("DONE", "write_to_file", 3,
                                       parameters={"TargetFile": "a.txt"}, output="ok")))
    assert (wrote["type"], wrote["tool"], wrote["status"]) == (
        "mcp_tool_call", "write_to_file", "completed")
    assert look == {"type": "file_change", "id": "agy_3", "changes": [{"path": "a.txt"}]}


def test_reading_only_a_denied_action_settles_a_command_that_failed_before_one_said_done():
    # (B-317's held DONE command took the one denied action's count from an ERROR one.)
    translate = translator()
    translate(tool("DONE", "run_command", 2, parameters={"CommandLine": "dir"}, output="a.txt"))
    translate(tool("ERROR", "run_command", 3, parameters={"CommandLine": "rm x"},
                   error={"message": "exit status 1"}))
    told = items(translate(result(response="", usage={}, denied_actions=[
        {"action": "command", "display_name": "RunCommand"}])))
    assert [(item["id"], item["type"], item["status"]) for item in told[:2]] == [
        ("agy_3", "mcp_tool_call", "denied"), ("agy_2", "command_execution", "completed")]


def test_reading_only_a_done_commands_output_is_a_refusal_only_where_it_begins_with_one():
    translate = translator()
    printed = "log: user denied permission to x\n"
    translate(tool("DONE", "run_command", 2, parameters={"CommandLine": "type log.txt"},
                   output=printed))
    (ran,) = items(translate(result(response="It printed a log.", usage={})))[:1]
    assert (ran["type"], ran["status"], ran["aggregated_output"]) == (
        "command_execution", "completed", printed)


def test_with_leave_for_everything_an_error_is_never_put_down_as_a_refusal():
    translate = translator(reads=False)
    # a command that ran and printed "Permission denied" is a command that failed
    (ran,) = items(translate(tool(
        "ERROR", "run_command", 2, parameters={"CommandLine": "type secret.txt"},
        error={"message": "Permission denied"})))
    assert ran == {"type": "command_execution", "id": "agy_2", "command": "type secret.txt",
                   "aggregated_output": "Permission denied", "exit_code": None,
                   "status": "failed"}
    (worded,) = items(translate(tool("ERROR", "run_command", 3, parameters={},
                                     error={"message": REFUSAL})))
    assert (worded["type"], worded["status"]) == ("command_execution", "failed")
    failed, look = items(translate(tool("ERROR", "write_to_file", 4, parameters={},
                                        error={"message": "no permission to write"})))
    assert (failed["type"], failed["status"]) == ("mcp_tool_call", "failed")
    assert look["type"] == "file_change"


def test_a_write_that_was_done_is_its_own_record_and_a_look_at_the_project():
    translate = translator(reads=False)
    for index, name in enumerate(("write_to_file", "replace_file_content",
                                  "multi_replace_file_content", "sed_file", "notebook_edit")):
        given = {"TargetFile": "C:\\elsewhere\\notes.txt"}
        wrote, look = items(translate(tool("DONE", name, index, parameters=given, output="ok")))
        # the step with what it was given - a path outside the project is named there -
        assert wrote == {
            "type": "mcp_tool_call", "id": f"agy_{index}", "server": "agy", "tool": name,
            "arguments": given, "status": "completed", "error": None,
            "result": {"content": [{"type": "text", "text": "ok"}]}}
        # and which file changed is read off the project, with the path it named
        assert look == {"type": "file_change", "id": f"agy_{index}",
                        "changes": [{"path": "C:\\elsewhere\\notes.txt"}]}
    # a name never measured: a parameter called like a path, once - never what one holds
    # (a file's content can be a path: it was put down as a file that was written)
    elsewhere = str(Path.cwd() / "x.txt")
    _wrote, look = items(translate(tool("DONE", "sed_file", 9, parameters={
        "File": elsewhere, "OutputPath": elsewhere, "Filename": "y.txt", "N": 3,
        "CodeContent": "C:\\Windows\\System32\\drivers\\etc\\hosts", "Pattern": "//host/x",
        "Profile": elsewhere + ".not"}, output="ok")))
    assert look["changes"] == [{"path": elsewhere}, {"path": "y.txt"}]


def test_a_write_of_the_real_cli_names_its_full_path_for_the_look():
    """Measured natively (11 Oct 2026): write_to_file's "TargetFile" is a full path."""
    translate = translator(reads=False)
    told = [item for event in recorded("native_writes_and_runs.jsonl")
            for item in items(translate(event))]
    looks = [item for item in told if item["type"] == "file_change"]
    assert looks == [{"type": "file_change", "id": "agy_2",
                      "changes": [{"path": "C:\\proj\\hello.txt"}]}]
    # the command after it names no file
    (ran,) = [item for item in told if item["type"] == "command_execution"]
    assert ran["command"] == "python --version"


def test_an_error_result_is_a_failure_in_the_clis_own_words():
    assert translator()(nested("result", status="ERROR", error="quota exhausted")) == [
        {"type": "error", "message": "quota exhausted"}]
    assert translator()(nested("result", status="ERROR",
                               error={"message": "model not found"})) == [
        {"type": "error", "message": "model not found"}]
    # an ending nobody knows is not called a success
    (odd,) = translator()(nested("result", status="PAUSED"))
    assert odd["type"] == "error" and "PAUSED" in odd["message"]


def test_what_nobody_knows_is_passed_over():
    translate = translator()
    for event in ({"event": "heartbeat"}, {"no": "event"}, {"event": "step_update"},
                  nested("step_update", step_type="planning", state="ACTIVE"),
                  nested("step_update", step_type="tool", state="QUEUED", tool_name="view_file"),
                  nested("step_update", step_type="agent_response", state="ACTIVE",
                         text_delta=5)):
        assert translate(event) == []


# --- turns -----------------------------------------------------------------------------


@pytest.fixture
def agy_app(settings_env, tmp_path):
    opened = []
    record, plan = tmp_path / "record.json", tmp_path / "plan.json"

    def write_plan(script, **more):
        plan.write_text(json.dumps({"record": str(record), "script": script, **more}),
                        encoding="utf-8")

    def make(script, mode="reads", default_steps=(), timeout=30, asked="gemini-asked",
             provider=None, **more):
        write_plan(script, **more)
        cli = AgyClient(None, asked, timeout=timeout, reads=mode == "reads", launcher=FAKE,
                        env={"FAKE_AGY_PLAN": str(plan)})
        make.cli = cli
        default = ScriptedModel(
            default_steps if isinstance(default_steps, dict) else list(default_steps),
            model_id="big-model")
        app = create_app(load_settings(settings_env), model=default, clients={"agy": cli})
        client = TestClient(app, base_url="http://127.0.0.1:8790")
        client.__enter__()
        opened.append(client)
        made = client.post("/api/providers", json={
            "name": "agy", "kind": "agy_cli", "mode": mode, "default_model": asked,
            **(provider or {})})
        assert made.status_code == 201, made.text
        return client, made.json(), default

    make.rescript = write_plan
    make.record = lambda: json.loads(record.read_text(encoding="utf-8"))
    make.ran = record.exists
    yield make
    for client in opened:
        client.__exit__(None, None, None)


def start(client, project_dir, provider, mode="ask", content="what does it print?",
          lead_work="itself"):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    # (B-310: a Lead on agy that delegates is refused its own writes, as on Codex: "itself" here)
    client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": mode, "provider_id": provider["id"] if provider else None,
        "lead_work": lead_work},
        headers={"Origin": "http://127.0.0.1:8790"})  # a level is raised from the app's own page
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": content}).json()["run"]
    return cid, run["id"]


def test_a_reads_turn_is_on_record_as_the_clis_own_work(agy_app, wait_run, project_dir):
    client, provider, default = agy_app([
        {"say": "Let me look."},
        {"tool": "view_file", "parameters": {"AbsolutePath": "hello.py"},
         "output": "print('hi')"},
        {"other": True},
        {"say": "It prints hi."}], model="gemini-as-run")
    assert provider["mode"] == "reads"
    cid, run_id = start(client, project_dir, provider)  # at the "ask" level
    snap = wait_run(client, cid, run_id)

    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [m["content"] for m in snap["messages"] if m["role"] == "assistant" and m["content"]] == [
        "Let me look.\n", "It prints hi.\n"]  # as it came, the "\n" each answer ends with too
    (read,) = snap["tool_calls"]
    assert (read["name"], read["status"], read["origin"]) == ("agy__view_file", "succeeded", "cli")
    assert json.loads(read["arguments"]) == {"AbsolutePath": "hello.py"}
    assert read["result"] == "print('hi')"
    assert snap["commands"] == [] and snap["file_changes"] == []
    lead = snap["agents"][0]
    # the model it said it ran on, and the tokens it counted for the whole turn
    assert (lead["provider_name"], lead["model_id"], lead["model_from"]) == (
        "agy", "gemini-as-run", None)
    assert (lead["input_tokens"], lead["output_tokens"]) == (2100, 45)
    assert lead["provider_mode"] == "reads"
    assert len(default.calls) == 0

    seen = agy_app.record()
    # started as measured: -p= is one argument with nothing after the sign, and the last
    assert seen["argv"] == ["--model", "gemini-asked", "--input-format", "stream-json",
                            "--output-format", "stream-json", "-p="]
    assert Path(seen["cwd"]) == project_dir
    # the prompt is one JSON line on stdin, and nowhere on the command line
    assert seen["stdin"].endswith("\n") and seen["stdin"].count("\n") == 1
    sent = json.loads(seen["stdin"])
    assert set(sent) == {"event", "message"} and sent["event"] == "user"
    assert set(sent["message"]) == {"role", "content"} and sent["message"]["role"] == "user"
    prompt = sent["message"]["content"]
    assert "what does it print?" in prompt and "print?" not in json.dumps(seen["argv"])
    document = json.loads(prompt[prompt.index("\n\n{") + 2:])
    assert document["conversation"] == [{"role": "user", "content": "what does it print?"}]
    assert f'The project folder is "{project_dir}".' in prompt
    # it has none of KOLONİ's tools, and is not told of any
    told_of_kolonis(prompt)
    assert "refused" in prompt  # it is told that here it only reads


def test_without_a_model_none_is_named(agy_app, wait_run, project_dir):
    client, provider, _ = agy_app([{"say": "hello"}], asked=None)
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert agy_app.record()["argv"] == [
        "--input-format", "stream-json", "--output-format", "stream-json", "-p="]
    assert snap["agents"][0]["model_id"] == "auto"  # what the CLI said, not "agy default"


def test_a_step_the_cli_refuses_is_denied_and_nothing_is_run(agy_app, wait_run, project_dir):
    client, provider, _ = agy_app([
        {"tool": "run_command", "asks": True, "parameters": {"CommandLine": "python made.py"},
         "output": "ran", "touches": {"made.txt": "x"}},
        {"tool": "write_to_file", "asks": True, "parameters": {"TargetFile": "hello.py"},
         "touches": {"hello.py": "print('changed')\n"}},
        {"tool": "view_file", "parameters": {}, "error": "no such file"},
        {"say": "I could not run or change anything here."}])
    cid, run_id = start(client, project_dir, provider, mode="full_auto")  # even at Full auto
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [(t["name"], t["status"], t["origin"]) for t in snap["tool_calls"]] == [
        ("agy__run_command", "denied", "cli"), ("agy__write_to_file", "denied", "cli"),
        ("agy__view_file", "failed", "cli")]
    refused = snap["tool_calls"][0]
    assert json.loads(refused["arguments"]) == {"CommandLine": "python made.py"}
    assert refused["result"].startswith(
        'refused by the CLI: permission check failed for command "python made.py": '
        "user denied permission to run command")
    assert "no such file" in snap["tool_calls"][2]["result"]
    # nothing ran and nothing changed, and the records say no different
    assert snap["commands"] == [] and snap["file_changes"] == []
    assert not (project_dir / "made.txt").exists()
    assert (project_dir / "hello.py").read_bytes() == b"print('hi')\n"
    assert SKIP not in agy_app.record()["argv"]


def test_reads_works_for_a_role_that_only_reads_at_any_level(agy_app, wait_run, project_dir):
    client, provider, default = agy_app(
        [{"tool": "view_file", "parameters": {}, "output": "print('hi')"},
         {"say": "Nothing wrong with it."}],
        default_steps=[spawn("Reviewer", "Review hello.py"), text("The reviewer is content.")])
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={"provider_id": provider["id"]})
    for level in ("ask", "auto_edit", "full_auto"):
        default.steps = [spawn("Reviewer", "Review hello.py"), text("The reviewer is content.")]
        cid, run_id = start(client, project_dir, None, mode=level)
        snap = wait_run(client, cid, run_id)
        assert snap["runs"][0]["status"] == "completed", (level, snap["runs"][0]["error"])
        lead, reviewer = snap["agents"]
        assert (reviewer["provider_name"], reviewer["status"], reviewer["report"]) == (
            "agy", "completed", "Nothing wrong with it."), level
        assert (lead["provider_mode"], reviewer["provider_mode"]) == (None, "reads")
    prompt = json.loads(agy_app.record()["stdin"])["message"]["content"]
    assert "Review hello.py" in prompt
    told_of_kolonis(prompt)


def test_the_level_can_be_lowered_while_a_reads_agent_works(agy_app, wait_run, project_dir):
    client, provider, _ = agy_app([{"say": "Looking."}, {"hang": True}])
    cid, run_id = start(client, project_dir, provider, mode="full_auto")
    for _ in range(300):
        if any(m["content"] for m in client.get(f"/api/conversations/{cid}").json()["messages"]
               if m["role"] == "assistant"):
            break
        time.sleep(0.02)
    # it changes nothing, so nothing depends on the level staying where it is
    lowered = client.patch(f"/api/conversations/{cid}", json={"permission_mode": "ask"})
    assert lowered.status_code == 200, lowered.text
    client.post(f"/api/runs/{run_id}/cancel")
    wait_run(client, cid, run_id)


def test_native_asks_first_so_it_runs_at_every_level_and_for_a_role_that_only_reads(
    agy_app, wait_run, project_dir
):
    # (slice 89e: its hook asks KOLONİ before each tool - tests/test_agy_hook_scenarios.py)
    client, provider, default = agy_app([{"say": "hello"}], mode="native")
    assert provider["mode"] == "native"
    for level in ("ask", "auto_edit"):
        cid, run_id = start(client, project_dir, provider, mode=level)
        run = wait_run(client, cid, run_id)["runs"][0]
        assert run["status"] == "completed", (level, run["error"])
    # a role that may not write: its write is refused through the hook, whatever the level
    agy_app.rescript([
        {"tool": "write_to_file", "parameters": {"TargetFile": "hello.py", "CodeContent": "x"},
         "touches": {"hello.py": "x"}}, {"say": "I could not change it."}])
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={"provider_id": provider["id"]})
    default.steps = [spawn("Reviewer", "Review hello.py"), text("It could not.")]
    cid, run_id = start(client, project_dir, None, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    reviewer = snap["agents"][1]
    assert reviewer["status"] == "completed", reviewer["error"]
    assert (project_dir / "hello.py").read_bytes() == b"print('hi')\n"
    assert ("edit_file", "denied") in [(t["name"], t["status"]) for t in snap["tool_calls"]]


def test_native_is_started_with_the_flag_and_what_it_did_is_on_record(
    agy_app, wait_run, project_dir
):
    client, provider, _ = agy_app([
        {"say": "I will fix it."},
        {"tool": "write_to_file", "asks": True, "parameters": {"TargetFile": "hello.py"},
         "touches": {"hello.py": "print('hello')\n"}, "output": "written"},
        {"tool": "run_command", "asks": True, "parameters": {"CommandLine": "python hello.py"},
         "output": "hello\n"},
        {"say": "Fixed and checked."}], mode="native")
    cid, run_id = start(client, project_dir, provider, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    # (natively a write's record is its change: one asked about is the card's)
    assert [(t["name"], t["status"], t["origin"]) for t in snap["tool_calls"]] == [
        ("edit_file", "succeeded", "cli"), ("run_command", "succeeded", "cli")]
    (change,) = snap["file_changes"]
    assert (change["path"], change["status"], change["origin"]) == ("hello.py", "applied", "cli")
    assert "+print('hello')" in change["diff"]
    (ran,) = snap["commands"]
    # it reports no exit code and KOLONİ does not know where its shell stood
    assert (ran["command"], ran["status"], ran["exit_code"], ran["cwd"], ran["origin"]) == (
        "python hello.py", "exited", None, None, "cli")
    assert ran["output"] == "hello\n"
    assert snap["agents"][0]["provider_mode"] == "native"
    argv = agy_app.record()["argv"]
    assert argv == ["--model", "gemini-asked", "--input-format", "stream-json",
                    "--output-format", "stream-json", SKIP, "-p="]
    prompt = json.loads(agy_app.record()["stdin"])["message"]["content"]
    told_of_kolonis(prompt)


def test_an_agent_can_pick_native_agy_at_ask_now_that_it_asks_first(
    agy_app, wait_run, project_dir
):
    pick = spawn("Coder", "Change it")
    pick = type(pick)(pick.content, [type(pick.tool_calls[0])(
        "s1", "spawn_agent", json.dumps({"role": "Coder", "task": "Change it",
                                         "provider": "agy", "why": "the user asked for it"}))],
        5, 2)
    client, provider, default = agy_app(
        [{"say": "hello"}], mode="native", default_steps=[pick, text("It is done.")],
        provider={"for_agents": True})
    cid, run_id = start(client, project_dir, None, mode="ask")
    # (the user approves a model the agent chose; native agy no longer needs Full auto for it)
    proposed = wait_status(client, cid, "waiting_approval")["agents"][1]
    assert (proposed["provider_name"], proposed["status"]) == ("agy", "proposed")
    assert client.post(f"/api/agents/{proposed['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert snap["agents"][1]["status"] == "completed" and agy_app.ran()


def test_the_users_rules_and_the_memory_core_reach_agy(agy_app, wait_run, project_dir):
    client, provider, _ = agy_app([{"say": "Understood."}])
    client.headers["Origin"] = "http://127.0.0.1:8790"
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    fact = client.post(f"/api/projects/{pid}/memory",
                       json={"text": "the port is 8790", "about": "port"}).json()
    assert client.put(f"/api/projects/{pid}/rules",
                      json={"rules": "Sign every commit."}).status_code == 200
    cid, run_id = start(client, project_dir, provider, content="which port does it use?")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert snap["agents"][0]["facts_given"] == [fact["id"]]
    prompt = json.loads(agy_app.record()["stdin"])["message"]["content"]
    instructions = json.loads(prompt[prompt.index("\n\n{") + 2:])["instructions"]
    assert "standing rules for this project" in instructions
    assert "Sign every commit." in instructions
    assert '- "the port is 8790" (written by the user on ' in instructions
    told_of_kolonis(prompt)


def test_agy_is_told_to_look_up_with_recall_now_that_it_has_it(agy_app, wait_run, project_dir):
    """Work that names no subject of the core: an agent is told there is a memory to look in
    with recall. B-310: agy has KOLONİ's recall over its bridge, so it is told too."""
    client, provider, _ = agy_app([{"say": "It prints hi."}])
    client.headers["Origin"] = "http://127.0.0.1:8790"
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    client.post(f"/api/projects/{pid}/memory", json={"text": "the port is 8790", "about": "port"})
    cid, run_id = start(client, project_dir, provider)  # "what does it print?"
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert snap["agents"][0]["facts_given"] == []
    prompt = json.loads(agy_app.record()["stdin"])["message"]["content"]
    assert "8790" not in prompt and "1 approved note; recall(query)" in prompt
    told_of_kolonis(prompt)


def test_in_a_discussion_native_agy_speaks_reading_only(agy_app, wait_run, project_dir):
    from tests.test_spawn import call, step

    client, provider, default = agy_app(
        [{"say": "I would keep hi."}], mode="native", default_steps={"Lead": [
            spawn("Coder", "Look at the greeting"),
            step(call("discuss", {"topic": "hi or hello?", "with": ["Coder"], "rounds": 1}, "d")),
            text("hello."), text("done")]})
    client.patch(f"/api/roles/{role_id(client, 'Coder')}", json={"provider_id": provider["id"]})
    cid, run_id = start(client, project_dir, None, mode="full_auto")
    snap = wait_run(client, cid, run_id, timeout=40)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [(p["content"], p["kind"]) for p in snap["discussion_posts"]] == [
        ("I would keep hi.", "said"), ("hello.", "said")]
    # its work was started with the flag; its speech, the last run, without it
    seen = agy_app.record()
    assert SKIP not in seen["argv"] and seen["argv"][-1] == "-p="
    prompt = json.loads(seen["stdin"])["message"]["content"]
    assert "You are in a discussion with Lead" in prompt and "no command can run" in prompt
    told_of_kolonis(prompt)
    coder = snap["agents"][1]
    assert (coder["status"], coder["report"]) == ("completed", "I would keep hi.")


def test_an_agent_can_pick_reads_agy_at_any_level(agy_app, wait_run, project_dir):
    pick = spawn("Reviewer", "Review hello.py")
    pick = type(pick)(pick.content, [type(pick.tool_calls[0])(
        "s1", "spawn_agent", json.dumps({"role": "Reviewer", "task": "Review hello.py",
                                         "provider": "agy", "why": "It reads well."}))], 5, 2)
    client, provider, default = agy_app(
        [{"say": "It is fine."}], default_steps=[pick, text("Good.")],
        provider={"for_agents": True})
    cid, run_id = start(client, project_dir, None, mode="ask")
    for _ in range(300):
        snap = client.get(f"/api/conversations/{cid}").json()
        if len(snap["agents"]) == 2 and snap["agents"][1]["status"] == "proposed":
            break
        time.sleep(0.02)
    # a model the agent picked is the user's to allow, as on any provider
    client.post(f"/api/agents/{snap['agents'][1]['id']}/approve")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert (snap["agents"][1]["status"], snap["agents"][1]["report"]) == (
        "completed", "It is fine.")
    # the guide said how it runs
    described = json.dumps(default.tool_args[0])
    assert "reads with its own tools; started without leave to write or run" in described


def test_its_parent_can_carry_on_with_it_after_it_finished(agy_app, wait_run, project_dir):
    client, provider, default = agy_app(
        [{"say": "It prints hi."}],
        default_steps=[spawn("Reviewer", "Read hello.py"),
                       message("reviewer", "And what does check.py print?"), text("Done.")])
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={"provider_id": provider["id"]})
    cid, run_id = start(client, project_dir, None)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [m["kind"] for m in snap["channel_messages"]] == ["task", "report", "message", "reply"]
    assert snap["agents"][1]["status"] == "completed"
    prompt = json.loads(agy_app.record()["stdin"])["message"]["content"]
    assert "And what does check.py print?" in prompt and "the agent you work for" in prompt
    told_of_kolonis(prompt)


def test_nobody_else_can_message_an_agy_agent(agy_app, wait_run, project_dir):
    client, provider, default = agy_app(
        [{"say": "It prints hi."}],
        default_steps=[
            spawn("Reviewer", "Read hello.py"), spawn("Tester", "Ask the reviewer", "s2"),
            message("reviewer", "What did you find?"), text("I could not ask."),
            text("Done.")])
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={"provider_id": provider["id"]})
    cid, run_id = start(client, project_dir, None, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    asked = next(t for t in snap["tool_calls"] if t["name"] == "message_agent")
    assert asked["status"] == "failed"
    # in words that fit an agent that only reads: nothing about holding it to reading
    assert "Reviewer cannot be messaged by you now: it works with tools of its own, so only " \
        "the agent it works for can message it" in asked["result"]
    assert "held to reading" not in asked["result"]


# --- B-310: KOLONİ's tools over its bridge, allowed one by one ---------------------------


def on_local(client, role):
    """The role's agents on the scripted default model, not on agy."""
    local = next(p for p in client.get("/api/providers").json() if p["kind"] != "agy_cli")
    assert client.patch(f"/api/roles/{role_id(client, role)}",
                        json={"provider_id": local["id"]}).status_code == 200


SPAWN = {"koloni": "spawn_agent", "args": {"role": "Reviewer", "task": "Read hello.py"}}


@pytest.mark.parametrize("mode", ["reads", "native"])
def test_an_agy_lead_opens_a_sub_agent_over_kolonis_bridge(agy_app, wait_run, project_dir, mode):
    client, provider, default = agy_app(
        [SPAWN, {"say": "The reviewer found nothing wrong."}], mode=mode,
        default_steps={"Reviewer": [text("Nothing wrong with hello.py.")]})
    on_local(client, "Reviewer")
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    lead, reviewer = snap["agents"]
    assert (reviewer["name"], reviewer["status"], reviewer["report"]) == (
        "Reviewer", "completed", "Nothing wrong with hello.py.")
    # its call on record once, as KOLONİ's: not again as a step of agy's own
    assert [(t["name"], t["status"]) for t in snap["tool_calls"]] == [("spawn_agent", "succeeded")]
    seen = agy_app.record()
    assert "Nothing wrong with hello.py." in json.dumps(seen["results"])
    if mode == "native":  # its hook let KOLONİ's own tool through, with no card of its own
        (ran,) = seen["hooks"]
        assert ran["in"]["toolCall"]["name"] == "mcp__koloni__spawn_agent"
        assert json.loads(ran["out"])["decision"] == "allow"


@pytest.mark.parametrize("mode", ["reads", "native"])
def test_a_second_connection_with_its_bridges_key_stops_the_run(
    agy_app, wait_run, project_dir, mode
):
    client, provider, _ = agy_app([{"say": "never"}], mode=mode, second_bridge=True)
    cid, run_id = start(client, project_dir, provider)
    run = wait_run(client, cid, run_id)["runs"][0]
    assert run["status"] == "failed" and "a second connection" in run["error"], run


def test_a_native_agy_lead_that_delegates_is_refused_its_own_write(agy_app, wait_run, project_dir):
    # (R101: it wrote unrefused while it could open no sub-agent; now it can, as on Codex)
    client, provider, _ = agy_app([
        {"tool": "write_to_file", "parameters": {"TargetFile": "hello.py", "CodeContent": "x"},
         "touches": {"hello.py": "x"}}, {"say": "I will hand it on."}], mode="native")
    cid, run_id = start(client, project_dir, provider, mode="full_auto", lead_work="delegates")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [(t["name"], t["status"]) for t in snap["tool_calls"]] == [("edit_file", "denied")]
    assert (project_dir / "hello.py").read_bytes() == b"print('hi')\n"


def test_its_home_names_kolonis_bridge_and_allows_each_offered_tool_alone(
    agy_app, wait_run, project_dir
):
    client, provider, _ = agy_app([
        {"koloni": "write_file", "args": {"path": "made.txt", "content": "x"}},
        {"say": "I could not write it."}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    seen = agy_app.record()
    home = Path(seen["env"]["USERPROFILE"])
    assert home.name.startswith("agy-") and not home.exists()  # KOLONİ's, gone after the run
    ((name, server),) = json.loads(seen["config"]["mcp_config.json"])["mcpServers"].items()
    assert name == "koloni" and server["command"] == sys.executable
    bridge, config = server["args"]
    assert Path(bridge).name == "mcp_bridge.py"
    assert Path(config) == home / ".gemini" / "config" / "bridge.json"
    assert set(json.loads(seen["config"]["bridge.json"])) == {"port", "key"}
    # B-317: told that no command runs here, and where its tools' definitions are, to read
    # them with its own file tool rather than list them with a command
    prompt = json.loads(seen["stdin"])["message"]["content"]
    assert str(home / ".gemini" / "antigravity-cli" / "mcp" / "koloni") in prompt
    assert "no command can run" in prompt and "do not try it another way" not in prompt
    # one rule for each tool it is offered, by name: no wildcard, nothing else
    offered = seen["tools"]
    assert {"spawn_agent", "message_agent", "ask_user"} <= set(offered)
    assert seen["allowed"] == sorted(f"mcp(koloni/{tool})" for tool in offered)
    # a Lead reading only is offered none of KOLONİ's file tools: no rule, and agy refused it
    assert "write_file" not in offered and "mcp(koloni/write_file)" not in seen["allowed"]
    assert not (project_dir / "made.txt").exists() and seen["results"] == []
    (refused,) = snap["tool_calls"]  # (on record as agy's own try, as a tool KOLONİ never ran)
    assert refused["name"] == "agy__mcp__koloni__write_file" and refused["status"] in (
        "denied", "failed"), refused


def test_an_agy_older_than_the_bridge_is_offered_none_and_says_so(agy_app, wait_run, project_dir):
    client, provider, _ = agy_app([{"say": "I did it myself."}], version="1.4.8")
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    seen = agy_app.record()
    assert "mcp_config.json" not in seen["config"] and seen["allowed"] == []
    prompt = json.loads(seen["stdin"])["message"]["content"]
    assert "nothing here to reach" in prompt and '"koloni" MCP server' not in prompt
    (said,) = snap["tool_calls"]
    assert said["status"] == "denied" and "agy cannot open sub-agents or write with KOLONİ's " \
        "tools here" in said["result"]
    (shown,) = [p for p in client.get("/api/providers").json() if p["kind"] == "agy_cli"]
    assert shown["version_note"].startswith("agy 1.4.8 cannot open sub-agents here")


def test_a_kolonis_tool_agy_refused_is_on_record_not_dropped(agy_app, wait_run, project_dir):
    # (Its rule not taken - a shape agy reads otherwise: the user sees the refusal.)
    client, provider, _ = agy_app([SPAWN, {"say": "I could not."}], ignore_allowed=True)
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (refused,) = snap["tool_calls"]
    assert refused["name"] == "agy__mcp__koloni__spawn_agent" and refused["status"] in (
        "denied", "failed") and "permission check failed" in refused["result"], refused
    assert len(snap["agents"]) == 1


@pytest.fixture
def short_bridge_wait(monkeypatch):
    import app.model_agy

    monkeypatch.setattr(app.model_agy, "BRIDGE_SECONDS", 0.5)


def test_a_native_lead_whose_bridge_never_comes_runs_the_old_way_and_writes_itself(
    agy_app, wait_run, project_dir, short_bridge_wait
):
    # (Its config not taken, say: the default Lead that hands code on could neither hand it on
    # nor write. It is given its task only once the bridge is in, or told it has none.)
    from app.model_agy import BRIDGE_NOT_STARTED

    client, provider, _ = agy_app([
        {"tool": "write_to_file", "parameters": {"TargetFile": "hello.py", "CodeContent": "x"},
         "touches": {"hello.py": "x"}}, {"say": "Changed it myself."}],
        mode="native", no_bridge=True)
    cid, run_id = start(client, project_dir, provider, mode="full_auto", lead_work="delegates")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [(t["name"], t["status"], t["result"]) for t in snap["tool_calls"]][0] == (
        "koloni_tools", "failed", BRIDGE_NOT_STARTED)
    assert ("edit_file", "succeeded") in [(t["name"], t["status"]) for t in snap["tool_calls"]]
    assert (project_dir / "hello.py").read_bytes() == b"x"
    prompt = json.loads(agy_app.record()["stdin"])["message"]["content"]
    assert "nothing here to reach" in prompt and '"koloni" MCP server' not in prompt


def test_a_reading_agy_whose_bridge_never_comes_says_so(
    agy_app, wait_run, project_dir, short_bridge_wait
):
    client, provider, _ = agy_app([SPAWN, {"say": "I could not."}], no_bridge=True)
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    names = [(t["name"], t["status"]) for t in snap["tool_calls"]]
    assert names[0] == ("koloni_tools", "failed") and len(snap["agents"]) == 1
    # its try, refused by agy, is on record as its own: nothing of KOLONİ's ran
    assert ("agy__mcp__koloni__spawn_agent", "failed") in names or (
        "agy__mcp__koloni__spawn_agent", "denied") in names


@pytest.mark.parametrize("mode", ["reads", "native"])
def test_kolonis_tool_through_agys_wrapper_is_judged_as_when_called_directly(
    agy_app, wait_run, project_dir, mode
):
    # B-318: 1.4.x calls it through its call_mcp_tool - at Full auto, no card and one record
    client, provider, default = agy_app(
        [{**SPAWN, "wrapped": True}, {"say": "The reviewer found nothing wrong."}], mode=mode,
        default_steps={"Reviewer": [text("Nothing wrong with hello.py.")]})
    on_local(client, "Reviewer")
    cid, run_id = start(client, project_dir, provider, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert snap["agents"][1]["report"] == "Nothing wrong with hello.py."
    assert [(t["name"], t["status"]) for t in snap["tool_calls"]] == [("spawn_agent", "succeeded")]
    if mode == "native":
        (ran,) = agy_app.record()["hooks"]
        assert ran["in"]["toolCall"]["name"] == "call_mcp_tool"
        assert json.loads(ran["out"])["decision"] == "allow"


def test_reading_only_agy_reads_its_own_definition_of_a_kolonis_tool_with_its_own_tool(
    agy_app, wait_run, project_dir
):
    # B-317: it looked for them with a command, refused reading only; its own read is not
    client, provider, _ = agy_app([{"tool": "view_file", "parameters": {
        "AbsolutePath": "{home}/.gemini/antigravity-cli/mcp/koloni/spawn_agent.json"}},
        {"say": "Read it."}])
    cid, run_id = start(client, project_dir, provider, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (read,) = snap["tool_calls"]
    assert (read["name"], read["status"]) == ("agy__view_file", "succeeded"), read


def test_a_read_only_product_owner_on_native_agy_reads_the_backlog_through_the_wrapper(
    agy_app, wait_run, project_dir
):
    # B-318: it was refused as "may only use tools that read"
    client, provider, default = agy_app(
        [{"koloni": "read_backlog", "args": {}, "wrapped": True}, {"say": "The list is empty."}],
        mode="native", default_steps=[spawn("Product owner", "plan the work"), text("done")])
    client.patch(f"/api/roles/{role_id(client, 'Product owner')}",
                 json={"provider_id": provider["id"]})
    cid, run_id = start(client, project_dir, None, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    owner = snap["agents"][1]
    assert owner["status"] == "completed", owner["error"]
    assert ("read_backlog", "succeeded") in [(t["name"], t["status"]) for t in snap["tool_calls"]]
    assert not [t for t in snap["tool_calls"] if "may only" in (t["result"] or "")]
    assert json.loads(agy_app.record()["hooks"][0]["out"])["decision"] == "allow"


@pytest.mark.parametrize("refusal", [None, "Commands are not allowed in this mode."])
def test_reading_only_a_command_agy_says_is_done_but_refused_is_denied_and_said(
    agy_app, wait_run, project_dir, refusal
):
    # B-317 (R110): on record as "succeeded, no exit code", the empty answer unexplained. Its
    # refusal in the measured words, or else only in the result's denied_actions.
    client, provider, _ = agy_app([{"tool": "run_command", "asks": True, "refused_done": True,
                                    "parameters": {"CommandLine": "Get-ChildItem mcp"},
                                    **({"refusal": refusal} if refusal else {})}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [(t["name"], t["status"]) for t in snap["tool_calls"]] == [
        ("agy__run_command", "denied")]
    assert snap["commands"] == []
    (said,) = [m["content"] for m in snap["messages"] if m["role"] == "assistant" and m["content"]]
    assert said.startswith("KOLONİ: agy ended its turn without an answer"), said


def test_a_turn_that_ends_without_a_word_after_a_refusal_says_what_was_refused(
    agy_app, wait_run, project_dir
):
    # B-317: its command refused reading only, it ended with an empty answer, unexplained
    from app.model_agy import _Hooked

    client, provider, _ = agy_app([{"tool": "run_command", "asks": True,
                                    "parameters": {"CommandLine": "dir mcp"}}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (said,) = [m["content"] for m in snap["messages"] if m["role"] == "assistant" and m["content"]]
    assert said.startswith("KOLONİ: agy ended its turn without an answer") and (
        "`run_command: refused by agy`" in said) and "dir mcp" not in said, said
    # natively, what KOLONİ's hook refused is said so
    hooked = _Hooked()
    hooked.refused.append("run_command: the Reviewer role may not run commands")
    hooked.refused.append("edit_file: rejected: the user declined `a.py`")
    told = AgyClient(None, "m", reads=False)._translator(hooked)(result(response=""))
    assert items(told)[0]["text"].endswith(  # (a backtick in a reason does not end the quote)
        "`run_command: the Reviewer role may not run commands`; "
        "`edit_file: rejected: the user declined 'a.py'`.")
    # one that answered, or was refused nothing, is not added to
    assert items(translator()(result(response="Done.\n")))[0]["text"] == "Done.\n"
    assert items(translator()(result(response=""))) == []


@pytest.mark.parametrize("wrapped", [False, True])
def test_a_kolonis_call_its_bridge_never_ran_stops_the_run(agy_app, wait_run, project_dir,
                                                           wrapped):
    # (Another server named "koloni" - a project's, the user's - answered it, past KOLONİ.)
    client, provider, _ = agy_app([{**SPAWN, "wrapped": wrapped}, {"say": "done"}],
                                  foreign_koloni=True)
    cid, run_id = start(client, project_dir, provider)
    run = wait_run(client, cid, run_id)["runs"][0]
    assert run["status"] == "failed" and "KOLONİ's server never ran" in run["error"], run
    assert run["error"].startswith("agy reported a call of KOLONİ's mcp__koloni__spawn_agent")


def test_a_name_is_kolonis_only_by_its_two_prefixes_and_an_offered_tool():
    from app.model_agy import kolonis

    offered = frozenset({"spawn_agent", "fake__echo"})
    assert kolonis("mcp__koloni__spawn_agent", offered) and kolonis("koloni/spawn_agent", offered)
    assert kolonis("mcp__koloni__fake__echo", offered)  # (a server's tool, by its bridge name)
    for name in ("spawn_agent", "mcp_koloni_spawn_agent", "koloni_spawn_agent",
                 "koloni__spawn_agent", "mcp__koloni__echo", "mcp__koloni__fake",
                 "mcp__koloni__write_file", "mcp__other__spawn_agent", "xkoloni/spawn_agent"):
        assert not kolonis(name, offered), name


def test_stop_ends_the_cli(agy_app, wait_run, project_dir):
    client, provider, _ = agy_app([{"say": "Looking."}, {"hang": True}])
    cid, run_id = start(client, project_dir, provider)
    for _ in range(300):
        if any(m["content"] for m in client.get(f"/api/conversations/{cid}").json()["messages"]
               if m["role"] == "assistant"):
            break
        time.sleep(0.02)
    pid = agy_app.record()["pid"]
    assert alive(pid)
    client.post(f"/api/runs/{run_id}/cancel")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "cancelled"
    assert [m["content"] for m in snap["messages"] if m["role"] == "assistant"] == ["Looking.\n"]
    assert gone(pid)


def test_an_error_result_fails_the_turn_in_the_clis_words(agy_app, wait_run, project_dir):
    client, provider, _ = agy_app([
        {"tool": "view_file", "parameters": {}, "output": "x"}, {"error": "quota exhausted"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    run = snap["runs"][0]
    assert run["status"] == "failed" and run["error"] == "agy reported an error: quota exhausted"
    assert snap["tool_calls"][0]["status"] == "succeeded"  # what it did before is on record


def test_a_crash_fails_the_turn_with_what_it_wrote_last(agy_app, wait_run, project_dir):
    client, provider, _ = agy_app([{"exit": 3, "stderr": "fatal: not signed in"}])
    cid, run_id = start(client, project_dir, provider)
    run = wait_run(client, cid, run_id)["runs"][0]
    assert run["status"] == "failed"
    assert run["error"] == "agy exited with code 3: fatal: not signed in"


def test_an_answer_that_comes_only_with_the_result_is_kept(agy_app, wait_run, project_dir):
    client, provider, _ = agy_app([{"say": "It prints hi."}], silent=True)
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [m["content"] for m in snap["messages"] if m["role"] == "assistant"] == [
        "It prints hi.\n"]  # the result's response, as it came


# --- the two streams kept from the real CLI, as whole turns -------------------------------


def test_the_real_stream_of_a_file_read_as_a_turn(agy_app, wait_run, project_dir):
    client, provider, default = agy_app([], replay=str(STREAMS / "reads_a_file.jsonl"))
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (read,) = snap["tool_calls"]
    assert (read["name"], read["status"], read["origin"]) == ("agy__view_file", "succeeded", "cli")
    assert json.loads(read["arguments"]) == {"AbsolutePath": "C:\\proj\\hello.py"}
    assert read["result"] == "2 lines, 12 bytes"
    deltas = [event["step_update"]["text_delta"] for event in recorded("reads_a_file.jsonl")
              if event["event"] == "step_update" and "text_delta" in event["step_update"]]
    # what it said in pieces, once: the ending is neither lost nor said again by the result
    said = [m["content"] for m in snap["messages"] if m["role"] == "assistant" and m["content"]]
    assert said == ["".join(deltas)] and said[0].endswith("hello.py) prints `hi`.\n")
    assert snap["commands"] == [] and snap["file_changes"] == []
    lead = snap["agents"][0]
    assert (lead["model_id"], lead["model_from"]) == ("gemini-3.8-flash-low", None)
    assert (lead["input_tokens"], lead["output_tokens"]) == (25911, 189)
    assert len(default.calls) == 0


def test_the_real_stream_of_a_refused_command_as_a_turn(agy_app, wait_run, project_dir):
    client, provider, _ = agy_app([], replay=str(STREAMS / "command_refused.jsonl"))
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (refused,) = snap["tool_calls"]
    assert (refused["name"], refused["status"], refused["origin"]) == (
        "agy__run_command", "denied", "cli")
    # the command it wanted is there to read
    assert json.loads(refused["arguments"]) == {"CommandLine": "Get-ChildItem -Path ."}
    assert refused["result"].startswith(
        'refused by the CLI: permission check failed for command "Get-ChildItem -Path .": '
        "user denied permission to run command")
    assert snap["commands"] == [] and snap["file_changes"] == []
    # it said nothing and its result held no answer: no word is put in its mouth - KOLONİ says
    # in its own name what was refused before that (B-317)
    (said,) = [m["content"] for m in snap["messages"] if m["role"] == "assistant" and m["content"]]
    assert said == ("KOLONİ: agy ended its turn without an answer, after it was refused "
                    "`run_command: refused by agy`.")
    lead = snap["agents"][0]
    assert (lead["status"], lead["report"], lead["error"]) == ("completed", None, None), lead
    assert (lead["input_tokens"], lead["output_tokens"]) == (11708, 125)


# --- what a step did, when the CLI does not say it plainly --------------------------------


def calls(snap):
    return [(t["name"], t["status"]) for t in snap["tool_calls"]]


def test_a_step_that_starts_and_is_never_heard_of_again_does_not_hold_the_limit_off(
    agy_app, wait_run, project_dir
):
    client, provider, _ = agy_app([
        {"tool": "view_file", "parameters": {"AbsolutePath": "hello.py"}, "never_ends": True},
        {"hang": True}])
    cid, run_id = start(client, project_dir, provider)
    # The limit, short, from the step on: agy's start and its bridge's (half the limit) are
    # not what is tested, and under load they took longer than a second.
    deadline = time.monotonic() + 30
    while not (agy_app.ran() and agy_app.record().get("hung")):  # (its step printed)
        assert time.monotonic() < deadline, "agy never got to its step"
        time.sleep(0.05)
    agy_app.cli._timeout = 1
    snap = wait_run(client, cid, run_id, timeout=20)
    run = snap["runs"][0]
    assert (run["status"], run["error"]) == ("failed", "agy sent nothing for 1 seconds")
    (left,) = snap["tool_calls"]
    assert (left["name"], left["status"], left["origin"]) == (
        "agy__view_file", "interrupted", "cli")
    assert json.loads(left["arguments"]) == {"AbsolutePath": "hello.py"}
    assert "not known whether it finished" in left["result"]


def test_a_step_never_said_to_end_is_not_on_record_as_done_when_the_turn_ends(
    agy_app, wait_run, project_dir
):
    client, provider, _ = agy_app([
        {"tool": "view_file", "parameters": {}, "never_ends": True}, {"say": "Done."}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert calls(snap) == [("agy__view_file", "interrupted")]
    assert "not known whether it finished" in snap["tool_calls"][0]["result"]


def test_reading_only_an_error_that_is_no_refusal_is_not_known_to_have_done_nothing(
    agy_app, wait_run, project_dir
):
    client, provider, _ = agy_app([
        {"tool": "write_to_file", "parameters": {"TargetFile": "hello.py"},
         "error": "disk full", "touches": {"hello.py": "print('half')\n"}},
        {"tool": "run_command", "parameters": {"CommandLine": "python made.py"},
         "error": "exit status 1"},
        {"say": "Something went wrong."}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    # failed, not refused - and the project was looked at: the write had got half-way
    assert calls(snap) == [
        ("agy__write_to_file", "failed"), ("edit_file", "succeeded"),
        ("agy__run_command", "failed")]
    wrote, _change, ran = snap["tool_calls"]
    assert wrote["result"] == "error: ended in an error; not known whether it ran: disk full"
    assert ran["result"] == "error: ended in an error; not known whether it ran: exit status 1"
    assert json.loads(ran["arguments"]) == {"CommandLine": "python made.py"}
    (change,) = snap["file_changes"]
    assert (change["path"], change["status"], change["origin"]) == ("hello.py", "applied", "cli")
    assert snap["commands"] == []  # not known to have run: no command is on record


def test_reading_only_a_command_the_result_names_as_denied_is_refused_whatever_its_error_said(
    agy_app, wait_run, project_dir
):
    client, provider, _ = agy_app([
        {"tool": "run_command", "asks": True, "parameters": {"CommandLine": "pytest"},
         "refusal": "this action was not carried out"},
        {"say": "I could not run it."}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert calls(snap) == [("agy__run_command", "denied")]
    assert snap["tool_calls"][0]["result"] == (
        "refused by the CLI: this action was not carried out")
    assert snap["commands"] == [] and snap["file_changes"] == []


def test_reading_only_a_command_whose_error_is_unread_and_no_result_comes_is_still_on_record(
    agy_app, wait_run, project_dir
):
    client, provider, _ = agy_app([
        {"tool": "run_command", "parameters": {"CommandLine": "pytest"}, "error": "killed"},
        {"exit": 3, "stderr": "fatal: lost the connection"}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "failed"
    assert calls(snap) == [("agy__run_command", "failed")]
    assert "not known whether it ran: killed" in snap["tool_calls"][0]["result"]


def test_reading_only_what_the_users_own_agy_settings_let_through_is_on_record_as_done(
    agy_app, wait_run, project_dir
):
    client, provider, _ = agy_app([
        {"tool": "run_command", "parameters": {"CommandLine": "python made.py"},
         "output": "made\n", "touches": {"made.txt": "x"}},
        {"tool": "write_to_file", "parameters": {"TargetFile": "hello.py"},
         "touches": {"hello.py": "print('changed')\n"}, "output": "ok"},
        {"say": "Done."}])
    cid, run_id = start(client, project_dir, provider)  # reading only, at the "ask" level
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert SKIP not in agy_app.record()["argv"]
    # (the stand-in does not wait to be watched: which look finds which file is not fixed,
    # and a file the command's look found is named again by the write)
    assert sorted(set(calls(snap))) == [
        ("agy__write_to_file", "succeeded"), ("edit_file", "succeeded"),
        ("run_command", "succeeded"), ("write_file", "succeeded")]
    (ran,) = snap["commands"]
    assert (ran["command"], ran["status"], ran["exit_code"], ran["origin"]) == (
        "python made.py", "exited", None, "cli")
    assert sorted(change["path"] for change in snap["file_changes"]) == ["hello.py", "made.txt"]
    assert snap["agents"][0]["provider_mode"] == "reads"


def test_natively_a_write_outside_the_project_is_asked_about_and_a_no_writes_nothing(
    agy_app, wait_run, project_dir, tmp_path
):
    outside = tmp_path / "elsewhere" / "notes.txt"
    outside.parent.mkdir()
    client, provider, _ = agy_app([
        {"tool": "write_to_file", "parameters": {"TargetFile": str(outside)},
         "touches": {str(outside): "kept elsewhere"}, "output": "written"},
        {"say": "Left it."}], mode="native")
    cid, run_id = start(client, project_dir, provider, mode="full_auto")
    snap = wait_status(client, cid, "waiting_approval")  # outside: asked, as for Claude Code
    (pending,) = [t for t in snap["tool_calls"] if t["status"] == "pending"]
    assert json.loads(pending["arguments"]) == {"path": str(outside)}
    client.post(f"/api/tool-calls/{pending['id']}/reject", headers={"Origin": ORIGIN})
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert not outside.exists() and snap["file_changes"] == []


def test_with_leave_for_everything_a_command_that_printed_permission_denied_ran_and_failed(
    agy_app, wait_run, project_dir
):
    client, provider, _ = agy_app([
        {"tool": "run_command", "parameters": {"CommandLine": "python made.py"},
         "error": "Permission denied: secret.txt", "touches": {"made.txt": "x"}},
        {"say": "It failed."}], mode="native")
    cid, run_id = start(client, project_dir, provider, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    # a command that ran: on record as one, failed, and the project looked at after it
    assert calls(snap) == [("run_command", "failed"), ("write_file", "succeeded")]
    (ran,) = snap["commands"]
    assert (ran["command"], ran["status"], ran["exit_code"], ran["output"]) == (
        "python made.py", "exited", None, "Permission denied: secret.txt")
    assert [change["path"] for change in snap["file_changes"]] == ["made.txt"]


def test_none_of_kolonis_own_settings_reach_the_cli(agy_app, wait_run, project_dir, monkeypatch):
    monkeypatch.setenv("KOLONI_MODEL_API_KEY", "sk-koloni-secret")
    monkeypatch.setenv("KOLONI_RUNTIME_ROOT", "C:/somewhere/koloni")
    monkeypatch.setenv("GEMINI_API_KEY", "the-users-own")
    monkeypatch.setenv("ANTIGRAVITY_HOME", "C:/the/users/own/settings")
    client, provider, _ = agy_app([{"say": "hello"}])
    cid, run_id = start(client, project_dir, provider)
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    seen = agy_app.record()
    # (101: the planted test key is put there on purpose, a fake one; nothing else of KOLONİ's)
    assert [name for name in seen["env"]
            if name.upper().startswith("KOLONI_") and name.upper() != "KOLONI_CANARY_KEY"] == []
    assert "sk-koloni-secret" not in json.dumps(seen)
    # B-310: reading too, none of the user's own Gemini or Antigravity set-up (its sign-in is in
    # the Windows vault): such a variable could name other settings, other MCP servers
    assert not [name for name in seen["env"]
                if name.upper().startswith(("GEMINI_", "ANTIGRAVITY_"))]


def test_only_these_models_holds_for_agy_too(agy_app, wait_run, project_dir):
    client, provider, _ = agy_app([{"say": "hello"}], asked="gemini-other", provider={
        "models": [{"name": "gemini-listed"}], "only_listed": True})
    cid, run_id = start(client, project_dir, provider)
    run = wait_run(client, cid, run_id)["runs"][0]
    assert run["status"] == "failed"
    assert "runs only with the models listed for it" in run["error"]
    tried = client.post(f"/api/providers/{provider['id']}/test?run=true").json()
    assert tried["ok"] is False and "gemini-other is not one of them" in tried["error"]
    assert not agy_app.ran()  # it was never started


# --- the provider ----------------------------------------------------------------------


def test_agy_runs_reading_unless_native_is_chosen(client):
    made = client.post("/api/providers", json={"name": "agy", "kind": "agy_cli"})
    assert made.status_code == 201, made.text
    body = made.json()
    assert (body["kind"], body["mode"], body["base_url"], body["has_key"], body["options"]) == (
        "agy_cli", "reads", None, False, None)
    assert client.post("/api/providers", json={
        "name": "agy 2", "kind": "agy_cli", "mode": "native"}).json()["mode"] == "native"
    for other in ("session", "step"):
        refused = client.post("/api/providers", json={
            "name": "agy 3", "kind": "agy_cli", "mode": other})
        assert refused.status_code == 422 and "agy cannot run" in refused.json()["detail"]
    # and reading with its own tools is agy's way only
    assert client.post("/api/providers", json={
        "name": "Cx", "kind": "codex_cli", "mode": "reads"}).status_code == 422
    assert client.patch(f"/api/providers/{body['id']}", json={"mode": "native"}).json()[
        "mode"] == "native"


def test_agy_found_on_the_first_start_is_offered_switched_off_reading_and_not_to_agents(
    settings_env, tmp_path
):
    settings_env["KOLONI_DETECT_CLI"] = "1"
    found = {"agy": str(tmp_path / "agy.cmd"), "claude": str(tmp_path / "claude.cmd")}
    app = create_app(load_settings(settings_env), model=ScriptedModel([]), which=found.get)
    with TestClient(app, base_url="http://127.0.0.1:8790") as client:
        by_kind = {p["kind"]: p for p in client.get("/api/providers").json()}
        agy = by_kind["agy_cli"]
        assert (agy["name"], agy["mode"], agy["for_agents"], agy["enabled"]) == (
            "agy", "reads", False, False)
        # Google's terms: agy waits for the user to switch it on; the others are on.
        assert by_kind["openai_compat"]["enabled"] and by_kind["claude_cli"]["enabled"]


def test_the_team_guide_says_how_agy_runs():
    from app.team import describe, guide

    def row(mode):
        return Provider(id="p", name="agy", kind="agy_cli", mode=mode, for_agents=True)

    # what is true of it: how it is started. Its own settings can let more through.
    assert [guide([row(mode)])[0].runs for mode in (None, "reads", "session", "native")] == [
        "reads with its own tools; started without leave to write or run"] * 3 + [
        "with its own tools, asks first"]  # (through its hook: slice 89e)
    assert describe(guide([row("reads")])).splitlines()[1] == (
        '- "agy" (agy, reads with its own tools; started without leave to write or run). '
        "Default model: its own choice.")
    assert "changes nothing" not in describe(guide([row("reads")]))


def test_in_a_discussion_and_a_try_out_agy_only_reads():
    native = AgyClient(None, "m", reads=False)
    assert native.native and native.asks and not native.reads  # (asking through its hook)
    talker = native.talker()
    assert isinstance(talker, AgyClient) and talker.reads and talker.native
    reader = AgyClient(None, "m")
    assert reader.reads and reader.talker() is reader


def test_agy_lists_its_own_models(agy_app):
    client, provider, _ = agy_app([], models=[
        ["gemini-3.8-flash-low", "Gemini 3.8 Flash (low)"], ["claude-sonnet-4.6", "Claude Sonnet 4.6"]],
        provider={"models": [{"name": "my-own"}, {"name": "claude-sonnet-4.6"}]})
    listed = client.get(f"/api/providers/{provider['id']}/models").json()
    assert listed == {
        "models": ["my-own", "claude-sonnet-4.6", *KNOWN, "gemini-3.8-flash-low"], "note": None}
    seen = agy_app.record()
    assert seen["argv"] == ["models"] and seen["stdin"] is None  # no model was used


def test_the_list_is_had_also_when_only_listed_models_may_run(agy_app):
    client, provider, _ = agy_app([], asked="gemini-other", models=[["gemini-a", "Gemini A"]],
                                  provider={"models": [{"name": "mine"}], "only_listed": True})
    listed = client.get(f"/api/providers/{provider['id']}/models").json()
    assert listed == {"models": ["mine", *KNOWN, "gemini-a"], "note": None}


def test_a_list_that_cannot_be_had_is_empty_and_says_why(agy_app):
    client, provider, _ = agy_app([], models_exit=2, stderr="fatal: not signed in")
    listed = client.get(f"/api/providers/{provider['id']}/models").json()
    assert listed["models"] == KNOWN
    assert listed["note"] == "agy exited with code 2: fatal: not signed in"


def test_a_line_is_a_model_only_if_it_is_an_id_a_tab_and_a_name():
    from app.model_agy import listed_models

    printed = (
        "Fetching available models...\n"
        "gemini-3.8-flash-low\tGemini 3.8 Flash (low)\n"
        "claude_opus-4.6\tClaude Opus 4.6\r\n"
        "Warning: could not reach\tthe update server\n"  # a tab, and no id before it
        "sign in at https://x.example/a?b=1\tfirst\n"
        "an-id-and-nothing\t\n"
        "\tonly a name\n"
        "no-tab-here\n"
        "gemini-3.8-flash-low\tsaid twice\n"
    )
    assert listed_models(printed) == ["gemini-3.8-flash-low", "claude_opus-4.6"]


def test_a_list_with_no_model_in_it_says_so(agy_app):
    client, provider, _ = agy_app([], models_text="No models available for this account.\n")
    listed = client.get(f"/api/providers/{provider['id']}/models").json()
    assert listed == {"models": KNOWN, "note": (
        "agy listed no models. Type the name you would give its --model option, or leave "
        "it empty for its own choice.")}


def test_what_agy_says_when_it_cannot_list_is_scrubbed_like_any_clis_words(tmp_path):
    import asyncio

    from app.model_client import ModelUnavailable

    class Scrubbing(AgyClient):
        def _hide(self, text):
            return text.replace("sk-secret", "[key]")

    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"record": str(tmp_path / "record.json"), "models_exit": 2,
                                "stderr": "fatal: the key sk-secret was refused"}),
                    encoding="utf-8")
    cli = Scrubbing(None, None, launcher=FAKE, env={"FAKE_AGY_PLAN": str(plan)})
    with pytest.raises(ModelUnavailable) as failed:
        asyncio.run(cli.models())
    assert str(failed.value) == "agy exited with code 2: fatal: the key [key] was refused"


def test_an_exit_code_nobody_knows_is_not_called_zero():
    from app.model_native import how_it_ended

    assert how_it_ended("agy", 3, "fatal: not signed in") == (
        "agy exited with code 3: fatal: not signed in")
    assert how_it_ended("agy", 0, "") == "agy ended without finishing (exit code 0)"
    assert how_it_ended("agy", None, "it was cut off") == (
        "agy ended, exit code not known: it was cut off")
    assert how_it_ended("agy", None, "") == (
        "agy ended without finishing (exit code not known)")


@pytest.mark.parametrize(("mode", "runs_as", "flag"), [
    (None, "reads", False), ("reads", "reads", False), ("session", "reads", False),
    ("native", "native", True)])
def test_a_providers_row_is_started_with_the_flag_only_when_it_says_native(
    settings_env, tmp_path, project_dir, wait_run, monkeypatch, mode, runs_as, flag
):
    # No stand-in client here: the row goes the way a real one does, through
    # Providers._build, and the command it names is started.
    record, plan = tmp_path / "record.json", tmp_path / "plan.json"
    plan.write_text(json.dumps({"record": str(record), "script": [{"say": "hello"}]}),
                    encoding="utf-8")
    monkeypatch.setenv("FAKE_AGY_PLAN", str(plan))
    if sys.platform == "win32":
        shim = tmp_path / "agy-stand-in.cmd"
        shim.write_text(f'@"{FAKE[0]}" "{FAKE[1]}" %*\r\n', encoding="utf-8")
    else:
        shim = tmp_path / "agy-stand-in"
        shim.write_text(f'#!/bin/sh\nexec "{FAKE[0]}" "{FAKE[1]}" "$@"\n', encoding="utf-8")
        shim.chmod(0o755)
    app = create_app(load_settings(settings_env))
    with TestClient(app, base_url="http://127.0.0.1:8790") as client:
        made = client.post("/api/providers", json={
            "name": "agy", "kind": "agy_cli", "executable": str(shim),
            "default_model": "gemini-asked"}).json()
        # A row as it may stand in the table, also one the API would not write.
        with app.state.session_factory() as session:
            row = session.get_one(Provider, made["id"])
            row.mode = mode
            session.commit()
            built = app.state.providers._build(row, "gemini-asked")
        assert isinstance(built, AgyClient) and built.reads is not flag
        assert (SKIP in built._agy_arguments()) is flag
        cid, run_id = start(client, project_dir, made, mode="full_auto")
        snap = wait_run(client, cid, run_id, timeout=30)
        assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
        argv = json.loads(record.read_text(encoding="utf-8"))["argv"]
        assert argv == ["--model", "gemini-asked", "--input-format", "stream-json",
                        "--output-format", "stream-json", *([SKIP] if flag else []), "-p="]
        assert snap["agents"][0]["provider_mode"] == runs_as


def test_a_list_that_takes_too_long_is_given_up(agy_app, monkeypatch):
    from app import model_agy

    monkeypatch.setattr(model_agy, "MODELS_SECONDS", 0.5)
    client, provider, _ = agy_app([], models_hang=True)
    began = time.monotonic()
    listed = client.get(f"/api/providers/{provider['id']}/models").json()
    assert listed["models"] == KNOWN and "did not list its models" in listed["note"]
    assert time.monotonic() - began < 20


def test_an_agy_that_is_not_installed_has_no_list(settings_env):
    app = create_app(load_settings(settings_env))
    with TestClient(app, base_url="http://127.0.0.1:8790") as client:
        made = client.post("/api/providers", json={
            "name": "agy", "kind": "agy_cli",
            "executable": "C:/nowhere/there-is-no-agy-here.exe"}).json()
        listed = client.get(f"/api/providers/{made['id']}/models").json()
        assert listed["models"] == KNOWN and "was not found" in listed["note"]
        tested = client.post(f"/api/providers/{made['id']}/test").json()
        assert tested["ok"] is False and "was not found" in tested["error"]


def test_trying_agy_out_is_a_reading_run_in_an_empty_folder(agy_app, project_dir):
    client, provider, _ = agy_app([{"say": "ok"}], mode="native", model="gemini-as-run")
    plain = client.post(f"/api/providers/{provider['id']}/test").json()
    assert (plain["ok"], plain["model_id"], plain["reply"]) == (True, "gemini-asked", None)
    assert not agy_app.ran()  # a check never runs the CLI
    tried = client.post(f"/api/providers/{provider['id']}/test?run=true").json()
    assert tried == {"ok": True, "model_id": "gemini-as-run", "tools_supported": True,
                     "error": None, "reply": "ok", "model_from": None}
    seen = agy_app.record()
    # a native provider is tried without the flag: a try-out can change nothing
    assert SKIP not in seen["argv"] and seen["argv"][-1] == "-p="
    asked = json.loads(seen["stdin"])["message"]["content"]
    assert "Reply with the single word" in asked
    assert Path(seen["cwd"]) != project_dir and not Path(seen["cwd"]).exists()
    # the folder it is run in is nobody's project, and it is not told that it is one
    assert "project" not in asked.lower()
    assert seen["cwd"] not in asked and json.dumps(seen["cwd"])[1:-1] not in asked
    # B-310: in a home of KOLONİ's, as its runs are, so it signs in as they do; gone after it
    home = Path(seen["env"]["USERPROFILE"])
    assert home.name.startswith("agy-") and seen["env"]["HOME"] == str(home)
    assert not home.exists()


def test_migration_0018_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0017")
    command.upgrade(cfg, "head")
    with sqlite3.connect(db) as conn:
        assert "provider_mode" in [row[1] for row in conn.execute("PRAGMA table_info(agents)")]
    command.downgrade(cfg, "0017")
    with sqlite3.connect(db) as conn:
        assert "provider_mode" not in [
            row[1] for row in conn.execute("PRAGMA table_info(agents)")]


def test_agy_is_given_its_level_flag_only_when_a_level_is_asked(tmp_path):
    import asyncio

    async def quiet(_text):
        pass

    record, plan = tmp_path / "record.json", tmp_path / "plan.json"
    plan.write_text(json.dumps({"record": str(record), "script": [{"say": "hello"}]}),
                    encoding="utf-8")
    cli = AgyClient(None, None, launcher=FAKE, env={"FAKE_AGY_PLAN": str(plan)})
    said = [{"role": "user", "content": "hi"}]
    asyncio.run(cli.stream_step("auto", said, None, quiet))
    assert "--effort" not in json.loads(record.read_text(encoding="utf-8"))["argv"]
    asyncio.run(cli.stream_step("auto", said, None, quiet, effort="xhigh"))
    argv = json.loads(record.read_text(encoding="utf-8"))["argv"]
    assert argv[argv.index("--effort") + 1] == "xhigh" and argv[-1] == "-p="
    assert asyncio.run(cli.info()).efforts == ("low", "medium", "high", "xhigh", "max")


def test_an_agy_model_whose_name_fixes_its_level_takes_none():
    """B-404 (live): "--model gemini-3.8-flash-low conflicts with --effort=medium"."""
    import asyncio

    from app.catalog import facts

    for name in ("gemini-3.8-flash-low", "gemini-4-argon-high", "gemini-x-XHIGH"):
        cli = AgyClient(None, name, reads=False)
        assert cli.level_named and asyncio.run(cli.info()).efforts == ()
        assert cli.talker().level_named  # (its reading self too)
        assert facts("agy_cli", None, name)[0]["efforts"] == []
    for name in (None, "gemini-3.8-flash", "gemini-highland"):
        cli = AgyClient(None, name)
        assert not cli.level_named and cli.efforts == ("low", "medium", "high", "xhigh", "max")
    assert facts("agy_cli", None, "gemini-3.8-flash")[0]["efforts"] == list(cli.efforts)
    # (agy's alone: a Qoder model's name ends in a level's word, and is not read so)
    assert facts("qoder_cli", None, "Qwen-3.8-Max")[1].get("efforts") != "its name says its level"


def test_an_agy_that_crashes_leaving_a_child_on_its_output_fails_the_turn_at_once(
    agy_app, wait_run, project_dir
):
    # denetim-010 #3: a child of its own held its output open after it crashed: the turn
    # waited out the limit on silence and blamed that.
    client, provider, _ = agy_app([
        {"tool": "view_file", "parameters": {"AbsolutePath": "hello.py"}, "never_ends": True},
        {"die": 7}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=20)
    run = snap["runs"][0]
    assert run["status"] == "failed" and "code 7" in run["error"], run["error"]
