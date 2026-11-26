"""Slice 20a's acceptance set: a desktop notification (0.1.10: the only place a notification
goes), a host allowed by hand, and secrets written in an address or a body. Written before the
code.

No test touches the real network or the real desktop: `app.web.raw`, `app.web.resolve` and
`app.web.desktop` (the one place a desktop notification is shown from) are stood in for.
"""

import json

import pytest

import app.web

if not hasattr(app.web, "desktop"):  # written before the code: skipped until it exists
    pytest.skip("slice 20a is not built yet", allow_module_level=True)

from tests.test_chat_flow import text  # noqa: E402
from tests.test_parallel import until  # noqa: E402
from tests.test_spawn import call, step  # noqa: E402
from tests.test_web_tool_scenarios import Net, get, go, results, setup  # noqa: E402

SAYS = call("notify", {"message": 'the tests <pass> & "done"'}, "n")


def desk(monkeypatch):
    shown = []
    monkeypatch.setattr(app.web, "has_desktop", lambda: True)
    monkeypatch.setattr(app.web, "desktop", lambda title, said: shown.append((title, said)))
    return shown


def sent(monkeypatch):
    """Stand in for the network, keeping what was sent: (url, headers, body)."""
    Net(monkeypatch)
    out = []

    async def raw(method, url, headers, body, ip):
        out.append((url, {name.lower(): value for name, value in headers.items()}, body))
        return app.web.Raw(200, {"content-type": "text/plain"}, b"ok")

    monkeypatch.setattr(app.web, "raw", raw)
    return out


def test_a_desktop_notification_needs_no_address(make_client, wait_run, project_dir, monkeypatch):
    shown, out = desk(monkeypatch), sent(monkeypatch)
    client, model, pid, cid = setup(
        make_client, project_dir, [step(SAYS), text("done")], project={"notify_desktop": True}
    )
    snap = wait_run(client, cid, go(client, cid)["id"])
    ((status, said),) = results(snap, "notify")
    assert status == "succeeded" and "desktop" in said
    ((title, message),) = shown
    assert message == 'the tests <pass> & "done"' and "KOLON" in title  # as said, whole
    assert out == []
    assert client.get(f"/api/projects/{pid}").json()["notify_desktop"] is True


def test_a_desktop_that_cannot_show_it_is_said_and_nothing_is_made_up(
    make_client, wait_run, project_dir, monkeypatch
):
    def desktop(title, said):
        raise app.web.WebError("a desktop notification is not available on this system")

    monkeypatch.setattr(app.web, "has_desktop", lambda: True)
    monkeypatch.setattr(app.web, "desktop", desktop)
    sent(monkeypatch)
    client, model, pid, cid = setup(
        make_client, project_dir, [step(SAYS), text("done")], project={"notify_desktop": True}
    )
    snap = wait_run(client, cid, go(client, cid)["id"])
    ((status, said),) = results(snap, "notify")
    assert status == "failed" and "not available" in said


def test_a_host_allowed_by_hand_is_asked_without_a_card(
    make_client, wait_run, project_dir, monkeypatch
):
    net = Net(monkeypatch, {"example.com": (200, "text/plain", "ok")})
    client, model, pid, cid = setup(
        make_client,
        project_dir,
        [
            step(get("https://example.com/a", "a")),
            step(get("https://other.example.org/", "b")),
            text("done"),
        ],
        permission_mode="ask",
    )
    rules = f"/api/conversations/{cid}/allowed-web"
    assert client.post(rules, json={"host": "example.com"}).status_code == 200
    assert client.post(rules, json={"host": "example.com"}).status_code == 200  # once on record
    for inside in ("127.0.0.1", "localhost", "http://10.0.0.5:8080", "[::1]"):
        assert client.post(rules, json={"host": inside}).status_code == 422, inside
    assert (
        client.post(rules, json={"host": "example.com"}, headers={"Origin": ""}).status_code == 403
    )  # the user's own page only
    run_id = go(client, cid)["id"]
    snap = until(client, cid, lambda s: [w for w in s["web_requests"] if w["status"] == "proposed"])
    (asked,) = snap["web_requests"]  # the other host is still asked about
    assert asked["host"] == "other.example.org"
    assert [rule["host"] for rule in snap["allowed_web"]] == ["example.com"]
    assert ("GET", "https://example.com/a") in [(m, u) for m, u, _ip in net.asked]
    client.post(f"/api/web-requests/{asked['id']}/reject")
    wait_run(client, cid, run_id)


def test_a_secret_written_in_the_address_or_the_body_is_not_kept(
    make_client, wait_run, project_dir, monkeypatch
):
    out = sent(monkeypatch)
    asked = call(
        "http_request",
        {
            "method": "POST",
            "url": "https://example.com/hook?api_key=K-11-SECRET&q=tea",
            "body": json.dumps(
                {
                    "password": "hunter2",
                    "note": "two cups",
                    "nested": {"Access_Token": "T-22-SECRET"},
                }
            ),
            "headers": {"Content-Type": "application/json"},
        },
        "p",
    )
    client, model, pid, cid = setup(
        make_client, project_dir, [step(asked), text("done")], permission_mode="ask"
    )
    run_id = go(client, cid)["id"]
    snap = until(client, cid, lambda s: s["web_requests"])
    card = json.dumps(snap["web_requests"])
    assert "K-11-SECRET" in card  # before the user decides, the card shows what goes
    client.post(
        f"/api/web-requests/{snap['web_requests'][0]['id']}/approve", json={"remember": False}
    )
    snap = wait_run(client, cid, run_id)
    assert results(snap, "http_request")[0][0] == "succeeded"
    ((url, _headers, went),) = out  # what went is what was written
    assert "api_key=K-11-SECRET" in url and json.loads(went)["password"] == "hunter2"
    kept = json.dumps(snap)
    for secret in ("K-11-SECRET", "hunter2", "T-22-SECRET"):
        assert secret not in kept, secret
    assert "q=tea" in kept and "two cups" in kept  # the rest is as it was written
