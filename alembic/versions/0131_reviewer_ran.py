"""a checking role says "verified" only of what it ran itself (K-kanit)

The live-test agent: a Reviewer wrote "verified" of what it never ran, and its Lead took it on.
The four built-in checking roles - Tester, Reviewer, Security reviewer, Model evaluator - are told
to list what they ran under "ran:" and say "not run" of the rest, added to the end of their
instructions only where they are still word for word as KOLONİ gave them: instructions the user
changed are left alone. Going back takes away exactly what was added, where it is still there.

Revision ID: 0131
Revises: 0130
"""
import sqlalchemy as sa
from alembic import op

revision = "0131"
# (Written on the k-kanit branch: re-chained after main's newest at its merge.)
down_revision = "0130"
branch_labels = None
depends_on = None

# As they were when this was written (app.roles): a migration does not follow later code.
RAN = ("Say \"verified\" or \"works\" only of what you ran yourself in this turn, and list each "
       "test or command under \"ran:\" in your report; say \"not run\" of anything else.")
ROLES = {
    "Tester": "Run the checks you are asked to run and report the results exactly. Do not "
              "change files.",
    "Reviewer": "Read the code under review and report concrete problems with file and line. "
                "Say plainly when you find none. Do not change files.",
    "Security reviewer": "Read the code as an attacker would: what comes in from outside, what "
                         "is trusted, where secrets go. Report concrete problems with file and "
                         "line, and how each could be used. Say plainly when you find none. Do "
                         "not change files.",
    "Model evaluator": "Run the evaluation you are asked to run and compare each metric with the "
                       "previous model's, both numbers side by side. Look for leakage between "
                       "training and test data and for drift. Report the results exactly. Do not "
                       "change files.",
}


def _swap(back: bool) -> None:
    for name, was in ROLES.items():
        now = f"{was} {RAN}"
        old, new = (now, was) if back else (was, now)
        op.get_bind().execute(sa.text(
            "UPDATE roles SET instructions = :new WHERE name = :name AND builtin = 1 "
            "AND instructions = :old"), {"new": new, "old": old, "name": name})


def upgrade() -> None:
    _swap(back=False)


def downgrade() -> None:
    _swap(back=True)
