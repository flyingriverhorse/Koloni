"""What makes a line that looks like a lone search or a look do more than read - beside
`app.commands`, which is at its size limit. Claude Code's own exceptions to its read-only list
among them (the comparison of the CLIs' rules, 27 Nov 2026)."""

import re

# What a search may be told that writes or runs something: find's actions, rg's preprocessor and
# its replace and hostname program, ag's/ack's pager (`-r` is rg's and ag's replace, grep's not).
SEARCH_DOES = re.compile(
    r"(?i)-exec|-execdir|-ok|-okdir|-delete|-fprint0?|-fprintf|-fls"
    r"|--pre(?:=.*)?|--replace(?:=.*)?|--pager(?:=.*)?|--hostname-bin(?:=.*)?"
)
# A connection bash (and ksh) opens where a redirection names one of these - `cat <
# /dev/tcp/host/80`, `exec 3<>/dev/udp/host/53`: the internet, with no program's name in the line.
NET_PATH = re.compile(r"/dev/(?:tcp|udp)/[^\s;&|<>()]*", re.IGNORECASE)
# What sh expands in a word: a wildcard, and a brace (`{a,-}*`).
_EXPANDS = frozenset("*?[{")


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
        elif quote:
            before += char
        elif char in "'\"":
            quote = char
        elif char.isspace() or char in ";&|<>()":
            before = ""  # (a word of its own starts)
        elif char == "\\":
            before += next(chars, "")
        elif char in _EXPANDS and (not before or before[0] == "-" and "=" not in before):
            return True
        else:
            before += char
    return False
