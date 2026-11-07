"""K-tarayici-disari A1: the agent's browser opens the sites the user allows - a project's list
(`allowed_web` kind "page"), each site with its Ask first mark; one not on it, or marked, on the
web card at every level; never in a turn nobody watches. A site is faked by a name of a test's
own (site.test) for a server on loopback: the stand-in browser fetches it there, the real Chrome
is told so by --host-resolver-rules. Nothing reaches the network."""

import asyncio
import contextlib
import functools
import http.server
import os
import socket
import threading
import time

import pytest

import app.web
from app import browser
from app.db.models import AllowedWeb, BacklogTask
from app.workspace import Workspace
from tests.test_browser import FAKE, REAL, _calls, closed_server  # noqa: F401
from tests.test_chat_flow import text
from tests.test_parallel import until
from tests.test_spawn import call, step
from tests.test_trigger_scenarios import run_now, trigger

ORIGIN = {"Origin": "http://127.0.0.1:8790"}
PAGE = (b"<!doctype html><title>Site</title><h1>SITE-MARKER</h1>"
        b"<button id=b>Start</button>")


@pytest.fixture
def site():
    """A site's server on loopback; what it was asked for."""
    asked: list[str] = []

    class Site(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            asked.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(PAGE)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1], asked
    server.shutdown()


# What a test's names stand for out there (`web.check`): nothing is looked up for real.
PUBLIC, INSIDE_IP = "93.184.216.34", "192.168.1.1"


@pytest.fixture(autouse=True)
def names(monkeypatch):
    monkeypatch.setattr(app.web, "resolve",
                        lambda host: [INSIDE_IP if host.startswith("lan.") else PUBLIC])


# --- the rule ------------------------------------------------------------------------------


def test_a_site_is_told_from_this_machine_and_its_network():
    assert browser.site_of("http://127.0.0.1:5173/") is None
    assert browser.site_of("http://localhost:5173/") is None
    assert browser.site_of("docs/index.html") is None
    assert browser.site_of("file:///C:/x.html") is None
    assert browser.site_of(" https://Example.COM/docs ") == "example.com"
    assert browser.site_of("http://example.com:8080/") == "example.com"
    for inside in ("http://192.168.1.5/", "http://10.0.0.1/", "http://2130706433/",
                   "https://localhost./", "http://app.localhost/", "http://[fd00::1]/",
                   "http://169.254.169.254/"):
        with pytest.raises(browser.BrowserError, match="this machine or its network"):
            browser.site_of(inside)
    # A name of one word, or a home network's (`web.check` judges the rest by its address).
    for inside in ("http://printer/", "https://router.lan/", "http://foo.internal/",
                   "http://nas.home.arpa/", "https://x.corp/", "http://box.local/"):
        with pytest.raises(browser.BrowserError, match="this machine or its network"):
            browser.site_of(inside)
    for odd in ("https://user@example.com/", "https://example.com%2f@x/",
                "https://example.com\\@x/"):
        with pytest.raises(browser.BrowserError, match="with \\\\, @ or %"):
            browser.site_of(odd)


def test_what_a_sites_page_loads_is_judged():
    sites, closed = frozenset({"example.com"}), {8790}
    # The page itself: only an allowed site, on any port but a closed one.
    browser.outside("https://example.com/a", sites, closed, main=True)
    browser.outside("http://example.com:8080/a", sites, closed, main=True)
    refused = {
        ("https://other.org/", True): "not a site the user allowed",
        ("https://www.example.com/", True): "not a site the user allowed",
        ("http://example.com:8790/", True): "a closed port",
        ("http://127.0.0.1:5173/", True): "does not reach this machine",
        # What the page loads besides: https from any host out on the internet.
        ("http://cdn.example.net/x.js", False): "only https",
        ("http://example.com/x.css", False): "only https",
        ("https://10.0.0.1/x", False): "this machine or its network",
        ("https://127.0.0.1:5173/x", False): "does not reach this machine",
        ("http://localhost:5173/x", False): "does not reach this machine",
        ("https://cdn.example.net:8790/x", False): "a closed port",
        ("file:///C:/Windows/win.ini", False): "does not reach this machine or a file",
    }
    for (url, main), why in refused.items():
        with pytest.raises(browser.BrowserError, match=why):
            browser.outside(url, sites, closed, main=main)
    browser.outside("https://cdn.example.net/x.js", sites, closed, main=False)


@pytest.mark.anyio
async def test_the_judge_of_a_browser_that_went_out(tmp_path):
    """The page's own frame (its target's id) only to an allowed site; a frame in it and what
    it loads as any other load; the refusals said in the next result."""
    one = browser.Browser(tmp_path, "a")
    one.away, one._page, one.sites, one.closed = True, "t1", frozenset({"site.test"}), {9}
    one._project = Workspace(str(tmp_path))
    told: list[str] = []

    async def tell(method, params, session):
        told.append(method)

    one._tell = tell  # type: ignore[method-assign]

    async def judge(url, kind="Document", frame="t1", method="GET"):
        await one._judge({"params": {"requestId": "r", "resourceType": kind, "frameId": frame,
                                     "request": {"url": url, "method": method}}})
        return told.pop()

    assert await judge("http://site.test:5000/") == "Fetch.continueRequest"
    # (an allowed name that stands for an inside address: refused as the page itself)
    one.sites = frozenset({"site.test", "lan.test"})
    assert await judge("http://lan.test:5000/") == "Fetch.failRequest"
    assert "lan.test is on this machine or its network" in one.refused()
    assert await judge("https://other.test/") == "Fetch.failRequest"
    assert await judge("https://other.test/", frame="f2") == "Fetch.continueRequest"
    assert await judge("http://other.test/", frame="f2") == "Fetch.failRequest"
    assert await judge("http://127.0.0.1:5000/x", kind="Fetch", frame="f2") == "Fetch.failRequest"
    assert await judge("data:text/plain,x", kind="Image") == "Fetch.continueRequest"
    said = one.refused()
    assert "other.test is not a site the user allowed" in said
    assert "http://other.test/: only https" in said and "127.0.0.1:5000" in said
    # A2: a form the page or a frame of it sends goes once, right after a yes - never else.
    assert await judge("http://site.test:5000/in", method="POST") == "Fetch.failRequest"
    assert await judge("https://pay.test/in", frame="f2", method="POST") == "Fetch.failRequest"
    assert "tried to send a form" in one.refused()
    one.posting = time.monotonic() + 10
    # (a yes is for an action on the page itself: a frame's form still is not sent)
    assert await judge("https://pay.test/in", frame="f2", method="POST") == "Fetch.failRequest"
    assert await judge("http://site.test:5000/in", method="POST") == "Fetch.continueRequest"
    assert await judge("http://site.test:5000/in", method="POST") == "Fetch.failRequest"
    # (a page's own fetch POST is not a form: not asked)
    assert await judge("https://api.test/x", kind="XHR", frame="t1", method="POST")         == "Fetch.continueRequest"


def test_what_waits_for_the_users_yes_on_a_sites_page():
    def seen(**over):
        return {"host": "site.test", "words": "", "password": False, "posts": False,
                "frame": False, **over}

    assert browser.stop(None, "click")[0] == "sign"  # (what cannot be read waits)
    assert browser.stop(seen(frame=True), "type")[0] == "sign"
    assert browser.stop(seen(password=True), "type") == (
        "password", "type into a password field", "site.test")
    assert browser.stop(seen(words="Sign in", editable=True), "type") is None
    # (what has the focus and cannot be seen into - a closed shadow root's host - waits)
    assert browser.stop(seen(editable=True, hidden=True), "type")[0] == "field"
    assert browser.stop(seen(), "type")[0] == "field"
    assert browser.stop(seen(words="Pay"), "click") == (
        "sign", "click a button or link - the page's own words on it: 'Pay'", "site.test")
    assert browser.keys_held(seen(hidden=True)) and not browser.keys_held(seen())
    assert browser.stop(seen(posts=True, words="Go"), "click")[0] == "form"
    assert browser.stop(seen(posts=True), "press")[0] == "form"
    for words in ("Sign in", "LOG IN", "Pay now", "Checkout", "Buy", "Subscribe",
                  "Place order", "Delete account", "Satın al", "Giriş yap"):
        assert browser.stop(seen(words=words), "click")[0] == "sign", words
    for words in ("Display", "Payload", "Docs", "Start", "Logo"):
        assert browser.stop(seen(words=words), "click") is None, words


def test_screenshots_older_than_a_week_are_swept(tmp_path):
    (tmp_path / "shots").mkdir()
    for name in ("old.png", "new.png"):
        (tmp_path / "shots" / name).write_bytes(b"x")
    week = time.time() - browser.SHOTS_KEPT - 60
    os.utime(tmp_path / "shots" / "old.png", (week, week))
    browser.sweep(tmp_path, keep=set())
    assert [p.name for p in (tmp_path / "shots").iterdir()] == ["new.png"]


# --- the card, end to end on the stand-in browser -------------------------------------------


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("KOLONI_BROWSER_FAKE", FAKE)


def _setup(make_client, project_dir, steps, mode):
    client, _model = make_client(steps)
    client.headers.update(ORIGIN)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json={"permission_mode": mode}).status_code \
        == 200
    return client, pid, cid


def _go(client, cid):
    return client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()[
        "run"]["id"]


def _asked(client, cid):
    snap = until(client, cid, lambda s: any(w["status"] == "proposed" for w in s["web_requests"]))
    return next(w for w in snap["web_requests"] if w["status"] == "proposed")


def _allow(client, cid, host, ask_first=False):
    made = client.post(f"/api/conversations/{cid}/allowed-web",
                       json={"host": host, "kind": "page"})
    assert made.status_code == 200, made.text
    rule = made.json()
    if ask_first:
        rule = client.patch(f"/api/allowed-web/{rule['id']}", json={"ask_first": True}).json()
    return rule


def test_a_site_not_on_the_list_is_asked_and_allow_this_site_keeps_it_for_the_project(
        fake, site, make_client, wait_run, project_dir):
    port, asked = site
    url = f"http://site.test:{port}/?token=abc"
    open_it = step(call("browser_open", {"url": url}, "b1"))
    client, pid, cid = _setup(make_client, project_dir, [
        open_it, step(call("browser_read", {}, "b2")), text("done"),
        step(call("browser_open", {"url": f"http://site.test:{port}/two"}, "b3")), text("done")],
        "ask")
    run_id = _go(client, cid)
    card = _asked(client, cid)
    # Below Full auto a site not on the list is the user's to say.
    assert (card["kind"], card["host"], card["method"]) == ("page", "site.test", "GET")
    assert asked == []  # (nothing opened before the yes)
    assert client.post(f"/api/web-requests/{card['id']}/approve",
                       json={"remember": True}).status_code == 200
    snap = wait_run(client, cid, run_id)
    made = _calls(client, cid)
    assert made["browser_open"]["status"] == "succeeded", made["browser_open"]["result"]
    assert made["browser_open"]["result"].startswith(f"opened {url} - Site")
    assert "SITE-MARKER" in made["browser_read"]["result"]
    (rule,) = snap["allowed_web"]
    assert (rule["kind"], rule["host"], rule["ask_first"]) == ("page", "site.test", False)
    # (the address on the card's record is kept as a request's is)
    assert "abc" not in snap["web_requests"][0]["target"]
    # Another chat of the project opens it unasked: the site is the project's.
    cid2 = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert [r["host"] for r in client.get(f"/api/conversations/{cid2}").json()["allowed_web"]] \
        == ["site.test"]
    client.patch(f"/api/conversations/{cid2}", json={"permission_mode": "ask"})
    snap = wait_run(client, cid2, _go(client, cid2))
    assert snap["web_requests"] == []
    assert _calls(client, cid2)["browser_open"]["status"] == "succeeded"


def test_a_site_marked_ask_first_is_asked_at_full_auto_and_this_time_keeps_no_rule(
        fake, site, make_client, wait_run, project_dir):
    port, _asked_paths = site
    client, _pid, cid = _setup(make_client, project_dir, [
        step(call("browser_open", {"url": f"http://site.test:{port}/"}, "b1")), text("done")],
        "full_auto")
    rule = _allow(client, cid, "SITE.test", ask_first=True)
    assert (rule["host"], rule["ask_first"]) == ("site.test", True)
    run_id = _go(client, cid)
    card = _asked(client, cid)
    assert client.post(f"/api/web-requests/{card['id']}/approve",
                       json={"remember": False}).status_code == 200
    snap = wait_run(client, cid, run_id)
    assert _calls(client, cid)["browser_open"]["status"] == "succeeded"
    assert [(r["host"], r["ask_first"]) for r in snap["allowed_web"]] == [("site.test", True)]


def test_an_allowed_site_opens_unasked_below_full_auto_and_a_no_is_on_record_as_denied(
        fake, site, make_client, wait_run, project_dir):
    port, asked = site
    client, _pid, cid = _setup(make_client, project_dir, [
        step(call("browser_open", {"url": f"http://site.test:{port}/"}, "b1")),
        step(call("browser_open", {"url": f"http://other.test:{port}/"}, "b2")), text("done")],
        "ask")
    _allow(client, cid, "site.test")
    run_id = _go(client, cid)
    card = _asked(client, cid)
    assert card["host"] == "other.test"
    assert client.post(f"/api/web-requests/{card['id']}/reject").status_code == 200
    wait_run(client, cid, run_id)
    opened = [t for t in client.get(f"/api/conversations/{cid}").json()["tool_calls"]
              if t["name"] == "browser_open"]
    assert [t["status"] for t in opened] == ["succeeded", "denied"]
    assert "declined this site" in opened[1]["result"]
    assert asked == ["/"]  # (other.test was never asked for)


def test_a_turn_nobody_watches_opens_no_site_and_asks_nothing(
        fake, site, make_client, wait_run, project_dir):
    port, asked = site
    opens = [step(call("browser_open", {"url": f"http://site.test:{port}/"}, "b1")),
             text("done")]
    client, pid, cid = _setup(make_client, project_dir, opens * 2, "full_auto")
    _allow(client, cid, "site.test")
    made = trigger(client, pid, cid)
    snap = wait_run(client, cid, run_now(client, made["id"]), timeout=15)
    (opened,) = [t for t in snap["tool_calls"] if t["name"] == "browser_open"]
    assert opened["status"] == "denied" and "nobody is watching this turn" in opened["result"]
    assert snap["web_requests"] == [] and asked == []
    # A backlog task's chat: the same, though its turn is an ordinary one.
    cid2 = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    with client.app.state.session_factory() as session:
        session.add(BacklogTask(project_id=pid, title="t", status="doing", position=0, created_by="user",
                                conversation_id=cid2))
        session.commit()
    snap = wait_run(client, cid2, _go(client, cid2))
    (opened,) = [t for t in snap["tool_calls"] if t["name"] == "browser_open"]
    assert opened["status"] == "denied" and asked == []


def test_a_project_without_a_network_opens_no_site_but_its_previews(
        fake, site, make_client, wait_run, project_dir):
    port, asked = site
    client, pid, cid = _setup(make_client, project_dir, [
        step(call("browser_open", {"url": f"http://site.test:{port}/"}, "b1")),
        step(call("browser_open", {"url": f"http://127.0.0.1:{port}/"}, "b2")), text("done")],
        "full_auto")
    assert client.patch(f"/api/projects/{pid}", json={
        "docker_image": "python:3.12", "exec_location": "docker"}).status_code == 200
    _allow(client, cid, "site.test")
    snap = wait_run(client, cid, _go(client, cid))
    opened = [t for t in snap["tool_calls"] if t["name"] == "browser_open"]
    assert opened[0]["status"] == "failed" and "network access is off" in opened[0]["result"]
    assert opened[1]["status"] == "succeeded"  # (a preview is this machine's)
    assert snap["web_requests"] == [] and asked == ["/"]


def test_at_full_auto_a_site_not_on_the_list_opens_unasked_and_is_not_listed(
        fake, site, make_client, wait_run, project_dir):
    port, asked = site
    client, _pid, cid = _setup(make_client, project_dir, [
        step(call("browser_open", {"url": f"http://site.test:{port}/"}, "b1")), text("done")],
        "full_auto")
    snap = wait_run(client, cid, _go(client, cid))
    assert _calls(client, cid)["browser_open"]["status"] == "succeeded"
    assert snap["web_requests"] == [] and snap["allowed_web"] == [] and asked == ["/"]


LOGIN = ('<title>Login</title><button>Start</button><form method="post" action="/in">'
         '<input id="user"><input id="pw" type="password"><button>Sign in</button></form>')


def test_a_password_and_a_form_on_a_site_wait_for_a_yes_at_full_auto(
        fake, make_client, wait_run, project_dir, tmp_path):
    folder = tmp_path / "login"
    folder.mkdir()
    (folder / "index.html").write_text(LOGIN, encoding="utf-8")

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(Quiet, directory=str(folder)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client, _pid, cid = _setup(make_client, project_dir, [
            step(call("browser_open", {"url": f"http://site.test:{server.server_address[1]}/"},
                      "b1")),
            step(call("browser_type", {"selector": "#user", "text": "murat"}, "b2")),
            step(call("browser_type", {"selector": "#pw", "text": "hunter2-SECRET"}, "b3")),
            step(call("browser_click", {"text": "Start"}, "b4")),
            step(call("browser_click", {"text": "Sign in"}, "b5")),
            step(call("browser_key", {"key": "x"}, "b6")),
            step(call("browser_key", {"key": "Tab"}, "b7")), text("done")],
            "full_auto")
        run_id = _go(client, cid)
        card = _asked(client, cid)
        assert (card["kind"], card["target"], card["host"]) == (
            "password", "type into a password field", "site.test")
        assert client.post(f"/api/web-requests/{card['id']}/approve",
                           json={"remember": True}).status_code == 200
        card = _asked(client, cid)
        assert (card["kind"], card["host"]) == ("form", "site.test")
        assert "Sign in" in card["target"]
        assert client.post(f"/api/web-requests/{card['id']}/reject").status_code == 200
        snap = wait_run(client, cid, run_id)
    finally:
        server.shutdown()
    done = [(t["name"], t["status"]) for t in snap["tool_calls"]]
    assert done == [("browser_open", "succeeded"), ("browser_type", "succeeded"),
                    ("browser_type", "succeeded"), ("browser_click", "succeeded"),
                    ("browser_click", "denied"), ("browser_key", "failed"),
                    ("browser_key", "succeeded")]
    # (a key at a time into the password field - focused by browser_type - is never pressed)
    assert "not pressed" in snap["tool_calls"][5]["result"]
    assert [w["kind"] for w in snap["web_requests"]] == ["password", "form"]
    assert "SECRET" not in str(snap["web_requests"])
    assert snap["allowed_web"] == []  # (a yes here is never a rule)


def test_a_click_at_a_mark_on_sign_in_waits_for_a_yes_as_its_words_do(
        fake, make_client, wait_run, project_dir, tmp_path):
    """K-gorsel-motor: A2 looks at what is at a mark's point, as at x, y."""
    folder = tmp_path / "login"
    folder.mkdir()
    (folder / "index.html").write_text(LOGIN, encoding="utf-8")

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(Quiet, directory=str(folder)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client, _pid, cid = _setup(make_client, project_dir, [
            step(call("browser_open", {"url": f"http://site.test:{server.server_address[1]}/"},
                      "b1")),
            step(call("browser_screenshot", {"marks": True}, "b2")),
            step(call("browser_click", {"mark": 2}, "b3")), text("done")],
            "full_auto")
        run_id = _go(client, cid)
        card = _asked(client, cid)
        assert (card["kind"], card["host"]) == ("form", "site.test")
        assert "Sign in" in card["target"]
        assert client.post(f"/api/web-requests/{card['id']}/reject").status_code == 200
        snap = wait_run(client, cid, run_id)
    finally:
        server.shutdown()
    assert "2: button 'Sign in'" in snap["tool_calls"][1]["result"]
    assert snap["tool_calls"][2]["status"] == "denied"


def test_an_allowed_name_that_stands_for_an_inside_address_is_not_opened(
        fake, site, make_client, wait_run, project_dir):
    """As a web request: what the name stands for is looked up after the yes, and an inside
    address - wildcard DNS, a rebinding name - is refused before the browser goes there."""
    port, asked = site
    client, _pid, cid = _setup(make_client, project_dir, [
        step(call("browser_open", {"url": f"http://lan.test:{port}/"}, "b1")), text("done")],
        "full_auto")
    _allow(client, cid, "lan.test")
    wait_run(client, cid, _go(client, cid))
    opened = _calls(client, cid)["browser_open"]
    assert opened["status"] == "failed" and "lan.test is on this machine or its network" in         opened["result"]
    assert asked == []


def test_a_site_unlisted_or_marked_while_the_browser_runs_is_out_from_the_next_call(
        fake, site, make_client, wait_run, project_dir):
    port, _asked_paths = site
    opens = [step(call("browser_open", {"url": f"http://{host}.test:{port}/"}, f"b{n}"))
             for n, host in enumerate(("site", "other", "third", "fourth"))]
    client, _pid, cid = _setup(make_client, project_dir, [*opens, text("done")], "ask")
    run_id = _go(client, cid)
    approve = "/api/web-requests/{}/approve"
    # site.test: Allow this site (a rule); other.test: This time (held by the browser).
    card = _asked(client, cid)
    client.post(approve.format(card["id"]), json={"remember": True})
    card = _asked(client, cid)
    assert card["host"] == "other.test"
    (rule,) = client.get(f"/api/conversations/{cid}").json()["allowed_web"]
    client.post(approve.format(card["id"]), json={"remember": False})
    card = _asked(client, cid)
    assert card["host"] == "third.test"
    agent_id = card["agent_id"]
    one = client.app.state.runner._browsers[agent_id]
    assert one.sites == {"site.test", "other.test"}
    # The user takes site.test off the list: gone from the next call, not kept as a yes.
    assert client.delete(f"/api/allowed-web/{rule['id']}").status_code == 204
    client.post(approve.format(card["id"]), json={"remember": False})
    card = _asked(client, cid)
    assert one.sites == {"other.test", "third.test"}
    client.post(f"/api/web-requests/{card['id']}/reject")
    wait_run(client, cid, run_id)


def test_a_site_is_listed_by_its_name_and_only_a_site_is_marked(make_client, project_dir):
    client, _pid, cid = _setup(make_client, project_dir, [], "ask")
    # Judged as an agent's open is (`site_of`), and said why in words of the user's.
    for bad, why in (("localhost", "not a site"), ("http://192.168.0.1/", "network"),
                     ("http://[::1]:5173/", "not a site"), ("printer", "network"),
                     ("nas.lan", "network"), ("a@b.test", "@")):
        refused = client.post(f"/api/conversations/{cid}/allowed-web",
                              json={"host": bad, "kind": "page"})
        assert refused.status_code == 422, bad
        assert why in refused.json()["detail"] and "browser_open" not in refused.json()["detail"]
    one = _allow(client, cid, "https://Example.com:8443/x")
    assert (one["host"], one["conversation_id"]) == ("example.com", None)
    assert _allow(client, cid, "example.com")["id"] == one["id"]  # (one rule for one site)
    get = client.post(f"/api/conversations/{cid}/allowed-web", json={"host": "example.com"})
    assert get.json()["kind"] == "host"
    assert client.patch(f"/api/allowed-web/{get.json()['id']}",
                        json={"ask_first": True}).status_code == 404
    # From another place than the app's own page: no.
    assert client.patch(f"/api/allowed-web/{one['id']}", json={"ask_first": True},
                        headers={"Origin": "http://evil.example"}).status_code == 403


def test_a_site_is_the_projects_added_on_its_settings_and_outlives_the_chat(
        make_client, project_dir):
    client, pid, cid = _setup(make_client, project_dir, [], "ask")
    sites = f"/api/projects/{pid}/sites"
    made = client.post(sites, json={"host": "Docs.test", "ask_first": True})
    assert made.status_code == 200, made.text
    site = made.json()
    assert (site["host"], site["ask_first"], site["project_id"], site["conversation_id"]) == (
        "docs.test", True, pid, None)
    assert client.post(sites, json={"host": "printer"}).status_code == 422
    # Allowed again in a chat: the one rule it was; every chat of the project has it.
    assert _allow(client, cid, "docs.test")["id"] == site["id"]
    assert [r["id"] for r in client.get(f"/api/conversations/{cid}").json()["allowed_web"]] == [
        site["id"]]
    get = client.post(f"/api/conversations/{cid}/allowed-web", json={"host": "api.test"}).json()
    # The chat goes for good, with its own GET rule; the site stays the project's.
    assert client.patch(f"/api/conversations/{cid}", json={"archived": True}).status_code == 200
    assert client.post("/api/conversations/delete", json={"ids": [cid]}).json()["deleted"] == [cid]
    assert client.delete(f"/api/allowed-web/{get['id']}").status_code == 404
    assert [r["host"] for r in client.get(sites).json()] == ["docs.test"]
    assert client.patch(f"/api/allowed-web/{site['id']}",
                        json={"ask_first": False}).json()["ask_first"] is False
    assert client.delete(f"/api/allowed-web/{site['id']}").status_code == 204
    assert client.get(sites).json() == []
    assert client.post(sites, json={"host": "x.test"},
                       headers={"Origin": "http://evil.example"}).status_code == 403
    long = client.post(sites, json={"host": ".".join(["a" * 60] * 4) + ".abcdef.test"})
    assert (long.status_code, long.json()["detail"]) == (
        422, "a site's name is at most 253 characters")


def test_a_chat_moved_into_a_project_brings_its_sites_and_keeps_ask_first(
        make_client, project_dir):
    client, pid, _cid = _setup(make_client, project_dir, [], "ask")
    plain = client.post("/api/conversations", json={}).json()["id"]
    marked = _allow(client, plain, "docs.test", ask_first=True)
    assert (marked["conversation_id"], marked["project_id"]) == (plain, None)
    _allow(client, plain, "own.test")
    client.post(f"/api/projects/{pid}/sites", json={"host": "docs.test"})
    assert client.patch(f"/api/conversations/{plain}", json={"project_id": pid}).status_code \
        == 200
    # One rule a site, the project's; the chat's Ask first is kept, never lost for the move.
    sites = client.get(f"/api/projects/{pid}/sites").json()
    assert sorted((s["host"], s["ask_first"], s["conversation_id"]) for s in sites) == [
        ("docs.test", True, None), ("own.test", False, None)]
    assert sorted(r["host"] for r in client.get(f"/api/conversations/{plain}").json()[
        "allowed_web"]) == ["docs.test", "own.test"]
    assert client.app.state.runner._page_rules(plain) == {"docs.test": True, "own.test": False}


def test_a_site_held_twice_is_asked_about_if_either_rule_says_so(make_client, project_dir):
    client, pid, cid = _setup(make_client, project_dir, [], "ask")
    client.post(f"/api/projects/{pid}/sites", json={"host": "docs.test"})
    runner = client.app.state.runner
    # (As a chat moved in before its sites went with it: its own marked rule beside the project's.)
    with runner._factory() as session:
        session.add(AllowedWeb(conversation_id=cid, kind="page", host="docs.test", ask_first=True))
        session.commit()
    assert runner._page_rules(cid) == {"docs.test": True}


# --- the real Chrome ------------------------------------------------------------------------


async def _away(tmp_path, port, sites=frozenset({"site.test"}), closed=frozenset(),
                resolver=None):
    (tmp_path / "proj").mkdir(exist_ok=True)
    one = browser.Browser(tmp_path / "scratch", "agent1")
    command = browser.find_browser()
    assert command is not None
    # (A test's names only - and nothing else resolves, the network never reached.)
    await one.start(command, Workspace(str(tmp_path / "proj")), set(closed), away=True,
                    resolver=resolver if resolver is not None else
                    "MAP site.test 127.0.0.1, MAP other.test 127.0.0.1, MAP * ~NOTFOUND, ")
    one.sites = sites
    return one


@REAL
@pytest.mark.anyio
async def test_the_real_chrome_opens_an_allowed_site_and_keeps_it_from_this_machine(
        tmp_path, site):
    port, asked = site
    one = await _away(tmp_path, port)
    try:
        assert (await one.open(f"http://site.test:{port}/")).endswith(" - Site")
        assert "SITE-MARKER" in await one.read()
        said = await one._eval(
            f"Promise.all([fetch('http://127.0.0.1:{port}/loop').then(() => 'got', () => 'no'),"
            f" fetch('http://other.test:{port}/plain').then(() => 'got', () => 'no'),"
            " (() => { try { new WebSocket('ws://site.test/'); return 'made' }"
            "          catch (e) { return e.name } })(),"
            " (() => { try { new WebSocket('wss://127.0.0.1/'); return 'made' }"
            "          catch (e) { return e.name } })()]).then(r => r.join(' '))", wait=True)
        assert said == "no no SecurityError SecurityError"
        # The page takes itself to a site not on the list: refused.
        await one._eval(f"setTimeout(() => location.href = 'http://other.test:{port}/away', 10)")
        await asyncio.sleep(1.5)
        refused = one.refused()
        assert "other.test is not a site the user allowed" in refused
        assert "/loop" not in asked and "/plain" not in asked and "/away" not in asked
        assert "127.0.0.1" in refused and "only https" in refused
    finally:
        await one.close()


@REAL
@pytest.mark.anyio
async def test_the_real_chrome_that_went_out_resolves_nothing_of_this_machine(
        tmp_path, site, monkeypatch):
    """The backstop behind the judge, for what it does not see (a worker's socket): with every
    load let through, this machine by name or address still does not resolve."""
    port, asked = site
    monkeypatch.setattr(browser, "outside", lambda *args, **kwargs: None)
    monkeypatch.setattr(browser, "looked_up", lambda url: asyncio.sleep(0))  # (a judge too)
    one = await _away(tmp_path, port, resolver="")
    try:
        for url in (f"http://127.0.0.1:{port}/a", f"http://localhost:{port}/b",
                    f"http://[::1]:{port}/c"):
            with contextlib.suppress(browser.BrowserError):
                await one.open(url)
        assert asked == []
    finally:
        await one.close()


def test_no_rule_of_the_inside_takes_every_name():
    """B-361: Chrome matches a rule against host:port too - "*:*" took example.com:443."""
    assert "*:*" not in browser.INSIDE and "*::*" in browser.INSIDE


@REAL
@pytest.mark.anyio
async def test_the_real_chrome_that_went_out_does_not_reach_an_ipv6_server_here(
        tmp_path, monkeypatch):
    """The rules out of `INSIDE` alone keep a server on [::1] out of reach. The tests before
    B-361 each put `MAP * ~NOTFOUND` in front, so no name was ever resolved by those rules -
    and "*:*" refusing every one went unseen."""

    class Six(http.server.ThreadingHTTPServer):
        address_family = socket.AF_INET6

    asked: list[str] = []

    class Here(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            asked.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    try:
        server = Six(("::1", 0), Here)
    except OSError:
        pytest.skip("no IPv6 loopback on this machine")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    # (Every judge let through - the page's own lookup refuses [::1] too - so only the rules.)
    monkeypatch.setattr(browser, "outside", lambda *args, **kwargs: None)
    monkeypatch.setattr(browser, "looked_up", lambda url: asyncio.sleep(0))
    one = await _away(tmp_path, 0, resolver="")
    try:
        with contextlib.suppress(browser.BrowserError):
            await one.open(f"http://[::1]:{server.server_address[1]}/six")
        assert asked == []
    finally:
        await one.close()
        server.shutdown()


@REAL
@pytest.mark.anyio
async def test_the_real_chrome_sees_a_password_and_a_form_and_holds_the_form_till_a_yes(
        tmp_path):
    """A2 on the real Chrome: what a click or typing reaches is seen in a world of KOLONİ's
    own - a page that hides it from its own scripts does not hide it - and a form the page
    sends by itself is refused until a yes."""
    posted: list[str] = []

    class Login(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<title>Login</title><form method=post action=/in><input id=pw type=password>"
                b"<button id=go style='width:200px;height:40px'>Sign in</button></form>"
                b"<script>document.elementFromPoint = () => null;"
                b" Element.prototype.closest = function () { return null };</script>")

        def do_POST(self):
            posted.append(self.path)
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Login)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    one = await _away(tmp_path, port)
    try:
        await one.open(f"http://site.test:{port}/")
        at, _named = await one.point("#go", None, None, None)
        assert browser.stop(await one.what(at=at), "click") == (
            "form", "send a form - the page's own words on it: 'Sign in'", "site.test")
        assert browser.stop(await one.what(selector="#pw"), "type")[0] == "password"
        await one._eval("document.getElementById('pw').focus()")
        assert browser.stop(await one.what(), "type")[0] == "password"  # (the focused field)
        # The page sends it by itself: refused, nothing posted.
        await one._eval("document.forms[0].submit()")
        await asyncio.sleep(1.0)
        assert "tried to send a form" in one.refused() and posted == []
        # After a yes, the click sends it once.
        await one.open(f"http://site.test:{port}/")
        one.posting = time.monotonic() + browser.LOAD_WAIT
        await one.click_at(at, "#go")
        assert posted == ["/in"] and one.posting == 0.0
    finally:
        await one.close()
        server.shutdown()


@REAL
@pytest.mark.anyio
async def test_the_real_chrome_guards_a_workers_socket_and_looks_at_the_field_once_focused(
        tmp_path, site, closed_server):  # noqa: F811
    """Security review: a Blob worker's WebSocket reached a closed port; a page that names
    another field, turns one into a password field as it is focused, or hides one in a closed
    shadow root, typed with no card. What is typed into is looked at once it has the focus,
    in KOLONİ's own world."""
    port, _asked_paths = site
    closed, upgrades = closed_server
    one = await _away(tmp_path, port, closed={closed})
    try:
        await one.open(f"http://site.test:{port}/")
        said = await one._eval(
            "new Promise(r => { const w = new Worker(URL.createObjectURL(new Blob(["
            f"\"try {{ new WebSocket('wss://site.test:{closed}/w'); postMessage('made') }}"
            " catch (e) { postMessage(e.name) }\"]))); w.onmessage = e => r(e.data);"
            " setTimeout(() => r('timeout'), 3000) })", wait=True)
        assert said == "SecurityError" and upgrades == []
        await one._eval(
            "document.body.innerHTML = '<input id=q><input id=pw type=password>"
            "<input id=t data-k=password onfocus=this.type=this.dataset.k>"
            "<x-box id=box></x-box>';"
            "const pw = document.getElementById('pw');"
            "const real = Document.prototype.querySelector;"
            "document.querySelector = s => s === '#q' ? pw : real.call(document, s);"
            "const root = document.getElementById('box').attachShadow("
            "{ mode: 'closed', delegatesFocus: true }); root.innerHTML = '<input type=password>'")
        seen: list = []

        async def judge(found):
            seen.append(found)
            raise browser.BrowserError("held")  # (the card's no: nothing typed)

        for selector, kind in (("#q", "password"), ("#t", "password"), ("#box", "field")):
            seen.clear()
            with pytest.raises(browser.BrowserError, match="held"):
                await one.type(selector, "x", judge)
            assert browser.stop(seen[0], "type")[0] == kind, (selector, seen)
        assert await one._eval("document.getElementById('pw').value") == ""
    finally:
        await one.close()


@REAL
@pytest.mark.anyio
async def test_the_real_chrome_does_not_follow_a_page_to_an_allowed_name_that_is_inside(
        tmp_path, site):
    port, asked = site
    one = await _away(tmp_path, port, sites=frozenset({"site.test", "lan.test"}),
                      resolver="MAP site.test 127.0.0.1, MAP lan.test 127.0.0.1, "
                               "MAP * ~NOTFOUND, ")
    try:
        await one.open(f"http://site.test:{port}/")
        await one._eval(f"setTimeout(() => location.href = 'http://lan.test:{port}/away', 10)")
        await asyncio.sleep(1.5)
        assert "lan.test is on this machine or its network" in one.refused()
        assert "/away" not in asked
    finally:
        await one.close()
