"""Branches of the agent runner's tools that no other test reached, kept as they were when their
functions were split (C901): each ran green on the function before its split."""

from tests.test_agent_writes import wait_status
from tests.test_chat_flow import text
from tests.test_mcp_scenarios import LONG, calls, events, give, server
from tests.test_spawn import begin, call, step
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
