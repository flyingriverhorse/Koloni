"""What a command's record says of KOLONİ's judges (`Command.judged`), as the API gives it - beside
`app.schemas`, which is at its size limit."""

from typing import Literal

from pydantic import BaseModel, Field


class Judged(BaseModel):
    """K-yargic: what the check of the user's words said of a command at Full auto: it ran with
    no card ("run": on `quote`, a line of the user's found in `source`), it was not run and its
    agent told that line ("refuse"), or it was asked ("ask"; `why`, the check's own sentence where
    it said so). `model`: who was asked; `seen`: the user's OK on one that ran or was not run
    (Decided for you). Full auto's judge's (`kind` "risk"): "fine", it ran; "risky", its card -
    `why`, the judge's sentence, or KOLONİ's where it was not asked or gave no answer to go by
    (`model` then "" where none was asked); "refuse", not run, its agent told the judge's sentence
    (the project's Refuse and go on; `seen` as above). Since §8 the check of the user's words is
    the judge's too, `kind` "words" ("" on a record from before 0.1.9). K5 (0.1.10): `kind` "said",
    an "ask" whose card quotes the sentence of the user's own message (`quote`, `source`
    "message") that asked for this push, pull request or merge (`judge.asked_for`) - which of
    them, `action` (its card's verb; none on any other record)."""

    kind: Literal["", "risk", "words", "said"] = ""
    verdict: Literal["run", "ask", "refuse", "fine", "risky"]
    quote: str = ""
    source: Literal["preferences", "rules", "message", ""] = ""
    why: str = ""
    model: str = ""
    seen: bool = False
    action: Literal["push", "pr", "merge"] | None = Field(
        None, exclude_if=lambda value: value is None
    )
