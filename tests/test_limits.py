"""Slice 25a beside its acceptance set: `codex app-server` asked through a stand-in, Claude
Code's own word on its limits kept from each way it runs, the classes of a failure, and
what an opener is told of who has room."""

import asyncio
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path

import httpx2
import pytest
from sqlalchemy.exc import OperationalError

import app.limits
from app.config import load_settings
from app.db.models import Provider
from app.db.session import make_engine, make_session_factory, upgrade_db
from app.limits import (
    Limits,
    account,
    another_account,
    app_server,
    classify,
    claude_turn,
    of_claude,
    of_codex,
)
from app.main import create_app
from app.model_cli import ClaudeCliClient, CodexCliClient
from app.model_client import ModelUnavailable, OwnStop, _describe
from app.model_native import ClaudeNativeClient
from app.model_session import ClaudeSessionClient, CopilotSessionClient, QoderSessionClient
from app.providers import Providers
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_chat_flow import text
from tests.test_claude_native import FAKE as FAKE_NATIVE
from tests.test_claude_native import start
from tests.test_limits_scenarios import ACCOUNT, ORIGIN, provider, told_by_codex
from tests.test_model_cli import FAKE as FAKE_STEP
from tests.test_model_cli import MESSAGES, alive
from tests.test_model_session import FAKE as FAKE_SESSION
from tests.test_model_session import run as run_session
from tests.test_spawn import call, role_id, step

pytestmark = pytest.mark.anyio

FAKE_CODEX = [sys.executable, str(Path(__file__).with_name("fake_codex_app_server.py"))]
RESETS = int(time.time()) + 3600
REJECTED = {"status": "rejected", "rateLimitType": "five_hour", "utilization": 1,
            "resetsAt": RESETS,
            "unifiedWindows": {"five_hour": {"utilization": 1, "resetsAt": RESETS},
                               "another_window": {"utilization": 0.4, "resetsAt": RESETS + 86400}}}
ALLOWED = {"status": "allowed", "rateLimitType": "five_hour", "utilization": 0.99,
           "resetsAt": RESETS,
           "unifiedWindows": {"five_hour": {"utilization": 0.99, "resetsAt": RESETS}}}


# --- codex app-server -----------------------------------------------------------------------


async def test_codex_is_asked_over_its_app_server_and_its_account_is_dropped(monkeypatch):
    monkeypatch.setenv("KOLONI_SECRET", "not for a CLI")
    monkeypatch.delenv("FAKE_APP_SERVER", raising=False)
    told = await app_server(None, 20, launcher=FAKE_CODEX)
    assert told["rateLimits"]["planType"] == "pro"
    # Notifications came in between and were passed over; the account id is not handed on.
    assert "accountId" not in told and ACCOUNT not in json.dumps(told)
    assert told["argv"] == ["app-server"] and told["sawKoloni"] == []
    shown = of_codex(told, datetime.now(UTC))
    assert shown["plan"] == "pro" and shown["windows"][0]["minutes"] == 10080
    assert shown["credits"] == {"balance": "49675.89", "has_credits": True, "unlimited": False}


@pytest.mark.skipif(sys.platform != "win32", reason="a .cmd shim is a Windows thing")
async def test_a_codex_that_is_a_cmd_file_is_started_through_it(tmp_path, monkeypatch):
    monkeypatch.delenv("FAKE_APP_SERVER", raising=False)
    shim = tmp_path / "codex.cmd"
    shim.write_text(f'@"{FAKE_CODEX[0]}" "{FAKE_CODEX[1]}" %*\r\n', encoding="utf-8")
    told = await app_server(str(shim), 20)
    assert told["rateLimits"]["primary"]["usedPercent"] == 7


async def test_a_codex_that_does_not_answer_is_ended_at_the_limit(monkeypatch, tmp_path):
    monkeypatch.setenv("FAKE_APP_SERVER", "hang")
    monkeypatch.setenv("FAKE_APP_SERVER_STARTED", str(tmp_path / "started"))
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        await app_server(None, 3, launcher=FAKE_CODEX)
    assert time.monotonic() - started < 15
    # Not only given up on: it is gone when this returns.
    (pid,) = (tmp_path / "started").read_text("utf-8").split()
    assert not alive(int(pid))


async def test_the_time_codex_has_starts_before_it_does(monkeypatch):
    def slow(self, workdir):
        time.sleep(1.5)
        return ["app-server"]

    monkeypatch.delenv("FAKE_APP_SERVER", raising=False)
    monkeypatch.setattr(app.limits._AppServer, "_arguments", slow)
    with pytest.raises(TimeoutError):
        await app_server(None, 0.5, launcher=FAKE_CODEX)


async def test_asked_twenty_times_at_once_codex_is_started_once(monkeypatch, tmp_path):
    monkeypatch.delenv("FAKE_APP_SERVER", raising=False)
    monkeypatch.setenv("FAKE_APP_SERVER_STARTED", str(tmp_path / "started"))

    async def stand_in(executable, timeout, home=None):
        return await app_server(executable, 20, launcher=FAKE_CODEX)

    monkeypatch.setattr(app.limits, "app_server", stand_in)
    limits, codex = Limits(), Provider(id="c", name="Codex", kind="codex_cli")
    told = await asyncio.gather(*(limits.read(codex) for _ in range(20)))
    assert [reading["plan"] for reading in told] == ["pro"] * 20
    assert len((tmp_path / "started").read_text("utf-8").split()) == 1
    # One after another it is asked each time: only a read in flight is waited for.
    await limits.read(codex)
    assert len((tmp_path / "started").read_text("utf-8").split()) == 2


async def test_a_read_that_fails_leaves_the_last_good_one_with_its_time(monkeypatch):
    given = [told_by_codex(RESETS), TimeoutError(), ModelUnavailable("it is away"),
             told_by_codex(RESETS, used=9)]

    async def stand_in(executable, timeout, home=None):
        told = given.pop(0)
        if isinstance(told, Exception):
            raise told
        return told

    monkeypatch.setattr(app.limits, "app_server", stand_in)
    limits, codex = Limits(), Provider(id="c", name="Codex", kind="codex_cli")
    good = await limits.read(codex)
    assert good["windows"][0]["used_percent"] == 7 and not good.get("failed")
    late = await limits.read(codex)
    assert late["failed"] == "Codex did not answer within 15 seconds"
    assert (late["read_at"], late["windows"], late["plan"]) == (
        good["read_at"], good["windows"], "pro")
    away = await limits.read(codex)
    assert away["failed"] == "it is away" and away["read_at"] == good["read_at"]
    again = await limits.read(codex)
    assert again["windows"][0]["used_percent"] == 9 and not again.get("failed")


@pytest.mark.parametrize("mode, said", [("refuse", "would not say"), ("gone", "ended without"),
                                        ("loud", "said too much")])
async def test_a_codex_that_says_no_or_goes_away_says_so(monkeypatch, mode, said):
    monkeypatch.setenv("FAKE_APP_SERVER", mode)
    with pytest.raises(ModelUnavailable, match=said):
        await app_server(None, 20, launcher=FAKE_CODEX)


async def test_a_codex_that_is_not_installed_is_not_started():
    # (How this machine is set up, not something Codex's side said.)
    with pytest.raises(OwnStop, match="was not found"):
        await app_server("no-such-codex-command", 5)


def test_only_what_codex_says_is_shown():
    now = datetime.now(UTC)
    both = told_by_codex(RESETS)
    both["rateLimits"]["secondary"] = {"usedPercent": 100, "windowDurationMins": 300,
                                       "resetsAt": RESETS}
    assert [w["minutes"] for w in of_codex(both, now)["windows"]] == [10080, 300]
    # A part it does not say stays unknown; nothing at all is no reading.
    bare = of_codex({"rateLimits": {"primary": {"usedPercent": "7"}, "planType": "plus"}}, now)
    assert bare["windows"] == [] and bare["credits"] is None and bare["plan"] == "plus"
    assert of_codex({"rateLimits": {}}, now)["unknown"]
    # A limit Codex itself calls reached leaves no room, whatever its windows say.
    reached = told_by_codex(RESETS, used=40)
    assert of_codex(reached, now)["reached"] is False
    reached["rateLimits"]["rateLimitReachedType"] = "primary"
    limits, codex = Limits(), Provider(id="c", name="Codex", kind="codex_cli", for_agents=True)
    limits._kept[account(codex)] = of_codex(reached, now)
    assert limits.room(None, [codex], None) == "No other provider is known to have room now."


def test_room_is_not_another_provider_on_the_same_account_nor_one_nobody_can_pick():
    def made(id, kind, **fields):
        return Provider(id=id, name=id, kind=kind, for_agents=True, **fields)

    opus, sonnet = made("Claude Opus", "claude_cli"), made("Claude Sonnet", "claude_cli")
    elsewhere = made("Claude elsewhere", "claude_cli", executable="C:/other/claude.cmd")
    held = made("Held", "codex_cli", only_listed=True, models=[], executable="held-codex")
    listed = made("Listed", "codex_cli", only_listed=True, models=[{"name": "gpt-5"}],
                  executable="listed-codex")
    limits, now = Limits(), datetime.now(UTC)
    limits.said(account(opus), ALLOWED)
    for other in (elsewhere, held, listed):
        limits._kept[account(other)] = of_codex(told_by_codex(RESETS, used=7), now)
    # What one says of its plan is what the other on the same sign-in has left too.
    assert limits.last(sonnet)["windows"] == limits.last(opus)["windows"]
    assert limits.last(sonnet)["windows"][0]["used_percent"] == 99
    said = limits.room(None, [opus, sonnet, elsewhere, held, listed], opus.id)
    assert '"Claude elsewhere" (' in said and '"Listed" (' in said
    assert "Claude Sonnet" not in said and "Claude Opus" not in said and "Held" not in said
    # With nobody else left, nobody is named.
    assert limits.room(None, [opus, sonnet, held], opus.id) == (
        "No other provider is known to have room now.")


def test_at_a_limit_another_account_of_the_same_cli_is_never_named_but_another_kind_is():
    # K-claude-hesap: a Claude Code provider at its limit is not replaced by another Claude Code
    # account; another kind is fine, and any other failure names them all as before.
    def made(id, kind, **fields):
        return Provider(id=id, name=id, kind=kind, for_agents=True, options={"sign_in": "koloni"},
                        **fields)

    work, home, codex = made("Work", "claude_cli"), made("Home", "claude_cli"), made("Cx", "codex_cli")
    local = Provider(id="Local", name="Local", kind="claude_cli", for_agents=True,
                     base_url="http://127.0.0.1:8080/v1")  # (the user's own model server)
    limits, now = Limits(), datetime.now(UTC)
    for other in (home, codex):
        limits._kept[account(other)] = of_codex(told_by_codex(RESETS, used=7), now)
    providers = [work, home, codex]
    at_limit_ = limits.room(None, providers, work.id, "rate_limited")
    assert '"Cx" (' in at_limit_ and "Home" not in at_limit_
    assert "Home" not in limits.room(None, providers, work.id, "credits_exhausted")
    for failure in (None, "signed_out", "other"):
        assert '"Home" (' in limits.room(None, providers, work.id, failure)
    assert another_account(work, home, "rate_limited") and not another_account(work, codex, "rate_limited")
    assert not another_account(work, local, "rate_limited")


# --- Claude Code's own word, from each way it runs -------------------------------------------


def test_claude_codes_windows_are_named_and_only_a_measured_one_has_a_length():
    shown = of_claude(REJECTED, datetime.now(UTC))
    assert shown["source"] == "its last run" and shown["plan"] is None
    assert [(w["name"], w["minutes"], w["used_percent"]) for w in shown["windows"]] == [
        ("five_hour", 300, 100), ("another_window", None, 40)]
    # Without windows by name, the one it speaks of.
    one = of_claude({"rateLimitType": "five_hour", "utilization": 0.99, "resetsAt": RESETS},
                    datetime.now(UTC))
    assert [(w["name"], w["minutes"], w["used_percent"]) for w in one["windows"]] == [
        ("five_hour", 300, 99)]
    assert of_claude({"status": "allowed"}, datetime.now(UTC))["unknown"]


@pytest.mark.parametrize("share, shown", [
    (0.996, 99), (0.9999, 99), (1, 100), (1.2, 120), (0.29, 29), (0.004, 0), (0, 0),
    (float("nan"), None), (float("inf"), None), ("0.5", None), (True, None),
])
def test_a_window_is_full_only_when_claude_code_says_so_and_what_is_no_number_is_none(
        share, shown):
    told = of_claude({"rateLimitType": "five_hour", "utilization": share, "resetsAt": RESETS},
                     datetime.now(UTC))
    assert told["windows"][0]["used_percent"] == shown


async def test_what_claude_code_says_of_its_limits_never_breaks_its_run(tmp_path):
    plan = tmp_path / "plan.json"
    odd = {**ALLOWED, "utilization": float("nan"), "resetsAt": float("nan"),
           "unifiedWindows": {"five_hour": {"utilization": float("nan"), "resetsAt": "soon"}}}
    plan.write_text(json.dumps({"record": str(tmp_path / "r.json"), "limits": odd}), "utf-8")
    limits, heard = Limits(), []

    def keeps_and_breaks(info):
        limits.said(("claude_cli", None), info)
        heard.append(info)
        raise RuntimeError("whoever keeps it broke")

    async def on_delta(_text):
        pass

    cli = ClaudeCliClient(timeout=20, launcher=FAKE_STEP, env={"FAKE_CLI_PLAN": str(plan)})
    cli.on_limits = keeps_and_breaks
    assert (await cli.stream_step(None, MESSAGES, [], on_delta)).content == "hello"
    assert len(heard) == 1
    assert limits.last(Provider(id="p", name="x", kind="claude_cli"))["unknown"]


async def test_a_step_of_claude_code_hands_on_its_limits_and_a_rejected_one_says_why(tmp_path):
    kept = []
    plan = tmp_path / "plan.json"

    def make(**fields):
        plan.write_text(json.dumps({"record": str(tmp_path / "r.json"), **fields}), "utf-8")
        cli = ClaudeCliClient(timeout=20, launcher=FAKE_STEP, env={"FAKE_CLI_PLAN": str(plan)})
        cli.on_limits = kept.append
        return cli

    async def on_delta(_text):
        pass

    await make(limits=ALLOWED).stream_step(None, MESSAGES, [], on_delta)
    assert kept == [ALLOWED]
    with pytest.raises(ModelUnavailable, match="reported an error") as failed:
        await make(limits=REJECTED, mode="reported_error").stream_step(
            None, MESSAGES, [], on_delta)
    assert kept[-1] == REJECTED
    assert classify(failed.value) == ("rate_limited", datetime.fromtimestamp(RESETS, UTC))
    # Without that event nothing is made of it: what its `result` holds is the text of
    # its answer ("Credit balance is too low" here), which can be the model's own words.
    with pytest.raises(ModelUnavailable, match="Credit balance is too low") as plain:
        await make(mode="reported_error").stream_step(None, MESSAGES, [], on_delta)
    assert classify(plain.value) == ("other", None)


async def test_read_now_runs_one_short_claude_code_turn_with_nothing_of_its_own(tmp_path, monkeypatch):
    plan, record = tmp_path / "plan.json", tmp_path / "r.json"
    monkeypatch.setenv("FAKE_CLI_PLAN", str(plan))
    plan.write_text(json.dumps({"record": str(record), "limits": ALLOWED}), "utf-8")
    # (The real `claude_turn`, imported above before conftest stood it in, on the stand-in CLI.)
    assert await claude_turn(None, 20, launcher=FAKE_STEP) == ALLOWED
    argv = json.loads(record.read_text("utf-8"))["argv"]
    assert argv[argv.index("--model") + 1] == "haiku" and argv[argv.index("--tools") + 1] == ""
    assert {"-p", "--strict-mcp-config", "--no-session-persistence"} <= set(argv)
    assert argv[argv.index("--setting-sources") + 1] == "" and "--json-schema" not in argv
    # A turn that names no limit is no reading.
    plan.write_text(json.dumps({"record": str(record)}), "utf-8")
    with pytest.raises(ModelUnavailable, match="without saying its limits"):
        await claude_turn(None, 20, launcher=FAKE_STEP)


async def test_a_session_of_claude_code_hands_on_its_limits(tmp_path):
    kept = []
    plan = tmp_path / "plan.json"

    def make(script):
        plan.write_text(json.dumps({"record": str(tmp_path / "r.json"), "script": script}),
                        encoding="utf-8")
        cli = ClaudeSessionClient(timeout=20, launcher=FAKE_SESSION,
                                  env={"FAKE_CLI_PLAN": str(plan)})
        cli.on_limits = kept.append
        return cli

    event = {"type": "rate_limit_event", "rate_limit_info": ALLOWED}
    _result, said, _calls = await run_session(make([{"emit": event}, {"say": "hello"}]))
    assert kept == [ALLOWED] and said == ["hello"]
    with pytest.raises(ModelUnavailable) as failed:
        await run_session(make([{"emit": {**event, "rate_limit_info": REJECTED}},
                                {"result_error": "You have hit your limit"}]))
    assert failed.value.failure == ("rate_limited", datetime.fromtimestamp(RESETS, UTC))


def test_only_claude_codes_clients_keep_what_they_say(settings):
    providers = Providers(settings)
    for kind, mode, built in [("claude_cli", "session", ClaudeSessionClient),
                              ("claude_cli", "step", ClaudeCliClient),
                              ("claude_cli", "native", ClaudeNativeClient),
                              ("qoder_cli", "session", QoderSessionClient),
                              ("codex_cli", "step", CodexCliClient)]:
        client = providers._build(Provider(id="p1", name="x", kind=kind, mode=mode), None)
        assert type(client) is built
        assert (client.on_limits is not None) == (kind == "claude_cli")
    # Natively it speaks in a discussion as a session of its own: that one keeps it too.
    native = providers._build(Provider(id="p1", name="x", kind="claude_cli", mode="native"), None)
    assert native.talker().on_limits == native.on_limits
    client = providers._build(Provider(id="p1", name="x", kind="claude_cli"), None)
    client.on_limits(ALLOWED)
    shown = providers.limits.last(Provider(id="p1", name="x", kind="claude_cli"))
    assert shown["windows"][0]["used_percent"] == 99 and shown["read_at"]


@pytest.fixture
def native_claude(settings_env, tmp_path):
    """An app whose provider "Claude" is the stand-in for Claude Code working natively,
    keeping what it says of its limits as a provider built here would."""
    opened = []

    def make(script):
        plan = tmp_path / "plan.json"
        plan.write_text(json.dumps({"record": str(tmp_path / "r.json"), "script": script}),
                        encoding="utf-8")
        cli = ClaudeNativeClient(launcher=FAKE_NATIVE, timeout=30,
                                 env={"FAKE_CLI_PLAN": str(plan)})
        made = create_app(load_settings(settings_env), model=ScriptedModel([]),
                          clients={"Claude": cli})
        client = TestClient(made, base_url="http://127.0.0.1:8790")
        client.__enter__()
        opened.append(client)
        client.headers["Origin"] = ORIGIN
        claude = client.post("/api/providers", json={
            "name": "Claude", "kind": "claude_cli", "mode": "native"}).json()
        cli.on_limits = partial(made.state.providers.limits.said, ("claude_cli", None))
        return client, claude

    yield make
    for client in opened:
        client.__exit__(None, None, None)


def test_claude_code_turned_away_at_its_limit_is_on_its_agent_and_on_the_usage_page(
        native_claude, wait_run, project_dir):
    event = {"type": "rate_limit_event", "rate_limit_info": REJECTED}
    client, claude = native_claude([{"emit": event}, {"fail": "You have hit your limit"}])
    assert client.get(f"/api/providers/{claude['id']}/limits").json()["unknown"].startswith(
        "not run yet")
    cid, run_id = start(client, project_dir, claude, "full_auto")
    snap = wait_run(client, cid, run_id, timeout=30)
    (lead,) = snap["agents"]
    assert (lead["status"], lead["failure"]) == ("failed", "rate_limited")
    assert lead["failure_resets_at"].startswith(
        time.strftime("%Y-%m-%dT%H:%M", time.gmtime(RESETS)))
    shown = client.get(f"/api/providers/{claude['id']}/limits").json()
    assert shown["source"] == "its last run" and shown["unknown"] is None
    assert [(w["name"], w["minutes"], w["used_percent"], w["stale"]) for w in shown["windows"]] == [
        ("five_hour", 300, 100, False), ("another_window", None, 40, False)]


def test_natively_too_the_text_of_claude_codes_result_classes_nothing(
        native_claude, wait_run, project_dir):
    event = {"type": "rate_limit_event", "rate_limit_info": ALLOWED}
    client, claude = native_claude([{"emit": event}, {"fail": "Credit balance is too low"}])
    cid, run_id = start(client, project_dir, claude, "full_auto")
    (lead,) = wait_run(client, cid, run_id, timeout=30)["agents"]
    assert (lead["status"], lead["failure"]) == ("failed", "other")
    assert "Credit balance is too low" in lead["error"]


# Claude Code's own word for why a message failed: the Agent SDK's assistant `error`
# (documented, not measured). Not its text: a field the model does not write.
BILLING = {"type": "assistant", "message": {"content": []}, "error": "billing_error"}


def test_natively_claude_codes_own_word_that_it_is_out_of_credit_is_taken(
        native_claude, wait_run, project_dir):
    event = {"type": "rate_limit_event", "rate_limit_info": ALLOWED}
    client, claude = native_claude([{"emit": BILLING}, {"emit": event},
                                    {"fail": "Credit balance is too low"}])
    cid, run_id = start(client, project_dir, claude, "full_auto")
    (lead,) = wait_run(client, cid, run_id, timeout=30)["agents"]
    assert (lead["status"], lead["failure"]) == ("failed", "credits_exhausted")


async def test_a_step_and_a_session_of_claude_code_take_its_own_word_for_why_it_failed(tmp_path):
    plan = tmp_path / "plan.json"

    async def on_delta(_text):
        pass

    for said, failure in [("billing_error", "credits_exhausted"), ("rate_limit", "rate_limited"),
                          ("server_error", "other")]:
        plan.write_text(json.dumps({"record": str(tmp_path / "r.json"), "mode": "reported_error",
                                    "assistant_error": said}), "utf-8")
        step = ClaudeCliClient(timeout=20, launcher=FAKE_STEP, env={"FAKE_CLI_PLAN": str(plan)})
        with pytest.raises(ModelUnavailable) as failed:
            await step.stream_step(None, MESSAGES, [], on_delta)
        assert classify(failed.value)[0] == failure
        plan.write_text(json.dumps({"record": str(tmp_path / "r.json"), "script": [
            {"emit": {**BILLING, "error": said}}, {"result_error": "Credit balance is too low"}]}),
            encoding="utf-8")
        session = ClaudeSessionClient(timeout=20, launcher=FAKE_SESSION,
                                      env={"FAKE_CLI_PLAN": str(plan)})
        with pytest.raises(ModelUnavailable) as failed:
            await run_session(session)
        assert classify(failed.value)[0] == failure
    # Out of credit is said before the limit event: the limit's "allowed" does not unsay it.
    plan.write_text(json.dumps({"record": str(tmp_path / "r.json"), "script": [
        {"emit": BILLING}, {"emit": {"type": "rate_limit_event", "rate_limit_info": ALLOWED}},
        {"result_error": "x"}]}), encoding="utf-8")
    with pytest.raises(ModelUnavailable) as failed:
        await run_session(ClaudeSessionClient(timeout=20, launcher=FAKE_SESSION,
                                              env={"FAKE_CLI_PLAN": str(plan)}))
    assert failed.value.failure == ("credits_exhausted", None)


def test_claude_codes_window_of_its_extra_usage_is_not_shown_as_its_plans():
    """B-61: "The seven_day_overage_included window 100% left" on the Models card."""
    limits, claude = Limits(), Provider(id="p", name="Claude", kind="claude_cli")
    limits.said(account(claude), {"unifiedWindows": {
        "five_hour": {"utilization": 0.4, "resetsAt": RESETS},
        "seven_day_overage_included": {"utilization": 0, "resetsAt": RESETS}}})
    limits.said(account(claude), {"rateLimitType": "seven_day_overage_included",
                                  "utilization": 0, "resetsAt": RESETS})
    assert [w["name"] for w in limits.last(claude)["windows"]] == ["five_hour"]


def test_a_window_of_claude_code_that_has_reset_since_is_stale():
    limits, claude = Limits(), Provider(id="p", name="Claude", kind="claude_cli")
    past = int(time.time()) - 5
    limits.said(account(claude),
                {"rateLimitType": "five_hour", "utilization": 0.99, "resetsAt": past})
    (window,) = limits.last(claude)["windows"]
    assert window["stale"] is True and window["used_percent"] is None


async def test_a_kept_reading_is_not_unsaid_after_a_restart(tmp_path, monkeypatch):
    # Memory is empty after a restart: what was kept is what a run that names no limit, or
    # a check that fails, is set beside - not something that is overwritten.
    upgrade_db(tmp_path / "x.db")
    factory = make_session_factory(make_engine(tmp_path / "x.db"))
    claude = Provider(id="p", name="Claude", kind="claude_cli")
    codex = Provider(id="c", name="Codex", kind="codex_cli")
    before = Limits(factory)
    before.said(account(claude), REJECTED)
    given = [told_by_codex(RESETS), ModelUnavailable("it is away")]

    async def stand_in(executable, timeout, home=None):
        told = given.pop(0)
        if isinstance(told, Exception):
            raise told
        return told

    monkeypatch.setattr(app.limits, "app_server", stand_in)
    good = await before.read(codex)

    after = Limits(factory)
    after.said(account(claude), {"status": "allowed"})  # a run that named no limit
    kept = after.last(claude)
    assert [w["used_percent"] for w in kept["windows"]] == [100, 40]
    assert kept["windows"][0]["resets_at"] == datetime.fromtimestamp(RESETS, UTC)
    failed = await after.read(codex)
    assert failed["failed"] == "it is away" and failed["read_at"] == good["read_at"]
    assert failed["windows"] == good["windows"] and failed["plan"] == "pro"
    # Why it failed is not kept: a third start shows the reading as it was read.
    assert "failed" not in Limits(factory).last(codex)


def kept_in(tmp_path):
    upgrade_db(tmp_path / "x.db")
    return make_session_factory(make_engine(tmp_path / "x.db"))


async def test_a_limit_codex_said_was_reached_is_not_reached_once_its_window_has_reset(
        tmp_path, monkeypatch):
    factory = kept_in(tmp_path)
    codex = Provider(id="c", name="Codex", kind="codex_cli")
    given = []

    async def stand_in(executable, timeout, home=None):
        return given.pop(0)

    monkeypatch.setattr(app.limits, "app_server", stand_in)
    for resets, reached in ((RESETS, True), (int(time.time()) - 5, False)):
        told = told_by_codex(resets)
        told["rateLimits"]["rateLimitReachedType"] = "primary"
        given.append(told)
        await Limits(factory).read(codex)
        # After a restart too: what was read is kept, as it stands now.
        assert Limits(factory).last(codex)["reached"] is reached


def test_a_reading_kept_meanwhile_is_not_replaced_by_an_older_one_read_from_the_database(
        tmp_path):
    factory = kept_in(tmp_path)
    claude = Provider(id="p", name="Claude", kind="claude_cli")
    Limits(factory).said(account(claude), REJECTED)  # the older one, kept before a restart
    limits, ran = Limits(), []

    def racing():
        session = factory()
        real = session.get

        def get(*args, **kwargs):
            row = real(*args, **kwargs)
            if not ran:  # a run keeps its limits while the page's reading is on its way
                ran.append(limits._kept.setdefault(
                    account(claude), of_claude(ALLOWED, datetime.now(UTC))))
            return row

        session.get = get
        return session

    limits._factory = racing
    assert [w["used_percent"] for w in limits.last(claude)["windows"]] == [99]


def test_an_account_with_nothing_kept_is_looked_for_once(tmp_path):
    factory, opened = kept_in(tmp_path), []
    limits = Limits(lambda: opened.append(1) or factory())
    local = Provider(id="l", name="Local", kind="openai_compat")
    for _ in range(3):
        assert limits.last(local) == {"unknown": app.limits.NO_PLAN}
    assert len(opened) == 1


async def test_a_reading_that_cannot_be_saved_is_kept_in_memory_and_said_in_the_log(
        tmp_path, monkeypatch, caplog):
    factory = kept_in(tmp_path)

    def broken():
        session = factory()
        session.commit = lambda: (_ for _ in ()).throw(OperationalError("x", {}, Exception()))
        return session

    async def stand_in(executable, timeout, home=None):
        return told_by_codex(RESETS)

    monkeypatch.setattr(app.limits, "app_server", stand_in)
    limits = Limits(broken)
    claude = Provider(id="p", name="Claude", kind="claude_cli")
    codex = Provider(id="c", name="Codex", kind="codex_cli", executable="C:/secret/codex.exe")
    limits.said(account(claude), ALLOWED)
    assert limits.last(claude)["windows"][0]["used_percent"] == 99
    # "Check now" answers what was read, not an error.
    assert (await limits.read(codex))["plan"] == "pro"
    said = [r.getMessage() for r in caplog.records if r.name == "app.limits"]
    assert said == [f"the last limits reading of a {kind} could not be saved: OperationalError"
                    for kind in ("claude_cli", "codex_cli")]
    assert "secret" not in caplog.text


def test_an_unknown_provider_has_no_limits(make_client):
    client, _model = make_client([text("x")])
    assert client.get("/api/providers/nope/limits").status_code == 404


# --- why it failed ---------------------------------------------------------------------------


@pytest.mark.parametrize("said, failure", [
    ("model server returned 429: slow down", "rate_limited"),
    ("Codex reported an error: You've hit your usage limit. Try again later.", "rate_limited"),
    ("model server returned 429: You exceeded your current quota", "credits_exhausted"),
    ("Codex reported an error: Credit balance is too low", "credits_exhausted"),
    # (Before B-88 a crash: now what it says, since another provider helps there.)
    ("Codex exited with code 3: not signed in", "signed_out"),
    ("Claude Code ended without finishing (exit code 1)", "cli_crashed"),
    ("agy ended, exit code not known: it was gone", "cli_crashed"),
    ("Codex ended without an answer", "empty_output"),
    ("model server returned 500: boom", "other"),
    ("Codex did not answer within 900 seconds", "other"),
    ("model server returned 4290: no", "other"),
    # Only where the provider layer puts the status, and only what its own line begins
    # with: a model's words, a refusal or a word further in make nothing of it.
    ("Claude Code reported an error: I can't help with bypassing a rate limit", "other"),
    ("Claude Code reported an error: unexpected rate_limit_event in the stream", "other"),
    ("model server returned 500: upstream returned 429", "other"),
    ("model server reported an error: the tool said your credit balance is too low", "other"),
    ("Codex reported an error: the command exited with code 1", "other"),
    ("the model declined to answer (rate limit)", "other"),
    ("5-hour limit reached ∙ resets 3pm", "other"),
    ("Claude Code exited with code 1: 5-hour limit reached ∙ resets 3pm", "rate_limited"),
    ("Codex reported an error: usage limit reached, try again later", "rate_limited"),
    ("Codex exited with code 1: You've hit your usage limit.", "rate_limited"),
    # (Qoder's, in a live run: B-88.)
    ("Qoder exited with code 1: You've reached your credit usage limit", "rate_limited"),
    ("model server returned 429", "rate_limited"),
    # Not signed in, or a key refused: another provider helps, as with a limit.
    ("model server returned 401: Incorrect API key provided", "signed_out"),
    ("Claude Code exited with code 1: Invalid API key · Please run /login", "signed_out"),
    ("Codex reported an error: Not logged in", "signed_out"),
    ("Claude Code reported an error: the page says you are not signed in to GitHub", "other"),
    ("model server reported an error: Rate limit exceeded", "rate_limited"),
    ("model server returned 400: Your credit balance is too low to access the API",
     "credits_exhausted"),
    # Alibaba's Token Plan used up, and its plain throttle: a limit both, no reset said.
    ("model server returned 429: Your token-plan quota has been exhausted.", "rate_limited"),
    ('model server returned 429: {"error": {"code": "insufficient_quota"}}', "rate_limited"),
    ("model server returned 429: Requests rate limit exceeded", "rate_limited"),
])
def test_a_failure_is_classed_from_the_providers_own_words(said, failure):
    assert classify(ModelUnavailable(said)) == (failure, None)
    assert failure in app.limits.FAILURES


@pytest.mark.parametrize("status, limited", [
    ("allowed", False), ("allowed_warning", False), (None, False), (7, False),
    ("rejected", True), ("blocked", True),
])
async def test_claude_code_at_its_limit_is_told_by_its_event_only_when_its_run_fails(
        tmp_path, status, limited):
    plan, info = tmp_path / "plan.json", {**REJECTED, "status": status}

    async def on_delta(_text):
        pass

    def make(**fields):
        plan.write_text(json.dumps({"record": str(tmp_path / "r.json"), "limits": info,
                                    **fields}), "utf-8")
        return ClaudeCliClient(timeout=20, launcher=FAKE_STEP, env={"FAKE_CLI_PLAN": str(plan)})

    # A run that ends well is not a failure, whatever the event said.
    assert (await make().stream_step(None, MESSAGES, [], on_delta)).content == "hello"
    with pytest.raises(ModelUnavailable) as failed:
        await make(mode="reported_error").stream_step(None, MESSAGES, [], on_delta)
    # Its event is all that classes it: the text of its `result` never does.
    assert classify(failed.value) == (
        ("rate_limited", datetime.fromtimestamp(RESETS, UTC)) if limited else ("other", None))


async def test_what_a_cli_says_in_its_result_is_classed_only_where_it_is_its_own_error_line(
        tmp_path):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"record": str(tmp_path / "r.json"), "script": [
        {"result_error": "5-hour limit reached ∙ resets 3pm"}]}), encoding="utf-8")
    for built, failure in [(ClaudeSessionClient, "other"), (QoderSessionClient, "other")]:
        with pytest.raises(ModelUnavailable, match="5-hour limit reached") as failed:
            await run_session(built(timeout=20, launcher=FAKE_SESSION,
                                    env={"FAKE_CLI_PLAN": str(plan)}))
        assert classify(failed.value) == (failure, None)
    # Copilot's failed result is made from its own `session.error`: its words count.
    assert CopilotSessionClient.result_is_its_error and not ClaudeSessionClient.result_is_its_error


# --- what the opener is told -----------------------------------------------------------------


def failing_coder(make_client, project_dir, error, monkeypatch=None, codex_used=None):
    """Two turns: the lead alone, which ends well on Local; then a Coder on "Flaky", whose
    model fails. Local and (with `codex_used`) a Codex that was read are in the team guide."""
    client, _model = make_client({
        "Lead": [text("hello"),
                 step(call("spawn_agent", {"role": "Coder", "task": "do it"}, "s")),
                 text("done")],
        "Coder": [error],
    })
    client.headers["Origin"] = ORIGIN
    local = next(p for p in client.get("/api/providers").json() if p["name"] == "Local")
    assert client.patch(f"/api/providers/{local['id']}",
                        json={"for_agents": True}).status_code == 200
    flaky = provider(client, "openai_compat", "Flaky")
    assert client.patch(f"/api/roles/{role_id(client, 'Coder')}",
                        json={"provider_id": flaky}).status_code == 200
    if codex_used is not None:
        async def answers(executable, timeout, home=None):
            return told_by_codex(RESETS, used=codex_used)

        monkeypatch.setattr(app.limits, "app_server", answers)
        codex = provider(client, "codex_cli", "Codex")
        assert client.patch(f"/api/providers/{codex}", json={"for_agents": True}).status_code == 200
        assert client.post(f"/api/providers/{codex}/limits/check").json()["plan"] == "pro"

        async def never(executable, timeout, home=None):
            raise AssertionError("Codex is not asked when an agent fails")

        monkeypatch.setattr(app.limits, "app_server", never)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "full_auto", "spawn_approval": "never"}).status_code == 200
    return client, cid


def turn(client, wait_run, cid):
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()[
        "run"]["id"]
    return wait_run(client, cid, run_id)


def test_the_opener_is_told_who_has_room_and_why(make_client, wait_run, project_dir,
                                                 monkeypatch):
    limited = ModelUnavailable("Claude Code reported an error: You have hit your limit")
    limited.failure = ("rate_limited", datetime(2026, 10, 13, 14, 0, tzinfo=UTC))
    client, cid = failing_coder(make_client, project_dir, limited, monkeypatch, codex_used=7)
    assert turn(client, wait_run, cid)["runs"][-1]["status"] == "completed"
    snap = turn(client, wait_run, cid)
    coder = next(a for a in snap["agents"] if a["name"] == "Coder")
    assert (coder["failure"], coder["failure_resets_at"]) == (
        "rate_limited", "2026-10-13T14:00:00Z")
    (spawned,) = [t for t in snap["tool_calls"] if t["name"] == "spawn_agent"]
    said = spawned["result"]
    assert "Why it failed: rate_limited, resets 2026-10-13 14:00 UTC." in said
    # Each with why: one by its last run, one by a limit that was read - and when.
    assert '"Local" (its limit is not known; its last run ended well)' in said
    assert '"Codex" (7% of its 10080-minute window used; read ' in said
    assert "Flaky" not in said.split("Why it failed")[1]
    assert said.rstrip().endswith("open a new agent on it.")
    # Advice only: no agent was opened for it, on any provider.
    assert [a["name"] for a in snap["agents"] if a["run_id"] == snap["runs"][-1]["id"]] == [
        "Lead", "Coder"]


def test_a_provider_whose_limit_is_full_or_that_never_ran_has_no_room(
        make_client, wait_run, project_dir, monkeypatch):
    client, cid = failing_coder(
        make_client, project_dir, ModelUnavailable("model server returned 500: boom"),
        monkeypatch, codex_used=100)
    # No turn before it: nothing has ended well on Local.
    client.app.state.providers.override.by_agent["Lead"].pop(0)
    snap = turn(client, wait_run, cid)
    (spawned,) = [t for t in snap["tool_calls"] if t["name"] == "spawn_agent"]
    assert spawned["result"].endswith(
        "Why it failed: other. No other provider is known to have room now.")


@pytest.mark.parametrize("error, failure", [
    # KOLONİ's own stop, or how this machine is set up: no class, and no advice.
    (OwnStop("Claude Code started with tools of its own (Bash); the session was stopped"),
     None),
    (OwnStop("Codex's config.toml could not be read, so its MCP servers cannot be "
             "switched off"), None),
    # What the provider's side did, though nobody can say what: `other`, with advice.
    (ModelUnavailable("Codex did not answer within 900 seconds"), "other"),
    (ModelUnavailable("Codex sent an answer that is not the agreed JSON object"), "other"),
])
def test_only_what_the_providers_side_did_is_a_failure_of_its_own_with_advice(
        make_client, wait_run, project_dir, error, failure):
    client, cid = failing_coder(make_client, project_dir, error)
    turn(client, wait_run, cid)
    snap = turn(client, wait_run, cid)
    coder = next(a for a in snap["agents"] if a["name"] == "Coder")
    assert (coder["status"], coder["failure"]) == ("failed", failure)
    (spawned,) = [t for t in snap["tool_calls"] if t["name"] == "spawn_agent"]
    assert str(error) in spawned["result"]
    assert ("Why it failed: other. These providers have room now" in spawned["result"]) == (
        failure is not None)
    assert ("room" in spawned["result"]) == (failure is not None)


def test_a_lead_whose_model_fails_has_its_class_and_one_that_ends_well_has_none(
        make_client, wait_run, project_dir):
    client, _model = make_client([
        text("fine"), ModelUnavailable("model server returned 429: rate limit")])
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert [a["failure"] for a in turn(client, wait_run, cid)["agents"]] == [None]
    assert [a["failure"] for a in turn(client, wait_run, cid)["agents"]] == [None, "rate_limited"]


def test_a_rate_limit_without_a_time_takes_it_from_a_full_window_last_read():
    limits, codex = Limits(), Provider(id="c", name="Codex", kind="codex_cli")
    exc = ModelUnavailable("Codex reported an error: You've hit your usage limit")
    assert limits.why(codex, exc) == ("rate_limited", None)
    now = datetime.now(UTC)
    limits._kept[account(codex)] = of_codex(told_by_codex(RESETS, used=100), now)
    assert limits.why(codex, exc) == ("rate_limited", datetime.fromtimestamp(RESETS, UTC))
    limits._kept[account(codex)] = of_codex(told_by_codex(RESETS, used=40), now)
    assert limits.why(codex, exc) == ("rate_limited", None)
    assert now - timedelta(seconds=1) < limits.last(codex)["read_at"]


def used_up_by(body: dict) -> ModelUnavailable:
    """A 429 as `_describe` words it, from a body as the server sends it."""
    response = httpx2.Response(429, json=body, request=httpx2.Request("POST", "http://x/v1"))
    return ModelUnavailable(_describe(httpx2.HTTPStatusError("429", request=response.request,
                                                             response=response)))


def test_a_plan_keys_used_up_quota_is_kept_as_seen_and_a_throttle_or_a_paid_key_is_not(
        tmp_path):
    factory = kept_in(tmp_path)
    plan = Provider(id="a", name="Alibaba", kind="openai_compat", plan=True,
                    base_url="https://token-plan.ap-southeast-1.maas.aliyuncs.com/v1")
    paid = Provider(id="b", name="Paid", kind="openai_compat", plan=False,
                    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
    limits = Limits(factory)
    throttle = ModelUnavailable("model server returned 429: Requests rate limit exceeded")
    assert limits.why(plan, throttle) == ("rate_limited", None)
    assert "used_up" not in limits.last(plan)
    # Its words in `message` or only its code: which the 429 carries is not measured.
    for body in ({"error": {"code": "insufficient_quota",
                            "message": "Your token-plan quota has been exhausted."}},
                 {"error": {"code": "insufficient_quota"}},
                 {"code": "insufficient_quota", "message": "quota gone"}):
        before = datetime.now(UTC)
        assert limits.why(plan, used_up_by(body)) == ("rate_limited", None)
        seen = limits.last(plan)
        assert seen["used_up"] is True and seen["read_at"] >= before and seen["windows"] == []
        assert limits.why(paid, used_up_by(body)) == ("rate_limited", None)
        assert "used_up" not in limits.last(paid)
    # After a restart too: when it was seen is kept, in UTC.
    kept = Limits(factory).last(plan)
    assert kept["used_up"] is True and kept["read_at"] == seen["read_at"]


def test_a_plan_key_whose_quota_a_turn_found_used_up_says_so_in_its_limits(
        make_client, wait_run, project_dir):
    client, _model = make_client([used_up_by({"error": {"code": "insufficient_quota"}})])
    client.headers["Origin"] = ORIGIN
    (key,) = [p["id"] for p in client.get("/api/providers").json()]
    assert client.patch(f"/api/providers/{key}", json={"plan": True}).status_code == 200
    assert client.get(f"/api/providers/{key}/limits").json()["used_up"] is None
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert [a["failure"] for a in turn(client, wait_run, cid)["agents"]] == ["rate_limited"]
    said = client.get(f"/api/providers/{key}/limits").json()
    assert said["used_up"] is True and said["read_at"] and said["windows"] == []


SOON = datetime(2026, 10, 26, 15, 0, tzinfo=UTC)


def reading(minutes, used=50.0, resets=SOON):
    return {"windows": [{"name": None, "minutes": minutes, "used_percent": used, "resets_at": resets,
                         "stale": False}]}


@pytest.mark.parametrize("failure, error, resets, read, said", [
    # The provider's last reading first: the window that resets when the failure does, or is full.
    ("rate_limited", "x", SOON, reading(300), "short"),
    ("rate_limited", "x", SOON.replace(tzinfo=None), reading(10080), "long"),
    ("rate_limited", "x", None, reading(10080, used=100), "long"),
    # Out of credits is long, whatever window is full; a reset a day away is long, whatever the reading says.
    ("credits_exhausted", "x", None, reading(300, used=100), "long"),
    ("rate_limited", "x", datetime.now(UTC) + timedelta(days=2), reading(300), "long"),
    # Codex says "usage limit" of its 5-hour window too.
    ("rate_limited", "Codex reported an error: You've hit your usage limit", None, {}, "short"),
    ("rate_limited", "Codex reported an error: weekly limit", SOON, reading(300), "short"),
    # Else the provider's own words.
    ("rate_limited", "Qoder exited with code 1: You've reached your credit usage limit", None, {}, "long"),
    ("rate_limited", "Codex reported an error: daily limit reached", None, {}, "long"),
    ("rate_limited", "model server returned 429: quota exceeded", None, {}, "long"),
    ("rate_limited", "model server returned 429: insufficient_quota", None, {}, "long"),
    ("credits_exhausted", "model server returned 402: pay", None, {}, "long"),
    ("rate_limited", "model server returned 429: too many requests", None, {}, "short"),
    ("rate_limited", "Claude Code reported an error: rate limit reached", None, {}, "short"),
    ("rate_limited", "it said: the weekly limit", None, {}, None),  # (words further in: a model's)
    ("signed_out", "model server returned 401: no", None, {}, "sign_in"),
    ("other", "model server returned 429: weekly", None, {}, None),
])
def test_a_failure_is_in_a_long_or_short_window_or_needs_a_sign_in(failure, error, resets, read, said):
    assert app.limits.window(failure, error, resets, read) == said


def test_a_limit_whose_reset_is_a_day_or_more_away_is_a_long_window_whatever_its_words():
    later = datetime.now(UTC) + timedelta(days=2)
    assert app.limits.window("rate_limited", "model server returned 429: slow down", later, {}) == "long"


def test_codexs_plan_is_read_in_a_providers_own_folder(client, monkeypatch):
    # K-codex-ev: its app-server is started with the provider's own CODEX_HOME.
    asked = []

    async def stand_in(executable, timeout, home=None):
        asked.append(home)
        return {"rateLimits": {"primary": {"usedPercent": 10, "windowDurationMins": 300}}}

    monkeypatch.setattr(app.limits, "app_server", stand_in)
    made = client.post("/api/providers", headers={"Origin": "http://127.0.0.1:8790"}, json={
        "name": "Codex work", "kind": "codex_cli", "options": {"sign_in": "koloni"}}).json()
    client.post(f"/api/providers/{made['id']}/limits/check",
                headers={"Origin": "http://127.0.0.1:8790"})
    assert asked == [client.app.state.settings.runtime_root / "cli-homes" / made["id"]]
