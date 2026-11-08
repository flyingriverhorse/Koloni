"""K-ev-klasoru: a file in a CLI's own folder in the home folder (~/.codex, ~/.claude, ~/.copilot,
~/.gemini) is read and written by KOLONİ's file tools on a card, every time and at every level,
and never where nobody watches; its logins and past conversations never, card or not. A temporary
home folder only: no real one is looked at."""

import json
import sys
import time

import pytest

from app.commands import names_standing
from app.workspace import CLI_HOME_CARD, CliHome, Workspace, WorkspaceError
from tests.test_agent_writes import write
from tests.test_chat_flow import text
from tests.test_folders import start
from tests.test_folders_security import variants
from tests.test_outside_folders_scenarios import (
    ORIGIN,
    conversation,
    junction,
    project,
    read,
)
from tests.test_plain_chat_scenarios import plain, say
from tests.test_trigger_scenarios import run_now, trigger

CARD = CLI_HOME_CARD.format(cli="Codex")
KEY = "sk-e2e1234567890abcdefghij"
NEVER = [".codex/auth.json", ".claude.json", ".claude/projects/x.jsonl",
         ".codex/sessions/2026/r.jsonl"]


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    for name in [".codex/config.toml", *NEVER]:
        (home / name).parent.mkdir(parents=True, exist_ok=True)
        (home / name).write_text("model = 'o'\n", encoding="utf-8")
    (home / ".codex" / "keyed.toml").write_text(f'openai = "{KEY}"\nmodel = \'o\'\n',
                                                encoding="utf-8")
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    return home


def until(client, cid, seen):
    for _ in range(250):
        snap = client.get(f"/api/conversations/{cid}").json()
        if seen(snap):
            return snap
        time.sleep(0.02)
    raise AssertionError(f"never seen: {snap['tool_calls']}")


def pending(snap):
    return [t for t in snap["tool_calls"] if t["status"] == "pending"]


def decide(client, call, word):
    said = (client.post(f"/api/tool-calls/{call['id']}/reject", headers={"Origin": ORIGIN})
            if word == "reject" else client.post(f"/api/tool-calls/{call['id']}/approve",
                                                 json={"scope": word}, headers={"Origin": ORIGIN}))
    assert said.status_code == 200, said.text


def test_a_read_there_is_a_card_every_time_at_full_auto_and_allow_this_folder_is_no_leave(
    make_client, wait_run, project_dir, home
):
    config = (home / ".codex" / "config.toml").resolve()
    client, _model = make_client([read(config, "r1"), read(config, "r2"), text("ok")])
    cid, run_id = start(client, project(client, project_dir))
    (asked,) = pending(until(client, cid, pending))
    assert (asked["why_asked"], asked["outside_folder"]) == (CARD, str(config))
    decide(client, asked, "folder")  # (no folder is put on any list by this card)
    snap = until(client, cid, lambda s: len(pending(s)) == 1 and len(s["tool_calls"]) == 2)
    first, again = snap["tool_calls"]
    assert first["status"] == "succeeded" and "model = 'o'" in first["result"]
    assert again["why_asked"] == CARD
    assert (conversation(client, cid)["read_in"], conversation(client, cid)["also_in"]) == ([], [])
    decide(client, again, "reject")
    assert wait_run(client, cid, run_id)["tool_calls"][1]["status"] == "denied"


@pytest.mark.parametrize("word", ["once", "reject"])
def test_a_write_there_is_a_card_then_its_change_even_at_full_auto(
    make_client, wait_run, project_dir, home, word
):
    config = home / ".codex" / "config.toml"
    client, _model = make_client([write(str(config), "model = 'n'\n"), text("ok")])
    cid, run_id = start(client, project(client, project_dir))
    (asked,) = pending(until(client, cid, pending))
    assert asked["why_asked"] == CARD
    decide(client, asked, word)
    if word == "once":  # (.codex stands over later turns: its change is a card of its own)
        (change,) = until(client, cid, lambda s: s["file_changes"])["file_changes"]
        assert client.post(f"/api/file-changes/{change['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id)
    held = config.read_text(encoding="utf-8")
    assert held == ("model = 'n'\n" if word == "once" else "model = 'o'\n")
    assert snap["tool_calls"][0]["status"] == ("succeeded" if word == "once" else "denied")


def test_a_key_in_such_a_file_is_hidden_from_the_model(make_client, wait_run, project_dir, home):
    client, model = make_client([read(home / ".codex" / "keyed.toml"), text("ok")])
    cid, run_id = start(client, project(client, project_dir))
    decide(client, pending(until(client, cid, pending))[0], "once")
    snap = wait_run(client, cid, run_id)
    assert "model = 'o'" in snap["tool_calls"][0]["result"]
    assert KEY not in json.dumps(snap) and KEY not in json.dumps(model.calls)


@pytest.mark.parametrize("named", ["~/.codex/config.toml", pytest.param(
    "%USERPROFILE%\\.codex\\config.toml",
    marks=pytest.mark.skipif(sys.platform != "win32", reason="%USERPROFILE% and \\ are Windows'"))])
def test_in_a_project_chat_a_tilde_is_the_home_folder_not_a_folder_of_the_project(
    make_client, wait_run, project_dir, home, named
):
    client, _model = make_client([read(named), text("ok")])
    cid, run_id = start(client, project(client, project_dir))
    (asked,) = pending(until(client, cid, pending))
    assert (asked["why_asked"], asked["outside_folder"]) == (
        CARD, str((home / ".codex" / "config.toml").resolve()))
    decide(client, asked, "once")
    assert "model = 'o'" in wait_run(client, cid, run_id)["tool_calls"][0]["result"]
    assert not (project_dir / "~").exists()


def test_a_write_to_gemini_s_settings_shows_its_change_at_full_auto_and_cannot_be_undone_here(
    make_client, wait_run, project_dir, home
):
    settings = home / ".gemini" / "settings.json"
    client, _model = make_client([write(str(settings), "{}\n"), text("ok")])
    cid, run_id = start(client, project(client, project_dir))
    decide(client, pending(until(client, cid, pending))[0], "once")
    (change,) = until(client, cid, lambda s: s["file_changes"])["file_changes"]
    assert change["status"] == "proposed" and not settings.exists()  # (a diff card: Full auto too)
    assert client.post(f"/api/file-changes/{change['id']}/approve").status_code == 200
    wait_run(client, cid, run_id)
    assert settings.read_text(encoding="utf-8") == "{}\n"
    undone = client.post(f"/api/file-changes/{change['id']}/revert")
    assert undone.status_code == 409 and "can't be undone here" in undone.text
    assert settings.exists()


@pytest.mark.parametrize("folder", [".gemini", ".copilot"])
def test_a_command_that_writes_gemini_s_or_copilot_s_settings_is_asked_at_every_level(folder):
    assert names_standing(f"echo x > %USERPROFILE%\\{folder}\\settings.json") == folder


def test_nobody_watching_it_is_refused(make_client, wait_run, project_dir, home):
    client, _model = make_client([read(home / ".codex" / "config.toml"), text("ok")])
    client.headers["Origin"] = ORIGIN
    pid = project(client, project_dir)
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    run_id = run_now(client, trigger(client, pid, cid, permissions={"write": True})["id"])
    (refused,) = wait_run(client, cid, run_id)["tool_calls"]
    assert refused["status"] != "succeeded", refused
    assert "outside the project" in refused["result"] and "model" not in refused["result"]


def test_a_chat_with_no_folder_reads_it_with_a_tilde_on_the_same_card(make_client, wait_run, home):
    client, _model = make_client([read("~/.codex/config.toml"), text("ok")])
    cid = plain(client, permission_mode="full_auto")
    run_id = say(client, cid)
    (asked,) = pending(until(client, cid, pending))
    assert asked["why_asked"] == CARD
    decide(client, asked, "once")
    (tool,) = wait_run(client, cid, run_id)["tool_calls"]
    assert tool["status"] == "succeeded" and "model = 'o'" in tool["result"]


@pytest.mark.parametrize("name", NEVER)
def test_a_login_or_a_past_conversation_is_refused_without_a_card(
    make_client, wait_run, project_dir, home, name
):
    client, _model = make_client([read(home / name, "r"), write(str(home / name), "x", "w"),
                                  text("ok")])
    cid, run_id = start(client, project(client, project_dir))
    snap = wait_run(client, cid, run_id)
    assert [t["status"] for t in snap["tool_calls"]] == ["failed", "failed"]
    assert all(t["why_asked"] is None and "never opened" in t["result"] for t in snap["tool_calls"])
    assert (home / name).read_text(encoding="utf-8") == "model = 'o'\n"


def test_a_project_there_is_still_refused(make_client, home):
    client, _model = make_client([])
    made = client.post("/api/projects", json={"root_path": str(home / ".claude")})
    assert made.status_code in (400, 422), made.text


@pytest.mark.parametrize(("name", "card"), [
    (".gemini/settings.json", True), (".copilot/mcp-config.json", True),
    (".claude/settings.json", True), (".gemini/oauth_creds.json", False),
    (".gemini/google_accounts.json", False), (".gemini/tmp/abc/logs.json", False),
    (".copilot/session-state/a.json", False), (".copilot/config.json", False),
    (".claude/.credentials.json", False), (".codex/history.jsonl", False),
    (".codex/AUTH.JSON.", False), (".claude/x/my-token.txt", False), (".gemini/.env", False),
    (".claude/backups/.claude.json.backup.1", False), (".claude/ide/41234.lock", False),
])
def test_each_cli_s_logins_and_records_are_kept_out_by_name(project_dir, home, name, card):
    with pytest.raises(WorkspaceError) as caught:
        Workspace(project_dir).resolve(str(home / name))
    assert isinstance(caught.value, CliHome) is card, caught.value
    if name.endswith(".env"):
        assert "it is a secret" in str(caught.value)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' names")
def test_a_login_is_refused_by_any_spelling_of_its_name(project_dir, home):
    for named in [v for v in variants(home / ".codex") if "koloni.db" in v]:
        with pytest.raises(WorkspaceError) as caught:
            Workspace(project_dir).resolve(named.replace("koloni.db", "auth.json"))
        assert not isinstance(caught.value, CliHome), named


def test_by_dots_or_a_link_it_is_the_same_and_a_grant_is_for_that_one_file(project_dir, home):
    ws, config = Workspace(project_dir), (home / ".codex" / "config.toml").resolve()
    with pytest.raises(CliHome) as caught:
        ws.resolve(str(home / "x" / ".." / ".codex" / "config.toml"))
    assert caught.value.real == config
    granted = Workspace(project_dir, granted=config)
    assert granted.resolve(str(home / ".codex" / "config.toml")) == config
    with pytest.raises(CliHome):
        granted.resolve(str(home / ".codex" / "other.toml"))
    if sys.platform != "win32":
        pytest.skip("junctions are Windows'")
    junction(project_dir / "door", home / ".codex")
    with pytest.raises(CliHome):
        ws.resolve("door/config.toml")
    with pytest.raises(WorkspaceError) as caught:
        ws.resolve("door/sessions/2026/r.jsonl")
    assert not isinstance(caught.value, CliHome)


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are Windows'")
def test_a_cli_folder_that_leads_into_another_place_never_opened_is_no_card(
    tmp_path, monkeypatch, project_dir
):
    home = tmp_path / "other-home"
    (home / ".ssh").mkdir(parents=True)
    junction(home / ".codex", home / ".ssh")
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    with pytest.raises(WorkspaceError) as caught:
        Workspace(project_dir).resolve(str(home / ".codex" / "id_x"))
    assert not isinstance(caught.value, CliHome)
