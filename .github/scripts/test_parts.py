"""The test files of one CI part (backend.yml): each tests/test_*.py in exactly one of N parts.

    python .github/scripts/test_parts.py PART COUNT   # PART 0..COUNT-1; prints one file a line

Largest file first, each to the part with the fewest bytes so far, so the parts take about as long.
shortcut: a file's size stands for its run time; if one part keeps finishing well after the
others, weigh by pytest's --durations instead.
"""

import sys
from pathlib import Path


def parts(files: list[Path], count: int) -> list[list[str]]:
    loads = [0] * count
    split: list[list[str]] = [[] for _ in range(count)]
    for file in sorted(files, key=lambda f: (-f.stat().st_size, f.as_posix())):
        lightest = loads.index(min(loads))
        split[lightest].append(file.as_posix())
        loads[lightest] += file.stat().st_size
    return split


def main() -> int:
    part, count = int(sys.argv[1]), int(sys.argv[2])
    files = sorted(Path("tests").glob("test_*.py"))
    split = parts(files, count)
    # Every test file runs, once: the parts are disjoint and together are all of them.
    assert sorted(f for files_of in split for f in files_of) == [f.as_posix() for f in files]
    if not 0 <= part < count or not split[part]:
        print(f"no test files for part {part} of {count}", file=sys.stderr)
        return 1
    print(*split[part], sep="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
