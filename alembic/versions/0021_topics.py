"""topics: the turns that go on with the same piece of work; an agent goes on from an earlier one

Revision ID: 0021
Revises: 0020
"""
import uuid

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

MAX_TITLE = 80


def _title(text: str | None) -> str:
    """The first line of a message that says anything, on one line and cut to a size."""
    for line in (text or "").splitlines():
        shown = " ".join("".join(ch if ch.isprintable() else " " for ch in line).split())
        if shown:
            return shown if len(shown) <= MAX_TITLE else shown[: MAX_TITLE - 1] + "…"
    return ""


def upgrade() -> None:
    op.create_table(
        "topics",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("conversation_id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        # Not a foreign key: a topic stays when its trigger is deleted.
        sa.Column("trigger_id", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("topics") as batch:
        batch.create_index(batch.f("ix_topics_conversation_id"), ["conversation_id"], unique=False)
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("topic_id", sa.String(length=32), nullable=True))
        batch.create_index(batch.f("ix_runs_topic_id"), ["topic_id"], unique=False)
    with op.batch_alter_table("agents") as batch:
        # Left empty for the agents there already: nothing on record says which of them
        # went on from which.
        batch.add_column(sa.Column("continues_id", sa.String(length=32), nullable=True))

    # The turns there already: a conversation's own turns were one run of work as far
    # as anything on record says, so they are one topic; each trigger's turns in a
    # conversation are a topic of their own. A topic is named by the first line of the
    # message that started its first turn.
    bind = op.get_bind()
    runs = sa.table(
        "runs", sa.column("id", sa.String), sa.column("conversation_id", sa.String),
        sa.column("trigger_id", sa.String), sa.column("created_at", sa.DateTime),
        sa.column("topic_id", sa.String), sa.column("unattended", sa.Boolean),
        sa.column("trigger_name", sa.String),
    )
    messages = sa.table(
        "messages", sa.column("run_id", sa.String), sa.column("role", sa.String),
        sa.column("content", sa.Text), sa.column("created_at", sa.DateTime),
    )
    conversations = sa.table(
        "conversations", sa.column("id", sa.String), sa.column("title", sa.String),
    )
    topics = sa.table(
        "topics", sa.column("id", sa.String), sa.column("conversation_id", sa.String),
        sa.column("title", sa.String), sa.column("trigger_id", sa.String),
        sa.column("created_at", sa.DateTime),
    )
    names = dict(bind.execute(sa.select(conversations.c.id, conversations.c.title)).all())
    made: dict[tuple, str] = {}
    rows = bind.execute(
        sa.select(runs.c.id, runs.c.conversation_id, runs.c.trigger_id, runs.c.created_at,
                  runs.c.unattended, runs.c.trigger_name)
        .order_by(runs.c.created_at, sa.literal_column("runs.rowid"))
    ).all()
    for run_id, cid, trigger_id, created_at, unattended, trigger_name in rows:
        # A turn nobody watched whose trigger is not on record (none is known to exist)
        # is still not one of the user's own: those are a topic by the trigger's name.
        key = (cid, trigger_id or None, trigger_name if unattended and not trigger_id else None,
               bool(unattended) and not trigger_id)
        if key not in made:
            first = bind.execute(
                sa.select(messages.c.content)
                .where(messages.c.run_id == run_id, messages.c.role.in_(("user", "trigger")))
                .order_by(messages.c.created_at, sa.literal_column("messages.rowid"))
                .limit(1)
            ).scalar()
            made[key] = uuid.uuid4().hex
            bind.execute(topics.insert().values(
                id=made[key], conversation_id=cid, trigger_id=key[1], created_at=created_at,
                title=_title(first) or _title(names.get(cid)) or "Untitled",
            ))
        bind.execute(runs.update().where(runs.c.id == run_id).values(topic_id=made[key]))


def downgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("continues_id")
    with op.batch_alter_table("runs") as batch:
        batch.drop_index(batch.f("ix_runs_topic_id"))
        batch.drop_column("topic_id")
    op.drop_table("topics")
