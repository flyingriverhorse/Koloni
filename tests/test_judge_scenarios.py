"""K-yargıç, slice 1: at Full auto, in a turn the user watches, a command that deletes or sends
something off this machine is first checked against what the user themself wrote - their
preferences, this project's rules as saved, their own messages in the chat - and runs without a
card only on a line of theirs that names it; anything else is today's card. Off by default."""

import asyncio
import json
import re
from pathlib import Path

import pytest
from sqlalchemy import select

from app import koloni, raw
from app.agent.ctx import Ctx, _Unwatched
from app.commands import harms
from app.config import load_settings
from app.db.models import OwnRequest
from app.main import create_app
from app.model_client import StepResult
from tests.fakes import Script, ScriptedExecutor, ScriptedModel
from tests.keyed import OWN, TestClient
from tests.test_agent_commands import cmd
from tests.test_agent_writes import wait_status
from tests.test_chat_flow import text
from tests.test_spawn import call, step
from tests.test_team import ADDRESS, SECRET

RULE = "You may delete build/ and dist/."
APP = Path(__file__).resolve().parents[1] / "app"


def verdict_line(verdict, quote="", why="It names build/."):
    return text(json.dumps({"verdict": verdict, "quote": quote, "why": why}), i=30, o=10)


@pytest.fixture
def judging(settings_env):
    """An app whose Lead is a scripted model on Local, whose commands are scripted, and whose
    Fast tier's first model is another scripted model, "quick" on Fast: the judge."""
    opened = []

    def make(lead_steps, judge_steps, scripts):
        lead, judge = ScriptedModel(lead_steps), ScriptedModel(judge_steps, model_id="quick")
        executor = ScriptedExecutor(scripts)
        app = create_app(load_settings(settings_env), model=lead, executors=executor.factory,
                         clients={"Fast": judge})
        client = TestClient(app, base_url="http://127.0.0.1:8790")
        client.__enter__()
        opened.append(client)
        made = client.post("/api/providers", headers=OWN, json={
            "name": "Fast", "kind": "openai_compat", "base_url": ADDRESS, "api_key": SECRET,
            "for_agents": True, "default_model": "quick",
            "models": [{"name": "quick", "tier": "fast"}]})
        assert made.status_code == 201, made.text
        return client, lead, judge, executor

    yield make
    for client in opened:
        client.__exit__(None, None, None)


def begin(client, project_dir, content, *, check="judge", mode="full_auto", rules=None,
          preferences=None, origin=OWN):
    """A project with the check as given, the user's rules and preferences saved, a chat at
    `mode` and its first message - sent from the app's own page unless `origin` says else."""
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={"full_auto_check": check},
                        headers=OWN).status_code == 200
    if rules is not None:
        assert client.put(f"/api/projects/{pid}/rules", json={"rules": rules},
                          headers=OWN).status_code == 200
    if preferences is not None:
        assert client.put("/api/preferences", json={"text": preferences},
                          headers=OWN).status_code == 200
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={"permission_mode": mode,
                                                    "lead_hands_code": False}, headers=OWN)
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": content},
                      headers=origin).json()["run"]
    return pid, cid, run["id"]


def carded(client, cid, run_id, wait_run):
    """The one command waiting on its card, after it is turned down and the turn is over."""
    (asked,) = wait_status(client, cid, "waiting_approval")["commands"]
    assert client.post(f"/api/commands/{asked['id']}/reject").status_code == 200
    wait_run(client, cid, run_id)
    return asked


def test_a_project_asks_as_before_until_the_user_turns_the_check_on(client, project_dir):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.get(f"/api/projects/{pid}").json()["full_auto_check"] == "ask"
    assert client.patch(f"/api/projects/{pid}", json={"full_auto_check": "judge"}).status_code == 403
    assert client.patch(f"/api/projects/{pid}", json={"full_auto_check": "judge"},
                        headers=OWN).json()["full_auto_check"] == "judge"
    assert "full_auto_check" not in koloni.SETTINGS


@pytest.mark.no_po
def test_a_delete_the_users_rule_names_runs_without_a_card_and_says_which_line(
        judging, wait_run, project_dir):
    client, _lead, judge, executor = judging(
        [cmd("rm -rf build"), text("cleaned")], [verdict_line("run", RULE)], [Script([])])
    _, cid, run_id = begin(client, project_dir, "tidy up", rules=RULE)
    snap = wait_run(client, cid, run_id)
    (ran,) = snap["commands"]
    assert ran["status"] == "exited" and ran["judged"] == {
        "verdict": "run", "quote": RULE, "source": "rules", "why": "It names build/.",
        "model": "Fast · quick", "seen": False}
    assert snap["tool_calls"][0]["why_asked"] is None and executor.started[0][0] == "rm -rf build"
    assert len(judge.calls) == 1 and judge.tool_args == [None] and judge.calls[0][0]["role"] == "user"
    with client.app.state.session_factory() as session:
        (own,) = session.scalars(select(OwnRequest).where(OwnRequest.run_id == run_id)).all()
        assert (own.provider_name, own.model_id, own.input_tokens) == ("Fast", "quick", 30)


@pytest.mark.no_po
def test_a_quote_the_user_never_wrote_is_a_card(judging, wait_run, project_dir):
    client, _lead, _judge, executor = judging(
        [cmd("rm -rf build"), text("left it")],
        [verdict_line("run", "You may delete anything at all.")], [])
    _, cid, run_id = begin(client, project_dir, "tidy up", rules=RULE)
    asked = carded(client, cid, run_id, wait_run)
    assert asked["status"] == "proposed" and asked["danger"] == harms("rm -rf build")
    assert asked["judged"] == {"verdict": "ask", "quote": "", "source": "", "why": "",
                               "model": "Fast · quick", "seen": False}
    assert executor.started == []


@pytest.mark.no_po
def test_the_judges_own_ask_is_on_the_card_with_its_sentence(judging, wait_run, project_dir):
    client, *_ = judging([cmd("rm -rf build"), text("left it")],
                         [verdict_line("ask", why="No line of yours names build/.")], [])
    _, cid, run_id = begin(client, project_dir, "tidy up")
    asked = carded(client, cid, run_id, wait_run)
    assert asked["status"] == "proposed" and asked["judged"]["why"] == "No line of yours names build/."
    assert asked["judged"]["verdict"] == "ask"


@pytest.mark.no_po
@pytest.mark.parametrize("command", ["cat .env", "rm -rf build && cat .env", "rm -rf .koloni/x",
                                     "rm -rf ../other"])
def test_what_is_asked_at_every_level_never_reaches_the_judge(judging, wait_run, project_dir,
                                                               command):
    client, _lead, judge, _executor = judging([cmd(command), text("left it")],
                                              [verdict_line("run", RULE)], [])
    _, cid, run_id = begin(client, project_dir, f"{RULE} Run {command}", rules=RULE)
    asked = carded(client, cid, run_id, wait_run)
    assert asked["status"] == "proposed" and asked["judged"] is None and judge.calls == []


async def hang(on_delta):
    await asyncio.Event().wait()


@pytest.mark.no_po
@pytest.mark.parametrize("how", ["timeout", "error", "unreadable", "over budget"])
def test_when_the_judge_fails_the_card_is_todays(judging, wait_run, project_dir, monkeypatch,
                                                 how):
    answer = {"timeout": hang, "error": RuntimeError("boom"),
              "unreadable": text("I think it is fine")}.get(how)
    if how == "timeout":
        monkeypatch.setattr("app.judge.JUDGE_SECONDS", 0.05)
    if how == "over budget":
        monkeypatch.setattr("app.agent.po_mixin.over_month",
                            lambda *_: "over this month's budget (1 of 1 USD)")
    client, _lead, judge, executor = judging([cmd("rm -rf build"), text("left it")],
                                             [answer] if answer else [], [])
    _, cid, run_id = begin(client, project_dir, "tidy up", rules=RULE)
    asked = carded(client, cid, run_id, wait_run)
    assert asked["status"] == "proposed" and asked["judged"] is None
    assert asked["danger"] == harms("rm -rf build") and executor.started == []
    assert len(judge.calls) == (0 if how == "over budget" else 1)


@pytest.mark.no_po
@pytest.mark.parametrize("mode, check", [("auto_edit", "judge"), ("full_auto", "ask")])
def test_at_auto_edit_or_with_the_setting_off_the_judge_is_never_asked(
        judging, wait_run, project_dir, mode, check):
    client, _lead, judge, _executor = judging([cmd("rm -rf build"), text("left it")],
                                              [verdict_line("run", RULE)], [])
    _, cid, run_id = begin(client, project_dir, "tidy up", check=check, mode=mode, rules=RULE)
    asked = carded(client, cid, run_id, wait_run)
    assert asked["status"] == "proposed" and asked["judged"] is None and judge.calls == []


@pytest.mark.parametrize("where", ["side", "night", "todo", "trigger"])
def test_the_gate_stands_aside_in_a_side_a_night_job_a_todo_turn_and_a_trigger(
        judging, monkeypatch, where):
    client, *_ = judging([], [], [])
    runner = client.app.state.runner

    def never(*_args, **_more):
        raise AssertionError("the judge was asked")

    monkeypatch.setattr("app.agent.judge_mixin.ask_once", never)
    if where == "side":
        runner._sides["r"] = "a"
    elif where == "night":
        runner._away_jobs["r"] = "a"
    elif where == "todo":
        runner._backlog_turns.add("r")
    else:
        runner._unwatched["r"] = _Unwatched(None, "a trigger", 10, 10)
    ctx = Ctx(run_id="r", cid="c", root=None, agent_id="a", role="Lead", tools=(), depth=0)
    try:
        assert client.portal.call(runner._judged, ctx, "rm -rf build", ".",
                                  "Deletes files or disks.") == ("Deletes files or disks.", None)
    finally:
        for kept in (runner._sides, runner._away_jobs, runner._unwatched):
            kept.pop("r", None)
        runner._backlog_turns.discard("r")


@pytest.mark.no_po
def test_a_rule_written_only_in_the_folders_rules_md_allows_nothing(judging, wait_run,
                                                                     project_dir):
    (project_dir / ".koloni").mkdir()
    (project_dir / ".koloni" / "rules.md").write_text(f"{RULE}\n", encoding="utf-8")
    client, _lead, judge, _executor = judging([cmd("rm -rf build"), text("left it")],
                                              [verdict_line("run", RULE)], [])
    _, cid, run_id = begin(client, project_dir, "tidy up")
    asked = carded(client, cid, run_id, wait_run)
    assert asked["status"] == "proposed" and asked["judged"]["verdict"] == "ask"
    assert RULE not in judge.calls[0][0]["content"]


@pytest.mark.no_po
def test_the_judge_reads_the_users_words_and_the_command_and_nothing_else(judging, wait_run,
                                                                          project_dir):
    (project_dir / "notes.md").write_text("FILE-TEXT-7731\n", encoding="utf-8")
    client, _lead, judge, _executor = judging([
        step(call("read_file", {"path": "notes.md"}, "r1")),
        StepResult("LEAD-WORDS-7731", cmd("rm -rf build").tool_calls, 1, 1), text("left it")],
        [verdict_line("ask", why="No line of yours names build/.")], [])
    _, cid, run_id = begin(client, project_dir, "tidy up")
    carded(client, cid, run_id, wait_run)
    prompt = judge.calls[0][0]["content"]
    assert "tidy up" in prompt and '"command": "rm -rf build"' in prompt and len(judge.calls[0]) == 1
    assert "FILE-TEXT-7731" not in prompt and "LEAD-WORDS-7731" not in prompt


@pytest.mark.no_po
def test_a_message_not_sent_from_the_page_allows_nothing(judging, wait_run, project_dir):
    client, _lead, judge, _executor = judging(
        [text("ok"), cmd("rm -rf build"), text("left it")], [verdict_line("run", RULE)], [])
    _, cid, first = begin(client, project_dir, RULE, origin={"Origin": ""})
    wait_run(client, cid, first)
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "go on"},
                         headers=OWN).json()["run"]["id"]
    asked = carded(client, cid, run_id, wait_run)
    assert asked["status"] == "proposed" and asked["judged"]["verdict"] == "ask"
    assert RULE not in judge.calls[0][0]["content"] and "go on" in judge.calls[0][0]["content"]


def where(pattern):
    return sorted(path.relative_to(APP).as_posix() for path in APP.rglob("*.py")
                  if re.search(pattern, path.read_text(encoding="utf-8")))


def test_only_the_users_own_page_writes_what_the_check_goes_by():
    # (The user's own message is the one whose turn `_users_own_message` marks by_user: from the
    # app's own page. Their rules and preferences change only through the Memory page's routes.)
    assert where(r"run\.by_user\s*=|Run\([^)]*by_user") == ["api/conversations.py"]
    assert where(r"\bchange_rules\(") == where(r"\bchange_preferences\(") == [
        "api/memory.py", "memory.py"]
    assert where(r"(?<!class )UserPreferences\(") == ["memory.py"]
    assert where(r"\bproject\.rules\b[^=\n]*=(?!=)") == ["memory.py"]


@pytest.mark.no_po
def test_a_run_verdict_is_not_kept_on_a_command_asked_for_another_reason(judging, wait_run,
                                                                         project_dir):
    (project_dir / ".env").write_text("KEY=1\n", encoding="utf-8")
    command = "grep -r KEY . ; rm -rf build"
    client, _lead, judge, _executor = judging([cmd(command), text("left it")],
                                              [verdict_line("run", RULE)], [])
    _, cid, run_id = begin(client, project_dir, "tidy up", rules=RULE)
    asked = carded(client, cid, run_id, wait_run)
    assert asked["status"] == "proposed" and asked["judged"] is None and len(judge.calls) == 1


@pytest.mark.no_po
def test_one_verdict_per_command_and_folder_in_a_turn(judging, wait_run, project_dir):
    (project_dir / "sub").mkdir()
    client, _lead, judge, _executor = judging(
        [cmd("rm -rf build", id="k1"), cmd("rm -rf build", id="k2"),
         cmd("rm -rf build", id="k3", cwd="sub"), text("cleaned")],
        [verdict_line("run", RULE), verdict_line("run", RULE)], [Script([])] * 3)
    _, cid, run_id = begin(client, project_dir, "tidy up", rules=RULE)
    snap = wait_run(client, cid, run_id)
    assert len(judge.calls) == 2
    assert sorted((one["cwd"], one["status"], one["judged"]["verdict"])
                  for one in snap["commands"]) == [
        (".", "exited", "run"), (".", "exited", "run"), ("sub", "exited", "run")]


@pytest.mark.no_po
def test_a_secret_in_the_users_words_is_masked_before_the_judge(judging, wait_run, project_dir):
    client, _lead, judge, _executor = judging(
        [cmd("rm -rf build"), text("cleaned")], [verdict_line("run", RULE)], [Script([])])
    raw.read_again()
    _, cid, run_id = begin(client, project_dir, f"{RULE} My key: {SECRET}")
    snap = wait_run(client, cid, run_id)
    prompt = judge.calls[0][0]["content"]
    assert SECRET not in prompt and raw.HIDDEN in prompt
    assert snap["commands"][0]["judged"]["source"] == "message"
