"""☾ Away's tables beside `app.db.models` (that file is at its size limit; `app.db` imports this
one, so `Base.metadata` - Alembic, the deletes that walk it - has them)."""

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base, new_id, now


class Parked(Base):
    """What a job parked for the user while they were away (§10, `app.parked`): a command's card,
    an Orchestrator's question it could not answer - not run, not answered; the agent was told so
    and went on. The user decides it under Waiting for you: "run", "reject", "answer" - or "stop"
    (Stop this task, Try again). Once a task's rows are all decided, KOLONİ runs what was Run in
    the task's copy and starts one going-on turn (`went_on`: that turn's run id)."""

    __tablename__ = "parked"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    away_run_id: Mapped[str] = mapped_column(ForeignKey("away_runs.id"), index=True)
    # The job's To-do task (by id alone: a task outlives its chat).
    task_id: Mapped[str] = mapped_column(String(32), index=True)
    seq: Mapped[int] = mapped_column(Integer)  # (in its Away: the order parked)
    kind: Mapped[str] = mapped_column(String(16))  # `parked.KINDS`: "command", "question", ...
    # Its Command or Question; None for a record of KOLONİ's own.
    ref_id: Mapped[str | None] = mapped_column(String(32), default=None)
    what: Mapped[str] = mapped_column(Text)  # the line or the question, whole (data, never read)
    # A command's {"cwd", "copy", "location", "image", "timeout", "reason", "judge",
    # "needs_project"}; a question's {"options", "why"}. Set by KOLONİ.
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    decision: Mapped[str | None] = mapped_column(String(8), default=None)
    answer: Mapped[str | None] = mapped_column(Text, default=None)
    result: Mapped[str | None] = mapped_column(Text, default=None)  # (what its morning run said)
    went_on: Mapped[str | None] = mapped_column(String(32), default=None)
    decided_at: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=now)
