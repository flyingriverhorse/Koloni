"""89m: "Finish only when the tests pass". A Claude Code agent that changed files is sent back
to work while the project's tests fail (`AgentRunner._tests_at_stop`); here, which command
those tests are and whether that is on when the user has not said."""

import json
import math
from pathlib import Path

from sqlalchemy import select

from app.db.models import Command, Conversation, Project, Run

# A previous run of the test command this quick, on record: on by default.
FAST_SECONDS = 60
NO_COMMAND = "no test command found - set a check command to use this"
NOT_TIMED = "test time not known yet - turn it on if your tests are quick"
NOT_STARTED = "the tests' command did not start last time - check it, then turn this on"
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


def automatic(session, project: Project) -> dict:
    """What it is when the user has not said: on where a run of the test command KOLONİ made
    in this project took at most FAST_SECONDS; and why, in words."""
    command = command_of(project.root_path, project.check_command)
    if command is None:
        return {"on": False, "command": None, "reason": NO_COMMAND}
    took = session.execute(
        select(Command.started_at, Command.ended_at, Command.status, Command.exit_code,
               Command.output)
        .join(Run, Run.id == Command.run_id)
        .join(Conversation, Conversation.id == Run.conversation_id)
        # (A CLI's own run counts too: its times are when KOLONİ saw it start and end - a wait
        # for the user's yes in them makes it look slower.)
        # shortcut: one first seen only at its end reads as ~0 s, quick; leave CLI rows out
        # (origin "cli") if such a "fast" is ever wrong in use.
        .where(Conversation.project_id == project.id, Command.command == command,
               Command.status.in_(("exited", "failed_to_start")),
               Command.ended_at.is_not(None))
        .order_by(Command.ended_at.desc()).limit(1)
    ).first() if session is not None else None
    if took is None:
        return {"on": False, "command": command, "reason": NOT_TIMED}
    if took[2] != "exited" or took[0] is None or did_not_start(took[3], took[4] or ""):
        return {"on": False, "command": command, "reason": NOT_STARTED}
    seconds = (took[1] - took[0]).total_seconds()
    if seconds <= FAST_SECONDS:
        return {"on": True, "command": command,
                "reason": f"the tests took {max(1, round(seconds))} s last time"}
    return {"on": False, "command": command,
            "reason": f"the tests took {math.ceil(seconds / 60)} min last time"}


def is_on(session, project: Project) -> bool:
    return project.finish_tests if project.finish_tests is not None \
        else automatic(session, project)["on"]
