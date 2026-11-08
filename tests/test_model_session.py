"""A CLI run as one session whose only tools are KOLONİ's, with a stand-in CLI."""

import asyncio
import json
import socket
import sys
import time
from pathlib import Path

import pytest

from app import model_session
from app.model_client import ModelUnavailable, OwnStop
from app.model_session import (
    QUEUE_WAIT_SECONDS,
    SECOND_BRIDGE,
    ClaudeSessionClient,
    CopilotSessionClient,
    QoderSessionClient,
    SessionStop,
    ToolServer,
    bridge_file,
    build_session_prompt,
)
from app.tools import TOOL_SCHEMAS
from tests.test_model_cli import alive, soon

pytestmark = pytest.mark.anyio

FAKE = [sys.executable, str(Path(__file__).with_name("fake_session_cli.py"))]
TOOLS = TOOL_SCHEMAS[:2]  # list_dir, read_file
MESSAGES = [
    {"role": "system", "content": "You are KOLONİ's agent."},
    {"role": "user", "content": "What does hello.py print?"},
]


@pytest.fixture
def cli(tmp_path):
    record = tmp_path / "record.json"
    plan = tmp_path / "plan.json"

    def make(kind, script, model=None, timeout=20.0, said_model=None, **more):
        # (said_model: the model its init line says it runs on)
        said = {"model": said_model} if said_model else {}
        plan.write_text(json.dumps({"record": str(record), "script": script, **said, **more}),
                        encoding="utf-8")
        return kind(model=model, timeout=timeout, launcher=FAKE, env={"FAKE_CLI_PLAN": str(plan)})

    return make, lambda: json.loads(record.read_text(encoding="utf-8"))


async def run(client, call_tool=None, tools=TOOLS):
    said: list[str] = []
    calls: list[tuple[str, dict, list[str]]] = []

    async def on_text(text):
        said.append(text)

    async def default_tool(name, arguments):
        # what had been said when the call arrived shows the order things were recorded in
        calls.append((name, json.loads(arguments), list(said)))
        return True, f"result of {name}"

    result = await client.run_session("m", MESSAGES, tools, call_tool or default_tool, on_text)
    return result, said, calls


def test_the_session_prompt_carries_rules_instructions_and_the_conversation():
    prompt = build_session_prompt(MESSAGES)
    rules, _, document = prompt.partition("\n\n{")
    assert "mcp__koloni__" in rules and "do what the last user message" in rules
    data = json.loads("{" + document)
    assert data == {"instructions": "You are KOLONİ's agent.",
                    "conversation": [{"role": "user", "content": "What does hello.py print?"}]}


async def test_text_and_tool_calls_flow_through_koloni_in_order(cli):
    make, record = cli
    client = make(ClaudeSessionClient, [
        {"say": "Let me look."},
        {"call": "read_file", "args": {"path": "hello.py"}},
        {"say": "It prints hi."},
    ], model="sonnet")
    result, said, calls = await run(client)

    assert said == ["Let me look.", "It prints hi."]
    # the call arrived after the text before it had been taken in, and before the text after
    assert calls == [("read_file", {"path": "hello.py"}, ["Let me look."])]
    assert (result.input_tokens, result.output_tokens) == (500, 40)

    seen = record()
    assert seen["tools"] == ["list_dir", "read_file"]
    assert seen["results"] == [
        {"content": [{"type": "text", "text": "result of read_file"}], "isError": False}]
    argv = seen["argv"]
    assert argv[argv.index("--tools") + 1] == ""  # none of its own
    assert "--strict-mcp-config" in argv and "--no-session-persistence" in argv
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert argv[argv.index("--allowedTools") + 1] == "mcp__koloni__list_dir,mcp__koloni__read_file"
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert seen["files"] == ["bridge.json", "mcp.json"]  # nothing of the project in its folder
    assert not Path(seen["cwd"]).exists()
    assert int(seen["env_tool_wait"]) >= 3_600_000  # an approval may take a while
    assert json.loads(seen["stdin"][seen["stdin"].index("\n\n{") + 2:])["conversation"]


async def test_qoder_gets_the_same_isolation_with_its_own_flags(cli):
    make, record = cli
    result, said, calls = await run(make(
        QoderSessionClient, [{"call": "list_dir"}, {"say": "One file."}],
        model="Qwen3.8-Flash", usage={"input_tokens": 0, "output_tokens": 0}))
    assert said == ["One file."] and [c[0] for c in calls] == ["list_dir"]
    # a CLI that reports zeros has not counted: the numbers stay unknown
    assert (result.input_tokens, result.output_tokens) == (None, None)
    argv = record()["argv"]
    assert argv[argv.index("--tools") + 1] == "" and "--strict-mcp-config" in argv
    assert argv[argv.index("-o") + 1] == "stream-json"
    allowed = [argv[i + 1] for i, a in enumerate(argv) if a == "--allowed-tools"]
    assert allowed == ["mcp__koloni__list_dir", "mcp__koloni__read_file"]
    assert argv[argv.index("-m") + 1] == "Qwen3.8-Flash"


QUEUED = [json.loads(line) for line in Path(__file__).with_name("qoder_streams").joinpath(
    "queue-status.jsonl").read_text(encoding="utf-8").splitlines()]  # (measured, qodercli 1.1.51)


async def test_qoder_says_how_long_its_free_model_has_been_queued_and_no_more_once_it_answers(cli):
    """K-qoder-kuyruk: each queue line is shown live as it comes (the page shows the latest);
    a line with another status, or its model's first move (a tool call straight from the
    queue, say, or its words), clears it - once, not at every move after."""
    make, _record = cli
    shown: list[dict] = []
    # (The measured lines still under QUEUE_WAIT_SECONDS: six of the queue's, 65 s in at most.)
    under = [line for line in QUEUED
             if line.get("queue_wait_elapsed_ms", 0) < QUEUE_WAIT_SECONDS * 1000]
    # shortcut: the status word that ends a queue was not measured; one that is not
    # "queued" stands for it here.
    client = make(QoderSessionClient, [
        *({"emit": line} for line in under),
        {"emit": {**under[-1], "status": "done"}}, {"emit": under[-1]},
        {"call": "list_dir"}, {"say": "ok"}])

    async def on_text(_text):
        pass

    async def a_tool(_name, _arguments):
        return True, "one file"

    await client.run_session("m", MESSAGES, TOOLS, a_tool, on_text, on_live=shown.append)
    last = {"queue": {"elapsed_s": 65, "max_s": 3600, "available": False}}
    assert shown[0] == {"queue": {"elapsed_s": 0, "max_s": 3600, "available": False}}
    assert shown[5] == last
    assert shown[6:] == [{"queue": None}, last, {"queue": None}]  # (the last: its tool call)


async def test_a_model_queued_past_the_limit_ends_the_session_as_unavailable(cli):
    """K-altajan-saglayici: queued QUEUE_WAIT_SECONDS (R115: 5.5 min, then "Queuing failed"),
    the session is given up before a first word, so its opener can move the agent on. R130:
    with no limit (an agent nowhere to move) it waits for as long as Qoder queues it."""
    make, _record = cli
    client = make(QoderSessionClient, [*({"emit": line} for line in QUEUED), {"say": "ok"}])
    with pytest.raises(ModelUnavailable, match="Qoder kept its model queued for 2 min"):
        await run(client)

    said: list[str] = []

    async def on_text(text):
        said.append(text)

    await client.run_session("m", MESSAGES, TOOLS, None, on_text, queue_wait=None)
    assert said == ["ok"]


async def test_a_failed_or_declined_tool_is_returned_as_an_error_result(cli):
    make, record = cli

    async def refuse(name, arguments):
        return False, "rejected: the user declined this change"

    await run(make(ClaudeSessionClient, [{"call": "read_file"}]), call_tool=refuse)
    assert record()["results"] == [{
        "content": [{"type": "text", "text": "rejected: the user declined this change"}],
        "isError": True}]


async def test_a_cli_that_starts_with_tools_of_its_own_is_stopped(cli):
    make, record = cli
    client = make(ClaudeSessionClient, [{"say": "hi"}, {"hang": True}], own_tools=["Bash", "Edit"])
    # (KOLONİ's own rule stopped it, not something its provider said: no class of failure.)
    with pytest.raises(OwnStop, match="tools of its own .*Bash, Edit"):
        await run(client)
    assert await soon(lambda: not alive(record()["pid"]))


async def test_only_this_sessions_cli_can_reach_the_tools():
    called = []

    async def call_tool(name, arguments):
        called.append(name)
        return True, "ok"

    server = ToolServer(TOOLS, call_tool)
    await server.start()
    try:
        def ask(key: bytes) -> bytes:
            with socket.create_connection(("127.0.0.1", server.port), timeout=5) as s:
                s.sendall(key + b"\n" + json.dumps({
                    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "read_file", "arguments": {}}}).encode() + b"\n")
                s.settimeout(2)
                try:
                    return s.recv(4096)
                except TimeoutError:
                    return b"<nothing>"

        assert await asyncio.to_thread(ask, b"wrong-key") == b""  # the door is shut
        assert called == []
        answer = await asyncio.to_thread(ask, server.key.encode())
        assert json.loads(answer)["result"]["isError"] is False and called == ["read_file"]
    finally:
        await server.close()


def connect(server):
    s = socket.create_connection(("127.0.0.1", server.port), timeout=5)
    s.sendall(server.key.encode() + b"\n")
    return s


async def test_the_key_serves_one_bridge_and_a_second_ends_the_session(tmp_path, caplog):
    # B-304: once its bridge is in, the session's bridge file is gone; another program with
    # the key is turned away and ends the session, said why - never the key. agy's door
    # serves a connection per call.
    called = []

    async def call_tool(name, arguments):
        called.append(name)
        return True, "ok"

    def call(s) -> bytes:
        s.sendall(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "read_file", "arguments": {}}}).encode() + b"\n")
        s.settimeout(2)
        try:
            return s.recv(4096)
        except (TimeoutError, ConnectionError):
            return b""

    server, door = ToolServer(TOOLS, call_tool), ToolServer(TOOLS, call_tool, alone=False)
    await server.start()
    await door.start()
    ended = []
    server.on_end = lambda: ended.append(True)
    told = bridge_file(server, tmp_path)
    try:
        bridge = await asyncio.to_thread(connect, server)
        assert json.loads(await asyncio.to_thread(call, bridge))["result"]["isError"] is False
        assert not told.exists()  # read by its bridge, by nobody after
        second = await asyncio.to_thread(connect, server)
        assert await asyncio.to_thread(call, second) == b"" and called == ["read_file"]
        second.close()
        bridge.close()
        assert isinstance(server.ended, OwnStop) and str(server.ended) == SECOND_BRIDGE
        assert ended and SECOND_BRIDGE in caplog.text and server.key not in caplog.text
        both = [await asyncio.to_thread(connect, door) for _ in range(2)]
        for one in both:
            assert json.loads(await asyncio.to_thread(call, one))["result"]["isError"] is False
            one.close()
    finally:
        await server.close()
        await door.close()


async def test_a_second_program_with_the_key_stops_the_run_and_says_why(cli, monkeypatch):
    # B-304: had another program got in first, the run's own bridge would be the one turned
    # away - so the run never goes on without its tools unsaid.
    make, record = cli
    servers = []

    def noted(server, workdir):
        servers.append(server)
        return bridge_file(server, workdir)

    monkeypatch.setattr(model_session, "bridge_file", noted)
    task = asyncio.create_task(run(make(ClaudeSessionClient, [{"say": "hi"}, {"hang": True}])))

    def listed() -> bool:  # its bridge in and its tools listed: then it is on record
        try:
            return "tools" in record()
        except (OSError, ValueError):
            return False

    # (Only its bridge in, under load the second program came before the CLI's record.)
    assert await soon(listed, 15) and servers[0]._taken
    (await asyncio.to_thread(connect, servers[0])).close()
    with pytest.raises(OwnStop, match="second connection with this run's key"):
        await asyncio.wait_for(task, 15)
    assert await soon(lambda: not alive(record()["pid"]))


def test_no_clis_config_holds_the_key(tmp_path):
    # B-304: the key is in the bridge file alone (Claude Code's and Qoder's mcp.json had it).
    server = ToolServer(TOOLS, None)
    for client in (ClaudeSessionClient(), QoderSessionClient(), CopilotSessionClient()):
        config = client._mcp_config(server, tmp_path)
        assert server.key not in json.dumps(config)
        assert config["mcpServers"]["koloni"]["args"][1] == str(tmp_path / "bridge.json")
        told = json.loads((tmp_path / "bridge.json").read_text(encoding="utf-8"))
        assert told == {"port": server.port, "key": server.key}


async def test_the_tool_callback_can_end_the_session(cli):
    make, record = cli
    seen = 0

    async def limited(name, arguments):
        nonlocal seen
        seen += 1
        if seen > 2:
            raise SessionStop("step_limit")
        return True, "ok"

    script = [{"call": "list_dir"}] * 6 + [{"hang": True}]
    started = time.monotonic()
    with pytest.raises(SessionStop, match="step_limit") as stopped:
        await run(make(ClaudeSessionClient, script, said_model="claude-x"), call_tool=limited)
    assert time.monotonic() - started < 15
    assert stopped.value.model == "claude-x"  # (B-410: the model it ran on, on record still)
    assert seen == 3 and await soon(lambda: not alive(record()["pid"]))


async def test_stop_ends_the_cli_and_a_waiting_tool_call(cli):
    make, record = cli
    waiting = asyncio.Event()
    cancelled = []

    async def never(name, arguments):
        waiting.set()
        try:
            await asyncio.sleep(120)
        except asyncio.CancelledError:
            cancelled.append(name)
            raise
        return True, "ok"

    task = asyncio.create_task(run(make(ClaudeSessionClient, [{"call": "read_file"}]),
                                   call_tool=never))
    await asyncio.wait_for(waiting.wait(), 10)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled == ["read_file"]
    assert await soon(lambda: not alive(record()["pid"]) and not Path(record()["cwd"]).exists())


async def test_failures_say_why(cli):
    make, _ = cli
    with pytest.raises(ModelUnavailable, match="exited with code 3: .*not signed in"):
        await run(make(ClaudeSessionClient, [{"exit": 3, "stderr": "Error: not signed in"}]))
    with pytest.raises(ModelUnavailable, match="reported an error: .*quota"):
        await run(make(ClaudeSessionClient, [{"result_error": "monthly quota exceeded"}]))
    with pytest.raises(ModelUnavailable, match="sent nothing for 1.5 seconds"):
        await run(make(ClaudeSessionClient, [{"hang": True}], timeout=1.5))


async def test_a_session_client_does_not_run_step_by_step(cli):
    make, _ = cli
    with pytest.raises(ModelUnavailable, match="runs as a session"):
        await make(ClaudeSessionClient, []).stream_step("m", MESSAGES, TOOLS, None)
    info = await QoderSessionClient(which=lambda name: "C:/q/qodercli.exe").info()
    assert info.tools_supported is True
    with pytest.raises(ModelUnavailable, match="the qodercli command was not found"):
        await QoderSessionClient(which=lambda name: None).info()


# --- review fixes -----------------------------------------------------------------


async def test_time_spent_waiting_on_a_tool_is_not_the_clis_silence(cli):
    # An approval, a long command or a sub-agent can take far longer than the CLI may
    # stay silent; the limit is on silence, and a tool in flight is not silence.
    make, _ = cli

    async def slow(name, arguments):
        await asyncio.sleep(3)
        return True, "approved at last"

    client = make(ClaudeSessionClient, [{"call": "read_file"}, {"say": "Done."}], timeout=1.0)
    result, said, _ = await run(client, call_tool=slow)
    assert said == ["Done."] and result.output_tokens == 40


async def test_a_large_tool_argument_arrives_whole(cli):
    make, record = cli
    big = "x" * 300_000
    got = []

    async def take(name, arguments):
        got.append(len(json.loads(arguments)["content"]))
        return True, "applied"

    await run(make(ClaudeSessionClient, [
        {"call": "read_file", "args": {"path": "a", "content": big}}]), call_tool=take)
    assert got == [300_000] and record()["results"][0]["isError"] is False


async def test_a_bug_inside_a_tool_ends_the_session_with_that_bug(cli):
    make, record = cli

    async def broken(name, arguments):
        raise KeyError("some_internal_key")

    started = time.monotonic()
    with pytest.raises(KeyError, match="some_internal_key"):
        await run(make(ClaudeSessionClient, [{"call": "read_file"}, {"hang": True}]),
                  call_tool=broken)
    assert time.monotonic() - started < 15  # not after waiting out a time limit
    assert await soon(lambda: not alive(record()["pid"]))


async def test_a_cli_that_does_not_say_which_tools_it_has_is_not_served(cli):
    make, record = cli
    called = []

    async def note(name, arguments):
        called.append(name)
        return True, "ok"

    with pytest.raises(ModelUnavailable, match="did not say which tools it started with"):
        await run(make(ClaudeSessionClient, [{"call": "read_file"}, {"say": "hi"}],
                       no_init=True, timeout=20), call_tool=note)
    assert called == []


async def test_several_calls_at_once_are_answered_one_at_a_time(cli):
    make, record = cli
    running = 0
    most = 0

    async def one_at_a_time(name, arguments):
        nonlocal running, most
        running += 1
        most = max(most, running)
        await asyncio.sleep(0.05)
        running -= 1
        return True, json.loads(arguments)["path"]

    await run(make(ClaudeSessionClient, [
        {"say": "Three at once."},
        {"parallel": [{"call": "read_file", "args": {"path": p}} for p in "abc"]},
        {"say": "Done."}]), call_tool=one_at_a_time)
    assert most == 1
    assert sorted(r["content"][0]["text"] for r in record()["results"]) == ["a", "b", "c"]


async def test_odd_first_lines_never_get_past_the_door():
    async def call_tool(name, arguments):
        raise AssertionError("must not be reached")

    server = ToolServer(TOOLS, call_tool)
    await server.start()
    try:
        def knock(first: bytes) -> bytes:
            with socket.create_connection(("127.0.0.1", server.port), timeout=5) as s:
                s.sendall(first + b"\n" + b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n')
                s.settimeout(2)
                try:
                    return s.recv(4096)
                except (TimeoutError, ConnectionError):
                    return b""

        for first in (b"", "anahtar-\u00e7\u011f".encode(), b"k" * 200_000, server.key.encode() + b"x"):
            assert await asyncio.to_thread(knock, first) == b""
    finally:
        await server.close()


async def test_text_blocks_of_one_message_are_kept_apart(cli):
    make, _ = cli
    _, said, _ = await run(make(ClaudeSessionClient, [{"say": "Let me look."}, {"say": "It prints hi."}]))
    assert "".join(said) == "Let me look.\n\nIt prints hi."


async def test_a_tool_that_was_not_offered_is_not_run_under_any_name(cli):
    make, record = cli
    called = []

    async def note(name, arguments):
        called.append(name)
        return True, "ok"

    # only list_dir and read_file are offered to this session
    await run(make(ClaudeSessionClient, [{"call": "run_command", "args": {"command": "x"}}]),
              call_tool=note)
    assert called == []
    result = record()["results"][0]
    assert result["isError"] is True and "not one of the tools" in result["content"][0]["text"]


async def test_qoder_is_given_its_level_flag_only_when_a_level_is_asked(cli):
    make, record = cli

    async def quiet(_text):
        pass

    async def no_tool(_name, _arguments):
        return True, ""

    client = make(QoderSessionClient, [{"say": "ok"}])
    assert (await client.info()).efforts == ("off", "low", "medium", "high", "xhigh")
    await client.run_session("m", MESSAGES, TOOLS, no_tool, quiet)
    assert "--reasoning-effort" not in record()["argv"]
    await client.run_session("m", MESSAGES, TOOLS, no_tool, quiet, effort="medium")
    assert record()["argv"][:2] == ["--reasoning-effort", "medium"]


def test_only_copilots_own_tool_search_goes_on_another_servers_tool_so_named_stops_it():
    # B-410: tool_search_tool of no MCP server is its search; one of another server's is not.
    copilot = CopilotSessionClient()
    search = {"name": "tool_search_tool", "arguments": {"query": "read"}}
    assert copilot._translate({"type": "assistant.message", "data": {"toolRequests": [search]}}) == []
    assert copilot._translate({"type": "tool.execution_start",
                               "data": {"toolName": "tool_search_tool"}}) == []
    other = {**search, "mcpServerName": "elsewhere"}
    with pytest.raises(OwnStop, match="asked for a tool of its own"):
        copilot._translate({"type": "assistant.message", "data": {"toolRequests": [other]}})
    with pytest.raises(OwnStop, match="used a tool of its own"):
        copilot._translate({"type": "tool.execution_start", "data": {
            "toolName": "tool_search_tool", "mcpServerName": "elsewhere"}})
