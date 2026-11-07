"""All of the user's KOLONİ in one .zip (K-disa-aktar), and that .zip put back.

Export: the database as SQLite's own online backup makes it (a consistent copy, never the
live file), the stores of the runtime folder KOLONİ keeps for the user, and a manifest.
What it holds of the user's secrets is left out unless asked for - in the copy only.
Restore: a .zip is checked and staged in the runtime folder; it replaces the live data at
the next start, before anything opens the database (`apply_staged`), the live data moved
to a dated folder first. Never while turns run; never by an agent (no tool does either).

Not in it: the projects (the user's own folders - their `.koloni/` knowledge too), working
copies, the CLIs' homes, logs, previews, and the database's own migration backups."""

import json
import logging
import os
import shutil
import sqlite3
import stat
import tempfile
import time
import tomllib
import zipfile
from collections.abc import Callable
from contextlib import closing, suppress
from datetime import UTC, datetime
from pathlib import Path

from alembic.script import ScriptDirectory
from alembic.util import CommandError

from app import copies
from app.api.providers import SESSION_KEY
from app.api.voice import KEY as VOICE_KEY
from app.backlog import HOLD
from app.config import REPO_ROOT
from app.db.models import now
from app.mcp_client import command_shown, keys_in
from app.skill_github import safe_path

log = logging.getLogger(__name__)

MANIFEST = "manifest.json"
DB = "data/koloni.db"
# What of the runtime folder is the user's: folders, then single files.
FOLDERS = ("skills", "attachments")
FILES = ("models_dev.json", "local-server.json")
# Where a restore waits for the next start, is while it is applied (`-<time>`), and where
# the data it replaced is kept (`before-restore/<time>`).
STAGED, PART, APPLYING = "restore", "restore.part", "restore.applying"
# shortcut: never pruned; prune as `session.BACKUPS_KEPT` does if they ever pile up.
KEPT = "before-restore"
# What a restore moves aside and puts back: the whole `data/` (its -wal holds rows too).
LIVE = ("data", *FOLDERS, *FILES)
# shortcut: fixed caps (a 4 GB upload, 16 GB unpacked, 200k files); raise them if a real
# user's data is ever larger.
MAX_UPLOAD = 4 * 2**30
MAX_UNPACKED = 16 * 2**30
MAX_MEMBERS = 200_000
# Flags that hold a key: Gemini's voice key and Claude Code's status line key.
SECRET_FLAGS = (VOICE_KEY, SESSION_KEY)


class Refused(Exception):
    pass


HELD_COPIES = ("a working copy holds changes that never reached the project: take them in "
               "or discard them first")


def version() -> str:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text("utf-8"))["project"]["version"]


def _revision(db: Path) -> str | None:
    with closing(sqlite3.connect(db)) as conn:
        try:
            row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        except sqlite3.DatabaseError:
            return None
    return row[0] if row else None


def _without_secrets(db: Path) -> list[str]:
    """Every secret the copy holds blanked (`main.known_secrets` names them all), and
    overwritten on disk too; what needs its key again, in words."""
    need: list[str] = []
    with closing(sqlite3.connect(db)) as conn:
        # Blanked bytes are zeroed, not left in a free page for whoever opens the file.
        conn.execute("PRAGMA secure_delete=ON")
        need += [f"provider {name}" for (name,) in conn.execute(
            "SELECT name FROM providers WHERE api_key IS NOT NULL AND api_key != ''")]
        need += [f"project {name}'s notification address" for (name,) in conn.execute(
            "SELECT name FROM projects WHERE notify_url IS NOT NULL AND notify_url != ''")]
        for server_id, name, command, env in conn.execute(
                "SELECT id, name, command, env FROM mcp_servers").fetchall():
            command, env = json.loads(command or "[]"), json.loads(env or "{}")
            if any(env.values()) or keys_in(command):
                need.append(f"MCP server {name}")
            # Its variables keep their names, so the user sees which to give again.
            conn.execute("UPDATE mcp_servers SET command = ?, env = ? WHERE id = ?", (
                json.dumps(command_shown(command)), json.dumps(dict.fromkeys(env, "")),
                server_id))
        for flag, what in zip(SECRET_FLAGS, (
                "Gemini voice", "Claude Code's status line (set it up again)"), strict=True):
            if conn.execute("SELECT 1 FROM flags WHERE name = ?", (flag,)).fetchone():
                need.append(what)
        conn.execute("UPDATE providers SET api_key = NULL")
        conn.execute("UPDATE projects SET notify_url = NULL")
        conn.execute(f"DELETE FROM flags WHERE name IN ({','.join('?' * len(SECRET_FLAGS))})",
                     SECRET_FLAGS)
        conn.commit()
        conn.execute("VACUUM")
    return need


def export(runtime_root: Path, db_path: Path, out: Path, secrets: bool) -> dict:
    """The .zip at `out`; its manifest back. The live database is only read."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        snapshot = Path(tmp) / "koloni.db"
        with closing(sqlite3.connect(db_path)) as live, closing(sqlite3.connect(snapshot)) as copy:
            live.backup(copy)
            copy.execute("PRAGMA journal_mode=DELETE")  # one file, with no -wal beside it
        need = [] if secrets else _without_secrets(snapshot)
        parts = [DB]
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot, DB)
            for name in FOLDERS:
                folder = runtime_root / name
                files = sorted(p for p in folder.rglob("*") if p.is_file() and not p.is_symlink()) \
                    if folder.is_dir() else []
                for path in files:
                    archive.write(path, f"{name}/{path.relative_to(folder).as_posix()}")
                parts += [name] if files else []
            for name in FILES:
                if not (runtime_root / name).is_file():
                    continue
                text = (runtime_root / name).read_text("utf-8")
                if name == "local-server.json" and not secrets:
                    text, masked = _server_without_key(text)
                    need += ["the local model server's key"] if masked else []
                archive.writestr(name, text)
                parts.append(name)
            manifest = {
                "koloni": version(), "revision": _revision(snapshot),
                "made_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "secrets": secrets, "need_keys": need, "parts": parts,
            }
            archive.writestr(MANIFEST, json.dumps(manifest, indent=2, ensure_ascii=False))
    return manifest


def _server_without_key(text: str) -> tuple[str, bool]:
    """local-server.json with a key in its arguments (`--api-key`) masked."""
    try:
        told = json.loads(text)
        command = [str(told["executable"]), *map(str, told["args"])]
    except (ValueError, KeyError, TypeError):
        return text, False
    shown = command_shown(command)
    if shown == command:
        return text, False
    return json.dumps({"executable": shown[0], "args": shown[1:]}), True


def _target(name: str) -> bool:
    """Whether a member's path is one a restore may write: inside a part, and a path a
    file of this machine may have (no `..`, drive, backslash or device name)."""
    if name in (MANIFEST, DB, *FILES):
        return True
    top, _, rest = name.partition("/")
    return top in FOLDERS and bool(rest) and safe_path(rest)


def stage(runtime_root: Path, upload: Path) -> dict:
    """Check the .zip at `upload` and stage it for the next start; its manifest back.
    Refused says why it cannot be: nothing is staged then."""
    part = runtime_root / PART
    shutil.rmtree(part, ignore_errors=True)
    try:
        manifest = _unpacked(upload, part)
        _check_db(part / DB, manifest)
        staged = runtime_root / STAGED
        shutil.rmtree(staged, ignore_errors=True)
        os.replace(part, staged)  # whole or not at all: a half-written stage never applies
    except BaseException:
        shutil.rmtree(part, ignore_errors=True)
        raise
    return manifest


def _check_db(db: Path, manifest: dict) -> None:
    """Refused where the database is not one this KOLONİ can take, or not the manifest's."""
    if not db.is_file():  # (connecting would make an empty one)
        raise Refused(f"it has no database ({DB})")
    revision = _revision(db)
    if revision is None:
        raise Refused("its database is not KOLONİ's")
    if revision != manifest.get("revision"):
        raise Refused("its database is not the one its manifest describes")
    try:
        ScriptDirectory(str(REPO_ROOT / "alembic")).get_revision(revision)
    except CommandError:
        raise Refused(f"it was made by a newer KOLONİ (database version {revision} is "
                      "not known to this one): update KOLONİ first") from None
    with closing(sqlite3.connect(db)) as conn:
        if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise Refused("its database is damaged")


def summary(manifest: dict) -> dict:
    """What the page is told of a staged export (`RestoreOut`)."""
    return {key: manifest.get(key) for key in ("made_at", "secrets", "need_keys")}


def staged_summary(runtime_root: Path) -> dict | None:
    """The export staged for the next start, as `summary` says it; None: none is."""
    try:
        return summary(json.loads((runtime_root / STAGED / MANIFEST).read_text("utf-8")))
    except (OSError, ValueError):
        return None


def last_failed(runtime_root: Path) -> Path | None:
    """The newest restore a start could not apply, kept where it is."""
    return max(runtime_root.glob("restore.failed-*"), default=None)


def _unpacked(upload: Path, into: Path) -> dict:  # noqa: C901
    try:
        with zipfile.ZipFile(upload) as archive:
            infos = [info for info in archive.infolist() if not info.is_dir()]
            if len(infos) > MAX_MEMBERS:
                raise Refused(f"it holds more than {MAX_MEMBERS} files")
            if sum(info.file_size for info in infos) > MAX_UNPACKED:
                raise Refused(f"it unpacks to more than {MAX_UNPACKED // 2**30} GB")
            names = {info.filename for info in infos}
            if MANIFEST not in names:
                raise Refused("it is not a KOLONİ export: it has no manifest.json")
            if DB not in names:
                raise Refused(f"it has no database ({DB})")
            for info in infos:
                if not _target(info.filename) or stat.S_ISLNK(info.external_attr >> 16):
                    raise Refused(f"{info.filename!r} is not a file a KOLONİ export holds")
            for info in infos:
                path = into / info.filename
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as member, path.open("wb") as out:
                    got = 0
                    while chunk := member.read(2**20):
                        got += len(chunk)
                        if got > info.file_size:
                            break
                        out.write(chunk)
                if got != info.file_size:  # (a zip bomb says less than it holds)
                    raise Refused(f"{info.filename!r} is not the size it says")
    except zipfile.BadZipFile as exc:
        raise Refused(f"the .zip could not be read: {exc}") from None
    try:
        manifest = json.loads((into / MANIFEST).read_text("utf-8"))
    except ValueError:
        raise Refused("its manifest.json could not be read") from None
    if not (isinstance(manifest, dict) and isinstance(manifest.get("made_at"), str | None)
            and isinstance(manifest.get("secrets"), bool)
            and isinstance(manifest.get("need_keys"), list)
            and all(isinstance(one, str) for one in manifest["need_keys"])):
        raise Refused("its manifest.json is not one KOLONİ writes")
    return manifest


def apply_staged(runtime_root: Path, upgrade: Callable[[], None]) -> bool:
    """At the start, before anything opens the database: a staged restore replaces the
    live data, which is moved to `before-restore/<time>/` first; then `upgrade` brings the
    database to this KOLONİ's schema, and everything is held (Stop everything) until the
    user says Resume. Where any of it fails the old data is put back, the restore is kept
    as `restore.failed-<time>` and the log says why. True when restored. A restore a crash
    cut off midway stops the start (RuntimeError): nothing opens a database half put back.
    shortcut: that one is put right by hand, as the error says; automate it if it is seen."""
    cut = sorted(runtime_root.glob(f"{APPLYING}-*"))
    if cut:
        raise RuntimeError(_cut_off(runtime_root, cut[-1]))
    staged = runtime_root / STAGED
    if not (staged / MANIFEST).is_file():
        return False
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")  # (two starts in a second differ)
    kept = runtime_root / KEPT / stamp
    applying = runtime_root / f"{APPLYING}-{stamp}"
    # Taken first: a stage outlives no start, or a later start would undo what came since.
    _move(staged, applying)
    moved: list[str] = []  # the live parts moved aside
    placed: list[str] = []  # the staged parts moved in
    try:
        if held_copies(runtime_root):
            raise Refused(HELD_COPIES)
        _check_db(applying / DB, json.loads((applying / MANIFEST).read_text("utf-8")))
        kept.mkdir(parents=True)
        for name in LIVE:
            if (runtime_root / name).exists():
                _move(runtime_root / name, kept / name)
                moved.append(name)
        for name in LIVE:
            if (applying / name).exists():
                _move(applying / name, runtime_root / name)
                placed.append(name)
        upgrade()
        _settle(runtime_root)
    except Exception:
        log.exception("the staged restore could not be applied: the data before it is back")
        for name in placed:  # (back where they came from: the failed restore stays whole)
            _move(runtime_root / name, applying / name)
        for name in moved:
            _move(kept / name, runtime_root / name)
        with suppress(OSError):
            kept.rmdir()
        _move(applying, runtime_root / f"restore.failed-{stamp}")
        return False
    done = runtime_root / f"restore.applied-{stamp}"
    _move(applying, done)  # (not "applying" any more, even where it cannot all be deleted)
    shutil.rmtree(done, ignore_errors=True)
    log.warning("restored from the staged export; the data before it is in %s", kept)
    return True


def _settle(runtime_root: Path) -> None:
    """The restored database made this machine's: each skill's folder is the store's here,
    whatever folder the file named; and everything is held until the user says Resume, so
    the restored triggers, backlogs and nights do not start by themselves."""
    with closing(sqlite3.connect(runtime_root / DB)) as conn:
        for skill_id, folder in conn.execute("SELECT id, folder FROM skills").fetchall():
            name = folder.replace("\\", "/").rstrip("/").rpartition("/")[2]
            here = runtime_root / "skills" / (name if safe_path(name) else skill_id)
            conn.execute("UPDATE skills SET folder = ? WHERE id = ?", (str(here), skill_id))
        conn.execute("INSERT OR REPLACE INTO flags (name, value) VALUES (?, ?)",
                     (HOLD, now().isoformat()))
        conn.commit()


def _cut_off(runtime_root: Path, applying: Path) -> str:
    """What to do where a crash cut a restore off: said by the error that stops the start."""
    kept = runtime_root / KEPT / applying.name.rpartition("-")[2]
    if not kept.is_dir():
        return (f"a restore was cut off at an earlier start before it moved anything: delete "
                f"{applying} and start KOLONİ again")
    return (f"a restore was cut off midway at an earlier start: the data before it is in "
            f"{kept}. Move what is in it back into {runtime_root} (replacing what is there), "
            f"delete {applying}, and start KOLONİ again")


def _move(source: Path, target: Path) -> None:
    """os.replace, tried again for a moment where Windows says a file is in use (a virus
    scanner or the search indexer holding it open)."""
    for attempt in range(5):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.2)


def held_copies(runtime_root: Path) -> bool:
    """Whether a working copy is there: one that outlived its turn holds what never reached
    the project, and a restored database would not know it - the start would delete it."""
    return any(held.is_dir() and any(held.iterdir()) for held in copies.folders(runtime_root))
