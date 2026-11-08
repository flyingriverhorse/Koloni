"""Slice 50's acceptance set: a turn undone, or the conversation put back to before a turn. Written
before the code.

Undoing a turn takes back the changes it applied, last first, and turns down the ones still waiting.
A file changed since by someone else (the user, a later turn) is not overwritten: it is skipped and
said so. What commands did cannot be taken back: the turn's commands are listed. Before anything is
done, the same answer is given as a look ahead, and nothing changes. "Restore to before turn N"
undoes N and every later turn of the conversation, latest first. Only from the app's own page.

Contract:
- `GET /api/runs/{id}/undo` → `{revert: [path], skip: [{path, why}], reject: [path], commands: [str]}`
- `POST /api/runs/{id}/undo` (own origin) → the same, done.
- `GET` / `POST /api/conversations/{cid}/restore?before={run_id}` → the same shape, for that run and
  every later one.
"""

import pytest

from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_commands import cmd
from tests.test_agent_writes import read, write
from tests.test_chat_flow import text

ORIGIN = {"Origin": "http://127.0.0.1:8790"}


def _built(client):
    # (An included router is one entry in `app.routes`: its paths are in the OpenAPI schema.)
    return "/api/runs/{run_id}/undo" in client.app.openapi()["paths"]


def conversation(client, project_dir):
    if not _built(client):
        pytest.skip("slice 50 is not built yet")  # written before the code
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    # (the Lead writes itself here: slice 48's handing on is not what is tested)
    client.patch(
        f"/api/conversations/{cid}",
        json={"permission_mode": "full_auto", "lead_hands_code": False},
        headers=ORIGIN,
    )
    return cid


def turn(client, wait_run, cid, words):
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": words}).json()[
        "run"
    ]["id"]
    wait_run(client, cid, run_id)
    return run_id


def test_a_turn_is_undone_and_the_look_ahead_said_so_first(make_client, wait_run, project_dir):
    client, _model = make_client(
        [write("a.txt", "one\n"), text("made a"), write("b.txt", "two\n"), text("made b")]
    )
    cid = conversation(client, project_dir)
    turn(client, wait_run, cid, "make a")
    second = turn(client, wait_run, cid, "make b")

    ahead = client.get(f"/api/runs/{second}/undo")
    assert ahead.status_code == 200, ahead.text
    assert ahead.json()["revert"] == ["b.txt"] and ahead.json()["skip"] == []
    assert read(project_dir, "b.txt") == "two\n"  # a look ahead changes nothing

    assert (
        client.post(f"/api/runs/{second}/undo").status_code == 403
    )  # says nothing of where it is from
    done = client.post(f"/api/runs/{second}/undo", headers=ORIGIN)
    assert done.status_code == 200, done.text
    assert not (project_dir / "b.txt").exists()
    assert read(project_dir, "a.txt") == "one\n"  # the other turn's work stays


def test_a_file_changed_since_is_skipped_never_overwritten(make_client, wait_run, project_dir):
    client, _model = make_client(
        [write("a.txt", "one\n"), text("made a"), write("a.txt", "two\n"), text("changed a")]
    )
    cid = conversation(client, project_dir)
    first = turn(client, wait_run, cid, "make a")
    turn(client, wait_run, cid, "change a")

    done = client.post(f"/api/runs/{first}/undo", headers=ORIGIN).json()
    assert done["revert"] == [] and [s["path"] for s in done["skip"]] == ["a.txt"]
    assert done["skip"][0]["why"]
    assert read(project_dir, "a.txt") == "two\n"


def test_restore_before_a_turn_undoes_it_and_every_later_one_latest_first(
    make_client, wait_run, project_dir
):
    client, _model = make_client(
        [write("a.txt", "one\n"), text("made a"), write("a.txt", "two\n"), text("changed a")]
    )
    cid = conversation(client, project_dir)
    first = turn(client, wait_run, cid, "make a")
    turn(client, wait_run, cid, "change a")

    ahead = client.get(f"/api/conversations/{cid}/restore", params={"before": first}).json()
    assert ahead["skip"] == [] and sorted(ahead["revert"]) == ["a.txt", "a.txt"]
    done = client.post(
        f"/api/conversations/{cid}/restore", params={"before": first}, headers=ORIGIN
    )
    assert done.status_code == 200, done.text
    assert not (project_dir / "a.txt").exists()


def test_what_a_command_did_is_named_not_taken_back(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([Script(["installed\n"])])
    client, _model = make_client(
        [cmd("pip install something"), text("installed")], executor=executor
    )
    cid = conversation(client, project_dir)
    run_id = turn(client, wait_run, cid, "install it")
    assert client.get(f"/api/runs/{run_id}/undo").json()["commands"] == ["pip install something"]
