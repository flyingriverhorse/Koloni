"""the roles that read files get view_image (28e)

view_image looks at an image of the project and only reads, as read_file does: each role that
holds read_file - built in, or one the user or an agent made - is given it after its other file
reading tools, where app.roles puts it. Going back takes it off every role.

Revision ID: 0125
Revises: 0124
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0125"
# (Written on the k-28e branch: re-chained after main's newest at its merge.)
down_revision = "0124"
branch_labels = None
depends_on = None

# As they were when this was written (app.roles): a migration does not follow later code.
READ = ["list_dir", "read_file", "search"]


def _changed(tools: list[str], back: bool) -> list[str]:
    if back:
        return [tool for tool in tools if tool != "view_image"]
    if "read_file" not in tools or "view_image" in tools:
        return tools
    at = max(tools.index(name) for name in READ if name in tools) + 1
    return [*tools[:at], "view_image", *tools[at:]]


def _swap(back: bool) -> None:
    bind = op.get_bind()
    for id_, held in bind.execute(sa.text("SELECT id, tools FROM roles")):
        tools = json.loads(held) if isinstance(held, str) else held
        if (new := _changed(tools, back)) != tools:
            bind.execute(sa.text("UPDATE roles SET tools = :tools WHERE id = :id"),
                         {"tools": json.dumps(new), "id": id_})


def upgrade() -> None:
    _swap(back=False)


def downgrade() -> None:
    _swap(back=True)
