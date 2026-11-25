"""MEDIUM-2: one set of the secrets KOLONİ looks for in what a branch commits, merges and pushes -
and masks out of what goes up with it (a commit's message, a pull request's title and body): those
given on a card in the turn, the values of this process's environment a secret's name holds
(`secret_values`) and of the variables a project passes to its commands (`pass_env`: what an agent
can see), and those KOLONİ keeps (`raw.known`: its saved keys, an MCP server's secret variables,
the page's key). None that reads as a word (`raw.WORDISH`: "production", "not-needed")."""

import os
from collections.abc import Callable, Iterable

from app import raw
from app.commands import secret_values, spellings_of

# The values of the variables the projects pass to their commands (`app.main.passed_values`).
passed: Callable[[], Iterable[str]] = tuple


def checked(given: Iterable[str] = ()) -> list[str]:
    """The set, as the secrets are looked for (`spellings_of`); `given`: the turn's, as they are."""
    env = spellings_of([*secret_values(os.environ), *passed()])
    env = [one for one in env if not raw.WORDISH.fullmatch(one)]
    return list(dict.fromkeys(one for one in [*given, *env, *raw.known()] if one))
