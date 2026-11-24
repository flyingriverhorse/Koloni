"""What a Copilot account offers (the user, 24 Nov: menus by the Copilot account)

`providers.offers` keeps what Copilot's `models.list` said of the account when last asked - its
models and Auto's tiers, each on or not and why (`app.copilot_offers`). Empty until then.

Going back drops the column: it is read again within ten minutes.

Revision ID: 0176
Revises: 0175
"""

import sqlalchemy as sa
from alembic import op

revision = "0176"
# (Written on the k-copilot-hesap branch: re-chained after main's newest at its merge.)
down_revision = "0175"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("providers") as batch:
        batch.add_column(sa.Column("offers", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("providers") as batch:
        batch.drop_column("offers")
