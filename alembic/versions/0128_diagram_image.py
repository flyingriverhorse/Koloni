"""four built-in roles get diagram_image (K-drawio)

The Lead, Coder, Docs writer and UI designer are given diagram_image after their file tools -
only where their tools are still as KOLONİ gave them, in whatever order (B-335): a list the user
changed is left alone. Going back takes it off where the list is still as this made it.

Revision ID: 0128
Revises: 0127
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0128"
# (Written on the k-drawio branch: re-chained after main's newest at its merge.)
down_revision = "0127"
branch_labels = None
depends_on = None

# As they were when this was written (app.roles): a migration does not follow later code.
READ = ["list_dir", "read_file", "search"]
WRITE = ["write_file", "edit_file"]
TALK = ["ask_user", "message_agent"]
KEEP = ["post_note", "read_notes", "remember", "recall"]
BROWSER = ["browser_open", "browser_screenshot", "browser_click", "browser_type", "browser_key",
           "browser_scroll", "browser_read", "browser_console"]
ROLES = (
    ("Lead", [*READ, *WRITE, "show", "run_command", "web_search", "http_request", *BROWSER,
              "notify", "spawn_agent", "create_role", "add_skill", "ask_user", "ask_folder",
              "message_agent", "open_room", "discuss", "read_backlog", "add_task", "change_task",
              "assess_task", "propose_trigger", *KEEP]),
    ("Coder", [*READ, *WRITE, "run_command", *BROWSER, "spawn_agent", *TALK, *KEEP]),
    ("Docs writer", [*READ, *WRITE, *TALK, *KEEP]),
    ("UI designer", [*READ, *WRITE, "show", *BROWSER, *TALK, *KEEP]),
)
# Tools other migrations give, in any order (B-335: a list upgraded over the years is not in
# app.roles's order): a list is judged as KOLONİ gave it with or without them - 28e's view_image
# (0125) and slice 51's browser (0122, appended where a list was older).
EITHER = frozenset({"view_image", *BROWSER})
AFTER = (*READ, "view_image", *WRITE, "show")


def _with(tools: list[str]) -> list[str]:
    """diagram_image after the last of the file tools: where app.roles puts it."""
    at = max(tools.index(name) for name in AFTER if name in tools) + 1
    return [*tools[:at], "diagram_image", *tools[at:]]


def _swap(back: bool) -> None:
    bind = op.get_bind()
    for name, was in ROLES:
        old = set(was) - EITHER | ({"diagram_image"} if back else set())
        for id_, held in bind.execute(sa.text(
                "SELECT id, tools FROM roles WHERE name = :name AND builtin = 1"), {"name": name}):
            tools = json.loads(held) if isinstance(held, str) else held
            if set(tools) - EITHER != old:
                continue
            new = [tool for tool in tools if tool != "diagram_image"] if back else _with(tools)
            bind.execute(sa.text("UPDATE roles SET tools = :tools WHERE id = :id"),
                         {"tools": json.dumps(new), "id": id_})


def upgrade() -> None:
    _swap(back=False)


def downgrade() -> None:
    _swap(back=True)
