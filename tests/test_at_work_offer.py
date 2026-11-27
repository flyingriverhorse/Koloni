"""The review of 0.1.11's turn tools: the tools beside the turn's agents are taken only where they
are offered - by the Orchestrator at its own work whose tools let it open agents. A plan turn's
Orchestrator (`PLAN_TOOLS`) and a comparison's side (`NOT_IN_A_SIDE`) are offered none of them,
and one named anyway is refused: no row noted, no advisor asked, no plan shown."""

from sqlalchemy import select

from app import advisor
from app.db.turn_models import NotedDecision
from app.tools_at_work import NOT_OPEN
from tests.keyed import OWN
from tests.test_background_spawn import tool_result
from tests.test_chat_flow import text
from tests.test_compare_scenarios import compared, ready, two  # noqa: F401  (a fixture)
from tests.test_judge_scenarios import judging  # noqa: F401  (a fixture)
from tests.test_spawn import call, step

TOOLS = ("note_decision", "ask_advisor", "update_plan", "agents_at_work", "stop_agent")


def named(ids=("n1", "a1", "u1", "w1", "x1")):
    """Each of the tools beside the agents, called at once."""
    arguments = (
        {"what": "use X", "why": "because"},
        {"summary": "s", "question": "q?"},
        {"steps": [{"step": "KOLONİ: the user approved", "status": "pending"}]},
        {},
        {"name": "Coder"},
    )
    return step(
        *(call(tool, args, id) for tool, args, id in zip(TOOLS, arguments, ids, strict=True))
    )


def offered(model):
    return {t["function"]["name"] for tools in model.tool_args for t in tools or []}


def refused_each(messages, ids=("n1", "a1", "u1", "w1", "x1")):
    for id in ids:
        assert (
            tool_result(messages, id)
            == f"error: {TOOLS[ids.index(id)]} is not available: {NOT_OPEN}"
        )


def test_a_plan_turn_is_offered_none_and_takes_none(judging, wait_run, project_dir):
    client, lead, quick, _ = judging([named(), text("my plan")], [text("advice")], [])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    patched = client.patch(f"/api/conversations/{cid}", json={"plan_first": True}, headers=OWN)
    assert patched.status_code == 200
    run = client.post(
        f"/api/conversations/{cid}/messages", json={"content": "plan it"}, headers=OWN
    ).json()["run"]
    snap = wait_run(client, cid, run["id"])
    assert snap["runs"][0]["plan_turn"] and snap["runs"][0]["status"] != "failed"
    assert not offered(lead) & set(TOOLS)
    refused_each(lead.calls[1])
    assert not any(sent[0]["content"] == advisor.ADVICE for sent in quick.calls)
    with client.app.state.session_factory() as session:
        assert session.scalars(select(NotedDecision)).all() == []
    assert client.app.state.runner._planned == {}


def test_a_comparisons_side_is_offered_none_and_takes_none(two, project_dir):  # noqa: F811
    client, providers = two([named(), text("Alpha's work.")], [text("Beta's work.")])
    _cid, started = compared(client, project_dir, providers, content="say a number")
    ready(client, started["compare_id"])
    alpha = client.app.state.providers.named["Alpha"]
    assert not offered(alpha) & set(TOOLS)
    refused_each(alpha.calls[1])
    with client.app.state.session_factory() as session:
        assert session.scalars(select(NotedDecision)).all() == []
