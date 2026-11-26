"""Rooms are gone (0.1.10, the user's 26 Nov: 2 to 6 agents writing in one copy at once runs
against KOLONİ's own way - each writer in a copy of its own, then merged - and a discussion lets
agents talk): `open_room` from every role's tools; what a room may spend, from every folder and
chat; a recipe's Room step becomes an "All at once" group with a step of each of its roles, in its
place (`app.schemas.without_rooms`, which reads a folder's recipe file so too); and each chat that
had a room says so in one line where it was. The rooms' own tables stay as they were - what was
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
Revises: 0190
"""

import json
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0193"
# (Written on the k-oda-sil branch on 0190, 0.1.10's head then; 0191 and 0192 are other branches'.)
down_revision = "0190"
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


def _fresh(base: object, taken: set) -> str:
    n = 1
    while (made := f"{str(base)[:36]}-{n}") in taken:
        n += 1
    taken.add(made)
    return made


def without_rooms(graph: object) -> object:
    """`app.schemas.without_rooms` as it was when this was written: a migration does not follow
    later code."""
    if not isinstance(graph, dict) or not isinstance(graph.get("steps"), list):
        return graph
    steps, groups = [], list(graph.get("groups") or [])
    taken = {
        one.get("id")
        for one in [*graph["steps"], *groups, *(graph.get("ends") or [])]
        if isinstance(one, dict)
    }
    for step in graph["steps"]:
        who = step.get("who") if isinstance(step, dict) else None
        if not (isinstance(who, dict) and isinstance(who.get("room"), list)):
            steps.append(step)
            continue
        roles = list(dict.fromkeys(one for one in who["room"] if isinstance(one, str)))
        rest = {key: value for key, value in step.items() if key not in ("id", "name", "who")}
        if len(roles) < 2 or rest.get("group") is not None:
            ids = [step.get("id")] + [_fresh(step.get("id"), taken) for _one in roles[1:]]
            names = [step.get("name", ""), *roles[1:]]
            steps += [
                {**rest, "id": i, "name": name, "who": {"role": one}}
                for i, name, one in zip(ids, names, roles or [""], strict=False)
            ]
            continue
        group = {"id": step.get("id"), "name": step.get("name", "")}
        if rest.get("pos") is not None:
            group["pos"] = rest["pos"]
        groups.append(group)
        rest = {**rest, "group": step.get("id")}
        rest.pop("pos", None)
        steps += [
            {**rest, "id": _fresh(step.get("id"), taken), "name": one, "who": {"role": one}}
            for one in roles
        ]
    return {**graph, "steps": steps, "groups": groups} if steps != graph["steps"] else graph


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
