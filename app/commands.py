"""Rules about shell commands: allow-list matching and what the model gets to see."""

import contextlib
import fnmatch
import os
import posixpath
import re
import shlex
import sys
import time
from collections.abc import Iterable, Mapping
from pathlib import Path, PureWindowsPath
from urllib.parse import quote

from sqlalchemy import or_, select

from app import raw
from app.copies import LINKED
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
_SUBCOMMAND_TOOLS = frozenset({
    "git", "npm", "pnpm", "yarn", "uv", "pip", "cargo", "dotnet", "docker", "go",
})
# ...and those where the task is one word further on: `npm run build`, `uv run pytest`.
_RUNNERS = frozenset({("npm", "run"), ("pnpm", "run"), ("yarn", "run"), ("uv", "run")})
_RUNNER_PROGRAMS = frozenset({"npx", "pnpx", "uvx", "bunx"})
# ...and subcommands that do the same: a rule must name the package (`uv tool run x`: one
# word further on).
_EXECUTORS = {
    ("npm", "exec"): 3, ("npm", "x"): 3, ("pnpm", "dlx"): 3, ("pnpm", "exec"): 3,
    ("yarn", "dlx"): 3, ("yarn", "exec"): 3, ("uv", "tool"): 4,
}
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
    # (`npm.cmd ci` is npm's: a shim's name is the program's)
    # shortcut: a bare `cat.cmd a.py` reads as cat; PowerShell and bash find a bare name on PATH
    # only, but cmd.exe looks in cwd first - judge a bare .cmd/.bat as the folder's own if a CLI
    # is seen to run its commands through cmd.exe.
    return name.removesuffix(".exe").removesuffix(".cmd").removesuffix(".bat")


def suggest_prefix(command: str) -> str:  # noqa: C901
    """The allow-list rule to offer for a command, or "" when none should be offered.

    A rule names one program and one task. Nothing is offered where the shortest
    honest rule would still mean "run anything": shells, interpreters given inline
    code, or commands that use shell syntax - nor where it deletes, cannot be undone or
    sends something off this machine (`harms`: asked at every level, a rule would be a lie).
    """
    # shortcut: such a rule can still be written by hand (`tidy_rule`) and serves a trigger's
    # exact match (`is_exactly`) - unwatched turns as before; refuse it there too if asked.
    # (Nor for any delete at all, whatever it deletes: a rule names a program, not its paths.)
    if not is_plain(command) or is_wrapped(command) or harms(command) or _git_runs(command) or (
            _fetch_writes(command)) or any(
            _program(words[0]) in _DELETERS for words in _commands_in(command) if words):
        return ""
    words = _words(command.strip())
    if not words:
        return ""
    program = _program(words[0])
    rest = words[1:]
    if program in _SHELLS:
        return ""
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
        if (need := _EXECUTORS.get((program, rest[0]))) is not None:
            named = len(words) >= need and not any(w.startswith("-") for w in words[2:need])
            return " ".join(words[:need]) if named else ""
        if (program, rest[0]) in _RUNNERS:
            task_named = len(rest) >= 2 and not rest[1].startswith("-")
            return " ".join(words[:3]) if task_named else ""
        return " ".join(words[:2])
    return words[0]


# Words that run whatever follows them: a rule for one of these would cover anything.
_WRAPPERS = frozenset({
    "env", "timeout", "xargs", "sudo", "nohup", "nice", "time", "watch", "exec", "eval",
    "command", "builtin", "start", "call",
    # PowerShell's (commands run in it on Windows), by name and alias; and the dot and
    # `source`, which run whatever script or command they are given.
    "iex", "invoke-expression", "icm", "invoke-command", "saps", "start-process",
    "sajb", "start-job", "ihy", "r", "invoke-history", ".", "source",
    # ...and what else on Windows runs a command line, a script or a file it is given.
    "forfiles", "wmic", "iwmi", "invoke-wmimethod", "icim", "invoke-cimmethod", "conhost",
    "schtasks", "runas", "ii", "invoke-item", "ipmo", "import-module", "start-threadjob",
    "cscript", "wscript", "mshta", "rundll32", "regsvr32", "msiexec", "explorer",
    # ...and elsewhere.
    "setsid", "stdbuf", "ionice", "flock", "su", "doas", "busybox", "ssh",
})
# K-r132: a shell's or a wrapper's options that take the next word for their value (`nice -n
# 5`, `xargs -a f`), those whose value is a command line of its own (`env -S 'rm x'`, `su -c`,
# `sh -c`), and those known to take none (cmd's and PowerShell's in lower case: any case is
# theirs). Any other option might take one: what it hands on is judged both ways.
_TAKES_VALUE = {program: frozenset(options.split()) for program, options in {
    "timeout": "-s --signal -k --kill-after", "nice": "-n --adjustment",
    "env": "-u --unset -C --chdir",
    "xargs": "-a --arg-file -n --max-args -I -d --delimiter -L --max-lines -P --max-procs -s "
             "--max-chars -E",
    "sudo": "-u --user -g --group -C -D --chdir -p --prompt -r -t -T -U",
    "ionice": "-c --class -n --classdata -p --pid -P --pgid -u --uid", "stdbuf": "-i -o -e",
    "exec": "-a", "time": "-f --format -o --output", "watch": "-n --interval",
    "flock": "-w --timeout -E --conflict-exit-code",
    "su": "-s --shell -g --group -G --supp-group -w --whitelist-environment",
    "wsl": "-d --distribution -u --user --cd --shell-type",
    "sh": "-o +o -O +O --rcfile --init-file", "bash": "-o +o -O +O --rcfile --init-file",
    "zsh": "-o +o",
    "powershell": "-executionpolicy -ep -ex -exec -windowstyle -w -win -encodedcommand -e -ec "
                  "-enc -inputformat -outputformat -version -configurationname "
                  "-workingdirectory -wd -settingsfile",
}.items()}
_TAKES_LINE = {program: frozenset(options.split()) for program, options in {
    "env": "-S --split-string", "flock": "-c --command", "su": "-c --command",
    "sh": "-c", "bash": "-c", "zsh": "-c",
}.items()}
_TAKES_NONE = {program: frozenset(options.split()) for program, options in {
    "timeout": "--preserve-status --foreground -v --verbose",
    "env": "- -i --ignore-environment -0 --null -v --debug",
    "xargs": "-0 --null -r --no-run-if-empty -t --verbose -p --interactive -x --exit -o "
             "--open-tty -i -e -l",
    "sudo": "-E -H -n -S -b -i -s -k -A -P --preserve-env", "ionice": "-t --ignore",
    "exec": "-c -l", "time": "-p -v --verbose -a --append", "command": "-v -V -p",
    "watch": "-t -x --exec -b -e -g -c -p", "wsl": "-e --exec",
    "flock": "-s --shared -x -e --exclusive -u --unlock -n --nb --nonblock -o --close -F "
             "--no-fork",
    "su": "- -l --login -m -p --preserve-environment -P --pty",
    "cmd": "/c /k /s /q /d /a /u",  # (`/v:on`, `/e:on`, `/t:0a` hold theirs after the colon)
    "sh": "-e -x -u -l -i -s -v -n -f -a --login --norc --noprofile --posix",
    "bash": "-e -x -u -l -i -s -v -n -f -a --login --norc --noprofile --posix",
    "zsh": "-e -x -u -l -i -s -v -n -f",
    "powershell": "-command -c -noprofile -nop -noninteractive -noni -nologo -nol -noexit "
                  "-noe -sta -mta -file -f -login -l",
}.items()}
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
                        option = words[at].casefold() if program in (
                            "cmd", "powershell", "pwsh") else words[at]
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
    return [*found, *lines_handed, *([[UNREAD]] if unread else [])]


def _hands_on(command: str) -> bool:
    """Whether a command's program runs what its arguments name: an interpreter, a
    package runner (`npx`, `npm exec`). A rule for one covers a command only where it
    names as much as "Always run" would offer now (`suggest_prefix`): one stored before,
    or written by hand, for the program alone covers nothing."""
    words = _words(command.strip())
    if not words:
        return False
    program = _program(words[0])
    return bool(
        _INTERPRETER.fullmatch(program) or program in _RUNNER_PROGRAMS
        or (len(words) > 1 and (program, words[1]) in _EXECUTORS)
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
_GIT_RULED = frozenset({
    "status", "diff", "log", "show", "add", "commit", "fetch", "pull", "clone", "rebase", "grep",
    "checkout", "switch", "branch", "push", "merge", "stash", "tag", "remote", "restore", "rm",
    "mv", "reset", "blame", "shortlog", "describe", "rev-parse", "ls-files", "cherry-pick",
    "ls-remote", "rev-list", "cat-file", "reflog", "worktree", "submodule",
})
# ...and of these, only the forms that look (their first word past the options; "" for none).
_GIT_RULED_ONLY = {"reflog": ("", "show", "list"), "worktree": ("", "list"),
                   "submodule": ("", "status")}
_GIT_RUNS = ("open-files-in-pager", "upload-pack", "receive-pack", "exec", "extcmd", "output",
             "output-directory", "template", "config")
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
    if sub in _GIT_RULED_ONLY and next(
            (a for a in args if not a.startswith("-")), "") not in _GIT_RULED_ONLY[sub]:
        return True
    for at, a in enumerate(args if sub in ("merge", "pull", "rebase") else ()):
        # (a strategy not git's own runs `git-merge-<name>` from PATH)
        after = args[at + 1] if at + 1 < len(args) else ""
        if _long(a, "strategy") or _cluster(a, "s"):
            name = a.partition("=")[2] if a.startswith("--") else a[a.index("s", 1) + 1:]
            if (name or after) not in _GIT_STRATEGIES:
                return True
    return any(_long(a, *_GIT_RUNS) or any(
        _cluster(a, letter) for letter in _GIT_RUNS_SHORT.get(sub, "")) for a in args)


# Security review 0.1.0, finding 5: what makes a fetcher write a file or read its options from one
# (`curl -o`, `-K`, `wget -P`): short ones in a cluster (`-sSo`), long ones by prefix; and
# PowerShell's `-OutFile`, by any prefix of it (`-OutF`), in any case.
_FETCH_WRITES = {
    "curl": ("oODKc", ("output", "output-dir", "remote-name", "remote-name-all", "config",
                       "dump-header", "cookie-jar", "trace", "trace-ascii", "stderr", "libcurl",
                       "etag-save", "etag-compare", "hsts", "alt-svc", "ssl-sessions",
                       "proto-default")),
    "wget": ("oOaPe", ("output-document", "output-file", "append-output", "directory-prefix",
                       "execute", "config", "use-askpass", "save-cookies", "warc-file",
                       "rejected-log", "hsts-file")),
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
            for word in words[1:])
    if program not in _FETCH_WRITES:
        return False
    short, long = _FETCH_WRITES[program]
    if program == "wget":  # (`-qO-`, `-O -`: to the output, no file)
        words = [word[:-2] if word.endswith("O-") and word.startswith("-") else word[:-1] if (
            _cluster(word, "O") and word.endswith("O") and after == "-") else word
                 for word, after in zip(words, [*words[1:], ""], strict=True)]
    # (`-G -d @file` reads a file into the address: `@` is not `_PLAIN`, so no rule covers it)
    return not _only_fetches(words) or any(
        _long(word, *long) or any(_cluster(word, letter) for letter in short)
        for word in words[1:])


def matches(command: str, prefix: str) -> bool:
    """Whether an allow-list rule covers a command. Only a plain command can match, and never
    one that deletes or cannot be undone (`danger`), makes git run a program (`_git_runs`) or a
    fetcher write a file (`_fetch_writes`)."""
    if (not prefix or not is_plain(command) or is_wrapped(command) or _in_a_shell(command)
            or danger(command) or _git_runs(command) or _git_runs(prefix)
            or _fetch_writes(command)):
        return False
    if _hands_on(command):
        offered = suggest_prefix(command)
        if not offered or len(prefix.split()) < len(offered.split()):
            return False
    normal = " ".join(command.split())
    return normal == prefix or normal.startswith(prefix + " ")


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
        raise ValueError("a git rule names git's command and no option that runs a program or "
                         "writes a file it is told of (`git status`): it is asked every time")
    if _fetch_writes(command):
        raise ValueError("a fetcher's rule only fetches: no option that writes a file, reads "
                         "a config or sends (`-o`, `-K`, `-OutFile`, `-d`)")
    rule = " ".join(words)
    if len(rule) > MAX_RULE:
        raise ValueError(f"a rule is a command of at most {MAX_RULE} characters")
    return rule


def is_exactly(command: str, rule: str) -> bool:
    """Whether a command is a rule's text, character for character - how a rule is read
    where nobody is watching: no further argument, no other spacing, nothing chained or
    wrapped, and nothing that deletes or cannot be undone."""
    return (bool(rule) and command == rule and is_plain(command) and not is_wrapped(command)
            and not _in_a_shell(command) and not danger(command))


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
        for rule in session.scalars(select(AllowedCommand).where(
            AllowedCommand.conversation_id == trigger.conversation_id,
            AllowedCommand.project_id == trigger.project_id,
            AllowedCommand.id.in_(wanted),
        ))
    }
    return [found[rule_id] for rule_id in dict.fromkeys(wanted) if rule_id in found]


def rules_here(conversation):
    """The "Always run" rules that hold in a chat now: its own, made in the folder it is in
    (slice 86a). A plain chat has none."""
    return select(AllowedCommand).where(
        AllowedCommand.conversation_id == conversation.id,
        AllowedCommand.project_id == conversation.project_id)


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
_DELETERS = frozenset({
    "rm", "del", "erase", "rd", "rmdir", "remove-item", "ri", "unlink", "shred", "dd",
    "format", "diskpart", "wipefs",
})
# git's and docker's options that take a value before the subcommand (`git -C repo push`).
_GIT_VALUE_OPTIONS = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace",
                                "--config-env", "--attr-source", "--super-prefix"})
_DOCKER_VALUE_OPTIONS = frozenset({
    "-c", "--context", "-H", "--host", "--config", "-l", "--log-level",
    "--tlscacert", "--tlscert", "--tlskey",
})
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
    r"(?i)\[\s*(?:system\s*\.\s*)?io\s*\.\s*(?:file|directory)\s*\]\s*::\s*delete")


def _cluster(word: str, letter: str) -> bool:
    """Whether a short-option word (`-fd`, `-xfd`) holds a letter."""
    return word.startswith("-") and not word.startswith("--") and letter in word[1:]


def _after_options(rest: list[str], takes_value: frozenset[str]) -> list[str]:
    """The words from the subcommand on: the options before it skipped, with their values."""
    at = 0
    while at < len(rest) and rest[at].startswith("-"):
        at += 2 if rest[at] in takes_value else 1
    return rest[at:]


def _danger_of(words: list[str]) -> str:  # noqa: C901
    program = _program(words[0])
    if program == UNREAD:
        return ("It hands shells or wrappers more options and lines than are read here: what "
                "runs is not seen.")
    if program in _DELETERS or program.startswith("mkfs"):
        return "Deletes files or disks."
    if program in ("clear-content", "clc"):
        return "Empties files (Clear-Content)."
    rest = words[1:]
    # K-koloni-klasor (review): a link made under the scratch can lead to `.koloni` or out of
    # the project, and a write through it is judged by the path written.
    if program == "mklink" or program == "ln" and any(
            a == "--symbolic" or _cluster(a, "s") for a in rest) or program in (
            "new-item", "ni") and any(  # (`-ItemType:Junction` too: review of B-336)
                a.casefold().rsplit(":", 1)[-1] in ("junction", "symboliclink", "hardlink")
                for a in rest):
        return "Makes a link, which can point anywhere."
    if program == "find" and "-delete" in rest:
        return "Deletes files (find -delete)."
    if program in ("docker", "docker-compose"):
        # `docker volume rm x`, `docker --context x rm web`: the task is in the first two words
        named = [w for w in _after_options(rest, _DOCKER_VALUE_OPTIONS) if not w.startswith("-")]
        compose = program == "docker-compose" or named[:1] == ["compose"]
        if {"rm", "rmi"} & set(named[:2]) or "prune" in named or compose and (
            "rm" in named or "down" in named
            and any(a.startswith("--volumes") or _cluster(a, "v") for a in rest)
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
        or _cluster(a, "f") or _cluster(a, "d") or (a[:1] in "+:" and len(a) > 1)
        for a in args
    ):
        return "Overwrites or deletes branches on the git remote."
    if sub == "reset" and any(_long(a, "hard") for a in args):
        return "Throws away uncommitted work (git reset --hard)."
    if sub == "clean" and force:
        return "Deletes untracked files (git clean)."
    if sub == "rm" and force and not any(_long(a, "cached") for a in args):
        return "Deletes files with uncommitted changes (git rm -f)."
    if (sub == "branch" and (force or any(_cluster(a, "D") or _cluster(a, "M") for a in args))
            or sub == "checkout" and any(_cluster(a, "B") for a in args)
            or sub == "switch" and any(_cluster(a, "C") or _long(a, "force-create") for a in args)
            or sub == "update-ref"):
        return "Deletes or moves a git branch by force: commits only it held may be lost."
    staged = any(a == "--staged" or _cluster(a, "S") for a in args)
    worktree = any(_long(a, "worktree") or _cluster(a, "W") for a in args)
    if (sub == "checkout" and ("--" in args[:-1] or force or _checks_out_paths(args))
            or sub == "switch" and (force or any(_long(a, "discard-changes") for a in args))
            or sub == "restore" and (worktree or not staged)):
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
    return bool(path) and (os.path.isabs(path) or bool(PureWindowsPath(path).anchor)
                           or path.startswith("~") or norm == ".." or norm.startswith("../"))


def switches_branch(command: str) -> bool:
    """K-dallar: whether a part of a command moves the project onto another branch - `git
    switch`, `git checkout <branch>` (not `-- <path>`, nor `.`, which `danger` asks about).
    shortcut: `git checkout file.py` with no `--` reads as a switch too - git itself tells them
    apart by what the word names; it is asked about only while another's work is held."""
    for words in _parts(command):
        sub, rest = _git_sub(words)
        if not rest or {"-h", "--help"} & set(rest):
            continue
        # (`git switch -- x` too; `git checkout x --` is a switch, `-- <path>` after it is not)
        if sub == "switch" or sub == "checkout" and "." not in rest and (
                "--" not in rest or rest.index("--") == len(rest) - 1 and len(rest) > 1):
            return True
    return False


# K-dal-takim: a branch's worktree shares the user's repository - their stash, refs, reflog,
# objects, config, remotes. There git runs unasked only for an agent's own work on its branch
# (`reaches_shared_git`, an allow-list): what is not on it is asked at every level.
SHARED_GIT = ("it runs git in a branch's worktree beyond its own work there - git there is the "
              "user's own repository (their stash, branches, history, settings, remotes): asked "
              "at every level")
# The subcommands an agent's own work needs, each with the exact options it may be given
# (`_own_git`): (options alone, options whose value is the next word, `--x=` forms that take one).
# git takes a value stuck to its option (`-Bmain`), short options bundled (`-qC`) and any unique
# prefix of a long one (`--op` for --open-files-in-pager): so an option is taken only as written
# here, whole - never by its start. Never on a list: --output, --ext-diff, --textconv, --filters,
# -O / --open-files-in-pager.
_OWN_FLAGS: dict[str, tuple[frozenset[str], frozenset[str], tuple[str, ...]]] = {
    "status": (frozenset({"-s", "--short", "-b", "--branch", "--porcelain", "--porcelain=v1",
                          "--porcelain=v2", "-uno", "-unormal", "-uall", "--ignored"}),
               frozenset(), ()),
    "diff": (frozenset({"--stat", "--name-only", "--name-status", "--cached", "--staged",
                        "--no-color", "--color=never", "-U0", "-U1", "-U3"}), frozenset(), ()),
    "log": (frozenset({"--oneline", "--stat", "--name-only", "--name-status", "--graph",
                       "--decorate", "--no-color"}), frozenset({"-n"}),
            ("--format=", "--pretty=")),
    "show": (frozenset({"--stat", "--name-only", "--name-status", "--no-color"}), frozenset(),
             ("--format=", "--pretty=")),
    "add": (frozenset({"-A", "--all", "-u", "--update", "-N", "--intent-to-add", "-q",
                       "--quiet"}), frozenset(), ()),
    "commit": (frozenset({"-a", "--all", "--amend", "--no-edit", "--allow-empty", "-q",
                          "--quiet"}),
               frozenset({"-m", "--message"}), ("--message=",)),
    "rm": (frozenset({"--cached", "-r", "-q", "--quiet"}), frozenset(), ()),
    "mv": (frozenset(), frozenset(), ()),
    "restore": (frozenset({"--staged", "--worktree", "-W", "-S"}), frozenset(), ()),
    "checkout": (frozenset({"-q", "--quiet"}), frozenset(), ()),
    "switch": (frozenset({"-q", "--quiet"}), frozenset(), ()),
    "branch": (frozenset({"-a", "--all", "-r", "--remotes", "-v", "-vv", "--verbose", "-l",
                          "--list", "--show-current", "--no-color"}), frozenset(), ()),
    "tag": (frozenset({"-l", "--list", "--no-color"}), frozenset(), ()),
    "grep": (frozenset({"-n", "-i", "-l", "-L", "-c", "-w", "-E", "-F", "-I", "-h", "-H",
                        "--line-number", "--ignore-case", "--files-with-matches", "--count",
                        "--word-regexp", "--fixed-strings", "--extended-regexp"}),
             frozenset({"-e"}), ()),
    "rev-parse": (frozenset({"--show-toplevel", "--abbrev-ref", "--short", "--verify",
                             "--git-dir"}), frozenset(), ()),
    "ls-files": (frozenset({"--others", "--exclude-standard", "--cached", "--modified",
                            "--deleted", "-z"}), frozenset(), ()),
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
# A variable of git's own set on the line: in POSIX `GIT_X=`, cmd `set GIT_X=`, PowerShell
# `$env:GIT_X=` or `Set-Item env:GIT_X`, .NET's SetEnvironmentVariable.
_GIT_ENV = re.compile(r"(?i)(?:^|[\s;&|(`{])(?:\$env:)?GIT_\w*\s*=|env:GIT_|"
                      r"SetEnvironmentVariable\(\s*['\"]GIT_")
# git as a word of the line, wherever it stands: one not read as a command's program is asked.
_GIT_WORD = re.compile(r"(?i)(?:^|[\s;&|(`{'\"\\/])git(?:\.exe)?(?=$|[\s;&|)`}'\"])")


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
    before = words[1:len(words) - len(rest) - (1 if sub else 0)]
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
        if word in valued or sub == "commit" and _COMMIT_BUNDLE.fullmatch(word) and (
                len(set(word)) == len(word)):
            at += 1 if word.endswith("m") else 0  # (its value: the message)
            continue
        if word.startswith("-") and not (word in alone or word.startswith(forms) and forms
                                         or sub == "log" and re.fullmatch(r"-\d+", word)):
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
    own branch, the one a checkout or switch may go onto (None: none yet - asked).
    shortcut: git run by a script, or a name spliced by the shell (`g`it`, `$(echo git)`), is not
    seen - as `danger` does not see those either."""
    if _GIT_ENV.search(command):
        return SHARED_GIT
    read = 0
    for words in (words for words in _commands_in(command) if words):
        if words == [UNREAD]:
            return SHARED_GIT
        if _program(words[0]) == "git":
            read += 1
            if not _own_git(words, own):
                return SHARED_GIT
    # (PowerShell drops a backtick before a letter: `g`it` is git.)
    return SHARED_GIT if len(_GIT_WORD.findall(command.replace("`", ""))) > read else ""


DELETES_THROUGH_LINKS = (
    "it deletes in a working copy, where node_modules, .venv and venv are links to the "
    "project's own: through one it would delete the project's"
)
REBUILDS_THROUGH_LINKS = (
    "it rebuilds a dependency folder in a working copy, where node_modules, .venv and venv "
    "are links to the project's own: through one it would empty and rebuild the project's"
)
# What empties a dependency folder and makes it anew - measured 29 Oct through a junction:
# `npm ci` emptied the project's node_modules, `uv venv` its .venv; `uv sync` makes the venv
# anew when its interpreter changed. shortcut: `pnpm install --frozen-lockfile`, `yarn
# install --force` and `uv run x` (it syncs the environment first, so may make the venv anew
# too) are not measured, so not here; and a script that runs one of these is not seen -
# measure and list them if met.
_REBUILDERS = frozenset({("npm", "ci"), ("uv", "venv"), ("uv", "sync")})


def _recursive(word: str) -> bool:
    """A delete's flag that goes down into folders: `-r`, `-rf`, `-R`, `-Recurse`, `/s`."""
    word = word.casefold()
    return (word in ("/s", "--recursive") or word.startswith("-rec")
            or bool(re.fullmatch(r"-[a-z]{1,4}", word)) and "r" in word)


def _through_links(words: list[str]) -> str:
    """Why a command may reach through a linked folder into the project's own, "" for none:
    a delete that goes down into folders or names a linked one, what deletes folders by
    itself (`find -delete`, `git worktree remove`, `robocopy /MIR` or `/PURGE`), and what
    empties a dependency folder to make it anew (`_REBUILDERS`)."""
    program, rest = _program(words[0]), words[1:]
    if (program, *rest[:1]) in _REBUILDERS:
        return REBUILDS_THROUGH_LINKS
    if (program == "find" and "-delete" in rest
            or program == "robocopy" and any(w.casefold() in ("/mir", "/purge") for w in rest)
            or program == "git" and _after_options(rest, _GIT_VALUE_OPTIONS)[:2] == [
                "worktree", "remove"]):
        return DELETES_THROUGH_LINKS
    return DELETES_THROUGH_LINKS if program in _DELETERS and any(
        _recursive(word) or any(part.casefold() in LINKED for part in re.split(r"[\\/]", word))
        for word in rest) else ""


def _spellings(path: str) -> re.Pattern:
    """A folder's path as a command may write it, as `os.path.normcase` gives it: as given,
    resolved, and Git Bash's `/c/...` for a drive's - not a longer name it begins
    (`Proj` is not `Proj-old`)."""
    forms = {path.rstrip("\\/"), os.path.realpath(path)}
    forms |= {f"/{form[0]}{form[2:]}" for form in list(forms) if re.match(r"[A-Za-z]:", form)}
    # (Grouped: the end of the name holds for every spelling, not the last one alone.)
    return re.compile("(?:" + "|".join(re.escape(os.path.normcase(form)) for form in forms)
                      + r")(?![\w.-])")


NAMES_PROJECT = (
    "it names the project folder ({root}), outside the working copy it works in: there it "
    "would act on the project itself"
)


def copy_reason(command: str, linked: bool, project: str, runtime: Path | str) -> str:
    """Why a command an agent runs in its working copy is asked at every level, Full auto
    too, and refused in a turn nobody watches; "" where there is none. It names `project`,
    the project's folder (K-kopya-istem) - KOLONİ's own `runtime` in it is not the project's
    (the copy, a skill's script: KOLONİ on its own repository). Or `linked`: the copy has
    the project's dependency folders linked in, and a delete there - or what empties such a
    folder to make it anew, `_REBUILDERS` - may go through a link into the project's own
    (K-70-junction), in a shell too (`cmd /c rd /s x`).
    shortcut: by the path as written, either slash, in any case on Windows; `..` out of the
    copy, a short name (`PROJ~1`), a variable or a script that names it is not seen - nor a
    delete in a script, or by a program `_through_links` does not list."""
    written = _spellings(str(runtime)).sub("", os.path.normcase(command))
    if _spellings(project).search(written):
        return NAMES_PROJECT.format(root=project)
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
    return ""


SECRET_FILE = "Opens a secret file (keys, passwords): asked at every level."
KOLONI_FILES = (
    "Names .koloni, the folder's KOLONİ rules and settings, which agents do not change: asked "
    "at every level. Scratch belongs under .koloni/tmp/: put it there and run again."
)
# B-339: said where the line climbs out of the scratch (`_CLIMBS`) rather than naming `.koloni`.
CLIMBS_OUT = (
    "Climbs out of .koloni/tmp, the agents' scratch, into .koloni - the folder's KOLONİ rules "
    "and settings, which agents do not change (by `..`, a change of folder or a built path): "
    "asked at every level. Stay inside .koloni/tmp/ and run again."
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
    return is_secret(piece) if _outside(piece) else secret_in_project(
        posixpath.normpath(piece.replace("\\", "/")))


def _outside(piece: str) -> bool:
    """Whether a path in a command leads out of the folder it runs in: from a root, a drive,
    the home folder, or by `..` past it."""
    p = piece.replace("\\", "/")
    return bool(p.startswith(("/", "~")) or re.match(r"[A-Za-z]:", p)
                or posixpath.normpath(p).startswith(".."))


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
        for word in _words(part.strip()):
            # (split at `:` too: a drive letter's path is left starting with `/`, out of it;
            # and at `,`: PowerShell's list of paths, `gc a,.env`)
            if any(_secret_path(piece) for piece in re.split(r"[=:<>,]", word.strip("'\""))
                   if piece and not (members and _MEMBER.fullmatch(piece))):
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
_PASSED_BY = re.compile(r"""(?i)\s(?:(?:-g|--i?glob)[\s=]+['"]?!|--exclude(?:-dir)?[\s=]+"""
                        r"""|(?:-not|!)\s+-i?path\s+)['"]?[^\s'"]+['"]?""")


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
    # of it or build a path from it (`_CLIMBS`: `cd .koloni/tmp; echo x > ../rules.md`,
    # `Split-Path .koloni/tmp`), nor on a git line (`git add -f .koloni/tmp/x` would commit a
    # profile's cookies): there it is `.koloni`, and asked. shortcut: by that spelling -
    # `.koloni/t*`, `KOLONI~1/tmp` and `.koloni/./tmp` are still `.koloni`, and asked.
    # (`..` split by quotes, a caret or a backtick is `..` to the shell: judged without them.)
    scratch = not _CLIMBS.search(_as_read(command)) and not any(
        _git_sub(words)[0] for words in _parts(command))
    parts: list[str] = []
    for word in re.split(r"[\s=:<>,;|&()]", re.sub(r"[`^'\"]", "", kept)):
        pieces = [_name(piece) for piece in re.split(r"[\\/]", word)]
        if scratch:
            pieces = [piece for at, piece in enumerate(pieces)
                      if not (piece == ".koloni" and pieces[at + 1:at + 2] == ["tmp"])]
        parts += pieces
    return parts


# What can climb out of the scratch or reach `.koloni` from it: `..`, a change of folder, a
# path built or resolved, `-C <dir>` (git's, tar's).
_CLIMBS = re.compile(
    r"\.\.|(?<![\w-])(?i:cd|chdir|pushd|popd|sl|set-location|push-location|pop-location"
    r"|split-path|join-path|resolve-path)(?![\w-])|(?<!\S)-C(?!\S)")


def _as_read(command: str) -> str:
    """A line as the shell reads its names: quotes (PowerShell's smart ones too), carets,
    backticks and a backslash before a dot taken out (`.'.'`, `.‘.’`, `.^.`, `` .`. `` and sh's
    `.\\.` are `..`)."""
    return re.sub(r"[`^'\"‘-„]|\\(?=\.)", "", command)


def with_cwd(command: str, cwd: object) -> str:
    """A command as it is judged with the folder it is run in (run_command's `cwd`): `cd
    <cwd>; <command>` - so that `cwd=.koloni/tmp` with `echo x > ../settings.json`, or
    `cwd=.claude`, names what it reaches. What runs is the command alone."""
    return f"cd {cwd}; {command}" if isinstance(cwd, str) and cwd not in ("", ".") else command


# B-304: the files that hold the key to a run's tool server (its bridge's, agy's door), and a
# CLI run's own temp folder (`tempfile.mkdtemp(prefix="koloni-cli-")`).
KEY_FILES = frozenset({"bridge.json", "koloni-door.json"})
_RUN_FOLDER = re.compile(r"koloni-cli-[a-z0-9_]+")


def _where_keys_are(part: str) -> bool:
    """A part of a path that places a KEY_FILES name there: the temp folder, a run's, agy's."""
    return part.strip("%") in ("temp", "tmp") or part.startswith("agy-") or bool(
        _RUN_FOLDER.fullmatch(part))


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
            if (parts[at + 1:at + 3] != ["plugin", "skills"] or ".." in command
                    or _GLOB.search(command)):
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
    named = {key for piece in _path_names(" ".join(code))
             if (key := _standing_of(piece, wildcards=False))}
    rest = _INLINE_CODE.sub(lambda found: found[0][:found.start(1) - found.start()], command)
    parts = _CHAIN.split(rest)
    if "$(" in rest or not all(map(_balanced, parts)):
        parts = [rest]
    named |= {key for part in parts if not _reads(part, sinks)
              for piece in _path_names(part) if (key := _standing_of(piece))}
    named |= {".git"} if _sets_git_config(command) else set()
    named |= {PATCH} if applies_patch(command) else set()
    return min(named) if named else ""


# A chain's commands, a pipeline one of them: `_PARTS` less a single `|`.
_CHAIN = re.compile(r"&&|\|\||[;&\r\n]")
# B-316: what a pipe may hand a read's text to that only picks, sorts, counts or lays it out,
# writing nothing (not `sort`: sort.exe's `/o` and `sort -o` write a file).
_SINKS = frozenset({"select-object", "select", "select-string", "sls", "sort-object",
                    "measure-object", "out-string", "ft", "fl", "fw"})


def _sink(stage: str) -> bool:
    """A stage of a pipeline that only shapes the text it is handed: one of `_SINKS` or a
    Format-*, handed no block, hashtable, bracket, variable, redirection or escape (`{`, `@{`,
    `(`, `$`, `>`, a backtick): with those it could run or write anything."""
    words = _words(stage.strip())
    program = _program(words[0]) if words else ""
    return not re.search(r"[{}()$<>`]", stage) and (
        program in _SINKS or program.startswith("format-"))


def _reads(part: str, sinks: bool = True) -> bool:
    """A command of a chain that reads what it names (`names_standing`): it only reads, only
    searches, or is a read piped on only into sinks (`_sink`) - not where the line may give a
    sink's name to another program (`sinks` False: `_RENAMES`). shortcut: a `|` inside quotes
    (`sls -Pattern "a|b"`) splits the pipeline there, so such a one asks; split outside quotes
    if that is met with a standing name."""
    first, *stages = part.split("|")
    return only_reads(part.strip()) or _only_searches(part) or sinks and bool(stages) and (
        only_reads(first.strip()) and all(map(_sink, stages)))


# What gives a command's name to something else in the line: an alias, a function or a filter.
# (`alias`: bash's, K-r147.)
_RENAMES = re.compile(
    r"(?i)(?<![\w-])(?:set-alias|new-alias|sal|nal|function|filter|alias)(?![\w-])")
# What a search may be told that writes or runs something: find's actions, rg's preprocessor and
# its replace (`-r` is rg's and ag's replace, grep's recursion).
_SEARCH_DOES = re.compile(r"(?i)-exec|-execdir|-ok|-okdir|-delete|-fprint0?|-fprintf|-fls"
                          r"|--pre(?:=.*)?|--replace(?:=.*)?")


def _only_searches(part: str) -> bool:
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
        for word in words)


# B-307: a shell handed a script to run - `powershell[.exe]` or `pwsh` (by its name, or its path
# from a drive) with only flags that take no value, then `-Command` or `-c`; `cmd /c` - and the
# script: the rest. Not one handed a file, an encoded command or another flag (`-File`,
# `-EncodedCommand`), nor one of the folder's own (`.\powershell.exe`, which an agent can write).
# shortcut: a path from a drive into the project is taken as the shell, as `POWERSHELL_LINE` does.
_SHELL_SCRIPT = re.compile(
    r"""(?is)\s*("[^"]*"|\S+)\s+(?:(?:-NoProfile|-NonInteractive|-NoLogo|/[dsq])\s+)*"""
    r"""(?:-Command|-c|/c)\s+(.*?)\s*""")


def _script(command: str) -> str | None:
    """The script a shell is handed (`_SHELL_SCRIPT`), out of the quotes around all of it
    (`""` and `\\"` in them a quote); None where it is no such line."""
    found = _SHELL_SCRIPT.fullmatch(command)
    shell = found[1].strip("'\"") if found else ""
    if (not found or _program(shell) not in ("powershell", "pwsh", "cmd")
            or re.search(r"[\\/]", shell) and not re.match(r"[A-Za-z]:", shell)):
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
        part.count(a) == part.count(b) for a, b in ("()", "{}", "[]"))
# The code an interpreter is handed inline, quoted: `python -c "..."`, `node -e '...'` - the
# interpreter a word of its own, by its path too (not `deploy.py -c`).
_INLINE_CODE = re.compile(
    r"""(?i)(?:^|(?<=[\s;&|(]))(?:\S*[\\/])?(?:python|py|node)[\d.]*w?(?:\.exe)?\s+"""
    r"""(?:-\w+\s+)*?(?:-c|-e|-p|--eval|--print)\s+("[^"]*"|'[^']*')""")


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
    if wildcards and re.search(r"[?*\[]", piece) and len(
            re.split(r"[?*\[]", piece, maxsplit=1)[0]) >= 3:
        return next((key for key in sorted(NOT_WRITTEN_UNATTENDED)
                     if fnmatch.fnmatchcase(key, piece)), None)
    if short := _SHORT.fullmatch(piece):
        # (Its first six letters before the extension, the leading dot dropped: `.mcp.json`
        # is MCP~1.JSO.)
        return next((key for key in sorted(NOT_WRITTEN_UNATTENDED)
                     if key.lstrip(".").rsplit(".", 1)[0][:6] == short[1]), None)
    return None


def _git_sub(words: list[str]) -> tuple[str | None, list[str]]:
    """The git command a line runs (`git -C x config a b`: "config") and its words after it;
    None for a line that is not git's."""
    if not words or _program(words[0]) != "git":
        return None, []
    at = 1
    while at < len(words) and words[at].startswith("-"):
        at += 2 if words[at] in ("-C", "-c", "--git-dir", "--work-tree") else 1
    return (words[at], words[at + 1:]) if at < len(words) else (None, [])


def _parts(command: str, at: re.Pattern = _PARTS) -> list[list[str]]:
    return [[word.strip("'\"") for word in _words(part.strip())] for part in at.split(command)]


def _sets_git_config(command: str) -> bool:
    """Whether a part of a command is `git config` setting or taking off a value - not one
    that only reads (`--get…`, `--list`, `-l`, a key alone)."""
    for words in _parts(command):
        sub, rest = _git_sub(words)
        if sub != "config" or rest[:1] in (["get"], ["list"]):  # (git 2.46's words for a read)
            continue
        if not any(w.startswith(("--get", "--list", "-l")) for w in rest) and (
                len([w for w in rest if not w.startswith("-")]) > 1
                or any(w.startswith(("--unset", "--add", "--replace", "--rename", "--remove",
                                     "--edit", "-e")) for w in rest)):
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
    if not parts or re.search(r"\$\(|`|[<>]", command) or any(
            _git_sub(words)[0] is None or words[1].startswith("-") for words in parts):
        return []
    return [_git_sub(words) for words in parts]


def writes_git_config(command: str) -> bool:
    """Whether a command is git's own alone (`_git_alone`) and one of its parts rewrites
    `.git/config` as it works (`git init`, `git remote add`, `git push -u`, `git checkout
    --track`, `git config` not `--global`)."""
    return any(sub in _CONFIG_WRITERS
               or sub == "push" and bool({"-u", "--set-upstream"} & set(rest))
               or sub == "config" and not {"--global", "--system"} & set(rest)
               for sub, rest in _git_alone(command))


PATCH = "a patch"
_ONLY_LOOKS = ("--check", "--stat", "--numstat", "--summary", "--dry-run",
               "--show-current-patch")


def applies_patch(command: str) -> bool:
    """Whether a part of a command applies a patch (`git apply`, `git am`, `patch`): it writes
    whatever files the patch names - `.github/workflows` too - without the line naming them.
    Not one that only looks at it (`--check`, `--stat`, `--dry-run`)."""
    for words in _parts(command):
        sub, rest = _git_sub(words)
        applies = sub in ("apply", "am") or bool(words) and _program(words[0]) == "patch"
        if applies and not any(w.startswith(_ONLY_LOOKS) for w in (rest or words[1:])):
            return True
    return False


def danger(command: str, instructions: bool = True) -> str:
    """What a command does that cannot be taken back - it deletes, overwrites a git
    remote, opens a secret file or names `.koloni` or another file that steers later turns
    (`names_standing`, `standing_asked`: `instructions` False leaves the instruction files
    out) - in one sentence; "" when it does none.
    Each part of a chained command is looked at. No rule covers such a command, and none is
    offered; Full auto asks about one too (`harms`). shortcut: a list of programs and
    flags, not a sandbox; a deleting script, a program renamed or one inside a shell (`cmd /c
    del`) is not seen - add what the user meets."""
    standing = standing_asked(command, instructions)
    return _harm(command) or (
        PATCHES if standing == PATCH else GIT_IDENTITY if standing == ".git" and _sets_identity(
            command)
        else STANDING_FILE.format(name=standing) if standing else "")


def _sets_identity(command: str) -> bool:
    """Whether every part of a command is a plain `git config [--local] user.name|user.email
    <value>`: this project's own name for its commits, nothing else of .git."""
    parts = _parts(command)
    for words in parts:
        sub, rest = _git_sub(words)
        key = [w for w in rest if w != "--local"]  # (and no option before `config`: -C x)
        if (sub != "config" or len(words) - len(rest) != 2 or len(key) != 2
                or key[0].lower() not in ("user.name", "user.email")):
            return False
    return bool(parts)


def standing_asked(command: str, instructions: bool = True) -> str:
    """The name a command names that is asked about at every level (`names_standing`); "" for
    none - and, `instructions` False, for an instruction file alone (`INSTRUCTION_FILES`):
    K-fullauto-sorma, at Full auto in a turn the user watches it is no card, as agents read
    it as the user's words and it runs nothing by itself."""
    standing = names_standing(command)
    return "" if standing in INSTRUCTION_FILES and not instructions else standing


def _harm(command: str) -> str:
    """`danger` but for a file that steers later turns: what `only_reads` cannot have. What a
    shell is handed is looked at too (`_commands_in`): B-339's `cmd /c mklink /J .koloni\\tmp\\x
    ..` is a link before it names `.koloni`."""
    for words in _commands_in(command, at=_BLOCKS):
        if words and (said := _danger_of(words)):
            return said
    if _DOTNET_DELETE.search(command):
        return "Deletes files through .NET ([IO.File]::Delete)."
    if names_secret(command):
        return SECRET_FILE
    if not names_koloni(command):
        return ""
    climbs = _SCRATCH.search(command) and _CLIMBS.search(_as_read(command))
    return CLIMBS_OUT if climbs else KOLONI_FILES


# B-336: the one card-free delete - a deleter alone on its line, by its bare name; plain forcing
# its only flags; its paths each spelt plainly under `.koloni/tmp/` (no part starting with ".", no
# wildcard); and nothing in the line that joins, wraps, quotes, expands or redirects (`_NOT_PLAIN`:
# `|;&`, a newline, `<>`, a comma or `=` list, any quote - smart ones too -, `^`, a backtick,
# brackets, `$ % ~`, `* ?`).
_SCRATCH_DELETERS = frozenset({"remove-item", "ri", "rm", "del", "erase", "unlink"})
_SCRATCH_FLAGS = frozenset({"-f", "--force", "-force", "-fo", "-q", "-path",
                            "-literalpath"})
_SCRATCH = re.compile(r"\.koloni[\\/]tmp\b", re.IGNORECASE)
_IN_SCRATCH = re.compile(r"(?:\./)?\.koloni[/\\]tmp(?:[/\\][\w-][\w.-]*)+", re.IGNORECASE)
_NOT_PLAIN = re.compile(r"[|;&\n\r<>,=`^'\"()\[\]{}$%~*?‘-„]")


def scratch_delete_only(command: str, root: str | None) -> bool:
    """B-336: whether a line is one delete of files in `.koloni/tmp/`, the agents' scratch of
    `root` (the folder it runs in), and nothing else - no card at Full auto, as writing there has
    none. Judged where the card is decided (`AgentRunner._night_asks`): `danger` stays as strict
    as ever, so no rule is offered for such a delete nor covers one. As narrow as it can be
    (`_SCRATCH_DELETERS`, `_SCRATCH_FLAGS`, `_IN_SCRATCH`, `_NOT_PLAIN`), not climbing out
    (`_CLIMBS`, the line read as the shell reads it), and each path, links resolved, inside the
    project's own scratch - which is no link itself.
    shortcut: judged when it is asked; a link made between that and the run is not seen (making
    one is a card of its own)."""
    if root is None or _NOT_PLAIN.search(command) or _CLIMBS.search(_as_read(command)):
        return False
    words = command.split()
    if not words or words[0].casefold() not in _SCRATCH_DELETERS:
        return False
    flags = [word for word in words[1:] if word.startswith("-")]
    paths = [word for word in words[1:] if not word.startswith("-")]
    if (not paths or any(flag.casefold() not in _SCRATCH_FLAGS for flag in flags)
            or not all(_IN_SCRATCH.fullmatch(path) for path in paths)):
        return False
    where = os.path.normcase(os.path.join(os.path.realpath(root), ".koloni", "tmp"))
    scratch = os.path.normcase(os.path.realpath(where))
    if scratch != where:  # (the scratch, or .koloni, a link itself: where it leads is not it)
        return False
    return all(os.path.normcase(os.path.realpath(os.path.join(root, path))).startswith(
        scratch + os.sep) for path in paths) and not names_secret(command)


# Programs that read every file below the folder they are in; those that read what they are
# handed; and those that list a folder's files, which a reader later in the line then reads.
_SEARCHERS = frozenset({"rg", "ripgrep", "ag", "ack"})
_GREPS = frozenset({"grep", "egrep", "fgrep"})
_READERS = frozenset({
    *_GREPS, "cat", "type", "more", "less", "head", "tail", "strings", "get-content", "gc",
    "findstr", "select-string", "sls",
})
_LISTERS = frozenset({"get-childitem", "gci", "ls", "dir"})
# Get-Content and its aliases: handed names by a pipe, it opens each of them.
_GETS = frozenset({"get-content", "gc", "cat", "type"})
# What also passes a pipe's names on, beside `_sink`'s: Sort-Object and Where-Object by their
# aliases (not sinks: sort.exe's `/o` writes, a `where` block may run anything).
_SHAPERS = frozenset({"sort", "where", "where-object", "?"})
# What hands a pipe text alone, never a file to open: the web's answers, git's, echo's.
_TEXTS = frozenset({
    "curl", "wget", "invoke-webrequest", "iwr", "invoke-restmethod", "irm", "echo",
    "write-output", "git",
})
_GLOB = re.compile(r"[*?]")
# (said on its card only where the folder holds one: `command_out`'s `held`)
SEARCHES_FOLDER = (
    "It searches the whole folder, and the folder holds a secret file: asked at every level."
)


def _one_file(rest: list[str]) -> bool:
    """Whether Select-String is handed one file, no wildcard: by -Path or -LiteralPath, or
    as its second word that is no option's (`sls KEY README.md`)."""
    named = [rest[at + 1] for at, word in enumerate(rest[:-1])
             if word.lower() in ("-path", "-literalpath", "-lp")]
    if not named:
        plain = [word for at, word in enumerate(rest)
                 if not word.startswith("-") and not (at and rest[at - 1].startswith("-"))]
        named = plain[1:2]
    return len(named) == 1 and not _GLOB.search(named[0])


def _lists_all(program: str, rest: list[str]) -> bool:
    """Whether a lister goes into every folder below: `gci -r`, `-Recurse`, `dir /s`, `ls -R`."""
    return program == "find" or program in _LISTERS and any(
        "-recurse".startswith(word.lower()) and len(word) > 1 or word.lower() == "/s"
        or word.lower().startswith("-dep")  # (`-Depth 9`: as deep as it is told)
        or _cluster(word, "R") for word in rest)


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
    "rg": (frozenset({
        "-i", "--ignore-case", "-S", "--smart-case", "-s", "--case-sensitive", "-n",
        "--line-number", "-N", "--no-line-number", "-l", "--files-with-matches",
        "--files-without-match", "-c", "--count", "--count-matches", "-w", "--word-regexp", "-x",
        "--line-regexp", "-v", "--invert-match", "-F", "--fixed-strings", "-P", "--pcre2", "-U",
        "--multiline", "--multiline-dotall", "-o", "--only-matching", "-.", "--hidden", "-u",
        "--unrestricted", "--no-ignore", "--no-ignore-vcs", "--no-ignore-dot", "--no-ignore-global",
        "--no-ignore-parent", "--no-ignore-exclude", "--no-ignore-files", "--no-heading",
        "--heading", "-H", "--with-filename", "-I", "--no-filename", "--vimgrep", "--json", "-q",
        "--quiet", "--column", "--no-column", "-a", "--text", "--trim", "-b", "--byte-offset",
        "-0", "--null", "--stats", "--no-config", "-p", "--pretty", "--line-buffered",
        "--block-buffered", "--binary", "--no-binary", "--crlf", "--no-messages", "--no-unicode",
        "--include-zero", "--no-require-git", "--one-file-system", "--no-follow", "--passthru",
        "--sort-files"}), frozenset({
        "-e", "--regexp", "-g", "--glob", "--iglob", "-t", "--type", "-T", "--type-not",
        "--type-add", "-A", "--after-context", "-B", "--before-context", "-C", "--context", "-m",
        "--max-count", "-d", "--max-depth", "-M", "--max-columns", "-j", "--threads", "--color",
        "--colors", "--sort", "--sortr", "-E", "--encoding", "--max-filesize", "-r", "--replace",
        "--path-separator", "--context-separator", "--engine"}), False),
    "grep": (frozenset({
        "-r", "--recursive", "-n", "--line-number", "-i", "-y", "--ignore-case",
        "--no-ignore-case", "-v", "--invert-match", "-w", "--word-regexp", "-x", "--line-regexp",
        "-c", "--count", "-l", "--files-with-matches", "-L", "--files-without-match", "-o",
        "--only-matching", "-q", "--quiet", "--silent", "-s", "--no-messages", "-H",
        "--with-filename", "-h", "--no-filename", "-b", "--byte-offset", "-a", "--text", "-I",
        "-E", "--extended-regexp", "-F", "--fixed-strings", "-G", "--basic-regexp", "-P",
        "--perl-regexp", "-z", "--null-data", "-Z", "--null", "-T", "--initial-tab", "-U",
        "--binary", "--color", "--colour", "--line-buffered", "--no-group-separator"}), frozenset({
        "-e", "--regexp", "-m", "--max-count", "-A", "--after-context", "-B", "--before-context",
        "-C", "--context", "-d", "--directories", "-D", "--devices", "--include", "--exclude",
        "--exclude-dir", "--label", "--group-separator", "--binary-files"}), False),
    "git grep": (frozenset({
        "-n", "--line-number", "-i", "--ignore-case", "-I", "-v", "--invert-match", "-w",
        "--word-regexp", "-l", "--files-with-matches", "--name-only", "-L",
        "--files-without-match", "-c", "--count", "-h", "-H", "-o", "--only-matching", "-q",
        "--quiet", "-E", "--extended-regexp", "-F", "--fixed-strings", "-G", "--basic-regexp",
        "-P", "--perl-regexp", "--cached", "--untracked", "--exclude-standard",
        "--no-exclude-standard", "--full-name", "--heading", "--break", "--column", "-p",
        "--show-function", "-W", "--function-context", "--and", "--or", "--not", "--all-match",
        "-a", "--text", "-r", "--recursive", "--no-recursive", "-z", "--null", "--color",
        "--no-color", "--recurse-submodules", "--no-textconv"}), frozenset({
        "-e", "-m", "--max-count", "-A", "--after-context", "-B", "--before-context", "-C",
        "--context", "--max-depth", "--threads"}), False),
    "select-string": (frozenset({
        "-simplematch", "-casesensitive", "-allmatches", "-notmatch", "-quiet", "-list", "-raw",
        "-noemphasis"}), frozenset({
        "-pattern", "-path", "-literalpath", "-lp", "-pspath", "-include", "-exclude",
        "-encoding", "-context", "-culture"}), True),
    "lister": (frozenset({
        "-recurse", "-rec", "-r", "-file", "-force", "-name", "-directory", "-hidden", "-readonly",
        "-system", "-af", "-ad", "-ah"}), frozenset({
        "-path", "-literalpath", "-lp", "-include", "-exclude", "-depth"}), True),
}
# A search's pattern, quoted - after `-Pattern`, `-e`/`-E`, `--regexp`, or as the first word of
# rg's, grep's or Select-String's past their flags (`rg -n "a|b"`) - holds no `|` or `;` that
# chains. Only these: a quoted script a shell is handed (`bash -lc "a | b"`) does chain.
_QUOTED_VALUE = re.compile(
    r"""(?i)(?<![\w-])((?:-pattern|-e|--regexp|(?:rg|grep|egrep|fgrep|sls|select-string)"""
    r"""(?:\s+-[\w-]+)*)\s+)("[^"]*"|'[^']*')""")
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
    r"""|warningvariable|wv|informationvariable|iv|pipelinevariable|pv)(?![\w-])|\.value\b""")
_CD = frozenset({"cd", "sl", "chdir", "pushd", "push-location", "set-location", "popd",
                 "pop-location"})


def _known_values(command: str) -> dict[str, str]:
    """The variables a line assigns a literal path once and nothing else, by their name in lower
    case; none where something else may set one (`_SETS_VARIABLES`)."""
    if _SETS_VARIABLES.search(command):
        return {}
    named = [(a or b).casefold() for a, b in _ASSIGNS.findall(command)]
    return {name: path for a, b, _quote, path in _ASSIGNED_PATH.findall(command)
            if named.count(name := (a or b).casefold()) == 1}


def _unquoted(word: str) -> str:
    return word[1:-1] if len(word) > 1 and word[0] == word[-1] and word[0] in "'\"" else word


def _plain(raw: str, base: Path | None, root: Path | None) -> str | None:
    """A path word of a search as the folder's own path to it (`root`'s, from `base`, where it
    runs), or None for one that is not a plain literal inside it: a variable left, a bracket, a
    backtick, a brace, `%`, pathspec magic (`:`), a trailing dot or space (Windows drops them),
    `..`, a root, a drive or `~`; a wildcard in a short name's place (`*~1`); or - with `root` -
    one not there, or that leads out of it (a link)."""
    word = _unquoted(raw)
    if (not word or re.search(r"[$(){}`%@;]", word) or word.startswith(":")
            or word.endswith(" ") or len(word) > 1 and word.endswith(".") and word[-2] not in "/\\"
            or _outside(word)):
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
            plain += words[at + 1:]
            break
        if not word.startswith("-") or len(word) < 2:
            plain.append(words[at])
        elif (given := key.partition(":" if ps else "=")) and given[1] and (
                given[0] in valued or given[0] in flags):
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
                if word[spot + 1:]:
                    values.append((f"-{letter}", word[spot + 1:]))
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


def _scope(kind: str, words: list[str], base: Path | None, root: Path | None,  # noqa: C901
           handed: Scope) -> Scope:
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
        paths = [value for name, value in values if name in ("-path", "-literalpath", "-lp",
                                                                 "-pspath")]
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
    raw = _VAR_RE.sub(lambda found: known.get((found[1] or found[2]).casefold(), found[0]),
                      command)
    raw = _QUOTED_VALUE.sub(lambda found: found[1] + re.sub(r"[|;&<>]", " ", found[2]),
                            re.sub(r"\d?>&\d", " ", raw))
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
    lost = lost or any(_program(word.strip("{(")) in _CD for part in raws[::2]
                       for word in _words(part.strip())[1:])
    for part, written, before in zip(pieces[::2], raws[::2], ["", *pieces[1::2]], strict=True):
        words, fed = _words(part.strip()), False
        given = _words(written.strip())
        handed_list, lists = (lists if before == "|" else None), None
        handed_names, lister = (lister if before == "|" else False), False
        # shortcut: only what it runs were its wrappers' unknown options to take no value
        # (`_unwrapped`'s first); judge the others too if a search is met hidden so.
        handed = _unwrapped(words)[0]
        wrapped = len(handed) < len(words)
        fed = any(_program(w) == "xargs" for w in words[:len(words) - len(handed)])
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

        def scope(kind: str, words: list[str] = given[1:], base: Path | None = base,
                  handed: Scope = handed_list, known: bool = known_words) -> Scope:
            return _scope(kind, words, base, root, handed) if known else None

        # (a listing handed to it in brackets: `gc (gci -r -File)`)
        handed = any(_program(w) in _LISTERS and _lists_all(_program(w), rest[at + 1:])
                     for at, w in enumerate(rest))
        # Only names (`rg --files`): a list, as `gci -r` is. A Select-String given no file
        # reads what the pipe hands it: only text where all before it make text alone
        # (`curl ... | sls`), else maybe files (`gci | sls`, `gi * | sls`).
        names = program in _SEARCHERS and "--files" in rest
        piped = before == "|" and texts
        grep = program == "git" and _after_options(rest, _GIT_VALUE_OPTIONS)[:1] == ["grep"]
        if program in ("rg", "ripgrep") and not names:
            found.append(scope("rg"))
        elif program in _GREPS and not fed and any(
                _cluster(w, "r") or _cluster(w, "R") or w.startswith("--") and "recurs" in w
                or w == "recurse" and rest[at - 1:at] in (["-d"], ["--directories"])
                for at, w in enumerate(rest)):
            found.append(scope("grep"))
        elif grep:
            # (git told anything before its grep - `-C ..`, `--git-dir` - asks)
            found.append(scope("git grep", given[2:]) if given[1:2] == ["grep"] else None)
        elif (program in _SEARCHERS and not names
              or program == "findstr" and any(re.fullmatch(r"/[a-z]*s[a-z]*", w, re.I)
                                              for w in rest)
              or program in _READERS and (fed or handed)
              or program == "find" and any(_program(w) in _READERS for w in rest)):
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
            program in _TEXTS or bool(_INTERPRETER.fullmatch(program)) or program in _GETS)
    return found


# What only reads or lists what it is named (`more` and `less` wait for a key); and git's.
_LOOKERS = frozenset({*_READERS, *_LISTERS, "pwd", "get-location", "test-path"}
                     - {"more", "less"})
_GIT_LOOKS = frozenset({"status", "diff", "log", "show"})


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
    if (not is_plain(command) or is_wrapped(command) or _in_a_shell(command)
            or _harm(command) or searches_folder(command)):
        return False
    words = [word.strip("'\"") for word in _words(command.strip())]
    # (one by its path - `.\cat` - is a program of the folder's own, which an agent can write)
    if not words or re.search(r"[\\/]", words[0]):
        return False
    program, rest = _program(words[0]), words[1:]
    if program == "git":
        # (Whole names: git's diff options are not taken cut short - `--outp` is refused, `--text`
        # is its own and only reads.)
        looks = bool(rest) and rest[0] in _GIT_LOOKS and not any(
            word.startswith(("--output", "--ext-diff", "--textconv")) for word in rest)
        pieces = [piece for word in rest for piece in re.split(r"[=:,]", word)]  # (`HEAD:a.py`)
    else:
        looks = program in _LOOKERS and not _lists_all(program, rest) and not (
            # (one that follows a file runs on, as a server does: asked, as one is)
            program == "tail" and any(w.startswith(("-f", "-F", "--f")) for w in rest)
            or program in ("get-content", "gc", "type", "cat")
            and any(w.lower().startswith("-wa") for w in rest))
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
    return _reads(command) or is_plain(command) and bool(words) and (
        _program(words[0]) in _LOOKERS | _SEARCHERS)


def reads_here(command: str, root: Path, at_root: bool) -> bool:
    """Whether a command runs unasked below Full auto (`only_reads`): git's only at the root
    of the folder it works in (a repository shaped in a folder below could set what git
    runs) and while that folder holds no secret file - its diff, log and show print a
    committed one's lines without naming it. shortcut: a gitignored .env cards git too;
    ask `git ls-files` if that is met. Blocking: call it off the event loop."""
    if not only_reads(command):
        return False
    return _program(_words(command.strip())[0]) != "git" or at_root and secret_held(root) is None


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
                    inside = next((n for n, part in enumerate(parts[:-1])
                                   if part.casefold() in SECRET_FOLDERS), None)
                    found.append(rel if inside is None else "/".join(parts[:inside + 1]))
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
    (`_reaches`); one whose scope is not read off the line reaches every one."""
    if not (scopes := _search_scopes(command, root, cwd)) or not (
            secrets := secret_files(root)):
        return ""
    held = next((secret for secret in secrets if any(
        scope is None or _reaches(scope, secret, root) for scope in scopes)), None)
    return "" if held is None else (
        f"it searches the whole folder, and the folder holds a secret file ({held}) - "
        "asked at every level")


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
    kept = not globs or is_dir or any(
        fnmatch.fnmatch(tail, glob) or fnmatch.fnmatch(parts[-1], glob)
        for glob in globs for tail in tails)
    for raw_path in paths:
        if _outside(raw_path):
            return True
        path = posixpath.normpath(raw_path.replace("\\", "/")).strip("/")
        if path in ("", ".") and kept:
            return True
        if kept and any(tail == path or tail.startswith(path + "/") or path.startswith(tail + "/")
                        or fnmatch.fnmatch(tail, path) or fnmatch.fnmatch(tail, path + "/*")
                        for tail in tails):
            return True
    return False


# A variable whose name has one of these parts (split at "_"), or a part that ends in KEY,
# TOKEN or SECRET, holds a secret: its value is hidden in a command's output.
_SECRET_PARTS = frozenset({
    "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "CREDENTIALS", "AUTH", "PRIVATE",
    "COOKIE", "SESSION", "DSN",
})
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
    r"(-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----)[\s\S]*?(-----END [A-Z0-9 ]*PRIVATE KEY-----)")
# A value given to a name that says it is a secret - `aws_secret_access_key = ...`,
# `"password": "..."`, `api_key: ...` - of MIN_SECRET characters or more (`max_tokens = 4096`
# is no secret).
# The name starts only where a word starts, and is at most 64 characters each side: an
# unbounded `[\w.-]*` tried again from every character took hours on one long line of output.
_ASSIGNED = re.compile(
    r"""((?<![\w.-])["']?[\w.-]{0,64}?(?:password|passwd|pwd|secret|token|api[_-]?key"""
    r"""|access[_-]?key|private[_-]?key|credential)[\w.-]{0,64}["']?[ \t]*[:=][ \t]*["']?)"""
    r"""[^\s"'`,;]{8,}""",
    re.IGNORECASE)
# ...but not a variable whose name ends in one of these: it names a place or a kind, and
# an address of it must stay readable (`AUTH_URL=http://localhost:3000`).
# shortcut: a secret kept in such a one (`APP_ID`, `X_URL`) is hidden only by its shape or as
# an address's password; name the variable here if one turns up.
_NOT_SECRET_LAST = frozenset({
    "URL", "HOST", "HOSTNAME", "DOMAIN", "PATH", "DIR", "SOCK", "ID", "MODE", "TYPE", "DRIVER",
})
# How much of a line without its end is held back before it is let out anyway.
# shortcut: a secret that straddles this cut, on a line longer than it, is not hidden;
# keep the last secret's length back too if one turns up there.
HELD_AT_MOST = 4096


def secret_name(name: str) -> bool:
    """Whether a variable holds a secret by its name."""
    parts = name.upper().split("_")
    return parts[-1] not in _NOT_SECRET_LAST and any(
        part in _SECRET_PARTS or part.endswith(("KEY", "TOKEN", "SECRET")) for part in parts)


def secret_values(env: Mapping[str, str]) -> list[str]:
    """The values in an environment that are secrets by their variable's name."""
    return [value for name, value in env.items()
            if secret_name(name) and isinstance(value, str) and len(value) >= raw.MIN_SECRET]


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
    return (rest.rsplit("_", 1)[-1] not in ("FILE", "HELPER")
            and rest != "GOOGLE_APPLICATION_CREDENTIALS" and secret_name(rest))


def held_back(env: Mapping[str, str], passed: str | None = None) -> list[str]:
    """The names of the secret variables a command is not given (slice 103, `_withheld`):
    all but those the user passes (`Project.pass_env`, comma-separated, in any case) - and
    KOLONİ's own, which no command is given whatever it says."""
    given = {name.strip().upper() for name in (passed or "").split(",")}
    return sorted(name for name in env if _withheld(name) and name.upper() not in given
                  and not name.upper().startswith("KOLONI_"))


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
        command and CANARY in text.upper())


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
    text = _TOKENS.sub(lambda found: found.group() if any(
        sample in found.group() for sample in SAMPLE_KEYS) else raw.HIDDEN, text)
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


def is_allowed(command: str, prefixes: Iterable[str]) -> bool:
    return any(matches(command, prefix) for prefix in prefixes)


# K-gecmis-zengin: said beside an output that was cut, or left out of a history to fit - its
# call's id, which recall_output gives the whole of (`AgentRunner._recall_output`).
RECALL_HINT = " (full: recall_output id={id})"


def recallable(name: str, outside_folder: str | None, why_asked: str | None,
               command: str | None) -> bool:
    """Whether recall_output gives a call's output again (and its id is said): not what the
    memory held then (`memory.looked_up_earlier`), nor what was read on the user's word, for
    that once - outside the project, a secret file, a command that names one."""
    return name != "recall" and not outside_folder and not (
        why_asked if command is None else names_secret(command))


def for_model(output: str, call_id: str | None = None) -> str:
    """Command output as the model sees it: whole if short, else its start and end - and, with
    its call's id, where the whole of it is."""
    if len(output) <= MODEL_HEAD + MODEL_TAIL:
        return output
    omitted = len(output) - MODEL_HEAD - MODEL_TAIL
    hint = RECALL_HINT.format(id=call_id) if call_id else ""
    return (f"{output[:MODEL_HEAD]}\n[… {omitted} characters omitted …]{hint}\n"
            f"{output[-MODEL_TAIL:]}")


# What sends work or data off this machine - asked in a job while the user is away (slice 106),
# whatever the chat's level: a word that pushes, publishes, uploads, deploys or mails anywhere in
# it (`npm --prefix x publish`, `docker buildx build --push`; not `git stash push`), a program
# that only moves things elsewhere, and any request from the command line - whatever it asks,
# what it sends is not seen (a GET carries a file in its address as well as a POST in its body).
# shortcut: words and programs, not a sandbox: a script that uploads, or a program not listed
# here, is not seen; add what the user meets.
_SENDING_WORDS = frozenset({"push", "publish", "upload", "deploy", "send-email"})
_SENDING_PROGRAMS = frozenset({
    "scp", "sftp", "ftp", "rsync", "rclone", "aws", "az", "gsutil", "gcloud", "gh", "nc", "ncat",
    "netcat", "socat", "kubectl", "terraform", "helm", "vercel", "netlify", "flyctl", "heroku",
    "firebase", "send-mailmessage", "curl", "wget", "invoke-webrequest", "iwr",
    "invoke-restmethod", "irm",
})
# What installs into the dependency folders a working copy shares with the project
# (node_modules, .venv): through the link it writes the project's own.
_INSTALLERS = {
    "pip": {"install", "uninstall"}, "pip3": {"install", "uninstall"},
    "uv": {"sync", "add", "remove", "pip"}, "npm": {"install", "i", "ci", "add", "uninstall"},
    "pnpm": {"install", "i", "add", "remove"}, "yarn": {"install", "add", "remove"},
    "poetry": {"install", "add", "remove"}, "bun": {"install", "i", "add", "remove"},
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
_CURL_SENDS = re.compile(r"(?:^|\s)(?:-[^-\s]*[dTF]|--(?:data|form|upload-file|json)"
                         r"|(?:-[^-\s]*X|--request)(?!\s*=?\s*(?:GET|HEAD)\b))")
# With `-G` / `--get` curl puts its `-d` data in the address: a GET, unless a file or a verb.
_CURL_GET = re.compile(r"(?:^|\s)(?:-[^-\s]*G|--get\b)")
_CURL_GET_SENDS = re.compile(r"(?:^|\s)(?:-[^-\s]*[TF]|--(?:form|upload-file)"
                             r"|(?:-[^-\s]*X|--request)(?!\s*=?\s*(?:GET|HEAD)\b))")
_WGET_SENDS = re.compile(r"(?:^|\s)--(?:post-|body-|method(?!\s*=?\s*(?:GET|HEAD)\b))", re.I)
_PS_SENDS = re.compile(
    r"(?:^|\s)-(?:body|infile|form|(?:custom)?method(?![:\s]*(?:get|head)\b))", re.I)
_FETCHERS = {"curl": _CURL_SENDS, "wget": _WGET_SENDS, "invoke-webrequest": _PS_SENDS,
             "iwr": _PS_SENDS, "invoke-restmethod": _PS_SENDS, "irm": _PS_SENDS}
# Security review 0.1.0: long options are spelt out before those read a line, as the programs
# take one cut short (`-InF`, `-Me Post`, `--meth`, `--upload-f`): to the first name it starts
# (an ambiguous one the program refuses, so that only over-asks).
_SPELT = {"curl": ("--", ("data", "data-ascii", "data-binary", "data-raw", "data-urlencode",
                          "form", "form-string", "upload-file", "json", "request", "get")),
          "wget": ("--", ("post-data", "post-file", "body-data", "body-file", "method")),
          **dict.fromkeys(_PS_FETCHERS, ("-", ("infile", "body", "form", "method",
                                               "custommethod")))}


def _spelt(word: str, dash: str, names: tuple[str, ...]) -> str:
    """A long option cut short, spelt out (`-InF:x` is `-infile:x`); any other word as it is."""
    found = re.match(r"-+([A-Za-z][\w-]*)(.*)", word, re.S) if word.startswith(dash) else None
    full = found and next((name for name in names if name.startswith(found[1].casefold())), None)
    return f"{dash}{full}{found[2]}" if found and full else word
_GH_READS = frozenset({"list", "view", "status", "api", "checkout", "diff", "checks", "clone",
                       "download", "search", "browse"})
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
    line = " ".join(_spelt(word, *_SPELT[program]) if program in _SPELT else word
                    for word in words[1:])
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
    seen; Ask and Auto-edit are the wall (and `runs_another` at night)."""
    return danger(command, instructions) or next((
        said for words in _commands_in(command, at=_BLOCKS) if words and (
            said := danger(" ".join(words), instructions) or (
                "" if _only_fetches(words) else _sends(words)))), "")


# K-r147 (live): what a pipe may hand a command's output to, at night too - it only picks,
# counts, sorts or lays out the text, and runs nothing it is handed (`_filters`).
_FILTERS = _SINKS | {"where-object", "where", "?", "head", "tail", "grep", "egrep", "fgrep",
                     "findstr", "wc", "more"}
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
        return not any(_cluster(word, "o") or _cluster(word, "T") or word.casefold().startswith(
            ("--o", "/o", "--co", "--t")) for word in said)
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
        if is_wrapped(first) or _in_a_shell(first) or stages and (
                renames or not all(map(_filters, stages))) or any(  # (in a block: `(cmd /c x)`)
                is_wrapped(piece) or _in_a_shell(piece) for piece in _BLOCKS.split(part)):
            return ANOTHER
    return ""


# K-r135: an interpreter handed its code on the line, quoted or not (`python -c "..."`, `node
# -e`, `ruby -e`, `perl -e`, `deno eval`) - by the program's name, its path too, as
# `_INLINE_CODE` finds it (not `deploy.py -c`, `pytest -c x.ini`). A shell's `-Command` is
# `runs_another`'s. shortcut: a script the agent itself wrote runs unasked in a backlog turn;
# card interpreters running a just-written file if that is seen live.
_INLINE = re.compile(
    r"""(?i)(?:^|(?<=[\s;&|(]))(?:\S*[\\/])?(?:(?:python|py|node|ruby|perl|php|bun)[\d.]*w?"""
    r"""(?:\.exe)?\s+(?:-\w+\s+)*?(?:-c|-e|-p|--eval|--print)|deno(?:\.exe)?\s+eval)"""
    r"""(?=\s|$)""")


def runs_inline(command: str) -> str:
    """Why a command runs code written on its line (`_INLINE`), in one sentence; "" for none."""
    return ("It runs code written on the line: what it does is not seen."
            if _INLINE.search(command) else "")


def installs(command: str) -> str:
    """Whether a part of a command installs or removes packages (`pip install`, `npm i`,
    `python -m pip install`), in one sentence; "" for none."""
    for words in _parts(command):
        if words[:1] and _program(words[0]).startswith("python") and words[1:3] == ["-m", "pip"]:
            words = words[2:]
        rest = [w.lower() for w in words[1:] if not w.startswith("-")]
        if words and rest[:1] and rest[0] in _INSTALLERS.get(_program(words[0]), ()):
            return ("It installs or removes packages: in a working copy its dependency folders "
                    "are the project's own, linked in.")
    return ""


# What reaches the internet from a command (K-web-komut): `_SENDING_PROGRAMS` and these, as
# whole words anywhere in the line - inside `powershell -Command "..."` too, but not as a part
# of a path or a file's name (`tests/aws/x.py`, `docs/curl.md`) - by a program's path where a
# part runs it (`C:\Windows\System32\curl.exe`), .NET's web classes, or an address.
# shortcut: words, not a parser or a sandbox: a script that fetches, an alias, a variable or an
# encoded command is not seen; `curl localhost`, `pip uninstall`, `git submodule status` and a
# word in a message (`git commit -m "nc"`) are carded too. The real cut is Docker's `--network
# none`, or K-yazma-denetimi's research for this machine.
_NET_PROGRAMS = _SENDING_PROGRAMS | {
    "ssh", "telnet", "start-bitstransfer", "test-netconnection", "tnc", "winget", "choco",
    "scoop", "install-module", "install-package", "save-module"}
_NETWORK = re.compile(
    r"(?<![\w\\/-])(?:" + "|".join(map(re.escape, sorted(_NET_PROGRAMS, key=len, reverse=True)))
    + r")(?![\w\\/-]|\.(?!exe\b)\w)"
    r"|\bnet\.(?:webclient|httpwebrequest|webrequest|http|sockets)\b"
    r"|\b(?:https?|ftp)://[^\s'\"`]*", re.IGNORECASE)
_GIT_REACHES = frozenset({"clone", "fetch", "pull", "push", "ls-remote", "submodule", "lfs"})
# Windows' own tools that download only with these switches (`certutil -hashfile` stays).
_DOWNLOAD_SWITCHES = {"certutil": {"urlcache", "verifyctl"}, "bitsadmin": {"transfer", "addfile"}}
WEB_OFF = ("web is off on the Tools page ({tool} is off); this command reaches the internet: "
           "{what} - asked at every level")


def _commands_in(command: str, left: list[int] | None = None,
                 at: re.Pattern = _PARTS) -> list[list[str]]:
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
            else:
                found.append(handed)
    return found


def reaches_network(command: str) -> str:
    """What in a command reaches the internet - a program, an address, a git fetch, a package
    install or download, or a word that publishes (`npm publish`, `docker push`); "" for none."""
    if found := _NETWORK.search(command):
        return found[0]
    for words in (words for words in _commands_in(command) if words):
        program, sub = _program(words[0]), _git_sub(words)[0]
        said = {word.lower().lstrip("-") for word in words[1:]}
        if program in _NET_PROGRAMS or _DOWNLOAD_SWITCHES.get(program, set()) & {
                word.lower().lstrip("-/") for word in words[1:]}:
            return program
        if sub in _GIT_REACHES:
            return f"git {sub}"
        if installs(" ".join(words)) or program in ("pip", "pip3") and "download" in said:
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
