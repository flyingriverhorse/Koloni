import pytest

from app.tools import BROWSER_TOOLS, TOOL_SCHEMAS, ToolError, parse_arguments, run_read_tool
from app.workspace import Workspace


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "a.py").write_bytes("".join(f"line {i}\n" for i in range(1, 6)).encode())
    return Workspace(tmp_path)


def test_schemas_name_the_seven_tools_and_the_browsers():
    assert [t["function"]["name"] for t in TOOL_SCHEMAS] == [
        "list_dir", "read_file", "search", "view_image", "write_file", "edit_file", "run_command",
        *BROWSER_TOOLS, "diagram_image"]  # (slice 51; K-drawio)


def test_read_file_numbers_lines_and_honours_offset_limit(ws):
    assert run_read_tool(ws, "read_file", {"path": "a.py", "offset": 2, "limit": 2}) == (
        "     2\tline 2\n     3\tline 3\n[showing lines 2-3 of 5]\n"
        "[the file: LF line endings, ends with a newline; edit_file and write_file keep these]")


def test_read_file_truncates_at_2000_lines(ws):
    (ws.root / "big.txt").write_text("x\n" * 2500, encoding="utf-8")
    out = run_read_tool(ws, "read_file", {"path": "big.txt"})
    assert "\n[showing lines 1-2000 of 2500]\n[the file: " in out


def test_read_file_stops_at_the_byte_budget(ws):
    (ws.root / "wide.txt").write_text(("y" * 1000 + "\n") * 600, encoding="utf-8")
    out = run_read_tool(ws, "read_file", {"path": "wide.txt"})
    assert len(out.encode()) <= 256 * 1024 + 100
    assert "of 600]" in out and "[showing lines 1-600" not in out


def test_read_file_past_the_end_and_empty_file(ws):
    assert run_read_tool(ws, "read_file", {"path": "a.py", "offset": 99}) == (
        "[no lines at offset 99; the file has 5 lines]")
    (ws.root / "empty.txt").write_text("", encoding="utf-8")
    assert run_read_tool(ws, "read_file", {"path": "empty.txt"}) == "[the file is empty]"


@pytest.mark.parametrize("data, said", [
    (b"one\ntwo\n", "LF line endings, ends with a newline"),
    (b"one\r\ntwo", "CRLF line endings, no final newline"),
    (b"\xef\xbb\xbfone\r\ntwo\r\nthree\n", "BOM, mixed line endings, mostly CRLF, ends with a newline"),
    (b"only", "no line breaks, no final newline"),
    (b"one\r", "no line breaks, no final newline"),  # (a lone CR ends no line here)
])
def test_read_file_ends_with_the_files_form_on_a_line_of_its_own(ws, monkeypatch, data, said):
    from app import workspace

    monkeypatch.setattr(workspace, "READ_CHUNK", 1)  # a CRLF across two pieces counts once
    (ws.root / "f.txt").write_bytes(data)
    *_, shown, form = run_read_tool(ws, "read_file", {"path": "f.txt"}).split("\n")
    assert shown.startswith("[showing lines 1-")
    assert form == f"[the file: {said}; edit_file and write_file keep these]"


def test_list_and_search_format(ws):
    assert run_read_tool(ws, "list_dir", {}) == "a.py  (file, 35 bytes)"
    assert run_read_tool(ws, "search", {"pattern": "line 4"}) == "a.py:4: line 4"
    assert run_read_tool(ws, "search", {"pattern": "zzz"}) == "no matches"


@pytest.mark.parametrize("args, message", [
    ({}, "missing required argument: path"),
    ({"path": 5}, "argument path must be a string"),
    ({"path": "a.py", "offset": 0}, "offset must be 1 or greater"),
    ({"path": "a.py", "limit": "ten"}, "argument limit must be an integer"),
    ({"path": "../elsewhere/x"}, "outside the project"),  # (the folder above holds the home)
])
def test_bad_arguments_are_tool_errors(ws, args, message):
    with pytest.raises(ToolError, match=message):
        run_read_tool(ws, "read_file", args)


def test_unknown_read_tool_is_a_tool_error(ws):
    with pytest.raises(ToolError, match="unknown tool: rm"):
        run_read_tool(ws, "rm", {})


@pytest.mark.parametrize("raw", ["{not json", "[1,2]", '"text"', "null"])
def test_parse_arguments_rejects_non_objects(raw):
    with pytest.raises(ToolError, match="arguments must be a JSON object"):
        parse_arguments(raw)


def test_parse_arguments_accepts_empty_string_as_empty_object():
    assert parse_arguments("") == {}
    assert parse_arguments('{"path": "a"}') == {"path": "a"}


def test_write_and_edit_say_they_keep_a_files_line_endings_and_bom():
    # B-126 (live): not told so, agents wrote a CRLF file through PowerShell to keep its endings.
    said = {t["function"]["name"]: t["function"]["description"] for t in TOOL_SCHEMAS}
    for name in ("write_file", "edit_file"):
        assert "keeps its line endings (CRLF or LF) and its BOM" in said[name]
        # B-155 (live): a night's Coder read a file's last bytes with PowerShell before adding a line.
        assert "There is no need to read a file's bytes first." in said[name]
    assert "To add a line at the end, put the file's last line in old_string" in said["edit_file"]


@pytest.mark.parametrize("before, after", [
    (b"\xef\xbb\xbfone\r\ntwo\r\n", b"\xef\xbb\xbfone\r\ntwo\r\nthree\r\n"),
    (b"one\ntwo", b"one\ntwo\nthree"),
])
def test_a_line_added_at_the_end_as_edit_file_says_keeps_the_files_end(tmp_path, before, after):
    # B-155: done the way the description says, the file keeps its endings, its BOM and how its last line ends.
    from app.tools import plan_write
    (tmp_path / "lines.txt").write_bytes(before)
    planned = plan_write(Workspace(tmp_path), "edit_file", {"path": "lines.txt", "old_string": "two", "new_string": "two\nthree"})
    assert planned.after.encode() == after
