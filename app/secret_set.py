"""MEDIUM-2: one set of the secrets KOLONİ looks for in what a branch commits, merges and pushes -
and masks out of what goes up with it (a commit's message, a pull request's title and body): those
given on a card in the turn, the values of this process's environment that are secrets by their
name or their shape (`values`: a project's `pass_env` passes some of these), and those KOLONİ keeps
(`raw.known`: its saved keys, an MCP server's secret variables, the page's key - none of those kept
that reads as a word, `raw.WORDISH`: "not-needed") - and the token or password each holds alone
(`parts`)."""

import os
from collections.abc import Iterable, Mapping
from urllib.parse import unquote

from app import raw
from app.commands import _ADDRESS_PASSWORD, _TOKENS, HANDLE, _withheld, secret_name, spellings_of


def shaped(value: str) -> bool:
    """M-B: whether a value has a secret's shape, whatever its name holds - a token
    (`commands._TOKENS`: `ghp_…`, `sk-…`) or a password in an address (`_ADDRESS_PASSWORD`)."""
    return bool(_TOKENS.search(value) or _ADDRESS_PASSWORD.search(value))


def parts(value: str) -> list[str]:
    """M-B: the secrets a value holds by their shape, alone - each token, an address's password as
    written and unquoted (`DATABASE_URL`'s password in a settings.py) - none shorter than
    MIN_SECRET, nor a word (`postgres://postgres:postgres@…` makes no "postgres" one)."""
    found = [token.group() for token in _TOKENS.finditer(value)]
    for address in _ADDRESS_PASSWORD.finditer(value):
        password = value[address.end(1) : address.start(2)]
        found += [password, unquote(password)]
    return [one for one in found if len(one) >= raw.MIN_SECRET and not raw.WORDISH.fullmatch(one)]


def values(env: Mapping[str, str]) -> list[str]:
    """The values of `env` that are secrets - and their `parts`: by their shape (`shaped`:
    `GH_PAT=ghp_…`, a `DATABASE_URL` with a password), or by their variable's name as a command is
    not given them (`commands._withheld`) - not a session's name, nor the file or program a secret
    is in (`*_FILE`, `*_HELPER`, Google's credentials path), nor a handle's (`HANDLE`: a socket's
    or a program's path) that no secret's name holds (M-A: `CLAUDE_CODE_OAUTH_TOKEN` is one)."""
    whole = [
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
    return list(dict.fromkeys(one for value in whole for one in (value, *parts(value))))


def checked(given: Iterable[str] = ()) -> list[str]:
    """The set, as the secrets are looked for (`spellings_of`); `given`: the turn's, as they are."""
    known = raw.known()
    env = spellings_of([*values(os.environ), *(one for value in known for one in parts(value))])
    return list(dict.fromkeys(one for one in [*given, *env, *known] if one))
