"""what was made and changed on a trigger stays on record; a trigger's commands are rules

Revision ID: 0020
Revises: 0019
"""
import json
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

TYPED = (
    "its commands were typed into it, and a trigger's commands are now ticked on its "
    "conversation's allow list: they could not be carried over, so it may run no command "
    "now. They were: {lines}"
)


def upgrade() -> None:
    op.create_table(
        "trigger_changes",
        sa.Column("id", sa.String(length=32), nullable=False),
        # Neither is a foreign key: what was done to a trigger outlives it.
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("trigger_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("what", sa.String(length=24), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("trigger_changes") as batch:
        batch.create_index(batch.f("ix_trigger_changes_project_id"), ["project_id"], unique=False)
        batch.create_index(batch.f("ix_trigger_changes_trigger_id"), ["trigger_id"], unique=False)
    with op.batch_alter_table("triggers") as batch:
        batch.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))
    # A trigger there already was last changed, for all that is on record, when it was made.
    op.execute("UPDATE triggers SET updated_at = created_at")

    # Until now a trigger kept the command lines themselves. A line cannot be taken for
    # a rule of its conversation's list (the user never put it there), so it is dropped -
    # the trigger then allows no command - and that is written on the trigger's record.
    bind = op.get_bind()
    triggers = sa.table(
        "triggers", sa.column("id", sa.String), sa.column("project_id", sa.String),
        sa.column("name", sa.String), sa.column("permissions", sa.JSON),
        sa.column("updated_at", sa.DateTime),
    )
    changes = sa.table(
        "trigger_changes", sa.column("id", sa.String), sa.column("project_id", sa.String),
        sa.column("trigger_id", sa.String), sa.column("name", sa.String),
        sa.column("at", sa.DateTime), sa.column("what", sa.String),
        sa.column("detail", sa.Text),
    )
    moment = datetime.now(UTC).replace(tzinfo=None)
    rows = bind.execute(sa.select(
        triggers.c.id, triggers.c.project_id, triggers.c.name, triggers.c.permissions,
    )).all()
    for trigger_id, project_id, name, permissions in rows:
        if isinstance(permissions, str):
            permissions = json.loads(permissions)
        if not isinstance(permissions, dict) or not permissions.get("commands"):
            continue
        typed = permissions["commands"]
        lines = "; ".join(str(line) for line in typed) if isinstance(typed, list) else str(typed)
        bind.execute(triggers.update().where(triggers.c.id == trigger_id).values(
            permissions={**permissions, "commands": []}, updated_at=moment))
        bind.execute(changes.insert().values(
            id=uuid.uuid4().hex, project_id=project_id, trigger_id=trigger_id, name=name,
            at=moment, what="permissions changed", detail=TYPED.format(lines=lines)))

    with op.batch_alter_table("triggers") as batch:
        batch.alter_column("updated_at", existing_type=sa.DateTime(), nullable=False)


def downgrade() -> None:
    # (The command lines that were dropped are not brought back: they are on the record
    # that goes with this table, and nowhere else.)
    with op.batch_alter_table("triggers") as batch:
        batch.drop_column("updated_at")
    op.drop_table("trigger_changes")
