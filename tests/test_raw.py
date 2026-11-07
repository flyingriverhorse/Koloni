"""The raw stream of an agent's CLI (`app.raw`), and the readers that feed it: what is kept
and what is not, what is hidden, and that a CLI's error output is read line by line without
changing what is said of a CLI that failed."""

import asyncio
import json
import logging
import sys
import time
import uuid
from pathlib import Path

import pytest

from app import model_cli, raw
from app.config import load_settings
from app.main import NoRawStreamReads, create_app
from app.model_cli import (
    ERRORS_KEPT,
    ClaudeCliClient,
    CodexSearch,
    _brief,
    complaints,
)
from app.model_client import ModelUnavailable
from app.model_native import CodexNativeClient
from app.model_session import ClaudeSessionClient
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_model_cli import cli, step  # noqa: F401  (a fixture)
from tests.test_model_session import FAKE as FAKE_SESSION
from tests.test_model_session import MESSAGES, run
from tests.test_native_agent import FAKE as FAKE_NATIVE
from tests.test_session_agent import start
from tests.test_spawn import role_id

pytestmark = pytest.mark.anyio

KEY = "sk-ant-SECRET-0123456789abcdef"
BRIDGE_KEY = "bridge-key-0123456789abcdefghijklmn"


@pytest.fixture
def agent():
    return uuid.uuid4().hex  # the backlogs outlive a test: each has an agent of its own


@pytest.fixture
def knows(monkeypatch):
    """Says which secrets KOLONİ knows, for this test."""
    known: list[str | None] = []
    monkeypatch.setattr(raw, "_source", lambda: list(known))
    monkeypatch.setattr(raw, "_secrets", [])
    monkeypatch.setattr(raw, "_read_at", 0.0)
    return known


def texts(agent_id, stream=None, **asked):
    kept = raw.read(agent_id, **asked)
    return [line["text"] for line in kept["lines"] if stream in (None, line["stream"])]


def everything(agent_id):
    """All the lines kept for an agent, asked for answer by answer; and how many are gone."""
    lines, told = [], raw.read(agent_id)
    while told["more"]:
        lines += told["lines"]
        told = raw.read(agent_id, lines[-1]["n"])
    return lines + told["lines"], told["dropped"]


async def work(client, root):
    """A run of a CLI that works with its own tools, with nobody listening."""
    async def nothing(*_):
        return None

    return await client.run_native("m", MESSAGES, [], str(root), nothing, nothing, nothing)


# --- what is kept -------------------------------------------------------------------------


def test_the_numbers_go_on_over_the_runs_of_a_cli_and_nobodys_lines_are_not_kept(agent, knows):
    raw.feed("stdout", "said for nobody\n")  # a provider being tried out, say
    assert raw.read(agent) is None
    with raw.of(agent):
        raw.feed("stdout", '{"type": "init"}\r\n')
        raw.feed("stderr", "a warning\n")
        with raw.of(None):  # a CLI asked to search the web, inside the agent's own work
            raw.feed("stdout", "a search's line\n")
    with raw.of(agent):  # the next run of its CLI
        raw.feed("stdout", "not json at all")
    assert raw.read(agent) == {"dropped": 0, "more": False, "lines": [
        {"n": 1, "stream": "stdout", "text": '{"type": "init"}'},
        {"n": 2, "stream": "stderr", "text": "a warning"},
        {"n": 3, "stream": "stdout", "text": "not json at all"}]}
    assert texts(agent, after=2) == ["not json at all"] and texts(agent, after=3) == []


async def test_a_million_empty_lines_take_no_more_room_than_any_other_backlog(agent, knows):
    with raw.of(agent):
        await read_errors(b"\n" * 1_000_000, b"x\n" * 300_000)  # as its error output brings them
        for _ in range(raw.MAX_LINES + 500):  # and one at a time, as its output does
            raw.feed("stdout", "")
    kept = raw._agents[agent]
    assert kept.written == 1_300_000 + raw.MAX_LINES + 500
    assert len(kept.lines) == raw.MAX_LINES and kept.size <= raw.MAX_BYTES
    assert raw.read(agent)["dropped"] == 1_300_000 + 500
    # what Python really spends on them is about what they are charged for
    really = sum(sys.getsizeof(part) for line in kept.lines for part in (line, line[0], line[2]))
    assert really <= raw.MAX_BYTES * 1.1
    # ...and so it is with lines of some length: the room is what bounds them
    with raw.of(agent):
        raw.feed_lines("stderr", [b"y" * 200] * 20_000)
    assert 3000 < len(kept.lines) < 4000 and kept.size <= raw.MAX_BYTES
    really = sum(sys.getsizeof(part) for line in kept.lines for part in (line, line[0], line[2]))
    assert really <= raw.MAX_BYTES * 1.1


def test_one_answer_carries_only_so_many_lines_and_the_rest_is_had_by_asking_again(agent, knows):
    with raw.of(agent):
        raw.feed_lines("stdout", [b"line %d" % n for n in range(1, 5001)])
    first = raw.read(agent)
    assert (len(first["lines"]), first["lines"][0]["n"], first["more"]) == (
        raw.ANSWER_LINES, 1, True)
    lines, dropped = everything(agent)
    assert [line["n"] for line in lines] == list(range(1, 5001)) and dropped == 0
    assert lines[-1]["text"] == "line 5000"
    assert raw.read(agent, 5000) == {"dropped": 0, "more": False, "lines": []}
    # A number it has no line of: it was forgotten and began again. From its first line.
    assert raw.read(agent, 9999)["lines"][0]["n"] == 1


async def test_a_flood_of_short_lines_is_taken_reading_by_reading_not_line_by_line(agent, knows):
    errors = asyncio.StreamReader(limit=2**24)
    errors.feed_data(b"ab\n" * 5_000_000)
    errors.feed_eof()
    began = time.perf_counter()
    with raw.of(agent):
        await complaints(errors)
    took = time.perf_counter() - began
    kept = raw._agents[agent]
    assert kept.written == 5_000_000 and kept.lines[-1] == (5_000_000, "stderr", b"ab")
    # (Measured: half a second; line by line it was five to eight.)
    assert took < 3.0, f"{took:.1f} s for five million short lines"


def test_a_line_too_long_is_cut_where_it_shows_and_a_secret_across_the_cut_is_hidden(
    agent, knows
):
    knows.append(KEY)
    start = "x" * (raw.LINE_CHARS - 10)
    with raw.of(agent):
        raw.feed("stdout", start + KEY + "y" * 5000)
    (line,) = texts(agent)
    assert line == (start + "***" + "y" * 5000)[:raw.LINE_CHARS] + raw.CUT
    assert KEY[:12] not in line


def test_with_too_many_agents_the_one_silent_longest_goes_but_never_one_at_work(
    monkeypatch, knows
):
    first, second, third = (uuid.uuid4().hex for _ in range(3))
    monkeypatch.setattr(raw, "_agents", type(raw._agents)())
    monkeypatch.setattr(raw, "MAX_AGENTS", 2)
    with raw.of(first):
        raw.feed("stdout", "the lead's")
        with raw.of(second):
            raw.feed("stdout", "a sub-agent's")
        with raw.of(third):
            raw.feed("stdout", "another's")
    # the oldest is still at work: the one that ended goes
    assert raw.read(second) is None
    assert texts(first) == ["the lead's"] and texts(third) == ["another's"]


def test_after_is_a_number_from_zero_up(client):
    assert client.get("/api/agents/nobody/raw", params={"after": -1}).status_code == 422
    assert client.get("/api/agents/nobody/raw", params={"after": 0}).status_code == 404


# --- what is hidden -----------------------------------------------------------------------


def test_a_secret_is_hidden_as_it_is_and_as_json_writes_it_and_a_short_one_is_not_looked_for(
    agent, knows
):
    odd = 'pass"word\\with ç & more'
    knows += [KEY, "short", None, odd, "https://hooks.example/T0/B1"]
    with raw.of(agent):
        raw.feed("stdout", f"ANTHROPIC_API_KEY={KEY} and a short word")
        raw.feed("stdout", json.dumps({"output": f"token: {odd}"}))
        raw.feed("stdout", json.dumps({"output": odd}, ensure_ascii=False))
        raw.feed("stdout", json.dumps({"o": odd}).replace("&", "\\u0026"))  # as Go writes it
        raw.feed("stderr", "POST http://127.0.0.1:8790/api/hooks/AbC_123-xyz failed")
        raw.feed("stdout", "the session's key is abcdefgh12345678", ("abcdefgh12345678",))
        # as a JSON writer that escapes the slashes puts them: a hook's address, and a secret
        raw.feed("stdout", r'{"url": "http:\/\/127.0.0.1:8790\/api\/hooks\/AbC_123-xyz"}')
        raw.feed("stdout", r'{"notify": "https:\/\/hooks.example\/T0\/B1"}')
    assert texts(agent) == [
        "ANTHROPIC_API_KEY=*** and a short word",
        '{"output": "token: ***"}',
        '{"output": "***"}',
        '{"o": "***"}',
        "POST http://127.0.0.1:8790/api/hooks/*** failed",
        "the session's key is ***",
        r'{"url": "http:\/\/127.0.0.1:8790\/api\/hooks\/***"}',
        '{"notify": "***"}',
    ]


def test_a_secret_that_became_known_later_is_hidden_from_then_on_and_in_what_was_kept(
    agent, knows
):
    with raw.of(agent):
        raw.feed("stdout", f"before: {KEY}")
        knows.append(KEY)  # a provider added while the CLI runs
        raw.feed("stdout", f"at once after: {KEY}")
        # what is read never shows it, however fresh the secrets a line was kept with
        assert texts(agent) == ["before: ***", "at once after: ***"]
        raw.feed("stdout", f"after: {KEY}")
    assert raw._agents[agent].lines[-1][2] == b"after: ***"  # not kept at all any more


def test_secrets_that_cannot_be_read_do_not_break_the_run_a_line_came_in(
    agent, knows, monkeypatch
):
    knows.append(KEY)
    with raw.of(agent):
        raw.feed("stdout", f"first: {KEY}")
        monkeypatch.setattr(raw, "_source", lambda: 1 / 0)
        monkeypatch.setattr(raw, "_read_at", 0.0)
        raw.feed("stdout", f"second: {KEY}")  # kept, without the secrets known last
    assert [line[2] for line in raw._agents[agent].lines] == [b"first: ***", b"second: ***"]
    with pytest.raises(ZeroDivisionError):
        raw.read(agent)  # and nothing is shown while what to hide is not known


# --- the readers --------------------------------------------------------------------------


async def read_errors(*chunks: bytes) -> bytes:
    """What `complaints` returns for error output that comes in these pieces."""
    errors = asyncio.StreamReader()
    reading = asyncio.ensure_future(complaints(errors))
    for chunk in chunks:
        errors.feed_data(chunk)
        await asyncio.sleep(0.01)  # read before the next piece comes
    errors.feed_eof()
    return await reading


async def test_error_output_is_handed_on_line_by_line_and_returned_as_it_was(agent, knows):
    said = "uyarı: ağ yavaş\r\n\r\nfatal: not signed in\nno line end".encode()
    with raw.of(agent):
        # (in pieces that end inside a letter, and inside a line)
        assert await read_errors(said[:5], said[5:30], said[30:]) == said
    assert texts(agent, "stderr") == ["uyarı: ağ yavaş", "", "fatal: not signed in", "no line end"]
    assert texts(agent, "stdout") == []


async def test_a_line_with_no_end_is_not_waited_for_and_only_the_end_is_kept_to_say_why(
    agent, knows
):
    endless = b"x" * 3_000_000
    with raw.of(agent):
        # of more than is kept: its end, as it came - also where that begins inside a line
        assert await read_errors(
            endless[:1_000_000], endless[1_000_000:], b"\nfatal: gave up\n"
        ) == (endless + b"\nfatal: gave up\n")[-ERRORS_KEPT:]
        # all one line: its end
        assert await read_errors(endless) == endless[-ERRORS_KEPT:]
    cut, last, again = texts(agent)
    assert cut == again == "x" * raw.LINE_CHARS + raw.CUT and last == "fatal: gave up"


@pytest.mark.parametrize("said, its_end", [
    ('starting\n{"error":"' + "q" * 200_000 + ' rate limit reached"}\n', 'rate limit reached"}'),
    ("y" * 70_000 + "\nError: X", "yyy Error: X"),
], ids=["a last line longer than is kept", "a line before the last that the cut falls in"])
async def test_why_a_cli_failed_is_said_as_before_however_long_its_last_lines_are(
    said, its_end, agent, knows, tmp_path
):
    script = tmp_path / "fails.py"
    script.write_text(
        "import sys\n"
        "sys.stdin.readline()\n"  # (a line: Codex's app-server is never sent the end of it)
        f"sys.stderr.buffer.write({said.encode()!r})\n"
        "sys.exit(3)\n", encoding="utf-8")
    fails = {"timeout": 20.0, "launcher": [sys.executable, str(script)]}
    why = _brief(said)  # what was said when all of its error output was read in one piece
    assert why.endswith(its_end) and len(why) == model_cli.ERROR_CHARS
    with raw.of(agent):
        for label, reader in (
            ("Claude Code", lambda: step(ClaudeCliClient(**fails))),
            ("Claude Code", lambda: run(ClaudeSessionClient(**fails))),
            ("Codex", lambda: work(CodexNativeClient(**fails), tmp_path)),
        ):
            with pytest.raises(ModelUnavailable) as failed:
                await reader()
            assert str(failed.value) == f"{label} exited with code 3: {why}"


async def test_a_cli_that_floods_its_error_output_ends_and_why_it_failed_reads_as_before(
    agent, knows, tmp_path
):
    script = tmp_path / "floods.py"
    script.write_text(
        "import sys\n"
        "sys.stdin.read()\n"
        "for i in range(60000):\n"
        "    sys.stderr.write(f'warning {i}: ' + 'w' * 80 + '\\n')\n"
        "sys.stderr.write('fatal: the disk is full\\nfatal: giving up\\n')\n"
        "sys.exit(3)\n", encoding="utf-8")
    client = ClaudeCliClient(timeout=60.0, launcher=[sys.executable, str(script)])
    whole = "".join(f"warning {i}: " + "w" * 80 + "\n" for i in range(60000))
    whole += "fatal: the disk is full\nfatal: giving up\n"
    with raw.of(agent), pytest.raises(ModelUnavailable) as failed:
        await step(client)
    assert str(failed.value) == f"Claude Code exited with code 3: {_brief(whole)}"
    lines, dropped = everything(agent)
    assert dropped > 50000 and lines[0]["n"] == dropped + 1 and lines[-1] == {
        "n": 60002, "stream": "stderr", "text": "fatal: giving up"}


async def test_a_line_of_error_output_is_there_while_the_cli_that_wrote_it_still_runs(
    agent, knows, tmp_path
):
    go = tmp_path / "go"
    script = tmp_path / "waits.py"
    script.write_text(
        "import pathlib, sys, time\n"
        "sys.stdin.read()\n"
        "sys.stderr.write('warning: still at it\\n')\n"
        "sys.stderr.flush()\n"
        f"while not pathlib.Path({str(go)!r}).exists():\n"
        "    time.sleep(0.02)\n"
        "sys.exit(3)\n", encoding="utf-8")
    with raw.of(agent):
        stepping = asyncio.ensure_future(
            step(ClaudeCliClient(timeout=30.0, launcher=[sys.executable, str(script)])))
    deadline = time.monotonic() + 20
    while raw.read(agent) is None:
        assert time.monotonic() < deadline and not stepping.done()
        await asyncio.sleep(0.02)
    assert texts(agent) == ["warning: still at it"]
    assert not stepping.done() and not go.exists()  # its CLI has not ended, nor was told to
    go.write_text("", encoding="utf-8")
    with pytest.raises(ModelUnavailable) as failed:
        await stepping
    assert str(failed.value) == "Claude Code exited with code 3: warning: still at it"


async def test_a_line_without_an_end_is_there_after_a_moment_and_a_carriage_return_ends_one(
    agent, knows, monkeypatch
):
    monkeypatch.setattr(model_cli, "OPEN_SECONDS", 0.05)
    errors = asyncio.StreamReader()
    with raw.of(agent):
        reading = asyncio.ensure_future(complaints(errors))
    said = [b"Password: ", b"\n10%\r", b"50%\r100%\r", b"\ndone", b" at last\r\n"]
    seen = []
    # (a pause after a line without an end; none where a reading ends with a line's end)
    for piece, pause in zip(said, (0.3, 0.01, 0.01, 0.3, 0.01), strict=True):
        errors.feed_data(piece)
        await asyncio.sleep(pause)
        seen.append(texts(agent))
    errors.feed_eof()
    assert await reading == b"".join(said)  # what says why it failed is as it came
    assert seen == [
        ["Password: "],  # a prompt: before any line end, and long before the end
        ["Password: ", "10%"],  # the prompt's own end is no line more
        ["Password: ", "10%", "50%", "100%"],  # a progress line
        ["Password: ", "10%", "50%", "100%", "done"],  # "\r\n" in two readings is one end
        ["Password: ", "10%", "50%", "100%", "done", " at last"],
    ]


async def test_a_cli_run_step_by_step_feeds_every_run_and_says_why_it_failed_as_before(
    agent, knows, cli  # noqa: F811
):
    make, _ = cli
    with raw.of(agent):
        await step(make(ClaudeCliClient))
        first = len(texts(agent))
        await step(make(ClaudeCliClient))
        with pytest.raises(ModelUnavailable) as failed:
            await step(make(ClaudeCliClient, mode="exit"))
    assert str(failed.value) == (
        "Claude Code exited with code 3: warming up not signed in: run the login command")
    kept = raw.read(agent)["lines"]
    assert [line["n"] for line in kept] == list(range(1, 2 * first + 3))
    assert first > 0 and {line["stream"] for line in kept[:2 * first]} == {"stdout"}
    assert json.loads(kept[first - 1]["text"])["type"] == "result"
    assert [(line["stream"], line["text"]) for line in kept[2 * first:]] == [
        ("stderr", "warming up"), ("stderr", "not signed in: run the login command")]


async def test_a_cli_run_as_a_session_feeds_what_it_wrote_with_what_nobody_reads(
    agent, knows, tmp_path
):
    def make(script):
        plan = tmp_path / "plan.json"
        plan.write_text(json.dumps({"record": str(tmp_path / "record.json"), "script": script}),
                        encoding="utf-8")
        return ClaudeSessionClient(timeout=20.0, launcher=FAKE_SESSION,
                                   env={"FAKE_CLI_PLAN": str(plan)})

    with raw.of(agent):
        await run(make([{"emit": {"type": "nobody_knows", "n": 1}}, {"say": "hello"}]))
        with pytest.raises(ModelUnavailable) as failed:
            await run(make([{"exit": 3, "stderr": "Error: not signed in"}]))
    assert str(failed.value) == "Claude Code exited with code 3: Error: not signed in"
    kept = raw.read(agent)["lines"]
    events = [json.loads(line["text"]).get("type") for line in kept if line["stream"] == "stdout"]
    assert events[0] == "system" and "nobody_knows" in events and "result" in events
    assert [line["text"] for line in kept if line["stream"] == "stderr"] == [
        "Error: not signed in"]


async def test_a_cli_asked_to_search_the_web_is_in_no_agents_raw_stream(agent, knows, tmp_path):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({
        "record": str(tmp_path / "record.json"), "searched": "search",
        "answer": {"results": [{"title": "T", "url": "https://example.org/", "snippet": "s"}]},
    }), encoding="utf-8")
    fake = [sys.executable, str(Path(__file__).with_name("fake_cli.py"))]
    searcher = CodexSearch(timeout=20.0, launcher=fake, env={"FAKE_CLI_PLAN": str(plan)})
    with raw.of(agent):  # asked for by a tool of the agent's
        assert len(await searcher.search("py docs")) == 1
        raw.feed("stdout", "the agent's own CLI goes on")
    assert texts(agent) == ["the agent's own CLI goes on"]


async def test_the_key_a_run_reaches_kolonis_tools_with_is_in_no_raw_stream(
    agent, knows, tmp_path, monkeypatch
):
    # The key is made up anew for every run and kept nowhere: here it is one the test knows.
    monkeypatch.setattr("app.model_session.secrets.token_urlsafe", lambda _size: BRIDGE_KEY)

    def plan(script):
        written = tmp_path / "plan.json"
        written.write_text(json.dumps({"record": str(tmp_path / "record.json"), "script": script}),
                           encoding="utf-8")
        return {"timeout": 20.0, "env": {"FAKE_CLI_PLAN": str(written)}}

    gives_up = {"exit": 3, "stderr": f"the bridge refused {BRIDGE_KEY}"}
    with raw.of(agent):
        with pytest.raises(ModelUnavailable):
            await run(ClaudeSessionClient(launcher=FAKE_SESSION, **plan([
                {"emit": {"type": "debug", "env": f"KOLONI_MCP_KEY={BRIDGE_KEY}"}}, gives_up])))
        session = len(texts(agent))
        with pytest.raises(ModelUnavailable):
            await work(CodexNativeClient(launcher=FAKE_NATIVE, **plan([
                {"web": f"what is {BRIDGE_KEY}"}, gives_up])), tmp_path)
    for said in (texts(agent)[:session], texts(agent)[session:]):  # of the session, of the native run
        assert BRIDGE_KEY not in json.dumps(said)
        assert [line for line in said if "***" in line and "refused" not in line]  # its output
        assert "the bridge refused ***" in said  # its error output


# --- whose lines they are, in a turn ----------------------------------------------------------


def test_agents_at_work_at_once_and_a_sub_agent_under_its_opener_each_have_their_own_lines(
    settings_env, tmp_path, project_dir, wait_run
):
    go = tmp_path / "go"

    def cli_of(name, script, **more):
        plan = tmp_path / f"{name}.plan.json"
        plan.write_text(json.dumps({
            "record": str(tmp_path / f"{name}.record.json"), "script": script, **more}), encoding="utf-8")
        return ClaudeSessionClient(launcher=FAKE_SESSION, timeout=30,
                                   env={"FAKE_CLI_PLAN": str(plan)})

    def mark(who):
        return {"emit": {"type": "mark", "of": who}}

    # Three CLIs, each with a script of its own: the lead's opens the other two at once.
    clients = {
        "Lead CLI": cli_of("lead", [mark("lead"), {"parallel": [
            {"call": "spawn_agent", "args": {"role": "Coder", "task": "do A"}},
            {"call": "spawn_agent", "args": {"role": "Tester", "task": "do B"}}]},
            mark("lead again"), {"say": "Both started."}],
            # (Its calls come back at once, K-paralel-spawn: started again, it reads both reports.)
            later_script=[mark("lead read"), {"say": "Both done."}], later_when="B done"),
        "Coder CLI": cli_of("coder", [mark("coder"), {"wait_for": str(go)}, {"say": "A done"}]),
        "Tester CLI": cli_of("tester", [mark("tester"), {"wait_for": str(go)}, {"say": "B done"}]),
    }
    app = create_app(load_settings(settings_env), model=ScriptedModel([]), clients=clients)
    with TestClient(app, base_url="http://127.0.0.1:8790") as client:
        made = {}
        for name in clients:
            added = client.post("/api/providers", json={"name": name, "kind": "claude_cli"})
            assert added.status_code == 201, added.text
            made[name] = added.json()
        for role in ("Coder", "Tester"):
            client.patch(f"/api/roles/{role_id(client, role)}",
                         json={"provider_id": made[f"{role} CLI"]["id"]})

        def events(agent_id):
            told = client.get(f"/api/agents/{agent_id}/raw").json()["lines"]
            assert [line["n"] for line in told] == list(range(1, len(told) + 1))
            return [json.loads(line["text"]) for line in told if line["stream"] == "stdout"]

        def marks(agent_id):
            return [event["of"] for event in events(agent_id) if event["type"] == "mark"]

        cid, run_id = start(client, project_dir, made["Lead CLI"])
        deadline = time.monotonic() + 30
        while True:  # until both sub-agents' CLIs have written, and wait to be told to go on
            agents = {a["name"]: a for a in client.get(f"/api/conversations/{cid}").json()["agents"]}
            if all(name in agents and marks(agents[name]["id"]) for name in ("Coder", "Tester")):
                break
            assert time.monotonic() < deadline, agents
            time.sleep(0.02)
        # Both at work at the same time, under an opener whose own CLI still runs (K-paralel-spawn:
        # its calls came back at once, so it may have gone on): each has its own lines and nobody else's.
        lead = marks(agents["Lead"]["id"])
        assert lead[0] == "lead" and set(lead) <= {"lead", "lead again"}
        assert {name: marks(agents[name]["id"]) for name in ("Coder", "Tester")} == {
            "Coder": ["coder"], "Tester": ["tester"]}
        go.write_text("", encoding="utf-8")
        snap = wait_run(client, cid, run_id, timeout=30)
        assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
        assert {a["name"]: marks(a["id"]) for a in snap["agents"]} == {
            "Lead": ["lead", "lead again", "lead read"], "Coder": ["coder"], "Tester": ["tester"]}
        for one in snap["agents"]:  # one run of one CLI each - the Lead's two: its first line and its last
            kinds = [event["type"] for event in events(one["id"])]
            runs = 2 if one["name"] == "Lead" else 1
            assert (kinds[0], kinds[-1], kinds.count("system"), kinds.count("result")) == (
                "system", "result", runs, runs)


# --- the server's own log ----------------------------------------------------------------------


def test_an_answered_reading_of_a_raw_stream_is_not_in_the_access_log_and_any_other_is():
    def logged(method, address, status):
        return NoRawStreamReads().filter(logging.LogRecord(
            "uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
            ("127.0.0.1:50000", method, address, "1.1", status), None))

    assert not logged("GET", "/api/agents/0af3/raw?after=12", 200)
    assert not logged("GET", "/api/agents/0af3/raw", 200)
    assert logged("GET", "/api/agents/0af3/raw?after=12", 404)  # one that failed is
    assert logged("GET", "/api/agents/0af3/rawer", 200) and logged("GET", "/api/agents", 200)
    assert logged("POST", "/api/agents/0af3/approve", 200)
    assert NoRawStreamReads().filter(logging.LogRecord(
        "uvicorn.access", logging.INFO, "", 0, "started", None, None))
