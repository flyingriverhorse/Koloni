"""tek-ev, the user 6 Nov: a chat's sub-agent settings are its project's - Settings › This project -
and every chat of it follows them, one made before too; a chat with no project has the defaults;
a night's job follows the project, not the evening's chat; and what runs without asking in each
chat is read in one list."""

from app.db.models import AllowedCommand, AllowedWeb, Conversation, Project, lead_work_of
from tests.test_away_scenarios import card, ended, evening
from tests.test_chat_flow import text

OWN = {"Origin": "http://127.0.0.1:8790"}


def test_a_chat_made_before_follows_a_changed_project_setting(client, project_dir):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    # (an agent's command against the app's address does not loosen them)
    assert client.patch(f"/api/projects/{pid}", json={"spawn_max_agents": 1}).status_code == 403
    assert client.patch(f"/api/projects/{pid}", json={
        "spawn_approval": "always", "spawn_max_agents": 1, "room_tokens": 9000,
        "discussion_budget": None}, headers=OWN).status_code == 200
    got = client.get(f"/api/conversations/{cid}").json()["conversation"]
    assert (got["spawn_approval"], got["spawn_max_agents"], got["room_tokens"]) == (
        "always", 1, 9000)
    # ...and a turn reads them: a room of two is more than the turn may open now
    opened = client.post(f"/api/conversations/{cid}/rooms", headers=OWN, json={
        "goal": "fix it", "with": [{"role": "Coder"}, {"role": "Reviewer"}]})
    assert opened.status_code == 422 and "open 1 sub-agent" in opened.text
    for bad in (0, 21, True):
        assert client.patch(f"/api/projects/{pid}", json={"spawn_max_agents": bad},
                            headers=OWN).status_code == 422


def test_a_chat_with_no_project_has_the_defaults(client, project_dir):
    made = client.post("/api/conversations", headers=OWN).json()
    assert made["project_id"] is None
    assert {name: made[name] for name in (
        "spawn_approval", "spawn_max_depth", "spawn_max_agents", "spawn_max_parallel",
        "discussion_budget", "lead_work", "when_away", "away_minutes", "room_posts",
        "room_tokens", "room_minutes", "room_min_tokens")} == {
        "spawn_approval": "auto", "spawn_max_depth": 2, "spawn_max_agents": 6,
        "spawn_max_parallel": 2, "discussion_budget": None, "lead_work": "delegates",
        "when_away": "waits", "away_minutes": 10, "room_posts": 40, "room_tokens": None,
        "room_minutes": 30, "room_min_tokens": 60_000}
    # (B-414: and a new project's, which its chats follow)
    project = client.post("/api/projects", json={"root_path": str(project_dir)}).json()
    assert project["room_min_tokens"] == 60_000


def test_a_nights_job_follows_the_project_not_the_evenings_chat(make_client, wait_run,
                                                               project_dir):
    client, _model, pid, cid, run_id = evening(
        make_client, project_dir, [text("one done"), text("two done")], lead_work="decides")
    wait_run(client, cid, run_id)
    with client.app.state.session_factory() as session:
        session.get_one(Conversation, cid).lead_work = "itself"  # (a value of before, unused)
        session.commit()
    assert client.post(f"/api/away/{card(client, cid)['id']}/start").json()[
        "status"] == "running"
    jobs = [job["conversation_id"] for job in ended(client, pid)["jobs"]]
    assert len(jobs) == 2
    for job in jobs:
        assert client.get(f"/api/conversations/{job}").json()["conversation"][
            "lead_work"] == "decides"
    client.patch(f"/api/projects/{pid}", json={"lead_work": "delegates"})
    assert client.get(f"/api/conversations/{jobs[0]}").json()["conversation"][
        "lead_work"] == "delegates"
    # The To-do page's own choice is its chats', a night's jobs too (K-r144).
    with client.app.state.session_factory() as session:
        session.get_one(Project, pid).backlog_lead_work = "itself"
        session.commit()
        assert lead_work_of(session, session.get_one(Conversation, jobs[0])) == "itself"
        assert lead_work_of(session, session.get_one(Conversation, cid)) == "delegates"


def test_what_runs_without_asking_is_listed_by_chat(client, project_dir):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    a = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    b = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.post(f"/api/projects/{pid}/conversations")  # (one with none: not listed)
    client.patch(f"/api/conversations/{a}", json={"title": "Alpha"}, headers=OWN)
    with client.app.state.session_factory() as session:
        session.add_all([
            AllowedCommand(conversation_id=a, project_id=pid, prefix="python"),
            AllowedCommand(conversation_id=b, project_id=pid, prefix="rm -rf"),
            AllowedCommand(conversation_id=b, project_id="elsewhere", prefix="npm test"),
            AllowedWeb(conversation_id=a, kind="host", host="example.com"),
            AllowedWeb(project_id=pid, kind="page", host="docs.example.com"),
        ])
        session.commit()
    listed = client.get(f"/api/projects/{pid}/allowed").json()
    assert [(chat["conversation_id"], [r["prefix"] for r in chat["commands"]],
             [r["host"] for r in chat["web"]]) for chat in listed] == [
        (a, ["python"], ["example.com"]), (b, ["rm -rf"], [])]
    assert listed[0]["title"] == "Alpha"
    # a rule kept from before slice 90 for a command that is asked every time: said so
    assert listed[1]["commands"][0]["danger"]
    assert client.get("/api/projects/nope/allowed").status_code == 404


def test_a_project_chat_is_refused_its_projects_settings_and_a_plain_chat_keeps_its_own(
        client, project_dir):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    for body in ({"spawn_approval": "never"}, {"spawn_max_parallel": 4}, {"room_tokens": None},
                 {"discussion_budget": 5}, {"when_away": "lead"}, {"away_minutes": 3},
                 {"lead_work": "itself"}, {"lead_hands_code": False},
                 {"title": "t", "room_posts": 5}):
        # (`request`: the test client sends these to the project, as Settings does - keyed.py)
        refused = client.request("PATCH", f"/api/conversations/{cid}", json=body, headers=OWN)
        assert refused.status_code == 422 and "Settings › This project" in refused.text, body
    assert client.get(f"/api/conversations/{cid}").json()["conversation"]["title"] != "t"
    plain = client.post("/api/conversations", headers=OWN).json()["id"]
    # (whether opening a sub-agent asks: not an agent's command against the app's address)
    for body in ({"spawn_approval": "never"}, {"spawn_max_agents": 20}):
        assert client.request("PATCH", f"/api/conversations/{plain}",
                              json=body).status_code == 403
    kept = client.request("PATCH", f"/api/conversations/{plain}",
                          json={"spawn_approval": "never", "discussion_budget": 5}, headers=OWN)
    assert kept.status_code == 200
    assert (kept.json()["spawn_approval"], kept.json()["discussion_budget"]) == ("never", 5)


def test_a_project_change_is_told_to_its_chats_open_pages(client, project_dir, monkeypatch):
    told = []
    monkeypatch.setattr(client.app.state.bus, "emit_transient",
                        lambda cid, kind, payload: told.append((cid, kind, payload)))
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    a = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    b = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/projects/{pid}", json={"search_agy": True}, headers=OWN)
    assert told == []  # (not one of theirs)
    client.patch(f"/api/projects/{pid}", json={"spawn_max_parallel": 5}, headers=OWN)
    assert sorted((cid, kind, payload["spawn_max_parallel"]) for cid, kind, payload in told) == (
        sorted([(a, "conversation.updated", 5), (b, "conversation.updated", 5)]))


def test_the_to_do_pages_lead_work_is_told_to_the_chats_too(client, project_dir, monkeypatch):
    told = []
    monkeypatch.setattr(client.app.state.bus, "emit_transient",
                        lambda cid, kind, payload: told.append((cid, kind)))
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    chose = client.put(f"/api/projects/{pid}/backlog/choice", headers=OWN, json={
        "permission_mode": "ask", "provider_id": None, "model_id": None, "lead_work": "itself"})
    assert chose.status_code == 200, chose.text
    assert (cid, "conversation.updated") in told
