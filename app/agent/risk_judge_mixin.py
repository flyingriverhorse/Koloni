"""Full auto's judge (0.1.9), its gate: at Full auto, before a command the list does not stop runs,
a small model is asked once whether it is risky (`app.risk_judge`) - since 0.1.10 (K3) before a
delete or a stop by name in the folder the list asked of too - `RiskJudgeMixin`."""

import asyncio
import hashlib
import json
import logging
import os
import re
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, NamedTuple

from sqlalchemy import func, literal_column, select
from sqlalchemy.exc import IntegrityError

from app import away, commands, ledger, project_map, proof, proof_style, raw, risk_judge
from app.agent.cards import _answer
from app.agent.ctx import Ctx
from app.command_runner import _planted
from app.commands import (
    _BLOCKS,
    _INTERPRETER,
    _SHELLS,
    _commands_in,
    _hands_on,
    _in_a_shell,
    _parts,
    _program,
    _words,
    is_exactly,
    is_plain,
    is_wrapped,
    names_secret,
    only_reads,
    rules_here,
    standing_asked,
    with_cwd,
)
from app.db.judge_models import JudgeAllowed
from app.db.models import (
    Command,
    Conversation,
    FileChange,
    Project,
    Provider,
    Run,
    ToolCall,
    project_of,
)
from app.providers import ask_once
from app.roles import LEAD, find_role
from app.team import judge_chosen, judge_pick, would_run
from app.workspace import in_scratch

if TYPE_CHECKING:
    from app.agent import AgentRunner

log = logging.getLogger("app.agent")
CARD = risk_judge.CARD
# Its card where it may not be asked now - no model to ask (0.1.10: fails closed, as Claude Code's
# auto mode does where its classifier cannot answer) or none with room -, or was asked and gave no
# answer to go by: never a run.
NO_MODEL = (
    "no judge model answered - choose a Judge model in Settings › The app › Agents, or give a "
    "model the Fast tier"
)
NO_ROOM = "{name} has no room for it now"
OVER_LIMIT = "the turn is past its token limit"
NOT_ASKED = "it could not be asked: {why}"
# ...and said once a turn in the chat, as such cards may come one after another.
NOT_ASKED_LINE = (
    "Full auto's judge could not be asked this turn: {why}. Each command it would look at asks you."
)
CHANGED = "the program it runs changed while it was looked at"
LATE = "it did not answer in time"
UNREAD = "its answer could not be read"
FAILED = "it could not be asked"
NOT_LOOKED = "it could not look at this command"
NO_REASON = risk_judge.NO_REASON
# Said once a turn where the judge's refusals reach `risk_judge.refusals`' limits: the rest of the
# turn's risky commands are cards.
CAPPED = "Full auto's judge refused {count} this turn; each risky one asks you now."

# An option word of an interpreter's after which the line holds its code itself (`python -c`,
# `node -e`, `-p`, `-r`): no file of its own runs (`python -m x` is read as its module's file). A
# shell's: a POSIX shell's cluster with c in it (`bash -c`, `bash -lc`), PowerShell's `-Command` /
# `-EncodedCommand` cut short as it takes them, cmd's `/c` `/k` - `bash -e x.sh` runs x.sh.
_INLINE = re.compile(r"-(?:c|e|p|r|-eval|-print)")
_POSIX_INLINE = re.compile(r"-[a-zA-Z]*c[a-zA-Z]*")
_POWERSHELL_INLINE = re.compile(r"(?i)-c|-co\w*|-en\w*|-ec")
_ENCODED = re.compile(r"(?i)-en\w*|-ec")
_FILE = re.compile(r"(?i)-f(?:i(?:le?)?)?")
_PYTHON = re.compile(r"python[\d.]*w?|pyw?")
# Their options that take a value: the word after one is no script.
_VALUED = frozenset(
    {"-X", "-W", "--require", "--import", "--loader", *("-executionpolicy", "-ep", "-ex")}
    | {"-windowstyle", "-version", "-workingdirectory", "-wd", "-configurationname", "-o"}
    | {"-settingsfile", "-psconsolefile", "-configurationfile", "-inputformat", "-outputformat"}
    | {"-custompipename"}
)
# The options of a Python's, a Node's or a POSIX shell's that load no code but the file it is
# handed: with only these (and any of PowerShell's or cmd's but their code) the file found is the
# whole program it runs (`_Files.exact`); any other (`node --require x`, `ruby -I x`, `bash
# --rcfile x`) may load more, and nothing is kept for the line.
_PYTHON_PLAIN = re.compile(r"-[uBOEsSIPqbdvi]+|-OO|-bb|-[XW]\S*")
# Python's options that keep a PYTHONPATH it is given out (-I, -E), alone or in a bundle.
_PYTHON_ISOLATED = re.compile(r"-[uBOEsSIPqbdvi]*[IE][uBOEsSIPqbdvi]*")
_NODE_PLAIN = frozenset({"--no-warnings", "--enable-source-maps", "--trace-warnings"})
# PowerShell's, as it takes them cut short (`-nop`, `-ep`): any other (`-SettingsFile`,
# `-PSConsoleFile`) may load more.
_POWERSHELL_PLAIN = frozenset(
    {"-noprofile", "-nop", "-noninteractive", "-noni", "-nologo", "-executionpolicy", "-ep"}
    | {"-ex", "-exec", "-windowstyle"}
)
# Interpreters that load the folder's own settings or code before the file they are handed
# (bun's bunfig.toml preload, R's .Rprofile): the file is never all they run.
_LOADS_THE_FOLDERS = frozenset({"bun", "rscript"})
_POSIX_PLAIN = re.compile(r"-[abd-zA-Z]+|-o")
# What a name with no ending may be, as its runner looks: Node's, a Python's folder, and a
# program by its path on Windows (PowerShell's `.\x` runs x.ps1, cmd's x.cmd).
_NODE_ENDINGS = ("", ".js", ".mjs", ".cjs", "/index.js")
_PYTHON_ENDINGS = ("", "/__main__.py")
_RUN_ENDINGS = ("", ".ps1", ".cmd", ".bat")
# A bare name with one of these endings is a script of the folder's, whatever runs it.
_SCRIPT_ENDINGS = frozenset({".ps1", ".cmd", ".bat", ".sh", ".py", ".js", ".mjs", ".cjs", ".ts"})
_MAKEFILES = ["GNUmakefile", "makefile", "Makefile"]
# The programs a line keeps a key for by its words alone, with no file of the folder's hashed:
# one plain command of one of these - and, for those told a file to read their settings or
# commands from (`curl -K x`, `wget -i x`), no word of it naming a path in the folder
# (`_READS_NAMED`).
# shortcut: deliberately small - a program goes in only if it never runs the project's code or
# settings (no hooks, plugins, build, pager, ssh command or config it executes: not git, whose
# `-c core.pager=…`, hooks, `submodule foreach` and filters run what they are told, nor gh, which
# runs git); grow it one measured program at a time, else a line with no file hashed is judged
# at every run (git's ordinary lines are never judged: `risk_judge.ordinary`).
RUNS_NO_LOCAL_CODE = frozenset(
    {"curl", "wget", "rm", "rmdir", "del", "mkdir", "md", "cp", "copy", "mv", "move", "ren"}
    | {"chmod", "touch"}
)
_READS_NAMED = frozenset({"curl", "wget"})


class _Files(NamedTuple):
    """The files a line may run as its program, in the order its runner looks, and whether one
    found is all the line runs *by name* (`exact`: no option that loads more, no shell's code
    around it, no settings of the folder's its runner loads first). What that program imports in
    turn - even a file of the folder's beside it shadowing a standard module (`json.py` beside
    `x.py`) - is not hashed: the design's known limit "a program that imports another file"."""

    names: list[str]
    exact: bool


_NONE = _Files([], False)


def _endings(name: str, endings: tuple[str, ...]) -> list[str]:
    """`name` and, where it has no ending of its own, `name` with each of `endings`."""
    if PurePosixPath(name.replace("\\", "/")).suffix:
        return [name]
    return [name + one for one in endings]


def _pathlike(word: str) -> bool:
    """Whether a program word names a file of the folder: by its path, or a script's ending."""
    suffix = PurePosixPath(word.replace("\\", "/")).suffix.lower()
    return bool(word) and (bool(re.search(r"[\\/]", word)) or suffix in _SCRIPT_ENDINGS)


def _first_of(code: str) -> _Files:
    """A shell's code (`bash -lc ./x.sh`, `powershell -c "& .\\x.ps1"`, `cmd /c .\\x`): the file
    its first word names, where it is one of the folder's - shown, never the whole of it."""
    words = [word.strip("'\"") for word in _words(code.strip("'\""))]
    first = (words[1:2] if words[:1] in (["&"], ["."]) else words[:1]) or [""]
    return _Files(_endings(first[0], _RUN_ENDINGS), False) if _pathlike(first[0]) else _NONE


def _loads_nothing(program: str, word: str) -> bool:
    """Whether an option of `program`'s loads no code of its own (`_PYTHON_PLAIN` and the rest)."""
    if _PYTHON.fullmatch(program):
        return bool(_PYTHON_PLAIN.fullmatch(word))
    if program.startswith(("node", "bun", "deno")):
        return word in _NODE_PLAIN
    if program in ("powershell", "pwsh"):
        return word.lower() in _POWERSHELL_PLAIN
    if program == "cmd":
        return True
    return program in _SHELLS and bool(_POSIX_PLAIN.fullmatch(word))


def _inline(program: str, word: str, interpreter: bool) -> bool:
    """Whether `word` is an option after which the line holds its code (`_INLINE` and the rest)."""
    if interpreter:
        return bool(_INLINE.fullmatch(word))
    if program in ("powershell", "pwsh"):
        return bool(_POWERSHELL_INLINE.fullmatch(word))
    if program == "cmd":
        return word.lower() in ("/c", "/k")
    return bool(_POSIX_INLINE.fullmatch(word))


def _script(words: list[str]) -> _Files:
    """An interpreter's or a shell's line (`_files`): the script it is handed - its first word
    that is no option, or the value of PowerShell's `-File` -, `python -m x`'s module (x.py,
    x/__main__.py), Node's name with no ending; a shell's code by its first word (`_first_of`;
    encoded: none known); _NONE where an interpreter's line holds its code (`_INLINE`)."""
    program = _program(words[0])
    interpreter = bool(_INTERPRETER.fullmatch(program))
    python, node = bool(_PYTHON.fullmatch(program)), program.startswith(("node", "bun", "deno"))
    exact, rest = program not in _LOADS_THE_FOLDERS, iter(words[1:])
    for word in rest:
        if python and word.startswith("-m"):
            module = (word[2:] or next(rest, "")).replace(".", "/")
            return _Files([f"{module}.py", f"{module}/__main__.py"] if module else [], exact)
        if _inline(program, word, interpreter):
            return _NONE if interpreter or _ENCODED.fullmatch(word) else _first_of(next(rest, ""))
        if program in ("powershell", "pwsh") and _FILE.fullmatch(word):
            return _Files([next(rest, "")], exact)
        if word.startswith("-") or program == "cmd" and word.startswith("/"):
            exact = exact and _loads_nothing(program, word)
            if word in _VALUED or word.lower() in _VALUED:
                next(rest, None)
            continue
        ending = _NODE_ENDINGS if node else _PYTHON_ENDINGS if python else ("",)
        return _Files(_endings(word, ending), exact)
    return _NONE


def _plain_tool(words: list[str]) -> _Files:
    """make's, npm's and docker build's line in its plain form alone, whose file is all it runs
    for the line's key: `make [target...]` / `make -f F [target...]` (F, else GNUmakefile,
    makefile, Makefile), `npm run <script>` / `npm test` (the folder's own package.json - npm
    goes up from a folder with none), `docker build [-f F] [-t T] .` (F, else ./Dockerfile). Any
    other option or form - another folder or project (`-C`, `--prefix`, `-w`, another context),
    `npx`, `npm exec`, `yarn node` - is _NONE: its file is not the one it runs.
    shortcut: what a makefile's recipe, a package script or a Dockerfile runs besides is not
    hashed (the judge's known limit "a program that imports another file")."""
    program, rest = _program(words[0]), words[1:]
    if program == "make":
        named = rest[1:2] if rest[:1] == ["-f"] else []
        targets = rest[2:] if named else rest
        # (`make SHELL=./x`, `CC=./x`: a variable set on the line runs what it names - none)
        if all(not word.startswith("-") and "=" not in word for word in targets):
            return _Files(named or list(_MAKEFILES), True)
    if program == "npm" and (rest in (["test"], ["t"]) or len(rest) == 2 and rest[0] == "run"):
        return _Files(["package.json"], not rest[-1].startswith("-"))
    if program == "docker" and rest[:1] == ["build"] and rest[-1:] == ["."]:
        options = dict(zip(rest[1:-1:2], rest[2:-1:2], strict=False))
        if len(rest) % 2 == 0 and set(options) <= {"-f", "-t", "--file", "--tag"}:
            return _Files([options.get("-f") or options.get("--file") or "Dockerfile"], True)
    return _NONE


def _files(words: list[str]) -> _Files:
    """The files a line may run as its program, and whether one found is all of it: an
    interpreter's or a shell's (`_script`), a program by its path (`.\\x`, `./x.sh`) or a
    script's ending (`x.ps1`), make's, npm's or docker build's in its plain form (`_plain_tool`);
    _NONE for anything else."""
    program = _program(words[0])
    if _INTERPRETER.fullmatch(program) or program in _SHELLS:
        return _script(words)
    if _pathlike(words[0]):
        return _Files(_endings(words[0], _RUN_ENDINGS), True)
    return _plain_tool(words)


def _sees_python_path(command: str, in_copy: bool) -> bool:
    """Whether a Python's line imports what a PYTHONPATH it is given holds before its script: a
    working copy's commands get the copy and its src first (`host.copy_python_path`), and KOLONİ's
    own environment may set one - there a `sitecustomize.py` or `usercustomize.py` an agent wrote
    runs first, so the script found is not all the line runs. Not with -I or -E (alone or in a
    bundle, `-IB`) before what it runs; an option it cannot read leaves it seeing one."""
    words = [word.strip("'\"") for word in _words(command)]
    words = words[1:] if words[:1] in (["&"], ["."]) else words  # (PowerShell's call)
    if not words or not _PYTHON.fullmatch(_program(words[0])):
        return False
    if not (in_copy or os.environ.get("PYTHONPATH")):
        return False
    for word in words[1:]:
        if not word.startswith("-") or word.startswith(("-m", "-c")):
            break
        if _PYTHON_ISOLATED.fullmatch(word):
            return False
    return True


def _named_file(root: Path, command: str, cwd: str) -> tuple[Path | None, bool]:
    """The file `command` (run in `cwd` of `root`: the project, or a copy of it) runs as its
    program (`_files`: `node x.js`, `node x`, `python -m x`, `./x.sh`, `bash x.sh`, `powershell
    -File x.ps1`, `.\\x`, the first word of a shell's code, make's Makefile, a Dockerfile, a
    package.json), its full path - the first that is a file in `root` -, and whether it is all
    of what the line runs (`_Files.exact`). (None, False): none found."""
    words = [word.strip("'\"") for word in _words(command)]
    words = words[1:] if words[:1] in (["&"], ["."]) else words  # (PowerShell's call)
    names, exact = _files(words) if words else _NONE
    home = root.resolve()
    for name in names:
        try:
            path = (root / cwd / name).resolve()
            # (by its own spelling: on macOS's case-blind disk `makefile` would find Makefile)
            if (
                name
                and path.is_relative_to(home)
                and path.is_file()
                and path.name in os.listdir(path.parent)
            ):
                # (a package's __main__.py: its __init__.py runs first - `python -m pkg`)
                return path, exact and path.name != "__main__.py"
        except (OSError, ValueError):
            continue
    return None, False


# What moves a line's later parts to another folder (`named_files`), and the most parts it reads.
_CDS = frozenset({"cd", "chdir", "pushd", "set-location", "sl"})
MOST_PARTS = 32
# L-1: what runs code no word of its part names as a file - an expression (`iex`), a package runner
# (`npx tsx x.ts`), find's -exec, a test runner (the tests an agent wrote) - and, `_runs_unnamed`,
# a shell or an interpreter given no script (`sh < x.sh`, `cat x.sh | sh`, `python -c`).
_RUNS_UNNAMED = frozenset(
    {"iex", "invoke-expression", "npx", "pnpx", "bunx", "uvx", "pytest", "py.test", "vitest"}
    | {"jest", "mocha", "tox", "nox"}
)
_EXECS = frozenset({"-exec", "-execdir", "-ok", "-okdir"})
_RUNS_TESTS = re.compile(
    r"(?i)\s-m\s+(?:pytest|unittest)\b|^(?:npm|pnpm|yarn|bun)\s+(?:(?:run\s+)?test|exec|dlx|x)\b"
    r"|^(?:go|cargo)\s+test\b|^playwright\s+test\b"
)


def _runs_unnamed(words: list[str]) -> bool:
    """Whether a part runs code no word of it names as a file (L-1): its files are not known."""
    program = _program(words[0])
    if program in _RUNS_UNNAMED or _EXECS & {word.lower() for word in words}:
        return True
    if _RUNS_TESTS.search(" ".join([program, *words[1:]])):
        return True
    if _INTERPRETER.fullmatch(program) and not _files(words).names:
        return True  # (its code on its line or on stdin: `python -c`, `node -`)
    # (a shell's code on its line is read past it - `_commands_in`; on stdin, or a redirection)
    return bool(_INTERPRETER.fullmatch(program) or program in _SHELLS) and (
        any(word.startswith("<") for word in words[1:])
        or all(word.startswith(("-", "/")) for word in words[1:])
    )


def named_files(root: Path, command: str, cwd: str) -> list[Path] | None:
    """Every file `command` runs as a program (`_named_file`), not its first alone (F411 P1): each
    part of a chain, a pipe, a group, a shell's or a wrapper's (`_commands_in`, cut as harm is),
    looked for in `cwd` and in each folder a `cd` of the line goes to. None - fails closed: a part
    not read (`commands.UNREAD`), one that runs code no word of it names (`_runs_unnamed`, L-1), a
    `cd` not plainly to a folder, or past MOST_PARTS parts."""
    parts = [words for words in _commands_in(command, at=_BLOCKS) if any(words)]
    # (and as written, before a shell's or a wrapper's own words are read past: `cat x.sh | sh`)
    written = [words for words in _parts(command, _BLOCKS) if any(words)]
    if len(parts) > MOST_PARTS or [commands.UNREAD] in parts:
        return None
    if any(map(_runs_unnamed, [*parts, *written])):
        return None
    places = [cwd]
    for words in (words for words in parts if _program(words[0]) in _CDS):
        if len(words) != 2 or words[1] == "-" or re.search(r"[$%~`]", words[1]):
            return None
        places += [str(Path(places[-1], words[1])), str(Path(cwd, words[1]))]
    found = []
    for words in (words for words in parts if _program(words[0]) not in _CDS):
        line = " ".join(f'"{word}"' if re.search(r"\s", word) else word for word in words)
        for place in dict.fromkeys(places):
            if (path := _named_file(root, line, place)[0]) is not None and path not in found:
                found.append(path)
    return found


def _no_local_code(root: Path, command: str, cwd: str) -> bool:
    """Whether a line runs none of the folder's code, so its words alone may be its key: one
    plain command (`is_plain`, not wrapped nor in a shell), its program bare and one of
    `RUNS_NO_LOCAL_CODE` - and `curl` / `wget` (`_READS_NAMED`: they read what they are told)
    only as `_only_fetches` reads them. `root` and `cwd`: where it runs (no word is looked up
    there now - fails closed)."""
    del root, cwd
    if not is_plain(command) or is_wrapped(command) or _in_a_shell(command):
        return False
    raw = _words(command.strip())
    program = _program(raw[0].strip("'\"")) if raw else ""
    if not raw or _pathlike(raw[0].strip("'\"")) or program not in RUNS_NO_LOCAL_CODE:
        return False
    return program not in _READS_NAMED or _only_fetches(program, raw[1:])


# `curl` / `wget` with none of the folder's code (fails closed, review round 5): each word after the
# program a plain http(s) address or one of these value-less flags, matched whole - no quote taken
# off - or the one output target (`-o NAME`; wget's `-O NAME`) to a plain file name of the folder it
# runs in. Any other flag, a value glued on, `-K`, `--config`, `-T`, `-d`, `-i`, `-e`, `@file`, a
# quote, `file://`: not so.
_FETCH_FLAGS = {
    "curl": frozenset(
        {"-s", "-S", "-f", "-L", "-I", "-v", "-sS", "-fsS", "-fsSL", "-sSL", "-fL"}
        | {"--silent", "--show-error", "--fail", "--location", "--head", "--verbose"}
        | {"--compressed"}
    ),
    "wget": frozenset(
        {"-q", "-nv", "--quiet", "--no-verbose", "-S", "--server-response", "--spider"}
    ),
}
_FETCH_OUT = {"curl": "-o", "wget": "-O"}
_PLAIN_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-]*")


def _only_fetches(program: str, words: list[str]) -> bool:
    """Whether `curl` / `wget`'s words (as written: quotes kept) are each an http(s) address, a
    flag of `_FETCH_FLAGS`, or its output option followed by a plain file name."""
    at = 0
    while at < len(words):
        word = words[at]
        if word == _FETCH_OUT[program] and at + 1 < len(words):
            if not _PLAIN_NAME.fullmatch(words[at + 1]):
                return False
            at += 2
            continue
        if word not in _FETCH_FLAGS[program] and not word.startswith(("http://", "https://")):
            return False
        at += 1
    return True


def _agents(factory, cid: str, root: Path, path: Path, scratch: bool = True) -> bool:
    """Whether `path` (in `root`) is as an agent wrote it - its write on record, of any turn of
    the project's, still stands (`proof_style.still_written`) - or, with `scratch`, in the agents'
    scratch, theirs whoever wrote it there (`workspace.in_scratch`)."""
    rel = path.relative_to(root.resolve()).as_posix()
    if scratch and in_scratch(rel):
        return True
    with factory() as session:
        found = session.execute(
            select(FileChange.path, FileChange.after_sha)
            .join(Run, Run.id == FileChange.run_id)
            .join(Conversation, Conversation.id == Run.conversation_id)
            .where(
                Conversation.project_id
                == select(Conversation.project_id).where(Conversation.id == cid).scalar_subquery(),
                FileChange.status.in_((*ledger.KEPT, proof.MERGED)),
                func.lower(FileChange.path) == rel.lower(),
            )
            .order_by(FileChange.created_at, literal_column("file_changes.rowid"))
        ).all()
    newest = dict(found)  # (the last write of each spelling)
    return bool(proof_style.still_written(root, newest.items()))


def planted_program(factory, cid: str, root: Path, command: str, cwd: str) -> Path | None:
    """The file `command` runs by its name (`_named_file`) where an agent wrote it (`_agents`):
    its full path. None: no such file, one out of `root`, or the user's own (none on record, or
    changed since). Blocking: off the event loop.
    shortcut: by the line's first file alone - one it imports, or a tool an agent changed but
    did not write, is not seen (the judge's known limits)."""
    path = _named_file(root, command, cwd)[0]
    return path if path is not None and _agents(factory, cid, root, path) else None


def _digest(path: Path) -> str:
    """The digest of all of a file ("" where it cannot be read: gone, say)."""
    try:
        with path.open("rb") as file:
            return hashlib.file_digest(file, "sha256").hexdigest()
    except OSError:
        return ""


def _program_read(path: Path, root: Path) -> tuple[tuple[str, str, int], str]:
    """A program a line runs: its path from `root`, the text of its first PROGRAM_BYTES and the
    bytes left - and the digest of all of it, which the line's key holds (a change past what is
    shown is a change too, and so is one no write on record made).
    shortcut: the whole file hashed at each judged command; cap it if a big one slows a turn."""
    with path.open("rb") as file:
        head = file.read(risk_judge.PROGRAM_BYTES)
    left = max(0, path.stat().st_size - len(head))
    rel = path.relative_to(root.resolve()).as_posix()
    return (rel, head.decode("utf-8", "replace"), left), _digest(path)


# Tools whose `run` builds the folder's code and runs it (`cargo run`, `go run .`, `dotnet run`):
# what an agent wrote there is no one file KOLONİ finds, so a rule never lets such a line by.
_BUILDS_AND_RUNS = commands._RUNS_AFTER_DASHES | {("go", "run")}


def _builds_and_runs(command: str) -> bool:
    """Whether a line is one of `_BUILDS_AND_RUNS`'s, by its program and first word."""
    words = [word.strip("'\"") for word in _words(command.strip())]
    return len(words) > 1 and (_program(words[0]), words[1].lower()) in _BUILDS_AND_RUNS


def _refused(judged: object) -> bool:
    """Whether a command's record of the judge is its refusal (Refuse and go on)."""
    return (
        isinstance(judged, dict)
        and judged.get("kind") == "risk"
        and judged.get("verdict") == "refuse"
    )


class _Seen(NamedTuple):
    """What of a line besides it the judge goes by: where it runs (`root`, `cwd`), the file it
    runs by its name (`_named_file`; None: none found, or its folder no fact), that program as
    shown where an agent wrote it (`_risk_line`), its digest ("": none), and what the same agent
    did before it in the turn (`_risk_earlier`)."""

    root: Path
    cwd: str | None  # (None: no fact - `_risk_judged`'s `known`)
    path: Path | None
    program: tuple[str, str | None, int] | None
    digest: str
    earlier: list[str]


class RiskJudgeMixin:
    async def _risk_judged(
        self: "AgentRunner",
        ctx: Ctx,
        command: str,
        cwd: str | None,
        root: Path,
        found: tuple[str, dict | None],
        *,
        exempt: bool,
        known: bool = True,
        shell: str | None = None,
    ) -> tuple[str, dict | None]:
        """Full auto's judge: why `command` (run in `cwd` of `root`, the project or the copy it
        works in) waits for the user on a card though KOLONİ found no reason of its own - asked
        only where none was found, nor any by the check of the user's words (`found`, their
        reason and record: given back as they are). ("", record) - it runs, its record "fine";
        ("", None) - not judged; (`CARD`, record "risky") - its card; ("", record "refuse") - not
        run, its agent told so (`risk_judge.REFUSED`).
        Not judged: not a watched Full auto turn nor a job's at Full auto, a
        line the user lets run or KOLONİ asks of anyway (`exempt`: a skill's script they allowed,
        a disposable delete, a reason in a working copy, a role that runs no command),
        the project's switch off (read at each command), one that only reads (and an ordinary
        line: git's at the root alone, `risk_judge.git_below`), their own test
        command (but where an agent wrote the program it runs), one asked at every level anyway
        (a secret, a file that steers later turns), an ordinary line (`risk_judge.ordinary`, what
        it runs not an agent's: `_planted`, W7), one a narrow "Always run" rule of the chat covers
        in a turn the user watches (0.1.10, `_risk_line`: never a broad one, `risk_judge.
        broad_rule`, nor one that runs a program an agent wrote), one they said Run to on its card
        this turn - or not to ask about again here (`JudgeAllowed`). A card unasked:
        `risk_judge.risky_unasked`; one with no model to ask, `_risk_asked`.
        `known`: False where `cwd` is no fact (a CLI's folder not known, or its model's word):
        then no program is read. Nothing is kept for such a line - neither its verdict, nor a Run
        on its card -, nor for one but where the file it runs was found, hashed, and is all it
        runs (`_named_file`), or it runs none of the folder's code (`_no_local_code`): what it
        runs may change unseen, the same words in another folder be another line. `shell`: the
        one it runs in where that is KOLONİ's own PowerShell (a `\\` there is no escape: K3).
        In a watched turn its own "risky" may be refused instead (`_risk_refuses`).
        Whatever goes wrong in it but a Stop is its card, never a run nor a refusal.
        K3 (0.1.10, as Claude Code's auto mode): the list's own card that is the judge's to decide
        (`_risk_takes`: a delete or a stop by name in the folder, a plain line, a watched turn) is
        put to it too - its "risky" kept for the turn, never its "fine" nor a Run on its card -, and
        runs only on the model's own "fine"; any other answer but its "risky" (no verdict, not
        asked, the switch off) gives the card back."""
        if exempt:
            return found
        try:
            # (the list's own card stays one where the look at it fails: below)
            takes = self._risk_takes(ctx, command, cwd, root, found, known, shell)
            if found != ("", None) and not takes:
                return found
            watched = self._full_auto(ctx)
            if not (watched or self._away_full_auto(ctx)):
                return found if takes else ("", None)  # (a level changed meanwhile: its card)
            judged = await self._risk_judging(ctx, command, cwd, root, known, takes)
            if takes and not (judged[1] or {}).get("looked"):
                return found
            # (R2: what it names looked at again once the judge said fine - a link may have been
            # made meanwhile; KOLONİ's own command is looked at once more as it runs: `_gate_open`)
            line = with_cwd(command, cwd)
            moved = takes and not judged[0]
            if moved and not await asyncio.to_thread(risk_judge.on_disk, root, line):
                return found
            return self._risk_refuses(ctx, *judged) if watched else judged
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("run %s: Full auto's judge failed", ctx.run_id, exc_info=True)
            return found if found != ("", None) else (CARD.format(why=NOT_LOOKED), None)

    def _risk_takes(
        self: "AgentRunner",
        ctx: Ctx,
        command: str,
        cwd: str | None,
        root: Path,
        found: tuple[str, dict | None],
        known: bool,
        shell: str | None = None,
    ) -> bool:
        """K3: whether the list's own card (`found`: its reason, and no record of the check of the
        user's words - its run runs, its refusal refuses and its ask, a condition of theirs or
        "ask me first", keeps the card) is Full auto's judge's to decide: each harm of the line
        one it takes (`risk_judge.judges`), where it runs a fact (`known`), in a turn the user
        watches at Full auto - not a job while they are away, a To-do task's, a side of a
        comparison, nor a turn of the chat they went away from (`away.gone_from`) -, and what it
        names on the disk where it is written (`risk_judge.on_disk`, under `root`). Ask,
        Auto-edit and every turn nobody watches keep the list as it is."""
        reason, record = found
        if not (
            reason
            and known
            and record is None
            and ctx.run_id not in self._todo_turns
            and ctx.run_id not in self._sides
            and risk_judge.judges(with_cwd(command, cwd), shell)
            and self._full_auto(ctx)
            and risk_judge.on_disk(root, with_cwd(command, cwd))
        ):
            return False
        with self._factory() as session:
            return away.gone_from(session, ctx.cid) is None

    def _risk_line(
        self: "AgentRunner",
        ctx: Ctx,
        command: str,
        cwd: str,
        root: Path,
        known: bool,
        ruled: bool = False,
    ) -> tuple[bool, Path | None, tuple[str, str | None, int] | None, str, bool]:
        """Whether a line is let by unjudged: ordinary (`risk_judge.ordinary`) or covered by a
        narrow rule (`ruled`), nothing it runs an agent's (`_planted`; a ruled line's program not
        an agent's either: `_agents`); the
        file it runs as its program (`_named_file`, where `known`); that program as the judge is
        shown it where an agent wrote it (`_agents`) - its text only where a write of an agent's
        on record made it, never one in the scratch it did not (0.1.10: a command's output, a
        fetched page; text None) -; its digest whoever wrote it ("": no file found); and whether
        that file is all the line runs (`_Files.exact`). Blocking."""
        npm = [_program(word) for word in _words(command.strip())[:1]] == ["npm"]  # (npm.cmd)
        # (git in a folder below the root: a repository shaped there sets what it runs)
        below = risk_judge.git_below(command, cwd)
        ordinary = risk_judge.ordinary(command, npm_run=True) and not below
        plain = (
            (ordinary or ruled)
            and _planted(self._factory, ctx.cid, root, command, cwd) is None
            # W7: what `npm test` and `npm run x` run is package.json's - an agent's, where one of
            # its writes of one (or of a lock, a runner's setting) still stands: as npx's reads
            and not (npm and _planted(self._factory, ctx.cid, root, "npx -", cwd))
        )
        path, exact = (
            (None, False) if plain and ordinary or not known else _named_file(root, command, cwd)
        )
        if path is None:
            # (a ruled interpreter's or runner's line whose file is not found - `uv run python
            # x.py`, `npx x` -, or a tool's run that builds the folder's code - `cargo run`, `go
            # run .` - is judged: what it runs is not known. shortcut: what a found file runs in
            # turn - a Makefile recipe's script, a package script - is not looked at)
            unknown = ruled and not ordinary and (_hands_on(command) or _builds_and_runs(command))
            return plain and not unknown, None, None, "", False
        shown, digest = _program_read(path, root)
        written = _agents(self._factory, ctx.cid, root, path, scratch=False)
        if not (written or in_scratch(shown[0])):
            return plain, path, None, digest, exact
        # (a ruled line that runs an agent's program is judged: no rule covers what an agent wrote)
        return False, path, shown if written else (shown[0], None, 0), digest, exact

    async def _risk_judging(
        self: "AgentRunner",
        ctx: Ctx,
        command: str,
        cwd: str | None,
        root: Path,
        known: bool,
        takes: bool = False,
    ) -> tuple[str, dict | None]:
        """`_risk_judged`'s work, which may raise. `takes`: the list's card put to the judge (K3) -
        no Run on its card nor "don't ask again" is kept for its line, nor its "fine" (what the
        turn did before it changes); its "risky" is, as any line's: not asked again and again."""
        line = with_cwd(command, cwd)
        with self._factory() as session:
            conversation = session.get_one(Conversation, ctx.cid)
            project = project_of(session, conversation)
            if (
                project is None
                or not project.full_auto_judge
                or (only_reads(command) and not risk_judge.git_below(command, cwd))
                or names_secret(line)
                or standing_asked(line, False)
            ):
                return "", None
            # (decision 6, 0.1.10: a narrow "Always run" rule lets a line by as Claude Code's auto
            # mode does - in a turn the user watches, its folder known; a broad one never)
            narrow = [
                rule.prefix
                for rule in session.scalars(rules_here(conversation))
                if not risk_judge.broad_rule(rule.prefix)
            ]
            # (the review of K1: only its very line - one word more and it is another task, its
            # program's options or a file it is told to load -, at the project's root - the same
            # words in another folder run another file -, in a turn the user watches: not a job
            # while away, nor a To-do task's, which may run with nobody there)
            ruled = (
                known
                and (cwd or ".") == "."
                and ctx.run_id not in self._away_jobs
                and ctx.run_id not in self._todo_turns
                and any(is_exactly(command, one) for one in narrow)
            )
            project_id = project.id
            own = project_map.own_test(project.test_commands, command, cwd)
            earlier = self._risk_earlier(session, ctx)
            # (anywhere but the project itself - a working copy, a branch's worktree - is a copy)
            in_copy = root.resolve() != Path(project.root_path).resolve()
        plain, path, program, digest, exact = await asyncio.to_thread(
            self._risk_line, ctx, command, cwd or ".", root, known, ruled
        )
        exact = exact and not _sees_python_path(command, in_copy)
        # (the user's own test command is theirs - but not where it runs a program an agent wrote)
        if plain or own and program is None:
            return "", None
        # (fails closed: a key - its verdict kept for the turn, a Run on its card, "don't ask again
        # here" - only where all it runs is known as it is: one plain command, the file found,
        # hashed, all of it - never a chain, pipe, redirection or substitution after it (F408 J1:
        # `python k.py && python e.py` was kept on k.py) -, or it runs none of the folder's code;
        # else what it runs may change unseen. A shell handed a script file is kept as `python
        # x.py` is; a shell's code never is: `_named_file`'s exact)
        one = is_plain(command) and not is_wrapped(command)
        hashed = bool(digest) and exact and one
        kept = known and (hashed or _no_local_code(root, command, cwd or "."))
        # (K3: a moved line's "risky" is kept for the turn by its words alone - a refusal kept
        # loosens nothing -, its "fine" never: `_risk_asked`)
        key = (
            # (a moved line's by its words, spaced as they are read: `rm  -rf src` is the line
            # refused before - the review of K3)
            (
                " ".join(_words(command.strip())) if takes else command.strip(),
                cwd or "",
                digest if hashed else "",
                str(root),
            )
            if kept or takes
            else None
        )
        if (
            key
            and not takes
            and (
                self._risk_cache.get(ctx.run_id, {}).get(key) == "approved"
                or self._risk_allowed(project_id, key)
            )
        ):
            return "", None
        # ("program", "root": the line's key, for `_risk_approved` - "program" None: none;
        # "looked": False until the model's verdict is had - no fields of `schemas.Judged`)
        record: dict = {"kind": "risk", "verdict": "risky", "why": "", "model": "", "looked": False}
        record |= {"program": digest if key and not takes else None, "root": str(root)}
        if why := risk_judge.risky_unasked(command, program[1] if program else None, earlier):
            return CARD.format(why=why), {**record, "why": why}
        seen = _Seen(root, (cwd or ".") if known else None, path, program, digest, earlier)
        return await self._risk_asked(ctx, command, cwd, seen, key, record, takes)

    @staticmethod
    def _risk_earlier(session, ctx: Ctx) -> list[str]:
        """What the same agent did before in the turn (0.1.10, as Claude Code's auto mode's
        classifier reads it): its tool calls that ended and were not refused nor turned down - a
        command, a file written or read, a page opened, by its name and arguments
        (`risk_judge.action`), never what it gave back -, at most `EARLIER`, oldest first, each's
        first `EARLIER_READ` characters masked (`raw.hidden`)."""
        done = session.execute(
            select(ToolCall.name, func.substr(ToolCall.arguments, 1, risk_judge.EARLIER_READ))
            .where(
                ToolCall.run_id == ctx.run_id,
                ToolCall.agent_id == ctx.agent_id,
                ToolCall.status.in_(("succeeded", "failed")),
            )
            .order_by(literal_column("tool_calls.rowid").desc())
            .limit(risk_judge.EARLIER)
        ).all()
        return [raw.hidden(risk_judge.action(*one)) for one in reversed(done)]

    def _risk_allowed(self: "AgentRunner", project_id: str, key: tuple[str, ...]) -> bool:
        """Whether the user said on a judge's card not to ask about this line again here: its
        command, folder and program digest (in any copy of the project)."""
        command, cwd, digest = key[:3]
        with self._factory() as session:
            found = session.scalar(
                select(JudgeAllowed.id).where(
                    JudgeAllowed.project_id == project_id,
                    JudgeAllowed.command == command,
                    JudgeAllowed.cwd == cwd,
                    JudgeAllowed.program_sha == digest,
                )
            )
        return found is not None

    def _risk_refuses(
        self: "AgentRunner", ctx: Ctx, why: str, record: dict | None
    ) -> tuple[str, dict | None]:
        """The judge's own "risky" (its model looked at the line: `looked`), where the project
        refuses such a one (`Project.judge_risky`, read at each command): no card, its record's
        verdict "refuse" - the command is not run and its agent is told so. Any other card stays
        one - KOLONİ's own before it was asked, or one the model gave no verdict for (fails
        closed: the user decides) -, and so does each once the turn's refusals, by all its agents,
        reached `risk_judge.refusals`' limits - 3 in a row (a command that started ends a row), 20
        in all - read from the turn's records (said once in the chat: `CAPPED`). The turn's kept
        verdict stays "risky" (a new record).
        shortcut: two commands judged at once both read the records before either refusal is
        kept - a row may go one past its limit; hold a count in memory if that is seen."""
        if not (record and record["looked"] and record["verdict"] == "risky"):
            return why, record
        with self._factory() as session:
            project = project_of(session, session.get_one(Conversation, ctx.cid))
            if project is None or project.judge_risky != "refuse":
                return why, record
            turn = session.execute(
                select(Command.judged, Command.started_at)
                .where(Command.run_id == ctx.run_id)
                .order_by(Command.created_at, literal_column("commands.rowid"))
            ).all()
        row, total, capped = risk_judge.refusals(
            (_refused(judged), started is not None) for judged, started in turn
        )
        if capped:
            return why, record
        if row + 1 >= risk_judge.MOST_REFUSED_IN_A_ROW:
            self._koloni_line(
                ctx.cid, ctx.run_id, CAPPED.format(count=f"{row + 1} commands in a row")
            )
        elif total + 1 >= risk_judge.MOST_REFUSED_IN_A_TURN:
            self._koloni_line(ctx.cid, ctx.run_id, CAPPED.format(count=f"{total + 1} commands"))
        return "", {**record, "verdict": "refuse"}

    def _risk_no_room(self: "AgentRunner", session, ctx: Ctx, picked, project) -> str:
        """Why the judge's model may not be asked now: the turn past its token limit, no room on
        its provider - an agent may bring either about (its own request spends), so its card;
        "" for none."""
        limit = project.turn_token_limit
        if limit and self._turn_spent(session, ctx.run_id)[0] > limit:
            return OVER_LIMIT
        provider = session.get_one(Provider, picked[0].provider_id)
        return (
            "" if self._has_room(session, provider, project) else NO_ROOM.format(name=provider.name)
        )

    async def _risk_asked(
        self: "AgentRunner",
        ctx: Ctx,
        command: str,
        cwd: str | None,
        seen: _Seen,
        key: tuple[str, ...] | None,
        record: dict,
        takes: bool = False,
    ) -> tuple[str, dict | None]:
        """The judge asked (`_risk_asks`) - once a turn for a line with a key and the user's words
        as they are (`takes`, K3: its "fine" never kept) -, what it reads masked (`raw.hidden`); a
        "fine" whose program changed while it was asked is a card. Where no model can be asked
        (`NO_MODEL`: fails closed) or one may not be asked now (`_risk_no_room`), its card - said
        once a turn in the chat."""
        with self._factory() as session:
            conversation = session.get_one(Conversation, ctx.cid)
            project = session.get_one(Project, conversation.project_id)
            # (A job's: the chat the user went away from - never its task's own words.)
            night = away.night_of(session, ctx.cid) if ctx.run_id in self._away_jobs else None
            said = self._users_words(
                session, night.conversation_id if night else ctx.cid, project.rules
            )
            digest = hashlib.sha256(json.dumps(said, sort_keys=True).encode()).hexdigest()
            full = (*key, digest) if key else None
            cache = self._risk_cache.setdefault(ctx.run_id, {})
            found = cache.get(full) if full else None
            if isinstance(found, dict) and not (takes and found["verdict"] == "fine"):
                why = found["why"] or NO_REASON
                return ("" if found["verdict"] == "fine" else CARD.format(why=why)), found
            would = would_run(session, find_role(session, LEAD), conversation)
            picked = judge_pick(session, would, self.providers, judge_chosen(session))
            why = NO_MODEL if picked is None else self._risk_no_room(session, ctx, picked, project)
            if picked is None or why:
                self._koloni_line(ctx.cid, ctx.run_id, NOT_ASKED_LINE.format(why=why))
                why = NOT_ASKED.format(why=why)
                return CARD.format(why=why), {**record, "why": why}
            asking, mode = self._on(session, ctx, *picked)
        program = seen.program
        asked = risk_judge.prompt(
            said,
            {
                "command": raw.hidden(command),
                "where": raw.hidden(cwd) if cwd else "not known",
                "by": "Orchestrator" if not ctx.depth else raw.hidden(f"sub-agent {ctx.role}"),
            },
            seen.earlier,
            (raw.hidden(program[0]), program[1] and raw.hidden(program[1]), program[2])
            if program
            else None,
        )
        record = {**record, "model": f"{asking.provider} · {asking.model_name}"}
        got, failed = await self._risk_asks(ctx, asking, mode, asked)
        if got is None:
            return CARD.format(why=failed), {**record, "why": failed}
        # ("looked": the model's own verdict on the line as it is - the one record a Run on its card
        # may keep the line for: `risk_judge.kept`)
        record = {**record, **got, "why": raw.hidden(got["why"]), "looked": True}
        if await asyncio.to_thread(self._risk_moved, command, seen):
            changed = {"verdict": "risky", "why": CHANGED, "looked": False}
            return CARD.format(why=CHANGED), {**record, **changed}
        if full and not (takes and got["verdict"] == "fine"):
            cache[full] = record
        why = record["why"] or NO_REASON
        return ("" if got["verdict"] == "fine" else CARD.format(why=why)), record

    @staticmethod
    def _risk_moved(command: str, seen: _Seen) -> bool:
        """Whether what the line runs changed while the judge looked: the file it runs, found anew
        (`_named_file`: a link or a junction set elsewhere meanwhile, one made or taken away), is
        another, or its digest is. Not for a line whose folder is no fact: nothing was found."""
        if seen.cwd is None:
            return False
        path, _exact = _named_file(seen.root, command, seen.cwd)
        return path != seen.path or path is not None and _digest(path) != seen.digest

    async def _risk_asks(
        self: "AgentRunner", ctx: Ctx, asking: Ctx, mode: str | None, asked: str
    ) -> tuple[dict | None, str]:
        """The judge's one request, in the turn's usage (`_own_request`): its word
        (`risk_judge.verdict`), or None and why - it timed out (`API_SECONDS`, a CLI's
        `CLI_SECONDS`), failed or said nothing that can be read. Stop goes on as Stop."""
        try:
            try:
                limit = risk_judge.API_SECONDS if mode is None else risk_judge.CLI_SECONDS
                async with asyncio.timeout(limit):
                    said, answer = await ask_once(
                        asking.model, asking.model_name or "", [{"role": "user", "content": asked}]
                    )
            except BaseException:
                self._own_request(ctx, asking, mode, None)  # sent, and not heard out
                raise
            self._own_request(ctx, asking, mode, answer)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return None, LATE
        except Exception:
            log.warning("run %s: Full auto's judge was not answered", ctx.run_id, exc_info=True)
            return None, FAILED
        got = risk_judge.verdict(_answer(said))
        return got, "" if got else UNREAD

    def _risk_approved(self: "AgentRunner", command_id: str, remember: bool) -> None:
        """The user's Run on a card of Full auto's judge: its line - the command, its folder, the
        digest of the program it ran as the judge saw it and where it ran (a copy, say) - is not
        asked again this turn, and with `remember` (its card's "Don't ask about this line again
        here") nor in this project again, in any copy. Nothing for another card, nor for one
        with no key (`_risk_judging`'s `kept`, as `risk_judge.kept` reads it from the record)."""
        with self._factory() as session:
            row = session.get(Command, command_id)
            record = row.judged if row is not None else None
            if row is None or not risk_judge.kept(record):
                return
            key = (row.command.strip(), row.cwd or "", record["program"], record.get("root", ""))
            self._risk_cache.setdefault(row.run_id, {})[key] = "approved"
            project_id = session.scalar(
                select(Conversation.project_id)
                .join(Run, Run.conversation_id == Conversation.id)
                .where(Run.id == row.run_id)
            )
            if not remember or project_id is None:
                return
            command, cwd, digest = key[:3]
            session.add(
                JudgeAllowed(project_id=project_id, command=command, cwd=cwd, program_sha=digest)
            )
            try:
                session.commit()
            except IntegrityError:  # (said before)
                session.rollback()
