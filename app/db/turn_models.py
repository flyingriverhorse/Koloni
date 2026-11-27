"""Tables of the turn while its agents work (0.1.11), and `Flag`, moved here from
`app.db.models` to make room there (it imports this module back at its end)."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class Flag(Base):
    """A switch of the whole app that outlives a restart, or one of its
    settings (Gemini's voice: its key, which no answer carries, model and voice; app.api.voice)."""

    __tablename__ = "flags"
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))
