"""0.1.8: Qoder is no longer run (the user, 24 Nov: "qoder sil"). A Qoder provider from before
stays - switched off by migration 0177, its settings kept - and cannot be switched on again; a
chat on it fails as on any provider switched off, with why; the user deletes it."""

import sqlite3

import pytest
from alembic import command

from app.config import load_settings
from app.db.models import Provider
from app.main import create_app
from app.providers import RETIRED, SwitchedOff, allowed, is_on
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_chat_flow import text
from tests.test_migration_0002 import _config

OWN = {"Origin": "http://127.0.0.1:8790"}
WHY = RETIRED["qoder_cli"]


def test_migration_0177_switches_qoder_off_and_nothing_else(tmp_path):
    db = tmp_path / "q.db"
    cfg = _config(db)
    command.upgrade(cfg, "0176")
    with sqlite3.connect(db) as conn:
        for at, (pid, kind) in enumerate([("q", "qoder_cli"), ("c", "claude_cli")]):
            conn.execute(
                "INSERT INTO providers (id, name, kind, position, enabled, models, created_at, "
                "updated_at) VALUES (?, ?, ?, ?, 1, '[{\"name\": \"m\"}]', '2026-11-24', "
                "'2026-11-24')",
                (pid, pid, kind, at),
            )
    command.upgrade(cfg, "0177")
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT id, enabled, models FROM providers ORDER BY id").fetchall()
    assert rows == [("c", 1, '[{"name": "m"}]'), ("q", 0, '[{"name": "m"}]')]  # (kept whole)
    command.downgrade(cfg, "0176")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT enabled FROM providers WHERE id = 'q'").fetchone() == (0,)


def test_a_qoder_row_is_never_on_whatever_its_switch_says():
    # (A row put back on by hand, or from a copy no migration saw.)
    qoder = Provider(name="Qoder", kind="qoder_cli", enabled=True)
    assert not is_on(qoder, "Qwen3.8-Flash")
    with pytest.raises(SwitchedOff, match="^Qoder: Qoder is no longer supported") as refused:
        allowed(qoder, "Qwen3.8-Flash")
    assert refused.value.to_agent == "Qoder can no longer be used: choose another model."


def test_a_qoder_provider_from_before_is_shown_off_fails_a_chat_and_can_be_deleted(
    settings_env, tmp_path, project_dir, wait_run
):
    settings = load_settings(settings_env)
    settings.db_path.parent.mkdir(parents=True)
    cfg = _config(settings.db_path)
    command.upgrade(cfg, "0176")
    with sqlite3.connect(settings.db_path) as conn:
        for at, (pid, name, kind) in enumerate(
            [("local", "Local", "openai_compat"), ("q", "Qoder", "qoder_cli")]
        ):
            conn.execute(
                "INSERT INTO providers (id, name, kind, base_url, mode, position, enabled, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 1, '2026-11-24', '2026-11-24')",
                (
                    pid,
                    name,
                    kind,
                    "http://127.0.0.1:9/v1" if pid == "local" else None,
                    None if pid == "local" else "session",
                    at,
                ),
            )
    model = ScriptedModel([text("on Local")])
    with TestClient(create_app(settings, model=model), base_url="http://127.0.0.1:8790") as client:
        shown = {p["name"]: p for p in client.get("/api/providers").json()}
        assert (shown["Qoder"]["kind"], shown["Qoder"]["enabled"]) == ("qoder_cli", False)
        assert (shown["Qoder"]["off_why"], shown["Local"]["off_why"]) == (WHY, None)
        assert shown["Local"]["enabled"] is True
        refused = client.patch("/api/providers/q", headers=OWN, json={"enabled": True})
        assert (refused.status_code, refused.json()["detail"]) == (422, WHY)
        # Nobody is refused anything else of the page: its models list, its availability.
        assert client.get("/api/providers/q/models").status_code == 200
        assert client.get("/api/providers/q/availability?free=true").status_code == 200
        assert client.get("/api/roles/models").status_code == 200

        pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
        cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
        client.patch(f"/api/conversations/{cid}", json={"provider_id": "q", "model_id": None})
        run = client.post(f"/api/conversations/{cid}/messages", json={"content": "hi"}).json()
        ended = wait_run(client, cid, run["run"]["id"])["runs"][-1]
        assert (ended["status"], ended["error"]) == ("failed", f"Lead: Qoder: {WHY}")
        assert model.calls == []  # no model was asked

        assert client.delete("/api/providers/q", headers=OWN).status_code == 204
        # The chat goes on on what is left, as after any provider is deleted.
        run = client.post(f"/api/conversations/{cid}/messages", json={"content": "hi"}).json()
        assert wait_run(client, cid, run["run"]["id"])["runs"][-1]["status"] == "completed"
        assert len(model.calls) == 1
