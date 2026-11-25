"""☾ Away, park and continue (§10): in a job while the user is away, a command's card or a question
the Orchestrator cannot answer does not stop the job - KOLONİ parks it (`Parked`), tells the agent
it did not run, and the job goes on. In the morning the user decides each under Waiting for you.

Every word here is KOLONİ's; what is parked - a line, a question - is data, quoted where it is said
to a model, never read as an instruction."""

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.commands import _BLOCKS, _parts, _program
from app.copies import NOT_COPIED
from app.db.away_models import Parked
from app.db.models import BacklogTask
from app.team import quoted

# To the agent whose command was parked (CLI: `deny(text, fixed=True)`).
PARKED = (
    "KOLONİ parked this for the user, who is away: {what}. It did not run. Do what you can "
    "without it, and say in your summary what waits."
)
# ...whose question was.
PARKED_ASKED = (
    "KOLONİ parked this for the user, who is away: {what}. Do what you can without their answer, "
    "and say in your summary what waits."
)
WHY = "{n} parked"  # (a job's reason to wait, `away.turn_ended`)
# Why a question was parked where the Orchestrator gave no answer that counts.
COULD_NOT_ANSWER = "The Orchestrator could not answer it"
# What a package manager's `run` is followed by: a script's name, not a folder.
_RUNNERS = frozenset({"npm", "pnpm", "yarn", "bun"})


def said(line: str, cwd: str | None) -> str:
    """What the agent is told of its parked command."""
    at = f" in {cwd}" if cwd and cwd != "." else ""
    return PARKED.format(what=f"run {quoted(line)}{at}")


def needs_project(line: str) -> bool:
    """Whether a command needs the project itself, not a copy of it: a stage of it runs git (a
    copy has no `.git`), or a word of it names a folder a copy leaves out (`copies.NOT_COPIED`:
    `build`, `dist`...), split as `away.kept_out` splits words - not `npm run build`'s script.
    shortcut: a script named by its runner without `run` (`yarn build`) counts as a folder; read
    the runner's own scripts if that keeps a line closed that need not be."""
    for words in _parts(line, _BLOCKS):
        if words and _program(words[0]) == "git":
            return True
        if words and _program(words[0]) in _RUNNERS and words[1:2] == ["run"]:
            words = words[:2] + words[3:]  # (its script's name is no folder)
        if any(
            part.casefold() in NOT_COPIED
            for word in words
            for piece in re.split(r"[=,;:<>|&()]+", word.strip("'\""))
            for part in re.split(r"[\\/]", piece)
        ):
            return True
    return False


def park(
    session: Session, task: BacklogTask, kind: str, ref_id: str | None, what: str, data: dict
) -> Parked:
    """A row parked for task `task` (a job of an Away) - or the one parked already: the same kind,
    the same line or question and folder, not decided yet. Not committed."""
    for one in session.scalars(
        select(Parked).where(
            Parked.task_id == task.id,
            Parked.kind == kind,
            Parked.what == what,
            Parked.decision.is_(None),
        )
    ):
        if one.data.get("cwd") == data.get("cwd"):
            return one
    seq = session.scalar(select(func.max(Parked.seq)).where(Parked.away_run_id == task.away_run_id))
    row = Parked(
        away_run_id=task.away_run_id,
        task_id=task.id,
        seq=(seq or 0) + 1,
        kind=kind,
        ref_id=ref_id,
        what=what,
        data=data,
    )
    session.add(row)
    session.flush()
    return row
