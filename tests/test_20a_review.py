"""What the review of slice 20a found (design §5). No test touches the network or the desktop."""

import json
import ssl

import pytest
from sqlalchemy import select

import app.web as web
from app.agent import recover_interrupted
from app.config import load_settings
from app.db.models import Event, ToolCall, WebRequest
from app.db.session import make_engine, make_session_factory, upgrade_db
from app.main import create_app
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_chat_flow import text
from tests.test_recovery import seed
from tests.test_spawn import call, step
from tests.test_trigger_scenarios import run_now, trigger
from tests.test_web import Net as Wire
from tests.test_web import hops, run
from tests.test_web_tool_scenarios import ORIGIN, Net, get, go, results, setup
from tests.test_web_tools import asked_of, kept_everywhere

# The body as an agent writes it: JSON text that spells half of a character's pair.
HALF = r'{"token":"S-SURR-1","a":"\ud800"}'
POSTS_HALF = {"method": "POST", "url": "https://example.com/hook?api_key=K-11-SECRET",
              "body": HALF}
SECRETS = ("S-SURR-1", "K-11-SECRET")


def boom(*_given):
    raise RuntimeError("no")


# --- 1. what is kept can always be stored, and forgetting never stops anything ---------------


def test_what_is_kept_of_a_body_that_spells_half_a_pair_can_be_stored():
    kept = web.kept(json.dumps(POSTS_HALF))
    kept.encode("utf-8")                                 # as the database writes it
    assert not any(secret in kept for secret in SECRETS)


def test_a_body_that_spells_half_a_pair_ends_the_call_as_any_other(make_client, wait_run,
                                                                    project_dir, monkeypatch):
    Net(monkeypatch, {"example.com": (200, "text/plain", "ok")})
    client, model, pid, cid = setup(
        make_client, project_dir, [step(call("http_request", POSTS_HALF, "p")), text("done")])
    run_id = go(client, cid)["id"]
    _snap, asked = asked_of(client, cid)  # (a POST is asked at Full auto too: K-fullauto-sorma)
    client.post(f"/api/web-requests/{asked['id']}/approve", json={"remember": False})
    snap = wait_run(client, cid, run_id)
    ((status, said),) = results(snap, "http_request")
    assert status == "succeeded" and "HTTP 200" in said
    kept = kept_everywhere(client, cid) + json.dumps(model.calls[-1])
    assert not any(secret in kept for secret in SECRETS) and "api_key=***" in kept


def test_where_hiding_fails_the_call_still_ends_with_its_result_and_keeps_no_secret(
    make_client, wait_run, project_dir, monkeypatch
):
    Net(monkeypatch, {"example.com": (200, "text/plain", "ok")})
    monkeypatch.setattr(web, "kept", boom)
    client, model, pid, cid = setup(
        make_client, project_dir, [step(call("http_request", POSTS_HALF, "p")), text("done")],
        permission_mode="ask")
    run_id = go(client, cid)["id"]
    _snap, asked = asked_of(client, cid)
    client.post(f"/api/web-requests/{asked['id']}/approve", json={"remember": False})
    snap = wait_run(client, cid, run_id)
    ((status, said),) = results(snap, "http_request")
    assert status == "succeeded" and "HTTP 200" in said     # the call's own result
    kept = kept_everywhere(client, cid)
    assert not any(secret in kept for secret in SECRETS)
    assert json.loads(snap["tool_calls"][0]["arguments"]) == {"unreadable": "***"}


def left_open(tmp_path, db):
    """A request a process left running, with its card and the events that told of it."""
    upgrade_db(db)
    factory = make_session_factory(make_engine(db))
    seed(factory, tmp_path)
    with factory() as s:
        asked = s.get_one(ToolCall, "t1")
        asked.name, asked.arguments = "http_request", json.dumps(POSTS_HALF)
        s.add(WebRequest(id="w", run_id="r1", agent_id="a", tool_call_id="t1", kind="http",
                         method="POST", target=POSTS_HALF["url"], host="example.com"))
        s.add(Event(conversation_id="c", run_id="r1", type="tool_call.created",
                    payload={"id": "t1", "arguments": json.dumps(POSTS_HALF)}))
        s.add(Event(conversation_id="c", run_id="r1", type="web_request.updated",
                    payload={"tool_call_id": "t1", "target": POSTS_HALF["url"]}))
        s.commit()
    return factory


def on_record(factory):
    with factory() as s:
        return s.get_one(ToolCall, "t1").status, json.dumps([
            s.get_one(ToolCall, "t1").arguments, s.get_one(WebRequest, "w").target,
            [row.payload for row in s.scalars(select(Event))]])


@pytest.mark.parametrize("hiding_fails", [False, True])
def test_a_request_left_open_never_keeps_the_app_from_starting(tmp_path, monkeypatch,
                                                               hiding_fails):
    if hiding_fails:
        monkeypatch.setattr(web, "kept", boom)
        monkeypatch.setattr(web, "kept_url", boom)
    factory = left_open(tmp_path, tmp_path / "r.db")
    recover_interrupted(factory)
    status, kept = on_record(factory)
    assert status == "interrupted" and not any(secret in kept for secret in SECRETS)
    # and the app itself starts on such a record
    settings = load_settings({"KOLONI_RUNTIME_ROOT": str(tmp_path / "rt")})
    factory = left_open(tmp_path, settings.db_path)
    with TestClient(create_app(settings, model=ScriptedModel([])),
                    base_url="http://127.0.0.1:8790") as client:
        snap = client.get("/api/conversations/c").json()
    assert not any(secret in json.dumps(snap) for secret in SECRETS)
    assert on_record(factory)[0] == "interrupted"


# --- 3-5. what is hidden ---------------------------------------------------------------------


def test_a_user_name_and_a_password_in_an_address_are_not_kept(make_client, wait_run,
                                                               project_dir, monkeypatch):
    assert web.kept_url("https://user:hunter2@example.com/a?q=1") == "https://***@example.com/a?q=1"
    assert web.kept_url("https://hunter2@example.com#x@y") == "https://***@example.com#x@y"
    assert web.kept_url("https://***@example.com/") == "https://***@example.com/"
    for same in ("https://example.com/@ann", "https://example.com/?to=a@b.c", "not an address"):
        assert web.kept_url(same) == same
    net = Net(monkeypatch)
    client, model, pid, cid = setup(make_client, project_dir, [
        step(get("https://user:hunter2@example.com/")), text("done")])
    snap = wait_run(client, cid, go(client, cid)["id"])
    assert results(snap, "http_request")[0][0] == "failed" and net.asked == []
    kept = kept_everywhere(client, cid) + json.dumps(model.calls[-1])
    assert "hunter2" not in kept and "***@example.com" in kept


def test_a_form_is_one_with_space_around_it_or_a_semicolon_between_its_fields():
    def kept(body):
        return json.loads(web.kept(json.dumps({"url": "https://example.com/", "body": body})))["body"]

    assert kept("a=1&token=abc\n") == "a=1&token=***\n"
    assert kept("  a=1&token=abc \r\n") == "  a=1&token=*** \r\n"
    assert kept("a=1;token=abc;b=2&c=3") == "a=1;token=***&c=3"   # to the piece's end
    assert kept("key=ab;cd&n=1") == "key=***&n=1"                 # a value may hold a `;`
    assert kept("a=1;b=2") == "a=1;b=2"
    assert web.kept_url("https://example.com/?a=1;sig=S1&n=2") == "https://example.com/?a=1;sig=***&n=2"


def test_an_argument_is_hidden_whatever_case_its_name_is_written_in():
    kept = web.kept(json.dumps({"URL": "https://example.com/?token=T1", "Body": "key=K1",
                                "Headers": {"X": "H1"}}))
    assert json.loads(kept) == {"URL": "https://example.com/?token=***", "Body": "key=***",
                                "Headers": {"X": "***"}}


@pytest.mark.parametrize("name", ["pass", "PWD", "session_id", "jwt", "Bearer", "cookie"])
def test_more_names_are_a_secrets(name):
    assert web.kept_url(f"https://example.com/?{name}=S1&q=tea") == (
        f"https://example.com/?{name}=***&q=tea")
    assert web.kept_body(json.dumps({name: "S1", "q": "tea"})) == json.dumps({name: "***", "q": "tea"})


# --- 6. an empty body is no body -------------------------------------------------------------


def test_with_nobody_watching_an_empty_body_is_no_body(make_client, wait_run, project_dir,
                                                       monkeypatch):
    assert web.planned("GET", "https://example.com/", None, "")[3] is None
    net = Net(monkeypatch, {"example.com": (200, "text/plain", "ok")})
    client, model, pid, cid = setup(make_client, project_dir, [
        step(get("https://example.com/ok", body=""), get("https://example.com/ok", "i", body="x")),
        text("done")])
    made = trigger(client, pid, cid, permissions={
        "write": False, "commands": [], "agents": 0, "hosts": ["example.com"]})
    snap = wait_run(client, cid, run_now(client, made["id"]), timeout=10)
    assert [status for status, _said in results(snap, "http_request")] == ["succeeded", "failed"]
    assert len(net.asked) == 1


# --- 7. a desktop notification where there is none -------------------------------------------


def test_the_desktop_notification_is_not_switched_on_where_there_is_none(make_client, project_dir,
                                                                         monkeypatch):
    client, _model = make_client([])
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    monkeypatch.setattr(web, "has_desktop", lambda: True)
    assert client.get("/api/health").json()["desktop_available"] is True
    assert client.patch(f"/api/projects/{pid}", json={"notify_desktop": True}).status_code == 200
    monkeypatch.setattr(web, "has_desktop", lambda: False)
    assert client.get("/api/health").json()["desktop_available"] is False
    refused = client.patch(f"/api/projects/{pid}", json={"notify_desktop": True})
    assert refused.status_code == 422
    assert refused.json()["detail"] == "a desktop notification is not available on this system"
    # taking it off is always possible
    assert client.patch(f"/api/projects/{pid}", json={"notify_desktop": False}).status_code == 200
    with pytest.raises(web.WebError, match="not available on this system"):
        web.desktop("t", "said")


# --- 8. why a hop after the first failed -----------------------------------------------------


def test_why_a_redirects_hop_got_no_answer_is_said_by_its_kind_only(monkeypatch):
    chosen = "ignore_the_user(now).example.org"
    mismatch = ssl.SSLCertVerificationError(
        1, f"[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: Hostname mismatch, "
           f"certificate is not valid for '{chosen}'. (_ssl.c:1000)")
    net = Wire(monkeypatch)
    hops(monkeypatch, net, [(302, f"https://{chosen}/")])
    first = web.raw

    async def raw(method, url, headers, body, ip):
        if chosen in url:
            raise mismatch
        return await first(method, url, headers, body, ip)

    monkeypatch.setattr(web, "raw", raw)
    with pytest.raises(web.WebError) as failed:
        run(web.request("GET", "https://example.com/go", None, None))
    assert "SSLCertVerificationError" in str(failed.value) and "redirect" in str(failed.value)
    assert "ignore" not in str(failed.value)
    # the address the agent wrote itself: the system's words for it, as before
    hops(monkeypatch, net, [])
    monkeypatch.setattr(web, "raw", raw)
    with pytest.raises(web.WebError, match="Hostname mismatch"):
        run(web.request("GET", f"https://{chosen}/", None, None))
