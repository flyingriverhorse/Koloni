"""MEDIUM-2: one set of the secrets KOLONİ looks for in what a branch commits, merges and pushes -
and masks out of what goes up with it (a commit's message, a pull request's title and body): those
given on a card in the turn, the values of this process's environment that are secrets by their
name or their shape (`values`), those of the variables the project passes to its commands
(`pass_env`: what an agent can see) - but one that reads as a word -, and those KOLONİ keeps
(`raw.known`: its saved keys, an MCP server's secret variables, the page's key - none of those kept
that reads as a word, `raw.WORDISH`: "not-needed")."""

import os
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

from app import raw
from app.commands import _ADDRESS_PASSWORD, _TOKENS, HANDLE, _withheld, secret_name, spellings_of


def _none(_project: Path | None) -> Iterable[tuple[str, str]]:
    return ()


# The variables - name, value - the project at a folder passes to its commands
# (`app.main.passed_values`).
passed: Callable[[Path | None], Iterable[tuple[str, str]]] = _none


def shaped(value: str) -> bool:
    """M-B: whether a value has a secret's shape, whatever its name holds - a token
    (`commands._TOKENS`: `ghp_…`, `sk-…`) or a password in an address (`_ADDRESS_PASSWORD`)."""
    return bool(_TOKENS.search(value) or _ADDRESS_PASSWORD.search(value))


def values(env: Mapping[str, str]) -> list[str]:
    """The values of `env` that are secrets: by their shape (`shaped`: `GH_PAT=ghp_…`, a
    `DATABASE_URL` with a password), or by their variable's name as a command is not given them
    (`commands._withheld`) - not a session's name, nor the file or program a secret is in
    (`*_FILE`, `*_HELPER`, Google's credentials path), nor a handle's (`HANDLE`: a socket's or a
    program's path) that no secret's name holds (M-A: `CLAUDE_CODE_OAUTH_TOKEN` is one)."""
    return [
        value
        for name, value in env.items()
        if isinstance(value, str)
        and len(value) >= raw.MIN_SECRET
        and (
            shaped(value)
            or _withheld(name)
            and not (HANDLE.fullmatch(name.upper()) and not secret_name(name))
        )
    ]


def checked(given: Iterable[str] = (), project: Path | None = None) -> list[str]:
    """The set, as the secrets are looked for (`spellings_of`); `given`: the turn's, as they are;
    `project`: the folder whose `pass_env` counts - no other project's."""
    ours = [one for one in values(dict(passed(project))) if not raw.WORDISH.fullmatch(one)]
    env = spellings_of([*values(os.environ), *ours])
    return list(dict.fromkeys(one for one in [*given, *env, *raw.known()] if one))
