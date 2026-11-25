"""Full auto's judge's table beside `app.db.models` (that file is at its size limit; `app.db`
imports this one, so `Base.metadata` - Alembic, the deletes that walk it - has it)."""

from datetime import datetime

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base, new_id, now


class JudgeAllowed(Base):
    """A line the user said on a card of Full auto's judge not to ask about again in a project:
    the command as it ran, its folder, and the digest of the agent's program it ran ("": none)."""

    __tablename__ = "judge_allowed"
    __table_args__ = (UniqueConstraint("project_id", "command", "cwd", "program_sha"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(String(32), index=True)  # (gone with its project)
    command: Mapped[str] = mapped_column(Text)
    cwd: Mapped[str] = mapped_column(Text)
    program_sha: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=now)
