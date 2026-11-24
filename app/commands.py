"""Rules about shell commands: allow-list matching and what the model gets to see."""

import contextlib
import fnmatch
import glob
import itertools
import ntpath
import os
import posixpath
import re
import shlex
import sys
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from pathlib import Path, PureWindowsPath
from typing import Literal
from urllib.parse import quote

from sqlalchemy import or_, select

from app import raw
from app.copies import LINKED, folders
from app.db.models import AllowedCommand, AllowedWeb
from app.workspace import (
    INSTRUCTION_FILES,
    NOT_WRITTEN_UNATTENDED,
    SECRET_FOLDERS,
    Workspace,
    _name,
    is_secret,
    secret_in_project,
)

MAX_STORED_OUTPUT = 1024 * 1024
MODEL_HEAD, MODEL_TAIL = 2000, 6000

# A command the allow list may cover is made of these characters only: words, paths,
# flags and simple quotes. Everything a shell could use to run a second command,
# substitute a value or redirect output (; | & < > ( ) { } $ ` % # ! * ~ and line
# breaks) is absent, so the list does not have to chase each shell's syntax.
_PLAIN = re.compile(r"""[A-Za-z0-9 _\-./\\:=,+'"]*""")

# Programs whose first argument names what they actually do.
_SUBCOMMAND_TOOLS = frozenset(
    {
        "git",
        "npm",
        "pnpm",
        "yarn",
        "uv",
        "poetry",
        "pipenv",
        "pdm",
        "hatch",
        "pip",
        "cargo",
        "dotnet",
        "docker",
        "go",
    }
)
# ...and those where the task is one word further on: `npm run build`, `uv run pytest`.
_RUNNERS = frozenset({("npm", "run"), ("pnpm", "run"), ("yarn", "run"), ("uv", "run")})
# ...of them, those whose `run` runs any program of an environment (`poetry run python x.py`): a
# rule must name the program, never the bare tool (W8).
_ENV_RUNS = frozenset({("uv", "run"), ("poetry", "run"), ("pipenv", "run"), ("pdm", "run")})
_ENV_RUNS |= {("hatch", "run")}
_RUNNERS |= _ENV_RUNS
_RUNNER_PROGRAMS = frozenset({"npx", "pnpx", "uvx", "bunx"})
# 0.1.7's Code style and types: the linters and type checkers KOLONİ runs on a turn's files. A
# rule for one is its line's fixed part - the program and its options, up to the first file it is
# given (`./x`) - never the bare program: what it reads and where it writes is in those options.
_LINTERS = frozenset({"ruff", "mypy", "eslint", "tsc"})
# ...and subcommands that do the same: a rule must name the package (`uv tool run x`: one
# word further on).
_EXECUTORS = {
    ("npm", "exec"): 3,
    ("npm", "x"): 3,
    ("pnpm", "dlx"): 3,
    ("pnpm", "exec"): 3,
    ("yarn", "dlx"): 3,
    ("yarn", "exec"): 3,
    ("uv", "tool"): 4,
    ("bun", "x"): 3,
}
# `corepack x ...` runs the package manager x as it is: a rule for it is x's, past `corepack`.
_COREPACK_RUNS = frozenset({"npm", "npx", "pnpm", "pnpx", "yarn"})
# These run whatever they are handed, so a rule must name the script or module too - by
# any version in their name (`python3.12`, `pythonw`, `node22`); `.exe` is dropped first.
_INTERPRETER = re.compile(
    r"(python|pythonw|pyw?|node|nodejs|deno|bun|ruby|perl|php|rscript|lua|luajit|tclsh)[\d.]*w?"
)
# A rule for a shell would allow anything at all.
_SHELLS = frozenset({"cmd", "powershell", "pwsh", "sh", "bash", "zsh", "wsl"})


def is_plain(command: str) -> bool:
    """Whether a command is a single plain invocation the allow list may cover."""
    return _PLAIN.fullmatch(command) is not None


def _words(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=False)
    except ValueError:  # unbalanced quotes
        return command.split()


def _program(word: str) -> str:
    """`C:\\x\\Python.EXE` and `.venv/Scripts/python` both name the program `python`."""
    name = re.split(r"[\\/]", word.strip("'\""))[-1].lower()
    # (`npm.cmd ci` is npm's: a shim's name is the program's. A bare `cat.cmd a.py` reads as cat:
    # PowerShell and sh find a bare name on PATH only, and so does cmd.exe where KOLONİ runs it -
    # `host.command_env` sets NoDefaultCurrentDirectoryInExePath, W1)
    # (W8: `npx.ps1`, npm's PowerShell shim, is npx too)
    return name.removesuffix(".exe").removesuffix(".cmd").removesuffix(".bat").removesuffix(".ps1")


def suggest_prefix(command: str) -> str:
    """The allow-list rule to offer for a command, or "" when none should be offered (`_offer`) -
    nor where the command's words past it hold an option no rule covers (`_past_the_rule`: the
    rule would not cover the very line it was offered for)."""
    offered = _offer(command)
    normal = " ".join(command.split())
    extra = normal[len(offered) :].split() if normal.startswith(offered) else normal.split()
    return "" if offered and _past_the_rule(normal.split(), extra) else offered


def _offer(command: str) -> str:  # noqa: C901
    """The allow-list rule to offer for a command, or "" when none should be offered.

    A rule names one program and one task. Nothing is offered where the shortest
    honest rule would still mean "run anything": shells, interpreters given inline
    code, or commands that use shell syntax - nor where it deletes, cannot be undone or
    sends something off this machine (`harms`: asked at every level, a rule would be a lie).
    """
    # shortcut: such a rule can still be written by hand (`tidy_rule`) and serves a trigger's
    # exact match (`is_exactly`) - unwatched turns as before; refuse it there too if asked.
    # (Nor for any delete at all, whatever it deletes: a rule names a program, not its paths.)
    if (
        not is_plain(command)
        or is_wrapped(command)
        or harms(command)
        or _git_runs(command)
        or (_fetch_writes(command))
        or any(_program(words[0]) in _DELETERS for words in _commands_in(command) if words)
        or elsewhere(command)
    ):
        return ""
    words = _words(command.strip())
    if not words:
        return ""
    program = _program(words[0])
    rest = words[1:]
    if program in _SHELLS:
        return ""
    if program == "corepack":  # (never the bare `corepack`: it runs any package manager)
        inner = _offer(" ".join(rest)) if rest and _program(rest[0]) in _COREPACK_RUNS else ""
        return f"{words[0]} {inner}" if inner else ""
    if rest and (need := _EXECUTORS.get((program, rest[0]))) is not None:
        named = len(words) >= need and not any(w.startswith("-") for w in words[2:need])
        return " ".join(words[:need]) if named else ""  # (`bun x tsc` too: bun is no interpreter)
    if program in _LINTERS:
        return " ".join(
            words[: next((at for at, w in enumerate(words) if at and w.startswith("./")), None)]
        )
    if _INTERPRETER.fullmatch(program):
        if len(rest) >= 2 and rest[0] == "-m":
            return " ".join(words[:3])
        if rest and not rest[0].startswith("-"):
            return " ".join(words[:2])
        return ""
    if program in _RUNNER_PROGRAMS:
        return " ".join(words[:2]) if rest and not rest[0].startswith("-") else ""
    if program in _SUBCOMMAND_TOOLS:
        if not rest:
            return words[0]
        if rest[0].startswith("-"):
            return ""  # options before the subcommand can change what it runs
        if (program, rest[0]) in _RUNNERS:
            task_named = len(rest) >= 2 and not rest[1].startswith("-")
            if task_named and _INTERPRETER.fullmatch(_program(rest[1])):  # (`uv run python -m x`)
                inner = _offer(" ".join(rest[1:]))
                return f"{words[0]} {rest[0]} {inner}" if inner else ""
            return " ".join(words[:3]) if task_named else ""
        return " ".join(words[:2])
    return words[0]


# Words that run whatever follows them: a rule for one of these would cover anything.
_WRAPPERS = frozenset(
    {
        "env",
        "timeout",
        "xargs",
        "sudo",
        "nohup",
        "nice",
        "time",
        "watch",
        "exec",
        "eval",
        "command",
        "builtin",
        "start",
        "call",
        # PowerShell's (commands run in it on Windows), by name and alias; and the dot and
        # `source`, which run whatever script or command they are given.
        "iex",
        "invoke-expression",
        "icm",
        "invoke-command",
        "saps",
        "start-process",
        "sajb",
        "start-job",
        "ihy",
        "r",
        "invoke-history",
        ".",
        "source",
        # ...and what else on Windows runs a command line, a script or a file it is given.
        "forfiles",
        "wmic",
        "iwmi",
        "invoke-wmimethod",
        "icim",
        "invoke-cimmethod",
        "conhost",
        "schtasks",
        "runas",
        "ii",
        "invoke-item",
        "ipmo",
        "import-module",
        "start-threadjob",
        "cscript",
        "wscript",
        "mshta",
        "rundll32",
        "regsvr32",
        "msiexec",
        "explorer",
        # ...and elsewhere.
        "setsid",
        "stdbuf",
        "ionice",
        "flock",
        "su",
        "doas",
        "busybox",
        "ssh",
    }
)
# K-r132: a shell's or a wrapper's options that take the next word for their value (`nice -n
# 5`, `xargs -a f`), those whose value is a command line of its own (`env -S 'rm x'`, `su -c`,
# `sh -c`), and those known to take none (cmd's and PowerShell's in lower case: any case is
# theirs). Any other option might take one: what it hands on is judged both ways.
_TAKES_VALUE = {
    program: frozenset(options.split())
    for program, options in {
        "timeout": "-s --signal -k --kill-after",
        "nice": "-n --adjustment",
        "env": "-u --unset -C --chdir",
        "xargs": "-a --arg-file -n --max-args -I -d --delimiter -L --max-lines -P --max-procs -s "
        "--max-chars -E",
        "sudo": "-u --user -g --group -C -D --chdir -p --prompt -r -t -T -U",
        "ionice": "-c --class -n --classdata -p --pid -P --pgid -u --uid",
        "stdbuf": "-i -o -e",
        "exec": "-a",
        "time": "-f --format -o --output",
        "watch": "-n --interval",
        "flock": "-w --timeout -E --conflict-exit-code",
        "su": "-s --shell -g --group -G --supp-group -w --whitelist-environment",
        "wsl": "-d --distribution -u --user --cd --shell-type",
        "sh": "-o +o -O +O --rcfile --init-file",
        "bash": "-o +o -O +O --rcfile --init-file",
        "zsh": "-o +o",
        "powershell": "-executionpolicy -ep -ex -exec -windowstyle -w -win -encodedcommand -e -ec "
        "-enc -inputformat -outputformat -version -configurationname "
        "-workingdirectory -wd -settingsfile",
    }.items()
}
_TAKES_LINE = {
    program: frozenset(options.split())
    for program, options in {
        "env": "-S --split-string",
        "flock": "-c --command",
        "su": "-c --command",
        "sh": "-c",
        "bash": "-c",
        "zsh": "-c",
        "schtasks": "/tr /TR /Tr -tr",
    }.items()
}
_TAKES_NONE = {
    program: frozenset(options.split())
    for program, options in {
        "timeout": "--preserve-status --foreground -v --verbose",
        "env": "- -i --ignore-environment -0 --null -v --debug",
        "xargs": "-0 --null -r --no-run-if-empty -t --verbose -p --interactive -x --exit -o "
        "--open-tty -i -e -l",
        "sudo": "-E -H -n -S -b -i -s -k -A -P --preserve-env",
        "ionice": "-t --ignore",
        "exec": "-c -l",
        "time": "-p -v --verbose -a --append",
        "command": "-v -V -p",
        "watch": "-t -x --exec -b -e -g -c -p",
        "wsl": "-e --exec",
        "flock": "-s --shared -x -e --exclusive -u --unlock -n --nb --nonblock -o --close -F "
        "--no-fork",
        "su": "- -l --login -m -p --preserve-environment -P --pty",
        "cmd": "/c /k /s /q /d /a /u",  # (`/v:on`, `/e:on`, `/t:0a` hold theirs after the colon)
        "sh": "-e -x -u -l -i -s -v -n -f -a --login --norc --noprofile --posix",
        "bash": "-e -x -u -l -i -s -v -n -f -a --login --norc --noprofile --posix",
        "zsh": "-e -x -u -l -i -s -v -n -f",
        "powershell": "-command -c -noprofile -nop -noninteractive -noni -nologo -nol -noexit "
        "-noe -sta -mta -file -f -login -l",
    }.items()
}
for _table in (_TAKES_VALUE, _TAKES_NONE):
    _table["pwsh"] = _table["powershell"]
# The words a wrapper takes before the command it runs (`timeout 5`, `flock x.lock`, `su root`).
_POSITIONAL = {"timeout": 1, "flock": 1, "su": 1}
_OPTION = re.compile(r"[-+]\S*|/[A-Za-z]\w*(?::\S*)?")  # (`-Command`, `+o`, `/wait`, `/v:on`)
_ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=")  # `A=1 cmd`, `env A=1 cmd`
# How many ways a part's unknown options are read at most: past that it is asked (`_danger_of`),
# so padding a line with them (`nice -x nice -x ...`) neither hides a delete nor stalls the check.
MAX_READINGS = 8
MAX_OTHER_READINGS = 64  # (of a whole line, `_commands_in`)
UNREAD = "koloni:unread"  # (the program a part is read as past either)
# K-okuyucu-3 round 3: what runs a program it is given (`poetry run cmd /c rd /s /q src`, `uv run
# rm -rf x`, `npx x`) - what it runs is read as a line of its own too (`_runner_lines`): its harm, a
# shell, a wrapper. `cargo run` / `dotnet run` hand on only what follows their `--`.
_RUNS_PROGRAM = frozenset(
    {
        ("poetry", "run"),
        ("uv", "run"),
        ("pipenv", "run"),
        ("pdm", "run"),
        ("hatch", "run"),
        ("rye", "run"),
        ("conda", "run"),
        ("pnpm", "exec"),
        ("pnpm", "dlx"),
        ("yarn", "exec"),
        ("yarn", "run"),
        ("yarn", "dlx"),
        ("bun", "x"),
        ("npm", "exec"),
        ("npm", "x"),
    }
)
_RUNS_AFTER_DASHES = frozenset({("cargo", "run"), ("dotnet", "run")})


def _runner_lines(words: list[str]) -> list[str]:
    """What a runner runs (`_RUNS_PROGRAM`, `npx` and its kin, `cargo run --`), as lines: from its
    first word that is no option - its own options' values skipped (`_RUNNER_VALUES`); after one
    it does not know, with no `=`, from the word after that one too (fails closed: `uv run --x 1
    rm -rf y`). What follows is the program's own (`uv run ruff format .`: ruff's words)."""
    program = _program(words[0])
    rest: list[str] = words[1:] if program in _RUNNER_PROGRAMS else []
    for name, verb in [] if rest else _verbs(words):
        pair, at = (name, verb.casefold()), words.index(verb) if verb in words else -1
        if at > 0 and pair in _RUNS_AFTER_DASHES and "--" in words[at:]:
            dashes = words.index("--", at)
            return [" ".join(_quoted_word(word) for word in words[dashes + 1 :])][
                : 1 if dashes + 1 < len(words) else 0
            ]
        if at > 0 and pair in _RUNS_PROGRAM:
            rest, program = words[at + 1 :], name
            break
    values, at, unknown = _RUNNER_VALUES.get(program, frozenset()), 0, False
    while at < len(rest) and rest[at].startswith("-"):
        unknown = rest[at] not in values and "=" not in rest[at] and rest[at] != "--"
        at += 2 if rest[at] in values else 1
    starts = (
        [at, at + 1]
        if unknown and at + 1 < len(rest) and not rest[at + 1].startswith("-")
        else [at]
    )
    return [
        " ".join(_quoted_word(word) for word in rest[one:]) for one in starts if one < len(rest)
    ]


# uv's options of `uv run` and `uvx` that take a value: its index, resolver, build, cache and
# global ones besides its own (`--color never --index-strategy x rm -rf .` hid the program: two
# unknown ones in a row). Never a flag here - `--isolated rm` would hide rm as its value; one uv
# does not know is refused by uv itself (`--python-preference`, `--preview-features`, `uv run`'s
# `--from`: not in 0.10.4's help, kept). shortcut: as uv 0.10.4's `uv run --help` and `uv tool
# run --help` list them (every `<value>` option in, no flag); a later uv's new value option, two
# in a row, still hides the program - read each unknown option both ways if one is met.
_UV_VALUES = (
    "-p --python -w --with --with-editable --with-requirements --env-file --index -i --index-url "
    "--extra-index-url --default-index -f --find-links --index-strategy --keyring-provider "
    "--resolution --prerelease --fork-strategy --exclude-newer --exclude-newer-package -C "
    "--config-setting --config-settings-package --no-build-isolation-package --no-build-package "
    "--no-binary-package --no-sources-package --link-mode --refresh-package -P --upgrade-package "
    "--reinstall-package --allow-insecure-host --cache-dir --color --config-file "
    "--python-preference --preview-features --directory --project --python-platform"
)
# The runners' own options that take the next word for their value (`conda run -n env python`).
_RUNNER_VALUES = {
    program: frozenset(options.split())
    for program, options in {
        "uv": f"{_UV_VALUES} --package --extra --no-extra --group --no-group --only-group --from",
        "conda": "-n --name -p --prefix",
        "poetry": "-C --directory -P --project",
        "pdm": "-p --project",
        "hatch": "-e --env",
        "pnpm": "-C --dir --filter -F",
        "yarn": "--cwd",
        "npm": "--package -w --workspace --prefix -C",
        **dict.fromkeys(
            ("npx", "pnpx", "bunx"),
            "-p --package -c --call -w --workspace --cache "
            "--registry --prefix --userconfig --node-options --loglevel",
        ),
        "uvx": f"{_UV_VALUES} --from -c --constraints -b --build-constraints --overrides "
        "--torch-backend",
    }.items()
}


def _quoted_word(word: str) -> str:
    return f'"{word}"' if re.search(r"\s", word) else word


def _unwrapped(words: list[str]) -> list[list[str]]:  # noqa: C901
    """What a part runs, its shells and wrappers in front taken off with the options, values and
    variables they take (`timeout 5`, `nice -n 5`, `env A=1`, `cmd /v:on /c`) - first; then the
    command lines handed in an option or a variable (`env -S 'rm x'`, `sh -c 'A=1 rm x'`, each
    one word for `_commands_in` to look into), and, for an option not known here, what runs were
    it to take the next word as its value: such a part keeps the danger of anything it could
    run. Past MAX_READINGS, [UNREAD]."""
    found: list[list[str]] = []
    lines_handed: list[list[str]] = []
    todo, seen, unread = [(0, "")], {(0, "")}, False
    while todo:
        at, program = todo.pop()
        while True:
            if program:
                values, nones = _TAKES_VALUE.get(program, ()), _TAKES_NONE.get(program, ())
                lines, positional = _TAKES_LINE.get(program, ()), _POSITIONAL.get(program, 0)
                while True:
                    while at < len(words) and _OPTION.fullmatch(words[at]):
                        option = (
                            words[at].casefold()
                            if program in ("cmd", "powershell", "pwsh")
                            else words[at]
                        )
                        at += 1
                        if option == "--":
                            break
                        # A line in its value (`--split-string='rm x'`, `-S'rm x'`): split at
                        # its spaces by `_words`, so the words after it are taken in too.
                        given = re.sub(r"^[-+/][\w-]*[=:]?", "", option)
                        if " " in given or given.startswith(("'", '"')):
                            lines_handed.append([" ".join([given, *words[at:]]).strip("'\"")])
                        if option in lines and at < len(words):
                            lines_handed.append([words[at]])
                            at += 1
                        elif option in values:
                            at += 1
                        elif option not in nones and not re.search(r"[=:]", option):
                            if (at + 1, program) in seen:
                                continue
                            if len(seen) > MAX_READINGS:
                                unread = True
                                continue
                            seen.add((at + 1, program))
                            todo.append((at + 1, program))
                    if not positional or at >= len(words):
                        break
                    at, positional = at + 1, positional - 1  # (its options may come after)
            while at < len(words) and _ASSIGNMENT.match(words[at]):
                if " " in words[at]:  # (`sh -c 'A=1 rm x'`: the quoted line, as one word)
                    lines_handed.append([words[at]])
                at += 1
            if at >= len(words) or _program(words[at]) not in _SHELLS | _WRAPPERS:
                break
            program, at = _program(words[at]), at + 1
        found.append(words[at:])
        if at < len(words):  # (what a runner it reaches runs: a line of its own too)
            lines_handed += [[line] for line in _runner_lines(words[at:])]
    return [*found, *lines_handed, *([[UNREAD]] if unread else [])]


def _hands_on(command: str) -> bool:
    """Whether a command's program runs what its arguments name: an interpreter, a
    package runner (`npx`, `npm exec`; `corepack` before one; `poetry run`). A rule for one
    covers a command only where it names as much as "Always run" would offer now
    (`suggest_prefix`): one stored before, or written by hand, for the program alone covers
    nothing."""
    words = _words(command.strip())
    if not words:
        return False
    program = _program(words[0])
    return bool(
        _INTERPRETER.fullmatch(program)
        or program in _RUNNER_PROGRAMS
        or program == "corepack"
        or (len(words) > 1 and (program, words[1]) in {*_EXECUTORS, *_ENV_RUNS})
    )


def is_wrapped(command: str) -> bool:
    """Whether a command starts by setting a variable or with a word that runs another
    command (`VAR=x cmd`, `env cmd`, `timeout 5 cmd`): what really runs comes later."""
    words = _words(command.strip())
    if not words:
        return False
    first = words[0].strip("'\"")
    return "=" in first or _program(first) in _WRAPPERS


def _long(word: str, *names: str) -> bool:
    """Whether an option word is one of these long options by any prefix of it (`--ha`,
    `--upload-p`: git and getopt take one cut short); an ambiguous one too: it only over-asks."""
    name = re.split(r"[=:]", word[2:], maxsplit=1)[0] if word.startswith("--") else ""
    return bool(name) and any(full.startswith(name) for full in names)


# Security review 0.1.0, finding 2: the git commands a rule may cover (others - `filter-branch`,
# `bisect`, `format-patch`, `difftool`, `archive`, `update-ref`... - are asked every time); and
# in them what makes git run a program or write a file it is told of (`git grep -O<cmd>`,
# `--upload-pack=`, `--output=`): long options in any, short ones in these; and any option
# before git's command (`-c core.fsmonitor=x`, `--exec-path`).
_GIT_RULED = frozenset(
    {
        "status",
        "diff",
        "log",
        "show",
        "add",
        "commit",
        "fetch",
        "pull",
        "clone",
        "rebase",
        "grep",
        "checkout",
        "switch",
        "branch",
        "push",
        "merge",
        "stash",
        "tag",
        "remote",
        "restore",
        "rm",
        "mv",
        "reset",
        "blame",
        "shortlog",
        "describe",
        "rev-parse",
        "ls-files",
        "cherry-pick",
        "ls-remote",
        "rev-list",
        "cat-file",
        "reflog",
        "worktree",
        "submodule",
    }
)
# ...and of these, only the forms that look (their first word past the options; "" for none).
_GIT_RULED_ONLY = {
    "reflog": ("", "show", "list"),
    "worktree": ("", "list"),
    "submodule": ("", "status"),
}
_GIT_RUNS = (
    "open-files-in-pager",
    "upload-pack",
    "receive-pack",
    "exec",
    "extcmd",
    "output",
    "output-directory",
    "template",
    "config",
)
_GIT_RUNS_SHORT = {"grep": "O", "clone": "uc", "rebase": "x", "ls-remote": "u"}
_GIT_STRATEGIES = frozenset({"ort", "recursive", "resolve", "octopus", "ours", "subtree"})


def _git_runs(command: str) -> bool:
    """Whether a git line names no command a rule may cover (`_GIT_RULED`), an option before it,
    or one that runs a program or writes a file it is told of (`_GIT_RUNS`): no rule covers it,
    and none is offered."""
    words = [re.sub(r"['\"]", "", word) for word in _words(command.strip())]
    if not words or _program(words[0]) != "git":
        return False
    if len(words) < 2 or words[1] not in _GIT_RULED:
        return True
    sub, args = words[1], words[2:]
    if (
        sub in _GIT_RULED_ONLY
        and next((a for a in args if not a.startswith("-")), "") not in _GIT_RULED_ONLY[sub]
    ):
        return True
    for at, a in enumerate(args if sub in ("merge", "pull", "rebase") else ()):
        # (a strategy not git's own runs `git-merge-<name>` from PATH)
        after = args[at + 1] if at + 1 < len(args) else ""
        if _long(a, "strategy") or _cluster(a, "s"):
            name = a.partition("=")[2] if a.startswith("--") else a[a.index("s", 1) + 1 :]
            if (name or after) not in _GIT_STRATEGIES:
                return True
    return any(
        _long(a, *_GIT_RUNS) or any(_cluster(a, letter) for letter in _GIT_RUNS_SHORT.get(sub, ""))
        for a in args
    )


# Security review 0.1.0, finding 5: what makes a fetcher write a file or read its options from one
# (`curl -o`, `-K`, `wget -P`): short ones in a cluster (`-sSo`), long ones by prefix; and
# PowerShell's `-OutFile`, by any prefix of it (`-OutF`), in any case.
_FETCH_WRITES = {
    "curl": (
        "oODKc",
        (
            "output",
            "output-dir",
            "remote-name",
            "remote-name-all",
            "config",
            "dump-header",
            "cookie-jar",
            "trace",
            "trace-ascii",
            "stderr",
            "libcurl",
            "etag-save",
            "etag-compare",
            "hsts",
            "alt-svc",
            "ssl-sessions",
            "proto-default",
        ),
    ),
    "wget": (
        "oOaPe",
        (
            "output-document",
            "output-file",
            "append-output",
            "directory-prefix",
            "execute",
            "config",
            "use-askpass",
            "save-cookies",
            "warc-file",
            "rejected-log",
            "hsts-file",
        ),
    ),
}
_PS_FETCHERS = frozenset({"invoke-webrequest", "iwr", "invoke-restmethod", "irm"})


def _fetch_writes(command: str) -> bool:
    """Whether a fetcher's line does more than fetch: it writes a file, reads its options from
    one or sends something (`_only_fetches`). A rule for it is offered for a GET, so it covers
    that and nothing more. shortcut: wget writes the file it fetches into its folder unasked."""
    words = [re.sub(r"['\"]", "", word) for word in _words(command.strip())]
    program = _program(words[0]) if words else ""
    if any("file:" in word.casefold() for word in words[1:]):  # (`--url=file:///x` too)
        return program in _PS_FETCHERS or program in _FETCH_WRITES  # (it reads a local file)
    if program in _PS_FETCHERS:
        return not _only_fetches(words) or any(
            word.startswith("-") and _long("--" + word.lstrip("-").casefold(), "outfile")
            for word in words[1:]
        )
    if program not in _FETCH_WRITES:
        return False
    short, long = _FETCH_WRITES[program]
    if program == "wget":  # (`-qO-`, `-O -`: to the output, no file)
        words = [
            word[:-2]
            if word.endswith("O-") and word.startswith("-")
            else word[:-1]
            if (_cluster(word, "O") and word.endswith("O") and after == "-")
            else word
            for word, after in zip(words, [*words[1:], ""], strict=True)
        ]
    # (`-G -d @file` reads a file into the address: `@` is not `_PLAIN`, so no rule covers it)
    return not _only_fetches(words) or any(
        _long(word, *long) or any(_cluster(word, letter) for letter in short) for word in words[1:]
    )


def matches(command: str, prefix: str) -> bool:
    """Whether an allow-list rule covers a command. Only a plain command can match, and never
    one that deletes or cannot be undone (`danger`), makes git run a program (`_git_runs`) or a
    fetcher write a file (`_fetch_writes`) - nor one whose words past the rule hold an option
    that runs another program, fetches code or writes outside (`_past_the_rule`)."""
    if (
        not prefix
        or not is_plain(command)
        or is_wrapped(command)
        or _in_a_shell(command)
        or danger(command)
        or _git_runs(command)
        or _git_runs(prefix)
        or _fetch_writes(command)
        or elsewhere(command)
    ):
        return False
    if _hands_on(command):
        offered = _offer(command)
        if not offered or len(prefix.split()) < len(offered.split()):
            return False
    normal = " ".join(command.split())
    return (normal == prefix or normal.startswith(prefix + " ")) and not _past_the_rule(
        normal.split(), normal[len(prefix) :].split()
    )


# K-okuyucu-3: options that make a program run another one, fetch code or write outside the
# folder - a rule ("Always run") for the program does not cover a line that adds one past it
# (`_past_the_rule`): asked as if no rule matched. The rule names the program; these change what
# it runs. Past a rule that names a runner's package (`npx tsc`, `pnpm dlx x`, `bunx x`) the words
# are the tool's own - those runners read their options before it - so theirs are not here; npm
# exec reads `--package` anywhere (npm's row), and a hand-written `uv run` rule covers uv's own.
_PAST_A_RULE = {
    # emptied first (a delete: `_deletes_basetemp`); a plugin loaded by its name; which
    # conftest.py and ini file run; settings of another's (its addopts: any of these again)
    "pytest": (
        "--basetemp",
        "-p",
        "--rootdir",
        "--confcutdir",
        "-o",
        "--override-ini",
        "-c",
        "--config-file",
    ),
    "go": ("-exec", "-toolexec", "-C"),  # (a program run on what it builds; another module)
    "cargo": ("--config", "--manifest-path"),  # (any setting: a runner, a linker; another crate)
    # code run before the build; another project's build
    **dict.fromkeys(
        ("gradle", "gradlew"), ("-I", "--init-script", "-p", "--project-dir", "-b", "--build-file")
    ),
    # scripts run by another program; another folder's package.json or config; a package
    # fetched; node given code to load; a shell line `npm exec` runs (`-c`, `--call`)
    "npm": (
        *("--script-shell", "--prefix", "-C", "--package", "--userconfig", "--node-options"),
        *("-c", "--call"),
    ),
    "make": ("SHELL=", "-f", "--file"),  # (recipes run by another program; another makefile)
    "tox": ("-c",),  # (another tox.ini: its commands)
    "mvn": ("-Dmaven.ext",),  # (an extension's classes loaded into the build)
    # a package fetched to run (`_fetches_to_run`): `uv run --with x`, `pipx run --spec x`
    "uv": ("-w", "--with", "--from"),
    "uvx": ("-w", "--with", "--from"),
    "pipx": ("--spec",),
    # 0.1.7's Code style and types: another config (a plugin it loads is code), a rules folder or
    # plugins found elsewhere, another Python run for it; a fix written into the files; a
    # formatter (but its own, `_ESLINT_FORMATS`), plugin or parser loaded by name or path; eslint's
    # `--init` and `--inspect-config`, which fetch a package and run it (npm init, npx), and its
    # suppressions file written; mypy's stubs installed (pip); tsc made to write - its build info,
    # a trace, its output, a build (but `--incremental false`, `--composite false`, `--noEmit`,
    # `--generateTrace null`, which Code style's own line gives: `_harmless`)
    "ruff": ("--config", "--fix", "--fix-only", "--unsafe-fixes", "--add-noqa"),
    "mypy": ("--config-file", "--python-executable", "--install-types"),
    "eslint": (
        *("-c", "--config", "--resolve-plugins-relative-to", "--rulesdir"),
        *("-f", "--format", "--plugin", "--parser", "--fix", "--init", "--inspect-config"),
        *("--suppress-all", "--suppress-rule", "--prune-suppressions"),
    ),
    "tsc": ("--incremental", "--composite", "--noEmit", "--generateTrace", "-b", "--build"),
}
_ESLINT_FORMATS = frozenset({"stylish", "json", "json-with-metadata", "html"})
# ...these only where their value leads out of the folder (a report written there)...
_PAST_A_RULE_OUT = {
    "pytest": ("--junitxml", "--junit-xml"),
    # (0.1.7: a report, a cache or a build put elsewhere; tsc on another folder's config, its
    # trace or profile - tsc reads its options in any case, `--OUTDIR` too: measured, 5.9)
    "ruff": ("--output-file", "-o", "--cache-dir"),
    "mypy": (
        *("--cache-dir", "--junit-xml", "--html-report", "--txt-report", "--xml-report"),
        *("--xslt-html-report", "--xslt-txt-report", "--cobertura-xml-report"),
        *("--linecount-report", "--linecoverage-report", "--lineprecision-report"),
        *("--any-exprs-report", "--memory-xml-report"),
    ),
    "eslint": (
        *("--output-file", "-o", "--cache-location", "--cache-file"),
        "--suppressions-location",
    ),
    "tsc": (
        *("-p", "--project", "--outDir", "--outFile", "--tsBuildInfoFile", "--declarationDir"),
        "--generateCpuProfile",
    ),
}
# ...the short options that take a value where a program bundles its short ones (`pytest -qo x`:
# the bundle ends at one of these; elsewhere only the first letter counts, `-pfoo`)...
_SHORT_VALUES = {
    "pytest": "kmnrW",
    "make": "CIjloW",
    "tox": "e",
    "uv": "p",
    "uvx": "p",
    "gradle": "DPx",
    "gradlew": "DPx",
}
# ...and what of pytest's `-p` / `-o` changes nothing of what runs: a plugin turned off
# (`-p no:x`), how it logs.
_HARMLESS_INI = frozenset({"log_cli", "log_cli_level", "log_level", "console_output_style"})
# ...and a shell handed a line (`... bash -c "x"`, `cmd /c x`), anywhere past the rule.
_SHELL_LINE = re.compile(
    r"(?i)(?:^|\s)['\"]?(?:\S*[\\/])?(?:sh|bash|zsh|dash|cmd|powershell|pwsh)"
    r"(?:\.exe)?['\"]?\s+[-/](?:c|command)\b"
)


# W7c: a node runner's own options past its rule. npm reads its settings from any of them -
# `--globalconfig=x` a file of them (`node-options=--require x`), `--shell=`, `--node-gyp=`,
# `--editor=` a program -, so a rule covers only these, which change what it prints, where it
# fetches from or that it runs less:
_HARMLESS_RUNNER_OPTIONS = frozenset(
    {
        *("--silent", "-s", "--quiet", "-q", "--loglevel"),  # (how much it prints)
        *("--color", "--no-color"),  # (its colours)
        *("--offline", "--prefer-offline"),  # (its cache alone, no network)
        "--no",  # (npx / npm exec: installs nothing missing)
        *("--no-audit", "--no-fund"),  # (sends for no report)
        "--ignore-scripts",  # (runs no package's scripts)
        *("--frozen-lockfile", "--immutable"),  # (changes no lockfile)
    }
)
# ...these two with any value; the rest are switches, harmless only on: alone or `=true` - npm's
# parser (nopt) reads `--ignore-scripts=false`, `=0`, `=null` and a `false` word after it as off.
_VALUED_RUNNER_OPTIONS = frozenset({"--loglevel", "--color"})
# ...npm reads its own up to `--`, anywhere; pnpm, yarn and bun theirs up to the verb that hands
# the rest on (a bin's, a script's); npx, pnpx and bunx theirs before the package only.
_HAND_ON = frozenset({"exec", "dlx", "x", "run", "run-script"})


def _runner_options_past(words: list[str], extra: list[str]) -> bool:
    """W7c: whether a node runner's line (`corepack` before one too) gives past its rule
    (`extra`, up to `--`) an option of the runner's own not in `_HARMLESS_RUNNER_OPTIONS` - its
    value a word of its own (`--loglevel silent`) or after `=`; a switch of those turned off
    (`--ignore-scripts=false`, `--ignore-scripts false` - its `false` past a rule that ends in
    the switch too)."""
    words = words[1:] if words and _program(words[0]) == "corepack" else words
    program = _program(words[0]) if words else ""
    if program not in ("npm", "pnpm", "yarn", "bun") or (
        program != "npm" and words[1:2] and words[1] in _HAND_ON
    ):
        return False
    own = extra[: extra.index("--")] if "--" in extra else extra
    last = words[-len(extra) - 1] if len(words) > len(extra) else ""  # (the rule's last word)
    seen = [last, *own] if last in _HARMLESS_RUNNER_OPTIONS else own
    return any(
        not _harmless_runner_option(word, after)
        for word, after in zip(seen, [*seen[1:], ""], strict=False)
    )


def _harmless_runner_option(word: str, after: str) -> bool:
    """Whether a word of a node runner's own past its rule changes only what it prints, where it
    fetches from or that it runs less (`_HARMLESS_RUNNER_OPTIONS`): not an option, or one of
    those - a switch on (`--offline`, `=true`), never followed by a `false` word (`"false"`,
    `fal""se`: as a shell joins it). An option in pieces (`'--ignore-scripts=false'`) never is."""
    plain = _PIECES.sub("", word)
    if not plain.startswith("-"):
        return True
    if plain != word:
        return False
    name, sep, value = word.partition("=")
    if name in _VALUED_RUNNER_OPTIONS:
        return True
    return name in _HARMLESS_RUNNER_OPTIONS and (
        value == "true" if sep else _PIECES.sub("", after) != "false"
    )


def _past_the_rule(words: list[str], extra: list[str]) -> bool:
    """Whether a line's words past a rule (`extra`, up to a `--`: past it they are a script's)
    give an option `_PAST_A_RULE` lists for a program the line names (`python -m pytest`, `uv run
    pytest`: pytest's too) - by `_option_given`; `_PAST_A_RULE_OUT`'s one leading out - or hand a
    shell a line (`_SHELL_LINE`); or a node runner's option no rule covers (W7c)."""
    if _runner_options_past(words, extra):
        return True
    named = {_program(word) for word in words}
    given, out = (
        [
            (program, _option_spelling(program, option), _SHORT_VALUES.get(program))
            for program in named
            for option in rows.get(program, ())
        ]
        for rows in (_PAST_A_RULE, _PAST_A_RULE_OUT)
    )
    own = extra[: extra.index("--")] if "--" in extra else extra
    for at, written in enumerate(own):
        after = own[at + 1] if at + 1 < len(own) else ""
        # (an option's name in pieces a shell joins - `--incre"mental"` - is past any rule of
        # these; its value after `=` may be quoted whole, `--select="E,F"`; a value in pieces is
        # judged with its option - as `after`, or glued as written)
        name, sep, glued = written.partition("=")
        if (bare := _one_piece(name)) is None:
            # (...and so is a word of its own the shell joins into one: `'SHELL=/x'`, `SH""ELL=`)
            joined = _PIECES.sub("", written)
            if (
                (given or out)
                and joined.startswith("-")
                or any(
                    _option_given(joined, after, option, takes) is not None
                    for _program_name, option, takes in given
                    if not option.startswith("-")
                )
            ):
                return True
            continue
        word = f"{bare}{sep}{_one_piece(glued, path=True) or glued}"
        for program, option, takes in given:
            value = _option_given(_option_spelling(program, word), after, option, takes)
            if value is not None and not _harmless(program, option, value):
                return True
        if any(
            (value := _option_given(_option_spelling(program, word), after, option, takes))
            is not None
            and _value_leads_out(value)
            for program, option, takes in out
        ):
            return True
    return bool(_SHELL_LINE.search(" ".join(extra)))


def _option_spelling(program: str, word: str) -> str:
    """A word as `program` reads an option's name: tsc's in any case (`--OUTDIR`, `-P`: measured,
    5.9); eslint's long ones in any case and with or without inner dashes (`--outputFile`) -
    optionator 0.9.4, eslint's, looks a name up as written and refuses `--Fix` or `-F`: this
    fails closed if a version does not. A value after `=` stays as written."""
    if program == "tsc":  # (and `--p` is `-p` to it)
        folded = word.casefold()
        return folded[1:] if len(folded) == 3 and folded.startswith("--") else folded
    if program == "eslint" and word.startswith("--"):
        name, sep, value = word[2:].partition("=")
        return f"--{name.replace('-', '').casefold()}{sep}{value}"
    return word


def _harmless(program: str, option: str, written: str) -> bool:
    """What of an option `_PAST_A_RULE` lists changes nothing of what runs: pytest's plugin
    turned off (`-p no:x`) or how it logs (`-o log_cli=true`), eslint's own formatter, tsc
    told to write nothing (`--incremental false`, `--composite false`, `--noEmit`,
    `--generateTrace null` - tsc reads `false` and `null` as written: `FALSE` is true). A value
    in pieces a shell joins (`fal""se`, `f\\alse`) never is (`_one_piece`)."""
    if (value := _one_piece(written)) is None:
        return False
    if program == "tsc":  # (`--noEmit` last, before another option, or `true`: on)
        return (
            (option in ("--incremental", "--composite") and value == "false")
            or (option == "--noemit" and (value in ("", "true") or value.startswith("-")))
            or (option == "--generatetrace" and value == "null")
        )
    if program == "pytest":
        return (option == "-p" and value.startswith("no:")) or (
            option in ("-o", "--override-ini") and value.split("=", 1)[0] in _HARMLESS_INI
        )
    return program == "eslint" and option in ("-f", "--format") and value in _ESLINT_FORMATS


# A quote or a backslash in a word past a rule: a shell joins or unescapes its pieces.
_PIECES = re.compile(r"[\"'\\]")


def _one_piece(text: str, path: bool = False) -> str | None:
    """`text` without one pair of outer quotes - None where a quote or a backslash is anywhere
    else in it (a `path` on Windows may hold a backslash: its separator there): a shell joins
    or unescapes such pieces (`fal""se`, `".."/x`, sh's `f\\alse`), never worked out here."""
    quoted = len(text) > 1 and text[0] == text[-1] and text[0] in "'\""
    inner = text[1:-1] if quoted else text
    odd = re.search(r"[\"']", inner) if path and sys.platform == "win32" else _PIECES.search(inner)
    return None if odd else inner


def _value_leads_out(value: str) -> bool:
    """Whether an option's value leads out of the folder - or is in pieces (`_one_piece`)."""
    plain = _one_piece(value, path=True)
    return plain is None or _outside(plain) or bool(re.search(r"[$%~]", plain))


def _option_given(word: str, after: str, option: str, takes: str | None) -> str | None:
    """The value `word` (and the word `after` it) gives `option`, "" for none; None where it is
    not that option. A short one alone, glued to its value (`-pfoo`) or - `takes` its program's
    value letters, None for one that bundles none - after flags in a bundle (`-qo x`); a long one
    by any start of three letters or more (argparse and getopt take one cut short), `--x=v` too;
    one dash and a long name (go's `-exec`, `--exec` too; maven's `-Dmaven.ext...`) as it starts;
    a word of its own (`SHELL=`) as it starts."""
    if not option.startswith("-"):
        return word[len(option) :] if word.startswith(option) else None
    full = option.lstrip("-")
    if len(full) == 1:
        if not word.startswith("-") or word.startswith("--"):
            return None
        for at, letter in enumerate(word[1:], 1):
            if letter == full:  # (`-o=x` is `-o x` to clap and argparse)
                return word[at + 1 :].removeprefix("=") or after
            if takes is None or not letter.isalpha() or letter in takes:
                return None
        return None
    name, sep, glued = word.lstrip("-").partition("=")
    if word.startswith("--") and option.startswith("--"):
        hit = name == full or len(name) >= 3 and full.startswith(name)
    else:
        hit = word.startswith("-") and (name == full or word.startswith(option))
    return (glued if sep else after) if hit else None


MAX_RULE = 200


def tidy_rule(command: str) -> str:
    """A command the user puts on a conversation's allow list by hand, as "Always run"
    would have stored it: its words with one space between them. ValueError says why it
    cannot be a rule - one line of plain words that names a program, nothing a shell
    could turn into a second command, and no word that runs whatever follows it."""
    if not isinstance(command, str) or not is_plain(command):
        raise ValueError(
            "a rule is one plain command: no chaining, pipes, redirection or substitution"
        )
    words = _words(command.strip())
    if not words:
        raise ValueError("a rule names a command: this one is empty")
    if is_wrapped(command) or _program(words[0]) in _SHELLS:
        raise ValueError(
            "a rule cannot start with a shell, a variable or a word that runs another "
            "command: it would allow anything"
        )
    if said := danger(command):
        raise ValueError(f"{said} No rule covers it: it is asked every time.")
    if _git_runs(command):
        raise ValueError(
            "a git rule names git's command and no option that runs a program or "
            "writes a file it is told of (`git status`): it is asked every time"
        )
    if _fetch_writes(command):
        raise ValueError(
            "a fetcher's rule only fetches: no option that writes a file, reads "
            "a config or sends (`-o`, `-K`, `-OutFile`, `-d`)"
        )
    rule = " ".join(words)
    if len(rule) > MAX_RULE:
        raise ValueError(f"a rule is a command of at most {MAX_RULE} characters")
    return rule


def is_exactly(command: str, rule: str) -> bool:
    """Whether a command is a rule's text, character for character - how a rule is read
    where nobody is watching: no further argument, no other spacing, nothing chained or
    wrapped, nothing that deletes or cannot be undone, nor runs in another package
    (`elsewhere`)."""
    return (
        bool(rule)
        and command == rule
        and is_plain(command)
        and not is_wrapped(command)
        and not _in_a_shell(command)
        and not danger(command)
        and not elsewhere(command)
    )


# W7b: a node runner's options that run it in another package or folder of a monorepo - its
# `bin`, its scripts (measured, npm 11.9: `npm exec tsc -w sub` runs sub's own `bin`, which the
# folder's checks never read): no rule covers such a line, and none is offered.
_NPM_ELSEWHERE = ("-w", "--workspace", "--workspaces", "--ws", "--prefix", "-C")
_PNPM_ELSEWHERE = ("--filter", "-F", "-r", "--recursive", "-C", "--dir", "-w", "--workspace-root")
_ELSEWHERE = {
    "npm": _NPM_ELSEWHERE,
    "npx": _NPM_ELSEWHERE,
    "pnpm": _PNPM_ELSEWHERE,
    "pnpx": _PNPM_ELSEWHERE,
    "yarn": ("--cwd",),
    "bun": ("--filter", "-F", "--cwd"),
    "bunx": ("--cwd",),
}


def elsewhere(command: str) -> bool:
    """W7b: whether a node runner's line (`corepack` before one too) runs in another package or
    folder: npm's and npx's `-w` / `--workspace` / `--workspaces` / `--ws` / `--prefix` / `-C`,
    pnpm's `--filter` / `-r` / `--dir` / `-C` / `-w`, yarn's `workspace x` / `workspaces
    foreach` / `--cwd`, bun's `--filter` / `--cwd` - in any spelling (`--workspace=x`, `-ws`).
    The words before `--` are the runner's; npx's, pnpx's and bunx's only before the package."""
    words = [word.strip("'\"") for word in _words(command.strip())]
    words = words[1:] if words and _program(words[0]) == "corepack" else words
    flags = _ELSEWHERE.get(_program(words[0])) if words else None
    if flags is None:
        return False
    if _program(words[0]) == "yarn" and words[1:2] in (["workspace"], ["workspaces"]):
        return True
    rest = words[1 : words.index("--")] if "--" in words else words[1:]
    if _program(words[0]) in _RUNNER_PROGRAMS:
        rest = list(itertools.takewhile(lambda word: word.startswith("-"), rest))
    return any(
        word.split("=")[0] in flags
        or (
            not word.startswith("--")
            and any(word.startswith(one) for one in flags if len(one) == 2)
        )
        for word in rest
    )


def _in_a_shell(command: str) -> bool:
    """Whether a command hands its rest to a shell (`cmd /c del x`): `danger` cannot see
    inside one, so no rule covers it, not even one stored before slice 90."""
    words = _words(command.strip())
    return bool(words) and _program(words[0]) in _SHELLS


def ticked(session, trigger) -> list[AllowedCommand]:
    """The rules a trigger's turns may run, in the order they were ticked: the ids its
    permissions name that are, right now, on the allow list of the conversation its
    turns go into. Read off that list every time, so a rule the user takes off it - or
    a trigger moved to another conversation - leaves nothing behind. Whatever is not a
    rule's id (a command's text, as triggers once kept) is no rule."""
    leave = trigger.permissions if trigger is not None else None
    ids = leave.get("commands") if isinstance(leave, dict) else None
    if not isinstance(ids, list):
        return []
    wanted = [rule_id for rule_id in ids if isinstance(rule_id, str) and rule_id]
    if not wanted:
        return []
    found = {
        rule.id: rule
        for rule in session.scalars(
            select(AllowedCommand).where(
                AllowedCommand.conversation_id == trigger.conversation_id,
                AllowedCommand.project_id == trigger.project_id,
                AllowedCommand.id.in_(wanted),
            )
        )
    }
    return [found[rule_id] for rule_id in dict.fromkeys(wanted) if rule_id in found]


def rules_here(conversation):
    """The "Always run" rules that hold in a chat now: its own, made in the folder it is in
    (slice 86a). A plain chat has none."""
    return select(AllowedCommand).where(
        AllowedCommand.conversation_id == conversation.id,
        AllowedCommand.project_id == conversation.project_id,
    )


def web_rules_here(conversation):
    """The web rules that hold in a chat now: its own, and the sites of its project's agents'
    browsers (K-tarayici-disari: the user's call, a site is the project's)."""
    own = AllowedWeb.conversation_id == conversation.id
    if conversation.project_id is None:
        return select(AllowedWeb).where(own)
    return select(AllowedWeb).where(or_(own, AllowedWeb.project_id == conversation.project_id))


def new_web_rule(conversation, kind: str, host: str) -> AllowedWeb:
    """A web rule a chat makes: a site is kept on its project (A3), all else on the chat."""
    if kind == "page" and conversation.project_id is not None:
        return AllowedWeb(project_id=conversation.project_id, kind=kind, host=host)
    return AllowedWeb(conversation_id=conversation.id, kind=kind, host=host)


# Programs that delete: every form of them is asked, flags or not (slice 90).
_DELETERS = frozenset(
    {
        "rm",
        "del",
        "erase",
        "rd",
        "rmdir",
        "remove-item",
        "ri",
        "unlink",
        "shred",
        "dd",
        "format",
        "diskpart",
        "wipefs",
    }
)
# git's and docker's options that take a value before the subcommand (`git -C repo push`).
_GIT_VALUE_OPTIONS = frozenset(
    {
        "-C",
        "-c",
        "--git-dir",
        "--work-tree",
        "--namespace",
        "--config-env",
        "--attr-source",
        "--super-prefix",
    }
)
_DOCKER_VALUE_OPTIONS = frozenset(
    {
        "-c",
        "--context",
        "-H",
        "--host",
        "--config",
        "-l",
        "--log-level",
        "--tlscacert",
        "--tlscert",
        "--tlskey",
    }
)
# Where one command ends and the next begins, for a chained one.
# shortcut: blind to quotes, so a line of `python -c "..."` code that starts with `del`, `format`
# or `dd` reads as that program ("Deletes files or disks."): over-asks, never under-asks; split
# by the shell's own quoting if such cards are seen often (R161).
_PARTS = re.compile(r"&&|\|\||[;&|\r\n]")
# ...and, where harm is judged (`_harm`, `harms`, `runs_another`), the blocks a PowerShell line
# runs inside it: `(rm x)`, `$(rm x)`, `if(1){rm x}`, `% { ri $_ }` (security review 0.1.0,
# finding 4). The same blindness to quotes: `git commit -m "x (del y)"` over-asks.
_BLOCKS = re.compile(r"&&|\|\||[;&|\r\n(){}]")
# .NET's own delete a PowerShell line can call, past any program's name.
# shortcut: a write or move over a file (`[IO.File]::WriteAllText`, `Move`, `Set-Content`,
# `Out-File`, `>`) is not harm here, as an edit and `mv` are not (agents edit files that way at
# Full auto), nor a method on an object (`(gi x).Delete()`); card them if the user meets one.
_DOTNET_DELETE = re.compile(
    r"(?i)\[\s*(?:system\s*\.\s*)?io\s*\.\s*(?:file|directory)\s*\]\s*::\s*delete"
)


def _cluster(word: str, letter: str) -> bool:
    """Whether a short-option word (`-fd`, `-xfd`) holds a letter."""
    return word.startswith("-") and not word.startswith("--") and letter in word[1:]


# K-koordinasyon: by its id an agent stops what it started; by a name, whatever runs under it.
KILLS_BY_NAME = (
    "Stops programs by their name (taskkill /IM, pkill, killall, Stop-Process "
    "-Name): KOLONİ, other agents' runs and the user's own programs share this "
    "machine."
)


# What stops a process (`_part_stop`) is asked at every level - recognised by its safe shape, not
# by a dangerous one: a stop is "by id" only where every target is a pid written out, or one the
# line itself started (`_started`). By a name it is "soft" unless the name may be KOLONİ itself or
# an agent's CLI (`_named`). WMI's and CIM's own removals, a process object's own Kill / Terminate,
# `fuser -k` and the kill-port packages say nothing of what they reach.
_CIM_REMOVES = frozenset({"remove-ciminstance", "rcim", "remove-wmiobject", "rwmi"})
# WMI's own stop of whatever its query finds (`wmic process where ... delete`, `... call terminate`,
# `Invoke-CimMethod -MethodName Terminate`): read in the line as written, in what a shell is handed
# too - wmic is a wrapper to `_commands_in`.
_WMI_STOPS = re.compile(
    r"(?i)(?:^|(?<=[\s\"'(;&|{]))(?:wmic|invoke-cimmethod|icim|"
    r"invoke-wmimethod)(?:\.exe)?\s[^;&|\r\n]*\b(?:delete|terminate)\b"
)
# What stops processes by its name as a word of a line (`_stands`), and what hands a stop the words
# it reads (`xargs`, `parallel`): a stop on such a line is of whatever it is handed, its own words
# or not (`xargs -I 99 kill 99`).
_STOP_PROGRAMS = frozenset(
    {"kill", "stop-process", "spps", "taskkill", "tskill", "pkill", "killall"}
)
_HANDS_WORDS = re.compile(r"(?i)(?<![\w-])(?:xargs|parallel)(?![\w-])")
# Code an interpreter is handed on the line (`_INLINE`: `python -c`, `node -e`, `perl -e`, `ruby
# -e`; an awk program) is not read: a stop's name in it - a program's, a process object's own, a
# signal - is a stop of what may be KOLONİ itself (review round 5).
_AWK = re.compile(r"(?i)(?:^|(?<=[\s;&|(]))(?:\S*[\\/])?[gmn]?awk(?:\.exe)?\s")
_CODE_STOPS = re.compile(
    r"(?i)(?<![\w-])(?:taskkill|tskill|pkill|killall|kill|killpg|posix_kill|"
    r"stop-process|spps|terminateprocess)(?![\w-])|\.(?:kill|terminate)\s*\("
    r"|\bsignal\.SIG"
)
# ...and code an interpreter reads on stdin: piped into it, or a heredoc or a here-string on its
# part (`echo "..." | python`, `python - <<'EOF'`, `tclsh <<< '...'` - k-okuyucu-2).
_INTERPRETERS = (
    r"(?:python[\d.]*w?|py|node|ruby|perl|php|lua\w*|tclsh[\d.]*|wish|r|rscript|julia|"
    r"bun|deno|go)(?:\.exe)?"
)
_STDIN_CODE = re.compile(
    rf"(?i)\|\s*(?:\S*[\\/])?{_INTERPRETERS}(?![\w.-])"
    rf"|(?:^|(?<=[\s;&|(]))(?:\S*[\\/])?{_INTERPRETERS}(?![\w.-])[^|;&\n]*<<"
)
# A line's words as its shell splits them - by its quotes, glued ones too (`--grep="x|kill"`) -
# and what joins its commands (`_stands`).
_SHELL_WORDS = re.compile(r"""(?:[^\s'";&|(){}]|"[^"]*"|'[^']*')+|[;&|(){}]+""")
# A process object's own way to end (`$p.Kill()`, `% Terminate`, `ForEach-Object Kill`).
_STOP_METHODS = frozenset({"kill", "terminate", "closemainwindow"})
_KILL_PACKAGES = frozenset({"kill-port", "fkill", "fkill-cli"})
# A package runner and its word before the package: `npx x`, `npm exec x`, `pnpm dlx x`.
_RUNS_PACKAGE = {
    "npx": (),
    "pnpx": (),
    "bunx": (),
    "npm": ("exec", "x"),
    "pnpm": ("dlx", "exec"),
    "yarn": ("dlx", "exec"),
    "bun": ("x",),
}
# Stop-Process's switches: a number after one is its id (`Stop-Process -Force 1234`).
_STOP_SWITCHES = ("-force", "-passthru", "-whatif", "-confirm", "-verbose", "-debug")
# What KOLONİ itself runs as, and the CLIs its agents run on: a stop by a name that may be one is
# never soft (`_named`) - nor one not written out (a wildcard, a bracket, a variable).
_KOLONIS_PROGRAMS = (
    "python",
    "pythonw",
    "py",
    "uvicorn",
    "node",
    "claude",
    "codex",
    "copilot",
    "qodercli",
    "agy",
)
_KOLONIS_NAMES = re.compile(
    r"(?i)(?:python|uvicorn|node|claude|codex|copilot|qodercli|agy)"
    r"[\w.-]*|py(?:\.exe)?|.*[*?$(@`%\[\]].*"
)
# What a line sets a variable to: PowerShell's `$p = x`, `foreach ($p in x)`, and sh's `P=x`.
_PS_SETS = re.compile(r"(?i)\$(\w+)\s*=(?!=)\s*([^;\r\n]*)")
_PS_LOOPS = re.compile(r"(?i)\bforeach\s*\(\s*\$(\w+)\s+in\b")
_SH_SETS = re.compile(r"(?<![\w$.-])([A-Za-z_]\w*)=([^\s;&|]*)")
# A start's whole value: Start-Process with -PassThru and nothing that pipes it on, runs a block
# or a subexpression, or chains another command (`| % { Get-Process node }`, `(gps node).Id`).
_STARTS = re.compile(r"(?i)\s*(?:start-process|saps|start)\b[^|&;(){}`]*-passthru[^|&;(){}`]*")
# Names the shell keeps for itself - bash's (`PPID=$!` leaves `$PPID` its parent's), PowerShell's
# `$PID` (its own id): a stop of one is never of what the line started.
_SHELLS_NAMES = frozenset(
    {
        "ppid",
        "uid",
        "euid",
        "bashpid",
        "groups",
        "random",
        "srandom",
        "seconds",
        "lineno",
        "histcmd",
        "epochseconds",
        "epochrealtime",
    }
)
# pkill's and killall's selections by an owner, a parent, a session, a terminal, a group, the
# whole command line or a pattern: whose processes they reach is not said.
_SELECTS = {"pkill": set("uUPstGgf"), "killall": set("ugr")}
_SELECTS_LONG = (
    "--full",
    "--euid",
    "--uid",
    "--parent",
    "--session",
    "--terminal",
    "--group",
    "--pgroup",
    "--user",
    "--regexp",
    "--process-group",
)


def _started(command: str) -> set[str]:
    """How a line names the processes it starts: `$p.id` of `$p = Start-Process x -PassThru`,
    `$pid` of sh's `PID=$!` - a variable set to nothing else on the line (`$p = Get-Process x`
    after it, `foreach ($p in ...)`), named nowhere else on it but where a stop takes it
    (`_named_elsewhere`), and not one the shell keeps (`_SHELLS_NAMES`, PowerShell's `$PID`)."""
    sets: dict[str, list[str]] = {}
    for name, value in _PS_SETS.findall(command):
        sets.setdefault(f"${name.casefold()}.id", []).append(
            "" if name.casefold() == "pid" else value
        )
    for name, value in _SH_SETS.findall(command):
        sets.setdefault(f"${name.casefold()}", []).append(
            "" if name.casefold() in _SHELLS_NAMES else value
        )
    for name in _PS_LOOPS.findall(command):
        sets.setdefault(f"${name.casefold()}.id", []).append("")
    return {
        name
        for name, values in sets.items()
        if all(_STARTS.fullmatch(value) or value.strip() == "$!" for value in values)
        and not _named_elsewhere(command, name[1:].removesuffix(".id"))
    }


def _named_elsewhere(command: str, name: str) -> bool:
    """Whether a line names a variable anywhere but where it starts a process (`$p = Start-Process
    x -PassThru`, `PID=$!`) and where a stop takes it, in any spelling: `${p}`, `$script:p`, a
    bare `p` (`-OutVariable p`, `Set-Variable p`, `sv p`, `Tee-Object -Variable p`, `for PID
    in`, `read PID`, `mapfile -t PID`, `printf -v PID`, `((PID++))`), `$p, $q =` - any of which
    may set it to another process."""
    named = re.compile(rf"(?i)(?<![\w/-]){re.escape(name)}(?!\w)")
    start = re.compile(
        rf"(?i)\s*(?:\${re.escape(name)}\s*=(?!=){_STARTS.pattern[4:]}"
        rf"|{re.escape(name)}=\$!\s*)"
    )
    for part in _BLOCKS.split(command):
        if not named.search(part) or start.fullmatch(part):
            continue
        words = _parts(part, _BLOCKS)[0] if part.strip() else []
        program = _program(words[0]) if words else ""
        if program not in _STOP_PROGRAMS and program.rpartition(".")[2] not in _STOP_METHODS:
            return True
    return False


def _own_id(word: str, started: set[str], jobs: bool = False) -> bool:
    """Whether a stop's target is a pid written out, `$!`, a job (`%1`, sh's `kill` alone:
    `jobs`), or how the line names a process it started (`_started`: `$p.Id`, `$PID` of
    `PID=$!`)."""
    word = re.sub(r"^\$\{(\w+)\}", r"$\1", word.strip("'\"").casefold())
    return bool(
        re.fullmatch(r"[1-9]\d*(?:,[1-9]\d*)*|\$!", word)
        or jobs
        and re.fullmatch(r"%(?:\d+|[%+-])", word)
        or word in started
    )


def _named(names: list[str], pattern: bool = False) -> str:
    """A stop by these names (a word may list them: `a,b`): "koloni" where one may be KOLONİ
    itself or another agent's CLI (`_KOLONIS_NAMES`), or none is written; else "soft".
    `pattern`: pkill's - a regular expression found anywhere in a process's name (`pkill thon`)."""
    names = [name for word in names for one in word.split(",") if (name := one.strip("'\" "))]
    if not names or any(map(_KOLONIS_NAMES.fullmatch, names)):
        return "koloni"
    for name in names if pattern else ():
        try:
            if any(re.search(name, program, re.I) for program in _KOLONIS_PROGRAMS):
                return "koloni"
        except re.error:
            return "koloni"
    return "soft"


def _stop_process(said: list[str], started: set[str], stands: bool) -> str:
    """`_part_stop` of PowerShell's Stop-Process: by id only by `-Id` (`-i`, `-Id:1`) or numbers
    no option takes as its value - each a pid written out or one the line started; by `-Name`; a
    process object (`-InputObject`, a word in Id's place) only one the line started."""
    names, ids, by_name, at = [], [], False, 0
    while at < len(said):
        word = said[at].casefold()
        option, _sep, glued = word.partition(":")
        if not word.startswith("-"):
            (names if by_name else ids).append(said[at])
        elif option in ("-i", "-id") or option.startswith("-in"):
            ids.append(glued or (said[at + 1] if at + 1 < len(said) else ""))
            at += 1 if glued else 2
            continue
        elif option.startswith(("-n", "-processn")):
            by_name = True
            names += [glued] if glued else []
        elif not glued and not any(
            switch.startswith(option) and len(option) > 1 for switch in _STOP_SWITCHES
        ):
            at += 1  # (an option's value: `-ErrorAction 0`)
        at += 1
    if ids and not all(_own_id(one, started) for one in ids):
        return "koloni"
    return _named(names) if by_name else "" if ids else _bare(stands)


def _kill(said: list[str], started: set[str], stands: bool) -> str:
    """`_part_stop` of `kill`: PowerShell's by `-Name` (`-n x`, `-name:x`); sh's by its pids
    after its signal (`-9`, `-s KILL`, `--`) - each a pid written out, a job, or one the line
    started (`$!`); everyone's (`-1`), a group's (`0`, a negative pid), one in another variable
    (`$PPID`) or none written (what `xargs` hands it) may be KOLONİ itself."""
    low = [word.casefold() for word in said]
    if low[:1] in (["-l"], ["--list"]):
        return ""  # (it lists the signals)
    for at, word in enumerate(low):
        option, _sep, glued = word.partition(":")
        value = glued or (said[at + 1] if at + 1 < len(said) else "")
        if option.startswith(("-n", "-processn")) and not value.isdigit():  # (sh's `-n 9`)
            return _named([value, *[one for one in said[at + 2 :] if not one.startswith("-")]])
    targets, ended, signalled, at = [], False, False, 0
    while at < len(said):
        word = said[at]
        if not ended and word == "--":
            ended = True
        elif not ended and word in ("-s", "-n"):
            at, signalled = at + 1, True
        elif not ended and word.startswith("-") and not signalled and at + 1 < len(said):
            signalled = True
        else:
            targets.append(word)
        at += 1
    if not targets:
        return _bare(stands)
    return "" if all(_own_id(one, started, jobs=True) for one in targets) else "koloni"


def _taskkill(said: list[str], started: set[str]) -> str:
    """`_part_stop` of taskkill: by `/IM` (`/IM:x`, Git Bash's `//IM`) a name; `/FI` a filter -
    what it reaches is not said; by `/PID` each a pid written out or one the line started
    (`for /f ... do taskkill /PID %a` is of what the loop found)."""
    names, ids, at = [], [], 0
    while at < len(said):
        key, _sep, glued = said[at].casefold().lstrip("/-").partition(":")
        if not said[at].startswith(("/", "-")):
            at += 1
            continue
        if key == "fi":
            return "koloni"
        if key in ("im", "pid", "s", "u", "p"):
            value = glued or (said[at + 1] if at + 1 < len(said) else "")
            names += [value] if key == "im" else []
            ids += [value] if key == "pid" else []
            at += 1 if glued else 2
            continue
        at += 1
    if ids and not all(_own_id(one, started) for one in ids):
        return "koloni"
    return _named(names) if names else "" if ids else "koloni"  # (none said: not read)


def _pkill(program: str, said: list[str]) -> str:
    """`_part_stop` of pkill and killall: by their names - pkill's a pattern found anywhere in a
    name but with `-x` - but a selection by owner, parent, session, terminal, group, command line
    or pattern (`_SELECTS`) is of whatever it finds."""
    names, exact, at = [], program == "killall", 0
    while at < len(said):
        word = said[at]
        if word.startswith("--"):
            if word.split("=")[0] in _SELECTS_LONG:
                return "koloni"
            exact = exact or word == "--exact"
        elif re.fullmatch(r"-(?:\d+|SIG[A-Z0-9]+|[A-Z]{2,}[A-Z0-9]*)", word):
            pass  # (a signal: -9, -KILL, -SIGTERM)
        elif word.startswith("-"):
            if set(word[1:]) & _SELECTS[program]:
                return "koloni"
            exact = exact or "x" in word[1:]
            at += 1 if word == "-s" and program == "killall" else 0  # (its signal's value)
        else:
            names.append(word)
        at += 1
    return _named(names, pattern=not exact)


def _runs_kill_package(program: str, said: list[str]) -> bool:
    """Whether a package runner runs one that stops by a port or a name (`_KILL_PACKAGES`)."""
    runner = _RUNS_PACKAGE.get(program)
    named = [word.casefold() for word in said if not word.startswith("-")]
    if runner is None or runner and named[:1] and named[0] not in runner:
        return False
    named = named[1:] if runner else named
    return bool(named) and named[0].split("@")[0] in _KILL_PACKAGES


def _bare(stands: bool) -> str:
    """A kill or a Stop-Process with no target written: "koloni" - of what a pipe, a block or a
    file hands it (`| xargs /bin/kill`, `| & 'Stop-Process'`, `kill -9 $(pgrep x)`) - wherever
    its name stands as a word of its own in the line (`_stands`); none only where the quote-blind
    split cut it out of a message or a search (`git commit -m "fix (kill)"`).
    shortcut: what the pipe hands is not read, so the line's own started process handed so
    (`$p = Start-Process x -PassThru; $p | Stop-Process`) is asked too (OA-d); read the pipe's
    left side against `_started` in 0.1.6."""
    return "koloni" if stands else ""


def _substituted(line: str) -> list[str]:
    """What each `$(...)` of a line runs, to its own closing bracket - in quotes too; past
    MAX_OTHER_READINGS of them, no more (`_too_deep`)."""
    found: list[str] = []
    for start in (found.end() for found in re.finditer(r"\$\(", line)):
        if len(found) > MAX_OTHER_READINGS:
            break
        depth, at = 1, start
        while at < len(line) and depth:
            depth += {"(": 1, ")": -1}.get(line[at], 0)
            at += 1
        found.append(line[start : at - (not depth)])
    return found


def _too_deep(command: str) -> bool:
    """Whether a line holds more than MAX_OTHER_READINGS backtick pairs and `$(...)`: past them it
    is not read, and a stop on it is asked as one of what may be KOLONİ itself (review round 5:
    reading 1000 nested ones took seconds)."""
    return command.count("`") // 2 + command.count("$(") > MAX_OTHER_READINGS


def _stands(command: str, names: frozenset[str] = _STOP_PROGRAMS, depth: int = 4) -> bool:
    """Whether one of `names` is a word of its own in a line - split by its quotes, its quotes
    then taken off (`xargs 'kill'`, `| & "Stop-Process"`, `/bin/kill`, cmd's `@taskkill`) - in
    what its backticks or a `$(...)` run, in quotes too (`"`kill $x`"`, `"$(pkill x)"`), first
    in a line in quotes (`$s = 'Stop-Process -Name x'; iex $s`, a here-string) or in a line a
    shell or a wrapper is handed (`bash -c "x; kill $(y)"`); not past a message's or a pattern's
    first word (`git commit -m "tidy; kill"`). Past MAX_OTHER_READINGS of what backticks
    and `$(...)` run, it stands (`_too_deep`)."""
    if _too_deep(command):
        return True
    for text in [command, *re.findall(r"`([^`]*)`", command), *_substituted(command)]:
        if _SHELL_WORDS.sub("", text).strip():  # (unbalanced quotes: every word)
            text = re.sub(r"['\"]", " ", text)
        words = _SHELL_WORDS.findall(text)
        if any(
            _program(word.lstrip("@")) in names
            or _program((word.strip("@'\"").split() or [""])[0]) in names
            for word in words
        ):
            return True
        part: list[str] = []
        for word in [*words, ";"] if depth else ():
            if not re.fullmatch(r"[;&|(){}]+", word):
                part.append(word.strip("'\""))
                continue
            if part and any(
                len(handed) == 1 and " " in handed[0] and _stands(handed[0], names, depth - 1)
                for handed in _unwrapped(_led(part))
            ):
                return True
            part = []
    return False


def _part_stop(program: str, rest: list[str], started: set[str], stands: bool = True) -> str:
    """Whether a part stops a process otherwise than by an id the line knows: "" (none, or by
    such an id), "soft" (by a name not KOLONİ's) or "koloni" (what may be KOLONİ itself, another
    agent's CLI, or what is not said). `started`: the line's own processes (`_started`)."""
    said = [word.strip("'\"") for word in rest]
    method = program.rpartition(".")[2] if "." in program else ""
    if method in _STOP_METHODS:  # (`$p.Kill()`, `(...).Terminate()`)
        owner = program.rpartition(".")[0]
        return "" if owner and _own_id(owner, started) else "koloni"
    if (
        program in ("%", "foreach-object", "foreach")
        and {word.casefold() for word in said} & _STOP_METHODS
    ):
        return "koloni"
    if program in _KILL_PACKAGES or program in _CIM_REMOVES or _runs_kill_package(program, said):
        return "koloni"
    if program == "fuser":
        return "koloni" if any(_cluster(word, "k") or word == "--kill" for word in said) else ""
    if program == "tskill":
        target = next((word for word in said if not word.startswith("/")), "")
        return (
            ""
            if _own_id(target, started)
            else "koloni"
            if re.fullmatch(r"-?\d+", target)
            else _named([target])
        )
    if program == "taskkill":
        return _taskkill(said, started)
    if program in _SELECTS:
        return _pkill(program, said)
    if program in ("stop-process", "spps"):
        return _stop_process(said, started, stands)
    return _kill(said, started, stands) if program == "kill" else ""


def _stop_kind(command: str) -> str:
    """`_part_stop` of a whole line, in any part a shell is handed too: "koloni" where a part may
    stop KOLONİ itself, "soft" where one stops by another name, "" for none. WMI's stops
    (`_WMI_STOPS`) are read in the line as written. A continued line is read joined too.
    shortcut: a command run out of the line's sight is not read (review rounds 4, k-okuyucu-2):
    `find -exec kill {} ;`, `git submodule foreach '...'`, `script -q -c '...'`, `at`; a line
    kept in a variable or an alias first (`c='B'; $c`, `eval "$c"`, `iex $c`, `alias i='B'; i`,
    `Set-Alias k Stop-Process; k -Name x`); a program's own way to run one (`sed e`, ed's `!` -
    in a script a heredoc hands them too: `sed -f - <<EOF`, `ed -s x <<EOF` -, `vim -c
    ':!...'`, `gdb -ex 'shell ...'`, `sqlite3 '.shell ...'`, `psql -c '\\! ...'`, `git -c
    core.pager=` / `alias.x='!...'`, `tar --checkpoint-action=exec=`); `ssh host '...'` (another
    machine's); a name in smart quotes PowerShell takes for quotes. Read them when one is seen."""
    kinds = {_stop_kind_of(line) for line in _readings(command)}
    return "koloni" if "koloni" in kinds else "soft" if "soft" in kinds else ""


def _stop_kind_of(command: str) -> str:
    if _too_deep(command):
        return "koloni"
    started, stands = _started(command), _stands(command)
    # (`stands` acts only on a stop with no target, `_bare`: a stop with one, cut by the
    # quote-blind split out of a line a shell is handed - `echo "x; pkill y" | bash` - is asked,
    # one cut out of a message or a pattern too: `rg -n 'terminate|kill' app` over-asks)
    kinds = {
        _part_stop(_program(words[0]), words[1:], started, stands)
        for words in _commands_in(command, at=_BLOCKS)
        if words
    }
    # (what a pipe hands its objects to, told to end them: `| Invoke-Method Kill`)
    ends = any(
        {word.casefold() for word in words[1:]} & _STOP_METHODS
        for stage in re.split(r"(?<!\|)\|(?!\|)", command)[1:]
        for words in _parts(stage, _BLOCKS)
        if words
    )
    if (
        _WMI_STOPS.search(command)
        or stands
        and _HANDS_WORDS.search(command)
        or ends
        and (_stands(command, _STOP_METHODS))
        or _CODE_STOPS.search(command)
        and (_INLINE.search(command) or _AWK.search(command) or _STDIN_CODE.search(command))
    ):
        return "koloni"
    return "koloni" if "koloni" in kinds else "soft" if "soft" in kinds else ""


def _stops_by_name(command: str) -> bool:
    return bool(_stop_kind(command))


def _stops_koloni(command: str) -> bool:
    """`harm_class`: whether a stop by name may stop KOLONİ itself - never let run by a check of
    the user's words (`_stop_kind`)."""
    return _stop_kind(command) == "koloni"


def _after_options(rest: list[str], takes_value: frozenset[str]) -> list[str]:
    """The words from the subcommand on: the options before it skipped, with their values."""
    at = 0
    while at < len(rest) and rest[at].startswith("-"):
        at += 2 if rest[at] in takes_value else 1
    return rest[at:]


def _danger_of(words: list[str]) -> str:  # noqa: C901
    program = _program(words[0])
    if program == UNREAD:
        return (
            "It hands shells or wrappers more options and lines than are read here: what "
            "runs is not seen."
        )
    if program in _DELETERS or program.startswith("mkfs"):
        return "Deletes files or disks."
    if program in ("clear-content", "clc"):
        return "Empties files (Clear-Content)."
    rest = words[1:]
    # K-koloni-klasor (review): a link made under the scratch can lead to `.koloni` or out of
    # the project, and a write through it is judged by the path written.
    if (
        program == "mklink"
        or program == "ln"
        and any(a == "--symbolic" or _cluster(a, "s") for a in rest)
        or program in ("new-item", "ni")
        and any(  # (`-ItemType:Junction` too: review of B-336)
            a.casefold().rsplit(":", 1)[-1] in ("junction", "symboliclink", "hardlink")
            for a in rest
        )
    ):
        return "Makes a link, which can point anywhere."
    if program == "find" and "-delete" in rest:
        return "Deletes files (find -delete)."
    if program in ("docker", "docker-compose"):
        # `docker volume rm x`, `docker --context x rm web`: the task is in the first two words
        named = [w for w in _after_options(rest, _DOCKER_VALUE_OPTIONS) if not w.startswith("-")]
        compose = program == "docker-compose" or named[:1] == ["compose"]
        if (
            {"rm", "rmi"} & set(named[:2])
            or "prune" in named
            or compose
            and (
                "rm" in named
                or "down" in named
                and any(a.startswith("--volumes") or _cluster(a, "v") for a in rest)
            )
        ):
            return "Deletes Docker containers, images or volumes."
        return ""
    if program != "git":
        return ""
    rest = _after_options(rest, _GIT_VALUE_OPTIONS)
    sub, args = (rest[0], rest[1:]) if rest else ("", [])
    # (long options by any prefix git takes: `--ha`, `--forc` - security review 0.1.0, finding 3)
    force = any(_long(a, "force") or _cluster(a, "f") for a in args)
    if sub == "push" and any(
        _long(a, "force", "force-with-lease", "force-if-includes", "mirror", "delete", "prune")
        or _cluster(a, "f")
        or _cluster(a, "d")
        or (a[:1] in "+:" and len(a) > 1)
        for a in args
    ):
        return "Overwrites or deletes branches on the git remote."
    if sub == "reset" and any(_long(a, "hard") for a in args):
        return "Throws away uncommitted work (git reset --hard)."
    if sub == "clean" and force:
        return "Deletes untracked files (git clean)."
    if sub == "rm" and force and not any(_long(a, "cached") for a in args):
        return "Deletes files with uncommitted changes (git rm -f)."
    if (
        sub == "branch"
        and (force or any(_cluster(a, "D") or _cluster(a, "M") for a in args))
        or sub == "checkout"
        and any(_cluster(a, "B") for a in args)
        or sub == "switch"
        and any(_cluster(a, "C") or _long(a, "force-create") for a in args)
        or sub == "update-ref"
    ):
        return "Deletes or moves a git branch by force: commits only it held may be lost."
    staged = any(a == "--staged" or _cluster(a, "S") for a in args)
    worktree = any(_long(a, "worktree") or _cluster(a, "W") for a in args)
    if (
        sub == "checkout"
        and ("--" in args[:-1] or force or _checks_out_paths(args))
        or sub == "switch"
        and (force or any(_long(a, "discard-changes") for a in args))
        or sub == "restore"
        and (worktree or not staged)
    ):
        return "Throws away uncommitted changes to files (git checkout / switch / restore)."
    if sub == "stash" and args[:1] in (["drop"], ["clear"]):
        return "Throws away stashed work (git stash drop / clear)."
    if sub == "worktree" and args[:1] == ["remove"]:
        return "Deletes a git worktree's folder (git worktree remove)."
    if sub == "worktree" and args[:1] == ["add"] and _outside_here(_worktree_path(args[1:])):
        return "Opens a git worktree outside the project (git worktree add)."
    return ""


# A word no branch's name can be: a ref holds no `:` `*` `?` `[` `\`, no part starts with `.`;
# or one ending in a file's extension (`a.py`; `v1.2` stays a branch).
_NOT_A_BRANCH = re.compile(r"[:*?\[\\]|^\.|/\.|\.[A-Za-z]\w*$")


def _checks_out_paths(args: list[str]) -> bool:
    """Whether `git checkout` is given paths without `--` (`git checkout a.py`, `git checkout HEAD
    a.py`, `git checkout :/`): two names past its options' values, or one no branch can be.
    shortcut: a folder named like a branch (`git checkout src`) is read as a branch."""
    named, at = [], 0
    while at < len(args) and args[at] != "--":  # (paths after `--`: `_danger_of`)
        word = args[at]
        at += 2 if word in ("-b", "-B", "--orphan") else 1
        if not word.startswith("-") or word == "-":
            named.append(word)
    return len(named) > 1 or any(_NOT_A_BRANCH.search(name) for name in named)


def _worktree_path(args: list[str]) -> str:
    """The folder `git worktree add` is given: its first word that is no option or an
    option's value (-b, -B, --reason)."""
    at = 0
    while at < len(args) and args[at].startswith("-"):
        if args[at] == "--":
            return args[at + 1] if at + 1 < len(args) else ""
        at += 2 if args[at] in ("-b", "-B", "--reason") else 1
    return args[at] if at < len(args) else ""


def _outside_here(path: str) -> bool:
    """K-dallar: whether a folder a command names leads out of the folder it runs in - by its
    name alone: absolute, on a drive, the home folder, or up past its start.
    shortcut: judged from where the command starts, not from a `cd` or `git -C` before it; a
    worktree added from a subfolder to `../x` is asked about though it stays in the project."""
    norm = os.path.normpath(path.replace("\\", "/")).replace("\\", "/")
    # (An anchor: `/x`, which 3.13's isabs no longer calls whole on Windows, and git reads as
    # C:\x; `C:x`, a drive's own folder.)
    return bool(path) and (
        os.path.isabs(path)
        or bool(PureWindowsPath(path).anchor)
        or path.startswith("~")
        or norm == ".."
        or norm.startswith("../")
    )


def switches_branch(command: str) -> bool:
    """K-dallar: whether a part of a command moves the project onto another branch - `git
    switch`, `git checkout <branch>` (not `-- <path>`, nor `.`, which `danger` asks about) - in
    any reading (`_readings`: `git `⏎`switch x` too, k-okuyucu).
    shortcut: `git checkout file.py` with no `--` reads as a switch too - git itself tells them
    apart by what the word names; it is asked about only while another's work is held."""
    return any(map(_switches_branch, _readings(command)))


def _switches_branch(command: str) -> bool:
    for words in _commands_in(command):  # (behind a wrapper too: `time git switch x`)
        sub, rest = _git_sub(words)
        if not rest or {"-h", "--help"} & set(rest):
            continue
        # (`git switch -- x` too; `git checkout x --` is a switch, `-- <path>` after it is not)
        if (
            sub == "switch"
            or sub == "checkout"
            and "." not in rest
            and ("--" not in rest or rest.index("--") == len(rest) - 1 and len(rest) > 1)
        ):
            return True
    return False


# K-dal-takim: a branch's worktree shares the user's repository - their stash, refs, reflog,
# objects, config, remotes. There git runs unasked only for an agent's own work on its branch
# (`reaches_shared_git`, an allow-list): what is not on it is asked at every level.
SHARED_GIT = (
    "it runs git in a branch's worktree beyond its own work there - git there is the "
    "user's own repository (their stash, branches, history, settings, remotes): asked "
    "at every level"
)
# The subcommands an agent's own work needs, each with the exact options it may be given
# (`_own_git`): (options alone, options whose value is the next word, `--x=` forms that take one).
# git takes a value stuck to its option (`-Bmain`), short options bundled (`-qC`) and any unique
# prefix of a long one (`--op` for --open-files-in-pager): so an option is taken only as written
# here, whole - never by its start. Never on a list: --output, --ext-diff, --textconv, --filters,
# -O / --open-files-in-pager.
_OWN_FLAGS: dict[str, tuple[frozenset[str], frozenset[str], tuple[str, ...]]] = {
    "status": (
        frozenset(
            {
                "-s",
                "--short",
                "-b",
                "--branch",
                "--porcelain",
                "--porcelain=v1",
                "--porcelain=v2",
                "-uno",
                "-unormal",
                "-uall",
                "--ignored",
            }
        ),
        frozenset(),
        (),
    ),
    "diff": (
        frozenset(
            {
                "--stat",
                "--name-only",
                "--name-status",
                "--cached",
                "--staged",
                "--no-color",
                "--color=never",
                "-U0",
                "-U1",
                "-U3",
            }
        ),
        frozenset(),
        (),
    ),
    "log": (
        frozenset(
            {
                "--oneline",
                "--stat",
                "--name-only",
                "--name-status",
                "--graph",
                "--decorate",
                "--no-color",
            }
        ),
        frozenset({"-n"}),
        ("--format=", "--pretty="),
    ),
    "show": (
        frozenset({"--stat", "--name-only", "--name-status", "--no-color"}),
        frozenset(),
        ("--format=", "--pretty="),
    ),
    "add": (
        frozenset({"-A", "--all", "-u", "--update", "-N", "--intent-to-add", "-q", "--quiet"}),
        frozenset(),
        (),
    ),
    "commit": (
        frozenset({"-a", "--all", "--amend", "--no-edit", "--allow-empty", "-q", "--quiet"}),
        frozenset({"-m", "--message"}),
        ("--message=",),
    ),
    "rm": (frozenset({"--cached", "-r", "-q", "--quiet"}), frozenset(), ()),
    "mv": (frozenset(), frozenset(), ()),
    "restore": (frozenset({"--staged", "--worktree", "-W", "-S"}), frozenset(), ()),
    "checkout": (frozenset({"-q", "--quiet"}), frozenset(), ()),
    "switch": (frozenset({"-q", "--quiet"}), frozenset(), ()),
    "branch": (
        frozenset(
            {
                "-a",
                "--all",
                "-r",
                "--remotes",
                "-v",
                "-vv",
                "--verbose",
                "-l",
                "--list",
                "--show-current",
                "--no-color",
            }
        ),
        frozenset(),
        (),
    ),
    "tag": (frozenset({"-l", "--list", "--no-color"}), frozenset(), ()),
    "grep": (
        frozenset(
            {
                "-n",
                "-i",
                "-l",
                "-L",
                "-c",
                "-w",
                "-E",
                "-F",
                "-I",
                "-h",
                "-H",
                "--line-number",
                "--ignore-case",
                "--files-with-matches",
                "--count",
                "--word-regexp",
                "--fixed-strings",
                "--extended-regexp",
            }
        ),
        frozenset({"-e"}),
        (),
    ),
    # (not --git-dir, --git-common-dir, --absolute-git-dir, --git-path: the shared git's own path,
    # from where a line writes another worktree's link, HEAD or a ref - k-okuyucu-3 review)
    "rev-parse": (
        frozenset({"--show-toplevel", "--abbrev-ref", "--short", "--verify"}),
        frozenset(),
        (),
    ),
    "ls-files": (
        frozenset({"--others", "--exclude-standard", "--cached", "--modified", "--deleted", "-z"}),
        frozenset(),
        (),
    ),
    "merge-base": (frozenset({"--is-ancestor", "--all"}), frozenset(), ()),
    "cat-file": (frozenset({"-p", "-t", "-s", "-e"}), frozenset(), ()),
    "describe": (frozenset({"--tags", "--always"}), frozenset(), ()),
    "shortlog": (frozenset({"-s", "-n", "-e"}), frozenset(), ()),
    "blame": (frozenset(), frozenset({"-L"}), ()),
    "stash": (frozenset({"-p", "--stat"}), frozenset(), ()),
}
# Options before the subcommand that change nothing of where git works or what it runs.
_GLOBAL_OWN = frozenset({"--no-pager", "--literal-pathspecs", "--no-optional-locks"})
# The one bundle of short options taken (the main session's call: agents write `commit -am`):
# of commit's, `a` and `q`, each once, `m` last where it is - its value the next word. A letter
# twice is refused where it is read (`_own_git`).
_COMMIT_BUNDLE = re.compile(r"-[aq]{1,2}m?|-[aq]?m")
# A variable of git's own set, emptied or unset on the line, or the whole environment dropped: what
# KOLONİ gives git in a copy (`copies.git_env`: no hook, no repository above) would go. Set: POSIX
# `GIT_X=`, cmd `set GIT_X=`, PowerShell `$env:GIT_X=`, .NET's SetEnvironmentVariable (a name not
# written out too); PowerShell's env: drive (`Remove-Item Env:\GIT_X`, a wildcard, a name not
# written out); unset: `unset`, `export -n`, `declare +x` (a name not written out: `${!GI@}`), `env
# -u`; dropped: `env -i`, `env -` (env by its path too). Each part is bounded: a line of a thousand
# `unset `s took half a minute to read, on the event loop.
# shortcut: a wrapper that starts what it runs with an environment of its own (`sudo`, `su -`,
# `doas`, `runas`, `Start-Process -UseNewEnvironment`, `wsl`), or `Get-ChildItem env: |
# Remove-Item`, is not seen; ask those too if an agent is seen to reach git's hooks so.
_GIT_ENV = re.compile(r"""(?ix)
    (?:^|[\s;&|(`{'"]) (?:\$env:)? GIT_\w*\s*=
  | env:[\\/]? (?:GIT_|\w*[*?\[]|[$(])
  | SetEnvironmentVariable\(\s*(?:['"]GIT_|[^'"\s])
  | \b(?:unset|export\s+-\w*n|(?:declare|typeset)\s+\+\w*x)\b [^;&|\n]{0,256} (?:\bGIT_|[$`])
  | (?:\s-\w*u\s*|--u[\w-]*[=\s]\s*) ['"]? GIT_
  | (?:^|[\s;&|(`{'"\\/]) env(?:\.exe)?['"]? (?:\s+(?:-[^\s=]+|[A-Za-z_]\w*=\S*)){0,16}? \s+
      (?:-\w*i\w*|-|--i[\w-]*) (?=\s|$)
""")
# git as a word of the line, wherever it stands - and one of its own programs by its name
# (`/usr/lib/git-core/git-push`, `git-reset`): one not read as a command's program is asked.
_GIT_WORD = re.compile(r"(?i)(?:^|[\s;&|(`{'\"\\/])git(?:-[\w-]+)?(?:\.exe)?(?=$|[\s;&|)`}'\"])")


def _outside(path: str) -> bool:
    """Whether a path an agent names leads out of its worktree by how it is written: absolute,
    or up through `..`."""
    plain = path.replace("\\", "/")
    return plain.startswith("/") or bool(re.match(r"[A-Za-z]:", plain)) or ".." in plain.split("/")


def _own_git(words: list[str], own: str | None = None) -> bool:  # noqa: C901
    """Whether one git invocation is an agent's own work in its branch's worktree: a subcommand of
    `_OWN_FLAGS` with only its options, each exactly as listed (a value only where listed - the
    next word, or a `--x=` form; `-N` a number of log's), and only `_GLOBAL_OWN` before it; no
    path that leads out of the worktree. And as each subcommand allows: a branch or a tag only
    listed, a stash only looked at (a push lands in the user's own list), a checkout or switch
    only onto `own` - the worktree's own branch - or of paths after `--`."""
    sub, rest = _git_sub(words)
    before = words[1 : len(words) - len(rest) - (1 if sub else 0)]
    if not set(before) <= _GLOBAL_OWN:
        return False
    if sub is None:
        return not before and len(words) == 1  # (`git` alone: its help)
    if sub not in _OWN_FLAGS:
        return False
    alone, valued, forms = _OWN_FLAGS[sub]
    named: list[str] = []
    paths: list[str] = []
    at = 0
    while at < len(rest):
        word = rest[at]
        at += 1
        if word == "--":
            paths = rest[at:]
            break
        if (
            word in valued
            or sub == "commit"
            and _COMMIT_BUNDLE.fullmatch(word)
            and (len(set(word)) == len(word))
        ):
            at += 1 if word.endswith("m") else 0  # (its value: the message)
            continue
        if word.startswith("-") and not (
            word in alone
            or word.startswith(forms)
            and forms
            or sub == "log"
            and re.fullmatch(r"-\d+", word)
        ):
            return False
        if not word.startswith("-"):
            named.append(word)
    if any(_outside(word) for word in named + paths):
        return False
    if sub in ("branch", "tag"):
        return not named or bool({"-l", "--list"} & set(rest))
    if sub == "stash":
        return named[:1] in (["list"], ["show"])
    if sub in ("checkout", "switch"):
        return not named and bool(paths) or own is not None and named == [own]
    return True


def reaches_shared_git(command: str, own: str | None = None) -> str:
    """K-dal-takim: why a command run in a branch's worktree is asked at every level (`SHARED_GIT`)
    - "" where every git it runs is an agent's own work there (`_own_git`), as are commands that
    run no git. Asked: any other git; one that sets a variable of git's own (`GIT_DIR`,
    `GIT_CONFIG_*`); git as a word not read as a command's program (`(git)`, `xargs git`, `& $g`);
    a line too deep to read. Read in what a shell or a wrapper is handed too (`_commands_in`). An
    alias of the repository's own config is a name not on the list: asked. `own`: the worktree's
    own branch, the one a checkout or switch may go onto (None: none yet - asked). And a write to a
    place built at run time (`_writes_built`: `BUILT_TARGET`), in any reading of the line.
    shortcut: git run by a script, or a name spliced by the shell (`g`it`, `$(echo git)`), is not
    seen - as `danger` does not see those either."""
    if _GIT_ENV.search(command):
        return SHARED_GIT
    if any(_writes_built(line) for line in _readings(command)):
        return BUILT_TARGET
    read = 0
    for words in (words for words in _commands_in(command) if words):
        if (
            words == [UNREAD]
            or _program(words[0]) != "git"
            and _program(words[0].strip("(){}")) == "git"
        ):  # (git glued to a bracket: `(git) stash pop`)
            return SHARED_GIT
        if _program(words[0]) == "git":
            read += 1
            if not _own_git(words, own):
                return SHARED_GIT
    # (PowerShell drops a backtick before a letter: `g`it` is git.)
    return SHARED_GIT if len(_GIT_WORD.findall(command.replace("`", ""))) > read else ""


# K-okuyucu-3 (the k-pr-wt review): in a branch's worktree `$(git rev-parse --git-dir)` leads into
# the user's own repository - one unasked `echo "$PWD/x" > "$(dirname "$(git rev-parse
# --git-dir)")/<id>/gitdir"` took the user's other worktree for KOLONİ's, a ref written under
# refs/remotes/origin hid their commit, and their unpushed work went out in a pull request.
BUILT_TARGET = (
    "it writes to a place built at run time ($(...), a variable, Join-Path, git "
    "rev-parse), which may be the project's shared git - another worktree's link, HEAD "
    "or history, the user's branches and remotes: asked at every level"
)
# What builds a path at run time: a substitution or a variable (`$(`, `${`, `$x` - not `$null`), a
# backtick, a bracket (PowerShell's `( ... )`), cmd's `%x%` and a `for` loop's `%i` / `%%i`, xargs'
# and find's `{}`, Join-Path, Split-Path, git rev-parse.
_BUILT = re.compile(
    r"(?i)\$(?!null\b)[\w({]|[`(]|%\w+%|(?<![%\w])%%?[a-z](?![\w%])|\{\}"
    r"|join-path|split-path|rev-parse"
)
_NULL = re.compile(r"(?i)\$null|/dev/null|nul")  # (what is written there is thrown away)
_IO_WRITE = re.compile(r"(?i)\[(?:system\.)?io\.file\]::(?:write|append)\w*\(")
# What writes the place it is given last, or by `-t` / `--target-directory` / `-Destination`.
_WRITES_TO_LAST = frozenset(
    {"cp", "mv", "copy", "move", "copy-item", "cpi", "move-item", "mi", "install", "ln"}
)
# PowerShell's writers: the parameters that name what they write, by any start of the name...
_PS_TARGETS = {
    **dict.fromkeys(
        ("set-content", "sc", "add-content", "ac"), ("path", "literalpath", "pspath", "lp")
    ),
    "out-file": ("filepath", "path", "literalpath", "pspath", "lp"),
    **dict.fromkeys(("new-item", "ni"), ("path", "name")),
    "tee-object": ("filepath", "literalpath", "path"),
}
# ...those whose value is no path (another's value counts as one: it may name what is written),
# and their switches.
_PS_NOT_PATHS = (
    "value",
    "inputobject",
    "encoding",
    "itemtype",
    "type",
    "stream",
    "delimiter",
    "width",
    "filter",
    "include",
    "exclude",
    "credential",
    "target",
)
_PS_SWITCHES = frozenset(
    {
        "force",
        "nonewline",
        "append",
        "noclobber",
        "passthru",
        "whatif",
        "confirm",
        "asbytestream",
        "verbose",
        "debug",
    }
)
_DEEPEST = 4  # (shells handed shells: deeper, asked)
# Built, yet no place a line could aim at the shared git: cured narrowly (`_curing`) - the temp
# folder by its variable (`$TMPDIR/f`, `$env:TEMP\a`), the folder the line runs in at the start of
# the target (`$PWD/x`, `$(pwd)/x`, `(Join-Path $PWD x)`), a `$(date ...)` in the file's own name
# (`build-$(date +%s).log`, no `/`, `.` or quote in its format), a `for` loop's variable over a
# glob or names written out (`for f in *.py`: no `$`, bracket, backtick or `..` in its list, no
# path from a root). Never where the target climbs (`..`), nor where the line gives that name a
# value (`_assigned`: `TMPDIR=`, `read ... PWD`, `Set-Item env:TEMP`). Any other built place stays
# asked.
_TEMP_VAR = re.compile(
    r"(?i)^(['\"]?)\$(?:\{(?:tmpdir|tmp|temp)\}|(?:tmpdir|tmp|temp)\b|"
    r"env:(?:temp|tmp)\b)"
)
_PWD_START = re.compile(r"(?i)^(['\"]?)(?:\$\{pwd\}|\$pwd\b|\$\(pwd(?:\s+-W)?\))(?=[\\/'\"]|$)")
_JOIN_PWD = re.compile(r"(?i)\(\s*join-path\s+\$pwd\s+['\"]?[^()$`'\"\s]+['\"]?\s*\)")
# (each repeat takes a character that is no space: `(?:\s+x*)*` tried every split of a run of
# spaces - exponential, and the line is the model's)
_DATE_NAME = re.compile(r"\$\(date(?:\s+[^()`$/.'\"\\\s]+)*\s*\)(?=[^\\/]*$)")
_FOR_LIST = re.compile(r"(?:^|[\s;&|(])for\s+(\w+)\s+in\s+([^;\n]*)")


_GIVES = frozenset(
    {
        "read",
        "export",
        "declare",
        "typeset",
        "local",
        "readonly",
        "set",
        "set-variable",
        "new-variable",
        "sv",
        "nv",
        "set-item",
        "si",
        "new-item",
        "ni",
        "printf",
        "getopts",
    }
)
_LOOPS = re.compile(r"(?i)(?:^|[\s;&|(])(for|select)\s+(\w+)\s+in\b")


def _assigned(line: str) -> set[str]:
    """The names a line gives a value, in lower case: `x=`, `x+=`, `$env:x =`; any name after
    `read` / `export` / `declare` / `typeset` / `local` / `readonly` / `set` / `printf -v` /
    `getopts` / `Set-Variable` / `New-Variable` / `Set-Item env:` / `New-Item env:` in its part;
    `SetEnvironmentVariable('x'`; a `for` or `select` loop's name. Linear: each part read once."""
    names = {
        found[1].casefold()
        for found in re.finditer(r"(?<![\w$.-])(?:\$env:)?([A-Za-z_]\w*)\s*\+?=", line)
    }
    names |= {
        found[1].casefold()
        for found in re.finditer(r"(?i)setenvironmentvariable\(\s*['\"](\w+)", line)
    }
    names |= {found[2].casefold() for found in _LOOPS.finditer(line)}
    for part in re.split(r"[;&|\n]", line):
        words = [
            re.sub(r"(?i)^(?:env:[\\/]?|-\w+:)", "", word.strip("'\"$")).split("=")[0].casefold()
            for word in part.split()
        ]
        given = next((at for at, word in enumerate(words) if word in _GIVES), None)
        names |= set(words[given + 1 :]) if given is not None else set()
    return names


def _curing(line: str, outer: frozenset[str] = frozenset()) -> Callable[[str], str]:
    """`_writes_built`'s cure for `line`, read once: a write's target as `_BUILT` judges it.
    `outer`: the names the line that hands this one on gives a value (`TMPDIR=x sh -c '...'`)."""
    assigned = _assigned(line) | outer
    temp, here = not assigned & {"tmpdir", "tmp", "temp"}, "pwd" not in assigned
    loops = [(found[1], found[2]) for found in _FOR_LIST.finditer(line)]
    # (a loop's own name is no setter of it - but another loop, or any other setter, is)
    others = _assigned(_FOR_LIST.sub(" ", line)) | outer
    literal = {
        name: not re.search(r"[$`(]|\.\.", items)
        and not any(_full(item.strip("'\"")) for item in items.split())
        for name, items in loops
    }
    names = {name for name, items in loops if literal[name] and name.casefold() not in others}
    either = "|".join(sorted(names))
    pattern = re.compile(rf"\$(?:\{{(?:{either})\}}|(?:{either})\b)") if names else None

    def cured(target: str) -> str:
        if ".." in target:
            return target
        target = _TEMP_VAR.sub(r"\1x", target) if temp else target
        target = _JOIN_PWD.sub("x", _PWD_START.sub(r"\1x", target)) if here else target
        target = _DATE_NAME.sub("x", target)
        return pattern.sub("x", target) if pattern else target

    return cured


def _shell_words(line: str) -> list[str]:
    """A line's words with what each holds kept whole - its quotes, a `$( ... )` and a `( ... )`
    with the spaces and quotes inside (`"$(dirname "$(git rev-parse --git-dir)")/x"`, `((Split-Path
    $p) + '/x')`) - and what joins or redirects commands (`;` `&` `|` `<` `>` `>&` `,` a line's
    end) as words of their own. Linear; a quote or a bracket that does not close holds the rest.
    shortcut: an escaped quote (`"a\\"b"`) closes its quotes here; read escapes if that is met."""
    words: list[str] = []
    word: list[str] = []
    held: list[str] = []
    for at, char in enumerate(line):
        if _holding(char, line[at - 1 : at], held) or not (char.isspace() or char in ";&|<>,"):
            word.append(char)
            continue
        if word:
            words.append("".join(word))
            word = []
        if char in "&|" and words and words[-1] == ">":  # (`2>&1`, `>& f`; `>|`: a write)
            words[-1] = ">" + char
        elif not char.isspace() or char == "\n":
            words.append(char)
    return [*words, "".join(word)] if word else words


def _holding(char: str, before: str, held: list[str]) -> bool:
    """`_shell_words`: whether `char` is in quotes or a bracket, or opens or closes one - `held`
    the ones open, innermost last: in double quotes `$(` opens a bracket, in a bracket quotes open
    anew."""
    top = held[-1] if held else ""
    if top in ("'", '"'):
        if char == top:
            held.pop()
        elif top == '"' and char == "(" and before == "$":
            held.append("(")
        return True
    if char in "'\"(":
        held.append(char)
        return True
    if char == ")" and top == "(":
        held.pop()
        return True
    return bool(held)


def _writes_built(line: str, depth: int = 0, outer: frozenset[str] = frozenset()) -> bool:
    """Whether a line writes to a place built at run time (`_BUILT`): a redirect's target (`>`,
    `>>`, `2>`; not `2>&1`, nor `$null`, `/dev/null`, `NUL`), a copy's, move's, install's or link's
    (`_WRITES_TO_LAST`), what `tee` writes, a PowerShell writer's path (`_ps_targets`),
    `[IO.File]::Write*`'s first argument - or any write after a `cd` to such a place (`cd
    "$(git rev-parse --git-dir)" && echo x > config`). In what a shell or a wrapper is handed too
    (`_unwrapped`), `_DEEPEST` shells deep: deeper, asked. A data heredoc's body and a comment
    write nothing.
    shortcut: a write by a program's own way (`sed -i`, `find -exec`, `git config --file`, code in
    `python -c`, a script) is not read, nor a redirect inside a substitution's quotes; list them
    where an agent is seen to write the shared git so."""
    if depth > _DEEPEST:
        return True
    line = _uncommented(
        _blanked(line, ((start, end) for start, end, _quoted in _data_bodies(line)))
    )
    for found in _IO_WRITE.finditer(line):
        first = _shell_words(line[found.end() :])[:1]
        if first and _BUILT.search(first[0]):
            return True
    given = outer | _assigned(line)  # (what a line it hands a shell is read with)
    moved, part, cured = False, [], _curing(line, outer)
    for word in [*_shell_words(line), ";"]:
        if word not in (";", "&", "|", "\n"):
            part.append(word)
            continue
        targets, went = _part_targets(part, depth, given) if part else ([], False)
        if (
            UNREAD in targets
            or any(_BUILT.search(cured(one)) for one in targets)
            or (moved and targets)
        ):
            return True
        moved, part = moved or went, []
    return False


def _part_targets(
    words: list[str], depth: int, given: frozenset[str] = frozenset()
) -> tuple[list[str], bool]:
    """What one part of a line writes (`_writes_built`) - UNREAD where a line it hands a shell
    writes to a place built at run time, or is not read - and whether it is a `cd` to such a
    place."""
    targets: list[str] = []
    rest: list[str] = []
    at = 0
    while at < len(words):
        word = words[at]
        at += 1
        if word in (">", ">&", ">|", "<"):
            if rest and re.fullmatch(r"[\d*]", rest[-1]):  # (`2>`, `*>`: the stream's number)
                rest.pop()
            while word == ">" and at < len(words) and words[at] in (">", ">|"):  # (`>>`)
                at += 1
            # (`>&1`, `>&-`: a stream joined or closed; `>& f`, bash's, writes f)
            if (
                word != "<"
                and at < len(words)
                and not _NULL.fullmatch(words[at].strip("'\""))
                and not (word == ">&" and re.fullmatch(r"\d+-?|-", words[at]))
            ):
                targets.append(words[at])
            at += 1  # (the place written, read or joined to)
            continue
        rest.append(word)
    went = False
    rest = _led(rest)  # (`if x then`, cmd's `for ... do copy x %%i`)
    for one in _unwrapped(rest) if rest else []:
        word = one[0] if len(one) == 1 else ""
        handed = (
            len(word) > 1
            and word[0] in "'\""
            and word[-1] == word[0]
            and any(map(str.isspace, word))
        )
        if one == [UNREAD] or handed and _writes_built(word[1:-1], depth + 1, given):
            return [*targets, UNREAD], False  # (a line handed a shell or a wrapper, quoted)
        if one:
            written, moved = _command_targets(one)
            targets += written
            went = went or moved
    return targets, went


def _command_targets(words: list[str]) -> tuple[list[str], bool]:
    """The places a command's words name as what it writes (`_writes_built`), and whether it is a
    `cd` to a place built at run time."""
    program, rest = _program(words[0]), words[1:]
    if program in _CD:
        return [], any(_BUILT.search(word) for word in rest)
    if program == "tee":  # (any file it is given; PowerShell's is Tee-Object)
        return rest, False
    # A link made, or what it leads to: a write there goes through it (`ln -s "$D" g`, `mklink /J
    # g %D%`, `New-Item -ItemType Junction -Target $d`).
    if (
        program in ("ln", "mklink")
        or program in ("new-item", "ni")
        and any(
            word.casefold().rsplit(":", 1)[-1] in ("junction", "symboliclink", "hardlink")
            for word in rest
        )
    ):
        return [
            word for word in rest if not word.startswith("/" if program == "mklink" else "-")
        ], False
    if program in _PS_TARGETS:
        return _ps_targets(program, rest), False
    if program not in _WRITES_TO_LAST:
        return [], False
    given = [
        value
        for at in range(len(rest))
        if (value := _option_value(rest, at, _TARGET_OPTIONS)) is not None
    ]
    clustered = [
        found[1] or (rest[at + 1] if at + 1 < len(rest) else "")
        for at, word in enumerate(rest)
        if program in ("cp", "mv", "install", "ln") and (found := _CLUSTER_TARGET.fullmatch(word))
    ]
    return [*given, *clustered, *[word for word in rest if not word.startswith("-")][-1:]], False


def _ps_targets(program: str, rest: list[str]) -> list[str]:
    """What a PowerShell writer writes (`_PS_TARGETS`): the value of a path parameter, by any start
    of its name - and of one not known to take what is no path (`_PS_NOT_PATHS`) - and its first
    word given by position. A switch (`_PS_SWITCHES`) takes no value."""
    names = _PS_TARGETS[program]
    found: list[str] = []
    placed: list[str] = []
    at = 0
    while at < len(rest):
        word = rest[at]
        at += 1
        if not re.match(r"-[A-Za-z]", word):
            placed.append(word)
            continue
        name, colon, value = word[1:].partition(":")
        name = name.casefold()
        if not colon:
            if name in _PS_SWITCHES:
                continue
            value, at = (rest[at] if at < len(rest) else ""), at + 1
        if any(full.startswith(name) for full in names) or not any(
            full.startswith(name) for full in _PS_NOT_PATHS
        ):
            found.append(value)
    return [*found, *placed[:1]]


DELETES_THROUGH_LINKS = (
    "it deletes in a working copy, where node_modules, .venv and venv are links to the "
    "project's own: through one it would delete the project's"
)
REBUILDS_THROUGH_LINKS = (
    "it rebuilds a dependency folder in a working copy, where node_modules, .venv and venv "
    "are links to the project's own: through one it would empty and rebuild the project's"
)
WRITES_THROUGH_LINKS = (
    "it writes in node_modules, .venv or venv, in a working copy links to the project's own: "
    "through one it would write the project's"
)
# What writes the file it is given last (a copy's or a move's target), and what writes any it
# is given (`_writes_links`).
_WRITES_LAST = frozenset({"cp", "mv", "copy", "move", "copy-item", "cpi", "move-item", "mi"})
_WRITES_ANY = frozenset({"set-content", "sc", "add-content", "ac", "out-file", "tee", "tee-object"})
# A copy's or move's target by its option (`Copy-Item -Destination x`, `cp -t x`).
_TARGET_OPTIONS = ("-destination", "-t", "--target-directory")
# GNU cp's and mv's short options in one word, the target's `t` among them (`-S` takes a value).
_CLUSTER_TARGET = re.compile(r"-[^-St]*t(.*)")


def _in_linked(word: str, own: re.Pattern | None = None) -> bool:
    """Whether a path a command names leads into a linked folder of a copy, by any of its parts
    once read where it leads (`node_modules/x`, `.\\.venv\\x`, `-Path:venv/x`,
    `src/../node_modules/x`) - by the copy's own full path too (`own`: its tree's spellings)."""
    path = re.sub(r"^-[\w-]*[:=]", "", word.strip("'\""))
    found = own.match(os.path.normcase(path)) if own is not None else None
    if found:
        path = os.path.normcase(path)[found.end() :]
    elif _full(path):
        return False
    # (as written, or where it leads: `node_modules/../src` passes through the link)
    parts = [
        *re.split(r"[\\/]", path),
        *posixpath.normpath(path.replace("\\", "/").lstrip("/") or ".").split("/"),
    ]
    return any(part.casefold() in LINKED for part in parts)


def _writes_links(words: list[str], own: re.Pattern | None = None) -> bool:
    """Whether a part writes in a linked folder (`_in_linked`): by a redirect (`>`, `>>`, `2>`,
    glued to the path or to what comes before), a copy's or move's target (its last word, or
    its `-Destination` / `-t` / `--target-directory`), `Set-Content` / `Add-Content` /
    `Out-File` / `tee`, or `sed -i`.
    shortcut: by the path as written from where the part runs - one after a `cd` into the
    folder - and what writes by a program's own way (`New-Item -Value`, `[IO.File]::WriteAllText`,
    `touch`, `mkdir`, `robocopy`, `xcopy`, `tar -C`, `unzip -d`, `Expand-Archive`, `perl -pi`,
    code in `python -c`, `npm config set`, `pip-sync`, `corepack`, a script) is not seen -
    nor `install -D`, `curl -o`, `wget -O`, `Invoke-WebRequest -OutFile`, `uv pip compile -o`,
    a linked name in quotes of its own (`"node_modules"/x`), or a target with a comment after it
    read as the last word (`cp a.js node_modules/x # ok`); 0.1.6 (review rounds 4-5)."""
    for at, word in enumerate(words):
        redirect = re.search(r">{1,2}(?!&)", word)
        target = (
            word[redirect.end() :] or (words[at + 1] if at + 1 < len(words) else "")
            if (redirect)
            else ""
        )
        if target and _in_linked(target, own):
            return True
    program, rest = _program(words[0]), words[1:]
    if program in _WRITES_LAST:
        targets = [
            value
            for at, word in enumerate(rest)
            if (value := _option_value(rest, at, _TARGET_OPTIONS)) is not None
        ]
        named = [word for word in rest if not word.startswith("-")]
        # (GNU's `-t` in a cluster, `cp -rt x a.js`, `cp -tx a.js`: as well, never instead - in
        # PowerShell `cp` is Copy-Item, whose `-Container` is no target)
        clustered = [
            found[1] or (rest[at + 1] if at + 1 < len(rest) else "")
            for at, word in enumerate(rest)
            if program in ("cp", "mv") and (found := _CLUSTER_TARGET.fullmatch(word))
        ]
        return any(_in_linked(one, own) for one in (targets or named[-1:]) + clustered)
    in_place = program == "sed" and any(word.startswith(("-i", "--in-place")) for word in words)
    return (program in _WRITES_ANY or in_place) and any(_in_linked(one, own) for one in rest)


def _option_value(words: list[str], at: int, options: Iterable[str]) -> str | None:
    """The value of the option at `at` where it is one of `options` (`-t x`, `-Destination:x`,
    `--target-directory=x`), by any case; None for another word."""
    name, sep, glued = (
        re.split(r"([:=])", words[at], maxsplit=1)
        if re.search(r"[:=]", words[at])
        else (words[at], "", "")
    )
    if name.casefold() not in options:
        return None
    return glued if sep else (words[at + 1] if at + 1 < len(words) else "")


# npm 11's own names for its commands (`lib/utils/cmd-list.js`): a verb is read as npm reads it.
_NPM_CI = frozenset({"ci", "clean-install", "ic", "install-clean", "cit", "install-ci-test", "sit"})
_NPM_INSTALLS = _NPM_CI | {
    "install",
    "i",
    "add",
    "in",
    "ins",
    "inst",
    "insta",
    "instal",
    "isnt",
    "isnta",
    "isntal",
    "isntall",
    "install-test",
    "it",
    "uninstall",
    "rm",
    "r",
    "remove",
    "un",
    "unlink",
    "update",
    "up",
    "upgrade",
    "udpate",
    "rebuild",
    "rb",
    "dedupe",
    "ddp",
    "prune",
    "link",
    "ln",
}
# Package managers' options that take a value before the verb (`npm --prefix web ci`, `pnpm -C
# web i`, `uv --directory x sync`): `_after_options` reads past them to the verb.
_PM_VALUES = frozenset(
    {
        "--prefix",
        "-C",
        "--cwd",
        "--dir",
        "--filter",
        "-F",
        "--workspace",
        "-w",
        "--registry",
        "--cache",
        "--userconfig",
        "--globalconfig",
        "--loglevel",
        "--directory",
        "--project",
        "--python",
        "-p",
        "--config-file",
    }
)
# Each package manager's own options before its verb, as it reads them: (those that take a value,
# flags) - `-p` takes a value in uv's, in npm's it is `--parseable`. One not here is read both
# ways (`_verbs`).
_PM_OPTIONS = {
    "npm": (
        frozenset(
            {
                "--prefix",
                "-C",
                "--workspace",
                "-w",
                "--registry",
                "--cache",
                "--userconfig",
                "--globalconfig",
                "--loglevel",
                "--include",
                "--omit",
                "--install-strategy",
            }
        ),
        frozenset(
            {
                "-p",
                "--parseable",
                "-s",
                "--silent",
                "-q",
                "--quiet",
                "-g",
                "--global",
                "-y",
                "--yes",
                "-d",
                "--verbose",
                "--json",
                "-D",
                "-S",
                "-O",
                "-E",
            }
        ),
    ),
    "pnpm": (
        frozenset({"-C", "--dir", "--filter", "-F", "--reporter"}),
        frozenset({"-w", "--workspace-root", "-r", "--recursive", "-s", "--silent", "-g"}),
    ),
    "yarn": (frozenset({"--cwd"}), frozenset({"-s", "--silent", "-W"})),
    "uv": (
        frozenset(
            {
                "--directory",
                "--project",
                "--python",
                "-p",
                "--config-file",
                "--cache-dir",
                "--color",
            }
        ),
        frozenset(
            {
                "-q",
                "--quiet",
                "-v",
                "--verbose",
                "--offline",
                "--no-cache",
                "-n",
                "--frozen",
                "--locked",
            }
        ),
    ),
    "pip": (
        frozenset(
            {
                "--proxy",
                "--cache-dir",
                "--log",
                "--timeout",
                "--exists-action",
                "--python",
                "--index-url",
                "-i",
                "--retries",
                "--cert",
                "--client-cert",
            }
        ),
        frozenset(
            {
                "-q",
                "--quiet",
                "-v",
                "--verbose",
                "--isolated",
                "--no-cache-dir",
                "--disable-pip-version-check",
                "--user",
            }
        ),
    ),
    "poetry": (
        frozenset({"-C", "--directory", "-P", "--project"}),
        frozenset({"-q", "--quiet", "-n", "--no-interaction", "-v"}),
    ),
}
# The runners whose first word is the package they run (`npx x`): what they hand on.
_RUNNERS_OF = frozenset(name for name, words in _RUNS_PACKAGE.items() if not words)
# ...and those whose `run` runs a program in an environment (`uv run pip install x`, `poetry run
# npm ci`, `uv tool run`, `pipx run`) - review rounds 4-5.
_ENV_RUNNERS = frozenset({"uv", "poetry", "pipenv", "pdm", "hatch", "conda", "pipx"})
# An option's first mark, and the dashes a phone or an editor types for it (`npm –g ci`): an
# option not known, read both ways.
_DASHES = ("-", "\u2013", "\u2014", "\u2212")
# What empties a dependency folder and makes it anew - measured 29 Oct through a junction:
# `npm ci` emptied the project's node_modules, `uv venv` its .venv; `uv sync` makes the venv
# anew when its interpreter changed. shortcut: `pnpm install --frozen-lockfile`, `yarn
# install --force` and `uv run x` (it syncs the environment first, so may make the venv anew
# too) are not measured, so not here; and a script that runs one of these is not seen -
# measure and list them if met. (A venv made at a linked folder - `python -m venv` with any
# prefix of `--clear` argparse takes, `virtualenv` - is one too: `_makes_venv`.)
_REBUILDERS = frozenset({*(("npm", verb) for verb in _NPM_CI), ("uv", "venv"), ("uv", "sync")})


def _verbs(words: list[str], left: list[int] | None = None) -> list[tuple[str, str]]:
    """Every (program, verb) a package manager's part may run: its words past the options before
    the verb - an option of `_PM_OPTIONS` read as it is; one not known, without `=`, both as a
    flag and as taking a value, so either word after it may be the verb (fail closed) - `uv pip
    x` as pip's own, a module an interpreter runs as the program (`_module_run`), and what a
    runner hands a package manager past any options of its own (`npm exec --yes -- npm i x`,
    `npm exec -c "npm ci"`, `uv run --with x pip install y`). Past MAX_OTHER_READINGS of those
    (`left`), (program, UNREAD): an install, as what is not read may be one."""
    left = [MAX_OTHER_READINGS] if left is None else left
    words = _module_run(words) or words
    program = _program(words[0])
    values, flags = _PM_OPTIONS.get(
        "pip" if program.startswith("pip") else program, (_PM_VALUES, frozenset())
    )
    rest, found, at, maybe = words[1:], [], 0, False
    while at < len(rest):
        word = rest[at]
        if word.startswith(_DASHES):
            known = "=" in word or word in flags or word in values
            at += 2 if "=" not in word and word in values else 1
            maybe = not known  # (its value, or the verb)
            continue
        found.append(at)
        if not maybe:
            break
        at, maybe = at + 1, False
    verbs = [(program, rest[at]) for at in found]
    for at in found:
        verb = rest[at].casefold()
        if program == "uv" and verb == "pip":
            verbs += _verbs(["pip", *rest[at + 1 :]], left)
        elif (
            program in _RUNNERS_OF
            or verb in _RUNS_PACKAGE.get(program, ())
            or (verb in ("run", "tool") and program in _ENV_RUNNERS)
        ):
            # (a runner's own options too: `npx --call="npm ci"`, `npx -c "npm ci"`)
            inner = rest if program in _RUNNERS_OF else rest[at + 1 :]
            for start, word in enumerate(inner):
                # (a command glued to its option, its quotes split by the line's words:
                # `npm exec --call="npm ci"`, `-c='npm i x'`)
                word = re.sub(r"^-[\w-]*=", "", word)
                runs = _program(word)
                line = bool(re.search(r"\s", word))
                if not (
                    line
                    or runs in _INSTALLERS
                    or runs.startswith(("pip", "python"))
                    or runs == "py"
                ):
                    continue
                if left[0] <= 0:
                    return [*verbs, (program, UNREAD)]
                left[0] -= 1
                verbs += (
                    [one for part in _parts(word) if part for one in _verbs(part, left)]
                    if (line)
                    else _verbs([word.strip("'\""), *inner[start + 1 :]], left)
                )
    return verbs


def _makes_venv(words: list[str], own: re.Pattern | None = None) -> bool:
    """Whether a part makes a venv at a linked folder (`_in_linked`, by the copy's own full path
    too: `own`): `python -m venv` or `-m virtualenv`, or `virtualenv`, with any options - over one
    there it rewrites it.
    shortcut: by any part of the path, so a venv a folder deeper (`python -m venv build/venv`)
    is asked as a rebuild though only the copy's top `venv` is linked (OA-d); match the linked
    folder from the copy's own top in 0.1.6."""
    module = _module_run(words)
    made = (
        module[1:]
        if module[:1] in (["venv"], ["virtualenv"])
        else (words[1:] if _program(words[0]) == "virtualenv" else [])
    )
    return any(_in_linked(word, own) for word in made if not word.startswith("-"))


def _recursive(word: str) -> bool:
    """A delete's flag that goes down into folders: `-r`, `-rf`, `-R`, `-Recurse`, `/s`."""
    word = word.casefold()
    return (
        word in ("/s", "--recursive")
        or word.startswith("-rec")
        or bool(re.fullmatch(r"-[a-z]{1,4}", word))
        and "r" in word
    )


def _through_links(words: list[str], own: re.Pattern | None = None) -> str:
    """Why a command may reach through a linked folder into the project's own, "" for none:
    a delete that goes down into folders or names a linked one, what deletes folders by
    itself (`find -delete`, `git worktree remove`, `robocopy /MIR` or `/PURGE`), and what
    empties a dependency folder to make it anew (`_REBUILDERS`, `_makes_venv`; `own`: the copy's
    tree's spellings)."""
    program, rest = _program(words[0]), words[1:]
    if any((manager, verb.casefold()) in _REBUILDERS for manager, verb in _verbs(words)) or (
        _makes_venv(words, own)
    ):
        return REBUILDS_THROUGH_LINKS
    if (
        program == "find"
        and "-delete" in rest
        or program == "robocopy"
        and any(w.casefold() in ("/mir", "/purge") for w in rest)
        or program == "git"
        and _after_options(rest, _GIT_VALUE_OPTIONS)[:2] == ["worktree", "remove"]
    ):
        return DELETES_THROUGH_LINKS
    return (
        DELETES_THROUGH_LINKS
        if program in _DELETERS
        and any(
            _recursive(word) or any(part.casefold() in LINKED for part in re.split(r"[\\/]", word))
            for word in rest
        )
        else ""
    )


def _spellings(path: str) -> re.Pattern:
    """A folder's path as a command may write it, as `os.path.normcase` gives it: as given,
    resolved, and Git Bash's `/c/...` for a drive's - not a longer name it begins
    (`Proj` is not `Proj-old`)."""
    forms = {path.rstrip("\\/"), os.path.realpath(path)}
    forms |= {f"/{form[0]}{form[2:]}" for form in list(forms) if re.match(r"[A-Za-z]:", form)}
    # (Grouped: the end of the name holds for every spelling, not the last one alone.)
    return re.compile(
        "(?:" + "|".join(re.escape(os.path.normcase(form)) for form in forms) + r")(?![\w.-])"
    )


# A folder a command may name by a variable (`%LOCALAPPDATA%`, `$env:SystemRoot`, `${HOME}`,
# `$HOME`) or `~`: read with KOLONİ's own value where that is one full path (`_as_path_line`) -
# never by the shell's own place (`$PWD`, `$OLDPWD`, `$_`), which KOLONİ's is not.
_SHELLS_OWN = frozenset({"PWD", "OLDPWD", "_"})
_VARIABLE = re.compile(r"(?i)%(\w+)%|\$\{?env:(\w+)\}?|\$\{(\w+)\}|\$(\w+)")
_TILDE = re.compile(r"(?:^|(?<=[\s'\"=:(,]))~(?=[\\/\s'\")]|$)")
# This machine's own drives by a share or a device path: `\\localhost\c$\x`, `\\127.0.0.2\c$\x`,
# `\\[::1]\c$\x`, `\\<its name>\c$\x` (`\\$env:COMPUTERNAME\c$\x` too), `\\?\UNC\localhost\c$\x`,
# `\\?\C:\x`, `\\.\C:\x`.
# shortcut: by its LAN address or full DNS name, or a share of a folder (`\\localhost\Users\x`),
# it is not read so; list the machine's addresses and shares if an agent is seen to write one.
_THIS_MACHINE = os.environ.get("COMPUTERNAME", "")
_LOCAL_SHARE = re.compile(
    r"(?i)[\\/]{2}(?:[?.][\\/]UNC[\\/])?(?:localhost|127(?:\.\d{1,3}){3}|"
    r"\[::1\]|\?|\.|%computername%|\$\{?(?:env:)?computername\}?"
    + (f"|{re.escape(_THIS_MACHINE)}" if _THIS_MACHINE else "")
    + r")[\\/](?:([a-z])\$(?=[\\/])|(?=[a-z]:))"
)
# A full path in a line (from a drive or a root), and a `..` part in one.
_FULL_PATH = re.compile(r"(?:^|(?<=[\s'\"=<>(,;|&:]))(?:[A-Za-z]:|[\\/])[^\s'\"<>|;&,()]*")
_UP = re.compile(r"(?:^|[\\/])\.\.(?:[\\/]|$)")


def _variable_folder(found: re.Match) -> str:
    name = next(filter(None, found.groups()))
    home = os.path.expanduser("~") if name.upper() in ("HOME", "USERPROFILE") else None
    value = (
        None
        if name.upper() in _SHELLS_OWN
        else (os.environ.get(name.upper() if os.name == "nt" else name) or home)
    )
    # (one full path: `PATH`'s list, a word or a number is no folder)
    return value if value and _full(value) and os.pathsep not in value else found[0]


def _expanded(command: str) -> str:
    """A command with its paths as the machine reads them: a folder by its variable
    (`_variable_folder`, `%HOMEDRIVE%%HOMEPATH%`, `~`) with KOLONİ's own value, this machine's
    drives by a share (`_LOCAL_SHARE`), separators doubled or with `.` between them as one
    (`C:\\\\Users`, `C://x`, `/c//x`, `C:\\.\\x`) - a doubled one that starts a word stays
    (`\\\\server\\share`) - and a full path's `..` gone where it leads (`C:\\a\\..\\proj`); on
    Windows a name's last dots go (`proj.\\x`, `proj.` are `proj` there).
    shortcut: a short name (`PROJ~1`) and a name's last spaces are not read so; resolve them if
    an agent is seen to write one."""
    line = _TILDE.sub(
        lambda _found: os.path.expanduser("~"), _VARIABLE.sub(_variable_folder, command)
    )
    line = _LOCAL_SHARE.sub(lambda found: f"{found[1]}:" if found[1] else "", line)
    if os.name == "nt":
        line = re.sub(r"(?<=\w)\.+(?=[\\/\s'\");,]|$)", "", line)
    line = re.sub(r"(?<=[^\s'\"=(])[\\/](?:\.?[\\/])+", lambda _found: os.sep, line)
    climbs = ntpath.normpath if os.name == "nt" else posixpath.normpath
    return _FULL_PATH.sub(
        lambda found: climbs(found[0]) if _UP.search(found[0]) else found[0], line
    )


def _path_lines(command: str) -> list[str]:
    """A command as its full paths are matched (`_spellings`): as written and as the machine
    reads it (`_as_path_line`) - reading it so may only add what is asked."""
    return list(dict.fromkeys((os.path.normcase(command), _as_path_line(command))))


def _as_path_line(command: str) -> str:
    """A command as its full paths are matched (`_spellings`): `_expanded`, in
    `os.path.normcase`'s case."""
    return os.path.normcase(_expanded(command))


NAMES_PROJECT = (
    "it names the project folder ({root}), outside the working copy it works in: there it "
    "would act on the project itself"
)
# K-koordinasyon: agents work beside each other, each in a copy of its own.
OUT_OF_COPY = (
    "it names {path}, outside the copy it works in - another agent's copy, a worktree of the "
    "project or KOLONİ's own records of the copy: write, move or delete nothing there; say in "
    "the report what should go"
)


def _full(path: str) -> bool:
    """A path from a root, a drive or the home folder: not from where a command runs."""
    return path.startswith(("/", "\\", "~")) or bool(re.match(r"[A-Za-z]:", path))


def _in_copy(path: str, at: str, own: re.Pattern | None) -> str | None:
    """Where `path` leads in a copy, from its folder `at` (both relative to the copy's tree, `/`
    between parts): ".." first where it leads above the tree. A full path only by the tree's own
    (`own`: its spellings, `_spellings`); None for another full path, which is not followed."""
    if _full(path):
        found = own.match(os.path.normcase(path)) if own is not None else None
        if found is None:
            return None
        path, at = os.path.normcase(path)[found.end() :].lstrip("\\/"), "."
    return posixpath.normpath(posixpath.join(at, path.replace("\\", "/") or "."))


def _above(went: str | None) -> bool:
    return went is not None and went.split("/")[0] == ".."


def _cd_to(words: list[str], at: str | None, own: re.Pattern | None) -> str | None:
    """Where a part that changes folder (`_CD`) leaves a command in a copy (`_in_copy`; `at`
    None: not known); None where that is not followed: `popd`, no folder named or more than
    one, a variable, a wildcard or `~`, a full path not of the copy's own tree, a folder from
    where it is not known."""
    named = [
        word for word in words[1:] if not word.startswith("-") and word.casefold() != "/d"
    ]  # (cmd's `cd /d x`)
    if (
        _program(words[0]) in ("popd", "pop-location")
        or len(named) != 1
        or re.search(r"[$%`~*?]", named[0])
        or at is None
        and not _full(named[0])
    ):
        return None
    return _in_copy(named[0], at or ".", own)


# What reads its first word that is no option as a pattern or a script, not a path (`rg
# "from '../x'" src`, `sed "s#../a#../b#"`) - but where an option gave it (`-e x`, `-ex`,
# `--regexp=x`, `-f file`, `-Pattern x`) the words after are paths, a pattern file's too; perl's
# code comes only by `-e`, and `rg --files` takes none.
_POSITIONAL_PATTERN = frozenset(
    {
        "rg",
        "ripgrep",
        "ag",
        "ack",
        "grep",
        "egrep",
        "fgrep",
        "select-string",
        "sls",
        "findstr",
        "sed",
        "awk",
    }
)
_PATTERN_GIVEN = ("-e", "--regexp", "--expression")
_PATTERN_FILE = ("-f", "--file")
# Each search's options known to take no path (review round 4): (short letters that take no
# value - in a cluster too, `-rn` -, short letters that take one, long names written out that
# take none, long names whose value is no path). A long name cut short (`--reg=` may be
# `--regexp`), a cluster holding a letter that takes a value (`-iex`, `-A3`), one whose value
# is a path (`rg --ignore-file`, `--pre`) or any other is not known: past it, the first word is
# no pattern but a path (`_path_words`).
_GREP_OPTIONS = (
    "abcEFGhHiIlLnoPqrRsTUvVwxyzZ0123456789",
    "ABCDdefm",
    "--recursive --dereference-recursive --ignore-case --no-ignore-case --line-number --count "
    "--files-with-matches --files-without-match --invert-match --word-regexp --line-regexp "
    "--extended-regexp --fixed-strings --basic-regexp --perl-regexp --only-matching --quiet "
    "--silent --no-messages --with-filename --no-filename --null --null-data --text "
    "--byte-offset --initial-tab --line-buffered --color --colour",
    "--include --exclude --exclude-dir --context --after-context --before-context --max-count "
    "--label --binary-files --devices --directories",
)
_RG_OPTIONS = (
    "abcFHhiIlLnNopPqsSuUvVwxz0.",
    "ABCdEefgjmMrtT",
    "--hidden --no-ignore --ignore-case --smart-case --case-sensitive --fixed-strings "
    "--word-regexp --line-regexp --line-number --no-line-number --count --count-matches "
    "--files-with-matches --files-without-match --invert-match --only-matching --multiline "
    "--json --vimgrep --heading --no-heading --follow --text --null --pcre2 --stats --trim "
    "--column --no-messages --quiet --no-filename --with-filename --unrestricted --search-zip "
    "--sort-files --no-ignore-vcs --no-ignore-parent --no-config",
    "--glob --iglob --type --type-not --max-count --max-depth --context --after-context "
    "--before-context --replace --encoding --threads --type-add --sort --sortr --color --colors "
    "--max-columns --max-filesize --path-separator --engine",
)
_SLS_OPTIONS = (
    "",
    "",
    "-simplematch -casesensitive -quiet -list -notmatch -allmatches -raw -noemphasis",
    "-context -encoding -culture -include -exclude",
)
_SEARCH_OPTIONS = {
    program: (none, value, frozenset(long_none.split()), frozenset(long_value.split()))
    for program, (none, value, long_none, long_value) in {
        "grep": _GREP_OPTIONS,
        "egrep": _GREP_OPTIONS,
        "fgrep": _GREP_OPTIONS,
        "rg": _RG_OPTIONS,
        "ripgrep": _RG_OPTIONS,
        "select-string": _SLS_OPTIONS,
        "sls": _SLS_OPTIONS,
        "sed": (
            "nrEsuz",
            "efl",
            "--quiet --silent --regexp-extended --separate --unbuffered "
            "--null-data --posix --debug --sandbox --follow-symlinks --in-place",
            "--line-length",
        ),
        "findstr": ("", "", "/b /e /l /r /s /i /x /v /n /m /o /p /offline", ""),
    }.items()
}


def _known_option(word: str, program: str) -> int | None:
    """How many words after it a search's option known to take no path takes (`_SEARCH_OPTIONS`):
    0 (`-rn`, `--include=*.ts`, sed's `-i.bak`, `--`), 1 (`-A 3`, `--include '*.ts'`), None for one
    not known."""
    none, value, long_none, long_value = _SEARCH_OPTIONS.get(
        program, ("", "", frozenset(), frozenset())
    )
    if word == "--":
        return 0
    if program in ("select-string", "sls", "findstr") or word.startswith("--"):
        name, sep, _glued = word.casefold().partition("=" if word.startswith("--") else ":")
        return (
            0
            if name in long_none or sep and name in long_value
            else (1 if name in long_value else None)
        )
    letters = word[1:]
    if program == "sed" and "i" in letters:  # (sed's `-i` takes its suffix glued: `-i.bak`)
        letters = letters[: letters.index("i")]
        return 0 if all(letter in none for letter in letters) else None
    if len(letters) == 1 and letters in value:
        return 1
    return 0 if letters and all(letter in none for letter in letters) else None


def _pattern_option(word: str, program: str) -> tuple[bool, bool, bool] | None:
    """`_path_words`: what a word is where it gives the pattern - (its value is the next word,
    that value is a path - a pattern file -, the word itself holds a path), or None for another
    word. `-e x`, `-ex`, `--regexp=x`, `-f file`, `-ffile`, `--file=file`; Select-String's
    `-Pattern`; findstr's `/c:x`, `/g:file`."""
    low = word.casefold()
    name, sep, _value = low.partition("=")
    if program in ("select-string", "sls"):
        option = low.partition(":")[0]
        return (
            (":" not in low, False, False)
            if len(option) > 4 and "-pattern".startswith(option)
            else None
        )
    if program == "findstr":
        return (False, False, low.startswith("/g:")) if low.startswith(("/c:", "/g:")) else None
    if name in _PATTERN_GIVEN or name in _PATTERN_FILE:
        return not sep, name in _PATTERN_FILE, bool(sep) and name in _PATTERN_FILE
    if re.fullmatch(r"-[ef]\S+", word):  # (glued: `-ex`, `-es/a/b/`, `-fx.sed`)
        return False, False, word[1] == "f"
    return None


def _path_words(words: list[str]) -> list[str]:
    """The words of a part that may be paths: a search's or sed's pattern left out - the first
    word that is no option, where no option gave the pattern (`_pattern_option`) and every option
    before it is known to take no path (`_known_option`); Select-String's `-Path` and
    `-LiteralPath` values are paths.
    shortcut: a pattern with `(` in it reaches here cut, as `_BLOCKS` splits inside quotes
    (`rg "require('../lib')" src`, `grep -rn "import('../x')" src`, `rg -g '*.ts' "'../" src`,
    `grep -E "from '(\\.\\./)+" src`), and its `..` is asked as a climb (OA-c); read the line's
    quotes before its blocks in 0.1.6."""
    program = _program(words[0])
    if program not in _POSITIONAL_PATTERN | {"perl"}:
        return words
    kept, given, known, at = words[:1], program == "perl" or "--files" in words, True, 1
    while at < len(words):
        word, found = words[at], _pattern_option(words[at], program)
        if found is not None:
            value_next, value_path, holds_path = found
            given, kept = True, [*kept, word] if holds_path else kept
            if value_next and at + 1 < len(words):
                kept += [words[at + 1]] if value_path else []
                at += 1
        elif program in ("select-string", "sls") and word.casefold().partition(":")[0].startswith(
            ("-pa", "-li", "-lp", "-ps")
        ):  # (-Path, -LiteralPath: their value a path)
            kept.append(word)
            known = known and word.casefold().partition(":")[0] in (
                "-path",
                "-literalpath",
                "-lp",
                "-pspath",
            )  # (`-Pa` may be -Pattern)
            if ":" not in word and at + 1 < len(words):
                kept.append(words[at + 1])
                at += 1
        elif word.startswith("-") or program == "findstr" and word.startswith("/"):
            kept.append(word)
            takes = _known_option(word, program)
            known = known and takes is not None
            if takes and at + 1 < len(words):
                kept.append(words[at + 1])
                at += 1
        elif given or not known:
            kept.append(word)
        else:
            given = True  # (this word: the pattern)
        at += 1
    return kept


def _climbing(words: list[str], at: str | None, own: re.Pattern | None, code: bool = False) -> str:
    """A path among `words` that leads above a copy's tree by `..` from its folder `at` - from
    one not known (None), any that climbs; split at what may stand around a path in a line
    (`--dir="../x"`, `>"..\\x"`) - and, in a line of code handed to an interpreter (`code`), at
    its quotes and brackets (`open(r'..\\x')`); as written and as the shell reads it (`_as_read`:
    `.''./`, sh's `.\\./`). A search's pattern is none (`_path_words`).
    shortcut: a path glued to a short option (`-o../../x`) and findstr's `/F:` `/D:` values are
    not split off, so not read; 0.1.6 (review round 4)."""
    split = r"[=<>,@'\"(]" if code else r"[=<>,@]"
    for word in _path_words(words) if words else ():  # (a program too: `..\.venv\Scripts\x`)
        for written in dict.fromkeys((word, _as_read(word))):
            for piece in re.split(split, re.sub(r"^-[\w-]*:", "", written.strip("'\""))):
                if ".." in re.split(r"[\\/]", piece) and (
                    at is None and not _full(piece) or _above(_in_copy(piece, at or ".", own))
                ):
                    return piece
    return ""


def _climbs_out(command: str, cwd: str | None, own: str | None) -> str:
    """What a command run in a copy names above the copy's tree by `..` - from where it runs
    (`cwd`, in the copy), followed through each plain `cd` (`sl`, `pushd`, `Set-Location`) to a
    folder of the copy, or from the tree's own full path (`own`); past a `cd` not followed (a
    variable, another full path, `popd`), any `..`: fail closed. A variable set to a path that
    climbs counts too (`D=../../b; cp x $D/y`). "" for none, and where it runs is not known
    (`cwd` None). `HEAD..main` is no `..`.
    shortcut: honest lines, not a wall - a path built, or held in a script, is not seen; the
    folder a command runs in, and its copy's folder, are the wall."""
    if cwd is None:
        return ""
    # (as written - sh's `.\./` is `../` - and with its paths as the machine reads them: the
    # copy's own tree by a variable, `C:\.\x`)
    return next(
        filter(
            None,
            (
                _climbs_in(line, cwd, own, bool(_INLINE.search(command)))
                for line in dict.fromkeys((command, _expanded(command)))
            ),
        ),
        "",
    )


def _climbs_in(command: str, cwd: str, own: str | None, code: bool) -> str:
    """`_climbs_out` of one reading of a line (`code`: it hands an interpreter code)."""
    mine = _spellings(own) if own is not None else None
    start = posixpath.normpath(cwd.replace("\\", "/"))
    at: str | None = start
    for words in (words for words in _commands_in(command, at=_BLOCKS) if words):
        if _program(words[0]) in _CD:
            went = _cd_to(words, at, mine)
            if _above(went) or went is None and _climbing(words[1:], None, mine):
                return words[-1]
            at = went
        elif piece := _climbing(words, at, mine, code):
            return piece
    for words in _parts(command, _BLOCKS):  # (what a shell's variable is set to)
        if piece := _climbing(
            [word.split("=", 1)[1] for word in words if _ASSIGNMENT.match(word)], start, mine
        ):
            return piece
    return ""


def _names_elsewhere(
    command: str,
    project: str,
    runtime: Path | str,
    own: str | None,
    cwd: str | None,
    worktrees: Iterable[str],
) -> str:
    """The place outside its copy a command run in it names, "" for none: by its full path, a
    copies folder of KOLONİ's (another agent's copy, KOLONİ's records of a copy - `folders`) or a
    worktree of the project, its own folder aside - the copy's own tree (`own`) taken out of the
    line first; or above the tree by `..` (`_climbs_out`). `own` None: the copy is not made yet,
    and every copy is another's."""
    lines = _path_lines(command)
    if own is not None:
        lines = [_spellings(own).sub("", line) for line in lines]
    here = os.path.normcase(os.path.realpath(project))
    for place in [
        *map(str, folders(Path(runtime))),
        *(one for one in worktrees if os.path.normcase(os.path.realpath(one)) != here),
    ]:
        if any(map(_spellings(place).search, lines)):
            return place
    return _climbs_out(command, cwd, own)


def copy_reason(
    command: str,
    linked: bool,
    project: str,
    runtime: Path | str,
    own: Path | str | None = None,
    cwd: str | None = ".",
    worktrees: Iterable[str] = (),
) -> str:
    """`_copy_reason` of a line as the shell reads it (`joined`) and as written: the first reason
    either gives."""
    worktrees = list(worktrees)
    return next(
        filter(
            None,
            (
                _copy_reason(line, linked, project, runtime, own, cwd, worktrees)
                for line in _readings(command)
            ),
        ),
        "",
    )


def _copy_reason(
    command: str,
    linked: bool,
    project: str,
    runtime: Path | str,
    own: Path | str | None,
    cwd: str | None,
    worktrees: Iterable[str],
) -> str:
    """Why a command an agent runs in its working copy is asked at every level, Full auto
    too, and refused in a turn nobody watches; "" where there is none. It names `project`,
    the project's folder (K-kopya-istem) - KOLONİ's own `runtime` in it is not the project's
    (the copy, a skill's script: KOLONİ on its own repository). It names a place outside its
    copy (K-koordinasyon, `_names_elsewhere`: `own`, the copy's tree, None before it is made;
    `cwd`, where in it the command runs, None not known; `worktrees`, the project's). It stops
    programs by their name (`KILLS_BY_NAME`), in any part. Or `linked`: the copy has
    the project's dependency folders linked in, and a delete there - or what empties such a
    folder to make it anew, `_REBUILDERS`, or writes there, `_writes_links` - may go through a
    link into the project's own (K-70-junction), in a shell too (`cmd /c rd /s x`).
    shortcut: by the path as written, either slash, in any case on Windows; a short name
    (`PROJ~1`), a variable KOLONİ has no folder in (`_variable_folder`) or a script that names
    it is not seen - nor a delete in a script, or by a program `_through_links` does not list.
    shortcut: a line PowerShell is handed encoded (`-EncodedCommand`), a name spliced by
    backticks (`ki`ll`), and what code handed to `python -c` / `node -e` does are not read;
    `runs_another` and `runs_inline` ask of those where a night's rules hold."""
    if any(
        _spellings(project).search(_spellings(str(runtime)).sub("", line))
        for line in _path_lines(command)
    ):
        return NAMES_PROJECT.format(root=project)
    own = str(own) if own is not None else None
    if elsewhere := _names_elsewhere(command, project, runtime, own, cwd, worktrees):
        return OUT_OF_COPY.format(path=elsewhere)
    if _stops_by_name(command):
        return KILLS_BY_NAME
    for part in _PARTS.split(command) if linked else ():
        words = [word.strip("'\"") for word in _words(part.strip())]
        if words and _in_a_shell(part):
            # What it hands the shell, word by word: a delete anywhere in it counts.
            words = " ".join(words[1:]).split()
            reasons = (why for at in range(len(words)) if (why := _through_links(words[at:])))
            if why := next(reasons, ""):
                return why
        elif words and (why := _through_links(words)):
            return why
    # (and as `_commands_in` reads a part: past a wrapper, `env X=1 uv sync`)
    parts = [words for words in _commands_in(_expanded(command)) if words] if linked else []
    mine = _spellings(own) if own is not None else None
    if why := next((why for words in parts if (why := _through_links(words, mine))), ""):
        return why
    return WRITES_THROUGH_LINKS if any(_writes_links(words, mine) for words in parts) else ""


SECRET_FILE = "Opens a secret file (keys, passwords): asked at every level."
KOLONI_FILES = (
    "Names .koloni, the folder's KOLONİ rules and settings, which agents do not change: asked "
    "at every level. Scratch belongs under .koloni/tmp/: put it there and run again."
)
# B-339: said where the line climbs out of the scratch (`_CLIMBS`) rather than naming `.koloni`.
CLIMBS_OUT = (
    "Climbs out of .koloni/tmp, the agents' scratch, into .koloni - the folder's KOLONİ rules "
    "and settings, which agents do not change (by `..`, a change of folder other than one "
    "`cd .koloni/tmp/...` at the line's start, or a path built or looked up): asked at every "
    "level. Stay inside .koloni/tmp/ and run again."
)
STANDING_FILE = (
    "Names {name}: such a file tells later turns what they may do, or runs by itself: asked at "
    "every level."
)
# R141: the commit of a machine with no git identity failed; this is what the agent then asks.
GIT_IDENTITY = (
    "Sets this project's git name / e-mail (its .git/config), which its commits are made "
    "with: asked at every level."
)
PATCHES = (
    "Applies a patch, which may write any file - one that tells later turns what they may do "
    "too: asked at every level."
)


def _secret_path(piece: str) -> bool:
    """A path in a command, judged as slice 88 judges a file: in the project by its own name
    (`secret_in_project`), out of it by every part (`is_secret`) - `..` resolved first, so
    `.venv/../.env` is the project's `.env`."""
    return (
        is_secret(piece)
        if _outside(piece)
        else secret_in_project(posixpath.normpath(piece.replace("\\", "/")))
    )


def _outside(piece: str) -> bool:
    """Whether a path in a command leads out of the folder it runs in: from a root, a drive,
    the home folder, or by `..` past it."""
    p = piece.replace("\\", "/")
    return bool(
        p.startswith(("/", "~"))
        or re.match(r"[A-Za-z]:", p)
        or posixpath.normpath(p).startswith("..")
    )


def names_secret(command: str) -> bool:
    """Whether a command names a secret file (`.env`, a key), also as an option's value
    (`--env-file=.env`, `-Path:.env`) or next to a redirection (`cat<.env`). It is asked at
    every level, Full auto too. shortcut: by the names it is given; `type .en?`, a script
    that opens one or a short name (`ENV~1`) is not seen - the secret's values are still
    hidden in its output (`OutputMask`), only when they are named like one.
    R140 (B-348's family): in PowerShell a variable's member (`$_.Key`, `$cfg.Env`) is no
    file's name; in sh `$n.env` is the file `<n's value>.env`, and asked.
    shortcut: which shell runs a line is not known here (a host's, Docker's, a CLI's own), so
    the member passes only on Windows, spelt as PowerShell's are (a capital first: `$n.Env`),
    on a line that names no POSIX shell; pass the executor's shell in if that misjudges one."""
    if names_koloni_key(command) or _HOME_VARIABLE.search(command):
        return True
    members = sys.platform == "win32" and not _POSIX_SHELL.search(command)
    for part in _PARTS.split(command):
        # (both ways of splitting: a word's quoted pieces joined, `".e"nv`, and apart)
        for word in {*_words(part.strip()), *_joined_words(part.strip())}:
            # (split at `:` too: a drive letter's path is left starting with `/`, out of it;
            # and at `,`: PowerShell's list of paths, `gc a,.env`)
            # (each spelling: sh's `.e\\nv` is `.env`, pwsh's is no such name)
            if any(
                _secret_path(piece)
                for spelt in _read_spellings(word)
                for piece in re.split(r"[=:<>,]", spelt)
                if piece and not (members and _MEMBER.fullmatch(piece))
            ):
                return True
    return False


_MEMBER = re.compile(r"\$\w+(?:\.[A-Z]\w*)+")
# 27: a CLI's sign-in folder by the variable it is started with, named anywhere on the line
# (`$CLAUDE_CONFIG_DIR`, `${CODEX_HOME}`, `%COPILOT_HOME%`, `!...!`, `$env:...`, `printenv ...`,
# a script's `os.environ['...']`): `cli-homes`, with its kept sessions' transcripts - asked at
# every level as the folder is (`SECRET_NAMES`). A search for the name is asked too (taken).
# shortcut: a listing of every variable (`env`, `gci env:`) is not seen.
_HOME_VARIABLE = re.compile(r"(?i)(?<![\w-])(?:CLAUDE_CONFIG_DIR|CODEX_HOME|COPILOT_HOME)(?!\w)")
_POSIX_SHELL = re.compile(r"(?i)(?<![\w.-])(?:sh|bash|zsh|wsl)(?:\.exe)?(?![\w.-])")


# B-198: what a search is told to pass by - `rg -g '!.koloni'`, `--glob=!x`, `grep
# --exclude-dir=.koloni`, `find -not -path x`, `! -path x` - is not a path it opens (not
# `--exclude-from x`: that one reads x). Only in a part of the line a searcher, a grep or find
# runs, and none past a bare `--`: to `cp -- --exclude .koloni/x` they are a file's names.
# shortcut: such a word given as another option's value (`grep -e --exclude .koloni/x`) passes too.
_PASSED_BY = re.compile(
    r"""(?i)\s(?:(?:-g|--i?glob)[\s=]+['"]?!|--exclude(?:-dir)?[\s=]+"""
    r"""|(?:-not|!)\s+-i?path\s+)['"]?[^\s'"]+['"]?"""
)


def _passed_by(part: str) -> str:
    words = _words(part.strip())
    searches = words and _program(words[0]) in _SEARCHERS | _GREPS | {"find"} and "--" not in words
    return _PASSED_BY.sub(" ", part) if searches else part


def _path_names(command: str) -> set[str]:
    """Each part of each path in a command, as Windows opens the name (`_name`), but those a
    search is told to pass by (`_passed_by`)."""
    return set(_path_parts(command))


def _path_parts(command: str) -> list[str]:
    """`_path_names` in the order they are written."""
    # Quotes and escapes taken out first: `.ko`loni`, `.ko""loni` and `.k^oloni` are the name
    # to PowerShell and cmd. (Split at `:` too: `-Path:.koloni\x`, `.koloni::$DATA`.)
    kept = " ".join(map(_passed_by, _PARTS.split(command)))
    # K-koloni-klasor: `.koloni/tmp/` is the agents' scratch, no standing name - its `.koloni`
    # is left out, the rest of the path judged as any. Not where the line can climb back out
    # of it or build a path from it (`_climbs`: `cd .koloni/tmp; echo x > ../rules.md`,
    # `Split-Path .koloni/tmp`), nor on a git line (`git add -f .koloni/tmp/x` would commit a
    # profile's cookies): there it is `.koloni`, and asked. shortcut: by that spelling -
    # `.koloni/t*`, `KOLONI~1/tmp` and `.koloni/./tmp` are still `.koloni`, and asked.
    # (`..` split by quotes, a caret or a backtick is `..` to the shell: judged without them.)
    # (Live: `ls .koloni/tmp; git status --short` asked. A git that only reads - `_git_looks`,
    # by its bare name - is no such line; but one run inside the scratch, `_ENTERS`: a
    # repository shaped there could set what git runs, as `reads_here` has it.)
    entered = bool(_ENTERS.match(command))
    scratch = not _climbs(command) and not any(
        _git_sub(words)[0]
        and (entered or re.search(r"[\\/]", words[0]) or not _git_looks(words[1:]))
        for words in _parts(command)
    )
    parts: list[str] = []
    for word in re.split(r"[\s=:<>,;|&()]", re.sub(r"[`^'\"]", "", kept)):
        pieces = [_name(piece) for piece in re.split(r"[\\/]", word)]
        if scratch:
            pieces = [
                piece
                for at, piece in enumerate(pieces)
                if not (piece == ".koloni" and pieces[at + 1 : at + 2] == ["tmp"])
            ]
        parts += pieces
    return parts


# What can climb out of the scratch or reach `.koloni` from it: `..`, a change of folder, a
# path built or resolved, `-C <dir>` (git's, tar's).
_CLIMBS = re.compile(
    r"\.\.|(?<![\w-])(?i:cd|chdir|pushd|popd|sl|set-location|push-location|pop-location"
    r"|split-path|join-path|resolve-path)(?![\w-])|(?<!\S)-C(?!\S)"
)
# One change of folder into the scratch at the line's start, plainly spelt (no quote, variable,
# wildcard, `..` or dot-name), then `;`, `&&` or a newline: run_command's `cwd` there
# (`with_cwd`) and an agent's own `cd .koloni/tmp/work; pytest` - no climb by itself.
_ENTERS = re.compile(
    r"\s*(?:cd|chdir|pushd|sl|set-location|push-location)[ \t]+(?:\./)?\.koloni[/\\]tmp"
    r"(?:[/\\][\w-][\w.-]*)*[/\\]?[ \t]*(?:;|&&|\r?\n)",
    re.IGNORECASE,
)
# ...but from inside it `.koloni` is the folder above, reached with no `..` by a line that
# learns where it is or hands a path on: `$(dirname "$PWD")`, `(gi .).Parent`, `%cd%`, `.?/x`.
# shortcut: by these words, each a word of its own (`test_parent.py`, `--parents` are none), as
# the rest here - code or a script that builds the path, or cmd's `%~dpi`, is not seen (a path
# built from pieces is not from the project's folder either: `names_standing`);
# K-yazma-denetimi ends it.
# (`parents` not after a `-`: pathlib's `.parents[0]`, not `mkdir --parents`.)
_WHERE = re.compile(
    r"\.[?*\[]|(?<!\w)(?i:pwd|oldpwd|cwd|getcwd|dirname|parent|location|gl"
    r"|realpath|abspath|xargs|pardir|getparent|psparentpath|getdirectoryname"
    r"|convert-path|(?<!-)parents)(?!\w)"
)


def _climbs(command: str) -> bool:
    """Whether a line can climb out of the scratch (`_CLIMBS`, read as the shell reads it) -
    its one leading change of folder into the scratch (`_ENTERS`) left out, and what follows
    that held to `_WHERE` too (sh's `p\\wd` is `pwd`: judged without backslashes as well).
    shortcut: where it enters is not resolved (no root is known here) - a link in the scratch
    is entered as it is written through (`echo x > .koloni/tmp/link/x`); making one is asked."""
    entered = _ENTERS.match(command)
    if not entered:
        return bool(_CLIMBS.search(_as_read(command)))
    rest = command[entered.end() :]
    read = _as_read(rest)
    # (nothing after it: a shell that keeps its folder would run the next line there)
    return not rest.strip() or any(
        found.search(text) for found in (_CLIMBS, _WHERE) for text in (read, read.replace("\\", ""))
    )


def _as_read(command: str) -> str:
    """A line as the shell reads its names: quotes (PowerShell's smart ones too), carets,
    backticks and a backslash before a dot taken out (`.'.'`, `.‘.’`, `.^.`, `` .`. `` and sh's
    `.\\.` are `..`)."""
    return re.sub(r"[`^'\"‘-„]|\\(?=\.)", "", command)


def with_cwd(command: str, cwd: object) -> str:
    """A command as it is judged with the folder it is run in (run_command's `cwd`): `cd
    <cwd>; <command>` - so that `cwd=.koloni/tmp` with `echo x > ../settings.json`, or
    `cwd=.claude`, names what it reaches (a `cwd` in the scratch alone is no climb: `_ENTERS`).
    What runs is the command alone. `cwd` None: where it runs is not known - a CLI that names
    none and may keep its shell's folder (Qoder; Copilot's other commands - it sends none; Codex
    or agy without one), so its `cd .koloni/tmp; ls` would leave the next line, `echo x >
    ../rules.md`, in the scratch and judged at the root: such a line is judged as one more
    change of folder, a card as it was. "." is the root, known: KOLONİ's own run_command, a
    CLI's report, Claude Code's Bash tool, whose every call starts there
    (`ClaudeNativeClient.cwd_from`, measured), and a Copilot command read to start in a new
    shell (`model_native._ShellPatches`). Whose word a CLI's cwd is: `cwd_from`.
    shortcut: Codex is trusted to name the folder its shell stands in for each command;
    measure it if it is seen to keep a `cd` unnamed."""
    if cwd is None and _ENTERS.match(command):
        return f"cd .; {command}"
    return f"cd {cwd}; {command}" if isinstance(cwd, str) and cwd not in ("", ".") else command


# B-304: the files that hold the key to a run's tool server (its bridge's, agy's door), and a
# CLI run's own temp folder (`tempfile.mkdtemp(prefix="koloni-cli-")`).
KEY_FILES = frozenset({"bridge.json", "koloni-door.json"})
_RUN_FOLDER = re.compile(r"koloni-cli-[a-z0-9_]+")


def _where_keys_are(part: str) -> bool:
    """A part of a path that places a KEY_FILES name there: the temp folder, a run's, agy's."""
    return (
        part.strip("%") in ("temp", "tmp")
        or part.startswith("agy-")
        or bool(_RUN_FOLDER.fullmatch(part))
    )


# (`KOLONI_*` names KOLONİ's variables, no file of its: `koloni-cli-<id>`, `koloni.db`)
_KEY_WILDCARD = re.compile(r"koloni(?!_)")


def names_koloni_key(command: str) -> bool:
    """Whether a command names where a run's tool-server key is: a CLI run's temp folder
    ("koloni-cli-<id>"), a wildcard with `koloni` in it (`*koloni*`, `koloni-cli*`: B-304's
    Lead listed the temp folder so), or `koloni-cli` or a file of KEY_FILES beside the temp
    folder, a run's or agy's (a project's own docs/bridge.json is not; `rg koloni-cli app/`
    is a search). With that key another agent would call KOLONİ's tools as that run's agent:
    asked at every level, as a secret file is. Not a run's plugin of skills
    (`koloni-cli-<id>/plugin/skills/`, Claude Code's: a skill's script runs from there; it
    holds no key) with no `..` or wildcard to climb out by - any run's, not only its own.
    shortcut: a speed bump, by the names written: a search of the temp folder that names
    none of them, a variable, a short name (`KOLONI~1`) or a `cd` out of the plugin is not
    seen. What holds is the tool server: its key serves one bridge, and its file is gone
    once that bridge is in (`ToolServer`).
    B-348: a wildcard where `koloni` is followed by `_` (`gci env: | ? Name -like 'KOLONI_*'`,
    KOLONİ's variables, which no command is given: `command_env`) is no card. The one it is
    given, the planted KOLONI_CANARY_KEY, is so named on purpose: such a listing shows it
    masked, and a command that sends it out is refused (`sends_canary`).
    shortcut: `env:KOLONI*` or `'*KOLONI*'` on that line is still asked; let the `env:` drive's
    wildcards pass if the user meets one."""
    parts = [part for part in _path_parts(command) if part]
    placed = any(map(_where_keys_are, parts))
    for at, part in enumerate(parts):
        if _GLOB.search(part) and _KEY_WILDCARD.search(part):
            return True
        if _RUN_FOLDER.fullmatch(part):
            if (
                parts[at + 1 : at + 3] != ["plugin", "skills"]
                or ".." in command
                or _GLOB.search(command)
            ):
                return True
        elif (part == "koloni-cli" or part in KEY_FILES) and placed:
            return True
    return False


def names_koloni(command: str) -> bool:
    """Whether a command names the folder's `.koloni` (slice 86c) - as any part of a path, in
    any case, as Windows opens the name - but not its scratch, `.koloni/tmp/` (K-koloni-klasor,
    `_path_parts`). It is asked at every level, Full auto too.
    shortcut: by the name it is given; a wildcard (`.kolon?`, `.koloni*`, `[.]koloni`), a brace
    expansion, the short name (`KOLONI~1`) or a script that writes it is not seen."""
    return ".koloni" in _path_names(command)


def names_standing(command: str) -> str:
    """The name of `NOT_WRITTEN_UNATTENDED` a command names (`.claude`, `.github`, AGENTS.md,
    `.koloni`...) and does more than read (`only_reads`: `cat AGENTS.md`, `git log -- .github`
    run as any read does), as `names_koloni` finds `.koloni` - also by a wildcard or a short
    name (`_standing_of`); "" for none (B-79). Such a command is asked at every level, Full
    auto too (`CommandRunner`), and refused in a turn nobody watches (its `danger` keeps any
    rule from covering it: `is_exactly`): a write to one tells later turns what they may do,
    or runs by itself. One that writes one without naming it: `git config` setting a value
    (`.git/config`: `core.fsmonitor` runs at the next `git status`), and a patch applied
    (`git apply`, `git am`, `patch`: PATCH), which may write any file.
    shortcut: by the names written in it. Code that builds the name (`python -c
    "open('.cla'+'ude/x','w')"`), an encoded command (`powershell -enc`), a variable, a
    helper script or another program that writes one unnamed (`claude mcp add --scope
    project`) is not seen. The real answer is K-yazma-denetimi: commands held by what they
    write, not by what they name.
    B-188 (live): each command of a chain is judged apart - `python train.py; cat
    .github/x.yml` reads it, as the `cat` alone does - but a pipeline whole, as what is read
    is handed on (`ls .github | xargs cp x`); and in an interpreter's inline code
    (`python -c "..."`, `node -e`) a name counts as written, a `*` or `?` there being code
    (`import *`, `a * b`), not a wildcard. shortcut: inline code that globs a name
    (`glob('.cla*')`) is not seen - as code that builds one is not. A chain split inside
    quotes, brackets or a substitution (`cp x "$(ls -d .github; :)/y"`) is judged whole.
    B-307 (live): a script handed to a shell (`_script`: Codex's `powershell.exe -Command
    "Get-Location; rg --files -g AGENTS.md"`) reads what it names when every part of it reads
    (`only_reads`) or only searches; one with any other part is judged whole, as before.
    shortcut: a part in brackets (`if (Test-Path AGENTS.md) { gc AGENTS.md }`, Codex's live) is no
    read, so a name in it asks; tell such a block apart if it is met often. (A .NET call of
    another file - `[IO.File]::ReadAllBytes(...)` - asks nothing: it names no such file.)
    B-316 (live): a read piped on into what only shapes its text (`_reads`: `Get-Content
    AGENTS.md | Select-Object -First 150`) reads too, in both."""
    script = _script(command)
    sinks = not _RENAMES.search(command)
    parts = [part for part in _CHAIN.split(script or "") if part.strip()]
    if parts and not _harm(command) and all(_reads(part, sinks) for part in parts):
        return ""
    code = [found[1] for found in _INLINE_CODE.finditer(command)]
    named = {
        key
        for piece in _path_names(" ".join(code))
        if (key := _standing_of(piece, wildcards=False))
    }
    rest = _INLINE_CODE.sub(lambda found: found[0][: found.start(1) - found.start()], command)
    parts = _CHAIN.split(rest)
    # (A line that enters the scratch is judged whole: its `cd` alone would name `.koloni` -
    # and with its inline code, which may learn where it is: `_WHERE`.)
    entered = _ENTERS.match(rest)
    if "$(" in rest or entered or not all(map(_balanced, parts)):
        parts = [rest]
    named |= {".koloni"} if entered and names_koloni(command) else set()
    named |= {
        key
        for part in parts
        if not _reads(part, sinks)
        for piece in _path_names(part)
        if (key := _standing_of(piece))
    }
    named |= {".git"} if _sets_git_config(command) else set()
    named |= {PATCH} if applies_patch(command) else set()
    return min(named) if named else ""


# A chain's commands, a pipeline one of them: `_PARTS` less a single `|`.
_CHAIN = re.compile(r"&&|\|\||[;&\r\n]")
# B-316: what a pipe may hand a read's text to that only picks, sorts, counts or lays it out,
# writing nothing (not `sort`: sort.exe's `/o` and `sort -o` write a file).
_SINKS = frozenset(
    {
        "select-object",
        "select",
        "select-string",
        "sls",
        "sort-object",
        "measure-object",
        "out-string",
        "ft",
        "fl",
        "fw",
    }
)


def _sink(stage: str) -> bool:
    """A stage of a pipeline that only shapes the text it is handed: one of `_SINKS` or a
    Format-*, handed no block, hashtable, bracket, variable, redirection or escape (`{`, `@{`,
    `(`, `$`, `>`, a backtick): with those it could run or write anything."""
    words = _words(stage.strip())
    program = _program(words[0]) if words else ""
    return not re.search(r"[{}()$<>`]", stage) and (
        program in _SINKS or program.startswith("format-")
    )


def _reads(part: str, sinks: bool = True) -> bool:
    """A command of a chain that reads what it names (`names_standing`): it only reads, only
    searches, or is a read piped on only into sinks (`_sink`) - not where the line may give a
    sink's name to another program (`sinks` False: `_RENAMES`). shortcut: a `|` inside quotes
    (`sls -Pattern "a|b"`) splits the pipeline there, so such a one asks; split outside quotes
    if that is met with a standing name."""
    first, *stages = part.split("|")
    return (
        only_reads(part.strip())
        or only_searches(part)
        or sinks
        and bool(stages)
        and (only_reads(first.strip()) and all(map(_sink, stages)))
    )


# What gives a command's name to something else in the line: an alias, a function or a filter.
# (`alias`: bash's, K-r147.)
_RENAMES = re.compile(
    r"(?i)(?<![\w-])(?:set-alias|new-alias|sal|nal|function|filter|alias)(?![\w-])"
)
# What a search may be told that writes or runs something: find's actions, rg's preprocessor and
# its replace (`-r` is rg's and ag's replace, grep's recursion).
_SEARCH_DOES = re.compile(
    r"(?i)-exec|-execdir|-ok|-okdir|-delete|-fprint0?|-fprintf|-fls"
    r"|--pre(?:=.*)?|--replace(?:=.*)?"
)


def only_searches(part: str) -> bool:
    """B-198: a lone search that only reads - rg, ag, ack, a grep or find by its own name,
    nothing piped, redirected, substituted or wrapped (a shell's script: `_script`, B-307),
    none of `_SEARCH_DOES`. A file that
    steers later turns it names (`rg --files -g AGENTS.md`, `rg foo .github/`) it reads, as a
    `cat` does: `names_standing` asks nothing of it. (`.koloni` and a secret still ask: `_harm`.)"""
    words = [word.strip("'\"") for word in _words(part.strip())]
    if not words or re.search(r"[|<>`$(){}]", part) or re.search(r"[\\/]", words[0]):
        return False
    program = _program(words[0])
    return program in _SEARCHERS | _GREPS | {"find"} and not any(
        _SEARCH_DOES.fullmatch(word) or program in ("rg", "ripgrep", "ag") and word == "-r"
        for word in words
    )


# B-307: a shell handed a script to run - `powershell[.exe]` or `pwsh` (by its name, or its path
# from a drive) with only flags that take no value, then `-Command` or `-c`; `cmd /c` - and the
# script: the rest. Not one handed a file, an encoded command or another flag (`-File`,
# `-EncodedCommand`), nor one of the folder's own (`.\powershell.exe`, which an agent can write).
# shortcut: a path from a drive into the project is taken as the shell, as `POWERSHELL_LINE` does.
_SHELL_SCRIPT = re.compile(
    r"""(?is)\s*("[^"]*"|\S+)\s+(?:(?:-NoProfile|-NonInteractive|-NoLogo|/[dsq])\s+)*"""
    r"""(?:-Command|-c|/c)\s+(.*?)\s*"""
)


def _script(command: str) -> str | None:
    """The script a shell is handed (`_SHELL_SCRIPT`), out of the quotes around all of it
    (`""` and `\\"` in them a quote); None where it is no such line."""
    found = _SHELL_SCRIPT.fullmatch(command)
    shell = found[1].strip("'\"") if found else ""
    if (
        not found
        or _program(shell) not in ("powershell", "pwsh", "cmd")
        or re.search(r"[\\/]", shell)
        and not re.match(r"[A-Za-z]:", shell)
    ):
        return None
    script = found[2]
    if len(script) > 1 and script[0] == script[-1] and script[0] in "'\"":
        quote = script[0]
        script = script[1:-1].replace(quote * 2, quote)
        script = script.replace('\\"', '"') if quote == '"' else script
    return script


def _balanced(part: str) -> bool:
    """Whether a part of a chain closes what it opens: its quotes, backticks and brackets."""
    return all(part.count(mark) % 2 == 0 for mark in "\"'`") and all(
        part.count(a) == part.count(b) for a, b in ("()", "{}", "[]")
    )


# The code an interpreter is handed inline, quoted: `python -c "..."`, `node -e '...'` - the
# interpreter a word of its own, by its path too (not `deploy.py -c`).
_INLINE_CODE = re.compile(
    r"""(?i)(?:^|(?<=[\s;&|(]))(?:\S*[\\/])?(?:python|py|node)[\d.]*w?(?:\.exe)?\s+"""
    r"""(?:-\w+\s+)*?(?:-c|-e|-p|--eval|--print)\s+("[^"]*"|'[^']*')"""
)


# A short name (8.3) Windows gives a long one: `CLAUDE~1`, `GITHUB~1`, `CLAUDE~1.JSO`.
_SHORT = re.compile(r"([^~.]{1,6})~\d+(\.[^.]*)?")


def _standing_of(piece: str, wildcards: bool = True) -> str | None:
    """The name of `NOT_WRITTEN_UNATTENDED` a piece of a path is (as `_name` gives it), or
    may be: one a wildcard in it matches (`.cla?de`, `.claud[e]`, `.claude*`) - not in code,
    `wildcards` False -, or one whose short name it is (`claude~1`). shortcut: a wildcard
    counts where it starts with at least three plain characters (`*.json` names none: it
    would card most commands); one that starts with one (`?laude`) is not seen."""
    if piece in NOT_WRITTEN_UNATTENDED:
        return piece
    if (
        wildcards
        and re.search(r"[?*\[]", piece)
        and len(re.split(r"[?*\[]", piece, maxsplit=1)[0]) >= 3
    ):
        return next(
            (key for key in sorted(NOT_WRITTEN_UNATTENDED) if fnmatch.fnmatchcase(key, piece)), None
        )
    if short := _SHORT.fullmatch(piece):
        # (Its first six letters before the extension, the leading dot dropped: `.mcp.json`
        # is MCP~1.JSO.)
        return next(
            (
                key
                for key in sorted(NOT_WRITTEN_UNATTENDED)
                if key.lstrip(".").rsplit(".", 1)[0][:6] == short[1]
            ),
            None,
        )
    return None


def _git_sub(words: list[str]) -> tuple[str | None, list[str]]:
    """The git command a line runs (`git -C x config a b`: "config") and its words after it;
    None for a line that is not git's."""
    if not words or _program(words[0]) != "git":
        return None, []
    at = 1
    while at < len(words) and words[at].startswith("-"):
        at += 2 if words[at] in ("-C", "-c", "--git-dir", "--work-tree") else 1
    return (words[at], words[at + 1 :]) if at < len(words) else (None, [])


def _parts(command: str, at: re.Pattern = _PARTS) -> list[list[str]]:
    """A line's parts, split `at`, each past what leads into it (`_led`) - and what its groups
    hold, split so too (`_groups`: `(cd web && npm ci)`, `{ npm ci; }`, `if ($true) { npm ci }`);
    a group that does not pair, or past MAX_OTHER_READINGS of them, is [UNREAD]: what runs
    there is not read (an "always" harm, `_danger_of`)."""
    # (cmd's `for /f %a in ('del x') do y` runs its set's command too: a part of its own - in
    # any split, as `_BLOCKS` cuts at its brackets - as `_led` reads past the loop to `y`)
    sets = re.findall(r"(?i)(?:^|[\s;&|(@])for\s[^;&|]*?\bin\s*\(\s*(['`\"])(.*?)\1\s*\)", command)
    groups, paired = _groups(command)
    # (and what a `$( ... )` runs, in double quotes too: `out=$(npm ci)` - k-okuyucu-2; `_BLOCKS`
    # cuts at its brackets already; past MAX_OTHER_READINGS of them, not read: `_too_deep`)
    deep = _too_deep(command)
    subs = _substituted(_unliteral(command)) if at is _PARTS and not deep else []
    return [
        *([word.strip("'\"") for word in _words(inner)] for _quote, inner in sets),
        *(
            [word.strip("'\"") for word in _led(_words(part.strip()))]
            for text in (command, *groups, *subs)
            for part in at.split(text)
        ),
        *([] if paired and not deep else [[UNREAD]]),
    ]


def _groups(command: str, quotes: bool = True) -> tuple[list[str], bool]:
    """What a line's brackets hold, outside its quotes - `( ... )`, `{ ... }`, `@( ... )`, a
    script block, cmd's `if x ( ... ) else ( ... )` - but a `$( ... )` / `${...}`, read as a
    substitution (`_substituted`, `_BLOCKS`); and whether they pair, within MAX_OTHER_READINGS
    of them (k-okuyucu). Quotes that do not pair are no quotes."""
    found: list[str] = []
    opened: list[tuple[str, int]] = []
    quote = ""
    # (a data heredoc's body, a comment and a case pattern pair no bracket)
    command = _uncommented(
        _uncased(_blanked(command, ((start, end) for start, end, _quoted in _data_bodies(command))))
    )
    for mark in re.finditer(r"""[(){}'"]""" if quotes else r"[(){}]", command):
        char, at = mark[0], mark.start()
        if quote:
            quote = "" if char == quote else quote
        elif char in "'\"":
            quote = char
        elif char in "({":
            opened.append((char, at))
        elif not opened or opened[-1][0] != ("(" if char == ")" else "{"):
            return found, False
        else:
            start = opened.pop()[1]
            if command[start - 1 : start] == "$":
                continue
            if len(found) >= MAX_OTHER_READINGS:
                return found, False
            found.append(command[start + 1 : at])
    return _groups(command, quotes=False) if quote else (found, not opened)


# A comment as each shell reads it (k-okuyucu-2): sh's and PowerShell's `#` at a word's start
# outside quotes (not `${#x}`, `$#`), PowerShell's `<# ... #>`, cmd's `rem` / `::` at a command's
# start - what precedes it is read; its brackets pair nothing (`echo done # 1) first`).
_COMMENT = re.compile(
    r"""'[^']*'|"[^"]*"|<#.*?#>|(?:^|(?<=[\s;&|(]))#[^\n]*"""
    r"""|(?:^|(?<=[\n&|(]))[ \t]*(?:(?i:rem)(?=\s|$)|::)[^\n]*""",
    re.S,
)


def _uncommented(command: str) -> str:
    return _COMMENT.sub(lambda found: found[0] if found[0][:1] in "'\"" else " ", command)


# What leads into a part's command without being it (review round 4), for every rule: sh's `!`,
# `if`, `elif`, `while`, `until`, `then`, `else`, `do`, `coproc` (`time` is a wrapper's, with its
# options: `_unwrapped`); cmd's `@`, `for ... do` and its `if [/i] [not] exist x | defined x |
# errorlevel n | a op b`; PowerShell's `$x =`; trap's line, which it runs as eval runs one.
_LEADS = frozenset({"!", "if", "elif", "while", "until", "then", "else", "do", "coproc"})
_CMD_TESTS = frozenset({"exist", "defined", "errorlevel", "cmdextversion"})
_CMD_COMPARES = frozenset({"==", "equ", "neq", "lss", "leq", "gtr", "geq"})


def _led(words: list[str]) -> list[str]:
    """A part's command past what leads into it (`_LEADS`): `if pkill -f x` is pkill's, `if not
    exist x.pid taskkill /IM python.exe` taskkill's, `$p = Get-Process x` Get-Process's - but
    `$g = 'git'` sets a word, runs nothing (its quotes are read: `_parts` hands the words as
    written). cmd's quoted comparison too, however its quotes split it (`if "%a%"=="x" npm ci`),
    and trap's `--`; what a group holds is `_groups`'."""
    while words:
        first = words[0].casefold()
        if first in _LEADS:
            words = words[1:]
            while first == "if" and words and words[0].casefold() in ("/i", "not"):
                words = words[1:]
            if first == "if" and words:  # (cmd's test or comparison before its command -
                # `"%a%"=="x"` splits at its quotes into `"%a%"` and `=="x"`)
                words = (
                    words[2:]
                    if words[0].casefold() in _CMD_TESTS
                    else words[3:]
                    if len(words) > 2 and words[1].casefold() in _CMD_COMPARES
                    else words[2:]
                    if len(words) > 1 and words[1].startswith("==")
                    else words[1:]
                    if "==" in words[0]
                    else words
                )
        elif first == "for" and "do" in (low := [word.casefold() for word in words]):
            words = words[low.index("do") + 1 :]
        elif first == "case" and "in" in words[2:3]:  # (its patterns out: `_uncased`)
            words = words[3:]
        elif first == "trap" and len(words) > 1 and len(words) > 1 + (words[1] == "--"):
            return ["eval", words[1 + (words[1] == "--")]]  # (`trap -- 'x' EXIT`)
        elif first.startswith("@") and len(first) > 1:
            words = [words[0][1:], *words[1:]]
        elif (
            len(words) > 2
            and re.fullmatch(r"\$[\w:]+", words[0])
            and words[1] == "="
            and (not words[2].startswith(("'", '"')))
        ):
            words = words[2:]
        elif glued := re.fullmatch(r"\$[\w:]+=([^'\"].*)", words[0]):
            words = [glued[1], *words[1:]]
        else:
            break
    return words


def _sets_git_config(command: str) -> bool:
    """Whether a part of a command is `git config` setting or taking off a value - not one
    that only reads (`--get…`, `--list`, `-l`, a key alone)."""
    for words in _parts(command):
        sub, rest = _git_sub(words)
        if sub != "config" or rest[:1] in (["get"], ["list"]):  # (git 2.46's words for a read)
            continue
        if not any(w.startswith(("--get", "--list", "-l")) for w in rest) and (
            len([w for w in rest if not w.startswith("-")]) > 1
            or any(
                w.startswith(
                    ("--unset", "--add", "--replace", "--rename", "--remove", "--edit", "-e")
                )
                for w in rest
            )
        ):
            return True
    return False


# git's own commands that rewrite `.git/config` in their ordinary work: a remote, a branch's
# upstream, a submodule, a new repository (K-yazma-denetimi lets that stand, `writes_git_config`).
_CONFIG_WRITERS = frozenset({"init", "remote", "submodule", "branch", "checkout", "switch"})


def _git_alone(command: str) -> list[tuple[str | None, list[str]]]:
    """Each part's git command and its words, where a command is git's own alone - every
    part of it; [] where it is not: a part that is no git command, a substitution in it
    (another program inside) or a redirection, or git told something before its command
    (`-c core.hooksPath=` runs a hook of anywhere)."""
    parts = [words for words in _parts(command) if words]
    if (
        not parts
        or re.search(r"\$\(|`|[<>]", command)
        or any(_git_sub(words)[0] is None or words[1].startswith("-") for words in parts)
    ):
        return []
    return [_git_sub(words) for words in parts]


def writes_git_config(command: str) -> bool:
    """Whether a command is git's own alone (`_git_alone`) and one of its parts rewrites
    `.git/config` as it works (`git init`, `git remote add`, `git push -u`, `git checkout
    --track`, `git config` not `--global`) - in every reading (`_readings`, k-okuyucu): what
    it lets stand is the least any reading lets (`git init # `⏎`rm .git/config` is not git's
    own alone as written)."""
    return all(map(_writes_git_config, _readings(command)))


def _writes_git_config(command: str) -> bool:
    return any(
        sub in _CONFIG_WRITERS
        or sub == "push"
        and bool({"-u", "--set-upstream"} & set(rest))
        or sub == "config"
        and not {"--global", "--system"} & set(rest)
        for sub, rest in _git_alone(command)
    )


PATCH = "a patch"
_ONLY_LOOKS = ("--check", "--stat", "--numstat", "--summary", "--dry-run", "--show-current-patch")


def applies_patch(command: str) -> bool:
    """Whether a part of a command applies a patch (`git apply`, `git am`, `patch`): it writes
    whatever files the patch names - `.github/workflows` too - without the line naming them.
    Not one that only looks at it (`--check`, `--stat`, `--dry-run`). In any reading
    (`_readings`, k-okuyucu)."""
    return any(map(_applies_patch, _readings(command)))


def _applies_patch(command: str) -> bool:
    for words in _commands_in(command):  # (behind a wrapper too: `bash -c 'git apply x'`)
        sub, rest = _git_sub(words)
        applies = sub in ("apply", "am") or bool(words) and _program(words[0]) == "patch"
        if applies and not any(w.startswith(_ONLY_LOOKS) for w in (rest or words[1:])):
            return True
    return False


# A line's continuations: PowerShell's backtick right at a line's end, sh's backslash. A backtick
# with a space after it does not continue (measured, pwsh 7: `Write-Output one ` ⏎ two` runs `two`).
# cmd's `^` at a line's end continues it too (k-okuyucu-2).
# shortcut: a lone CR, U+2028 / U+0085 are not joined (each part is read as written); join them
# if an agent is seen to write one (review round 4).
_CONTINUED = re.compile(r"`\r?\n|\\\r?\n|\^\r?\n")


def joined(line: str) -> str:
    """A command line with its continued lines joined as the shell reads it: PowerShell's backtick
    at a line's very end as a space between words, sh's backslash and cmd's `^` as nothing
    (`gi\\⏎t` is `git`). KOLONİ judges a line both so and as written (`_readings`): reading it
    joined may only add. Joined alone it misses what a line's end that continues nothing hands
    on (`rm x # done `⏎`npm publish`): a caller judges each of `readings(line)`, not this
    alone."""
    return _CONTINUED.sub(lambda found: " " if found[0][0] == "`" else "", line)


def readings(line: str) -> list[str]:
    """Every way KOLONİ reads a command line (`_readings`): joined, as written and what its
    backtick pairs hold - a caller outside this module judges each (review round 4)."""
    return _readings(line)


def _readings(line: str) -> list[str]:
    """A line as written - always one of them: every other reading may only add (k-okuyucu-2) -
    and as the shell reads it (`joined`): a backtick or a backslash at a line's end continues
    nothing in a comment (`rm x # done `⏎`npm publish`), glued to a word in `pwsh -Command`
    (`build`⏎`git push`), after a Windows path (`C:\\`⏎) or in bash, where a backtick opens what
    it runs (`echo `⏎`rm -rf build`⏎``) (review round 4). And what its backticks hold, each a line
    of its own: bash runs it, in double quotes too, so a message holding a backtick pair is no
    message (`git commit -m "`kill -9 $(pgrep x)`"`); its `case` branches past their patterns
    (`_uncased`); what follows a PowerShell block comment (`<# c #> Stop-Process ...`); what a
    launcher hands on (`_handed`).
    shortcut: pairs taken in order - nested substitutions (`` `a \\`b\\`` ``) and PowerShell's own
    escapes (`` `t ``) read as pairs are not parsed as bash does; do so in 0.1.6."""
    insides = re.findall(r"`([^`]*)`", line)
    return list(
        dict.fromkeys(
            (
                line,
                joined(line),
                _uncased(line),
                re.sub(r"(?s)<#.*?#>", " ", line),
                *(["\n".join(insides)] if insides else []),
                *_handed(line),
            )
        )
    )


# Lines a command hands on that its parts do not split out (k-okuyucu-2): Start-Process's
# argument list (`Start-Process powershell -ArgumentList '-Command','taskkill ...'`, any program,
# its path quoted with a space, `@(...)`, named after its arguments), a package runner's `-c` /
# `--call` (`npx -c 'taskkill ...'`), `[scriptblock]::Create('...')`.
_START_PROCESS = re.compile(
    r"""(?i)(?:^|(?<=[\s;&|(]))(?:start-process|saps|start)(?=\s)"""
    r"""((?:'[^']*'|"[^"]*"|[^\n|;'"])*)"""
)
_RUNNER_CALL = re.compile(
    r"(?i)\b(?:npx|npm\s+(?:exec|x)|pnpm\s+(?:dlx|exec)|yarn\s+(?:dlx|exec))"
    r"\b[^;&|\n]*?\s(?:-c|--call)(?:=|\s+)(['\"])(.*?)\1"
)
_SCRIPTBLOCK = re.compile(
    r"(?i)\[(?:system\.management\.automation\.)?scriptblock\]::create\("
    r"\s*(['\"])(.*?)\1\s*\)"
)
# Start-Process's own parameters, by any prefix PowerShell takes: those with a value, its
# switches; its argument list and its program.
_SP_VALUES = (
    "-windowstyle",
    "-workingdirectory",
    "-verb",
    "-credential",
    "-environment",
    "-redirectstandardoutput",
    "-redirectstandarderror",
    "-redirectstandardinput",
)
_SP_SWITCHES = (
    "-wait",
    "-nonewwindow",
    "-passthru",
    "-usenewenvironment",
    "-loaduserprofile",
    "-whatif",
    "-confirm",
)
_SP_TOKENS = re.compile(r"""'[^']*'|"[^"]*"|,|@\(|[()]|[^\s,'"()]+""")
# What reads the line it is handed as code or commands: a variable in its place is not read.
_RUNS_LINES = re.compile(
    rf"(?i){_INTERPRETERS}|(?:powershell|pwsh|cmd|bash|sh|zsh|wsl|dash)"
    r"(?:\.exe)?"
)


def _sp_param(word: str, names: Iterable[str]) -> bool:
    name = word.casefold().partition(":")[0]
    return len(name) > 2 and any(full.startswith(name) for full in names)


def _started_line(rest: str) -> str:
    """What `Start-Process ...` runs, as a line (`_handed`): its program - `-FilePath`'s, else
    its first word - and its argument list; UNREAD where it hands a shell or an interpreter a
    variable (`-ArgumentList $a`)."""
    tokens, program, items, at, listing = _SP_TOKENS.findall(rest), None, [], 0, False
    while at < len(tokens):
        token = tokens[at]
        at += 1
        if token in (",", "@(", "(", ")"):
            continue
        if token.startswith("-") and _sp_param(token, ("-filepath", "-pspath", "-path")):
            program = (
                tokens[at] if at < len(tokens) and ":" not in token else token.partition(":")[2]
            )
            at, listing = at + (0 if ":" in token else 1), False
        elif token.startswith("-") and _sp_param(token, _SP_VALUES):
            at, listing = at + (0 if ":" in token else 1), False
        elif token.startswith("-") and _sp_param(token, _SP_SWITCHES):
            listing = False
        elif token.startswith("-") and _sp_param(token, ("-argumentlist", "-args")):
            listing = True
        elif program is None and not listing:
            program = token if token.strip("'\"") else None  # (cmd's `start "" x`: a title)
        else:
            items.append(token.strip("'\""))
            # (the list goes on past a comma only: `-ArgumentList '/c x' cmd` names cmd after it)
            listing = listing and at < len(tokens) and tokens[at] == ","
    program = (program or "").strip("'\"")
    if any(item.startswith("$") for item in items) and _RUNS_LINES.fullmatch(_program(program)):
        return UNREAD
    return " ".join(
        [
            f'"{program}"' if " " in program else program,
            *(
                items
                if len(items) < 2
                else (
                    f"'{item}'" if '"' in item else f'"{item}"' if re.search(r"\s", item) else item
                    for item in items
                )
            ),
        ]
    )


def _handed(line: str) -> list[str]:
    """The lines a line hands on as `_START_PROCESS`, `_RUNNER_CALL` and `_SCRIPTBLOCK` find them,
    each as the program handed it reads it (`powershell -Command "taskkill ..."`)."""
    found = [inner for _quote, inner in _RUNNER_CALL.findall(line)]
    found += [inner for _quote, inner in _SCRIPTBLOCK.findall(line)]
    return found + [_started_line(rest) for rest in _START_PROCESS.findall(line)]


# A heredoc's body (`<<EOF`, `<<-'EOF'`, `<<"EOF"`, `<<\EOF`, `<<'E'OF`) is data to what only reads
# it - a file it writes, a message, a count (k-okuyucu-2): its brackets pair nothing (`1) first`),
# and where its delimiter is quoted its `$(...)` runs nothing either. Handed to anything else
# (`bash <<EOF`, `python - <<'EOF'`, `make -f -`, a pipe or a chain on its line) it is code.
_HEREDOC = re.compile(r"(?<!<)<<(-?)[ \t]*((?:'[^'\n]*'|\"[^\"\n]*\"|\\?[\w.@%+-])+)")
_DATA_READERS = frozenset(
    {
        "cat",
        "tee",
        "git",
        "gh",
        "wc",
        "sort",
        "uniq",
        "head",
        "tail",
        "grep",
        "egrep",
        "fgrep",
        "rg",
        "jq",
        "yq",
        "base64",
        "diff",
        "cmp",
        "less",
        "more",
        "nl",
        "tr",
        "cut",
        "column",
        "fold",
        "iconv",
        "xxd",
        "od",
        "md5sum",
        "sha256sum",
        "shasum",
        "curl",
        "echo",
        "printf",
    }
)


def _data_bodies(line: str) -> list[tuple[int, int, bool]]:
    """Where each heredoc body handed to a data reader (`_DATA_READERS`, alone on its line: no
    pipe, no chain) starts and ends in a line, and whether its delimiter is quoted. Two on one
    line follow each other; one with no closing line runs to the line's end."""
    bodies: list[tuple[int, int, bool]] = []
    after: dict[int, int] = {}  # (a head line's next body: `cat <<A <<B`)
    for found in _HEREDOC.finditer(line):
        head_start = line.rfind("\n", 0, found.start()) + 1
        head_end = line.find("\n", found.end())
        if head_end < 0:
            break
        word = found[2]
        delimiter = re.sub(r"['\"\\]", "", word)
        start = after.get(head_start, head_end + 1)
        tabs = r"\t*" if found[1] else ""
        close = re.compile(rf"^{tabs}{re.escape(delimiter)}\r?$", re.M).search(line, start)
        end = close.start() if close else len(line)
        after[head_start] = close.end() + 1 if close else len(line)
        head = line[head_start:head_end]
        words = _words(head.strip())
        if (
            words
            and _program(words[0]) in _DATA_READERS
            and not re.search(r"[|;&]", re.sub(r"\d?>&\d|&>", "", head))
        ):
            bodies.append((start, end, word != delimiter))
    return bodies


def _blanked(line: str, spans: Iterable[tuple[int, int]]) -> str:
    """A line with these spans' characters but its line ends made spaces: what they hold is read
    as nothing, and every other place stays where it was."""
    chars = list(line)
    for start, end in spans:
        for at in range(start, end):
            chars[at] = chars[at] if chars[at] in "\r\n" else " "
    return "".join(chars)


def _unliteral(line: str) -> str:
    """A line with what no shell runs a `$( ... )` in made blank (`_substituted` reads the rest):
    a single-quoted string, an escaped `\\$(`, a PowerShell literal here-string (`@'...'@`), a
    quoted delimiter's heredoc body handed to a data reader (k-okuyucu-2).
    shortcut: a single-quoted word inside an unquoted heredoc's body is blanked too, though the
    shell expands what it holds there; read it so if an agent is seen to write one."""
    line = _blanked(line, ((start, end) for start, end, quoted in _data_bodies(line) if quoted))
    line = re.sub(
        r"""(?s)@'.*?'@|"(?:[^"\\`]|[\\`].)*"|'[^']*'""",
        lambda found: found[0] if found[0][:1] == '"' else " " * len(found[0]),
        line,
    )
    return line.replace("\\$(", "   ")  # (an escaped `\$(`, in double quotes too)


# sh's `case x in a|b) cmd ;; esac`: its patterns are no command, only its branches are.
# (possessive: the pattern's class holds spaces too - `\s*` and it split a run of them every way)
_CASE_BRANCH = re.compile(r"(\bin\b|;;&?|;&)(\s*+\(?[^()\n;|&]+(?:\|[^()\n;|&]+)*\))")


def _uncased(line: str) -> str:
    """A line with the patterns of its `case ... esac` taken out (k-okuyucu-2): `start) npm ci`
    is `npm ci`, and a pattern's `)` pairs nothing."""
    if not (re.search(r"\bcase\b", line) and re.search(r"\besac\b", line)):
        return line
    return _CASE_BRANCH.sub(lambda found: f"{found[1]} ", line)


def danger(command: str, instructions: bool = True) -> str:
    """What a command does that cannot be taken back - it deletes, overwrites a git
    remote, opens a secret file or names `.koloni` or another file that steers later turns
    (`names_standing`, `standing_asked`: `instructions` False leaves the instruction files
    out) - in one sentence; "" when it does none.
    Each part of a chained command is looked at. No rule covers such a command, and none is
    offered; Full auto asks about one too (`harms`). shortcut: a list of programs and
    flags, not a sandbox; a deleting script, a program renamed or one inside a shell (`cmd /c
    del`) is not seen - add what the user meets. A continued line is read joined too
    (`_readings`)."""
    return next(filter(None, (_danger(line, instructions) for line in _readings(command))), "")


def _danger(command: str, instructions: bool) -> str:
    standing = standing_asked(command, instructions)
    return _harm(command) or (
        PATCHES
        if standing == PATCH
        else GIT_IDENTITY
        if standing == ".git" and _sets_identity(command)
        else STANDING_FILE.format(name=standing)
        if standing
        else ""
    )


def _sets_identity(command: str) -> bool:
    """Whether every part of a command is a plain `git config [--local] user.name|user.email
    <value>`: this project's own name for its commits, nothing else of .git."""
    parts = _parts(command)
    for words in parts:
        sub, rest = _git_sub(words)
        key = [w for w in rest if w != "--local"]  # (and no option before `config`: -C x)
        if (
            sub != "config"
            or len(words) - len(rest) != 2
            or len(key) != 2
            or key[0].lower() not in ("user.name", "user.email")
        ):
            return False
    return bool(parts)


def standing_asked(command: str, instructions: bool = True) -> str:
    """The name a command names that is asked about at every level (`names_standing`); "" for
    none - and, `instructions` False, for an instruction file alone (`INSTRUCTION_FILES`):
    K-fullauto-sorma, at Full auto in a turn the user watches it is no card, as agents read
    it as the user's words and it runs nothing by itself."""
    standing = names_standing(command)
    return "" if standing in INSTRUCTION_FILES and not instructions else standing


# PowerShell handed its command encoded (`-EncodedCommand`, `-enc`, `-ec`, `-e`).
_ENCODED = re.compile(
    r"(?i)(?:^|(?<=[\s;&|(\"',]))(?:\S*[\\/])?(?:powershell|pwsh)(?:\.exe)?['\"]?"
    r"[\s,](?:[^;&|\n]*[\s,'\"])?[-/]e(?:c|n[a-z]*)?(?=[\s:'\",]|$)"
)


def _harm(command: str) -> str:
    """`danger` but for a file that steers later turns: what `only_reads` cannot have. What a
    shell is handed is looked at too (`_commands_in`): B-339's `cmd /c mklink /J .koloni\\tmp\\x
    ..` is a link before it names `.koloni`."""
    for words in _commands_in(command, at=_BLOCKS):
        if words and (said := _danger_of(words)):
            return said
    if _ENCODED.search(command):  # (what it runs is not read: k-okuyucu-2)
        return _danger_of([UNREAD])
    if _stops_by_name(command):  # (by a name, or an id the line does not know: `_stop_kind`)
        return KILLS_BY_NAME
    if _DOTNET_DELETE.search(command):
        return "Deletes files through .NET ([IO.File]::Delete)."
    if _deletes_basetemp(command):
        return BASETEMP
    if names_secret(command):
        return SECRET_FILE
    if not names_koloni(command):
        return ""
    climbs = _SCRATCH.search(command) and _climbs(command)
    return CLIMBS_OUT if climbs else KOLONI_FILES


# K-okuyucu-3: pytest empties the folder it is given as --basetemp before it runs - on its line,
# in `-o addopts=...` or PYTEST_ADDOPTS (sh's prefix, `$env:`) - but the agents' scratch
# (`.koloni/tmp/...`, `_IN_SCRATCH`). shortcut: one a config file names (`-c x.ini`, an ini's
# addopts) is not read; the rule check asks of `-c` (`_PAST_A_RULE`).
BASETEMP = "Deletes the folder given to pytest's --basetemp: pytest empties it first."
_BASETEMP = re.compile(r"--basetemp(?:=|\s+)['\"]?([^\s'\";&|()]+)")


def _deletes_basetemp(command: str) -> bool:
    return bool(re.search(r"(?i)pytest", command)) and any(
        not _IN_SCRATCH.fullmatch(found[1]) for found in _BASETEMP.finditer(command)
    )


# B-336: the one card-free delete - a deleter alone on its line, by its bare name; plain forcing
# and recursion (`_RECURSES`: a folder of the scratch, no link anywhere below it) its only
# flags; its paths each spelt plainly under `.koloni/tmp/` (no part starting with ".", no
# wildcard); and nothing in the line that joins, wraps, quotes, expands or redirects (`_NOT_PLAIN`:
# `|;&`, a newline, `<>`, a comma or `=` list, any quote - smart ones too -, `^`, a backtick,
# brackets, `$ % ~`, `* ?`).
_SCRATCH_DELETERS = frozenset({"remove-item", "ri", "rm", "del", "erase", "unlink"})
_RECURSES = frozenset({"-r", "-rf", "-fr", "-recurse"})  # (`-R`, `-Rf`: by `casefold`)
_SCRATCH_FLAGS = _RECURSES | {"-f", "--force", "-force", "-fo", "-q", "-path", "-literalpath"}
_SCRATCH = re.compile(r"\.koloni[\\/]tmp\b", re.IGNORECASE)
_IN_SCRATCH = re.compile(r"(?:\./)?\.koloni[/\\]tmp(?:[/\\][\w-][\w.-]*)+", re.IGNORECASE)
_NOT_PLAIN = re.compile(r"[|;&\n\r<>,=`^'\"()\[\]{}$%~*?‘-„]")
# Live (Codex 0.164.0): `Remove-Item -LiteralPath '.koloni/tmp/cs' -Recurse -Force` asked. A
# word that is one plain scratch path in one pair of plain quotes is that path, to sh and to
# PowerShell: read without them. Any other quote - around a flag, a space, two pieces glued,
# a pair left open - is still no plain line.
_QUOTED_SCRATCH = re.compile(r"(?<!\S)(['\"])(" + _IN_SCRATCH.pattern + r")\1(?!\S)", re.IGNORECASE)


def scratch_delete_only(command: str, root: str | None) -> bool:
    """B-336: whether a line is one delete of files in `.koloni/tmp/`, the agents' scratch of
    `root` (the folder it runs in), and nothing else - no card at Full auto, as writing there has
    none. Judged where the card is decided (`AgentRunner._night_asks`): `danger` stays as strict
    as ever, so no rule is offered for such a delete nor covers one. As narrow as it can be
    (`_SCRATCH_DELETERS`, `_SCRATCH_FLAGS`, `_IN_SCRATCH`, `_NOT_PLAIN`), not climbing out
    (`_CLIMBS`, the line read as the shell reads it), and each path, links resolved, inside the
    project's own scratch - which is no link itself. A recursive one (`_RECURSES`) of a folder
    that holds no link (`_holds_link`: Windows PowerShell's `Remove-Item -Recurse` deletes
    through a junction). Not `rmdir /s /q`: `/s` is a path to sh and pwsh. Nor a delete after a
    `cd` into the scratch (run_command's `cwd` there): a `cd` that fails leaves it in the project.
    shortcut: only the links there when it is asked are checked; one made after that by a script
    (python's `_winapi.CreateJunction`: a `mklink` line is a card, a script that makes a link is
    not) is not seen, and Windows PowerShell 5.1's `Remove-Item -Recurse` follows it. Not given
    to Copilot's new shell for that (`_approve_command`); check again as it runs if it is."""
    command = _QUOTED_SCRATCH.sub(r"\2", command)
    if root is None or _NOT_PLAIN.search(command) or _CLIMBS.search(_as_read(command)):
        return False
    words = command.split()
    if not words or words[0].casefold() not in _SCRATCH_DELETERS:
        return False
    flags = [word for word in words[1:] if word.startswith("-")]
    paths = [word for word in words[1:] if not word.startswith("-")]
    if (
        not paths
        or any(flag.casefold() not in _SCRATCH_FLAGS for flag in flags)
        or not all(_IN_SCRATCH.fullmatch(path) for path in paths)
    ):
        return False
    where = os.path.normcase(os.path.join(os.path.realpath(root), ".koloni", "tmp"))
    scratch = os.path.normcase(os.path.realpath(where))
    if scratch != where:  # (the scratch, or .koloni, a link itself: where it leads is not it)
        return False
    real = [os.path.realpath(os.path.join(root, path)) for path in paths]
    recursive = any(flag.casefold() in _RECURSES for flag in flags)
    # (What KOLONİ itself keeps there - the browser's profile, the user's screenshots, the
    # images shown - is not an agent's to empty unasked: `_KOLONIS_OWN`.)
    # (`browser.`: Windows opens a name without its last dots.)
    own = recursive and any(
        re.split(r"[/\\]", path.removeprefix("./"))[2].rstrip(".").casefold() in _KOLONIS_OWN
        for path in paths
    )
    return all(os.path.normcase(path).startswith(scratch + os.sep) for path in real) and not (
        own or names_secret(command) or recursive and _holds_link(real)
    )


_KOLONIS_OWN = frozenset({"browser", "images"})  # (`AgentRunner._scratch_folder`'s)


def _holds_link(tops: list[str], left: int = 10_000) -> bool:
    """Whether a line's folders hold a link or a junction anywhere below them, or more than is
    looked at. shortcut: 10,000 entries (`left`) for the line, then it is asked - a scratch
    folder larger than that (a browser's cache) keeps its card; raise it, or walk off the event
    loop, if that is met. shortcut: any link asks - a venv's own symlinks (POSIX) too; tell
    those that stay in the folder apart if a venv in the scratch is met."""
    folders = list(tops)
    while folders:
        try:
            with os.scandir(folders.pop()) as found:
                for entry in found:
                    left -= 1
                    if left < 0 or entry.is_symlink() or entry.is_junction():
                        return True
                    if entry.is_dir(follow_symlinks=False):
                        folders.append(entry.path)
        except (FileNotFoundError, NotADirectoryError):  # (a file, or nothing: no folder)
            continue
        except (OSError, ValueError):  # (not read, or a path too long for Windows: not known)
            return True
    return False


# Programs that read every file below the folder they are in; those that read what they are
# handed; and those that list a folder's files, which a reader later in the line then reads.
_SEARCHERS = frozenset({"rg", "ripgrep", "ag", "ack"})
_GREPS = frozenset({"grep", "egrep", "fgrep"})
_READERS = frozenset(
    {
        *_GREPS,
        "cat",
        "type",
        "more",
        "less",
        "head",
        "tail",
        "strings",
        "get-content",
        "gc",
        "findstr",
        "select-string",
        "sls",
    }
)
_LISTERS = frozenset({"get-childitem", "gci", "ls", "dir"})
# Get-Content and its aliases: handed names by a pipe, it opens each of them.
_GETS = frozenset({"get-content", "gc", "cat", "type"})
# What also passes a pipe's names on, beside `_sink`'s: Sort-Object and Where-Object by their
# aliases (not sinks: sort.exe's `/o` writes, a `where` block may run anything).
_SHAPERS = frozenset({"sort", "where", "where-object", "?"})
# What hands a pipe text alone, never a file to open: the web's answers, git's, echo's.
_TEXTS = frozenset(
    {
        "curl",
        "wget",
        "invoke-webrequest",
        "iwr",
        "invoke-restmethod",
        "irm",
        "echo",
        "write-output",
        "git",
    }
)
_GLOB = re.compile(r"[*?]")
# (said on its card only where the folder holds one: `command_out`'s `held`)
SEARCHES_FOLDER = (
    "It searches the whole folder, and the folder holds a secret file: asked at every level."
)


def _one_file(rest: list[str]) -> bool:
    """Whether Select-String is handed one file, no wildcard: by -Path or -LiteralPath, or
    as its second word that is no option's (`sls KEY README.md`)."""
    named = [
        rest[at + 1]
        for at, word in enumerate(rest[:-1])
        if word.lower() in ("-path", "-literalpath", "-lp")
    ]
    if not named:
        plain = [
            word
            for at, word in enumerate(rest)
            if not word.startswith("-") and not (at and rest[at - 1].startswith("-"))
        ]
        named = plain[1:2]
    return len(named) == 1 and not _GLOB.search(named[0])


def _lists_all(program: str, rest: list[str]) -> bool:
    """Whether a lister goes into every folder below: `gci -r`, `-Recurse`, `dir /s`, `ls -R`."""
    return (
        program == "find"
        or program in _LISTERS
        and any(
            "-recurse".startswith(word.lower())
            and len(word) > 1
            or word.lower() == "/s"
            or word.lower().startswith("-dep")  # (`-Depth 9`: as deep as it is told)
            or _cluster(word, "R")
            for word in rest
        )
    )


def searches_folder(command: str) -> bool:
    """Whether a command reads every file of a folder: a search that goes into each folder
    below (`rg`, `grep -r`, `findstr /s`, `git grep`, Select-String not handed one file), a
    list of them all handed to a reader (`gci -Recurse | gc`, `find -exec cat`, `| xargs
    grep`), or a reader handed a wildcard (`type *`) - in a shell (`cmd /c`, `powershell
    -Command '...'`) too. shortcut: a table of programs and flags, not a parser; an alias or
    a loop that opens each file is not seen. shortcut: a script run (`python x.py`) that
    reads .env is not seen - carding every script would end Full auto; the OS-level answer
    is a sandbox (105 for Copilot, 104 in Docker; AGENT_CHAT CL-20261024-008)."""
    return bool(_search_scopes(command))


# B-316: where a search reads - the paths it is given and the globs it keeps to - or None where
# that is not read off the line. Fail closed: a scope is read only where every word of the search
# is understood (`_OPTIONS`' tables, `_plain`); anything else - an option not listed, a variable,
# a bracket, `..`, pathspec magic, a `cd` out - is None, and None reaches every secret file.
Scope = tuple[list[str], list[str]] | None
# Each searcher's options: flags that take no value, and options that take one. Short ones are
# compared as written (grep's `-T` is not `-t`); PowerShell's (`ps`) in any case, by the full name
# or a listed alias only - an abbreviation is not read. Left out on purpose, so they ask: an option
# whose value is a file read or a program run (`-f`, `--pre`, `--ignore-file`, `-O`), one that
# follows links (`-L`, `-R`, `-FollowSymlink`), git's `--no-index`, and gci's `-Filter` (it matches
# 8.3 short names: `env*` is `.env`'s ENV~1).
_OPTIONS: dict[str, tuple[frozenset[str], frozenset[str], bool]] = {
    "rg": (
        frozenset(
            {
                "-i",
                "--ignore-case",
                "-S",
                "--smart-case",
                "-s",
                "--case-sensitive",
                "-n",
                "--line-number",
                "-N",
                "--no-line-number",
                "-l",
                "--files-with-matches",
                "--files-without-match",
                "-c",
                "--count",
                "--count-matches",
                "-w",
                "--word-regexp",
                "-x",
                "--line-regexp",
                "-v",
                "--invert-match",
                "-F",
                "--fixed-strings",
                "-P",
                "--pcre2",
                "-U",
                "--multiline",
                "--multiline-dotall",
                "-o",
                "--only-matching",
                "-.",
                "--hidden",
                "-u",
                "--unrestricted",
                "--no-ignore",
                "--no-ignore-vcs",
                "--no-ignore-dot",
                "--no-ignore-global",
                "--no-ignore-parent",
                "--no-ignore-exclude",
                "--no-ignore-files",
                "--no-heading",
                "--heading",
                "-H",
                "--with-filename",
                "-I",
                "--no-filename",
                "--vimgrep",
                "--json",
                "-q",
                "--quiet",
                "--column",
                "--no-column",
                "-a",
                "--text",
                "--trim",
                "-b",
                "--byte-offset",
                "-0",
                "--null",
                "--stats",
                "--no-config",
                "-p",
                "--pretty",
                "--line-buffered",
                "--block-buffered",
                "--binary",
                "--no-binary",
                "--crlf",
                "--no-messages",
                "--no-unicode",
                "--include-zero",
                "--no-require-git",
                "--one-file-system",
                "--no-follow",
                "--passthru",
                "--sort-files",
            }
        ),
        frozenset(
            {
                "-e",
                "--regexp",
                "-g",
                "--glob",
                "--iglob",
                "-t",
                "--type",
                "-T",
                "--type-not",
                "--type-add",
                "-A",
                "--after-context",
                "-B",
                "--before-context",
                "-C",
                "--context",
                "-m",
                "--max-count",
                "-d",
                "--max-depth",
                "-M",
                "--max-columns",
                "-j",
                "--threads",
                "--color",
                "--colors",
                "--sort",
                "--sortr",
                "-E",
                "--encoding",
                "--max-filesize",
                "-r",
                "--replace",
                "--path-separator",
                "--context-separator",
                "--engine",
            }
        ),
        False,
    ),
    "grep": (
        frozenset(
            {
                "-r",
                "--recursive",
                "-n",
                "--line-number",
                "-i",
                "-y",
                "--ignore-case",
                "--no-ignore-case",
                "-v",
                "--invert-match",
                "-w",
                "--word-regexp",
                "-x",
                "--line-regexp",
                "-c",
                "--count",
                "-l",
                "--files-with-matches",
                "-L",
                "--files-without-match",
                "-o",
                "--only-matching",
                "-q",
                "--quiet",
                "--silent",
                "-s",
                "--no-messages",
                "-H",
                "--with-filename",
                "-h",
                "--no-filename",
                "-b",
                "--byte-offset",
                "-a",
                "--text",
                "-I",
                "-E",
                "--extended-regexp",
                "-F",
                "--fixed-strings",
                "-G",
                "--basic-regexp",
                "-P",
                "--perl-regexp",
                "-z",
                "--null-data",
                "-Z",
                "--null",
                "-T",
                "--initial-tab",
                "-U",
                "--binary",
                "--color",
                "--colour",
                "--line-buffered",
                "--no-group-separator",
            }
        ),
        frozenset(
            {
                "-e",
                "--regexp",
                "-m",
                "--max-count",
                "-A",
                "--after-context",
                "-B",
                "--before-context",
                "-C",
                "--context",
                "-d",
                "--directories",
                "-D",
                "--devices",
                "--include",
                "--exclude",
                "--exclude-dir",
                "--label",
                "--group-separator",
                "--binary-files",
            }
        ),
        False,
    ),
    "git grep": (
        frozenset(
            {
                "-n",
                "--line-number",
                "-i",
                "--ignore-case",
                "-I",
                "-v",
                "--invert-match",
                "-w",
                "--word-regexp",
                "-l",
                "--files-with-matches",
                "--name-only",
                "-L",
                "--files-without-match",
                "-c",
                "--count",
                "-h",
                "-H",
                "-o",
                "--only-matching",
                "-q",
                "--quiet",
                "-E",
                "--extended-regexp",
                "-F",
                "--fixed-strings",
                "-G",
                "--basic-regexp",
                "-P",
                "--perl-regexp",
                "--cached",
                "--untracked",
                "--exclude-standard",
                "--no-exclude-standard",
                "--full-name",
                "--heading",
                "--break",
                "--column",
                "-p",
                "--show-function",
                "-W",
                "--function-context",
                "--and",
                "--or",
                "--not",
                "--all-match",
                "-a",
                "--text",
                "-r",
                "--recursive",
                "--no-recursive",
                "-z",
                "--null",
                "--color",
                "--no-color",
                "--recurse-submodules",
                "--no-textconv",
            }
        ),
        frozenset(
            {
                "-e",
                "-m",
                "--max-count",
                "-A",
                "--after-context",
                "-B",
                "--before-context",
                "-C",
                "--context",
                "--max-depth",
                "--threads",
            }
        ),
        False,
    ),
    "select-string": (
        frozenset(
            {
                "-simplematch",
                "-casesensitive",
                "-allmatches",
                "-notmatch",
                "-quiet",
                "-list",
                "-raw",
                "-noemphasis",
            }
        ),
        frozenset(
            {
                "-pattern",
                "-path",
                "-literalpath",
                "-lp",
                "-pspath",
                "-include",
                "-exclude",
                "-encoding",
                "-context",
                "-culture",
            }
        ),
        True,
    ),
    "lister": (
        frozenset(
            {
                "-recurse",
                "-rec",
                "-r",
                "-file",
                "-force",
                "-name",
                "-directory",
                "-hidden",
                "-readonly",
                "-system",
                "-af",
                "-ad",
                "-ah",
            }
        ),
        frozenset({"-path", "-literalpath", "-lp", "-include", "-exclude", "-depth"}),
        True,
    ),
}
# A search's pattern, quoted - after `-Pattern`, `-e`/`-E`, `--regexp`, or as the first word of
# rg's, grep's or Select-String's past their flags (`rg -n "a|b"`) - holds no `|` or `;` that
# chains. Only these: a quoted script a shell is handed (`bash -lc "a | b"`) does chain.
_QUOTED_VALUE = re.compile(
    r"""(?i)(?<![\w-])((?:-pattern|-e|--regexp|(?:rg|grep|egrep|fgrep|sls|select-string)"""
    r"""(?:\s+-[\w-]+)*)\s+)("[^"]*"|'[^']*')"""
)
# A PowerShell variable, as PowerShell reads its name: in any case, `${f}` and `$script:f` too
# (not `$env:x`, nor another drive's).
_SCOPED = r"(?:(?:script|global|local|private):)?"
_VAR = rf"\$(?:\{{{_SCOPED}(\w+)\}}|{_SCOPED}(\w+)(?![\w:{{]))"
_VAR_RE = re.compile(_VAR, re.I)
_ASSIGNS = re.compile(_VAR + r"""\s*(?:[-+*/%]|\?\?)?=(?!=)""", re.I)
# `$f = 'a.py'` alone: its line's last command, or followed by one.
_ASSIGNED_PATH = re.compile(_VAR + r"""\s*=\s*(['"])([^'"$`]*)\3\s*(?=;|\r?\n|$)""", re.I)
# What may set a variable another way, or run code that may: then none is read.
_SETS_VARIABLES = re.compile(
    r"""(?i)(?<![\w-])(?:set-variable|new-variable|clear-variable|remove-variable|sv|nv|clv|rv"""
    r"""|set|gv|get-variable|psvariable|iex|invoke-expression"""
    r"""|foreach|for|param|ref|variable:)(?![\w-])|(?<![\w-])-(?:outvariable|ov|errorvariable|ev"""
    r"""|warningvariable|wv|informationvariable|iv|pipelinevariable|pv)(?![\w-])|\.value\b"""
)
_CD = frozenset(
    {"cd", "sl", "chdir", "pushd", "push-location", "set-location", "popd", "pop-location"}
)


def _known_values(command: str) -> dict[str, str]:
    """The variables a line assigns a literal path once and nothing else, by their name in lower
    case; none where something else may set one (`_SETS_VARIABLES`)."""
    if _SETS_VARIABLES.search(command):
        return {}
    named = [(a or b).casefold() for a, b in _ASSIGNS.findall(command)]
    return {
        name: path
        for a, b, _quote, path in _ASSIGNED_PATH.findall(command)
        if named.count(name := (a or b).casefold()) == 1
    }


def _unquoted(word: str) -> str:
    return word[1:-1] if len(word) > 1 and word[0] == word[-1] and word[0] in "'\"" else word


def _plain(raw: str, base: Path | None, root: Path | None) -> str | None:
    """A path word of a search as the folder's own path to it (`root`'s, from `base`, where it
    runs), or None for one that is not a plain literal inside it: a variable left, a bracket, a
    backtick, a brace, `%`, pathspec magic (`:`), a trailing dot or space (Windows drops them),
    `..`, a root, a drive or `~`; a wildcard in a short name's place (`*~1`); or - with `root` -
    one not there, or that leads out of it (a link)."""
    word = _unquoted(raw)
    if (
        not word
        or re.search(r"[$(){}`%@;]", word)
        or word.startswith(":")
        or word.endswith(" ")
        or len(word) > 1
        and word.endswith(".")
        and word[-2] not in "/\\"
        or _outside(word)
    ):
        return None
    parts = [part for part in word.replace("\\", "/").split("/") if part not in ("", ".")]
    if ".." in parts or any(_GLOB.search(part) and "~" in part for part in parts):
        return None
    if root is None or base is None:
        return "/".join(parts) or "."
    fixed = next((at for at, part in enumerate(parts) if re.search(r"[*?\[]", part)), len(parts))
    # shortcut: only the path as named is resolved; a junction below it that leads elsewhere, which
    # PowerShell 5.1's `gci -Recurse` walks into, is not seen - placing one takes deliberate steps
    # (a write, then a search); walk the scope for links if that is ever met.
    try:
        at = (base / "/".join(parts[:fixed])).resolve(strict=True).relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    return "/".join([*([at.as_posix()] if at.as_posix() != "." else []), *parts[fixed:]]) or "."


def _options(words: list[str], kind: str) -> tuple[list[str], list[tuple[str, str]], int] | None:  # noqa: C901
    """A searcher's words read by its table (`_OPTIONS`): the words no option's, each option's
    value by its name, and how many of those words came before a bare `--`; None where a word is
    an option not in the table, or wants a value it is not given."""
    flags, valued, ps = _OPTIONS[kind]
    plain: list[str] = []
    values: list[tuple[str, str]] = []
    ended = None
    at = 0
    while at < len(words):
        word = _unquoted(words[at])
        key = word.lower() if ps else word
        if word == "--" and not ps:
            ended = len(plain)
            plain += words[at + 1 :]
            break
        if not word.startswith("-") or len(word) < 2:
            plain.append(words[at])
        elif (
            (given := key.partition(":" if ps else "="))
            and given[1]
            and (given[0] in valued or given[0] in flags)
        ):
            values.append((given[0], given[2]))  # (`--glob=x`, `-Path:x`, `--color=never`)
        elif given[1]:
            return None
        elif key in flags:
            pass
        elif key in valued:
            if at + 1 == len(words):
                return None
            values.append((key, words[at + 1]))
            at += 1
        elif not ps and not word.startswith("--"):
            # A cluster of short ones (`-rn`, `-C3`, `-rnA 3`): a value's letter takes the rest.
            for spot, letter in enumerate(word[1:], 1):
                if f"-{letter}" in flags:
                    continue
                if f"-{letter}" not in valued:
                    return None
                if word[spot + 1 :]:
                    values.append((f"-{letter}", word[spot + 1 :]))
                elif at + 1 < len(words):
                    values.append((f"-{letter}", words[at + 1]))
                    at += 1
                else:
                    return None
                break
        else:
            return None
        at += 1
    return plain, values, len(plain) if ended is None else ended


def _scope(  # noqa: C901
    kind: str,
    words: list[str],
    base: Path | None,
    root: Path | None,
    handed: Scope,
) -> Scope:
    """The scope of one search (`_OPTIONS`' `kind`, or "reader": a reader handed a wildcard) by
    its raw words past its program's; `handed`: what a lister before it hands its pipe."""
    if kind == "reader":
        read = None if any(_unquoted(w).startswith("-") for w in words) else (words, [], 0)
    else:
        read = _options(words, kind)
    if read is None:
        return None
    plain, values, ended = read
    said = {name for name, _value in values}
    globs = [value for name, value in values if name in ("-g", "--glob", "--iglob", "--include")]
    # (`-g '!x'` passes x by: it keeps the search to nothing it did not have)
    globs = [_unquoted(g) for g in globs if not _unquoted(g).startswith("!")]
    # (rg's globs are gitignore's - `/x` anchored at the root, `**/` no folder too - and fnmatch
    # reads neither: one with a folder in it reads no scope; `*.py` does.)
    if any(re.search(r"[{}$`(/\\]", g) for g in globs):
        return None
    if kind == "lister":
        paths = [value for name, value in values if name in ("-path", "-literalpath", "-lp")]
        if len(plain) > 1:  # (its second plain word is a -Filter)
            return None
        paths += plain
        globs = [_unquoted(v) for name, v in values if name == "-include"]
        if any(re.search(r"[{}$`(~/\\]", g) for g in globs):
            return None
    elif kind == "select-string":
        paths = [
            value for name, value in values if name in ("-path", "-literalpath", "-lp", "-pspath")
        ]
        paths += plain if "-pattern" in said else plain[1:]
        globs = []
        if not paths:
            return handed
    elif kind == "git grep":
        told = "-e" in said
        before, after = plain[:ended], plain[ended:]
        # (past the pattern, only a pathspec: a revision or a word git may take for one asks)
        if len(before) != (0 if told else 1):
            return None
        paths = after or ["."]
    elif kind == "reader":
        paths = plain
    else:
        told = said & {"-e", "--regexp"}
        paths = plain if told else plain[1:]
        if not told and not plain:
            return None
    # (no path: where it runs)
    found = [_plain(p, base, root) for raw in paths or ["."] for p in raw.split(",")]
    return None if None in found else ([p for p in found if p is not None], globs)


def _search_scopes(command: str, root: Path | None = None, cwd: str = ".") -> list[Scope]:  # noqa: C901
    """The scope of each search of the whole folder a command makes (`searches_folder`), read
    against `root` where given, from `cwd` (the folder's own path to where it runs): [] for a
    command that makes none."""
    # (A variable `_known_values` reads is its path; any other stands for what is not known: for
    # what a search is, a wildcard - `gc $f` may read anything -, and no scope.)
    known = _known_values(command)
    raw = _VAR_RE.sub(lambda found: known.get((found[1] or found[2]).casefold(), found[0]), command)
    raw = _QUOTED_VALUE.sub(
        lambda found: found[1] + re.sub(r"[|;&<>]", " ", found[2]), re.sub(r"\d?>&\d", " ", raw)
    )
    # (quotes and brackets out: what a shell is handed is read as the rest of the line is; and
    # `2>&1`, whose `&` chains nothing. The raw line beside it, part by part, for the scope.)
    seen = re.sub(r"[\"'`(){}$@]", " ", re.sub(r"\$[\w:]+", "?*", raw))
    found: list[Scope] = []
    listed, texts, lists, lister = False, True, None, False
    base, lost = (root / cwd if root is not None else None), False
    pieces = re.split(f"({_PARTS.pattern})", seen)
    raws = re.split(f"({_PARTS.pattern})", raw)
    # (A `cd` anywhere but at the start of a part of the line - in a block, a loop - is not
    # followed: then no scope is read.)
    lost = lost or any(
        _program(word.strip("{(")) in _CD for part in raws[::2] for word in _words(part.strip())[1:]
    )
    for part, written, before in zip(pieces[::2], raws[::2], ["", *pieces[1::2]], strict=True):
        words, fed = _words(part.strip()), False
        given = _words(written.strip())
        handed_list, lists = (lists if before == "|" else None), None
        handed_names, lister = (lister if before == "|" else False), False
        # shortcut: only what it runs were its wrappers' unknown options to take no value
        # (`_unwrapped`'s first); judge the others too if a search is met hidden so.
        handed = _unwrapped(words)[0]
        wrapped = len(handed) < len(words)
        fed = any(_program(w) == "xargs" for w in words[: len(words) - len(handed)])
        words = handed
        if not words:
            continue
        program, rest = _program(words[0]), words[1:]
        known_words = not wrapped and not lost and bool(given) and _program(given[0]) == program
        if program in _CD:
            # Only into a plain folder inside the folder: from there what it searches is read.
            target = _plain(given[1], base, root) if known_words and len(given) == 2 else None
            if target is None or root is None or not (root / target).is_dir():
                lost = True
            else:
                base = root / target
            continue

        def scope(
            kind: str,
            words: list[str] = given[1:],
            base: Path | None = base,
            handed: Scope = handed_list,
            known: bool = known_words,
        ) -> Scope:
            return _scope(kind, words, base, root, handed) if known else None

        # (a listing handed to it in brackets: `gc (gci -r -File)`)
        handed = any(
            _program(w) in _LISTERS and _lists_all(_program(w), rest[at + 1 :])
            for at, w in enumerate(rest)
        )
        # Only names (`rg --files`): a list, as `gci -r` is. A Select-String given no file
        # reads what the pipe hands it: only text where all before it make text alone
        # (`curl ... | sls`), else maybe files (`gci | sls`, `gi * | sls`).
        names = program in _SEARCHERS and "--files" in rest
        piped = before == "|" and texts
        grep = program == "git" and _after_options(rest, _GIT_VALUE_OPTIONS)[:1] == ["grep"]
        if program in ("rg", "ripgrep") and not names:
            found.append(scope("rg"))
        elif (
            program in _GREPS
            and not fed
            and any(
                _cluster(w, "r")
                or _cluster(w, "R")
                or w.startswith("--")
                and "recurs" in w
                or w == "recurse"
                and rest[at - 1 : at] in (["-d"], ["--directories"])
                for at, w in enumerate(rest)
            )
        ):
            found.append(scope("grep"))
        elif grep:
            # (git told anything before its grep - `-C ..`, `--git-dir` - asks)
            found.append(scope("git grep", given[2:]) if given[1:2] == ["grep"] else None)
        elif (
            program in _SEARCHERS
            and not names
            or program == "findstr"
            and any(re.fullmatch(r"/[a-z]*s[a-z]*", w, re.I) for w in rest)
            or program in _READERS
            and (fed or handed)
            or program == "find"
            and any(_program(w) in _READERS for w in rest)
        ):
            found.append(None)
        elif program in ("select-string", "sls") and not _one_file(rest) and not piped:
            # (handed files by a pipe: those the lister right before it lists)
            found.append(scope("select-string"))
        elif program in _READERS and any(_GLOB.search(w) for w in rest):
            found.append(scope("reader"))
        elif listed and any(_program(w) in _READERS for w in words):
            found.append(handed_list)
        elif handed_names and any(_program(w) in _GETS for w in words):
            # A lister's names of one level, handed by a pipe to Get-Content (`gci | gc`, `ls |
            # cat` in PowerShell, `gci | % { gc $_ }`): it opens each of them, a secret file
            # too. shortcut: in a POSIX shell `ls | cat` prints the names, and is a card all the
            # same - only where the folder holds a secret file; `gi * | gc` is not seen - add
            # Get-Item to the listers if it is met.
            found.append(handed_list)
        if names or _lists_all(program, rest):
            listed = True
            lists = scope("lister") if program in _LISTERS else None
        elif program in _LISTERS:
            lister, lists = True, scope("lister")
        elif handed_names and (_sink(part) or program in _SHAPERS):
            # (a stage that only shapes the names - `gci | select -first 3 | gc` - hands them on)
            lister, lists = True, handed_list
        # (Each pipeline of a chain on its own: `cd x; git log | sls y` hands sls git's text.
        # B-316: an interpreter's output - `python -m pytest | sls x` - and a named file's lines
        # are text too. shortcut: another program's - `.\tool.exe | sls x` - is not.)
        texts = (texts or before != "|") and (
            program in _TEXTS or bool(_INTERPRETER.fullmatch(program)) or program in _GETS
        )
    return found


# What only reads or lists what it is named (`more` and `less` wait for a key); and git's.
_LOOKERS = frozenset({*_READERS, *_LISTERS, "pwd", "get-location", "test-path"} - {"more", "less"})
_GIT_LOOKS = frozenset({"status", "diff", "log", "show"})


def _git_looks(rest: list[str]) -> bool:
    """Whether git's words (after `git`) only read: one of `_GIT_LOOKS` its first word - no
    option before it (`-C`, `--git-dir`) -, with nothing that writes a file or runs a program."""
    return (
        bool(rest)
        and rest[0] in _GIT_LOOKS
        and not any(word.startswith(("--output", "--ext-diff", "--textconv")) for word in rest)
    )


def only_reads(command: str) -> bool:
    """Whether a command only reads or lists what it names in the folder it runs in: one
    plain command (`Get-Content x`, `ls src`, `git diff`), naming no secret file, nothing
    outside the folder, and no search of the whole folder or listing of every folder below.
    Below Full auto it runs unasked (K-ask-okuma, B-49). shortcut: a table of programs, not
    a sandbox; `rg foo a.py` is judged a folder search and asked - tell a named file apart if
    that is met. shortcut: git's diff and log run a diff driver or textconv set in its config;
    writing .git or running `git config` is asked, so one got there only on the user's word.
    Where git's may run unasked: `reads_here`."""
    # (`_harm`, not `danger`: a read of AGENTS.md is a read - `names_standing` asks this)
    if (
        not is_plain(command)
        or is_wrapped(command)
        or _in_a_shell(command)
        or _harm(command)
        or searches_folder(command)
    ):
        return False
    words = [word.strip("'\"") for word in _words(command.strip())]
    # (one by its path - `.\cat` - is a program of the folder's own, which an agent can write)
    if not words or re.search(r"[\\/]", words[0]):
        return False
    program, rest = _program(words[0]), words[1:]
    if program == "git":
        # (Whole names: git's diff options are not taken cut short - `--outp` is refused, `--text`
        # is its own and only reads.)
        looks = _git_looks(rest)
        pieces = [piece for word in rest for piece in re.split(r"[=:,]", word)]  # (`HEAD:a.py`)
    else:
        looks = (
            program in _LOOKERS
            and not _lists_all(program, rest)
            and not (
                # (one that follows a file runs on, as a server does: asked, as one is)
                program == "tail"
                and any(w.startswith(("-f", "-F", "--f")) for w in rest)
                or program in ("get-content", "gc", "type", "cat")
                and any(w.lower().startswith("-wa") for w in rest)
            )
        )
        # A `:` past an option's own (`-Path:x`) is another drive's folder (`D:x`) or a
        # provider (`env:`, `HKCU:`): never a plain read here.
        named = [re.sub(r"^-\w+:", "", word) for word in rest]
        looks = looks and not any(":" in word for word in named)
        pieces = [piece for word in named for piece in re.split(r"[=,]", word)]
    # (`git diff --no-index /x` reads outside too; `gc a,..\x` is a list of two)
    return looks and not any(_outside(piece) for piece in pieces if piece)


def only_looks(command: str) -> bool:
    """K-48: whether a command only reads, lists or searches (`_reads`) - also one plain lister,
    reader or search by its program whatever it is told (`gci -Recurse`, `dir C:\\x`): what is
    refused it is a read, never a write."""
    words = _words(command.strip())
    return (
        _reads(command)
        or is_plain(command)
        and bool(words)
        and (_program(words[0]) in _LOOKERS | _SEARCHERS)
    )


def reads_here(command: str, root: Path, at_root: bool, cwd: str = ".") -> bool:
    """Whether a command runs unasked below Full auto (`only_reads`): git's only at the root
    of the folder it works in (a repository shaped in a folder below could set what git
    runs) and while that folder holds no secret file - its diff, log and show print a
    committed one's lines without naming it. And (k-okuma-yol) every path it names, followed
    through links and junctions as `read_file` follows them (`Workspace.resolve`), ends in the
    folder and on no secret path (`_named_here`). `cwd`: where in `root` it runs. shortcut: a
    gitignored .env cards git too; ask `git ls-files` if that is met. Blocking: call it off the
    event loop."""
    if not only_reads(command) or not _named_here(command, root, cwd):
        return False
    return _program(_words(command.strip())[0]) != "git" or at_root and secret_held(root) is None


# What a read's paths are followed for, at most: a line naming more is asked.
MOST_NAMED = 64
MOST_MATCHED = 256


def _named_here(command: str, root: Path, cwd: str) -> bool:
    """Whether each path a plain read names (`only_reads`' words, a glob's matches), followed
    through links and junctions, ends inside `root` and on no secret path - a link in the
    project that leads out of it (planted, or a repository's symlink) reads nothing outside
    unasked, as `read_file` refuses it. A name that is no file reads nothing: passed. A line
    naming more than it is worth following (MOST_NAMED, a glob over MOST_MATCHED): False.
    shortcut: the paths are followed when the line is judged - a link made between this and
    the run needs a second process at work at the same time; follow again at the run if that
    is met. shortcut: a hard link to a secret file is one file of two names, which `resolve()`
    does not see (as for `read_file`); compare file ids if that is met."""
    try:
        top = root.resolve()
        here = (root / cwd).resolve()
    except (OSError, RuntimeError):
        return False
    if not here.is_relative_to(top):
        return False
    pieces = [
        piece
        for word in _joined_words(command.strip())[1:]
        for name in _names_in(word)
        for piece in re.split(r"[=:,]", name)
        if piece
    ]
    if len(pieces) > MOST_NAMED:
        return False
    for piece in pieces:
        found = _named_paths(here, piece)
        if found is None or not all(_lands_here(one, top) for one in found):
            return False
    return True


def _joined_words(command: str) -> list[str]:
    """A line's words as a shell splits them: at whitespace outside quotes - a word's quoted
    pieces stay one word (`".e"nv`, which `shlex`'s non-POSIX split cuts in two)."""
    words: list[str] = []
    word, quote = "", ""
    for char in command:
        if quote:
            word += char
            quote = "" if char == quote else quote
        elif char in "'\"":
            word, quote = word + char, char
        elif char.isspace():
            words, word = (words + [word]) if word else words, ""
        else:
            word += char
    return [*words, word] if word else words


def _dequoted(word: str) -> str:
    """A word as the shell hands it on: pwsh and sh both join quoted pieces in one word
    (`.e'nv'`, `".e"nv`, `out/'secret.txt'` are `.env`, `.env`, `out/secret.txt`)."""
    return word.replace("'", "").replace('"', "")


def _unescaped(word: str) -> str:
    """A word as sh hands it on: its backslash escapes resolved - any outside quotes (`ou\\t`
    is `out`, `.e\\nv` is `.env`), only `\\ " $ ` ` in double quotes, none in single ones -
    and its quotes gone."""
    out: list[str] = []
    quote, at = "", 0
    while at < len(word):
        char = word[at]
        if (
            char == "\\"
            and quote != "'"
            and at + 1 < len(word)
            and (not quote or word[at + 1] in '\\"$`')
        ):
            out.append(word[at + 1])
            at += 2
            continue
        if char in "'\"" and quote in ("", char):
            quote = "" if quote else char
        else:
            out.append(char)
        at += 1
    return "".join(out)


def _read_spellings(word: str) -> list[str]:
    """A word as each shell may hand it on: with its backslashes kept (pwsh, cmd: a separator)
    and resolved as sh's escapes (Git Bash, a CLI's Bash tool) - followed both ways everywhere,
    a spelling that names no file passing."""
    return list(dict.fromkeys((_dequoted(word), _unescaped(word))))


def _names_in(word: str) -> list[str]:
    """What a read's word may name (review of k-okuma-yol): the word, unquoted - each spelling
    (`_read_spellings`) - or, for an option, its value (`-Path:x`, `--file=x`) and an attached short
    option's tail (`-fx`). More candidates cost nothing: one that is no file passes."""
    return [name for spelt in _read_spellings(word) for name in _option_names(spelt)]


def _option_names(word: str) -> list[str]:
    if not word.startswith("-"):
        return [word]
    value = re.split(r"[=:]", word, maxsplit=1)
    return [*value[1:], *([word[2:]] if not word.startswith("--") and len(word) > 2 else [])]


def _named_paths(here: Path, piece: str) -> list[Path] | None:
    """What a word of a read names in `here`: its glob's matches, or the path where something
    is there (a dangling link too); None: a glob over MOST_MATCHED."""
    if glob.has_magic(piece):
        matched = list(itertools.islice(glob.iglob(str(here / piece)), MOST_MATCHED + 1))
        return None if len(matched) > MOST_MATCHED else [Path(one) for one in matched]
    path = here / piece
    return [path] if os.path.lexists(path) else []


def _lands_here(path: Path, top: Path) -> bool:
    """Whether a named path, followed through every link, ends in the folder and on no secret
    path."""
    try:
        real = path.resolve()
    except (OSError, RuntimeError):  # (a loop of links: not followed, asked)
        return False
    if not (real == top or real.is_relative_to(top)):
        return False
    return real == top or not secret_in_project(real.relative_to(top).as_posix())


# How long a folder's answer is kept: the commands of one turn do not each walk it.
HELD_SECONDS = 10.0
_held: dict[Path, tuple[float, list[str]]] = {}


def secret_files(root: Path) -> list[str]:
    """The secret files (`secret_in_project`) in a folder, by their paths in it - a secret
    folder (.ssh) as itself - walked as KOLONİ's own search walks one: not into .git, .venv
    or node_modules, nor through a link. shortcut: `grep -r` reads `.git/config` too, whose
    remote may hold a token; counting it would card every search in every repository -
    count it if a token turns up there. shortcut: a folder it may not open stops the walk,
    and what was not reached counts as no secret (fails open) - walk on past it if that is
    met. shortcut: one made after the walk (kept HELD_SECONDS) is not among them; walk again
    for each command if that matters. Blocking: call it off the event loop."""
    at, found = _held.get(root, (float("-inf"), []))
    if time.monotonic() - at >= HELD_SECONDS:
        folder, found = Workspace(root), []
        with contextlib.suppress(OSError):  # a folder it may not open: what it holds is not known
            for path in folder._walk(folder.root):
                if secret_in_project(rel := folder.rel(path)):
                    parts = rel.split("/")
                    inside = next(
                        (
                            n
                            for n, part in enumerate(parts[:-1])
                            if part.casefold() in SECRET_FOLDERS
                        ),
                        None,
                    )
                    found.append(rel if inside is None else "/".join(parts[: inside + 1]))
        # KOLONİ's own checkout or record in the folder: not walked, but a search of the
        # whole folder reads its .env and its CLIs' logins - a secret folder of its own.
        found = list(dict.fromkeys([*found, *folder.koloni_places()]))
        _held[root] = (time.monotonic(), found)
    return found


def secret_held(root: Path) -> str | None:
    """The first of `secret_files`, or None."""
    return next(iter(secret_files(root)), None)


def search_reason(command: str, root: Path, cwd: str = ".") -> str:
    """Why a command is asked at every level, Full auto too, and refused where nobody is
    watching: it searches the whole folder, and `root` holds a secret file - "" when not.
    `cwd`: where in `root` it runs (K-buyuk-proje: a part's folder), which its paths are read
    from; one that leads out of `root` reads no scope, and asks. A search of a folder outside
    it is judged by that folder's own rules.
    B-316: a search kept to paths or globs (`sls -Path tests/*.py`, `git grep x -- tests`,
    `rg x src -g '*.py'`) asks only where one of the folder's secret files is in its reach
    (`_reaches`); one whose scope is not read off the line reaches every one.
    A line that begins by entering the scratch (`_ENTERS`, no card of its own) is also judged as
    if that `cd` failed - sh's `cd .koloni\\tmp\\x; grep -r KEY .` and `sl .koloni/tmp; ...`
    run the search where the line began."""
    entered = _ENTERS.match(command)
    scopes = _search_scopes(command, root, cwd) + (
        _search_scopes(command[entered.end() :], root, cwd) if entered else []
    )
    if not scopes or not (secrets := secret_files(root)):
        return ""
    held = next(
        (
            secret
            for secret in secrets
            if any(scope is None or _reaches(scope, secret, root) for scope in scopes)
        ),
        None,
    )
    return (
        ""
        if held is None
        else (
            f"it searches the whole folder, and the folder holds a secret file ({held}) - "
            "asked at every level"
        )
    )


def _reaches(scope: tuple[list[str], list[str]], secret: str, root: Path) -> bool:
    """Whether a search kept to `scope` (paths, globs) may read `secret`, a secret file's (or
    folder's) path in the folder. A path is matched against each of its tails - the search may
    run in a folder below (`cd x; rg y tests`) - so a same-named folder elsewhere asks too; one
    out of the folder (`..`, a drive) reaches everything. shortcut: a path with a space, its
    quotes taken off, is read as two; it may then not reach what it does."""
    # (In any case: Windows opens `Config\id_rsa` as `config\id_rsa`.)
    paths, globs = [p.casefold() for p in scope[0]], [g.casefold() for g in scope[1]]
    is_dir = (root / secret).is_dir()
    secret = secret.casefold()
    parts = secret.split("/")
    tails = ["/".join(parts[at:]) for at in range(len(parts))]
    kept = (
        not globs
        or is_dir
        or any(
            fnmatch.fnmatch(tail, glob) or fnmatch.fnmatch(parts[-1], glob)
            for glob in globs
            for tail in tails
        )
    )
    for raw_path in paths:
        if _outside(raw_path):
            return True
        path = posixpath.normpath(raw_path.replace("\\", "/")).strip("/")
        if path in ("", ".") and kept:
            return True
        if kept and any(
            tail == path
            or tail.startswith(path + "/")
            or path.startswith(tail + "/")
            or fnmatch.fnmatch(tail, path)
            or fnmatch.fnmatch(tail, path + "/*")
            for tail in tails
        ):
            return True
    return False


# A variable whose name has one of these parts (split at "_"), or a part that ends in KEY,
# TOKEN or SECRET, holds a secret: its value is hidden in a command's output.
_SECRET_PARTS = frozenset(
    {
        "TOKEN",
        "SECRET",
        "PASSWORD",
        "PASSWD",
        "CREDENTIAL",
        "CREDENTIALS",
        "AUTH",
        "PRIVATE",
        "COOKIE",
        "SESSION",
        "DSN",
    }
)
# Secrets that are known by their shape, wherever they come from.
_TOKENS = re.compile(
    # (`sk-` with a digit in it, and not inside a word: `task-runner-...` is no key)
    r"\b(?:(?<![\w-])sk-(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{20,}"
    r"|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}"
    r"|xox[abposr]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}"
    r"|eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})"
)
_BEARER = re.compile(r"(\bBearer[ \t]+)[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE)
_ADDRESS_PASSWORD = re.compile(r"(://[^\s:/@]*:)[^\s@/]+(@)")  # `redis://:pass@` too
# A private key in PEM: its lines between BEGIN and END (slice 85b).
# shortcut: in a command's output, which is hidden a line at a time, only a key printed whole
# on one line is caught; hold lines between BEGIN and END back if a printed key is seen.
_PEM = re.compile(
    r"(-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----)[\s\S]*?(-----END [A-Z0-9 ]*PRIVATE KEY-----)"
)
# A value given to a name that says it is a secret - `aws_secret_access_key = ...`,
# `"password": "..."`, `api_key: ...` - of MIN_SECRET characters or more (`max_tokens = 4096`
# is no secret).
# The name starts only where a word starts, and is at most 64 characters each side: an
# unbounded `[\w.-]*` tried again from every character took hours on one long line of output.
_ASSIGNED = re.compile(
    r"""((?<![\w.-])["']?[\w.-]{0,64}?(?:password|passwd|pwd|secret|token|api[_-]?key"""
    r"""|access[_-]?key|private[_-]?key|credential)[\w.-]{0,64}["']?[ \t]*[:=][ \t]*["']?)"""
    r"""[^\s"'`,;]{8,}""",
    re.IGNORECASE,
)
# ...but not a variable whose name ends in one of these: it names a place or a kind, and
# an address of it must stay readable (`AUTH_URL=http://localhost:3000`).
# shortcut: a secret kept in such a one (`APP_ID`, `X_URL`) is hidden only by its shape or as
# an address's password; name the variable here if one turns up.
_NOT_SECRET_LAST = frozenset(
    {
        "URL",
        "HOST",
        "HOSTNAME",
        "DOMAIN",
        "PATH",
        "DIR",
        "SOCK",
        "ID",
        "MODE",
        "TYPE",
        "DRIVER",
    }
)
# How much of a line without its end is held back before it is let out anyway.
# shortcut: a secret that straddles this cut, on a line longer than it, is not hidden;
# keep the last secret's length back too if one turns up there.
HELD_AT_MOST = 4096


def secret_name(name: str) -> bool:
    """Whether a variable holds a secret by its name."""
    parts = name.upper().split("_")
    return parts[-1] not in _NOT_SECRET_LAST and any(
        part in _SECRET_PARTS or part.endswith(("KEY", "TOKEN", "SECRET")) for part in parts
    )


def secret_values(env: Mapping[str, str]) -> list[str]:
    """The values in an environment that are secrets by their variable's name."""
    return [
        value
        for name, value in env.items()
        if secret_name(name) and isinstance(value, str) and len(value) >= raw.MIN_SECRET
    ]


# A way into a program the user is signed in to (VS Code, Claude Code, an ssh agent), when
# KOLONİ is started from its terminal: whatever its value, a command reaching it gets the
# user's credential (`$GIT_ASKPASS`, or `git credential fill` over VS Code's IPC handle).
HANDLE = re.compile(r".*ASKPASS.*|.*_IPC_HANDLE|SSH_AUTH_SOCK|.*_NONCE|CLAUDE_CODE_.*|VSCODE_.*")


def _withheld(name: str) -> bool:
    """`secret_name`, narrower, for what a command is not given: a session's name is no
    secret (`WT_SESSION`, `DBUS_SESSION_BUS_ADDRESS`; `AWS_SESSION_TOKEN` is by its TOKEN),
    nor the file or program a secret is in (`*_FILE`, `*_HELPER`, Google's credentials
    path) - but a HANDLE is. shortcut: an address's password (`HTTPS_PROXY=http://user:
    pass@...`) is given on, masked only in what is printed; hold such a variable back if
    one is met."""
    if HANDLE.fullmatch(name.upper()):
        return True
    rest = "_".join(part for part in name.upper().split("_") if part != "SESSION")
    return (
        rest.rsplit("_", 1)[-1] not in ("FILE", "HELPER")
        and rest != "GOOGLE_APPLICATION_CREDENTIALS"
        and secret_name(rest)
    )


def held_back(env: Mapping[str, str], passed: str | None = None) -> list[str]:
    """The names of the secret variables a command is not given (slice 103, `_withheld`):
    all but those the user passes (`Project.pass_env`, comma-separated, in any case) - and
    KOLONİ's own, which no command is given whatever it says."""
    given = {name.strip().upper() for name in (passed or "").split(",")}
    return sorted(
        name
        for name in env
        if _withheld(name) and name.upper() not in given and not name.upper().startswith("KOLONI_")
    )


# shortcut: not base64, hex or any other encoding - a command can print one so; add those
# here if a given secret is ever seen so.
def spellings_of(secrets: Iterable[str]) -> list[str]:
    """Secrets as they are looked for in what is printed or read: as written, as JSON and
    URLs write them, and each line of one too (a key in PEM: output is hidden a line at a
    time)."""
    values = [value for value in secrets if isinstance(value, str)]
    values += [line.strip() for value in values for line in value.splitlines()]
    return raw.spellings([*values, *(quote(value, safe="") for value in values)])


# 101: the variable a turn's planted test key is in - no agent is told of it.
CANARY = "KOLONI_CANARY_KEY"


def sends_canary(text: str, canary: str, command: bool) -> bool:
    """Whether a call's arguments carry a turn's planted test key (101): its value, as output
    is searched for it (`spellings_of`) - and in a command, its variable's name, which the
    shell turns into the value (any case: Windows reads `%koloni_canary_key%` too).
    shortcut: a command that only looks for the name (`grep KOLONI_CANARY_KEY`) stops the turn
    too; match only its expansions if KOLONİ's own code is ever worked on in KOLONİ."""
    return any(one in text for one in spellings_of([canary])) or (
        command and CANARY in text.upper()
    )


_PEM_BEGIN = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
# The samples documentation prints: AWS's example key, jwt.io's example token's signature.
SAMPLE_KEYS = ("AKIAIOSFODNN7EXAMPLE", "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c")


def holds_a_key(line: str) -> bool:
    """Whether a line holds a key by its shape (`_TOKENS`, a private key's first line) that
    is not a well-known sample (`SAMPLE_KEYS`). Not by `_ASSIGNED`: ordinary code (`api_key
    = os.environ[...]`) has that shape; nor a value given on an ask_secret card, which a
    tool's result hides instead (slice 91)."""
    return bool(_PEM_BEGIN.search(line)) or hide_keys(line) != line


def hide_keys(text: str) -> str:
    """Text with the keys `holds_a_key` looks for hidden - not a sample, and not a value
    `_ASSIGNED` would take (`password = getpass()` stays as it is: code is edited from it)."""
    text = _TOKENS.sub(
        lambda found: (
            found.group() if any(sample in found.group() for sample in SAMPLE_KEYS) else raw.HIDDEN
        ),
        text,
    )
    return _PEM.sub(rf"\g<1>\n{raw.HIDDEN}\n\g<2>", text)


class OutputMask:
    """Hides secrets in a command's output before it is shown, kept or given to the model:
    the values it is handed (`spellings_of`), the secrets KOLONİ knows (`raw.hidden`), and
    secrets known by their shape. Line by line: half a line waits for the rest of it, so a
    secret cut between two chunks is hidden too."""

    def __init__(self, secrets: Iterable[str]):
        self._secrets = spellings_of(secrets)
        self._held = ""

    def hide(self, text: str) -> str:
        text = raw.hidden(raw.hide(text, self._secrets))
        text = _TOKENS.sub(raw.HIDDEN, text)
        text = _BEARER.sub(rf"\g<1>{raw.HIDDEN}", text)
        text = _PEM.sub(rf"\g<1>\n{raw.HIDDEN}\n\g<2>", text)
        text = _ASSIGNED.sub(rf"\g<1>{raw.HIDDEN}", text)
        return _ADDRESS_PASSWORD.sub(rf"\g<1>{raw.HIDDEN}\g<2>", text)

    def feed(self, chunk: str) -> str:
        """What of the output so far may go out, hidden: up to its last line end."""
        text = self._held + chunk
        end = max(text.rfind("\n"), text.rfind("\r")) + 1
        if not end and len(text) < HELD_AT_MOST:
            self._held = text
            return ""
        end = end or len(text)
        self._held = text[end:]
        return self.hide(text[:end])

    def peek(self) -> str:
        """What is held back, hidden, without letting it out."""
        return self.hide(self._held) if self._held else ""

    def flush(self) -> str:
        """What is left once the output ended, hidden."""
        held, self._held = self._held, ""
        return self.hide(held) if held else ""


# W2, W6: why a command is asked although a rule matches it - an agent wrote what it runs. No
# rule is offered on its card (Y2): none would cover it while that write stands.
PLANTED = (
    "an agent wrote its program ({place}): no rule covers a program an agent wrote, so none is "
    "offered - run it once or reject it"
)
PLANTED_SAYS = PLANTED.partition("(")[0]


def is_allowed(command: str, prefixes: Iterable[str]) -> bool:
    return any(matches(command, prefix) for prefix in prefixes)


# A terminal's colours, and its links (OSC 8: an address round an address).
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


def plain(output: str) -> str:
    """A command's output as it reads on a screen: its colours and links' codes off (CL-316: a
    coloured `1 passed` is no count where a code stands before its number)."""
    return ANSI.sub("", output)


# K-gecmis-zengin: said beside an output that was cut, or left out of a history to fit - its
# call's id, which recall_output gives the whole of (`AgentRunner._recall_output`).
RECALL_HINT = " (full: recall_output id={id})"


def recallable(
    name: str, outside_folder: str | None, why_asked: str | None, command: str | None
) -> bool:
    """Whether recall_output gives a call's output again (and its id is said): not what the
    memory held then (`memory.looked_up_earlier`), nor what was read on the user's word, for
    that once - outside the project, a secret file, a command that names one."""
    return (
        name != "recall"
        and not outside_folder
        and not (why_asked if command is None else names_secret(command))
    )


def for_model(output: str, call_id: str | None = None) -> str:
    """Command output as the model sees it: whole if short, else its start and end - and, with
    its call's id, where the whole of it is."""
    if len(output) <= MODEL_HEAD + MODEL_TAIL:
        return output
    omitted = len(output) - MODEL_HEAD - MODEL_TAIL
    hint = RECALL_HINT.format(id=call_id) if call_id else ""
    return (
        f"{output[:MODEL_HEAD]}\n[… {omitted} characters omitted …]{hint}\n{output[-MODEL_TAIL:]}"
    )


# What sends work or data off this machine - asked in a job while the user is away (slice 106),
# whatever the chat's level: a word that pushes, publishes, uploads, deploys or mails anywhere in
# it (`npm --prefix x publish`, `docker buildx build --push`; not `git stash push`), a program
# that only moves things elsewhere, and any request from the command line - whatever it asks,
# what it sends is not seen (a GET carries a file in its address as well as a POST in its body).
# shortcut: words and programs, not a sandbox: a script that uploads, or a program not listed
# here, is not seen; add what the user meets.
_SENDING_WORDS = frozenset({"push", "publish", "upload", "deploy", "send-email"})
_SENDING_PROGRAMS = frozenset(
    {
        "scp",
        "sftp",
        "ftp",
        "rsync",
        "rclone",
        "aws",
        "az",
        "gsutil",
        "gcloud",
        "gh",
        "nc",
        "ncat",
        "netcat",
        "socat",
        "kubectl",
        "terraform",
        "helm",
        "vercel",
        "netlify",
        "flyctl",
        "heroku",
        "firebase",
        "send-mailmessage",
        "curl",
        "wget",
        "invoke-webrequest",
        "iwr",
        "invoke-restmethod",
        "irm",
    }
)
# What installs into the dependency folders a working copy shares with the project
# (node_modules, .venv): through the link it writes the project's own.
_INSTALLERS = {
    "pip": {"install", "uninstall", "sync"},
    "pip3": {"install", "uninstall"},
    "uv": {"sync", "add", "remove"},
    "npm": _NPM_INSTALLS,
    "pnpm": {"install", "i", "add", "remove", "update", "up"},
    "yarn": {"install", "add", "remove", "up", "upgrade"},
    "poetry": {"install", "add", "remove", "update"},
    "bun": {"install", "i", "add", "remove"},
}


def sends_off(command: str) -> str:
    """What of a command sends something off this machine, in one sentence; "" for none."""
    return next((said for words in _parts(command) if words and (said := _sends(words))), "")


def _sends(words: list[str]) -> str:
    """`sends_off` for one part of a command."""
    program = _program(words[0])
    said = {w.lower().lstrip("-") for w in words[1:]}
    if program in _SENDING_PROGRAMS:
        return f"It reaches beyond this machine ({program}): what it sends is not seen."
    # (`git stash push` stays, as `reaches_network` has it: it pushes onto its own stash)
    if (found := _SENDING_WORDS & said) and _git_sub(words)[0] != "stash":
        return f"It sends work off this machine ({program} {sorted(found)[0]})."
    return ""


# What on a fetcher's line sends: a body, a file, or a verb other than GET or HEAD. curl's short
# options cluster and are case-sensitive (`-sd x`, `-XPOST`, `-sSfT a`; `-D` only dumps headers).
_CURL_SENDS = re.compile(
    r"(?:^|\s)(?:-[^-\s]*[dTF]|--(?:data|form|upload-file|json)"
    r"|(?:-[^-\s]*X|--request)(?!\s*=?\s*(?:GET|HEAD)\b))"
)
# With `-G` / `--get` curl puts its `-d` data in the address: a GET, unless a file or a verb.
_CURL_GET = re.compile(r"(?:^|\s)(?:-[^-\s]*G|--get\b)")
_CURL_GET_SENDS = re.compile(
    r"(?:^|\s)(?:-[^-\s]*[TF]|--(?:form|upload-file)"
    r"|(?:-[^-\s]*X|--request)(?!\s*=?\s*(?:GET|HEAD)\b))"
)
_WGET_SENDS = re.compile(r"(?:^|\s)--(?:post-|body-|method(?!\s*=?\s*(?:GET|HEAD)\b))", re.I)
_PS_SENDS = re.compile(
    r"(?:^|\s)-(?:body|infile|form|(?:custom)?method(?![:\s]*(?:get|head)\b))", re.I
)
_FETCHERS = {
    "curl": _CURL_SENDS,
    "wget": _WGET_SENDS,
    "invoke-webrequest": _PS_SENDS,
    "iwr": _PS_SENDS,
    "invoke-restmethod": _PS_SENDS,
    "irm": _PS_SENDS,
}
# Security review 0.1.0: long options are spelt out before those read a line, as the programs
# take one cut short (`-InF`, `-Me Post`, `--meth`, `--upload-f`): to the first name it starts
# (an ambiguous one the program refuses, so that only over-asks).
_SPELT = {
    "curl": (
        "--",
        (
            "data",
            "data-ascii",
            "data-binary",
            "data-raw",
            "data-urlencode",
            "form",
            "form-string",
            "upload-file",
            "json",
            "request",
            "get",
        ),
    ),
    "wget": ("--", ("post-data", "post-file", "body-data", "body-file", "method")),
    **dict.fromkeys(_PS_FETCHERS, ("-", ("infile", "body", "form", "method", "custommethod"))),
}


def _spelt(word: str, dash: str, names: tuple[str, ...]) -> str:
    """A long option cut short, spelt out (`-InF:x` is `-infile:x`); any other word as it is."""
    found = re.match(r"-+([A-Za-z][\w-]*)(.*)", word, re.S) if word.startswith(dash) else None
    full = found and next((name for name in names if name.startswith(found[1].casefold())), None)
    return f"{dash}{full}{found[2]}" if found and full else word


_GH_READS = frozenset(
    {
        "list",
        "view",
        "status",
        "api",
        "checkout",
        "diff",
        "checks",
        "clone",
        "download",
        "search",
        "browse",
    }
)
# (a short option's value may be attached: `-XPOST`, `-fa=b`)
_GH_SENDS = re.compile(r"(?:^|\s)(?:-[XfF]|--(?:method|field|raw-field|input)\b)")


def _only_fetches(words: list[str]) -> bool:
    """Whether one part of a command, of a program that reaches the network, only fetches: curl,
    wget or Invoke-WebRequest/RestMethod with nothing on the line that sends, `gh` with a read
    subcommand (`gh pr list`, `gh api` with nothing to send). K-fullauto-sorma: a watched Full
    auto turn does not ask about one (`harms`); a job while the user is away asks about any
    (`sends_off`). shortcut: what a config file (`curl -K`, `--config`) or a variable makes it
    send is not seen; look inside if a POST gets through one."""
    program = _program(words[0])
    line = " ".join(
        _spelt(word, *_SPELT[program]) if program in _SPELT else word for word in words[1:]
    )
    if program == "curl" and _CURL_GET.search(line):
        return not _CURL_GET_SENDS.search(line)
    if program in _FETCHERS:
        return not _FETCHERS[program].search(line)
    if program == "gh":
        said = [w for w in words[1:] if not w.startswith("-")]
        if not said:  # (`gh --version`, `gh -h`: nothing to send)
            return True
        verb = said[0] if len(said) == 1 or said[0] in ("api", "search") else said[1]
        return verb in _GH_READS and not _GH_SENDS.search(line)
    return False


def harms(command: str, instructions: bool = True) -> str:
    """What of a command cannot be taken back - it deletes or overwrites (`danger`), or sends
    something off this machine (`sends_off`, but for a line that only fetches: `_only_fetches`)
    - in one sentence; "" for none; what a shell or a wrapper is handed is looked at too
    (`_commands_in`: `cmd /c "git push"`, `sh -c 'rm -rf x'`). K-fullauto-sorma: the user's
    rule is that Full auto asks about nothing but harm, so this is asked at every level in a
    watched turn as in a job while the user is away, and no rule is offered for it; there an
    instruction file alone is no harm (`instructions` False, `standing_asked`).
    shortcut: `robocopy /MIR`, `mail` / `sendmail` and `ssh host 'cmd'` are in neither `danger`
    nor `sends_off` today; add them there when the user meets one. shortcut: a shell nested in
    a shell with escaped quotes (`cmd /c "powershell -c \\"git push\\""`) is not looked into
    (`_commands_in` opens one quoted level; a night job still asks through `runs_another`).
    shortcut: at Full auto this check is a courtesy for honest commands, not a wall against
    obfuscation - a name spliced or escaped (`r`i`, `& (gcm ri)`, `&('r'+'i')`, `$c='ri'; & $c`)
    or a program started with its words in a list (`Start-Process ... -ArgumentList`) is not
    seen; Ask and Auto-edit are the wall (and `runs_another` at night).
    shortcut (security review of K-yargic): no harm is seen in `powershell -enc <base64>`,
    `ssh host 'rm -rf /'`, `find . -exec rm {} ;` or `python -c "shutil.rmtree('..')"` - they run
    at Full auto as before, and are never put to the check of the user's words (no harm, no
    check); add them to `danger` / `sends_off` when the user meets one. A continued line is read
    joined too (`_readings`)."""
    return next(
        filter(
            None, (said for line in _readings(command) for said in _reasons(line, instructions))
        ),
        "",
    )


def _reasons(command: str, instructions: bool) -> Iterator[str]:
    """`harms`'s sentences in its order: `danger` of the whole line, then of each part."""
    # (Its parts apart, but for a leading `cd` into the scratch - `_ENTERS`, judged above with
    # the whole line: alone it would name `.koloni`.)
    entered = _ENTERS.match(command)
    yield danger(command, instructions)
    # (A part's stop is judged with its line: the line may have started what it stops.)
    stops = _stops_by_name(command)
    for words in _commands_in(command[entered.end() if entered else 0 :], at=_BLOCKS):
        if words and (said := danger(" ".join(words), instructions)) == KILLS_BY_NAME:
            yield said if stops else ""
        elif words:
            yield said or ("" if _only_fetches(words) else _sends(words))


HarmClass = Literal["", "soft", "always"]
# K-yargic: what a check of the user's own words may let run - any other sentence (one added
# later too) is asked as before.
_SOFT = re.compile(
    r"(?:Deletes|Empties|Overwrites or deletes|Throws away|Stops programs by their"
    r" name|It reaches beyond this machine|It sends work off this machine)\b"
)


def harm_class(command: str, instructions: bool = True) -> HarmClass:
    """K-yargic: whether a harm (`harms`) is one a check of the user's own words may let run
    ("soft": each part only deletes, throws away, stops programs by name or sends off, `_SOFT`;
    from a copy stopping by name is asked at every level, `copy_reason`) or one asked at every
    level ("always": any other sentence, a secret, `.koloni`, a file that steers later turns, a
    path out of the folder, a line handed to another program); "" for no harm. Every part is
    looked at, not the first sentence `harms` gives: `rm -rf build && cat .env` deletes first,
    and opens a secret too. A continued line is read joined too (`_readings`): the higher."""
    classes = [_harm_class(line, instructions) for line in _readings(command)]
    return "always" if "always" in classes else "soft" if "soft" in classes else ""


def _harm_class(command: str, instructions: bool) -> HarmClass:
    harmful = False
    for said in _reasons(command, instructions):
        if said and not _SOFT.match(said):
            return "always"  # (at once: a line padded with options says so first)
        harmful = harmful or bool(said)
    if not harmful:
        return ""
    return "always" if _asked_anyway(command, instructions) else "soft"


def _asked_anyway(command: str, instructions: bool) -> bool:
    """`harm_class`: what makes a harm one asked at every level - a secret (named after an `@`
    too: `-F f=@id_rsa`), `.koloni`, a file that steers later turns, a line handed to another
    program (`runs_another`: a variable set before it, `xargs`, `sudo`, a shell), a path out of
    the folder in any word of the line, its program's own too (`_leads_out`), a glob on a
    dot-name (`.k*`, `.[k]oloni`, `.env*`), a harm over all of the folder (`_sweeps`), or a stop
    of what may be KOLONİ itself (`_stops_koloni`)."""
    words = re.split(
        r"[\s;&|(){}]+", _TASKKILL.sub(lambda part: _SWITCH.sub(" ", part[0]), command)
    )
    return bool(
        names_secret(command)
        or names_secret(_as_read(command).replace("@", " "))
        or names_koloni(command)
        or standing_asked(command, instructions)
        or runs_another(command)
        or _stops_koloni(command)
        or any(map(_leads_out, words))
        or any(_DOT_GLOB.search(_as_read(word)) for word in words)
        or _sweeps(command)
    )


# A glob or a bracket on a name that starts with a dot: it may reach `.git`, `.koloni` or a secret.
_DOT_GLOB = re.compile(r"(?:^|[\\/=@,:])\.[^\\/]*[*?\[]")
# A part of a line taskkill runs, and its switches (`/IM`, `/F`, Git Bash's `//PID`): no path out
# of the folder (`_asked_anyway`). Only as a part's program: `rm -rf taskkill /etc` keeps `/etc`.
_TASKKILL = re.compile(
    r"(?i)(?:^|(?<=[;&|(){}\r\n]))\s*taskkill(?:\.exe)?(?![\w.-])[^;&|(){}\r\n]*"
)
_SWITCH = re.compile(r"(?<!\S)/{1,2}[A-Za-z]+(?::\S*)?(?!\S)")  # (`/IM:x.exe` too)


def _sweeps(command: str) -> bool:
    """`_asked_anyway`: a part of a harmful line that reaches all of the folder - `.git` and
    `.koloni` with it: a delete or a revert of the folder itself or all in it (`.`, `*`,
    `sub/..`; `git checkout .` takes back a change to `.koloni/rules.md` too), or of a
    line that sends, any part but git's (`git add .` is no send of the folder) that takes it
    (`scp -r .`, `zip -r x.zip . && curl ...`); git told what to run (`-c`, `--config-env`), or
    `git clean` of the ignored files too (`-x`, `-X`)."""
    parts = [words for words in _commands_in(command, at=_BLOCKS) if words]
    sends = any(_sends(words) for words in parts)
    for words in parts:
        git = _program(words[0]) == "git"
        if git and (
            any(word == "-c" or word.startswith("--config-env") for word in words)
            or (
                _git_sub(words)[0] == "clean"
                and any(_cluster(word, "x") or _cluster(word, "X") for word in words[2:])
            )
        ):
            return True
        if any(map(_whole, words[1:])) and (
            _danger_of(words).startswith(("Deletes", "Throws away")) or sends and not git
        ):
            return True
    return False


def _whole(word: str) -> bool:
    """`_sweeps`: whether a word names the folder itself, or all in it: `.`, `./`, `*`,
    `sub/..`, a word of wildcards and dots alone (PowerShell's `*.*` or `?*` with -Force takes
    `.git` too) - also as an option's value (`-Path:.`)."""
    # (Windows' `\` made `/` before quotes are taken off: `_as_read` drops a `\` before a dot.)
    plain = _as_read(re.sub(r"^-[\w-]*[:=]", "", word).replace("\\", "/"))
    whole = posixpath.normpath(plain) if plain else ""
    return not plain.startswith("-") and (
        whole == "." or bool(re.fullmatch(r"[.*?]*[*?][.*?]*", whole))
    )


def _leads_out(word: str) -> bool:
    """`_asked_anyway`: whether a word names a path out of the folder (`_outside`) - also glued
    to an option (`-Path:C:/x`, `--dir=../x`), a redirection or an `@` (`-d@/etc/passwd`,
    `file=@C:/x`) - or one whose place is not seen: behind a variable (`$HOME`, `%USERPROFILE%`),
    a command's output (`` `pwd` ``) or a brace."""
    plain = _as_read(word)
    # (and the word as written: `_as_read` drops the `\` of Windows' `build\..\..`)
    return (
        bool(re.search(r"[$%`{}]", word))
        or _outside(word.strip("'\""))
        or any(
            _outside(piece)
            for piece in re.split(r"[=<>,@]", re.sub(r"^-[\w-]*:", "", plain))
            if piece
        )
    )


# K-r147 (live): what a pipe may hand a command's output to, at night too - it only picks,
# counts, sorts or lays out the text, and runs nothing it is handed (`_filters`).
_FILTERS = _SINKS | {
    "where-object",
    "where",
    "?",
    "head",
    "tail",
    "grep",
    "egrep",
    "fgrep",
    "findstr",
    "wc",
    "more",
}
_TEE_FLAGS = frozenset({"-a", "--append", "-append", "-i", "-p", "-filepath", "-literalpath"})
# A stream joined to another (`2>&1`, `*>&1`): no `&` that runs a command.
_JOINED = re.compile(r"[\d*]?>&\d(?![\w.])")
# PowerShell's call operator on a value worked out on the line (`& (gcm cmd)`, `& $c`).
_CALLED = re.compile(r"(?<![&>])&(?!&)\s*[($]")
ANOTHER = "It runs another command through a shell or a wrapper: what runs is not seen."


def _filters(stage: str) -> bool:
    """A pipe's later stage that only shapes the text it is handed: one of `_FILTERS` by its bare
    name (not a path: one the agent wrote), or a Format-*; `sort` but with `-o`/`/o`, which write
    a file, `--co` (GNU's `--compress-program` cut short: live, it ran a script) or `-T`, its
    temporary folder; `tee` only into the agents' scratch (`_IN_SCRATCH`) or nowhere. Nothing in
    it that could run code: a block, a bracket, a variable, a splat, an input redirect or an
    escape."""
    words = _words(stage.strip())
    if not words or re.search(r"[{}()$@<`]", stage) or re.search(r"[\\/'\"]", words[0]):
        return False
    program, said = _program(words[0]), [word.strip("'\"") for word in words[1:]]
    rest = [word.casefold() for word in said]
    if program == "sort":  # (case kept: `-t,` is a field separator, `-T` a folder)
        return not any(
            _cluster(word, "o")
            or _cluster(word, "T")
            or word.casefold().startswith(("--o", "/o", "--co", "--t"))
            for word in said
        )
    if program == "tee":
        return all(word in _TEE_FLAGS or _IN_SCRATCH.fullmatch(word) for word in rest)
    return program in _FILTERS or program.startswith("format-")


def runs_another(command: str) -> str:
    """Why a command runs what cannot be looked at here: a part of it hands its rest to a
    shell or a word that runs another command (`cmd /c`, `bash -c`, `env`, `sudo`, `timeout
    60`, `VAR=1 cmd`), or a pipe hands its output to anything but a filter (`_filters`: not `|
    python`, `| iex`, `| xargs`, `| ForEach-Object {...}`) - or to any stage at all in a line
    that renames a command (`_RENAMES`: `sal grep cmd; ls | grep /c x`); "" for none. K-r147
    (live: agents run their tests as `python -m unittest 2>&1 | Select-Object -Last 20`).
    A shell handed a script stays a shell (`pwsh -c "git push" origin`: pwsh joins every word
    after `-c` into its script, so what runs is not what the quotes show).
    shortcut: a `|` in quotes (`Select-String "a|b"`) splits the pipe there, so such a line
    asks; split outside quotes if that is met at night.
    shortcut: not this slice's - `taskkill`, `reg add` and `py -m pip` are in no rule here, and
    a name renamed and then run outside a pipe (`Set-Alias` splicing) is not seen; add them
    where the user meets one."""
    renames = bool(_RENAMES.search(command))
    if _CALLED.search(_JOINED.sub(" ", command)):
        return ANOTHER
    for part in _CHAIN.split(_JOINED.sub(" ", command)):
        first, *stages = part.split("|")
        if (
            is_wrapped(first)
            or _in_a_shell(first)
            or stages
            and (renames or not all(map(_filters, stages)))
            or any(  # (in a block: `(cmd /c x)`)
                is_wrapped(piece) or _in_a_shell(piece) or _runs_a_shell(piece)
                for piece in _BLOCKS.split(part)
            )
        ):
            return ANOTHER
    return ""


def _runs_a_shell(piece: str) -> bool:
    """Whether a runner hands a shell or a wrapper a line (`poetry run cmd /c x`, `uv run env x`:
    `_runner_lines`)."""
    words = _words(piece.strip())
    return bool(words) and any(
        is_wrapped(line) or _in_a_shell(line)
        for line in _runner_lines([word.strip("'\"") for word in words])
    )


# K-r135: an interpreter handed its code on the line, quoted or not (`python -c "..."`, `node
# -e`, `ruby -e`, `perl -e`, `deno eval`) - by the program's name, its path too, as
# `_INLINE_CODE` finds it (not `deploy.py -c`, `pytest -c x.ini`). A shell's `-Command` is
# `runs_another`'s. shortcut: a script the agent itself wrote runs unasked in a backlog turn;
# card interpreters running a just-written file if that is seen live.
_INLINE = re.compile(
    r"""(?i)(?:^|(?<=[\s;&|('"]))(?:\S*[\\/])?(?:(?:python|py|node|ruby|perl|php|bun|lua\w*|r|"""
    r"""rscript|julia)[\d.]*w?(?:\.exe)?\s+(?:-\w+\s+)*?(?:-c|-e|-p|--eval|--print)"""
    r"""|php[\d.]*(?:\.exe)?\s+(?:-\w+\s+)*?-r|deno(?:\.exe)?\s+eval)(?=\s|$)"""
)


def runs_inline(command: str) -> str:
    """Why a command runs code written on its line (`_INLINE`), in one sentence; "" for none -
    in any reading (`_readings`: `python `⏎`-c "x"` too, k-okuyucu)."""
    return (
        "It runs code written on the line: what it does is not seen."
        if any(map(_INLINE.search, _readings(command)))
        else ""
    )


def _module_run(words: list[str]) -> list[str]:
    """What an interpreter runs as a module (`python -I -m pip install x`, `py -m pip`): its words
    from the module's name on, the module as the program; [] for another line."""
    program, at = _program(words[0]), 1
    if not (program == "py" or program.startswith("python")):
        return []
    while at < len(words) and words[at].startswith("-") and words[at] != "-m":
        at += 2 if words[at] in ("-X", "-W", "--check-hash-based-pycs") else 1  # (with a value)
    return words[at + 1 :] if words[at : at + 1] == ["-m"] else []


def installs(command: str) -> str:
    """Whether a part of a command installs or removes packages, in one sentence; "" for none:
    one of `_INSTALLERS`' verbs as its verb, past the options before it (`_verbs`: `npm --prefix
    web install x`, `pnpm -C web i`, `uv pip install`), by a program starting with `pip` (pip3.12,
    pipenv) or run as a module (`python -X utf8 -m pip install`, `py -m pip`), a bare `yarn` -
    and in what a shell or a wrapper is handed (`cmd /c "npm i x"`) or a runner (`uv run pip
    install x`, `npm exec --yes -- npm ci`). A script run by its name (`npm run install`) is
    none; a dry run is one (review round 4: `pip install x # --dry-run` installs). A runner that
    downloads a package to run it is one too (`_fetches_to_run`: K-okuyucu-3).
    shortcut: `pip-sync` and `corepack` writing into node_modules / .venv are not seen, nor an
    install word `_INSTALLERS` does not list (`pnpm import`, `pnpm fetch`, `poetry sync`, `pdm
    add`, `conda install`); 0.1.6 (review round 4)."""
    for words in (words for line in _readings(command) for words in _commands_in(line) if words):
        if _installs_part(words):
            return (
                "It installs or removes packages: in a working copy its dependency folders "
                "are the project's own, linked in."
            )
        if _fetches_to_run(words):
            return (
                "It downloads a package and runs it (npx -p, uvx, dlx): what runs comes from "
                "the internet, not from the project."
            )
    return ""


def _installs_part(words: list[str]) -> bool:
    """`installs` of one part's words."""
    return words == ["yarn"] or any(
        verb == UNREAD
        or verb.casefold()
        in (_INSTALLERS["pip"] if program.startswith("pip") else _INSTALLERS.get(program, set()))
        for program, verb in _verbs(words)
    )


# K-okuyucu-3: what downloads a package to run it - an install by another name, from the internet:
# `uvx x`, `bunx x`, `pnpx x`; `pnpm dlx`, `yarn dlx`, `pipx run`, `bun x`, `uv tool run`; `npm`
# / `yarn` / `pnpm` / `bun create x`, `npm init x` (create-x), `corepack pnpm dlx x`; `npx` given
# `-p` / `--package` before what it runs, `npm exec` given `--package` anywhere before `--`, `uv
# run` given `--with` / `-w`; `deno run npm:x` / `jsr:x`; `go run <module>@<version>`.
# shortcut: a bare `npx <bin>` / `npx -y <bin>` / `npm exec <bin>` runs the project's own bin
# where it has one, and is left as before - one not installed it downloads all the same; card it
# if agents fetch so.
_FETCH_RUNNERS = frozenset({"uvx", "bunx", "pnpx"})
_FETCH_VERBS = frozenset(
    {
        ("pnpm", "dlx"),
        ("yarn", "dlx"),
        ("pipx", "run"),
        ("bun", "x"),
        ("npm", "create"),
        ("yarn", "create"),
        ("pnpm", "create"),
        ("bun", "create"),
    }
)
# npx's options that take a value (npm 11's): any other is a flag. It reads its own only before
# what it runs - `npx tsc -p x` is tsc's `-p`.
_NPX_VALUES = frozenset(
    {
        "-p",
        "--package",
        "-c",
        "--call",
        "-w",
        "--workspace",
        "--cache",
        "--registry",
        "--prefix",
        "--userconfig",
        "--node-options",
        "--loglevel",
    }
)
_MODULE_AT = re.compile(r"[\w.-]+(?:/[\w.~-]+)+@\S+")  # (`golang.org/x/tools/cmd/x@latest`)


def _fetches_to_run(words: list[str]) -> bool:
    """Whether one part's words download a package to run it (`_FETCH_RUNNERS`, `_FETCH_VERBS`)."""
    words = _module_run(words) or words
    program, said = _program(words[0]), [word.casefold() for word in words[1:]]
    if program == "corepack" and said:  # (the package manager it runs, fetched first)
        return _fetches_to_run(words[1:])
    verbs = {(name, verb.casefold()) for name, verb in _verbs(words)}
    after = {verb: said[said.index(verb) + 1 :] for _name, verb in verbs if verb in said}
    if (
        program in _FETCH_RUNNERS
        and said
        or verbs & _FETCH_VERBS
        or ("uv", "tool") in verbs
        and "run" in said
        or ("npm", "init") in verbs
        and any(not w.startswith("-") for w in after["init"])
        or program == "deno"
        and any(w.startswith(("npm:", "jsr:")) for w in said)
        or ("go", "run") in verbs
        and any(map(_MODULE_AT.fullmatch, after["run"]))
    ):
        return True
    if program == "npx":
        package = _npx_options(words[1:])
    else:  # (npm exec reads `--package` anywhere before `--`: `npm exec x --package=y`; its `-p`
        # is npm's --parseable, `npm exec tsc -p x` tsc's)
        package = [
            w
            for verb in ("exec", "x")
            if ("npm", verb) in verbs
            for w in after[verb][: (after[verb] + ["--"]).index("--")]
            if w != "-p"
        ]
    with_ = _runner_options(words[said.index("run") + 2 :]) if ("uv", "run") in verbs else []
    return any(
        word in ("-p", "--package") or word.startswith("--package=") for word in package
    ) or any(word.startswith(("--with", "-w")) for word in with_)


def _npx_options(rest: list[str]) -> list[str]:
    """npx's own options: its words before what it runs, a value after one of `_NPX_VALUES`."""
    found, at = [], 0
    while at < len(rest) and rest[at].startswith("-") and rest[at] != "--":
        found.append(rest[at])
        at += 2 if rest[at] in _NPX_VALUES else 1
    return found


def _runner_options(rest: list[str]) -> list[str]:
    """uv run's own options - its words before what it runs: a word after an option with no `=`
    may be its value, so it reads on past it (fails closed); `--` ends them."""
    found = []
    for at, word in enumerate(rest):
        if word == "--":
            break
        if word.startswith("-"):
            found.append(word)
        elif not (at and rest[at - 1].startswith("-") and "=" not in rest[at - 1]):
            break
    return found


# What reaches the internet from a command (K-web-komut): `_SENDING_PROGRAMS` and these, as
# whole words anywhere in the line - inside `powershell -Command "..."` too, but not as a part
# of a path or a file's name (`tests/aws/x.py`, `docs/curl.md`) - by a program's path where a
# part runs it (`C:\Windows\System32\curl.exe`), .NET's web classes, or an address.
# shortcut: words, not a parser or a sandbox: a script that fetches, an alias, a variable or an
# encoded command is not seen; `curl localhost`, `pip uninstall`, `git submodule status` and a
# word in a message (`git commit -m "nc"`) are carded too. The real cut is Docker's `--network
# none`, or K-yazma-denetimi's research for this machine.
_NET_PROGRAMS = _SENDING_PROGRAMS | {
    "ssh",
    "telnet",
    "start-bitstransfer",
    "test-netconnection",
    "tnc",
    "winget",
    "choco",
    "scoop",
    "install-module",
    "install-package",
    "save-module",
}
_NETWORK = re.compile(
    r"(?<![\w\\/-])(?:"
    + "|".join(map(re.escape, sorted(_NET_PROGRAMS, key=len, reverse=True)))
    + r")(?![\w\\/-]|\.(?!exe\b)\w)"
    r"|\bnet\.(?:webclient|httpwebrequest|webrequest|http|sockets)\b"
    r"|\b(?:https?|ftp)://[^\s'\"`]*",
    re.IGNORECASE,
)
_GIT_REACHES = frozenset({"clone", "fetch", "pull", "push", "ls-remote", "submodule", "lfs"})
# Windows' own tools that download only with these switches (`certutil -hashfile` stays).
_DOWNLOAD_SWITCHES = {"certutil": {"urlcache", "verifyctl"}, "bitsadmin": {"transfer", "addfile"}}
WEB_OFF = (
    "web is off on the Tools page ({tool} is off); this command reaches the internet: "
    "{what} - asked at every level"
)


def _commands_in(
    command: str, left: list[int] | None = None, at: re.Pattern = _PARTS
) -> list[list[str]]:
    """Each part's words (split `at`; `_BLOCKS` where harm is judged), and of a part that hands
    a shell or a wrapper its rest, the command it is handed (`cmd /c "pip install x"`,
    `powershell -Command 'git clone x'`). Past MAX_OTHER_READINGS readings of the whole line
    beyond each part's first (`left`, shared with the lines looked into: `env
    --split-string='env --split-string=...` doubles them at each one), [UNREAD]."""
    left = [MAX_OTHER_READINGS] if left is None else left
    found = []
    for words in _parts(command, at):
        for number, handed in enumerate(_unwrapped(words)):
            if number:
                if left[0] <= 0:
                    return [*found, [UNREAD]]
                left[0] -= 1
            if len(handed) == 1 and " " in handed[0] and len(handed) < len(words):
                found += _commands_in(handed[0], left, at)  # (handed as one quoted line)
            elif handed != words and (led := _led(handed)) != handed:  # (`cmd /c if exist x ...`)
                found += _commands_in(
                    " ".join(f'"{word}"' if re.search(r"\s", word) else word for word in led),
                    left,
                    at,
                )
            else:
                found.append(handed)
    return found


def reaches_network(command: str) -> str:
    """What in a command reaches the internet - a program, an address, a git fetch, a package
    install or download, or a word that publishes (`npm publish`, `docker push`); "" for none.
    A package manager's part reaches it where any of its words is an install verb of its own
    (`_reaches_by_word`: no carve-out - `pip install --dry-run x` resolves from the index too).
    A continued line is read as `_readings` reads it."""
    return next((found for line in _readings(command) if (found := _reaches_of(line))), "")


def _reaches_by_word(words: list[str]) -> bool:
    """`reaches_network`: whether a package manager's part holds one of its install verbs
    anywhere (`uv pip compile`, `npm run install`, `pip show install`: over-asks, never fewer)."""
    words = _module_run(words) or words
    program = _program(words[0])
    verbs = _INSTALLERS["pip"] if program.startswith("pip") else _INSTALLERS.get(program, set())
    return any(word.casefold() in verbs or program == "uv" and word == "pip" for word in words[1:])


def _reaches_of(command: str) -> str:
    if found := _NETWORK.search(command):
        return found[0]
    for words in (words for words in _commands_in(command) if words):
        program, sub = _program(words[0]), _git_sub(words)[0]
        said = {word.lower().lstrip("-") for word in words[1:]}
        if program in _NET_PROGRAMS or _DOWNLOAD_SWITCHES.get(program, set()) & {
            word.lower().lstrip("-/") for word in words[1:]
        }:
            return program
        if sub in _GIT_REACHES:
            return f"git {sub}"
        # (an install of the part as a line - its quoted words kept: `git commit -m "run (npm
        # ci) first"` - and of its words split at their spaces: `"pip install" x`)
        quoted = " ".join(f'"{word}"' if re.search(r"\s", word) else word for word in words)
        split = " ".join(words).split()
        if (
            installs(quoted)
            or split
            and _installs_part(split)
            or _reaches_by_word(words)
            or program in ("pip", "pip3")
            and "download" in said
        ):
            return "a package install"
        if (sending := _SENDING_WORDS & said) and sub != "stash":  # (`git stash push` stays)
            return f"{program} {sorted(sending)[0]}"
    return ""


def web_off_reason(command: str, off: Iterable[str]) -> str:
    """Why a command is asked at every level, Full auto too, and refused where nobody watches:
    a web tool is off on the Tools page (either: a command can search or fetch) and it reaches
    the internet; "" while both are on, or for one that does not."""
    tool = next((name for name in ("http_request", "web_search") if name in off), None)
    what = reaches_network(command) if tool else ""
    return WEB_OFF.format(tool=tool, what=what) if what else ""


# Coordination §4: the deletes KOLONİ can check by itself, where the user allowed them in the
# project (`Project.disposable_deletes`) - a build or cache folder, a worktree, a branch. Read
# from a line this plain only: words of ASCII letters, digits and `_ . / -`, one space between
# them - no quote, backslash, drive, comment, splat, variable, wildcard or other space a shell
# reads past a plain word - and no option that is not read here.
DISPOSABLE_NAMES = frozenset(
    {
        "build",
        "dist",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "coverage",
        ".next",
        ".turbo",
        "target",
    }
)
_DISPOSABLE_LINE = re.compile(r"[A-Za-z0-9_./-]+(?: [A-Za-z0-9_./-]+)*")
# The shells a folder's delete is read for (`disposable_targets`' `shell`): KOLONİ's own command
# runs in PowerShell on Windows and in sh elsewhere and in Docker (`executors.host.shell_argv`); a
# CLI's, in the one it says (`disposable.cli_shell`). Each its own forms, as each reads them -
# measured in Windows PowerShell 5.1 (22 Nov 2026): Remove-Item and its aliases, `-r` its
# -Recurse, `-fo` its -Force, one path (`-rf`, `-f` and a second path are errors, nothing
# deleted); sh's rm by its own name and options, as many paths as it is given.
POWERSHELL, POSIX = "powershell", "posix"
_DELETE_FORMS = {  # (its deleters, its recursions, its other flags, its forcings, most paths)
    POWERSHELL: (
        frozenset({"remove-item", "ri", "rm", "del", "erase"}),
        frozenset({"-recurse", "-r"}),
        frozenset({"-force", "-fo", "-path", "-literalpath"}),
        frozenset({"-force", "-fo"}),
        1,
    ),
    POSIX: (
        frozenset({"rm"}),
        frozenset({"-r", "-R", "-rf", "-fr", "-Rf", "-fR"}),
        frozenset({"-f", "--force"}),
        frozenset({"-f", "--force", "-rf", "-fr", "-Rf", "-fR"}),
        None,
    ),
}


def disposable_targets(command: str, shell: str | None) -> list[tuple[str, str, bool]] | None:
    """What a line deletes where it is nothing but a delete KOLONİ can check: ("folder", its
    path, forced) for each build or cache folder of the `shell`'s own recursive delete (`rm -r`
    in sh, `Remove-Item -Recurse` in PowerShell; a shell not known: none); ("worktree", its path,
    False) for `git worktree remove <path>`; ("branch", its name, forced) for each of `git branch
    -d|-D` (git's, every shell's alike). None for any other line. What it names only: whether
    each is disposable is for the checks of its folder."""
    if not _DISPOSABLE_LINE.fullmatch(command):
        return None
    words = command.split(" ")
    if words[0] == "git":
        return _worktree_target(words[1:]) or _branch_targets(words[1:])
    return _folder_targets(words, shell)


def _plain_name(part: str) -> bool:
    """A path's or a branch's part as every shell and file system reads it: not empty, no
    dot-name, nothing Windows opens as another (`node_modules.` is `node_modules`)."""
    return bool(part) and not part.startswith(".") and not part.endswith(".")


def _folder_targets(words: list[str], shell: str | None) -> list[tuple[str, str, bool]] | None:
    """A bare deleter's recursive delete of build or cache folders below where it runs, in the
    shell's own form (PowerShell's names and options in any case, sh's as spelt; no trailing
    slash: `build/` is where a link named build leads)."""
    if shell not in _DELETE_FORMS:
        return None
    deleters, recursions, others, forcings, most = _DELETE_FORMS[shell]
    read = str.casefold if shell == POWERSHELL else str
    flags = {read(word) for word in words[1:] if word.startswith("-")}
    paths = [word for word in words[1:] if not word.startswith("-")]
    if (
        read(words[0]) not in deleters
        or not paths
        or not flags & recursions
        or not flags <= recursions | others
        or most is not None
        and len(paths) > most
    ):
        return None
    for path in paths:
        *above, name = path.split("/")
        if name not in DISPOSABLE_NAMES or not all(
            _plain_name(part) and part.casefold() not in LINKED for part in above
        ):
            return None
    return [("folder", path, bool(flags & forcings)) for path in paths]


def _worktree_target(rest: list[str]) -> list[tuple[str, str, bool]] | None:
    """`git worktree remove <path>` alone - never forced; up and absolute paths too (a
    worktree is registered where it is)."""
    if len(rest) != 3 or rest[:2] != ["worktree", "remove"] or rest[2].startswith("-"):
        return None
    parts = rest[2].split("/")
    if all(
        part == ".." or _plain_name(part) and part.casefold() not in LINKED
        for part in (parts if parts[0] else parts[1:])
    ):  # (`/x/wt`: from the root)
        return [("worktree", rest[2], False)]
    return None


def _branch_targets(rest: list[str]) -> list[tuple[str, str, bool]] | None:
    """`git branch -d|-D <name>...`: none of KOLONİ's own (`koloni/…` - Windows and macOS find
    `Koloni/x`'s ref file as `koloni/x`'s)."""
    if len(rest) < 3 or rest[0] != "branch" or rest[1] not in ("-d", "-D"):
        return None
    for name in rest[2:]:
        parts = name.split("/")
        if (
            name.startswith("-")
            or parts[0].casefold() == "koloni"
            or not all(map(_plain_name, parts))
        ):
            return None
    return [("branch", name, rest[1] == "-D") for name in rest[2:]]
