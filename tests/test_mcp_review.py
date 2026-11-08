"""What the reviews of slice 28b found, each as a test: a server is never started where a
project's files could decide what is run; a server that misbehaves ends its own call and
no more; what the user is shown where they give leave is what is so; and an agent is told
the path of the folder it works in."""

import asyncio
import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import select

from app import copies, mcp_client
from app.api.mcp_servers import UNSHOWN
from app.db.models import McpServer
from app.mcp_client import Client, McpError
from app.model_client import ToolCallRequest
from tests.test_agent_writes import wait_status
from tests.test_chat_flow import text
from tests.test_mcp import ECHO, HELLO, peer
from tests.test_mcp_scenarios import FAKE, LONG, NOTHING, ORIGIN, calls, events, give, gone, server
from tests.test_migration_0002 import _config
from tests.test_session_agent import _begin as begin_on
from tests.test_session_agent import session_app  # noqa: F401  (a fixture)
from tests.test_spawn import begin, call, names, role_id, spawn, step

windows = pytest.mark.skipif(sys.platform != "win32", reason="a .cmd launcher is a Windows thing")
LISTS_ECHO = f'say({{"id": mid, "result": {{"tools": [{ECHO!r}]}}}})'
# Characters that do not show, by their numbers (an editor may not keep them as written): one
# that turns the text round, one without width, a tag character, and the two separators.
TURNED, NO_WIDTH, TAG, LINE, PARAGRAPH = map(chr, (0x202e, 0x200b, 0xe0041, 0x2028, 0x2029))
NOT_FINITE = "its input schema holds a number that is not finite (NaN, Infinity)"
UNSEEN_INPUTS = "its inputs hold characters that do not show"


def added(client, name, command_, free=False, **env):
    """Add a server of a test's own through the API and read its tools; returns it. `free`:
    its tools marked "Runs without asking" (`server`'s)."""
    client.headers["Origin"] = ORIGIN
    made = client.post("/api/mcp-servers", json={"name": name, "command": command_, "env": env})
    assert made.status_code == 201, made.text
    read = client.post(f"/api/mcp-servers/{made.json()['id']}/read").json()
    assert read["server"]["read_error"] is None, read["server"]["read_error"]
    marks = {tool["name"]: "free" for tool in read["server"]["tools"]} if free else {}
    # trusted (slice 92): these tests are of what a server's call is held to then
    return client.patch(f"/api/mcp-servers/{made.json()['id']}",
                        json={"trusted": True, "marks": marks}).json()


# --- where a server is started, and what is started ---------------------------------------------


@windows
@pytest.mark.parametrize("told", [True, False])
def test_a_launcher_never_runs_a_program_that_lies_in_the_project(
    make_client, wait_run, project_dir, tmp_path, monkeypatch, told
):
    """A launcher that names its program bare, as npm's launchers name node: the command
    interpreter looks such a name up in the folder it stands in before PATH. Two things
    keep the project's file from being that program: the server stands in an empty folder,
    and it is told not to look where it stands. `told` False takes the second away."""
    # KOLONİ's own environment says nothing of it, as on a user's machine (this alone
    # changes nothing for the server: `start` tells it all the same)...
    monkeypatch.delenv("NoDefaultCurrentDirectoryInExePath", raising=False)
    if not told:
        # ...and here the server is not told either: the empty folder is all there is
        monkeypatch.setattr(mcp_client, "NOT_WHERE_IT_STANDS", {})
    tools, on_path, ran = tmp_path / "tools", tmp_path / "bin", tmp_path / "planted-ran"
    tools.mkdir()
    on_path.mkdir()
    (tools / "server.cmd").write_text("@helper %*\r\n", encoding="utf-8")
    (on_path / "helper.cmd").write_text(f'@"{FAKE[0]}" "{FAKE[1]}" %*\r\n', encoding="utf-8")
    (project_dir / "helper.cmd").write_text(f'@echo ran> "{ran}"\r\n', encoding="utf-8")
    monkeypatch.setenv("PATH", f"{on_path}{os.pathsep}{os.environ['PATH']}")
    record, plan = tmp_path / "record.jsonl", tmp_path / "plan.json"
    plan.write_text(json.dumps({"record": str(record)}), encoding="utf-8")
    client, _ = make_client([step(call("npm__echo", {"text": "hi"})), text("done")])
    added(client, "npm", [str(tools / "server.cmd")], free=True, FAKE_MCP_PLAN=str(plan))
    give(client, "Lead", "npm")
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id, timeout=LONG)
    # What lies in the project was not run, and the server behind the launcher answered.
    # With `told` False these two lines pin the empty folder alone: started in the
    # project, the interpreter would find helper.cmd there first and run it.
    assert calls(snap)["npm__echo"][0] == "succeeded", calls(snap)
    assert not ran.exists()
    read, for_the_lead = events(record, "start")
    for start in (read, for_the_lead):
        assert start["files"] == []                      # nothing in the folder it stands in
        # what the server is told, as it saw it: this line pins the variable, none above
        assert start["env"].get("NODEFAULTCURRENTDIRECTORYINEXEPATH") == ("1" if told else None)


@windows
@pytest.mark.anyio
async def test_a_bare_name_is_not_found_in_the_folder_koloni_itself_stands_in(
    tmp_path, monkeypatch
):
    # KOLONİ's own environment is the one that counts here - the look-up is KOLONİ's, and
    # no server is started, so what a server is told plays no part: without the variable,
    # as on a user's machine, the look-up finds a bare name in the folder KOLONİ stands in.
    monkeypatch.delenv("NoDefaultCurrentDirectoryInExePath", raising=False)
    ran = tmp_path / "ran"
    (tmp_path / "planted-by-a-test.cmd").write_text(f'@echo ran> "{ran}"\r\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert shutil.which("planted-by-a-test")             # the premise: it is found from here
    assert mcp_client.found("planted-by-a-test") is None  # pins that such a find is none
    # pins that a start goes by `found`, and says what the user can do about it
    with pytest.raises(McpError, match="the program planted-by-a-test was not found"):
        await Client.start(["planted-by-a-test"], {}, tmp_path)
    assert not ran.exists()     # (follows from the two above: nothing was started at all)


@windows
def test_a_path_that_names_no_drive_is_made_whole(tmp_path, monkeypatch):
    """`\\tools\\x.cmd` counts as a full path on Windows (Python 3.12), and means another
    file from every folder on another drive: what is started is said with its drive."""
    script = tmp_path / "server.cmd"
    script.write_text("@echo off\r\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    at = mcp_client.found(os.path.splitdrive(str(script))[1])
    assert at is None or (os.path.splitdrive(at)[0] and os.path.samefile(at, script))
    assert mcp_client.found(str(script)) == str(script)   # one that is whole is as it was


@windows  # (elsewhere a file named so is a program like any other, and is started as one)
def test_what_the_command_interpreter_would_act_on_is_refused_when_a_launcher_is_saved(
    make_client, tmp_path
):
    client, _ = make_client([text("x")])
    client.headers["Origin"] = ORIGIN
    shim, odd = tmp_path / "server.cmd", tmp_path / "a&b"
    odd.mkdir()
    for launcher in (shim, odd / "server.bat"):
        launcher.write_text("@echo off\r\n", encoding="utf-8")
    for refused in ([str(shim), "https://example.com/?a=1&b=2"], [str(shim), "100%"],
                    [str(odd / "server.bat")]):          # in its own path too
        answer = client.post("/api/mcp-servers", json={"name": "npm", "command": refused})
        assert answer.status_code == 422, refused
        assert "% ! ^ & | < > cannot be in its path or in an argument" in answer.json()["detail"]
    # a program the interpreter does not run is given the same argument as it is
    made = client.post("/api/mcp-servers", json={
        "name": "npm", "command": [sys.executable, "https://example.com/?a=1&b=2"]})
    assert made.status_code == 201, made.text
    assert client.patch(f"/api/mcp-servers/{made.json()['id']}",
                        json={"command": [str(shim), "a|b"]}).status_code == 422
    assert client.get("/api/mcp-servers").json()[0]["command"][0] == sys.executable


# --- a server that misbehaves ends its call, and no more ---------------------------------------


@pytest.mark.anyio
async def test_a_server_that_reads_nothing_more_holds_neither_the_call_nor_the_stop(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(mcp_client, "CALL_SECONDS", 1.0)
    deaf = peer(tmp_path, "pass", hello=HELLO + "\n        time.sleep(60)")
    much, pid = {"text": "x" * 90_000}, tmp_path / "pid"  # more than a pipe takes unread
    client = await Client.start(deaf, {"PEER_PID": str(pid)}, tmp_path)
    began = time.monotonic()
    with pytest.raises(McpError, match="did not answer within 1 seconds"):
        await asyncio.wait_for(client.call("anything", much), 15)
    assert time.monotonic() - began < 10 and gone([int(pid.read_text())])
    # and a Stop: one is enough
    client = await Client.start(deaf, {"PEER_PID": str(pid)}, tmp_path)
    calling = asyncio.ensure_future(client.call("anything", much))
    await asyncio.sleep(0.3)
    calling.cancel()
    done, _ = await asyncio.wait({calling}, timeout=15)
    assert done and calling.cancelled() and gone([int(pid.read_text())])


@pytest.mark.anyio
async def test_an_answer_that_cannot_be_read_ends_the_call_and_half_a_character_is_made_whole(
    tmp_path, monkeypatch
):
    # nested deeper than anything reads
    deep = await Client.start(peer(
        tmp_path, 'print("[" * 100000 + "]" * 100000, flush=True)', "time.sleep(60)"), {}, tmp_path)
    with pytest.raises(McpError, match="answered tools/call with what cannot be read"):
        await deep.call("anything", {})
    assert not deep.alive
    # half of a character's pair, as a server that cuts through an emoji writes it
    half = await Client.start(peer(
        tmp_path, 'say({"id": mid, "result": {"content": [{"type": "text", '
        '"text": "half \\ud83d of a pair"}]}})'), {}, tmp_path)
    try:
        assert await half.call("anything", {}) == (False, "half ? of a pair")
    finally:
        await half.end()
    # and whatever else goes wrong in reading an answer is the server's failure
    odd = await Client.start(peer(tmp_path, 'say({"id": mid, "result": {}})'), {}, tmp_path)
    monkeypatch.setattr(mcp_client, "_message", lambda line: {}["not there"])
    with pytest.raises(McpError, match="answered tools/call with what cannot be read"):
        await odd.call("anything", {})
    assert not odd.alive


def test_a_result_that_could_not_be_kept_as_it_came_ends_no_turn(
    make_client, wait_run, project_dir, tmp_path
):
    client, model = make_client([step(call("odd__echo", {"text": "x"})), text("done")])
    added(client, "odd", peer(
        tmp_path, 'say({"id": mid, "result": {"content": [{"type": "text", '
        '"text": "half \\ud83d and \\u0000 nothing"}]}})', listing=LISTS_ECHO), free=True)
    give(client, "Lead", "odd")
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    status, result = calls(snap)["odd__echo"]
    assert status == "succeeded" and "half ? and" in result
    assert model.calls[1][-1]["content"] == result


@pytest.mark.anyio
async def test_a_server_that_refuses_to_say_hello_is_ended_and_its_folder_goes_with_it(tmp_path):
    """It answered, so nothing timed out and nothing broke - and it is of no use all the
    same: left running, there would be one more of it for every reading and every call."""
    pid, stood = tmp_path / "pid", tmp_path / "stood"
    refusing = peer(tmp_path, "pass", hello=(
        f'open({str(stood)!r}, "w").write(os.getcwd()); sys.stderr.write("too new\\n"); '
        'say({"id": mid, "error": {"code": -32602, "message": "Unsupported protocol version"}})'))
    for start in (Client.start, mcp_client.read_tools):  # for an agent's call, and for a reading
        with pytest.raises(McpError) as refused:
            await start(refusing, {"PEER_PID": str(pid)}, tmp_path)
        folder = Path(stood.read_text())
        assert gone([int(pid.read_text())])
        assert folder.name.startswith("koloni-mcp-") and not folder.exists()
        assert str(refused.value) == (
            'refused initialize: Unsupported protocol version; its last words: "too new"')
        pid.unlink()
        stood.unlink()


def test_a_file_named_as_a_launcher_is_a_program_like_any_other_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert not mcp_client._launcher("/opt/tools/server.cmd")   # not handed to a shell there
    assert mcp_client.not_startable(["/opt/tools/server.bat", "a & b", "100%"]) is None
    assert mcp_client.not_startable(["/usr/bin/node", "D:proj/s.js"]) is None  # a file's name there


def test_a_drive_relative_argument_is_refused_on_windows(monkeypatch):
    # D:proj\s.js runs D:\proj\s.js (the server starts on another drive, with no =D: of its own),
    # which `in_project` would not pin: said in full instead.
    monkeypatch.setattr(sys, "platform", "win32")
    for bad in ("D:proj\\s.js", "--entry=D:proj\\s.js", "ENTRY=D:s.js", "D:x", "d:.\\s.js",
                "x:y", "D:1a"):
        assert "names a drive without a folder" in mcp_client.not_startable(
            ["C:\\tools\\node.exe", bad]), bad
    # a full path, a flag, a host and port, a number after a letter, a bare drive: no path read
    # from a drive's own folder
    for good in ("D:\\proj\\s.js", "D:/proj/s.js", "/c", "localhost:8080", "--port=8:80",
                 "http://x", "a:1", "--level=a:12", "--root=D:", "D:", "ab:cd"):
        assert mcp_client.not_startable(["C:\\tools\\node.exe", good]) is None, good


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' root-relative paths; a patched isabs breaks posixpath")
def test_a_path_from_the_root_is_pinned_by_python_3_13s_isabs_too(monkeypatch, tmp_path):
    from pathlib import PureWindowsPath

    project = tmp_path / "proj"
    project.mkdir()
    (project / "s.py").write_text("print()\n", encoding="utf-8")
    # 3.13+ on Windows: whole only with a drive and a root - `\proj\s.py` is not, the server reads
    # it on its drive
    monkeypatch.setattr(os.path, "isabs", lambda p: bool(
        PureWindowsPath(p).drive and PureWindowsPath(p).root))
    rooted = os.path.splitdrive(project / "s.py")[1]
    assert list(mcp_client.in_project([sys.executable, rooted], [project]))


def nested(levels):
    schema = {"type": "string"}
    for _ in range(levels):
        schema = {"type": "object", "properties": {"p": schema}}
    return schema


def test_what_is_kept_of_a_tool_can_always_be_shown(make_client, tmp_path):
    most = max(n for n in range(1, 40)
               if mcp_client._depth(nested(n)) <= mcp_client.MAX_SCHEMA_DEPTH)
    client, _ = make_client([text("x")])
    made, _, _ = server(client, tmp_path, more=[
        {"name": "deepest", "description": "x", "inputSchema": nested(most)},
        {"name": "too_deep", "description": "x", "inputSchema": nested(most + 1)},
        # a hundred levels: 736 characters, far under what a schema may have
        {"name": "hundred", "description": "x", "inputSchema": nested(50)},
        # a direction turned round, a character without width, a bell, half a pair
        {"name": "odd", "description": "a\u202eb\u200bc\x07d\ne\tf \ud83d", "inputSchema": NOTHING}])
    by = {tool["name"]: tool for tool in made["tools"]}
    assert by["deepest"]["unusable"] is None and by["deepest"]["input_schema"] == nested(most)
    for name in ("too_deep", "hundred"):
        assert by[name]["unusable"] == "its input schema is nested deeper than 32 levels"
        assert by[name]["input_schema"] == {} and by[name]["chars"] is None
    assert by["odd"]["description"] == "abcd\ne\tf ?"
    assert client.get("/api/mcp-servers").status_code == 200
    # what a tool's inputs are is the server's word too, and is said to be
    assert mcp_client.schema("fake", by["deepest"])["function"]["description"].startswith(
        'Tool of the MCP server "fake", which the user added. Its description and inputs follow')


def test_inputs_that_hold_what_does_not_show_are_not_kept_and_not_offered(make_client, tmp_path):
    """A tool's inputs are shown on the page as JSON, in which such a character cannot be
    seen, and are handed to the model as the server wrote them - "Runs without asking"
    would be said of what the user did not see. Not cleaned, as a description is: that
    would rewrite a schema's keys."""
    hidden = {
        "title": {**NOTHING, "title": "T" + TURNED + TAG},
        "key": {"type": "object", "properties": {"p" + NO_WIDTH: {"type": "string"}}},
        "nested": {"type": "object", "properties": {"p": {
            "type": "string", "description": "a path" + TAG + TAG}}},
        "parted": {"type": "object", "properties": {"p": {"description": "one" + LINE + "two"}}},
        # controls that JSON writes as they are
        "controls": {**NOTHING, "description": "a" + chr(0x7f) + chr(0x9b)},
    }
    client, _ = make_client([text("x")])
    made, _, _ = server(client, tmp_path, more=[
        *({"name": name, "description": "x", "inputSchema": schema}
          for name, schema in hidden.items()),
        # a line end and a tab JSON writes out itself, where they are seen: kept; and of a
        # description the separators of lines and paragraphs are dropped like the rest
        {"name": "plain", "description": "one" + LINE + "two" + PARAGRAPH + "three",
         "inputSchema": {"type": "object", "properties": {"p": {"description": "1\n2\t3 é"}}}}])
    by = {tool["name"]: tool for tool in made["tools"]}
    for name in hidden:
        assert (by[name]["unusable"], by[name]["input_schema"], by[name]["chars"]) == (
            UNSEEN_INPUTS, {}, None), name
    assert by["plain"]["unusable"] is None and by["plain"]["description"] == "onetwothree"
    assert by["plain"]["input_schema"]["properties"]["p"]["description"] == "1\n2\t3 é"
    # where leave is asked the separators are written out, as what turns the text round is
    assert mcp_client.visible(f"a{LINE}{PARAGRAPH}b") == (
        "a" + (LINE + PARAGRAPH).encode("unicode_escape").decode() + "b")


def test_a_number_that_is_not_one_keeps_no_tool_and_fails_no_step(
    make_client, wait_run, project_dir, tmp_path
):
    """1e999 is JSON, and is read as infinity (NaN and Infinity are read too): a request to
    a model's server cannot be made of one, so every step of an agent that had such a tool
    failed - and said the model's server was at fault."""
    listed = tmp_path / "tools.json"                     # as a server writes it: not Python's words
    listed.write_text(
        '[{"name": "echo", "description": "x", "inputSchema": {"type": "object", '
        '"properties": {"text": {"type": "string"}, "n": {"type": "number"}}}}, '
        '{"name": "huge", "description": "x", "inputSchema": {"type": "object", '
        '"properties": {"n": {"type": "number", "maximum": 1e999}}}}, '
        '{"name": "none", "description": "x", "inputSchema": {"type": "object", "default": NaN}}, '
        '{"name": "less", "description": "x", "inputSchema": {"type": "object", '
        '"properties": {"n": {"minimum": -Infinity}}}}]', encoding="utf-8")
    lists = ('print(\'{"jsonrpc": "2.0", "id": %d, "result": {"tools": %s}}\' % (mid, open('
             + repr(str(listed)) + ').read()), flush=True)')
    # ...and one in a result, beside its text: in a part that is no text, and elsewhere
    answers = ('say({"id": mid, "result": {"content": [{"type": "text", "text": "fine"}, '
               '{"type": "text", "text": 1e999}], "structuredContent": {"n": float("nan")}}})')
    client, model = make_client([
        step(call("odd__echo", {"text": "hi"}, "a")),
        # in a model's arguments: not sent - no server can be sent it as JSON - and not asked about
        step(ToolCallRequest("b", "odd__echo", '{"text": "hi", "n": 1e999}')),
        step(ToolCallRequest("c", "odd__echo", '{"text": "hi", "n": [NaN]}')), text("done")])
    made = added(client, "odd", peer(tmp_path, answers, listing=lists))
    by = {tool["name"]: tool for tool in made["tools"]}
    assert by["echo"]["unusable"] is None and by["echo"]["chars"]
    for name in ("huge", "none", "less"):
        assert (by[name]["unusable"], by[name]["input_schema"], by[name]["chars"]) == (
            NOT_FINITE, {}, None), name
    assert client.get("/api/mcp-servers").status_code == 200    # and the page still comes
    give(client, "Lead", "odd")
    cid, run_id = begin(client, project_dir, mode="ask")
    (question,) = wait_status(client, cid, "waiting_approval")["questions"]
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "Allow"})
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert len(snap["questions"]) == 1                   # the other two calls were never asked about
    first, *refused = [(t["status"], t["result"]) for t in snap["tool_calls"]]
    assert first[0] == "succeeded" and "\nfine\n[text: not shown]\n" in first[1]
    assert refused == [("failed", "error: the arguments hold a number that is not finite "
                        "(NaN, Infinity)")] * 2
    # what the model was offered at each step can be written as a request to its server
    assert [names(tools)[-1] for tools in model.tool_args] == ["odd__echo"] * 4
    json.dumps([model.tool_args, model.calls], allow_nan=False)


@pytest.mark.parametrize("kept", [
    {"description": "x", "input_schema": nested(200)},  # (deeper than pydantic shows on Linux too)
    {"description": "half \ud83d", "input_schema": NOTHING},
    {"description": "x"},                                # not a tool as one is kept
])
def test_a_server_whose_kept_tools_cannot_be_shown_is_still_listed_and_can_be_deleted(
    make_client, tmp_path, kept
):
    """Kept by a reading from before what is kept was cleaned: the page must still come."""
    client, _ = make_client([text("x")])
    server(client, tmp_path, name="other")
    made, _, _ = server(client, tmp_path)
    with client.app.state.session_factory() as session:
        row = session.scalar(select(McpServer).where(McpServer.name == "fake"))
        row.tools = [{"name": "old", "unusable": None, "mark": "free", **kept}]
        session.commit()
    listed = client.get("/api/mcp-servers")
    assert listed.status_code == 200, listed.text
    other, one = listed.json()
    assert len(other["tools"]) == 8 and other["read_error"] is None
    assert (one["name"], one["tools"], one["read_error"]) == ("fake", [], UNSHOWN)
    # where the last reading failed, why it did is what the page says
    with client.app.state.session_factory() as session:
        row = session.scalar(select(McpServer).where(McpServer.name == "fake"))
        row.read_error = "The server ended without an answer."
        session.commit()
    again = client.get("/api/mcp-servers").json()[1]
    assert (again["tools"], again["read_error"]) == ([], "The server ended without an answer.")
    assert client.delete(f"/api/mcp-servers/{one['id']}").status_code == 204


# --- what the user is shown where they give leave ----------------------------------------------


def test_the_question_is_kolonis_own_and_shows_what_is_sent(
    make_client, wait_run, project_dir, tmp_path
):
    sent = {"text": "safe\u202e\u200b\x1b é ş"}           # turned round, no width, a control
    client, _ = make_client([step(call("fake__echo", sent)), text("done")])
    _made, record, _ = server(client, tmp_path)
    give(client, "Lead", "fake")
    cid, run_id = begin(client, project_dir, mode="ask")
    question = wait_status(client, cid, "waiting_approval")["questions"][0]
    assert question["leave"] is True and question["options"] == ["Allow", "Deny"]
    # what does not show is written out; other letters are left to be read
    assert r'{"text": "safe\u202e\u200b\u001b é ş"}' in question["question"]
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "Allow"})
    wait_run(client, cid, run_id, timeout=LONG)
    assert [e["arguments"] for e in events(record, "call")] == [sent]   # sent as it was


# --- an agent is told the path of the folder it works in ---------------------------------------

WRITES = {"path": "a.txt", "content": "A"}
THE_FOLDER = "so give them full paths. The folder you work in has the full path {}\n"
THE_COPY = (" The copy's full path is {}: give the tools of MCP servers full paths under it, "
            "not under the project folder.")


def copy_of(client, snap, name):
    """Where the working copy of this agent was."""
    agent = next(a for a in snap["agents"] if a["name"] == name)
    return copies.folder(client.app.state.settings.runtime_root) / agent["id"] / copies.TREE


def test_a_sub_agent_in_a_copy_is_told_its_copys_path_and_a_lead_the_projects(
    make_client, wait_run, project_dir, tmp_path
):
    """A sub-agent that has changed a file works in a copy of its own from then on. Told
    the project's path, a server's tool it points at that file would read it as it was -
    and one that writes would write past the copy, into the project itself."""
    client, model = make_client({
        "Lead": [spawn("Coder", "do it"), step(call("fake__echo", {"text": "hi"}, "e")),
                 text("done")],
        "Coder": [step(call("write_file", WRITES, "w")), step(call("fake__where", {}, "m")),
                  text("did it")]})
    server(client, tmp_path, free=True)
    give(client, "Lead", "fake")
    give(client, "Coder", "fake")
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    copy = copy_of(client, snap, "Coder")
    before, *after = (request[0]["content"] for request in model.calls_of["Coder"])
    # until it has a copy it works in the project; from the step after, in the copy
    assert THE_FOLDER.format(project_dir) in before and str(copy) not in before
    for told in after:
        assert THE_FOLDER.format(copy) in told and THE_FOLDER.format(project_dir) not in told
    # and with the change that made the copy, where the rest of it is said
    assert calls(snap)["write_file"][1].endswith(THE_COPY.format(copy))
    # the lead works in the project, also after its sub-agent has a copy
    for request in model.calls_of["Lead"]:
        assert THE_FOLDER.format(project_dir) in request[0]["content"]
        assert str(copy) not in request[0]["content"]


def test_a_cli_session_in_a_copy_is_told_its_copys_path_when_the_copy_is_made(
    session_app, wait_run, project_dir, tmp_path  # noqa: F811
):
    """Its instructions are written once, before it has a copy: the copy's path follows with
    the note of the copy. (What an agent without a server is told there is pinned whole in
    tests/test_copy_runner.py: nothing of a path.)"""
    client, provider, _ = session_app(
        [{"call": "write_file", "args": WRITES}, {"call": "fake__where", "args": {}},
         {"say": "did it"}],
        default_steps={"Lead": [spawn("Coder", "do it"), text("done")]})
    server(client, tmp_path, free=True)
    give(client, "Lead", "fake")
    give(client, "Coder", "fake")
    client.patch(f"/api/roles/{role_id(client, 'Coder')}", json={"provider_id": provider["id"]})
    cid, run_id = begin_on(client, project_dir, None, "full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    wrote = calls(snap)["write_file"][1]
    assert "From here on you work in a copy of the project of your own" in wrote
    assert wrote.endswith(THE_COPY.format(copy_of(client, snap, "Coder")))
    seen = session_app.record()
    assert seen["results"][0]["content"][0]["text"] == wrote and "fake__where" in seen["tools"]
    told = json.loads(seen["stdin"][seen["stdin"].index("\n\n{") + 2:])["instructions"]
    assert THE_FOLDER.format(project_dir) in told   # where it worked when they were written


def test_migration_0036_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0035")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO questions (id, run_id, agent_id, tool_call_id, question, options, "
            "status, created_at) VALUES ('q', 'r', 'a', 't', 'Which?', '[]', 'pending', "
            "'2026-10-13 10:00:00')")
    command.upgrade(cfg, "0036")
    with sqlite3.connect(db) as conn:
        # a question from before is shown as an agent's own
        assert conn.execute("SELECT leave FROM questions").fetchall() == [(0,)]
    command.downgrade(cfg, "0035")
    with sqlite3.connect(db) as conn:
        assert "leave" not in [row[1] for row in conn.execute("PRAGMA table_info(questions)")]
        assert conn.execute("SELECT question FROM questions").fetchall() == [("Which?",)]
