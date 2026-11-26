"""0.1.8: a CLI's Orchestrator working with its own tools (Claude Code, Codex) is given notify over
KOLONİ's bridge, held to the same rules as an API model's: only where the project has somewhere to
send it, at its limit."""

import app.web
from tests.test_claude_native import claude_app  # noqa: F401  (a fixture)
from tests.test_native_agent import native_app  # noqa: F401  (a fixture)

ORIGIN = {"Origin": "http://127.0.0.1:8790"}


def place(client, project_dir, provider, project=None):
    """A Full auto chat on the CLI in a project with `project`'s settings."""
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    if project:
        patched = client.patch(f"/api/projects/{pid}", json=project, headers=ORIGIN)
        assert patched.status_code == 200, patched.text
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(
        f"/api/conversations/{cid}",
        json={
            "permission_mode": "full_auto",
            "provider_id": provider["id"],
            "lead_hands_code": False,
        },
        headers=ORIGIN,
    )
    return pid, cid


def start(client, project_dir, provider, project=None):
    """A Full auto turn of the CLI's Orchestrator in a project with `project`'s settings."""
    pid, cid = place(client, project_dir, provider, project)
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()["run"]
    return pid, cid, run["id"]


def koloni_calls(snap, name):
    return [(t["status"], t["result"] or "") for t in snap["tool_calls"] if t["name"] == name]


def test_codex_notifies_the_desktop(
    native_app,  # noqa: F811
    wait_run,
    project_dir,
    monkeypatch,
):
    shown = []
    monkeypatch.setattr(app.web, "has_desktop", lambda: True)
    monkeypatch.setattr(app.web, "desktop", lambda title, said: shown.append(said))
    client, provider, _ = native_app(
        [
            *[{"koloni": "notify", "args": {"message": f"step {n}"}} for n in range(7)],
            {"say": "Done."},
        ]
    )
    # (6 an hour here, not a minute: a slow runner's seven calls stay in one window)
    client.app.state.runner._toasts = app.web.Rate(6, 3600.0)
    _pid, cid, run_id = start(client, project_dir, provider, {"notify_desktop": True})
    snap = wait_run(client, cid, run_id, 60.0)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    seen = native_app.record()
    assert "notify" in seen["tools"]
    # As an API model's notify: at most 6 a minute on the desktop - the seventh is refused.
    notified = koloni_calls(snap, "notify")
    assert [status for status, _ in notified] == ["succeeded"] * 6 + ["failed"]
    assert "at most 6 desktop notifications a minute" in notified[-1][1]
    assert shown == [f"step {n}" for n in range(6)]


def test_claude_code_is_not_given_notify_where_the_project_sends_none(
    claude_app,  # noqa: F811
    wait_run,
    project_dir,
):
    client, provider, _ = claude_app(
        [
            {"koloni": "notify", "args": {"message": "hello"}},
            {"say": "Done."},
        ]
    )
    _pid, cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    argv = claude_app.record()["argv"]
    allowed = set(argv[argv.index("--allowedTools") + 1].split(","))
    assert "mcp__koloni__notify" not in allowed  # (no address, no desktop: as `_lead_tools`)
    # Its calls of the ones not offered never reached KOLONİ: no card.
    assert koloni_calls(snap, "notify") == []
