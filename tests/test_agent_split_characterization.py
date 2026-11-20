"""Branches of `app/agent/__init__.py` that no other test met, pinned before its long
functions were split (C901 <= 12): each test here ran green on the code before the split."""

from tests.fakes import Script, ScriptedExecutor
from tests.test_browser import FAKE
from tests.test_chat_flow import start_in_mode, text
from tests.test_claim_scenarios import ORIGIN, write
from tests.test_copy_part import mono, spawn
from tests.test_spawn import call, step
from tests.test_trigger_scenarios import allow, run_now, trigger


def test_a_diagram_that_is_not_there_or_not_text_is_refused_with_why(
        monkeypatch, make_client, wait_run, project_dir):
    monkeypatch.setenv("KOLONI_BROWSER_FAKE", FAKE)
    (project_dir / "bytes.drawio").write_bytes(b"\xff\xfe\x00not text")
    client, _model = make_client([
        step(call("diagram_image", {"path": "bytes.drawio"}, "d1")),
        step(call("diagram_image", {"path": "gone.drawio"}, "d2")),
        text("done")])
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    wait_run(client, cid, run_id)
    said = [t["result"] for t in client.get(f"/api/conversations/{cid}").json()["tool_calls"]]
    assert said == ["error: bytes.drawio is not UTF-8 text: not a draw.io file",
                    "error: gone.drawio: no such file"]
    assert not list(project_dir.glob("*.png"))


def test_nobody_watching_a_part_copys_passing_check_keeps_a_root_file_for_the_user(
        make_client, wait_run, tmp_path):
    project = mono(tmp_path / "repo").resolve()
    client, _model = make_client({
        "Lead": [step(spawn("core")), text("done")],
        "Coder": [step(write("pyproject.toml", "[tool.ruff]\n")), text("did it")],
    }, executor=ScriptedExecutor([Script(["ok\n"])]))
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={"check_command": "check"}).status_code == 200
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    made = trigger(client, pid, cid, permissions={
        "write": True, "commands": [allow(client, cid, "check")], "agents": 1})
    snap = wait_run(client, cid, run_now(client, made["id"]), timeout=30)
    (merge,) = snap["merges"]
    assert merge["check"]["state"] == "passed" and merge["status"] == "kept" and merge["kept_in"]
    assert [f["state"] for f in merge["files"]] == ["ready"]
    told = next(t for t in snap["tool_calls"] if t["name"] == "spawn_agent")["result"]
    assert 'it ran in a copy of "core/" alone, without the other parts' in told
    assert merge["kept_in"] in told
    assert (project / "pyproject.toml").read_text(encoding="utf-8").startswith("[tool.pytest")
