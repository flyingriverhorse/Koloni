"""K-drawio: a draw.io diagram of the project as a picture beside it - by an agent's
diagram_image (the headless browser of slice 51 on about:blank, which loads nothing; the
stand-in where a test names it) and by the user's "Save as PNG / SVG" in the Workspace."""

import asyncio
import base64
import functools
import hashlib
import http.server
import os
import threading

import pytest
import websockets
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import browser, diagram, views
from app.main import _serve_frontend
from app.workspace import Workspace, WorkspaceError
from tests.test_browser import FAKE, _calls
from tests.test_chat_flow import start_in_mode, text
from tests.test_spawn import begin, call, step
from tests.test_trigger_scenarios import finished, results, run_now, setup, trigger

FLOW = ('<mxfile><diagram id="a" name="P"><mxGraphModel><root><mxCell id="0"/>'
        '<mxCell id="1" parent="0"/><mxCell id="2" value="Start &lt;b&gt;here&lt;/b&gt;" '
        'style="rounded=1;html=1;" vertex="1" parent="1"><mxGeometry x="0" y="0" width="120" '
        'height="60" as="geometry"/></mxCell>{more}</root></mxGraphModel></diagram></mxfile>')
PNG = diagram.PNG + b"rest"
OWN = {"Origin": "http://127.0.0.1:8790"}


def test_a_diagram_is_known_by_its_name_and_its_picture_goes_beside_it():
    assert views.kind_of("docs/Flow.DRAWIO") == views.kind_of("a.drawio.xml") == "drawio"
    assert views.kind_of("b.dio") == "drawio" and views.kind_of("c.xml") is None
    assert diagram.picture_of("docs/flow.drawio", "png") == "docs/flow.png"
    assert diagram.picture_of("docs/flow.drawio.xml", "svg") == "docs/flow.svg"
    assert diagram.picture_of("Map.DIO", "png") == "Map.png"


def test_a_picture_is_written_over_an_earlier_one_and_what_is_not_one_is_refused(tmp_path):
    ws = Workspace(str(tmp_path))
    (tmp_path / "docs").mkdir()
    assert diagram.write_picture(ws, "docs/flow.drawio", "png", PNG) == "docs/flow.png"
    assert diagram.write_picture(ws, "docs/flow.drawio", "png", PNG + b"2") == "docs/flow.png"
    assert (tmp_path / "docs" / "flow.png").read_bytes() == PNG + b"2"
    svg = b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg"/>'
    assert diagram.write_picture(ws, "docs/flow.drawio.xml", "svg", svg) == "docs/flow.svg"
    for rel, format, data, why in (
        ("docs/flow.drawio", "png", svg, "not a PNG"),
        ("docs/flow.drawio", "svg", PNG, "not a SVG"),
        ("docs/flow.drawio", "gif", PNG, "png"),
        ("hello.py", "png", PNG, "not a draw.io file"),
        (".env.drawio", "png", PNG, "not written here"),
        (".claude/flow.drawio", "png", PNG, "not written here"),
        ("../out.drawio", "png", PNG, "outside|never opened|not written"),
        ("docs/flow.drawio", "png", PNG + bytes(diagram.MAX_PICTURE), "larger than 20 MB"),
    ):
        with pytest.raises(WorkspaceError, match=why):
            diagram.write_picture(ws, rel, format, data)
    assert not (tmp_path / ".env.png").exists() and not (tmp_path / ".claude").exists()


def test_a_picture_is_never_written_through_a_link_on_its_way(tmp_path):
    ws = Workspace(str(tmp_path))
    (tmp_path / "docs").mkdir()
    (tmp_path / "src").mkdir()
    victim = tmp_path / "src" / "main.py"
    victim.write_text("print('kept')", encoding="utf-8")
    try:
        os.symlink(victim, tmp_path / "docs" / "flow.png")
    except OSError:
        pytest.skip("this machine makes no symbolic link for this user (Windows without "
                    "Developer Mode)")
    with pytest.raises(WorkspaceError, match="a link"):
        diagram.write_picture(ws, "docs/flow.drawio", "png", PNG)
    assert victim.read_text(encoding="utf-8") == "print('kept')"


@pytest.mark.skipif(os.name != "nt", reason="a junction is Windows' own")
def test_a_picture_is_never_written_through_a_junction_for_its_folder(tmp_path):
    import _winapi

    ws = Workspace(str(tmp_path))
    (tmp_path / "src").mkdir()
    _winapi.CreateJunction(str(tmp_path / "src"), str(tmp_path / "docs"))
    with pytest.raises(WorkspaceError, match="a link"):
        diagram.write_picture(ws, "docs/flow.drawio", "png", PNG)
    assert not (tmp_path / "src" / "flow.png").exists()


def _project(project_dir):
    (project_dir / "docs").mkdir()
    (project_dir / "docs" / "flow.drawio").write_text(FLOW.format(more=""), encoding="utf-8")
    (project_dir / ".env.drawio").write_text(FLOW.format(more=""), encoding="utf-8")


def test_the_tool_draws_on_the_stand_in_writes_beside_it_unasked_and_refuses_the_rest(
        monkeypatch, make_client, wait_run, project_dir, tmp_path):
    monkeypatch.setenv("KOLONI_BROWSER_FAKE", FAKE)
    _project(project_dir)
    (tmp_path / "outside.drawio").write_text(FLOW.format(more=""), encoding="utf-8")
    client, _model = make_client([
        step(call("diagram_image", {"path": "docs/flow.drawio"}, "d1")),
        step(call("diagram_image", {"path": "docs/flow.drawio", "format": "svg"}, "d2")),
        step(call("diagram_image", {"path": "hello.py"}, "d3")),
        step(call("diagram_image", {"path": ".env.drawio"}, "d4")),
        step(call("diagram_image", {"path": str(tmp_path / "outside.drawio")}, "d5")),
        step(call("diagram_image", {"path": "docs/flow.drawio", "format": "gif"}, "d6")),
        text("done")])
    # At Ask: no card - the user gave the tool by role.
    cid, run_id = start_in_mode(client, project_dir, "ask")
    snap = wait_run(client, cid, run_id, timeout=15)
    # (In the order they were called: d1 ... d6.)
    made = {f"d{n}": t for n, t in enumerate(
        client.get(f"/api/conversations/{cid}").json()["tool_calls"], 1)}
    said = {key: made[key]["result"] for key in made}
    assert said["d1"] == ("drew docs/flow.drawio as docs/flow.png (66 bytes), beside it; the "
                          "user sees it there")
    # (No card asked for it: it is put in the view beside the chat.)
    shown = {(v["path"], v["kind"]) for v in client.get(f"/api/conversations/{cid}/views").json()}
    assert {("docs/flow.png", "image"), ("docs/flow.svg", "svg")} <= shown
    assert (project_dir / "docs" / "flow.png").read_bytes().startswith(diagram.PNG)
    assert said["d2"].startswith("drew docs/flow.drawio as docs/flow.svg (")
    assert (project_dir / "docs" / "flow.svg").read_bytes().startswith(b"<svg")
    assert "only a draw.io file of the project is drawn" in said["d3"]
    assert "is a secret file" in said["d4"] and not (project_dir / ".env.png").exists()
    assert made["d5"]["status"] in ("failed", "denied") and not (tmp_path / "outside.png").exists()
    assert said["d6"] == 'error: format is "png" or "svg"'
    assert next(r for r in snap["runs"] if r["id"] == run_id)["status"] == "completed"
    # (The stand-in's profile is gone with it.)
    assert not list((project_dir / ".koloni" / "tmp" / "browser" / "diagram").glob("profile-*"))


def test_no_chrome_or_edge_is_said_with_what_the_user_can_do(
        monkeypatch, make_client, wait_run, project_dir):
    _project(project_dir)
    monkeypatch.setattr(browser, "find_browser", lambda: None)
    client, _model = make_client([
        step(call("diagram_image", {"path": "docs/flow.drawio"}, "d1")), text("done")])
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    wait_run(client, cid, run_id)
    assert _calls(client, cid)["diagram_image"]["result"] == f"error: {diagram.NO_BROWSER}"


def test_an_orchestrator_that_hands_code_on_is_not_given_it_and_a_trigger_writes_only_if_let(
        monkeypatch, make_client, wait_run, project_dir):
    monkeypatch.setenv("KOLONI_BROWSER_FAKE", FAKE)
    _project(project_dir)
    draw = step(call("diagram_image", {"path": "docs/flow.drawio"}, "d1"))
    # (slice 48: a new conversation's Lead hands every change to files on)
    client, model = make_client([draw, text("done")])
    cid, run_id = begin(client, project_dir, mode="full_auto")
    wait_run(client, cid, run_id)
    assert "diagram_image" not in [t["function"]["name"] for t in model.tool_args[0]]
    assert _calls(client, cid)["diagram_image"]["status"] == "failed"
    assert not (project_dir / "docs" / "flow.png").exists()
    # A trigger's turn: refused where the trigger may not write, drawn where it may.
    for may, drawn in ((False, False), (True, True)):
        client, _model, pid, cid = setup(make_client, project_dir, {"Lead": [draw, text("done")]})
        made = trigger(client, pid, cid, permissions={"write": may, "commands": [], "agents": 0})
        run_id = run_now(client, made["id"])
        snap = finished(client, wait_run, cid, run_id, timeout=20)
        ((_name, status, said),) = [one for one in results(snap, run_id)
                                    if one[0] == "diagram_image"]
        assert (status == "succeeded") is drawn, said
        assert (project_dir / "docs" / "flow.png").exists() is drawn


def test_the_users_save_writes_beside_the_diagram_from_the_apps_own_page_only(
        client, project_dir):
    _project(project_dir)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    url = f"/api/projects/{pid}/diagram-picture"
    body = {"path": "docs/flow.drawio", "format": "png", "data": base64.b64encode(PNG).decode()}
    assert client.post(url, json=body).status_code == 403  # (no Origin: not the app's page)
    answer = client.post(url, json=body, headers=OWN)
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"path": "docs/flow.png"}
    assert (project_dir / "docs" / "flow.png").read_bytes() == PNG
    for wrong, status in (
        ({"data": "not base64!"}, 422),
        ({"data": base64.b64encode(b"<svg/>").decode()}, 422),
        ({"path": "hello.py"}, 422),
        ({"path": ".env.drawio"}, 404),
        ({"path": "../x.drawio"}, 400),
        ({"path": "docs/none.drawio"}, 404),  # (no picture of a diagram that is not there)
    ):
        assert client.post(url, json={**body, **wrong}, headers=OWN).status_code == status, wrong


def test_a_diagram_is_served_to_the_workspace_as_text_and_the_viewer_under_its_own_policy(
        client, project_dir, tmp_path, settings_env):
    _project(project_dir)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    raw = client.get(f"/api/projects/{pid}/raw/docs/flow.drawio")
    assert raw.status_code == 200 and raw.headers["content-type"].startswith("text/plain")
    policy = views.VIEWER_HEADERS["Content-Security-Policy"]
    assert "sandbox allow-scripts" in policy and "connect-src 'none'" in policy
    assert "script-src 'self';" in policy and "frame-ancestors 'self'" in policy


def test_the_viewer_page_has_its_policy_by_any_case_of_its_address(tmp_path):
    dist = tmp_path / "dist"
    (dist / "drawio").mkdir(parents=True)
    (dist / "index.html").write_text("app", encoding="utf-8")
    (dist / "drawio" / "viewer.html").write_text("viewer", encoding="utf-8")
    # (K-belge-ciktilari: the document viewer's page is under the same policy.)
    (dist / "office").mkdir()
    (dist / "office" / "viewer.html").write_text("viewer", encoding="utf-8")
    app = FastAPI()
    _serve_frontend(app, dist)
    with TestClient(app) as client:
        for address in ("/drawio/viewer.html", "/DRAWIO/viewer.html", "/Drawio/Viewer.html",
                        "/office/viewer.html", "/OFFICE/viewer.html",
                        # (Windows opens a part without its trailing dot or space: refused.)
                        "/office./viewer.html", "/drawio./viewer.html", "/office /viewer.html",
                        "/office/viewer.html."):
            answer = client.get(address)
            # (Where the file system tells no case apart, each is the viewer: with its policy.)
            if answer.text == "viewer":
                assert "sandbox allow-scripts" in answer.headers["content-security-policy"], address


REAL = pytest.mark.skipif(browser.find_browser() is None or "KOLONI_BROWSER_FAKE" in os.environ,
                          reason="no Chrome or Edge on this machine")


@REAL
@pytest.mark.anyio
async def test_the_real_chrome_draws_a_png_and_an_svg_and_loads_nothing_a_diagram_names(
        tmp_path):
    hits: list[str] = []

    class Counted(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            super().do_GET()

        def log_message(self, *args):
            pass

    (tmp_path / "x.png").write_bytes(PNG)
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(Counted, directory=str(tmp_path)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    # A picture on this machine and one on the web, and a font from the web: none is asked for.
    more = (f'<mxCell id="3" style="shape=image;image=http://127.0.0.1:{port}/x.png;" '
            'vertex="1" parent="1"><mxGeometry x="200" y="0" width="40" height="40" '
            'as="geometry"/></mxCell><mxCell id="4" value="Web" style="shape=image;'
            'image=https://example.com/y.png;fontSource=https%3A%2F%2Ffonts.googleapis.com%2Fcss'
            '%3Ffamily%3DLobster;fontFamily=Lobster;" vertex="1" parent="1"><mxGeometry x="300" '
            'y="0" width="40" height="40" as="geometry"/></mxCell>')
    command = browser.find_browser()
    assert command is not None
    try:
        png = await diagram.draw(command, tmp_path / "scratch", "t1", FLOW.format(more=more), "png")
        svg = await diagram.draw(command, tmp_path / "scratch", "t2", FLOW.format(more=""), "svg")
    finally:
        server.shutdown()
    assert png.startswith(diagram.PNG) and len(png) > 2000
    assert svg.startswith(b"<?xml") and b"<svg" in svg[:200] and b"Start" in svg
    assert hits == []
    assert not list((tmp_path / "scratch").glob("profile-*"))


@REAL
@pytest.mark.anyio
async def test_the_real_render_browser_resolves_no_name_a_websocket_to_loopback_neither(tmp_path):
    reached: list[str] = []

    async def heard(socket):
        reached.append("connected")
        await socket.close()

    async with websockets.serve(heard, "127.0.0.1", 0) as server:
        port = next(iter(server.sockets)).getsockname()[1]
        one = browser.Browser(tmp_path, "t")
        command = browser.find_browser()
        assert command is not None
        try:
            await one.start(command, None, set())
            await one._eval(browser._tag("socket") + f"new WebSocket('ws://127.0.0.1:{port}/'); 1")
            await asyncio.sleep(1.5)
        finally:
            await one.close()
    assert reached == []


@REAL
@pytest.mark.anyio
async def test_the_real_chrome_places_shapes_a_diagram_gives_no_geometry(tmp_path):
    bare = ('<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
            + "".join(f'<mxCell id="{n}" value="{n}" vertex="1" parent="1"/>' for n in "abc")
            + '<mxCell id="e" edge="1" source="a" target="b" parent="1"/></root></mxGraphModel>')
    command = browser.find_browser()
    assert command is not None
    svg = (await diagram.draw(command, tmp_path, "t", bare, "svg")).decode()
    # Three boxes drawn, and the edge between them: nothing was drawn without the places.
    assert svg.count("<rect") >= 3 and "<path" in svg
    with pytest.raises(browser.BrowserError, match="not a draw.io file"):
        await diagram.draw(command, tmp_path, "t", "not xml at all", "png")


def test_the_viewer_is_as_downloaded_and_where_the_server_reads_it():
    for name in (*diagram.SCRIPTS, "viewer.html", "LICENSE"):
        assert (diagram.VIEWER / name).is_file(), name
    page = (diagram.VIEWER / "viewer.html").read_text(encoding="utf-8")
    assert page.index("koloni.js") < page.index("viewer-static.min.js")
    # draw.io v32.6.9 (jgraph/drawio, Apache-2.0), byte for byte (.gitattributes: -text)
    assert hashlib.sha256((diagram.VIEWER / "viewer-static.min.js").read_bytes()).hexdigest() == (
        "21f5b0a744765eba94fdc14f4006f2e024ef01635579f421191529f4712b57b7")
