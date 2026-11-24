"""Qoder is no longer run (the user, 24 Nov: "qoder sil")

A provider of kind `qoder_cli` stays - its name, models, notes and what points at it (a role, a
chat, a tier) - but switched off: what used it falls back as for any switched-off provider, and
the Models page says why it cannot be switched on again (`app.providers.RETIRED`). Nothing is
deleted: the user deletes the row once what used it is moved elsewhere.

Going back leaves the rows off: whether each was on before is not kept, and the user switches it
on again in that version.

Revision ID: 0181
Revises: 0180
"""

from alembic import op

revision = "0181"
# (Written on the k-qoder-sil branch: re-chained after main's newest at its merge.)
down_revision = "0180"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE providers SET enabled = 0 WHERE kind = 'qoder_cli'")


def downgrade() -> None:
    pass
