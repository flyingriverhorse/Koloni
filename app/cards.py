"""Cards measured (0.1.7, the user: "evet ölçelim"): why each command card was asked, how the user
answered, and what "Check what I said first" decided - and, where the user approved the same
delete again and again, a line for the project's rules that would spare its card.

Every word here is KOLONİ's: a card's reason is the gate's own family of it (`card_reason`, when
the card opens - never an agent's words); a suggested rule is built from KOLONİ's words and the
targets of a command the user approved unchanged, each a plain relative path, and is saved only by
the user's click on the app's own page (`app.api.cards`)."""

import fnmatch
import hashlib
import json
import re
from datetime import datetime, timedelta

from sqlalchemy import Select, case, func, select
from sqlalchemy.orm import Session

from app import judge, memory
from app.commands import (
    SEARCHES_FOLDER,
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
    "judge": "Full auto's judge found it risky",
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
    ("judge", r"KOLONİ's judge: "),  # (Full auto's judge's card: `risk_judge.CARD`)
)
_FAMILY = [(name, re.compile(pattern)) for name, pattern in _FAMILIES]

# The family of a card a CLI asked for with a reason of its own (Codex: to leave its sandbox) where
# KOLONİ's gate gave none: the CLI's words are on the card, never read for its family (review of
# the card measurement: a reason that started "Deletes" made any command a delete card).
CLI_ASKED = "The CLI asked for it in words of its own"

# A suggestion: a delete the user approved unchanged this many times, of the last DAYS - of the
# MOST_SUGGESTED commands approved most, each no longer than MAX_RULE (a plain delete of
# MOST_TARGETS paths is far shorter; a longer one is not read: its harm check is linear but slow).
TIMES, DAYS = 5, 30
MOST_SUGGESTED = 20
MAX_RULE = 400
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
# A target a rule may name, joined with its folder: a relative path every part of which is plain
# characters - never a glob, a variable, `.`, `..`, a dot file, a part that ends in a dot.
_PART = re.compile(r"[A-Za-z0-9_](?:[A-Za-z0-9_.\-]*[A-Za-z0-9_\-])?")
MOST_PATH = 80
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
    (the harm of `judged` - the command with its folder, `with_cwd` - else the reason KOLONİ gave
    its call, `why` - `ToolCall.why_asked`, never a CLI's own words: `CLI_ASKED` -, else the
    folder search), then web off, a server, else no rule covered it at the chat's level."""
    said = harms(judged, instructions) or why or (SEARCHES_FOLDER if searched else "")
    if said:
        return family(said)
    if names_secret(judged):
        return "secret"
    return "web" if web_off else "server" if keep_running else "rule"


def _counts() -> dict:
    return {"asked": 0, "approved": 0, "rejected": 0, "unanswered": 0}


_VERDICTS = ("run", "refuse", "ask")


def _in_period(query: Select, project_id: str | None, since: datetime | None) -> Select:
    query = query.join(Run, Run.id == Command.run_id)
    if project_id is not None:
        query = query.join(Conversation, Conversation.id == Run.conversation_id).where(
            Conversation.project_id == project_id
        )
    return query if since is None else query.where(Command.created_at >= since)


def stats(session: Session, project_id: str | None, since: datetime | None) -> dict:
    """The cards asked since `since` (None: all) in a project's chats (None: every chat's): how
    many, answered how - approved or rejected by the user, or no answer (the turn ended first) -
    by reason, the average seconds to an answer (None: none answered), and the three outcomes of
    "Check what I said first". Only cards from 0.1.7 on carry their reason (`asked_reason`).
    Counted by the database: a row for each reason and answer, and for each outcome (review: every
    command of the period was read, its check's record with it)."""
    how = case(
        (Command.decided_at.is_(None), "unanswered"),
        (Command.status == "rejected", "rejected"),
        else_="approved",
    )
    waited = (func.julianday(Command.decided_at) - func.julianday(Command.created_at)) * 86400
    asked = _in_period(
        select(Command.asked_reason, how, func.count(), func.sum(waited))
        .where(Command.asked_reason.in_(REASONS))
        .group_by(Command.asked_reason, how),
        project_id,
        since,
    )
    verdict = Command.judged["verdict"].as_string()
    judged = _in_period(
        select(verdict, func.count()).where(verdict.in_(_VERDICTS)).group_by(verdict),
        project_id,
        since,
    )
    total, by_reason, seconds, answered = _counts(), {}, 0.0, 0
    for reason, said, n, took in session.execute(asked):
        for counts in (total, by_reason.setdefault(reason, _counts())):
            counts["asked"] += n
            counts[said] += n
        if said != "unanswered":
            seconds, answered = seconds + (took or 0.0), answered + n
    return {
        **total,
        "by_reason": [
            {"reason": key, "said": REASONS[key], **by_reason[key]}
            for key in REASONS
            if key in by_reason
        ],
        "decide_seconds": round(seconds / answered, 1) if answered else None,
        "checked": {**dict.fromkeys(_VERDICTS, 0), **dict(session.execute(judged).tuples().all())},
    }


def _targets(command: str, cwd: str | None) -> list[str] | None:
    """What a plain delete names, each joined with its folder; None where its folder is not known,
    a switch is not one of its plain ones (`_DELETERS`), or a target is no plain relative path."""
    words = _words(command)
    # (By its bare name alone: `./rm` is a script of the project's, `C:/x/rm.exe` another program.)
    bare = words[0] if words else ""
    program = bare if bare in _CASED else bare.casefold()
    if cwd is None or program not in _DELETERS:
        return None
    switches = [w for w in words[1:] if w.startswith(("-", "/"))]
    plain = _DELETERS[program]
    if any((w if program in _CASED else w.casefold()) not in plain for w in switches):
        return None
    # (`./build` is `build`: §8's two lines that disagree name it so - "Never delete ./build.")
    named = [w.removeprefix("./") for w in words[1:] if not w.startswith(("-", "/"))]
    if not named or len(named) > MOST_TARGETS:
        return None
    # The path as joined, never resolved, is what must be plain - its folder is on record as the
    # agent's command gave it (review: a cwd "all of src and" wrote "You may delete all of src
    # and/build.", and `x/../src` "You may delete src."). The root is "." - or "", as a CLI's
    # command at the root may be on record.
    joined = [w.rstrip("/") if cwd in ("", ".") else f"{cwd}/{w}".rstrip("/") for w in named]
    if not all(_plain_path(one) for one in joined):
        return None
    return joined


def _plain_path(path: str) -> bool:
    return len(path) <= MOST_PATH and all(_PART.fullmatch(part) for part in path.split("/"))


def rule_line(command: str, cwd: str | None) -> str | None:
    """The line for the project's rules that names this delete and its targets, each as a path
    from the project's root - "You may delete ./build." (review: a bare word, "everything", read
    as a grant of all) - in KOLONİ's words; None: no such line (`_targets`)."""
    if len(command) > MAX_RULE or cwd is None or not is_plain(command):
        return None
    targets = _targets(command, cwd)
    if targets is None or harm_class(with_cwd(command, cwd)) != "soft":
        return None
    paths = [f"./{one}" for one in targets]
    named = paths[0] if len(paths) == 1 else f"{', '.join(paths[:-1])} and {paths[-1]}"
    return f"You may delete {named}."


def _stands(rules: str, line: str) -> bool:
    """Whether the check of the user's words would let a run stand on `line` in the rules as they
    would be with it (`judge.verdict`): never under a heading or beside a line that forbids or
    sets a condition."""
    answer = json.dumps({"verdict": "run", "quote": line, "why": ""})
    said = judge.said(None, with_rule(rules, line), [])
    return (judge.verdict(answer, said) or {}).get("verdict") == "run"


def mentioned(texts: list[str | None], command: str, cwd: str | None) -> str | None:
    """S: the first line of the user's words - their preferences, the project's rules - that
    names a target of this delete at all, however spelled (`./build`, `.\\build`, `build/`,
    `build`, a path under it: `build/keep.txt`), or a folder it is in ("anything under out"), its
    own name ("any build folder"), a full path ending in it, or a pattern that takes it in
    (`out/*`, `**/build`, `*.db`) - a nested list item and a code block's line too; None: none
    does. Such a delete is never suggested, nor added: where a line allows it a "You may" is one
    too many, where one forbids it the two are set against each other - and no list of words
    tells the two apart. (Named too widely - "out" in "find out" - it is only not suggested.)"""
    targets = _targets(command, cwd) or []
    if not targets:
        return None
    names: set[str] = set()
    for one in targets:
        parts = one.split("/")
        names.update("/".join(parts[:n]) for n in range(1, len(parts) + 1))
        names.add(parts[-1])
    named = re.compile(
        # (a path of its own or one under it - never part of a longer name: `src/build`,
        # `build-cache`, `build.old`; a sentence's full stop after it is none - or the end of a
        # full path: `C:/proj/out/build`, `/home/me/proj/build`)
        # (bounded: a long line of "/a;/a;…" is read in time, never each start to its end)
        r"(?<![\w./\\-])(?:\.[/\\]|(?:[A-Za-z]:)?[/\\](?:[^\s/\\]{1,80}[/\\]){0,32})?(?:"
        + "|".join(re.escape(one).replace("/", r"[/\\]") for one in sorted(names, key=len)[::-1])
        + r")(?![\w-]|\.[\w-])",
        re.IGNORECASE,
    )
    lines = (line.strip() for text in texts for line in (text or "").splitlines())
    return next((line for line in lines if named.search(line) or _globbed(line, targets)), None)


def _globbed(line: str, targets: list[str]) -> bool:
    """Whether a word of `line` is a pattern (`*`, `?`) that takes a target in, as a shell's glob
    would from the project's root or any folder (`**/build`); whatever its case."""
    for word in line.split():
        if ("*" in word or "?" in word) and len(word) <= MOST_PATH:
            glob = word.strip(".,;:`'\"()").removeprefix("./").replace("\\", "/").casefold()
            if not glob.strip("*?/"):  # (a list's `*`, "5 * 3", a lone `**`: no pattern)
                continue
            for one in targets:
                path = one.casefold()
                if fnmatch.fnmatchcase(path, glob) or fnmatch.fnmatchcase(
                    path, glob.removeprefix("**/")
                ):
                    return True
    return False


def _has(rules: str, line: str) -> bool:
    """Whether the rules hold `line` as a line of their own (a list item too)."""
    return any(judge.LIST_MARK.sub("", one.strip()) == line for one in rules.splitlines())


def key_of(project_id: str, command: str, cwd: str | None) -> str:
    return hashlib.sha256(f"{project_id}\n{cwd or '.'}\n{command}".encode()).hexdigest()[:16]


def suggestions(session: Session, project: Project, rules: str, added: bool = False) -> list[dict]:
    """The deletes the user approved unchanged TIMES times or more in DAYS, in this project's
    chats - each with the line for the project's rules (`rules`, as in effect) that would spare
    its card at Full auto with Check what I said first on; one the rules hold already is left out
    (`added` False). Each command as it was approved, to the character: one with a line break
    in it is two commands, and never plain (review: `rm -rf build⏎src`, its spaces made one,
    suggested "You may delete build and src."). One whose path the user's words name
    (`mentioned`) is not suggested - `added`: kept, with that line, for Add to rules to refuse;
    one the rules hold already is no such line."""
    times = func.count()
    approved = (
        select(Command.command, Command.cwd, times)
        .join(Run, Run.id == Command.run_id)
        .join(Conversation, Conversation.id == Run.conversation_id)
        .where(
            Conversation.project_id == project.id,
            Command.asked_reason == "delete",
            Command.cwd.is_not(None),  # (a CLI's whose folder is not known: no rule names it)
            Command.decided_at.is_not(None),
            Command.status != "rejected",
            Command.created_at >= now() - timedelta(days=DAYS),
            func.length(Command.command) <= MAX_RULE,
        )
        .group_by(Command.command, Command.cwd)
        .having(times >= TIMES)
        .order_by(times.desc(), Command.command)
        .limit(MOST_SUGGESTED)
    )
    found = []
    preferences = memory.preferences(session)
    for command, cwd, n in session.execute(approved):
        line = rule_line(command, cwd)
        if line is None or not (added or not _has(rules, line)) or not _stands(rules, line):
            continue
        why = None if _has(rules, line) else mentioned([preferences, rules], command, cwd)
        if why is None or added:
            found.append(
                {
                    "key": key_of(project.id, command, cwd),
                    "command": command,
                    "cwd": cwd,
                    "times": n,
                    "rule": line,
                    **({"mentioned": why} if why is not None else {}),
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
