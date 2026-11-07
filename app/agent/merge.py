"""A copy's files against the project's: merging one file (`_merge_file`), what a Take in card
shows and keeps on record (`kept_on_record`, `_kept_files`, `_look_again`), putting files back
(`_put_back`, `_restore`), and recovery at start-up (`recover_copies`, `recover_interrupted`).

Its code reads `_merge_file` here; `AgentRunner` reads the one `app.agent` imports. A test that
replaces it patches both.
"""

import contextlib
import difflib
import hashlib
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Collection, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from sqlalchemy import and_, func, literal_column, or_, select
from sqlalchemy.orm import object_session

from app import away, backlog, copies, git, koloni, project_view, recipe_run, web
from app import room as rooms
from app.agent.ctx import TERMINAL, Ctx
from app.agent.words import (
    AGENT_TERMINAL,
    ASKED_AT_EVERY_LEVEL,
    CHECK_CUT_SHORT,
    MAX_PATHS_TOLD,
    NO_TRIGGER_ALLOWS,
    OPEN,
    SECRET_IN_COPY,
)
from app.commands import PATCH, names_standing, writes_git_config
from app.db.models import (
    Agent,
    Command,
    Conversation,
    ConversationTeam,
    Discussion,
    Event,
    FileChange,
    Merge,
    Message,
    Project,
    Question,
    Room,
    Run,
    ToolCall,
    WebRequest,
    now,
)
from app.project_view import LINK as STANDING_LINK
from app.project_view import _is_link, hooks_folder
from app.project_view import standing as standing_files
from app.schemas import ChatTeamOut
from app.workspace import (
    MAX_WRITE_BYTES,
    Workspace,
    WorkspaceError,
    _name,
    for_change,
    in_scratch,
    sha256_text,
    standing_asks,
    stands_over_later_turns,
    unified_diff,
)

# Measured 29 Oct (R115): `npm ci` / `uv venv` in a copy empty the project's own node_modules /
# .venv through the junction (`commands._REBUILDERS` asks them); a root lockfile rewritten from
# any copy - whole or of one part - is the sign of such an install, so it is taken only on the
# user's word (`_root_lock`). shortcut: a plain `npm install` at the root is not measured
# through the junction; refuse the install itself if it is seen to prune the project's own.
ROOT_LOCKS = frozenset({"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "uv.lock",
                        "poetry.lock"})
ROOT_LOCK_ASKED = (
    "{path}: a lockfile at the project root changed from a working copy, where the dependency "
    "folders are the project's own, linked in: taken only on the user's word, at every "
    "permission level"
)

# Why a file both sides changed is asked about as a whole, not merged line by line.
ONE_SIDE_DELETED = "one side deleted it and the other changed it"
NOT_TEXT = "it is not text, or is larger than 1 MiB"
NO_BASE = "what it held when the copy was made was not kept"
NEW_ON_BOTH = "both sides made it anew: there is nothing both started from"
NO_DIFF = "there is no diff to show of it, and the project holds another file there"
NOT_BY_LINE = "changed in the project meanwhile, and not merged line by line: {why}"

CHECK_PRESS_RUN = "below Full auto it runs only when you say: press Run the test before you Take in"
# ...and as a merge stored before the card's word became Take in says it.
CHECK_PRESS_RUN_WAS = CHECK_PRESS_RUN.replace("before you Take in", "before you Apply")

# A card shows the diffs of this many of a branch's files; the rest by name.
# shortcut: one git each (`git.branch_diffs`); one `git diff` split by file if a branch of
# hundreds of files is met.
MOST_BRANCH_DIFFS = 30

# Of a merged file, which lines are the project's is told up to this many lines a side:
# the comparing is quadratic on repeated lines (0.3 s at 2000, measured).
MAX_LINES_COMPARED = 2000

# A Python install, whose `.pth` files stand where nobody watches (`_command_names`).
PIP_INSTALLS = re.compile(
    r"(?i)(?:^|[\s;&|(])(?:\S*[\\/])?(?:(?:python[\d.]*|py)(?:\.exe)?\s+-m\s+)?"
    r"(?:pip3?|uv|poetry)(?:\.exe)?\s+(?:install|add|sync|pip\s+install)\b")


MAX_PLANNED_BYTES = 1024 * 1024  # larger files are asked about in words, not as a diff


def _planned_edit(target: Path, tool: str, given: dict) -> tuple[str | None, str] | None:
    """What a file holds and what it would hold after one of Claude Code's own edits,
    when that can be worked out from the request (a whole write, a single replacement);
    None when it cannot."""
    try:
        if target.is_file() and target.stat().st_size > MAX_PLANNED_BYTES:
            return None
        before = target.read_bytes().decode("utf-8") if target.is_file() else None
    except (OSError, UnicodeDecodeError):
        return None
    if tool == "Write" and isinstance(given.get("content"), str):
        return before, given["content"]
    old, new = given.get("old_string"), given.get("new_string")
    if tool == "Edit" and before is not None and isinstance(old, str) and isinstance(new, str):
        if not old:
            return None
        if old not in before and "\r\n" in before:
            # Claude Code matches as if the file had plain line ends, and keeps the file's.
            old, new = (s.replace("\r\n", "\n").replace("\n", "\r\n") for s in (old, new))
        if old not in before:
            return None
        if given.get("replace_all"):
            return before, before.replace(old, new)
        return before, before.replace(old, new, 1)
    return None


def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _text_of(target: Path) -> tuple[bool, str | None]:
    """A file's text, as a change record keeps it: (True, None) for a file that is not
    there, and (False, None) for one no record can hold - not text, or too large."""
    if not target.is_file():
        return True, None
    try:
        data = target.read_bytes()
        if len(data) > MAX_WRITE_BYTES:
            return False, None
        return True, data.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return False, None


def _side(place: Path | None) -> tuple[str | None, bool, str | None]:
    """One side of a file, from one read of it: its digest as `copies.digest` gives it
    (`copies.OUTSIDE` for a place behind a link, which is not read), whether a change
    record can hold it, and its text."""
    if place is None:
        return copies.OUTSIDE, False, None
    try:
        if place.is_symlink() or place.is_junction() or not place.is_file():
            return None, True, None
        data = place.read_bytes()
    except OSError:
        return "unreadable", False, None
    digest = hashlib.sha256(data).hexdigest()
    if len(data) > MAX_WRITE_BYTES:
        return digest, False, None
    try:
        return digest, True, data.decode("utf-8")
    except UnicodeDecodeError:
        return digest, False, None


def _git_commit_on(session, cid: str) -> bool:
    """Whether the project of a conversation has what is taken from an agent committed."""
    return bool(session.scalar(select(Project.git_commit).join(
        Conversation, Conversation.project_id == Project.id).where(Conversation.id == cid)))


def _held(place: Path | None) -> bytes | None | Literal[False]:
    """What a project file holds, for the commit of what is taken (`Copy.was`): None where
    there is no file at all; False where there is one that cannot be read - a link, a file
    held open -, which is no deletion: such a file goes in whole."""
    if place is None:
        return False
    data = copies._bytes(place)
    return False if data is None and os.path.lexists(place) else data


def _merge_file(
    copy: copies.Copy, path: str, base: dict[str, str] | None = None,
    recorded: dict[str, datetime] | None = None,
) -> dict | None:
    """One file a working copy changes, as its card shows it: how it stands against the
    project, and the diff from what the project holds now to what the copy holds - None
    where that is not text. "shown": the digests of the two, of the very bytes the diff
    and the state were made from - Apply writes over nothing else. None for a file the
    copy does not change. Nothing is read through a link that leads out of the project
    or of the copy: such a file is "refused", and says so. `base`: as `Copy.state`.

    A file the project changed too is merged line by line where that can be done
    (`_both_changed`): "merged" where the two went together - its diff is then to the
    two together - and else a "conflict" that says whether whole files or only lines
    stand against each other, and when each side last changed it (`recorded`: when the
    copy's agents last did, by path, as their records have it)."""
    (there, as_text, before), (here, is_text, after) = (
        _side(copy.there(path)), _side(copy.here(path))
    )
    found = copy.state(path, base, (there, here))
    if found is None:
        return None
    kind, state = found
    # (Its text is not shown, nor taken: it would be on record whole - slice 91.)
    held = path in copy.secret_held or is_text and after is not None and any(
        secret in after for secret in copy.secrets())
    if held:
        state = "refused"
    diff = added = removed = None
    if state in ("ready", "conflict") and as_text and is_text:
        diff, added, removed = unified_diff(before, after or "", path)
    why = {"refused": SECRET_IN_COPY if held else copies.OUTSIDE,
           # (B-189 first: what git ignores is not kept, outside a part copy's part too.)
           "left_out": copies.IGNORED if copy.ignored(path)
           else copies.NOT_IN_PART if not copy.holds(path) else copies.NOT_OFFERED}
    # Why such a file waits on the card at every level (nobody watching: refused instead).
    standing = stands_over_later_turns(Workspace(copy.project), path)
    one = {
        "path": path, "kind": kind, "state": state, "diff": diff, "additions": added,
        "deletions": removed,
        "note": why.get(state) or standing and ASKED_AT_EVERY_LEVEL.format(name=standing)
        or _root_lock(copy, path),
        "shown": [there, here],
        # Compared with the project alone: the card says so, and does not say "meanwhile".
        **({"two_way": True} if copy.two_way else {}),
    }
    if state == "ready" and here is not None and copy.joined.get(path) == here:
        one["state"] = "merged"  # the two sides together, as `_join` wrote them here
    if state == "conflict" and not copy.two_way:
        texts = (before, after) if as_text and is_text else (None, None)
        one.update(_both_changed(copy, path, base, (there, here), kind == "new", *texts))
        one["sides"] = _sides(copy, path, (recorded or {}).get(path))
        if kind == "new" and copy.git and copy.ignored(path):
            one["note"] = copies.NOT_HELD  # (not "changed meanwhile": it never was the copy's)
    return one


def _both_changed(
    copy: copies.Copy, path: str, base: dict[str, str] | None,
    shown: tuple[str | None, str | None], new: bool, before: str | None, after: str | None,
) -> dict:
    """What a card says of a file the project changed too, and differently: the two
    merged line by line with git's own merge, on what the copy was made from.

    Different lines: {"state": "merged"}, with the diff from the project's file to the
    two together. The same lines: a conflict of lines ("whole": False) - "diff" is what
    goes in whichever side is taken, "clash" the lines that stand against each other,
    from the project's to the agent's. Where no such merge can be made the two files
    stand against each other as wholes ("whole": True), and "note" says why: a side
    without the file, a file that is not text (`before`, `after`: None), one the copy
    did not start from (`new`) or whose start was not kept, git not there or failing.
    What the merge came to is kept with the copy (`Copy.results`), for `_join`."""
    copy.results.pop(path, None)

    def whole(why: str) -> dict:
        return {"whole": True, "note": NOT_BY_LINE.format(why=why)}

    if None in shown:
        return whole(ONE_SIDE_DELETED)
    if before is None or after is None:
        return whole(NOT_TEXT)
    was = copy.started_from(path, base)
    if was is None:
        return whole(NEW_ON_BOTH if new else NO_BASE)
    mine, theirs = before.encode("utf-8"), after.encode("utf-8")
    folder = copy.root.parent  # the copy's own folder, beside its tree
    try:
        clashes, merged = git.merge_file(folder, mine, was, theirs)
        made = {"merged": merged}
        if 0 < clashes < 128:
            # Either side's lines where they clash; what went together is in both.
            made = {}
            for side, favour in (("project", "ours"), ("agent", "theirs")):
                clashes, made[side] = git.merge_file(folder, mine, was, theirs, favour)
                if clashes != 0:
                    break
        if clashes != 0:
            return whole("git could not merge it")
        texts = {side: found.decode("utf-8") for side, found in made.items()}
    except git.Refused as exc:
        return whole(str(exc))
    except UnicodeDecodeError:
        return whole("git could not merge it")
    copy.results[path] = {"shown": shown, "there": mine, **made}
    diff, added, removed = unified_diff(before, texts.get("merged", texts.get("project", "")), path)
    found = {"diff": diff, "additions": added, "deletions": removed}
    if "merged" in made:
        return {"state": "merged", **found, "theirs": _projects_lines(after, texts["merged"])}
    clash = unified_diff(texts["project"], texts["agent"], path)[0]
    return {"whole": False, "clash": clash, **found}


def _changed_at(place: Path | None) -> datetime | None:
    """When a file was last written, as the disk has it; None for one that is not there."""
    try:
        return datetime.fromtimestamp(place.stat().st_mtime, UTC) if place else None
    except OSError:
        return None


def _projects_lines(agents: str, together: str) -> str:
    """The lines of a file merged with the project's changes that are not as the agent
    left them - the project's - by their numbers in the two together: "line 6", "lines
    3-4, 9"; "" where the project only took lines out, or the file is too long to compare
    (`MAX_LINES_COMPARED`: then it is named without its lines)."""
    mine, theirs = agents.splitlines(), together.splitlines()
    if max(len(mine), len(theirs)) > MAX_LINES_COMPARED:
        return ""
    # (no autojunk: it would take the agent's own repeated lines for the project's)
    spans = [
        (start + 1, end) for tag, _a, _b, start, end in difflib.SequenceMatcher(
            None, mine, theirs, autojunk=False).get_opcodes()
        if tag != "equal" and end > start
    ]
    if not spans:
        return ""
    shown = ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in spans[:MAX_PATHS_TOLD])
    more = " and more" if len(spans) > MAX_PATHS_TOLD else ""
    one_line = len(spans) == 1 and spans[0][0] == spans[0][1]
    return f"line {shown}" if one_line else f"lines {shown}{more}"


def _sides(copy: copies.Copy, path: str, recorded: datetime | None) -> dict:
    """When each side last changed a file both changed, and which came last - to be
    shown, never acted on. The project's: its file, as the disk has it. The agent's: its
    last change to the file as on record (`recorded`) - the copy's file may have been
    written since by KOLONİ itself - or, with nothing on record (a command's doing), the
    copy's file. Not known for a side that has no file."""
    project, agent = _changed_at(copy.there(path)), recorded or _changed_at(copy.here(path))
    newer = None
    if project is not None and agent is not None:
        newer = "project" if project >= agent else "agent"
    return {
        "project": {"changed_at": project.isoformat() if project else None},
        "agent": {"changed_at": agent.isoformat() if agent else None},
        "newer": newer,
    }


def _last_changes(session, line: list[str]) -> dict[str, datetime]:
    """When the agents of a working copy last changed each file in it, by path, as their
    change records have it."""
    found = session.execute(
        select(FileChange.path, func.max(FileChange.created_at))
        .where(FileChange.agent_id.in_(line), FileChange.status == "in_copy")
        .group_by(FileChange.path)
    ).all() if line else []
    return {path: at if at.tzinfo else at.replace(tzinfo=UTC) for path, at in found}


def unchosen(files: list[dict], choices: dict[str, str]) -> list[str]:
    """The files of a card whose two sides stand against each other and for which the
    user has not said whose is taken: nothing is chosen for them. (A copy compared with
    the project alone is asked about as before: Apply takes what it holds.)"""
    return [
        one["path"] for one in files
        if one["state"] == "conflict" and not one.get("two_way") and one["path"] not in choices
    ]


def _files_on_record(changes: list[FileChange], state: str, note: str) -> list[dict]:
    """The files of a working copy as its change records name them, for where the copy
    itself cannot be looked at: each path once, in path order, with no diff."""
    kinds: dict[str, str] = {}
    for change in changes:
        new = change.kind == "create" and change.path not in kinds
        kinds[change.path] = (
            "deleted" if change.kind == "delete"
            else "new" if new or kinds.get(change.path) == "new" else "changed"
        )
    return [
        {"path": path, "kind": kind, "state": state, "diff": None, "additions": None,
         "deletions": None, "note": note}
        for path, kind in sorted(kinds.items())
    ]


def _branch_files(
    copy: copies.Copy, look: dict, level: str, held: Mapping[str, str] | None = None
) -> dict[str, dict]:
    """K-dal-takim: what a branch changed (`look`, `git.branch_look`'s) as a card shows a copy's
    files: each with its diff from where the two parted - the first `MOST_BRANCH_DIFFS`, none
    of a secret (`git.branch_diffs`), and none of a file git does not diff as text. A file that
    waits for the user's word at this `level` as Take in has it - one that stands over later
    turns, a root lockfile - says why in its note: no such branch is merged unasked. `held`:
    files not committed, each with why (a secret given this turn, the project's own file
    there) - refused, as Take in refuses them; one the branch has all the same (an agent's own
    commit) is shown as the branch holds it.
    For a thread."""
    listed = list(look["files"].items())
    try:
        diffs = git.branch_diffs(copy.project, copy.branch or "",
                                 [path for path, _ in listed[:MOST_BRANCH_DIFFS]])
    except git.Refused:
        diffs = {}
    ws, found = Workspace(copy.project), {}
    for path, letter in listed:
        lines = diffs.get(path, "").splitlines()
        hunk = next((at for at, line in enumerate(lines) if line.startswith("@@")), None)
        body = lines[hunk:] if hunk is not None and hunk >= 2 else []
        standing = stands_over_later_turns(ws, path)
        found[path] = {
            "path": path, "kind": {"A": "new", "D": "deleted"}.get(letter, "changed"),
            "state": "ready", "note": ASKED_AT_EVERY_LEVEL.format(name=standing) if (
                standing_asks(standing, level)) else _root_lock(copy, path),
            "diff": "\n".join(lines[hunk - 2:]) if body and hunk is not None else None,
            "additions": sum(line.startswith("+") for line in body) if body else None,
            "deletions": sum(line.startswith("-") for line in body) if body else None,
        }
    for path, why in (held or {}).items():
        found.setdefault(path, {"path": path, "kind": "changed", "state": "refused", "note": why,
                                "diff": None, "additions": None, "deletions": None})
    return found


def _secret_forms(copy: copies.Copy) -> list[bytes]:
    """K-dal-takim: the secrets given in a branch copy's turn (`Copy.secrets`) as they are looked
    for in bytes: UTF-8 and UTF-16-LE."""
    return [form for one in copy.secrets() if one
            for form in (one.encode("utf-8"), one.encode("utf-16-le"))]


def _secret_in(copy: copies.Copy, path: str) -> bool:
    """K-dal-takim: whether a file of a branch's worktree holds a secret given in its turn
    (`Copy.secrets`), as UTF-8 or UTF-16 bytes, in a file of any text or none: it is not
    committed - git would keep it after the branch is gone."""
    place, forms = copy.here(path), _secret_forms(copy)
    try:
        data = place.read_bytes() if forms and place and place.is_file() else b""
    except OSError:
        return False
    return any(form in data for form in forms)


def _made_in(copy: copies.Copy | None, live: copies.Copy | None = None) -> list:
    """B-322: of a line's records, only those made in this copy - not in a copy of the same
    agent's kept for the user before this one was made, nor in `live`, the copy it works in
    now, where this is another (a kept one). Nothing to say of a copy loaded from disk.
    shortcut: two kept copies of one agent (a new copy that stopped too) are told apart by
    neither - Apply on one takes the other's records of the same path; put the copy's folder
    on each record if that is ever seen."""
    where = [FileChange.created_at >= copy.made_at] if copy is not None and copy.made_at else []
    if live is not None and live is not copy and live.made_at:
        where.append(FileChange.created_at < live.made_at)
    return where


def _cli(ctx: Ctx) -> bool:
    """Whether a CLI keeps the agent's loop: its calls are answered at once (`_run_from_cli`)."""
    return bool(getattr(ctx.model, "native", False) or getattr(ctx.model, "session", False))


def _few(paths: list[str]) -> str:
    """Paths as an agent is told them: the first `MAX_PATHS_TOLD`, and how many more."""
    more = len(paths) - MAX_PATHS_TOLD
    return ", ".join(paths[:MAX_PATHS_TOLD]) + (f" and {more} more" if more > 0 else "")


def kept_on_record(
    session, folder: Path, line: list[str], why: str, always: bool = False,
    room_id: str | None = None,
) -> Merge | None:
    """Put a working copy that is left on disk on record as that: what of it was on its
    way into the project is "interrupted", with where the copy is, and each file that
    is not in the project says so too. `line`: the agent whose copy it is, then the
    agents below it that changed files in it. `why`: what broke it off. None, and
    nothing changed, for a copy that holds nothing of theirs the project lacks - unless
    `always`: the copy is kept whatever is on record of it. Its change records stay
    "in_copy": that is where the changes are. `room_id`: the room whose copy it is.
    shortcut: a room's copy kept at a restart, and every merge from before 0082, has no
    room on record (nothing is filled in): its card is the lead's, not the room's tab's -
    look for the room by its run if that is missed."""
    changes = session.scalars(
        select(FileChange).where(FileChange.agent_id.in_(line), FileChange.status == "in_copy")
        .order_by(FileChange.created_at, literal_column("file_changes.rowid"))
    ).all() if line else []
    # The one of this folder; else the one that was asked about, or (before folders
    # were on record) the agent's interrupted one.
    merge = session.scalar(
        select(Merge).where(Merge.agent_id.in_(line[:1]), or_(
            Merge.kept_in == str(folder),
            and_(Merge.kept_in.is_(None), Merge.status.in_(("pending", "interrupted"))),
        )).order_by(Merge.kept_in.is_(None))
    )
    if merge is None and not (changes or (always and line)):
        return None
    note = f"{why}: its files are kept in {folder}"
    if merge is None:
        merge = Merge(
            run_id=session.get_one(Agent, line[0]).run_id, agent_id=line[0],
            files=_files_on_record(changes, "refused", note), room_id=room_id,
        )
        session.add(merge)
    else:
        # Until the copy is looked at again (`_show_kept`), nothing of it can be taken.
        merge.files = [
            one if one["state"] == "applied" else {**one, "state": "refused", "note": note}
            for one in merge.files
        ]
    if merge.status != "interrupted":
        merge.status, merge.decided_at = "interrupted", now()
    merge.kept_in = str(folder)
    _check_is_over(merge)
    return merge


def _check_is_over(merge: Merge) -> None:
    """A merge whose turn is over has no check running: one on record as running was
    cut short (Stop, a restart) - it did not pass, and says so."""
    if merge.check and merge.check.get("state") == "running":
        merge.check = {**merge.check, "state": "failed", "note": CHECK_CUT_SHORT}
    elif merge.check and merge.check.get("note") in (CHECK_PRESS_RUN, CHECK_PRESS_RUN_WAS):
        merge.check = {**merge.check, "note": None}  # (a kept copy has no Run to press)


def _no_diff_no_trust(one: dict) -> None:
    """A kept copy's file that has no diff to show: its label is all the card says of
    it, and what the copy was made from is only what its folder says (a command could
    have rewritten it). Wherever the project holds another file there, it is a conflict
    of the two files as wholes: whose is taken is the user's to say."""
    there, here = one["shown"]
    if one["state"] == "ready" and one["diff"] is None and there not in (None, here):
        one.update(state="conflict", whole=True, note=one["note"] or NO_DIFF)


def _kept_files(
    copy: copies.Copy, unattended: bool, recorded: dict[str, datetime] | None = None,
    base: dict[str, str] | None = None, names: dict[str, str] | None = None,
) -> dict[str, dict]:
    """What a kept copy holds that the project lacks, as a card shows it: each file as
    it stands against the project now, with its diff - from one look at the copy.
    `unattended`: it is of a turn nobody watched - what no trigger lets such a turn
    change stays refused, also now that somebody looks. `recorded`: as `_merge_file`.
    `base`, `names`: as `Copy.changes`, for a look made in a thread."""
    ws, fresh = Workspace(copy.project), {}
    for path, _kind, _state in copy.changes(base, names):
        one = _merge_file(copy, path, base, recorded)
        if one is None:
            continue
        _no_diff_no_trust(one)
        name = stands_over_later_turns(ws, path) if unattended else None
        if name and one["state"] in OPEN:
            one["state"], one["note"] = "refused", NO_TRIGGER_ALLOWS.format(name=name)
        fresh[path] = one
    return fresh


def as_shown(files: dict[str, dict], how: bool = False) -> dict[str, list]:
    """What a card shows of the files it still asks about, as digests: a check's result
    is of these, and of no other state of them. `how`: and how each stands (a file asked
    about another way with the same digests)."""
    return {
        path: [*(one.get("shown") or ()), *((one["state"], one.get("whole")) if how else ())]
        for path, one in files.items() if one["state"] in OPEN
    }


def writes_nothing(one: dict, choices: Mapping[str, str]) -> bool:
    """A whole file of which the user keeps the project's own: taking that writes nothing,
    whatever the project holds now, so it is not held to how the card showed it - one the
    project rewrites all the time (a log, a database) does not hold up the rest."""
    return one["state"] == "conflict" and bool(one.get("whole")) and (
        choices.get(one["path"]) == "project")


def _moved(copy: copies.Copy, files: dict[str, dict], choices: Mapping[str, str]) -> list[str]:
    """The files a card asks about of which a side is no longer as the card shows it."""
    return [
        path for path, one in files.items()
        if one["state"] in OPEN and not writes_nothing(one, choices)
        and tuple(one.get("shown") or ()) != copy.sides(path)
    ]


def not_as_seen(
    files: list[dict], seen: Mapping[str, list | None], keep: Collection[str] = (),
    how: bool = False,
) -> list[str]:
    """The files of a card that are not as the user saw them (`seen`: by path, `as_shown`
    of each): asked about anew, shown again, refused or gone from the card - but for one
    taken since or of which the project's own was kept, and those of `keep`."""
    now = as_shown({one["path"]: one for one in files}, how)
    done = {
        one["path"] for one in files if one["state"] == "applied" or _kept_the_projects(one)
    }
    return sorted(
        path for path in (seen.keys() | now.keys()) - done - set(keep)
        if list(seen.get(path) or ()) != now.get(path, [])
    )


def _is_stale(check: dict, files: dict[str, dict]) -> bool:
    """Whether a check's result is of an earlier state than the card now shows: a file
    it asks about is not as it was when the check ran ("checked"), or was not there."""
    checked = check.get("checked")
    return checked is not None and any(
        checked.get(path) != shown for path, shown in as_shown(files).items()
    )


def _kept_the_projects(one: dict) -> bool:
    """Whether a file is not taken because the user said the project's own is kept."""
    return one["state"] == "refused" and one.get("chose") == "project"


def _root_changed(copy: copies.Copy, files: dict[str, dict]) -> bool:
    """K-buyuk-proje: whether a copy of one part is about to change a file at the project
    root - one every part reads, which a check run in that copy alone does not vouch for.
    (A whole copy's check vouches for them; a root lockfile waits from any copy: `_root_lock`.)"""
    return copy.part is not None and any(
        "/" not in path for path, one in files.items() if one["state"] in OPEN)


def _root_lock(copy: copies.Copy, path: str) -> str | None:
    """K-lead-folder: why a lockfile at the project root changed from a working copy - whole
    or of one part - is taken only on the user's word (`ROOT_LOCKS`); None for any other file."""
    return ROOT_LOCK_ASKED.format(path=path) if path.casefold() in ROOT_LOCKS else None


def _look_again(
    copy: copies.Copy, files: dict[str, dict], recorded: dict[str, datetime] | None,
    choices: Mapping[str, str],
) -> None:
    """Before a kept card is applied: each file of it that both sides changed is merged
    once more - what a merge came to is not on the card - and one that is not as the
    card has it (a side moved, or the two would now be put together another way) is
    shown again instead of taken ("again"); so is any other file of it a side of which
    moved - not one that `writes_nothing`. One that was written into the copy before
    (`_join`) is its file as it is."""
    for path, one in files.items():
        if one["state"] not in OPEN or writes_nothing(one, choices) or (
            (one["state"] == "ready" or one.get("two_way"))
            and tuple(one.get("shown") or ()) == copy.sides(path)
        ):
            continue
        fresh = _merge_file(copy, path, recorded=recorded)
        if fresh is None:
            continue  # the copy no longer changes it: `_apply` takes it off the card
        _no_diff_no_trust(fresh)
        joined = one["state"] == "merged" and fresh["state"] == "ready"
        same = (fresh["state"], fresh.get("whole")) == (one["state"], one.get("whole"))
        if fresh["shown"] != one.get("shown") or not (joined or same):
            _shown_again(one, fresh)
            one["again"] = True


def _shown_again(one: dict, fresh: dict | None) -> None:
    """A file is not as its card has it: the card says of it what holds now, and nothing
    of what it said before. (None: the copy no longer changes the file - it is left for
    `_apply` to take off the card.)"""
    if fresh is not None:
        one.clear()
        one.update(fresh)


def _show_kept(merge: Merge, fresh: dict[str, dict]) -> None:
    """Put what a kept copy holds (`_kept_files`) on its record, beside what of it is
    in the project already. A check that ran on other files than these is said to be of
    an earlier state: it is not run again on a kept copy."""
    kept = {one["path"]: one for one in merge.files if one["state"] == "applied"}
    if merge.check:
        merge.check = {**merge.check, "stale": _is_stale(merge.check, fresh)}
    merge.files = [one for _path, one in sorted({**kept, **fresh}.items())]


def _kept_as(session, agent_id: str, held: Path) -> tuple[Path | None, list[str], str | None]:
    """What the records say of a kept copy in the folder `held`, for one that does not
    say what it was made from (`copies.kept`): where its files are, the paths its
    agents changed in it, and the part it was made for (K-buyuk-proje; None: the whole
    project). The tree in its folder, where the agent's row or a card of
    its says so; the folder itself - the layout before there were trees - where a card
    says that and the agent is from before a copy's tree went on its row. None where
    no record says which: what the folder holds does not, and such a copy is only to
    discard."""
    agent = session.get_one(Agent, agent_id)
    said = set(session.scalars(select(Merge.kept_in).where(Merge.agent_id == agent_id)))
    said.add((agent.copy or {}).get("tree"))
    recorded = list(session.scalars(select(FileChange.path).where(
        FileChange.agent_id.in_(_line_on_record(session, agent_id)),
        FileChange.status == "in_copy",
    )))
    part = ((agent.copy or {}).get("parts") or {}).get(str(held / copies.TREE))
    if str(held / copies.TREE) in said:
        return held / copies.TREE, recorded, part
    if str(held) in said and "tree" not in (agent.copy or {}):
        return held, recorded, part
    return None, recorded, part


def recover_copies(session_factory, runtime_root: Path) -> None:
    """The working copies a previous process left behind; no turn is running any more.
    One that holds what never reached the project - its card was waiting, or its agent
    was at work - is the user's: it stays on disk, without its links, on record as
    interrupted with where it is (`kept_on_record`), and its files are shown as a card
    shows them, to be taken or discarded (`AgentRunner.decide_kept`). Whether it holds
    such work the copy itself says, by what it was made from - a command's doing too;
    where that cannot be read, the change records say it, and each file of the copy
    that is not the project's is shown against that alone, as a conflict
    (`copies.kept`). The others are deleted, and what is on record of a copy that is
    not there is closed."""
    with session_factory() as session:
        kept: list[str] = []
        still: list[str] = []

        def keep(name: str) -> bool:
            line = _line_on_record(session, name.split("-")[0])
            if not line:
                return False
            held = copies.place(runtime_root, name)
            agent = session.get_one(Agent, line[0])
            run = session.get_one(Run, agent.run_id)
            project = session.get_one(
                Project, session.get_one(Conversation, run.conversation_id).project_id
            )
            tree, recorded, part = _kept_as(session, line[0], held)
            copy = fresh = None
            try:
                copy = copies.kept(Path(project.root_path), runtime_root, name, tree, recorded,
                                   part)
                # Looked at once: whether it holds anything, and what its card shows.
                fresh = _kept_files(copy, run.unattended, _last_changes(session, line))
                if not fresh:
                    return False  # all it held is in the project
            except Exception:
                # Whatever is wrong with this one copy, the app starts: it is kept, and
                # is only to discard.
                copy = None
            # One that says what it was made from - readable or not - was not thrown
            # away (`copies.forget`): it stays, whatever is on record of it. Only a copy
            # with a tree ever said so.
            noted = os.path.lexists(held / copies.BASE_FILE)
            folder = copy.root if copy else tree or (held / copies.TREE if noted else held)
            found = kept_on_record(
                session, folder, line, "interrupted by a restart", always=noted
            )
            if found is None:
                return False
            if copy is not None and fresh is not None:
                _show_kept(found, fresh)
            elif tree is None and folder == held and "tree" not in (agent.copy or {}):
                # No record says how it is laid out, and the folder its card now names
                # is not to say it at the next start: it stays only to discard.
                agent.copy = {**(agent.copy or {}), "tree": None}
            kept.extend(line)
            session.flush()  # one made just now has its id
            still.append(found.id)
            return True

        copies.clear(runtime_root, keep)
        for change in session.scalars(
            select(FileChange).where(
                FileChange.status == "in_copy", FileChange.agent_id.not_in(kept)
            )
        ):
            change.status, change.decided_at = "discarded", now()
        for merge in session.scalars(
            select(Merge).where(
                Merge.status.in_(("pending", "interrupted")), Merge.id.not_in(still)
            )
        ):
            # Its copy is not there: deleted by hand, if it was a kept one.
            gone = "the folder its files were kept in is gone"
            if merge.status == "interrupted":
                merge.files = [
                    one if one["state"] == "applied" else {**one, "state": "refused", "note": gone}
                    for one in merge.files
                ]
            taken = any(one["state"] == "applied" for one in merge.files)
            merge.status, merge.decided_at = "applied" if taken else "discarded", now()
            merge.kept_in = None
            _check_is_over(merge)
        session.commit()


def _line_on_record(session, owner: str) -> list[str]:
    """An agent and the agents below it that changed files in its working copy, as the
    records have it; nothing for a name that is no agent's."""
    agent = session.get(Agent, owner)
    if agent is None:
        return []
    line = [owner]
    for below in session.scalars(
        select(Agent).where(Agent.run_id == agent.run_id).order_by(Agent.depth)
    ):
        if below.parent_agent_id in line and (below.copy or {}).get("state") == "parent":
            line.append(below.id)
    return line


Taken = tuple[str, bytes | None, str | None, str | None]  # (`_put_back`)
# What one turn keeps of what it took back (`_keep_aside`), and for how long, in days.
TAKEN_BACK_BYTES = 64 * 1024 * 1024
TAKEN_BACK_DAYS = 14
# A command with more in it than one program: a chain, a pipe, a substitution, a redirection.
MORE_THAN_ONE = re.compile(r"[;&|<>\r\n`]|\$\(")
# A turn's folder of copies (`_keep_aside`) -> the bytes kept in it so far.
# shortcut: one small entry a turn, never dropped; drop it with the turn if that matters.
_KEPT: dict[Path, int] = {}
_KEPT_LOCK = threading.Lock()  # (it is counted in the threads `_put_back` runs in)


def _command_names(
    command: str, approved: bool, unwatched: bool
) -> tuple[set[str], frozenset[str]]:
    """What a command lets stand at the one look just after it (K-yazma-denetimi), as paths
    and names for `_put_back`, where the user `approved` it: the standing name its card showed
    (`names_standing`) - of git's folder its config alone, never its hooks; `.git/config` where
    it is git's own that rewrites it as it works (`writes_git_config`); and, `unwatched` - or
    at Full auto in a watched turn (K-fullauto-sorma: kept, said on record) -, the `.pth`
    files a Python install alone adds - whether it ran was its approval's, and taken back
    they would leave it half undone (npm's runs its packages' own scripts; below Full auto,
    watched, those are a card that says the install made them). What any other git command
    changes there - a checkout, a pull - is a card like any write.
    shortcut: a checkout that brings in other standing files is a card for each of them."""
    if not approved:
        return set(), frozenset()
    key = names_standing(command)
    paths = {".git/config"} if key == ".git" or writes_git_config(command) else set()
    names = {key} if key and key not in (".git", PATCH) else set()
    if unwatched and PIP_INSTALLS.search(command) and not MORE_THAN_ONE.search(command):
        names.add("*.pth")
    return paths, frozenset(names)


def _put_back(
    root: Path, before: dict[str, bytes], paths: set[str], names: frozenset[str] = frozenset(),
    since: float = 0.0, keep_in: Path | None = None,
) -> tuple[list[Taken], set[str]]:
    """K-yazma-denetimi: the project's standing files (`standing_files`) that differ from
    `before` are put back as they were - deleted, where there was none; and where there was a
    link, what is there instead is taken away, as KOLONİ makes no link - but for what the
    user's yes named: `paths` (casefolded), and for this one look `names` (of
    `NOT_WRITTEN_UNATTENDED`, anywhere in a path; "*.pth": an install's), and what KOLONİ itself
    wrote in `.koloni/` since `since`. What an agent - or the user, by hand - wrote there is
    kept in `keep_in` first, where it can be (`_keep_aside`). Returns what was put back - its
    path, what it held (None: it was deleted), why it could not be (then it stands as it is),
    what is said of it - and the paths let stand; `before` is what is on disk now."""
    # K-koloni-klasor: a scratch the agent made is ignored by git now - KOLONİ's own write,
    # which this look lets stand. (Here, in the thread and inside a caller's shield: no await
    # of its own that a Stop could cut before the put-back.)
    koloni.scratch(str(root), made=True)
    now = standing_files(root)
    taken: list[Taken] = []
    let: set[str] = set()
    here = str(root.resolve())
    # (Deepest first: a folder's files go before the folder that took a link's place.)
    for rel in sorted(before.keys() | now.keys(), reverse=True):
        was, theirs = before.get(rel), now.get(rel)
        if was == theirs:
            continue
        wrote = koloni.WROTE.get((here, rel))
        if rel.casefold() in paths or any(_name(part) in names for part in rel.split("/")) or (
                "*.pth" in names and rel.endswith(".pth") and "/site-packages/" in rel.casefold()
        ) or (wrote is not None and wrote[1] >= since and wrote[0] == theirs):
            let.add(rel)
            failed: str | None = "named"
        else:
            said = [_keep_aside(keep_in, rel, theirs)] if theirs is not None and keep_in else []
            link = was is not None and was.startswith(STANDING_LINK)
            if link:
                said.append(f"this was a link to {os.fsdecode(was[len(STANDING_LINK):])}; KOLONİ "
                            "does not make links: make it again yourself")
            failed = _restore(root, rel, None if link else was)
            taken.append((rel, theirs, failed, "; ".join(said) or None))
            if not failed and link:
                before.pop(rel, None)  # (what is on disk: nothing there now)
        if failed:
            if theirs is None:
                before.pop(rel, None)
            else:
                before[rel] = theirs
    return taken, let


def _keep_aside(keep_in: Path, rel: str, data: bytes) -> str:
    """Keep a copy of what a project file `rel` holds in `keep_in`, its turn's folder: named
    by a digest of its path (a long one would not fit), the path beside it in `paths.txt`, at
    most TAKEN_BACK_BYTES a turn. What is said of it: where it is, or why there is none."""
    with _KEPT_LOCK:  # (room taken first, given back where the copy fails)
        if _KEPT.get(keep_in, 0) + len(data) > TAKEN_BACK_BYTES:
            return (f"no copy of the agent's version was kept (this turn's copies are "
                    f"{TAKEN_BACK_BYTES // 2**20} MiB already)")
        _KEPT[keep_in] = _KEPT.get(keep_in, 0) + len(data)
    try:
        keep_in.mkdir(parents=True, exist_ok=True)
        copy = keep_in / f"{hashlib.sha256(rel.encode()).hexdigest()[:16]}-{uuid.uuid4().hex[:6]}"
        copy.write_bytes(data)
        with open(keep_in / "paths.txt", "a", encoding="utf-8") as listed:
            listed.write(f"{copy.name}\t{rel}\n")
    except OSError as exc:
        with _KEPT_LOCK:
            _KEPT[keep_in] -= len(data)
        return f"no copy of the agent's version was kept ({exc.strerror or exc})"
    return f"what it held is kept in {copy}"


def prune_commit_sides(runtime_root: Path, session) -> None:
    """Take away what was kept of taken files for their commit (`_keep_sides`: copies of
    the project's files) where none is offered any more: its merge gone, or committed."""
    with contextlib.suppress(OSError):
        for folder in (runtime_root / "commit-sides").iterdir():
            merge = session.get(Merge, folder.name)
            if merge is None or (merge.commit or {}).get("state") != "offered":
                shutil.rmtree(folder, ignore_errors=True)


def _prune_taken_back(runtime_root: Path) -> None:
    """Take away the turns' copies of what was taken back (`_keep_aside`) older than
    TAKEN_BACK_DAYS."""
    old = time.time() - TAKEN_BACK_DAYS * 86400
    with contextlib.suppress(OSError):
        for turn in (runtime_root / "taken-back").iterdir():
            if turn.stat().st_mtime < old:
                shutil.rmtree(turn, ignore_errors=True)


def _restore(root: Path, rel: str, held: bytes | None) -> str | None:  # noqa: C901
    """Make a project file hold `held` again - None: there is none (nor a folder that took a
    link's place, emptied first) -, by a new file put in its place (a hard link to it stays
    as it was); a link or a junction there now is taken away itself, never what it leads to.
    Why it could not be, or None."""
    path, parts = root / rel, Path(rel).parts
    real = os.path.realpath(root)

    def outside(at: Path | str) -> bool:
        # (Looked at again just before each write: a folder may have become a link meanwhile.)
        # shortcut: a folder swapped for a link between this look and the write is not seen -
        # that takes a process racing KOLONİ on purpose; open the folder by handle if it must.
        try:
            return os.path.commonpath([real, os.path.realpath(at)]) != real
        except ValueError:
            return True

    if any(_is_link(root.joinpath(*parts[:n])) for n in range(1, len(parts))):
        return "a folder in its path is a link now"
    if held is not None and held.startswith(STANDING_LINK):
        return "KOLONİ makes no links: make it again yourself"  # (Keep of a link an agent made)
    try:
        if _is_link(path):
            if os.name == "nt" and path.is_dir():
                os.rmdir(path)  # (a junction, or a link to a folder: itself only)
            else:
                os.unlink(path)
        if outside(path.parent):
            return "its folder leads out of the project now"
        if held is None:
            if path.is_dir():
                path.rmdir()
            else:
                path.unlink(missing_ok=True)
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, spare = tempfile.mkstemp(dir=path.parent, prefix=".koloni-")
        try:
            with os.fdopen(handle, "wb") as out:
                out.write(held)
            # As runnable as it was with these bytes (a hook), not mkstemp's 0600 - on Linux
            # and macOS; a version never seen keeps 0600.
            if os.name != "nt" and (mode := project_view.mode_of(path, held)) is not None:
                os.chmod(spare, mode)
            if outside(spare) or outside(path.parent):
                return "its folder leads out of the project now"
            os.replace(spare, path)
        finally:
            with contextlib.suppress(OSError):
                os.unlink(spare)
    except OSError as exc:
        return exc.strerror or str(exc)
    return None


def _git_parts(files: dict[str, bytes], root: Path) -> dict[str, str]:
    """What of git's folder runs at a commit, of the standing files (`standing_files`), as
    digests: its hooks all together - with the folder `core.hooksPath` names -, and its config
    (with a `.git` that is a file or a link: where git's folder is)."""
    digests = {"hooks": hashlib.sha256(), "config": hashlib.sha256()}
    folder = hooks_folder(root, files.get(".git/config"))
    for rel in sorted(files):
        top, _, rest = rel.partition("/")
        if _name(top) == ".git":
            part = "hooks" if rest and _name(rest) != "config" else "config"
        elif folder and rel.casefold().startswith(f"{folder}/".casefold()):
            part = "hooks"
        else:
            continue
        digests[part].update(b"%s\0%d\0" % (rel.encode(), len(files[rel])) + files[rel])
    return {part: digest.hexdigest() for part, digest in digests.items()}


def _digest_now(ws: Workspace, path: str) -> str | None:
    """A digest of what a project file holds now; None for a file that is not there. A
    file that cannot be read as text is like nothing an agent has seen."""
    try:
        target = ws.resolve(path)
        if target.is_file() and target.stat().st_size > 4 * MAX_PLANNED_BYTES:
            # Too large to be written here at all: told apart by its size and its date.
            at = target.stat()
            return f"large:{at.st_size}:{at.st_mtime_ns}"
        return sha256_text(ws.read_text_or_none(path))
    except (WorkspaceError, OSError):
        return "unreadable"


def running_docker_commands(session_factory) -> list[str]:
    """Ids of commands recorded as running in a container; ask this before recovery."""
    with session_factory() as session:
        return list(
            session.scalars(
                select(Command.id).where(
                    Command.status == "running", Command.location == "docker"
                )
            )
        )


def recover_interrupted(session_factory, notes: list | None = None) -> int:  # noqa: C901
    """Settle work a previous process left open; nothing is ever re-run.

    Returns the number of runs marked interrupted.
    """
    restarted = "interrupted: the server restarted before this tool call finished"
    with session_factory() as session:
        runs = session.scalars(select(Run).where(Run.status.not_in(TERMINAL))).all()
        run_ids = [run.id for run in runs]
        for run in runs:
            run.status, run.ended_at = "interrupted", now()
            backlog.turn_ended(session, run, "interrupted")
        away.settle(session, notes)  # (nor is a night started again: `notes`, its notification)
        cut_short = []
        for call in session.scalars(
            select(ToolCall).where(
                ToolCall.run_id.in_(run_ids), ToolCall.status.in_(("pending", "running"))
            )
        ):
            call.status, call.result, call.ended_at = "interrupted", restarted, now()
            cut_short.append(call.id)
            _forget_secrets(session, call)
        for change in session.scalars(
            select(FileChange).where(
                FileChange.run_id.in_(run_ids),
                # ("approved": the user's yes was there, its agent's place was not yet.)
                FileChange.status.in_(("proposed", "approved")),
            )
        ):
            # A crash between writing the file and recording it leaves the change
            # "proposed" although it is on disk: say what is true. One the user had said
            # yes to and that was never made is "discarded", not their no - and when
            # they said it stays.
            change.status = (
                "applied" if _is_on_disk(session, change)
                else "discarded" if change.status == "approved" else "rejected")
            change.decided_at = change.decided_at or now()
        # (What was changed in a working copy and never reached the project is looked
        # at with the copies themselves: `recover_copies`.)
        # Every open command, whatever its run says: nothing is running any more.
        for command in session.scalars(
            select(Command).where(Command.status.in_(("proposed", "approved", "running")))
        ):
            # A command that was running is not run again; one never started is dropped -
            # as "interrupted" too where the user had said yes to it: "rejected" is
            # their own no. (Such a one never started: it has no `started_at`.)
            command.status = "rejected" if command.status == "proposed" else "interrupted"
            command.ended_at = now()
        # A search or a request that was waiting for a yes: it never went out. One that
        # had its yes and whose call was cut short above is "interrupted", as that call
        # is: "approved" is what one that went out is, and "rejected" the user's own no.
        for asked in session.scalars(select(WebRequest).where(WebRequest.status == "proposed")):
            asked.status, asked.decided_at = "rejected", now()
        for asked in session.scalars(select(WebRequest).where(
            WebRequest.status == "approved", WebRequest.tool_call_id.in_(cut_short)
        )):
            asked.status = "interrupted"
        for agent in session.scalars(select(Agent).where(Agent.status.not_in(AGENT_TERMINAL))):
            # Who held which file went with the process: nobody waits for one any more.
            agent.waiting_for = None
            if agent.status == "running" and agent.ended_at is not None:
                # It had finished and was only answering another agent's message.
                agent.status = "failed" if agent.error else "completed"
                continue
            # An agent that was never started is dropped; one at work is not resumed.
            agent.status = "rejected" if agent.status == "proposed" else "interrupted"
            agent.ended_at = now()
        for question in session.scalars(select(Question).where(Question.status == "pending")):
            question.status = "interrupted"
        for message in session.scalars(select(Message).where(Message.status == "streaming")):
            message.status = "complete"
        for talk in session.scalars(select(Discussion).where(Discussion.status == "running")):
            talk.status, talk.ended_at = "interrupted", now()
        # A room that was running: its members are not started again, and how long its
        # clock ran on after the last time that was written down is not known.
        for room in session.scalars(select(Room).where(Room.status.in_(rooms.RUNNING))):
            room.status, room.ended_at, room.clock_since = "interrupted", now(), None
            room.paused = False  # (29c: nothing is left to resume)
        # A chat team's recipe at work keeps where it was, and says why it stands (84b-2);
        # the next turn starts it again (what its copy held is a kept copy's card).
        for row in session.scalars(select(ConversationTeam)):
            if row.state and row.state.get("status") in recipe_run.OPEN:
                row.state = {**row.state, "status": recipe_run.INTERRUPTED,
                             "why": recipe_run.RESTARTED}
                keep_turn(row)
        session.commit()
    return len(run_ids)


def keep_turn(row: ConversationTeam) -> None:
    """B-107: a chat team's row as it stands now, on the turn it is of (`Run.teams`): the chat's
    teams changed later, or the row run again, do not change how that turn is drawn."""
    session = object_session(row)
    run = session.get(Run, row.state["run_id"]) if session is not None and row.state else None
    if session is None or run is None:
        return
    kept = ChatTeamOut.model_validate(row).model_dump(mode="json")
    teams = [kept if one["team_id"] == row.team_id else one for one in run.teams or []]
    # In the chat's order: a row saved later (a team with no recipe, beside one) is not drawn last
    # for it. A row the chat has no more keeps its place after them.
    order = {one.team_id: one.position for one in session.scalars(select(ConversationTeam).where(
        ConversationTeam.conversation_id == row.conversation_id))}
    run.teams = sorted(teams if kept in teams else [*teams, kept],
                       key=lambda one: order.get(one["team_id"], len(order)))


def _is_on_disk(session, change: FileChange) -> bool:
    """Whether the project file currently holds exactly this change's new content."""
    root = session.scalar(
        select(Project.root_path)
        .join(Conversation, Conversation.project_id == Project.id)
        .join(Run, Run.conversation_id == Conversation.id)
        .where(Run.id == change.run_id)
    )
    if root is None:
        return False
    try:
        held = for_change(root, change.path).read_text_or_none(change.path)
        return sha256_text(held) == change.after_sha
    except WorkspaceError:
        return False


def _forget_secrets(session, call: ToolCall) -> None:
    """An `http_request` call as it is kept once its request has been decided - gone,
    failed, rejected or cut short: what looks like a secret in its address and its body
    is hidden (`web.kept`) in the call, in the request the user was asked about, and
    in the events that told of either while the user could still look."""
    if call.name != "http_request":
        return
    call.arguments = _kept(web.kept, call.arguments)
    for asked in session.scalars(select(WebRequest).where(WebRequest.tool_call_id == call.id)):
        asked.target = _kept(web.kept_url, asked.target)
    told = select(Event).where(
        # By the conversation: that is what the events are indexed by.
        Event.conversation_id == select(Run.conversation_id).where(
            Run.id == call.run_id).scalar_subquery(),
        Event.run_id == call.run_id,
        Event.type.in_(("tool_call.created", "tool_call.updated", "web_request.updated")),
    )
    for event in session.scalars(told):
        payload = event.payload if isinstance(event.payload, dict) else {}
        if event.type == "web_request.updated":
            if payload.get("tool_call_id") == call.id:
                event.payload = {**payload, "target": _kept(web.kept_url, payload.get("target"))}
        elif payload.get("id") == call.id:
            event.payload = {**payload, "arguments": _kept(web.kept, payload.get("arguments"))}


def _kept(how: Callable, text: object) -> str:
    """A text as `how` keeps it (`web.kept`, `web.kept_url`) - or, where that fails or
    gives what cannot be stored, a fixed text in its place: what could not be hidden is
    not kept as it came, and hiding never stops a turn, a Stop or the app's start."""
    try:
        hidden = how(text)
        hidden.encode("utf-8")
        return hidden
    except Exception:
        return '{"unreadable": "***"}' if how is web.kept else "***"


# B-205: where a turn's work is at its end, said by KOLONİ from the records - not the model's words.
NAMED_LANDED = 3  # files named in that line; the rest counted


def _named(paths: list[str]) -> str:
    more = len(paths) - NAMED_LANDED
    shown = paths[:NAMED_LANDED]
    if more > 0:
        return f"{', '.join(shown)} and {more} more"
    return " and ".join([", ".join(shown[:-1]), shown[-1]] if shown[1:] else shown)


def _went_in(changes: list[FileChange]) -> dict[str, tuple[int, int] | str | None]:
    """Each file the turn's own records put in the project: (added, removed) lines, "deleted",
    or "binary" (an attached file that is not text) - from its first record to its last, as
    `changes.in_copy` reads a copy. One changed back, or made and deleted, went in as nothing."""
    ends: dict[str, list[FileChange]] = {}
    for change in changes:
        # ("merged": what went into a pull request, or a branch with nothing to merge - not here.)
        if change.status == "applied":
            ends.setdefault(change.path, [change, change])[1] = change
    went: dict[str, tuple[int, int] | str | None] = {}
    for path, (first, last) in ends.items():
        after = None if last.kind == "delete" else last.after_content
        if first.before_content == after:
            continue
        if after is None:
            went[path] = "deleted"
        elif last.after_from and sha256_text(after) != last.after_sha:  # (its text says what it is)
            went[path] = "binary"
        else:
            went[path] = unified_diff(first.before_content, after, path)[1:]
    return went


def _ran_in_project(session, run_id: str) -> bool:
    """Whether an agent of the turn ran a command in the project itself, not in a copy: what such
    a command wrote is on no record (B-143)."""
    copies_of = session.scalars(select(Agent.copy).join(
        Command, Command.agent_id == Agent.id).where(
        Command.run_id == run_id, Command.started_at.is_not(None)))
    return any(copy is None or copy.get("state") in ("too_big", "failed") for copy in copies_of)


def _in_the_project(went: dict[str, tuple[int, int] | str | None]) -> str:
    """"In the project: a.py, b.py (deleted) and c.py: +3 −1 in all.": three named, the rest
    counted, and the lines of those whose count is known; one file, "a.py (+3 −1)"."""
    names = [path if how is None or isinstance(how, tuple) else f"{path} ({how})"
             for path, how in went.items()]
    counts = [how for how in went.values() if isinstance(how, tuple)]
    lines = f"+{sum(a for a, _ in counts)} −{sum(d for _, d in counts)}"
    if counts and len(went) == 1:
        return f"In the project: {names[0]} ({lines})."
    return f"In the project: {_named(names)}{f': {lines} in all' if counts else ''}."


def landed(session, run_id: str) -> str | None:
    """B-205: one line of where a turn's work is - in the project, sent as a pull request, waiting
    in Ready for you, or nowhere - from its file changes and merges. None for a turn that changed
    no file anywhere.
    shortcut: a kept copy's files are only those on record (`_show_kept`); a command's change in
    the project is on no record - said only as commands that ran in it, where nothing else is."""
    records = session.scalars(select(FileChange).where(FileChange.run_id == run_id).order_by(
        FileChange.created_at, literal_column("file_changes.rowid")))
    changes = [change for change in records if not in_scratch(change.path)]
    merges = session.scalars(select(Merge).where(Merge.run_id == run_id).order_by(
        Merge.created_at)).all()
    if not changes and not merges:
        return None
    went = _went_in(changes)
    waiting: list[str] = []
    sent: list[str] = []
    for merge in merges:
        if (merge.commit or {}).get("state") == "pull_request":
            url = merge.commit.get("url")
            sent.append(f"Sent as a pull request{': ' + url if url else ''}.")
        waits = merge.status == "pending" or (merge.status == "interrupted" and merge.kept_in)
        for one in merge.files:
            if one["state"] == "applied":  # (what went in, as its merge counted it)
                # (No count is no sign of a binary: a branch's 31st file, a mode-only change...)
                went[one["path"]] = "deleted" if one["kind"] == "deleted" else (
                    (one["additions"], one["deletions"]) if one.get("additions") is not None
                    and one.get("deletions") is not None else None)
            # (Only what its card offers to take: not one refused, nor one left out of it.)
            elif waits and one["state"] in ("ready", "merged", "conflict") and (
                    one["path"] not in waiting):
                waiting.append(one["path"])
    said = [_in_the_project(went)] if went else []
    said += sent
    if waiting:
        one = len(waiting) == 1
        said.append(f"Not in the project yet: {_named(waiting)} wait{'s' if one else ''} in "
                    f"Ready for you - Take in to apply {'it' if one else 'them'}.")
    if said:
        return " ".join(said)
    return ("No file change on record reached the project, but commands ran in it."
            if _ran_in_project(session, run_id) else "Nothing reached the project.")
