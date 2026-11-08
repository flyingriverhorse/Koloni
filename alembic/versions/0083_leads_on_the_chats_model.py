"""teams' leads run on the chat's model (batch-16)

0073's leads (and every team's made since) came with "balanced or stronger" as their tier rule:
a lead with no model of its own ran on a balanced model while the chat was on a faster one (REA,
25 Oct: sonnet beside a haiku chat). A team's lead is its team's own Lead, which runs on the
chat's model: a lead whose rule is still that untouched one gets the conversation's model as its
rule. One the user changed is left as it is.

Revision ID: 0083
Revises: 0082
"""
from alembic import op

revision = "0083"
down_revision = "0082"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE roles SET tier = 'conversation', tier_min = NULL WHERE kind = 'lead' "
               "AND tier IS NULL AND tier_min = 'balanced' AND tier_max IS NULL")


def downgrade() -> None:
    op.execute("UPDATE roles SET tier = NULL, tier_min = 'balanced' WHERE kind = 'lead' "
               "AND tier = 'conversation' AND tier_min IS NULL AND tier_max IS NULL")
