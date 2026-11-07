"""teams' leads get open_room and discuss (K-lider-araclari)

0073's leads (and those made before 84e, with the same tools) lack the two, which 84e gave every
new team's lead: a Room step such a lead runs beside another team could not open its room. Every
team's lead whose tools are still that untouched set gets them, whatever its team is called; one
the user changed is left as it is.

Revision ID: 0080
Revises: 0079
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0080"
down_revision = "0079"
branch_labels = None
depends_on = None

# As they were when this was written (0073's lead tools, app.roles' order of tools): a migration
# does not follow later code.
SEEDED = ["list_dir", "read_file", "search", "spawn_agent", "ask_user", "message_agent",
          "post_note", "read_notes", "remember", "recall"]
WITH_ROOMS = ["list_dir", "read_file", "search", "spawn_agent", "ask_user", "message_agent",
              "open_room", "discuss", "post_note", "read_notes", "remember", "recall"]


def _change(were: list[str], now: list[str]) -> None:
    bind = op.get_bind()
    leads = bind.execute(sa.text(
        "SELECT roles.id, roles.tools FROM teams JOIN roles ON roles.id = teams.lead_role_id"
    )).fetchall()
    for role_id, tools in leads:
        # (The same tools in another order are still untouched.)
        if sorted(json.loads(tools)) == sorted(were):
            bind.execute(sa.text("UPDATE roles SET tools = :tools WHERE id = :id"),
                         {"tools": json.dumps(now), "id": role_id})


def upgrade() -> None:
    _change(SEEDED, WITH_ROOMS)


def downgrade() -> None:
    _change(WITH_ROOMS, SEEDED)
