"""Migration 0147 (tek-ev, the user 6 Nov): a project has its chats' sub-agent settings, with
the defaults a chat had; a new chat's discussions have no token limit, and one from before keeps
the 200000 it has. Going back gives new ones that again."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config

AT = "2026-11-06 10:00:00"
CHAT = "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, 'c', ?, ?)"


def test_a_project_has_the_sub_agent_settings_and_a_new_discussion_no_token_limit(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0146")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO projects (id, name, root_path, created_at) "
                     "VALUES ('p', 'P', 'C:/p', ?)", (AT,))
        conn.execute(CHAT, ("old", AT, AT))

    command.upgrade(cfg, "0147")
    with sqlite3.connect(db) as conn:
        conn.execute(CHAT, ("new", AT, AT))
        assert conn.execute(
            "SELECT spawn_approval, spawn_max_depth, spawn_max_agents, spawn_max_parallel, "
            "discussion_budget, room_posts, room_tokens, room_minutes FROM projects"
        ).fetchall() == [("auto", 2, 6, 2, None, 40, None, 30)]
        assert conn.execute(
            "SELECT id, discussion_budget FROM conversations ORDER BY id"
        ).fetchall() == [("new", None), ("old", 200_000)]

    command.downgrade(cfg, "0146")
    with sqlite3.connect(db) as conn:
        conn.execute(CHAT, ("back", AT, AT))
        assert conn.execute(
            "SELECT id, discussion_budget FROM conversations ORDER BY id"
        ).fetchall() == [("back", 200_000), ("new", None), ("old", 200_000)]
        assert "spawn_approval" not in [row[1] for row in conn.execute("PRAGMA table_info(projects)")]


CHAT_WITH = ("INSERT INTO conversations (id, project_id, title, created_at, updated_at, spawn_approval, "
             "spawn_max_depth, spawn_max_agents, spawn_max_parallel, room_posts, room_minutes, "
             "room_tokens, discussion_budget, when_away, away_minutes, lead_work) "
             "VALUES (?, ?, 'c', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")


def test_each_project_takes_the_strictest_of_its_chats_and_a_turn_reads_that(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.db.models import Conversation, lead_work_of, settings_of

    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0146")
    with sqlite3.connect(db) as conn:
        for pid, work in (("p", "itself"), ("q", "delegates"), ("r", "delegates")):
            conn.execute("INSERT INTO projects (id, name, root_path, created_at, lead_work) "
                         "VALUES (?, ?, ?, ?, ?)", (pid, pid, f"C:/{pid}", AT, work))
        for row in (
            # loose everywhere, and the old defaults of a room's and a discussion's tokens
            ("c1", "p", "never", 4, 10, 8, 100, None, 400_000, 200_000, "lead", 5, "itself"),
            # strict where the other is loose
            ("c2", "p", "always", 3, 3, 4, 20, 60, 50_000, 200_000, "waits", 30, "decides"),
            # a value not known counts as the strictest
            ("c4", "p", "sometimes", 4, 10, 8, 100, None, None, None, "lead", 5, "itself"),
            # a discussion's limit someone set; no limit on a room's tokens
            ("c3", "q", "auto", 2, 6, 2, 40, 30, None, 5000, "lead", 10, "delegates"),
        ):
            conn.execute(CHAT_WITH, (row[0], row[1], AT, AT, *row[2:]))

    # (To the head, not 0147: `settings_of` reads through today's models, whose select names every
    # column added since - 0150's on projects too - so a database left at 0147 cannot be read.)
    command.upgrade(cfg, "head")
    engine = create_engine(f"sqlite:///{db}")
    names = ("spawn_approval", "spawn_max_depth", "spawn_max_agents", "spawn_max_parallel",
             "room_posts", "room_minutes", "room_tokens", "discussion_budget", "when_away",
             "away_minutes")
    with Session(engine) as session:
        read = {cid: (*(getattr(settings_of(session, chat), name) for name in names),
                      lead_work_of(session, chat))
                for cid in ("c1", "c2", "c3", "c4") if (chat := session.get_one(Conversation, cid))}
    engine.dispose()
    # (the new columns from the chats alone; when_away, away_minutes, lead_work the project's own too)
    strict_p = ("always", 3, 3, 4, 20, 60, 50_000, None, "waits", 30, "decides")
    assert read == {"c1": strict_p, "c2": strict_p, "c4": strict_p,
                    "c3": ("auto", 2, 6, 2, 40, 30, None, 5000, "waits", 10, "delegates")}
    # a project with no chats keeps the defaults
    with sqlite3.connect(db) as conn:
        assert conn.execute(f"SELECT {', '.join(names)} FROM projects WHERE id = 'r'").fetchone() == (
            "auto", 2, 6, 2, 40, 30, None, None, "waits", 10)
    # Back to 0146: each chat takes what it followed, none looser than it was.
    command.downgrade(cfg, "0146")
    with sqlite3.connect(db) as conn:
        assert conn.execute(f"SELECT id, {', '.join(names)}, lead_work FROM conversations "
                            "ORDER BY id").fetchall() == [
            ("c1", *strict_p), ("c2", *strict_p),
            ("c3", "auto", 2, 6, 2, 40, 30, None, 5000, "waits", 10, "delegates"),
            ("c4", *strict_p)]
