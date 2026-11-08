"""0.1.0-hijyen: what KOLONİ's runtime keeps does not grow for ever - a copy whose card is
decided goes at the next start, waiting work stays; vectors of what is gone are dropped; the
database is compacted when much of it is free; the log rotates."""

import os
import sqlite3

import pytest

import app.copies
from app.config import load_settings
from tests.test_copy_later_scenarios import again, interrupted


def _copy_folder(settings_env):
    runtime = load_settings(settings_env).runtime_root
    return [path for held in app.copies.folders(runtime) if held.is_dir()
            for path in held.iterdir()]


@pytest.mark.skipif(os.name != "nt", reason="a junction is Windows'")
def test_a_decided_copy_left_on_disk_goes_at_the_next_start_its_junction_as_a_link(
    settings_env, project_dir, tmp_path, monkeypatch
):
    import _winapi

    cid = interrupted(settings_env, project_dir)
    with again(settings_env) as client:
        (card,) = client.get(f"/api/conversations/{cid}").json()["merges"]
        assert card["status"] == "kept"                 # waiting: kept at the start
        (copy,) = _copy_folder(settings_env)
        # The folder cannot be deleted right now (a file held open): the card is decided all the same.
        with monkeypatch.context() as patched:
            patched.setattr(app.copies, "remove", lambda *a: (_ for _ in ()).throw(OSError("held")))
            assert client.post(f"/api/merges/{card['id']}/reject").status_code == 200
    assert copy.is_dir()
    target = tmp_path / "venv-target"
    (target / "Lib").mkdir(parents=True)
    (target / "Lib" / "keep.txt").write_text("main's", encoding="utf-8")
    _winapi.CreateJunction(str(target), str(copy / ".venv"))
    with again(settings_env) as client:
        assert client.get(f"/api/conversations/{cid}").json()["merges"][0]["status"] == "rejected"
    assert not copy.exists()
    assert (target / "Lib" / "keep.txt").read_text(encoding="utf-8") == "main's"


def _db(tmp_path):
    from app.db.session import upgrade_db

    path = tmp_path / "data" / "koloni.db"
    upgrade_db(path)
    return path


def test_vectors_of_what_is_gone_are_deleted_at_the_start_the_rest_kept(tmp_path):
    from sqlalchemy import text

    from app.db.models import Embedding, Memory, Project
    from app.db.session import make_engine, make_session_factory, tidy_db

    path = _db(tmp_path)
    engine = make_engine(path)
    with make_session_factory(engine)() as session:
        project = Project(name="p", root_path=str(tmp_path / "p"), embedding_model="m1")
        session.add(project)
        session.flush()
        kept = Memory(project_id=project.id, tier="note", text="kept", origin="user")
        other = Memory(project_id=project.id, tier="note", text="other", origin="user")
        session.add_all([kept, other])
        session.flush()
        row = session.execute(text(
            "INSERT INTO said_in_turns (words, said, project_id, conversation_id, run_id, agent, "
            "at) VALUES ('w', 'said', :p, 'c', 'r', 'Lead', '2026-01-01')"), {"p": project.id}
        ).lastrowid
        vector = [1.0, 0.0]
        session.add_all([
            Embedding(kind="memory", record_id=kept.id, project_id=project.id, model="m1",
                      vector=vector),
            Embedding(kind="turn", record_id=str(row), project_id=project.id, model="m1",
                      vector=vector),
            # gone: its record, its turn's row, its project, its model
            Embedding(kind="memory", record_id="nothere", project_id=project.id, model="m1",
                      vector=vector),
            Embedding(kind="turn", record_id=str(row + 99), project_id=project.id, model="m1",
                      vector=vector),
            Embedding(kind="memory", record_id=other.id, project_id="gone", model="m1",
                      vector=vector),
            Embedding(kind="memory", record_id=kept.id, project_id=project.id, model="old",
                      vector=vector),
        ])
        session.commit()
        expected = {("memory", kept.id, "m1"), ("turn", str(row), "m1")}
    engine.dispose()
    tidy_db(path)
    with sqlite3.connect(path) as conn:
        left = set(conn.execute("SELECT kind, record_id, model FROM embeddings"))
    assert left == expected


def _with_free_pages(path, megabytes):
    """A database that had `megabytes` of rows, deleted: its pages are free, the file as big."""
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE filler (blob BLOB)")
        conn.executemany("INSERT INTO filler VALUES (?)",
                         [(b"x" * 1024 * 1024,) for _ in range(megabytes)])
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("DELETE FROM filler")
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return path.stat().st_size


def test_the_database_is_compacted_only_when_much_of_it_is_free(tmp_path, monkeypatch):
    from app.db import session as db

    monkeypatch.setattr(db, "VACUUM_FREE_BYTES", 4 * 1024 * 1024)
    small = _db(tmp_path / "small")
    before = _with_free_pages(small, 3)                    # under the bytes: left as it is
    db.tidy_db(small)
    assert small.stat().st_size == before
    big = _db(tmp_path / "big")
    before = _with_free_pages(big, 8)
    db.tidy_db(big)
    assert big.stat().st_size < before / 2
    with sqlite3.connect(big) as conn:
        assert conn.execute("PRAGMA freelist_count").fetchone() == (0,)


def test_a_database_that_cannot_be_tidied_does_not_keep_kolonis_start(tmp_path, monkeypatch,
                                                                     caplog):
    from app.db import session as db

    path = _db(tmp_path)
    monkeypatch.setattr(db, "STALE_VECTORS", ("DELETE FROM no_such_table",))
    db.tidy_db(path)
    assert "database not tidied" in caplog.text


def test_the_log_rotates_by_size_holds_what_the_start_said_and_hides_keys(
    settings_env, tmp_path, monkeypatch
):
    import logging

    import uvicorn

    from app import main
    from app.db import session as db

    for name, value in settings_env.items():
        monkeypatch.setenv(name, value)
    runtime = load_settings(settings_env).runtime_root
    _with_free_pages(_db(runtime), 8)
    monkeypatch.setattr(db, "VACUUM_FREE_BYTES", 4 * 1024 * 1024)

    def serve(app, **kwargs):
        assert kwargs["log_config"] is None  # (set up before the app was made)
        logging.getLogger("uvicorn.access").info(
            '%s - "%s %s HTTP/%s" %d', "127.0.0.1:1", "GET", "/api/x?key=SECRET", "1.1", 200)
        logging.getLogger("httpx").info("HTTP Request: GET https://x/?key=SECRET")

    monkeypatch.setattr(uvicorn, "run", serve)
    names = ("", "uvicorn", "uvicorn.access", "uvicorn.error", "app")
    saved = {name: (lg.handlers[:], lg.level, lg.propagate, lg.disabled, lg.filters[:])
             for name in names for lg in [logging.getLogger(name)]}
    try:
        main.run()
    finally:
        for name, (handlers, level, propagate, disabled, filters) in saved.items():
            lg = logging.getLogger(name)
            for one in lg.handlers:
                if one not in handlers:
                    one.close()
            lg.handlers[:], lg.filters[:] = handlers, filters
            lg.level, lg.propagate, lg.disabled = level, propagate, disabled
    handler = main.log_config(runtime)["handlers"]["file"]
    assert handler["class"] == "logging.handlers.RotatingFileHandler"
    assert (handler["maxBytes"], handler["backupCount"]) == (10 * 2**20, 5)
    written = (runtime / "logs" / "koloni.log").read_text(encoding="utf-8")
    assert "database compacted" in written
    assert "key=[key]" in written and "SECRET" not in written


def test_what_kolonis_data_takes_is_counted_following_no_link(client, settings, tmp_path,
                                                              monkeypatch):
    import app.api.health as health

    (settings.runtime_root / "logs").mkdir(parents=True, exist_ok=True)
    (settings.runtime_root / "logs" / "koloni.log").write_bytes(b"x" * 2**20)
    held = app.copies.folder(settings.runtime_root)
    (held / "c1").mkdir(parents=True)
    (held / "c1" / "f").write_bytes(b"x" * 3 * 2**20)
    big = tmp_path / "big"
    big.mkdir()
    (big / "f").write_bytes(b"x" * 5 * 2**20)
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(big), str(held / "c1" / ".venv"))
    else:
        os.symlink(big, held / "c1" / ".venv")
    said = client.get("/api/storage").json()
    assert said["db_mb"] > 0
    assert (said["copies_mb"], said["logs_mb"]) == (3.0, 1.0)
    # (R125: the backups apart - "db 651 MB" was 535 MB of them)
    (settings.db_path.parent / "backups").mkdir(exist_ok=True)
    (settings.db_path.parent / "backups" / "koloni-1.db").write_bytes(b"x" * 2 * 2**20)
    said = client.get("/api/storage").json()
    assert said["backups_mb"] == 2.0 and said["db_mb"] < 2
    monkeypatch.setattr(health, "COUNT_SECONDS", -1)        # a count that takes too long
    assert client.get("/api/storage").json() == {
        "db_mb": None, "backups_mb": None, "copies_mb": None, "logs_mb": None}


def test_old_events_are_deleted_at_the_start_but_warnings_and_the_newest(tmp_path):
    # (Audit #9: each holds a call's whole arguments and result; only a page that reconnects
    # reads them, after the snapshot it loaded - and every injection warning is listed.)
    from app.db.session import tidy_db

    path = _db(tmp_path)
    old, new = "2026-01-01 10:00:00.000000", "2999-01-01 10:00:00.000000"
    with sqlite3.connect(path) as conn:
        conn.executemany(
            "INSERT INTO events (id, conversation_id, run_id, type, payload, created_at) "
            "VALUES (?, 'c', 'r', ?, '{}', ?)", [
                (1, "tool_call.created", old), (2, "injection.warned", old),
                (3, "tool_call.updated", new), (4, "message.created", old)])
    tidy_db(path)
    with sqlite3.connect(path) as conn:
        left = [row[0] for row in conn.execute("SELECT id FROM events ORDER BY id")]
    assert left == [2, 3, 4]  # the old call gone; the newest stays, old as it is
