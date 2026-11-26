"""Notes in two places: Memory and the job's notebook (0.1.10)

- `projects.project_notes`: the Project notes - what the user kept at a turn's end - are the second
  box of the project's rules on Memory's Told tab, no longer a knowledge of their own. What each
  project's old "Project notes" knowledge holds (`sources == ["notes:"]`) is copied in: the line of
  each of its pages, as its `learned.json` in the project's folder lists them, `- <line>` each, the
  newest that fit in MOST characters. The folder is only read - a link, a file over a megabyte or
  one that does not parse is passed over - and the knowledge, its pages and the roles that use it
  are left as they are: nothing is deleted.
- `backlog_tasks.notes`: a To-do task of no story (a task's chat, a night's job) keeps a notebook
  as a story does.

Going back drops both columns: 0.1.9 has the old knowledge as it was; what was added to either
after the upgrade goes with them (the copy KOLONİ made before it, `runtime/data/backups/`, is the
database without it).

Revision ID: 0196
Revises: 0195
"""

import json
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0196"
# (Written on the k-defter branch: re-chained after main's newest at its merge.)
down_revision = "0195"
branch_labels = None
depends_on = None

# As `app.project_notes` holds them from now on (a migration does not follow later code).
MOST = 4000
LINE = 200
LEARNED = Path(".koloni", "knowledge", "project-notes", "learned.json")
BIGGEST = 1 << 20


def _lines(root: str) -> list[str]:
    """The notes' lines as the folder's learned.json lists them, oldest first; none where it is
    not there, is a link, is too big or does not parse."""
    try:
        where = Path(root) / LEARNED
        if not where.resolve().is_relative_to(Path(root).resolve()):  # (a link on its way)
            return []
        if where.is_symlink() or not where.is_file() or where.stat().st_size > BIGGEST:
            return []
        read = json.loads(where.read_text(encoding="utf-8").removeprefix("﻿"))
    except (OSError, ValueError, RecursionError):
        return []
    pages = read.get("pages") if isinstance(read, dict) else None
    lines = []
    for page in pages if isinstance(pages, list) else []:
        line = page.get("line") if isinstance(page, dict) else None
        if isinstance(line, str) and (one := " ".join(line.split())[:LINE]):
            lines.append(f"- {one}")
    return lines


def _fitting(lines: list[str]) -> str | None:
    """The newest lines that fit in MOST characters, in their order."""
    kept: list[str] = []
    for line in reversed(lines):
        if len("\n".join([line, *kept])) > MOST:
            break
        kept.insert(0, line)
    return "\n".join(kept) or None


def _is_notes(sources: str | None) -> bool:
    try:
        return json.loads(sources or "null") == ["notes:"]
    except (ValueError, RecursionError):
        return False


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("project_notes", sa.Text(), nullable=True))
    with op.batch_alter_table("backlog_tasks") as batch:
        batch.add_column(sa.Column("notes", sa.JSON(), nullable=False, server_default="[]"))
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT DISTINCT p.id, p.root_path FROM knowledge k JOIN projects p "
            "ON p.id = k.project_id"
        )
    ).all()
    for project_id, root in rows:
        has_notes = any(
            _is_notes(sources)
            for (sources,) in conn.execute(
                sa.text("SELECT sources FROM knowledge WHERE project_id = :p"), {"p": project_id}
            )
        )
        if has_notes and (kept := _fitting(_lines(root))):
            conn.execute(
                sa.text("UPDATE projects SET project_notes = :n WHERE id = :p"),
                {"n": kept, "p": project_id},
            )


def downgrade() -> None:
    # shortcut: a task's notebook and the Project notes kept after the upgrade go with their
    # columns; write them into 0.1.9's places (a knowledge's pages) if that loss is ever missed.
    with op.batch_alter_table("backlog_tasks") as batch:
        batch.drop_column("notes")
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("project_notes")
