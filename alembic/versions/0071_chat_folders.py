"""a chat's extra folders are its own; every project's ("open_folders") go into each project's
defaults and its chats (slice 86b)

Revision ID: 0071
Revises: 0070
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0071"
down_revision = "0070"
branch_labels = None
depends_on = None


def _merged(write: list, read: list, more_write: list, more_read: list) -> tuple[list, list]:
    """Both lists with more of each, in order and once; one in both is one to write in."""
    write = list(dict.fromkeys([*write, *more_write]))
    return write, [f for f in dict.fromkeys([*read, *more_read]) if f not in write]


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT path, access FROM open_folders")).all()
    every_write = [path for path, access in rows if access == "write"]
    every_read = [path for path, access in rows if access == "read"]
    for pid, also, read in bind.execute(
            sa.text("SELECT id, also_in, read_in FROM projects")).all():
        also, read = _merged(json.loads(also or "[]"), json.loads(read or "[]"),
                             every_write, every_read)
        bind.execute(sa.text("UPDATE projects SET also_in = :a, read_in = :r WHERE id = :i"),
                     {"a": json.dumps(also), "r": json.dumps(read), "i": pid})
        # A chat's agents used its folder's lists as well as its own: now they are its own.
        for cid, own_also, own_read in bind.execute(sa.text(
                "SELECT id, also_in, read_in FROM conversations WHERE project_id = :p"),
                {"p": pid}).all():
            chat_also, chat_read = _merged(also, read, json.loads(own_also or "[]"),
                                           json.loads(own_read or "[]"))
            bind.execute(
                sa.text("UPDATE conversations SET also_in = :a, read_in = :r WHERE id = :i"),
                {"a": json.dumps(chat_also), "r": json.dumps(chat_read), "i": cid})
    op.drop_table("open_folders")


def downgrade() -> None:
    # (Empty: what was every project's is each project's and its chats' now, and stays so.)
    op.create_table(
        "open_folders",
        sa.Column("path", sa.Text(), primary_key=True),
        sa.Column("access", sa.String(5), nullable=False),
    )
