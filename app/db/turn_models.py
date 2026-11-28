"""Tables of the turn while its agents work (0.1.11), and `Flag`, moved here from
`app.db.models` to make room there (it imports this module back at its end)."""

from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base, new_id, now


class Flag(Base):
    """A switch of the whole app that outlives a restart, or one of its
    settings (Gemini's voice: its key, which no answer carries, model and voice; app.api.voice)."""

    __tablename__ = "flags"
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))


class NotedDecision(Base):
    """Task 10 (0.1.11): a decision the Orchestrator noted for the user with note_decision - a row
    of Decided for you (`app.decisions`), never a card: who and when are KOLONİ's, `what` and `why`
    the Orchestrator's words, masked, on one line and cut. Only added by the tool, never changed by
    an agent; `seen_at`, the user's OK (or Change) on it from the app's own page."""

    __tablename__ = "noted_decisions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    tool_call_id: Mapped[str | None] = mapped_column(String(32), default=None)
    what: Mapped[str] = mapped_column(String(200))
    why: Mapped[str] = mapped_column(String(200))
    seen_at: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=now)
