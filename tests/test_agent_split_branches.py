"""Branches of the agent runner's tools that no other test reached, kept as they were when their
functions were split (C901): each ran green on the function before its split."""

from app.db.models import ProjectKnowledge
from tests.test_agent_writes import wait_status
from tests.test_chat_flow import text
from tests.test_experts_scenarios import EXPERT
from tests.test_experts_work_scenarios import docs
from tests.test_knowledge_page import expert
from tests.test_mcp_scenarios import LONG, calls, events, give, server
from tests.test_room_open_scenarios import begin as room_begin
from tests.test_room_open_scenarios import open_room
from tests.test_room_scenarios import LONG as ROOM_LONG
from tests.test_room_scenarios import wait
from tests.test_skill_scenarios import SKILL_MD
from tests.test_skills import folder_of
from tests.test_spawn import begin, call, spawn, step
from tests.test_web_tool_scenarios import Net, go, results, setup


def test_a_search_with_no_query_is_refused_before_anybody_is_asked(
    make_client, wait_run, project_dir, monkeypatch
):
    net = Net(monkeypatch)
    client, _model, _pid, cid = setup(
        make_client, project_dir, [step(call("web_search", {"query": "  "}, "s")), text("done")],
        permission_mode="ask")
    snap = wait_run(client, cid, go(client, cid)["id"])
    assert results(snap, "web_search") == [("failed", "error: missing required argument: query")]
    assert net.asked == [] and snap["web_requests"] == []


def test_a_server_switched_off_while_the_user_is_asked_is_not_called(
    make_client, wait_run, project_dir, tmp_path
):
    client, _ = make_client([step(call("fake__echo", {"text": "hi"})), text("done")])
    made, record, _ = server(client, tmp_path)
    give(client, "Lead", "fake")
    cid, run_id = begin(client, project_dir, mode="ask")
    question = wait_status(client, cid, "waiting_approval")["questions"][0]
    off = client.patch(f"/api/mcp-servers/{made['id']}", json={"enabled": False})
    assert off.status_code == 200, off.text
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "Allow"})
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert calls(snap)["fake__echo"] == (
        "failed", "error: fake__echo is no longer available"), calls(snap)
    assert events(record, "start") == [] and events(record, "call") == []


def test_a_skill_for_a_role_that_is_not_there_or_a_teams_lead_is_refused_before_a_card(
    make_client, wait_run, project_dir, tmp_path
):
    folder = folder_of(tmp_path / "tidy", {"SKILL.md": SKILL_MD})
    client, _model = make_client([
        step(call("add_skill", {"folder": str(folder), "roles": ["Coder", "Nobody"]}, "k1")),
        step(call("add_skill", {"folder": str(folder), "roles": ["Web app lead"]}, "k2")),
        text("could not"),
    ])
    cid, run_id = begin(client, project_dir, mode="ask")
    snap = wait_run(client, cid, run_id)
    said = {t["provider_call_id"]: (t["status"], t["result"]) for t in snap["tool_calls"]}
    assert said["k1"] == ("failed", "error: there is no role named Nobody"), said
    assert said["k2"] == (
        "failed", "error: Web app lead is a team's coordinator: its skills are the user's to "
        "give, on the Agents page"), said
    assert snap["pending_skills"] == []


def test_an_invitation_whose_role_or_why_is_not_text_invites_nobody(
    make_client, wait_run, project_dir
):
    client, _model, cid, run_id = room_begin(make_client, project_dir, {
        "Lead": [open_room(), text("ok")],
        "Coder": [text("Nothing to add."),
                  step(call("invite_to_room", {"role": 7}, "i1")),
                  step(call("invite_to_room", {"role": "Tester", "why": 7}, "i2")),
                  wait(), text("Done.")],
        "Reviewer": [text("Nothing to add."), text("Looked: fine.")]})
    snap = wait_run(client, cid, run_id, timeout=ROOM_LONG)
    said = {t["provider_call_id"]: (t["status"], t["result"]) for t in snap["tool_calls"]}
    assert said["i1"] == ("failed", "error: argument role must be a role's name"), said
    assert said["i2"] == ("failed", "error: argument why must be a string"), said
    (room,) = snap["rooms"]
    assert [m["role"] for m in room["members"]] == ["Coder", "Reviewer"]


def test_a_role_whose_sources_are_no_list_is_not_created(make_client, wait_run, project_dir):
    client, _model = make_client([
        step(call("create_role", {"name": "Pay expert", "tools": ["read_file"],
                                  "sources": "docs/pay.md"}, "r")),
        text("could not")])
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    (made,) = [t for t in snap["tool_calls"] if t["name"] == "create_role"]
    assert made["status"] == "failed" and made["result"].startswith(
        "error: knows and sources: "), made["result"]
    assert "Pay expert" not in [role["name"] for role in client.get("/api/roles").json()]


def test_an_expert_whose_model_to_learn_with_is_gone_learns_nothing(
    make_client, wait_run, project_dir
):
    docs(project_dir)
    client, _model = make_client({
        "Lead": [spawn("Pay expert", "learn", "e"), text("done")],
        "Pay expert": [step(call("learn", {}, "l1")), text("not learned")],
    })
    made = expert(client, project_dir, EXPERT)
    with client.app.state.session_factory() as session:  # (as a provider deleted since leaves it)
        session.get_one(ProjectKnowledge, made["knowledge_id"]).learn_with = {
            "provider_id": "gone", "model_id": "any"}
        session.commit()
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never",
                        content="ask the Pay expert to learn")
    snap = wait_run(client, cid, run_id)
    refused = next(t for t in snap["tool_calls"] if t["provider_call_id"] == "l1")
    assert (refused["status"], refused["result"]) == (
        "failed", "error: the model it learns with is gone: the user chooses another")
