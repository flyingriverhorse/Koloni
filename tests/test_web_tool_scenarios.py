"""Agent tools' acceptance set (slice 18c): web search, an HTTP request, a notification.

Written before the code. Three tools of KOLONİ's own, for any agent that works with them.
What goes out of this machine can be asked about; nothing reaches this machine or its
network; a search that cannot be made says so and makes nothing up; where a notification
goes is the user's, not the agent's; and a secret is in no record.

No test touches the real network: `app.web.raw` (the one place a request leaves from),
`app.web.resolve` (name to addresses) and `app.web.cli_search` are stood in for.
"""

import json

import pytest

pytest.importorskip("app.web")  # written before the code: skipped until it exists

import app.web  # noqa: E402, I001
from tests.test_chat_flow import text  # noqa: E402
from tests.test_parallel import until  # noqa: E402
from tests.test_spawn import call, step  # noqa: E402
from tests.test_trigger_scenarios import run_now, trigger  # noqa: E402

ORIGIN = "http://127.0.0.1:8790"
PUBLIC = "93.184.216.34"
SEARX = "http://searx.test:8888"
DDG_PAGE = (
    '<div class="result"><a class="result__a" href="https://docs.python.org/3/">Python docs</a>'
    '<a class="result__snippet">The official documentation.</a></div>'
)


def search(query="python docs", id="s"):
    return call("web_search", {"query": query}, id)


def get(url, id="h", **more):
    return call("http_request", {"method": "GET", "url": url, **more}, id)


class Net:
    """What the outside answers, and a list of what was asked of it."""

    def __init__(self, monkeypatch, answers=None, names=None, cli=None):
        self.asked, self.answers = [], answers or {}
        self.names = {"searx.test": [PUBLIC], "example.com": [PUBLIC], **(names or {})}

        async def raw(method, url, headers, body, ip):
            self.asked.append((method, url, ip))
            for part, answer in self.answers.items():
                if part in url:
                    if isinstance(answer, Exception):
                        raise answer
                    status, kind, said = answer
                    data = said if isinstance(said, bytes) else said.encode()
                    return app.web.Raw(status, {"content-type": kind}, data)
            return app.web.Raw(404, {"content-type": "text/plain"}, b"nothing here")

        async def cli_search(query):
            self.asked.append(("CLI", query, None))
            return cli

        monkeypatch.setattr(app.web, "raw", raw)
        monkeypatch.setattr(app.web, "resolve", lambda host: self.names.get(host, [PUBLIC]))
        monkeypatch.setattr(app.web, "cli_search", cli_search)


def setup(make_client, project_dir, steps, project=None, **conversation):
    client, model = make_client(steps)
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    if project:
        assert client.patch(f"/api/projects/{pid}", json=project).status_code == 200
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    settings = {"permission_mode": "full_auto", **conversation}
    assert client.patch(f"/api/conversations/{cid}", json=settings).status_code == 200
    return client, model, pid, cid


def go(client, cid):
    return client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()["run"]


def results(snap, name):
    return [(t["status"], t["result"] or "") for t in snap["tool_calls"] if t["name"] == name]


def test_a_search_asks_the_users_own_searxng_first(make_client, wait_run, project_dir,
                                                   monkeypatch):
    found = json.dumps({"results": [{"title": "Python docs", "url": "https://docs.python.org/3/",
                                     "content": "The official documentation."}]})
    net = Net(monkeypatch, {"searx.test": (200, "application/json", found)})
    client, model, pid, cid = setup(make_client, project_dir, [step(search()), text("done")],
                                    project={"search_url": SEARX})
    snap = wait_run(client, cid, go(client, cid)["id"])
    ((status, said),) = results(snap, "web_search")
    assert status == "succeeded" and "https://docs.python.org/3/" in said
    assert "official documentation" in said and "SearXNG did not answer" not in said
    assert all("searx.test" in url for _method, url, _ip in net.asked)


def test_a_searxng_that_does_not_answer_is_said_and_the_built_in_search_is_used(
    make_client, wait_run, project_dir, monkeypatch
):
    net = Net(monkeypatch, {"searx.test": ConnectionError("refused"),
                            "duckduckgo.com": (200, "text/html", DDG_PAGE)})
    client, model, pid, cid = setup(make_client, project_dir, [step(search()), text("done")],
                                    project={"search_url": SEARX})
    snap = wait_run(client, cid, go(client, cid)["id"])
    ((status, said),) = results(snap, "web_search")
    assert status == "succeeded" and "https://docs.python.org/3/" in said
    assert "SearXNG did not answer" in said
    assert ("CLI", "python docs", None) not in net.asked


def test_a_search_that_cannot_be_made_says_so_and_makes_nothing_up(
    make_client, wait_run, project_dir, monkeypatch
):
    net = Net(monkeypatch, {"duckduckgo.com": (202, "text/html", "<html>are you a robot</html>")},
              cli=None)
    client, model, pid, cid = setup(make_client, project_dir, [step(search()), text("done")])
    snap = wait_run(client, cid, go(client, cid)["id"])
    ((status, said),) = results(snap, "web_search")
    assert status == "failed" and "search could not be made" in said and "docs.python.org" not in said
    assert ("CLI", "python docs", None) in net.asked           # every way was tried


def test_where_the_user_is_asked_a_search_waits_for_a_yes_and_always_is_remembered(
    make_client, wait_run, project_dir, monkeypatch
):
    net = Net(monkeypatch, {"duckduckgo.com": (200, "text/html", DDG_PAGE)})
    client, model, pid, cid = setup(
        make_client, project_dir,
        [step(search("first")), step(search("second", "s2")), text("done")],
        permission_mode="ask")
    run_id = go(client, cid)["id"]
    snap = until(client, cid, lambda s: [w["status"] for w in s["web_requests"]] == ["proposed"])
    (asked,) = snap["web_requests"]
    assert (asked["kind"], asked["target"]) == ("search", "first")
    assert snap["runs"][0]["status"] == "waiting_approval" and net.asked == []
    assert client.post(f"/api/web-requests/{asked['id']}/approve",
                       json={"remember": True}).status_code == 200
    snap = wait_run(client, cid, run_id)
    assert [status for status, _ in results(snap, "web_search")] == ["succeeded", "succeeded"]
    assert len(snap["web_requests"]) == 1                       # the second was not asked


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8790/api/projects",       # KOLONİ's own API
    "http://localhost:8790/api/projects",
    "http://[::1]/",
    "http://10.0.0.5/",
    "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/",
    "http://inside.example.com/",               # a public name that leads inside
    "file:///C:/Windows/win.ini",
    "http://user:pass@example.com/",
])
def test_nothing_reaches_this_machine_or_its_network_at_any_level(
    make_client, wait_run, project_dir, monkeypatch, url
):
    net = Net(monkeypatch, names={"localhost": ["127.0.0.1"], "inside.example.com": ["10.1.2.3"]})
    client, model, pid, cid = setup(make_client, project_dir, [step(get(url)), text("done")])
    snap = wait_run(client, cid, go(client, cid)["id"])
    ((status, said),) = results(snap, "http_request")
    assert status == "failed" and "not reachable from here" in said
    assert net.asked == [] and snap["web_requests"] == []


def test_a_redirect_that_leads_inside_is_not_followed(make_client, wait_run, project_dir,
                                                      monkeypatch):
    net = Net(monkeypatch)

    async def raw(method, url, headers, body, ip):
        net.asked.append((method, url, ip))
        return app.web.Raw(302, {"location": "http://127.0.0.1:8790/api/projects"}, b"")

    monkeypatch.setattr(app.web, "raw", raw)
    client, model, pid, cid = setup(make_client, project_dir,
                                    [step(get("https://example.com/go")), text("done")])
    snap = wait_run(client, cid, go(client, cid)["id"])
    ((status, said),) = results(snap, "http_request")
    assert status == "failed" and "not reachable from here" in said
    # the one request that left went to the address the name was checked as
    assert net.asked == [("GET", "https://example.com/go", PUBLIC)]


def test_a_request_gives_the_page_as_text_cut_where_it_is_too_long(
    make_client, wait_run, project_dir, monkeypatch
):
    page = "<html><script>x()</script><body><h1>Title</h1>" + "word " * 100_000 + "</body></html>"
    Net(monkeypatch, {"example.com": (200, "text/html", page)})
    client, model, pid, cid = setup(make_client, project_dir,
                                    [step(get("https://example.com/long")), text("done")])
    wait_run(client, cid, go(client, cid)["id"])
    said = model.calls[-1][-1]["content"]                       # what the agent was given
    assert "Title" in said and "x()" not in said and "<h1>" not in said
    assert "cut at" in said and len(said) < 210_000


def test_a_secret_in_a_header_is_in_no_record(make_client, wait_run, project_dir, monkeypatch):
    Net(monkeypatch, {"example.com": (200, "text/plain", "ok")})
    client, model, pid, cid = setup(make_client, project_dir, [
        step(get("https://example.com/api", headers={"Authorization": "Bearer TOP-SECRET-1"})),
        text("done")], permission_mode="ask")
    run_id = go(client, cid)["id"]
    snap = until(client, cid, lambda s: [w["status"] for w in s["web_requests"]] == ["proposed"])
    assert snap["web_requests"][0]["host"] == "example.com"
    assert client.post(f"/api/web-requests/{snap['web_requests'][0]['id']}/approve",
                       json={"remember": False}).status_code == 200
    snap = wait_run(client, cid, run_id)
    assert results(snap, "http_request")[0][0] == "succeeded"
    assert "TOP-SECRET-1" not in json.dumps(snap)


def test_a_turn_nobody_watches_searches_and_asks_only_what_its_trigger_allows(
    make_client, wait_run, project_dir, monkeypatch
):
    net = Net(monkeypatch, {"duckduckgo.com": (200, "text/html", DDG_PAGE),
                            "example.com": (200, "text/plain", "ok")})
    steps = [step(search()), step(get("https://example.com/a", "h1")),
             step(get("https://other.example.org/b", "h2")), text("done")]
    client, model, pid, cid = setup(make_client, project_dir, steps * 2)
    closed = trigger(client, pid, cid)
    snap = wait_run(client, cid, run_now(client, closed["id"]), timeout=10)
    assert [status for status, _ in results(snap, "web_search")] == ["failed"]
    assert all("nobody is here to ask" in said for _status, said in results(snap, "http_request"))
    assert net.asked == []
    cid2 = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    opened = trigger(client, pid, cid2, permissions={
        "write": False, "commands": [], "agents": 0, "web": True, "hosts": ["example.com"],
        "notify": False})
    snap = wait_run(client, cid2, run_now(client, opened["id"]), timeout=10)
    assert [status for status, _ in results(snap, "web_search")] == ["succeeded"]
    assert [status for status, _ in results(snap, "http_request")] == ["succeeded", "failed"]
    assert not [w for w in snap["web_requests"] if w["status"] == "proposed"]


def test_where_a_notification_goes_is_the_users_and_is_in_no_record(
    make_client, wait_run, project_dir, monkeypatch
):
    hook = "https://hooks.example.com/services/T000/B000/XYZ-PRIVATE"
    net = Net(monkeypatch, {"hooks.example.com": (200, "text/plain", "ok")})
    client, model, pid, cid = setup(make_client, project_dir, [
        step(call("notify", {"message": "the tests pass", "url": "https://evil.example.org/x"},
                  "n")), text("done")], project={"notify_url": hook})
    shown = client.get("/api/projects").json()[0]
    assert shown["has_notify_url"] is True and "notify_url" not in shown
    snap = wait_run(client, cid, go(client, cid)["id"])
    assert results(snap, "notify")[0][0] == "succeeded"
    assert [url for _method, url, _ip in net.asked] == [hook]   # not where the agent said
    assert "XYZ-PRIVATE" not in json.dumps(snap)


def test_without_an_address_of_the_users_there_is_no_notify_tool(
    make_client, wait_run, project_dir, monkeypatch
):
    Net(monkeypatch)
    client, model, pid, cid = setup(make_client, project_dir, [text("done")])
    snap = wait_run(client, cid, go(client, cid)["id"])
    offered = set(snap["agents"][0]["tools"])
    assert {"web_search", "http_request"} <= offered and "notify" not in offered
