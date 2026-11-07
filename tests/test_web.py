"""The rules above the three places `app.web` leaves this machine from (slice 18c).

No test touches the network: `raw`, `resolve` and `cli_search` are stood in for, and an
address written as one is never handed to `resolve` at all.
"""

import asyncio
import json
import time

import pytest

from app import web

PUBLIC = "93.184.216.34"


class Net:
    """Answers by a part of the address, and keeps what was asked."""

    def __init__(self, monkeypatch, answers=None, names=None, cli=None):
        self.asked, self.sent, self.answers = [], [], answers or {}
        self.resolved: list[str] = []
        names = names or {}

        async def raw(method, url, headers, body, ip):
            self.asked.append((method, url, ip))
            self.sent.append((dict(headers), body))
            for part, answer in self.answers.items():
                if part in url:
                    if isinstance(answer, Exception):
                        raise answer
                    status, headers_back, said = answer
                    if isinstance(headers_back, str):
                        headers_back = {"content-type": headers_back}
                    return web.Raw(status, headers_back,
                                   said if isinstance(said, bytes) else said.encode())
            return web.Raw(404, {"content-type": "text/plain"}, b"nothing here")

        def resolve(host):
            self.resolved.append(host)
            return names.get(host, [PUBLIC])

        async def cli_search(query):
            self.asked.append(("CLI", query, None))
            return cli

        monkeypatch.setattr(web, "raw", raw)
        monkeypatch.setattr(web, "resolve", resolve)
        monkeypatch.setattr(web, "cli_search", cli_search)


def run(work):
    return asyncio.run(work)


# --- the address check -------------------------------------------------------------------


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://127.0.0.1:8790/api/projects", "http://127.1/",
    "http://2130706433/",                 # 127.0.0.1 as one decimal number
    "http://0x7f000001/", "http://0x7f.1/", "http://0x7F.0.0.1/",       # hex
    "http://017700000001/", "http://0177.0.0.1/", "http://012.0.0.1/",  # octal
    "http://127.0.0.1./", "http://LOCALHOST/", "http://LocalHost./",   # trailing dot, case
    "http://[::1]/", "http://[::]/", "http://0.0.0.0/", "http://0/",
    "http://10.0.0.5/", "http://172.16.0.1/", "http://172.31.255.255/", "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/", "http://[fe80::1]/",    # link-local, metadata
    "http://[fc00::1]/", "http://[fd12:3456::1]/",                      # unique-local
    "http://100.64.0.1/", "http://100.127.255.255/",                    # carrier-grade NAT
    "http://224.0.0.1/", "http://[ff02::1]/", "http://240.0.0.1/", "http://255.255.255.255/",
    "http://[::ffff:127.0.0.1]/", "http://[::ffff:10.0.0.1]/", "http://[::ffff:7f00:1]/",
    "http://[::127.0.0.1]/", "http://[::7f00:1]/",                      # IPv4-compatible
    "http://[64:ff9b::7f00:1]/", "http://[2002:7f00:1::]/",             # NAT64, 6to4
    "http://999.1.1.1/", "http://1.2.3.4.5/", "http://0x100.1.1.1/",    # numbers, no address
    "http://inside.example.com/", "http://both.example.com/",
    "file:///C:/Windows/win.ini", "ftp://example.com/", "gopher://example.com/", "//example.com/",
    "http://user:pass@example.com/", "http://user@example.com/", "http://@example.com/",
    "http://example.com\\@127.0.0.1/", "http:///nohost", "http://exa mple.com/",
    "http://example.com:99999/", "http://[::1", "", "example.com",
])
def test_an_address_that_leads_to_this_machine_or_its_network_is_refused(monkeypatch, url):
    net = Net(monkeypatch, names={
        "localhost": ["127.0.0.1"], "inside.example.com": ["10.1.2.3"],
        "both.example.com": [PUBLIC, "192.168.0.9"],     # every address has to be public
    })
    with pytest.raises(web.NotReachable, match="not reachable from here"):
        run(web.fetch("GET", url, {}, None))
    assert net.asked == []


def test_an_address_written_as_numbers_is_judged_as_written_and_never_looked_up(monkeypatch):
    net = Net(monkeypatch)
    for url in ("http://2130706433/", "http://0x7f.1/", "http://[::1]/", "http://127.0.0.1./"):
        with pytest.raises(web.NotReachable):
            run(web.fetch("GET", url, {}, None))
    assert net.resolved == []                 # the stand-in would have called each public
    assert web.literal("1.2.3.4") == "1.2.3.4" and web.literal("0x5db8d822") == PUBLIC
    assert web.literal("example.com") is None and web.literal("1e100.net") is None
    assert web.literal("010.0.0.1") == "8.0.0.1"      # octal, as a system reads it: public


def test_a_public_address_is_asked_at_the_address_its_name_was_checked_as(monkeypatch):
    net = Net(monkeypatch, {"Example.COM": (200, "text/plain", "ok")},
              names={"example.com": ["2001:4860:4860::8888", PUBLIC]})
    answer, final = run(web.fetch("GET", "https://Example.COM./a?b=c", {"X": "1"}, None))
    assert (answer.status, final) == (200, "https://Example.COM./a?b=c")
    assert net.asked == [("GET", "https://Example.COM./a?b=c", "2001:4860:4860::8888")]
    assert net.resolved == ["example.com"]
    run(web.fetch("GET", f"http://{PUBLIC}:8080/", {}, None))
    assert net.asked[-1] == ("GET", f"http://{PUBLIC}:8080/", PUBLIC)


def test_the_next_address_of_a_name_is_tried_when_one_cannot_be_connected_to(monkeypatch):
    net = Net(monkeypatch, names={"example.com": ["2001:4860:4860::8888", PUBLIC]})

    async def raw(method, url, headers, body, ip):
        net.asked.append((method, url, ip))
        if ":" in ip:
            raise web.NotConnected("no route to host")  # a machine without IPv6
        return web.Raw(200, {"content-type": "text/plain"}, b"ok")

    monkeypatch.setattr(web, "raw", raw)
    answer, _final = run(web.fetch("GET", "https://example.com/", {}, None))
    assert answer.status == 200 and [ip for _m, _u, ip in net.asked] == [
        "2001:4860:4860::8888", PUBLIC]
    assert "sent" in run(web.notify("https://example.com/hook", "hi"))
    # when none can be, the last failure is the request's
    monkeypatch.setattr(web, "resolve", lambda host: ["2001:4860:4860::8888"])
    with pytest.raises(OSError):
        run(web.fetch("GET", "https://example.com/", {}, None))


def test_what_is_written_as_an_inside_address_is_refused_without_anything_looked_up(monkeypatch):
    net = Net(monkeypatch)
    for url in ("http://127.0.0.1:8790/", "http://[::1]/", "http://2130706433/", "http://10.0.0.5/",
                "http://localhost:8790/", "http://api.LOCALHOST./", "file:///x",
                "http://u:p@example.com/"):
        with pytest.raises(web.NotReachable):
            web.host_of(url)
    assert web.host_of("https://Example.COM./a") == "example.com"
    assert web.host_of(f"http://{PUBLIC}/") == PUBLIC
    assert net.resolved == []


def test_a_name_that_cannot_be_looked_up_is_not_reachable(monkeypatch):
    Net(monkeypatch)
    monkeypatch.setattr(web, "resolve", lambda host: (_ for _ in ()).throw(OSError("no such")))
    with pytest.raises(web.NotReachable):
        run(web.fetch("GET", "https://nowhere.example/", {}, None))
    monkeypatch.setattr(web, "resolve", lambda host: [])
    with pytest.raises(web.NotReachable):
        run(web.fetch("GET", "https://nowhere.example/", {}, None))


# --- the one place a request leaves from (against a server of the test's, on loopback) ----


def test_a_request_goes_to_the_address_it_is_given_under_the_name_in_its_address():
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            size = int(self.headers.get("Content-Length") or 0)
            seen.append((self.path, self.headers.get("Host"), self.headers.get("X-Mine"),
                         self.rfile.read(size)))
            self.send_response(302 if self.path.startswith("/moved") else 200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Location", "/elsewhere")
            self.end_headers()
            if self.path.startswith("/big"):
                self.wfile.write(b"a" * (web.MAX_BYTES + 100_000))
            else:
                self.wfile.write(b"hello")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        # A name nothing looks up: only the address given is connected to.
        url = f"http://name.invalid:{port}"
        answer = web._send("POST", f"{url}/a b?q=1 2", {"X-Mine": "1"}, b"data", "127.0.0.1")
        assert (answer.status, answer.body) == (200, b"hello")
        assert answer.headers["content-type"] == "text/plain"
        assert seen == [("/a%20b?q=1%202", f"name.invalid:{port}", "1", b"data")]
        # a redirect is the caller's to follow, and an endless answer is read so far only
        assert web._send("POST", f"{url}/moved", {}, None, "127.0.0.1").status == 302
        assert len(web._send("POST", f"{url}/big", {}, None, "127.0.0.1").body) == web.MAX_BYTES + 1
    finally:
        server.shutdown()
        server.server_close()


# --- redirects ---------------------------------------------------------------------------


def hops(monkeypatch, net, where):
    """Every request is answered with a redirect to the next of `where`, then with ok."""
    left = list(where)

    async def raw(method, url, headers, body, ip):
        net.asked.append((method, url, ip))
        net.sent.append((dict(headers), body))
        if left:
            status, target = left.pop(0)
            return web.Raw(status, {"location": target}, b"")
        return web.Raw(200, {"content-type": "text/plain"}, b"ok")

    monkeypatch.setattr(web, "raw", raw)


def test_every_hop_of_a_redirect_is_checked_again(monkeypatch):
    for inside in ("http://127.0.0.1:8790/api/projects", "http://inside.example.com/",
                   "http://2130706433/", "file:///etc/passwd", "//10.0.0.1/x"):
        net = Net(monkeypatch, names={"inside.example.com": ["10.1.2.3"]})
        hops(monkeypatch, net, [(302, "/next"), (301, inside)])
        with pytest.raises(web.NotReachable):
            run(web.fetch("GET", "https://example.com/go", {}, None))
        assert [url for _m, url, _ip in net.asked] == [
            "https://example.com/go", "https://example.com/next"]


def test_at_most_five_redirects_are_followed(monkeypatch):
    net = Net(monkeypatch)
    hops(monkeypatch, net, [(302, f"/{n}") for n in range(5)])
    answer, final = run(web.fetch("GET", "https://example.com/go", {}, None))
    assert (answer.status, final, len(net.asked)) == (200, "https://example.com/4", 6)
    net = Net(monkeypatch)
    hops(monkeypatch, net, [(302, f"/{n}") for n in range(6)])
    with pytest.raises(web.WebError, match="more than 5 redirects"):
        run(web.fetch("GET", "https://example.com/go", {}, None))
    assert len(net.asked) == 6


def test_a_redirect_to_somewhere_else_does_not_take_the_agents_headers_along(monkeypatch):
    net = Net(monkeypatch)
    hops(monkeypatch, net, [(307, "/same"), (307, "https://other.example.org/x")])
    secret = {"Authorization": "Bearer S"}
    run(web.fetch("POST", "https://example.com/go", secret, None))   # (a body: not sent on)
    assert [headers for headers, _body in net.sent] == [secret, secret, {}]
    assert [m for m, _u, _ip in net.asked] == ["POST"] * 3      # 307 keeps the method
    # ...and the same name over plain http is somewhere else too
    net = Net(monkeypatch)
    hops(monkeypatch, net, [(302, "http://example.com/plain")])
    run(web.fetch("GET", "https://example.com/go", secret, None))
    assert net.sent[-1][0] == {}


def test_a_see_other_is_fetched_with_get_and_no_body(monkeypatch):
    net = Net(monkeypatch)
    hops(monkeypatch, net, [(303, "/done")])
    run(web.fetch("POST", "https://example.com/form", {}, b"data"))
    assert [(m, body) for (m, _u, _ip), (_h, body) in zip(net.asked, net.sent, strict=True)] == [
        ("POST", b"data"), ("GET", None)]


def test_a_redirect_to_a_host_that_was_not_allowed_is_not_followed(monkeypatch):
    net = Net(monkeypatch)
    hops(monkeypatch, net, [(302, "https://other.example.org/x")])
    with pytest.raises(web.WebError, match="other.example.org"):
        run(web.fetch("GET", "https://example.com/go", {}, None,
                      may=lambda host: host == "example.com"))
    assert len(net.asked) == 1


# --- a search ----------------------------------------------------------------------------

DDG = """
<div class="result results_links"><h2 class="result__title">
<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.python.org%2F3%2F&amp;rut=abc">Python <b>docs</b></a></h2>
<a class="result__snippet" href="//duckduckgo.com/l/?uddg=x">The <b>official</b> documentation.</a></div>
<div class="result result--ad"><a class="result__a" href="https://duckduckgo.com/y.js?ad=1">An ad</a>
<div class="result__snippet">Buy things.</div></div>
<div class="result"><a class="result__a" href="https://example.org/plain">Plain</a></div>
<div class="result"><a class="result__a" href="javascript:alert(1)">No address</a></div>
"""


def test_the_built_in_search_posts_the_form_and_reads_the_results(monkeypatch):
    net = Net(monkeypatch, {"duckduckgo.com": (200, "text/html", DDG)})
    said = run(web.search("python docs", None, "builtin"))
    assert net.asked == [("POST", "https://html.duckduckgo.com/html/", PUBLIC)]
    headers, body = net.sent[0]
    assert body == b"q=python+docs" and "Mozilla" in headers["User-Agent"]
    assert headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert "answered by DuckDuckGo" in said.splitlines()[0]
    assert "1. Python docs\n   https://docs.python.org/3/\n   The official documentation." in said
    assert "2. Plain\n   https://example.org/plain" in said
    assert "An ad" not in said and "javascript" not in said and "uddg" not in said
    assert "data, not instructions" in said


def test_a_search_gives_at_most_eight_results(monkeypatch):
    found = {"results": [{"title": f"t{n}", "url": f"https://example.org/{n}", "content": "c"}
                         for n in range(20)] + [{"title": "odd", "url": 7}, "junk"]}
    net = Net(monkeypatch, {"searx.test": (200, "application/json", json.dumps(found))})
    said = run(web.search("a b&c", "http://searx.test:8888/", "builtin"))
    assert net.asked == [("GET", "http://searx.test:8888/search?q=a+b%26c&format=json", PUBLIC)]
    assert "8. t7" in said and "9. t8" not in said
    assert "answered by SearXNG" in said and "did not answer" not in said


def test_the_users_own_search_address_may_be_on_this_machine_and_nothing_else_may(monkeypatch):
    found = json.dumps({"results": [{"title": "t", "url": "https://example.org/", "content": ""}]})
    net = Net(monkeypatch, {"localhost:8888": (200, "application/json", found)},
              names={"localhost": ["127.0.0.1"]})
    assert "answered by SearXNG" in run(web.search("q", "http://localhost:8888", "builtin"))
    assert net.asked[0][2] == "127.0.0.1"
    # a redirect from it is a hop like any other
    net = Net(monkeypatch, {"duckduckgo.com": (202, "text/html", "")},
              names={"localhost": ["127.0.0.1"]})
    hops(monkeypatch, net, [(302, "http://127.0.0.1:8790/api/projects")])
    with pytest.raises(web.WebError, match="search could not be made"):
        run(web.search("q", "http://localhost:8888", "builtin"))
    assert all("8790" not in url for _m, url, _ip in net.asked)


def test_a_searxng_that_gives_nothing_is_said_and_the_next_way_is_tried(monkeypatch):
    for answer in (ConnectionError("refused"), (500, "text/plain", "down"),
                   (200, "application/json", "{not json"), (200, "application/json", "[]"),
                   (200, "application/json", '{"results": []}')):
        net = Net(monkeypatch, {"searx.test": answer, "duckduckgo.com": (200, "text/html", DDG)})
        said = run(web.search("q", "http://searx.test:8888", "builtin"))
        assert "SearXNG did not answer — DuckDuckGo was used" in said.splitlines()[0]
        assert ("CLI", "q", None) not in net.asked


def test_the_cli_is_asked_last_or_before_the_built_in_search_as_the_project_says(monkeypatch):
    found = [{"title": "From a CLI", "url": "https://example.org/cli", "snippet": "s"},
             {"title": "no address"}, {"title": "inside", "url": "file:///x"}]
    net = Net(monkeypatch, {"duckduckgo.com": (200, "text/html", DDG)}, cli=found)
    assert "answered by DuckDuckGo" in run(web.search("q", None, "builtin"))
    assert ("CLI", "q", None) not in net.asked
    net = Net(monkeypatch, {"duckduckgo.com": (200, "text/html", DDG)}, cli=found)
    said = run(web.search("q", None, "cli"))
    assert "answered by a CLI" in said and "1. From a CLI\n   https://example.org/cli\n   s" in said
    assert "no address" not in said and "file:" not in said
    assert net.asked == [("CLI", "q", None)]
    net = Net(monkeypatch, {"duckduckgo.com": (202, "text/html", "<html>robot?</html>")},
              cli=found)
    assert "answered by a CLI" in run(web.search("q", None, "builtin"))


def test_a_search_no_way_answers_makes_nothing_up_and_says_why(monkeypatch):
    net = Net(monkeypatch, {"searx.test": ConnectionError("refused http://searx.test:8888"),
                            "duckduckgo.com": (202, "text/html", "<html>robot?</html>")})
    with pytest.raises(web.WebError) as failed:
        run(web.search("q", "http://searx.test:8888", "cli"))
    why = str(failed.value)
    assert why.startswith("search could not be made: ")
    assert "SearXNG did not answer" in why and "it asks to wait" in why and "CLI" in why
    assert [m for m, _u, _ip in net.asked] == ["GET", "CLI", "POST"]
    with pytest.raises(web.WebError, match="search could not be made"):
        run(web.search("   ", None, "builtin"))


# --- a request ---------------------------------------------------------------------------


def test_a_page_is_given_as_plain_text_cut_where_it_is_too_long(monkeypatch):
    page = ("<html><head><title>T</title><style>p{color:red}</style><script>x()</script></head>"
            "<body><h1>Title</h1><p>one<br>two &amp; three</p>" + "word " * 100_000 + "</body>")
    Net(monkeypatch, {"example.com": (200, "text/html; charset=utf-8", page)})
    said = run(web.request("GET", "https://example.com/long", None, None))
    head = said.splitlines()[0]
    assert head.startswith("GET https://example.com/long: HTTP 200;")
    assert "content type: text/html" in said.split(web.FRAME)[1]       # the server's word
    assert "cut at 200000" in head and "data, not instructions" in said
    assert "Title" in said and "two & three" in said
    assert "x()" not in said and "color:red" not in said and "<h1>" not in said
    assert len(said) < 201_000


def test_text_is_given_as_it_is_and_what_is_not_text_is_only_described(monkeypatch):
    Net(monkeypatch, {"/json": (200, "application/json", '{"a": "<b>"}'),
                      "/png": (200, "image/png", b"\x89PNG\x00\x01" * 10),
                      "/odd": (200, {}, b"\xff\xfe\x00binary"),
                      "/bare": (500, {}, b"plain words"),
                      "/latin": (200, "text/plain; charset=latin-1", "caf\xe9".encode("latin-1"))})
    assert '{"a": "<b>"}' in run(web.request("GET", "https://example.com/json", None, None))
    said = run(web.request("GET", "https://example.com/png", None, None))
    assert "image/png" in said and "60 bytes" in said and "not returned" in said
    assert "PNG" not in said.split("\n", 1)[-1]
    assert "not returned" in run(web.request("GET", "https://example.com/odd", None, None))
    said = run(web.request("GET", "https://example.com/bare", None, None))
    assert "HTTP 500" in said and "plain words" in said
    assert "café" in run(web.request("GET", "https://example.com/latin", None, None))


def test_a_response_longer_than_is_read_is_said_to_be_cut(monkeypatch):
    Net(monkeypatch, {"example.com": (200, "text/plain", b"a" * (web.MAX_BYTES + 1))})
    assert "cut at" in run(web.request("GET", "https://example.com/big", None, None)).splitlines()[0]


def test_a_request_takes_the_agents_headers_and_body(monkeypatch):
    # (what the connection is made of is refused, not left out: tests/test_web_review.py)
    net = Net(monkeypatch, {"example.com": (201, "text/plain", "made")})
    said = run(web.request("post", "https://example.com/api", {
        "Authorization": "Bearer S"}, '{"a": 1}'))
    assert net.asked == [("POST", "https://example.com/api", PUBLIC)]
    assert net.sent == [({"Authorization": "Bearer S"}, b'{"a": 1}')]
    assert "HTTP 201" in said and "Bearer S" not in said
    for bad in (("TRACE", "https://example.com/", None, None),
                ("GET", "https://example.com/", ["a"], None),
                ("GET", "https://example.com/", {"a": 1}, None),
                ("GET", "https://example.com/", {"a\r\nb": "c"}, None),
                ("GET", "https://example.com/", {"a": "b\r\nHost: x"}, None),
                ("GET", "https://example.com/", None, 7), ("GET", None, None, None)):
        with pytest.raises(web.WebError):
            run(web.request(*bad))
    assert len(net.asked) == 1


def test_a_request_that_fails_says_so_in_few_words(monkeypatch):
    Net(monkeypatch, {"example.com": TimeoutError("timed out")})
    with pytest.raises(web.WebError, match="got no answer.*TimeoutError"):
        run(web.request("GET", "https://example.com/", None, None))


# --- a notification ----------------------------------------------------------------------

HOOK = "https://hooks.example.com/services/T000/B000/XYZ-PRIVATE"


def test_a_notification_is_posted_as_json_to_the_users_address(monkeypatch):
    net = Net(monkeypatch, {"hooks.example.com": (200, "text/plain", "ok")})
    said = run(web.notify(HOOK, "the tests pass — ✓"))
    assert net.asked == [("POST", HOOK, PUBLIC)]
    headers, body = net.sent[0]
    assert headers == {"Content-Type": "application/json"}
    assert json.loads(body) == {"text": "the tests pass — ✓"}
    assert "XYZ-PRIVATE" not in said and "hooks.example.com" not in said


def test_a_notification_that_fails_never_says_where_it_was_going(monkeypatch):
    for answer in (ConnectionError(f"could not reach {HOOK}"), (403, "text/plain", HOOK),
                   (302, {"location": HOOK + "/moved"}, "")):
        Net(monkeypatch, {"hooks.example.com": answer})
        with pytest.raises(web.WebError) as failed:
            run(web.notify(HOOK, "hello"))
        assert "XYZ-PRIVATE" not in str(failed.value) and "hooks.example" not in str(failed.value)
    Net(monkeypatch, names={"hooks.example.com": ["10.0.0.7"]})
    with pytest.raises(web.NotReachable) as failed:
        run(web.notify(HOOK, "hello"))
    assert "XYZ-PRIVATE" not in str(failed.value) and "hooks.example" not in str(failed.value)


def test_a_notification_is_a_text_of_at_most_two_thousand_characters(monkeypatch):
    net = Net(monkeypatch, {"hooks.example.com": (200, "text/plain", "ok")})
    for bad in ("", "   ", None, 5, "x" * 2001):
        with pytest.raises(web.WebError):
            run(web.notify(HOOK, bad))
    assert net.asked == []
    run(web.notify(HOOK, "x" * 2000))
    assert len(net.asked) == 1


# --- what is kept ------------------------------------------------------------------------


def test_header_values_are_hidden_in_what_is_kept_of_a_call():
    kept = web.masked(json.dumps({"method": "GET", "url": "https://example.com/", "headers": {
        "Authorization": "Bearer TOP", "X-Key": "k"}, "body": "b"}))
    assert json.loads(kept) == {"method": "GET", "url": "https://example.com/", "headers": {
        "Authorization": "***", "X-Key": "***"}, "body": "b"}
    assert json.loads(web.masked('{"url": "u", "headers": "Authorization: TOP"}'))["headers"] == "***"
    assert json.loads(web.masked('{"url": "u"}')) == {"url": "u"}
    # what cannot be read is not kept as it came: a secret may be anywhere in it
    for unreadable in ('{"headers": {"Authorization": "TOP"', "[1]", "TOP"):
        assert "TOP" not in web.masked(unreadable)


def test_an_address_that_can_be_kept_is_http_or_https_without_a_name_and_password():
    assert web.settable("http://localhost:8888") and web.settable("https://hooks.example.com/a/b")
    for bad in ("ftp://example.com", "example.com", "http://u:p@example.com", "http://", "",
                "http://exa mple.com", "http://example.com:port"):
        assert not web.settable(bad)


def test_a_host_a_trigger_names_is_a_bare_name():
    assert web.host_name(" Example.COM. ") == "example.com"
    assert web.host_name("api.example.com") == "api.example.com"
    for bad in ("https://example.com", "example.com/path", "example.com:8080", "", "a b",
                "user@example.com", "*.example.com", 5):
        with pytest.raises(ValueError):
            web.host_name(bad)


def test_so_many_a_minute_and_no_more():
    rate = web.Rate(2)
    assert rate.take("c", 0.0) and rate.take("c", 1.0) and not rate.take("c", 59.0)
    assert rate.take("other", 59.0)           # each conversation has its own
    assert rate.take("c", 60.5) and not rate.take("c", 60.9)


# --- slice 20a: the desktop, the body's form, secrets in an address or a body ------------

TITLE, SAID = "KOLONİ — $(calc) 'p'", "done <b>&amp; `whoami`\"; $env:PATH\x00\x07\nline two"


def powershell(monkeypatch, ends=0):
    """Stand in for the process a toast is shown by; keeps how it was started."""
    started = []

    def start(argv, **how):
        started.append((argv, how))
        if isinstance(ends, Exception):
            raise ends
        return web.subprocess.CompletedProcess(argv, ends)

    monkeypatch.setattr(web.sys, "platform", "win32")
    monkeypatch.setattr(web.subprocess, "run", start)
    return started


def test_a_toasts_title_and_text_are_never_on_the_command_line(monkeypatch):
    started = powershell(monkeypatch)
    web.desktop(TITLE, SAID)
    ((argv, how),) = started
    assert argv[1:4] == ["-NoProfile", "-NonInteractive", "-Command"] and argv[4] == web._TOAST
    # by its full path: not whatever is called powershell.exe where the app runs
    assert argv[0].endswith("powershell.exe") and "System32" in argv[0]
    for part in ("calc", "whoami", "done", "line two", "KOLONİ"):
        assert not any(part in arg for arg in argv), part
    # they go by the environment, and the script puts them in as text - never as markup
    assert how["env"]["KOLONI_TOAST_TITLE"] == TITLE
    assert how["env"]["KOLONI_TOAST_TEXT"] == SAID.replace("\x00", " ").replace("\x07", " ")
    assert "CreateTextNode($env:KOLONI_TOAST_TEXT)" in web._TOAST and '"' not in web._TOAST
    assert how["timeout"] == web.TOAST_SECONDS and "shell" not in how


@pytest.mark.parametrize("ends", [
    1, web.subprocess.TimeoutExpired("powershell", 10), FileNotFoundError("powershell")])
def test_a_toast_that_was_not_shown_says_so_without_the_text(monkeypatch, ends):
    powershell(monkeypatch, ends)
    with pytest.raises(web.WebError) as failed:
        web.desktop(TITLE, SAID)
    assert "was not shown" in str(failed.value)
    assert "done" not in str(failed.value) and "calc" not in str(failed.value)


def test_there_is_no_desktop_notification_off_windows(monkeypatch):
    started = powershell(monkeypatch)
    monkeypatch.setattr(web.sys, "platform", "linux")
    with pytest.raises(web.WebError, match="not available on this system"):
        web.desktop(TITLE, SAID)
    assert started == []


def test_what_is_shown_on_the_desktop_is_a_notifications_text(monkeypatch):
    shown = []
    monkeypatch.setattr(web, "desktop", lambda title, said: shown.append((title, said)))
    for bad in ("", "   ", None, "x" * 2001):
        with pytest.raises(web.WebError):
            run(web.show("t", bad))
    assert shown == [] and "desktop" in run(web.show("t", "hi")) and shown == [("t", "hi")]


@pytest.mark.parametrize("form, kind, body", [
    ("discord", "application/json", b'{"content": "caf\\u00e9 & <b>"}'),
    ("text", "text/plain; charset=utf-8", "café & <b>".encode()),
])
def test_a_notifications_body_is_in_the_form_asked_for(monkeypatch, form, kind, body):
    net = Net(monkeypatch, {"hooks.example.com": (200, "text/plain", "ok")})
    run(web.notify(HOOK, "café & <b>", form))
    assert net.sent == [({"Content-Type": kind}, body)]


def test_a_field_named_like_a_secret_is_hidden_in_an_address():
    assert web.kept_url("https://example.com/a?api_key=K1&q=tea&X-Signature=S1&page=2#top") == (
        "https://example.com/a?api_key=***&q=tea&X-Signature=***&page=2#top")
    assert web.kept_url("https://example.com/a?access%5Ftoken=T1&flag&=x") == (
        "https://example.com/a?access%5Ftoken=***&flag&=x")
    for same in ("https://example.com/", "https://example.com/token/T1", "https://example.com/?",
                 "https://example.com/?q=a%20b&&n=1"):
        assert web.kept_url(same) == same       # the rest is letter for letter as written


def test_a_field_named_like_a_secret_is_hidden_in_a_body():
    def kept(body):
        return json.loads(web.kept(json.dumps({"url": "https://example.com/", "body": body})))["body"]

    assert kept("user=ann&PassWord=hunter2&note=two+cups") == "user=ann&PassWord=***&note=two+cups"
    assert json.loads(kept(json.dumps({"a": [{"client_secret": {"deep": "S1"}}, 5], "b": "é"}))) == {
        "a": [{"client_secret": "***"}, 5], "b": "é"}
    # nothing named like a secret, or neither JSON nor a form: as it was written
    for same in ('{ "note" : "two cups" }', "my password=hunter2 is written in a sentence",
                 "plain words", "[1, 2]", "", "a=1&b"):
        assert kept(same) == same
    assert kept("[" * 100_000) == "***"         # too deep to look into: not kept as it came


def test_json_too_deep_is_told_by_its_brackets_the_same_on_every_python():
    # (3.14's json reads 100,000 deep on Linux's stack, and raises far sooner on Windows')
    deep = web.MAX_JSON_DEPTH + 1
    assert web.too_deep("[" * deep) and web.too_deep("[" * deep + "]" * deep)
    assert not web.too_deep("[" * (deep - 1) + "]" * (deep - 1))
    assert not web.too_deep(json.dumps({"a": ["[{" * deep + '"', "x"]}))  # in a string: none
    assert web.kept_body("[" * deep + '{"password": "S"}' + "]" * deep) == "***"
    assert not web.too_deep('"' + "[" * deep)  # a string left open: to the end, as json reads it
    # ... and read once: not tried again from each quote in it (once some seconds a 32K line)
    started = time.monotonic()
    assert not web.too_deep('"' + '\\"' * 200_000)
    assert time.monotonic() - started < 2


def test_what_is_kept_of_a_call_has_its_headers_hidden_too_and_stays_as_it_is():
    asked = json.dumps({"method": "POST", "url": "https://example.com/?token=T1&q=tea",
                        "headers": {"Authorization": "Bearer TOP"}, "body": '{"key": "K1"}'})
    once = web.kept(asked)
    assert json.loads(once) == {"method": "POST", "url": "https://example.com/?token=***&q=tea",
                                "headers": {"Authorization": "***"}, "body": '{"key": "***"}'}
    assert web.kept(once) == once
    assert "TOP" not in web.kept('{"url": "https://example.com/?token=TOP"')   # unreadable
