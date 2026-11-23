"""The To-do list's built-in roles named for KOLONİ's hive (K-rol-adlari, the user, 23 Nov: "Product
owner is company jargon, people who don't use it may not know it"): the Product owner is the Hive
keeper, the Assistant product owner the Scout - the same jobs

The two built-in rows take the new names and, where still as KOLONİ wrote them, the new one-line
descriptions. What names a role by its name follows: each recipe's steps (`graph.steps[].who` - a
role, a step's candidates, a room's roles: the ready Spec's and the user's copies) and each saved
slash command (`own_commands.role`). A role of the user's own already named "Hive keeper" or
"Scout" (whatever its case) keeps its name: the built-in is then "Hive keeper (built-in)" or "Scout
(built-in)", and what named the old built-in names that. Past conversations - their agents' names,
rooms and records - are history: not rewritten. Teams hold their roles by id: nothing to do there.
shortcut: a recipe file of a folder's own (`.koloni/recipes`) is no row - one naming an old role
says it is unknown as it runs, as any role deleted since does; rename it there.

Going back gives the built-in rows their old names where they still bear a new one and the old is
free, the old descriptions where the new still stand, and what names a built-in's new name the old.

Revision ID: 0174
Revises: 0173
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0174"
# (Written on the k-rol-adlari branch: re-chained after main's newest at its merge.)
down_revision = "0173"
branch_labels = None
depends_on = None

BUILT_IN = " (built-in)"
# (old name, new name, old description, new description) - as they were written: a migration does
# not follow later code.
RENAMED = (
    (
        "Product owner",
        "Hive keeper",
        "Keeps the project's To-do list: breaks a goal into tasks, each with what makes it done, "
        "and puts them in order.",
        "Keeps the To-do list: turns a goal into tasks, each with what makes it done, and puts "
        "them in order.",
    ),
    (
        "Assistant product owner",
        "Scout",
        "Helps keep the To-do list: splits vague tasks, asks what is missing, flags problems and "
        "assesses finished work against what makes it done.",
        "After each turn, looks for what is left and suggests follow-up tasks; checks finished "
        "tasks against what makes them done.",
    ),
)


def _named(names: dict[str, str], name: object) -> object:
    """`name` as it is to be: its new one where `names` has it (whatever its case)."""
    return names.get(name.casefold(), name) if isinstance(name, str) else name


def _who(who: object, names: dict[str, str]) -> object:
    """A step's `who` with the roles it names renamed: a role, a step's candidates, a room's."""
    if not isinstance(who, dict):
        return who
    who = dict(who)
    for key in ("role", "candidates"):
        if key in who:
            who[key] = _named(names, who[key])
    if isinstance(who.get("room"), list):
        who["room"] = [_named(names, one) for one in who["room"]]
    return who


def _follow(bind, names: dict[str, str]) -> None:
    """Each recipe step and saved command that names a key of `names` (casefolded) names its value."""
    for id_, graph in bind.execute(sa.text("SELECT id, graph FROM recipes")).all():
        drawn = json.loads(graph) if isinstance(graph, str) else graph
        steps = drawn.get("steps") if isinstance(drawn, dict) else None
        if not isinstance(steps, list):
            continue
        now = [
            {**one, "who": _who(one.get("who"), names)} if isinstance(one, dict) else one
            for one in steps
        ]
        if now != steps:
            bind.execute(
                sa.text("UPDATE recipes SET graph = :graph WHERE id = :id"),
                {"graph": json.dumps({**drawn, "steps": now}), "id": id_},
            )
    for id_, role in bind.execute(
        sa.text("SELECT id, role FROM own_commands WHERE role IS NOT NULL")
    ).all():
        if (now := _named(names, role)) != role:
            bind.execute(
                sa.text("UPDATE own_commands SET role = :role WHERE id = :id"),
                {"role": now, "id": id_},
            )


def _taken(bind, name: str, but: str | None = None) -> bool:
    """Whether a role other than `but` (an id) bears `name`, whatever its case."""
    return (
        bind.execute(
            sa.text("SELECT 1 FROM roles WHERE lower(name) = lower(:name) AND id IS NOT :but"),
            {"name": name, "but": but},
        ).first()
        is not None
    )


def upgrade() -> None:
    bind = op.get_bind()
    names: dict[str, str] = {}
    for old, new, was, now in RENAMED:
        row = bind.execute(
            sa.text("SELECT id, description FROM roles WHERE name = :old AND builtin = 1"),
            {"old": old},
        ).first()
        if row is None:  # (none yet: `seed_builtin_roles` adds it by its new name)
            names[old.casefold()] = new
            continue
        to = new + BUILT_IN if _taken(bind, new, row[0]) else new
        bind.execute(
            sa.text("UPDATE roles SET name = :to, description = :description WHERE id = :id"),
            {"to": to, "description": now if row[1] == was else row[1], "id": row[0]},
        )
        names[old.casefold()] = to
    _follow(bind, names)


def downgrade() -> None:
    bind = op.get_bind()
    names: dict[str, str] = {}
    for old, new, was, now in RENAMED:
        for id_, name, description in bind.execute(
            sa.text(
                "SELECT id, name, description FROM roles WHERE builtin = 1 AND name IN (:a, :b)"
            ),
            {"a": new, "b": new + BUILT_IN},
        ).all():
            if _taken(bind, old, id_):  # (one of the user's took the old name since: kept)
                continue
            bind.execute(
                sa.text("UPDATE roles SET name = :old, description = :description WHERE id = :id"),
                {"old": old, "description": was if description == now else description, "id": id_},
            )
            names[name.casefold()] = old
    _follow(bind, names)
