"""six built-in roles get the browser tools (slice 51)

The Lead, Coder, Tester, Researcher, Debugger and UI designer are given browser_open ...
browser_console - only where their tools are still as KOLONİ gave them: a list the user changed
is left alone. Going back takes them off where the list is still as this made it.

Revision ID: 0122
Revises: 0121
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0122"
# (Written on the k-51-tarayici branch: re-chained after main's newest at its merge.)
down_revision = "0121"
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
    ("Lead", [*READ, *WRITE, "show", "run_command", "web_search", "http_request", "notify",
              "spawn_agent", "create_role", "add_skill", "ask_user", "ask_folder", "message_agent",
              "open_room", "discuss", "read_backlog", "add_task", "change_task", "assess_task",
              "propose_trigger", *KEEP]),
    ("Coder", [*READ, *WRITE, "run_command", "spawn_agent", *TALK, *KEEP]),
    ("Tester", [*READ, "run_command", *TALK, *KEEP]),
    ("Researcher", [*READ, "web_search", "http_request", *TALK, *KEEP]),
    ("Debugger", [*READ, *WRITE, "run_command", "spawn_agent", *TALK, *KEEP]),
    ("UI designer", [*READ, *WRITE, "show", *TALK, *KEEP]),
)


def _with_browser(tools: list[str]) -> list[str]:
    """The browser tools after the last of run_command, http_request and show: where
    app.roles puts them."""
    at = max(tools.index(name) for name in ("run_command", "http_request", "show")
             if name in tools) + 1
    return [*tools[:at], *BROWSER, *tools[at:]]


def _swap(back: bool) -> None:
    bind = op.get_bind()
    for name, was in ROLES:
        old, new = (_with_browser(was), was) if back else (was, _with_browser(was))
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
