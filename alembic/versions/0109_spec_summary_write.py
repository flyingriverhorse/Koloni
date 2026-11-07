"""the built-in Spec writer and Summarizer write the document they are asked for (B-190)

Live: the Research and Spec recipes could not write the project file asked for (docs/...):
neither role had a tool that writes. Each is given write_file and edit_file, as the Docs
writer has, and told to write only that document - never code. Only where the built-in role
is still as KOLONİ gave it, its tools and its instructions both: one the user changed is left
alone. Going back puts exactly what was there back, where it is still as this made it.

Revision ID: 0109
Revises: 0108
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0109"
# (Another slice takes 0107: chained after it at merge.)
down_revision = "0108"
branch_labels = None
depends_on = None

# As they were when this was written (app.roles): a migration does not follow later code.
READ = ["list_dir", "read_file", "search"]
WRITE = ["write_file", "edit_file"]
KEEP = ["post_note", "read_notes", "remember", "recall"]
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
# Its name; its tools and instructions before; and after.
ROLES = (
    ("Spec writer", [*READ, "ask_user", "message_agent", *KEEP], SPEC_WAS,
     [*READ, *WRITE, "ask_user", "message_agent", *KEEP], SPEC_NOW),
    ("Summarizer", [*READ, "message_agent", *KEEP], SUMMARY_WAS,
     [*READ, *WRITE, "message_agent", *KEEP], SUMMARY_NOW),
)


def _swap(back: bool) -> None:
    bind = op.get_bind()
    for name, *sides in ROLES:
        (tools, said), (new_tools, new_said) = (sides[2:], sides[:2]) if back else (
            sides[:2], sides[2:])
        for id_, held, instructions in bind.execute(sa.text(
                "SELECT id, tools, instructions FROM roles WHERE name = :name AND builtin = 1"),
                {"name": name}):
            held = json.loads(held) if isinstance(held, str) else held
            # (Tools in another order are still untouched - B-335.)
            if instructions == said and sorted(held) == sorted(tools):
                bind.execute(sa.text(
                    "UPDATE roles SET tools = :tools, instructions = :said WHERE id = :id"),
                    {"tools": json.dumps(new_tools), "said": new_said, "id": id_})


def upgrade() -> None:
    _swap(back=False)


def downgrade() -> None:
    _swap(back=True)
