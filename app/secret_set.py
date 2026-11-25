"""MEDIUM-2: one set of the secrets KOLONİ looks for in what a branch commits, merges and pushes -
and masks out of what goes up with it (a commit's message, a pull request's title and body): those
given on a card in the turn, the values of this process's environment a secret's name holds
(`secret_values`) and of the variables a project passes to its commands (`pass_env`: what an agent
can see), and those KOLONİ keeps (`raw.known`: its saved keys, an MCP server's secret variables,
the page's key - none of those kept that reads as a word, `raw.WORDISH`: "not-needed")."""

import os
from collections.abc import Callable, Iterable, Mapping

from app import raw
from app.commands import HANDLE, _withheld, spellings_of

# The values of the variables the projects pass to their commands (`app.main.passed_values`).
passed: Callable[[], Iterable[str]] = tuple


def values(env: Mapping[str, str]) -> list[str]:
    """The values of `env` that are secrets by their variable's name, as a command is not given them
    (`commands._withheld`) - not a session's name, nor the file or program a secret is in (`*_FILE`,
    `*_HELPER`, Google's credentials path) - nor a handle's (`HANDLE`: a socket's or a program's
    path): no path or name a branch's look would stop on (HIGH-1)."""
    return [
        value
        for name, value in env.items()
        if isinstance(value, str)
        and len(value) >= raw.MIN_SECRET
        and _withheld(name)
        and not HANDLE.fullmatch(name.upper())
    ]


def checked(given: Iterable[str] = ()) -> list[str]:
    """The set, as the secrets are looked for (`spellings_of`); `given`: the turn's, as they are."""
    env = spellings_of([*values(os.environ), *passed()])
    return list(dict.fromkeys(one for one in [*given, *env, *raw.known()] if one))
