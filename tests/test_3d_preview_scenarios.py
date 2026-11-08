"""Slice 58's acceptance set, the backend's part: 3D models an agent makes are shown. Written before
the code. (The view itself - turning, Fit, the sizes, the keyboard, three.js loaded only when a model
opens - is the frontend's: vitest and Playwright, written with the code.)

An agent `show`s an STL, OBJ, glTF / GLB or 3MF file of the project as it does a picture; the file
is served with a type of its own, by slice 39's rules (inside the project, no secrets, no links),
and the files a model names beside it (an OBJ's .mtl, a glTF's .bin) too. A model may be larger
than a page (up to 50 MB); a larger one is listed but not served.

Contract: `views.KINDS` gives these suffixes the kind "model"; served types: .stl model/stl,
.obj model/obj, .gltf model/gltf+json, .glb model/gltf-binary, .3mf model/3mf, .mtl text/plain,
.bin application/octet-stream.
"""

import pytest

from app import views

if ".stl" not in views.KINDS:
    pytest.skip("slice 58 is not built yet", allow_module_level=True)  # written before the code

from tests.test_chat_flow import start, text  # noqa: E402
from tests.test_view_scenarios import content, show  # noqa: E402
from tests.test_view_scenarios import views as listed  # noqa: E402

STL = b"solid cube\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\n" \
      b"endloop\nendfacet\nendsolid cube\n"
TYPES = {
    "part.stl": "model/stl", "part.obj": "model/obj", "part.gltf": "model/gltf+json",
    "part.glb": "model/gltf-binary", "part.3mf": "model/3mf",
}
MB = 1024 * 1024


@pytest.mark.parametrize(("path", "kind"), TYPES.items())
def test_an_agent_shows_a_3d_model_of_the_project(make_client, wait_run, project_dir, path, kind):
    (project_dir / path).write_bytes(STL)
    client, _model = make_client([show(path, "the part"), text("Here it is.")])
    cid, run_id = start(client, project_dir)
    (tool,) = wait_run(client, cid, run_id)["tool_calls"]
    assert tool["status"] == "succeeded", tool["result"]
    (view,) = listed(client, cid)
    assert (view["path"], view["kind"], view["note"]) == (path, "model", "the part")
    answer = content(client, view)
    assert answer.status_code == 200 and answer.content == STL
    assert answer.headers["content-type"].split(";")[0] == kind
    assert answer.headers["x-content-type-options"] == "nosniff"


def test_what_a_model_names_beside_it_is_served_and_nothing_outside(make_client, project_dir):
    (project_dir / "part.gltf").write_text('{"buffers": [{"uri": "part.bin"}]}')
    (project_dir / "part.bin").write_bytes(b"\0\1\2")
    (project_dir / "part.mtl").write_text("newmtl steel\n")
    client, _model = make_client([])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    raw = f"/api/projects/{pid}/raw"
    assert client.get(f"{raw}/part.bin").headers["content-type"] == "application/octet-stream"
    assert client.get(f"{raw}/part.mtl").headers["content-type"].startswith("text/plain")
    assert client.get(f"{raw}/part.gltf").headers["content-type"] == "model/gltf+json"
    assert client.get(f"{raw}/../outside.glb").status_code == 404


def test_a_model_may_be_larger_than_a_page_up_to_50_mb(make_client, wait_run, project_dir):
    (project_dir / "big.glb").write_bytes(b"\0" * (6 * MB))  # a page or picture this size is refused
    (project_dir / "huge.stl").write_bytes(b"\0" * (50 * MB + 1))
    client, _model = make_client([show("big.glb", id="a"), show("huge.stl", id="b"), text("ok")])
    cid, run_id = start(client, project_dir)
    wait_run(client, cid, run_id, timeout=15)
    by_path = {view["path"]: view for view in listed(client, cid)}
    assert content(client, by_path["big.glb"]).status_code == 200
    assert content(client, by_path["huge.stl"]).status_code == 413  # listed, not served
