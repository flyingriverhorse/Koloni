"""Fails unless requirements-dev.lock satisfies pyproject.toml (backend.yml's lint part).

    python .github/scripts/check_lock.py

Every requirement of [project].dependencies and the dev extra must be in the lock at a version its
specifier accepts. Dependabot bumps pyproject.toml but cannot rebuild the lock (compiled on
Windows), so its pull request would otherwise pass on the old versions. Offline: reads two files.
"""

import re
import sys
import tomllib
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[2]


def name(text: str) -> str:
    return re.sub(r"[-_.]+", "-", text).lower()


def problems(pyproject: str, lock: str) -> list[str]:
    project = tomllib.loads(pyproject)["project"]
    pins = re.findall(r"^([A-Za-z0-9._-]+)==(\S+)", lock, re.MULTILINE)
    locked = {name(n): v for n, v in pins}
    found = []
    for line in [*project["dependencies"], *project["optional-dependencies"]["dev"]]:
        req = Requirement(line)
        version = locked.get(name(req.name))
        if version is None:
            found.append(f"{req.name}: not in requirements-dev.lock")
        elif not req.specifier.contains(version, prereleases=True):
            found.append(f"{req.name}: locked {version}, pyproject.toml wants {req.specifier}")
    return found


def main() -> int:
    found = problems((ROOT / "pyproject.toml").read_text(encoding="utf-8"),
                     (ROOT / "requirements-dev.lock").read_text(encoding="utf-8"))
    for line in found:
        print(f"error: {line}", file=sys.stderr)
    if found:
        print("Rebuild the lock with the command in its header.", file=sys.stderr)
        return 1
    print("requirements-dev.lock satisfies pyproject.toml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
