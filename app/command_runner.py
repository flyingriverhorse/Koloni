"""Runs one `run_command` tool call: record it, get it decided, execute it, record the end."""

import asyncio
import contextlib
import functools
import os
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path, PurePosixPath
from typing import NamedTuple
from urllib.parse import urlsplit

from sqlalchemy import func, literal_column, or_, select, true
from sqlalchemy.exc import IntegrityError

from app import ledger, project_map, proof, proof_style, risk_judge
from app.cards import card_reason, rule_kept_off
from app.commands import (
    _INTERPRETER,
    MAX_STORED_OUTPUT,
    MODEL_HEAD,
    MODEL_TAIL,
    PLANTED,
    OutputMask,
    _program,
    _words,
    applies_patch,
    danger,
    for_model,
    held_back,
    is_allowed,
    names_secret,
    reads_here,
    recallable,
    rules_here,
    search_reason,
    secret_values,
    standing_asked,
    with_cwd,
)
from app.commands import ANSI as _ANSI
from app.db.models import (
    Agent,
    AllowedCommand,
    Command,
    Conversation,
    FileChange,
    Project,
    Run,
    ToolCall,
    now,
)
from app.executors.base import Executor, StartError
from app.serialize import allowed_command_out, command_event, command_out
from app.tools import MAX_TIMEOUT, ToolError, plan_command
from app.workspace import Workspace

FLUSH_SECONDS = 0.5
# How long output may keep arriving after the process itself has exited.
DRAIN_GRACE_SECONDS = 2.0
# How long killing a command may take before we stop waiting for it.
KILL_SECONDS = 20.0
TRUNCATED_NOTE = "\n[output truncated: more than 1 MiB]"
# command_output (0.1.8): at most this much of a command that keeps running at a time - as much
# as of a command's output the model is shown (`for_model`).
OUTPUT_AT_MOST = MODEL_HEAD + MODEL_TAIL
# stop_command: the one way round the command gate is to stop a command the agent started itself.
NOT_YOURS = (
    "command {id} was not started by you, and you stop only one you started: another agent's "
    "or an earlier turn's is the user's to stop, under Preview"
)
# B-321: a refusal ends that one action, not the task - told "do not try another way" and
# "stop and ask", Codex gave up the whole task over one part of one command.
CARRY_ON = (
    "Carry on with the rest of the task without it, and say in your report what you could not do."
)
REJECTED = (
    "rejected: the user declined to run this command. This is their decision, not a tool "
    "error: do not run it again, or anything that does the same. " + CARRY_ON
)
# K-yargic: a command a sentence of the user's forbids at Full auto (`judge.verdict` "refuse"),
# told as a declined one is: not "another way" - one no pattern of KOLONİ's sees (`python -c`,
# `find -exec rm`) would go around the rule (the security review of slice 2).
REFUSED = (
    'KOLONİ did not run this: your user\'s rule says "{quote}". Do not run it again, or '
    "anything that does the same; do what the rule allows, or ask them. " + CARRY_ON
)
REFUSED_BY_A_MESSAGE = (
    "KOLONİ did not run this: a message of your user's in this chat forbids "
    "it. Do not run it again, or anything that does the same; do what it "
    "allows, or ask them. " + CARRY_ON
)
# B-389 (R187, live): a patch sent as a command, refused, and the agent gave up its change. Not
# the change was refused - the command: it is made with the file tools, as a card of its own.
FILE_TOOLS = (
    "If the change is still needed, make it with edit_file / write_file (or your own "
    "file edit tool, where you work with your own tools); the user sees it as a file "
    "change. "
)
PATCH_REJECTED = (
    "rejected: the user declined to run this patch as a command. Do not run it again, or "
    "anything else that applies a patch, as a command. " + FILE_TOOLS + CARRY_ON
)
# B-393 (R188, live): refused a patch, Copilot's Coder wrote the file with PowerShell instead.
WRITE_REJECTED = (
    "rejected: the user declined to run this command, which writes a file. Do not run it "
    "again, or anything else that writes a file, as a command. " + FILE_TOOLS + CARRY_ON
)
# apply_patch as the program a part of the command runs (`'@ | apply_patch`, a line of its own),
# not a word it names (`grep apply_patch`).
APPLY_PATCH = re.compile(r"(?:^|[|;&])\s*apply_patch\b", re.M)
# A file written by PowerShell or .NET, or by a redirection - not one into nothing (`>$null`,
# `2>&1`) nor an arrow or comparison (`=>`, `->`, `>=`).
# shortcut: blind to quotes - `-m "a > b"` gets this wording too; only the wording, never the card.
WRITES_FILE = re.compile(
    r"(?i)\[\s*(?:system\s*\.\s*)?io\s*\.\s*file\s*\]\s*::\s*(?:write|append)all"
    r"|\b(?:set-content|add-content|out-file)\b"
    r"|(?<![=<>-])>>?(?![>&=])\s*(?!\$null\b|nul\b|/dev/null\b)[^\s|;&]"
)
# ...and `New-Item … -Value`, looked for part by part: as one pattern, a long line of `new-item`
# with no `-value` took seconds.
NEW_ITEM, WITH_VALUE = re.compile(r"(?i)\bnew-item\b"), re.compile(r"(?i)\s-value\b")


def _writes_file(command: str) -> bool:
    return bool(WRITES_FILE.search(command)) or any(
        NEW_ITEM.search(part) and WITH_VALUE.search(part) for part in re.split(r"[|;&\n]", command)
    )


def rejected(command: str) -> str:
    """What an agent is told of a command the user declined (`PATCH_REJECTED` for a patch,
    `WRITE_REJECTED` for one that writes a file)."""
    if applies_patch(command) or APPLY_PATCH.search(command):
        return PATCH_REJECTED
    # (One that also deletes or the like was refused for that, not for its write.)
    return WRITE_REJECTED if _writes_file(command) and not danger(command) else REJECTED


def refused_by_rule(judgement: dict) -> str:
    """What an agent is told of a command the check of the user's words refused: the sentence
    where it is one of their saved texts, which every agent is given (`REFUSED`); of a message of
    theirs in the chat, only that one forbids it (`REFUSED_BY_A_MESSAGE`) - a sub-agent or a CLI
    never saw the chat, and a token nothing masks may stand beside the sentence. Full auto's
    judge's own refusal (`kind` "risk"): a general reason, never its sentence (`REFUSED`)."""
    if judgement.get("kind") == "risk":
        return risk_judge.REFUSED
    if judgement.get("source") in ("preferences", "rules"):
        return REFUSED.format(quote=judgement["quote"])
    return REFUSED_BY_A_MESSAGE


def _gate_open(mode: str, check: bool, judgement: dict | None, judge: bool, line: str) -> bool:
    """Whether what the check of the user's words said of a command still holds: only while the
    chat is at Full auto and the project's check is on (`check`: its judge and the judge's box,
    §8) - a run or a refusal that comes back after either changed is its card, as if never checked
    (the security review of K-yargic's slice 2). Full auto's judge's "risk" and K5's quote
    (`kind` "said", an ask at every level) have none - "risky" a card or a refusal -, but a risk
    "fine" on a line the list asks of (`line` with its folder, K3): it holds as the check's run
    does, the judge on (`judge`) and the chat at Full auto."""
    kind = judgement.get("kind") if judgement is not None else None
    if kind == "risk" and danger(line, False):
        return mode == "full_auto" and judge
    return kind in ("risk", "said") or mode == "full_auto" and check


def _refuses(judgement: dict | None, gate: bool) -> bool:
    """Whether the check refused a command, and that holds (`_gate_open`)."""
    return gate and judgement is not None and judgement["verdict"] == "refuse"


def _kept(judgement: dict | None, asks: bool, gate: bool) -> dict | None:
    """What of the check goes on a command's record: nothing once its gate closed (`_gate_open`),
    nor a run (or Full auto's judge's "fine") asked all the same."""
    stale = judgement is not None and (not gate or asks and judgement["verdict"] in ("run", "fine"))
    return None if stale else judgement


def _free(ask: bool, disposable: dict | None, mode: str, allows: bool) -> bool:
    """Coordination §4: whether a delete found disposable goes without the level's own card -
    the caller found it so in a turn the user watches (`allowed`) and, read again as it is
    decided, the project allows such deletes (`allows`) and the chat is at Auto-edit or Full
    auto. What asks at every level is asked all the same."""
    return (
        ask
        and disposable is not None
        and disposable["allowed"]
        and allows
        and mode in ("auto_edit", "full_auto")
    )


def _lapsed(disposable: dict | None, free: bool) -> bool:
    """Whether a delete its caller found free (`allowed`) is no longer so as it is decided - the
    project's switch turned off, the chat's level changed meanwhile: its caller made no ask of
    its own for it (the harm ask of a watched turn), so it is asked here, as `_gate_open`'s."""
    return disposable is not None and disposable["allowed"] and not free


def _noted(disposable: dict | None, unasked: bool) -> dict | None:
    """What of a command goes on its record as disposable (`schemas.DisposableOut`)."""
    return None if disposable is None else {"what": disposable["what"], "unasked": unasked}


# (where nobody can be asked - a trigger's turn: its leave matches by the line's text too)
PLANTED_REFUSED = "KOLONİ did not run this: {why}, and nobody is here to ask. " + CARRY_ON


# W6: a package runner finds the program it runs by itself - npx, npm exec, yarn, pnpm and bun
# (`corepack` before one: the same) in the node_modules of the folder it runs in or of one above
# it, beside the files that make it run code of their own there: `.npmrc` (`node-options`,
# `script-shell`), yarn's (`yarnPath` names the JS it runs, `.yarn/releases`, Plug'n'Play's
# loader), pnpm's hooks (`.pnpmfile.cjs`), bun's preloads; uv, poetry, pipenv, pdm, hatch and
# `python -m` in an environment: the .venv there or above, or one KOLONİ cannot place - any
# install folder of the project's counts (fails closed). A Python also imports what the folder it
# runs in holds first (`python -m`), and in a working copy what PYTHONPATH names - the copy's root
# and its `src` (`host.copy_python_path`) - `sitecustomize` there before anything it runs.
_NODE_RUNNERS = frozenset({"npx", "pnpx", "bunx", "npm", "pnpm", "yarn", "bun"})
# (yarn's `.env.yarn` and bun's `.env` files go into the environment of what it runs:
# `NODE_OPTIONS=--require x`)
_BUN_ENV = (".env", ".env.local", ".env.production", ".env.development")
_NODE_SETTINGS = {
    "yarn": (
        ".yarnrc.yml",
        ".yarnrc",
        ".yarn",
        ".pnp.cjs",
        ".pnp.loader.mjs",
        ".npmrc",
        ".env.yarn",
    ),
    "pnpm": (".pnpmfile.cjs", ".npmrc"),
    "pnpx": (".pnpmfile.cjs", ".npmrc"),
    "bun": ("bunfig.toml", *_BUN_ENV),
    "bunx": ("bunfig.toml", *_BUN_ENV),
}
# W7: npx and `npm exec` run a name the local package's `bin` gives first (measured, npm 11.9:
# installed into its cache and run from there, never node_modules/.bin), yarn and pnpm a script of
# its own, `npm install` every workspace's lifecycle scripts (W7d), and npm reads any `*.npmrc` it
# is pointed at (W7c) - so an agent's write of any package.json or runner setting in the project
# (`_NODE_EVERYWHERE`, a package's in a node_modules too) stops the rule: an install follows a
# lock's `resolved` address and runs node-gyp on a `binding.gyp`. A line of npm's or pnpm's that
# runs a script by its name (`npm run x`, `npm test`) runs the project's code by design and is not
# so - yarn's and bun's `run` run a bin too, npx's `test` is a package.
_SCRIPT_VERBS = frozenset({"run", "run-script", "test", "t", "tst", "start", "stop", "restart"})
_NODE_EVERYWHERE = frozenset(
    {
        *("package.json", ".yarn", ".pnpmfile.cjs", "pnpm-workspace.yaml", "bunfig.toml"),
        *("package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock"),
        *("bun.lockb", "bun.lock", "binding.gyp"),
    }
)


def _node_setting(rel: str) -> str | None:
    """W7c, W7d: the package.json, lock or runner setting (`.npmrc` / `x.npmrc`, `.yarnrc*`,
    `.yarn/`, `_NODE_EVERYWHERE`) `rel` (from the root) is or is in; None: none."""
    parts = PurePosixPath(rel).parts
    for at, part in enumerate(part.casefold() for part in parts):
        if part in _NODE_EVERYWHERE or part.endswith(".npmrc") or part.startswith(".yarnrc"):
            return PurePosixPath(*parts[: at + 1]).as_posix()
    return None


_PY_RUNNERS = frozenset({"uv", "uvx", "poetry", "pipenv", "pdm", "hatch", "pip", "pip3"})
# (one run as a module is that one - `python -m uv`, `py -m pip` -, and so is `python -m build`)
_PY_RUNNER_MODULES = _PY_RUNNERS | {"build"}
# ...and uv, poetry, pipenv, pdm, hatch resolve `[project.scripts]` and build the project to run
# in it, pip and build the one they install: an agent's `pyproject.toml` (or `setup.py`) there
# stops theirs - but a test run's. So
# does one anywhere in the project (F395, as W7d: a workspace member's or a path dependency's,
# built with it), and any of their settings, locks and requirements (`_python_setting`).
_PY_MANIFESTS = ("pyproject.toml", "setup.py")
_PY_EVERYWHERE = frozenset(
    {
        *(*_PY_MANIFESTS, "setup.cfg", "uv.toml", "poetry.toml", "pdm.toml", "hatch.toml"),
        *("pipfile", "pipfile.lock", "uv.lock", "poetry.lock", "pdm.lock", "pylock.toml"),
        *(".python-version", ".pdm-python"),  # (the Python uv / pdm run: a path too)
    }
)
_PY_RUNNER_SETTINGS = {"pipenv": (".env",)}  # (loaded into its environment: PATH, PYTHONPATH)


def _python_setting(rel: str, runner: str) -> str | None:
    """F395: `rel` (from the root) where it is a Python runner's manifest, setting or lock
    (`_PY_EVERYWHERE`, the runner's own `_PY_RUNNER_SETTINGS`) or requirements (`requirements*.txt`,
    `requirements/x.txt`); None: none.
    shortcut: by the tools' documents, not measured (no uv, poetry, pipenv, pdm or hatch runs
    here); a file a manifest names by another name (`-r deps.txt`) is not seen - count it if one is
    seen used so."""
    parts = [part.casefold() for part in PurePosixPath(rel).parts]
    name = parts[-1] if parts else ""
    if name in _PY_EVERYWHERE or name in _PY_RUNNER_SETTINGS.get(runner, ()):
        return rel
    named = any(part.startswith("requirements") for part in parts)
    return rel if named and name.endswith(".txt") else None


_PY_INSTALLS = (".venv", "venv", "site-packages")
_PYTHON = re.compile(r"python[\d.]*w?|pyw?")
# (`python -m pytest` imports the project's own modules by design - its tests are its code)
_RUNS_THE_PROJECT = frozenset({"pytest", "unittest"})
_COPY_PATH = (".", "src")  # (`host.copy_python_path`'s, from the copy's root)


class _Reach(NamedTuple):
    """W6: where a line's program comes from - folders and files from the root (None: its path,
    `proof_style.wrote_program`), install folders it may take it from anywhere in the project -
    and, of a Python, whether it imports the modules of the folder it runs in first (`python
    -m`), whether it reads PYTHONPATH (a copy's root and `src`), and whether only
    `sitecustomize` / `usercustomize` count (`pytest`'s tests import the project's code anyway -
    those run before anything)."""

    places: list[str] | None
    anywhere: tuple[str, ...] = ()
    reads_cwd: bool = False
    reads_path: bool = False
    startup_only: bool = False
    node_settings: bool = False  # (`_node_setting`: any in the project)
    py_settings: str = ""  # (the Python runner whose `_python_setting` count: any in the project)


def _python_module(words: list[str]) -> tuple[str, str] | None:
    """`python [its options] -m x` (`-mx`, `-Im x` too): x, and the letters of its options before
    it (`-I`, `-P`: not the folder it runs in; `-I`, `-E`: not PYTHONPATH); None: no `-m` before a
    script or `-c`."""
    flags, at = "", 1
    while at < len(words):
        word = words[at]
        if not word.startswith("-") or word in ("-", "--"):
            return None
        head, m, tail = word[1:].partition("m")
        if word.startswith("--"):
            at += 1
            continue
        flags += head
        if m:
            module = tail or (words[at + 1] if at + 1 < len(words) else "")
            return (module, flags) if module else None
        if "c" in head:
            return None
        at += 2 if word in ("-X", "-W") else 1
    return None


def _runner_places(words: list[str], cwd: str) -> _Reach | None:
    """W6: where a package runner's or a Python's line (`words`) finds what it runs (`_Reach`);
    None: neither."""
    words = words[1:] if words and _program(words[0]) == "corepack" else words
    name = _program(words[0]) if words else ""
    above = [PurePosixPath(cwd), *PurePosixPath(cwd).parents]
    if name in _NODE_RUNNERS:
        script = name in ("npm", "pnpm") and words[1:2] and words[1] in _SCRIPT_VERBS
        names = ("node_modules", *_NODE_SETTINGS.get(name, (".npmrc",)))
        return _Reach(
            [str(folder / one) for folder in above for one in names], node_settings=not script
        )
    python = next((at for at, word in enumerate(words) if _PYTHON.fullmatch(_program(word))), None)
    module = _python_module(words[python:]) if python is not None else None
    ran, flags = (module[0], set(module[1])) if module is not None else (None, set())
    led = ran in _PY_RUNNER_MODULES  # (`python -m uv`, `-m pip`)
    runner = name if name in _PY_RUNNERS or not led or ran is None else ran
    if runner not in _PY_RUNNERS and module is None:
        return None
    skip = ("run", ran if led and ran is not None else "run")
    rest = (w for w in words[1:] if w[:1] != "-" and w not in skip)
    tool = ran if ran is not None and not led else next(rest, "")
    safe_path = bool(os.environ.get("PYTHONSAFEPATH")) and "E" not in flags
    tests = _program(tool.split(".")[0]) in _RUNS_THE_PROJECT
    own = _PY_MANIFESTS if runner in _PY_RUNNER_MODULES and not tests else ()
    return _Reach(
        [str(folder / one) for folder in above for one in (".venv", "venv", *own)],
        _PY_INSTALLS,
        reads_cwd=module is not None and not flags & {"I", "P"} and not safe_path,
        reads_path=not flags & {"I", "E"},
        startup_only=tests,
        py_settings=runner if own else "",
    )


def _program_word(words: list[str]) -> str:
    """The word naming what a line runs: its program, or the script an interpreter is handed
    from an install folder (`node node_modules/typescript/bin/tsc`, W6)."""
    program = words[0] if words else ""
    script = next((word for word in words[1:] if not word.startswith("-")), "")
    parts = PurePosixPath(script.replace("\\", "/")).parts
    if _INTERPRETER.fullmatch(_program(program)) and any(
        part.casefold() in proof_style.INSTALLS for part in parts
    ):
        return script
    return program


def _path_reach(parts: tuple[str, ...]) -> _Reach:
    """A program named by its path: a console script of a Python environment (`.venv/Scripts/x`,
    `venv/bin/x`) reads PYTHONPATH as its Python does (W6)."""
    folded = [part.casefold() for part in parts]
    script = any(
        one in (".venv", "venv") and two in ("scripts", "bin")
        for one, two in zip(folded, folded[1:], strict=False)
    )
    tool = _program(parts[-1]) if parts else ""
    return _Reach(None, reads_path=script, startup_only=tool in _RUNS_THE_PROJECT)


def _reach_of(words: list[str], program: str, cwd: str) -> tuple[_Reach, list[str], bool] | None:
    """W2, W6: where a line's program comes from (`_Reach`), the names of what a write there is
    looked up by - and whether it runs tsc (W7: tsc's settings count too - but on Code style's own
    line, word for word `proof_style.TSC_WORDS`, whose `--composite false --generateTrace null`
    win over them: measured, 5.9); None: none of these."""
    parts = PurePosixPath(program.replace("\\", "/")).parts
    # (a runner first: `.venv/Scripts/python.exe -m x` is named by its path, and reads its folder)
    reach = _runner_places(words, cwd)
    tsc = words[1:] != proof_style.TSC_WORDS.split() and (
        _program(program).removesuffix(".js") in ("tsc", "_tsc")  # (`node …/lib/tsc.js` too)
        or reach is not None
        and reach.node_settings
        and "tsc" in {_program(word) for word in words}
    )
    if reach:
        named = [*{PurePosixPath(place).name for place in reach.places or ()}, *reach.anywhere]
    elif parts and ("/" in program or "\\" in program):
        reach = _path_reach(parts)
        named = [
            next(
                (part for part in parts if part.casefold() in proof_style.INSTALLS),
                parts[-1].split(".")[0],
            )
        ]
    elif tsc:
        reach, named = _Reach([]), []
    else:
        return None
    return reach, named, tsc


def _written_settings(
    reach: _Reach, root: Path, cwd: str, words: list[str], tsc: bool
) -> tuple[list[str], Callable[[str], str | None]]:
    """W7, F395: the settings files anywhere in the project an agent's write of which stops a
    rule of the line - a node runner's (`_node_setting`), a Python runner's (`_python_setting`),
    tsc's (`proof_style.tsc_setting`) -: the names a write's record is looked up by, and the test
    of its path (the place said; None: not one)."""
    names: list[str] = []
    tests: list[Callable[[str], str | None]] = []
    if reach.node_settings:
        names += [*_NODE_EVERYWHERE, "npmrc", ".yarnrc", "node_modules"]
        tests.append(_node_setting)
    if reach.py_settings:
        names += [*_PY_EVERYWHERE, *_PY_RUNNER_SETTINGS.get(reach.py_settings, ()), "requirements"]
        tests.append(functools.partial(_python_setting, runner=reach.py_settings))
    if tsc:
        read = proof_style.tsc_reads(root, cwd, words)
        names += ["tsconfig", "jsconfig", *map(os.path.basename, read or [".json"])]
        tests.append(functools.partial(proof_style.tsc_setting, root, read=read))
    return names, lambda rel: next((place for test in tests if (place := test(rel))), None)


def _planted(factory, cid: str, root: Path, command: str, cwd: str) -> str | None:
    """W2, W6: why a rule, a yes given before or a trigger's leave - each matches by the line's
    text, in any folder - does not cover `command`: its program, named by its path, is one an
    agent wrote on record - any turn's, as it still stands in `root` (`proof_style.
    still_written`) -, or is in the install folder such a write is in (`proof_style.
    wrote_program`); or a package runner's line (`_runner_places`) finds its program where such
    a write is; or a Python imports a module such a write is (`proof_style.shadows`); or such a
    write is a setting the line reads (`_written_settings`). None: no such write. In a thread:
    the records are matched to the program's place first, and only those files are read, once
    the session is closed.
    shortcut: the program alone - a script an interpreter is given (`node x.js`) is not judged
    so; judge it too if a rule of one is seen to run one an agent wrote."""
    words = [word.strip("'\"") for word in _words(command)]
    words = words[1:] if words[:1] in (["&"], ["."]) else words  # (PowerShell's call)
    program = _program_word(words)
    if (reached := _reach_of(words, program, cwd)) is None:
        return None
    reach, named, tsc = reached
    settings, setting = _written_settings(reach, root, cwd, words, tsc)
    with factory() as session:
        project = session.scalar(
            select(Project.root_path)
            .join(Conversation, Conversation.project_id == Project.id)
            .where(Conversation.id == cid)
        )
        in_copy = project is not None and Path(project).resolve() != root
        own = reach.reads_cwd and not reach.startup_only  # (the folder it runs in: `-m`)
        path = in_copy and reach.reads_path  # (a copy's PYTHONPATH)
        looked = [
            one.lower()
            for one in [
                *named,
                *((*proof_style.MODULE_ENDINGS, "__init__") if own or path else ()),
                *settings,
            ]
        ]
        found = session.execute(
            select(FileChange.path, FileChange.after_sha)
            .join(Run, Run.id == FileChange.run_id)
            .join(Conversation, Conversation.id == Run.conversation_id)
            .where(
                Conversation.project_id
                == select(Conversation.project_id).where(Conversation.id == cid).scalar_subquery(),
                FileChange.status.in_((*ledger.KEPT, proof.MERGED)),
                # (SQLite lowers ASCII alone: another name is looked for in every path)
                or_(*(func.lower(FileChange.path).contains(one, autoescape=True) for one in looked))
                if all(one.isascii() for one in looked)
                else true(),
            )
            .order_by(FileChange.created_at, literal_column("file_changes.rowid"))
        ).all()
    newest = {path: digest for path, digest in found}
    places, anywhere = reach.places, reach.anywhere
    # (the folders a Python imports from first, and whether only its `sitecustomize` counts)
    imported = [(cwd, False)] * own + [(one, reach.startup_only) for one in _COPY_PATH] * path

    def plants(rel: str) -> str | None:
        if places is None:
            found = proof_style.wrote_program(root, cwd, program, [rel])
        else:
            found = proof_style.planted_in(root, places, anywhere, rel)
        return (
            found
            or next(
                (one for entry, only in imported if (one := proof_style.shadows(entry, rel, only))),
                None,
            )
            or setting(rel)
        )

    held = proof_style.still_written(root, [one for one in newest.items() if plants(one[0])])
    place = next((place for rel in held if (place := plants(rel))), None)
    return PLANTED.format(place=place) if place else None


# Y1: cmd.exe's word for a bare name it did not find - under KOLONİ only on PATH (W1, as under
# git), so a batch file of the user's that calls its neighbour so no longer finds it.
NOT_RECOGNIZED = "' is not recognized as an internal or external command"
BARE_NAME = (
    "\n(KOLONİ's commands find a program named bare on PATH only, never in the folder they run "
    "in: call {name} as .\\{name} - in a batch file as %~dp0{name}.)"
)


def _bare_name_hint(output: str, folder: Path) -> str:
    """Y1: the hint for a bare name cmd.exe did not find (`NOT_RECOGNIZED`) that the run's
    folder has, as it is or with a program's ending; "" for none."""
    output = output[-64 * 1024 :]  # (its last words: the line cmd.exe ended on is there)
    if NOT_RECOGNIZED not in output:
        return ""
    for line in output.splitlines():
        head, found, _rest = line.partition(NOT_RECOGNIZED)
        name = head[head.rfind("'") + 1 :] if found else ""
        if (
            name
            and not set(name) & set('\\/:*?"<>|')
            and any(
                (folder / f"{name}{end}").is_file() for end in ("", ".cmd", ".bat", ".exe", ".com")
            )
        ):
            return BARE_NAME.format(name=name)
    return ""


HELD_BACK = (
    "(secret variables held back from this command: {names} - the user can pass one "
    "in Settings › This project › Commands and secrets)"
)


def _held_note(names: list[str], into: list[str] | None) -> str:
    """The note of the secrets held back - or none, where they go `into` a list (`run`)."""
    if into is not None:
        into.extend(names)
    return f"\n{HELD_BACK.format(names=', '.join(names))}" if names and into is None else ""


# A command that keeps running (a dev server, slice 42b): the tool answers once it printed
# its address, or its output went quiet for SERVE_QUIET after it began, or SERVE_AT_MOST is up.
SERVE_QUIET = 1.0
SERVE_AT_MOST = 10.0
MAX_SERVING = 3
# How a command ended: its status, exit code, output, and why it failed to start if it did.
Ended = tuple[str, int | None, str, str | None]
# An address on this machine with its port, as a server prints it - up to the space after it,
# so that one cut between two chunks of output is not taken half.
_LOOPBACK = re.compile(
    r"http://(?:localhost|127\.0\.0\.1|\[::1\]):(\d{1,5})(?:/[^\s'\"<>]*)?(?=[\s'\"<>])"
)


def preview_url(output: str, closed: set[int]) -> str | None:
    """The first address on this machine in a command's output whose port is none of
    `closed` (KOLONİ's own, a model server's), colours aside."""
    for found in _LOOPBACK.finditer(_ANSI.sub("", output)):
        if 0 < int(found[1]) < 65536 and int(found[1]) not in closed:
            return found[0]
    return None


def longest_seconds(project: Project | None) -> int:
    """The longest a command may take in `project` (0.1.8: its `longest_command`), in seconds -
    an agent's, and KOLONİ's own test runs'; MAX_TIMEOUT where there is no project."""
    return project.longest_command * 60 if project is not None else MAX_TIMEOUT


def port_of(url: str | None) -> int | None:
    try:
        parts = urlsplit(url or "")
        return parts.port or {"http": 80, "https": 443}.get(parts.scheme)
    except ValueError:  # not a port at all
        return None


class CommandRunner:
    def __init__(
        self,
        session_factory,
        bus,
        executors: Callable[[str, Project], Executor],
        update_run: Callable[..., None],
    ):
        self._factory = session_factory
        self.bus = bus
        self._executors = executors
        self._update_run = update_run
        # command id -> future resolved with "once", "always", "disposable" or "reject"
        self._decisions: dict[str, asyncio.Future[str]] = {}
        # The commands whose own card the user answered "Always run" (the end check reads it:
        # option A, a saved test command kept as the user's - `said_always`).
        self._always: set[str] = set()
        # command id -> (conversation id, output so far) while the command runs
        self._live: dict[str, tuple[str, str]] = {}
        # command id -> what hides the secrets in its output, while it runs (slice 90)
        self._masks: dict[str, OutputMask] = {}
        # The kills under way, each with the folder its command ran in. One that failed
        # stays: its process may still be alive.
        self._ending: dict[asyncio.Future, Path] = {}
        # How the user's decision is waited for, for an agent (by its id): whoever owns
        # the agents' places puts its own here, so that one that waits holds none. Its
        # last argument is called with the decision as soon as it is there, and with
        # whether the agent has to wait for a place before it can go on.
        self.users_word: (
            Callable[[str, asyncio.Future[str], Callable[[str, bool], None]], Awaitable[str]] | None
        ) = None
        # The ports a served address may not have: KOLONİ's own, the model servers'.
        self.closed_ports: Callable[[], set[int]] = set
        # A turn's secrets the user gave on a card (slice 91), by run id: name -> value.
        self.secrets: Callable[[str], dict[str, str]] = lambda _run_id: {}
        # command id -> (conversation id, its task) while a command that keeps running runs
        self._serving: dict[str, tuple[str, asyncio.Task]] = {}
        self._closing = False

    def decide(self, command_id: str, decision: str) -> bool:
        """Deliver the user's decision to the waiting run; False if nothing waits."""
        future = self._decisions.get(command_id)
        if future is None or future.done():
            return False
        future.set_result(decision)
        return True

    def longest(self, cid: str) -> int:
        """The longest a command may take in conversation `cid`'s project, in seconds."""
        with self._factory() as session:
            conversation = session.get(Conversation, cid)
            project_id = conversation.project_id if conversation is not None else None
            return longest_seconds(session.get(Project, project_id) if project_id else None)

    def live_outputs(self, conversation_id: str) -> dict[str, str]:
        return {k: text for k, (cid, text) in self._live.items() if cid == conversation_id}

    async def run(
        self,
        run_id: str,
        cid: str,
        agent_id: str,
        ws: Workspace,
        call_id: str,
        args: dict,
        ask: bool = True,
        where: Callable[[], Awaitable[Workspace]] | None = None,
        always: bool = False,
        web_off: bool = False,
        once: set[str] | None = None,
        judgement: dict | None = None,
        disposable: dict | None = None,
        env: Mapping[str, str] | None = None,
        park: Callable[[str], Awaitable[str]] | None = None,
        held_into: list[str] | None = None,
    ) -> tuple[str, str]:
        """Returns the tool call's final status and the result text for the model.
        `ask` is False where the command has its leave already (a skill's script the user lets
        run, the user's own Run): it runs, whatever the conversation says.
        `ws` is where it runs: the project folder, or the agent's working copy.
        `where`: asked once the command may run, for where it then runs - an agent's
        working copy is made by its first command, and not for one that is refused.
        `always`: asked about at every level, as `ask_for`'s (`copy_reason`). `web_off`: that
        is because web is off (`web_off_reason`): no rule is offered. `once`: commands the
        user said yes to on a card, exactly as written, that the level alone does not ask again
        (K-evrim's measure, for its run) - what asks at every level still does; a yes on this
        one's card is added to it. `judgement`: what the check of the user's words said of it
        (K-yargic, `AgentRunner._judged`) - not kept as a run where it is asked all the same; one
        it refused (`_refuses`) goes on record ended, "refused", and is neither asked nor run.
        `disposable`: what of it KOLONİ found disposable, {"what", "allowed"} (coordination §4):
        `allowed` lifts the level's own ask only (`_free`), and its card offers "Allow such
        deletes in this project" where it is asked. `env`: what its environment gets besides
        (KOLONİ's own test runs: their processes, S6) - never an agent's command. `park` (☾ Away):
        one asked is parked, not waited on - what it returns, the model is told. `held_into` (☾
        Away's morning): the secrets held back go into it by name, not into the result (F411 P4)."""
        cap = self.longest(cid)
        planned = plan_command(ws, args, cap)
        searched = await asyncio.to_thread(search_reason, planned.command, ws.root, planned.cwd_rel)
        planted = await asyncio.to_thread(
            _planted, self._factory, cid, ws.root, planned.command, planned.cwd_rel
        )
        reads = await asyncio.to_thread(
            reads_here, planned.command, ws.root, planned.cwd_rel == ".", planned.cwd_rel
        )
        with self._factory() as session:
            conversation = session.get_one(Conversation, cid)
            project = session.get_one(Project, conversation.project_id)
            check, judge = project.full_auto_judge and project.judge_words, project.full_auto_judge
            # (Judged with its cwd, `with_cwd`: `cwd=.koloni/tmp` and `.. ` reach out of it.)
            judged = with_cwd(planned.command, planned.cwd_rel)
            gate = _gate_open(conversation.permission_mode, check, judgement, judge, judged)
            forbidden = _refuses(judgement, gate)
            if planned.keep_running and not forbidden:
                self._may_serve(
                    session,
                    cid,
                    project,
                    ws,
                    ask,
                    where,
                    lead=session.get_one(Agent, agent_id).depth == 0,
                )
            prefixes = [rule.prefix for rule in session.scalars(rules_here(conversation))]
            # (Its id is said beside a cut output only where recall_output would give it.)
            asked = session.get(ToolCall, call_id) if call_id else None  # (a check: none)
            recall = (
                call_id
                if asked is not None
                and recallable(asked.name, asked.outside_folder, None, planned.command)
                else None
            )
            # One the user is not asked about runs on a yes given before - a rule, the
            # level, its trigger's leave: "approved" from the first, so that while its
            # start is waited for it is not shown as waiting for the user, and a turn
            # that ends before it starts does not leave it "rejected". A server is asked
            # for every time but in Full auto: no rule covers one. One that names a secret
            # file is asked for at every level (slice 90), and so is one that searches the
            # whole folder while it holds one, or names `.koloni` (86c) or another file that
            # steers later turns (`names_standing`, B-79), or has a reason in a working copy
            # (`copy_reason`, which its card shows from its call's record). One that only reads
            # is not (K-ask-okuma), nor the user's own test command run in its part's folder
            # (`project_map.own_test`). Nor is one the check of the user's words let run - while
            # that holds (`_gate_open`).
            own = project_map.own_test(project.test_commands, planned.command, planned.cwd_rel)
            # (K-fullauto-sorma: at Full auto an instruction file alone is not asked.)
            free = _free(ask, disposable, conversation.permission_mode, project.disposable_deletes)
            covered = (
                is_allowed(planned.command, prefixes)
                or reads
                or own
                or free
                or planned.command in (once or ())
            )
            # W2: never a program an agent wrote by a rule or a yes given before - on its card -,
            # nor by a trigger's leave where nobody can be asked: refused. (Full auto, watched:
            # it runs, as any command does.)
            by_leave = conversation.permission_mode != "full_auto" and covered
            planted = planted if by_leave or not ask else None
            refused = bool(planted) and not ask
            if planted and asked is not None and not asked.why_asked:
                asked.why_asked = planted
            asks = ask and (
                always
                or names_secret(judged)
                or bool(standing_asked(judged, conversation.permission_mode != "full_auto"))
                or bool(searched)
                or judgement is not None
                and not gate
                or _lapsed(disposable, free)
                or (
                    conversation.permission_mode != "full_auto"
                    and (planned.keep_running or not covered or bool(planted))
                )
            )
            # The place is fixed now: changing the project setting while this command
            # waits for a decision must not move it somewhere the user did not see.
            command = Command(
                run_id=run_id,
                agent_id=agent_id,
                tool_call_id=call_id,
                command=planned.command,
                cwd=planned.cwd_rel,
                location=project.exec_location,
                image=project.docker_image if project.exec_location == "docker" else None,
                timeout_seconds=planned.timeout,
                status="refused"
                if forbidden or refused
                else ("parked" if park else "proposed")
                if asks
                else "approved",
                ended_at=now() if forbidden or refused else None,
                keep_running=planned.keep_running,
                web_off=web_off,
                # shortcut: a check that said run on one asked for another reason (a search that
                # reaches a secret, `searched`) was a request spent; look for that before it if
                # such checks are seen often.
                judged=_kept(judgement, asks, gate),
                disposable=_noted(disposable, free and not asks),
                # (Cards measured: why it is asked, as the gate sees it now - KOLONİ's words.)
                asked_reason=card_reason(
                    judged,
                    conversation.permission_mode != "full_auto",
                    (asked.why_asked or "") if asked is not None else "",
                    searched=bool(searched),
                    web_off=web_off,
                    keep_running=planned.keep_running,
                )
                if asks and not forbidden
                else None,
            )
            session.add(command)
            rule_kept_off(session, command, prefixes, conversation.permission_mode != "full_auto")
            session.commit()
            command_id, location = command.id, command.location
            payload = command_out(command, held=bool(searched))
            rule = payload["suggested_prefix"]
        self.bus.emit(cid, run_id, "command.created", payload)
        if forbidden and judgement:  # K-yargic: a sentence of the user's forbids it - not run
            return "denied", refused_by_rule(judgement)
        if refused or asks and park is not None:  # (☾ Away, §10: a card parked, not waited on)
            by = None if refused else park
            return "denied", await by(command_id) if by else PLANTED_REFUSED.format(why=planted)

        if asks:
            # (`rule` is empty when this command cannot be remembered.)
            decision = await self._wait_for_decision(run_id, cid, agent_id, command_id, rule)
            if decision == "reject":
                self._set(cid, command_id, status="rejected", ended_at=now())
                return "denied", rejected(planned.command)
            if once is not None:
                once.add(planned.command)

        try:
            if where is not None:
                ws = await where()
                planned = plan_command(ws, args, cap)
        except ToolError as exc:  # its folder is not in the copy (one that is left out)
            self._set(
                cid, command_id, status="failed_to_start", output=f"error: {exc}", ended_at=now()
            )
            return "failed", f"error: {exc}"
        try:
            in_copy = ws.root != Path(project.root_path).resolve()
            # shortcut: a command that keeps running (42b) keeps what it was given after the
            # turn; stop such a one at the turn's end if a secret is ever given to a server.
            given = self.secrets(run_id)
            running = await self._executors(location, project).start(
                command_id,
                planned.command,
                planned.cwd_path,
                copy=ws.root if in_copy else None,
                links=ws.links if in_copy else None,
                secrets=given,
                env=env,
            )
        except StartError as exc:
            # The reason stays on the record, so the user sees it and not only the model.
            self._set(
                cid, command_id, status="failed_to_start", output=f"error: {exc}", ended_at=now()
            )
            return "failed", f"error: {exc}"

        self._set(cid, command_id, status="running", started_at=now())
        self._live[command_id] = (cid, "")
        # (The command gets this machine's environment, `KOLONI_*` and the secret variables
        # the user did not pass aside: what of it is a secret is hidden in what it prints. In
        # Docker it gets none; hiding is harmless.)
        self._masks[command_id] = OutputMask([*secret_values(os.environ), *given.values()])
        # Which were held back (slice 103), by name: the model is told, and that the user can
        # pass one. (Not one the user gave this turn on a card: it has that.)
        held = (
            [name for name in held_back(os.environ, project.pass_env) if name.upper() not in given]
            if location == "host"
            else []
        )
        note = _held_note(held, held_into)
        started = time.monotonic()
        if not planned.keep_running:
            ended = await self._through(cid, command_id, running, ws.root, planned.timeout)
            status, said = self._told(*ended, planned.timeout, time.monotonic() - started, recall)
            return status, said + _bare_name_hint(ended[2], planned.cwd_path) + note
        heard = {"url": None, "at": None, "scanned": 0, "closed": self.closed_ports()}
        life = asyncio.ensure_future(self._through(cid, command_id, running, ws.root, None, heard))
        self._serving[command_id] = (cid, life)
        life.add_done_callback(lambda _: self._serving.pop(command_id, None))
        status, said = await self._first_words(cid, command_id, life, heard, started)
        return status, said + note

    async def _through(
        self,
        cid: str,
        command_id: str,
        running,
        root: Path,
        timeout: int | None,
        heard: dict | None = None,
    ) -> Ended:
        """Watch a started command to its end and record it: how it ended, its exit code,
        its output, and why it failed to start if it did. Raises CancelledError, once that is
        recorded, where it was stopped. `heard`: what a server said of its address."""
        state = {"truncated": False}
        drain = asyncio.ensure_future(self._drain(cid, command_id, running, state, heard))
        code: int | None = None
        cancelled = False
        try:
            code = await asyncio.wait_for(running.wait(), timeout)
            status = "exited"
            # The process is done. Whatever it left running may still hold the output
            # open, so the rest of the output gets a moment, not forever.
            with contextlib.suppress(TimeoutError, Exception):
                await asyncio.wait_for(asyncio.shield(drain), DRAIN_GRACE_SECONDS)
        except TimeoutError:
            status = "timed_out"
        except asyncio.CancelledError:
            # Stop; or, of a server, KOLONİ closing ("stopped when KOLONİ closed").
            status, cancelled = "interrupted" if heard and self._closing else "killed", True
        except Exception:
            status = "killed"
        # From here to the record below nothing may be skipped, whatever arrives:
        # a second Stop must not leave the command "running".
        cancelled = await self._end(running, status != "exited", root) or cancelled
        drain.cancel()
        # What was held back - half a line, with no end after it - comes out hidden now.
        mask = self._masks.pop(command_id, None)
        if mask is not None and (rest := mask.flush()) and not state["truncated"]:
            self._add_output(cid, command_id, rest, state)
        output = self._live.get(command_id, (cid, ""))[1]
        failure = None
        if status == "exited" and code is not None:
            failure = running.start_failure(code, output)
        if failure:
            status = "failed_to_start"
        self._finish(cid, command_id, status, code, state["truncated"])
        if cancelled:
            raise asyncio.CancelledError
        return status, code, output, failure

    @staticmethod
    def _told(
        status: str,
        code: int | None,
        output: str,
        failure: str | None,
        timeout: int | None,
        seconds: float,
        call_id: str | None = None,
    ) -> tuple[str, str]:
        """How a command ended, for the model: the tool call's status and its result - where
        that is cut, with the id that gives the whole of it (K-gecmis-zengin).
        shortcut: not a server's (`_first_words`): it goes on printing; pass its id there if
        an agent is seen to need a server's whole output."""
        shown = for_model(output, call_id)
        if failure:
            return "failed", f"error: {failure}\n{shown}"
        if status == "timed_out":
            return "failed", f"error: timed out after {timeout} seconds and was stopped\n{shown}"
        if status != "exited":
            return "failed", f"error: the command was stopped\n{shown}"
        # A non-zero exit code is a result for the model to read, not a tool failure.
        return "succeeded", f"exit code {code} ({seconds:.1f}s)\n{shown}"

    def _may_serve(
        self,
        session,
        cid: str,
        project: Project,
        ws: Workspace,
        ask: bool,
        where,
        lead: bool = False,
    ) -> None:
        """Why a command may not keep running here, as a ToolError: said before anything of
        it is on record. `lead`: the agent is the turn's Lead, in a copy only in a recipe's
        turn (or a side's, a night job's) - there is nobody above it to start it."""
        if project.exec_location == "docker":
            raise ToolError(
                "keep_running is only on this machine for now, and this project runs its "
                "commands in Docker: run it without keep_running, or ask the user to start it"
            )
        # shortcut: never in a working copy (it goes with its agent's work, and a server in it
        # would too); upgrade when a sub-agent has to serve what it made.
        if (where is not None or ws.root != Path(project.root_path).resolve()) and lead:
            raise ToolError(
                "keep_running does not run in the copy you work in: start it once the work is "
                "taken into the project (the user's Take in), or run the server and its test in "
                "one command without keep_running"
            )
        if where is not None or ws.root != Path(project.root_path).resolve():
            raise ToolError(
                "keep_running runs in the project folder itself, not in a working copy: "
                "say what to start, and the Orchestrator starts it"
            )
        if not ask:
            raise ToolError("keep_running is not for a turn nobody watches")
        serving = session.scalar(
            select(func.count())
            .select_from(Command)
            .join(Run, Run.id == Command.run_id)
            .where(
                Run.conversation_id == cid,
                Command.keep_running,
                Command.status.in_(("proposed", "approved", "running")),
            )
        )
        if serving >= MAX_SERVING:
            raise ToolError(
                f"at most three commands keep running in a conversation, and {serving} do: "
                "nothing was started. The user can stop one under Preview"
            )

    async def _first_words(
        self,
        cid: str,
        command_id: str,
        life: asyncio.Future[Ended],
        heard: dict,
        started: float,
    ) -> tuple[str, str]:
        """The answer for a command that keeps running: once it said its address, its output
        went quiet or SERVE_AT_MOST is up - or, where it ended first, as any command's."""
        while (
            not life.done()
            and heard["url"] is None
            and (
                (heard["at"] is None or time.monotonic() - heard["at"] < SERVE_QUIET)
                and time.monotonic() - started < SERVE_AT_MOST
            )
        ):
            await asyncio.sleep(0.05)
        if not life.done() and heard["url"] is None and heard["at"] is not None:
            # (one printed last, with nothing after it, is whole once its output went quiet -
            # and still held back, with the half line it is on)
            mask = self._masks.get(command_id)
            output = self._live.get(command_id, (cid, ""))[1] + (mask.peek() if mask else "")
            self._look_for_address(cid, command_id, output + "\n", heard)
        if life.done():
            if life.cancelled():
                return "failed", "error: the command was stopped"
            return self._told(*life.result(), None, time.monotonic() - started)
        last = "\n".join(self._live.get(command_id, (cid, ""))[1].splitlines()[-20:])
        where = (
            f"serving {heard['url']}"
            if heard["url"]
            else "no address on this machine in its output yet"
        )
        return "succeeded", (
            f"keeps running as command {command_id}, {where}. The user sees its page under "
            f"Preview and can stop it there; command_output reads what it prints later, and "
            f"stop_command stops it. Its last lines:\n{for_model(last)}"
        )

    def stop(self, command_id: str) -> bool:
        """Stop a command that keeps running, with what it started; False if none does."""
        serving = self._serving.get(command_id)
        if serving is None:
            return False
        serving[1].cancel()
        return True

    def serving_here(self, cid: str) -> list[tuple[str, str]]:
        """The commands that keep running in a conversation now: (id, command line)."""
        ids = [command_id for command_id, (at, _life) in self._serving.items() if at == cid]
        if not ids:
            return []
        with self._factory() as session:
            return [
                (command_id, line)
                for command_id, line in session.execute(
                    select(Command.id, Command.command).where(Command.id.in_(ids))
                )
            ]

    def server(self, cid: str, command_id: str) -> Command:
        """A command that keeps running (or did) in conversation `cid`, by its id - where it is
        none, a ToolError that names the ones running there now."""
        with self._factory() as session:
            command = session.scalar(
                select(Command)
                .join(Run, Run.id == Command.run_id)
                .where(
                    Command.id == command_id,
                    Run.conversation_id == cid,
                    Command.keep_running.is_(True),
                )
            )
            if command is not None:
                session.expunge(command)
                return command
        running = "; ".join(f"{one} ({line})" for one, line in self.serving_here(cid))
        raise ToolError(
            f"no command that keeps running in this conversation has the id {command_id!r}: "
            + (f"these run now - {running}" if running else "none runs now")
        )

    def output_of(self, command: Command, since: int | None) -> str:
        """command_output: what a command that keeps running (`server`) printed - hidden as it was
        kept (`_masks`), never the half line still held back - its newest OUTPUT_AT_MOST, or from
        `since` on; of one that ended, its record's."""
        command_id = command.id
        live = self._live.get(command_id) if command_id in self._serving else None
        text = live[1] if live is not None else command.output or ""
        total = len(text)
        start = max(0, total - OUTPUT_AT_MOST) if since is None else min(since, total)
        shown = text[start : start + OUTPUT_AT_MOST]
        end = start + len(shown)
        if live is not None:
            url = f", serving {command.preview_url}" if command.preview_url else ""
            state = f"keeps running{url}"
        else:
            code = f", exit code {command.exit_code}" if command.exit_code is not None else ""
            state = f"has ended ({command.status}{code})"
        said = f"Command {command_id} ({command.command}) {state}. Characters {start}-{end} of "
        said += f"{total} of its output"
        if end < total:
            said += f"; {total - end} more after them: call again with since={end}"
        elif live is not None:
            said += f"; for what it prints next, call again with since={end}"
        if command.output_truncated or text.endswith(TRUNCATED_NOTE):
            said += "; past 1 MiB its output is no longer kept"
        return f"{said}:\n{shown}" if shown else f"{said}: nothing new."

    async def stop_own(self, command: Command, agent_id: str) -> str:
        """stop_command: a command that keeps running (`server`), stopped with what it started -
        only one `agent_id` started itself (its card was its) - and waited for until it is on
        record ended, so that it can be started again at once (its port free, MAX_SERVING not
        reached)."""
        command_id = command.id
        if command.agent_id != agent_id:
            raise ToolError(NOT_YOURS.format(id=command_id))
        serving = self._serving.get(command_id)
        if serving is None and command.status in ("proposed", "approved"):
            waits = "its card waits for the user" if command.status == "proposed" else "starting"
            raise ToolError(f"command {command_id} has not started yet: {waits}")
        if serving is None:
            raise ToolError(f"command {command_id} is not running: it has ended ({command.status})")
        serving[1].cancel()
        await asyncio.wait({serving[1]}, timeout=KILL_SECONDS + DRAIN_GRACE_SECONDS)
        with self._factory() as session:
            status = session.get_one(Command, command_id).status
        if status == "running":
            return f"Command {command_id} ({command.command}) is being stopped: not ended yet."
        return f"Command {command_id} ({command.command}) is stopped ({status})."

    def stop_all(self, cid: str) -> None:
        """Stop every command of a conversation that keeps running, and turn down one still
        asked about."""
        for command_id, (at, _life) in list(self._serving.items()):
            if at == cid:
                self.stop(command_id)
        with self._factory() as session:
            asked = session.scalars(
                select(Command.id)
                .join(Run, Run.id == Command.run_id)
                .where(
                    Run.conversation_id == cid, Command.keep_running, Command.status == "proposed"
                )
            ).all()
        for command_id in asked:
            self.decide(command_id, "reject")

    async def shutdown(self) -> None:
        """KOLONİ closes: every command that keeps running is stopped, and recorded so."""
        self._closing = True
        lives = [life for _cid, life in self._serving.values()]
        for life in lives:
            life.cancel()
        await asyncio.gather(*lives, return_exceptions=True)

    async def ask_for(
        self,
        run_id: str,
        cid: str,
        agent_id: str,
        call_id: str,
        command: str,
        ask: bool = True,
        always: bool = False,
        held: bool = False,
        reads: bool = False,
        web_off: bool = False,
        cwd: str | None = None,
        judgement: dict | None = None,
        disposable: dict | None = None,
        why: str = "",
        park: Callable[[str], Awaitable[str]] | None = None,
    ) -> tuple[bool, str]:
        """A command a CLI is about to run with a tool of its own: put it on record,
        get it decided the way KOLONİ's own commands are, and say whether it may run.
        KOLONİ does not run it; the record is completed when the CLI reports the end.
        `always`: asked about at every level, whatever was allowed before - as one that
        names a secret file always is. `held`: as `command_out`'s; `web_off`: as `run`'s.
        `reads`: it only reads (`reads_here`), so below Full auto it is not asked. `cwd`:
        where the CLI says it runs, on the record as KOLONİ's own commands' is ("." for
        the root), so that the card is judged the same when it is read again. What it
        prints comes from the CLI, hidden there (`AgentRunner._observe_command`) for the
        screen and the record - the CLI's own model has read it already. `judgement`: as
        `run`'s (one it refused: (False, its id), as for the user's no); `disposable` too.
        `why`: KOLONİ's own reason for its card, for the family it is counted in (`card_reason`)
        - never the reason the CLI gave in words of its own, shown on its card all the same.
        `park`: as `run`'s - (False, its id) once it is parked."""
        with self._factory() as session:
            conversation = session.get_one(Conversation, cid)
            mode = conversation.permission_mode
            prefixes = [rule.prefix for rule in session.scalars(rules_here(conversation))]
            tests, judge, words, allows = session.execute(
                select(
                    Project.test_commands,
                    Project.full_auto_judge,
                    Project.judge_words,
                    Project.disposable_deletes,
                ).where(Project.id == conversation.project_id)
            ).one()
            # (judged in its folder, as `run`'s: `> settings.json` in `.claude` - denetim-010 #18)
            judged = with_cwd(command, cwd)
            gate = _gate_open(mode, judge and words, judgement, judge, judged)
            forbidden = _refuses(judgement, gate)
            # (as `run`'s: the user's own test command in its part's folder is not asked)
            own = project_map.own_test(tests, command, cwd)
            free = _free(ask, disposable, mode, allows)
            asks = ask and (
                always
                or names_secret(judged)
                or bool(standing_asked(judged, mode != "full_auto"))
                or judgement is not None
                and not gate
                or _lapsed(disposable, free)
                or (
                    mode != "full_auto"
                    and not (is_allowed(command, prefixes) or reads or own or free)
                )
            )
            row = Command(
                run_id=run_id,
                agent_id=agent_id,
                tool_call_id=call_id,
                command=command,
                cwd=cwd,
                location="host",
                timeout_seconds=0,
                origin="cli",
                web_off=web_off,
                status="refused" if forbidden else "parked" if asks and park else "proposed",
                ended_at=now() if forbidden else None,
                # (as `run`'s: what the check said holds only while its gate is open)
                judged=_kept(judgement, asks, gate),
                disposable=_noted(disposable, free and not asks),
                asked_reason=card_reason(
                    judged, mode != "full_auto", why, searched=held, web_off=web_off
                )
                if asks and not forbidden
                else None,
            )
            session.add(row)
            rule_kept_off(session, row, prefixes, mode != "full_auto")
            session.commit()
            command_id, payload = row.id, command_out(row, held=held)
        self.bus.emit(cid, run_id, "command.created", payload)
        if forbidden:
            return False, command_id
        if asks and park is not None:
            await park(command_id)
            return False, command_id
        if asks:
            decision = await self._wait_for_decision(
                run_id, cid, agent_id, command_id, payload["suggested_prefix"]
            )
            if decision == "reject":
                self._set(cid, command_id, status="rejected", ended_at=now())
                return False, command_id
        self._set(cid, command_id, status="running", started_at=now())
        return True, command_id

    def ending(self, root: Path) -> list[asyncio.Future]:
        """The kills of commands that ran in a folder which are not over, or failed:
        while there is one, a process may still be at work in that folder."""
        return [kill for kill, at in self._ending.items() if at == root]

    async def _end(self, running, kill: bool, root: Path) -> bool:
        """Kill (if asked) and release a command; returns whether Stop arrived meanwhile.

        Bounded and shielded: a kill that hangs, fails or is interrupted never keeps
        the caller from recording how the command ended. `root`: where it ran.
        """

        async def end() -> None:
            if kill:
                await running.kill()
            await running.close()

        task = asyncio.ensure_future(asyncio.wait_for(end(), KILL_SECONDS))
        if kill:
            self._ending[task] = root
            task.add_done_callback(
                lambda done: (
                    None if done.cancelled() or done.exception() else self._ending.pop(done, None)
                )
            )
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            return True  # the kill carries on in the background
        except Exception:
            pass  # could not kill it; the record still says what we know
        return False

    def close_open(
        self, run_id: str, cid: str, agent_id: str | None = None, calls: list[str] | None = None
    ) -> None:
        """Settle whatever a run (or one of its agents, or these of its tool calls) leaves
        behind: a command nobody decided on is rejected, one the user said yes to that never
        started - its agent never got its place, or its start never came back - is
        interrupted ("rejected" is the user's own no), and one still marked running (its task
        was cut short) is killed."""
        with self._factory() as session:
            query = select(Command).where(
                Command.run_id == run_id,
                Command.status.in_(("proposed", "approved", "running")),
            )
            if agent_id is not None:
                query = query.where(Command.agent_id == agent_id)
            if calls is not None:
                query = query.where(Command.tool_call_id.in_(calls))
            # (A command that keeps running outlives its turn: it is stopped by itself.)
            leftover = [c for c in session.scalars(query) if c.id not in self._serving]
            for command in leftover:
                if command.status == "running":
                    command.output = self._live.pop(command.id, (cid, command.output))[1]
                    command.status = "killed"
                else:
                    command.status = "interrupted" if command.status == "approved" else "rejected"
                command.ended_at = now()
            session.commit()
            payloads = [command_event(command) for command in leftover]
        for payload in payloads:
            self.bus.emit(cid, run_id, "command.updated", payload)

    # --- steps -----------------------------------------------------------------

    async def _wait_for_decision(
        self, run_id: str, cid: str, agent_id: str, command_id: str, rule: str
    ) -> str:
        """`rule`: what "Always run" puts on the conversation's allow list for it."""
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._decisions[command_id] = future
        self._update_run(run_id, cid, status="waiting_approval")

        def heard(word: str, waits: bool) -> None:
            # "Always run" is the user's word about later commands: it is kept the
            # moment it is said, whether or not this command ever gets to run.
            if word == "always":
                self._add_rule(cid, rule)
                self._always.add(command_id)
            elif word == "disposable":
                self._allow_disposable(cid, command_id)
            # A yes is on record the moment it is given - "approved", not the user's to
            # decide a second time - whether or not anything is waited for before the
            # command runs: a place for its agent, or its start (a container, a working
            # copy). And where its agent has to stand in line, a no is too: it needs no
            # place.
            if word != "reject":
                self._set(cid, command_id, status="approved")
            elif waits:
                self._set(cid, command_id, status="rejected", ended_at=now())

        try:
            if self.users_word:
                decision = await self.users_word(agent_id, future, heard)
            else:
                decision = await future
                heard(decision, False)
        finally:
            self._decisions.pop(command_id, None)
            # Also when the wait is cut short: the turn no longer waits on this one.
            self._update_run(run_id, cid, status="running")
        return decision

    def said_always(self, command_id: str) -> bool:
        """Whether the user answered this command's own card "Always run" (asked once: forgotten
        as it is read)."""
        if command_id not in self._always:
            return False
        self._always.discard(command_id)
        return True

    def _add_rule(self, cid: str, prefix: str) -> None:
        if not prefix:
            return
        with self._factory() as session:
            project_id = session.get_one(Conversation, cid).project_id
            session.add(AllowedCommand(conversation_id=cid, project_id=project_id, prefix=prefix))
            try:
                session.commit()
            except IntegrityError:  # the rule is already there
                session.rollback()
        self.emit_rules(cid)

    def _allow_disposable(self, cid: str, command_id: str) -> None:
        """ "Allow such deletes in this project" on a disposable delete's card: the project's own
        switch on (`Project.disposable_deletes`), from now on - only from a row KOLONİ found
        disposable (the API takes the word on no other)."""
        with self._factory() as session:
            if session.get_one(Command, command_id).disposable is None:
                return
            project_id = session.get_one(Conversation, cid).project_id
            session.get_one(Project, project_id).disposable_deletes = True
            session.commit()

    def emit_rules(self, cid: str) -> None:
        with self._factory() as session:
            rules = session.scalars(
                rules_here(session.get_one(Conversation, cid)).order_by(AllowedCommand.created_at)
            ).all()
            payload = {"rules": [allowed_command_out(rule) for rule in rules]}
        self.bus.emit(cid, None, "allowed_commands.updated", payload)

    async def _drain(
        self, cid: str, command_id: str, running, state: dict, heard: dict | None = None
    ) -> None:
        """Read the output to the end; keep and publish at most MAX_STORED_OUTPUT of it. Of
        a command that keeps running (`heard`), take the first address it serves on."""
        last_flush = time.monotonic()
        mask = self._masks[command_id]
        async for chunk in running:
            if state["truncated"]:
                continue  # keep reading so the process is never blocked on a full pipe
            if heard is not None:
                heard["at"] = time.monotonic()
            chunk = mask.feed(chunk)
            if not chunk:
                continue  # half a line: it waits for the rest (a secret may be cut in two)
            output = self._add_output(cid, command_id, chunk, state)
            if heard is not None and heard["url"] is None:
                self._look_for_address(cid, command_id, output, heard)
            if time.monotonic() - last_flush >= FLUSH_SECONDS:
                last_flush = time.monotonic()
                self._save_output(command_id, output)

    def _add_output(self, cid: str, command_id: str, chunk: str, state: dict) -> str:
        """Keep and publish a piece of a command's output, at most MAX_STORED_OUTPUT of it
        in all; returns the output so far."""
        current = self._live[command_id][1]
        room = MAX_STORED_OUTPUT - len(current)
        if len(chunk) > room:
            chunk = chunk[:room] + TRUNCATED_NOTE
            state["truncated"] = True
        self._live[command_id] = (cid, current + chunk)
        self.bus.emit_transient(cid, "command.output", {"command_id": command_id, "text": chunk})
        return current + chunk

    def _look_for_address(self, cid: str, command_id: str, output: str, heard: dict) -> None:
        # (From a little before where the last look ended: an address cut by a chunk is whole.)
        # shortcut: the address is only what the output says - a server that prints none stays
        # "starting"; find the loopback port its process tree listens on if one is seen (B-351).
        url = preview_url(output[max(0, heard["scanned"] - 512) :], heard["closed"])
        heard["scanned"] = len(output)
        if url:
            heard["url"] = url
            self._set(cid, command_id, preview_url=url)

    def _save_output(self, command_id: str, output: str) -> None:
        with self._factory() as session:
            session.get_one(Command, command_id).output = output
            session.commit()

    def _finish(
        self, cid: str, command_id: str, status: str, code: int | None, truncated: bool
    ) -> str:
        output = self._live.pop(command_id, (cid, ""))[1]
        self._set(
            cid,
            command_id,
            status=status,
            exit_code=code if status == "exited" else None,
            output=output,
            output_truncated=truncated,
            ended_at=now(),
        )
        return output

    def _set(self, cid: str, command_id: str, **fields) -> None:
        with self._factory() as session:
            command = session.get_one(Command, command_id)
            for key, value in fields.items():
                setattr(command, key, value)
            session.commit()
            run_id, payload = command.run_id, command_event(command)
        self.bus.emit(cid, run_id, "command.updated", payload)
