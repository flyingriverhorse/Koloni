"""Working copies for sub-agents that are a CLI with tools of its own (slice 19c, completed):
native Claude Code and native Codex opened with spawn_agent are started in a copy of the
project, what they change is found there, and it is taken into the project when their work
is over - like any other sub-agent's. The lead stays in the project. Native agy too (slice
20b), tried with its stand-in only.

Whole turns, with the stand-ins for the CLIs.
"""

import json
import os
from pathlib import Path

from app import copies
from app.agent import LINKED_IN, NOT_LINKED_IN
from app.config import load_settings
from app.model_agy import SKIP_PERMISSIONS as SKIP
from app.model_agy import AgyClient
from app.model_native import ClaudeNativeClient, CodexNativeClient, CopilotNativeClient
from tests.conftest import Gate
from tests.test_agy_agent import agy_app  # noqa: F401  (a fixture)
from tests.test_chat_flow import text
from tests.test_claim_scenarios import agent, waits
from tests.test_claims import edit
from tests.test_claude_native import claude_app, hello  # noqa: F401  (a fixture)
from tests.test_copy_scenarios import files
from tests.test_native_agent import native_app  # noqa: F401  (a fixture)
from tests.test_parallel import until
from tests.test_spawn import call, reported, role_id, spawn, step

ORIGIN = "http://127.0.0.1:8790"

# Claude Code names its files by absolute paths: "CWD" is the folder it was started in.
WRITE = {"tool": "Write", "result": "File updated",
         "input": {"file_path": "CWD/hello.py", "content": "print('hello')\n"},
         "write": ["hello.py", "print('hello')\n"]}
LEAD = [spawn("Coder", "Change the greeting"), text("The coder did it.")]


def begin(client, project_dir, provider, mode="full_auto", lead=None):
    """A turn whose lead (the scripted model, or `lead`) opens a Coder that is the CLI."""
    client.headers["Origin"] = ORIGIN
    client.patch(f"/api/roles/{role_id(client, 'Coder')}", json={"provider_id": provider["id"]})
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": mode, "spawn_approval": "never", "lead_hands_code": False,
        "provider_id": lead["id"] if lead else None}).status_code == 200
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()["run"]
    return cid, run["id"]


def changes(snap):
    return [(c["path"], c["status"], c["origin"]) for c in snap["file_changes"]]


def copies_left(settings_env):
    held_in = copies.folder(load_settings(settings_env).runtime_root)
    return list(held_in.iterdir()) if held_in.is_dir() else []


# --- Claude Code --------------------------------------------------------------------------


def test_a_native_claude_sub_agent_works_in_its_copy_and_its_changes_are_taken_at_the_end(
    claude_app, wait_run, project_dir, settings_env  # noqa: F811
):
    (project_dir / "node_modules" / "pkg").mkdir(parents=True)
    (project_dir / "node_modules" / "pkg" / "index.js").write_text("dep", encoding="utf-8")
    client, provider, default = claude_app(
        [{"say": "I will fix it."}, WRITE, {"say": "Fixed."}], default_steps=LEAD)
    cid, run_id = begin(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    coder = agent(snap, "Coder")
    assert coder["copy"] == {"state": "own"} and agent(snap, "Lead")["copy"] is None
    seen = claude_app.record()
    # started in its copy, under the runtime root - not in the project
    tree = copies.folder(load_settings(settings_env).runtime_root) / coder["id"] / copies.TREE
    assert Path(seen["cwd"]) == tree
    # git there looks no higher than the copies folder: never into a repository above it
    assert seen["git_ceiling"] == str(tree.parent.parent)
    argv = seen["argv"]
    # the folders the copy shares with the project, by where they really are
    assert [argv[i + 1] for i, a in enumerate(argv) if a == "--add-dir"] == [
        str((project_dir / "node_modules").resolve())]
    assert f'The project folder is "{tree}"' in seen["stdin"]
    assert "a copy of the project of your own" in seen["stdin"]
    assert "git does not work in the copy" in seen["stdin"]
    assert LINKED_IN in seen["stdin"] and NOT_LINKED_IN not in seen["stdin"]
    # the write in the copy was allowed as asked, nobody having been asked
    assert seen["asked"] == [{"behavior": "allow", "updatedInput": {
        "file_path": f"{tree.as_posix()}/hello.py", "content": "print('hello')\n"}}]
    assert hello(project_dir) == "print('hello')\n"           # taken when its work was over
    assert changes(snap) == [("hello.py", "applied", "cli")]
    assert snap["file_changes"][0]["agent_id"] == coder["id"]
    assert [m["status"] for m in snap["merges"]] == ["applied"]
    assert copies_left(settings_env) == [] and snap["claims"] == []
    assert reported(default.calls[1][-1]["content"]) == "Coder finished.\n\nFixed."


def test_in_ask_mode_no_edit_of_a_native_sub_agent_is_asked_about_and_one_card_asks_for_all(
    claude_app, wait_run, project_dir, settings_env  # noqa: F811
):
    second = {**WRITE, "input": {"file_path": "CWD/new.txt", "content": "n\n"},
              "write": ["new.txt", "n\n"]}
    client, provider, _ = claude_app([WRITE, second, {"say": "Fixed."}], default_steps=LEAD)
    cid, run_id = begin(client, project_dir, provider, mode="ask")
    snap = until(client, cid, lambda s: [m["status"] for m in s["merges"]] == ["pending"],
                 timeout=20)
    # both were written, in the copy, without a word from the user
    assert [v["behavior"] for v in claude_app.record()["asked"]] == ["allow", "allow"]
    assert changes(snap) == [("hello.py", "in_copy", "cli"), ("new.txt", "in_copy", "cli")]
    assert hello(project_dir) == "print('hi')\n" and not (project_dir / "new.txt").exists()
    (card,) = snap["merges"]
    assert files(card) == {"hello.py": "ready", "new.txt": "ready"}
    coder = agent(snap, "Coder")
    assert (coder["status"], coder["copy"]) == ("completed", {"state": "own"})
    assert sorted(c["path"] for c in snap["claims"]) == ["hello.py", "new.txt"]
    assert client.post(f"/api/merges/{card['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert hello(project_dir) == "print('hello')\n"
    assert (project_dir / "new.txt").read_text(encoding="utf-8") == "n\n"
    assert changes(snap) == [("hello.py", "applied", "cli"), ("new.txt", "applied", "cli")]
    assert copies_left(settings_env) == [] and snap["claims"] == []


def test_what_a_native_sub_agent_asks_for_outside_its_copy_is_refused(
    claude_app, wait_run, project_dir, settings_env  # noqa: F811
):
    (project_dir / "node_modules" / "pkg").mkdir(parents=True)
    (project_dir / "node_modules" / "pkg" / "index.js").write_text("dep", encoding="utf-8")
    outside = {"file_path": "PROJECT/hello.py", "content": "print('straight in')\n"}

    def write(path):
        return {"tool": "Write", "input": {"file_path": path, "content": "x"},
                "write": [path, "x"]}

    client, provider, _ = claude_app([
        {"tool": "Write", "input": outside,
         "write": ["PROJECT/hello.py", "print('straight in')\n"]},
        {"tool": "Read", "input": {"file_path": "PROJECT/hello.py"}},
        {"tool": "Read",
         "input": {"file_path": "PROJECT/node_modules/pkg/index.js"}},
        write("CWD/dist/out.js"), write("CWD/node_modules/pkg/evil.js"),
        {"say": "I could not."}], default_steps=LEAD)
    cid, run_id = begin(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    wrote, read, shared, left_out, linked = claude_app.record()["asked"]
    assert wrote["behavior"] == "deny" and "outside your working copy" in wrote["message"]
    assert read["behavior"] == "deny" and "outside your working copy" in read["message"]
    assert shared["behavior"] == "allow"            # read through to the project's own
    assert left_out["behavior"] == "deny" and "not part of a working copy" in left_out["message"]
    assert linked["behavior"] == "deny" and "shares with the project" in linked["message"]
    assert hello(project_dir) == "print('hi')\n" and snap["file_changes"] == []
    assert not (project_dir / "node_modules" / "pkg" / "evil.js").exists()
    assert not (project_dir / "dist").exists() and snap["merges"] == []
    denied = [t["name"] for t in snap["tool_calls"] if t["status"] == "denied"]
    assert denied == ["edit_file", "claude__Read", "edit_file", "edit_file"]


def test_a_native_sub_agents_glob_whose_pattern_leaves_its_copy_is_refused(
    claude_app, wait_run, project_dir, settings_env  # noqa: F811
):
    # (Its pattern is a path: `../..` or a full one lists names outside - KOLONİ's own, ~/.ssh.)
    client, provider, _ = claude_app([
        {"tool": "Glob", "input": {"pattern": "../../../**"}},
        {"tool": "Glob", "input": {"pattern": f"{project_dir.parent.as_posix()}/**"}},
        {"tool": "Glob", "input": {"pattern": "**/*.py"}},
        {"say": "Done."}], default_steps=LEAD)
    cid, run_id = begin(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    up, full, own = claude_app.record()["asked"]
    assert up["behavior"] == "deny" and "outside your working copy" in up["message"]
    assert full["behavior"] == "deny" and "outside your working copy" in full["message"]
    assert own["behavior"] == "allow"


def test_a_folders_name_is_what_counts_for_what_a_native_sub_agent_may_write_in_its_copy(
    claude_app, wait_run, project_dir, settings_env  # noqa: F811
):
    """Not whether a link is there: this project has no node_modules, and a file written
    under that name in the copy would be dropped without a word. A file named like such a
    folder is a file like any other; and Windows drops the dot at the end of `dist.`."""
    (project_dir / "build").write_text("old\n", encoding="utf-8")

    def write(path):
        return {"tool": "Write", "input": {"file_path": path, "content": "x"},
                "write": [path, "x"]}

    client, provider, _ = claude_app([
        write("CWD/node_modules/pkg/new.js"), write("CWD/sub/Venv/x.py"),
        write("CWD/dist./out.js"), write("CWD/build"), {"say": "Done."}], default_steps=LEAD)
    cid, run_id = begin(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    linked, deeper, dotted, a_file = claude_app.record()["asked"]
    assert linked["behavior"] == "deny" and "shares with the project" in linked["message"]
    assert deeper["behavior"] == "deny" and "shares with the project" in deeper["message"]
    assert dotted["behavior"] == "deny" and "not part of a working copy" in dotted["message"]
    assert a_file["behavior"] == "allow"
    assert (project_dir / "build").read_text(encoding="utf-8") == "x"
    assert changes(snap) == [("build", "applied", "cli")]
    assert not (project_dir / "node_modules").exists() and not (project_dir / "dist").exists()


def test_in_its_copy_with_links_a_native_sub_agents_command_that_deletes_is_asked_at_full_auto(
    claude_app, wait_run, project_dir, settings_env  # noqa: F811
):
    """K-70-junction: through the copy's node_modules a delete reaches the project's own."""
    (project_dir / "node_modules" / "pkg").mkdir(parents=True)
    (project_dir / "node_modules" / "pkg" / "index.js").write_text("dep", encoding="utf-8")
    client, provider, _ = claude_app([
        {"tool": "Bash", "input": {"command": "rm -rf node_modules"}, "result": ""},
        {"say": "Left it."}], default_steps=LEAD)
    cid, run_id = begin(client, project_dir, provider)
    snap = until(client, cid, lambda s: [c["status"] for c in s["commands"]] == ["proposed"],
                 timeout=20)
    assert client.post(f"/api/commands/{snap['commands'][0]['id']}/reject").status_code == 200
    snap = wait_run(client, cid, run_id, timeout=20)
    (asked,) = claude_app.record()["asked"]
    assert asked["behavior"] == "deny"
    said = json.loads(next(t for t in snap["tool_calls"] if t["name"] == "run_command")[
        "arguments"])
    assert "links to the project's own" in said["reason"]
    assert (project_dir / "node_modules" / "pkg" / "index.js").read_text(encoding="utf-8") == "dep"


def test_a_native_sub_agent_that_may_only_read_gets_no_copy(
    claude_app, wait_run, project_dir, settings_env  # noqa: F811
):
    """Nothing it does can change a file: there is nothing to take into the project."""
    client, provider, _ = claude_app(
        [{"tool": "Read", "input": {"file_path": "PROJECT/hello.py"}}, {"say": "Looks fine."}],
        default_steps=[spawn("Reader", "Look at the greeting"), text("It was read.")])
    client.headers["Origin"] = ORIGIN
    assert client.post("/api/roles", json={
        "name": "Reader", "tools": ["read_file"], "provider_id": provider["id"],
    }).status_code == 201
    cid, run_id = begin(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert agent(snap, "Reader")["copy"] is None and snap["merges"] == []
    assert claude_app.record()["cwd"] == str(project_dir)
    assert copies_left(settings_env) == []


def test_a_native_sub_agents_write_waits_for_the_agent_that_holds_the_file(
    claude_app, wait_run, project_dir, settings_env  # noqa: F811
):
    gate = Gate()
    client, provider, _ = claude_app([WRITE, {"say": "Fixed."}], default_steps={
        "Lead": [edit("'hi'", "'one'"), gate.step(text("done")),
                 spawn("Coder", "Change the greeting"), text("The coder did it.")],
    })
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    first = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{first}", json={  # (its Lead writes: slice 48 off)
        "permission_mode": "full_auto", "lead_hands_code": False})
    one = client.post(f"/api/conversations/{first}/messages", json={"content": "go"}).json()[
        "run"]["id"]
    gate.wait_partial()                              # the first lead holds hello.py
    client.patch(f"/api/roles/{role_id(client, 'Coder')}", json={"provider_id": provider["id"]})
    second = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{second}", json={
        "permission_mode": "full_auto", "spawn_approval": "never"})
    other = client.post(f"/api/conversations/{second}/messages", json={"content": "go"}).json()[
        "run"]["id"]
    snap = until(client, second, lambda s: waits(s, "Coder") is not None, timeout=20)
    assert waits(snap, "Coder") == ("Lead", "hello.py")
    assert agent(snap, "Coder")["status"] == "blocked"
    gate.release()
    wait_run(client, first, one)
    snap = wait_run(client, second, other, timeout=20)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert claude_app.record()["asked"][0]["behavior"] == "allow"
    assert hello(project_dir) == "print('hello')\n" and snap["claims"] == []
    assert [t["result"] for t in snap["tool_calls"] if t["origin"] == "cli"][0] == (
        'waited for Lead (of the conversation "go") to finish with hello.py')


def test_what_its_own_sub_agent_changes_goes_into_the_project_with_the_native_agents_changes(
    claude_app, wait_run, project_dir, settings_env  # noqa: F811
):
    """Claude Code's own Agent tool runs in the same process, and so in the same copy. It
    is a tool call of the agent's, not an agent: there is no row to put a copy on."""
    inner = {"tool": "Write", "parent": "toolu_sub",
             "input": {"file_path": "CWD/sub.txt", "content": "by its helper\n"},
             "write": ["sub.txt", "by its helper\n"]}
    client, provider, _ = claude_app([
        {"tool": "Agent", "id": "toolu_sub", "open": True,
         "input": {"description": "Help", "prompt": "write sub.txt"}},
        {"say": "On it.", "parent": "toolu_sub"}, inner,
        {"result_for": "toolu_sub", "result": "Wrote it."},
        WRITE, {"say": "Done."}], default_steps=LEAD)
    cid, run_id = begin(client, project_dir, provider, mode="ask")
    # (Since slice 89b its Agent tool reaches KOLONİ through its hook: at Ask, a card.)
    (asked,) = until(client, cid, lambda s: s["questions"], timeout=20)["questions"]
    assert "Agent" in asked["question"]
    client.post(f"/api/questions/{asked['id']}/answer", json={"answer": "Allow"},
                headers={"Origin": ORIGIN})
    snap = until(client, cid, lambda s: [m["status"] for m in s["merges"]] == ["pending"],
                 timeout=20)
    assert not (project_dir / "sub.txt").exists()
    assert [a["name"] for a in snap["agents"]] == ["Lead", "Coder"]
    coder = agent(snap, "Coder")["id"]
    assert [(c["path"], c["status"], c["agent_id"]) for c in snap["file_changes"]] == [
        ("sub.txt", "in_copy", coder), ("hello.py", "in_copy", coder)]
    sub = next(t for t in snap["tool_calls"] if t["name"] == "claude__Agent")
    wrote = next(t for t in snap["tool_calls"] if t["id"] == snap["file_changes"][0]["tool_call_id"])
    assert wrote["parent_call_id"] == sub["id"]
    (card,) = snap["merges"]
    assert files(card) == {"hello.py": "ready", "sub.txt": "ready"}
    assert client.post(f"/api/merges/{card['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id, timeout=20)
    assert (project_dir / "sub.txt").read_text(encoding="utf-8") == "by its helper\n"
    assert hello(project_dir) == "print('hello')\n"


def test_stop_keeps_a_native_sub_agents_copy_for_the_user(
    claude_app, wait_run, project_dir, settings_env  # noqa: F811
):
    """6 Nov: Stop keeps its half work behind a kept card - nothing of it in the project."""
    client, provider, _ = claude_app([WRITE, {"hang": True}], default_steps=LEAD)
    cid, run_id = begin(client, project_dir, provider)
    until(client, cid, lambda s: changes(s) == [("hello.py", "in_copy", "cli")], timeout=20)
    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 202
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "cancelled"
    (kept,) = snap["merges"]
    assert kept["status"] == "kept" and files(kept) == {"hello.py": "ready"}
    assert hello(project_dir) == "print('hi')\n"
    assert len(copies_left(settings_env)) == 1 and snap["claims"] == []
    assert client.post(f"/api/merges/{kept['id']}/approve").status_code == 200
    assert hello(project_dir) == "print('hello')\n" and copies_left(settings_env) == []


def test_a_native_lead_works_in_the_project_as_before(
    claude_app, wait_run, project_dir, settings_env  # noqa: F811
):
    lead_write = {**WRITE, "input": {"file_path": "PROJECT/hello.py",
                                     "content": "print('hello')\n"}}
    client, provider, _ = claude_app([lead_write, {"say": "Fixed."}])
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "full_auto", "provider_id": provider["id"], "lead_hands_code": False})
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()[
        "run"]["id"]
    snap = wait_run(client, cid, run_id, timeout=20)
    seen = claude_app.record()
    assert seen["cwd"] == str(project_dir) and "--add-dir" not in seen["argv"]
    assert seen["git_ceiling"] == os.environ.get("GIT_CEILING_DIRECTORIES")  # git works there
    assert "copy of the project" not in seen["stdin"]
    assert agent(snap, "Lead")["copy"] is None and snap["merges"] == []
    assert changes(snap) == [("hello.py", "applied", "cli")]
    assert hello(project_dir) == "print('hello')\n" and copies_left(settings_env) == []


# --- Codex --------------------------------------------------------------------------------


def test_what_a_native_codex_sub_agent_changes_is_found_in_its_copy_and_taken_at_the_end(
    native_app, wait_run, project_dir, settings_env  # noqa: F811
):
    (project_dir / "old.txt").write_text("old\n", encoding="utf-8")
    client, provider, default = native_app(
        [{"write": "hello.py", "content": "print('hello')\n"},
         {"run": "make", "output": "ok\n", "touches": {"made.txt": "by a command\n"}},
         {"delete": "old.txt"}, {"koloni": "ask_user", "args": {"question": "Go on?"}},
         {"say": "Changed the greeting."}],
        default_steps=[LEAD[0], text("Not for me to say."), LEAD[1]])  # (K-fullauto-sorma: asked, the Lead gives no answer: the user is asked)
    cid, run_id = begin(client, project_dir, provider)
    snap = until(client, cid, lambda s: s["questions"], timeout=20)
    # while it works: in its copy, and on record as there - nothing in the project yet
    assert sorted(changes(snap)) == [
        ("hello.py", "in_copy", "cli"), ("made.txt", "in_copy", "cli"),
        ("old.txt", "in_copy", "cli")]
    assert hello(project_dir) == "print('hi')\n" and (project_dir / "old.txt").is_file()
    assert not (project_dir / "made.txt").exists()
    coder = agent(snap, "Coder")
    assert coder["copy"] == {"state": "own"}
    seen = native_app.record()
    tree = copies.folder(load_settings(settings_env).runtime_root) / coder["id"] / copies.TREE
    assert Path(seen["cwd"]) == tree
    assert seen["thread"]["cwd"] == str(tree)
    assert seen["git_ceiling"] == str(tree.parent.parent)
    assert "a copy of the project of your own" in seen["stdin"]
    question = snap["questions"][0]
    assert client.post(f"/api/questions/{question['id']}/answer",
                       json={"answer": "yes"}).status_code == 200
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert hello(project_dir) == "print('hello')\n"
    assert (project_dir / "made.txt").read_text(encoding="utf-8") == "by a command\n"
    assert not (project_dir / "old.txt").exists()
    assert sorted(changes(snap)) == [
        ("hello.py", "applied", "cli"), ("made.txt", "applied", "cli"),
        ("old.txt", "applied", "cli")]
    assert all(c["agent_id"] == coder["id"] for c in snap["file_changes"])
    assert copies_left(settings_env) == []
    # (The answer to the Coder's question follows it, told the Lead as the user's own - B-145.)
    assert reported(default.calls[-1][-2]["content"]) == "Coder finished.\n\nChanged the greeting."
    assert default.calls[-1][-1]["content"].startswith("The user answered Coder's question")


def test_a_file_that_changed_in_the_project_meanwhile_is_a_conflict_for_a_native_sub_agent_too(
    native_app, wait_run, project_dir, settings_env  # noqa: F811
):
    client, provider, _ = native_app(
        [{"write": "hello.py", "content": "print('codex')\n"},
         {"koloni": "ask_user", "args": {"question": "Go on?"}}, {"say": "Done."}],
        default_steps=LEAD)
    cid, run_id = begin(client, project_dir, provider)
    snap = until(client, cid, lambda s: s["questions"], timeout=20)
    (project_dir / "hello.py").write_text("print('the user')\n", encoding="utf-8")
    client.post(f"/api/questions/{snap['questions'][0]['id']}/answer", json={"answer": "yes"})
    snap = until(client, cid, lambda s: [m["status"] for m in s["merges"]] == ["pending"],
                 timeout=20)
    assert files(snap["merges"][0]) == {"hello.py": "conflict"}
    assert hello(project_dir) == "print('the user')\n"       # not written over unasked
    assert client.post(f"/api/merges/{snap['merges'][0]['id']}/reject").status_code == 200
    snap = wait_run(client, cid, run_id, timeout=20)
    assert hello(project_dir) == "print('the user')\n" and copies_left(settings_env) == []


def test_in_a_project_too_big_to_copy_a_native_sub_agent_works_in_the_project_as_before(
    native_app, wait_run, project_dir, settings_env, monkeypatch  # noqa: F811
):
    monkeypatch.setattr(copies, "MAX_FILES", 0)
    client, provider, _ = native_app(
        [{"write": "hello.py", "content": "print('hello')\n"}, {"say": "Done."}],
        default_steps=LEAD)
    cid, run_id = begin(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert agent(snap, "Coder")["copy"] == {"state": "too_big"} and snap["merges"] == []
    seen = native_app.record()
    assert seen["cwd"] == str(project_dir)
    assert seen["thread"]["cwd"] == str(project_dir)
    assert "copy of the project" not in seen["stdin"]
    assert changes(snap) == [("hello.py", "applied", "cli")]
    assert hello(project_dir) == "print('hello')\n" and copies_left(settings_env) == []


def test_a_native_sub_agent_that_cannot_be_started_gets_no_copy_of_the_project(
    native_app, wait_run, project_dir, settings_env, tmp_path  # noqa: F811
):
    """A skill of the user's that cannot be switched off: Codex is not started - and the
    project was copied first, for nothing."""
    skill = tmp_path / "codex-home" / "skills" / "it's"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: x\n---\n", encoding="utf-8")
    client, provider, default = native_app([{"say": "never"}], default_steps=LEAD)
    cid, run_id = begin(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=20)
    coder = agent(snap, "Coder")
    assert coder["status"] == "failed" and "cannot be switched off" in coder["error"]
    assert coder["copy"] is None and copies_left(settings_env) == [] and snap["merges"] == []
    assert not (tmp_path / "record.json").exists()
    # and a check of the provider says the same, rather than that all is well
    said = client.post(f"/api/providers/{provider['id']}/test").json()
    assert said["ok"] is False and "cannot be switched off" in said["error"]


def test_a_native_sub_agent_that_fails_leaves_a_card_with_what_it_had_changed(
    native_app, wait_run, project_dir, settings_env  # noqa: F811
):
    client, provider, default = native_app(
        [{"write": "hello.py", "content": "print('half')\n"}, {"exit": 3, "stderr": "boom"}],
        default_steps=LEAD)
    cid, run_id = begin(client, project_dir, provider)      # full auto: asked all the same
    # B-322: the lead hears at once, and the card waits for the user after the turn
    snap = wait_run(client, cid, run_id, timeout=20)
    assert agent(snap, "Coder")["status"] == "failed"
    assert snap["merges"][0]["status"] == "kept"
    assert files(snap["merges"][0]) == {"hello.py": "ready"}
    assert changes(snap) == [("hello.py", "in_copy", "cli")]
    assert hello(project_dir) == "print('hi')\n"
    told = default.calls[1][-1]["content"]
    assert told.startswith("Coder failed: Codex exited with code 3") and "(hello.py)" in told
    assert client.post(f"/api/merges/{snap['merges'][0]['id']}/approve").status_code == 200
    snap = client.get(f"/api/conversations/{cid}").json()
    assert hello(project_dir) == "print('half')\n"
    assert changes(snap) == [("hello.py", "applied", "cli")]
    assert copies_left(settings_env) == []


def test_what_another_agents_merge_puts_in_a_native_agents_copy_is_not_put_down_to_it(
    native_app, wait_run, project_dir, settings_env  # noqa: F811
):
    """The project's file changed and the copy, which had not changed it, got the new one:
    that is not something the CLI did."""
    client, provider, _ = native_app(
        [{"koloni": "ask_user", "args": {"question": "Go on?"}},
         {"write": "mine.txt", "content": "mine\n"}, {"say": "Done."}],
        default_steps=LEAD)
    cid, run_id = begin(client, project_dir, provider, "auto_edit")
    snap = until(client, cid, lambda s: s["questions"], timeout=20)
    runner = client.app.state.runner
    (copy,) = [c for c in runner._copies.values() if c is not None]
    (project_dir / "hello.py").write_text("print('taken in')\n", encoding="utf-8")
    assert copy.refresh("hello.py")                  # as another agent's merge does
    lead = next(ctx for ctx in runner._ctxs.values() if ctx.depth == 0)
    client.portal.call(runner._seen_by_watchers, lead, {"hello.py"})  # and tells the watches
    client.post(f"/api/questions/{snap['questions'][0]['id']}/answer", json={"answer": "yes"})
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert changes(snap) == [("mine.txt", "applied", "cli")]
    assert hello(project_dir) == "print('taken in')\n"


def test_an_agent_a_native_sub_agent_opens_works_in_its_copy_and_goes_in_with_it(
    native_app, wait_run, project_dir, settings_env  # noqa: F811
):
    client, provider, _ = native_app(
        [{"koloni": "spawn_agent", "args": {"role": "Writer", "task": "make a file"}},
         {"write": "hello.py", "content": "print('hello')\n"},
         {"koloni": "ask_user", "args": {"question": "Go on?"}}, {"say": "Done."}],
        default_steps={"Lead": LEAD, "Writer": [
            step(call("write_file", {"path": "made.txt", "content": "new\n"})), text("made")]})
    assert client.post("/api/roles", headers={"Origin": ORIGIN}, json={
        "name": "Writer", "tools": ["read_file", "write_file"]}).status_code == 201
    cid, run_id = begin(client, project_dir, provider, "auto_edit")
    snap = until(client, cid, lambda s: s["questions"], timeout=20)
    by = {a["id"]: a["name"] for a in snap["agents"]}
    # each change is its maker's, and both are in the one copy
    assert sorted((c["path"], c["status"], c["origin"], by[c["agent_id"]])
                  for c in snap["file_changes"]) == [
        ("hello.py", "in_copy", "cli", "Coder"), ("made.txt", "in_copy", "koloni", "Writer")]
    assert agent(snap, "Writer")["copy"] == {"state": "parent"}
    assert not (project_dir / "made.txt").exists() and len(copies_left(settings_env)) == 1
    client.post(f"/api/questions/{snap['questions'][0]['id']}/answer", json={"answer": "yes"})
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert (project_dir / "made.txt").read_text(encoding="utf-8") == "new\n"
    assert hello(project_dir) == "print('hello')\n"
    assert sorted(changes(snap)) == [
        ("hello.py", "applied", "cli"), ("made.txt", "applied", "koloni")]
    assert copies_left(settings_env) == []


def test_a_native_lead_that_opens_a_native_sub_agent_stays_in_the_project(
    native_app, wait_run, project_dir, settings_env  # noqa: F811
):
    # every agent is Codex with one script: each writes its own file, then opens a Coder
    # until the depth limit says no (the Lead, not waited on, reads its Coder's report after)
    client, provider, _ = native_app(
        [{"write": "hello.py", "content": "print('hello')\n"},
         {"koloni": "spawn_agent", "args": {"role": "Coder", "task": "go deeper"}},
         {"say": "Done."}], later_script=[{"say": "Done."}], later_when="Message from Coder")
    cid, run_id = begin(client, project_dir, provider, lead=provider)
    snap = wait_run(client, cid, run_id, timeout=60)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    by = {a["name"]: a for a in snap["agents"]}
    assert {name: (a["copy"] or {}).get("state") for name, a in by.items()} == {
        "Lead": None, "Coder": "own", "Coder 2": "parent"}
    assert hello(project_dir) == "print('hello')\n" and copies_left(settings_env) == []
    # the lead's was written in the project; the others' had nothing left to change
    assert [(c["path"], c["status"], c["agent_id"]) for c in snap["file_changes"]] == [
        ("hello.py", "applied", by["Lead"]["id"])]


# --- how each CLI is started --------------------------------------------------------------


def test_the_arguments_a_native_cli_is_started_with_in_a_copy(tmp_path):
    tree, linked = tmp_path / "copies" / "a1" / "tree", (str(tmp_path / "proj" / "node_modules"),
                                                         str(tmp_path / "proj" / "web" / ".venv"))
    bridge = tmp_path / "bridge.json"
    claude = ClaudeNativeClient(launcher=["x"])._native_arguments(tree, bridge, (), linked)
    assert [claude[i + 1] for i, a in enumerate(claude) if a == "--add-dir"] == list(linked)
    assert "--add-dir" not in ClaudeNativeClient(launcher=["x"])._native_arguments(tree, bridge)
    codex = CodexNativeClient(launcher=["x"])._native_arguments(tree, bridge, (), linked)
    # (Its folder goes in thread/start.) The linked folders are not made writable for it.
    assert codex[-1] == "app-server" and not [a for a in codex for one in linked if one in a]
    # which of them a sub-agent gets a copy with
    assert ClaudeNativeClient.own_copy and CodexNativeClient.own_copy
    assert not CopilotNativeClient.own_copy
    # agy: natively (not tried against the real CLI); reading only, it changes nothing
    assert AgyClient(reads=False).own_copy and not AgyClient().own_copy
    assert not AgyClient(reads=False).talker().own_copy


# --- agy, native (with the stand-in only: the real CLI was not run with the flag) ---------


def test_a_native_agy_sub_agent_works_in_its_copy_and_its_change_is_taken_at_the_end(
    agy_app, wait_run, project_dir, settings_env  # noqa: F811
):
    client, provider, default = agy_app([
        {"tool": "write_to_file", "asks": True, "parameters": {"TargetFile": "hello.py"},
         "touches": {"hello.py": "print('hello')\n"}, "output": "written"},
        {"say": "Fixed."}], mode="native", default_steps=LEAD)
    cid, run_id = begin(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    coder = agent(snap, "Coder")
    assert coder["copy"] == {"state": "own"} and agent(snap, "Lead")["copy"] is None
    seen = agy_app.record()
    tree = copies.folder(load_settings(settings_env).runtime_root) / coder["id"] / copies.TREE
    assert Path(seen["cwd"]) == tree and SKIP in seen["argv"]
    assert seen["env"]["GIT_CEILING_DIRECTORIES"] == str(tree.parent.parent)
    told = json.loads(seen["stdin"])["message"]["content"]
    assert f'The project folder is "{tree}"' in told
    assert "a copy of the project of your own" in told
    # its copy has none of the project's dependency folders, and it is not told it has
    assert NOT_LINKED_IN in told and "shared with it" not in told
    assert hello(project_dir) == "print('hello')\n"           # taken when its work was over
    assert changes(snap) == [("hello.py", "applied", "cli")]
    assert snap["file_changes"][0]["agent_id"] == coder["id"]
    assert copies_left(settings_env) == [] and snap["claims"] == []
    assert reported(default.calls[1][-1]["content"]) == "Coder finished.\n\nFixed."


def test_two_native_agy_sub_agents_each_in_a_copy_still_take_turns(
    agy_app, wait_run, project_dir, tmp_path  # noqa: F811
):
    # B-199 review: its commands are not kept to its copy (`_sandboxed`): one at a time.
    go = tmp_path / "go"
    client, provider, _ = agy_app([
        {"tool": "view_file", "parameters": {"AbsolutePath": "hello.py"}, "output": "x",
         "wait_for": str(go)}, {"say": "Looked."}], mode="native",
        default_steps={"Lead": [step(call("spawn_agent", {"role": "Coder", "task": "A"}, "s1"),
                                     call("spawn_agent", {"role": "Coder", "task": "B"}, "s2")),
                                text("done")]})
    cid, run_id = begin(client, project_dir, provider)
    until(client, cid, lambda s: sorted(a["status"] for a in s["agents"][1:]) == [
        "queued", "running"], timeout=20)
    go.write_text("")
    snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]


def test_two_native_agy_reviewers_work_at_the_same_time(
    agy_app, wait_run, project_dir, tmp_path  # noqa: F811
):
    # R102 (3): one that changes nothing has nothing to tell apart from the other's work.
    go = tmp_path / "go"
    client, provider, _ = agy_app([
        {"tool": "view_file", "parameters": {"AbsolutePath": "hello.py"}, "output": "x",
         "wait_for": str(go)}, {"say": "Looked."}], mode="native",
        default_steps={"Lead": [step(call("spawn_agent", {"role": "Reviewer", "task": "A"}, "s1"),
                                     call("spawn_agent", {"role": "Reviewer", "task": "B"}, "s2")),
                                text("done")]})
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={"provider_id": provider["id"]},
                 headers={"Origin": ORIGIN})
    cid, run_id = begin(client, project_dir, provider)
    until(client, cid, lambda s: [a["status"] for a in s["agents"][1:]] == ["running", "running"],
          timeout=20)
    # (What changes beside them meanwhile is not put down to either: neither writes.)
    (project_dir / "beside.txt").write_text("someone else's\n", encoding="utf-8")
    go.write_text("")
    snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert snap["file_changes"] == []


def test_a_reading_agy_sub_agent_gets_no_copy(
    agy_app, wait_run, project_dir, settings_env  # noqa: F811
):
    client, provider, _ = agy_app([{"say": "It prints hi."}], default_steps=LEAD)
    cid, run_id = begin(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert agent(snap, "Coder")["copy"] is None and snap["merges"] == []
    seen = agy_app.record()
    assert seen["cwd"] == str(project_dir) and SKIP not in seen["argv"]
    assert seen["env"].get("GIT_CEILING_DIRECTORIES") == os.environ.get("GIT_CEILING_DIRECTORIES")
    assert copies_left(settings_env) == []
