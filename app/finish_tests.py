"""The project's test command where the user named none - one its files show - and whether a
test run that ended says its program was not there (89m; read by the end check, `app.proof`)."""

import json
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
    """The project's check command, or one its files show: pytest, or `npm test`."""
    if check_command:
        return check_command
    folder = Path(root)
    if (folder / "pyproject.toml").is_file() or (folder / "pytest.ini").is_file():
        return "python -m pytest -q"
    try:
        test = json.loads((folder / "package.json").read_text(encoding="utf-8"))["scripts"]["test"]
    except (OSError, ValueError, KeyError, TypeError):
        test = None
    # (Not the line `npm init` writes, which only fails.)
    if isinstance(test, str) and test and "no test specified" not in test:
        return "npm test"
    return "python -m pytest -q" if (folder / "tests").is_dir() else None


def did_not_start(code: int | None, output: str) -> bool:
    """Whether a run that ended says its program was not found: nothing an agent can fix."""
    said = " ".join(output.split())  # (PowerShell wraps its words at the console's width)
    return code in NOT_FOUND_CODES or any(words in said for words in NOT_FOUND)
