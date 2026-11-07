"""a team's lead is told its roles do every file job, not that a small job stays with it (B-202)

B-202 (live): a team's lead has no tool that writes; told "a small job stays with you", one set
out to write a page itself and asked the user to route the work. Each team's lead's instructions
are rewritten only where they are still word for word as KOLONİ gave them - the ready teams' (0106,
"report to the Lead") or a team made since (`app.roles` then, "report to the Orchestrator");
instructions the user changed are left alone. Going back gives the ready teams' words, where the
new ones are still there as given.

Revision ID: 0153
Revises: 0152
"""
import sqlalchemy as sa
from alembic import op

revision = "0153"
# (Written on the k-room-steps branch: re-chained after main's newest at its merge.)
down_revision = "0152"
branch_labels = None
depends_on = None

# As they were when this was written (app.roles): a migration does not follow later code.
STAGES = ("Run your team's stages in order with the recipe you were given; hand findings to the "
          "right role; report to the {who}.")
WAS_SPLITS = ("When a job is big and splits into independent parts (separate files or modules), "
              "you may give each part its own agent, within what your step draws, asked for in "
              "one reply, never the same file to two; a small job stays with you.")
WAS = tuple(f"{STAGES.format(who=who)} {WAS_SPLITS}" for who in ("Lead", "Orchestrator"))
NOW = ("Run your team's stages in order with the recipe you were given. Your roles do the work: "
       "hand every file job and every finding to the right role - you write no file yourself; "
       "report to the Orchestrator. When a job is big and splits into independent parts "
       "(separate files or modules), you may give each part its own agent, within what your step "
       "draws, asked for in one reply, never the same file to two; a small job goes to one agent.")


def _set(new: str, old: str) -> None:
    op.get_bind().execute(sa.text(
        "UPDATE roles SET instructions = :new WHERE kind = 'lead' AND instructions = :old"),
        {"new": new, "old": old})


def upgrade() -> None:
    for old in WAS:
        _set(NOW, old)


def downgrade() -> None:
    _set(WAS[0], NOW)
