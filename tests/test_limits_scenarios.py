"""Slice 25a's acceptance set: how much of a CLI plan is left, and why an agent failed.
Written before the code.

Codex says what is left of its plan through `codex app-server` without a model call
(measured 11 Oct 2026); `app.limits.app_server` is the one place it is asked, and is stood
in for here. No other CLI says it: theirs is "unknown", never a made-up number.
"""

import importlib.util
import json
import time

import pytest

if importlib.util.find_spec("app.limits") is None:  # skipped until the code exists
    pytest.skip("slice 25a is not built yet", allow_module_level=True)

import app.limits  # noqa: E402, I001
from app.model_client import ModelUnavailable  # noqa: E402
from tests.test_chat_flow import text  # noqa: E402
from tests.test_spawn import call, step  # noqa: E402

ORIGIN = "http://127.0.0.1:8790"
ACCOUNT = "2124e951-0000-4203-9983-37fbc3e8d981"


def told_by_codex(resets_at, used=7):
    """What `account/rateLimits/read` answered, in the measured shape."""
    window = {"usedPercent": used, "windowDurationMins": 10080, "resetsAt": resets_at}
    limits = {"limitId": "codex", "primary": window, "secondary": None,
              "credits": {"hasCredits": True, "unlimited": False, "balance": "49675.89"},
              "planType": "pro", "rateLimitReachedType": None}
    return {"ordinaryUsageAllowed": True, "rateLimits": limits,
            "rateLimitsByLimitId": {"codex": limits}, "accountId": ACCOUNT}


def provider(client, kind, name):
    server = {"base_url": "http://127.0.0.1:8080/v1"} if kind in ("copilot_cli", "openai_compat") else {}
    made = client.post("/api/providers", json={"name": name, "kind": kind, **server})
    assert made.status_code in (200, 201), made.text
    return made.json()["id"]


@pytest.fixture
def limits(make_client, monkeypatch):
    asked = []

    def answer_with(given):
        async def app_server(executable, timeout, home=None):
            asked.append(executable)
            if isinstance(given, Exception):
                raise given
            return given

        monkeypatch.setattr(app.limits, "app_server", app_server)

    client, _model = make_client([text("x")])
    client.headers["Origin"] = ORIGIN
    return client, answer_with, asked


def test_what_is_left_of_a_codex_plan_is_shown_and_its_account_is_not(limits):
    client, answer_with, asked = limits
    week = int(time.time()) + 3 * 86400
    answer_with(told_by_codex(week))
    codex = provider(client, "codex_cli", "Codex")
    shown = client.post(f"/api/providers/{codex}/limits/check")
    assert shown.status_code == 200, shown.text
    told = shown.json()
    assert told["plan"] == "pro" and told["read_at"]
    (window,) = told["windows"]
    assert (window["minutes"], window["used_percent"], window["stale"]) == (10080, 7, False)
    assert window["resets_at"].startswith(time.strftime("%Y-%m-%d", time.gmtime(week)))
    assert told["credits"]["balance"] == "49675.89"
    assert ACCOUNT not in shown.text
    assert len(asked) == 1


def test_a_reading_whose_window_has_reset_since_is_stale_and_not_a_zero(limits):
    client, answer_with, _asked = limits
    answer_with(told_by_codex(int(time.time()) - 60, used=93))
    codex = provider(client, "codex_cli", "Codex")
    (window,) = client.post(f"/api/providers/{codex}/limits/check").json()["windows"]
    assert window["stale"] is True and window["used_percent"] is None


@pytest.mark.parametrize("given", [
    TimeoutError(), ModelUnavailable("codex app-server could not start"),
    {"rateLimits": "nonsense"}, {}, [],
])
def test_a_codex_that_cannot_say_is_unknown(limits, given):
    client, answer_with, _asked = limits
    answer_with(given)
    codex = provider(client, "codex_cli", "Codex")
    told = client.post(f"/api/providers/{codex}/limits/check").json()
    assert told.get("unknown") and not told.get("windows")


# Not claude_cli: Read now runs one short Claude Code turn for it (test_claude_fresh_scenarios);
# nor agy_cli, whose /quota says it (test_plan_quota). Copilot here is on a model server.
@pytest.mark.parametrize("kind", ["qoder_cli", "copilot_cli", "openai_compat"])
def test_what_no_cli_says_is_unknown_and_nothing_is_asked(limits, kind):
    client, answer_with, asked = limits
    answer_with(told_by_codex(int(time.time()) + 3600))
    other = provider(client, kind, f"other {kind}")
    told = client.post(f"/api/providers/{other}/limits/check").json()
    assert told.get("unknown") and not told.get("windows") and asked == []


def test_looking_asks_nothing_and_only_the_users_own_page_has_it_read_afresh(limits):
    """A GET - which a command an agent runs can make too - starts no CLI: it gives the
    last reading. Reading afresh is the user's, from the app's own page."""
    client, answer_with, asked = limits
    answer_with(told_by_codex(int(time.time()) + 3600))
    codex = provider(client, "codex_cli", "Codex")
    seen = client.get(f"/api/providers/{codex}/limits")
    assert seen.status_code == 200 and seen.json().get("unknown") and asked == []
    assert client.post(f"/api/providers/{codex}/limits/check",
                       headers={"Origin": ""}).status_code == 403 and asked == []
    assert client.post(f"/api/providers/{codex}/limits/check").json()["plan"] == "pro"
    assert client.get(f"/api/providers/{codex}/limits").json()["plan"] == "pro"
    assert len(asked) == 1


# --- why an agent failed -------------------------------------------------------------------


def failing(make_client, project_dir, error):
    client, _model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "do it"}, "s")),
                 text("done")],
        "Coder": [error],
    })
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "full_auto", "spawn_approval": "never"}).status_code == 200
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()[
        "run"]["id"]
    return client, cid, run_id


@pytest.mark.parametrize("error, failure", [
    (ModelUnavailable("model server returned 429: Number of request tokens has exceeded your "
                      "per-minute rate limit"), "rate_limited"),
    (ModelUnavailable("model server returned 400: Your credit balance is too low to access "
                      "the Anthropic API. Please go to Plans & Billing to upgrade or purchase "
                      "credits."), "credits_exhausted"),
    (ModelUnavailable("model server unreachable: All connection attempts failed"), "other"),
])
def test_why_an_agent_failed_is_said_and_its_opener_hears_it(make_client, wait_run, project_dir,
                                                            error, failure):
    client, cid, run_id = failing(make_client, project_dir, error)
    snap = wait_run(client, cid, run_id)
    coder = next(a for a in snap["agents"] if a["name"] == "Coder")
    assert coder["status"] == "failed" and coder["failure"] == failure
    (spawned,) = [t for t in snap["tool_calls"] if t["name"] == "spawn_agent"]
    said = (spawned["result"] or "").lower()
    if failure == "rate_limited":
        assert "rate limit" in said
    if failure == "credits_exhausted":
        assert "credit" in said
    # what it hears is advice: whether another provider has room, never a switch made for it
    assert "room" in said
    assert [a["name"] for a in snap["agents"]] == ["Lead", "Coder"]
    assert json.dumps(snap).count(ACCOUNT) == 0
