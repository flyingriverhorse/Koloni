"""Slice 61: KOLONİ's own tools switched off on the Tools page are offered to no agent,
whatever its role lists, and a call to one is refused; switched on again they are back; left
alone, nothing changes."""

from app.db.models import Flag
from app.roles import SWITCHABLE, tools_off
from tests.test_attachment_agents import send, step, told_of_files
from tests.test_attachments import attach
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import OWN
from tests.test_claude_native import claude_app  # noqa: F401  (a fixture)
from tests.test_claude_native import start as claude_start
from tests.test_experts_answering_scenarios import SEARCHING
from tests.test_experts_research_scenarios import RESEARCHER, fake_search
from tests.test_experts_work_scenarios import offered_to
from tests.test_knowledge_page import expert
from tests.test_native_agent import native_app  # noqa: F401  (a fixture)
from tests.test_native_agent import start as codex_start
from tests.test_spawn import begin, spawn
from tests.test_trigger_scenarios import run_now, trigger
from tests.test_usage_scenarios import began
from tests.test_web_tool_scenarios import setup
from tests.test_web_tools import leave


def names(tools):
    return [tool["function"]["name"] for tool in tools or []]


def switch(client, name, on):
    return client.put(f"/api/builtin-tools/{name}", json={"on": on})


def test_left_alone_every_one_is_on_and_offered(make_client, wait_run, project_dir):
    client, model, _pid, cid = began(make_client, project_dir, [text("hi")])
    assert client.get("/api/builtin-tools").json() == [
        {"name": name, "on": True} for name in SWITCHABLE]
    wait_run(client, cid, send(client, cid, "hello"))
    assert {"web_search", "http_request"} <= set(names(model.tool_args[0]))


def test_switched_off_it_is_offered_to_no_role_that_lists_it_and_back_when_on(
        make_client, wait_run, project_dir):
    client, model, _pid, cid = began(make_client, project_dir, [
        spawn("Researcher"), text("found"), text("one"), text("two")])
    lead = next(role for role in client.get("/api/roles").json() if role["name"] == "Lead")
    assert switch(client, "web_search", False).json()[0] == {"name": "web_search", "on": False}
    wait_run(client, cid, send(client, cid, "first"))
    # Neither the Lead nor its Researcher, though both roles list it; the other web tool stays.
    for offered in model.tool_args[:2]:
        assert "web_search" not in names(offered) and "http_request" in names(offered)
    # The role keeps it: only the offer goes.
    assert next(role for role in client.get("/api/roles").json()
                if role["name"] == "Lead")["tools"] == lead["tools"]

    assert switch(client, "web_search", True).json()[0]["on"] is True
    wait_run(client, cid, send(client, cid, "second"))
    assert "web_search" in names(model.tool_args[-1])


def test_a_call_to_one_switched_off_is_refused(make_client, wait_run, project_dir):
    client, model, _pid, cid = began(make_client, project_dir, [
        step("web_search", {"query": "python"}), text("could not")])
    switch(client, "web_search", False)
    wait_run(client, cid, send(client, cid, "look it up"))
    assert model.calls[1][-1]["content"] == "error: web_search is not available"


def test_read_attachment_switched_off_is_not_offered_nor_said(make_client, wait_run, project_dir):
    client, model, _pid, cid = began(make_client, project_dir, [text("seen")])
    code = attach(client, cid, "cart.ts", b"const x = 1\n").json()
    switch(client, "read_attachment", False)
    wait_run(client, cid, send(client, cid, "see", code["id"]))
    said = told_of_files(model.calls[0])["content"]
    assert "read_attachment" not in said and "read_attachment" not in names(model.tool_args[0])
    assert '"cart.ts" (text, 12 B): 1 line.' in said  # still told of the file
    # It may still hand the file on; the receiver is not said to read it.
    spawn_tool = next(t["function"] for t in model.tool_args[0]
                      if t["function"]["name"] == "spawn_agent")
    assert "reads them" not in spawn_tool["parameters"]["properties"]["attachments"]["description"]


def test_only_its_own_tools_from_the_apps_own_page(make_client, project_dir):
    client, *_ = began(make_client, project_dir, [])
    assert switch(client, "run_command", False).status_code == 404
    del client.headers["Origin"]
    assert switch(client, "web_search", False).status_code == 403
    assert client.get("/api/builtin-tools").json()[0]["on"] is True


def test_http_request_switched_off_the_links_line_does_not_name_it(
        make_client, wait_run, project_dir):
    client, model, _pid, cid = began(make_client, project_dir, [text("seen")])
    code = attach(client, cid, "cart.ts", b"const x = 1\n").json()
    switch(client, "http_request", False)
    wait_run(client, cid, send(client, cid, "see https://stripe.com/docs", code["id"]))
    said = told_of_files(model.calls[0])["content"]
    assert "Links in the message are not read" not in said and "http_request" not in said


def test_web_search_switched_off_an_expert_is_not_told_it_may_search(
        make_client, wait_run, project_dir):
    client, model = make_client({"Lead": [spawn("Pay expert", "what?", "e"), text("done")],
                                 "Pay expert": [text("I do not know.")]})
    expert(client, project_dir, SEARCHING)
    client.headers.update(OWN)
    switch(client, "web_search", False).raise_for_status()
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never",
                        content="ask the Pay expert")
    wait_run(client, cid, run_id)
    assert "web_search" not in offered_to(model, "Pay expert")
    assert "each search costs" not in model.calls_of["Pay expert"][0][0]["content"]


def test_web_search_switched_off_an_expert_neither_gets_learn_nor_learns(
        make_client, wait_run, project_dir, monkeypatch):
    searched = fake_search(monkeypatch, "https://a.test/hooks")

    async def off_then_learn(on_delta):
        # (Switched off while it works: written as the Tools page writes it.)
        with client.app.state.session_factory() as session:
            session.add(Flag(name="tool_off:web_search", value="1"))
            session.commit()
        return step("learn", {}, "l1")

    client, model = make_client({
        "Lead": [spawn("Pay expert", "learn", "e"), text("done"),
                 spawn("Pay expert", "learn", "f"), text("done")],
        "Pay expert": [off_then_learn, text("could not"), text("not learned")]})
    client.headers.update(OWN)
    expert(client, project_dir, RESEARCHER)
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never",
                        content="have the Pay expert learn")
    snap = wait_run(client, cid, run_id)
    refused = next(t for t in snap["tool_calls"] if t["provider_call_id"] == "l1")
    assert refused["status"] == "failed"
    assert "web_search is switched off on the Tools page" in refused["result"]
    assert searched == []

    # Opened while it is off, it is not given learn at all.
    run_id = send(client, cid, "again")
    wait_run(client, cid, run_id)
    assert "learn" not in names(model.tool_args[-2])


def test_a_row_of_a_tool_no_longer_switched_here_keeps_nothing_off(make_client, project_dir):
    client, *_ = began(make_client, project_dir, [])
    with client.app.state.session_factory() as session:
        session.add(Flag(name="tool_off:run_command", value="1"))
        session.commit()
        assert tools_off(session) == frozenset()
    # Switched twice the same way, as a double click sends it: no error, one row.
    assert switch(client, "web_search", False).status_code == 200
    assert switch(client, "web_search", False).json()[0]["on"] is False
    assert switch(client, "web_search", True).json()[0]["on"] is True
    assert switch(client, "web_search", True).status_code == 200


def test_claude_code_working_natively_loses_its_own_web_tool_switched_off(
        claude_app, wait_run, project_dir):  # noqa: F811
    client, provider, _ = claude_app([{"say": "looked"}])
    client.headers.update(OWN)
    switch(client, "web_search", False)
    cid, run_id = claude_start(client, project_dir, provider, "full_auto")
    wait_run(client, cid, run_id)
    argv = claude_app.record()["argv"]
    withheld = set(argv[argv.index("--disallowedTools") + 1].split(","))
    assert "WebSearch" in withheld and "WebFetch" not in withheld


def test_codex_working_natively_has_its_own_search_off_only_while_switched_off(
        native_app, wait_run, project_dir):  # noqa: F811
    client, provider, _ = native_app([{"say": "hi"}])
    client.headers.update(OWN)
    cid, run_id = codex_start(client, project_dir, provider)
    wait_run(client, cid, run_id)
    assert "web_search='disabled'" not in native_app.record()["argv"]
    assert "features.apps=false" not in native_app.record()["argv"]
    switch(client, "web_search", False)
    native_app.rescript([{"say": "hi"}])
    cid, run_id = codex_start(client, project_dir, provider)
    wait_run(client, cid, run_id)
    argv = native_app.record()["argv"]
    assert argv[argv.index("web_search='disabled'") - 1] == "-c"
    # B-185: its apps (connectors) too, with either web tool off
    assert argv[argv.index("features.apps=false") - 1] == "-c"
    switch(client, "web_search", True)
    switch(client, "http_request", False)
    native_app.rescript([{"say": "hi"}])
    cid, run_id = codex_start(client, project_dir, provider)
    wait_run(client, cid, run_id)
    argv = native_app.record()["argv"]
    assert "features.apps=false" in argv and "web_search='disabled'" not in argv


def test_an_unattended_turn_is_not_told_it_may_use_a_web_tool_switched_off(
        make_client, wait_run, project_dir):
    client, model, pid, cid = setup(make_client, project_dir, [text("done")])
    switch(client, "web_search", False)
    switch(client, "http_request", False)
    made = trigger(client, pid, cid, permissions=leave(web=True, hosts=["a.test"]))
    wait_run(client, cid, run_now(client, made["id"]), timeout=10)
    assert "make no web search; make no HTTP request" in model.calls[-1][0]["content"]
