"""scripts/check_file_size.py: a source file over 1500 lines fails unless the allow-list holds it,
and an allowed one fails once it grows past its count or drops to the limit; --update only lowers
the list; small fixtures."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "check_file_size.py"
_spec = importlib.util.spec_from_file_location("check_file_size", SCRIPT)
assert _spec and _spec.loader
size = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(size)

OVER = size.LIMIT + 1


def written(tmp_path: Path, name: str, count: int, end: bytes = b"\n") -> int:
    path = tmp_path / name
    path.write_bytes(b"x = 1\n" * (count - 1) + b"x = 1" + end)
    return size.lines(path)


def test_lines_are_counted_as_wc_does_and_a_last_one_with_no_newline(tmp_path):
    assert written(tmp_path, "a.py", 3) == 3
    assert written(tmp_path, "b.py", 3, end=b"") == 3
    (tmp_path / "c.py").write_bytes(b"")
    assert size.lines(tmp_path / "c.py") == 0
    # (a form feed is no line break: str.splitlines would count one)
    (tmp_path / "d.py").write_bytes(b"a\x0cb\n")
    assert size.lines(tmp_path / "d.py") == 1


def test_a_new_file_over_the_limit_fails_and_one_at_it_passes():
    errors, notes = size.check({"app/new.py": OVER, "app/ok.py": size.LIMIT}, {})
    assert errors == [f"app/new.py: {OVER} lines, over the limit of 1500 - split it"]
    assert notes == []


def test_an_allowed_file_may_stay_or_shrink_but_never_grow():
    allowed = {"app/big.py": 3000, "app/same.py": 2000}
    errors, notes = size.check({"app/big.py": 2900, "app/same.py": 2000}, allowed)
    assert errors == []
    assert notes == ["app/big.py: 2900 lines, down from 3000 - run it with --update"]
    errors, _ = size.check({"app/big.py": 3001, "app/same.py": 2000}, allowed)
    assert errors == [
        "app/big.py: 3001 lines, past the 3000 file_size_allow.txt allows - split it rather than "
        "raise its count"
    ]


def test_an_allowed_file_under_the_limit_or_gone_is_to_come_off_the_list():
    errors, _ = size.check({"app/big.py": size.LIMIT}, {"app/big.py": 3000, "app/old.py": 2000})
    assert errors == [
        "app/big.py: 1500 lines, under the limit now - take it off file_size_allow.txt",
        "app/old.py: gone - take it off file_size_allow.txt",
    ]


def test_the_allow_list_is_read_with_its_comments_and_a_path_may_hold_a_hash():
    text = "# why\n\n10612 app/agent/__init__.py\n  2000 tests/t#2.py \n"
    assert size.read_allow(text) == {"app/agent/__init__.py": 10612, "tests/t#2.py": 2000}


@pytest.mark.parametrize("line", ["app/a.py 2000", "2000", "lots app/a.py", "-5 app/a.py"])
def test_a_line_that_is_no_count_and_path_is_said_with_its_number(line):
    with pytest.raises(ValueError, match=r"file_size_allow\.txt line 2: not `<lines> <path>`"):
        size.read_allow(f"# head\n{line}\n")


def test_update_lowers_counts_and_takes_off_what_is_under_or_gone_never_raising_or_adding():
    text = "# kept\n3000 app/big.py\n2000 app/grew.py\n1800 app/small.py\n1900 app/old.py\n"
    counts = {"app/big.py": 2900, "app/grew.py": 2100, "app/small.py": 1500, "app/new.py": 4000}
    assert size.updated(text, counts) == "# kept\n2900 app/big.py\n2000 app/grew.py\n"
    # (what grew still fails after it, as a new file over the limit does)
    errors, notes = size.check(counts, size.read_allow(size.updated(text, counts)))
    assert [error.split(":")[0] for error in errors] == ["app/grew.py", "app/new.py"]
    assert notes == []


def test_update_writes_the_list_then_checks_and_a_bad_line_is_an_error_not_a_traceback(
    tmp_path, monkeypatch, capsys
):
    allow = tmp_path / "file_size_allow.txt"
    allow.write_text("# head\n3000 app/big.py\n1600 app/gone.py\n", encoding="utf-8")
    monkeypatch.setattr(size, "ALLOW", allow)
    monkeypatch.setattr(size, "sources", lambda root: ["app/big.py"])
    monkeypatch.setattr(size, "lines", lambda path: 2500)
    assert size.main(["--update"]) == 0
    assert allow.read_text(encoding="utf-8") == "# head\n2500 app/big.py\n"
    allow.write_text("x app/big.py\n", encoding="utf-8")
    assert size.main([]) == 1
    assert "error: file_size_allow.txt line 1: not `<lines> <path>`" in capsys.readouterr().out


def test_the_files_checked_are_the_sources_git_holds_but_no_generated_one():
    found = size.sources(size.ROOT)
    assert "scripts/check_file_size.py" in found and "app/ledger.py" in found
    assert "frontend/src/api/generated.ts" not in found
    assert all(path.endswith((".py", ".ts", ".tsx")) for path in found)
    assert not [path for path in found if path.startswith(("frontend/e2e/", "alembic/", "docs/"))]
