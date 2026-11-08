"""the Lead and the teams' leads are told how to split a job between agents (K-rol-cogul)

The user's: the split rule is to reach their Lead, not only a new install. Added to the end of the
built-in Lead's instructions and of each team lead's, only where they are still word for word as
KOLONİ gave them: instructions the user changed are left alone. Going back takes away exactly
what was added, where it is still there as added.

Revision ID: 0106
Revises: 0105
"""
import sqlalchemy as sa
from alembic import op

revision = "0106"
# (On main a slice in queue is 0104: chained after it there.)
down_revision = "0105"
branch_labels = None
depends_on = None

# As they were when this was written (app.roles): a migration does not follow later code.
LEAD = ("Do small jobs yourself. Hand a part of the work to a sub-agent when it is a separate job "
        "for another role, and tell them everything they need: they see only the task you write.")
LEAD_SPLITS = ("When a job is big and splits into independent parts (separate files or modules), "
               "you may give each part its own agent, asked for in one reply, never the same file "
               "to two; a small job stays with you.")
TEAM_LEAD = ("Run your team's stages in order with the recipe you were given; hand findings to "
             "the right role; report to the Lead.")
TEAM_SPLITS = ("When a job is big and splits into independent parts (separate files or modules), "
               "you may give each part its own agent, within what your step draws, asked for in "
               "one reply, never the same file to two; a small job stays with you.")
# Who, what it was given, what is added: the built-in Lead; each team's lead.
WHO = ((LEAD, LEAD_SPLITS, "name = 'Lead' AND builtin = 1"),
       (TEAM_LEAD, TEAM_SPLITS, "kind = 'lead'"))


def _swap(back: bool) -> None:
    for was, splits, where in WHO:
        now = f"{was} {splits}"
        old, new = (now, was) if back else (was, now)
        op.get_bind().execute(sa.text(
            f"UPDATE roles SET instructions = :new WHERE {where} AND instructions = :old"),
            {"new": new, "old": old})


def upgrade() -> None:
    _swap(back=False)


def downgrade() -> None:
    _swap(back=True)
