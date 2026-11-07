"""K-agy-kota: what is left of agy's and Copilot's plans, read without a model turn - agy's
`/quota` (`num_turns: 0`) and Copilot headless's `account.getQuota` (measured 24 Oct 2026,
tasarim/specs/2026-10-23-cli-denetim-protokolleri-design.md §4) - through stand-ins of both,
shown in the shape Codex's reading has."""

import asyncio
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import app.limits
import app.model_native
from app.db.models import Provider
from app.limits import Limits, account, agy_quota, copilot_quota  # (the readers themselves:
from app.model_client import ModelUnavailable  # conftest stands both in once a test starts)
from tests.test_copilot_agent import copilot_native, start  # noqa: F401  (a fixture)

pytestmark = pytest.mark.anyio

FAKE_AGY = [sys.executable, str(Path(__file__).with_name("fake_agy_cli.py"))]
FAKE_COPILOT = [sys.executable, str(Path(__file__).with_name("fake_copilot_headless.py"))]
ORIGIN = "http://127.0.0.1:8790"
# A reset a day on from now: a window that has reset by the time it is read is stale
# (`_as_of`), which the real answer's date (31 Oct 2026) became.
RESETS = (datetime.now(UTC) + timedelta(days=1)).replace(microsecond=0)


def iso(when: datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


# As agy 1.4.7 answered `agy -p "/quota" --output-format json` (trimmed).
AGY_QUOTA = {
    "conversation_id": "", "status": "SUCCESS", "response": "Weekly limits ...", "num_turns": 0,
    "usage": {"input_tokens": 0, "output_tokens": 0},
    "command": {"name": "usage", "data": {"groups": [
        {"name": "Gemini Models", "buckets": [
            {"id": "gemini-weekly", "name": "Weekly Limit Remaining", "window": "weekly",
             "remaining_fraction": 0.9216, "reset_time": iso(RESETS)}]},
        {"name": "Claude and GPT models", "buckets": [
            {"id": "3p-weekly", "window": "weekly", "remaining_fraction": 1,
             "reset_time": iso(RESETS + timedelta(hours=6))}]}]}},
}
# As Copilot 1.0.91 answered `account.getQuota` (trimmed), with whose account it is beside
# it - which the real answer was not seen to carry, and which is never kept if it does.
COPILOT_QUOTA = {
    "login": "someone-on-github", "email": "someone@example.com",
    "quotaSnapshots": {
        "chat": {"isUnlimitedEntitlement": True, "remainingPercentage": 100},
        "completions": {"isUnlimitedEntitlement": True, "remainingPercentage": 100},
        "premium_interactions": {
            "remainingPercentage": 9.8, "isUnlimitedEntitlement": False, "usedRequests": 271,
            "entitlementRequests": 300, "resetDate": iso(RESETS + timedelta(days=1))},
    },
}
NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)


def plan(tmp_path, monkeypatch, variable, **more) -> Path:
    record = tmp_path / "record.json"
    given = tmp_path / "plan.json"
    given.write_text(json.dumps({"record": str(record), "script": [], **more}), encoding="utf-8")
    monkeypatch.setenv(variable, str(given))
    return record


# --- what each says, as it is shown -----------------------------------------------------------


def test_agys_groups_are_its_windows_each_a_week():
    shown = app.limits.of_agy(AGY_QUOTA, NOW)
    assert shown["read_at"] == NOW and shown["credits"] is None and shown["plan"] is None
    assert shown["windows"] == [
        {"name": "Gemini Models", "minutes": 10080, "used_percent": 7.84,
         "resets_at": RESETS, "stale": False},
        {"name": "Claude and GPT models", "minutes": 10080, "used_percent": 0,
         "resets_at": RESETS + timedelta(hours=6), "stale": False},
    ]
    assert "unknown" in app.limits.of_agy({"status": "SUCCESS"}, NOW)


def test_copilots_premium_requests_are_its_one_window_and_the_unlimited_are_passed_over():
    shown = app.limits.of_copilot(COPILOT_QUOTA, NOW)
    assert shown["windows"] == [
        {"name": "premium requests", "minutes": None, "used_percent": 90.2,
         "resets_at": RESETS + timedelta(days=1), "stale": False}]
    assert "someone" not in json.dumps(shown, default=str)
    unlimited = {"quotaSnapshots": {"premium_interactions": {
        "isUnlimitedEntitlement": True, "remainingPercentage": 100}}}
    assert "unknown" in app.limits.of_copilot(unlimited, NOW)


@pytest.mark.parametrize("given", [NOW, NOW + timedelta(minutes=2), NOW - timedelta(days=1)])
def test_a_copilot_reset_at_the_time_of_reading_or_before_is_not_known(given):
    # As 1.0.103 answered (24 Oct 2026): its resetDate was the moment of the call itself.
    told = json.loads(json.dumps(COPILOT_QUOTA))
    told["quotaSnapshots"]["premium_interactions"]["resetDate"] = (
        given.isoformat(timespec="milliseconds").replace("+00:00", "Z"))
    (window,) = app.limits.of_copilot(told, NOW)["windows"]
    assert window["resets_at"] is None and window["used_percent"] == 90.2
    assert not window["stale"]


# --- the readers, against stand-ins of the CLIs -----------------------------------------------


async def test_agy_is_asked_its_quota_in_a_home_of_koloni_s_without_the_users_set_up(
        tmp_path, monkeypatch):
    record = plan(tmp_path, monkeypatch, "FAKE_AGY_PLAN", quota=AGY_QUOTA)
    monkeypatch.setenv("GEMINI_API_KEY", "not for agy")
    monkeypatch.setenv("ANTIGRAVITY_HOME", "not for agy")
    homes = tmp_path / "agy-home"
    told = await agy_quota(None, homes, 20, launcher=FAKE_AGY)
    assert app.limits.of_agy(told, NOW)["windows"][0]["used_percent"] == 7.84
    seen = json.loads(record.read_text("utf-8"))
    # A list argv: "/quota" as it was written, never a path a shell made of it.
    assert seen["argv"] == ["-p", "/quota", "--output-format", "json"]
    home = Path(seen["env"]["USERPROFILE"])
    assert seen["env"]["HOME"] == str(home) and home.parent == homes
    assert home.name.startswith("agy-")  # (what `sweep_homes` clears after a crash)
    assert not any(name.upper().startswith(("GEMINI_", "ANTIGRAVITY_")) for name in seen["env"])
    assert not home.exists()


async def test_an_agy_that_fails_says_so(tmp_path, monkeypatch):
    plan(tmp_path, monkeypatch, "FAKE_AGY_PLAN", quota_exit=3, stderr="not signed in")
    with pytest.raises(ModelUnavailable, match="agy exited with code 3: not signed in"):
        await agy_quota(None, tmp_path / "homes", 20, launcher=FAKE_AGY)
    plan(tmp_path, monkeypatch, "FAKE_AGY_PLAN", quota_text="Weekly limits: fine\n")
    with pytest.raises(ModelUnavailable, match="could not be read"):
        await agy_quota(None, tmp_path / "homes", 20, launcher=FAKE_AGY)


async def test_copilot_is_asked_its_quota_after_a_ping_and_no_session_is_made(
        tmp_path, monkeypatch):
    record = plan(tmp_path, monkeypatch, "FAKE_CLI_PLAN", quota=COPILOT_QUOTA)
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "the user's own")
    told = await copilot_quota(None, "gho_provider", 20, launcher=FAKE_COPILOT)
    assert app.limits.of_copilot(told, NOW)["windows"][0]["used_percent"] == 90.2
    # Whose account it is never leaves the reader.
    assert "someone" not in json.dumps(told)
    seen = json.loads(record.read_text("utf-8"))
    assert seen["quota_asked"] == {} and "create" not in seen and "prompt" not in seen
    assert "--headless" in seen["argv"] and "--stdio" in seen["argv"]
    assert seen["env"]["COPILOT_GITHUB_TOKEN"] == "gho_provider"
    assert seen["home_was_empty"]


async def test_a_copilot_that_says_no_says_so_without_its_token(tmp_path, monkeypatch):
    plan(tmp_path, monkeypatch, "FAKE_CLI_PLAN", quota_error="bad token gho_provider")
    with pytest.raises(ModelUnavailable, match="would not say") as said:
        await copilot_quota(None, "gho_provider", 20, launcher=FAKE_COPILOT)
    assert "gho_provider" not in str(said.value)
    plan(tmp_path, monkeypatch, "FAKE_CLI_PLAN", handshake="gone")
    with pytest.raises(ModelUnavailable, match="ended without"):
        await copilot_quota(None, "gho_provider", 20, launcher=FAKE_COPILOT)


async def test_a_copilot_without_a_token_reads_its_quota_by_the_users_own_sign_in(
        tmp_path, monkeypatch):
    record = plan(tmp_path, monkeypatch, "FAKE_CLI_PLAN", quota=COPILOT_QUOTA)
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "the user's own")
    monkeypatch.setenv("GH_TOKEN", "ghp_the_users_own")
    told = await copilot_quota(None, None, 20, launcher=FAKE_COPILOT)
    assert app.limits.of_copilot(told, NOW)["windows"][0]["used_percent"] == 90.2
    seen = json.loads(record.read_text("utf-8"))
    # KOLONİ's empty home and no token: Copilot signs in by gh's login itself.
    assert sorted(seen["env"]) == ["COPILOT_HOME"] and seen["github_tokens"] == []
    assert seen["home_was_empty"]
    assert not any(one.startswith("--secret-env-vars") for one in seen["argv"])


# --- when they are read -----------------------------------------------------------------------


def stand_ins(monkeypatch, given: list) -> list:
    """agy's and Copilot's readers, answering from `given` in turn; each call is noted."""
    asked = []

    async def answer(kind, *args):
        asked.append(kind)
        told = given.pop(0)
        if isinstance(told, BaseException):
            raise told
        if isinstance(told, asyncio.Event):
            await told.wait()
            told = AGY_QUOTA if kind == "agy" else COPILOT_QUOTA
        return told

    monkeypatch.setattr(app.limits, "agy_quota", lambda *a: answer("agy", *a))
    monkeypatch.setattr(app.limits, "copilot_quota", lambda *a: answer("copilot", *a))
    return asked


AGY = Provider(id="a", name="agy", kind="agy_cli")
COPILOT = Provider(id="g", name="Copilot", kind="copilot_cli", api_key="gho_provider")


async def test_read_now_reads_agy_and_copilot(monkeypatch):
    asked = stand_ins(monkeypatch, [AGY_QUOTA, COPILOT_QUOTA])
    limits = Limits()
    agy, copilot = await limits.read(AGY), await limits.read(COPILOT)
    assert [w["used_percent"] for w in agy["windows"]] == [7.84, 0]
    assert copilot["windows"][0]["name"] == "premium requests"
    assert asked == ["agy", "copilot"]


async def test_a_failed_read_keeps_the_last_good_one_with_why(monkeypatch):
    stand_ins(monkeypatch, [AGY_QUOTA, TimeoutError(), ModelUnavailable("agy is away")])
    limits = Limits()
    good = await limits.read(AGY)
    late = await limits.read(AGY)
    assert late["failed"] == "agy did not answer within 15 seconds"
    assert (late["read_at"], late["windows"]) == (good["read_at"], good["windows"])
    away = await limits.read(AGY)
    assert away["failed"] == "agy is away" and away["windows"] == good["windows"]


async def test_looking_reads_in_the_background_at_most_once_in_ten_minutes(monkeypatch):
    held = asyncio.Event()
    asked = stand_ins(monkeypatch, [held, ModelUnavailable("offline"), AGY_QUOTA])
    limits = Limits()
    assert limits.last(AGY) == {"unknown": app.limits.NOT_READ}
    limits.refresh(AGY)
    limits.refresh(AGY)  # one is being read: no second
    await asyncio.sleep(0)
    assert asked == ["agy"] and limits.last(AGY) == {"unknown": app.limits.NOT_READ}
    held.set()
    await asyncio.sleep(0.05)
    assert limits.last(AGY)["windows"][0]["used_percent"] == 7.84
    limits.refresh(AGY)
    assert asked == ["agy"]  # read just now
    # Ten minutes on, it is read again; a failure is not tried again on every look.
    limits._tried[account(AGY)] -= app.limits.AUTO_EVERY + 1
    limits.refresh(AGY)
    await asyncio.sleep(0.05)
    assert limits.last(AGY)["failed"] == "offline" and asked == ["agy", "agy"]
    limits.refresh(AGY)
    assert asked == ["agy", "agy"]


async def test_a_reading_restored_from_before_a_restart_is_not_read_again_within_ten_minutes(
        monkeypatch):
    asked = stand_ins(monkeypatch, [AGY_QUOTA])
    limits = Limits()
    fresh = app.limits.of_agy(AGY_QUOTA, datetime.now(UTC) - timedelta(minutes=3))
    limits._keep(account(AGY), fresh)
    limits.refresh(AGY)
    assert asked == []


async def test_only_agy_and_a_signed_in_copilot_are_read_in_the_background(monkeypatch):
    asked = stand_ins(monkeypatch, [])
    limits = Limits()
    for one in (Provider(id="c", name="Codex", kind="codex_cli"),
                Provider(id="k", name="Claude Code", kind="claude_cli"),
                Provider(id="s", name="Copilot local", kind="copilot_cli",
                         base_url="http://127.0.0.1:8080/v1")):
        limits.refresh(one)
    await asyncio.sleep(0)
    assert asked == []
    on_server = Provider(id="s", name="Copilot local", kind="copilot_cli",
                         base_url="http://127.0.0.1:8080/v1")
    assert limits.last(on_server) == {"unknown": app.limits.NO_PLAN}
    assert await limits.read(on_server) == {"unknown": app.limits.NO_PLAN}


def test_the_plan_meters_look_starts_a_read_and_answers_at_once(make_client, monkeypatch):
    from tests.test_chat_flow import text

    started = time.monotonic()
    asked = stand_ins(monkeypatch, [AGY_QUOTA, COPILOT_QUOTA])
    client, _model = make_client([text("x")])
    client.headers["Origin"] = ORIGIN
    agy = client.post("/api/providers", json={"name": "agy", "kind": "agy_cli"}).json()["id"]
    copilot = client.post("/api/providers", json={
        "name": "Copilot", "kind": "copilot_cli", "api_key": "gho_provider"}).json()["id"]
    first = client.get(f"/api/providers/{agy}/limits").json()
    assert first["unknown"] == app.limits.NOT_READ
    deadline = time.monotonic() + 5
    while not (shown := client.get(f"/api/providers/{agy}/limits").json())["windows"]:
        assert time.monotonic() < deadline
        time.sleep(0.02)
    assert [w["name"] for w in shown["windows"]] == ["Gemini Models", "Claude and GPT models"]
    while not (shown := client.get(f"/api/providers/{copilot}/limits").json())["windows"]:
        assert time.monotonic() < deadline
        time.sleep(0.02)
    assert shown["windows"][0]["used_percent"] == 90.2
    assert "someone" not in json.dumps(shown) and "gho_provider" not in json.dumps(shown)
    # Looked at again and again, as the meter does every 5 seconds: nothing more is read.
    for one in (agy, copilot):
        client.get(f"/api/providers/{one}/limits")
    assert asked == ["agy", "copilot"] and time.monotonic() - started < 30


# --- 89l: said by Copilot's own headless client in a native run, no turn of its own ----------


def wired(make, **more):
    """A native Copilot keeping what its client says, as `Providers._build` wires one on
    GitHub's plan (the fixture's own is on a model server, and handed in ready-made)."""
    from functools import partial

    client, provider = make([{"say": "ok"}], **more)
    limits = client.app.state.providers.limits
    client.app.state.providers.named["Copilot"].on_limits = partial(
        limits.copilot_said, account(ON_GITHUB))
    return client, provider, limits


ON_GITHUB = Provider(id="g", name="Copilot", kind="copilot_cli")


def test_a_native_copilot_says_its_quota_and_no_other_copilot_is_started(
        copilot_native, wait_run, project_dir, tmp_path):  # noqa: F811
    from app.db.models import LimitReading

    starts = tmp_path / "starts.txt"
    client, provider, limits = wired(copilot_native, quota=COPILOT_QUOTA, starts=str(starts))
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    shown = limits.last(ON_GITHUB)
    assert shown["windows"][0]["used_percent"] == 90.2 and shown["read_at"]
    with limits._factory() as session:
        kept = session.get(LimitReading, json.dumps(account(ON_GITHUB))).reading
    # Whose account it is is kept nowhere: not in the reading, nor in the run's record.
    assert "someone" not in json.dumps(kept) + json.dumps(shown, default=str) + json.dumps(snap)
    # Only the run's own Copilot was started, and its background read is not due now. (Its
    # `--version`, asked before the run since K-cli-surface, is no Copilot of its own.)
    assert len([line for line in starts.read_text("utf-8").splitlines()
                if line != '["--version"]']) == 1
    limits.refresh(ON_GITHUB)
    assert not limits._reading


@pytest.mark.parametrize("refusal", [{"quota_error": "not on a plan"}, {"quota_hang": True}])
def test_a_native_copilot_that_will_not_say_its_quota_runs_all_the_same(
        copilot_native, wait_run, project_dir, monkeypatch, refusal):  # noqa: F811
    monkeypatch.setattr(app.model_native, "QUOTA_SECONDS", 0.5)  # (one that never answers)
    client, provider, limits = wired(copilot_native, **refusal)
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert "quota_asked" in copilot_native.record()
    assert limits.last(ON_GITHUB) == {"unknown": app.limits.NOT_READ}


def test_only_a_native_copilot_on_githubs_plan_keeps_what_its_client_says(settings):
    from app.providers import Providers

    providers = Providers(settings)
    native = providers._build(Provider(id="p1", name="x", kind="copilot_cli", mode="native"), None)
    assert native.on_limits is not None
    for more in ({"mode": "session"},
                 {"mode": "native", "base_url": "http://localhost:8080/v1"}):
        built = providers._build(Provider(id="p1", name="x", kind="copilot_cli", **more), None)
        assert built.on_limits is None


async def test_a_reading_a_native_run_kept_while_copilot_was_asked_is_not_marked_failed(
        monkeypatch):
    limits = Limits()

    async def meanwhile(*args):
        limits.copilot_said(account(COPILOT), COPILOT_QUOTA)  # a native run's, as it is asked
        raise ModelUnavailable("Copilot ended without saying what is left of its plan")

    monkeypatch.setattr(app.limits, "copilot_quota", meanwhile)
    shown = await limits.read(COPILOT)
    assert "failed" not in shown and shown["windows"][0]["used_percent"] == 90.2
