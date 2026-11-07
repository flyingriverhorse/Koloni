"""K-bilgi 6: the project's "Project notes" - a knowledge (its only source `notes:`) whose pages are
short notes KOLONİ writes from what the user accepted on a card under a turn ("Add to Project
notes?", a `NotesOffer`: answered whenever the user likes - it never holds the turn):
a finding a fixer answered `| fixed:` (a Reviewer's, a Debugger's or a Bugfix recipe's - every
fixer answers so, `agent.FINDINGS_ANSWERED`) and a change to `docs/`. It is made the first time
the user accepts one. Its guide is a list of the notes, a line each, written with no model.

What an agent wrote is its words, not KOLONİ's: each page is framed as data and noted where it
reads like orders (`injection.noted`), as a page read from the web is. A docs/ file is read as
the Files window reads it (`project_files.text_of`: no secret, no link, no hard link, no place
KOLONİ never opens)."""

import difflib
import json
import re
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import injection, knowledge, knows, koloni, project_files, web
from app.db.models import Agent, FileChange, NotesOffer, Project, ProjectKnowledge, now
from app.views import Refused
from app.workspace import in_scratch, secret_in_project

TOPIC = "Project notes"
OFFERED = "notes.offered"  # (the event a chat reads its offers again on)
MOST = 8  # items on one offer
LINE = 200  # characters of an item's line on the card and in the guide
TEXT = 1_500  # characters of a note's page
SAID = 3  # lines of a docs/ file on its item's line: what the turn wrote there
WHAT = "note written from an agent's work"
# A fixer's answer to a finding, `- <what> | fixed: <how>`: found by its marker, which a run of
# spaces cannot make slow (no backtracking over the line).
FIXED = re.compile(r"\|[ \t]*fixed:", re.IGNORECASE)
CHANGED = "the offer changed since your card showed it: look at it again"
LEFT = ", as a turn left it:\n\n"  # (a docs/ note's text: its path, this, the file's text)


def _fixes(report: str) -> list[tuple[str, str]]:
    """A report's `- <what> | fixed: <how>` lines, each its what and how."""
    found = []
    for line in report.splitlines():
        marker = FIXED.search(line)
        if marker:
            what, how = line[:marker.start()].strip().lstrip("-*•").strip(), line[
                marker.end():].strip()
            if what and how:
                found.append((what, how))
    return found


def _said(before: str | None, after: str) -> list[str]:
    """What a turn wrote in a file, in its own words: the first `SAID` lines it added (blank lines
    and headings left out), else - it added none, or it made the file - the file's first."""
    def words(lines: list[str]) -> list[str]:
        return [one.strip().lstrip("-*•").strip() for one in lines
                if one.strip() and not one.lstrip().startswith("#")]
    lines = after.splitlines()
    added = [] if before is None else words([
        one for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(
            None, before.splitlines(), lines, autojunk=False).get_opcodes()
        if tag in ("insert", "replace") for one in lines[j1:j2]])
    return (added or words(lines))[:SAID]


def _text(root: str, path: str) -> str | None:
    """A docs/ file's text as the Files window reads it; None where there is none to note: gone,
    a secret, a second name, not text or too big to read."""
    if in_scratch(path) or secret_in_project(path):
        return None
    try:
        return project_files.text_of(root, path)["text"]
    except Refused:
        return None


def _kept(root: str, items: list[dict]) -> list[dict]:
    """B-380: an offer's items still so in the project now - a docs/ file's still there and still
    holding the words its line quotes (one offered before those were kept: the text it was
    offered with); a finding always. Read again as a turn adds to the offer, as a card shows it
    and as the user answers it: at most `MOST` files."""
    kept = []
    for one in items:
        if one["source"].startswith("docs/"):
            text = _text(root, one["source"])
            words = one.get("words") or [one["text"].partition(LEFT)[2]]
            if text is None or not all(word in text for word in words):
                continue
        kept.append(one)
    return kept


def items_of(session: Session, run_id: str, root: str) -> list[dict]:
    """What a turn offers for the notes: each finding its agents answered fixed, and each file of
    `docs/` it changed - as it is now in the project, where the Files window would show it - as
    {"line", "text", "source"}: `line` for the card and the guide, `text` for the note's page
    (and a file's "words": what its line quotes, for `_kept`). Only this turn's own changes."""
    found = []
    # (Its fixers' own reports: not the Lead's, which may repeat theirs.)
    for agent in session.scalars(select(Agent).where(
            Agent.run_id == run_id, Agent.depth > 0, Agent.report.is_not(None)).order_by(
            Agent.created_at)):
        for what, how in _fixes(agent.report or ""):
            said = f"{what} - fixed: {how}"
            found.append({"line": web._line(f"{agent.name}'s report (its words): {said}", LINE),
                          "text": said[:TEXT], "source": f"{agent.name}'s report"})
    paths: dict[str, str | None] = {}  # (each file's text before the turn's first change of it)
    for path, before in session.execute(select(FileChange.path, FileChange.before_content).where(
            FileChange.run_id == run_id, FileChange.status == "applied",
            FileChange.path.startswith("docs/"),  # (an attachment the user saved there: not one)
            FileChange.after_from.is_(None)).order_by(FileChange.created_at)):
        paths.setdefault(path, before)
    for path, before in paths.items():
        text = _text(root, path)
        if text is not None:
            words = _said(before, text)
            said = " · ".join(words)
            found.append({"line": web._line(f"{path} (its words): {said}" if said
                                            else f"{path} was changed", LINE),
                          "text": f"{path}{LEFT}{text[:TEXT]}", "source": path, "words": words})
    return found


def offer(session: Session, project_id: str, run_id: str, cid: str, root: str, watched: bool
          ) -> NotesOffer | None:
    """A turn's end: what it found (`items_of`) added to the project's waiting offer - made where
    none waits (one decided meanwhile is not added to) - each once, the newest `MOST` kept, what
    earlier turns left there only where still so (`_kept`, B-380). A
    watched turn's card shows it from now on, even with nothing of its own (what turns nobody
    watched left); one nobody watched only adds to it. None: nothing waits (not committed). Two
    made at once: the second meets `uq_notes_offers_waiting` (IntegrityError) - ask again.
    shortcut: past `MOST` the oldest items go unasked; offer the rest on a later card if that is
    missed."""
    new = items_of(session, run_id, root)
    # (A write first, that changes nothing: no answer commits between this look and the change.)
    session.execute(update(NotesOffer).where(
        NotesOffer.project_id == project_id, NotesOffer.status == "waiting").values(
        status=NotesOffer.status))
    waiting = session.scalar(select(NotesOffer).where(
        NotesOffer.project_id == project_id, NotesOffer.status == "waiting").limit(1)
        .execution_options(populate_existing=True))
    if waiting is None and not new:
        return None
    if waiting is None:
        waiting = NotesOffer(project_id=project_id, items=[])
        session.add(waiting)
    waiting.items = list({one["line"]: one for one in [
        *_kept(root, waiting.items), *new]}.values())[-MOST:]
    if watched and (new or waiting.conversation_id is None):
        waiting.conversation_id, waiting.run_id = cid, run_id
    session.flush()
    return waiting


def decide(session: Session, offer_id: str, shown: list[str], add: list[str],
           root: str) -> NotesOffer:
    """The user's word on a waiting offer: the items whose lines `add` names written as notes
    (`accept`), the rest gone; none named is Not now - nothing written. `shown`: the lines their
    card showed - where the offer has others now, Refused 409 (the card reads it again). A line
    not on it, Refused 422, and it waits on. Only one answer writes: a second, Refused 409 (not
    committed)."""
    # (A write first, that changes nothing: a second answer waits here, then finds it decided.)
    session.execute(update(NotesOffer).where(NotesOffer.id == offer_id).values(
        status=NotesOffer.status))
    offer = session.get(NotesOffer, offer_id, populate_existing=True)
    if offer is None:
        raise Refused(404, "offer not found")
    if offer.status != "waiting":
        raise Refused(409, "this offer was answered already")
    items = _kept(root, offer.items)  # (as its card shows it: `offers_of`)
    lines = [one["line"] for one in items]
    if shown != lines:
        raise Refused(409, CHANGED)
    if not set(add) <= set(lines):
        raise Refused(422, "add names a line that is not on the offer")
    chosen = [one for one in items if one["line"] in add]
    if chosen:
        accept(session, offer.project_id, root, chosen)
    offer.items = items
    offer.status, offer.decided_at = "added" if chosen else "discarded", now()
    offer.answer = f"added {len(chosen)} of {len(lines)}" if chosen else "not now"
    return offer


def out(offer: NotesOffer, items: list[dict] | None = None) -> dict:
    """An offer as its card shows it (`schemas.NotesOfferOut`): `items` in place of its own."""
    return {"id": offer.id, "run_id": offer.run_id,
            "lines": [one["line"] for one in (offer.items if items is None else items)],
            "status": offer.status, "answer": offer.answer}


def offers_of(session: Session, cid: str) -> list[dict]:
    """The offers a chat's cards show, decided or not, oldest first (`out`): a waiting one with
    only its items still so in the project (`_kept`) - none left, no card."""
    shown = []
    for one in session.scalars(select(NotesOffer).where(
            NotesOffer.conversation_id == cid).order_by(NotesOffer.created_at)):
        if one.status != "waiting":
            shown.append(out(one))
        elif items := _kept(session.get_one(Project, one.project_id).root_path, one.items):
            shown.append(out(one, items))
    return shown


def notes_of(session: Session, project_id: str) -> ProjectKnowledge | None:
    return next((row for row in session.scalars(select(ProjectKnowledge).where(
        ProjectKnowledge.project_id == project_id)) if knowledge.is_notes(knows.knowledge_of(row))),
        None)


def accept(session: Session, project_id: str, root: str, chosen: list[dict]) -> ProjectKnowledge:
    """The chosen items written as notes, a page each, and the guide and learned.json written
    again over all of them - the knowledge made first where the project has none (not
    committed). Refused 409 where another knowledge keeps its guide in the notes' folder: never
    written over.
    shortcut: two answers of two projects sharing a folder could number a page twice; lock the
    folder if that is ever met."""
    row = notes_of(session, project_id)
    if row is None:
        made = {"topic": TOPIC, "sources": [knowledge.NOTES]}
        if taken := knows.folder_taken(session, project_id, made):
            raise Refused(409, f"Project notes are not made: {taken}")
        row = ProjectKnowledge(project_id=project_id, topic=TOPIC, sources=[knowledge.NOTES],
                               max_pages=1000, max_usd=0.5, removed=[], weekly=False,
                               search_web=False)
        session.add(row)
        session.flush()
    known = knows.knowledge_of(row)
    where = knowledge.folder_of(known)
    record = knowledge.learned(root, known) or {}
    names = [name for name in knowledge._parts(record)
             if isinstance(name, str) and knowledge.NAMED.fullmatch(name)]
    pages = [one for one in record.get("pages") or [] if isinstance(one, dict)][:len(names)]
    at = datetime.now(UTC)
    for one in chosen:
        name, source = f"{len(names) + 1:04d}.md", f"{one['source']} · {at.date().isoformat()}"
        koloni.write(root, f"{where}/{knowledge.PAGES}/{name}", web.framed(
            f"Source: {web._line(source, 300)}\n\n{injection.noted(one['text'], 'agent')}", WHAT))
        names.append(name)
        pages.append({"source": source, "read": True, "why": None, "line": one["line"]})
    # (A note's line is its own words, B-372.) shortcut: a note accepted before that keeps its
    # "docs/x.md was changed"; read its page again here if those are seen to mislead.
    guide = (f"# {TOPIC}\n\nNotes KOLONİ wrote from what the user accepted at the end of a turn, "
             f"one page each ({knowledge.PAGES}/):\n" + "\n".join(
                 f"- {str(page.get('line'))[:LINE]} · {knowledge.PAGES}/{name}"
                 for name, page in zip(names, pages, strict=False)))
    koloni.write(root, f"{where}/{knowledge.GUIDE}", injection.noted(guide, "agent"))
    koloni.write(root, f"{where}/{knowledge.LEARNED}", json.dumps({
        "learned_at": at.isoformat(), "sources": known["sources"], "model": "KOLONİ",
        "pages": pages, "unread": 0, "parts": names, "guide_from": len(names), "left": 0,
        "cost": None, "removed": [], "changed": None}, indent=2, ensure_ascii=False))
    return row
