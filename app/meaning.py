"""Search by meaning (22c), optional: what of the memory and of the earlier turns is near
in meaning to a question, beside what shares its words.

Nothing here runs unless the user chose a provider for it on the Memory page
(`Project.embedding_provider_id`): then the vectors of the records' words and of what was
said in earlier turns come from that provider's OpenAI-compatible server
(`POST {base_url}/embeddings`, with its key), one request at each search, which also
carries the records that have no vector yet (nothing is asked at a write: that would
hold the loop an agent's `remember` runs on) - and the search compares the question's
vector with the ones kept (`embeddings`).
When the server does not answer, the search by words stands alone and says so in one
line; nothing is guessed. What is found is still somebody's words of that moment, quoted
with who, when and where (`memory.shown`, `earlier.told`): only the tag "by meaning"
is added.
"""

import logging
import math
from dataclasses import dataclass, field

import httpx2
from sqlalchemy import bindparam, select, text
from sqlalchemy.orm import Session

from app.db.models import Embedding, Memory, Project, Provider
from app.model_client import _describe
from app.providers import is_on

logger = logging.getLogger(__name__)

MAX_FOUND = 5
LEAST = 0.3  # the cosine below which nothing is near
# shortcut: at most this many records without a vector get one per search, in one request
# with the question's; the rest wait for the next searches. Embed at the index too if a
# big project is ever seen to lag behind.
BACKFILL = 50
# shortcut: only the first 8 000 characters of a text go to the server (an embedding
# model's window is a few thousand tokens); send it in parts if the rest is ever missed.
MAX_CHARS = 8000
SEARCH_SECONDS = 30.0
# The most an answer may be, and the longest a vector: past that it is not even parsed.
MAX_BODY = 4 * 1024 * 1024
MAX_DIMS = 8192
TOO_LARGE = "the model server's answer is too large"
OFF = "search by meaning is off: {why}"
NO_VECTORS = "the model server did not answer with vectors"
DEFAULT_MODEL = "text-embedding-3-small"


@dataclass(frozen=True)
class Hits:
    """What a search by meaning found, the nearest first: records of the memory by their
    id, earlier turns by their row in the index - or why it did not run (`off`)."""

    memory: list[str] = field(default_factory=list)
    turns: list[int] = field(default_factory=list)
    off: str | None = None


class Off(Exception):
    """The server gave no vectors: why, in words safe to show (no key; `_describe`
    strips any URL of what could hold one)."""


def provider_of(session: Session, project: Project) -> Provider | None:
    return session.get(Provider, project.embedding_provider_id) if (
        project.embedding_provider_id) else None


def embed(provider: Provider, model: str, texts: list[str]) -> list[list[float]]:
    """The vectors of these texts, in their order, from the provider's server with its
    key. `Off` when it did not answer with them - in KOLONİ's words: of a refusal only
    the status reaches whoever reads the search, what the server said goes to the log
    (the server is the user's choice; its words are not). The key goes in the request's
    header and nowhere else: not into a log, not into what is said of a failure.
    shortcut: the model's name is sent as given, never checked against the server's list
    (few servers list embedding models); a wrong one is seen as the server's refusal."""
    if not provider.base_url:
        raise Off("its provider has no server address")
    headers = {"Authorization": f"Bearer {provider.api_key}"} if provider.api_key else {}
    try:
        with httpx2.Client(headers=headers,
                           timeout=httpx2.Timeout(SEARCH_SECONDS, connect=5.0)) as http:
            r = http.post(f"{provider.base_url.rstrip('/')}/embeddings",
                          json={"model": model, "input": texts})
            r.raise_for_status()
            if len(r.content) > MAX_BODY:
                raise Off(TOO_LARGE)
            told = r.json()
    except httpx2.HTTPStatusError as exc:
        logger.info("the embeddings request was refused: %s", _describe(exc))
        raise Off(f"model server returned {exc.response.status_code}") from None
    except httpx2.HTTPError as exc:
        raise Off(_describe(exc)) from None
    except ValueError:
        raise Off(NO_VECTORS) from None
    try:
        vectors = [[float(x) for x in item["embedding"]]
                   for item in sorted(told["data"], key=lambda item: item["index"])]
    except (TypeError, KeyError, ValueError):
        raise Off(NO_VECTORS) from None
    if len(vectors) != len(texts) or not all(vectors):
        raise Off("the model server answered with the wrong number of vectors")
    if any(len(vector) > MAX_DIMS for vector in vectors):
        raise Off(TOO_LARGE)
    return vectors


def words_of(record: Memory) -> str:
    """What of a record is embedded: its subject, then its words."""
    return f"{record.about}: {record.text}" if record.about else record.text


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def search(session: Session, project: Project, project_ids: list[str], query: str) -> Hits | None:
    """The records in effect of these projects' memory, and the rows of their earlier
    turns, nearest in meaning to the question: the nearest first, at most MAX_FOUND, none
    below LEAST. On the way, up to BACKFILL of them that have no vector of this model yet
    get one (in the question's request) - a linked project's records too, kept under its
    id and this model's name, beside whatever that project embeds with. None when no
    provider is chosen, or nothing is asked;
    `Hits.off` says why when a provider is chosen and the search did not run.
    shortcut: every vector of the projects is read and compared here, in Python - a few
    thousand take well under a second; an index is for when a project outgrows that."""
    if not project.embedding_provider_id or not query.strip():
        return None
    provider = provider_of(session, project)
    if provider is None:
        return Hits(off=OFF.format(why="its provider is gone"))
    if not is_on(provider, project.embedding_model):
        return Hits(off=OFF.format(why="its provider is switched off"))
    model = project.embedding_model
    # What may be found, each with its project and - of a record - its words.
    wanted: dict[tuple[str, str], tuple[str, str | None]] = {
        ("memory", record.id): (record.project_id, words_of(record))
        for record in session.scalars(select(Memory).where(
            Memory.project_id.in_(project_ids), Memory.status == "active"))
    }
    turns = text("SELECT rowid, project_id FROM said_in_turns "
                 "WHERE project_id IN :ids AND said != ''").bindparams(
        bindparam("ids", expanding=True))
    for rowid, pid in session.execute(turns, {"ids": project_ids}):
        wanted[("turn", str(rowid))] = (pid, None)
    stored = {
        (kept.kind, kept.record_id): kept.vector
        for kept in session.scalars(select(Embedding).where(
            Embedding.project_id.in_(project_ids), Embedding.model == model))
        if (kept.kind, kept.record_id) in wanted  # (not in effect any more: not compared)
    }
    missing = [key for key in wanted if key not in stored][:BACKFILL]
    texts = [query[:MAX_CHARS]]
    for kind, record_id in missing:
        said = wanted[(kind, record_id)][1] if kind == "memory" else session.scalar(
            text("SELECT said FROM said_in_turns WHERE rowid = :row"), {"row": int(record_id)})
        texts.append((said or "")[:MAX_CHARS])
    try:
        asked, *made = embed(provider, model, texts)
    except Off as why:
        return Hits(off=OFF.format(why=why))
    for (kind, record_id), vector in zip(missing, made, strict=True):
        session.merge(Embedding(kind=kind, record_id=record_id, vector=vector, model=model,
                                project_id=wanted[(kind, record_id)][0]))
        stored[(kind, record_id)] = vector
    session.commit()
    near = sorted(((_cosine(asked, vector), key) for key, vector in stored.items()
                   if len(vector) == len(asked)), reverse=True)
    best = [key for score, key in near[:MAX_FOUND] if score >= LEAST]
    return Hits(memory=[record_id for kind, record_id in best if kind == "memory"],
                turns=[int(record_id) for kind, record_id in best if kind == "turn"])
