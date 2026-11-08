"""six more built-in roles may open a helper with spawn_agent (K-spawn-roller, R121)

Live: an Architect, Debugger, Product owner, Spec writer, DevOps or MLOps engineer could open
no helper, not even of its own role ("No such tool available: spawn_agent"). Each is given
spawn_agent where the Coder's list has it - only where its tools are still as KOLONİ gave them:
a list the user changed is left alone, and so are its instructions, which are the user's in the
record (migration 0106). Going back takes it off where the list is still as this made it.

Revision ID: 0121
Revises: 0120
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0121"
# (Written on the k-spawn-roller branch: re-chained after main's newest at its merge.)
down_revision = "0120"
branch_labels = None
depends_on = None

# As they were when this was written (app.roles): a migration does not follow later code.
READ = ["list_dir", "read_file", "search"]
WRITE = ["write_file", "edit_file"]
TALK = ["ask_user", "message_agent"]
BACKLOG = ["read_backlog", "add_task", "change_task", "assess_task"]
KEEP = ["post_note", "read_notes", "remember", "recall"]
OPS = [*READ, *WRITE, "run_command", "web_search"]
# Its name and its tools before; spawn_agent goes in front of ask_user.
ROLES = (
    ("Architect", [*READ, *TALK, *KEEP]),
    ("Debugger", [*READ, *WRITE, "run_command", *TALK, *KEEP]),
    ("Product owner", [*READ, *TALK, *BACKLOG, *KEEP]),
    ("Spec writer", [*READ, *WRITE, *TALK, *KEEP]),
    ("DevOps", [*OPS, *TALK, *KEEP]),
    ("MLOps engineer", [*OPS, *TALK, *KEEP]),
)


def _with_spawn(tools: list[str]) -> list[str]:
    at = tools.index("ask_user")
    return [*tools[:at], "spawn_agent", *tools[at:]]


def _swap(back: bool) -> None:
    bind = op.get_bind()
    for name, was in ROLES:
        old, new = (_with_spawn(was), was) if back else (was, _with_spawn(was))
        for id_, held in bind.execute(sa.text(
                "SELECT id, tools FROM roles WHERE name = :name AND builtin = 1"), {"name": name}):
            # (The same tools in another order are still as KOLONİ gave them: 0097 and older
            # migrations put theirs last, so an upgraded Lead was skipped - B-335.)
            if sorted(json.loads(held) if isinstance(held, str) else held) == sorted(old):
                bind.execute(sa.text("UPDATE roles SET tools = :tools WHERE id = :id"),
                             {"tools": json.dumps(new), "id": id_})


def upgrade() -> None:
    _swap(back=False)


def downgrade() -> None:
    _swap(back=True)
