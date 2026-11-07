"""0109, 0121 and 0122 again, with the tools compared in any order (B-335)

Those three gave a built-in role its new tools only where its list was exactly as KOLONİ gave
it, order included; but 0097 and older migrations put their tools last, so on an upgraded
install the Lead (and through effective_tools every helper it opens) got no browser tools, and
other roles may have missed theirs too. Each change is made again where the role's tools are
the same set as before it but in another order - view_image and diagram_image left out of the
comparison, as later migrations give them whatever the list was. The same list in the very order
it was is not B-335's: the old migration did see it, or the user saved it so (the page saves a
role's tools in that order) and took the new tools off; it is left alone. Going back changes
nothing: 0109, 0121 and 0122's own downgrades take their tools off.

Revision ID: 0129
Revises: 0128
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0129"
# (Written on the k-r124-r125 branch: re-chained after main's newest at its merge.)
down_revision = "0128"
branch_labels = None
depends_on = None

# As they were when this was written (0109, 0121, 0122): a migration does not follow later code.
READ = ["list_dir", "read_file", "search"]
WRITE = ["write_file", "edit_file"]
TALK = ["ask_user", "message_agent"]
BACKLOG = ["read_backlog", "add_task", "change_task", "assess_task"]
KEEP = ["post_note", "read_notes", "remember", "recall"]
OPS = [*READ, *WRITE, "run_command", "web_search"]
BROWSER = ["browser_open", "browser_screenshot", "browser_click", "browser_type", "browser_key",
           "browser_scroll", "browser_read", "browser_console"]
SPEC_WAS = ("Read enough of the project to know what is there, and ask the user what the "
            "request leaves open. Write requirements that can be checked and scenarios a test "
            "can follow; do not write code or change files.")
SPEC_NOW = ("Read enough of the project to know what is there, and ask the user what the "
            "request leaves open. Write requirements that can be checked and scenarios a test "
            "can follow. Write only the document you are asked for (docs/..., say); never code.")
SUMMARY_WAS = ("Keep what was decided, what is still open and who is doing what; leave out the "
               "rest. Post the summary as a note and keep what lasts in the project's memory.")
SUMMARY_NOW = (f"{SUMMARY_WAS} Write only the summary file you are asked for (docs/..., say), "
               "if one is; never code.")


# Given by later migrations to roles whatever their lists were (0125; K-drawio's diagram_image).
IGNORED = {"view_image", "diagram_image"}


def _spawn(tools: list[str]) -> list[str]:
    at = tools.index("ask_user")
    return [*tools[:at], "spawn_agent", *tools[at:]]


def _browser(tools: list[str]) -> list[str]:
    at = max(tools.index(name) for name in ("run_command", "http_request", "show")
             if name in tools) + 1
    return [*tools[:at], *BROWSER, *tools[at:]]


def _write(tools: list[str]) -> list[str]:
    at = max(tools.index(name) for name in [*READ, "view_image"] if name in tools) + 1
    return [*tools[:at], *WRITE, *tools[at:]]


# In the order they ran: the role, its instructions before (None: any), its tools before, and
# what the migration gave it. A role 0121 now gives spawn_agent is then as 0122 expects.
CHANGES = (
    # 0109
    ("Spec writer", SPEC_WAS, SPEC_NOW, [*READ, *TALK, *KEEP], _write),
    ("Summarizer", SUMMARY_WAS, SUMMARY_NOW, [*READ, "message_agent", *KEEP], _write),
    # 0121
    ("Architect", None, None, [*READ, *TALK, *KEEP], _spawn),
    ("Debugger", None, None, [*READ, *WRITE, "run_command", *TALK, *KEEP], _spawn),
    ("Product owner", None, None, [*READ, *TALK, *BACKLOG, *KEEP], _spawn),
    ("Spec writer", None, None, [*READ, *WRITE, *TALK, *KEEP], _spawn),
    ("DevOps", None, None, [*OPS, *TALK, *KEEP], _spawn),
    ("MLOps engineer", None, None, [*OPS, *TALK, *KEEP], _spawn),
    # 0122
    ("Lead", None, None, [*READ, *WRITE, "show", "run_command", "web_search", "http_request",
                          "notify", "spawn_agent", "create_role", "add_skill", "ask_user",
                          "ask_folder", "message_agent", "open_room", "discuss", "read_backlog",
                          "add_task", "change_task", "assess_task", "propose_trigger", *KEEP],
     _browser),
    ("Coder", None, None, [*READ, *WRITE, "run_command", "spawn_agent", *TALK, *KEEP], _browser),
    ("Tester", None, None, [*READ, "run_command", *TALK, *KEEP], _browser),
    ("Researcher", None, None, [*READ, "web_search", "http_request", *TALK, *KEEP], _browser),
    ("Debugger", None, None, [*READ, *WRITE, "run_command", "spawn_agent", *TALK, *KEEP],
     _browser),
    ("UI designer", None, None, [*READ, *WRITE, "show", *TALK, *KEEP], _browser),
)


def upgrade() -> None:
    bind = op.get_bind()
    for name, said, now_said, was, give in CHANGES:
        for id_, held, instructions in bind.execute(sa.text(
                "SELECT id, tools, instructions FROM roles WHERE name = :name AND builtin = 1"),
                {"name": name}).fetchall():
            tools = json.loads(held) if isinstance(held, str) else held
            others = [tool for tool in tools if tool not in IGNORED]
            if set(others) != set(was) or others == was:
                continue
            if said is not None and instructions != said:
                continue
            # (In the role's own order; the new tools where app.roles puts them.)
            bind.execute(sa.text(
                "UPDATE roles SET tools = :tools, instructions = :said WHERE id = :id"),
                {"tools": json.dumps(give(tools)), "id": id_,
                 "said": instructions if now_said is None else now_said})


def downgrade() -> None:
    pass
