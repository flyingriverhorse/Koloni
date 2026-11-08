"""a chat's teams - who picks them (the Lead, the user, nobody) and each with its recipe - and a
project's for its new chats; a chat's one team becomes its one Manual row (slice 84b)

Revision ID: 0075
Revises: 0074
"""
import uuid

import sqlalchemy as sa
from alembic import op

revision = "0075"
down_revision = "0074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_teams",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("conversation_id", sa.String(length=32), nullable=False),
        sa.Column("team_id", sa.String(length=32), nullable=False),
        sa.Column("recipe_id", sa.String(length=32), nullable=True),
        sa.Column("picked_by", sa.String(length=8), nullable=False),
        sa.Column("why", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversation_teams_conversation_id", "conversation_teams",
                    ["conversation_id"])
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("teams_mode", sa.String(length=8), server_default="none",
                                   nullable=False))
        batch.add_column(sa.Column("teams", sa.JSON(), server_default="[]", nullable=False))
    bind = op.get_bind()
    # (A team deleted since is no row: the chat has "No teams".) Read before the table is
    # rebuilt, and the rows written after: a rebuild never takes them with it.
    held = bind.execute(sa.text(
        "SELECT conversations.id, teams.id, teams.default_recipe_id FROM conversations "
        "JOIN teams ON teams.id = conversations.team_id")).all()
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("teams_mode", sa.String(length=8), server_default="none",
                                   nullable=False))
        batch.drop_column("team_id")
    for cid, team, recipe in held:
        bind.execute(sa.text(
            "INSERT INTO conversation_teams (id, conversation_id, team_id, recipe_id, picked_by, "
            "position) VALUES (:id, :cid, :team, :recipe, 'user', 0)"),
            {"id": uuid.uuid4().hex, "cid": cid, "team": team, "recipe": recipe})
        bind.execute(sa.text("UPDATE conversations SET teams_mode = 'manual' WHERE id = :cid"),
                     {"cid": cid})


def downgrade() -> None:
    bind = op.get_bind()
    # A chat's first Manual row is its one team again; the Lead's picks and the others go.
    # (Read before the table is rebuilt, as above.)
    first = bind.execute(sa.text(
        "SELECT conversations.id, (SELECT team_id FROM conversation_teams WHERE "
        "conversation_id = conversations.id ORDER BY position LIMIT 1) FROM conversations "
        "WHERE teams_mode = 'manual'")).all()
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("team_id", sa.String(length=32), nullable=True))
        batch.drop_column("teams_mode")
    for cid, team in first:
        bind.execute(sa.text("UPDATE conversations SET team_id = :team WHERE id = :cid"),
                     {"team": team, "cid": cid})
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("teams")
        batch.drop_column("teams_mode")
    op.drop_index("ix_conversation_teams_conversation_id", table_name="conversation_teams")
    op.drop_table("conversation_teams")
