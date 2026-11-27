"""What keeps a line a read, and what makes one that looks like a lone search or a look do more -
beside `app.commands`, which is at its size limit. Claude Code's own exceptions to its read-only
list among them (the comparison of the CLIs' rules, 27 Nov 2026)."""

import os
import re
from pathlib import Path

# B-316: what a pipe may hand a read's text to that only picks, sorts, counts or lays it out,
# writing nothing (not `sort`: sort.exe's `/o` and `sort -o` write a file).
SINKS = frozenset(
    {"select-object", "select", "select-string", "sls", "sort-object", "measure-object"}
    | {"out-string", "ft", "fl", "fw"}
)
# What a search may be told that writes or runs something: find's actions, rg's preprocessor and
# its replace and hostname program, ag's/ack's pager (`-r` is rg's and ag's replace, grep's not).
SEARCH_DOES = re.compile(
    r"(?i)-exec|-execdir|-ok|-okdir|-delete|-fprint0?|-fprintf|-fls"
    r"|--pre(?:=.*)?|--replace(?:=.*)?|--pager(?:=.*)?|--hostname-bin(?:=.*)?"
)
# A connection bash (and ksh) opens where a redirection names one of these - `cat <
# /dev/tcp/host/80`, `exec 3<>/dev/udp/host/53`: the internet, with no program's name in the line;
# and a part after `/dev/` the shell builds as it runs (`/dev/$t/h/80`, `$'/dev/tc\x70/h/80'`).
NET_PATH = re.compile(
    r"(?<![\w./~-])/dev/(?:(?:tcp|udp)/|[^\s;&|<>()/]*[$\\`])[^\s;&|<>()]*", re.IGNORECASE
)
# What sh expands in a word: a wildcard, and a brace (`{a,-}*`).
_EXPANDS = frozenset("*?[{")
# `git submodule`'s verbs that rewrite `.git/config` as they work (`update` with `--init`), and
# of them those that write `.gitmodules` too. Never `foreach` (it runs any command), `status`,
# `summary` nor a bare `git submodule`.
_SUBMODULE_CONFIG = frozenset({"add", "init", "sync", "set-url", "set-branch", "deinit"})
_SUBMODULE_GITMODULES = frozenset({"add", "set-url", "set-branch"})


def globs_an_option(line: str) -> bool:
    """Whether a word of a line holds a wildcard sh expands - not quoted, not after a backslash
    - that may expand to an option of its program: with nothing before it in the word (`*`,
    `*.py`, `''*`), or after an option's name it may finish (`-*`, `--p*`; not `--glob=*.py`,
    whose name is fixed). In a folder holding a file named `-delete` or `--pre=x`, `find *` is a
    delete and `rg foo *` runs a program (Claude Code asks of such a glob too). `src/*.py`, `./*`
    and a quoted `'*.py'` expand to no option.
    shortcut: read by sh's quotes and backslash - in PowerShell, which hands a program its `*` as
    it is, such a line is no read either; tell its lines apart if that is met often."""
    before, quote, chars = "", "", iter(line)
    for char in chars:
        if char == quote:
            quote = ""
        elif quote == '"' and char == "\\":
            before += next(chars, "")  # (sh's `\"` in double quotes: no end of them)
        elif quote:
            before += char
        elif char in "'\"":
            quote = char
        elif char.isspace() or char in ";&|<>()":
            before = ""  # (a word of its own starts)
        elif char == "\\":
            before += next(chars, "").strip("\r\n")  # (before a line break: the line goes on)
        elif char in _EXPANDS and (not before or before[0] == "-" and "=" not in before):
            return True
        else:
            before += char
    return False


def chained(line: str) -> bool:
    """Whether a line holds `;`, `&` or a line break outside quotes: one more command after it.
    Quotes as sh and PowerShell read them, the shells a bare line runs in - `'…'` and `"…"`, a
    quote after a backslash none (sh's `\\"`); a backslash before `;` keeps it a `;` (PowerShell's).
    shortcut: cmd keeps no `'` quote - a line it runs comes as `cmd /c …`, whose program is no
    search, and its script is split at every `&` before it is read (`_script`); a line run in
    cmd with no `cmd /c` would be misread here."""
    quote, at = "", 0
    while at < len(line):
        char = line[at]
        if quote:
            quote = "" if char == quote else quote
        elif char == "\\" and line[at + 1 : at + 2] in ("'", '"'):
            at += 1
        elif char in "'\"":
            quote = char
        elif char in ";&\r\n":
            return True
        at += 1
    return False


def looks_bare(root: Path) -> bool:
    """Whether a folder with no `.git` has a bare repository's shape - a `HEAD` file and an
    `objects/` folder: git takes it for a repository, whose config an agent could have written
    (no `.git` name to ask of). Blocking: a look at the disk."""
    return (
        not os.path.lexists(root / ".git")
        and (root / "HEAD").is_file()
        and (root / "objects").is_dir()
    )


def submodule_writes(rest: list[str]) -> frozenset[str]:
    """What of git's own files a `git submodule` line (its words past `submodule`) rewrites as it
    works, for the write audit to let stand: `.git/config`, and `.gitmodules` for `add`,
    `set-url`, `set-branch`; nothing for `foreach`, `status`, `summary` or a bare one."""
    verb = next((word for word in rest if not word.startswith("-")), None)
    if verb in _SUBMODULE_GITMODULES:
        return frozenset({".git/config", ".gitmodules"})
    if verb in _SUBMODULE_CONFIG or verb == "update" and "--init" in rest:
        return frozenset({".git/config"})
    return frozenset()
