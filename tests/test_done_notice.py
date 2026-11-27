"""Task 7 (0.1.11): an agent nobody waited for - a background one of the API Orchestrator's, one
a CLI opened - ends while nobody has its chat open: KOLONİ's own desktop notice, its name and how
it ended (its findings counted), where the project has notices on; none for an agent waited for.
A notice never carries the agent's own words (`web.desktop` stands in: Linux CI runs this too)."""

import pytest

import app.web
from app.db.models import Agent
from tests.conftest import Gate
from tests.test_background_spawn import bg
from tests.test_backlog_auto import until
from tests.test_chat_flow import text
from tests.test_spawn import call, step

OWN = {"Origin": "http://127.0.0.1:8790"}
FOUND = {"what": "a finding", "kind": "code", "role": None, "blocking": True}


@pytest.fixture
def shown(monkeypatch):
    said: list = []
    monkeypatch.setattr(app.web, "has_desktop", lambda: True)
    monkeypatch.setattr(app.web, "desktop", lambda title, text: said.append((title, text)))
    return said


def begin(client, project_dir, desktop=True):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    patched = client.patch(f"/api/projects/{pid}", json={"notify_desktop": desktop}, headers=OWN)
    assert patched.status_code == 200, patched.text
    name = client.get(f"/api/projects/{pid}").json()["name"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={"permission_mode": "full_auto"}, headers=OWN)
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}, headers=OWN)
    return name, cid, run.json()["run"]["id"]


def test_a_background_agents_end_is_one_notice_where_nobody_watches(
    make_client, wait_run, project_dir, shown
):
    gate = Gate()
    client, _model = make_client(
        {
            "Lead": [step(bg("Coder", "do A", "s1")), text("asked"), text("read")],
            "Coder": [gate.step(text("A done - sk-koloni-secret-in-its-words"))],
        }
    )
    name, cid, run_id = begin(client, project_dir)
    gate.release()
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    until(lambda: shown)
    assert shown == [(f"KOLONİ — {name}", "Coder finished")]  # KOLONİ's words: none of its own


def test_no_notice_where_the_chat_is_open_or_the_project_has_them_off_or_it_was_waited_for(
    make_client, wait_run, project_dir, shown
):
    # Its chat open (its events streamed): no notice.
    gate = Gate()
    client, _model = make_client(
        {
            "Lead": [step(bg("Coder", "do A", "s1")), text("asked"), text("read")],
            "Coder": [gate.step(text("A done"))],
        }
    )
    _name, cid, run_id = begin(client, project_dir)
    # (as the page's event stream holds its chat: one subscriber)
    client.app.state.bus._subs[cid].add(watcher := object())
    gate.release()
    wait_run(client, cid, run_id)
    client.app.state.bus._subs[cid].discard(watcher)
    assert shown == [] and not client.app.state.runner._telling  # (none on its way either)
    # Notices off for the project: none.
    off = Gate()
    client, _model = make_client(
        {
            "Lead": [step(bg("Coder", "do A", "s1")), text("asked"), text("read")],
            "Coder": [off.step(text("A done"))],
        }
    )
    _name, cid, run_id = begin(client, project_dir, desktop=False)
    off.release()
    wait_run(client, cid, run_id)
    assert shown == [] and not client.app.state.runner._telling  # (none on its way either)
    # Waited for: its opener's answer says it.
    client, _model = make_client(
        {
            "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "do A"}, "s1")), text("x")],
            "Coder": [text("A done")],
        }
    )
    _name, cid, run_id = begin(client, project_dir)
    wait_run(client, cid, run_id)
    assert shown == [] and not client.app.state.runner._telling  # (none on its way either)


def test_the_notice_counts_findings_and_says_a_stop_or_a_failure(
    make_client, wait_run, project_dir, shown
):
    gate = Gate()
    client, _model = make_client({"Lead": [gate.step(text("done"))]})
    name, cid, run_id = begin(client, project_dir)
    gate.wait_partial()
    runner = client.app.state.runner
    lead = runner._lead_of(run_id)
    made = {}
    with runner._factory() as session:
        for who, status, findings in (
            ("Reviewer", "completed", [FOUND, FOUND]),
            ("Checker", "completed", [FOUND]),
            ("Coder", "cancelled", None),
            ("Tester", "failed", None),
        ):
            one = Agent(
                run_id=run_id,
                role_name=who,
                name=who,
                tools=[],
                depth=1,
                status=status,
                findings=findings,
            )
            session.add(one)
            session.flush()
            made[who] = one.id
        session.commit()
    for agent_id in made.values():
        client.portal.call(runner._tell_done, lead, agent_id)
    gate.release()
    wait_run(client, cid, run_id)
    until(lambda: len(shown) == 4)
    assert [said for _title, said in shown] == [
        "Reviewer finished: 2 findings",
        "Checker finished: 1 finding",
        "Coder stopped",
        "Tester failed",
    ]
    assert {title for title, _said in shown} == {f"KOLONİ — {name}"}
