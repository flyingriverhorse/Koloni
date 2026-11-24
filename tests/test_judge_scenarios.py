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
from sqlalchemy.exc import OperationalError

from app import koloni, raw
from app.agent.ctx import Ctx, _Unwatched
from app.agent.judge_mixin import CHECK_STOOD_ASIDE
from app.command_runner import CARRY_ON
from app.commands import harms
from app.config import load_settings
from app.db.models import OwnRequest
from app.main import create_app
from app.model_client import StepResult
from app.model_native import DECLINED_WHY
from tests.conftest import Gate
from tests.fakes import Script, ScriptedExecutor, ScriptedModel
from tests.keyed import NO_ORIGIN, OWN, TestClient
from tests.test_agent_commands import cmd
from tests.test_agent_writes import wait_status
from tests.test_agy_agent import agy_app  # noqa: F401  (a fixture)
from tests.test_chat_flow import text
from tests.test_claude_native import claude_app  # noqa: F401  (a fixture)
from tests.test_codex_app_server_scenarios import ACCEPT, DECLINE, RUN, answers
from tests.test_copilot_agent import copilot_native  # noqa: F401  (a fixture)
from tests.test_judge import NO_MAIN
from tests.test_native_agent import native_app  # noqa: F401  (a fixture)
from tests.test_spawn import call, spawn, step
from tests.test_team import ADDRESS, SECRET

RULE = "You may delete build/ and dist/."
# What an agent is told of a push the user's rule forbids (B-321: as of a command the user
# declined - not to run it again, nor anything that does the same).
TOLD = (
    'KOLONİ did not run this: your user\'s rule says "Never push to main.". Do not run it '
    "again, or anything that does the same; do what the rule allows, or ask them. " + CARRY_ON
)
# ...and of one a message of theirs in the chat forbids: not quoted.
TOLD_OF_A_MESSAGE = (
    "KOLONİ did not run this: a message of your user's in this chat forbids it. "
    "Do not run it again, or anything that does the same; do what it allows, or "
    "ask them. " + CARRY_ON
)
NO_BUILD = "Do not delete the build folder."
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
        app = create_app(
            load_settings(settings_env),
            model=lead,
            executors=executor.factory,
            clients={"Fast": judge},
        )
        client = TestClient(app, base_url="http://127.0.0.1:8790")
        client.__enter__()
        opened.append(client)
        made = client.post(
            "/api/providers",
            headers=OWN,
            json={
                "name": "Fast",
                "kind": "openai_compat",
                "base_url": ADDRESS,
                "api_key": SECRET,
                "for_agents": True,
                "default_model": "quick",
                "models": [{"name": "quick", "tier": "fast"}],
            },
        )
        assert made.status_code == 201, made.text
        return client, lead, judge, executor

    yield make
    for client in opened:
        client.__exit__(None, None, None)


def begin(
    client,
    project_dir,
    content,
    *,
    check="judge",
    mode="full_auto",
    rules=None,
    preferences=None,
    origin=OWN,
    provider=None,
):
    """A project with the check as given, the user's rules and preferences saved, a chat at
    `mode` (its Lead on `provider`, where given) and its first message - sent from the app's own
    page unless `origin` says else."""
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert (
        client.patch(
            f"/api/projects/{pid}", json={"full_auto_check": check}, headers=OWN
        ).status_code
        == 200
    )
    if rules is not None:
        assert (
            client.put(f"/api/projects/{pid}/rules", json={"rules": rules}, headers=OWN).status_code
            == 200
        )
    if preferences is not None:
        assert (
            client.put("/api/preferences", json={"text": preferences}, headers=OWN).status_code
            == 200
        )
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(
        f"/api/conversations/{cid}",
        json={
            "permission_mode": mode,
            "lead_hands_code": False,
            **({"provider_id": provider["id"]} if provider else {}),
        },
        headers=OWN,
    )
    run = client.post(
        f"/api/conversations/{cid}/messages", json={"content": content}, headers=origin
    ).json()["run"]
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
    assert (
        client.patch(f"/api/projects/{pid}", json={"full_auto_check": "judge"}).status_code == 403
    )
    assert (
        client.patch(f"/api/projects/{pid}", json={"full_auto_check": "judge"}, headers=OWN).json()[
            "full_auto_check"
        ]
        == "judge"
    )
    assert "full_auto_check" not in koloni.SETTINGS


@pytest.mark.no_po
def test_a_delete_the_users_rule_names_runs_without_a_card_and_says_which_line(
    judging, wait_run, project_dir
):
    client, _lead, judge, executor = judging(
        [cmd("rm -rf build"), text("cleaned")], [verdict_line("run", RULE)], [Script([])]
    )
    _, cid, run_id = begin(client, project_dir, "tidy up", rules=RULE)
    snap = wait_run(client, cid, run_id)
    (ran,) = snap["commands"]
    assert ran["status"] == "exited" and ran["judged"] == {
        "verdict": "run",
        "quote": RULE,
        "source": "rules",
        "why": "It names build/.",
        "model": "Fast · quick",
        "seen": False,
    }
    assert snap["tool_calls"][0]["why_asked"] is None and executor.started[0][0] == "rm -rf build"
    assert (
        len(judge.calls) == 1 and judge.tool_args == [None] and judge.calls[0][0]["role"] == "user"
    )
    with client.app.state.session_factory() as session:
        (own,) = session.scalars(select(OwnRequest).where(OwnRequest.run_id == run_id)).all()
        assert (own.provider_name, own.model_id, own.input_tokens) == ("Fast", "quick", 30)


@pytest.mark.no_po
def test_a_quote_the_user_never_wrote_is_a_card(judging, wait_run, project_dir):
    client, _lead, _judge, executor = judging(
        [cmd("rm -rf build"), text("left it")],
        [verdict_line("run", "You may delete anything at all.")],
        [],
    )
    _, cid, run_id = begin(client, project_dir, "tidy up", rules=RULE)
    asked = carded(client, cid, run_id, wait_run)
    assert asked["status"] == "proposed" and asked["danger"] == harms("rm -rf build")
    assert asked["judged"] == {
        "verdict": "ask",
        "quote": "",
        "source": "",
        "why": "",
        "model": "Fast · quick",
        "seen": False,
    }
    assert executor.started == []


@pytest.mark.no_po
def test_the_judges_own_ask_is_on_the_card_with_its_sentence(judging, wait_run, project_dir):
    client, *_ = judging(
        [cmd("rm -rf build"), text("left it")],
        [verdict_line("ask", why="No line of yours names build/.")],
        [],
    )
    _, cid, run_id = begin(client, project_dir, "tidy up")
    asked = carded(client, cid, run_id, wait_run)
    assert (
        asked["status"] == "proposed" and asked["judged"]["why"] == "No line of yours names build/."
    )
    assert asked["judged"]["verdict"] == "ask"


@pytest.mark.no_po
@pytest.mark.parametrize(
    "command", ["cat .env", "rm -rf build && cat .env", "rm -rf .koloni/x", "rm -rf ../other"]
)
def test_what_is_asked_at_every_level_never_reaches_the_judge(
    judging, wait_run, project_dir, command
):
    client, _lead, judge, _executor = judging(
        [cmd(command), text("left it")], [verdict_line("run", RULE)], []
    )
    _, cid, run_id = begin(client, project_dir, f"{RULE} Run {command}", rules=RULE)
    asked = carded(client, cid, run_id, wait_run)
    assert asked["status"] == "proposed" and asked["judged"] is None and judge.calls == []


async def hang(on_delta):
    await asyncio.Event().wait()


@pytest.mark.no_po
@pytest.mark.parametrize("how", ["timeout", "error", "unreadable", "over budget"])
def test_when_the_judge_fails_the_card_is_todays(judging, wait_run, project_dir, monkeypatch, how):
    answer = {
        "timeout": hang,
        "error": RuntimeError("boom"),
        "unreadable": text("I think it is fine"),
    }.get(how)
    if how == "timeout":
        monkeypatch.setattr("app.judge.JUDGE_SECONDS", 0.05)
    if how == "over budget":
        monkeypatch.setattr(
            "app.agent.po_mixin.over_month", lambda *_: "over this month's budget (1 of 1 USD)"
        )
    client, _lead, judge, executor = judging(
        [cmd("rm -rf build"), text("left it")], [answer] if answer else [], []
    )
    _, cid, run_id = begin(client, project_dir, "tidy up", rules=RULE)
    asked = carded(client, cid, run_id, wait_run)
    assert asked["status"] == "proposed" and asked["judged"] is None
    assert asked["danger"] == harms("rm -rf build") and executor.started == []
    assert len(judge.calls) == (0 if how == "over budget" else 1)


@pytest.mark.no_po
@pytest.mark.parametrize("mode, check", [("auto_edit", "judge"), ("full_auto", "ask")])
def test_at_auto_edit_or_with_the_setting_off_the_judge_is_never_asked(
    judging, wait_run, project_dir, mode, check
):
    client, _lead, judge, _executor = judging(
        [cmd("rm -rf build"), text("left it")], [verdict_line("run", RULE)], []
    )
    _, cid, run_id = begin(client, project_dir, "tidy up", check=check, mode=mode, rules=RULE)
    asked = carded(client, cid, run_id, wait_run)
    assert asked["status"] == "proposed" and asked["judged"] is None and judge.calls == []


@pytest.mark.parametrize("where", ["side", "night", "trigger"])
def test_the_gate_stands_aside_in_a_side_a_night_job_and_a_trigger(judging, monkeypatch, where):
    client, *_ = judging([], [], [])
    runner = client.app.state.runner

    def never(*_args, **_more):
        raise AssertionError("the judge was asked")

    monkeypatch.setattr("app.agent.judge_mixin.ask_once", never)
    if where == "side":
        runner._sides["r"] = "a"
    elif where == "night":
        runner._away_jobs["r"] = "a"
    else:
        runner._unwatched["r"] = _Unwatched(None, "a trigger", 10, 10)
    ctx = Ctx(run_id="r", cid="c", root=None, agent_id="a", role="Lead", tools=(), depth=0)
    try:
        assert client.portal.call(
            runner._judged, ctx, "rm -rf build", ".", "Deletes files or disks."
        ) == ("Deletes files or disks.", None)
    finally:
        for kept in (runner._sides, runner._away_jobs, runner._unwatched):
            kept.pop("r", None)


@pytest.mark.no_po
def test_a_rule_written_only_in_the_folders_rules_md_allows_nothing(judging, wait_run, project_dir):
    (project_dir / ".koloni").mkdir()
    (project_dir / ".koloni" / "rules.md").write_text(f"{RULE}\n", encoding="utf-8")
    client, _lead, judge, _executor = judging(
        [cmd("rm -rf build"), text("left it")], [verdict_line("run", RULE)], []
    )
    _, cid, run_id = begin(client, project_dir, "tidy up")
    asked = carded(client, cid, run_id, wait_run)
    assert asked["status"] == "proposed" and asked["judged"]["verdict"] == "ask"
    assert RULE not in judge.calls[0][0]["content"]


@pytest.mark.no_po
def test_the_judge_reads_the_users_words_and_the_command_and_nothing_else(
    judging, wait_run, project_dir
):
    (project_dir / "notes.md").write_text("FILE-TEXT-7731\n", encoding="utf-8")
    client, _lead, judge, _executor = judging(
        [
            step(call("read_file", {"path": "notes.md"}, "r1")),
            StepResult("LEAD-WORDS-7731", cmd("rm -rf build").tool_calls, 1, 1),
            text("left it"),
        ],
        [verdict_line("ask", why="No line of yours names build/.")],
        [],
    )
    _, cid, run_id = begin(client, project_dir, "tidy up")
    carded(client, cid, run_id, wait_run)
    prompt = judge.calls[0][0]["content"]
    assert (
        "tidy up" in prompt and '"command": "rm -rf build"' in prompt and len(judge.calls[0]) == 1
    )
    assert "FILE-TEXT-7731" not in prompt and "LEAD-WORDS-7731" not in prompt


@pytest.mark.no_po
def test_a_message_not_sent_from_the_page_allows_nothing(judging, wait_run, project_dir):
    client, _lead, judge, _executor = judging(
        [text("ok"), cmd("rm -rf build"), text("left it")], [verdict_line("run", RULE)], []
    )
    _, cid, first = begin(client, project_dir, RULE, origin={"Origin": ""})
    wait_run(client, cid, first)
    run_id = client.post(
        f"/api/conversations/{cid}/messages", json={"content": "go on"}, headers=OWN
    ).json()["run"]["id"]
    asked = carded(client, cid, run_id, wait_run)
    assert asked["status"] == "proposed" and asked["judged"]["verdict"] == "ask"
    assert RULE not in judge.calls[0][0]["content"] and "go on" in judge.calls[0][0]["content"]


def where(pattern):
    return sorted(
        path.relative_to(APP).as_posix()
        for path in APP.rglob("*.py")
        if re.search(pattern, path.read_text(encoding="utf-8"))
    )


def test_only_the_users_own_page_writes_what_the_check_goes_by():
    # (The user's own message is the one whose turn `_users_own_message` marks by_user: from the
    # app's own page. Their rules and preferences change only through the Memory page's routes.)
    assert where(r"run\.by_user\s*=|Run\([^)]*by_user") == ["api/conversations.py"]
    assert (
        where(r"\bchange_rules\(")
        == where(r"\bchange_preferences\(")
        == ["api/memory.py", "memory.py"]
    )
    assert where(r"(?<!class )UserPreferences\(") == ["memory.py"]
    assert where(r"\bproject\.rules\b[^=\n]*=(?!=)") == ["memory.py"]


@pytest.mark.no_po
def test_a_run_verdict_is_not_kept_on_a_command_asked_for_another_reason(
    judging, wait_run, project_dir
):
    (project_dir / ".env").write_text("KEY=1\n", encoding="utf-8")
    command = "grep -r KEY . ; rm -rf build"
    client, _lead, judge, _executor = judging(
        [cmd(command), text("left it")], [verdict_line("run", RULE)], []
    )
    _, cid, run_id = begin(client, project_dir, "tidy up", rules=RULE)
    asked = carded(client, cid, run_id, wait_run)
    assert asked["status"] == "proposed" and asked["judged"] is None and len(judge.calls) == 1


@pytest.mark.no_po
def test_one_verdict_per_command_and_folder_in_a_turn(judging, wait_run, project_dir):
    (project_dir / "sub").mkdir()
    client, _lead, judge, _executor = judging(
        [
            cmd("rm -rf build", id="k1"),
            cmd("rm -rf build", id="k2"),
            cmd("rm -rf build", id="k3", cwd="sub"),
            text("cleaned"),
        ],
        [verdict_line("run", RULE), verdict_line("run", RULE)],
        [Script([])] * 3,
    )
    _, cid, run_id = begin(client, project_dir, "tidy up", rules=RULE)
    snap = wait_run(client, cid, run_id)
    assert len(judge.calls) == 2
    assert sorted(
        (one["cwd"], one["status"], one["judged"]["verdict"]) for one in snap["commands"]
    ) == [(".", "exited", "run"), (".", "exited", "run"), ("sub", "exited", "run")]


@pytest.mark.no_po
def test_a_secret_in_the_users_words_is_masked_before_the_judge(judging, wait_run, project_dir):
    client, _lead, judge, _executor = judging(
        [cmd("rm -rf build"), text("cleaned")], [verdict_line("run", RULE)], [Script([])]
    )
    raw.read_again()
    _, cid, run_id = begin(client, project_dir, f"{RULE} My key: {SECRET}")
    snap = wait_run(client, cid, run_id)
    prompt = judge.calls[0][0]["content"]
    assert SECRET not in prompt and raw.HIDDEN in prompt
    assert snap["commands"][0]["judged"]["source"] == "message"


# --- a native CLI's own command goes through the same check -------------------------------------


def judged_by_local(client, cli):
    """The default provider's model (the scripted one) is the Fast tier's first: the judge."""
    local = next(p for p in client.get("/api/providers").json() if p["id"] != cli["id"])
    assert (
        client.patch(
            f"/api/providers/{local['id']}",
            headers=OWN,
            json={
                "models": [{"name": local["default_model"] or "big-model", "tier": "fast"}],
                "for_agents": True,
            },
        ).status_code
        == 200
    )


def ran_on_the_rule(client, project_dir, cli, wait_run):
    judged_by_local(client, cli)
    _, cid, run_id = begin(client, project_dir, "tidy up", rules=RULE, provider=cli)
    snap = wait_run(client, cid, run_id, 30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (ran,) = snap["commands"]
    assert ran["status"] != "proposed" and ran["origin"] == "cli"
    assert (ran["judged"]["verdict"], ran["judged"]["quote"]) == ("run", RULE)


@pytest.mark.no_po
def test_codex_runs_a_delete_the_users_rule_names_without_a_card(
    native_app,
    wait_run,  # noqa: F811
    project_dir,
):
    client, cli, default = native_app(
        [{"run": "rm -rf build", "output": ""}, {"say": "cleaned"}],
        default_steps=[verdict_line("run", RULE)],
    )
    ran_on_the_rule(client, project_dir, cli, wait_run)
    assert answers(native_app) == [(RUN, ACCEPT)] and len(default.calls) == 1


@pytest.mark.no_po
def test_claude_codes_own_bash_runs_a_delete_the_users_rule_names_without_a_card(
    claude_app, wait_run, project_dir
):  # noqa: F811
    client, cli, default = claude_app(
        [{"tool": "Bash", "input": {"command": "rm -rf build"}, "result": ""}, {"say": "cleaned"}],
        default_steps=[verdict_line("run", RULE)],
    )
    ran_on_the_rule(client, project_dir, cli, wait_run)
    assert len(default.calls) == 1


@pytest.mark.no_po
def test_copilots_shell_runs_a_delete_the_users_rule_names_without_a_card(
    copilot_native, wait_run, project_dir
):  # noqa: F811
    # (a version whose new shell was measured, and that runs natively: it starts at the project,
    # a folder known)
    client, cli = copilot_native(
        [{"shell": "rm -rf build", "output": ""}, {"say": "cleaned"}],
        default_steps=[verdict_line("run", RULE)],
        version="1.0.105",
    )
    ran_on_the_rule(client, project_dir, cli, wait_run)


@pytest.mark.no_po
def test_agys_run_command_with_no_folder_is_a_card_the_check_never_sees(
    agy_app, wait_run, project_dir
):  # noqa: F811
    # (security review of K-yargıç, MEDIUM-3: where its shell stands is not known - `rm -rf build`
    # there may be another build/ than the one the user's rule names)
    client, cli, default = agy_app(
        [
            {
                "tool": "run_command",
                "asks": True,
                "parameters": {"CommandLine": "rm -rf build"},
                "output": "",
            },
            {"say": "left it"},
        ],
        mode="native",
        default_steps=[verdict_line("run", RULE)],
    )
    judged_by_local(client, cli)
    _, cid, run_id = begin(client, project_dir, "tidy up", rules=RULE, provider=cli)
    asked = carded(client, cid, run_id, lambda *args: wait_run(*args, 30))
    assert asked["status"] == "proposed" and asked["judged"] is None and default.calls == []


# --- Decided for you: OK ------------------------------------------------------------------------


@pytest.mark.no_po
def test_ok_takes_a_command_the_check_let_run_off_decided_for_you(judging, wait_run, project_dir):
    client, *_ = judging(
        [cmd("rm -rf build", id="k1"), cmd("git push origin main", id="k2"), text("done")],
        [verdict_line("run", RULE), verdict_line("ask", why="No line names a push.")],
        [Script([])],
    )
    _, cid, run_id = begin(client, project_dir, "tidy up", rules=RULE)
    commands = wait_status(client, cid, "waiting_approval")["commands"]
    (ran,), (asked,) = (
        [one for one in commands if (one["status"] == "proposed") is waits]
        for waits in (False, True)
    )
    assert client.post(f"/api/commands/{asked['id']}/reject").status_code == 200
    wait_run(client, cid, run_id)
    url = f"/api/commands/{ran['id']}/seen"
    assert client.post(url, headers=NO_ORIGIN).status_code == 403
    seen = client.post(url, headers=OWN)
    assert seen.status_code == 200 and seen.json()["judged"] == {**ran["judged"], "seen": True}
    assert client.post(url, headers=OWN).status_code == 409
    assert client.post(f"/api/commands/{asked['id']}/seen", headers=OWN).status_code == 404


@pytest.mark.no_po
def test_a_folder_the_clis_model_wrote_is_not_taken_on_its_word_by_the_check(
    agy_app,
    wait_run,  # noqa: F811
    project_dir,
):
    # (agy's Cwd is its model's argument: its shell may stand at the root, where `rm -rf .`
    # takes the whole project - "You may delete build/" covers nothing there)
    client, cli, default = agy_app(
        [
            {
                "tool": "run_command",
                "asks": True,
                "parameters": {"CommandLine": "rm -rf .", "Cwd": "build"},
                "output": "",
            },
            {"say": "left it"},
        ],
        mode="native",
        default_steps=[verdict_line("run", RULE)],
    )
    (project_dir / "build").mkdir()
    judged_by_local(client, cli)
    _, cid, run_id = begin(client, project_dir, "tidy up", rules=RULE, provider=cli)
    asked = carded(client, cid, run_id, lambda *args: wait_run(*args, 30))
    assert asked["status"] == "proposed" and asked["judged"] is None and default.calls == []


# --- the security review's fix round (LOW-5, 6, 7) ------------------------------------------------


@pytest.mark.no_po
def test_a_rule_taken_away_in_the_turn_is_checked_again(judging, wait_run, project_dir):
    gate = Gate()
    client, _lead, judge, _executor = judging(
        [cmd("rm -rf build", id="k1"), gate.step(cmd("rm -rf build", id="k2")), text("done")],
        [verdict_line("run", RULE), verdict_line("run", RULE)],
        [Script([])],
    )
    pid, cid, run_id = begin(client, project_dir, "tidy up", rules=RULE)
    gate.wait_partial()  # (the first ran on the rule; the user takes the rule away)
    assert (
        client.put(f"/api/projects/{pid}/rules", json={"rules": ""}, headers=OWN).status_code == 200
    )
    gate.release()
    commands = wait_status(client, cid, "waiting_approval")["commands"]
    (asked,) = [one for one in commands if one["status"] == "proposed"]
    assert asked["judged"]["verdict"] == "ask" and len(judge.calls) == 2
    assert client.post(f"/api/commands/{asked['id']}/reject").status_code == 200
    wait_run(client, cid, run_id)


@pytest.mark.no_po
@pytest.mark.parametrize("breaks", ["its answer", "the database"])
def test_whatever_breaks_in_the_check_the_card_is_todays(
    judging, wait_run, project_dir, monkeypatch, breaks
):
    def broken(*_args):
        raise (
            RecursionError("too deep")
            if breaks == "its answer"
            else OperationalError("SELECT", None, Exception("database is locked"))
        )

    monkeypatch.setattr(
        "app.judge.verdict" if breaks == "its answer" else "app.agent.judge_mixin.project_of",
        broken,
    )
    client, _lead, _judge, executor = judging(
        [cmd("rm -rf build"), text("left it")], [verdict_line("run", RULE)], []
    )
    _, cid, run_id = begin(client, project_dir, "tidy up", rules=RULE)
    asked = carded(client, cid, run_id, wait_run)
    assert asked["status"] == "proposed" and asked["judged"] is None and executor.started == []


@pytest.mark.no_po
def test_the_reason_the_judge_is_given_is_masked_too(judging, wait_run, project_dir, monkeypatch):
    monkeypatch.setattr(
        "app.agent.away_mixin.harms", lambda *_args: f"Deletes files or disks. {SECRET}"
    )
    client, _lead, judge, _executor = judging(
        [cmd("rm -rf build"), text("left it")], [verdict_line("ask")], []
    )
    raw.read_again()
    _, cid, run_id = begin(client, project_dir, "tidy up", rules=RULE)
    carded(client, cid, run_id, wait_run)
    prompt = judge.calls[0][0]["content"]
    assert (
        SECRET not in prompt
        and f'"flagged_because": "Deletes files or disks. {raw.HIDDEN}"' in prompt
    )


# --- slice 2: a command a sentence of the user's forbids is not run ------------------------------


def command_statuses(client):
    """Every status a command is given on the bus from now on."""
    statuses, emit = [], client.app.state.bus.emit

    def watch(conversation_id, run_id, kind, payload):
        if kind in ("command.created", "command.updated"):
            statuses.append(payload["status"])
        return emit(conversation_id, run_id, kind, payload)

    client.app.state.bus.emit = watch
    return statuses


@pytest.mark.no_po
def test_a_push_the_users_rule_forbids_is_not_run_and_the_agent_hears_the_rule(
    judging, wait_run, project_dir
):
    client, lead, _judge, executor = judging(
        [cmd("git push origin main"), text("pushed a branch instead")],
        [verdict_line("refuse", NO_MAIN, why="The rule forbids it.")],
        [],
    )
    statuses = command_statuses(client)
    _, cid, run_id = begin(client, project_dir, "ship it", rules=NO_MAIN)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (refused,) = snap["commands"]
    assert (
        refused["status"] == "refused"
        and refused["ended_at"]
        and refused["judged"]
        == {
            "verdict": "refuse",
            "quote": NO_MAIN,
            "source": "rules",
            "why": "The rule forbids it.",
            "model": "Fast · quick",
            "seen": False,
        }
    )
    assert statuses == ["refused"] and executor.started == []
    assert [one["status"] for one in snap["tool_calls"]] == ["denied"]
    assert TOLD in lead.calls[1][-1]["content"]
    assert [one for one in snap["messages"] if one["role"] == "koloni"] == []
    seen = client.post(f"/api/commands/{refused['id']}/seen", headers=OWN)
    assert seen.status_code == 200 and seen.json()["judged"]["seen"] is True


@pytest.mark.no_po
def test_a_refuse_on_a_line_that_forbids_nothing_is_a_card(judging, wait_run, project_dir):
    client, _lead, _judge, executor = judging(
        [cmd("rm -rf build"), text("left it")], [verdict_line("refuse", RULE)], []
    )
    _, cid, run_id = begin(client, project_dir, "tidy up", rules=RULE)
    asked = carded(client, cid, run_id, wait_run)
    assert asked["status"] == "proposed" and asked["judged"] == {
        "verdict": "ask",
        "quote": "",
        "source": "",
        "why": "",
        "model": "Fast · quick",
        "seen": False,
    }
    assert executor.started == []


def refused_on_the_rule(client, project_dir, cli, wait_run):
    judged_by_local(client, cli)
    _, cid, run_id = begin(client, project_dir, "ship it", rules=NO_MAIN, provider=cli)
    snap = wait_run(client, cid, run_id, 30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (refused,) = snap["commands"]
    assert (refused["status"], refused["origin"]) == ("refused", "cli")
    assert (refused["judged"]["verdict"], refused["judged"]["quote"]) == ("refuse", NO_MAIN)


@pytest.mark.no_po
def test_codex_is_told_in_its_turn_why_a_push_the_users_rule_forbids_is_declined(
    native_app, wait_run, project_dir
):  # noqa: F811
    client, cli, _default = native_app(
        [{"run": "git push origin main", "output": ""}, {"say": "pushed a branch"}],
        default_steps=[verdict_line("refuse", NO_MAIN)],
    )
    refused_on_the_rule(client, project_dir, cli, wait_run)
    assert answers(native_app) == [(RUN, DECLINE)]
    assert [one["input"][0]["text"] for one in native_app.record().get("steers", [])] == [
        DECLINED_WHY.format(why=TOLD)
    ]


@pytest.mark.no_po
def test_claude_codes_bash_push_the_users_rule_forbids_is_denied_with_the_rule(
    claude_app, wait_run, project_dir
):  # noqa: F811
    client, cli, _default = claude_app(
        [
            {"tool": "Bash", "input": {"command": "git push origin main"}, "result": ""},
            {"say": "pushed a branch"},
        ],
        default_steps=[verdict_line("refuse", NO_MAIN)],
    )
    refused_on_the_rule(client, project_dir, cli, wait_run)
    (asked,) = claude_app.record()["asked"]
    assert (asked["behavior"], asked["message"]) == ("deny", TOLD)


@pytest.mark.no_po
def test_a_message_of_the_users_that_forbids_is_quoted_to_no_agent_nor_a_sub_agent(
    judging, wait_run, project_dir
):
    # (security review of slice 2: a sub-agent or a CLI never saw the chat, and a token nothing
    # masks may stand beside the sentence - the user sees it on the row, no agent is told it)
    client, model, _judge, executor = judging(
        {
            "Lead": [
                cmd("git push origin main", id="k1"),
                spawn("Coder", "tidy the build folder"),
                text("done"),
            ],
            "Coder": [cmd("rm -rf build", id="k2"), text("left it")],
        },
        [verdict_line("refuse", NO_MAIN), verdict_line("refuse", NO_BUILD)],
        [],
    )
    _, cid, run_id = begin(client, project_dir, f"{NO_MAIN} {NO_BUILD} Tidy up.")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert sorted(
        (one["status"], one["judged"]["source"], one["judged"]["quote"]) for one in snap["commands"]
    ) == [("refused", "message", NO_BUILD), ("refused", "message", NO_MAIN)]
    for name in ("Lead", "Coder"):
        told = model.calls_of[name][1][-1]["content"]  # (its call after its command)
        assert TOLD_OF_A_MESSAGE in told and NO_MAIN not in told and NO_BUILD not in told
    assert NO_BUILD not in json.dumps(model.calls_of["Coder"], ensure_ascii=False)
    assert executor.started == []


def koloni_lines(snap):
    return [one["content"] for one in snap["messages"] if one["role"] == "koloni"]


@pytest.mark.no_po
def test_after_three_refusals_in_a_row_the_rest_of_the_turn_asks_on_a_card(
    judging, wait_run, project_dir
):
    # (a refusal the turn keeps is said again from its cache - the fourth try is not)
    client, _lead, judge, executor = judging(
        [*(cmd("git push origin main", id=f"k{n}") for n in range(1, 5)), text("left it")],
        [verdict_line("refuse", NO_MAIN)],
        [],
    )
    _, cid, run_id = begin(client, project_dir, "ship it", rules=NO_MAIN)
    commands = wait_status(client, cid, "waiting_approval")["commands"]
    assert [one["status"] for one in commands] == ["refused"] * 3 + ["proposed"]
    assert commands[3]["judged"] is None and len(judge.calls) == 1
    assert client.post(f"/api/commands/{commands[3]['id']}/reject").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert koloni_lines(snap) == [CHECK_STOOD_ASIDE.format(count="3 commands in a row")]
    assert executor.started == []


@pytest.mark.no_po
def test_a_turns_refusals_stop_the_check_too_and_a_run_ends_a_row(
    judging, wait_run, project_dir, monkeypatch
):
    monkeypatch.setattr("app.judge.MOST_REFUSED_IN_A_ROW", 2)
    monkeypatch.setattr("app.judge.MOST_REFUSED_IN_A_TURN", 2)
    client, _lead, judge, _executor = judging(
        [
            cmd("git push origin main", id="k1"),
            cmd("rm -rf build", id="k2"),
            cmd("git push origin main", id="k3"),
            cmd("rm -rf build", id="k4"),
            text("left it"),
        ],
        [verdict_line("refuse", NO_MAIN), verdict_line("run", RULE)],
        [Script([])],
    )
    _, cid, run_id = begin(client, project_dir, "tidy up", rules=f"{RULE}\n{NO_MAIN}")
    commands = wait_status(client, cid, "waiting_approval")["commands"]
    assert [one["status"] for one in commands] == ["refused", "exited", "refused", "proposed"]
    assert commands[3]["judged"] is None and len(judge.calls) == 2
    assert client.post(f"/api/commands/{commands[3]['id']}/reject").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert koloni_lines(snap) == [CHECK_STOOD_ASIDE.format(count="2 commands")]


def test_a_verdict_that_comes_back_once_the_check_stood_aside_is_a_card(judging):
    # (one asked while the third refusal was out: it neither runs nor refuses)
    client, *_ = judging([], [], [])
    runner = client.app.state.runner
    ctx = Ctx(run_id="r", cid="c", root=None, agent_id="a", role="Lead", tools=(), depth=0)
    runner._judge_refused["r"] = (3, 3)
    try:
        for word in ("run", "refuse"):
            assert runner._judgement(
                ctx,
                "Deletes files or disks.",
                {"verdict": word, "quote": NO_MAIN, "source": "rules", "why": ""},
            ) == ("Deletes files or disks.", None)
        assert runner._judge_refused["r"] == (3, 3)
    finally:
        runner._judge_refused.pop("r", None)


def left(client, pid, cid, change):
    """The chat's level lowered to Auto-edit, or the project's check turned off."""
    changed = (
        client.patch(
            f"/api/conversations/{cid}", json={"permission_mode": "auto_edit"}, headers=OWN
        )
        if change == "level"
        else client.patch(f"/api/projects/{pid}", json={"full_auto_check": "ask"}, headers=OWN)
    )
    assert changed.status_code == 200, changed.text


@pytest.mark.no_po
@pytest.mark.parametrize("change", ["level", "setting"])
def test_a_refusal_that_comes_back_once_full_auto_or_the_check_was_left_is_a_card(
    judging, wait_run, project_dir, change
):
    # (security review of slice 2: as a run is - a refusal holds only where it was asked for)
    gate = Gate()
    client, _lead, _judge, executor = judging(
        [cmd("git push origin main"), text("left it")],
        [gate.step(verdict_line("refuse", NO_MAIN))],
        [],
    )
    pid, cid, run_id = begin(client, project_dir, "ship it", rules=NO_MAIN)
    gate.wait_partial()
    left(client, pid, cid, change)
    gate.release()
    asked = carded(client, cid, run_id, wait_run)
    assert asked["status"] == "proposed" and asked["judged"] is None and executor.started == []


@pytest.mark.no_po
def test_claude_codes_bash_refused_once_full_auto_was_left_is_a_card(
    claude_app,
    wait_run,  # noqa: F811
    project_dir,
):
    gate = Gate()
    client, cli, _default = claude_app(
        [
            {"tool": "Bash", "input": {"command": "git push origin main"}, "result": ""},
            {"say": "left it"},
        ],
        default_steps=[gate.step(verdict_line("refuse", NO_MAIN))],
    )
    judged_by_local(client, cli)
    pid, cid, run_id = begin(client, project_dir, "ship it", rules=NO_MAIN, provider=cli)
    gate.wait_partial()
    left(client, pid, cid, "level")
    gate.release()
    asked = carded(client, cid, run_id, lambda *args: wait_run(*args, 30))
    assert asked["status"] == "proposed" and asked["judged"] is None
    assert claude_app.record()["asked"][0]["behavior"] == "deny"


@pytest.mark.no_po
def test_a_run_that_comes_back_once_the_check_was_turned_off_is_a_card(
    judging, wait_run, project_dir
):
    # (as a refusal is: a run holds only while the chat is at Full auto and the check is on)
    gate = Gate()
    client, _lead, _judge, executor = judging(
        [cmd("rm -rf build"), text("left it")], [gate.step(verdict_line("run", RULE))], []
    )
    pid, cid, run_id = begin(client, project_dir, "tidy up", rules=RULE)
    gate.wait_partial()
    left(client, pid, cid, "setting")
    gate.release()
    asked = carded(client, cid, run_id, wait_run)
    assert asked["status"] == "proposed" and asked["judged"] is None and executor.started == []


@pytest.mark.no_po
def test_claude_codes_bash_run_once_the_check_was_turned_off_is_a_card(
    claude_app,
    wait_run,  # noqa: F811
    project_dir,
):
    gate = Gate()
    client, cli, _default = claude_app(
        [{"tool": "Bash", "input": {"command": "rm -rf build"}, "result": ""}, {"say": "left it"}],
        default_steps=[gate.step(verdict_line("run", RULE))],
    )
    judged_by_local(client, cli)
    pid, cid, run_id = begin(client, project_dir, "tidy up", rules=RULE, provider=cli)
    gate.wait_partial()
    left(client, pid, cid, "setting")
    gate.release()
    asked = carded(client, cid, run_id, lambda *args: wait_run(*args, 30))
    assert asked["status"] == "proposed" and asked["judged"] is None
    assert claude_app.record()["asked"][0]["behavior"] == "deny"


# --- ☾ Away: a job's delete, while the user is away from a chat at Full auto -----------------


def away_with(client, project_dir, wait_run, mode, rules=RULE, todo=None):
    """The user's chat (at `mode`, the To-do page's level `todo` - `mode` without it -, the check
    on, `rules` saved) puts one task on To-do, and they go away; returns (pid, the night)."""
    from tests.test_away_scenarios import proposed_in

    pid, cid, run_id = begin(client, project_dir, "tidy up while I sleep", rules=rules, mode=mode)
    client.todo_mode = todo or mode
    wait_run(client, cid, run_id)
    gone = client.post(
        f"/api/conversations/{cid}/away", json={"task_ids": proposed_in(client, cid)}, headers=OWN
    )
    assert gone.status_code == 200, gone.text
    return pid, gone.json()


TIDY = {"jobs": [{"title": "tidy", "line": "delete every file in sight"}]}


@pytest.mark.no_po
def test_while_away_a_jobs_delete_your_words_allow_runs_in_its_copy_without_a_card(
    judging, wait_run, project_dir
):
    from tests.test_away_scenarios import ended, to_do

    client, _lead, judge, executor = judging(
        [to_do(TIDY), text("on your To-do"), cmd("rm -rf build"), text("tidied")],
        [verdict_line("run", RULE)],
        [Script([])],
    )
    pid, _night = away_with(client, project_dir, wait_run, "full_auto")
    done = ended(client, pid)
    (job,) = done["jobs"]
    assert job["state"] == "done"  # (it did not wait)
    (ran,) = client.get(f"/api/conversations/{job['conversation_id']}").json()["commands"]
    assert ran["status"] == "exited" and ran["judged"]["verdict"] == "run"
    assert executor.started[0][0] == "rm -rf build"
    assert done["decided"] == ['ran "rm -rf build" (your words)']
    # the check read the user's words in the chat they went away from - never the task's
    asked = str(judge.calls[0])
    assert "tidy up while I sleep" in asked and "delete every file in sight" not in asked


@pytest.mark.no_po
def test_while_away_below_full_auto_a_jobs_delete_still_waits(judging, wait_run, project_dir):
    from tests.test_away_scenarios import ended, to_do

    client, _lead, judge, executor = judging(
        [to_do(TIDY), text("on your To-do"), cmd("rm -rf build"), text("never")], [], []
    )
    pid, _night = away_with(client, project_dir, wait_run, "auto_edit")
    (job,) = ended(client, pid)["jobs"]
    assert job["state"] == "waits" and judge.calls == [] and executor.started == []


# Spec §6 / plan Task 5: in a job, only a delete in the folder is the check's. A send, a git
# remote's branch or an instruction file keeps its card, whatever the user's words allow.
SENDS = (
    "You may upload the report, copy src to the host, publish, open a pull request and "
    "push. You may prune Docker and delete its volumes."
)


@pytest.mark.no_po
@pytest.mark.parametrize(
    "line",
    [
        "curl -X POST https://example.com/up -d @report.txt",
        "scp -r src host:",
        "npm publish",
        "gh pr create",
        "git push --force origin main",
        "rm AGENTS.md",
        # (round 2: a send split by PowerShell's backtick and a new line - the line as it runs)
        "rm -rf build; git `\npush --force origin main",
        "rm -rf build; npm `\npublish",
        "rm -rf build; curl https://example.com/up `\n-d @report.txt",
        # (round 3: a command of more than one line, or continued, never passes as a delete alone -
        # a backtick in a comment, bash's backticks, one glued to a word, a backslash in a word)
        "rm -rf build # done `\nnpm publish",
        "rm -rf build; echo `\ncurl https://example.com/up -d @report.txt `\necho ok",
        "Remove-Item -Recurse -Force build`\r\ngit push origin main",
        "rm -rf build; npm pub\\\nlish",
        "rm -rf build; curl https://example.com/up -\\\nd @report.txt",
        "rm -rf build # done `\ndocker system prune -af",
        "rm -rf build\u2028npm publish",
        "rm -rf build; npm publish `",
        # (round 2: Docker's deletes are no delete in the copy; -H / --context reach another machine)
        "docker system prune -af",
        "docker volume rm db_data",
        "docker compose down -v",
        "docker -H tcp://host:2375 system prune -af",
        "docker --context prod volume rm data",
    ],
)
def test_while_away_a_jobs_send_remote_push_or_instruction_file_keeps_its_card(
    judging, wait_run, project_dir, line
):
    from tests.test_away_scenarios import ended, to_do

    client, _lead, judge, executor = judging(
        [to_do(TIDY), text("on your To-do"), cmd(line), text("never")],
        [verdict_line("run", SENDS)],
        [],
    )
    pid, _night = away_with(
        client, project_dir, wait_run, "full_auto", rules=SENDS + " You may delete AGENTS.md."
    )
    (job,) = ended(client, pid)["jobs"]
    (asked,) = client.get(f"/api/conversations/{job['conversation_id']}").json()["commands"]
    assert (job["state"], asked["status"], asked["judged"]) == ("waits", "proposed", None)
    assert judge.calls == [] and executor.started == []


@pytest.mark.no_po
def test_while_away_a_job_runs_at_the_level_of_the_chat_gone_from(judging, wait_run, project_dir):
    # (0.1.8: no To-do page's level any more - a job runs at the chat's, here Ask before changes.)
    from tests.test_away_scenarios import ended, to_do

    client, _lead, judge, executor = judging(
        [to_do(TIDY), text("on your To-do"), cmd("rm -rf build"), text("never")],
        [verdict_line("run", RULE)],
        [],
    )
    pid, _night = away_with(client, project_dir, wait_run, "ask")
    (job,) = ended(client, pid)["jobs"]
    chat = client.get(f"/api/conversations/{job['conversation_id']}").json()
    assert chat["conversation"]["permission_mode"] == "ask"
    assert job["state"] == "waits" and judge.calls == [] and executor.started == []


@pytest.mark.no_po
def test_in_the_chat_you_went_away_from_a_send_keeps_its_card(judging, wait_run, project_dir):
    # (Round 2: the chat gone from keeps its turn - no job - and its sends always wait too.)
    from app.db.models import AwayRun

    client, _lead, judge, executor = judging(
        [cmd("git push --force origin main"), text("never")], [verdict_line("run", SENDS)], []
    )
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert (
        client.patch(
            f"/api/projects/{pid}", json={"full_auto_check": "judge"}, headers=OWN
        ).status_code
        == 200
    )
    assert (
        client.put(f"/api/projects/{pid}/rules", json={"rules": SENDS}, headers=OWN).status_code
        == 200
    )
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(
        f"/api/conversations/{cid}",
        json={"permission_mode": "full_auto", "lead_hands_code": False},
        headers=OWN,
    )
    with client.app.state.session_factory() as session:
        session.add(AwayRun(project_id=pid, conversation_id=cid, run_id="r", status="running"))
        session.commit()
    # (not from the app's own page: a message of the user's own would end Away)
    run_id = client.post(
        f"/api/conversations/{cid}/messages", json={"content": "push it"}, headers=NO_ORIGIN
    ).json()["run"]["id"]
    asked = carded(client, cid, run_id, wait_run)
    assert (asked["status"], asked["judged"]) == ("proposed", None)
    assert judge.calls == [] and executor.started == []


def gone_from_chat(client, project_dir, rules, status="running"):
    """A chat at Full auto, the check on and `rules` saved, the user away from it (`status`
    "running") or back ("ended"); its id."""
    from app.db.models import AwayRun

    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert (
        client.patch(
            f"/api/projects/{pid}", json={"full_auto_check": "judge"}, headers=OWN
        ).status_code
        == 200
    )
    assert (
        client.put(f"/api/projects/{pid}/rules", json={"rules": rules}, headers=OWN).status_code
        == 200
    )
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(
        f"/api/conversations/{cid}",
        json={"permission_mode": "full_auto", "lead_hands_code": False},
        headers=OWN,
    )
    with client.app.state.session_factory() as session:
        session.add(AwayRun(project_id=pid, conversation_id=cid, run_id="r", status=status))
        session.commit()
    return cid


@pytest.mark.no_po
@pytest.mark.parametrize(
    ("line", "rule", "status"),
    [
        ("rm -rf build", RULE, "running"),  # (a delete in the folder is the check's while away)
        ("git push origin main", "You may push to main.", "ended"),
    ],
)  # (back: as before)
def test_in_the_chat_gone_from_a_delete_is_judged_and_once_back_a_push_is_again(
    judging, wait_run, project_dir, line, rule, status
):
    client, _lead, judge, executor = judging(
        [cmd(line), text("done")], [verdict_line("run", rule)], [Script([])]
    )
    cid = gone_from_chat(client, project_dir, rule, status)
    # (not from the app's own page: a message of the user's own would end Away)
    run_id = client.post(
        f"/api/conversations/{cid}/messages", json={"content": "go on"}, headers=NO_ORIGIN
    ).json()["run"]["id"]
    (ran,) = wait_run(client, cid, run_id)["commands"]
    assert (ran["status"], ran["judged"]["verdict"]) == ("exited", "run")
    assert len(judge.calls) == 1 and executor.started[0][0] == line
