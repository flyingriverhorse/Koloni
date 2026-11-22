"""The project's test command where the user named none - one its files show - and whether a
test run that ended says its program was not there (89m; read by the end check, `app.proof`)."""

import json
import re
from collections.abc import Callable
from pathlib import Path

# What a shell or Python says where the tests' program is not there; and their exit codes.
# (Measured, both exit 1: Windows PowerShell 5.1 "The term 'x' is not recognized as the name of
# a cmdlet, function, script file, or operable program" + CommandNotFoundException; PowerShell 7
# "… is not recognized as a name of a cmdlet, function, script file, or executable program".)
NOT_FOUND = ("not recognized as the name of a cmdlet", "not recognized as a name of a cmdlet",
             "is not recognized as an internal or external command", "command not found",
             "No module named pytest")
NOT_FOUND_CODES = (127, 9009)


def command_of(root: str, check_command: str | None) -> str | None:
    """The project's check command, or one the files of a folder show (S1b, plan decision 11:
    any language): pytest, `npm test`, then each marker of `MARKER_TESTS` in its order."""
    if check_command:
        return check_command
    folder = Path(root)
    if (folder / "pyproject.toml").is_file() or (folder / "pytest.ini").is_file():
        return "python -m pytest -q"
    test = _script(folder / "package.json")
    # (Not the line `npm init` writes, which only fails.)
    if isinstance(test, str) and test and "no test specified" not in test:
        return "npm test"
    found = next((command(folder) for command in MARKER_TESTS if command(folder)), None)
    return found or ("python -m pytest -q" if (folder / "tests").is_dir() else None)


def _script(manifest: Path) -> object:
    """A package.json's or composer.json's own `test` script; None: none."""
    try:
        return json.loads(manifest.read_text(encoding="utf-8"))["scripts"]["test"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _has(folder: Path, *patterns: str) -> bool:
    return any(next(folder.glob(pattern), None) is not None for pattern in patterns)


def _make_test(folder: Path) -> str | None:
    try:
        text = (folder / "Makefile").read_text(encoding="utf-8", errors="replace")[:64 * 1024]
    except OSError:
        return None
    return "make test" if re.search(r"^test\s*:", text, re.MULTILINE) else None


# Plan decision 11: a folder's marker files, and the command that runs its tests - the first that
# fits. shortcut: none of these is measured here (no Go, Rust, Java, .NET, Ruby, PHP, Elixir,
# Swift or CMake on this machine); each is the tool's documented default. `./gradlew` runs
# gradlew.bat in PowerShell too (its PATHEXT) - measure it on Windows when a Gradle project is met.
MARKER_TESTS: tuple[Callable[[Path], str | None], ...] = (
    lambda folder: "go test ./..." if (folder / "go.mod").is_file() else None,
    lambda folder: "cargo test" if (folder / "Cargo.toml").is_file() else None,
    lambda folder: "mvn -q test" if (folder / "pom.xml").is_file() else None,
    lambda folder: ("./gradlew test" if (folder / "gradlew").is_file() else "gradle test")
    if _has(folder, "build.gradle", "build.gradle.kts") else None,
    lambda folder: "dotnet test" if _has(folder, "*.sln", "*.csproj", "*.fsproj") else None,
    lambda folder: "bundle exec rspec" if (folder / "Gemfile").is_file() and (
        folder / "spec").is_dir() else None,
    lambda folder: ("composer test" if _script(folder / "composer.json") else
                    "vendor/bin/phpunit" if _has(folder, "phpunit.xml", "phpunit.xml.dist")
                    else None) if (folder / "composer.json").is_file() else None,
    lambda folder: "mix test" if (folder / "mix.exs").is_file() else None,
    lambda folder: "swift test" if (folder / "Package.swift").is_file() else None,
    lambda folder: "ctest --test-dir build" if (folder / "CMakeLists.txt").is_file() else None,
    _make_test,
)


def did_not_start(code: int | None, output: str) -> bool:
    """Whether a run that ended says its program was not found: nothing an agent can fix."""
    said = " ".join(output.split())  # (PowerShell wraps its words at the console's width)
    return code in NOT_FOUND_CODES or any(words in said for words in NOT_FOUND)
