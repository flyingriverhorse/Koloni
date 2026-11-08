"""roles' categories of their own (slice 63b): a name, a colour and a place, a role's kind its key

The four built-in kinds of work become categories under their keys, names and colours; any other
kind a role has (the user's own words) becomes one too, named as it was, under a key of its own
(the words may hold "/", "#" or "?", which a key in an address cannot), and its roles are given
that key. So no role is left without one. A team's lead is in none.

Revision ID: 0079
Revises: 0078
"""
import uuid

import sqlalchemy as sa
from alembic import op

revision = "0079"
down_revision = "0078"
branch_labels = None
depends_on = None

# As they were when this was written (app.roles): a migration does not follow later code.
BUILT_IN = (("plan", "Plan", "violet"), ("build", "Build", "amber"),
            ("check", "Check", "green"), ("write", "Write & keep up", "blue"))
LEADS = "SELECT lead_role_id FROM teams WHERE lead_role_id IS NOT NULL"


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("colour", sa.String(length=16), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    bind = op.get_bind()
    taken = {key for key, _name, _colour in BUILT_IN}
    own = [kind for (kind,) in bind.execute(sa.text(
        f"SELECT kind FROM roles WHERE id NOT IN ({LEADS}) "
        "GROUP BY kind ORDER BY MIN(created_at), kind")) if kind not in taken]
    # (A kind was 1 to 40 printable characters: the name it is shown by as it was, numbered where
    # another category has it, whatever its case.)
    rows, names = list(BUILT_IN), {name.casefold() for _key, name, _colour in BUILT_IN}
    for kind in own:
        name, n = kind, 1
        while name.casefold() in names:
            n += 1
            name = f"{kind[:37]} {n}"
        names.add(name.casefold())
        key = uuid.uuid4().hex
        bind.execute(sa.text(f"UPDATE roles SET kind = :key WHERE kind = :old AND id NOT IN ({LEADS})"),
                     {"key": key, "old": kind})
        rows.append((key, name, "brown"))
    for at, (key, name, colour) in enumerate(rows):
        bind.execute(sa.text(
            "INSERT INTO categories (key, name, colour, position) VALUES (:k, :n, :c, :at)"
        ), {"k": key, "n": name, "c": colour, "at": at})


def downgrade() -> None:
    # A role of one of the user's categories is given back its words: the category's name.
    built_in = ", ".join(f"'{key}'" for key, _name, _colour in BUILT_IN)
    op.execute(f"UPDATE roles SET kind = (SELECT name FROM categories WHERE key = roles.kind) "
               f"WHERE kind IN (SELECT key FROM categories WHERE key NOT IN ({built_in}))")
    op.drop_table("categories")
