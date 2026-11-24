"""Fails when a source file grows past LIMIT lines (the user, 24 Nov: "a 1500-line limit per file").

  python scripts/check_file_size.py

Reads the `.py`, `.ts` and `.tsx` files under app/, frontend/src/, scripts/ and tests/ that git
tracks or would (gitignored ones are skipped, and generated ones: `GENERATED`). Fails (exit 1) on:
- a file over LIMIT lines that is not on the allow-list (`ALLOW`): split it;
- an allowed file over the count the list records for it: split it rather than raise the count;
- an allowed file now at LIMIT or under, or gone: take it off the list.
The list records each file that was over the limit when the check came in, with its line count
then; it only gets shorter. An allowed file that shrank is said with its new count, to lower its
line by hand (no failure). Standard library only.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOW = ROOT / "scripts" / "file_size_allow.txt"
LIMIT = 1500
FOLDERS = ("app/", "frontend/src/", "scripts/", "tests/")
SUFFIXES = (".py", ".ts", ".tsx")
# Made by a tool, not written: openapi-typescript's (`npm run generate:api`).
GENERATED = frozenset({"frontend/src/api/generated.ts"})


def lines(path: Path) -> int:
    """A file's lines as `wc -l` counts them, and a last one with no newline after it."""
    data = path.read_bytes()
    return data.count(b"\n") + (not data.endswith(b"\n") and bool(data))


def sources(root: Path) -> list[str]:
    """The files checked, posix and from the root: what git tracks, and what it would track."""
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", *FOLDERS],
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout.decode()
    return sorted(
        {
            path
            for path in listed.split("\0")
            if path.endswith(SUFFIXES) and path not in GENERATED and (root / path).is_file()
        }
    )


def read_allow(text: str) -> dict[str, int]:
    """The allow-list: `<lines> <path>` a line; `#` starts a comment."""
    allowed = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            count, path = line.split(maxsplit=1)
            allowed[path] = int(count)
    return allowed


def check(counts: dict[str, int], allowed: dict[str, int]) -> tuple[list[str], list[str]]:
    """What fails and what is only said, from each file's line count and the allow-list."""
    errors, notes = [], []
    for path, count in sorted(counts.items()):
        was = allowed.get(path)
        if was is None:
            if count > LIMIT:
                errors.append(f"{path}: {count} lines, over the limit of {LIMIT} - split it")
        elif count <= LIMIT:
            errors.append(f"{path}: {count} lines, under the limit now - take it off {ALLOW.name}")
        elif count > was:
            errors.append(
                f"{path}: {count} lines, past the {was} {ALLOW.name} allows - split it rather "
                "than raise its count"
            )
        elif count < was:
            notes.append(f"{path}: {count} lines, down from {was} - lower its line in {ALLOW.name}")
    errors += [
        f"{path}: gone - take it off {ALLOW.name}"
        for path in sorted(allowed.keys() - counts.keys())
    ]
    return errors, notes


def main() -> int:
    counts = {path: lines(ROOT / path) for path in sources(ROOT)}
    errors, notes = check(counts, read_allow(ALLOW.read_text(encoding="utf-8")))
    for note in notes:
        print(f"note: {note}")
    for error in errors:
        print(f"error: {error}")
    if errors:
        print(f"check_file_size: {len(errors)} file(s) to fix (limit {LIMIT} lines)")
        return 1
    print(f"check_file_size: OK ({len(counts)} files; limit {LIMIT} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
