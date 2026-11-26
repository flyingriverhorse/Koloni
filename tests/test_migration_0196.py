"""Migration 0196 (0.1.10, notes in two places): a project's 0.1.9 Project notes knowledge has its
pages' lines copied into `projects.project_notes` - Memory's, the rules' second box - from the
folder's learned.json, which is only read; the newest that fit are kept, a link or a broken file is
passed over, and the knowledge row stays. A task of no story gets a notebook of its own. Going back
drops both columns."""

import json
import sqlite3

from alembic import command

from tests.test_migration_0002 import _config
from tests.test_migration_0177 import AT, columns

LEARNED = (".koloni", "knowledge", "project-notes", "learned.json")


def _project(conn, pid: str, root, sources: list | None) -> None:
    conn.execute(
        "INSERT INTO projects (id, name, root_path, created_at) VALUES (?, ?, ?, ?)",
        (pid, pid, str(root), AT),
    )
    if sources is not None:
        conn.execute(
            "INSERT INTO knowledge (id, project_id, topic, sources, max_pages, max_usd, removed, "
            "weekly, created_at) VALUES (?, ?, 'Project notes', ?, 1000, 0.5, '[]', 0, ?)",
            (f"k{pid}", pid, json.dumps(sources), AT),
        )


def _learned(root, pages) -> None:
    where = root.joinpath(*LEARNED)
    where.parent.mkdir(parents=True)
    where.write_text(json.dumps({"pages": pages}), encoding="utf-8")


def test_the_notes_lines_are_copied_into_memory_and_go_back_with_their_column(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0195")
    roots = {name: tmp_path / name for name in ("kept", "long", "broken", "mine", "none")}
    for root in roots.values():
        root.mkdir()
    _learned(
        roots["kept"],
        [
            {"line": "Coder's report (its words): the tax - fixed: added it"},
            {"line": "docs/a.md   (its words):\nnew words"},
            {"source": "no line"},
            "not a page",
        ],
    )
    _learned(roots["long"], [{"line": f"{n} " + "x" * 300} for n in range(40)])
    roots["broken"].joinpath(*LEARNED[:-1]).mkdir(parents=True)
    roots["broken"].joinpath(*LEARNED).write_text("{not json", encoding="utf-8")
    _learned(roots["mine"], [{"line": "a knowledge of the user's own, not the notes"}])
    with sqlite3.connect(db) as conn:
        _project(conn, "kept", roots["kept"], ["notes:"])
        _project(conn, "long", roots["long"], ["notes:"])
        _project(conn, "broken", roots["broken"], ["notes:"])
        _project(conn, "mine", roots["mine"], ["docs"])
        _project(conn, "none", roots["none"], None)
        _project(conn, "gone", tmp_path / "gone", ["notes:"])
        conn.execute(
            "INSERT INTO backlog_tasks (id, project_id, title, priority, status, position, "
            "created_by, created_at) VALUES ('t', 'kept', 't', 'normal', 'todo', 0, 'user', ?)",
            (AT,),
        )
        known = conn.execute("SELECT * FROM knowledge ORDER BY id").fetchall()
    command.upgrade(cfg, "0196")
    with sqlite3.connect(db) as conn:
        kept = dict(conn.execute("SELECT id, project_notes FROM projects"))
        assert kept["kept"] == (
            "- Coder's report (its words): the tax - fixed: added it\n- docs/a.md (its words): new words"
        )
        assert {kept[one] for one in ("broken", "mine", "none", "gone")} == {None}
        # The newest that fit, each cut to its line's 200 characters.
        lines = kept["long"].split("\n")
        assert len(kept["long"]) <= 4000 and lines[-1].startswith("- 39 x")
        assert len(lines) == 19 and all(len(line) == 202 for line in lines)
        # Nothing of the knowledge goes; nothing in the folder changes.
        assert conn.execute("SELECT * FROM knowledge ORDER BY id").fetchall() == known
        assert conn.execute("SELECT notes FROM backlog_tasks").fetchone() == ("[]",)
    assert json.loads(roots["kept"].joinpath(*LEARNED).read_text(encoding="utf-8"))["pages"][0]
    command.downgrade(cfg, "0195")
    with sqlite3.connect(db) as conn:
        assert "project_notes" not in columns(conn, "projects")
        assert "notes" not in columns(conn, "backlog_tasks")


def test_a_notes_file_reached_through_a_link_is_passed_over(tmp_path):
    import os

    import pytest

    elsewhere, root = tmp_path / "elsewhere", tmp_path / "linked"
    elsewhere.mkdir()
    root.mkdir()
    _learned(elsewhere, [{"line": "read from outside the folder"}])
    try:
        os.symlink(elsewhere / ".koloni", root / ".koloni", target_is_directory=True)
    except OSError:
        pytest.skip("no symbolic link can be made here")
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0195")
    with sqlite3.connect(db) as conn:
        _project(conn, "linked", root, ["notes:"])
    command.upgrade(cfg, "0196")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT project_notes FROM projects").fetchone() == (None,)
