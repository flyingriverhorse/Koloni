"""K-evrim: a candidate's score from its project's measure command, and which candidate is best.
Pure: what runs the command and what is done with the winner live in `agent`."""

import re
from pathlib import PurePosixPath

from app import injection
from app.board import as_data

_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_SENTENCE = re.compile(r"(?<=[.!?])\s")
# What KOLONİ's note of a round of candidates starts with: the next round's lead is given it
# (`AgentRunner._noted_for_team`).
ROUND_RESULT = "K-evrim round "


def score_of(output: str) -> float | None:
    """The score a measure command printed: its last non-empty line, a single number from 0 to
    100. Anything else - words, a sign, a percent, a number out of range - is no score."""
    last = next((line.strip() for line in reversed(output.splitlines()) if line.strip()), "")
    if not _NUMBER.fullmatch(last):
        return None
    score = float(last)
    return score if score <= 100 else None


def table(scores: dict[str, float | None], why: dict[str, str | None],
          models: dict[str, str | None] | None = None) -> str:
    """The candidates' scores as a card says them, best first: "Coder 2: 85 · Coder: 70 ·
    Coder 3: no score (no number)" - with `models` (K-evrim-model), each one's: "Coder 2
    (gpt-luna): 85"."""
    def shown(name: str) -> str:
        return f"{name} ({model})" if models and (model := models.get(name)) else name

    return " · ".join(f"{shown(name)}: {score:g}" if (score := scores[name]) is not None
                      else f"{shown(name)}: no score ({why.get(name) or 'none'})"
                      for name in best(scores))


def measured(held: dict[str, dict], part: str, round_no: int) -> str | None:
    """K-evrim-model: a round of a part's candidates measured so far, as the strip says them
    (`table`, with their models), from what its row keeps of each; None: none yet."""
    mine = [one for one in held.values()
            if one["part"] == part and one.get("round") == round_no and one.get("name")]
    return table({one["name"]: one["score"] for one in mine},
                 {one["name"]: one.get("why") for one in mine},
                 {one["name"]: one.get("model") for one in mine}) or None


def lessons(scores: dict[str, float | None], why: dict[str, str | None], picked: str,
            said: dict[str, str | None], round_no: int, recipe: str,
            kept: dict | None = None, models: dict[str, str | None] | None = None,
            unopened: list[str] | None = None) -> str:
    """KOLONİ's note of a round of candidates, for those after it: whose work went on and how
    it scored, and each other's score and the first sentence of its report - their copies are
    gone. `kept`: the work kept from a round before, where the pick did not beat it (`beats`):
    it stays, and each of the round's candidates is a lesson. What to take of theirs is the
    next round's to say: nothing is merged by code. A candidate's line is its own words, quoted
    as data (KOLONİ's note is not scanned as it is handed on: `board.handed`); one that reads
    as an order to the agents after it is held back. `models`: each one's, said with its name
    (K-evrim-model). `unopened`: KOLONİ's line on each candidate not opened (B-388)."""
    def on(name: str) -> str:
        return f"{name} on {model}" if models and (model := models.get(name)) else name

    def scored(name: str) -> str:
        score = scores.get(name)
        return f"{score:g}" if score is not None else f"no score: {why.get(name) or 'none'}"

    def first(name: str) -> str:
        # (B-369: not a heading - "## Done" says nothing.)
        line = next((_SENTENCE.split(one.strip(), maxsplit=1)[0]
                     for one in (said.get(name) or "").splitlines()
                     if one.strip() and not one.lstrip().startswith("#")), "")[:200]
        if not line:
            return "no report"
        hits = injection.scan(line, "agent")
        return f"(a candidate's line held back: {', '.join(hits)})" if hits else as_data(line)

    if kept is not None:
        held = "no score" if kept["score"] is None else f"{kept['score']:g}"
        head = (f"{ROUND_RESULT}{round_no} of {recipe}: no one beat {held}; {kept['name']}'s "
                "work stays - a next round starts from it again: beat its score, taking what "
                "worked in these.")
    else:
        head = (f"{ROUND_RESULT}{round_no} of {recipe}: {on(picked)} went on ({scored(picked)}); a "
                "next round starts from its copy - beat its score, keeping what scored and "
                "taking what worked in the others'.")
    return (f"{head} Lessons, in each one's own words:"
            + "".join(f"\n- {on(name)} ({scored(name)}): {first(name)}"
                      for name in best(scores) if name != picked or kept is not None)
            + "".join(f"\n- {one}" for one in unopened or []))


def beats(score: float | None, kept: dict | None) -> bool:
    """B-370: whether a round's pick goes on in place of the work kept from the rounds before
    (`kept["score"]`): the first round's always; a later one's only with a higher score - one
    with none never does, and any score beats work kept with none."""
    return kept is None or score is not None and (kept["score"] is None or score > kept["score"])


def best(scores: dict[str, float | None]) -> list[str]:
    """The candidates, best first: the highest score first, those with none last; of equal
    ones, the first opened (`scores` is in the order they were opened)."""
    return sorted(scores, key=lambda name: (scores[name] is None, -(scores[name] or 0)))


def names_one(command: str, paths: list[str]) -> bool:
    """Whether a measure command names one of these files - "measure.py", "-m measure",
    "-m tools.measure" all name measure.py: by each word's file name, its stem and its last
    dotted part. Over-asking is fine (`AgentRunner._measure`)."""
    words = [PurePosixPath(word.replace("\\", "/")) for word in re.split(r"[\s\"']+", command)
             if word]
    named = {one for word in words for one in (word.name, word.stem, word.name.rsplit(".")[-1])}
    return any(PurePosixPath(path).name in named or PurePosixPath(path).stem in named
               for path in paths)
