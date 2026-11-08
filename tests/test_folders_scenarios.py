"""Slice 75's acceptance set: the folders agents may use. Written before the code.

The user: "in settings let us choose which folder paths agents can reach - everything on the Desktop,
say". Design: `tasarim/specs/2026-10-22-dilim-75-klasorler-design.md`.

Contract:
- `GET /api/folders` -> {"also_in": [...], "read_in": [...], "never": [{"path", "why"}, ...]}: the
  app-wide lists (read and write / read only) and the places KOLONİ never opens, with why.
  `PUT /api/folders` {"also_in", "read_in"} from the app's own page only; each folder absolute, local,
  existing and not a never-opened one (422 with why otherwise).
- A project has `read_in` beside `also_in` (`ProjectOut` / `ProjectPatch`), checked the same way.
- A project's agents use the app's lists + the project's + the conversation's.

Slice 86b took the app-wide lists away (into each project's, and its chats'): `GET /api/folders`
says the never-opened places only, and a chat's agents use the chat's own lists, which start as
its folder's (tests/test_chat_folders.py).
- In a read-only folder reading needs no card; writing is asked for at every level, Full auto too,
  and nothing is written before the user says yes.
"""

import json
from pathlib import Path

import pytest

from app.schemas import ProjectOut

if "read_in" not in ProjectOut.model_fields:
    pytest.skip("slice 75 is not built yet", allow_module_level=True)  # written before the code

from tests.test_agent_writes import wait_status, write  # noqa: E402
from tests.test_chat_flow import text  # noqa: E402
from tests.test_outside_folders_scenarios import converse, project, read  # noqa: E402

ORIGIN = {"Origin": "http://127.0.0.1:8790"}


@pytest.fixture
def shelf(tmp_path):
    """A folder outside the project, with a file in it."""
    folder = tmp_path / "shelf"
    folder.mkdir()
    (folder / "notes.md").write_text("shelf notes\n", encoding="utf-8")
    return folder


# --- the app's lists ---------------------------------------------------------------------------


def test_the_never_opened_places_are_said(client):
    told = client.get("/api/folders").json()
    never = {Path(place["path"]): place["why"] for place in told["never"]}
    assert Path.home() / ".ssh" in never and never[Path.home() / ".ssh"]


@pytest.mark.parametrize("bad", [Path.home() / ".ssh", Path.home(), Path("relative/folder")])
def test_the_lists_never_take_a_secret_a_home_or_a_relative_folder(client, project_dir, bad):
    pid = project(client, project_dir)
    refused = client.patch(f"/api/projects/{pid}", headers=ORIGIN, json={"also_in": [str(bad)]})
    assert refused.status_code == 422


# --- a read-only folder ----------------------------------------------------------------------


def test_in_a_read_only_folder_reading_needs_no_card(make_client, wait_run, project_dir, shelf):
    client, _model = make_client([read(shelf / "notes.md"), text("done")])
    pid = project(client, project_dir, read_in=[str(shelf)])
    assert client.get(f"/api/projects/{pid}").json()["read_in"] == [str(shelf)]
    cid, run_id = converse(client, pid, mode="ask")
    snap = wait_run(client, cid, run_id)
    (tool,) = snap["tool_calls"]
    assert tool["status"] == "succeeded" and "shelf notes" in tool["result"]


@pytest.mark.parametrize("mode", ["auto_edit", "full_auto"])
def test_in_a_read_only_folder_a_write_is_asked_for_even_at_full_auto(make_client, project_dir, shelf, mode):
    client, _model = make_client([write(str(shelf / "out.md"), "x\n"), text("ok")])
    pid = project(client, project_dir, read_in=[str(shelf)])
    cid, _run_id = converse(client, pid, mode=mode)
    snap = wait_status(client, cid, "waiting_approval")
    assert "shelf" in json.dumps(snap["tool_calls"])
    assert not (shelf / "out.md").exists()


def test_a_read_only_folder_is_checked_like_the_project_list(make_client, project_dir):
    client, _model = make_client([text("ok")])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    refused = client.patch(f"/api/projects/{pid}", headers=ORIGIN, json={"read_in": [str(Path.home() / ".aws")]})
    assert refused.status_code == 422
