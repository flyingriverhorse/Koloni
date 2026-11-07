"""Slice 81a-2: a model saved before 81a says whether agents may use it - what its provider
said - so no screen reads it as on while its provider keeps agents off it."""

import importlib.util
import json
import sqlite3
from pathlib import Path

from alembic import command

from app.config import load_settings
from app.main import create_app
from tests.keyed import TestClient
from tests.test_migration_0002 import _config

OWN = {"Origin": "http://127.0.0.1:8790"}
# Read off the migration itself: it is renumbered when the slices are merged.
MIGRATION = next(Path(__file__).parents[1].glob("alembic/versions/*_model_agents.py"))
_spec = importlib.util.spec_from_file_location("model_agents_migration", MIGRATION)
assert _spec and _spec.loader
_migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_migration)

OLD_ROWS = [{"name": "glm-5.3", "note": None, "tier": "strongest"},
            {"name": "qwen3-max", "note": None, "tier": "balanced"}]


def _old_provider(db: Path, pid: str, for_agents: bool, rows: list[dict]) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO providers (id, name, kind, base_url, for_agents, models, only_listed, "
            "position, created_at, updated_at) VALUES (?, ?, 'openai_compat', "
            "'https://dashscope-intl.aliyuncs.com/compatible-mode/v1', ?, ?, 0, 5, "
            "'2026-10-20', '2026-10-20')", (pid, pid, for_agents, json.dumps(rows)))


def test_a_row_from_before_81a_takes_its_providers_word_and_nothing_contradicts(settings_env):
    settings = load_settings(settings_env)
    db = settings.db_path
    db.parent.mkdir(parents=True)
    cfg = _config(db)
    command.upgrade(cfg, _migration.down_revision)
    _old_provider(db, "off", False, OLD_ROWS)
    _old_provider(db, "on", True, OLD_ROWS)
    # One already saved by 81a keeps what it said.
    _old_provider(db, "said", True, [{**OLD_ROWS[0], "agents": False}, OLD_ROWS[1]])
    command.upgrade(cfg, _migration.revision)

    with TestClient(create_app(settings), base_url="http://127.0.0.1:8790") as client:
        providers = {p["id"]: p for p in client.get("/api/providers").json()}
        assert [m["agents"] for m in providers["off"]["models"]] == [False, False]
        assert [m["agents"] for m in providers["on"]["models"]] == [True, True]
        assert [m["agents"] for m in providers["said"]["models"]] == [False, True]
        # The slots say the same of each.
        slots = client.get("/api/tiers").json()
        assert {(one["provider_id"], one["agents"]) for one in slots["strongest"]} == {
            ("off", False), ("on", True), ("said", False)}

        # One switched on: the provider follows, and the other stays off.
        rows = [{**m, "agents": m["name"] == "glm-5.3"} for m in providers["off"]["models"]]
        now = client.patch("/api/providers/off", headers=OWN, json={"models": rows}).json()
        assert now["for_agents"] is True
        assert [m["agents"] for m in now["models"]] == [True, False]
        assert ("off", True) in {(one["provider_id"], one["agents"])
                                 for one in client.get("/api/tiers").json()["strongest"]}


def test_a_row_saved_without_saying_it_says_what_its_provider_does(client):
    made = client.post("/api/providers", headers=OWN, json={
        "name": "Plan", "kind": "openai_compat", "base_url": "https://api.example.invalid/v1",
        "models": [{"name": "glm-5.3", "tier": "strongest"}]}).json()
    assert (made["for_agents"], made["models"][0]["agents"]) == (False, False)
    made = client.post("/api/providers", headers=OWN, json={
        "name": "Open", "kind": "openai_compat", "base_url": "https://api.example.invalid/v1",
        "for_agents": True, "models": [{"name": "glm-5.3"}]}).json()
    assert made["models"][0]["agents"] is True
