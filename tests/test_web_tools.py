"""The web tools around `app.web` (slice 18c): what the acceptance set leaves open.

A CLI asked to search, the rules kept for a conversation, what a refusal and a Stop leave
behind, the project's settings, what a trigger may be given. No test touches the network.
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import select

import app.web
from app.db.models import Event
from app.model_cli import ClaudeSearch, CodexSearch
from app.roles import BROWSER
from tests.test_chat_flow import text
from tests.test_migration_0002 import _config
from tests.test_parallel import until
from tests.test_spawn import call, step
from tests.test_trigger_scenarios import run_now, trigger
from tests.test_web_tool_scenarios import DDG_PAGE, ORIGIN, Net, get, go, results, search, setup

FAKE = [sys.executable, str(Path(__file__).with_name("fake_cli.py"))]
FOUND = [{"title": "T", "url": "https://example.org/", "snippet": "s"}]


@pytest.fixture
def searcher(tmp_path):
    record, plan = tmp_path / "record.json", tmp_path / "plan.json"

    def make(kind, model=None, **plan_fields):
        plan.write_text(json.dumps({"record": str(record), **plan_fields}), encoding="utf-8")
        return kind(model=model, timeout=20.0, launcher=FAKE, env={"FAKE_CLI_PLAN": str(plan)})

    return make, lambda: json.loads(record.read_text(encoding="utf-8"))


# --- a CLI asked to search ---------------------------------------------------------------


@pytest.mark.anyio
async def test_codex_is_asked_to_search_and_only_that(searcher):
    make, record = searcher
    codex = make(CodexSearch, model="gpt-x", answer={"results": FOUND}, searched="search")
    assert await codex.search("py docs") == FOUND
    argv = record()["argv"]
    assert argv[:2] == ["--search", "exec"] and argv[-1] == "-"
    for flag in ("--json", "--skip-git-repo-check", "--ephemeral"):
        assert flag in argv
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert argv[argv.index("--model") + 1] == "gpt-x"
    assert "--output-schema" not in argv
    assert record()["stdin"].endswith("py docs") and record()["files"] == {}
    assert "koloni-search-" in record()["cwd"]          # an empty folder of its own
    # Measured with the real CLI on 10 Oct 2026: with its features on, a query that
    # asked for it had Codex run a command and read a file; with every one of these off
    # the search still ran and the file was not read. Its code-mode host stays on:
    # without it the search did not run, and Codex made a result up.
    off = [argv[at + 1] for at, flag in enumerate(argv) if flag == "--disable"]
    assert off == [one for one in CodexSearch.DISABLED if one != "code_mode_host"]
    assert {"shell_tool", "unified_exec", "apps", "plugins", "hooks", "memories"} <= set(off)
    assert "web_search='disabled'" not in argv  # (a model step's: never a search's)


@pytest.mark.anyio
@pytest.mark.parametrize("kind, tool", [(CodexSearch, "search"), (ClaudeSearch, "WebSearch")])
async def test_a_cli_that_made_no_search_gave_no_results_whatever_it_wrote(searcher, kind, tool):
    make, _record = searcher
    made_up = {"results": [{"title": "Python Downloads", "url": "https://www.python.org/",
                            "snippet": "web search was unavailable"}]}
    assert await make(kind, answer=made_up).search("q") is None
    other = "open_page" if kind is CodexSearch else "WebFetch"
    assert await make(kind, answer=made_up, searched=other).search("q") is None
    assert await make(kind, answer=made_up, searched=tool).search("q") == made_up["results"]
    if kind is ClaudeSearch:        # a search that was asked for and failed is none either
        assert await make(kind, answer=made_up, searched=tool, search_failed=True).search(
            "q") is None


@pytest.mark.anyio
async def test_codex_searches_without_the_users_own_skills_and_mcp_servers(searcher, tmp_path):
    home = tmp_path / "codex-home"
    (home / "skills" / "mine").mkdir(parents=True)
    (home / "skills" / "mine" / "SKILL.md").write_text("x", encoding="utf-8")
    (home / "config.toml").write_text('[mcp_servers.mine]\ncommand = "x"\n', encoding="utf-8")
    make, record = searcher
    await make(CodexSearch, answer={"results": FOUND}, searched="search").search("q")
    line = " ".join(record()["argv"])
    assert "mcp_servers.mine.enabled=false" in line and "enabled=false}" in line


@pytest.mark.anyio
async def test_claude_code_is_asked_to_search_with_its_search_tool_alone(searcher):
    make, record = searcher
    claude = make(ClaudeSearch, model="sonnet", answer={"results": FOUND}, searched="WebSearch")
    assert await claude.search("q") == FOUND
    assert record()["files"] == {} and "koloni-search-" in record()["cwd"]
    argv = record()["argv"]
    assert argv[0] == "-p" and "--strict-mcp-config" in argv
    assert argv[argv.index("--tools") + 1] == "WebSearch"
    assert argv[argv.index("--allowedTools") + 1] == "WebSearch"
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert "--json-schema" not in argv and record()["stdin"].endswith("q")


@pytest.mark.anyio
async def test_a_cli_that_does_not_answer_a_search_gives_nothing(searcher):
    make, _record = searcher
    assert await make(CodexSearch, answer={"text": "no idea"}, searched="search").search(
        "q") is None
    assert await make(ClaudeSearch, answer={"results": "many"}, searched="WebSearch").search(
        "q") is None


@pytest.mark.anyio
async def test_the_cli_way_asks_the_users_providers_in_their_order(monkeypatch):
    asked = []

    class Client:
        def __init__(self, name, found):
            self.name, self.found = name, found

        async def search(self, query):
            asked.append((self.name, query))
            if isinstance(self.found, Exception):
                raise self.found
            return self.found

    monkeypatch.setattr(app.web, "searchers", lambda: [
        Client("broken", RuntimeError("not signed in")), Client("silent", None),
        Client("third", FOUND), Client("never", FOUND)])
    assert await app.web.cli_search("q") == FOUND
    assert asked == [("broken", "q"), ("silent", "q"), ("third", "q")]
    monkeypatch.setattr(app.web, "searchers", list)
    assert await app.web.cli_search("q") is None


def test_the_clis_that_can_search_are_the_users_codex_claude_code_and_agy(client):
    from app.model_agy import AgySearch
    from app.providers import search_clients

    client.headers["Origin"] = ORIGIN
    for name, kind in (("A local", "openai_compat"), ("My agy", "agy_cli"),
                       ("My Codex", "codex_cli"), ("Q", "qoder_cli"), ("My Claude", "claude_cli")):
        body = {"name": name, "kind": kind, "default_model": "m"}
        if kind == "openai_compat":
            body["base_url"] = "http://127.0.0.1:9/v1"
        if kind == "agy_cli":
            body["mode"] = "native"  # it searches reading only, however it is set to run
        assert client.post("/api/providers", json=body).status_code == 201, kind
    found = search_clients(client.app.state.session_factory)
    assert [type(one) for one in found] == [AgySearch, CodexSearch, ClaudeSearch]
    assert [one._model for one in found] == ["m", "m", "m"]
    assert found[0].reads and "--dangerously-skip-permissions" not in found[0]._arguments(Path())


# --- asked first -------------------------------------------------------------------------


def events(client, cid):
    with client.app.state.session_factory() as session:
        rows = session.scalars(select(Event).where(Event.conversation_id == cid)).all()
        return [(row.type, row.payload) for row in rows]


def asked_of(client, cid, count=1):
    """The snapshot once `count` requests have been put before the user, the last waiting."""
    snap = until(client, cid, lambda s: len(s["web_requests"]) == count
                 and s["web_requests"][-1]["status"] == "proposed")
    return snap, snap["web_requests"][-1]


def decide(client, asked, how="approve", **body):
    return client.post(f"/api/web-requests/{asked['id']}/{how}",
                       json=body if how == "approve" else None)


def test_a_search_the_user_declines_is_not_made(make_client, wait_run, project_dir, monkeypatch):
    net = Net(monkeypatch, {"duckduckgo.com": (200, "text/html", DDG_PAGE)})
    client, model, pid, cid = setup(make_client, project_dir, [step(search()), text("done")],
                                    permission_mode="auto_edit")     # asked there too
    run_id = go(client, cid)["id"]
    snap, asked = asked_of(client, cid)
    assert (asked["kind"], asked["method"], asked["host"], asked["headers"]) == (
        "search", None, None, [])
    assert decide(client, asked, "reject").json()["status"] == "rejected"
    snap = wait_run(client, cid, run_id)
    ((status, said),) = results(snap, "web_search")
    assert status == "denied" and "the user declined this search" in said
    assert net.asked == [] and snap["allowed_web"] == []
    assert decide(client, asked).status_code == 409                  # decided already
    assert decide(client, {"id": "nope"}).status_code == 404


def test_only_the_apps_own_page_decides_what_goes_out(make_client, wait_run, project_dir,
                                                      monkeypatch):
    net = Net(monkeypatch)
    client, model, pid, cid = setup(make_client, project_dir, [step(search()), text("done")],
                                    permission_mode="ask")
    run_id = go(client, cid)["id"]
    snap, asked = asked_of(client, cid)
    del client.headers["Origin"]          # as a command an agent runs would ask
    assert decide(client, asked, remember=True).status_code == 403
    assert decide(client, asked, "reject").status_code == 403
    assert net.asked == []
    client.headers["Origin"] = ORIGIN
    client.post(f"/api/runs/{run_id}/cancel")
    snap = wait_run(client, cid, run_id)
    # a turn that is stopped leaves no card waiting
    assert [w["status"] for w in snap["web_requests"]] == ["rejected"]
    assert net.asked == []


def test_always_allows_get_from_that_host_and_nothing_more(make_client, wait_run, project_dir,
                                                           monkeypatch):
    net = Net(monkeypatch, {"example.com": (200, "text/plain", "ok"),
                            "example.org": (200, "text/plain", "ok")})
    post = call("http_request", {"method": "POST", "url": "https://example.com/c", "body": "abc",
                                 "headers": {"X-Key": "K1", "Accept": "*/*"}}, "p")
    client, model, pid, cid = setup(make_client, project_dir, [
        step(get("https://example.com/a", "h1")), step(get("https://EXAMPLE.com./b", "h2")),
        step(post), step(get("https://other.example.org/d", "h4")), text("done")],
        permission_mode="ask")
    run_id = go(client, cid)["id"]
    snap, asked = asked_of(client, cid)
    assert (asked["kind"], asked["method"], asked["target"], asked["host"]) == (
        "http", "GET", "https://example.com/a", "example.com")
    assert decide(client, asked, remember=True).json()["status"] == "approved"
    # the second GET from that host is not asked about; the POST to it is
    snap, asked = asked_of(client, cid, 2)
    assert (asked["method"], asked["headers"], asked["body_chars"]) == (
        "POST", ["Accept", "X-Key"], 3)
    assert [(rule["kind"], rule["host"]) for rule in snap["allowed_web"]] == [
        ("host", "example.com")]
    assert decide(client, asked, remember=True).status_code == 200   # no rule for a POST
    snap, asked = asked_of(client, cid, 3)                            # and another host is asked
    assert asked["host"] == "other.example.org"
    assert decide(client, asked).status_code == 200
    snap = wait_run(client, cid, run_id)
    assert [status for status, _ in results(snap, "http_request")] == ["succeeded"] * 4
    assert [(rule["kind"], rule["host"]) for rule in snap["allowed_web"]] == [
        ("host", "example.com")]
    assert [method for method, _url, _ip in net.asked] == ["GET", "GET", "POST", "GET"]
    said = json.dumps(snap) + json.dumps(events(client, cid))
    assert "K1" not in said and '\\"X-Key\\": \\"***\\"' in said
    kinds = [kind for kind, _payload in events(client, cid)]
    assert kinds.count("web_request.updated") == 6 and kinds.count("allowed_web.updated") == 1


def test_a_rule_is_for_a_get_that_carries_nothing_of_the_agents_own(
    make_client, wait_run, project_dir, monkeypatch
):
    """With a header or a body of its own a GET carries anything out to the host: it is
    asked about as if there were no rule, and "always" to it keeps none."""
    net = Net(monkeypatch, {"example.com": (200, "text/plain", "ok")})
    client, model, pid, cid = setup(make_client, project_dir, [
        step(get("https://example.com/a", "h1", headers={"X-Out": "what the project holds"})),
        step(get("https://example.com/b", "h2")),
        step(get("https://example.com/c", "h3", body="what the project holds")),
        step(get("https://example.com/d", "h4", headers={"X-Out": "more"})),
        step(get("https://example.com/e", "h5")), text("done")],
        permission_mode="ask")
    run_id = go(client, cid)["id"]
    snap, asked = asked_of(client, cid)
    assert (asked["method"], asked["headers"]) == ("GET", ["X-Out"])
    assert decide(client, asked, remember=True).json()["status"] == "approved"
    snap, asked = asked_of(client, cid, 2)                  # no rule came of that yes
    assert snap["allowed_web"] == [] and asked["target"] == "https://example.com/b"
    decide(client, asked, remember=True)
    for count, carried in ((3, ([], 22)), (4, (["X-Out"], None))):
        snap, asked = asked_of(client, cid, count)          # asked about, rule or no rule
        assert (asked["headers"], asked["body_chars"]) == carried
        assert decide(client, asked, remember=True).status_code == 200
    snap = wait_run(client, cid, run_id)
    assert [status for status, _ in results(snap, "http_request")] == ["succeeded"] * 5
    assert len(snap["web_requests"]) == 4 and len(net.asked) == 5   # the plain one went unasked
    assert [(rule["kind"], rule["host"]) for rule in snap["allowed_web"]] == [
        ("host", "example.com")]


def test_a_rule_that_is_taken_back_is_asked_about_again(make_client, wait_run, project_dir,
                                                        monkeypatch):
    Net(monkeypatch, {"duckduckgo.com": (200, "text/html", DDG_PAGE)})
    client, model, pid, cid = setup(make_client, project_dir, [
        step(search("one")), text("done"), step(search("two", "s2")), text("done")],
        permission_mode="ask")
    run_id = go(client, cid)["id"]
    snap, asked = asked_of(client, cid)
    decide(client, asked, remember=True)
    snap = wait_run(client, cid, run_id)
    (rule,) = snap["allowed_web"]
    assert (rule["kind"], rule["host"]) == ("search", "")
    del client.headers["Origin"]
    assert client.delete(f"/api/allowed-web/{rule['id']}").status_code == 403
    client.headers["Origin"] = ORIGIN
    assert client.delete(f"/api/allowed-web/{rule['id']}").status_code == 204
    assert client.delete(f"/api/allowed-web/{rule['id']}").status_code == 404
    run_id = go(client, cid)["id"]
    snap, asked = asked_of(client, cid, 2)
    assert asked["target"] == "two" and snap["allowed_web"] == []
    decide(client, asked, "reject")
    wait_run(client, cid, run_id)


def test_a_yes_for_one_host_is_not_a_yes_for_where_it_redirects(make_client, wait_run,
                                                                project_dir, monkeypatch):
    net = Net(monkeypatch)

    async def raw(method, url, headers, body, ip):
        net.asked.append((method, url, ip))
        return app.web.Raw(302, {"location": "https://other.example.org/x"}, b"")

    monkeypatch.setattr(app.web, "raw", raw)
    client, model, pid, cid = setup(make_client, project_dir, [
        step(get("https://example.com/go")), text("done")], permission_mode="ask")
    run_id = go(client, cid)["id"]
    snap, asked = asked_of(client, cid)
    decide(client, asked)
    snap = wait_run(client, cid, run_id)
    ((status, said),) = results(snap, "http_request")
    assert status == "failed" and "redirects to other.example.org" in said
    assert len(net.asked) == 1


def test_a_name_is_not_even_looked_up_before_the_request_may_go_out(make_client, wait_run,
                                                                    project_dir, monkeypatch):
    """Looking a name up already tells somebody outside: a name can carry data."""
    Net(monkeypatch, {"example.com": (200, "text/plain", "ok")})
    looked_up = []
    monkeypatch.setattr(app.web, "resolve", lambda host: looked_up.append(host) or ["93.184.216.34"])
    steps = [step(get("https://data.example.com/a")), text("done")]
    client, model, pid, cid = setup(make_client, project_dir, steps * 3, permission_mode="ask")
    run_id = go(client, cid)["id"]
    snap, asked = asked_of(client, cid)
    assert looked_up == []                       # the card is up, and nothing has left
    decide(client, asked, "reject")
    wait_run(client, cid, run_id)
    assert looked_up == []
    run_id = go(client, cid)["id"]
    snap, asked = asked_of(client, cid, 2)
    decide(client, asked)
    wait_run(client, cid, run_id)
    assert looked_up == ["data.example.com"]
    # with nobody watching: a host the trigger does not name is refused unlooked-up
    made = trigger(client, pid, cid, permissions=leave(hosts=["example.com"]))
    unwatched = run_now(client, made["id"])
    snap = wait_run(client, cid, unwatched, timeout=10)
    (refused,) = [t["result"] for t in snap["tool_calls"] if t["run_id"] == unwatched]
    assert "nobody is here to ask" in refused
    assert looked_up == ["data.example.com"]


def test_no_more_than_so_many_searches_go_out_in_a_minute(make_client, wait_run, project_dir,
                                                          monkeypatch):
    net = Net(monkeypatch, {"duckduckgo.com": (200, "text/html", DDG_PAGE)})
    steps = [step(search(f"q{n}", f"s{n}")) for n in range(11)]
    client, model, pid, cid = setup(make_client, project_dir, [*steps, text("done")])
    snap = wait_run(client, cid, go(client, cid)["id"], timeout=15)
    found = results(snap, "web_search")
    assert [status for status, _ in found] == ["succeeded"] * 10 + ["failed"]
    assert "at most 10 searches a minute" in found[-1][1] and len(net.asked) == 10


def test_a_call_with_arguments_that_make_no_request_fails_before_anybody_is_asked(
    make_client, wait_run, project_dir, monkeypatch
):
    net = Net(monkeypatch)
    bad = [call("http_request", {"method": "FETCH", "url": "https://example.com/"}, "a"),
           call("http_request", {"method": "GET"}, "b"),
           call("http_request", {"method": "GET", "url": "https://example.com/",
                                 "headers": {"X": "a\r\nHost: evil"}}, "c"),
           call("web_search", {}, "d"), call("notify", {"message": "hi"}, "e")]
    client, model, pid, cid = setup(make_client, project_dir, [step(*bad), text("done")],
                                    permission_mode="ask")
    snap = wait_run(client, cid, go(client, cid)["id"])
    assert [t["status"] for t in snap["tool_calls"]] == ["failed"] * 5
    assert snap["web_requests"] == [] and net.asked == []
    # no address of the user's: there was no such tool in this turn
    assert "notify is not available" in snap["tool_calls"][-1]["result"]


def test_a_request_left_waiting_by_a_process_that_ended_is_settled_at_the_next_start(tmp_path):
    from app.agent import recover_interrupted
    from app.db.models import WebRequest
    from app.db.session import make_engine, make_session_factory, upgrade_db
    from tests.test_recovery import seed

    db = tmp_path / "r.db"
    upgrade_db(db)
    factory = make_session_factory(make_engine(db))
    seed(factory, tmp_path)
    with factory() as s:
        s.add(WebRequest(id="w", run_id="r1", agent_id="a", tool_call_id="t1", kind="search",
                         target="python docs"))
        s.commit()
    recover_interrupted(factory)
    with factory() as s:
        asked = s.get(WebRequest, "w")
        assert asked.status == "rejected" and asked.decided_at is not None     # it never went out


# --- the project's settings --------------------------------------------------------------

HOOK = "https://hooks.example.com/services/T000/B000/XYZ-PRIVATE"


def test_where_a_search_and_a_notification_go_is_set_from_the_apps_own_page(client, project_dir):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    shown = client.get("/api/projects").json()[0]
    assert (shown["search_url"], shown["search_order"], shown["has_notify_url"]) == (
        None, "builtin", False)
    for body in ({"search_url": "http://localhost:8888"}, {"notify_url": HOOK},
                 {"search_order": "cli"}):
        assert client.patch(f"/api/projects/{pid}", json=body).status_code == 403
    client.headers["Origin"] = ORIGIN
    made = client.patch(f"/api/projects/{pid}", json={
        "search_url": " http://localhost:8888 ", "notify_url": HOOK, "search_order": "cli"})
    assert made.status_code == 200 and "XYZ-PRIVATE" not in made.text
    shown = made.json()
    assert (shown["search_url"], shown["search_order"], shown["has_notify_url"]) == (
        "http://localhost:8888", "cli", True)
    assert "notify_url" not in shown
    # left out: kept; empty: none
    shown = client.patch(f"/api/projects/{pid}", json={"docker_network": True}).json()
    assert shown["has_notify_url"] is True and shown["search_url"] == "http://localhost:8888"
    shown = client.patch(f"/api/projects/{pid}", json={"notify_url": "", "search_url": ""}).json()
    assert shown["has_notify_url"] is False and shown["search_url"] is None


@pytest.mark.parametrize("body", [
    {"search_url": "ftp://localhost:8888"}, {"search_url": "localhost:8888"},
    {"notify_url": "https://user:SECRET-PW@hooks.example.com/x"}, {"notify_url": "SECRET-PW"},
    {"notify_url": "https://hooks.example.com/SECRET-PW" + "x" * 500}, {"search_order": "fast"},
])
def test_an_address_that_cannot_be_asked_is_refused_without_being_repeated(
    client, project_dir, body
):
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    refused = client.patch(f"/api/projects/{pid}", json=body)
    assert refused.status_code == 422 and "SECRET-PW" not in refused.text
    assert client.get("/api/projects").json()[0]["has_notify_url"] is False


def test_a_notification_that_fails_is_in_no_record_either(make_client, wait_run, project_dir,
                                                          monkeypatch):
    Net(monkeypatch, {"hooks.example.com": ConnectionError(f"could not reach {HOOK}")})
    client, model, pid, cid = setup(make_client, project_dir, [
        step(call("notify", {"message": "done"}, "n")), text("done")],
        project={"notify_url": HOOK})
    snap = wait_run(client, cid, go(client, cid)["id"])
    ((status, said),) = results(snap, "notify")
    assert status == "failed" and "was not sent" in said
    everything = json.dumps(snap) + json.dumps(events(client, cid))
    assert "XYZ-PRIVATE" not in everything and "hooks.example.com" not in everything
    assert "notify" in snap["agents"][0]["tools"]


# --- a turn nobody watches ---------------------------------------------------------------


def leave(**more):
    return {"write": False, "commands": [], "agents": 0, **more}


def test_a_trigger_keeps_what_its_turns_may_do_on_the_web(make_client, project_dir):
    client, model, pid, cid = setup(make_client, project_dir, [])
    # made without a word of the web, or with all of it off: nothing of it is kept or said
    assert trigger(client, pid, cid)["permissions"] == leave()
    assert trigger(client, pid, cid, name="off", permissions=leave(
        web=False, hosts=[], notify=False))["permissions"] == leave()
    made = trigger(client, pid, cid, name="web", permissions=leave(
        web=True, hosts=[" API.Example.com. ", "example.org", "api.example.com"], notify=True))
    assert made["permissions"] == leave(
        web=True, hosts=["api.example.com", "example.org"], notify=True)
    assert made["changes"][0]["detail"].startswith(
        "every 60 minutes; no end; may search the web; may make GET and HEAD requests to: "
        "api.example.com, example.org; may notify; ")
    changed = client.patch(f"/api/triggers/{made['id']}", json={
        "permissions": leave(hosts=["example.org"])})
    assert changed.status_code == 200
    assert (changed.json()["changes"][0]["what"], changed.json()["changes"][0]["detail"]) == (
        "permissions changed", "may make GET and HEAD requests to: example.org")
    # the hosts were picked from one conversation's list: moved to another, it has none
    other = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    moved = client.patch(f"/api/triggers/{made['id']}", json={"conversation_id": other})
    assert moved.status_code == 200 and moved.json()["permissions"] == leave()
    for bad in ("https://example.com", "example.com/path", "example.com:8080", "", "a b", "*"):
        refused = client.post(f"/api/projects/{pid}/triggers", json={
            "name": "bad", "kind": "schedule", "conversation_id": cid, "message": "m",
            "config": {"every_minutes": 60}, "permissions": leave(hosts=[bad])})
        assert refused.status_code == 422 and "bare name" in refused.text, bad
        assert client.patch(f"/api/triggers/{made['id']}", json={
            "permissions": leave(hosts=[bad])}).status_code == 422


def test_an_unattended_turn_notifies_only_where_its_trigger_says_so(make_client, wait_run,
                                                                   project_dir, monkeypatch):
    net = Net(monkeypatch, {"hooks.example.com": (200, "text/plain", "ok")})
    steps = [step(call("notify", {"message": "done"}, "n")), text("done")]
    client, model, pid, cid = setup(make_client, project_dir, steps * 2,
                                    project={"notify_url": HOOK})
    closed = trigger(client, pid, cid)
    snap = wait_run(client, cid, run_now(client, closed["id"]), timeout=10)
    ((status, said),) = results(snap, "notify")
    assert status == "failed" and "nobody is here to ask" in said and net.asked == []
    cid2 = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    opened = trigger(client, pid, cid2, permissions=leave(notify=True))
    snap = wait_run(client, cid2, run_now(client, opened["id"]), timeout=10)
    assert results(snap, "notify")[0][0] == "succeeded" and len(net.asked) == 1
    # the agent was told what this turn may do on the web
    told = model.calls[-1][0]["content"]
    assert "make no web search; make no HTTP request; send the user a notification" in told


def test_an_unattended_request_is_not_carried_to_another_host_by_a_redirect(
    make_client, wait_run, project_dir, monkeypatch
):
    net = Net(monkeypatch)

    async def raw(method, url, headers, body, ip):
        net.asked.append((method, url, ip))
        if "example.com" in url:
            return app.web.Raw(302, {"location": "https://other.example.org/x"}, b"")
        return app.web.Raw(200, {"content-type": "text/plain"}, b"ok")

    monkeypatch.setattr(app.web, "raw", raw)
    client, model, pid, cid = setup(make_client, project_dir, [
        step(get("https://example.com/go")), text("done")])
    made = trigger(client, pid, cid, permissions=leave(hosts=["example.com"]))
    snap = wait_run(client, cid, run_now(client, made["id"]), timeout=10)
    ((status, said),) = results(snap, "http_request")
    assert status == "failed" and "redirects to other.example.org" in said
    assert len(net.asked) == 1 and snap["web_requests"] == []


def test_an_unattended_request_is_a_get_or_a_head_to_exactly_what_the_trigger_names(
    make_client, wait_run, project_dir, monkeypatch
):
    net = Net(monkeypatch, {"example.com": (200, "text/plain", "ok")})
    asked = [
        call("http_request", {"method": "DELETE", "url": "https://example.com/a", "body": "x"},
             "a"),
        call("http_request", {"method": "POST", "url": "https://example.com/a"}, "b"),
        get("http://EXAMPLE.com:9999/b", "c"), get("http://example.com/b", "d"),
        get("https://example.com:8443/b", "e"), get("https://example.com/ok", "f"),
        call("http_request", {"method": "HEAD", "url": "https://example.com:443/ok"}, "g"),
    ]
    client, model, pid, cid = setup(make_client, project_dir, [step(*asked), text("done")] * 2)
    made = trigger(client, pid, cid, permissions=leave(hosts=["example.com"]))
    snap = wait_run(client, cid, run_now(client, made["id"]), timeout=10)
    found = results(snap, "http_request")
    assert [status for status, _ in found] == ["failed"] * 5 + ["succeeded"] * 2
    assert all("nobody is here to ask" in said for _status, said in found[:5])
    assert "make a DELETE request to example.com" in found[0][1]
    assert "make a request to http://example.com:9999" in found[2][1]
    assert [(method, url) for method, url, _ip in net.asked] == [
        ("GET", "https://example.com/ok"), ("HEAD", "https://example.com:443/ok")]
    told = model.calls[-1][0]["content"]
    assert "make GET and HEAD requests to these and no other: example.com" in told
    # another scheme and port is another thing to name
    cid2 = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    other = trigger(client, pid, cid2, name="other",
                    permissions=leave(hosts=["http://example.com:9999"]))
    assert other["changes"][0]["detail"].startswith(
        "every 60 minutes; no end; may make GET and HEAD requests to: http://example.com:9999; ")
    snap = wait_run(client, cid2, run_now(client, other["id"]), timeout=10)
    assert [status for status, _ in results(snap, "http_request")] == (
        ["failed", "failed", "succeeded"] + ["failed"] * 4)


def test_always_is_for_the_scheme_and_port_it_was_given_for(make_client, wait_run, project_dir,
                                                           monkeypatch):
    Net(monkeypatch, {"example.com": (200, "text/plain", "ok")})
    client, model, pid, cid = setup(make_client, project_dir, [
        step(get("https://example.com/a", "h1")), step(get("http://EXAMPLE.com:9999/b", "h2")),
        step(get("http://example.com:9999/c", "h3")), text("done")], permission_mode="ask")
    run_id = go(client, cid)["id"]
    snap, asked = asked_of(client, cid)
    assert asked["host"] == "example.com"
    decide(client, asked, remember=True)
    snap, asked = asked_of(client, cid, 2)          # the rule is not for this one
    assert (asked["target"], asked["host"]) == (
        "http://EXAMPLE.com:9999/b", "http://example.com:9999")
    decide(client, asked, remember=True)
    snap = wait_run(client, cid, run_id)
    assert len(snap["web_requests"]) == 2           # ...and the third went under its own
    assert [rule["host"] for rule in snap["allowed_web"]] == [
        "example.com", "http://example.com:9999"]


def test_what_no_leave_covers_is_refused_before_anybody_is_asked(make_client, wait_run,
                                                                 project_dir, monkeypatch):
    net = Net(monkeypatch)
    bad = [get("http://127.0.0.1:8790/api/projects", "a"), get("http://localhost/", "b"),
           get("http://[fec0::1]/", "c"), search("x" * 301, "d"),
           get("https://example.com/", "e", headers={"Host ": "evil.example.org"})]
    client, model, pid, cid = setup(make_client, project_dir, [step(*bad), text("done")],
                                    permission_mode="ask")
    snap = wait_run(client, cid, go(client, cid)["id"])
    assert [t["status"] for t in snap["tool_calls"]] == ["failed"] * 5
    assert snap["web_requests"] == [] and net.asked == []
    assert "at most 300 characters" in snap["tool_calls"][3]["result"]


def test_a_project_that_asked_for_no_network_reaches_nothing(make_client, wait_run, project_dir,
                                                             monkeypatch):
    net = Net(monkeypatch, {"duckduckgo.com": (200, "text/html", DDG_PAGE),
                            "example.com": (200, "text/plain", "ok")})
    asked = [search(), get("https://example.com/"), call("notify", {"message": "done"}, "n")]
    client, model, pid, cid = setup(
        make_client, project_dir, [step(*asked), text("done")] * 2,
        project={"docker_image": "python:3.12", "exec_location": "docker", "notify_url": HOOK})
    snap = wait_run(client, cid, go(client, cid)["id"])
    assert [t["status"] for t in snap["tool_calls"]] == ["failed"] * 3
    assert all("this project's network access is off" in t["result"] for t in snap["tool_calls"])
    assert net.asked == []
    assert client.patch(f"/api/projects/{pid}", json={"docker_network": True}).status_code == 200
    again = go(client, cid)["id"]
    snap = wait_run(client, cid, again)
    # by its run: the snapshot lists calls run by run, not in the order of the runs
    assert [t["status"] for t in snap["tool_calls"] if t["run_id"] == again] == ["succeeded"] * 3


def test_half_a_character_in_the_arguments_does_not_end_the_turn(make_client, wait_run,
                                                                 project_dir, monkeypatch):
    from app.model_client import ToolCallRequest

    net = Net(monkeypatch, {"duckduckgo.com": (200, "text/html", DDG_PAGE),
                            "example.com": (200, "text/plain", "ok")})
    odd = [ToolCallRequest("s", "web_search", '{"query": "py\\ud800 docs"}'),
           ToolCallRequest("h", "http_request", '{"method": "POST", "url": '
                           '"https://example.com/a", "body": "a\\ud800b", "headers": {"X": "1"}}'),
           ToolCallRequest("u", "http_request", '{"method": "GET", "url": '
                           '"https://example.com/\\udc00"}')]
    client, model, pid, cid = setup(make_client, project_dir, [step(*odd), text("done")],
                                    permission_mode="ask")
    run_id = go(client, cid)["id"]
    for count in (1, 2, 3):
        snap, asked = asked_of(client, cid, count)
        decide(client, asked)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed" and snap["runs"][0]["error"] is None
    assert [t["status"] for t in snap["tool_calls"]] == ["succeeded"] * 3
    # it went out, and is kept, as "?"
    assert [w["target"] for w in snap["web_requests"]] == [
        "py? docs", "https://example.com/a", "https://example.com/?"]
    assert net.asked[1:] == [("POST", "https://example.com/a", "93.184.216.34"),
                             ("GET", "https://example.com/?", "93.184.216.34")]


# --- roles, and a database from before ----------------------------------------------------


def test_a_role_can_be_given_the_web_tools(client):
    roles = {role["name"]: role["tools"] for role in client.get("/api/roles").json()}
    # after the tools that act on the project, before the ones agents work together with
    # (slice 51: the browser's tools between the web's and the team's; 28e: view_image a READ;
    # K-drawio: diagram_image after the file tools and show)
    assert roles["Lead"][8:21] == ["run_command", "web_search", "http_request", *BROWSER,
                                   "notify", "spawn_agent"]
    assert roles["Researcher"][2:15] == ["search", "view_image", "web_search", "http_request", *BROWSER,
                                         "ask_user"]
    for name in ("Planner", "Coder", "Tester", "Reviewer"):
        assert not {"web_search", "http_request", "notify"} & set(roles[name]), name
    made = client.post("/api/roles", json={"name": "Scout", "tools": ["notify", "web_search"]})
    assert made.status_code == 201 and made.json()["tools"] == ["web_search", "notify"]


def test_migration_0025_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0024")
    role = ("INSERT INTO roles (id, name, description, instructions, tools, builtin, "
            "created_by_agent, created_at, updated_at) VALUES (?, ?, '', '', ?, ?, 0, "
            "'2026-10-06 10:00:00', '2026-10-06 10:00:00')")
    with sqlite3.connect(db) as conn:
        conn.execute(role, ("r1", "Lead", '["read_file", "recall"]', 1))
        conn.execute(role, ("r2", "Researcher", '["read_file"]', 1))
        conn.execute(role, ("r3", "Coder", '["read_file"]', 1))
        conn.execute(role, ("r4", "Researcher 2", '["read_file"]', 0))     # the user's own
        conn.execute("INSERT INTO projects (id, name, root_path, created_at, exec_location, "
                     "docker_network) VALUES ('p', 'p', 'C:/p', '2026-10-06 10:00:00', 'host', 0)")
    command.upgrade(cfg, "0025")

    def tools():
        with sqlite3.connect(db) as conn:
            return {name: json.loads(kept) for name, kept in
                    conn.execute("SELECT name, tools FROM roles ORDER BY id")}

    assert tools() == {
        "Lead": ["read_file", "web_search", "http_request", "notify", "recall"],
        "Researcher": ["read_file", "web_search", "http_request"],
        "Coder": ["read_file"], "Researcher 2": ["read_file"]}
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT search_url, search_order, notify_url FROM projects").fetchall() == [
            (None, "builtin", None)]
        assert conn.execute("SELECT count(*) FROM web_requests").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM allowed_web").fetchone() == (0,)
        conn.execute("UPDATE roles SET tools = ? WHERE id = 'r4'", ('["read_file", "notify"]',))
    command.downgrade(cfg, "0024")
    assert tools() == {"Lead": ["read_file", "recall"], "Researcher": ["read_file"],
                       "Coder": ["read_file"], "Researcher 2": ["read_file"]}


# --- slice 20a: what its acceptance set (`test_notify_scenarios`) leaves open ------------

NOTE = call("notify", {"message": "done"}, "n")


def desk(monkeypatch, fails=None):
    shown = []

    def desktop(title, said):
        if fails:
            raise app.web.WebError(fails)
        shown.append((title, said))

    monkeypatch.setattr(app.web, "has_desktop", lambda: True)
    monkeypatch.setattr(app.web, "desktop", desktop)
    return shown


def test_at_most_six_desktop_notifications_a_minute(make_client, wait_run, project_dir,
                                                    monkeypatch):
    shown = desk(monkeypatch)
    Net(monkeypatch)
    notes = [call("notify", {"message": f"note {at}"}, f"n{at}") for at in range(7)]
    client, model, pid, cid = setup(make_client, project_dir, [step(*notes), text("done")],
                                    project={"notify_desktop": True})
    snap = wait_run(client, cid, go(client, cid)["id"])
    assert [status for status, _said in results(snap, "notify")] == ["succeeded"] * 6 + ["failed"]
    assert "at most 6 desktop notifications a minute" in results(snap, "notify")[-1][1]
    assert len(shown) == 6


def test_where_one_of_the_two_fails_it_is_said_which_and_the_other_still_goes(
    make_client, wait_run, project_dir, monkeypatch
):
    desk(monkeypatch, fails="a desktop notification is not available on this system")
    net = Net(monkeypatch, {"hooks.example.com": (200, "text/plain", "ok")})
    client, model, pid, cid = setup(make_client, project_dir, [step(NOTE), text("done")],
                                    project={"notify_desktop": True, "notify_url": HOOK})
    snap = wait_run(client, cid, go(client, cid)["id"])
    ((status, said),) = results(snap, "notify")
    assert status == "failed" and len(net.asked) == 1
    assert said == ("sent to the user's notification address, but: a desktop notification is "
                    "not available on this system")
    assert "XYZ-PRIVATE" not in json.dumps(snap)


def test_with_the_network_off_the_desktop_still_shows_and_the_address_is_refused(
    make_client, wait_run, project_dir, monkeypatch
):
    shown = desk(monkeypatch)
    net = Net(monkeypatch)
    docker = {"docker_image": "python:3.12", "exec_location": "docker", "notify_desktop": True}
    client, model, pid, cid = setup(make_client, project_dir, [step(NOTE), text("done")] * 2,
                                    project=docker)
    snap = wait_run(client, cid, go(client, cid)["id"])
    assert results(snap, "notify") == [("succeeded", "shown on the user's desktop")]
    assert client.patch(f"/api/projects/{pid}", json={"notify_url": HOOK}).status_code == 200
    again = go(client, cid)["id"]
    snap = wait_run(client, cid, again)
    ((status, said),) = [(t["status"], t["result"]) for t in snap["tool_calls"]
                         if t["run_id"] == again]
    assert status == "failed" and said.startswith("shown on the user's desktop, but: not sent")
    assert "this project's network access is off" in said
    assert len(shown) == 2 and net.asked == []


def test_a_trigger_that_may_not_notify_shows_nothing_on_the_desktop(
    make_client, wait_run, project_dir, monkeypatch
):
    shown = desk(monkeypatch)
    Net(monkeypatch)
    client, model, pid, cid = setup(make_client, project_dir, [step(NOTE), text("done")],
                                    project={"notify_desktop": True})
    closed = trigger(client, pid, cid)
    snap = wait_run(client, cid, run_now(client, closed["id"]), timeout=10)
    ((status, said),) = results(snap, "notify")
    assert status == "failed" and "nobody is here to ask" in said and shown == []


def test_the_desktop_and_the_bodys_form_are_set_from_the_apps_own_page(client, project_dir,
                                                                       monkeypatch):
    monkeypatch.setattr(app.web, "has_desktop", lambda: True)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    shown = client.get(f"/api/projects/{pid}").json()
    assert (shown["notify_desktop"], shown["notify_format"]) == (False, "slack")
    for body in ({"notify_desktop": True}, {"notify_format": "text"}):
        assert client.patch(f"/api/projects/{pid}", json=body).status_code == 403
    client.headers["Origin"] = ORIGIN
    shown = client.patch(f"/api/projects/{pid}", json={
        "notify_desktop": True, "notify_format": "discord"}).json()
    assert (shown["notify_desktop"], shown["notify_format"]) == (True, "discord")
    shown = client.patch(f"/api/projects/{pid}", json={"notify_desktop": False}).json()
    assert (shown["notify_desktop"], shown["notify_format"]) == (False, "discord")
    assert client.get("/api/projects/nobody").status_code == 404


def test_a_host_allowed_by_hand_is_kept_as_a_rule_names_it(make_client, project_dir, monkeypatch):
    Net(monkeypatch)
    client, model, pid, cid = setup(make_client, project_dir, [text("done")])
    rules = f"/api/conversations/{cid}/allowed-web"
    kept = [client.post(rules, json={"host": written}).json()["host"] for written in (
        " Example.COM. ", "https://example.com/a/path?q=1", "http://example.com:8080",
        "example.com:8443", "HTTP://Example.com:8080/")]
    assert kept == ["example.com", "example.com", "http://example.com:8080",
                    "https://example.com:8443", "http://example.com:8080"]
    listed = client.get(f"/api/conversations/{cid}").json()["allowed_web"]
    assert [(rule["kind"], rule["host"]) for rule in listed] == [
        ("host", "example.com"), ("host", "http://example.com:8080"),
        ("host", "https://example.com:8443")]
    assert [kind for kind, _payload in events(client, cid)].count("allowed_web.updated") == 3
    for bad in ("", "  ", "ftp://example.com", "https://user:pw@example.com", "a b",
                "*.example.com", "169.254.169.254", "0x7f.1", "http://[fd00::1]:80",
                "app.localhost", "x" * 501):
        assert client.post(rules, json={"host": bad}).status_code == 422, bad
    assert client.post("/api/conversations/nobody/allowed-web",
                       json={"host": "example.com"}).status_code == 404
    assert len(client.get(f"/api/conversations/{cid}").json()["allowed_web"]) == 3


SECRETS = ("K-11-SECRET", "hunter2")
WITH_SECRETS = {"method": "POST", "url": "https://example.com/hook?api_key=K-11-SECRET&q=tea",
                "body": "password=hunter2&note=two+cups"}


def kept_everywhere(client, cid):
    """The snapshot and the events on record, as one text."""
    return json.dumps([client.get(f"/api/conversations/{cid}").json(), events(client, cid)])


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_once_decided_a_secret_is_in_no_record_and_in_no_event(
    make_client, wait_run, project_dir, monkeypatch, decision
):
    net = Net(monkeypatch, {"example.com": (200, "text/plain", "ok")})
    client, model, pid, cid = setup(
        make_client, project_dir, [step(call("http_request", WITH_SECRETS, "p")), text("done")],
        permission_mode="ask")
    run_id = go(client, cid)["id"]
    snap, asked = asked_of(client, cid)
    # while it waits the user is shown what would go - the address, and the body
    assert "api_key=K-11-SECRET" in asked["target"]
    assert "password=hunter2" in snap["tool_calls"][0]["arguments"]
    client.post(f"/api/web-requests/{asked['id']}/{decision}", json={"remember": False})
    snap = wait_run(client, cid, run_id)
    assert results(snap, "http_request")[0][0] == (
        "succeeded" if decision == "approve" else "denied")
    assert [url for _method, url, _ip in net.asked] == (
        [WITH_SECRETS["url"]] if decision == "approve" else [])   # what went is as written
    kept = kept_everywhere(client, cid)
    for secret in SECRETS:
        assert secret not in kept, secret
    assert "api_key=***&q=tea" in kept and "password=***&note=two+cups" in kept
    # and so in what a model is given of the turn afterwards
    assert not any(secret in json.dumps(model.calls[-1]) for secret in SECRETS)
    assert "api_key=***" in json.dumps(model.calls[-1])


def test_a_request_nobody_was_asked_about_keeps_no_secret_either(make_client, wait_run,
                                                                 project_dir, monkeypatch):
    Net(monkeypatch, {"example.com": (200, "text/plain", "ok")})
    # (a bare GET: the one request Full auto does not ask about, K-fullauto-sorma)
    unasked = {"method": "GET", "url": WITH_SECRETS["url"]}
    inside = {**unasked, "url": "http://127.0.0.1/hook?api_key=K-11-SECRET"}
    client, model, pid, cid = setup(make_client, project_dir, [
        step(call("http_request", unasked, "p"), call("http_request", inside, "q")),
        text("done")])
    snap = wait_run(client, cid, go(client, cid)["id"])
    assert [status for status, _said in results(snap, "http_request")] == ["succeeded", "failed"]
    assert "api_key=***&q=tea: HTTP 200" in results(snap, "http_request")[0][1]
    kept = kept_everywhere(client, cid)
    assert not any(secret in kept for secret in SECRETS)


def test_a_request_stopped_while_it_waits_keeps_no_secret(make_client, wait_run, project_dir,
                                                          monkeypatch):
    Net(monkeypatch)
    client, model, pid, cid = setup(
        make_client, project_dir, [step(call("http_request", WITH_SECRETS, "p")), text("done")],
        permission_mode="ask")
    run_id = go(client, cid)["id"]
    asked_of(client, cid)
    client.post(f"/api/runs/{run_id}/cancel")
    wait_run(client, cid, run_id)
    kept = kept_everywhere(client, cid)
    assert not any(secret in kept for secret in SECRETS) and "api_key=***" in kept


def test_a_request_left_by_a_process_that_ended_keeps_no_secret(tmp_path):
    from app.agent import recover_interrupted
    from app.db.models import ToolCall, WebRequest
    from app.db.session import make_engine, make_session_factory, upgrade_db
    from tests.test_recovery import seed

    db = tmp_path / "r.db"
    upgrade_db(db)
    factory = make_session_factory(make_engine(db))
    seed(factory, tmp_path)
    with factory() as s:
        asked = s.get_one(ToolCall, "t2")
        asked.name, asked.arguments = "http_request", json.dumps(WITH_SECRETS)
        s.add(WebRequest(id="w", run_id="r1", agent_id="a", tool_call_id="t2", kind="http",
                         method="POST", target=WITH_SECRETS["url"], host="example.com"))
        s.add(Event(conversation_id="c", run_id="r1", type="tool_call.created",
                    payload={"id": "t2", "arguments": json.dumps(WITH_SECRETS)}))
        s.commit()
    recover_interrupted(factory)
    with factory() as s:
        kept = json.dumps([s.get_one(ToolCall, "t2").arguments, s.get_one(WebRequest, "w").target,
                           [row.payload for row in s.scalars(select(Event))]])
    assert not any(secret in kept for secret in SECRETS) and "api_key=***" in kept


def test_migration_0026_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0025")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO projects (id, name, root_path, created_at, exec_location, "
                     "docker_network, search_order) VALUES ('p', 'p', 'C:/p', "
                     "'2026-10-06 10:00:00', 'host', 0, 'builtin')")
    command.upgrade(cfg, "0026")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT notify_format, notify_desktop FROM projects").fetchall() == [
            ("slack", 0)]
    command.downgrade(cfg, "0025")
    with sqlite3.connect(db) as conn:
        assert "notify_desktop" not in [row[1] for row in conn.execute(
            "PRAGMA table_info(projects)")]
