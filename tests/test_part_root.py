"""K-buyuk-proje, second slice: the part of a project an agent works in - a sub-agent's by
spawn_agent's `folder`, a whole chat's by the user. Its commands run in the part's folder (its
copy's), it is told the part's AGENTS.md and test command; nothing it may read or write changes."""

import json
import shutil
from pathlib import Path

import pytest

from app import commands, project_map
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_writes import wait_status
from tests.test_chat_flow import text
from tests.test_claim_scenarios import agent, calls, setup
from tests.test_command_safety_scenarios import waiting
from tests.test_copy_runner import here
from tests.test_project_map import _link, _put, map_ready  # noqa: F401  (a fixture)
from tests.test_spawn import call, step
from tests.test_triggers import allow, leave, run_now, trigger

OWN = {"Origin": "http://127.0.0.1:8790"}
WHERE = "python -c \"import os;print('AT='+os.getcwd())\""
CORE_RULES = "Core rules: tests live in core/tests."


def two_parts(root: Path) -> Path:
    """A repository of two parts: core (Python, its own AGENTS.md) and web, and a secret."""
    return _put(root, {
        "AGENTS.md": "Root rules: be brief.", ".env": "TOKEN=sk-part-test",
        "core/pyproject.toml": "[tool.pytest.ini_options]\n", "core/tests/test_a.py": "",
        "core/AGENTS.md": CORE_RULES,
        "web/package.json": json.dumps({"scripts": {"test": "vitest run"}}),
        "web/notes.txt": "web notes", "docs/guide.md": "",
    })


def spawn(folder=None, id="s"):
    return step(call("spawn_agent", {"role": "Coder", "task": "do it",
                                     **({"folder": folder} if folder is not None else {})}, id))


def at(said):
    """Where the WHERE command ran."""
    return Path(said.split("AT=", 1)[1].splitlines()[0]).resolve()


def system(model, name):
    return model.calls_of[name][0][0]["content"]


@pytest.mark.usefixtures("map_ready")
def test_a_sub_agent_given_a_part_runs_its_commands_there_in_its_copy_and_is_told_the_part(
        make_client, wait_run, tmp_path):
    root = two_parts(tmp_path / "repo")
    client, model, cid, run_id = setup(make_client, root, {
        "Lead": [spawn("core"), text("done")],
        "Coder": [step(call("run_command", {"command": WHERE}, "c")),
                  step(call("read_file", {"path": f"{root}/web/notes.txt"}, "r")),
                  text("did it")],
    })
    snap = wait_run(client, cid, run_id, timeout=15)
    assert snap["runs"][0]["status"] == "completed"
    ((status, said),) = calls(snap, "Coder", "run_command")
    assert status == "succeeded"
    assert at(said) == (here(client, snap) / "core").resolve()
    # Another part, not in its copy (slice 3), is read in the project by its full path.
    ((status, said),) = calls(snap, "Coder", "read_file")
    assert status == "succeeded" and "web notes" in said
    told = system(model, "Coder")
    assert "Root rules: be brief." in told and CORE_RULES in told
    assert 'The folder "core/"\'s AGENTS.md' in told
    assert 'You work in the project\'s part "core/"; its test command is "pytest"' in told
    # (A CLI's own shell starts at the root: only KOLONİ's run_command goes there by itself.)
    assert 'a shell of your own starts at the project root: go into "core/" first' in told
    # The Lead was offered the folder, and told to pass it.
    (offered,) = [t for t in model.tool_args[0] if t["function"]["name"] == "spawn_agent"]
    assert "folder" in offered["function"]["parameters"]["properties"]
    assert "as folder to spawn_agent" in model.calls[0][0]["content"]


def test_a_folder_that_is_not_a_part_is_refused_with_why(make_client, wait_run, tmp_path):
    root = two_parts(tmp_path / "repo")
    _link(root / "core", root / "link")
    wanted = ["../repo/core", str(root / "core"), "C:/Windows", "docs", "link"]
    client, model, cid, run_id = setup(make_client, root, {
        "Lead": [*(spawn(one, f"s{at}") for at, one in enumerate(wanted)), text("done")],
    })
    snap = wait_run(client, cid, run_id, timeout=15)
    refused = [t for t in snap["tool_calls"] if t["name"] == "spawn_agent"]
    assert [t["status"] for t in refused] == ["failed"] * len(wanted)
    said = [t["result"] for t in refused]
    assert all('".", "core/", "web/"' in one for one in said), said
    assert "nor one with .." in said[0] and "nor one with .." in said[1] and (
        "nor one with .." in said[2])
    assert '"docs" is not one of the project\'s parts' in said[3]
    assert '"link" is not one of the project\'s parts' in said[4]
    assert not [a for a in snap["agents"] if a["name"] == "Coder"]


def test_a_part_that_turned_into_a_link_is_refused(tmp_path, monkeypatch):
    root = two_parts(tmp_path / "repo")
    _link(root / "core", root / "link")
    kept = project_map.scan(str(root))  # (as a map kept from before the folder became a link)
    monkeypatch.setattr(project_map, "scan", lambda *_a: {
        **kept, "parts": [*kept["parts"], {**kept["parts"][0], "path": "link/"}]})
    with pytest.raises(ValueError, match="a link, or gone"):
        project_map.part_of(str(root), "link/")
    assert project_map.part_of(str(root), "core\\") == "core/"
    assert project_map.part_of(str(root), "./core") == project_map.part_of(
        str(root), ".\\core\\") == "core/"
    assert project_map.part_of(str(root), ".") is None


def test_the_chats_part_is_the_leads_and_its_sub_agents_unless_the_lead_says(
        make_client, wait_run, tmp_path):
    root = two_parts(tmp_path / "repo")
    client, model = make_client({
        "Lead": [step(call("run_command", {"command": WHERE}, "c")),
                 step(call("read_file", {"path": "web/notes.txt"}, "r")),
                 step(call("read_file", {"path": ".env"}, "e")),
                 spawn(id="s1"), spawn(".", "s2"), text("done")],
        "Coder": [text("in core")], "Coder 2": [text("in all")],
    })
    pid = client.post("/api/projects", json={"root_path": str(root)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    url = f"/api/conversations/{cid}"
    # The user's from the app's own page only, and one of the map's parts.
    assert client.patch(url, json={"part": "core"}).status_code == 403
    assert client.patch(url, json={"part": "docs"}, headers=OWN).status_code == 422
    assert client.patch(url, json={"part": "../x"}, headers=OWN).status_code == 422
    settings = {"part": "core", "permission_mode": "full_auto", "spawn_approval": "never"}
    patched = client.patch(url, json=settings, headers=OWN)
    assert patched.status_code == 200 and patched.json()["part"] == "core/"
    run_id = client.post(f"{url}/messages", json={"content": "go"}, headers=OWN).json()["run"]["id"]
    # A secret is asked about as before, in a part too.
    (secret,) = [t for t in wait_status(client, cid, "waiting_approval")["tool_calls"]
                 if t["status"] == "pending"]
    assert json.loads(secret["arguments"])["path"] == ".env"
    client.post(f"/api/tool-calls/{secret['id']}/approve", headers=OWN)
    snap = wait_run(client, cid, run_id, timeout=15)
    assert snap["runs"][0]["status"] == "completed"
    lead = agent(snap, "Lead")["id"]
    ran, read, env = [t for t in snap["tool_calls"] if t["agent_id"] == lead][:3]
    assert at(ran["result"]) == (root / "core").resolve()
    assert read["status"] == env["status"] == "succeeded" and "web notes" in read["result"]
    assert CORE_RULES in model.calls[0][0]["content"]
    assert CORE_RULES in system(model, "Coder") and CORE_RULES not in system(model, "Coder 2")
    assert "You work in the project's part" not in system(model, "Coder 2")
    # Another folder for the chat: its part was of the other one's map.
    other = client.post("/api/projects", json={"root_path": str(root / "web")}).json()["id"]
    moved = client.patch(url, json={"project_id": other}, headers=OWN)
    assert moved.status_code == 200, moved.text
    assert moved.json()["part"] is None


def in_part(make_client, root, lead, ran=0, **settings):
    """A chat set to the part core/, at Full auto, whose Lead does `lead`; `ran`: how many of
    its commands run (scripted, each printing "ok")."""
    client, model = make_client(lead, executor=ScriptedExecutor([Script(["ok\n"])] * ran))
    client.headers.update(OWN)
    pid = client.post("/api/projects", json={"root_path": str(root)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    patched = client.patch(f"/api/conversations/{cid}", json={
        "part": "core", "permission_mode": "full_auto", **settings})
    assert patched.status_code == 200, patched.text
    return client, model, pid, cid


def go(client, cid):
    return client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()[
        "run"]["id"]


def commands_of(lines):
    return [step(call("run_command", {"command": line}, f"c{at}")) for at, line in enumerate(lines)]


def asked(client, cid, wait_run, run_id, count):
    """The commands asked about, each turned down once it waits; and the turn as it ended."""
    said = []
    for at in range(1, count + 1):
        card = next(c for c in waiting(client, cid, at) if c["status"] == "proposed")
        said.append(card["command"])
        client.post(f"/api/commands/{card['id']}/reject")
    snap = wait_run(client, cid, run_id, timeout=15)
    assert snap["runs"][0]["status"] == "completed"
    return said, snap


def test_from_a_part_a_command_reading_the_roots_secret_is_asked_at_full_auto(
        make_client, wait_run, tmp_path):
    lines = ["cat ../.env", "Get-Content ..\\.env"]
    client, _model, _pid, cid = in_part(
        make_client, two_parts(tmp_path / "repo"), [*commands_of(lines), text("done")])
    said, _snap = asked(client, cid, wait_run, go(client, cid), 2)
    assert said == lines


def test_from_a_part_its_parents_venv_runs_unasked_at_full_auto(make_client, wait_run, tmp_path):
    root = _put(two_parts(tmp_path / "repo"), {".venv/Scripts/python.exe": ""})
    line = "..\\.venv\\Scripts\\python.exe -m pytest"
    client, _model, _pid, cid = in_part(
        make_client, root, [*commands_of([line]), text("done")], ran=1)
    _said, snap = asked(client, cid, wait_run, go(client, cid), 0)
    assert [(c["command"], c["cwd"], c["status"]) for c in snap["commands"]] == [
        (line, "core", "exited")]


@pytest.mark.parametrize("secret_in_part", [False, True])
def test_a_search_from_a_part_is_judged_from_its_folder(
        make_client, wait_run, tmp_path, secret_in_part):
    root = two_parts(tmp_path / "repo")  # (its .env at the root: out of the part's reach)
    if secret_in_part:
        _put(root, {"core/tests/.env": "TOKEN=sk-part-test"})  # (in reach of all three)
    lines = ["rg KEY .", "rg KEY tests", "rg KEY"]
    client, _model, _pid, cid = in_part(
        make_client, root, [*commands_of(lines), text("done")], ran=0 if secret_in_part else 3)
    said, snap = asked(client, cid, wait_run, go(client, cid), 3 if secret_in_part else 0)
    assert said == (lines if secret_in_part else [])
    assert [c["status"] for c in snap["commands"]] == (
        ["rejected"] * 3 if secret_in_part else ["exited"] * 3)


def test_a_triggers_turn_in_a_chat_with_a_part_runs_its_ticked_command(
        make_client, wait_run, tmp_path):
    client, model, pid, cid = in_part(
        make_client, two_parts(tmp_path / "repo"),
        [*commands_of(["python --version"]), text("done")], ran=1)
    given = leave(commands=[allow(client, cid, "python --version")])
    run_id = run_now(client, trigger(client, pid, cid, permissions=given)["id"])
    snap = wait_run(client, cid, run_id, timeout=15)
    assert [(c["command"], c["status"]) for c in snap["commands"]] == [
        ("python --version", "exited")]
    # (It is told where its commands run in this turn: the trigger allowed them at the root.)
    assert "runs at the project root in this turn" in model.calls[0][0]["content"]


def test_a_part_whose_folder_is_gone_is_taken_off_the_chat_and_the_lead_told(
        make_client, wait_run, tmp_path):
    root = two_parts(tmp_path / "repo")
    client, model, _pid, cid = in_part(make_client, root, [text("done")])
    shutil.rmtree(root / "core")
    snap = wait_run(client, cid, go(client, cid), timeout=15)
    assert snap["conversation"]["part"] is None
    assert 'part "core/", whose folder is gone' in model.calls[0][0]["content"]


def test_a_chat_with_no_folder_takes_an_empty_part_as_none(make_client):
    client, _model = make_client([text("ok")])
    cid = client.post("/api/conversations", json={}, headers=OWN).json()["id"]
    url = f"/api/conversations/{cid}"
    for part in ("", ".", None):
        assert client.patch(url, json={"part": part}, headers=OWN).status_code == 200
    assert client.patch(url, json={"part": "core"}, headers=OWN).status_code == 422


def test_a_searchs_paths_are_read_from_where_it_runs(tmp_path):
    root = _put(two_parts(tmp_path / "repo"), {"core/src/.env": "TOKEN=x", "docs/a.md": ""})
    _link(root / "docs", root / "src")  # (the root's src is elsewhere: not the part's)
    real = root.resolve()
    assert "core/src/.env" in commands.search_reason("rg KEY src", real, "core")
    # (out of where it runs, by "..", reads no scope: asked)
    assert "secret file" in commands.search_reason("rg KEY ../web", real, "core")


def run_in(command, cwd=None, id="c"):
    return step(call("run_command", {"command": command, **({"cwd": cwd} if cwd else {})}, id))


@pytest.mark.usefixtures("map_ready")
def test_the_users_own_test_command_runs_unasked_in_its_part_below_full_auto(
        make_client, wait_run, tmp_path):
    """Slice 4: what the user wrote for a part counts as a ticked rule there - exactly it, in
    that folder; KOLONİ's guess, another folder or a further argument are asked as before."""
    lines = [("pytest -q", None), ("pytest -q", "core"), ("pytest -q", "."), ("npm test", "web"),
             ("pytest -q --tb=short", None)]
    client, model, pid, cid = in_part(
        make_client, two_parts(tmp_path / "repo"),
        [*(run_in(line, cwd, f"c{at}") for at, (line, cwd) in enumerate(lines)), text("done")],
        ran=2, permission_mode="ask")
    assert client.put(f"/api/projects/{pid}/map/test",
                      json={"path": "core/", "command": "pytest -q"}).status_code == 200
    run_id = go(client, cid)
    for at in (3, 4, 5):
        card = waiting(client, cid, at)[at - 1]
        client.post(f"/api/commands/{card['id']}/reject")
    snap = wait_run(client, cid, run_id, timeout=15)
    assert [(c["command"], c["cwd"], c["status"]) for c in snap["commands"]] == [
        ("pytest -q", "core", "exited"), ("pytest -q", "core", "exited"),
        ("pytest -q", ".", "rejected"), ("npm test", "web", "rejected"),
        ("pytest -q --tb=short", "core", "rejected")]
    assert ("its test command is \"pytest -q\", run in that folder (the user's own: run_command "
            "runs it there without a card, as it is)") in model.calls[0][0]["content"]


def test_in_a_triggers_turn_the_users_own_test_command_runs_in_its_part_unticked(
        make_client, wait_run, tmp_path):
    client, _model, pid, cid = in_part(
        make_client, two_parts(tmp_path / "repo"),
        [run_in("pytest -q", "core", "c0"), run_in("pytest -q", None, "c1"), text("done")], ran=1)
    assert client.put(f"/api/projects/{pid}/map/test",
                      json={"path": "core/", "command": "pytest -q"}).status_code == 200
    run_id = run_now(client, trigger(client, pid, cid, permissions=leave())["id"])
    snap = wait_run(client, cid, run_id, timeout=15)
    assert [(c["command"], c["cwd"], c["status"]) for c in snap["commands"]] == [
        ("pytest -q", "core", "exited")]
    # (given no cwd it would run at the root in this turn: not the part's folder - refused)
    assert [t["status"] for t in snap["tool_calls"] if t["name"] == "run_command"] == [
        "succeeded", "denied"]
