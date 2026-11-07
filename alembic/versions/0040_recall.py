"""what was said in a project's finished turns, in a full-text index that recall looks in; a project: whether a fast model notes what a turn found, and how that went last; a note: the model that made it

Revision ID: 0040
Revises: 0039
"""
import sqlalchemy as sa
from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A project from before this has nothing noted by itself: the user has not said so.
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column(
            "auto_notes", sa.Boolean(), server_default=sa.false(), nullable=False))
        batch.add_column(sa.Column("last_auto", sa.JSON(), nullable=True))
    with op.batch_alter_table("memories") as batch:
        batch.add_column(sa.Column("noted_by", sa.JSON(), nullable=True))
    # SQLite's own full-text index (FTS5), in plain SQL: a virtual table is nothing
    # Alembic's batch mode knows. `words` is all that is searched - what was said, evened
    # out by KOLONİ before it is written (`app.earlier.evened`), so the tokenizer folds
    # nothing itself. Empty here: the turns there already are indexed when the app starts.
    # The words' first two and three letters are indexed too: a question's words are looked
    # for by how a word begins, and a short beginning is then found without a scan.
    op.execute(
        "CREATE VIRTUAL TABLE said_in_turns USING fts5("
        "words, said UNINDEXED, project_id UNINDEXED, conversation_id UNINDEXED, "
        "run_id UNINDEXED, agent UNINDEXED, at UNINDEXED, "
        "tokenize = \"unicode61 remove_diacritics 0 tokenchars '_'\", prefix = '2 3')"
    )


def downgrade() -> None:
    op.execute("DROP TABLE said_in_turns")
    with op.batch_alter_table("memories") as batch:
        batch.drop_column("noted_by")
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("last_auto")
        batch.drop_column("auto_notes")
