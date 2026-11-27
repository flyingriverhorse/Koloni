"""What keeps a line a read, and what makes one that looks like a lone search or a look do more -
beside `app.commands`, which is at its size limit. Claude Code's own exceptions to its read-only
list among them (the comparison of the CLIs' rules, 27 Nov 2026)."""

import os
import re
from collections.abc import Callable
from pathlib import Path

# B-316: what a pipe may hand a read's text to that only picks, sorts, counts or lays it out,
# writing nothing (not `sort`: sort.exe's `/o` and `sort -o` write a file).
SINKS = frozenset(
    {"select-object", "select", "select-string", "sls", "sort-object", "measure-object"}
    | {"out-string", "ft", "fl", "fw"}
)
# What a search may be told that writes or runs something: find's actions, rg's preprocessor and
# its replace and hostname program, ag's/ack's pager (`--pag` too: they take it cut short) and
# ack's `--output`, which ack 2.x runs as Perl (`-r` is rg's and ag's replace, grep's not).
SEARCH_DOES = re.compile(
    r"(?i)-exec|-execdir|-ok|-okdir|-delete|-fprint0?|-fprintf|-fls|--output(?:=.*)?"
    r"|--pre(?:=.*)?|--replace(?:=.*)?|--pag(?:e|er)?(?:=.*)?|--hostname-bin(?:=.*)?"
)
# A connection bash (and ksh) opens where a redirection names one of these - `cat <
# /dev/tcp/host/80`, `exec 3<>/dev/udp/host/53`: the internet, with no program's name in the line;
# and a part after `/dev/` the shell builds as it runs (`/dev/$t/h/80`, `$'/dev/tc\x70/h/80'`).
NET_PATH = re.compile(
    r"(?<![\w./~-])/dev/(?:(?:tcp|udp)/|[^\s;&|<>()/]*[$\\`])[^\s;&|<>()]*", re.IGNORECASE
)
# What sh expands in a word: a wildcard, and a brace (`{a,-}*`).
_EXPANDS = frozenset("*?[{")
# git's own commands that rewrite `.git/config` in their ordinary work: a remote, a branch's
# upstream, a new repository (K-yazma-denetimi lets that stand: `git_writes`).
_CONFIG_WRITERS = frozenset({"init", "remote", "branch", "checkout", "switch"})
# `git submodule`'s verbs that rewrite `.git/config` as they work (`update` with `--init`), and
# of them those that write `.gitmodules` too. Never `foreach` (it runs any command), `status`,
# `summary` nor a bare `git submodule`.
_SUBMODULE_CONFIG = frozenset({"add", "init", "sync", "set-url", "set-branch", "deinit"})
_SUBMODULE_GITMODULES = frozenset({"add", "set-url", "set-branch"})
# git commands that run a command they are handed with an option: its long name and its letter.
_HANDS_ON = {
    "rebase": ("--exec", "x"),
    "difftool": ("--extcmd", "x"),
    "grep": ("--open-files-in-pager", "O"),
}


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


def chained(line: str, handed: bool = False) -> bool:
    """Whether a line holds a `;`, `&` or line break that may end a command and start another:
    any of them - but in a simple line, one inside its quotes (`bare`: `rg '&&' .github`).
    shortcut: the simple line alone - a quoted `;` in any other line is a card; tell more lines
    apart if that is met often. cmd keeps no `'` quote: a line it runs comes as `cmd /c …`, whose
    program is no search, and what it hands on is `handed` (`bare`)."""
    return bool(re.search(r"[;&\r\n]", bare(line, handed)))


_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")


def bare(line: str, handed: bool = False) -> str:
    """A simple line with each `'…'` and `"…"` blanked, its quotes too (`_` for each character):
    what is left is what sh and PowerShell (the shells a bare line runs in) both read out of
    quotes; any other line as it is. Simple: no backslash, backtick or `$` (sh does not end `"…"`
    at a backslash's `"`; in PowerShell a backslash before `'` escapes nothing, so the `'` opens
    a quote), no `#` (out of quotes it starts a comment, and a quote in that is none), no line
    break, nothing past ASCII (PowerShell's typographic quotes are quotes too), every quote
    paired - and not `handed` on to a shell (`cmd /c "…"`, `bash -c '…'`: cmd keeps no `'`
    quote, and a `>` in it writes)."""
    if handed or re.search(r"[\\`$#\r\n]|[^\x00-\x7f]", line):
        return line
    blank = _QUOTED.sub(lambda found: "_" * len(found[0]), line)
    return line if re.search("['\"]", blank) else blank  # (a quote not paired: no simple line)


def split(at: re.Pattern, line: str, whole: Callable[[str], bool]) -> list[str]:
    """`at.split(line)` - but a piece of it cut only inside a simple line's quotes (`bare`) is
    one where it is `whole` (a lone search, `commands.only_searches`: `rg 'a|b' .github`, E12).
    A quoted word is a line again to a shell, a wrapper, `ssh` or `gdb -ex`, and cmd keeps no
    `'` quote: no other piece is kept whole, nor one of a line handed on (`commands._parts`)."""
    cuts = [0, *(end for found in at.finditer(bare(line)) for end in found.span()), len(line)]
    pieces = (line[start:end] for start, end in zip(cuts[::2], cuts[1::2], strict=True))
    return [
        one
        for piece in pieces
        for one in (at.split(piece) if at.search(piece) and not whole(piece) else [piece])
    ]


def rejoined(words: list[str]) -> str:
    """A part's words (`split`) as a line again, a word that holds a separator or a bracket
    quoted as it was - not chained: `rg "&&" .github`."""
    return " ".join(
        (f"'{word}'" if '"' in word else f'"{word}"') if re.search(r"[;&|(){}]", word) else word
        for word in words
    )


def looks_bare(root: Path) -> bool:
    """Whether a folder with no `.git` holds a `HEAD`: git may take it for a repository of its
    own - a bare one, one whose `objects` is a file, or whose `commondir` leads elsewhere -,
    whose config an agent could have written (no `.git` name to ask of). Blocking: a look at
    the disk."""
    return not os.path.lexists(root / ".git") and os.path.lexists(root / "HEAD")


def git_writes(parts: list[tuple[str | None, list[str]]]) -> frozenset[str]:
    """What of git's own files a chain of git's own commands (each part's command and its words,
    `commands._git_alone`) rewrites as it works, for the write audit to let stand: `.git/config`
    (`git init`, `git remote add`, `git push -u`, `git checkout --track`, `git config` not
    `--global`, a `git submodule` verb's), `.gitmodules` too (`git submodule add`). Nothing where
    a part runs a command it is handed (`_runs_one`): what that wrote there is not git's."""
    if any(_runs_one(sub, rest) for sub, rest in parts):
        return frozenset()
    written: set[str] = set()
    for sub, rest in parts:
        if sub == "submodule":
            written |= _submodule_writes(rest)
        elif (
            sub in _CONFIG_WRITERS
            or sub == "push"
            and bool({"-u", "--set-upstream"} & set(rest))
            or sub == "config"
            and not {"--global", "--system"} & set(rest)
        ):
            written.add(".git/config")
    return frozenset(written)


def _runs_one(sub: str | None, rest: list[str]) -> bool:
    """Whether a git command runs a command it is handed: `submodule foreach`, `bisect run`,
    `filter-branch` (its `--*-filter`s: all of it), and one with its option for that
    (`_HANDS_ON`: `rebase -x`, `difftool --extcmd`, `grep -O`) - by the option's long name or a
    part of it, as git takes one (`--exe=`), or its letter in a bundle of short ones (over-read,
    never under)."""
    verb = next((word for word in rest if not word.startswith("-")), None)
    if sub == "filter-branch":
        return True
    if sub in ("submodule", "bisect"):
        return verb == ("foreach" if sub == "submodule" else "run")
    long, short = _HANDS_ON.get(sub or "", ("", ""))
    return bool(long) and any(
        long.startswith(word.partition("=")[0])
        and len(word.partition("=")[0]) > 2
        or word.startswith("-")
        and not word.startswith("--")
        and short in word
        for word in rest
    )


def _submodule_writes(rest: list[str]) -> frozenset[str]:
    """What of git's own files a `git submodule` line (its words past `submodule`) rewrites as it
    works: `.git/config`, and `.gitmodules` for `add`, `set-url`, `set-branch`; nothing for
    `foreach`, `status`, `summary` or a bare one."""
    verb = next((word for word in rest if not word.startswith("-")), None)
    if verb in _SUBMODULE_GITMODULES:
        return frozenset({".git/config", ".gitmodules"})
    if verb in _SUBMODULE_CONFIG or verb == "update" and "--init" in rest:
        return frozenset({".git/config"})
    return frozenset()
