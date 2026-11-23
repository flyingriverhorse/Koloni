"""The To-do list's built-in roles named for KOLONİ's hive (K-rol-adlari, the user, 23 Nov: "Product
owner is company jargon, people who don't use it may not know it"): the Product owner is the Hive
keeper, the Assistant product owner the Scout - the same jobs

The two built-in rows take the new names and, where still as KOLONİ wrote them, the new one-line
descriptions. What names a role by its name follows: each recipe's steps (`graph.steps[].who` - a
role, a step's candidates, a room's roles: the ready Spec's and the user's copies) and each saved
slash command (`own_commands.role`). A role of the user's own already named "Hive keeper" or
"Scout" (as names are told apart: case, spaces and their kinds aside) keeps its name: the built-in
is then "Hive keeper (built-in)" or "Scout (built-in)" (or "(built-in 2)" … where that is taken
too), and what named the old built-in names that. A role of the user's own that bears an OLD name
(where no built-in was ever added beside it) is theirs: what names it is left as it is. A saved
slash command named as a built-in now is ("scout") - hidden behind the role's chip in the message
box - takes a free name ("scout-command"). Past conversations - their agents' names, rooms and
records - are history: not rewritten. Teams hold their roles by id: nothing to do there.
shortcut: a recipe file of a folder's own (`.koloni/recipes`) is no row - one naming an old role
says it is unknown as it runs (and that it is the new one now: `roles.WAS_NAMED`); rename it there.

Going back gives the built-in rows their old names where they still bear a new one and the old is
free, the old descriptions where the new still stand, and what names a built-in's new name the old;
a command given a free name keeps it.

Revision ID: 0174
Revises: 0173
"""

import json
import re
import unicodedata

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
        "Keeps watch on the To-do list: splits vague tasks, asks what is missing, flags "
        "duplicates, stale and blocked tasks, and checks finished tasks against what makes them "
        "done.",
    ),
)
_BUILT_IN = re.compile(r" \(built-in(?: \d+)?\)$")


def _norm(name: str) -> str:
    """A role's name as names are told apart: NFKC, what does not print a space, runs of spaces
    one, case folded (`roles.shown_name`, `find_role`) - "Scout\xa0" is "scout"."""
    plain = unicodedata.normalize("NFKC", name)
    return " ".join("".join(ch if ch.isprintable() else " " for ch in plain).split()).casefold()


def _fold(name: str) -> str:
    """A command's name as the message box's menu looks it up (`api.own_commands.fold`)."""
    plain = unicodedata.normalize("NFD", name.lower())
    return "".join(c for c in plain if not unicodedata.category(c).startswith("M")).replace(
        "ı", "i"
    )


def _named(names: dict[str, str], name: object) -> object:
    """`name` as it is to be: its new one where `names` has it (`_norm`)."""
    return names.get(_norm(name), name) if isinstance(name, str) else name


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
    """Each recipe step and saved command that names a key of `names` (`_norm`) names its value."""
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
    """Whether a role other than `but` (an id) bears `name`, as names are told apart (`_norm`)."""
    return any(
        _norm(one) == _norm(name)
        for one in bind.execute(
            sa.text("SELECT name FROM roles WHERE id IS NOT :but"), {"but": but}
        ).scalars()
    )


def _free(bind, new: str, but: str) -> str:
    """The built-in's new name - or, where a role of the user's bears it, the first of
    "<new> (built-in)", "<new> (built-in 2)" … none bears."""
    for n in range(1, 100):
        to = new if n == 1 else new + BUILT_IN if n == 2 else f"{new} (built-in {n - 1})"
        if not _taken(bind, to, but):
            return to
    raise RuntimeError(f"no free name for the built-in {new}")


def _commands_named(bind, role: str) -> None:
    """A saved command named as the role now is ("scout") would be hidden behind the role's chip
    in the message box - and refused if saved now: it takes a free name ("scout-command")."""
    rows = bind.execute(sa.text("SELECT id, name FROM own_commands")).all()
    taken = {_fold(name) for _id, name in rows}
    for id_, name in rows:
        if _fold(name) != _fold(role):
            continue
        to = next(
            one
            for n in range(1, 1000)
            if _fold(one := f"{name}-command" if n == 1 else f"{name}-command-{n}") not in taken
        )
        taken.add(_fold(to))
        bind.execute(
            sa.text("UPDATE own_commands SET name = :to WHERE id = :id"), {"to": to, "id": id_}
        )


def upgrade() -> None:
    bind = op.get_bind()
    names: dict[str, str] = {}
    for old, new, was, now in RENAMED:
        row = bind.execute(
            sa.text("SELECT id, description FROM roles WHERE name = :old AND builtin = 1"),
            {"old": old},
        ).first()
        if row is None:
            # (none yet - `seed_builtin_roles` adds it by its new name - unless a role of the
            # user's bears the old one: what names it is theirs, and stays so)
            if not _taken(bind, old):
                names[_norm(old)] = new
            continue
        to = _free(bind, new, row[0])
        bind.execute(
            sa.text("UPDATE roles SET name = :to, description = :description WHERE id = :id"),
            {"to": to, "description": now if row[1] == was else row[1], "id": row[0]},
        )
        names[_norm(old)] = to
        _commands_named(bind, to)
    _follow(bind, names)


def downgrade() -> None:
    bind = op.get_bind()
    names: dict[str, str] = {}
    for old, new, was, now in RENAMED:
        for id_, name, description in bind.execute(
            sa.text("SELECT id, name, description FROM roles WHERE builtin = 1")
        ).all():
            if _BUILT_IN.sub("", name) != new:
                continue
            if _taken(bind, old, id_):  # (one of the user's took the old name since: kept)
                continue
            bind.execute(
                sa.text("UPDATE roles SET name = :old, description = :description WHERE id = :id"),
                {"old": old, "description": was if description == now else description, "id": id_},
            )
            names[_norm(name)] = old
    _follow(bind, names)
