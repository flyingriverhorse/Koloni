"""scripts/check_file_size.py: a source file over 1500 lines fails unless the allow-list holds it,
and an allowed one fails once it grows past its count or drops to the limit; small fixtures."""

import importlib.util
from pathlib import Path

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
    assert notes == [
        "app/big.py: 2900 lines, down from 3000 - lower its line in file_size_allow.txt"
    ]
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


def test_the_allow_list_is_read_with_its_comments():
    assert size.read_allow(
        "# why\n\n10612 app/agent/__init__.py  # the runner\n2000 tests/t.py\n"
    ) == {
        "app/agent/__init__.py": 10612,
        "tests/t.py": 2000,
    }


def test_the_files_checked_are_the_sources_git_holds_but_no_generated_one():
    found = size.sources(size.ROOT)
    assert "scripts/check_file_size.py" in found and "app/ledger.py" in found
    assert "frontend/src/api/generated.ts" not in found
    assert all(path.endswith((".py", ".ts", ".tsx")) for path in found)
    assert not [path for path in found if path.startswith(("frontend/e2e/", "alembic/", "docs/"))]
