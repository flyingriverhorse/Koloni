import os
import subprocess

import pytest

from app.workspace import Workspace, WorkspaceError, sha256_text, unified_diff


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
    (root / "node_modules" / "x").mkdir(parents=True)
    (root / "node_modules" / "x" / "i.js").write_text("two\n", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("secret", encoding="utf-8")
    return Workspace(root)


# (elsewhere `..\x` is one file's name, in the project)
BACKSLASH = pytest.mark.skipif(os.name != "nt", reason="a backslash is a folder's mark on Windows")


@pytest.mark.parametrize("bad", [
    "../outside.txt", pytest.param("..\\outside.txt", marks=BACKSLASH), "src/../../outside.txt",
    "C:\\Windows\\win.ini", "/etc/passwd", "\\\\server\\share\\x", "C:relative.txt", "", "   ",
])
def test_paths_outside_the_root_are_rejected(ws, bad):
    with pytest.raises(WorkspaceError, match="outside the project|empty path|never opened"):
        ws.resolve(bad)


def test_paths_inside_the_root_resolve(ws):
    assert ws.resolve("src/a.py") == ws.root / "src" / "a.py"
    if os.name == "nt":  # (elsewhere `src\..\src\a.py` is one file's name, in the project)
        assert ws.resolve("src\\..\\src\\a.py") == ws.root / "src" / "a.py"
    assert ws.resolve(".") == ws.root
    assert ws.rel(ws.root / "src" / "a.py") == "src/a.py"


def test_link_escaping_the_root_is_rejected(ws, tmp_path):
    # (Beside the project, not the test's folder itself: that holds the test's home, never
    # opened since slice 75.)
    beyond = tmp_path / "beyond"
    beyond.mkdir()
    (beyond / "outside.txt").write_text("secret", encoding="utf-8")
    link = ws.root / "leak"
    try:
        os.symlink(beyond, link, target_is_directory=True)
    except OSError:
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(beyond)], check=True, capture_output=True
        )
    with pytest.raises(WorkspaceError, match="outside the project"):
        ws.resolve("leak/outside.txt")
    with pytest.raises(WorkspaceError):
        ws.write_text("leak/new.txt", "x")
    assert not (beyond / "new.txt").exists()
    matches, *_ = ws.search("secret")
    assert matches == []


def test_list_dir_skips_ignored_folders_and_sorts_dirs_first(ws):
    (ws.root / "z.txt").write_text("z", encoding="utf-8")
    assert ws.list_dir(".") == [("src", "dir", None), ("z.txt", "file", 1)]
    with pytest.raises(WorkspaceError, match="is not a folder"):
        ws.list_dir("z.txt")


def test_read_rejects_binary_and_missing(ws):
    (ws.root / "b.bin").write_bytes(b"\xff\xfe\x00\x01")
    with pytest.raises(WorkspaceError, match="not UTF-8 text"):
        ws.read_text("b.bin")
    with pytest.raises(WorkspaceError, match="does not exist"):
        ws.read_text("nope.py")
    with pytest.raises(WorkspaceError, match="is not a file"):
        ws.read_text("src")
    assert ws.read_text_or_none("nope.py") is None


def test_search_returns_path_line_text_and_skips_ignored(ws):
    matches, truncated, *_ = ws.search("tw.")
    assert matches == [("src/a.py", 2, "two")] and truncated is False


def test_search_honours_glob_and_stops_at_the_match_limit(ws):
    (ws.root / "many.txt").write_text("hit\n" * 250, encoding="utf-8")
    matches, truncated, *_ = ws.search("hit")
    assert len(matches) == 200 and truncated is True
    assert ws.search("hit", glob="*.py") == ([], False, 0, [])


def test_search_reports_bad_regex(ws):
    with pytest.raises(WorkspaceError, match="invalid regular expression"):
        ws.search("(")


def test_write_creates_parents_and_enforces_size(ws):
    ws.write_text("new/deep/f.txt", "hello")
    assert (ws.root / "new" / "deep" / "f.txt").read_text(encoding="utf-8") == "hello"
    with pytest.raises(WorkspaceError, match="larger than 1 MiB"):
        ws.write_text("big.txt", "x" * (1024 * 1024 + 1))
    with pytest.raises(WorkspaceError, match="is a folder"):
        ws.write_text("src", "x")


def test_write_preserves_exact_newlines(ws):
    ws.write_text("crlf.txt", "a\r\nb\n")
    assert (ws.root / "crlf.txt").read_bytes() == b"a\r\nb\n"
    assert ws.read_text("crlf.txt") == "a\r\nb\n"


def test_diff_counts(ws):
    diff, added, removed = unified_diff("one\ntwo\n", "one\n2\n3\n", "a.py")
    assert (added, removed) == (2, 1) and "+2" in diff and "-two" in diff
    assert unified_diff(None, "x\n", "n.py")[1:] == (1, 0)
    assert unified_diff("+++ x\n", "--- y\n", "p")[1:] == (1, 1)
    assert sha256_text(None) is None and len(sha256_text("x")) == 64



@pytest.mark.skipif(os.name != "nt", reason="Windows' devices and streams")
@pytest.mark.parametrize("bad", [
    "CON", "con.txt", "src/COM1.txt", "lpt9", "NUL.", "aux .", "a.txt:evil", "a.txt::$DATA",
    "src:x/a.txt"])
def test_a_device_or_a_file_s_stream_is_never_written(ws, bad):
    from app.tools import ToolError, plan_write

    with pytest.raises(ToolError, match="is not written"):
        plan_write(ws, "write_file", {"path": bad, "content": "x"})
    with pytest.raises(WorkspaceError, match="is not written"):
        ws.write_text(bad, "x")
    with pytest.raises(WorkspaceError, match="is not written"):
        ws.write_new(bad, b"x")
    with pytest.raises(WorkspaceError, match="is not written"):
        ws.delete(bad)  # (`x.exe:Zone.Identifier`: a download's mark)


@pytest.mark.skipif(os.name != "nt", reason="Windows' devices and streams")
def test_names_like_a_device_s_and_a_drive_s_colon_are_written(ws):
    for good in ("console.txt", "com10.txt", "src/conf.py", str(ws.root / "abs.txt")):
        ws.write_text(good, "x")
        assert ws.read_text(good) == "x"


def test_a_file_is_made_with_0o666_less_the_umask_not_runnable(ws, monkeypatch):
    # (`os.open` with no mode makes 0o777 less the umask: every agent's file runnable)
    modes = []
    real = os.open

    def spy(path, flags, mode=0o777, **kw):
        modes.append(mode)
        return real(path, flags, mode, **kw)

    monkeypatch.setattr(os, "open", spy)
    ws.write_text("new.md", "x")
    ws.write_new("given.bin", b"x")
    assert modes == [0o666, 0o666]


POSIX = pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")


@POSIX
def test_a_new_file_is_0644_and_one_there_keeps_its_mode(ws):
    import stat

    old = os.umask(0o022)
    try:
        ws.write_text("new.md", "x")
        ws.write_new("given.bin", b"x")
        (ws.root / "run.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        (ws.root / "run.sh").chmod(0o755)
        ws.write_text("run.sh", "#!/bin/sh\necho hi\n")
    finally:
        os.umask(old)
    assert [stat.S_IMODE((ws.root / name).stat().st_mode)
            for name in ("new.md", "given.bin", "run.sh")] == [0o644, 0o644, 0o755]
