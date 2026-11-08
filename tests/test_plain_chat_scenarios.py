"""Slice 86a's acceptance set, backend half: a chat with no folder. Written before the code.

Design: `tasarim/specs/2026-10-23-dilim-86-klasorler-design.md`, §1, §2, §6 and the user's
decisions of 24 October in §6b (those win over anything else).

Contract:
- `Conversation.project_id` may be null: a plain chat. Its root is None, never "" (which
  would be the server's own folder, KOLONİ itself).
- `POST /api/conversations` {project_id?} makes a chat (none: a plain one; an unknown
  project: 404); `GET /api/conversations` lists the chats of every folder.
- A plain chat's agents get no tool that needs a folder: no file, `show`, command, skill
  script, MCP, memory, backlog, room, `ask_folder` or notify tool - and a call of one is
  refused. A CLI that works with its own tools runs as its talker (Claude Code, Codex,
  Copilot: their own tools off, in an empty folder of their own); agy, which reads with its
  own tools however it is started, is refused and says why.
- It writes no memory, is held by no project's budget (a provider's limit still holds),
  opens no room or comparison and adds no folder named in a message to its list.
- `PATCH project_id` (null too) moves an idle chat from the app's own page; not while a
  turn of it runs or waits, nor once it changed files, kept a copy, or has a trigger or a
  backlog task ("taşınmasın").
- "Always run" rules belong to the chat and the folder they were made in.
"""

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import func, select

from app.db.models import BacklogTask, Compare, Memory, Merge
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_writes import wait_status
from tests.test_agy_agent import agy_app  # noqa: F401  (a fixture)
from tests.test_budget_scenarios import PRICE
from tests.test_chat_flow import text
from tests.test_context_scenarios import windowed  # noqa: F401  (a fixture)
from tests.test_context_state import lead_of
from tests.test_copilot_agent import copilot_native  # noqa: F401  (a fixture)
from tests.test_migration_0002 import _config
from tests.test_spawn import call, names, spawn, step
from tests.test_team import team  # noqa: F401  (a fixture)
from tests.test_trigger_scenarios import trigger
from tests.test_usage_scenarios import began, turn, usage
from tests.test_web_tools import events

ORIGIN = "http://127.0.0.1:8790"
OWN = {"Origin": ORIGIN}
# What a plain chat's Lead may have: nothing of it needs a folder (as literals: the code's
# own list is what is tested). A file named by its full path is read on a card (86b).
PLAIN = {"web_search", "http_request", "spawn_agent", "create_role", "ask_user",
         "message_agent", "discuss", "post_note", "read_notes", "read_file", "list_dir"}
NEEDS_A_FOLDER = {
    "search", "write_file", "edit_file", "show", "run_command",
    "run_skill_script", "ask_folder", "remember", "recall", "read_backlog", "add_task",
    "change_task", "assess_task", "open_room", "notify", "add_skill",
}


def plain(client, **settings):
    """A new chat with no folder, from the app's own page; `settings` patched onto it."""
    made = client.post("/api/conversations", headers=OWN)
    assert made.status_code == 201, made.text
    cid = made.json()["id"]
    if settings:
        patched = client.patch(f"/api/conversations/{cid}", json=settings, headers=OWN)
        assert patched.status_code == 200, patched.text
    return cid


def say(client, cid, content="hello"):
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": content},
                         headers=OWN)
    assert posted.status_code == 201, posted.text
    return posted.json()["run"]["id"]


def folder(client, path):
    made = client.post("/api/projects", json={"root_path": str(path)})
    assert made.status_code in (200, 201), made.text
    return made.json()["id"]


def move(client, cid, project_id, headers=OWN):
    return client.patch(f"/api/conversations/{cid}", json={"project_id": project_id},
                        headers=headers)


def done(snap):
    run = snap["runs"][-1]
    assert run["status"] == "completed", run["error"]
    return snap


# --- the data ------------------------------------------------------------------------------


AT = "2026-10-24 10:00:00"


def test_migration_0069_keeps_every_chats_folder_takes_none_and_goes_back_only_without_one(
    tmp_path,
):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0068")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO projects (id, name, root_path, created_at) "
                     f"VALUES ('p', 'p', 'C:/p', '{AT}')")
        conn.execute("INSERT INTO conversations (id, project_id, title, created_at, updated_at) "
                     f"VALUES ('c', 'p', 't', '{AT}', '{AT}')")
        conn.execute("INSERT INTO runs (id, conversation_id, status, created_at) "
                     f"VALUES ('r', 'c', 'completed', '{AT}')")
        conn.execute("INSERT INTO allowed_commands (id, conversation_id, prefix, created_at) "
                     f"VALUES ('a', 'c', 'pytest', '{AT}')")
    command.upgrade(cfg, "0069")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT id, project_id FROM conversations").fetchall() == [("c", "p")]
        # the rule is the chat's in the folder it was made in
        assert conn.execute("SELECT id, project_id FROM allowed_commands").fetchall() == [
            ("a", "p")]
        assert conn.execute("SELECT id FROM runs").fetchall() == [("r",)]
        conn.execute("INSERT INTO conversations (id, project_id, title, created_at, updated_at) "
                     f"VALUES ('plain', NULL, 't', '{AT}', '{AT}')")
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    with pytest.raises(Exception, match="no folder"):
        command.downgrade(cfg, "0068")
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM conversations WHERE id = 'plain'")
    command.downgrade(cfg, "0068")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT id, project_id FROM conversations").fetchall() == [("c", "p")]
        assert conn.execute("SELECT id, prefix FROM allowed_commands").fetchall() == [
            ("a", "pytest")]


def test_a_chat_is_made_with_no_folder_or_in_one_that_is_known(make_client, project_dir):
    client, _ = make_client([])
    made = client.post("/api/conversations", headers=OWN)
    assert made.status_code == 201 and made.json()["project_id"] is None
    pid = folder(client, project_dir)
    there = client.post("/api/conversations", json={"project_id": pid}, headers=OWN)
    assert there.status_code == 201 and there.json()["project_id"] == pid
    assert client.post("/api/conversations", json={"project_id": "nope"},
                       headers=OWN).status_code == 404


def test_every_folders_chats_are_listed_together_the_plain_ones_with_no_folder(
    make_client, project_dir
):
    client, _ = make_client([])
    pid = folder(client, project_dir)
    there = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    loose = plain(client)
    listed = client.get("/api/conversations")
    assert listed.status_code == 200, listed.text
    by_id = {one["id"]: one for one in listed.json()}
    assert (by_id[there]["project_id"], by_id[loose]["project_id"]) == (pid, None)
    assert by_id[loose]["kept"] is False


def test_a_listed_chat_says_whether_the_user_wrote_in_it(make_client, wait_run):
    # (The first steps are done once any chat has the user's message: 0.1.0-ilk-calistirma.)
    client, _ = make_client([text("hi")])
    written, empty = plain(client), plain(client)
    done(wait_run(client, written, say(client, written)))
    by_id = {one["id"]: one for one in client.get("/api/conversations").json()}
    assert (by_id[written]["wrote"], by_id[empty]["wrote"]) == (True, False)


# --- what its agents are given ---------------------------------------------------------------


def test_a_plain_chats_lead_is_offered_only_what_needs_no_folder(make_client, wait_run):
    client, model = make_client([text("hi")])
    cid = plain(client)
    snap = done(wait_run(client, cid, say(client, cid)))
    # (message_agent is offered once somebody can be messaged; recall_output is no role's tool,
    # every agent's at its own work: K-gecmis-zengin)
    assert set(names(model.tool_args[0])) == PLAIN - {"message_agent"} | {"recall_output"}
    lead = snap["agents"][0]
    assert set(lead["tools"]) == PLAIN and lead["mcp"] == []


def test_in_a_plain_chat_a_file_show_command_or_mcp_call_is_refused_and_nothing_is_read(
    make_client, wait_run, tmp_path
):
    secret = tmp_path / "notes.txt"
    secret.write_text("TOP SECRET", encoding="utf-8")
    executor = ScriptedExecutor([Script(["ran"])])
    client, model = make_client([
        step(call("write_file", {"path": str(secret), "content": "x"}, "w"),
             call("show", {"path": str(secret)}, "s"),
             call("run_command", {"command": f"type {secret}"}, "c"),
             call("files__read", {"path": str(secret)}, "m")),
        text("done")], executor=executor)
    cid = plain(client, permission_mode="full_auto")
    snap = done(wait_run(client, cid, say(client, cid)))
    calls = {one["name"]: one for one in snap["tool_calls"]}
    # (A read by its full path is asked about on a card: tests/test_chat_folders.py.)
    for name in ("write_file", "show", "run_command", "files__read"):
        assert calls[name]["status"] == "failed", calls[name]
        assert "folder" in calls[name]["result"], calls[name]["result"]
    assert "TOP SECRET" not in json.dumps(snap) and "TOP SECRET" not in json.dumps(model.calls)
    assert executor.started == []


def test_a_sub_agent_in_a_plain_chat_has_no_file_or_command_tool(make_client, wait_run):
    client, model = make_client({"Lead": [spawn("Coder", "write the code"), text("done")],
                                 "Coder": [text("I have no files here.")]})
    cid = plain(client, spawn_approval="never")
    snap = done(wait_run(client, cid, say(client, cid)))
    coder = next(agent for agent in snap["agents"] if agent["role_name"] == "Coder")
    assert coder["status"] == "completed" and not NEEDS_A_FOLDER & set(coder["tools"])
    assert set(coder["tools"]) <= PLAIN
    # the Coder's one step: Lead, Coder, Lead
    assert not NEEDS_A_FOLDER & set(names(model.tool_args[1]))


def test_claude_code_in_a_plain_chat_runs_with_its_own_tools_off_in_a_folder_of_its_own(
    settings_env, wait_run, tmp_path
):
    from app.config import load_settings
    from app.main import create_app
    from app.model_native import ClaudeNativeClient
    from tests.fakes import ScriptedModel
    from tests.keyed import TestClient

    # Its talker is a session: the stand-in for one, which the native client hands on.
    record, plan = tmp_path / "record.json", tmp_path / "plan.json"
    plan.write_text(json.dumps({"record": str(record), "script": [{"say": "Hello there."}]}),
                    encoding="utf-8")
    fake = [sys.executable, str(Path(__file__).with_name("fake_session_cli.py"))]
    cli = ClaudeNativeClient(launcher=fake, timeout=30, env={"FAKE_CLI_PLAN": str(plan)})
    app = create_app(load_settings(settings_env), model=ScriptedModel([]), clients={"Claude": cli})
    with TestClient(app, base_url=ORIGIN) as client:
        provider = client.post("/api/providers", json={
            "name": "Claude", "kind": "claude_cli", "mode": "native"}).json()
        cid = plain(client, provider_id=provider["id"])
        snap = done(wait_run(client, cid, say(client, cid)))
    assert [m["content"] for m in snap["messages"] if m["role"] == "assistant"] == [
        "Hello there."]
    seen = json.loads(record.read_text(encoding="utf-8"))
    argv = seen["argv"]
    assert argv[argv.index("--tools") + 1] == ""  # none of its own
    assert "--add-dir" not in argv and "--permission-prompt-tool" not in argv
    assert Path(seen["cwd"]).name.startswith("koloni-cli-")  # an empty folder of its own


def test_copilot_in_a_plain_chat_runs_with_kolonis_folderless_tools_only(
    copilot_native, wait_run  # noqa: F811
):
    client, provider = copilot_native([{"say": "Hi."}])
    cid = plain(client, provider_id=provider["id"])
    done(wait_run(client, cid, say(client, cid)))
    seen = copilot_native.record()
    argv = seen["argv"]
    given = argv[argv.index("--available-tools") + 1:]
    assert given and not any(name.endswith(("write_file", "run_command", "show")) for name in given)
    assert Path(seen["cwd"]).name.startswith("koloni-cli-")


def test_codex_in_a_plain_chat_runs_as_its_talker_and_never_natively(
    team, wait_run, tmp_path  # noqa: F811
):
    from app.model_cli import CodexCliClient
    from app.model_native import CodexNativeClient
    from tests.fakes import ScriptedModel

    client, _default, _fast = team([])
    talker = ScriptedModel([text("Hello from Codex.")], model_id="codex-talk")
    team.stubs["Codex"].talker = lambda: talker
    cid = plain(client, provider_id=team.providers["Codex"]["id"])
    done(wait_run(client, cid, say(client, cid)))
    assert team.stubs["Codex"].started == 0 and len(talker.calls) == 1
    assert not NEEDS_A_FOLDER & set(names(talker.tool_args[0]))
    # The real one's talker: one step at a time, read only, in the empty folder it is given.
    real = CodexNativeClient().talker()
    assert isinstance(real, CodexCliClient) and not getattr(real, "native", False)
    work = tmp_path / "work"
    work.mkdir()
    arguments = real._arguments(work)
    assert arguments[arguments.index("--sandbox") + 1] == "read-only"
    assert arguments[arguments.index("--cd") + 1] == str(work)
    assert "shell_tool" in arguments


def test_agy_in_a_plain_chat_is_refused_and_says_why(agy_app, wait_run):  # noqa: F811
    client, provider, _ = agy_app([{"say": "never"}])
    cid = plain(client, provider_id=provider["id"])
    run = wait_run(client, cid, say(client, cid))["runs"][0]
    assert run["status"] == "failed"
    assert "agy works with its own tools and needs a folder" in run["error"]
    assert not agy_app.ran()


def test_a_sub_agent_picked_on_codex_in_a_plain_chat_runs_as_its_talker(
    team, wait_run  # noqa: F811
):
    from tests.fakes import ScriptedModel
    from tests.test_team import WHY, pick

    client, _default, _fast = team([step(pick("Researcher", "Codex", why=WHY)), text("done")])
    talker = ScriptedModel([text("Reviewed with no files.")], model_id="codex-talk")
    team.stubs["Codex"].talker = lambda: talker
    cid = plain(client, spawn_approval="never")  # (at Ask: a native Codex would need Full auto)
    snap = done(wait_run(client, cid, say(client, cid)))
    reviewer = next(a for a in snap["agents"] if a["role_name"] == "Researcher")
    assert (reviewer["provider_name"], reviewer["status"]) == ("Codex", "completed")
    assert team.stubs["Codex"].started == 0 and len(talker.calls) == 1
    assert not NEEDS_A_FOLDER & set(names(talker.tool_args[0]))


def test_plan_first_is_no_part_of_a_plain_chat(make_client, wait_run):
    client, model = make_client([text("Just an answer.")])
    cid = plain(client, plan_first=True)
    run = done(wait_run(client, cid, say(client, cid)))["runs"][0]
    assert (run["plan_turn"], run["plan"]) == (False, None)
    assert "This turn is for a plan only" not in model.calls[0][0]["content"]


def test_native_work_with_no_folder_fails_before_any_process_starts(team):  # noqa: F811
    from app.agent import Ctx
    from app.roles import ALL_TOOLS

    client, _default, _fast = team([])
    stub = team.stubs["Codex"]
    ctx = Ctx("r", "c", None, "a", "Lead", tuple(ALL_TOOLS), 0, model=stub, provider="Codex")
    # (refused where such an agent starts, before its copy or its place: `_native_refused`)
    status, why = asyncio.run(client.app.state.runner._native_loop(ctx, None))
    assert status == "failed" and "needs a folder" in why and stub.started == 0


def test_a_plain_chats_prompt_names_no_folder_and_speaks_of_no_shell_or_hand_off(
    make_client, wait_run
):
    client, model = make_client([text("hi")])
    cid = plain(client)  # (the Lead hands code on by default: slice 48)
    done(wait_run(client, cid, say(client, cid)))
    system = model.calls[0][0]["content"]
    assert "no folder" in system  # and how one is picked
    assert "project folder" not in system and "run_command" not in system
    assert str(Path.cwd()) not in system and "None" not in system
    assert "Hand every change to files" not in system  # HANDS_CODE_PROMPT


def test_a_plain_chat_writes_nothing_into_any_memory(make_client, wait_run):
    client, _ = make_client([
        step(call("remember", {"text": "the tests run with pytest", "about": "tests"}, "m"),
             call("recall", {"query": "tests"}, "r")),
        text("done")])
    cid = plain(client, permission_mode="full_auto")
    snap = done(wait_run(client, cid, say(client, cid)))
    assert [t["status"] for t in snap["tool_calls"]] == ["failed", "failed"]
    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Memory)) == 0
    assert snap["agents"][0]["facts_given"] in ([], None)


# --- limits, rooms, folders named --------------------------------------------------------------


def test_a_plain_chat_is_held_by_no_projects_budget_but_by_a_providers_limit(
    make_client, wait_run, project_dir
):
    client, _model, pid, cid = began(
        make_client, project_dir, [text("a", 1_000_000, 500_000), text("b")])
    turn(client, wait_run, cid)  # 10.50 USD spent in the folder
    client.put("/api/prices", json=PRICE)
    assert client.patch(f"/api/projects/{pid}", json={"monthly_budget": 5}).status_code == 200
    assert client.post(f"/api/conversations/{cid}/messages",
                       json={"content": "more"}).status_code == 409
    loose = plain(client)
    done(wait_run(client, loose, say(client, loose)))  # no folder's budget holds it
    local = client.get("/api/providers").json()[0]
    assert client.patch(f"/api/providers/{local['id']}", json={"day_limit": 5}).status_code == 200
    held = client.post(f"/api/conversations/{loose}/messages", json={"content": "more"},
                       headers=OWN)
    assert held.status_code == 409 and f"over {local['name']}'s limit" in held.json()["detail"]


def test_a_room_a_comparison_or_a_view_in_a_plain_chat_is_refused(make_client):
    client, _ = make_client([])
    cid = plain(client)
    room = client.post(f"/api/conversations/{cid}/rooms", headers=OWN, json={
        "goal": "build it", "with": [{"role": "Coder"}, {"role": "Reviewer"}]})
    assert room.status_code == 409 and "folder" in room.json()["detail"], room.text
    local = client.get("/api/providers").json()[0]["id"]
    compare = client.post(f"/api/conversations/{cid}/compare", headers=OWN, json={
        "content": "x", "sides": [{"provider_id": local}, {"provider_id": local}]})
    assert compare.status_code == 409 and "folder" in compare.json()["detail"], compare.text
    assert client.get(f"/api/conversations/{cid}/views", headers=OWN).status_code == 404


def test_a_folder_named_in_a_plain_chats_message_is_not_added_to_it(
    make_client, wait_run, tmp_path
):
    client, _ = make_client([text("ok")])
    docs = tmp_path / "docs"
    docs.mkdir()
    cid = plain(client)
    snap = done(wait_run(client, cid, say(client, cid, f"look in {docs}")))
    assert snap["conversation"]["also_in"] == []


def test_a_web_search_works_in_a_plain_chat(make_client, wait_run, monkeypatch):
    from tests.test_web_tool_scenarios import DDG_PAGE, Net, results, search

    Net(monkeypatch, {"duckduckgo.com": (200, "text/html", DDG_PAGE)})
    client, _ = make_client([step(search()), text("done")])
    cid = plain(client, permission_mode="full_auto")
    snap = done(wait_run(client, cid, say(client, cid)))
    ((status, said),) = results(snap, "web_search")
    assert status == "succeeded" and "https://docs.python.org/3/" in said


def test_compact_now_works_in_a_plain_chat(windowed, wait_run):  # noqa: F811
    client, model = windowed([text("hi")])
    cid = plain(client)
    done(wait_run(client, cid, say(client, cid)))
    compacted = client.post(f"/api/agents/{lead_of(client, cid)['id']}/compact")
    assert compacted.status_code == 200, compacted.text
    assert compacted.json()["summarised"] == 0 and len(model.calls) == 1


def test_a_plain_chats_spend_is_in_usage_with_no_folder(make_client, wait_run):
    client, _ = make_client([text("a", 10, 5)])
    cid = plain(client)
    done(wait_run(client, cid, say(client, cid)))
    row = next(one for one in usage(client)["by_conversation"] if one["conversation_id"] == cid)
    assert row["project_id"] is None and (row["input_tokens"], row["output_tokens"]) == (10, 5)


def test_a_plain_chats_turn_is_undone_like_any_other(make_client, wait_run):
    client, _ = make_client([text("hi")])
    cid = plain(client)
    run_id = say(client, cid)
    done(wait_run(client, cid, run_id))
    ahead = client.get(f"/api/runs/{run_id}/undo")
    assert ahead.status_code == 200 and ahead.json()["revert"] == [], ahead.text
    undone = client.post(f"/api/runs/{run_id}/undo", headers=OWN)
    assert undone.status_code == 200 and undone.json()["revert"] == [], undone.text


# --- moving it ---------------------------------------------------------------------------------


def test_an_idle_chat_with_no_changes_moves(make_client, wait_run, project_dir, tmp_path):
    client, _ = make_client([text("hi")])
    other = tmp_path / "other"
    other.mkdir()
    here, there = folder(client, project_dir), folder(client, other)
    cid = plain(client)
    done(wait_run(client, cid, say(client, cid)))
    moved = move(client, cid, here)
    assert moved.status_code == 200 and moved.json()["project_id"] == here, moved.text
    moved = move(client, cid, there)
    assert moved.json()["project_id"] == there
    assert ("conversation.updated", moved.json()) in events(client, cid)
    out = move(client, cid, None)
    assert out.status_code == 200 and out.json()["project_id"] is None


def test_a_chat_at_work_or_waiting_is_not_moved(make_client, wait_run, project_dir, gate):
    client, _ = make_client([gate.step(text("first")), text("second")])
    pid = folder(client, project_dir)
    cid = plain(client)
    first = say(client, cid, "first")
    gate.wait_partial()
    refused = move(client, cid, pid)
    assert refused.status_code == 409 and "at work" in refused.json()["detail"]
    say(client, cid, "second")  # queued behind it
    gate.release()
    wait_run(client, cid, first)
    snap = client.get(f"/api/conversations/{cid}").json()
    if snap["runs"][-1]["status"] == "queued":  # (it may have started already)
        assert move(client, cid, pid).status_code == 409


def test_a_chat_that_changed_files_is_not_moved(make_client, wait_run, project_dir, tmp_path):
    client, _ = make_client([
        step(call("write_file", {"path": "made.txt", "content": "x"}, "w")), text("done")])
    here = folder(client, project_dir)
    other = tmp_path / "other"
    other.mkdir()
    there = folder(client, other)
    cid = client.post("/api/conversations", json={"project_id": here}, headers=OWN).json()["id"]
    client.patch(f"/api/conversations/{cid}", headers=OWN, json={
        "permission_mode": "full_auto", "lead_hands_code": False})
    done(wait_run(client, cid, say(client, cid)))
    assert (project_dir / "made.txt").exists()
    refused = move(client, cid, there)
    assert refused.status_code == 409, refused.text
    said = refused.json()["detail"]
    assert "changed files in proj" in said and "open a new chat for other" in said
    assert move(client, cid, None).status_code == 409  # nor out of every folder


def test_a_chat_whose_every_change_was_turned_down_moves(
    make_client, wait_run, project_dir, tmp_path
):
    client, _ = make_client([
        step(call("write_file", {"path": "made.txt", "content": "x"}, "w")), text("done")])
    here = folder(client, project_dir)
    other = tmp_path / "other"
    other.mkdir()
    there = folder(client, other)
    cid = client.post("/api/conversations", json={"project_id": here}, headers=OWN).json()["id"]
    client.patch(f"/api/conversations/{cid}", headers=OWN, json={"lead_hands_code": False})
    run_id = say(client, cid)
    change = wait_status(client, cid, "waiting_approval")["file_changes"][0]
    assert client.post(f"/api/file-changes/{change['id']}/reject").status_code == 200
    done(wait_run(client, cid, run_id))
    assert not (project_dir / "made.txt").exists()
    moved = move(client, cid, there)
    assert moved.status_code == 200 and moved.json()["project_id"] == there, moved.text


@pytest.mark.parametrize("kind", ["copy", "comparison", "trigger", "backlog"])
def test_a_chat_with_a_kept_copy_a_comparison_a_trigger_or_a_backlog_task_is_not_moved(
    make_client, wait_run, project_dir, tmp_path, kind
):
    client, _ = make_client([text("hi")])
    here = folder(client, project_dir)
    other = tmp_path / "other"
    other.mkdir()
    there = folder(client, other)
    cid = client.post("/api/conversations", json={"project_id": here}, headers=OWN).json()["id"]
    snap = done(wait_run(client, cid, say(client, cid)))
    if kind == "trigger":
        client.headers["Origin"] = ORIGIN  # (made from the app's own page)
        trigger(client, here, cid)
    else:
        with client.app.state.session_factory() as session:
            if kind == "copy":
                session.add(Merge(run_id=snap["runs"][0]["id"], agent_id=snap["agents"][0]["id"],
                                  status="interrupted", files=[], kept_in="kept-1"))
            elif kind == "comparison":  # (waiting for the user's choice of a side)
                session.add(Compare(conversation_id=cid, sides=[]))
            else:
                session.add(BacklogTask(project_id=here, conversation_id=cid, title="a task",
                                        position=0, created_by="user"))
            session.commit()
    refused = move(client, cid, there)
    assert refused.status_code == 409, refused.text
    assert "open a new chat for other" in refused.json()["detail"]


def test_a_chat_is_moved_only_from_the_apps_own_page_and_only_to_a_known_folder(
    make_client, project_dir
):
    client, _ = make_client([])
    pid = folder(client, project_dir)
    cid = plain(client)
    assert move(client, cid, pid, headers={}).status_code == 403
    assert move(client, cid, "nope").status_code == 404
    assert client.get(f"/api/conversations/{cid}").json()["conversation"]["project_id"] is None


def test_an_always_run_rule_holds_in_the_folder_it_was_made_in_only(
    make_client, wait_run, project_dir, tmp_path
):
    gone = ScriptedExecutor([Script(["ran in proj\n"]), Script(["ran in proj again\n"])])
    client, _ = make_client([
        step(call("run_command", {"command": "python hello.py"}, "c1")), text("one"),
        step(call("run_command", {"command": "python hello.py"}, "c2")), text("two"),
        step(call("run_command", {"command": "python hello.py"}, "c3")), text("three"),
    ], executor=gone)
    here = folder(client, project_dir)
    other = tmp_path / "other"
    other.mkdir()
    (other / "hello.py").write_text("print('there')\n", encoding="utf-8")
    there = folder(client, other)
    cid = client.post("/api/conversations", json={"project_id": here}, headers=OWN).json()["id"]
    assert client.post(f"/api/conversations/{cid}/allowed-commands", headers=OWN,
                       json={"prefix": "python hello.py"}).status_code == 201
    done(wait_run(client, cid, say(client, cid)))  # ran unasked
    assert len(gone.started) == 1
    assert move(client, cid, there).status_code == 200
    assert client.get(f"/api/conversations/{cid}").json()["allowed_commands"] == []
    second = say(client, cid)
    snap = wait_status(client, cid, "waiting_approval")  # asked: the rule is proj's
    waiting = next(c for c in snap["commands"] if c["status"] == "proposed")
    assert client.post(f"/api/commands/{waiting['id']}/reject").status_code == 200
    wait_run(client, cid, second)
    assert move(client, cid, here).status_code == 200
    done(wait_run(client, cid, say(client, cid)))  # unasked again
    assert len(gone.started) == 2
