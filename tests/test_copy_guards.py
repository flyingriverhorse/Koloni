"""Guards around working copies that the review of slice 19c found no test for: each test
here fails with its guard taken out. And what a native Codex sub-agent writes straight into
the project, by an absolute path, from its copy.
"""

import os
from pathlib import Path

import pytest
from sqlalchemy import select

from app import copies, observer
from app.agent import IN_THE_PROJECT
from app.api.undo import BY_WHOM
from app.config import load_settings
from app.db.models import Merge
from app.db.session import make_engine, make_session_factory
from app.main import create_app
from tests.conftest import Gate
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_agy_agent import agy_app  # noqa: F401  (a fixture)
from tests.test_chat_flow import text
from tests.test_claim_scenarios import agent, calls, write
from tests.test_claude_native import claude_app, hello  # noqa: F401  (a fixture)
from tests.test_copy_later_scenarios import again, interrupted
from tests.test_copy_places import mark
from tests.test_copy_runner import ORIGIN, at_work, card_of, kept_folders
from tests.test_copy_scenarios import files, one, run, seen
from tests.test_native_agent import native_app  # noqa: F401  (a fixture)
from tests.test_native_copies import LEAD, WRITE, begin, changes, copies_left
from tests.test_parallel import until
from tests.test_spawn import call, role_id, spawn, step
from tests.test_trigger_scenarios import run_now, trigger


def by_the_cli(snap):
    return [t["result"] for t in snap["tool_calls"] if t["origin"] == "cli"]


def test_a_path_a_native_sub_agent_names_in_its_copy_is_looked_up_in_the_copy(
    claude_app, wait_run, project_dir, settings_env  # noqa: F811
):
    """Looked up in the project, the file it wrote in its copy was a file "outside"."""
    client, provider, _ = claude_app([WRITE, {"say": "Fixed."}], default_steps=LEAD)
    cid, run_id = begin(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert by_the_cli(snap) == ["changed by the CLI: hello.py (+1 -1)"]


def test_what_is_written_in_the_project_is_not_looked_for_in_a_native_agents_copy(
    native_app, wait_run, project_dir, settings_env  # noqa: F811
):
    """A CLI at work in a copy is not beside an agent that writes in the project: looked
    at for that, what its copy holds went on record as changed in the project."""
    client, provider, _ = native_app(
        [{"koloni": "ask_user", "args": {"question": "Go on?"}}, {"say": "Done."}],
        default_steps=LEAD)
    cid, run_id = begin(client, project_dir, provider)
    snap = until(client, cid, lambda s: s["questions"], timeout=20)
    runner = client.app.state.runner
    (copy,) = [c for c in runner._copies.values() if c is not None]
    (copy.root / "silent.txt").write_text("not said yet\n", encoding="utf-8")
    lead = next(ctx for ctx in runner._ctxs.values() if ctx.depth == 0)
    client.portal.call(runner._seen_by_watchers, lead, {"elsewhere.txt"})
    assert client.get(f"/api/conversations/{cid}").json()["file_changes"] == []
    client.post(f"/api/questions/{snap['questions'][0]['id']}/answer", json={"answer": "yes"})
    snap = wait_run(client, cid, run_id, timeout=20)
    # in the project only once its copy was taken in
    assert [c[:2] for c in changes(snap)] == [("silent.txt", "applied")]
    assert (project_dir / "silent.txt").read_text(encoding="utf-8") == "not said yet\n"


def test_a_hand_change_in_the_project_while_an_asking_cli_works_in_its_copy_is_on_record(
    native_app, wait_run, project_dir, settings_env  # noqa: F811
):
    """B4-04 (live, 25 Oct): a CLI that asks first and keeps to its copy (Codex, Claude Code)
    had the project watched by no look - a file changed there by hand was on no record, and
    Undo this turn said nothing of it. Now it is, as one whose maker is not known (K-70-kimin)."""
    client, provider, _ = native_app(
        [{"koloni": "ask_user", "args": {"question": "Go on?"}}, {"say": "Done."}],
        default_steps=LEAD)
    cid, run_id = begin(client, project_dir, provider, "auto_edit")
    snap = until(client, cid, lambda s: s["questions"], timeout=20)
    (project_dir / "notes.md").write_text("by hand\n", encoding="utf-8")
    client.post(f"/api/questions/{snap['questions'][0]['id']}/answer", json={"answer": "yes"})
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert any(said.startswith(f"{IN_THE_PROJECT}: notes.md") for said in by_the_cli(snap))
    said = client.get(f"/api/runs/{run_id}/undo").json()
    assert {"path": "notes.md", "why": BY_WHOM} in said["skip"] and "notes.md" not in said["revert"]
    assert (project_dir / "notes.md").read_text(encoding="utf-8") == "by hand\n"
    # Nor is it the CLI's work in the project, where a team's is told (B-84's `_taken`), nor in
    # what the Observer reads of its work: what the user wrote goes to no model.
    assert client.app.state.runner._taken(run_id) == set()
    (cli,) = [a for a in snap["agents"] if a["depth"] == 1]
    with client.app.state.session_factory() as session:
        assert "notes.md" not in observer.on_record(session, cli["id"])


def test_a_secret_file_changed_by_hand_beside_a_cli_in_its_copy_is_named_and_kept_nowhere(
    native_app, wait_run, project_dir, settings_env  # noqa: F811
):
    """B4-04's review: the user's .env edit became a change of the CLI's, with what it held -
    which the Observer would read. Only its name is on record."""
    client, provider, _ = native_app(
        [{"koloni": "ask_user", "args": {"question": "Go on?"}}, {"say": "Done."}],
        default_steps=LEAD)
    (project_dir / ".env").write_text("KEY=old-value-1\n", encoding="utf-8")
    cid, run_id = begin(client, project_dir, provider, "auto_edit")
    snap = until(client, cid, lambda s: s["questions"], timeout=20)
    (project_dir / ".env").write_text("KEY=new-value-2\n", encoding="utf-8")
    client.post(f"/api/questions/{snap['questions'][0]['id']}/answer", json={"answer": "yes"})
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert f"{IN_THE_PROJECT}: .env (a secret file: KOLONİ keeps no copy of it)" in by_the_cli(snap)
    assert ".env" not in [c[0] for c in changes(snap)]
    assert "value-1" not in str(snap) and "value-2" not in str(snap)


def test_what_a_native_codex_sub_agent_would_write_straight_into_the_project_is_refused(
    native_app, wait_run, project_dir, settings_env  # noqa: F811
):
    """By an absolute path, from its copy: before slice 89a it was written and put on
    record; now that Codex asks first it is refused, as Claude Code's is (`_approve`)."""
    client, provider, _ = native_app([
        {"write_abs": str(project_dir / "hello.py"), "content": "print('straight in')\n"},
        {"write": "mine.txt", "content": "in the copy\n"},
        {"koloni": "ask_user", "args": {"question": "Go on?"}}, {"say": "Done."}],
        default_steps=LEAD)
    cid, run_id = begin(client, project_dir, provider, "auto_edit")
    snap = until(client, cid, lambda s: s["questions"], timeout=20)
    assert sorted(changes(snap)) == [("mine.txt", "in_copy", "cli")]
    assert hello(project_dir) == "print('hi')\n"  # never written
    assert [a["answer"] for a in native_app.record()["answers"] if "fileChange" in a["method"]] == [
        {"decision": "decline"}, {"decision": "accept"}]
    assert any("outside your working copy" in said for said in by_the_cli(snap))
    client.post(f"/api/questions/{snap['questions'][0]['id']}/answer", json={"answer": "yes"})
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert (project_dir / "mine.txt").read_text(encoding="utf-8") == "in the copy\n"
    assert hello(project_dir) == "print('hi')\n" and copies_left(settings_env) == []


def test_what_a_native_agy_sub_agent_would_write_straight_into_the_project_is_refused(
    agy_app, wait_run, project_dir, settings_env  # noqa: F811
):
    """By an absolute path, from its copy: before slice 89e it was written and put on
    record; now that agy asks first through its hook it is refused, as Codex's is."""
    target = str(project_dir / "hello.py")
    client, provider, _ = agy_app([
        {"tool": "write_to_file", "parameters": {"TargetFile": target},
         "touches": {target: "print('straight in')\n"}},
        {"tool": "write_to_file", "parameters": {"TargetFile": "mine.txt"},
         "touches": {"mine.txt": "in the copy\n"}},
        {"say": "Done."}], mode="native", default_steps=LEAD)
    cid, run_id = begin(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert sorted(changes(snap)) == [("mine.txt", "applied", "cli")]
    assert any("outside your working copy" in said for said in by_the_cli(snap))
    assert hello(project_dir) == "print('hi')\n"  # never written
    assert (project_dir / "mine.txt").read_text(encoding="utf-8") == "in the copy\n"
    assert copies_left(settings_env) == []


def the_copy(client):
    (copy,) = [c for c in client.app.state.runner._copies.values() if c is not None]
    return copy


def test_a_native_agy_copy_links_no_folder_of_the_projects(
    agy_app, wait_run, project_dir, settings_env, tmp_path  # noqa: F811
):
    """Nothing asks before it writes: under a linked folder its write went into the
    project's own node_modules, unrecorded. (And it is started there: with the links made
    all the same, it was refused its own copy and every check below held.)"""
    (project_dir / "node_modules" / "pkg").mkdir(parents=True)
    (project_dir / "node_modules" / "pkg" / "index.js").write_text("dep", encoding="utf-8")
    go = tmp_path / "go"
    client, provider, _ = agy_app([
        {"tool": "view_file", "parameters": {"AbsolutePath": "hello.py"}, "wait_for": str(go)},
        {"tool": "write_to_file", "parameters": {"TargetFile": "node_modules/pkg/evil.js"},
         "touches": {"node_modules/pkg/evil.js": "x"}},
        {"say": "Done."}], mode="native", default_steps=LEAD)
    cid, run_id = begin(client, project_dir, provider)
    until(client, cid, lambda s: agy_app.ran(), timeout=20)
    copy = the_copy(client)
    assert copy.links == {} and not (copy.root / "node_modules").exists()
    go.touch()
    snap = wait_run(client, cid, run_id, timeout=20)
    assert agent(snap, "Coder")["status"] == "completed", agent(snap, "Coder")["error"]
    assert not (project_dir / "node_modules" / "pkg" / "evil.js").exists()
    assert (project_dir / "node_modules" / "pkg" / "index.js").read_text(encoding="utf-8") == "dep"


def test_a_native_codex_copy_has_the_projects_dependency_folders_linked_in(
    native_app, wait_run, project_dir, settings_env  # noqa: F811
):
    """Its sandbox keeps it to its folder: it gets them as every other agent does."""
    (project_dir / "node_modules" / "pkg").mkdir(parents=True)
    (project_dir / "node_modules" / "pkg" / "index.js").write_text("dep", encoding="utf-8")
    client, provider, _ = native_app(
        [{"koloni": "ask_user", "args": {"question": "Go on?"}}, {"say": "Done."}],
        default_steps=LEAD)
    cid, run_id = begin(client, project_dir, provider)
    snap = until(client, cid, lambda s: s["questions"], timeout=20)
    copy = the_copy(client)
    assert list(copy.links) and (copy.root / "node_modules" / "pkg" / "index.js").is_file()
    client.post(f"/api/questions/{snap['questions'][0]['id']}/answer", json={"answer": "yes"})
    wait_run(client, cid, run_id, timeout=20)


# --- the second review of slice 20b: native agy, which nothing keeps to its copy -------------


def test_what_a_command_of_native_agy_writes_into_the_project_is_on_record_as_that(
    agy_app, wait_run, project_dir, settings_env, tmp_path  # noqa: F811
):
    """A command names no file: the project's file changed, and no list of changes had it."""
    go = tmp_path / "go"
    client, provider, _ = agy_app([
        {"tool": "run_command", "parameters": {"CommandLine": "python fix.py"},
         "touches": {str(project_dir / "hello.py"): "print('straight in')\n"}},
        {"tool": "view_file", "parameters": {"AbsolutePath": "hello.py"}, "wait_for": str(go)},
        {"say": "Done."}], mode="native", default_steps=LEAD)
    cid, run_id = begin(client, project_dir, provider)
    # found by the look after the command, while it is still at work
    snap = until(client, cid, lambda s: s["file_changes"], timeout=20)
    assert changes(snap) == [("hello.py", "applied", "cli")]
    (direct,) = snap["file_changes"]
    assert direct["agent_id"] == agent(snap, "Coder")["id"]
    # who changed it is not known: the user, or another agent, may have (K-70-kimin)
    assert f"{IN_THE_PROJECT}: hello.py (+1 -1)" in by_the_cli(snap)
    assert "who changed it is not known" in IN_THE_PROJECT
    go.touch()
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert changes(snap) == [("hello.py", "applied", "cli")]
    # so Undo this turn does not take it back: that is the user's to do, on its own row
    for undo in (client.get, client.post):
        said = undo(f"/api/runs/{run_id}/undo").json()
        assert said["revert"] == [] and said["skip"] == [{"path": "hello.py", "why": BY_WHOM}]
    assert hello(project_dir) == "print('straight in')\n"
    assert client.post(f"/api/file-changes/{direct['id']}/revert").status_code == 200
    assert hello(project_dir) == "print('hi')\n" and copies_left(settings_env) == []


def test_what_another_agents_merge_brings_into_the_project_is_not_put_down_to_native_agy(
    agy_app, wait_run, project_dir, settings_env, tmp_path  # noqa: F811
):
    """Nor does that merge take what agy changed there unseen off the record: sneaky.txt
    was written by a step that is no command and names no path."""
    go, held = tmp_path / "go", Gate()
    client, provider, _ = agy_app([
        {"tool": "view_file", "parameters": {"AbsolutePath": "hello.py"},
         "touches": {str(project_dir / "sneaky.txt"): "agy's\n"}},
        {"tool": "view_file", "parameters": {"AbsolutePath": "hello.py"}, "wait_for": str(go)},
        {"say": "Done."}], mode="native", default_steps={
            "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "work"}, "s1"),
                          call("spawn_agent", {"role": "Writer", "task": "write"}, "s2")),
                     text("done")],
            "Writer": [held.step(step(write("other.txt", "the writer's\n"))), text("made")]})
    client.headers["Origin"] = ORIGIN
    client.patch(f"/api/roles/{role_id(client, 'Coder')}", json={"provider_id": provider["id"]})
    assert client.post("/api/roles", json={
        "name": "Writer", "tools": ["read_file", "write_file"]}).status_code == 201
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "full_auto", "spawn_approval": "never", "spawn_max_parallel": 2})
    run_id = client.post(
        f"/api/conversations/{cid}/messages", json={"content": "go"}).json()["run"]["id"]
    until(client, cid, lambda s: (project_dir / "sneaky.txt").exists(), timeout=20)
    held.release()                      # the Writer's copy is taken in while agy works
    snap = until(client, cid, lambda s: agent(s, "Writer")["status"] == "completed", timeout=20)
    by = {a["id"]: a["name"] for a in snap["agents"]}

    def on_record(snap):
        return sorted((c["path"], c["status"], c["origin"], by[c["agent_id"]])
                      for c in snap["file_changes"])

    both = [("other.txt", "applied", "koloni", "Writer"), ("sneaky.txt", "applied", "cli", "Coder")]
    assert on_record(snap) == both
    go.touch()
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert on_record(snap) == both
    assert (project_dir / "other.txt").read_text(encoding="utf-8") == "the writer's\n"


def test_a_change_the_user_takes_back_while_native_agy_works_is_not_put_down_to_it(
    agy_app, wait_run, project_dir, settings_env, tmp_path  # noqa: F811
):
    """KOLONİ's own write in the project: agy's next look found the file gone, as its doing."""
    go = tmp_path / "go"
    client, provider, _ = agy_app([
        {"tool": "view_file", "parameters": {"AbsolutePath": "hello.py"}, "wait_for": str(go)},
        {"say": "Done."}], mode="native", default_steps=[step(write("lead.txt", "x")), *LEAD])
    cid, run_id = begin(client, project_dir, provider)
    snap = until(client, cid, lambda s: agy_app.ran(), timeout=20)
    (made,) = snap["file_changes"]
    assert client.post(f"/api/file-changes/{made['id']}/revert").status_code == 200
    assert not (project_dir / "lead.txt").exists()
    go.touch()
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [(c["path"], c["status"], c["origin"]) for c in snap["file_changes"]] == [
        ("lead.txt", "reverted", "koloni")]


def test_what_native_agy_changes_in_the_project_by_a_step_that_names_nothing_is_found_at_its_end(
    agy_app, wait_run, project_dir, settings_env  # noqa: F811
):
    client, provider, _ = agy_app([
        {"tool": "view_file", "parameters": {"AbsolutePath": "hello.py"},
         "touches": {str(project_dir / "sneaky.txt"): "agy's\n"}},
        {"say": "Done."}], mode="native", default_steps=LEAD)
    cid, run_id = begin(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=20)
    assert changes(snap) == [("sneaky.txt", "applied", "cli")]
    assert snap["file_changes"][0]["agent_id"] == agent(snap, "Coder")["id"]


def test_a_write_of_native_agy_that_changed_nothing_is_not_said_to_have_changed_a_file(
    agy_app, wait_run, project_dir, settings_env, tmp_path  # noqa: F811
):
    """One that ended in an error was put down as `edit_file succeeded - changed a file
    outside its working copy`, for a file of the project's that had not changed. (Since
    slice 89e one outside its copy is refused before it runs.)"""
    target = str(project_dir / "hello.py")
    client, provider, _ = agy_app([
        {"tool": "write_to_file", "parameters": {"TargetFile": target}, "error": "disk full"},
        {"tool": "write_to_file", "parameters": {"TargetFile": str(tmp_path / "out.txt")},
         "error": "disk full"},
        {"tool": "write_to_file", "parameters": {"TargetFile": "hello.py"}, "error": "disk full"},
        # done, and the project's file it named is as it was
        {"tool": "write_to_file", "parameters": {"TargetFile": target}},
        {"say": "Done."}], mode="native", default_steps=LEAD)
    cid, run_id = begin(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [(t["name"], t["status"]) for t in snap["tool_calls"] if t["origin"] == "cli"] == [
        ("edit_file", "denied"), ("edit_file", "denied"), ("agy__write_to_file", "failed"),
        ("edit_file", "denied")]
    assert snap["file_changes"] == [] and hello(project_dir) == "print('hi')\n"


def test_a_path_native_agy_names_from_its_copy_is_followed_from_the_copy(
    agy_app, wait_run, project_dir, settings_env  # noqa: F811
):
    """`..\\..\\x` was followed from the folder the server runs in: the project's file it
    leads to from the copy was called a file outside, of which KOLONİ keeps no copy. (Since
    slice 89e it is followed from the copy before it runs, and refused: out of the copy.)"""
    tree = copies.folder(load_settings(settings_env).runtime_root) / "any" / copies.TREE
    up = os.path.relpath(project_dir / "hello.py", tree)
    assert not Path(up).is_absolute()
    client, provider, _ = agy_app([
        {"tool": "write_to_file", "parameters": {"TargetFile": up},
         "touches": {up: "print('straight in')\n"}},
        {"say": "Done."}], mode="native", default_steps=LEAD)
    cid, run_id = begin(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=20)
    assert hello(project_dir) == "print('hi')\n" and changes(snap) == []
    assert any("outside your working copy" in said for said in by_the_cli(snap))
    assert not any("KOLONİ keeps no copy" in said for said in by_the_cli(snap))


def test_a_reading_agy_below_an_agent_with_a_copy_reads_in_that_copy(
    agy_app, wait_run, project_dir, settings_env  # noqa: F811
):
    # B-301: a reading agy for a role that only reads is no longer kept to the project (it was,
    # as a CLI not started in a copy - `only_in_project`): it reads its line's copy, as every
    # agent that only reads does - the Coder's work so far - and, writing nothing, is not
    # refused for the copy's linked dependency folders (`links_in_copy`).
    (project_dir / "node_modules").mkdir()
    client, provider, _ = agy_app([{"say": "It prints hi."}], default_steps={
        "Lead": LEAD,
        "Coder": [step(write("notes.txt", "mine")), spawn("Helper", "look"), text("ok")]})
    client.headers["Origin"] = "http://127.0.0.1:8790"
    assert client.post("/api/roles", json={
        "name": "Helper", "tools": ["read_file"], "provider_id": provider["id"]}).status_code == 201
    cid, run_id = below_the_coder(client, project_dir)
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert agent(snap, "Helper")["status"] == "completed"
    assert agent(snap, "Coder")["copy"] == {"state": "own"}
    seen = agy_app.record()
    assert Path(seen["cwd"]).is_relative_to(copies.folder(load_settings(settings_env).runtime_root))
    assert Path(seen["cwd"]).name == copies.TREE
    assert "--dangerously-skip-permissions" not in seen["argv"]


def test_a_copy_made_without_links_has_no_dependency_folders_at_all(tmp_path, project_dir):
    """What needs them (a test run, a build) does not find them in such a copy."""
    (project_dir / "node_modules" / "pkg").mkdir(parents=True)
    (project_dir / "node_modules" / "pkg" / "index.js").write_text("dep", encoding="utf-8")
    made = copies.make(project_dir, tmp_path / "runtime", "a1", linked=False)
    assert made.links == {} and not (made.root / "node_modules").exists()
    assert (made.root / "hello.py").is_file()
    assert copies.make(project_dir, tmp_path / "runtime", "a2").links  # as before otherwise


def below_the_coder(client, project_dir):
    """A turn at full auto whose lead opens the scripted Coder, which opens the Helper."""
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "full_auto", "spawn_approval": "never"}, headers={"Origin": ORIGIN})
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()["run"]
    return cid, run["id"]


def test_native_agy_is_not_started_in_a_copy_with_linked_folders_that_another_agent_made(
    agy_app, wait_run, project_dir, settings_env  # noqa: F811
):
    (project_dir / "node_modules" / "pkg").mkdir(parents=True)
    client, provider, _ = agy_app([
        {"tool": "write_to_file", "parameters": {"TargetFile": "node_modules/pkg/evil.js"},
         "touches": {"node_modules/pkg/evil.js": "x"}},
        {"say": "Done."}], mode="native", default_steps={
            "Lead": LEAD,
            "Coder": [step(write("notes.txt", "mine")), spawn("Helper", "help"), text("ok")]})
    client.headers["Origin"] = "http://127.0.0.1:8790"
    assert client.post("/api/roles", json={
        "name": "Helper", "tools": ["read_file", "write_file", "edit_file", "run_command"],
        "provider_id": provider["id"]}).status_code == 201
    cid, run_id = below_the_coder(client, project_dir)
    snap = wait_run(client, cid, run_id, timeout=20)
    helper = agent(snap, "Helper")
    assert helper["status"] == "failed" and "dependency folders" in helper["error"]
    # true also where the copy is its own, made while it ran on another provider
    assert "cannot work in this working copy" in helper["error"]
    assert not agy_app.ran()
    assert not (project_dir / "node_modules" / "pkg" / "evil.js").exists()


def test_a_file_outside_both_the_copy_and_the_project_is_not_written(
    native_app, wait_run, project_dir, settings_env, tmp_path  # noqa: F811
):
    outside = tmp_path / "elsewhere" / "out.txt"
    client, provider, _ = native_app([
        {"write_abs": str(outside), "content": "x"}, {"say": "Done."}], default_steps=LEAD)
    cid, run_id = begin(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["file_changes"] == [] and not outside.exists()  # refused (slice 89a)
    (said,) = by_the_cli(snap)
    assert "is outside your working copy" in said


def test_a_file_apply_on_a_kept_card_shows_again_is_labelled_as_a_kept_copys_files_are(
    settings_env, project_dir
):
    """It has no diff to show: its label is all the card says of it, and that is not left
    to what the copy's folder says the file was."""
    (project_dir / "data.bin").write_bytes(b"\xfe1")
    over = "python -c \"open('data.bin','wb').write(bytes([254, 50]))\""
    cid = at_work(settings_env, project_dir, [step(run(over))])
    (folder,) = kept_folders(settings_env)
    with again(settings_env) as client:
        card = card_of(client, cid)
        assert files(card) == {"data.bin": "conflict"}
        # (slice 30) whose file is taken is the user's to say, and the card says why it asks
        assert card["files"][0]["whole"] is True and "no diff" in card["files"][0]["note"]
        (folder / "tree" / "data.bin").write_bytes(b"\xfe3")        # since the card was shown
        assert client.post(f"/api/merges/{card['id']}/approve", json={
            "choices": {"data.bin": "agent"}, "shown": seen(card)}).status_code == 409
        said = card_of(client, cid)
        assert said["status"] == "kept" and files(said) == {"data.bin": "conflict"}
        assert said["files"][0]["whole"] is True
        assert (project_dir / "data.bin").read_bytes() == b"\xfe1"


def test_a_copy_kept_as_the_app_closes_is_shown_as_of_a_turn_nobody_watched(
    settings_env, project_dir
):
    """What no trigger lets such a turn change is refused on its card from the first -
    not offered until the next start looks again."""
    held = Gate()
    app_ = create_app(load_settings(settings_env), model=ScriptedModel({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "do it"}, "s")),
                 text("done")],
        "Coder": [step(write("notes.txt", "seen")), held.step(text("A done"))],
    }))
    with TestClient(app_, base_url="http://127.0.0.1:8790") as client:
        client.headers["Origin"] = ORIGIN
        pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
        cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
        made = trigger(client, pid, cid, permissions={"write": True, "commands": [], "agents": 1})
        run_now(client, made["id"])
        held.wait_partial()
        (folder,) = kept_folders(settings_env)
        (folder / "tree" / ".claude").mkdir()                       # as a command could
        (folder / "tree" / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    held.release()
    with make_session_factory(make_engine(load_settings(settings_env).db_path))() as s:
        (merge,) = s.scalars(select(Merge)).all()
        assert merge.status == "interrupted"
        assert {one["path"]: one["state"] for one in merge.files} == {
            ".claude/settings.json": "refused", "notes.txt": "ready"}
        assert "no trigger allows" in merge.files[0]["note"]


def test_what_a_copy_was_made_from_is_not_read_through_a_link(tmp_path, project_dir):
    """A command put a link where the note was: what it leads to is somebody else's file,
    and says whatever they like of what the copy was made from."""
    made = copies.make(project_dir, tmp_path / "runtime", "a1")
    note = made.root.parent / copies.BASE_FILE
    forged = tmp_path / "forged.json"
    forged.write_text('{"files": {}}', encoding="utf-8")
    note.unlink()
    try:
        os.symlink(forged, note)
    except OSError:
        # This account may not make a link to a file (Windows): a junction, then. Without
        # the guard that is read through too, and fails as a file that cannot be read.
        copies._link(note, tmp_path)
    with pytest.raises(ValueError):
        copies.load(project_dir, tmp_path / "runtime", "a1")


def test_one_patch_of_a_native_sub_agent_to_two_of_the_projects_files_is_refused_whole(
    native_app, wait_run, project_dir, settings_env  # noqa: F811
):
    """One patch, two of the project's files, from its copy: before slice 89a both were
    written (and the second once went unrecorded); now neither is."""
    (project_dir / "other.py").write_text("print('other')\n", encoding="utf-8")
    client, provider, _ = native_app([
        {"write_abs": str(project_dir / "hello.py"), "also": [str(project_dir / "other.py")],
         "content": "print('straight in')\n"},
        {"koloni": "ask_user", "args": {"question": "Go on?"}}, {"say": "Done."}],
        default_steps=LEAD)
    cid, run_id = begin(client, project_dir, provider)
    snap = until(client, cid, lambda s: s["questions"], timeout=20)
    assert changes(snap) == []
    assert hello(project_dir) == "print('hi')\n"
    assert (project_dir / "other.py").read_text(encoding="utf-8") == "print('other')\n"
    assert [a["answer"] for a in native_app.record()["answers"]
            if "fileChange" in a["method"]] == [{"decision": "decline"}]
    client.post(f"/api/questions/{snap['questions'][0]['id']}/answer", json={"answer": "yes"})
    wait_run(client, cid, run_id, timeout=20)


def test_apply_on_a_kept_card_does_not_delete_a_file_that_was_refused(
    settings_env, project_dir, tmp_path
):
    """Its path in the project runs through a link, so it was never offered: what the
    copy holds of it is nowhere else, and goes only with Discard."""
    cid = at_work(settings_env, project_dir, [
        step(write("a.txt", "A")), step(write("sub/new.txt", "x", "w2"))])
    (folder,) = kept_folders(settings_env)
    (tmp_path / "elsewhere").mkdir()
    copies._link(project_dir / "sub", tmp_path / "elsewhere")
    with again(settings_env) as client:
        card = card_of(client, cid)
        assert files(card) == {"a.txt": "ready", "sub/new.txt": "refused"}
        said = client.post(f"/api/merges/{card['id']}/approve")
        assert said.status_code == 200 and said.json()["status"] == "kept"
        assert files(said.json()) == {"a.txt": "applied", "sub/new.txt": "refused"}
        assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"
        assert (folder / "tree" / "sub" / "new.txt").read_text(encoding="utf-8") == "x"
        assert client.post(f"/api/merges/{card['id']}/reject").status_code == 200
        assert kept_folders(settings_env) == [] and list((tmp_path / "elsewhere").iterdir()) == []


@pytest.mark.parametrize("mode", ["ask", "full_auto"])
def test_a_copy_taken_in_while_the_app_runs_is_kept_while_it_holds_a_file_that_was_refused(
    make_client, wait_run, project_dir, tmp_path, mode
):
    """After Apply on its card, or taken unasked: the refused file is nowhere but in the
    copy, which went with the rest of it. It stays as a kept card, to discard."""
    held = Gate()
    client, _model, cid, run_id = one(make_client, project_dir, [
        step(write("a.txt", "A")), step(write("sub/new.txt", "x", "w2")),
        held.step(text("A done"))], permission_mode=mode)
    held.wait_partial()
    (tmp_path / "elsewhere").mkdir()
    copies._link(project_dir / "sub", tmp_path / "elsewhere")
    held.release()
    if mode == "ask":
        snap = until(client, cid, lambda s: [m["status"] for m in s["merges"]] == ["pending"])
        assert files(snap["merges"][0]) == {"a.txt": "ready", "sub/new.txt": "refused"}
        assert client.post(f"/api/merges/{snap['merges'][0]['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id, timeout=15)
    assert snap["runs"][0]["status"] == "completed" and snap["claims"] == []
    (card,) = snap["merges"]
    assert card["status"] == "kept"
    assert files(card) == {"a.txt": "applied", "sub/new.txt": "refused"}
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"
    kept = Path(card["kept_in"])
    assert (kept / "sub" / "new.txt").read_text(encoding="utf-8") == "x"
    assert "not applied to the project: sub/new.txt (it leads out" in calls(
        snap, "Lead", "spawn_agent")[0][1]
    # nothing of it is left to apply: it is the user's to discard
    assert client.post(f"/api/merges/{card['id']}/approve").status_code == 409
    assert client.post(f"/api/merges/{card['id']}/reject").status_code == 200
    assert not kept.exists() and list((tmp_path / "elsewhere").iterdir()) == []


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_a_copy_kept_in_the_users_data_folder_is_still_found_once_copies_live_in_the_runtime_root(
    settings_env, project_dir, tmp_path, decision
):
    """Where copies are made is told by what is above the runtime root now; where a kept
    one is, by where it was made."""
    mark(tmp_path / "runtime", "AGENTS.md")             # copies are made in the user's data
    cid = interrupted(settings_env, project_dir)
    (folder,) = kept_folders(settings_env)
    assert folder.is_relative_to(tmp_path / "user-data")
    (tmp_path / "runtime" / "AGENTS.md").unlink()       # from here on, in the runtime root
    with again(settings_env) as client:
        card = card_of(client, cid)
        assert card["status"] == "kept" and files(card) == {"a.txt": "ready"}
        assert card["kept_in"] == str(folder / "tree")
        assert client.post(f"/api/merges/{card['id']}/{decision}").status_code == 200
        assert (project_dir / "a.txt").exists() == (decision == "approve")
        assert not folder.exists()
