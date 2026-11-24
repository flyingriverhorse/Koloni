"""Cards measured (0.1.7, the user: "evet ölçelim"): why a command's card was asked, and when the
user answered it

`commands.asked_reason`: the family of the reason the card was asked for, as KOLONİ's gate saw it
the moment the card opened (`app.cards.card_reason`: delete, send, install, shell, secret …) -
written by KOLONİ, never from an agent's words; a rule changed later does not rewrite it. None:
no card was asked, or the command is from before this. `commands.decided_at`: when the user
answered its card from the app's own page (a turn that ended with the card open is no answer).

Going back drops both.

Revision ID: 0173
Revises: 0172
"""

import sqlalchemy as sa
from alembic import op

revision = "0173"
# (Written on the k-kart-olcum branch: re-chained after main's newest at its merge.)
down_revision = "0172"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("commands") as batch:
        batch.add_column(sa.Column("asked_reason", sa.String(16), nullable=True))
        batch.add_column(sa.Column("decided_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("commands") as batch:
        batch.drop_column("decided_at")
        batch.drop_column("asked_reason")
