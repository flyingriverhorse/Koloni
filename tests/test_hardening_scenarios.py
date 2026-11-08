"""Slice 36's acceptance set, the backend's part: what a general review found. Written before
the code.

A file that has another name outside the project is not written through. No "Always run" rule
is offered - or honoured - for a word that runs whatever it is given. A search pattern that
does not end is given up on, and the app goes on answering meanwhile. No answer may be put in
another page's frame. Reading a line of a large file does not take the file into memory.
"""

import dataclasses
import os
import time
import tracemalloc

import pytest

from app.config import Settings

if "search_seconds" not in {field.name for field in dataclasses.fields(Settings)}:
    pytest.skip("slice 36 is not built yet", allow_module_level=True)  # written before the code

from app.commands import matches, suggest_prefix  # noqa: E402
from tests.fakes import Script, ScriptedExecutor  # noqa: E402
from tests.test_agent_commands import cmd  # noqa: E402
from tests.test_agent_writes import edit, wait_status, write  # noqa: E402
from tests.test_chat_flow import start, start_in_mode, text  # noqa: E402
from tests.test_spawn import begin, call, step  # noqa: E402

ORIGIN = "http://127.0.0.1:8790"


# --- a file with another name outside the project ---------------------------------------------


def link(outside, inside):
    """Make `inside` another name of the file `outside` (a hard link)."""
    try:
        os.link(outside, inside)
    except OSError as exc:  # a file system without them
        pytest.skip(f"no hard links here: {exc}")


@pytest.mark.parametrize("mode", ["ask", "auto_edit", "full_auto"])
@pytest.mark.parametrize("change", [
    write("inside.txt", "changed\n"), edit("inside.txt", "outside", "changed")], ids=["write", "edit"])
def test_a_file_that_has_another_name_outside_the_project_is_not_written_through(
    make_client, wait_run, project_dir, tmp_path, mode, change
):
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside\n")
    link(outside, project_dir / "inside.txt")
    client, _model = make_client([change, text("It could not be written.")])
    cid, run_id = start_in_mode(client, project_dir, mode)
    # At every level the agent is told at once, and why: nothing is proposed that could
    # not be applied, and nobody is asked to approve it.
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (tool,) = snap["tool_calls"]
    assert tool["status"] == "failed" and "hard link" in tool["result"]
    assert snap["file_changes"] == []
    assert outside.read_bytes() == b"outside\n"
    assert (project_dir / "inside.txt").read_bytes() == b"outside\n"


def relinked(project_dir, tmp_path, name="hello.py"):
    """The project's file made, meanwhile, another name of a file outside that holds the
    very same text: nothing but the link is other than it was."""
    outside = tmp_path / f"outside-{name}"
    outside.write_bytes((project_dir / name).read_bytes())
    (project_dir / name).unlink()
    link(outside, project_dir / name)
    return outside, outside.read_bytes()


def test_a_change_that_waited_is_not_applied_through_a_link_made_meanwhile(
    make_client, project_dir, tmp_path
):
    client, _model = make_client([edit("hello.py", "hi", "hello"), text("done")])
    cid, _run_id = start(client, project_dir)                    # Ask: the change waits
    change = wait_status(client, cid, "waiting_approval")["file_changes"][0]
    outside, held = relinked(project_dir, tmp_path)
    answer = client.post(f"/api/file-changes/{change['id']}/approve")
    assert answer.status_code >= 400 or answer.json()["status"] != "applied"
    assert outside.read_bytes() == held == b"print('hi')\n"


def test_a_change_is_not_taken_back_through_a_link_made_meanwhile(
    make_client, wait_run, project_dir, tmp_path
):
    client, _model = make_client([edit("hello.py", "hi", "hello"), text("done")])
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    change = wait_run(client, cid, run_id)["file_changes"][0]
    assert change["status"] == "applied"
    outside, held = relinked(project_dir, tmp_path)
    answer = client.post(f"/api/file-changes/{change['id']}/revert")
    assert answer.status_code >= 400 or answer.json()["status"] != "reverted"
    assert outside.read_bytes() == held == b"print('hello')\n"


# --- "Always run" and the words that run what they are given ----------------------------------


@pytest.mark.parametrize("command", [
    "iex 'Get-Location'", "IEX 'Get-Location'", "Invoke-Expression 'Get-Location'",
    "icm 'Get-Location'", "Invoke-Command 'Get-Location'",
    "saps notepad", "Start-Process notepad",
    "sajb 'Get-Location'", "Start-Job 'Get-Location'",
    "ihy 3", "Invoke-History 3",
])
def test_no_rule_is_offered_or_honoured_for_a_word_that_runs_what_it_is_given(command):
    word = command.split()[0]
    assert suggest_prefix(command) == ""
    # a rule for the word - written by hand, or kept from before - covers nothing
    assert not matches(command, word) and not matches(command, word.lower())


def test_a_rule_for_such_a_word_runs_nothing_unasked(make_client, project_dir):
    executor = ScriptedExecutor([Script(["ran\n"])])
    client, _model = make_client(
        [cmd("iex 'Set-Content -LiteralPath only.txt marker'", id="k1"), text("done")],
        executor=executor)
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    # (refused when it is written, or kept and matching nothing: either way it runs nothing)
    written = client.post(f"/api/conversations/{cid}/allowed-commands", json={"prefix": "iex"})
    assert written.status_code in (200, 201, 422), written.text
    client.post(f"/api/conversations/{cid}/messages", json={"content": "set it"})
    command = wait_status(client, cid, "waiting_approval")["commands"][0]
    assert (command["status"], command["suggested_prefix"]) == ("proposed", "")
    assert executor.started == []


# --- a search pattern that does not end -------------------------------------------------------


def test_a_pattern_that_does_not_end_is_given_up_on_and_the_app_answers_meanwhile(
    make_client, wait_run, project_dir, settings_env
):
    settings_env["KOLONI_SEARCH_SECONDS"] = "4"
    (project_dir / "long.txt").write_text("a" * 29 + "!\n", encoding="utf-8")
    client, _model = make_client([
        step(call("search", {"pattern": "(a+)+$", "path": "."}, "s")),
        text("The pattern took too long.")])
    began = time.monotonic()
    cid, run_id = begin(client, project_dir, mode="full_auto")
    # While the search is at work the app is not held by it: another request is answered.
    at_work = False
    while time.monotonic() - began < 10 and not at_work:
        calls = client.get(f"/api/conversations/{cid}").json()["tool_calls"]
        at_work = bool(calls) and calls[0]["status"] in ("pending", "running")
        if calls and not at_work:
            break
        time.sleep(0.02)
    assert at_work, "the search was over before it could be seen at work"
    # (Not /api/health: it starts `docker version`, which under load took over the 1.5 s this
    # once allowed. Answered while the search still works is what "not held" is.)
    assert client.get("/api/projects").status_code == 200
    calls = client.get(f"/api/conversations/{cid}").json()["tool_calls"]
    assert calls[0]["status"] in ("pending", "running"), "answered only after the search"

    snap = wait_run(client, cid, run_id, timeout=90)
    (tool,) = snap["tool_calls"]
    assert tool["status"] == "failed" and "took too long" in tool["result"]
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert time.monotonic() - began < 30


# --- no answer in another page's frame --------------------------------------------------------


def test_no_answer_may_be_put_in_another_pages_frame(make_client):
    client, _model = make_client([])
    for path in ("/api/health", "/api/projects", "/api/nothing-here", "/"):
        answer = client.get(path)
        assert "frame-ancestors 'none'" in answer.headers.get("content-security-policy", ""), path
        assert answer.headers.get("x-frame-options") == "DENY", path


# --- reading a line of a large file -----------------------------------------------------------


def test_reading_a_line_of_a_large_file_does_not_take_the_file_into_memory(
    make_client, wait_run, project_dir
):
    (project_dir / "big.txt").write_bytes(b"0123456789abcdef\n" * 700_000)       # 11.9 MB
    client, model = make_client([
        step(call("read_file", {"path": "big.txt", "limit": 1}, "r")), text("done")])
    tracemalloc.start()
    try:
        cid, run_id = begin(client, project_dir, mode="full_auto")
        snap = wait_run(client, cid, run_id, timeout=60)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    (tool,) = snap["tool_calls"]
    assert tool["status"] == "succeeded" and "0123456789abcdef" in tool["result"]
    assert len(tool["result"]) < 500                  # one line, and what it says of the rest
    assert peak < 8_000_000, f"{peak:,} bytes at the most"
