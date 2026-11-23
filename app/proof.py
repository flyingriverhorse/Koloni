"""Kanıtlı bitiş (proven finish), what needs no model: the kind of each file a turn changed, the
project's test command(s), the turn's changes on record, whether a test run on record stands for
this turn's, and the rows of the Checked section KOLONİ writes under the answer (`ProofMixin`)."""

import contextlib
import difflib
import fnmatch
import hashlib
import json
import os
import re
from collections.abc import Collection, Iterable
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal, NamedTuple, NotRequired, TypedDict

from sqlalchemy import literal_column, or_, select
from sqlalchemy.orm import Session

from app import finish_tests, git, ledger, project_map, test_found
from app.code_map import PYTHON, SCRIPT, tested
from app.commands import only_reads, only_searches, plain
from app.db.models import (
    Agent,
    Command,
    Conversation,
    ConversationTeam,
    FileChange,
    Flag,
    Message,
    Project,
    Run,
    ToolCall,
)
from app.tools import MAX_TIMEOUT
from app.workspace import in_scratch, is_secret, secret_in_project, unified_diff

# KOLONİ's own end-of-turn test run: its call's id starts so (`ProofMixin`).
PROOF_CALL = "koloni_proof_"
# The spawns of KOLONİ's own that only read (S3's Reviewer, S11's diagnosis): `PROOF_CALL` + kind.
READ_ONLY_LOOKS = ("review", "diagnose")

# Project.after_change, shown as Test and review ("check"), Tests only, Nothing.
AFTER_CHANGE = ("check", "tests", "nothing")
# Conversation.after_change (S10): None the project's; this chat's "off" or "on".
CHAT_AFTER_CHANGE = ("off", "on")

# By the file's name, casefolded (a name wins over an extension).
KIND_BY_NAME: dict[str, str] = {
    **dict.fromkeys(
        (
            "requirements*.txt",
            "constraints*.txt",
            "pyproject.toml",
            "setup.py",
            "setup.cfg",
            "tox.ini",
            "pytest.ini",
            "conftest.py",
            "package.json",
            "package-lock.json",
            "pnpm-lock.yaml",
            "yarn.lock",
            "tsconfig*.json",
            "vite.config.*",
            "vitest.config.*",
            "makefile",
            "dockerfile",
            "docker-compose*.yml",
            ".env*",
        ),
        "config",
    ),
    "*.drawio.xml": "diagram",
}
KIND_BY_EXT: dict[str, str] = {
    **dict.fromkeys((".md", ".markdown", ".rst", ".adoc", ".txt", ".docx", ".odt"), "docs"),
    **dict.fromkeys((".pptx", ".odp", ".key"), "slides"),
    **dict.fromkeys(
        (".drawio", ".dio", ".mmd", ".mermaid", ".puml", ".plantuml", ".svg"), "diagram"
    ),
    **dict.fromkeys((".csv", ".tsv", ".ipynb", ".parquet", ".xlsx", ".xls"), "data"),
    **dict.fromkeys(
        (".html", ".htm", ".css", ".scss", ".sass", ".less", ".vue", ".svelte", ".tsx", ".jsx"),
        "ui",
    ),
    **dict.fromkeys((".toml", ".yaml", ".yml", ".json", ".ini", ".cfg", ".lock"), "config"),
}
# What changes nothing a test reads: only such a turn runs no test.
NO_TESTS = frozenset({"docs", "slides", "diagram", "data"})
# A branch turn's work once merged at its end (`_drop_copy`): still the turn's, made when it was
# made - not at the merge.
MERGED = "merged"


def kind_of(path: str) -> str:
    """ "code", "config", "docs", "slides", "diagram", "data" or "ui"; what no table names: code."""
    posix = path.replace("\\", "/").casefold()
    if "/.github/workflows/" in f"/{posix}":
        return "config"
    name = posix.rsplit("/", 1)[-1]
    named = next(
        (kind for pattern, kind in KIND_BY_NAME.items() if fnmatch.fnmatchcase(name, pattern)), None
    )
    return named or KIND_BY_EXT.get(PurePosixPath(name).suffix, "code")


def needs_tests(paths: Iterable[str]) -> bool:
    """False only for changes that are all documents, slides, diagrams or data."""
    kinds = {kind_of(path) for path in paths}
    return bool(kinds - NO_TESTS)


class TestRun(NamedTuple):
    """A test command, the folder it runs in (project-relative POSIX, "." the root), and whether
    it runs as the user's own - their command, or one KOLONİ saved that an Always rule covers
    (else on a card below Full auto: KOLONİ's guess, or a saved one no rule covers); and whether
    KOLONİ saved it (`Project.tests_found`: no guess any more, said so)."""

    command: str
    cwd: str
    yours: bool
    saved: bool = False
    # S8: a line of the project's CI workflows the user approved (said "from CI").
    ci: bool = False

    @property
    def guessed(self) -> bool:
        return not (self.yours or self.saved)


def test_runs(project: Project, found: dict | None) -> list[TestRun]:
    """The project's whole test command(s): the user's check command; else each part's test of
    its map (the user's, or the map's guess); else the guess from its files; else none."""
    if project.check_command and project.check_command.strip():
        return [TestRun(project.check_command.strip(), ".", True)]
    parts = project_map.edited(found, project.test_commands or {})["parts"] if found else []
    runs = [
        TestRun(
            part["test"], part["path"].removeprefix("./").rstrip("/") or ".", bool(part["edited"])
        )
        for part in parts
        if part["test"]
    ]
    guess = None if runs else finish_tests.command_of(project.root_path, None)
    return runs or ([TestRun(guess, ".", False)] if guess else [])


class Change(NamedTuple):
    """One path a turn changed: its kind, lines added and removed (first before to last after),
    whether it is gone, who changed it last, and whether it is where the tests run."""

    path: str
    kind: str
    added: int
    removed: int
    deleted: bool
    agent_id: str
    in_project: bool
    # S2: whether it was there before the turn - one it made and deleted again is no removal.
    existed: bool = True
    # k-onceki-1: in the project, with a newer change of it waiting in a copy - that agent's.
    waiting: str | None = None


def changes(
    session: Session, run_id: str, lead_id: str, sharing: Collection[str] = ()
) -> list[Change]:
    """The turn's kept changes, one a path. Not in the project: a copy's (`in_copy`) of an agent
    other than the Lead, waiting in Ready for you - but where that agent works in the Lead's own
    copy (`sharing`: an Away job's, a branch turn's), where the tests run. A path the project
    holds a change of the turn's to is in the project as that change stands, whatever a copy
    waiting since holds of it (k-onceki-1, K: a fixer's work its Take in's check kept out hid
    the whole turn's)."""
    here = {lead_id, *sharing}
    found = []
    for path, made in _kept(session, run_id).items():
        there = [
            at
            for at, one in enumerate(made)
            if one.status in ("applied", MERGED) or one.agent_id in here
        ]
        last = made[there[-1]] if there else made[-1]
        _diff, added, removed = unified_diff(
            made[0].before_content, last.after_content or "", path, context=0
        )
        after = made[there[-1] + 1 :] if there else []
        found.append(
            Change(
                path,
                kind_of(path),
                added,
                removed,
                last.kind == "delete",
                last.agent_id,
                bool(there),
                made[0].kind != "create",
                after[-1].agent_id if after else None,
            )
        )
    return found


# S2: the source files a test is asked for - a script of a language, by its extension.
# shortcut: by the file's name alone, as `code_map.tested` reads tests (`FooTest.java` is no test
# there: a Java change with only such a test is asked for one); read a language's own test
# convention if that is met.
SOURCE = frozenset(
    {
        *PYTHON,
        *SCRIPT,
        ".vue",
        ".svelte",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".cs",
        ".rb",
        ".php",
        ".ex",
        ".exs",
        ".swift",
        ".scala",
        ".c",
        ".cc",
        ".cpp",
        ".h",
        ".hpp",
    }
)


def is_test(path: str) -> bool:
    """Whether a path is a test file, by its name or folder (`code_map.tested`)."""
    return tested(path.replace("\\", "/")) is not None


def new_tests(changes: list[Change]) -> list[Change]:
    """The test files the turn added or changed - not deleted; one an agent's work holds still
    waiting in Ready for you too (a test is written for the change)."""
    return [one for one in changes if not one.deleted and is_test(one.path)]


def removed_tests(changes: list[Change]) -> list[str]:
    """The test files the turn deleted that were there before it."""
    return [
        one.path
        for one in changes
        if one.in_project and one.deleted and one.existed and is_test(one.path)
    ]


def untested(changes: list[Change]) -> list[str]:
    """S2: the source files the turn changed in the project (a script of a language, not deleted,
    not a test) where it changed no test; else none."""
    if new_tests(changes):
        return []
    return [
        one.path
        for one in changes
        if one.in_project
        and not one.deleted
        and one.kind in ("code", "ui")
        and not is_test(one.path)
        and PurePosixPath(one.path.replace("\\", "/").casefold()).suffix in SOURCE
    ]


def before_of(session: Session, run_id: str) -> dict[str, str | None]:
    """S5a: each path the turn kept a change of, as it was before the turn (None: not there)."""
    return {path: made[0].before_content for path, made in _kept(session, run_id).items()}


def added_lines(
    session: Session, run_id: str, lead_id: str, sharing: Collection[str] = ()
) -> dict[str, list[int]]:
    """S9: the lines the turn added (or rewrote) in each in-project file, by their number in
    the file as it now is - from its first before to its last after on record."""
    here = {lead_id, *sharing}
    out: dict[str, list[int]] = {}
    for path, made in _kept(session, run_id).items():
        last = made[-1]
        if not (last.status in ("applied", MERGED) or last.agent_id in here) or (
            last.kind == "delete"
        ):
            continue
        before = (made[0].before_content or "").splitlines()
        after = (last.after_content or "").splitlines()
        lines = [
            number + 1
            for tag, _a, _b, start, end in difflib.SequenceMatcher(
                None, before, after, autojunk=False
            ).get_opcodes()
            if tag in ("replace", "insert")
            for number in range(start, end)
        ]
        if lines:
            out[path] = lines
    return out


def _kept(session: Session, run_id: str) -> dict[str, list[FileChange]]:
    """The turn's kept changes by path, oldest first (none of its scratch folder)."""
    rows: dict[str, list[FileChange]] = {}
    for row in session.scalars(
        select(FileChange)
        .where(FileChange.run_id == run_id, FileChange.status.in_((*ledger.KEPT, MERGED)))
        .order_by(FileChange.created_at, literal_column("file_changes.rowid"))
    ):
        if not in_scratch(row.path):
            rows.setdefault(row.path, []).append(row)
    return rows


# --- S3: the Reviewer at a turn's end -------------------------------------------------------

# A change this big is looked over (lines added and removed, files) - of code, config and
# screens only: documents, slides, diagrams and data are not.
BIG_LINES, BIG_FILES = 80, 3
REVIEWED_KINDS = frozenset({"code", "config", "ui"})
# Path words, matched against each part of a path (casefolded), and file names, that make a
# change security-touching whatever its size.
SECURITY_PATHS = frozenset(
    {
        "auth",
        "authn",
        "authz",
        "authentication",
        "authorization",
        "oauth",
        "login",
        "session",
        "sessions",
        "token",
        "tokens",
        "secret",
        "secrets",
        "password",
        "passwords",
        "passwd",
        "credential",
        "credentials",
        "permission",
        "permissions",
        "cookie",
        "cookies",
        "crypto",
        "cipher",
        "acl",
        "policy",
        "policies",
        "sandbox",
        "security",
        "jwt",
        "csrf",
        "cors",
    }
)
SECURITY_NAMES = (".env*", "*.pem", "*.key", "dockerfile")
# ...and what an ADDED line may do: run a command, run code, load what runs code, reach the
# network, put HTML in a page, loosen a check or a file's rights.
SECURITY_LINES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern))
    for name, pattern in (
        ("subprocess", r"\bsubprocess\b"),
        ("os.system", r"\bos\.system\b"),
        ("shell=True", r"shell\s*=\s*True"),
        ("eval(", r"\beval\("),
        ("exec(", r"\bexec\("),
        ("pickle.load", r"\bpickle\.loads?\b"),
        ("yaml.load(", r"\byaml\.load\("),
        ("child_process", r"\bchild_process\b"),
        ("dangerouslySetInnerHTML", r"dangerouslySetInnerHTML"),
        (".innerHTML =", r"\.innerHTML\s*="),
        ("fetch(", r"\bfetch\("),
        ("requests.", r"\brequests\.\w"),
        ("httpx.", r"\bhttpx\.\w"),
        ("urllib.request", r"\burllib\.request\b"),
        ("socket.", r"\bsocket\.\w"),
        ("verify=False", r"verify\s*=\s*False"),
        ("chmod", r"\bchmod\b"),
        ("setuid", r"\bsetuid\b"),
    )
)


class Review(NamedTuple):
    """Why a turn's change is looked over: it is big (`lines` / `files` of code, config and
    screens), and what makes it security-touching ("app/auth.py (path)", "shell=True (added in
    app/utils.py)")."""

    big: bool
    security: list[str]
    lines: int
    files: int


# A word boundary inside a camelCase name: "userAuth", "OAuthToken".
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _security_path(path: str) -> bool:
    posix = path.replace("\\", "/").casefold()
    name = posix.rsplit("/", 1)[-1]
    # (Words of a name: "user_auth", "userAuth", "auth-service" - auth; a missed look is worse
    # than one too many, so "policy_net" is policy.)
    spaced = _CAMEL.sub(" ", path.replace("\\", "/"))
    words = {word.casefold() for word in re.split(r"[\W_]+", spaced) if word}
    # (Whole words, trailing digits off: "oauth2", "tokens" - not "author", "tokenizer".)
    return (
        any(word.rstrip("0123456789") in SECURITY_PATHS for word in words)
        or ("/.github/workflows/" in f"/{posix}")
        or any(fnmatch.fnmatchcase(name, pattern) for pattern in SECURITY_NAMES)
    )


def review_reasons(changes: Iterable[Change], diff: str) -> Review:
    """Whether a turn's in-project change is to be looked over, and why: its size over code,
    config and screens, its paths, and what its ADDED lines in `diff` do (a removed `eval(` is
    no reason)."""
    shown = [one for one in changes if one.in_project]
    counted = [one for one in shown if one.kind in REVIEWED_KINDS]
    lines = sum(one.added + one.removed for one in counted)
    found = [f"{one.path} (path)" for one in shown if _security_path(one.path)]
    path = ""
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[4:].removeprefix("b/")
        elif line.startswith("+") and not line.startswith("+++"):
            found += [
                f"{name} (added in {path})"
                for name, pattern in SECURITY_LINES
                if pattern.search(line) and f"{name} (added in {path})" not in found
            ]
    return Review(lines > BIG_LINES or len(counted) > BIG_FILES, found, lines, len(counted))


def turn_diff(
    session: Session, run_id: str, lead_id: str, most: int, sharing: Collection[str] = ()
) -> tuple[str, str, list[str]]:
    """The turn's in-project kept changes as one diff (each file from its first before to its
    last after), cut at `most` characters: the text, the whole of it (what is scanned for a
    security touch: every line), and the files left out. A secret file is named, never shown."""
    here = {lead_id, *sharing}
    parts: list[tuple[str, str]] = []
    for path, made in _kept(session, run_id).items():
        last = made[-1]
        if not (last.status in ("applied", MERGED) or last.agent_id in here):
            continue
        if secret_in_project(path):
            parts.append((path, f"{path}: a secret file - changed, not shown\n"))
            continue
        diff, _added, _removed = unified_diff(
            made[0].before_content, last.after_content or "", path
        )
        parts.append((path, diff if diff.endswith("\n") or not diff else f"{diff}\n"))
    return cut(parts, most)


def cut(parts: list[tuple[str, str]], most: int) -> tuple[str, str, list[str]]:
    """Each file's diff, (path, text), as one diff cut at `most` characters: the text, the whole
    of it, and the files left out."""
    whole = "".join(text for _path, text in parts)
    shown, left = "", []
    for path, text in parts:
        if len(shown) + len(text) <= most:
            shown += text
        else:
            left.append(path)
    return shown, whole, left


def kept_work(copy, lead_id: str) -> list[tuple[Change, str]]:
    """k-bakis-yeri: a kept copy's work as Take in would bring it - each file it changed against
    the project, as it stands - for the end check of the turn that goes on in it (Fix it on a
    "Not taken in" row): each file's change, where the tests run, and its diff (a secret file
    named, never shown). Blocking: it reads the copy and the project."""

    def text_of(place: Path | None) -> str:
        try:
            return (
                place.read_bytes().decode("utf-8", "replace") if place and place.is_file() else ""
            )
        except OSError:
            return ""

    found = []
    for path, kind, _state in copy.changes():
        after = "" if kind == "deleted" else text_of(copy.here(path))
        diff, added, removed = unified_diff(text_of(copy.there(path)), after, path)
        if secret_in_project(path):
            diff = f"{path}: a secret file - changed, not shown"
        made = Change(path, kind_of(path), added, removed, kind == "deleted", lead_id, True)
        found.append(
            (made._replace(existed=kind != "new"), diff.rstrip("\n") + "\n" if diff else "")
        )
    return found


def unrecorded(
    session: Session, run_id: str, by: Collection[str], folder: str | None = None
) -> tuple[str, datetime | None] | None:
    """CL-321 Bulgu D: the commands of `by` (the Lead and the agents working where it does) this
    turn, in `folder` (the project), that may have changed files no change record holds - each
    with a part that is neither a mere read (`only_reads`), a lone search (`only_searches`) nor a
    test run (`ledger.read_test`): `python -c "open(…)"`, `sed -i`, a heredoc to a file,
    `black . && pytest -q`. Not KOLONİ's own: its end check's, nor one it ran with no tool call
    (a merge's or a take-in's check, in a working copy or the project - as S7's
    `_changed_by_command`); nor one in a working copy, whose changes are recorded as it is taken
    in. The newest's line, shortened, and when the oldest started (an earlier `sed -i` wrote too);
    None: none."""
    mine = select(ToolCall.id).where(ToolCall.provider_call_id.startswith(PROOF_CALL))
    newest, oldest = None, None
    for line, started, cwd in session.execute(
        select(Command.command, Command.started_at, Command.cwd)
        .where(
            Command.run_id == run_id,
            Command.agent_id.in_(by),
            Command.status.in_(("exited", "timed_out")),
            Command.tool_call_id.is_not(None),
            Command.tool_call_id.not_in(mine),
        )
        .order_by(Command.started_at.desc(), literal_column("commands.rowid").desc())
    ):
        if _ran_in(cwd, folder) and may_write(line):
            if newest is None:
                said = " ".join(line.split())
                newest = said if len(said) <= MOST_COMMAND else said[: MOST_COMMAND - 1] + "…"
            oldest = started
    return None if newest is None else (newest, oldest)


def _ran_in(cwd: str | None, folder: str | None) -> bool:
    """Whether a command ran in the project `folder`: no folder said where it ran (a CLI's own
    command), or one in it - not a working copy's."""
    if not cwd or folder is None or not os.path.isabs(cwd):
        return True
    here = os.path.normcase(os.path.realpath(folder))
    there = os.path.normcase(os.path.realpath(cwd))
    return there == here or there.startswith(here.rstrip(os.sep) + os.sep)


def may_write(line: str) -> bool:
    """Whether a command line may change files: a part of it (`ledger._split`) is neither a mere
    read (`only_reads`), a lone search (`only_searches`: `rg KEY .`) nor a test run
    (`ledger.read_test`) - `black . && pytest -q` may. CL-329 G: so may a line that redirects
    into a file (`cat a > b`, `git show HEAD:f > f`; not `2>&1`, `/dev/null`), a test run with
    an option that writes (`jest -u`, `--junitxml=a.py`: `ledger.test_writes`), a command
    substitution (`pytest -q $(sed -i …)`) and a line handed to a shell that may
    (`bash -c "pytest -q > a.py"`)."""
    if ledger.written_to(line) or "$(" in line or "`" in line:
        return True
    for words, _op in ledger._split(line):
        if not words:
            continue
        handed = ledger._handed_on(ledger._past_leads(words))
        part = " ".join(words)
        if handed is not None:
            if may_write(handed):
                return True
        elif ledger.read_test(part) is not None:
            if ledger.test_writes(part):
                return True
        elif not only_reads(part) and not only_searches(part):
            return True
    return False


def touched_since(
    folder: Path, since: datetime | None, recorded: Collection[str], head: str | None = None
) -> list[str] | None:
    """Review of CL-321 D: what commands may have changed, by git - the files `git status`
    lists in `folder` (changed, added, untracked; not ignored) and, from `head` (the turn's
    start), those committed since (`black . && git commit -am x`), but those on record
    (`recorded`), written at or after `since` - and (CL-329 G) a tracked test file deleted, which
    has no time to read. None: no git there (or it did not answer in time). Blocking: call it
    off the event loop.
    shortcut: a tracked test file deleted before the turn is counted too (git says no when);
    read the deletions as the turn begins if that is seen.
    shortcut: another tracked file deleted is not seen (no time to read); count those if missed.
    shortcut: a write that keeps an old time (`cp -p`, `tar x`, `unzip`, `touch -d`), one into
    an ignored folder and a secret-named file (`git.changes` leaves it out) are not seen; ask
    git for them, or read the files' hashes as the turn begins, if a change slips by so."""
    listed = git.changes(folder)
    if listed is None:
        return None
    paths = [one["path"] for one in listed]
    if head is not None:
        paths += [one for one in git.committed_since(folder, head) if not is_secret(one)]
    edge = since.timestamp() - MTIME_SLACK if since is not None else float("-inf")
    found = [
        one["path"]
        for one in listed
        if one["status"] == "D" and is_test(one["path"]) and one["path"] not in recorded
    ]
    for path in dict.fromkeys(paths):
        if path in recorded or path in found:
            continue
        with contextlib.suppress(OSError):
            if (folder / path).stat().st_mtime >= edge:
                found.append(path)
    return sorted(found)


# CL-329: a tracked file over this size is left as KOLONİ's own run left it (not read to keep).
MOST_PUT_BACK = 2 * 1024 * 1024


class Before(NamedTuple):
    """CL-329: the project as KOLONİ's own run found it - its commit, and each tracked file git
    listed as changed then, by its bytes (None: gone, or too big to keep)."""

    head: str | None
    files: dict[str, bytes | None]


def sources_before(folder: Path) -> Before | None:
    """CL-329: the project's tracked files as KOLONİ's own run starts (`Before`); one git lists
    as unchanged is its commit's. None: no git there. Blocking: call it off the event loop."""
    listed = git.changes(folder)
    if listed is None:
        return None
    kept: dict[str, bytes | None] = {}
    for one in listed:
        if one["status"] == "?":
            continue
        try:
            path = folder / one["path"]
            kept[one["path"]] = path.read_bytes() if path.stat().st_size <= MOST_PUT_BACK else None
        except OSError:
            kept[one["path"]] = None
    return Before((git.where(folder) or {}).get("head"), kept)


def _digest(path: Path) -> str:
    """A file's bytes as a digest; "" where it is gone."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def changed_during(folder: Path, before: Before, spare: Collection[str]) -> dict[str, str]:
    """CL-329 (review: say it, never revert it by itself): each tracked file git lists as changed
    after KOLONİ's own run that it did not list before it, or whose bytes are not those of then -
    by the digest it has now -, but those written on record meanwhile (`spare`: an agent's). Who
    changed it is not known: the run itself (a check that formats), the user's editor, another
    chat's command. A file the run made that git does not track is not one. Blocking."""
    found: dict[str, str] = {}
    for one in git.changes(folder) or []:
        rel = one["path"]
        if (
            one["status"] == "?"
            or rel in spare
            or (rel in before.files and (before.files[rel] is None))
        ):
            continue
        if rel in before.files:
            try:
                if (folder / rel).read_bytes() == before.files[rel]:
                    continue
            except OSError:
                pass
        found[rel] = _digest(folder / rel)
    return found


def put_back(folder: Path, rel: str, before: Before, after: str) -> str | None:
    """The user's Put back of a file `changed_during` KOLONİ's run (their click): as it was when
    the run started - its bytes then, or the run's commit's through git's own filters and line
    ends (`git.restore_at`). Only where it is still as the run left it (`after`, its digest).
    None: put back; else why not."""
    target = folder / rel
    if not target.resolve().is_relative_to(folder.resolve()):
        return f"{rel} {OUTSIDE}"
    if _digest(target) != after:
        return f"{rel} {AGAIN}"
    if before.files.get(rel) is not None:
        try:
            target.write_bytes(before.files[rel] or b"")
        except OSError as exc:
            return f"{rel}: {exc}"
        return None
    if before.head is None:
        return f"{rel}: no commit to put it back from"
    return git.restore_at(folder, before.head, rel)


def change_states(session: Session, run_id: str) -> dict[str, tuple[str, str | None]]:
    """k-sira-016: the turn's kept change records - each one's status and agent, by id: what
    Ready for you's pass saw, to tell its own Take in from work that came in after it."""
    return {
        one: (status, agent)
        for one, status, agent in session.execute(
            select(FileChange.id, FileChange.status, FileChange.agent_id).where(
                FileChange.run_id == run_id, FileChange.status.in_((*ledger.KEPT, MERGED))
            )
        )
    }


def last_change(session: Session, run_id: str, made_there: Collection[str] = ()) -> datetime | None:
    """When the turn's newest kept change was made or taken in: a test run that started before
    it did not see it. (A merged branch's: when it was made - the gate ran on the branch. And,
    for a run where `made_there`'s agents worked, theirs: their copy held it when it was made.)"""
    times = session.execute(
        select(
            FileChange.created_at, FileChange.decided_at, FileChange.status, FileChange.agent_id
        ).where(FileChange.run_id == run_id, FileChange.status.in_((*ledger.KEPT, MERGED)))
    ).all()
    return max(
        (
            one
            for made, decided, status, agent in times
            for one in (made, None if status == MERGED or agent in made_there else decided)
            if one is not None
        ),
        default=None,
    )


def _folded(command: str) -> str:
    return " ".join(command.split())


def _known_as(session: Session, one: Command) -> str:
    """The command a run on record is known by, folded: S9 - KOLONİ's own end-check run (its call
    `PROOF_CALL…`) that added coverage's report flags, by the command it built that very line
    from (`known_as` on its call, beside the line - never read back out of the line: a project
    path may hold a space or a parenthesis); never an agent's line, however like them it looks
    (`pytest -q --cov=. --cov-report=json:….koloni/tmp/coverage-x;true` is not `pytest -q`)."""
    folded = _folded(one.command)
    if "coverage-" not in folded or one.tool_call_id is None:
        return folded
    call = session.execute(
        select(ToolCall.provider_call_id, ToolCall.arguments).where(ToolCall.id == one.tool_call_id)
    ).first()
    if call is None or not (call[0] or "").startswith(PROOF_CALL):
        return folded
    try:
        args = json.loads(call[1] or "{}")
    except ValueError:
        return folded
    plain = args.get("known_as") if isinstance(args, dict) else None
    built = isinstance(plain, str) and _folded(str(args.get("command", ""))) == folded
    return _folded(plain) if built else folded


def fresh(
    session: Session,
    run_id: str,
    lead_id: str,
    run: TestRun,
    since: datetime | None,
    sharing: Collection[str] = (),
    made: datetime | None = None,
) -> Command | None:
    """The newest run of exactly `run`'s command in its folder that ran to its end with an exit
    code and stands for the work as it is: the Lead's (or KOLONİ's, on its record) started after
    `since`; or one of `sharing`'s - the agents that worked where the Lead does, a recipe's Tester
    in its copy - started after `made` (`last_change` with them: what their copy held, Take in
    brought in as it was; plan decision 13, no second run). Never one after which a command of
    that place's agents started that may have changed files - a formatter, a codegen, a sed: no
    FileChange records what it rewrote (`_rewritten_after`). None: run it. (Claude Code's pass,
    exit code None, is never reused; nor a sub-agent's in a copy of its own.)
    shortcut: a Take-in check that ran the same command on what then went in is not counted - the
    project may hold more by then; count it when its `checked` files equal what was taken, if the
    double run is felt."""
    wanted, by, looked = _folded(run.command), {lead_id, *sharing}, set()
    for one in session.scalars(
        select(Command)
        .where(
            Command.run_id == run_id,
            Command.agent_id.in_(by),
            Command.status == "exited",
            Command.exit_code.is_not(None),
            Command.cwd == run.cwd,
            Command.started_at.is_not(None),
        )
        .order_by(Command.started_at.desc(), literal_column("commands.rowid").desc())
    ):
        mine = one.agent_id == lead_id  # (the newest of each place's runs is its word)
        if _known_as(session, one) != wanted or mine in looked:
            continue
        looked.add(mine)
        after = since if mine else made
        if (after is None or (one.started_at or after) > after) and not _rewritten_after(
            session, run_id, by, one, wanted
        ):
            return one
    return None


def _rewritten_after(
    session: Session, run_id: str, by: Collection[str], ran: Command, wanted: str
) -> bool:
    """Whether a command of `by` started after `ran` that may have changed files, or ran the same
    test command again and did not pass: any but one that only reads (`commands.only_reads`) or
    a clean pass of exactly the end check's command. A test tool on a line is no sign it only
    tested - `fmt && pytest`, `jest -u`, `--snapshot-update` write. Re-running is the safe way."""
    return any(
        not only_reads(one.command)
        and not (
            _known_as(session, one) == wanted and one.status == "exited" and one.exit_code == 0
        )
        for one in session.scalars(
            select(Command).where(
                Command.run_id == run_id,
                Command.agent_id.in_(by),
                Command.id != ran.id,
                # (`>=`: a later line in the same tick of Windows' clock is no proof it came first)
                Command.started_at.is_not(None),
                Command.started_at >= ran.started_at,
            )
        )
    )


def after_change_of(session: Session, conversation: Conversation, run: Run | None = None) -> str:
    """After a change for a turn of this chat (S10, plan decision 17): the project's ("check",
    "tests", "nothing") unless the chat says otherwise - "off" (its switch off: nothing checked),
    or on: the project's, Test and review where that is Nothing. A recipe's turn (`run.teams`)
    follows the recipe, never the chat's switch: the project's, unless its recipe's Checks step
    is set for the recipe (`checks_of`)."""
    project = session.get(Project, conversation.project_id) if conversation.project_id else None
    own = project.after_change if project is not None else "nothing"
    if run is not None and run.teams:
        return own
    if conversation.after_change == "off":
        return "off"
    return "check" if conversation.after_change == "on" and own == "nothing" else own


# S5c (plan decision 16): what the end gate checks, part by part - the project's tests, the
# Reviewer's look, each kind of work a turn wrote (`app.proof_kinds.WRITTEN`: S5b's pages, "ui").
PARTS = ("tests", "review", "docs", "diagram", "data", "slides", "ui")


class Checks(NamedTuple):
    """What a turn's end gate checks (S5c): its parts `on`; its Fix rounds (0: check only; None:
    until it passes, k-canli-016); the effective After a change (`after_change_of`); and whether
    a recipe of the turn set its own (its Checks step's "Set for this recipe")."""

    on: frozenset[str]
    rounds: int | None
    setting: str
    own: bool


# k-canli-016 (the user's): Until it passes - the work goes back while each round makes progress,
# within the turn's token limit and the project's budget, and never more than this many times.
UNTIL_CEILING = 20


def _more(*rounds: int | None) -> int | None:
    """The more of Fix rounds: until it passes (None) is more than any number."""
    numbers = [one for one in rounds if one is not None]
    return None if len(numbers) < len(rounds) else max(numbers, default=0)


def _asked(asked: int | str | None, rounds: int | None) -> int | None:
    """A recipe's Checks step's Fix rounds: None the project's, "until" until it passes."""
    return rounds if asked is None else None if asked == "until" else int(asked)


def recipe_checks(session: Session, run: Run | None) -> list[tuple[dict | None, str]]:
    """The Checks step of each recipe run in this turn, as its row's copy of the graph has it
    (`RecipeGraph.checks`; None: it follows the project), and who picked the row ("user" in
    Manual, "lead" where the Orchestrator decides)."""
    if run is None or not run.teams:
        return []
    rows = session.execute(
        select(ConversationTeam.state, ConversationTeam.picked_by).where(
            ConversationTeam.conversation_id == run.conversation_id
        )
    )
    return [
        (state["graph"].get("checks"), picked)
        for state, picked in rows
        if state and state.get("run_id") == run.id and isinstance(state.get("graph"), dict)
    ]


def checks_of(session: Session, conversation: Conversation, run: Run | None = None) -> Checks:
    """What the end gate checks in this turn: the project's After a change (Test and review: the
    tests, the review and each kind its Check by kind of work leaves on; Tests only: the tests;
    Nothing / off for the chat: nothing) and Fix rounds - or, in a recipe's turn whose Checks
    step is set for the recipe, what it sets (decisions 16, 17: never the chat's switch) - where
    the user picked the recipe; one the Orchestrator picked only adds to the project's. Two
    recipes in one turn: what either checks, the more rounds of the two.
    shortcut: a turn's recipe is known once it has started - the words its agents get before
    that (`_checks_told`) follow the project; tell them again if a recipe's own is missed."""
    setting = after_change_of(session, conversation, run)
    project = session.get(Project, conversation.project_id) if conversation.project_id else None
    rounds = project.fix_rounds if project is not None else None
    kinds = dict(project.check_kinds or {}) if project is not None else {}
    theirs = frozenset(
        (["tests"] if setting in ("check", "tests") else [])
        + (
            ["review", *(kind for kind in PARTS[2:] if kinds.get(kind, True))]
            if setting == "check"
            else []
        )
    )
    recipes = recipe_checks(session, run)
    if all(one is None for one, _who in recipes):
        return Checks(theirs, rounds, setting, False)
    on: set[str] = set()
    most: int | None = 0
    for one, who in recipes:
        parts = set() if one is None else {part for part in PARTS if one.get(part)}
        asked = None if one is None else one.get("fix_rounds")
        # (Review of S5c: only a recipe the user picked may lower the project's checks - one the
        # Orchestrator picked only adds to them, or it would switch its own checks off.)
        if one is not None and who == "user":
            on, most = on | parts, _more(most, _asked(asked, rounds))
        else:
            on, most = on | parts | theirs, _more(most, rounds, _asked(asked, rounds))
    return Checks(frozenset(on), most, setting, True)


def too_slow(session: Session, project_id: str, run: TestRun, seconds: int) -> str | None:
    """Why `run` is not run where a turn's end waits at most `seconds` for it: the newest run of
    it in the project (any chat's, anyone's) ran longer, or was stopped at a limit of that wait or
    more (the limit it really had, as its record keeps it - not one the wait for the machine ate
    into) - said as when; None: run it. A quicker run since (an agent's, the user's) lets it run
    again."""
    wanted = _folded(run.command)
    for one in session.scalars(
        select(Command)
        .join(Run, Run.id == Command.run_id)
        .join(Conversation, Conversation.id == Run.conversation_id)
        .where(
            Conversation.project_id == project_id,
            Command.cwd == run.cwd,
            Command.status.in_(("exited", "timed_out")),
            Command.started_at.is_not(None),
            Command.ended_at.is_not(None),
        )
        .order_by(Command.ended_at.desc(), literal_column("commands.rowid").desc())
    ):
        if _known_as(session, one) != wanted or one.ended_at is None or one.started_at is None:
            continue
        took = (one.ended_at - one.started_at).total_seconds()
        if (
            took > seconds
            or one.status == "timed_out"
            and one.timeout_seconds >= seconds
            and (took >= one.timeout_seconds - 1)
        ):  # (it ran its whole limit: a second's slack)
            return f"they ran past {clock(seconds)} on {one.ended_at:%d %b %H:%M}"
        return None
    return None


# S11: why a stronger model's rounds were no pass - a test changed without leave, the Reviewer
# held or did not read the test change, the tests gave no verdict, or they still fail.
Reason = Literal["touched", "held", "unread", "no_verdict", "still", "on_hold"]


class Row(TypedDict):
    kind: str
    state: str
    text: str
    command: str | None
    guessed: bool
    started_at: str | None
    # S1b: what its runner's summary counted ({"passed", "failed", "skipped", "unit"}); None:
    # no count known (never made up).
    counts: dict | None
    # S11: a "not_taken" row's kept copy (Take in anyway) and the stronger model's question
    # (Fix it sends the user's answer to it).
    merge_id: NotRequired[str]
    question: NotRequired[str]
    # S8: a "ci_offer" row's offer, by its name (`ci_commands.offer_id`): Run these approves it.
    offer: NotRequired[str]
    # S11: why a stronger model's rounds were no pass (`Reason`): Fix it's fixed sentence goes by
    # it, never by the row's text, which names what a model chose.
    reason: NotRequired[Reason]
    # N: a failed "tests" row whose every failure was failing before this turn, or flaky (S7, a
    # lint's CL-336 M) - said, not sent back: no gate waits on it (`still_failing`).
    before: NotRequired[bool]


ICONS = {"passed": "✓ ", "failed": "✗ ", "running": "… "}

PASSED_ROW = "Tests passed: {command}{guessed} - {summary}"
# A runner KOLONİ reads no count of (an `npm test` that prints none): its exit code alone, said.
BY_CODE = "Tests passed (by exit code, no count): {command}{guessed}"
SKIPPED_ONLY = "Tests skipped only: {command} - {summary}"
# A test line whose exit is not the tests' (`ledger.read_test`: `| tail -1`, `|| true`).
NO_VERDICT = "Tests gave no verdict: {command} masks its exit"
FAILED_ROW = "Tests failed: {command}{guessed} - {summary}"
RAN_NONE = "Tests ran none: {command} collected no test"
TIMED_OUT = "Tests timed out after {minutes} min: {command}"
# A turn the user watches waits at most so long for them (S1, until they can run on in the
# background): stopped then, and said so - never passed or failed.
NOT_WAITED = (
    "Tests not waited for: still running at {clock}, so KOLONİ stopped them rather "
    "than hold the answer - {command}"
)
NOT_RUN = "Tests not run: {why}"
# (A change made after the last run: that run did not see it.)
NOT_AGAIN = "Tests not run on the last change: {why}"
NOT_STARTED = "Tests could not start: {first}"
STOPPED = "Tests not finished: stopped"
NO_COMMAND = (
    "No test command: nothing was run (set one in Settings › This project › Checks and git)"
)
NO_TESTS_ROW = "No tests: only documents, slides, diagrams or data changed"
SENT_BACK = "Sent back to fix: {n} of {most} rounds"
# k-canli-016: Until it passes - how far it came, and why the rounds stopped short of a pass.
SENT_BACK_UNTIL = "Sent back to fix: round {n} (until it passes, {first} failing → {now})"
STOPPED_AFTER = "Stopped after round {n}: {why} - you decide (Fix it)"
NO_PROGRESS = "no progress in two rounds"
AT_CEILING = "at most {most} rounds"
TOKEN_LIMIT = "the turn's token limit"
BUDGET = "the project's monthly budget"
STILL_FAILING = "Still failing after {most} fix rounds: you decide (Fix it)"
RECIPE_SPENT = "Still failing after the recipe's fix rounds: you decide (Fix it)"
WAITING = "Not in this run: {name}'s work waits in Ready for you"
RUN_BY = "Tests passed: {command} - run by {who} after the last change"
NOT_CHECKED = "Not checked: After a change is set to Nothing"
# CL-321 Bulgu D: a turn whose only change a command made - no change of it on record.
UNRECORDED = "A command of this turn may have changed files KOLONİ did not record: {command}"
# CL-329 (review): a tracked file changed while KOLONİ's own run went on - said; Put back is the
# user's click (`ProofMixin.put_back_changed`), never KOLONİ's by itself.
CHANGED_DURING = "Changed while KOLONİ's run of {command} went on: {files}"
# ...and why one is not put back for good: changed again, not the project's, a secret file (of
# which KOLONİ keeps no copy: one changed before the run is the user's to put back).
AGAIN = "changed again since KOLONİ's run"
OUTSIDE = "is not in the project"
SECRET_KEPT = "a secret file - KOLONİ keeps no copy of it: put it back yourself"
MOST_COMMAND = 120  # characters of such a command said
MOST_TOUCHED = 5  # files it changed named, then "+N more"
# A file's time against a command's start: what a file system rounds down (FAT: 2 s).
MTIME_SLACK = 2.0
OFF_FOR_CHAT = "Not checked: off for this chat"
# S5c: a recipe's Checks step set to check nothing; its tests set off; its Fix rounds at 0.
RECIPE_OFF = "Not checked: this recipe's Checks step checks nothing"
TESTS_OFF = "Tests not checked: off in this recipe's Checks step"
CHECK_ONLY = (
    "Checked only: this recipe's Checks step sends nothing back to fix - you decide (Fix it)"
)
LAST_RUN = "An agent ran {command} {when} the last change: {how}"
# S2: the tests a turn added or changed; its Orchestrator's reason for none, where it was asked;
# a test it removed.
NEW_TESTS = "New tests: {files}"
NO_NEW_TEST = "No new test: the Orchestrator said “{line}”"
TEST_REMOVED = "Test removed: {path}"


def row(
    kind: str,
    state: str,
    text: str,
    command: str | None = None,
    guessed: bool = False,
    reason: "Reason | None" = None,
) -> Row:
    made: Row = {
        "kind": kind,
        "state": state,
        "text": text,
        "command": command,
        "guessed": guessed,
        "started_at": None,
        "counts": None,
    }
    if reason is not None:
        made["reason"] = reason
    return made


def still_failing(rows: list[Row]) -> bool:
    """Whether a test run of the turn failed that is the turn's own: a failed "tests" row not
    excused as failing before it (N: the review and the live try wait on these alone)."""
    return any(
        one["kind"] == "tests" and one["state"] == "failed" and not one.get("before")
        for one in rows
    )


def clock(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


# What a runner says where it ran no test: unittest's "Ran 0 tests", jest's "No tests found",
# vitest's "No test files found", pytest's "no tests ran" (its exit 5 too).
RAN_NO_TEST = re.compile(
    r"\bRan 0 tests\b|\bNo tests found\b|\bNo test files found\b|"
    r"\bno tests ran\b",
    re.IGNORECASE,
)
SKIPPED = re.compile(r"\b[1-9]\d* skipped\b", re.IGNORECASE)


def _summary(output: str, counts: re.Pattern = ledger.SUMS_UP) -> str | None:
    lines = [line.strip(" =-") for line in output[-4000:].splitlines() if counts.search(line)]
    return lines[-1] if lines else None


def _ran_none(run: TestRun, code: int, output: str) -> bool:
    """pytest's or unittest's exit 5, or a runner's own words that it ran no test - where its
    output counts none that passed or failed."""
    named = run.command.casefold()
    return (code == 5 and ("pytest" in named or "unittest" in named)) or (
        _summary(output) is None and bool(RAN_NO_TEST.search(output[-4000:]))
    )


def _counted(found: "test_found.Counts | None") -> str | None:
    """A runner's counts in words, where its summary is not pytest's own line: "11 passed, 1
    failed, 2 skipped" (of packages, for go's)."""
    if found is None or not found.total:
        return None
    unit = "" if found.unit == "tests" else f" {found.unit}"
    return ", ".join(
        f"{n}{unit} {word}"
        for n, word in zip(found[:3], ("passed", "failed", "skipped"), strict=True)
        if n or word == "passed"
    )


def _skipped_only(output: str, found: "test_found.Counts | None") -> str | None:
    """Where a passing run ran no test but skipped some: its summary; None: not so."""
    if found is not None:
        return _counted(found) if found.skipped and not found.passed + found.failed else None
    return _summary(output, SKIPPED) if _summary(output) is None else None


def _first(*said: str) -> str:
    for text in said:
        if line := next((one.strip() for one in text.splitlines() if one.strip()), ""):
            return line.removeprefix("error: ")
    return "no word of why"


def tests_row(
    run: TestRun,
    code: int | None,
    output: str,
    ended: str | None,
    said: str,
    seconds: int = MAX_TIMEOUT,
) -> Row:
    """A test run as its Checked row: failed is any exit but 0 (pytest's 5, nothing collected,
    aside) or a failure its output counts; never passed without exit code 0. `ended`: its
    record's status (None: none - it never started); `seconds`: the wait it was given. Its
    output is read with its colours off (`commands.plain`: CL-316)."""
    output = plain(output)
    guessed = " (guessed)" if run.guessed else " (from CI)" if run.ci else ""
    found = test_found.counts(output, run.command)

    def made(state: str, text: str) -> Row:
        return {
            **row("tests", state, text, run.command, run.guessed),
            "counts": found._asdict() if found else None,
        }

    if (
        ended in (None, "failed_to_start")
        or code not in (0, None)
        and (finish_tests.did_not_start(code, output))
    ):
        return made("not_run", NOT_STARTED.format(first=_first(said, output)))
    if ended == "timed_out":
        return made(
            "timed_out",
            TIMED_OUT.format(minutes=seconds // 60, command=run.command)
            if seconds >= MAX_TIMEOUT
            else NOT_WAITED.format(clock=clock(seconds), command=run.command),
        )
    if ended != "exited" or code is None:
        return made("not_run", STOPPED)
    counted = bool(ledger.FAILED.search(output[-4000:]))
    if (read := ledger.read_test(run.command)) is not None and read[1] and not counted:
        return made("not_run", NO_VERDICT.format(command=run.command))
    if _ran_none(run, code, output):
        return made("not_run", RAN_NONE.format(command=run.command))
    summary = _summary(output) or _counted(found)
    if code != 0 or counted:
        return made(
            "failed",
            FAILED_ROW.format(
                command=run.command, guessed=guessed, summary=summary or f"exit {code}"
            ),
        )
    if (skipped := _skipped_only(output, found)) is not None:
        return made("not_run", SKIPPED_ONLY.format(command=run.command, summary=skipped))
    return made(
        "passed",
        PASSED_ROW.format(command=run.command, guessed=guessed, summary=summary)
        if summary
        else BY_CODE.format(command=run.command, guessed=guessed),
    )


def checked_text(rows: list[Row]) -> str:
    """The Checked section as text: one line a row, its state's mark first."""
    return "\n".join(ICONS.get(one["state"], "– ") + one["text"] for one in rows)


# --- S6: related tests first, the whole suite in the background; the machine's load ----------

# A whole suite that goes on after the answer (`running`): waiting for another of KOLONİ's runs
# to end (no `started_at`), then running (`started_at` set: the page ticks its clock).
FULL_QUEUED = "Full tests waiting for another test run to end: {command}"
FULL_RUNNING = "Full tests running: {command}"
# ...its run over, waiting on the user's answer on a file it wrote (CL-316: no clock counts then).
FULL_ON_CARD = "Full tests waiting for your answer on a file the tests wrote: {command}"
FULL_HELD = "Full tests not run: the related tests fail"
SUPERSEDED = "Tests not finished: the project changed, and a newer run took their place"
RESTARTED = "Tests not finished: KOLONİ restarted"
# A result that came after the project changed beneath it: it stands for no state of the work.
CHANGED_WHILE = " - the project changed while they ran"

# Settings › The app: KOLONİ's own test runs at once, and the test processes each may start
# (pytest-xdist's `-n auto` reads it). Cautious: this machine once failed under test load.
TEST_RUNS_FLAG, TEST_RUNS_RANGE, TEST_RUNS = "test_runs_at_once", (1, 4), 1
TEST_WORKERS_FLAG, TEST_WORKERS_RANGE, TEST_WORKERS = "test_workers", (1, 16), 2


def related_said(text: str) -> str:
    """A related run's row: "Related tests passed: …" - not to be read as the whole suite's."""
    return f"Related t{text[1:]}" if text.startswith("Tests ") else text


def load_of(session: Session) -> tuple[int, int]:
    """KOLONİ's test runs at once, and the test processes each may start, as Settings › The app
    has them; a value out of its range is held to it, one that is no whole number is the
    default."""

    def read(name: str, low_high: tuple[int, int], default: int) -> int:
        value = session.scalar(select(Flag.value).where(Flag.name == name))
        try:
            return default if value is None else min(low_high[1], max(low_high[0], int(value)))
        except ValueError:
            return default

    return (
        read(TEST_RUNS_FLAG, TEST_RUNS_RANGE, TEST_RUNS),
        read(TEST_WORKERS_FLAG, TEST_WORKERS_RANGE, TEST_WORKERS),
    )


def written_since(
    session: Session, project_id: str, since: datetime
) -> dict[str, list[tuple[datetime, str | None]]]:
    """The project's paths a recorded change wrote after `since` - written there, taken in from a
    copy, or taken back (Undo), by any chat's turn - each with when, and what those changes
    left there (None: no file)."""
    left: dict[str, list[tuple[datetime, str | None]]] = {}
    for change in session.scalars(
        select(FileChange)
        .join(Run, Run.id == FileChange.run_id)
        .join(Conversation, Conversation.id == Run.conversation_id)
        .where(
            Conversation.project_id == project_id,
            FileChange.status.in_(("applied", MERGED, "reverted")),
            or_(FileChange.created_at > since, FileChange.decided_at > since),
        )
    ):
        # (Undo puts back what it replaced - nothing where it made the file: `revert_change`.)
        held = (
            (None if change.kind == "create" else change.before_content or "")
            if (change.status == "reverted")
            else (None if change.kind == "delete" else change.after_content)
        )
        left.setdefault(change.path, []).append((change.decided_at or change.created_at, held))
    return left


def changed_since(
    session: Session, project_id: str, since: datetime, ran: Command | None = None
) -> bool:
    """Whether the project changed after `since` beneath `ran` (a test run of KOLONİ's): a
    recorded change (`written_since`), or a command of any turn in it that may have changed
    files - `_rewritten_after`'s rule, the same as for a pass that stands.
    shortcut: what the user changes outside KOLONİ is not on record; read the files' times if a
    background result is seen to stand for an edit it never ran on."""
    if written_since(session, project_id, since):
        return True
    if ran is None or ran.started_at is None:
        return False
    # (Not KOLONİ's own test runs - another suite of the same turn, say: they change nothing the
    # tests read, and a standing file they write is put back as they end. Nor its read-only looks
    # - the Reviewer's (a read, or the approved test command: decision 6) and S11's diagnosis.
    # S11's fixer, though KOLONİ opened it, writes: its commands count.)
    proofs = select(ToolCall.id).where(ToolCall.provider_call_id.startswith(PROOF_CALL))
    reads = select(ToolCall.id).where(
        or_(
            *(
                ToolCall.provider_call_id.startswith(f"{PROOF_CALL}{kind}_")
                for kind in READ_ONLY_LOOKS
            )
        )
    )
    looks = select(Agent.id).where(Agent.tool_call_id.in_(reads))
    agents: dict[str, set[str]] = {}
    for run_id, agent_id in session.execute(
        select(Command.run_id, Command.agent_id)
        .join(Run, Run.id == Command.run_id)
        .join(Conversation, Conversation.id == Run.conversation_id)
        .where(
            Conversation.project_id == project_id,
            Command.id != ran.id,
            Command.started_at.is_not(None),
            Command.started_at >= since,
            or_(Command.tool_call_id.is_(None), Command.tool_call_id.not_in(proofs)),
            Command.agent_id.not_in(looks),
        )
    ):
        agents.setdefault(run_id, set()).add(agent_id)
    return any(
        _rewritten_after(session, run_id, by, ran, _known_as(session, ran))
        for run_id, by in agents.items()
    )


def settle_running(session: Session) -> None:
    """At start-up: a test run that went on after its turn ended with the process that ran it -
    its row says so, never "running" on (`recover_interrupted`)."""
    for note in session.scalars(
        select(Message).where(Message.role == "checked", Message.content.contains(ICONS["running"]))
    ):
        rows = [
            row("tests", "not_run", RESTARTED, one["command"], one["guessed"])
            if one["state"] == "running"
            else one
            for one in (note.blocks or {}).get("rows", [])
        ]
        note.blocks, note.content = {"rows": rows}, checked_text(rows)
