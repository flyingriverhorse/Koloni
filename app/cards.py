"""Cards measured (0.1.7, the user: "evet ölçelim"): why each command card was asked, how the user
answered, and what "Check what I said first" decided - and, where the user approved the same
delete again and again, a line for the project's rules that would spare its card.

Every word here is KOLONİ's: a card's reason is the gate's own family of it (`card_reason`, when
the card opens - never an agent's words); a suggested rule is built from KOLONİ's words and the
targets of a command the user approved unchanged, each a plain relative path, and is saved only by
the user's click on the app's own page (`app.api.cards`)."""

import hashlib
import json
import posixpath
import re
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import judge
from app.commands import (
    SEARCHES_FOLDER,
    _program,
    _words,
    harm_class,
    harms,
    is_plain,
    names_secret,
    with_cwd,
)
from app.db.models import Command, Conversation, Project, Run, now

# The families of why a card was asked, in the order the Usage page says them.
REASONS = {
    "delete": "Deletes or overwrites",
    "send": "Sends off this machine",
    "install": "Installs packages",
    "shell": "Runs a command through a shell",
    "secret": "A secret file",
    "standing": "A file that steers later turns",
    "stop": "Stops programs by name",
    "outside": "Out of its working copy",
    "web": "The web, with web tools off",
    "server": "Starts a server",
    "rule": "No rule covers it",
    "other": "Another reason",
}
# A reason's sentence (`harms`, `copy_reason`, `installs`, `runs_another`, `web_off_reason`, the
# disposable look's) by how it starts: case matters - "it names" a path out of the copy, "Names"
# a file that steers later turns.
_FAMILIES = (
    (
        "delete",
        r"(?:Deletes|Empties|Throws away|Overwrites or deletes|it deletes|it rebuilds"
        r"|what it deletes changed)\b",
    ),
    ("send", r"It (?:reaches beyond|sends work off)\b"),
    ("install", r"It (?:installs|downloads a package)\b"),
    ("shell", r"It (?:runs another command|hands shells)\b"),
    ("stop", r"Stops programs\b"),
    ("secret", r"(?:Opens a secret file|It searches the whole folder)\b"),
    ("standing", r"(?:Names|Sets this project's git|Applies a patch)\b"),
    ("outside", r"(?:it names|it writes in|Climbs out|Makes a link|Opens a git worktree)\b"),
    ("web", r"web is off\b"),
)
_FAMILY = [(name, re.compile(pattern)) for name, pattern in _FAMILIES]

# A suggestion: a delete the user approved unchanged this many times, of the last DAYS.
TIMES, DAYS = 5, 30
# What deletes files by their names, and the switches it may have in a suggested rule - none that
# takes a value (`-ErrorAction x`, `-Exclude src`: a value read as a target names what was not
# deleted) nor one that reaches further (`del /s`, `rmdir -p`). shortcut: deletes only; add a
# family (a push to a branch) when its rule's words are as plain.
_DELETERS = {
    "rm": frozenset(
        {
            "-r",
            "-R",
            "-f",
            "-rf",
            "-fr",
            "-Rf",
            "-fR",
            "-d",
            "-v",
            "--recursive",
            "--force",
            "--dir",
            "--verbose",
        }
    ),
    "rmdir": frozenset({"-v", "--verbose"}),
    "rd": frozenset({"/s", "/q"}),
    "del": frozenset({"/q", "/f"}),
    "erase": frozenset({"/q", "/f"}),
    "remove-item": frozenset({"-recurse", "-force"}),
    "ri": frozenset({"-recurse", "-force"}),
}
_CASED = frozenset({"rm", "rmdir"})  # (PowerShell's and cmd's switches are read in any case)
# A target a rule may name: a relative path of plain characters, never a glob, a variable, `..`.
_TARGET = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-/]{0,79}")
MOST_TARGETS = 3


def family(sentence: str) -> str:
    """A reason's sentence as a `REASONS` key; "other" for one none of them starts so."""
    return next((name for name, start in _FAMILY if start.match(sentence)), "other")


def card_reason(
    judged: str,
    instructions: bool,
    why: str,
    *,
    searched: bool = False,
    web_off: bool = False,
    keep_running: bool = False,
) -> str:
    """Why a card was asked, as the gate saw it the moment it opened: the sentence its card shows
    (the harm of `judged` - the command with its folder, `with_cwd` - else the reason its call was
    given, `ToolCall.why_asked`, else the folder search), then web off, a server, else no rule
    covered it at the chat's level."""
    said = harms(judged, instructions) or why or (SEARCHES_FOLDER if searched else "")
    if said:
        return family(said)
    if names_secret(judged):
        return "secret"
    return "web" if web_off else "server" if keep_running else "rule"


def _counts() -> dict:
    return {"asked": 0, "approved": 0, "rejected": 0, "unanswered": 0}


def stats(session: Session, project_id: str | None, since: datetime | None) -> dict:
    """The cards asked since `since` (None: all) in a project's chats (None: every chat's): how
    many, answered how - approved or rejected by the user, or no answer (the turn ended first) -
    by reason, the average seconds to an answer (None: none answered), and the three outcomes of
    "Check what I said first". Only cards from 0.1.7 on carry their reason (`asked_reason`)."""
    asked = select(
        Command.asked_reason,
        Command.status,
        Command.judged,
        Command.created_at,
        Command.decided_at,
    ).join(Run, Run.id == Command.run_id)
    if project_id is not None:
        asked = asked.join(Conversation, Conversation.id == Run.conversation_id).where(
            Conversation.project_id == project_id
        )
    if since is not None:
        asked = asked.where(Command.created_at >= since)
    total, by_reason, waited, checked = _counts(), {}, [], {"run": 0, "refuse": 0, "ask": 0}
    for reason, status, judged, made, decided in session.execute(asked):
        if judged and judged.get("verdict") in checked:
            checked[judged["verdict"]] += 1
        if reason is None:
            continue
        how = (
            "unanswered" if decided is None else "rejected" if status == "rejected" else "approved"
        )
        one = by_reason.setdefault(reason, _counts())
        for counts in (total, one):
            counts["asked"] += 1
            counts[how] += 1
        if decided is not None:
            waited.append((decided - made).total_seconds())
    return {
        **total,
        "by_reason": [
            {"reason": key, "said": REASONS[key], **by_reason[key]}
            for key in REASONS
            if key in by_reason
        ],
        "decide_seconds": round(sum(waited) / len(waited), 1) if waited else None,
        "checked": checked,
    }


def _targets(command: str, cwd: str | None) -> list[str] | None:
    """What a plain delete names, each joined with its folder; None where its folder is not known,
    a switch is not one of its plain ones (`_DELETERS`), or a target is no plain relative path."""
    words = _words(command)
    program = _program(words[0]) if words else ""
    if cwd is None or program not in _DELETERS:
        return None
    switches = [w for w in words[1:] if w.startswith(("-", "/"))]
    plain = _DELETERS[program]
    if any((w if program in _CASED else w.casefold()) not in plain for w in switches):
        return None
    named = [w for w in words[1:] if not w.startswith(("-", "/"))]
    if not named or len(named) > MOST_TARGETS or not all(_TARGET.fullmatch(w) for w in named):
        return None
    joined = [posixpath.normpath(posixpath.join(cwd, w)) for w in named]
    if any(one in (".", "..") or one.startswith(("../", "/")) for one in joined):
        return None
    return joined


def rule_line(command: str, cwd: str | None) -> str | None:
    """The line for the project's rules that names this delete and its targets - "You may delete
    build." - in KOLONİ's words; None: no such line (`_targets`)."""
    if cwd is None or not is_plain(command) or harm_class(with_cwd(command, cwd)) != "soft":
        return None
    targets = _targets(command, cwd)
    if targets is None:
        return None
    named = targets[0] if len(targets) == 1 else f"{', '.join(targets[:-1])} and {targets[-1]}"
    return f"You may delete {named}."


def _stands(rules: str, line: str) -> bool:
    """Whether the check of the user's words would let a run stand on `line` in the rules as they
    would be with it (`judge.verdict`): never under a heading or beside a line that forbids or
    sets a condition."""
    answer = json.dumps({"verdict": "run", "quote": line, "why": ""})
    said = judge.said(None, with_rule(rules, line), [])
    return (judge.verdict(answer, said) or {}).get("verdict") == "run"


def _has(rules: str, line: str) -> bool:
    """Whether the rules hold `line` as a line of their own (a list item too)."""
    return any(judge.LIST_MARK.sub("", one.strip()) == line for one in rules.splitlines())


def key_of(project_id: str, command: str, cwd: str | None) -> str:
    return hashlib.sha256(f"{project_id}\n{cwd or '.'}\n{command}".encode()).hexdigest()[:16]


def suggestions(session: Session, project: Project, rules: str, added: bool = False) -> list[dict]:
    """The deletes the user approved unchanged TIMES times or more in DAYS, in this project's
    chats - each with the line for the project's rules (`rules`, as in effect) that would spare
    its card at Full auto with Check what I said first on; one the rules hold already is left out
    (`added` False)."""
    approved = (
        select(Command.command, Command.cwd)
        .join(Run, Run.id == Command.run_id)
        .join(Conversation, Conversation.id == Run.conversation_id)
        .where(
            Conversation.project_id == project.id,
            Command.asked_reason == "delete",
            Command.cwd.is_not(None),  # (a CLI's whose folder is not known: no rule names it)
            Command.decided_at.is_not(None),
            Command.status != "rejected",
            Command.created_at >= now() - timedelta(days=DAYS),
        )
    )
    times: dict[tuple[str, str], int] = {}
    for command, cwd in session.execute(approved):
        shape = (" ".join(command.split()), cwd)
        times[shape] = times.get(shape, 0) + 1
    found = []
    for (command, cwd), n in sorted(times.items(), key=lambda one: -one[1]):
        line = rule_line(command, cwd) if n >= TIMES else None
        if line is not None and (added or not _has(rules, line)) and _stands(rules, line):
            found.append(
                {
                    "key": key_of(project.id, command, cwd),
                    "command": command,
                    "cwd": cwd,
                    "times": n,
                    "rule": line,
                }
            )
    return found


def with_rule(rules: str | None, line: str) -> str:
    """The project's rules with `line` as a line of its own at their end - as they are where it is
    there already."""
    rules = rules or ""
    if _has(rules, line):
        return rules
    return f"{rules.rstrip()}\n{line}" if rules.strip() else line
