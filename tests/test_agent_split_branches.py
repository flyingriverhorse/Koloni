"""Branches of the agent runner's tools that no other test reached, kept as they were when their
functions were split (C901): each ran green on the function before its split."""

import time

from app.db.models import ProjectKnowledge
from tests.conftest import scaled
from tests.test_agent_writes import wait_status
from tests.test_agy_agent import agy_app  # noqa: F401
from tests.test_agy_agent import start as start_agy
from tests.test_browser import fake, served  # noqa: F401
from tests.test_chat_flow import start_in_mode, text
from tests.test_experts_scenarios import EXPERT
from tests.test_experts_work_scenarios import docs
from tests.test_knowledge_page import expert
from tests.test_mcp_scenarios import LONG, ORIGIN, calls, events, give, server
from tests.test_native_agent import native_app  # noqa: F401
from tests.test_native_agent import start as start_native
from tests.test_room_open_scenarios import begin as room_begin
from tests.test_room_open_scenarios import open_room
from tests.test_room_scenarios import LONG as ROOM_LONG
from tests.test_room_scenarios import wait
from tests.test_skill_scenarios import SKILL_MD
from tests.test_skills import folder_of
from tests.test_spawn import begin, call, spawn, step
from tests.test_web_tool_scenarios import Net, go, results, setup
from tests.test_yazma_denetimi import open_card


def test_a_search_with_no_query_is_refused_before_anybody_is_asked(
    make_client, wait_run, project_dir, monkeypatch
):
    net = Net(monkeypatch)
    client, _model, _pid, cid = setup(
        make_client,
        project_dir,
        [step(call("web_search", {"query": "  "}, "s")), text("done")],
        permission_mode="ask",
    )
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
    assert calls(snap)["fake__echo"] == ("failed", "error: fake__echo is no longer available"), (
        calls(snap)
    )
    assert events(record, "start") == [] and events(record, "call") == []


def test_a_skill_for_a_role_that_is_not_there_or_a_teams_lead_is_refused_before_a_card(
    make_client, wait_run, project_dir, tmp_path
):
    folder = folder_of(tmp_path / "tidy", {"SKILL.md": SKILL_MD})
    client, _model = make_client(
        [
            step(call("add_skill", {"folder": str(folder), "roles": ["Coder", "Nobody"]}, "k1")),
            step(call("add_skill", {"folder": str(folder), "roles": ["Web app lead"]}, "k2")),
            text("could not"),
        ]
    )
    cid, run_id = begin(client, project_dir, mode="ask")
    snap = wait_run(client, cid, run_id)
    said = {t["provider_call_id"]: (t["status"], t["result"]) for t in snap["tool_calls"]}
    assert said["k1"] == ("failed", "error: there is no role named Nobody"), said
    assert said["k2"] == (
        "failed",
        "error: Web app lead is a team's coordinator: its skills are the user's to "
        "give, on the Agents page",
    ), said
    assert snap["pending_skills"] == []


def test_an_invitation_whose_role_or_why_is_not_text_invites_nobody(
    make_client, wait_run, project_dir
):
    client, _model, cid, run_id = room_begin(
        make_client,
        project_dir,
        {
            "Lead": [open_room(), text("ok")],
            "Coder": [
                text("Nothing to add."),
                step(call("invite_to_room", {"role": 7}, "i1")),
                step(call("invite_to_room", {"role": "Tester", "why": 7}, "i2")),
                wait(),
                text("Done."),
            ],
            "Reviewer": [text("Nothing to add."), text("Looked: fine.")],
        },
    )
    snap = wait_run(client, cid, run_id, timeout=ROOM_LONG)
    said = {t["provider_call_id"]: (t["status"], t["result"]) for t in snap["tool_calls"]}
    assert said["i1"] == ("failed", "error: argument role must be a role's name"), said
    assert said["i2"] == ("failed", "error: argument why must be a string"), said
    (room,) = snap["rooms"]
    assert [m["role"] for m in room["members"]] == ["Coder", "Reviewer"]


def test_a_role_whose_sources_are_no_list_is_not_created(make_client, wait_run, project_dir):
    client, _model = make_client(
        [
            step(
                call(
                    "create_role",
                    {"name": "Pay expert", "tools": ["read_file"], "sources": "docs/pay.md"},
                    "r",
                )
            ),
            text("could not"),
        ]
    )
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    (made,) = [t for t in snap["tool_calls"] if t["name"] == "create_role"]
    assert made["status"] == "failed" and made["result"].startswith("error: knows and sources: "), (
        made["result"]
    )
    assert "Pay expert" not in [role["name"] for role in client.get("/api/roles").json()]


def test_an_expert_whose_model_to_learn_with_is_gone_learns_nothing(
    make_client, wait_run, project_dir
):
    docs(project_dir)
    client, _model = make_client(
        {
            "Lead": [spawn("Pay expert", "learn", "e"), text("done")],
            "Pay expert": [step(call("learn", {}, "l1")), text("not learned")],
        }
    )
    made = expert(client, project_dir, EXPERT)
    with client.app.state.session_factory() as session:  # (as a provider deleted since leaves it)
        session.get_one(ProjectKnowledge, made["knowledge_id"]).learn_with = {
            "provider_id": "gone",
            "model_id": "any",
        }
        session.commit()
    cid, run_id = begin(
        client,
        project_dir,
        mode="full_auto",
        spawn_approval="never",
        content="ask the Pay expert to learn",
    )
    snap = wait_run(client, cid, run_id)
    refused = next(t for t in snap["tool_calls"] if t["provider_call_id"] == "l1")
    assert (refused["status"], refused["result"]) == (
        "failed",
        "error: the model it learns with is gone: the user chooses another",
    )


def test_a_browser_tool_whose_argument_is_not_what_it_takes_is_refused(
    fake,
    served,
    make_client,
    wait_run,
    project_dir,  # noqa: F811
):
    client, _model = make_client(
        [
            step(call("browser_open", {"url": served}, "b1")),
            step(call("browser_type", {"selector": "#name", "text": 5}, "b2")),
            step(call("browser_key", {"key": 5}, "b3")),
            step(call("browser_scroll", {"dy": "down"}, "b4")),
            text("done"),
        ]
    )
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id, timeout=15)
    said = {t["provider_call_id"]: (t["status"], t["result"]) for t in snap["tool_calls"]}
    assert said["b2"] == ("failed", "error: missing required argument: text"), said
    assert said["b3"] == ("failed", "error: missing required argument: key"), said
    assert said["b4"] == ("failed", "error: missing required argument: dy"), said


def test_a_discussion_opens_no_member_past_the_turns_limit_of_agents(
    make_client, wait_run, project_dir
):
    client, _model = make_client(
        {
            "Lead": [
                step(call("discuss", {"topic": "x", "with": ["Reviewer", "Tester"]}, "a")),
                text("done"),
            ]
        }
    )
    cid, run_id = begin(
        client, project_dir, mode="full_auto", spawn_approval="never", spawn_max_agents=1
    )
    snap = wait_run(client, cid, run_id)
    (refused,) = snap["tool_calls"]
    assert (refused["status"], refused["result"]) == (
        "failed",
        "error: limit of 1 sub-agents per turn reached: no Tester can be opened. "
        "Invite agents that already exist.",
    )
    assert snap["discussions"] == [] and len(snap["agents"]) == 1


def test_an_agy_older_than_the_bridge_is_told_which_servers_tools_it_was_not_given(
    agy_app,
    wait_run,
    project_dir,
    tmp_path,  # noqa: F811
):
    client, provider, _ = agy_app([{"say": "I did it myself."}], version="1.4.8")
    server(client, tmp_path)
    give(client, "Lead", "fake")
    cid, run_id = start_agy(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    said = [(t["name"], t["status"], t["result"]) for t in snap["tool_calls"]]
    assert said == [
        (
            "use_mcp_server",
            "denied",
            "the tools of the MCP server fake were not given to agy: it is handed none of KOLONİ's "
            "tools, and a server's tools reach a CLI only through them",
        ),
        (
            "koloni_tools",
            "denied",
            "agy cannot open sub-agents or write with KOLONİ's tools here: it is handed none of "
            "them (the Models page says why)",
        ),
    ], said


def test_a_cli_stopped_during_its_keep_card_leaves_nothing_to_hold_the_folder(
    native_app,
    wait_run,
    project_dir,  # noqa: F811
):
    (project_dir / ".git" / "hooks").mkdir(parents=True)
    client, provider, _ = native_app(
        [
            {"run": "pytest -q", "touches": {".git/hooks/pre-commit": "#!/bin/sh\necho hi\n"}},
            {"say": "ok"},
        ]
    )
    cid, run_id = start_native(client, project_dir, provider)
    open_card(client, cid)
    client.post(f"/api/runs/{run_id}/cancel", headers={"Origin": ORIGIN})
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "cancelled", snap["runs"][0]
    keeps, deadline = client.app.state.runner._keeps, time.monotonic() + scaled(5)
    while keeps.get(str(project_dir)) and time.monotonic() < deadline:
        time.sleep(0.05)  # (the cancelled card leaves the table a moment after its cancel)
    assert not keeps.get(str(project_dir))
    assert not (project_dir / ".git/hooks/pre-commit").exists()
