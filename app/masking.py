"""K3: an agent's or a model's words as KOLONİ keeps them on record - the Orchestrator's reason
for a card or a To-do task, a judge's sentence: whole (a lone surrogate the replacement
character), what nobody sees taken out (a secret split by a zero-width space is one again), every
secret masked as the decision log masks what it shows (`decisions.said`) - those KOLONİ knows and
those known by their shape (a Bearer token, a password in an address, a value given to a secret's
name) - on one line. Before any cut: a secret cut in half would no longer be known to hide.
shortcut: `decisions.said` keeps its own copy of the same reading (k-karar-b's file); have it call
`masked` once both are in."""

import unicodedata

from app import raw
from app.judge import whole

# What shows as nothing and is no Cf: a braille blank, a Hangul filler (`stories.BLANK_LOOKING`),
# the combining grapheme joiner and the emoji variation selector.
_UNSEEN = frozenset("\u2800\u3164\uffa0\u115f\u1160\u034f\ufe0f")


def _shows(ch: str) -> bool:
    kind = unicodedata.category(ch)
    return not (kind == "Cf" or kind == "Cc" and not ch.isspace() or ch in _UNSEEN)


def _hide(text: str) -> str:
    """`commands.OutputMask.hide`'s look by shape, with the secrets KOLONİ checks (`raw.known`,
    HIGH-1) in place of every value it masks where text is shown: a kept reason keeps an MCP
    server's `production` readable.
    shortcut: the shapes are OutputMask's, listed again; give it the set to use if they part."""
    from app.commands import _ADDRESS_PASSWORD, _ASSIGNED, _BEARER, _PEM, _TOKENS  # (as `masked`)

    text = _TOKENS.sub(raw.HIDDEN, raw.hide(text, raw.known()))
    text = _BEARER.sub(rf"\g<1>{raw.HIDDEN}", text)
    text = _PEM.sub(rf"\g<1>\n{raw.HIDDEN}\n\g<2>", text)
    text = _ASSIGNED.sub(rf"\g<1>{raw.HIDDEN}", text)
    return _ADDRESS_PASSWORD.sub(rf"\g<1>{raw.HIDDEN}\g<2>", text)


def masked(text: str) -> str:
    """`text` as it may be kept: see the module. Masked again once on one line: a secret with a
    space in it may have been written across a line break. (`app.commands` is read when called:
    app.judge, read by app.db, calls this.)"""
    seen = "".join(ch for ch in whole(text) if _shows(ch))
    return _hide(" ".join(_hide(seen).split()))
