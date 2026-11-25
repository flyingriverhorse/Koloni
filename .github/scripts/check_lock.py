"""Fails unless requirements-dev.lock and requirements-lint.lock satisfy pyproject.toml
(backend.yml's lint part).

    python .github/scripts/check_lock.py

Every requirement of [project].dependencies and the dev extra must be in the dev lock at a version
its specifier accepts; those and the lint extra's in the lint lock, which installs on top of the dev
lock (CI's lint part) and so may not hold another version of a package the dev lock pins. Dependabot
bumps pyproject.toml but cannot rebuild a lock (compiled on Windows), so its pull request would
otherwise pass on the old versions. Offline: reads three files.
"""

import re
import sys
import tomllib
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[2]


def name(text: str) -> str:
    return re.sub(r"[-_.]+", "-", text).lower()


def pinned(lock: str) -> dict[str, str]:
    return {name(n): v for n, v in re.findall(r"^([A-Za-z0-9._-]+)==(\S+)", lock, re.MULTILINE)}


def problems(pyproject: str, lock: str, extra: str = "dev") -> list[str]:
    project = tomllib.loads(pyproject)["project"]
    locked = pinned(lock)
    found = []
    for line in [*project["dependencies"], *project["optional-dependencies"][extra]]:
        req = Requirement(line)
        version = locked.get(name(req.name))
        if version is None:
            found.append(f"{req.name}: not in requirements-{extra}.lock")
        elif not req.specifier.contains(version, prereleases=True):
            found.append(f"{req.name}: locked {version}, pyproject.toml wants {req.specifier}")
    return found


def moved(dev: str, lint: str) -> list[str]:
    """What installing the lint lock on top of the dev lock would change."""
    under = pinned(dev)
    return [
        f"{one}: requirements-lint.lock holds {version}, requirements-dev.lock {under[one]}"
        for one, version in pinned(lint).items()
        if one in under and under[one] != version
    ]


def main() -> int:
    pyproject, dev, lint = (
        (ROOT / file).read_text(encoding="utf-8")
        for file in ("pyproject.toml", "requirements-dev.lock", "requirements-lint.lock")
    )
    found = [*problems(pyproject, dev), *problems(pyproject, lint, "lint"), *moved(dev, lint)]
    for line in found:
        print(f"error: {line}", file=sys.stderr)
    if found:
        print("Rebuild the locks, the dev lock first, as their headers say.", file=sys.stderr)
        return 1
    print("requirements-dev.lock and requirements-lint.lock satisfy pyproject.toml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
