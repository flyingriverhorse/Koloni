"""Slice 60a's acceptance set, the backend's part: a plan's limits outlive a restart. Written before
the code. (The Usage page's new layout - summary boxes, limits and budget on top, tables folded - is
the frontend's: vitest and Playwright, written with the code.)

Today Claude Code's limits are known only from its runs and kept in memory: after a restart the
Usage page says "none since KOLONİ started" while its table shows this week's runs. The last
reading of each account (and Codex's, read with "Check now") is kept in the database, with when it
was read, and shown as it was after a restart.

Contract: `app.db.models.LimitReading` keeps each account's last reading; `GET
/api/providers/{id}/limits` after a restart answers what was last read, `read_at` included.
"""

import time

import pytest

from app.db import models
from tests.keyed import TestClient

if not hasattr(models, "LimitReading"):
    pytest.skip("slice 60a is not built yet", allow_module_level=True)  # written before the code

from app.config import load_settings  # noqa: E402
from app.limits import NOT_RUN, account  # noqa: E402
from app.main import create_app  # noqa: E402

ORIGIN = {"Origin": "http://127.0.0.1:8790"}
RESETS = int(time.time()) + 3600
SAID = {"status": "allowed", "rateLimitType": "five_hour", "utilization": 0.42, "resetsAt": RESETS,
        "unifiedWindows": {"five_hour": {"utilization": 0.42, "resetsAt": RESETS}}}


def started(settings_env):
    client = TestClient(create_app(load_settings(settings_env)), base_url="http://127.0.0.1:8790")
    client.__enter__()
    return client


def test_claude_codes_last_reading_is_there_after_a_restart(settings_env):
    first = started(settings_env)
    try:
        made = first.post("/api/providers", json={"name": "Claude", "kind": "claude_cli"},
                          headers=ORIGIN)
        assert made.status_code == 201, made.text
        provider = first.app.state.providers
        with first.app.state.session_factory() as session:
            row = session.get(models.Provider, made.json()["id"])
            provider.limits.said(account(row), SAID)  # what its run said
        seen = first.get(f"/api/providers/{made.json()['id']}/limits").json()
        assert seen["windows"][0]["used_percent"] == 42
    finally:
        first.__exit__(None, None, None)

    again = started(settings_env)  # the app restarted
    try:
        kept = again.get(f"/api/providers/{made.json()['id']}/limits").json()
        assert kept.get("unknown") != NOT_RUN
        assert kept["windows"][0]["used_percent"] == 42 and kept["read_at"]
    finally:
        again.__exit__(None, None, None)
