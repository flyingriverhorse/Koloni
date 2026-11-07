"""Slice 42b beyond its acceptance set: how an address is read from a server's output, what a
command that keeps running may not do, and a real server on this machine stopped with Stop."""

import json
import sys
import time
import urllib.request
from types import SimpleNamespace

import httpx
import pytest

from app.command_runner import CommandRunner, port_of, preview_url
from app.config import load_settings
from app.db.models import Command
from app.main import create_app
from app.model_client import StepResult, ToolCallRequest
from app.tools import ToolError
from app.workspace import Workspace
from tests.fakes import Script, ScriptedExecutor, ScriptedModel
from tests.keyed import TestClient
from tests.test_agent_writes import wait_status
from tests.test_chat_flow import start, start_in_mode, text

ORIGIN = {"Origin": "http://127.0.0.1:8790"}


def serve(command="npm run dev", id="k1"):
    args = json.dumps({"command": command, "keep_running": True})
    return StepResult("", [ToolCallRequest(id, "run_command", args)], 1, 1)


def snap(client, cid):
    return client.get(f"/api/conversations/{cid}").json()


def until(check, timeout=10.0):
    deadline = time.monotonic() + timeout
    while not (found := check()):
        assert time.monotonic() < deadline, "not in time"
        time.sleep(0.05)
    return found


def test_an_address_is_read_as_printed_colours_aside_and_never_half():
    vite = "  \x1b[32m➜\x1b[39m  Local:   \x1b[36mhttp://localhost:\x1b[1m5173\x1b[22m/\x1b[39m\n"
    assert preview_url(vite, set()) == "http://localhost:5173/"
    assert preview_url(" * Running on http://[::1]:5000\n", set()) == "http://[::1]:5000"
    assert preview_url("at http://127.0.0.1:51", set()) is None  # the rest of it may follow
    assert preview_url("http://127.0.0.1:8790/ then http://127.0.0.1:3000/\n", {8790}) == (
        "http://127.0.0.1:3000/")
    assert preview_url("http://localhost.evil.com:3000/ http://10.0.0.2:3000/\n", set()) is None


def test_a_rule_does_not_cover_a_server_and_none_is_offered(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([Script(["ok"]), Script(["Local: http://127.0.0.1:3000\n"])])
    client, _model = make_client(
        [StepResult("", [ToolCallRequest("k0", "run_command", '{"command": "npm run dev"}')], 1, 1),
         text("ran"), serve(), text("up")], executor=executor)
    cid, run_id = start(client, project_dir)
    first = wait_status(client, cid, "waiting_approval")["commands"][0]
    client.post(f"/api/commands/{first['id']}/approve", json={"remember": True})
    wait_run(client, cid, run_id)
    client.post(f"/api/conversations/{cid}/messages", json={"content": "serve it"})
    asked = wait_status(client, cid, "waiting_approval")["commands"][1]
    assert (asked["status"], asked["keep_running"], asked["suggested_prefix"]) == (
        "proposed", True, "")


def test_in_docker_it_says_so_and_starts_nothing(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([])
    client, model = make_client([serve(), text("ok")], executor=executor)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    client.patch(f"/api/projects/{pid}", json={"exec_location": "docker", "docker_image": "alpine"})
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={"permission_mode": "full_auto"}, headers=ORIGIN)
    run_id = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "serve"}).json()["run"]["id"]
    done = wait_run(client, cid, run_id)
    assert done["commands"] == [] and executor.started == []
    assert "only on this machine" in model.calls[1][-1]["content"]


def test_the_next_turn_goes_on_while_it_runs_and_putting_the_chat_away_stops_it(
    make_client, wait_run, project_dir, gate
):
    executor = ScriptedExecutor([Script(["Local: http://127.0.0.1:3000\n"], hold=gate)])
    client, _model = make_client([serve(), text("up"), text("still here")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    wait_run(client, cid, run_id)
    second = client.post(f"/api/conversations/{cid}/messages", json={"content": "and?"}).json()
    after = wait_run(client, cid, second["run"]["id"])
    assert after["commands"][0]["status"] == "running"
    assert client.patch(f"/api/conversations/{cid}", json={"archived": True},
                        headers=ORIGIN).status_code == 200
    until(lambda: snap(client, cid)["commands"][0]["status"] == "killed")
    assert executor.killed == [after["commands"][0]["id"]]
    assert client.post(f"/api/commands/{after['commands'][0]['id']}/stop",
                       headers=ORIGIN).status_code == 409


def test_one_running_when_koloni_closes_is_recorded_so(settings_env, project_dir, gate):
    executor = ScriptedExecutor([Script(["Local: http://127.0.0.1:3000\n"], hold=gate)])
    app = create_app(load_settings(settings_env), model=ScriptedModel([serve(), text("up")]),
                     executors=executor.factory)
    with TestClient(app, base_url="http://127.0.0.1:8790") as client:
        cid, _run_id = start_in_mode(client, project_dir, "full_auto")
        until(lambda: snap(client, cid)["runs"][0]["status"] == "completed")
    with app.state.session_factory() as session:
        (left,) = session.query(Command).all()
        assert (left.status, left.keep_running) == ("interrupted", True)
    assert executor.killed == [left.id]


SERVER = """
import http.server, sys
class Page(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        if "deny" in sys.argv:
            self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(b"served")
    def log_message(self, *args):
        pass
server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Page)
print(f"Local: http://127.0.0.1:{server.server_address[1]}/", flush=True)
server.serve_forever()
"""


def test_a_real_server_is_shown_asked_whether_it_may_be_framed_and_stopped(
    make_client, wait_run, project_dir
):
    (project_dir / "serve.py").write_text(SERVER)
    python = f'& "{sys.executable}"' if sys.platform == "win32" else f'"{sys.executable}"'
    client, _model = make_client(
        [serve(f"{python} -u serve.py"), serve(f"{python} -u serve.py deny", "k2"), text("up")])
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    served, denied = wait_run(client, cid, run_id, timeout=30)["commands"]
    try:
        assert urllib.request.urlopen(served["preview_url"], timeout=5).read() == b"served"
        frame = client.get(f"/api/commands/{served['id']}/frame").json()
        assert frame == {"frameable": True}
        assert client.get(f"/api/commands/{denied['id']}/frame").json() == {"frameable": False}
    finally:
        for command in (served, denied):
            client.post(f"/api/commands/{command['id']}/stop", headers=ORIGIN)
    until(lambda: {c["status"] for c in snap(client, cid)["commands"]} == {"killed"}, 30)

    def gone():
        try:
            urllib.request.urlopen(served["preview_url"], timeout=2)
        except OSError:
            return True
        return False

    until(gone, 10)


def test_the_frame_check_follows_redirects_on_this_machine_only(
    make_client, project_dir, gate, monkeypatch
):
    """K-42b: a redirect to a page that refuses a frame is read as refused; one off this
    machine is not followed - nothing is asked of it - and is not known."""
    executor = ScriptedExecutor([Script(["Local: http://127.0.0.1:3000/\n"], hold=gate)])
    client, _model = make_client([serve(), text("up")], executor=executor)
    cid, _run_id = start_in_mode(client, project_dir, "full_auto")
    command = until(lambda: next(
        (c for c in snap(client, cid)["commands"] if c["preview_url"]), None))
    asked, pages = [], {}

    def answer(request):
        asked.append(str(request.url))
        status, headers = pages[request.url.path]
        return httpx.Response(status, headers=headers)

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(
        **kw, transport=httpx.MockTransport(answer)))
    frame = lambda: client.get(f"/api/commands/{command['id']}/frame").json()  # noqa: E731
    pages.update({"/": (302, {"Location": "/in"}), "/in": (200, {"X-Frame-Options": "DENY"})})
    assert frame() == {"frameable": False}
    assert asked == ["http://127.0.0.1:3000/", "http://127.0.0.1:3000/in"]
    asked.clear()
    pages["/"] = (302, {"Location": "http://example.com/in"})
    assert frame() == {"frameable": None}
    assert asked == ["http://127.0.0.1:3000/"]
    pages["/"] = (302, {"Location": "/"})  # round and round
    assert frame() == {"frameable": None}


def test_a_linked_address_and_one_printed_last_are_read_whole():
    # (OSC 8: a terminal hyperlink round the address, as newer dev servers print it)
    linked = "Local: \x1b]8;;http://localhost:5173/\x1b\\http://localhost:5173/\x1b]8;;\x1b\\\n"
    assert preview_url(linked, set()) == "http://localhost:5173/"
    assert preview_url("ready at http://127.0.0.1:4000", set()) is None  # more may follow...
    assert preview_url("ready at http://127.0.0.1:4000" + "\n", set()) == "http://127.0.0.1:4000"


def test_a_model_server_on_its_scheme_s_own_port_is_closed_too():
    assert port_of("http://127.0.0.1/v1") == 80 and port_of("https://localhost/v1") == 443
    assert port_of("http://127.0.0.1:1234/v1") == 1234 and port_of("http://[::1:x/") is None


def test_an_address_printed_last_with_nothing_after_it_is_taken_once_quiet(
    make_client, wait_run, project_dir, gate
):
    executor = ScriptedExecutor([Script(["ready at http://127.0.0.1:4000"], hold=gate)])
    client, model = make_client([serve(), text("up")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    (command,) = wait_run(client, cid, run_id)["commands"]
    assert command["preview_url"] == "http://127.0.0.1:4000"
    assert "serving http://127.0.0.1:4000" in model.calls[1][-1]["content"]


def test_putting_the_chat_away_turns_down_a_server_still_asked_about(make_client, project_dir):
    executor = ScriptedExecutor([Script(["Local: http://127.0.0.1:3000\n"])])
    client, _model = make_client([serve(), text("ok")], executor=executor)
    cid, _run_id = start(client, project_dir)
    wait_status(client, cid, "waiting_approval")
    client.patch(f"/api/conversations/{cid}", json={"archived": True}, headers=ORIGIN)
    until(lambda: snap(client, cid)["commands"][0]["status"] == "rejected")
    assert executor.started == []


@pytest.mark.parametrize("why", ["sub-agent", "copy", "unwatched", "lead"])
def test_no_server_for_a_sub_agent_in_a_working_copy_nor_a_turn_nobody_watches(tmp_path, why):
    project = SimpleNamespace(exec_location="host", root_path=str(tmp_path))
    (tmp_path / "copy").mkdir()
    ws = Workspace(tmp_path / "copy" if why in ("copy", "lead") else tmp_path)
    runner = CommandRunner(None, None, None, None)

    async def where():
        return ws

    with pytest.raises(ToolError) as refused:
        runner._may_serve(None, "c", project, ws, why != "unwatched",
                          where if why == "sub-agent" else None, lead=why == "lead")
    # (B-311 review: a recipe's Lead in its copy has nobody above it to start the server.)
    assert ("nobody watches" if why == "unwatched" else "the user's Take in" if why == "lead"
            else "not in a working copy") in str(refused.value)


def test_koloni_s_port_and_every_model_server_s_are_closed(client):
    from app.db.models import Provider

    with client.app.state.session_factory() as session:
        session.add(Provider(name="lm", kind="openai_compat", base_url="http://127.0.0.1:5555/v1"))
        session.add(Provider(name="plain", kind="openai_compat", base_url="http://localhost/v1"))
        session.commit()
    closed = client.app.state.runner.commands.closed_ports()
    assert {5555, 80, 9, client.app.state.settings.port} <= closed


def test_an_api_s_port_out_there_is_not_closed(client):
    """B-361: an API's https base_url closed 443, and with it every https site to the browser."""
    from app.db.models import Provider

    with client.app.state.session_factory() as session:
        session.add(Provider(name="api", kind="anthropic", base_url="https://api.anthropic.com"))
        session.commit()
    assert 443 not in client.app.state.runner.commands.closed_ports()
