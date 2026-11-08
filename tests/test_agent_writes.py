import json
import time
from pathlib import Path

import pytest

from app.model_client import StepResult, ToolCallRequest
from tests.test_chat_flow import start, start_in_mode, text


def edit(path="hello.py", old="hi", new="hello", id="w1"):
    args = json.dumps({"path": path, "old_string": old, "new_string": new})
    return StepResult("", [ToolCallRequest(id, "edit_file", args)], 1, 1)


def write(path, content, id="w1"):
    args = json.dumps({"path": path, "content": content})
    return StepResult("", [ToolCallRequest(id, "write_file", args)], 1, 1)


def wait_status(client, cid, status):
    snap = {}
    for _ in range(250):
        snap = client.get(f"/api/conversations/{cid}").json()
        if snap["runs"] and snap["runs"][-1]["status"] == status:
            return snap
        time.sleep(0.02)
    raise AssertionError(f"run never reached {status}: {snap.get('runs')}")


def read(project_dir, name="hello.py"):
    return (project_dir / name).read_bytes().decode()


def test_ask_mode_waits_then_applies_on_approval(make_client, wait_run, project_dir):
    client, model = make_client([edit(), text("Changed the greeting.")])
    cid, run_id = start(client, project_dir, "say hello instead")
    snap = wait_status(client, cid, "waiting_approval")
    change = snap["file_changes"][0]
    assert (change["status"], change["kind"], change["path"]) == ("proposed", "modify", "hello.py")
    assert (change["additions"], change["deletions"]) == (1, 1)
    assert "+print('hello')" in change["diff"] and "-print('hi')" in change["diff"]
    assert snap["tool_calls"][0]["status"] == "running"
    assert "'hi'" in read(project_dir)  # not written yet

    approved = client.post(f"/api/file-changes/{change['id']}/approve")
    assert approved.status_code == 200 and approved.json()["status"] == "applied"
    snap = wait_run(client, cid, run_id)
    assert "'hello'" in read(project_dir)
    assert snap["tool_calls"][0]["status"] == "succeeded"
    assert snap["file_changes"][0]["decided_at"]
    assert model.calls[1][-1]["content"].startswith("applied: hello.py (+1 -1)")
    assert snap["runs"][0]["status"] == "completed"


def test_reject_leaves_the_file_and_tells_the_model(make_client, wait_run, project_dir):
    client, model = make_client([edit(), text("Okay, left it.")])
    cid, run_id = start(client, project_dir)
    change = wait_status(client, cid, "waiting_approval")["file_changes"][0]
    assert client.post(f"/api/file-changes/{change['id']}/reject").json()["status"] == "rejected"
    snap = wait_run(client, cid, run_id)
    assert "'hi'" in read(project_dir)
    assert snap["tool_calls"][0]["status"] == "denied"
    result = model.calls[1][-1]["content"]
    assert result.startswith("rejected: the user declined this change to hello.py")
    # A real model took a vaguer message as a tool failure and retried with write_file.
    assert "not a tool error" in result and "with any tool" in result
    assert snap["runs"][0]["status"] == "completed"


def test_file_changed_while_waiting_is_a_conflict_not_an_overwrite(make_client, wait_run, project_dir):
    client, model = make_client([edit(), text("I will re-read it.")])
    cid, run_id = start(client, project_dir)
    change = wait_status(client, cid, "waiting_approval")["file_changes"][0]
    (project_dir / "hello.py").write_bytes(b"print('edited by me')\n")
    assert client.post(f"/api/file-changes/{change['id']}/approve").json()["status"] == "conflict"
    snap = wait_run(client, cid, run_id)
    assert read(project_dir) == "print('edited by me')\n"
    assert snap["tool_calls"][0]["status"] == "failed"
    assert model.calls[1][-1]["content"].startswith("conflict: hello.py changed on disk")


def test_file_deleted_while_waiting_is_a_conflict(make_client, wait_run, project_dir):
    client, _ = make_client([edit(), text("ok")])
    cid, run_id = start(client, project_dir)
    change = wait_status(client, cid, "waiting_approval")["file_changes"][0]
    (project_dir / "hello.py").unlink()
    assert client.post(f"/api/file-changes/{change['id']}/approve").json()["status"] == "conflict"
    wait_run(client, cid, run_id)
    assert not (project_dir / "hello.py").exists()


def test_auto_mode_writes_immediately_and_can_be_reverted(make_client, wait_run, project_dir):
    client, _ = make_client([write("notes/new.txt", "first\n"), text("Created it.")])
    cid, run_id = start_in_mode(client, project_dir, "auto_edit")
    snap = wait_run(client, cid, run_id)
    change = snap["file_changes"][0]
    assert (change["status"], change["kind"]) == ("applied", "create")
    assert read(project_dir, "notes/new.txt") == "first\n"

    assert client.post(f"/api/file-changes/{change['id']}/revert").json()["status"] == "reverted"
    assert not (project_dir / "notes" / "new.txt").exists()
    again = client.post(f"/api/file-changes/{change['id']}/revert")
    assert again.status_code == 409 and "only an applied change" in again.json()["detail"]


@pytest.mark.parametrize("mode", ["auto_edit", "full_auto"])
@pytest.mark.parametrize("path", [".claude/settings.json", ".venv/Lib/site-packages/x.pth"])
def test_a_file_that_stands_over_later_turns_is_asked_about_at_every_level(
    make_client, wait_run, project_dir, mode, path
):
    """`.claude/` tells later turns what they may do, and an environment's `.pth` runs at every
    start of its Python: its write waits for the user's word at Auto-edit and Full auto too, as
    in Ask (K-claude-yazma)."""
    client, _ = make_client([write(path, "{}"), text("Done.")])
    cid, run_id = start_in_mode(client, project_dir, mode)
    snap = wait_status(client, cid, "waiting_approval")
    assert snap["conversation"]["permission_mode"] == mode
    change = snap["file_changes"][0]
    assert (change["status"], change["path"]) == ("proposed", path)
    assert not (project_dir / path).exists()
    assert client.post(f"/api/file-changes/{change['id']}/approve").json()["status"] == "applied"
    wait_run(client, cid, run_id)
    assert read(project_dir, path) == "{}"


@pytest.mark.parametrize("mode", ["full_auto", "auto_edit"])
def test_an_instruction_file_is_written_unasked_at_full_auto_alone(
    make_client, wait_run, project_dir, mode
):
    """K-fullauto-sorma 2: AGENTS.md is read by later agents as the user's words and runs nothing:
    at Full auto its write is no card; at Auto-edit it still waits, as every standing file does."""
    client, _ = make_client([write("AGENTS.md", "# Rules\n"), text("Done.")])
    cid, run_id = start_in_mode(client, project_dir, mode)
    if mode == "full_auto":
        snap = wait_run(client, cid, run_id)
        assert snap["file_changes"][0]["status"] == "applied"
        assert read(project_dir, "AGENTS.md") == "# Rules\n"
        return
    change = wait_status(client, cid, "waiting_approval")["file_changes"][0]
    assert (change["status"], change["path"]) == ("proposed", "AGENTS.md")
    client.post(f"/api/file-changes/{change['id']}/reject")
    wait_run(client, cid, run_id)


def test_an_instruction_file_in_the_path_hides_no_other_standing_name(project_dir):
    """Review of K-fullauto-sorma 2: `AGENTS.md/../.claude/settings.json` is `.claude`'s - the
    instruction file is the name only where nothing else stands, in either chain."""
    from app.workspace import Workspace, stands_over_later_turns
    ws = Workspace(project_dir)
    assert stands_over_later_turns(ws, "AGENTS.md/../.claude/settings.json") == ".claude"
    assert stands_over_later_turns(ws, "GEMINI.md/../.mcp.json") == ".mcp.json"
    assert stands_over_later_turns(ws, "x/CLAUDE.md/../../.git/hooks/pre-commit") == ".git"
    assert stands_over_later_turns(ws, "docs/AGENTS.md") == "agents.md"
    assert stands_over_later_turns(ws, "docs/notes.md") is None
    # K-koloni-klasor: the scratch `.koloni/tmp/` is no standing name; the rest of .koloni is,
    # and a path that climbs back out of the scratch is seen where it really leads.
    assert stands_over_later_turns(ws, ".koloni/tmp/profile/x.log") is None
    assert stands_over_later_turns(ws, ".koloni\\TMP\\x") is None
    assert stands_over_later_turns(ws, ".koloni/settings.json") == ".koloni"
    assert stands_over_later_turns(ws, ".koloni/tmp/../settings.json") == ".koloni"
    assert stands_over_later_turns(ws, ".koloni/tmp/.claude/settings.json") == ".claude"


@pytest.mark.parametrize("path", ["AGENTS.md/../.claude/settings.json", "GEMINI.md/../.mcp.json",
                                  "x/CLAUDE.md/../../.git/hooks/pre-commit"])
def test_a_standing_file_behind_an_instruction_files_name_is_still_a_card_at_full_auto(
    make_client, wait_run, project_dir, path
):
    client, _ = make_client([write(path, "x"), text("Done.")])
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_status(client, cid, "waiting_approval")
    change = snap["file_changes"][0]
    assert change["status"] == "proposed" and ".." not in change["path"]
    client.post(f"/api/file-changes/{change['id']}/reject")
    wait_run(client, cid, run_id)
    assert not (project_dir / ".claude").exists() and not (project_dir / ".mcp.json").exists()
    assert not (project_dir / ".git/hooks/pre-commit").exists()


def test_edit_keeps_the_files_line_endings(make_client, wait_run, project_dir):
    (project_dir / "win.txt").write_bytes(b"one\r\ntwo\r\n")
    client, _ = make_client([edit("win.txt", "two", "2"), text("ok")])
    cid, run_id = start_in_mode(client, project_dir, "auto_edit")
    change = wait_run(client, cid, run_id)["file_changes"][0]
    assert (project_dir / "win.txt").read_bytes() == b"one\r\n2\r\n"
    client.post(f"/api/file-changes/{change['id']}/revert")
    assert (project_dir / "win.txt").read_bytes() == b"one\r\ntwo\r\n"


def test_revert_refuses_when_the_file_moved_on(make_client, wait_run, project_dir):
    client, _ = make_client([edit(), text("ok")])
    cid, run_id = start_in_mode(client, project_dir, "auto_edit")
    change = wait_run(client, cid, run_id)["file_changes"][0]
    (project_dir / "hello.py").write_bytes(b"print('later edit')\n")
    r = client.post(f"/api/file-changes/{change['id']}/revert")
    assert r.status_code == 409 and "changed since" in r.json()["detail"]
    assert read(project_dir) == "print('later edit')\n"


def test_edit_requires_exactly_one_match(make_client, wait_run, project_dir):
    (project_dir / "dup.txt").write_bytes(b"a\na\n")

    def call(id, path, old):
        args = json.dumps({"path": path, "old_string": old, "new_string": "b"})
        return ToolCallRequest(id, "edit_file", args)

    client, _ = make_client([
        StepResult("", [call("x", "dup.txt", "a"), call("y", "dup.txt", "zz"),
                        call("z", "missing.txt", "a"), call("w", "dup.txt", "")], 1, 1),
        text("ok")])
    cid, run_id = start_in_mode(client, project_dir, "auto_edit")
    snap = wait_run(client, cid, run_id)
    results = [t["result"] for t in snap["tool_calls"]]
    assert "matches 2 times in 'dup.txt' (at lines 1, 2)" in results[0]
    assert "was not found" in results[1]
    assert "does not exist" in results[2]
    assert "must not be empty" in results[3]
    assert all(t["status"] == "failed" for t in snap["tool_calls"])
    assert snap["file_changes"] == []


def edits(*calls):
    """One step of edit_file calls, each (path, old, new)."""
    return StepResult("", [
        ToolCallRequest(f"e{at}", "edit_file", json.dumps(
            {"path": path, "old_string": old, "new_string": new}))
        for at, (path, old, new) in enumerate(calls)], 1, 1)


def test_an_edit_ignores_line_endings_and_writes_the_files_own(make_client, wait_run,
                                                               project_dir):
    """B-92: an LF old_string is found in a CRLF file; the new lines are CRLF, the lines
    it does not touch (an LF one too) keep their bytes, and so does the BOM (G4.1)."""
    (project_dir / "calc.py").write_bytes(b"\xef\xbb\xbfdef f():\r\n    return 1\r\nx = 2\n")
    client, _ = make_client([
        edit("calc.py", "def f():\n    return 1\n", "def f():\n    # two\n    return 2\n"),
        text("ok")])
    cid, run_id = start_in_mode(client, project_dir, "auto_edit")
    snap = wait_run(client, cid, run_id)
    assert snap["tool_calls"][0]["result"].startswith("applied: calc.py")
    assert (project_dir / "calc.py").read_bytes() == (
        b"\xef\xbb\xbfdef f():\r\n    # two\r\n    return 2\r\nx = 2\n")


def test_a_whole_write_keeps_the_files_crlf_and_bom(make_client, wait_run, project_dir):
    (project_dir / "win.txt").write_bytes(b"\xef\xbb\xbfone\r\ntwo\r\n")
    client, _ = make_client([write("win.txt", "one\nthree\n"), text("ok")])
    cid, run_id = start_in_mode(client, project_dir, "auto_edit")
    wait_run(client, cid, run_id)
    assert (project_dir / "win.txt").read_bytes() == b"\xef\xbb\xbfone\r\nthree\r\n"


def test_an_edit_already_made_is_no_failure(make_client, wait_run, project_dir):
    """G4.2: the new text is there and the old is not - nothing written, nothing failed."""
    client, _ = make_client([edit(old="print('hi')", new="print('hey')"), text("ok")])
    (project_dir / "hello.py").write_bytes(b"print('hey')\n")
    cid, run_id = start_in_mode(client, project_dir, "auto_edit")
    snap = wait_run(client, cid, run_id)
    (call,) = snap["tool_calls"]
    assert call["status"] == "succeeded" and call["result"].startswith("already applied")
    assert snap["file_changes"] == []


def test_an_edit_not_found_shows_the_nearest_lines_and_a_third_miss_says_what_to_do(
        make_client, wait_run, project_dir):
    (project_dir / "calc.py").write_bytes(b"def f():\n\treturn 1\n")
    client, _ = make_client([
        edits(("calc.py", "def f():\n    return 1", "x"), ("calc.py", "nothing like it", "x"),
              ("calc.py", "nor this", "x")),
        text("ok")])
    cid, run_id = start_in_mode(client, project_dir, "auto_edit")
    results = [t["result"] for t in wait_run(client, cid, run_id)["tool_calls"]]
    # (a tab where the model wrote spaces: the copy's fault, shown)
    assert "    1| def f():\n    2| →return 1" in results[0]
    assert "times on calc.py" not in results[1]
    assert "edit_file failed 3 times on calc.py in this turn" in results[2]
    assert "read_file" in results[2] and "write_file" in results[2]


def test_a_loose_match_is_taken_only_where_it_is_the_one_place(make_client, wait_run,
                                                               project_dir):
    """G4.3: spaces at a line's end and curly quotes do not count - where only one place
    matches; the model is told the match was loose, and the change's diff is exact."""
    (project_dir / "msg.py").write_text("msg = “hi”   \nend = 1\n", encoding="utf-8")
    (project_dir / "two.py").write_text("a = ‘x’\na = ‘x’\n", encoding="utf-8")
    client, _ = make_client([
        edits(("msg.py", 'msg = "hi"\nend = 1', 'msg = "hello"\nend = 1'),
              ("two.py", "a = 'x'", "b")),
        text("ok")])
    cid, run_id = start_in_mode(client, project_dir, "auto_edit")
    snap = wait_run(client, cid, run_id)
    first, second = snap["tool_calls"]
    assert first["status"] == "succeeded" and "quote marks differing" in first["result"]
    assert (project_dir / "msg.py").read_text(encoding="utf-8") == 'msg = "hello"\nend = 1\n'
    assert '-msg = “hi”' in snap["file_changes"][0]["diff"]
    assert second["status"] == "failed" and "was not found" in second["result"]
    assert "a = ‘x’" in (project_dir / "two.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("bad_writes", [1, 2], ids=["put back", "cannot be put back"])
def test_a_write_that_does_not_read_back_is_a_failure_and_is_undone(
        make_client, wait_run, project_dir, monkeypatch, bad_writes):
    """A write that went wrong on its way does not leave the file cut short: what it held
    is put back - or, where even that goes wrong, the result says so plainly."""
    import app.workspace

    real, calls = app.workspace.write_bytes, []

    def short(target, data):
        calls.append(data)
        real(target, data[:-1] if len(calls) <= bad_writes else data)

    monkeypatch.setattr(app.workspace, "write_bytes", short)
    client, _ = make_client([edit(), text("ok")])
    cid, run_id = start_in_mode(client, project_dir, "auto_edit")
    snap = wait_run(client, cid, run_id)
    assert snap["file_changes"][0]["status"] == "failed"
    said = snap["tool_calls"][0]["result"]
    assert "does not read back as written" in said
    if bad_writes == 1:
        assert "the file is as it was" in said and read(project_dir) == "print('hi')\n"
    else:
        assert "may be partly written" in said and "on this change's record" in said


def test_a_deletion_or_a_typo_not_found_is_no_edit_already_made(make_client, wait_run,
                                                               project_dir):
    """new_string inside old_string - a line to drop, a typo - is never "already applied":
    the file tells nothing of an edit made, and the misses go on being counted."""
    (project_dir / "app.py").write_bytes(b"line_to_keep\nkeep()\n")
    client, _ = make_client([
        edits(("app.py", "line_to_drop\nkeep()", "keep()"),
              ("app.py", "keep()  # a note, misspelt", "keep()"),
              ("app.py", "line_to_drop\nkeep()", "keep()")),
        text("ok")])
    cid, run_id = start_in_mode(client, project_dir, "auto_edit")
    calls = wait_run(client, cid, run_id)["tool_calls"]
    assert [t["status"] for t in calls] == ["failed", "failed", "failed"]
    assert all("was not found" in t["result"] for t in calls)
    assert "edit_file failed 3 times on app.py" in calls[2]["result"]


def test_a_loose_match_over_a_long_run_of_spaces_is_quick(tmp_path):
    from app.tools import ToolError, plan_write
    from app.workspace import Workspace

    (tmp_path / "wide.txt").write_bytes(b" " * 50_000 + b"y\n")
    began = time.monotonic()
    with pytest.raises(ToolError, match="was not found"):
        plan_write(Workspace(tmp_path), "edit_file",
                   {"path": "wide.txt", "old_string": "\nfoo", "new_string": "x"})
    assert time.monotonic() - began < 1


def test_a_file_larger_than_a_write_is_not_edited(tmp_path):
    from app.tools import ToolError, plan_write
    from app.workspace import Workspace

    (tmp_path / "big.txt").write_bytes(b"a" * (2**20 + 1))
    with pytest.raises(ToolError, match="larger than 1 MiB: it is not edited"):
        plan_write(Workspace(tmp_path), "edit_file",
                   {"path": "big.txt", "old_string": "aa", "new_string": "b"})
    # (nor replaced whole: undo could not put it back)
    with pytest.raises(ToolError, match="larger than 1 MiB: it is not replaced"):
        plan_write(Workspace(tmp_path), "write_file", {"path": "big.txt", "content": "b"})


def test_new_lines_end_as_the_line_they_are_on_and_a_whole_write_as_most_lines_did(tmp_path):
    from app.tools import plan_write
    from app.workspace import Workspace

    ws = Workspace(tmp_path)
    (tmp_path / "mixed.txt").write_bytes(b"a\nb\r\nc\r\n")
    edited = plan_write(ws, "edit_file", {"path": "mixed.txt", "old_string": "b",
                                          "new_string": "b1\nb2"})
    assert edited.after == "a\nb1\r\nb2\r\nc\r\n"
    # (the last line, with no ending of its own: as most of the file's)
    (tmp_path / "last.txt").write_bytes(b"a\r\nb\r\nc")
    assert plan_write(ws, "edit_file", {"path": "last.txt", "old_string": "c",
                                        "new_string": "c\nd"}).after == "a\r\nb\r\nc\r\nd"
    (tmp_path / "lf.txt").write_bytes(b"a\nb\nc\r\nd\n")
    assert plan_write(ws, "write_file", {"path": "lf.txt", "content": "x\ny\n"}).after == "x\ny\n"
    (tmp_path / "crlf.txt").write_bytes(b"a\r\nb\r\nc\n")
    assert plan_write(ws, "write_file", {"path": "crlf.txt",
                                         "content": "x\ny\n"}).after == "x\r\ny\r\n"


def test_write_outside_the_project_is_refused(make_client, wait_run, project_dir, tmp_path):
    # (into a drive's root: never opened - another folder outside is asked about)
    client, _ = make_client([write("../" * 40 + "escaped.txt", "x"), text("ok")])
    cid, run_id = start_in_mode(client, project_dir, "auto_edit")
    snap = wait_run(client, cid, run_id)
    assert "never opened" in snap["tool_calls"][0]["result"]
    assert snap["file_changes"] == [] and not (Path(tmp_path.anchor) / "escaped.txt").exists()


def test_identical_content_is_not_a_change(make_client, wait_run, project_dir):
    client, _ = make_client([write("hello.py", "print('hi')\n"), text("ok")])
    cid, run_id = start_in_mode(client, project_dir, "auto_edit")
    snap = wait_run(client, cid, run_id)
    assert snap["file_changes"] == []
    assert "already has this content" in snap["tool_calls"][0]["result"]


def test_cancel_while_waiting_rejects_the_pending_change(make_client, wait_run, project_dir):
    client, _ = make_client([edit()])
    cid, run_id = start(client, project_dir)
    change = wait_status(client, cid, "waiting_approval")["file_changes"][0]
    client.post(f"/api/runs/{run_id}/cancel")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "cancelled"
    assert snap["file_changes"][0]["status"] == "rejected"
    assert snap["tool_calls"][0]["status"] == "interrupted"
    r = client.post(f"/api/file-changes/{change['id']}/approve")
    assert r.status_code == 409 and "no longer waiting" in r.json()["detail"]
    assert "'hi'" in read(project_dir)


def test_switching_to_auto_mid_run_applies_later_edits_directly(make_client, wait_run, project_dir):
    client, _ = make_client([
        edit(new="one", id="a"), edit(old="one", new="two", id="b"), text("done")])
    cid, run_id = start(client, project_dir)
    first = wait_status(client, cid, "waiting_approval")["file_changes"][0]
    client.patch(f"/api/conversations/{cid}", json={"permission_mode": "auto_edit"},
                 headers={"Origin": "http://127.0.0.1:8790"})
    client.post(f"/api/file-changes/{first['id']}/approve")
    snap = wait_run(client, cid, run_id)
    assert [c["status"] for c in snap["file_changes"]] == ["applied", "applied"]
    assert read(project_dir) == "print('two')\n"


def test_decisions_on_unknown_changes_are_404(make_client):
    client, _ = make_client([])
    for action in ("approve", "reject", "revert"):
        assert client.post(f"/api/file-changes/nope/{action}").status_code == 404


def test_change_events_are_replayable(make_client, wait_run, project_dir):
    client, _ = make_client([edit(), text("ok")])
    cid, run_id = start_in_mode(client, project_dir, "auto_edit")
    wait_run(client, cid, run_id)
    with client.stream("GET", f"/api/conversations/{cid}/events?after=0&once=1") as r:
        types = [line[7:] for line in r.read().decode().splitlines() if line.startswith("event: ")]
    assert types.index("file_change.created") < types.index("file_change.updated")
    assert types.index("file_change.updated") < types.index("run.finished")


def test_a_change_carries_its_hunks_and_its_whole_diff_is_read_on_asking(make_client, project_dir):
    # (slice 42a) Events and the snapshot hold three lines around each change; the Changes
    # window asks for the rest of the file when a fold is opened - up to a size.
    (project_dir / "long.txt").write_text("".join(f"line {n}\n" for n in range(1, 41)))
    client, _ = make_client([edit("long.txt", "line 20", "line twenty"), text("Done.")])
    cid, _ = start(client, project_dir, "change line 20")
    change = wait_status(client, cid, "waiting_approval")["file_changes"][0]
    assert "+line twenty" in change["diff"] and "\n line 1\n" not in change["diff"]
    whole = client.get(f"/api/file-changes/{change['id']}/diff")
    assert whole.status_code == 200
    assert "@@ -1,40 +1,40 @@" in whole.json()["diff"] and "\n line 1\n" in whole.json()["diff"]
    assert client.get("/api/file-changes/nope/diff").status_code == 404
    client.post(f"/api/file-changes/{change['id']}/reject")


def test_the_whole_diff_of_too_large_a_file_is_refused(make_client, project_dir):
    (project_dir / "big.txt").write_text("x" * 120_000 + "\nlast\n")
    client, _ = make_client([edit("big.txt", "last", "LAST"), text("Done.")])
    cid, _ = start(client, project_dir, "change the last line")
    change = wait_status(client, cid, "waiting_approval")["file_changes"][0]
    refused = client.get(f"/api/file-changes/{change['id']}/diff")
    assert refused.status_code == 413 and "too large" in refused.json()["detail"]
    client.post(f"/api/file-changes/{change['id']}/reject")


def test_misses_on_one_file_are_counted_by_any_spelling_of_it():
    from app.signs import Counts

    counts = Counts()
    said = [counts.missed_edit(json.dumps({"path": path}))
            for path in ("src/a.py", "src/../src/a.py", "src/./a.py")]
    assert said[:2] == ["", ""] and "failed 3 times" in said[2]
