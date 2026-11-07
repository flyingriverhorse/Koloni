"""Slice 94's acceptance set: the page key. Written before the code.

Found by the 24 October audit: the endpoints that approve a card took a request that said no
origin at all (`require_origin`), and the others one that said the right origin - which a command
can say too (`curl -H "Origin: ..."`). An agent in Full auto could approve its own cards.

Contract (`tasarim/specs/2026-10-24-dilim-94-sayfa-anahtari-design.md`):
- Each start makes a key, held in memory only (`app.state.page_key`). Every `/api` request
  carries it - the `X-KOLONI-Key` header, or `?key=` where a header cannot go (EventSource, a
  download link) - or is answered 401 before anything else is looked at.
- What has a door of its own needs no page key: health, a webhook, the status line, and what a
  frame loads (a view's files, a project's raw file).
- The key never reaches a child process (`KOLONI_PAGE_KEY` is taken out of the environment once
  read), the access log or the settings' repr. The window shows the link with the key in place of
  uvicorn's "running on" line.
"""

import logging
import os
import sys
import time
import webbrowser
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import PageKey, create_app, hide_webhook_keys, open_code, opens_browser, show_link

ORIGIN = {"Origin": "http://127.0.0.1:8790"}
HEADER = "X-KOLONI-Key"
TOLD = "open KOLONİ from the link in its window"


@pytest.fixture
def bare(settings_env):
    """An app, and a client that knows nothing of its key - what an agent's `curl` is."""
    app = create_app(load_settings(settings_env))
    with TestClient(app, base_url="http://127.0.0.1:8790") as client:
        yield app, client


WRITES_AND_READS = [
    ("post", "/api/commands/nope/approve"),
    ("post", "/api/agents/nope/approve"),
    ("post", "/api/tool-calls/nope/approve"),
    ("patch", "/api/conversations/nope"),
    ("get", "/api/projects"),
    ("get", "/api/conversations/nope/events"),
    ("get", "/api/no-such-thing"),
]


@pytest.mark.parametrize(("method", "path"), WRITES_AND_READS)
@pytest.mark.parametrize("headers", [{}, ORIGIN], ids=["no origin", "the right origin"])
def test_a_request_without_the_key_is_refused_before_anything_else(bare, method, path, headers):
    _, client = bare
    answer = getattr(client, method)(path, headers=headers)
    assert answer.status_code == 401
    assert TOLD in answer.text


def test_a_wrong_key_is_refused(bare):
    app, client = bare
    assert client.get("/api/projects", headers={HEADER: app.state.page_key + "x"}).status_code == 401
    assert client.get("/api/projects", headers={HEADER: ""}).status_code == 401


def test_the_key_opens_the_api(bare):
    app, client = bare
    key = {HEADER: app.state.page_key}
    assert client.get("/api/projects", headers=key).status_code == 200
    # Past the key, the endpoint answers for itself.
    assert client.post(
        "/api/commands/nope/approve", headers={**key, **ORIGIN}, json={}).status_code == 404


@pytest.mark.parametrize(("method", "path"), [
    ("post", "/api/commands/nope/approve"), ("post", "/api/agents/nope/approve"),
    ("post", "/api/tool-calls/nope/approve"), ("post", "/api/file-changes/nope/approve"),
    ("post", "/api/file-changes/nope/revert"), ("post", "/api/discussions/nope/posts"),
    ("post", "/api/rooms/nope/posts"), ("post", "/api/providers/nope/default"),
    ("delete", "/api/providers/nope"), ("post", "/api/roles"), ("delete", "/api/roles/nope"),
    ("post", "/api/roles/nope/reset"), ("post", "/api/commands/nope/reject"),
    ("post", "/api/agents/nope/reject"), ("post", "/api/tool-calls/nope/reject"),
    ("post", "/api/file-changes/nope/reject"), ("delete", "/api/allowed-commands/nope"),
    ("post", "/api/conversations/nope/attachments/project"),
])
def test_an_approval_with_the_key_but_not_from_the_apps_own_page_is_refused(bare, method, path):
    """Security review 0.1.0, 9: past the key, a card's yes (an "always" too), a revert, a word
    in a room and a provider's or a role's change say they come from the app's own page."""
    app, client = bare
    key = {HEADER: app.state.page_key}
    body = {"json": {}} if method == "post" else {}
    for headers in ({}, {"Origin": "http://evil.example"}):
        answer = getattr(client, method)(path, headers={**key, **headers}, **body)
        assert answer.status_code == 403, (headers, answer.text)
    assert getattr(client, method)(path, headers={**key, **ORIGIN}, **body).status_code != 403


def test_the_key_in_the_address_serves_where_a_header_cannot_go(bare):
    app, client = bare
    key = app.state.page_key
    assert client.get(f"/api/projects?key={key}").status_code == 200
    # (`once`: the stream ends after its replay - it has no 404 for a conversation it does not know.)
    assert client.get(f"/api/conversations/nope/events?after=0&once=1&key={key}").status_code != 401
    assert client.get("/api/projects?key=wrong").status_code == 401


def test_what_has_a_door_of_its_own_needs_no_page_key(bare):
    _, client = bare
    assert client.get("/api/health").status_code == 200
    # (A test client is not "this machine", so the webhook says 403 - its own refusal.)
    assert client.post("/api/hooks/no-such-key", content=b"{}").status_code in (403, 404)
    # The status line's own key is asked for, not the page's.
    assert client.post("/api/limits/claude-session", json={}).status_code == 403
    assert client.get("/api/conversations/nope/views/v/index.html").status_code == 404
    assert client.get("/api/projects/nope/raw/a.png").status_code == 404


def test_each_start_makes_a_new_key(settings_env):
    one = create_app(load_settings(settings_env)).state.page_key
    two = create_app(load_settings(settings_env)).state.page_key
    assert one != two
    assert len(one) >= 32 and len(two) >= 32


def test_a_key_given_for_tests_never_reaches_a_child(monkeypatch, settings_env):
    given = "k" * 40
    for name, value in settings_env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("KOLONI_PAGE_KEY", given)
    settings = load_settings()
    assert "KOLONI_PAGE_KEY" not in os.environ
    assert given not in repr(settings)
    assert create_app(settings).state.page_key == given


def test_the_key_is_not_in_the_access_log(caplog):
    hide_webhook_keys()
    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        logging.getLogger("uvicorn.access").info(
            '%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "GET",
            "/api/conversations/c/events?after=3&key=s3cr3tPAGEkey", "1.1", 200)
    assert "s3cr3tPAGEkey" not in caplog.text
    assert "/api/conversations/c/events" in caplog.text


def test_the_window_shows_the_link_with_the_key(capsys, caplog):
    remove = show_link(8790, "s3cr3tPAGEkey")
    try:
        with caplog.at_level(logging.INFO, logger="uvicorn.error"):
            logging.getLogger("uvicorn.error").info(
                "Uvicorn running on %s://%s:%d (Press CTRL+C to quit)", "http", "127.0.0.1", 8790)
    finally:
        remove()
    shown = capsys.readouterr().out
    assert "http://127.0.0.1:8790/#key=s3cr3tPAGEkey" in shown
    # uvicorn's own line, the link without the key, is not offered to be clicked instead.
    assert "Uvicorn running on" not in caplog.text
    assert "s3cr3tPAGEkey" not in caplog.text


@pytest.mark.parametrize(("tty", "env", "opens"), [
    (False, None, False),  # tests, e2e, REA's copy: no terminal
    (None, None, False),  # pythonw: no stdout at all
    (True, "0", False),
    (True, None, True),
    (True, "1", True),
])
def test_only_a_start_from_a_terminal_opens_the_browser(monkeypatch, tty, env, opens):
    monkeypatch.setattr(sys, "stdout", None if tty is None else SimpleNamespace(isatty=lambda: tty))
    if env is None:
        monkeypatch.delenv("KOLONI_OPEN_BROWSER", raising=False)
    else:
        monkeypatch.setenv("KOLONI_OPEN_BROWSER", env)
    assert opens_browser() is opens


@pytest.mark.parametrize("asked", [False, True])
def test_the_browser_is_opened_once_with_a_code_never_the_key(monkeypatch, capsys, caplog, asked):
    opened = []
    monkeypatch.setattr(webbrowser, "open_new_tab", opened.append)
    remove = show_link(8790, "s3cr3tPAGEkey", (lambda: "c0de") if asked else None)
    try:
        with caplog.at_level(logging.INFO, logger="uvicorn.error"):
            logging.getLogger("uvicorn.error").info("Uvicorn running on http://127.0.0.1:8790")
            logging.getLogger("uvicorn.error").info("Application startup complete.")
    finally:
        remove()
    # A browser it starts keeps its address on its command line, where an agent can read it.
    assert opened == (["http://127.0.0.1:8790/#open=c0de"] if asked else [])
    assert "http://127.0.0.1:8790/#key=s3cr3tPAGEkey" in capsys.readouterr().out


def test_a_browser_that_fails_to_open_is_silent(monkeypatch, capsys, caplog):
    def broken(url):
        raise webbrowser.Error("no browser")
    monkeypatch.setattr(webbrowser, "open_new_tab", broken)
    remove = show_link(8790, "s3cr3tPAGEkey", lambda: "c0de")
    try:
        with caplog.at_level(logging.INFO, logger="uvicorn.error"):
            logging.getLogger("uvicorn.error").info("Uvicorn running on http://127.0.0.1:8790")
    finally:
        remove()
    assert "http://127.0.0.1:8790/#key=s3cr3tPAGEkey" in capsys.readouterr().out


def test_the_opened_pages_code_gives_the_key_once_in_time_to_the_own_page_only(bare):
    app, client = bare
    assert client.post("/api/open", json={"code": "x"}, headers=ORIGIN).status_code == 401  # none made
    code = open_code(app.state)
    assert len(code) >= 43  # 32 bytes
    # another origin, or none: refused, and the code is still good
    assert client.post("/api/open", json={"code": code},
                       headers={"Origin": "http://evil.example"}).status_code == 403
    assert client.post("/api/open", json={"code": code}).status_code == 403
    wrong = client.post("/api/open", json={"code": code[:-1] + "!"}, headers=ORIGIN)
    assert (wrong.status_code, wrong.json()) == (401, {"detail": PageKey.REFUSED})
    given = client.post("/api/open", json={"code": code}, headers=ORIGIN)
    assert (given.status_code, given.json()) == (200, {"key": app.state.page_key})
    assert client.post("/api/open", json={"code": code}, headers=ORIGIN).status_code == 401  # once
    # past its time: refused
    late = open_code(app.state)
    app.state.open_code = (late, time.monotonic() - 1)
    assert client.post("/api/open", json={"code": late}, headers=ORIGIN).status_code == 401
