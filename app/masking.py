"""K3: an agent's or a model's words as KOLONİ keeps them on record - the Orchestrator's reason
for a card or a To-do task, a judge's sentence: whole (a lone surrogate the replacement
character), what nobody sees taken out (a secret split by a zero-width space is one again), every
secret masked as the decision log masks what it shows (`decisions.said`) - those KOLONİ knows and
those known by their shape (a Bearer token, a password in an address, a value given to a secret's
name) - on one line. Before any cut: a secret cut in half would no longer be known to hide.
shortcut: `decisions.said` keeps its own copy of the same reading (k-karar-b's file); have it call
`masked` once both are in."""

import unicodedata

from app.judge import whole

# What shows as nothing and is no Cf: a braille blank, a Hangul filler (`stories.BLANK_LOOKING`),
# the combining grapheme joiner and the emoji variation selector.
_UNSEEN = frozenset("⠀ㅤﾠᅟᅠ͏️")


def _shows(ch: str) -> bool:
    kind = unicodedata.category(ch)
    return not (kind == "Cf" or kind == "Cc" and not ch.isspace() or ch in _UNSEEN)


def masked(text: str) -> str:
    """`text` as it may be kept: see the module. Masked again once on one line: a secret with a
    space in it may have been written across a line break."""
    from app.commands import OutputMask  # (here: app.judge, read by app.db, calls this)

    hide = OutputMask(()).hide
    return hide(" ".join(hide("".join(ch for ch in whole(text) if _shows(ch))).split()))
