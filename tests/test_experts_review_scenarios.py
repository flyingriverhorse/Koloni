"""K-uzman, part 1's review round, an agent and its expert: an agent that makes no web request
of its own gets no expert that does, and one with an address is shown on its card; an expert
learns once a turn, with its own model where it has one; an unattended turn learns only where
its trigger lets it write; a project with no network learns from no address.
Contract: `tests/test_experts_scenarios.py`.
"""



from app.roles import ALL_TOOLS
from tests.test_agent_writes import wait_status
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import OWN
from tests.test_experts_scenarios import (
    EXPERT,
    GUIDE,
    MD,
    OPEN,
    SITE,
    Site,
    wait_learned,
)
from tests.test_experts_work_scenarios import docs, offered_to
from tests.test_knowledge_page import expert
from tests.test_spawn import begin, call, spawn, step
from tests.test_trigger_scenarios import NOBODY, run_now, trigger
from tests.test_web_tool_scenarios import go, setup

# --- an agent and its expert ----------------------------------------------------------------

URL_EXPERT = {**EXPERT, "knowledge": {"topic": "Pay", "sources": [f"{SITE}/pay"]}}
STRIPE = call("create_role", {"name": "Stripe expert", "tools": ["read_file", "search"],
                              "sources": ["https://docs.stripe.com/payments"]}, "r1")


def without_http(client):
    lead = next(r for r in client.get("/api/roles").json() if r["name"] == "Lead")
    tools = [one for one in ALL_TOOLS if one != "http_request"]
    assert client.patch(f"/api/roles/{lead['id']}", json={"tools": tools},
                        headers=OWN).status_code == 200


def test_an_expert_with_an_address_is_shown_on_its_card_below_full_auto(
    make_client, wait_run, project_dir
):
    client, _model = make_client({"Lead": [step(STRIPE), text("made")]})
    cid, run_id = begin(client, project_dir, mode="auto_edit", content="make a Stripe expert")
    snap = wait_status(client, cid, "waiting_approval")
    assert snap["pending_roles"][0]["knowledge"]["sources"] == ["https://docs.stripe.com/payments"]
    assert client.post(f"/api/tool-calls/{snap['tool_calls'][0]['id']}/approve").status_code == 200
    wait_run(client, cid, run_id)


def test_an_agent_that_makes_no_web_request_makes_no_expert_that_does(
    make_client, wait_run, project_dir
):
    client, _model = make_client({"Lead": [step(STRIPE), text("could not")]})
    without_http(client)
    cid, run_id = begin(client, project_dir, mode="full_auto", content="make a Stripe expert")
    snap = wait_run(client, cid, run_id)
    made = snap["tool_calls"][0]
    assert made["status"] == "failed" and "makes none" in made["result"]


def test_an_expert_reads_an_address_only_under_one_that_makes_web_requests(
    make_client, wait_run, project_dir
):
    client, model = make_client({"Lead": [spawn("Pay expert", "what is pay()?", "e"),
                                          text("done")],
                                 "Pay expert": [text("I have not learned yet.")]})
    without_http(client)
    expert(client, project_dir, URL_EXPERT)
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never",
                        content="ask the Pay expert")
    wait_run(client, cid, run_id)
    assert "learn" not in offered_to(model, "Pay expert")


def test_an_expert_learns_an_address_once_a_turn(make_client, wait_run, project_dir, monkeypatch):
    Site(monkeypatch, {f"{SITE}/robots.txt": OPEN, f"{SITE}/pay/llms.txt": (
        200, "text/plain", "- [a](/pay/a)\n"), f"{SITE}/pay/a": (200, MD, "pay(amount)")})
    client, _model = make_client({
        "Lead": [spawn("Pay expert", "learn", "e"), text(GUIDE), text("done")],
        "Pay expert": [step(call("learn", {}, "l1")), step(call("learn", {}, "l2")),
                       text("learned")],
    })
    expert(client, project_dir, URL_EXPERT)
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never",
                        content="ask the Pay expert to learn")
    snap = wait_run(client, cid, run_id)
    by_id = {t["provider_call_id"]: t for t in snap["tool_calls"]}
    assert by_id["l1"]["status"] == "succeeded", by_id["l1"]["result"]
    assert by_id["l1"]["result"].startswith("learned: 1 read")
    assert by_id["l2"]["status"] == "failed" and "in this turn already" in by_id["l2"]["result"]


def test_it_learns_with_its_own_model_one_its_provider_may_run(make_client, wait_run,
                                                               project_dir):
    docs(project_dir)
    client, _model = make_client({
        "Lead": [spawn("Pay expert", "learn", "e"), text("done"),
                 spawn("Pay expert", "learn", "f"), text(GUIDE), text("done")],
        "Pay expert": [step(call("learn", {}, "l1")), text("not learned"),
                       step(call("learn", {}, "l2")), text("learned")],
    })
    provider = client.get("/api/providers").json()[0]
    # (Its own model is listed too: the turn runs on it.)
    listed = client.patch(f"/api/providers/{provider['id']}", headers=OWN, json={
        "default_model": "fake-model", "models": [{"name": "fake-model"}, {"name": "cheap-1"}],
        "only_listed": True})
    assert listed.status_code == 200, listed.text
    made = expert(client, project_dir, {**EXPERT, "knowledge": {
        **EXPERT["knowledge"], "learn_with": {"provider_id": provider["id"],
                                              "model_id": "not-listed"}}})
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never",
                        content="ask the Pay expert to learn")
    snap = wait_run(client, cid, run_id)
    refused = next(t for t in snap["tool_calls"] if t["provider_call_id"] == "l1")
    assert refused["status"] == "failed" and "nothing was learned" in refused["result"]
    patch = {**made["knowledge"], "learn_with": {"provider_id": provider["id"],
                                                 "model_id": "cheap-1"}}
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.put(f"/api/knowledge/{made['knowledge_id']}", params={"project_id": pid},
                      json=patch, headers=OWN).status_code == 200
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never",
                        content="ask the Pay expert to learn")
    snap = wait_run(client, cid, run_id)
    learned = next(t for t in snap["tool_calls"] if t["provider_call_id"] == "l2")
    assert learned["status"] == "succeeded", learned["result"]
    pid = snap["conversation"]["project_id"]
    state = client.get(f"/api/roles/{made['id']}/knowledge", params={"project_id": pid}).json()
    assert state["learned"]["model"].endswith("cheap-1")


def test_a_model_that_does_not_answer_is_said_on_the_knowledge_tab(make_client, wait_run,
                                                                   project_dir):
    from app.model_client import ModelUnavailable

    docs(project_dir)
    client, _model = make_client({
        "Lead": [spawn("Pay expert", "learn", "e"), ModelUnavailable("down"), text("done")],
        "Pay expert": [step(call("learn", {}, "l1")), text("not learned")],
    })
    role = expert(client, project_dir, EXPERT)
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never",
                        content="ask the Pay expert to learn")
    snap = wait_run(client, cid, run_id)
    learned = next(t for t in snap["tool_calls"] if t["provider_call_id"] == "l1")
    assert learned["status"] == "failed" and "isn't answering" in learned["result"]
    pid = snap["conversation"]["project_id"]
    state = client.get(f"/api/roles/{role['id']}/knowledge", params={"project_id": pid}).json()
    assert "isn't answering" in state["failed"]


def test_an_unattended_turn_learns_only_where_its_trigger_lets_it_write(
    make_client, wait_run, project_dir
):
    docs(project_dir)
    client, _model, pid, cid = setup(make_client, project_dir, {
        "Lead": [spawn("Pay expert", "learn", "e"), text("done")],
        "Pay expert": [step(call("learn", {}, "l1")), text("could not")],
    })
    expert(client, project_dir, EXPERT)
    made = trigger(client, pid, cid, permissions={"write": False, "commands": [], "agents": 1})
    run_id = run_now(client, made["id"])
    snap = wait_run(client, cid, run_id, timeout=10)
    learned = next(t for t in snap["tool_calls"] if t["provider_call_id"] == "l1")
    assert learned["status"] == "failed" and NOBODY in learned["result"]
    assert not (project_dir / ".koloni").exists()


def test_a_project_with_no_network_learns_from_no_address(make_client, wait_run, project_dir,
                                                          monkeypatch):
    site = Site(monkeypatch, {})
    client, _model, pid, cid = setup(make_client, project_dir, {
        "Lead": [spawn("Pay expert", "learn", "e"), text("done")],
        "Pay expert": [step(call("learn", {}, "l1")), text("could not")],
    }, project={"docker_image": "python:3.12", "exec_location": "docker"},
        spawn_approval="never")
    role = expert(client, project_dir, URL_EXPERT)
    snap = wait_run(client, cid, go(client, cid)["id"])
    learned = next(t for t in snap["tool_calls"] if t["provider_call_id"] == "l1")
    assert learned["status"] == "failed" and "network access is off" in learned["result"]
    clicked = client.post(f"/api/roles/{role['id']}/learn", json={"project_id": pid}, headers=OWN)
    assert clicked.status_code == 409 and "network access is off" in clicked.text
    assert site.asked == []
    assert wait_learned(client, role["id"], pid)["learned"] is None
