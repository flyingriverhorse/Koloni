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
from tests.test_spawn import role_id, spawn

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


# A Qoder provider as a 0.1.7 install has it: a model in the fast tier, open to agents, a default.
QODER_ROWS = '[{"name": "Qwen3.8-Flash", "tier": "fast", "agents": true, "order": 0}]'


@pytest.mark.no_po  # (the model's calls are counted)
def test_a_qoder_provider_from_before_is_shown_off_fails_a_chat_and_can_be_deleted(
    settings_env, tmp_path, project_dir, wait_run
):
    settings = load_settings(settings_env)
    settings.db_path.parent.mkdir(parents=True)
    cfg = _config(settings.db_path)
    command.upgrade(cfg, "0176")
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute(
            "INSERT INTO providers (id, name, kind, base_url, position, enabled, created_at, "
            "updated_at) VALUES ('local', 'Local', 'openai_compat', 'http://127.0.0.1:9/v1', 0, 1, "
            "'2026-11-24', '2026-11-24')"
        )
        conn.execute(
            "INSERT INTO providers (id, name, kind, mode, position, enabled, for_agents, "
            "default_model, models, created_at, updated_at) VALUES ('q', 'Qoder', 'qoder_cli', "
            "'session', 1, 1, 1, 'Qwen3.8-Flash', ?, '2026-11-24', '2026-11-24')",
            (QODER_ROWS,),
        )
    model = ScriptedModel([spawn("Coder", "check hello.py"), text("carried on"), text("on Local")])
    with TestClient(create_app(settings, model=model), base_url="http://127.0.0.1:8790") as client:
        shown = {p["name"]: p for p in client.get("/api/providers").json()}
        assert (shown["Qoder"]["kind"], shown["Qoder"]["enabled"]) == ("qoder_cli", False)
        assert (shown["Qoder"]["off_why"], shown["Local"]["off_why"]) == (WHY, None)
        assert shown["Local"]["enabled"] is True
        assert shown["Qoder"]["models"][0]["tier"] == "fast"  # (its settings kept)
        refused = client.patch("/api/providers/q", headers=OWN, json={"enabled": True})
        assert (refused.status_code, refused.json()["detail"]) == (422, WHY)
        # A role still on it, as the user had set it: kept, never run.
        coder = f"/api/roles/{role_id(client, 'Coder')}"
        assert client.patch(coder, json={"provider_id": "q"}).status_code == 200
        # What the Models and Agents pages read of it answers, none with a 500.
        for path in (
            "/api/providers/q/models",
            "/api/providers/q/availability?free=true",
            "/api/providers/q/availability",
            "/api/providers/q/limits",
            "/api/providers/q/model-facts?model=Qwen3.8-Flash",
            "/api/tiers",
            "/api/roles/models",
        ):
            assert client.get(path).status_code == 200, path
        for path in ("/api/providers/fill-all", "/api/providers/q/test"):
            assert client.post(path, headers=OWN).status_code == 200, path
        tried = client.post("/api/providers/q/test?run=true", headers=OWN).json()
        assert tried["ok"] is False and WHY in tried["error"]

        pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
        cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
        # On Local, its Lead opens a Coder - whose role is on Qoder: refused, the turn goes on.
        run = client.post(f"/api/conversations/{cid}/messages", json={"content": "hi"}).json()
        snap = wait_run(client, cid, run["run"]["id"])
        assert snap["runs"][-1]["status"] == "completed", snap["runs"][-1]["error"]
        assert [a["provider_name"] for a in snap["agents"]] == ["Local"]  # (no Coder opened)

        client.patch(f"/api/conversations/{cid}", json={"provider_id": "q", "model_id": None})
        run = client.post(f"/api/conversations/{cid}/messages", json={"content": "hi"}).json()
        ended = wait_run(client, cid, run["run"]["id"])["runs"][-1]
        assert (ended["status"], ended["error"]) == ("failed", f"Lead: Qoder: {WHY}")
        assert len(model.calls) == 2  # (none on Qoder)

        assert client.delete("/api/providers/q", headers=OWN).status_code == 204
        # The chat goes on on what is left, as after any provider is deleted.
        run = client.post(f"/api/conversations/{cid}/messages", json={"content": "hi"}).json()
        assert wait_run(client, cid, run["run"]["id"])["runs"][-1]["status"] == "completed"
        assert len(model.calls) == 3
