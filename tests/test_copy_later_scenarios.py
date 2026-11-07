"""Working copies, second part (slice 19c): the acceptance set, written before the code.

What slice 19b left open: a command run before the first write still ran in the project, and
after a restart the work kept in a copy could only be looked up in a folder. Now a
sub-agent's first command gets it its copy as its first write does, and what a restart
interrupted comes back as a card: Apply puts it in the project, Discard removes the folder.
"""

import pytest

import app.copies

if not hasattr(app.copies, "BASE_FILE"):  # written before the code: skipped until it exists
    pytest.skip("slice 19c is not built yet", allow_module_level=True)

from app.config import load_settings  # noqa: E402
from app.main import create_app  # noqa: E402
from tests.conftest import Gate  # noqa: E402
from tests.fakes import ScriptedModel  # noqa: E402
from tests.keyed import TestClient  # noqa: E402
from tests.test_chat_flow import text  # noqa: E402
from tests.test_claim_scenarios import agent, calls, write  # noqa: E402
from tests.test_copy_scenarios import one, run  # noqa: E402
from tests.test_parallel import until  # noqa: E402
from tests.test_spawn import call, step  # noqa: E402

ORIGIN = "http://127.0.0.1:8790"
MAKES = "python -c \"open('made.txt','w').write('by a command')\""


def test_a_command_run_before_any_write_runs_in_the_copy_too(
    make_client, wait_run, project_dir
):
    first = Gate()
    client, model, cid, run_id = one(make_client, project_dir, [
        step(run(MAKES)), first.step(text("A done")),
    ])
    first.wait_partial()
    snap = until(client, cid, lambda s: calls(s, "Coder", "run_command")[0][0] == "succeeded")
    assert agent(snap, "Coder")["copy"] == {"state": "own"}
    assert not (project_dir / "made.txt").exists()          # not in the project while at work
    first.release()
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed"
    assert (project_dir / "made.txt").read_text(encoding="utf-8") == "by a command"


def test_an_agent_that_only_reads_gets_no_copy(make_client, wait_run, project_dir):
    client, model, cid, run_id = one(make_client, project_dir, [
        step(call("read_file", {"path": "hello.py"}, "r")),
        step(call("list_dir", {}, "l")), text("A done"),
    ])
    snap = wait_run(client, cid, run_id)
    assert agent(snap, "Coder")["copy"] is None and snap["merges"] == []


def interrupted(settings_env, project_dir):
    """A turn in ask mode whose Coder's card is waiting when the app is closed; returns the
    conversation's id."""
    app_ = create_app(load_settings(settings_env), model=ScriptedModel({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "do it"}, "s")),
                 text("done")],
        "Coder": [step(write("a.txt", "A")), text("A done")],
    }))
    with TestClient(app_, base_url="http://127.0.0.1:8790") as client:
        client.headers["Origin"] = ORIGIN
        pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
        cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
        assert client.patch(f"/api/conversations/{cid}", json={
            "permission_mode": "ask", "spawn_approval": "never"}).status_code == 200
        client.post(f"/api/conversations/{cid}/messages", json={"content": "go"})
        until(client, cid, lambda s: [m["status"] for m in s["merges"]] == ["pending"])
    return cid


def again(settings_env):
    client = TestClient(create_app(load_settings(settings_env)),
                        base_url="http://127.0.0.1:8790")
    client.headers["Origin"] = ORIGIN
    return client


def test_after_a_restart_the_kept_work_can_be_put_in_the_project(settings_env, project_dir):
    cid = interrupted(settings_env, project_dir)
    with again(settings_env) as client:
        (card,) = client.get(f"/api/conversations/{cid}").json()["merges"]
        assert card["status"] == "kept"
        assert {f["path"]: f["state"] for f in card["files"]} == {"a.txt": "ready"}
        assert not (project_dir / "a.txt").exists()
        assert client.post(f"/api/merges/{card['id']}/approve").status_code == 200
        snap = client.get(f"/api/conversations/{cid}").json()
        assert snap["merges"][0]["status"] == "applied"
        assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"
        assert [f["status"] for f in snap["file_changes"]] == ["applied"]
        assert list((load_settings(settings_env).runtime_root / "copies").iterdir()) == []
        # and it is taken once
        assert client.post(f"/api/merges/{card['id']}/approve").status_code == 409


def test_after_a_restart_what_changed_in_the_project_meanwhile_is_not_written_over(
    settings_env, project_dir
):
    cid = interrupted(settings_env, project_dir)
    (project_dir / "a.txt").write_text("THE USER'S OWN", encoding="utf-8")
    with again(settings_env) as client:
        (card,) = client.get(f"/api/conversations/{cid}").json()["merges"]
        assert {f["path"]: f["state"] for f in card["files"]} == {"a.txt": "conflict"}
        assert (project_dir / "a.txt").read_text(encoding="utf-8") == "THE USER'S OWN"


def test_after_a_restart_discard_removes_the_kept_folder_and_nothing_else(
    settings_env, project_dir
):
    cid = interrupted(settings_env, project_dir)
    with again(settings_env) as client:
        (card,) = client.get(f"/api/conversations/{cid}").json()["merges"]
        assert client.post(f"/api/merges/{card['id']}/reject").status_code == 200
        snap = client.get(f"/api/conversations/{cid}").json()
        assert snap["merges"][0]["status"] == "rejected"
        assert not (project_dir / "a.txt").exists()
        assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('hi')\n"
        assert list((load_settings(settings_env).runtime_root / "copies").iterdir()) == []
    # the next start has nothing left to offer
    with again(settings_env) as client:
        assert client.get(f"/api/conversations/{cid}").json()["merges"][0]["status"] == "rejected"
