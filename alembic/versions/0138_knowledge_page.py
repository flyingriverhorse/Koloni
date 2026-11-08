"""knowledge as the project's own, roles using it (K-bilgi)

A role's knowledge becomes a row of `knowledge`, in no project (in every project: a role has no
project, and its guide was learned in each project's `.koloni/knowledge/<topic>/`, which stays
where it is); the role uses it in full (`roles.knows`). Going back gives a role the first knowledge
it uses in full; a map, and a knowledge no role uses in full, are not kept. A knowledge many roles
use in full (or one folder's knowledge in two projects) comes back to each of them: they then share
its folder, which before K-bilgi only one role could (`knowledge.taken`).

Revision ID: 0138
Revises: 0137
"""
import json
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0138"
# (Written on the k-bilgi branch: re-chained after main's newest at its merge.)
down_revision = "0137"
branch_labels = None
depends_on = None

# A role's knowledge's keys, and the column each is kept in.
COLUMNS = {"topic": "topic", "sources": "sources", "max_pages": "max_pages",
           "max_usd": "max_usd", "learn_with": "learn_with", "removed": "removed",
           "weekly": "weekly", "search_answering": "search_web"}
JSONS = ("sources", "learn_with", "removed")
DEFAULTS = {"max_pages": 500, "max_usd": 0.5, "weekly": False, "search_answering": False}


def _loaded(value):
    return json.loads(value) if isinstance(value, str) else value


def upgrade() -> None:
    op.create_table(
        "knowledge",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.String(32), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("topic", sa.String(40), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("max_pages", sa.Integer(), nullable=False),
        sa.Column("max_usd", sa.Float(), nullable=False),
        sa.Column("learn_with", sa.JSON(), nullable=True),
        sa.Column("removed", sa.JSON(), nullable=False),
        sa.Column("weekly", sa.Boolean(), nullable=False),
        sa.Column("search_web", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_knowledge_project_id", "knowledge", ["project_id"])
    with op.batch_alter_table("roles") as batch:
        batch.add_column(sa.Column("knows", sa.JSON(), nullable=False, server_default="[]"))
    bind = op.get_bind()
    made = datetime.now(UTC).replace(tzinfo=None).isoformat(" ", "microseconds")
    for role, kept in bind.execute(sa.text(
            "SELECT id, knowledge FROM roles WHERE knowledge IS NOT NULL")).fetchall():
        known = _loaded(kept)
        if not isinstance(known, dict):
            continue
        row = uuid.uuid4().hex
        # (A knowledge saved before a key was added has none: the schema's default then.)
        values = {column: known.get(key, DEFAULTS.get(key)) for key, column in COLUMNS.items()}
        values.update({key: json.dumps(values[key]) for key in JSONS})
        values["removed"] = json.dumps(known.get("removed") or [])
        bind.execute(sa.text(
            f"INSERT INTO knowledge (id, project_id, {', '.join(COLUMNS.values())}, created_at) "
            f"VALUES (:id, NULL, {', '.join(f':{one}' for one in COLUMNS.values())}, :at)"),
            {**values, "id": row, "at": made})
        bind.execute(sa.text("UPDATE roles SET knows = :knows WHERE id = :id"), {
            "id": role, "knows": json.dumps([{"knowledge_id": row, "mode": "full"}])})
    with op.batch_alter_table("roles") as batch:
        batch.drop_column("knowledge")


def downgrade() -> None:
    with op.batch_alter_table("roles") as batch:
        batch.add_column(sa.Column("knowledge", sa.JSON(), nullable=True))
    bind = op.get_bind()
    rows = {row[0]: row for row in bind.execute(sa.text(
        f"SELECT id, {', '.join(COLUMNS.values())} FROM knowledge")).fetchall()}
    for role, knows in bind.execute(sa.text("SELECT id, knows FROM roles")).fetchall():
        full = next((rows[one["knowledge_id"]] for one in _loaded(knows) or []
                     if one.get("mode") == "full" and one.get("knowledge_id") in rows), None)
        if full is None:
            continue
        known = dict(zip(COLUMNS, full[1:], strict=True))
        known.update({key: _loaded(known[key]) for key in JSONS})
        known["weekly"] = bool(known["weekly"])
        if known["search_answering"] is not None:
            known["search_answering"] = bool(known["search_answering"])
        bind.execute(sa.text("UPDATE roles SET knowledge = :known WHERE id = :id"),
                     {"id": role, "known": json.dumps(known)})
    with op.batch_alter_table("roles") as batch:
        batch.drop_column("knows")
    op.drop_index("ix_knowledge_project_id", "knowledge")
    op.drop_table("knowledge")
