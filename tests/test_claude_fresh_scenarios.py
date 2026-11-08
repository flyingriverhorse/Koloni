"""Slice 87's acceptance set: what is left of Claude Code's plan, kept fresh. Written before the code.

The user (23 Oct): the card said "17% left this week" while their own /usage said the week was 93%
used - KOLONİ learns it only from its own Claude Code runs (a `rate_limit_event`), and the user's
other sessions are not in it. "Let's add a Read now, or is there something to automate it?" -
"let's do both". Plan row 87 in `tasarim/plans/kalan-isler.md`.

Contract:
- Read now: `POST /api/providers/{id}/limits/check` (the app's own page only, as for Codex) on a
  Claude Code provider runs ONE short Claude Code turn through `app.limits.claude_turn(executable,
  timeout)` - the cheapest model, no tools, a one-word answer - which returns the `rate_limit_info`
  of the turn's last `rate_limit_event` (or raises ModelUnavailable / TimeoutError). Its reading has
  `source` "a short run to read it". A failure keeps the last reading and says why (`failed`), as
  Codex's does. `GET .../limits` never runs it. Tests never start a real `claude`: `claude_turn` is
  stood in for, and KOLONİ's test setup makes an un-stood-in call fail rather than reach the CLI.
- From the user's own sessions: Claude Code's status line input carries `rate_limits`
  (`five_hour` / `seven_day`, each {"used_percentage": 0-100, "resets_at": epoch seconds}; Pro/Max
  only, after the session's first answer). `POST /api/limits/claude-session` takes that object as
  the body, as a script of KOLONİ's that the user puts in their status line sends it:
  - only with no `Origin` header (a web page always sends one), from this machine (the server
    listens on 127.0.0.1; the test client says it is 127.0.0.1), with the key of the setup
    (review of 87: a header the script sends): else 403;
  - only JSON, at most 4 KB, numbers in range; anything else 422 and nothing kept;
  - kept as the reading of the Claude Code providers started by the default command (no
    executable given), with `source` "your Claude Code session" and `read_at` now; 204.
- `GET /api/limits/claude-session/setup` says what the user adds to their Claude Code settings
  (review of 87: a POST from the app's own page only, as it carries the key):
  {"command": ..., "script": ...}; the command runs KOLONİ's script (which exists) and the script
  keeps a status line the user already has. KOLONİ never writes the user's Claude Code settings.
"""

import time
from pathlib import Path

import pytest

import app.limits
from tests.keyed import TestClient

if not hasattr(app.limits, "claude_turn"):  # written before the code: skipped until it exists
    pytest.skip("slice 87 is not built yet", allow_module_level=True)

from app.model_client import ModelUnavailable  # noqa: E402
from tests.test_chat_flow import text  # noqa: E402
from tests.test_limits_scenarios import ORIGIN, provider  # noqa: E402

SESSION = "/api/limits/claude-session"


def info(used=0.93, kind="seven_day"):
    """A `rate_limit_info` in the measured shape (utilization 0-1)."""
    return {"status": "allowed", "rateLimitType": kind, "utilization": used,
            "resetsAt": int(time.time()) + 3 * 86400}


@pytest.fixture
def claude(make_client, monkeypatch):
    asked = []

    def answer_with(given):
        async def claude_turn(executable, timeout, home=None):
            asked.append(executable)
            if isinstance(given, Exception):
                raise given
            return given

        monkeypatch.setattr(app.limits, "claude_turn", claude_turn)

    made, _model = make_client([text("x")])
    # From this machine, as the status line script is; with the key its setup carries.
    client = TestClient(made.app, base_url=str(made.base_url), client=("127.0.0.1", 50000))
    client.headers["Origin"] = ORIGIN
    command = client.post(f"{SESSION}/setup").json()["command"]
    line_key = command.rsplit("--key ", 1)[1]

    # Only on what the status line sends: its key has the page key's header (slice 94).
    def as_the_status_line(request):
        if request.url.path == SESSION:
            request.headers["X-Koloni-Key"] = line_key

    client.event_hooks["request"].append(as_the_status_line)
    return client, answer_with, asked


def test_read_now_runs_one_short_turn_and_its_reading_says_so(claude):
    client, answer_with, asked = claude
    answer_with(info(0.93))
    cc = provider(client, "claude_cli", "Claude Code")
    assert client.get(f"/api/providers/{cc}/limits").json().get("unknown") and asked == []
    told = client.post(f"/api/providers/{cc}/limits/check").json()
    assert asked == [None]
    assert told["source"] == "a short run to read it" and told["read_at"]
    week = next(w for w in told["windows"] if w["name"] == "seven_day")
    assert week["used_percent"] == 93
    assert client.get(f"/api/providers/{cc}/limits").json()["windows"] == told["windows"]
    assert asked == [None]  # looking again runs nothing


def test_read_now_is_the_users_from_the_apps_own_page(claude):
    client, answer_with, asked = claude
    answer_with(info())
    cc = provider(client, "claude_cli", "Claude Code")
    assert client.post(f"/api/providers/{cc}/limits/check", headers={"Origin": ""}).status_code == 403
    assert asked == []


@pytest.mark.parametrize("given", [ModelUnavailable("claude could not start"), TimeoutError()])
def test_a_read_now_that_fails_keeps_the_last_reading_and_says_why(claude, given):
    client, answer_with, _asked = claude
    cc = provider(client, "claude_cli", "Claude Code")
    answer_with(info(0.5))
    first = client.post(f"/api/providers/{cc}/limits/check").json()
    answer_with(given)
    told = client.post(f"/api/providers/{cc}/limits/check").json()
    assert told["failed"] and told["windows"] == first["windows"]


def test_a_read_now_that_says_nothing_new_is_still_read_now(claude):
    """B-74: the first press left "read 6 min ago, in its last run here"."""
    client, answer_with, _asked = claude
    cc = provider(client, "claude_cli", "Claude Code")
    both = rate_limits()
    week = both["seven_day"]
    client.post(SESSION, json=both, headers={"Origin": ""})
    before = client.get(f"/api/providers/{cc}/limits").json()["read_at"]
    answer_with({**info(week["used_percentage"] / 100), "resetsAt": week["resets_at"]})
    told = client.post(f"/api/providers/{cc}/limits/check").json()
    assert told["source"] == "a short run to read it"
    # the window it named is read now; the one it did not keeps when it was read
    by_name = {w["name"]: w for w in told["windows"]}
    assert (by_name["seven_day"]["used_percent"], by_name["seven_day"]["read_at"]) == (93, None)
    assert by_name["five_hour"]["used_percent"] == 53
    assert by_name["five_hour"]["read_at"] == before != told["read_at"]


def rate_limits(five=53, week=93):
    soon = int(time.time()) + 3600
    return {"five_hour": {"used_percentage": five, "resets_at": soon},
            "seven_day": {"used_percentage": week, "resets_at": soon + 3 * 86400}}


def test_the_users_own_session_keeps_the_reading_fresh(claude):
    client, _answer_with, asked = claude
    cc = provider(client, "claude_cli", "Claude Code")
    sent = client.post(SESSION, json=rate_limits(), headers={"Origin": ""})
    assert sent.status_code == 204, sent.text
    told = client.get(f"/api/providers/{cc}/limits").json()
    assert told["source"] == "your Claude Code session" and told["read_at"]
    used = {w["name"]: w["used_percent"] for w in told["windows"]}
    assert used == {"five_hour": 53, "seven_day": 93}
    assert asked == []  # nothing was run for it


def test_a_web_page_cannot_send_it(claude):
    client, _answer_with, _asked = claude
    cc = provider(client, "claude_cli", "Claude Code")
    for origin in (ORIGIN, "https://example.com"):
        assert client.post(SESSION, json=rate_limits(), headers={"Origin": origin}).status_code == 403
    assert client.get(f"/api/providers/{cc}/limits").json().get("unknown")


@pytest.mark.parametrize("body", [
    {"five_hour": {"used_percentage": 140, "resets_at": 1}},
    {"five_hour": {"used_percentage": "53", "resets_at": 1}},
    {"five_hour": {"used_percentage": 53, "resets_at": "soon"}},
    {"seven_day": {"used_percentage": 1, "resets_at": 1}, "note": "x" * 5000},
    [],
])
def test_what_is_not_the_status_lines_shape_is_refused_and_nothing_kept(claude, body):
    client, _answer_with, _asked = claude
    cc = provider(client, "claude_cli", "Claude Code")
    assert client.post(SESSION, json=body, headers={"Origin": ""}).status_code == 422
    assert client.get(f"/api/providers/{cc}/limits").json().get("unknown")


def test_only_the_claude_code_of_the_default_command_takes_it(claude):
    client, _answer_with, _asked = claude
    default = provider(client, "claude_cli", "Claude Code")
    other = client.post("/api/providers", json={"name": "Work Claude", "kind": "claude_cli",
                                                "executable": "C:/tools/claude-work.cmd"}).json()["id"]
    codex = provider(client, "codex_cli", "Codex")
    assert client.post(SESSION, json=rate_limits(), headers={"Origin": ""}).status_code == 204
    assert client.get(f"/api/providers/{default}/limits").json()["source"] == "your Claude Code session"
    for elsewhere in (other, codex):
        assert client.get(f"/api/providers/{elsewhere}/limits").json().get("unknown")


def test_the_setup_says_what_to_add_and_the_script_is_there(claude):
    client, _answer_with, _asked = claude
    setup = client.post(f"{SESSION}/setup").json()
    script = Path(setup["script"])
    assert script.is_file()
    assert str(script) in setup["command"] or script.name in setup["command"]
