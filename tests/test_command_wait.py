"""herdr's idea (28 Nov 2026): command_output waits for a piece of text in a command's output -
in what it may read (kept, secrets hidden), its server's or its background command's - until it is
seen, the command ends, or its time is up."""

import asyncio
import subprocess
import sys

import pytest

from app import command_wait
from app.command_wait import UNTIL_MOST, WAIT_MOST, until_of, waited
from app.tools import ToolError
from tests.conftest import scaled
from tests.fakes import Script, ScriptedExecutor
from tests.test_background_command import later, on
from tests.test_background_spawn import tool_result
from tests.test_chat_flow import start_in_mode, text
from tests.test_command_output import LOG, SECRET, on_its_id, results
from tests.test_keep_running import serve
from tests.test_spawn import begin, call, step


@pytest.mark.parametrize(
    ("args", "why"),
    [
        ({"until": ""}, "until is a piece of text"),
        ({"until": "x" * (UNTIL_MOST + 1)}, "until is a piece of text"),
        ({"until": 3}, "until is a piece of text"),
        ({"until": "ok", "timeout_seconds": True}, "timeout_seconds is a number"),
        ({"until": "ok", "timeout_seconds": WAIT_MOST + 1}, "timeout_seconds is a number"),
        ({"timeout_seconds": 5}, "timeout_seconds is for until"),
    ],
)
def test_what_it_waits_for_is_held_to_its_bounds(args, why):
    with pytest.raises(ToolError, match=why):
        until_of(args)
    assert until_of({}) is None and until_of({"until": "ok"}) == ("ok", 30.0)


@pytest.mark.anyio
async def test_it_says_the_line_it_was_seen_in_or_why_not(monkeypatch):
    monkeypatch.setattr(command_wait, "LOOK", 0.01)
    printed = ["starting\n"]
    later_on = asyncio.get_running_loop().call_later(
        0.05, printed.append, "ready: listening on 3000\nnext"
    )
    seen = await waited(lambda: "".join(printed), "listening on", 5, None)
    assert seen == "Seen at character 16, in the line: ready: listening on 3000\n"
    later_on.cancel()
    after = await waited(lambda: "passed\nlater passed", "passed", 0.05, 7)  # (after its since)
    assert after == "Seen at character 13, in the line: later passed\n"
    assert await waited(lambda: None, "passed", 5, None) == "Not seen: it is no longer running.\n"
    assert await waited(lambda: "x", "passed", 0.05, None) == "Not seen in 0.05 s.\n"


def test_a_long_output_and_the_longest_text_are_looked_through_in_little_time():
    # (The bomb rule: 16 KB of output, the longest text that almost matches everywhere - in a child
    # process with a time limit. A piece of text, no pattern: nothing to backtrack.)
    code = (
        "import asyncio; from app.command_wait import waited\n"
        f"print(asyncio.run(waited(lambda: 'a' * 16000, 'a' * {UNTIL_MOST - 1} + 'b', 0.0, None)))"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=scaled(30)
    )
    assert done.returncode == 0 and "Not seen in 0 s" in done.stdout, done.stderr


def test_it_waits_in_its_servers_output_never_for_what_is_hidden(
    make_client, wait_run, project_dir, gate, monkeypatch
):
    monkeypatch.setenv("KOLONI_TEST_API_KEY", SECRET)
    monkeypatch.setattr(command_wait, "LOOK", 0.05)
    executor = ScriptedExecutor([Script(LOG, hold=gate)])
    client, model = make_client([serve()], executor=executor)
    model.steps.extend(
        [
            on_its_id(model, "command_output", {"until": "500 boom", "timeout_seconds": 5}, "o1"),
            on_its_id(model, "command_output", {"until": SECRET, "timeout_seconds": 1}, "o2"),
            on_its_id(model, "stop_command", call_id="s1"),
            text("stopped"),
        ]
    )
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    done = wait_run(client, cid, run_id)
    assert done["runs"][0]["status"] == "completed", done["runs"][0]["error"]
    ((_, seen), (_, hidden)) = results(done, "command_output")
    assert "Seen at character" in seen and "in the line: GET / 500 boom in handler" in seen
    assert "Not seen in 1 s" in hidden  # (its secret is hidden in what it reads: no yes/no)
    assert SECRET not in seen + hidden


def test_it_waits_in_a_background_commands_output(make_client, wait_run, project_dir, gate):
    executor = ScriptedExecutor([Script(["building...\n", "tests passed\n"], hold=gate)])
    client, model = make_client({"Lead": []}, executor=executor)
    model.by_agent["Lead"] += [
        later("make test"),
        step(call("list_dir", {}, "l1")),
        on(client, "command_output", until="passed", timeout_seconds=5),
        on(client, "stop_command"),
        text("stopped it"),
        text("read its end"),
    ]
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    gate.release()
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    read = tool_result(model.calls_of["Lead"][3], "command_output-k1")
    assert read.startswith("Seen at character") and "in the line: tests passed" in read
