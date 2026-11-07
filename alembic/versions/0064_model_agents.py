"""a provider's model saved before slice 81a says whether agents may use it: what its
provider said of all of them (slice 81a-2)

Revision ID: 0064
Revises: 0063
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0064"
down_revision = "0063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A row without `agents` read as on everywhere, while its provider's `for_agents` kept
    # agents off it: the row now says what the provider did.
    conn = op.get_bind()
    for provider_id, for_agents, models in conn.execute(
        sa.text("SELECT id, for_agents, models FROM providers WHERE models IS NOT NULL")
    ).fetchall():
        rows = json.loads(models) if isinstance(models, str) else models
        if not isinstance(rows, list) or all("agents" in row for row in rows):
            continue
        said = [{**row, "agents": bool(for_agents)} if "agents" not in row else row
                for row in rows]
        conn.execute(sa.text("UPDATE providers SET models = :models WHERE id = :id"),
                     {"models": json.dumps(said), "id": provider_id})


def downgrade() -> None:
    # Nothing to undo: before 81a a row's `agents` was not read, and its provider's
    # `for_agents` is left as it was.
    pass
