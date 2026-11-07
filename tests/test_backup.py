"""Export everything and restore from a file (K-disa-aktar): every database and folder here
is the test's own, under tmp_path."""

import io
import json
import sqlite3
import zipfile
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

import app.main
from app import backup, copies
from app.backlog import HOLD
from app.config import REPO_ROOT
from app.db.models import Conversation, Flag, McpServer, Project, Provider, Run, Skill
from app.db.session import make_engine, make_session_factory
from app.main import known_secrets
from tests.keyed import TestClient

OWN = {"Origin": "http://127.0.0.1:8790"}
KEY = "sk-test-0123456789abcdefghijklmnop"
HOOK = "https://hooks.example.test/T000/B000/xyzSECRETxyz"
MCP_KEY = "ghp_0123456789abcdefghijklmnopqrstuvwxyz"
VOICE = "AIzaVoiceKey0123456789abcdefghij"


def _fill(app_) -> None:
    """One of every secret KOLONİ keeps, a skill, an attachment and the local server's file."""
    with app_.state.session_factory() as session:
        session.add(Provider(name="Keyed", kind="openai_compat", base_url="http://x/v1", api_key=KEY))
        session.add(Project(name="Proj", root_path="C:/nowhere/proj", notify_url=HOOK))
        session.add(McpServer(name="gh", command=["gh-mcp", "--token", MCP_KEY],
                              env={"GITHUB_TOKEN": MCP_KEY}))
        session.add(Flag(name="gemini_key", value=VOICE))
        session.add(Flag(name="claude_session_key", value="c" * 64))
        session.commit()
    root = app_.state.settings.runtime_root
    (root / "skills" / "s1").mkdir(parents=True)
    (root / "skills" / "s1" / "SKILL.md").write_text("# a skill\n", "utf-8")
    (root / "attachments" / "c1").mkdir(parents=True)
    (root / "attachments" / "c1" / "a1").write_bytes(b"\x89PNG picture")
    (root / "local-server.json").write_text(json.dumps(
        {"executable": "C:/llama/llama-server.exe", "args": ["-m", "x.gguf", "--api-key", KEY]}))
    (root / "agy-home").mkdir()
    (root / "agy-home" / "auth.json").write_text("{}")
    (root / "cli-homes" / "p1").mkdir(parents=True)  # (a provider's own login, K-claude-hesap)
    (root / "cli-homes" / "p1" / ".credentials.json").write_text("{}")


def _export(client, secrets: bool = False) -> zipfile.ZipFile:
    answer = client.post(f"/api/backup/export?secrets={str(secrets).lower()}", headers=OWN)
    assert answer.status_code == 200, answer.text
    assert answer.headers["content-type"] == "application/zip"
    assert "attachment" in answer.headers["content-disposition"]
    return zipfile.ZipFile(io.BytesIO(answer.content))


def _snapshot(archive: zipfile.ZipFile, tmp_path: Path) -> Path:
    out = tmp_path / "out" / "koloni.db"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(archive.read(backup.DB))
    return out


def _secrets_in(db: Path, settings) -> list:
    engine = make_engine(db)
    try:
        return [one for one in known_secrets(make_session_factory(engine),
                                             replace(settings, model_api_key=None)) if one]
    finally:
        engine.dispose()


def test_export_holds_the_database_the_stores_and_a_manifest_and_no_secret(
        client, tmp_path, settings):
    _fill(client.app)
    archive = _export(client)
    names = set(archive.namelist())
    assert {backup.MANIFEST, backup.DB, "skills/s1/SKILL.md", "attachments/c1/a1",
            "local-server.json"} <= names
    assert not any(name.startswith(("agy-home", "cli-homes", "copies", "data/backups"))
                   for name in names)
    manifest = json.loads(archive.read(backup.MANIFEST))
    assert manifest["secrets"] is False
    assert manifest["revision"] and manifest["koloni"] and manifest["made_at"]
    assert set(manifest["parts"]) >= {backup.DB, "skills", "attachments", "local-server.json"}
    assert {"provider Keyed", "project Proj's notification address", "MCP server gh",
            "Gemini voice", "Claude Code's status line (set it up again)",
            "the local model server's key"} == set(manifest["need_keys"])
    db = _snapshot(archive, tmp_path)
    with closing(sqlite3.connect(db)) as conn:  # a consistent copy: its rows read
        assert conn.execute("SELECT name FROM providers WHERE name = 'Keyed'").fetchone()
        (env,) = conn.execute("SELECT env FROM mcp_servers").fetchone()
        assert json.loads(env) == {"GITHUB_TOKEN": ""}  # its name kept, to be given again
    # Every secret the house knows of is gone - and gone from the file's bytes, too.
    assert _secrets_in(db, settings) == []
    raw = db.read_bytes() + archive.read("local-server.json")
    for secret in (KEY, HOOK, MCP_KEY, VOICE):
        assert secret.encode() not in raw
    # ...from the copy only: the live database keeps them.
    assert KEY in _secrets_in(settings.db_path, settings)


def test_export_with_the_secrets_keeps_them(client, tmp_path, settings):
    _fill(client.app)
    archive = _export(client, secrets=True)
    manifest = json.loads(archive.read(backup.MANIFEST))
    assert manifest["secrets"] is True and manifest["need_keys"] == []
    assert {KEY, HOOK, MCP_KEY, VOICE} <= set(_secrets_in(_snapshot(archive, tmp_path), settings))
    assert KEY in archive.read("local-server.json").decode()


@pytest.mark.parametrize("origin", [{}, {"Origin": "null"}, {"Origin": "http://evil.test"}])
def test_export_and_restore_only_from_the_apps_own_page(client, origin):
    assert client.post("/api/backup/export", headers=origin).status_code == 403
    assert client.post("/api/backup/restore", content=b"x", headers=origin).status_code == 403
    assert client.delete("/api/backup/staged", headers=origin).status_code == 403
    with TestClient(client.app, base_url="http://127.0.0.1:8790",
                    headers={"X-KOLONI-Key": "wrong"}) as other:
        assert other.post("/api/backup/export", headers=OWN).status_code == 401


def _zip(members: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return out.getvalue()


def _db_at(path: Path, revision: str) -> bytes:
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        conn.commit()
    return path.read_bytes()


def _manifest(revision: str) -> bytes:
    return json.dumps({"revision": revision, "secrets": False, "need_keys": []}).encode()


@pytest.mark.parametrize("members, why", [
    ({"manifest.json": b"{}", "data/koloni.db": b"", "../x": b"out"}, "'../x'"),
    ({"manifest.json": b"{}", "data/koloni.db": b"", "skills/../../x": b"out"}, "skills/../../x"),
    ({"manifest.json": b"{}", "data/koloni.db": b"", "C:/x": b"out"}, "C:/x"),
    ({"manifest.json": b"{}", "data/koloni.db": b"", "agy-home/auth.json": b"{}"}, "agy-home"),
    # (inside a part, and a name no file of Windows may have: refused by the name itself)
    ({"manifest.json": b"{}", "data/koloni.db": b"", "skills/s1/CON.txt": b""}, "CON.txt"),
    ({"data/koloni.db": b""}, "no manifest.json"),
])
def test_a_zip_that_is_not_an_export_is_refused(client, members, why):
    answer = client.post("/api/backup/restore", content=_zip(members), headers=OWN)
    assert answer.status_code == 422 and why in answer.json()["detail"]
    root = client.app.state.settings.runtime_root
    assert not (root / backup.STAGED).exists() and not (root / backup.PART).exists()
    assert not (root.parent / "x").exists()


def test_a_manifest_koloni_never_wrote_is_refused_before_anything_is_staged(client, tmp_path):
    zipped = _zip({"manifest.json": json.dumps({"revision": "0093", "secrets": "yes"}).encode(),
                   "data/koloni.db": _db_at(tmp_path / "x.db", "0093")})
    answer = client.post("/api/backup/restore", content=zipped, headers=OWN)
    assert answer.status_code == 422 and "manifest.json" in answer.json()["detail"]
    assert not (client.app.state.settings.runtime_root / backup.STAGED).exists()


def test_a_newer_revision_is_refused(client, tmp_path):
    zipped = _zip({"manifest.json": _manifest("9999"),
                   "data/koloni.db": _db_at(tmp_path / "new.db", "9999")})
    answer = client.post("/api/backup/restore", content=zipped, headers=OWN)
    assert answer.status_code == 422 and "newer KOLONİ" in answer.json()["detail"]


def test_no_restore_while_a_turn_runs(client):
    with client.app.state.session_factory() as session:
        conversation = Conversation()
        session.add(conversation)
        session.flush()
        session.add(Run(conversation_id=conversation.id, status="running"))
        session.commit()
    answer = client.post("/api/backup/restore", content=_zip({}), headers=OWN)
    assert answer.status_code == 409


def _close(app_) -> None:
    """The app's database closed, as it is when KOLONİ has stopped."""
    app_.state.session_factory.kw["bind"].dispose()


def test_a_staged_restore_replaces_the_data_at_the_next_start_and_keeps_the_old(settings):
    root = settings.runtime_root
    first = app.main.create_app(settings)
    with TestClient(first, base_url="http://127.0.0.1:8790") as client:
        _fill(first)
        with first.state.session_factory() as session:
            session.add(Skill(name="s1", source="x", text="# a skill", files=[], size=0,
                              scripts=[], hashes={}, folder=r"D:\elsewhere\runtime\skills\s1"))
            session.commit()
        zipped = _export(client).fp.getvalue()
        # What changes after the export is what the restore undoes; it is kept aside.
        with first.state.session_factory() as session:
            session.add(Provider(name="Later", kind="openai_compat", base_url="http://y/v1"))
            session.commit()
        (root / "skills" / "later").mkdir()
        answer = client.post("/api/backup/restore", content=zipped, headers=OWN)
        assert answer.status_code == 200, answer.text
        told = answer.json()
        assert told["secrets"] is False and "provider Keyed" in told["need_keys"]
        assert (root / backup.STAGED / backup.MANIFEST).is_file()
    _close(first)

    # The next start (on this test's own folder).
    restarted = TestClient(app.main.create_app(settings), base_url="http://127.0.0.1:8790")
    with restarted:
        with restarted.app.state.session_factory() as session:
            names = {p.name for p in session.query(Provider)}
            keyed = session.query(Provider).filter_by(name="Keyed").one()
            skill = session.query(Skill).filter_by(name="s1").one()
            held = session.get(Flag, HOLD)
        assert "Keyed" in names and "Later" not in names
        assert keyed.api_key is None  # restored without its key: given again on the Models page
        # The skill's folder is this machine's store; and nothing starts by itself till Resume.
        assert Path(skill.folder) == root / "skills" / "s1"
        assert held is not None and restarted.get("/api/hold").json()["held"] is True
    _close(restarted.app)
    assert not (root / backup.STAGED).exists() and not list(root.glob("restore.*"))
    assert (root / "skills" / "s1" / "SKILL.md").is_file() and not (root / "skills" / "later").exists()
    (kept,) = (root / backup.KEPT).iterdir()
    assert (kept / "data" / "koloni.db").is_file() and (kept / "skills" / "later").is_dir()
    # Applied once: the start after it finds nothing staged.
    assert backup.apply_staged(root, lambda: None) is False


def test_an_older_revision_is_upgraded_to_head(tmp_path):
    old = tmp_path / "old.db"
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{old.as_posix()}")
    command.upgrade(cfg, "0090")
    root = tmp_path / "runtime"
    upload = tmp_path / "up.zip"
    upload.write_bytes(_zip({"manifest.json": _manifest("0090"), "data/koloni.db": old.read_bytes()}))
    backup.stage(root, upload)
    db = root / backup.DB
    assert backup.apply_staged(root, lambda: app.db.session.upgrade_db(db)) is True
    head = backup.ScriptDirectory(str(REPO_ROOT / "alembic")).get_current_head()
    assert backup._revision(db) == head


def test_a_restore_that_fails_at_the_start_puts_the_old_data_back(tmp_path, caplog):
    root = tmp_path / "runtime"
    (root / "data").mkdir(parents=True)
    (root / "data" / "koloni.db").write_bytes(b"the old data")
    (root / "skills" / "old").mkdir(parents=True)
    staged = root / backup.STAGED
    (staged / "data").mkdir(parents=True)
    _db_at(staged / "data" / "koloni.db", "0093")
    (staged / "skills" / "new").mkdir(parents=True)
    (staged / backup.MANIFEST).write_bytes(_manifest("0093"))

    def broken():
        raise RuntimeError("the migration broke")

    assert backup.apply_staged(root, broken) is False
    assert (root / "data" / "koloni.db").read_bytes() == b"the old data"
    assert (root / "skills" / "old").is_dir() and not (root / "skills" / "new").exists()
    # The failed restore is kept whole, where it is said to be.
    (failed,) = root.glob("restore.failed-*")
    assert not staged.exists() and (failed / "skills" / "new").is_dir()
    assert (failed / backup.DB).is_file() and (failed / backup.MANIFEST).is_file()
    assert not any((root / backup.KEPT).iterdir())
    assert "could not be applied" in caplog.text and "the migration broke" in caplog.text


def test_a_half_written_stage_is_not_applied(tmp_path):
    root = tmp_path / "runtime"
    (root / backup.PART / "data").mkdir(parents=True)
    assert backup.apply_staged(root, lambda: None) is False


def test_no_restore_while_a_working_copy_holds_what_never_reached_the_project(client, tmp_path):
    root = client.app.state.settings.runtime_root
    (copies.folders(root)[0] / "abc-1").mkdir(parents=True)
    answer = client.post("/api/backup/restore", content=_zip({}), headers=OWN)
    assert answer.status_code == 409 and "working copy" in answer.json()["detail"]
    # ...nor at the start, where one is there by then: the stage is not applied.
    (root / backup.STAGED / "data").mkdir(parents=True)
    (root / backup.STAGED / backup.MANIFEST).write_bytes(_manifest("0093"))
    assert backup.apply_staged(root, lambda: None) is False
    assert list(root.glob("restore.failed-*")) and (copies.folders(root)[0] / "abc-1").is_dir()


def test_a_migration_that_fails_on_the_restored_database_puts_the_old_data_back(tmp_path):
    root = tmp_path / "runtime"
    (root / "data").mkdir(parents=True)
    (root / "data" / "koloni.db").write_bytes(b"the old data")
    staged = root / backup.STAGED
    (staged / "data").mkdir(parents=True)
    _db_at(staged / "data" / "koloni.db", "0090")  # says 0090, and has none of its tables
    (staged / backup.MANIFEST).write_bytes(_manifest("0090"))
    db = root / backup.DB
    assert backup.apply_staged(root, lambda: app.db.session.upgrade_db(db)) is False
    assert db.read_bytes() == b"the old data" and list(root.glob("restore.failed-*"))


@pytest.mark.parametrize("database", [None, "9999"])
def test_a_stage_whose_database_is_missing_or_newer_is_not_applied(tmp_path, database):
    root = tmp_path / "runtime"
    (root / "data").mkdir(parents=True)
    (root / "data" / "koloni.db").write_bytes(b"the old data")
    staged = root / backup.STAGED
    (staged / "data").mkdir(parents=True)
    if database:
        _db_at(staged / backup.DB, database)
    (staged / backup.MANIFEST).write_bytes(_manifest(database or "0093"))
    assert backup.apply_staged(root, lambda: None) is False
    assert (root / backup.DB).read_bytes() == b"the old data" and list(root.glob("restore.failed-*"))


def test_a_restore_a_crash_cut_off_stops_the_start_and_says_where_the_data_is(tmp_path):
    root = tmp_path / "runtime"
    (root / "restore.applying-20261028T100000000000").mkdir(parents=True)
    with pytest.raises(RuntimeError, match="before it moved anything"):
        backup.apply_staged(root, lambda: None)
    kept = root / backup.KEPT / "20261028T100000000000"
    kept.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="the data before it is in") as said:
        backup.apply_staged(root, lambda: None)
    assert str(kept) in str(said.value)
    assert (root / "restore.applying-20261028T100000000000").is_dir()  # nothing deleted


def test_the_staged_restore_is_shown_and_can_be_cancelled(client, tmp_path):
    root = client.app.state.settings.runtime_root
    assert client.get("/api/backup/staged").json() == {"staged": None, "failed": None}
    zipped = _zip({"manifest.json": json.dumps({
        "revision": "0093", "secrets": False, "need_keys": ["provider P"],
        "made_at": "2026-10-28T10:00:00+00:00"}).encode(),
        "data/koloni.db": _db_at(tmp_path / "x.db", "0093")})
    assert client.post("/api/backup/restore", content=zipped, headers=OWN).status_code == 200
    assert client.get("/api/backup/staged").json()["staged"] == {
        "made_at": "2026-10-28T10:00:00+00:00", "secrets": False, "need_keys": ["provider P"]}
    assert client.delete("/api/backup/staged", headers=OWN).status_code == 204
    assert client.get("/api/backup/staged").json()["staged"] is None
    assert not (root / backup.STAGED).exists()
    (root / "restore.failed-20261028T100000000000").mkdir()
    assert client.get("/api/backup/staged").json()["failed"] == str(
        root / "restore.failed-20261028T100000000000")
