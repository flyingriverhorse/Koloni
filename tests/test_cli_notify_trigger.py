"""0.1.8: a CLI's Orchestrator working with its own tools (Claude Code, Codex) is given notify over
KOLONİ's bridge, held to the same rules as an API model's: only where the project has somewhere to
send it, at its limit. 0.1.9: never propose_trigger - a trigger's turn never starts such a CLI, so
its card's Approve was always refused in that chat; a card left from 0.1.8 still is."""

import app.web
from app.db.models import TriggerProposal
from tests.test_claude_native import claude_app  # noqa: F401  (a fixture)
from tests.test_native_agent import native_app  # noqa: F401  (a fixture)

ORIGIN = {"Origin": "http://127.0.0.1:8790"}
TRIGGER = {
    "name": "Dependencies",
    "kind": "schedule",
    "config": {"at": "17:00", "days": ["fri"]},
    "message": "Look over the dependencies. Change nothing.",
}


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


def test_codex_notifies_the_desktop_and_is_not_offered_propose_trigger(
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
    seen = native_app.record()
    assert "notify" in seen["tools"] and "propose_trigger" not in seen["tools"]
    # As an API model's notify: at most 6 a minute on the desktop - the seventh is refused.
    notified = koloni_calls(snap, "notify")
    assert [status for status, _ in notified] == ["succeeded"] * 6 + ["failed"]
    assert "at most 6 desktop notifications a minute" in notified[-1][1]
    assert shown == [f"step {n}" for n in range(6)]
    # Asked for by name all the same, the bridge refuses it as a tool it does not have.
    refused = seen["results"][-1]
    assert refused["isError"] is True, refused
    assert "propose_trigger is not one of the tools offered here" in refused["content"][0]["text"]
    assert koloni_calls(snap, "propose_trigger") == []
    assert snap["trigger_proposals"] == []
    assert client.get(f"/api/projects/{pid}/triggers").json() == []


def test_a_card_left_from_0_1_8_in_a_native_chat_is_refused_at_approve(
    native_app,  # noqa: F811
    project_dir,
):
    client, provider, _ = native_app([{"say": "never run"}])
    pid, cid = place(client, project_dir, provider)
    with client.app.state.session_factory() as session:
        card = TriggerProposal(
            conversation_id=cid,
            run_id="r-0.1.8",
            name=TRIGGER["name"],
            kind=TRIGGER["kind"],
            config=TRIGGER["config"],
            message=TRIGGER["message"],
            ends={},
        )
        session.add(card)
        session.commit()
        card_id = card.id
    approved = client.post(f"/api/trigger-proposals/{card_id}/approve", headers=ORIGIN)
    assert approved.status_code == 422 and "works with its own tools" in approved.text, (
        approved.text
    )
    assert client.get(f"/api/projects/{pid}/triggers").json() == []
    (left,) = client.get(f"/api/conversations/{cid}/trigger-proposals").json()
    assert (left["status"], left["trigger_id"]) == ("proposed", None)


def test_claude_code_is_given_neither_notify_where_the_project_sends_none_nor_propose_trigger(
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
    assert "mcp__koloni__propose_trigger" not in allowed
    assert "mcp__koloni__notify" not in allowed  # (no desktop: as `_lead_tools`)
    # Its calls of the ones not offered never reached KOLONİ: no card.
    assert koloni_calls(snap, "notify") == []
    assert koloni_calls(snap, "propose_trigger") == []
    assert snap["trigger_proposals"] == []
