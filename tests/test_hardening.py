"""Slice 36, beside its acceptance set: the paths the set leaves to the code - a sub-agent's
work taken in through a link, a search that is stopped or meets a file that is not text,
and reading at the edges of a file."""

import os
import re

import pytest

from app import copies
from app.tools import _search
from app.workspace import Workspace, WorkspaceError, has_other_names
from tests.conftest import Gate
from tests.test_chat_flow import text
from tests.test_claude_native import WRITE, claude_app  # noqa: F401 (a fixture)
from tests.test_claude_native import start as claude_start
from tests.test_hardening_scenarios import link
from tests.test_parallel import until
from tests.test_spawn import begin, call, step
from tests.test_take_in_scenarios import LINES, LONG, edit, lines, start

# --- a file with another name: not written through, also when work is taken in ---------------


def test_a_file_with_one_name_is_written_and_one_with_two_is_not(tmp_path):
    ws = Workspace(tmp_path)
    ws.write_text("one.txt", "a")
    assert not has_other_names(tmp_path / "one.txt")
    link(tmp_path / "one.txt", tmp_path / "two.txt")
    assert has_other_names(tmp_path / "one.txt") and has_other_names(tmp_path / "two.txt")
    with pytest.raises(WorkspaceError, match="hard link"):
        ws.write_text("two.txt", "b")
    assert (tmp_path / "one.txt").read_bytes() == b"a"
    # deleting one of the names leaves the other as it was (this slice does not change that)
    ws.delete("two.txt")
    assert (tmp_path / "one.txt").read_bytes() == b"a" and not has_other_names(tmp_path / "one.txt")


def test_a_copys_file_is_not_put_into_the_project_through_a_link(tmp_path):
    project, outside = tmp_path / "proj", tmp_path / "outside.bin"
    project.mkdir()
    (project / "blob.bin").write_bytes(b"\x00base")
    copy = copies.make(project, tmp_path / "runtime", "a1")
    (copy.root / "blob.bin").write_bytes(b"\x00agent")
    outside.write_bytes(b"\x00base")
    (project / "blob.bin").unlink()
    link(outside, project / "blob.bin")
    with pytest.raises(OSError, match="hard link"):
        copy.put("blob.bin")
    assert outside.read_bytes() == b"\x00base"
    # nor is the copy's own file written through one a command made there
    (copy.root / "blob.bin").unlink()
    link(outside, copy.root / "blob.bin")
    with pytest.raises(OSError, match="hard link"):
        copy.join("blob.bin", b"joined", b"\x00base")
    assert outside.read_bytes() == b"\x00base"


def test_a_sub_agents_work_is_not_taken_in_through_a_link_made_meanwhile(
    make_client, project_dir, tmp_path
):
    held = Gate()
    client, _pid, cid, _run_id = start(make_client, project_dir, [
        step(edit("two", "TWO-agent")), held.step(text("A done"))])
    held.wait_partial()
    # the project's file becomes another name of a file outside that holds the same text
    outside = tmp_path / "outside-lines.txt"
    outside.write_bytes(LINES.encode())
    (project_dir / "lines.txt").unlink()
    link(outside, project_dir / "lines.txt")
    held.release()
    # Full auto takes the work in by itself: this file is not written, and the card says why
    # and stays for the user, as for any file that could not be written.
    snap = until(client, cid, lambda s: any(
        "hard link" in (one.get("note") or "") for merge in s["merges"] for one in merge["files"]),
        timeout=LONG)
    assert [one["state"] for one in snap["merges"][0]["files"]] != ["applied"]
    assert outside.read_bytes() == LINES.encode()
    assert lines(project_dir) == LINES.split("\n")[:-1]
    assert "applied" not in [f["status"] for f in snap["file_changes"]]
    assert os.stat(project_dir / "lines.txt").st_nlink == 2


# --- reading line by line ---------------------------------------------------------------------


def as_before(text, offset=1, limit=2000):
    """read_file as it was before slice 36: the whole text, split by str.splitlines."""
    lines = text.splitlines()
    if not lines:
        return "[the file is empty]"
    rows, size = [], 0
    for number in range(offset, min(offset + limit - 1, len(lines)) + 1):
        line = lines[number - 1]
        if len(line) > 2000:
            line = f"{line[:2000]} [line truncated: {len(line)} characters]"
        row = f"{number:>6}\t{line}"
        size += len(row.encode("utf-8")) + 1
        if size > 256 * 1024 and rows:
            break
        rows.append(row)
    if not rows:
        return f"[no lines at offset {offset}; the file has {len(lines)} lines]"
    return "\n".join(rows) + f"\n[showing lines {offset}-{offset + len(rows) - 1} of {len(lines)}]"


TEXTS = {
    "empty": "",
    "one line, no end": "only",
    "no final line end": "a\nb\nc",
    "crlf": "a\r\nb\r\n\r\nc\r\n",
    "lone cr": "a\rb\r\rc",
    "only line ends": "\n\n\r\n",
    "what splitlines also splits on": "a\fb\vc\x1cd\x85e\u2028f\u2029g\n",
    "a bom and other letters": "\ufeffşğü\nçö€\n",
    "a long line": "x" * 5000 + "\nshort\n" + "y" * 2001,
    "wide": ("w" * 1000 + "\n") * 600,
}


@pytest.mark.parametrize("chunk", [1, 3, 64 * 1024], ids=["chunk 1", "chunk 3", "chunk 64k"])
@pytest.mark.parametrize("name", TEXTS)
def test_a_file_read_line_by_line_reads_as_the_whole_text_did(tmp_path, monkeypatch, name, chunk):
    from app import workspace
    from app.tools import run_read_tool

    monkeypatch.setattr(workspace, "READ_CHUNK", chunk)  # every line end across two pieces
    (tmp_path / "f.txt").write_bytes(TEXTS[name].encode("utf-8"))
    ws = Workspace(tmp_path)
    for offset, limit in ((1, 2000), (2, 1), (3, 2), (5, 10), (99, 1), (600, 5)):
        out = run_read_tool(ws, "read_file", {"path": "f.txt", "offset": offset, "limit": limit})
        # (The file's form, KOLONİ's last line since B-162, is not in the old text.)
        assert re.sub(r"\n\[the file: [^\]]*\]$", "", out) == as_before(
            TEXTS[name], offset, limit), (offset, limit)


def test_a_file_that_is_not_text_is_said_to_be_not_text(tmp_path):
    from app.tools import ToolError, run_read_tool

    (tmp_path / "late.bin").write_bytes(b"line\n" * 50_000 + b"\xff\n")
    with pytest.raises(ToolError, match="is not UTF-8 text"):
        run_read_tool(Workspace(tmp_path), "read_file", {"path": "late.bin", "limit": 1})


# --- a search is made in a process of its own -------------------------------------------------

BACKTRACKS = "(a+)+$"  # on "aaaa...!" it does not end in any time worth waiting for


def test_a_pattern_that_does_not_end_is_given_up_and_a_set_stop_ends_it(tmp_path):
    import threading
    import time

    (tmp_path / "long.txt").write_text("a" * 40 + "!\n", encoding="utf-8")
    ws = Workspace(tmp_path)
    began = time.monotonic()
    with pytest.raises(WorkspaceError, match="took too long"):
        ws.search(BACKTRACKS, seconds=0.5)
    assert time.monotonic() - began < 10
    stop = threading.Event()
    threading.Timer(0.3, stop.set).start()
    began = time.monotonic()
    with pytest.raises(WorkspaceError, match="stopped"):
        ws.search(BACKTRACKS, seconds=60, stop=stop)
    assert time.monotonic() - began < 10


def test_a_search_skips_what_is_not_text_and_says_what_it_says_today(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"needle here\r\nnothing\n  needle again  \n")
    (tmp_path / "b.bin").write_bytes(b"needle \xff\xfe\n")
    (tmp_path / "c.txt").write_bytes("şu needle".encode())
    (tmp_path / "d.txt").write_bytes(b"needle\n" * 40_000)  # (over 256 KB: counted, not read)
    (tmp_path / "e.png").write_bytes(b"\x89PNG\0" * 60_000)  # (a big binary: not even counted)
    ws = Workspace(tmp_path)
    assert ws.search("needle") == (
        [("a.txt", 1, "needle here"), ("a.txt", 3, "needle again"), ("c.txt", 1, "şu needle")],
        False, 0, ["d.txt"])
    assert "[1 file(s) over 256 KB not searched: d.txt — read_file" in _search(
        ws, {"pattern": "needle"}, 30, None)
    for n in range(6):  # (named, five at most)
        (tmp_path / f"f{n}.txt").write_bytes(b"x\n" * 140_000)
    assert ("[7 file(s) over 256 KB not searched: d.txt, f0.txt, f1.txt, f2.txt, f3.txt and 2 "
            "more — read_file") in _search(ws, {"pattern": "needle"}, 30, None)
    with pytest.raises(WorkspaceError, match="invalid regular expression"):
        ws.search("(")
    with pytest.raises(WorkspaceError, match="does not exist"):
        ws.search("x", "nowhere")


def test_stop_during_a_search_ends_the_search_and_the_turn_at_once(
    make_client, wait_run, project_dir, settings_env
):
    import time

    settings_env["KOLONI_SEARCH_SECONDS"] = "120"
    (project_dir / "long.txt").write_text("a" * 40 + "!\n", encoding="utf-8")
    client, _model = make_client([step(call("search", {"pattern": BACKTRACKS}, "s")), text("-")])
    cid, run_id = begin(client, project_dir, mode="full_auto")
    until(client, cid, lambda s: [c["status"] for c in s["tool_calls"]] == ["running"])
    stopped = time.monotonic()
    client.post(f"/api/runs/{run_id}/cancel")
    snap = wait_run(client, cid, run_id, timeout=10)
    assert time.monotonic() - stopped < 10                    # not the search's 120 seconds
    assert snap["runs"][0]["status"] == "cancelled"
    (tool,) = snap["tool_calls"]
    assert tool["status"] == "failed" and "stopped" in tool["result"]


# --- no answer in another page's frame, an error nobody caught too ---------------------------


def test_the_answer_to_an_error_nobody_caught_may_not_be_framed_either(settings):
    from app.main import create_app
    from tests.keyed import TestClient

    app = create_app(settings)

    def broken():
        raise RuntimeError("nobody caught this")

    app.add_api_route("/api/broken", broken)
    app.router.routes.insert(0, app.router.routes.pop())  # before a built page's catch-all
    with TestClient(app, base_url="http://127.0.0.1:8790", raise_server_exceptions=False) as client:
        answer = client.get("/api/broken")
        assert (answer.status_code, answer.text) == (500, "Internal Server Error")
        assert answer.headers["content-security-policy"] == "frame-ancestors 'none'"
        assert answer.headers["x-frame-options"] == "DENY"
        # and the answer to a host that is not allowed, which the app's own checks give
        refused = client.get("/api/health", headers={"Host": "evil.example"})
        assert refused.status_code == 400 and refused.headers["x-frame-options"] == "DENY"


# --- a CLI's own write tool is given no leave for such a file either --------------------------


@pytest.mark.parametrize("mode", ["ask", "full_auto"])
def test_claude_code_gets_no_leave_to_write_a_file_with_another_name(
    claude_app, wait_run, project_dir, tmp_path, mode  # noqa: F811
):
    outside = tmp_path / "outside.py"
    outside.write_bytes(b"print('hi')\n")
    (project_dir / "hello.py").unlink()
    link(outside, project_dir / "hello.py")
    client, provider, _ = claude_app([WRITE, {"say": "I could not."}])
    cid, run_id = claude_start(client, project_dir, provider, mode)
    snap = wait_run(client, cid, run_id, timeout=20)
    assert outside.read_bytes() == b"print('hi')\n"
    assert snap["file_changes"] == []                       # nothing proposed, nobody asked
    (tool,) = snap["tool_calls"]
    assert tool["status"] == "failed" and "hard link" in tool["result"]
    verdict = claude_app.record()["asked"][0]
    assert verdict["behavior"] == "deny" and "hard link" in verdict["message"]


# --- after the review: no race, no failing open, the copy's own note, the setting --------------


def test_the_names_are_counted_on_the_handle_that_writes(tmp_path, monkeypatch):
    from app import workspace

    (tmp_path / "one.txt").write_bytes(b"a")
    link(tmp_path / "one.txt", tmp_path / "two.txt")
    # whatever a look beforehand said, the write itself does not go through the link
    monkeypatch.setattr(workspace, "has_other_names", lambda target: False)
    with pytest.raises(OSError, match="hard link"):
        workspace.write_bytes(tmp_path / "two.txt", b"b")
    assert (tmp_path / "one.txt").read_bytes() == b"a"
    # a file with one name is written whole, a longer one cut to the new length
    (tmp_path / "three.txt").write_bytes(b"long old text")
    workspace.write_bytes(tmp_path / "three.txt", b"new")
    workspace.write_bytes(tmp_path / "four.txt", b"made")
    assert (tmp_path / "three.txt").read_bytes() == b"new"
    assert (tmp_path / "four.txt").read_bytes() == b"made"


def test_a_file_that_cannot_be_looked_at_is_taken_to_have_other_names(tmp_path, monkeypatch):
    from pathlib import Path

    (tmp_path / "a.txt").write_bytes(b"a")
    assert not has_other_names(tmp_path / "a.txt") and not has_other_names(tmp_path / "none")
    assert not has_other_names(tmp_path / "a.txt" / "below")

    def refuse(self, *args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "stat", refuse)
    assert has_other_names(tmp_path / "a.txt")


def test_what_a_copy_was_made_from_is_never_written_through_a_link(tmp_path):
    project, outside = tmp_path / "proj", tmp_path / "outside.txt"
    project.mkdir()
    (project / "a.txt").write_bytes(b"a")
    copy = copies.make(project, tmp_path / "runtime", "a1")
    outside.write_bytes(b"theirs")
    link(outside, copy.root.parent / "base.new")      # made by a command beside the tree
    copy.save()
    assert outside.read_bytes() == b"theirs"
    assert not (copy.root.parent / "base.new").exists()
    assert copies.load(project, tmp_path / "runtime", "a1").base == copy.base


@pytest.mark.parametrize("given, seconds", [
    (None, 20.0), ("", 20.0), ("7.5", 7.5), ("0", 20.0), ("-3", 20.0), ("soon", 20.0),
    ("nan", 20.0), ("inf", 20.0),
])
def test_the_search_time_limit_is_a_positive_number_or_the_default(given, seconds):
    from app.config import load_settings

    env = {} if given is None else {"KOLONI_SEARCH_SECONDS": given}
    assert load_settings(env).search_seconds == seconds
