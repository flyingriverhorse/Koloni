"""0.1.8: a CLI's Orchestrator working with its own tools (Claude Code, Codex) is given notify and
propose_trigger over KOLONİ's bridge, held to the same rules as an API model's: notify only where
the project has somewhere to send it, at its limit; propose_trigger only a card."""

import app.web
from tests.test_claude_native import claude_app  # noqa: F401  (a fixture)
from tests.test_native_agent import native_app  # noqa: F401  (a fixture)

ORIGIN = {"Origin": "http://127.0.0.1:8790"}
TRIGGER = {
    "name": "Dependencies",
    "kind": "schedule",
    "config": {"at": "17:00", "days": ["fri"]},
    "message": "Look over the dependencies. Change nothing.",
}


def start(client, project_dir, provider, project=None):
    """A Full auto turn of the CLI's Orchestrator in a project with `project`'s settings."""
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
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()["run"]
    return pid, cid, run["id"]


def koloni_calls(snap, name):
    return [(t["status"], t["result"] or "") for t in snap["tool_calls"] if t["name"] == name]


def test_codex_notifies_the_desktop_and_proposes_a_trigger_on_a_card(
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
            {"koloni": "propose_trigger", "args": TRIGGER},
            {"say": "Done."},
        ]
    )
    # (6 an hour here, not a minute: a slow runner's seven calls stay in one window)
    client.app.state.runner._toasts = app.web.Rate(6, 3600.0)
    pid, cid, run_id = start(client, project_dir, provider, {"notify_desktop": True})
    snap = wait_run(client, cid, run_id, 60.0)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert {"notify", "propose_trigger"} <= set(native_app.record()["tools"])
    # As an API model's notify: at most 6 a minute on the desktop - the seventh is refused.
    notified = koloni_calls(snap, "notify")
    assert [status for status, _ in notified] == ["succeeded"] * 6 + ["failed"]
    assert "at most 6 desktop notifications a minute" in notified[-1][1]
    assert shown == [f"step {n}" for n in range(6)]
    # A card in the chat, nothing made until the user approves it.
    ((status, said),) = koloni_calls(snap, "propose_trigger")
    assert status == "succeeded" and "Fridays at 17:00" in said, said
    (card,) = snap["trigger_proposals"]
    assert (card["status"], card["trigger_id"]) == ("proposed", None)
    assert client.get(f"/api/projects/{pid}/triggers").json() == []


def test_claude_code_is_not_given_notify_where_the_project_sends_none(
    claude_app,  # noqa: F811
    wait_run,
    project_dir,
):
    client, provider, _ = claude_app(
        [
            {"koloni": "notify", "args": {"message": "hello"}},
            {"koloni": "propose_trigger", "args": TRIGGER},
            {"say": "Done."},
        ]
    )
    _pid, cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    argv = claude_app.record()["argv"]
    allowed = set(argv[argv.index("--allowedTools") + 1].split(","))
    assert "mcp__koloni__propose_trigger" in allowed
    assert "mcp__koloni__notify" not in allowed  # (no address, no desktop: as `_lead_tools`)
    # Its call of the one not offered never reached KOLONİ; the other is a card.
    assert koloni_calls(snap, "notify") == []
    ((status, _said),) = koloni_calls(snap, "propose_trigger")
    assert status == "succeeded"
    assert [card["status"] for card in snap["trigger_proposals"]] == ["proposed"]
