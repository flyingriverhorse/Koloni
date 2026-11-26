"""Rooms are gone (0.1.10, the user's 26 Nov: 2 to 6 agents writing in one copy at once runs
against KOLONİ's own way - each writer in a copy of its own, then merged - and a discussion lets
agents talk): `open_room` from every role's tools; what a room may spend, from every folder and
chat; a recipe's Room step becomes an "All at once" group with a step of each of its roles, in its
place (`app.recipe_rooms.without_rooms`, which reads a folder's recipe file so too); and each turn that
had a room says so in one line in its chat. The rooms' own tables stay as they were - what was
said there is the user's - and a room left running is ended at every start
(`merge.recover_interrupted`).

Going back: the line goes, the budgets come back as 0.1.9 had them (each at its default), and the
built-in Lead gets `open_room` again.
shortcut: a Room step, once a group, is not told from a group the user drew, and stays one going
back; a team's lead or a role of the user's own that had `open_room` does not get it back - give
them on their card (Tools) if that is missed.
shortcut: the line says a room was there, not what was said in it (`room_posts` keeps that); show
an old room's posts read-only in its chat if that is missed.

Revision ID: 0193
Revises: 0192
"""

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0193"
# (Written on the k-oda-sil branch on 0190; chained after 0.1.10's 0192 at merge, before 0194.)
down_revision = "0192"
branch_labels = None
depends_on = None

TOOL = "open_room"
# As 0039, 0146 and 0154 left them (0147 gave folders the same).
BUDGETS = (("room_posts", "40"), ("room_tokens", None), ("room_minutes", "30"))
LEAST = ("room_min_tokens", "60000")
# What a chat that had a room says where it was: a "koloni" line, which no agent is given.
LINE = (
    "A room was opened here. Rooms were removed in 0.1.10: what its members said is kept in "
    "KOLONİ's record, not shown in the chat. For agents talking it over, ask for a discussion."
)


def _tools(held) -> list:
    return json.loads(held) if isinstance(held, str) else list(held)


# 0.1.9's Room step held at most this many roles (`WhoRoom`), and a recipe this many steps
# (`RecipeGraph`): a drawing with more is not read.
MOST_ROOM_ROLES, MOST_STEPS = 10, 60


def without_rooms(graph: object) -> object:
    """`app.recipe_rooms.without_rooms` as it was when this was written: a migration does not follow
    later code. 0.1.10, rooms are gone: a Room step ({"room": [roles]}, slice 84e) of a recipe drawn
    before - saved, a folder's file, a run's state - read as an "All at once" group in its place
    (its id, name and spot, so its arrows and loops still meet it) with a step of each role, named
    "<its name> · <role>", each keeping the step's other choices. One role, or none, is a plain
    step of it (none: "" - no role here, which the board says). A drawing of any other shape - a
    room of more than 10 roles or more than 60 steps, as 0.1.9 refused them, steps, groups or ends
    no list - is left as it is, for the schema to say why.
    shortcut: a room that ran only if a problem was found (`when`) becomes a group that always runs
    - a group runs on no condition; draw a review before it and the condition by hand if one is
    seen to cost too much."""
    if not isinstance(graph, dict):
        return graph
    steps_in, groups_in, ends_in = (graph.get(key) for key in ("steps", "groups", "ends"))
    if (
        not isinstance(steps_in, list)
        or len(steps_in) > MOST_STEPS
        or not all(isinstance(one, list | None) for one in (groups_in, ends_in))
    ):
        return graph
    rooms = [one for one in steps_in if isinstance(one, dict) and _room_of(one) is not None]
    if not rooms or not all(
        isinstance(one.get("id"), str)
        and isinstance(room := _room_of(one), list)
        and len(room) <= MOST_ROOM_ROLES
        for one in rooms
    ):
        return graph
    nodes = [*steps_in, *(groups_in or []), *(ends_in or [])]
    taken = {one["id"] for one in nodes if isinstance(one, dict) and isinstance(one.get("id"), str)}
    names = {
        one["name"].casefold()
        for one in steps_in
        if isinstance(one, dict) and isinstance(one.get("name"), str)
    }
    # The roles that do the recipe's work at a step of their own (no review).
    writers = {
        str(who.get("role") or who.get("candidates")).casefold()
        for one in steps_in
        if isinstance(one, dict)
        and isinstance(who := one.get("who"), dict)
        and (who.get("role") or who.get("candidates"))
        and one.get("done_when") != "no_findings"
    }
    steps, groups = [], list(groups_in or [])
    for step in steps_in:
        room = _room_of(step) if isinstance(step, dict) else None
        if not isinstance(room, list):  # (no Room step: every one is a list by now)
            steps.append(step)
            continue
        roles = list(dict.fromkeys(one for one in room if isinstance(one, str)))
        rest = {key: value for key, value in step.items() if key not in ("id", "name", "who")}
        name = step["name"] if isinstance(step.get("name"), str) else ""
        fresh = _fresh(step["id"], taken)
        if len(roles) < 2 or rest.get("group") is not None:
            # (A room in a group was never ready: its roles go into that group.)
            steps += [
                {
                    **rest,
                    "id": step["id"] if at == 0 else next(fresh),
                    "name": name if at == 0 else _named(name, one, names),
                    "who": {"role": one},
                }
                for at, one in enumerate(roles or [""])
            ]
            continue
        group = {"id": step["id"], "name": name}
        if rest.get("pos") is not None:
            group["pos"] = rest["pos"]
        groups.append(group)
        # A room ran as a whole, and so did its condition and its review: a step in a group runs
        # on no condition of its own, and a role that does the work elsewhere would check its own
        # there - it works in the group, the others review (all of them review where that would
        # leave none: the recipe then says who would check its own work).
        rest = {**rest, "group": step["id"]}
        rest.pop("pos", None)
        rest.pop("when", None)
        works = (
            {one.casefold() for one in roles} & writers
            if rest.get("done_when") == "no_findings"
            and any(one.casefold() not in writers for one in roles)
            else set()
        )
        steps += [
            {
                **rest,
                "id": next(fresh),
                "name": _named(name, one, names),
                "who": {"role": one},
                **({"done_when": "done"} if one.casefold() in works else {}),
            }
            for one in roles
        ]
    return {**graph, "steps": steps, "groups": groups}


def _room_of(step: dict) -> object:
    """`without_rooms`: a step's room (its `who`'s "room"); None: no Room step."""
    who = step.get("who")
    return who.get("room") if isinstance(who, dict) else None


def _fresh(base: str, taken: set) -> Iterator[str]:
    """`without_rooms`: ids no node of the recipe has, from its Room step's (`NodeId`), one
    after another."""
    n = 1
    while True:
        while (made := f"{base[:36]}-{n}") in taken:
            n += 1
        taken.add(made)
        yield made


def _named(name: str, role: str, names: set) -> str:
    """`without_rooms`: "<the room's name> · <role>", within a step name's 60 characters, and no
    other step's (as a recipe is saved, two of one name are refused)."""
    made = (f"{name} · {role}" if name else role)[:54]  # (room for " 99999")
    n = 1
    while (shown := made if n == 1 else f"{made} {n}").casefold() in names:
        n += 1
    names.add(shown.casefold())
    return shown


def upgrade() -> None:
    bind = op.get_bind()
    # Every role, the user's own too: a role holding a tool that is gone is not saved again.
    for role_id, held in bind.execute(sa.text("SELECT id, tools FROM roles")).fetchall():
        tools = _tools(held)
        if TOOL in tools:
            bind.execute(
                sa.text("UPDATE roles SET tools = :tools WHERE id = :id"),
                {"tools": json.dumps([tool for tool in tools if tool != TOOL]), "id": role_id},
            )
    for recipe_id, held in bind.execute(sa.text("SELECT id, graph FROM recipes")).fetchall():
        graph = json.loads(held) if isinstance(held, str) else held
        now = without_rooms(graph)
        if now is not graph:
            bind.execute(
                sa.text("UPDATE recipes SET graph = :graph WHERE id = :id"),
                {"graph": json.dumps(now), "id": recipe_id},
            )
    rooms = bind.execute(
        sa.text(
            "SELECT runs.conversation_id, rooms.run_id, MIN(rooms.created_at) FROM rooms "
            "JOIN runs ON runs.id = rooms.run_id GROUP BY rooms.run_id"
        )
    ).fetchall()
    for conversation_id, run_id, at in rooms:
        bind.execute(
            sa.text(
                "INSERT INTO messages (id, conversation_id, run_id, role, content, status, "
                "created_at) VALUES (:id, :cid, :run, 'koloni', :line, 'complete', :at)"
            ),
            {
                "id": uuid.uuid4().hex,
                "cid": conversation_id,
                "run": run_id,
                "line": LINE,
                "at": at or datetime.now(UTC).replace(tzinfo=None),
            },
        )
    for table in ("conversations", "projects"):
        with op.batch_alter_table(table) as batch:
            for name, _default in (*BUDGETS, LEAST):
                batch.drop_column(name)


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM messages WHERE role = 'koloni' AND content = :line"), {"line": LINE}
    )
    for table in ("conversations", "projects"):
        with op.batch_alter_table(table) as batch:
            for name, default in (*BUDGETS, LEAST):
                batch.add_column(
                    sa.Column(name, sa.Integer(), nullable=True, server_default=default)
                )
    # The built-in Lead had it (ALL_TOOLS), after message_agent.
    for role_id, held in bind.execute(
        sa.text("SELECT id, tools FROM roles WHERE builtin AND name = 'Lead'")
    ).fetchall():
        tools = _tools(held)
        if TOOL in tools:
            continue
        at = tools.index("message_agent") + 1 if "message_agent" in tools else len(tools)
        bind.execute(
            sa.text("UPDATE roles SET tools = :tools WHERE id = :id"),
            {"tools": json.dumps([*tools[:at], TOOL, *tools[at:]]), "id": role_id},
        )
