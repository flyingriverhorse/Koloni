"""rooms: two to four agents working on one goal at the same time - its members, its list of items and what is said in it; what a room may spend, by conversation; a room's post as it was handed to a member; a command and a change no agent's call made

Revision ID: 0039
Revises: 0038
"""
import sqlalchemy as sa
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rooms",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=True),
        sa.Column("why", sa.String(length=12), nullable=True),
        sa.Column("max_posts", sa.Integer(), nullable=True),
        sa.Column("max_tokens", sa.Integer(), nullable=True),
        sa.Column("max_minutes", sa.Integer(), nullable=True),
        sa.Column("seconds", sa.Float(), nullable=False),
        sa.Column("clock_since", sa.DateTime(), nullable=True),
        sa.Column("told", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("rooms") as batch:
        batch.create_index(batch.f("ix_rooms_run_id"), ["run_id"], unique=False)
    op.create_table(
        "room_members",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("room_id", sa.String(length=32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=60), nullable=False),
        sa.Column("provider_id", sa.String(length=32), nullable=True),
        sa.Column("model_id", sa.String(length=200), nullable=True),
        sa.Column("agent_id", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("seen", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("room_members") as batch:
        batch.create_index(batch.f("ix_room_members_room_id"), ["room_id"], unique=False)
    op.create_table(
        "room_items",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("room_id", sa.String(length=32), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("paths", sa.JSON(), nullable=False),
        sa.Column("holder_agent_id", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("room_id", "number", name="uq_room_items_number"),
    )
    with op.batch_alter_table("room_items") as batch:
        batch.create_index(batch.f("ix_room_items_room_id"), ["room_id"], unique=False)
    op.create_table(
        "room_posts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("room_id", sa.String(length=32), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=True),
        sa.Column("type", sa.String(length=8), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("to_agent_id", sa.String(length=32), nullable=True),
        sa.Column("reply_to", sa.Integer(), nullable=True),
        sa.Column("open", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("room_id", "number", name="uq_room_posts_number"),
    )
    with op.batch_alter_table("room_posts") as batch:
        batch.create_index(batch.f("ix_room_posts_room_id"), ["room_id"], unique=False)
    # A conversation from before this lets a room spend what a new one does.
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("room_posts", sa.Integer(), server_default="40", nullable=True))
        batch.add_column(
            sa.Column("room_tokens", sa.Integer(), server_default="400000", nullable=True))
        batch.add_column(
            sa.Column("room_minutes", sa.Integer(), server_default="30", nullable=True))
    with op.batch_alter_table("messages") as batch:
        batch.add_column(sa.Column("room_post_id", sa.String(length=32), nullable=True))
    # What KOLONİ itself does with a room's copy hangs off no agent's call.
    for table in ("commands", "file_changes"):
        with op.batch_alter_table(table) as batch:
            batch.alter_column("tool_call_id", existing_type=sa.String(length=32), nullable=True)


def downgrade() -> None:
    # Only a room left such records; they go with it.
    for table in ("commands", "file_changes"):
        op.execute(f"DELETE FROM {table} WHERE tool_call_id IS NULL")
        with op.batch_alter_table(table) as batch:
            batch.alter_column("tool_call_id", existing_type=sa.String(length=32), nullable=False)
    # A room's post in a member's conversation says nothing without its room.
    op.execute("DELETE FROM messages WHERE room_post_id IS NOT NULL")
    with op.batch_alter_table("messages") as batch:
        batch.drop_column("room_post_id")
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("room_minutes")
        batch.drop_column("room_tokens")
        batch.drop_column("room_posts")
    op.drop_table("room_posts")
    op.drop_table("room_items")
    op.drop_table("room_members")
    op.drop_table("rooms")
