import logging
import sqlite3
from contextlib import closing, suppress
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import REPO_ROOT

log = logging.getLogger(__name__)


def make_engine(db_path: Path) -> Engine:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}", connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


BACKUPS_KEPT = 5
DAILY_KEPT = 3
STAMP = "%Y%m%dT%H%M%S"


def upgrade_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    if db_path.exists():
        _back_up(db_path, ScriptDirectory.from_config(cfg).get_current_head())
    command.upgrade(cfg, "head")


def _back_up(db_path: Path, head: str | None) -> None:
    """A copy of a database about to be moved to a newer schema, beside it in `backups/`, so a
    migration that goes wrong loses nothing; the last BACKUPS_KEPT are kept. It holds what the
    database holds - API keys too - and stays on this machine like the database itself."""
    with closing(sqlite3.connect(db_path)) as conn:
        try:
            (at,) = conn.execute("SELECT version_num FROM alembic_version").fetchone() or (None,)
        except sqlite3.OperationalError:
            at = None  # no schema yet: nothing of the user's to keep
        if at is None or at == head:
            return
        backups = db_path.parent / "backups"
        backups.mkdir(exist_ok=True)
        _copy(conn, backups / f"{db_path.stem}-{at}-{datetime.now(UTC).strftime(STAMP)}.db")
    old = sorted(backups.glob(f"{db_path.stem}-*.db"), key=lambda p: p.stat().st_mtime)
    for gone in old[:-BACKUPS_KEPT]:
        gone.unlink()


def _copy(conn: sqlite3.Connection, to: Path) -> None:
    # SQLite's own online backup: a consistent copy, the WAL's pages included.
    with closing(sqlite3.connect(to)) as copy:
        conn.backup(copy)


def back_up_daily(db_path: Path, at: datetime | None = None) -> None:
    """The routine copy, at the start (`app.main.run`): where none was made this UTC date, a copy
    in `backups/`, and the last DAILY_KEPT kept. Named `daily-…`, with its time: the copies
    before a migration (`_back_up`) neither count these nor are deleted here, and a copy's age
    is its name's, not the file's. One named later than now (a clock that was ahead) is no copy
    of today, and the first to go. One that fails is logged, and what it left is no copy
    (`.part`, deleted): KOLONİ starts all the same.
    shortcut: on the start path (0.5 s for 200 MB on an SSD), and only there - a KOLONİ left
    running makes none; run it in a thread, on the clock too, if a database grows past a few GB
    or a start is rare.
    shortcut: the rename is tried once (`backup._move` tries again for a virus scanner, but
    this module imports nothing of the app's); a copy lost to one is made at the next start."""
    at = at or datetime.now(UTC)
    backups = db_path.parent / "backups"
    name = f"daily-{db_path.stem}-{{}}.db".format
    made = backups / name(at.strftime(STAMP))
    part = made.with_name(made.name + ".part")
    try:
        for cut_short in backups.glob(name("*") + ".part"):  # (of a start that was killed)
            cut_short.unlink()
        kept = sorted(backups.glob(name("[0-9]" * 8 + "T" + "[0-9]" * 6)))
        past = [one for one in kept if one.name <= made.name]
        if past and past[-1].name.rpartition("T")[0] == made.name.rpartition("T")[0]:
            return
        backups.mkdir(exist_ok=True)
        with closing(sqlite3.connect(db_path)) as conn:
            _copy(conn, part)
        part.replace(made)
        ahead = [one for one in kept if one.name > made.name]
        for gone in [*ahead, *past, made][:-DAILY_KEPT]:
            gone.unlink()
    except (sqlite3.Error, OSError) as exc:  # (no room, a file held: nothing to stop a start for)
        log.warning("database not copied: %s", exc)
        with suppress(OSError):
            part.unlink(missing_ok=True)


# A vector nothing can find any more (`app.meaning`): its project, its record or its model gone.
STALE_VECTORS = (
    "DELETE FROM embeddings WHERE project_id NOT IN (SELECT id FROM projects)",
    "DELETE FROM embeddings WHERE kind = 'memory' AND record_id NOT IN (SELECT id FROM memories)",
    "DELETE FROM embeddings WHERE kind = 'turn' AND NOT EXISTS (SELECT 1 FROM said_in_turns "
    "WHERE said_in_turns.rowid = CAST(embeddings.record_id AS INTEGER))",
    # (A linked project's records are kept under the model of the project that asked.)
    "DELETE FROM embeddings WHERE model NOT IN (SELECT embedding_model FROM projects)",
)
# An event is kept for a page that reconnects (`EventBus.replay`, after the snapshot it loaded):
# the page itself is drawn from the tables, never from old events. Kept all the same: injection
# warnings (`app.injection` lists them all) and the newest, whose id SQLite would hand out again.
EVENTS_KEPT_DAYS = 30
OLD_EVENTS = (
    f"DELETE FROM events WHERE created_at < datetime('now', '-{EVENTS_KEPT_DAYS} days') "
    "AND type != 'injection.warned' AND id < (SELECT MAX(id) FROM events)"
)
# VACUUM only when this much of the file is free pages: it rewrites the whole file.
VACUUM_FREE_BYTES = 64 * 1024 * 1024
VACUUM_FREE_SHARE = 0.25


def tidy_db(db_path: Path) -> None:
    """At the start, nothing running yet (0.1.0-hijyen): stale vectors and old events deleted,
    then the file compacted where much of it is free. Two pragmas when there is nothing to do."""
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            for statement in (*STALE_VECTORS, OLD_EVENTS):
                conn.execute(statement)
        (pages,), (free,), (size,) = (
            conn.execute(f"PRAGMA {name}").fetchone()
            for name in ("page_count", "freelist_count", "page_size")
        )
        if free * size <= VACUUM_FREE_BYTES or free <= pages * VACUUM_FREE_SHARE:
            return
        before = db_path.stat().st_size
        conn.execute("VACUUM")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # (else the WAL holds the new pages)
        log.info(
            "database compacted: %.0f MB -> %.0f MB", before / 2**20, db_path.stat().st_size / 2**20
        )
    except sqlite3.Error as exc:  # (busy, or no room for VACUUM's copy: KOLONİ starts all the same)
        log.warning("database not tidied: %s", exc)
    finally:
        conn.close()
