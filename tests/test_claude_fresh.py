"""Slice 87 beside its acceptance set (its review round): the status line's key, readings taken
window by window whatever said them, and what was read of an account going with its last
provider."""

import time

import pytest

import app.limits
from app.db.models import LimitReading
from tests.keyed import TestClient
from tests.test_chat_flow import text
from tests.test_claude_fresh_scenarios import SESSION, info
from tests.test_limits_scenarios import ORIGIN, provider

R = int(time.time()) + 3 * 86400  # the week's reset


def week(used, resets=R):
    return {"seven_day": {"used_percentage": used, "resets_at": resets}}


@pytest.fixture
def here(make_client):
    made, _model = make_client([text("x")])
    client = TestClient(made.app, base_url=str(made.base_url), client=("127.0.0.1", 50000))
    client.headers["Origin"] = ORIGIN
    return made, client


def key_of(client):
    return client.post(f"{SESSION}/setup").json()["command"].rsplit("--key ", 1)[1]


def send(client, body, key):
    return client.post(SESSION, json=body, headers={"Origin": "", "X-Koloni-Key": key})


def shown(client, cc):
    told = client.get(f"/api/providers/{cc}/limits").json()
    return told.get("source"), {w["name"]: w["used_percent"] for w in told.get("windows") or []}


def test_only_the_key_of_the_setup_is_taken_and_the_setup_is_the_apps_own_pages(here):
    made, client = here
    cc = provider(client, "claude_cli", "Claude Code")
    assert send(client, week(93), "").status_code == 403  # before any setup there is no key
    # The setup carries the key: only the app's own page has it.
    for origin in ("", "https://example.com"):
        assert client.post(f"{SESSION}/setup", headers={"Origin": origin}).status_code == 403
    key = key_of(client)
    assert len(key) == 64 and not key.startswith("-")  # one word on the command line
    assert key and key == key_of(client)  # made once, the same each time
    for wrong in ("", "x" * len(key), key[:-1]):
        assert send(client, week(93), wrong).status_code == 403
    assert client.get(f"/api/providers/{cc}/limits").json().get("unknown")
    # The test client's own name for where it is, is not this machine.
    assert made.post(SESSION, json=week(93), headers={"Origin": "", "X-Koloni-Key": key}).status_code == 403
    assert send(client, week(93), key).status_code == 204


def test_the_newest_word_on_a_window_wins_and_an_earlier_window_never(here):
    _made, client = here
    cc = provider(client, "claude_cli", "Claude Code")
    key = key_of(client)
    send(client, week(93), key)
    factory = client.app.state.session_factory
    with factory() as session:
        first = session.get(LimitReading, '["claude_cli", null]').read_at
    # The same window said again: nothing changes, nothing is written.
    assert send(client, week(93), key).status_code == 204
    with factory() as session:
        assert session.get(LimitReading, '["claude_cli", null]').read_at == first
    # The same window with less used is taken: on 23 Oct a week went from 93% to 5% used
    # with the same reset time (the user's /usage), and the card kept 83% for days.
    assert send(client, week(50), key).status_code == 204
    assert shown(client, cc) == ("your Claude Code session", {"seven_day": 50})
    # The next week replaces it; the one before is over and is not taken.
    send(client, week(5, R + 7 * 86400), key)
    assert shown(client, cc)[1] == {"seven_day": 5}
    send(client, week(99, R), key)
    assert shown(client, cc)[1] == {"seven_day": 5}
    # Another window is added beside it.
    send(client, {"five_hour": {"used_percentage": 10, "resets_at": R - 2 * 86400}}, key)
    assert shown(client, cc)[1] == {"seven_day": 5, "five_hour": 10}


def test_read_now_after_a_reading_with_more_used_takes_its_place(here, monkeypatch):
    _made, client = here
    cc = provider(client, "claude_cli", "Claude Code")
    send(client, week(93), key_of(client))

    async def claude_turn(executable, timeout, home=None):
        return {**info(0.05), "resetsAt": R}

    monkeypatch.setattr(app.limits, "claude_turn", claude_turn)
    told = client.post(f"/api/providers/{cc}/limits/check").json()
    assert told["source"] == "a short run to read it"
    assert shown(client, cc) == ("a short run to read it", {"seven_day": 5})
    # And the user's session after it, with more used since: that is taken too.
    send(client, week(7), key_of(client))
    assert shown(client, cc) == ("your Claude Code session", {"seven_day": 7})


def test_what_was_read_of_an_account_goes_with_its_last_provider(here):
    _made, client = here
    one = provider(client, "claude_cli", "Claude Code")
    two = provider(client, "claude_cli", "Claude Code too")
    send(client, week(93), key_of(client))
    assert client.delete(f"/api/providers/{one}").status_code == 204
    assert shown(client, two)[1] == {"seven_day": 93}  # another is on that account still
    assert client.delete(f"/api/providers/{two}").status_code == 204
    again = provider(client, "claude_cli", "Claude Code")
    assert client.get(f"/api/providers/{again}/limits").json().get("unknown")


def test_each_provider_with_its_own_folder_is_read_there_and_the_users_session_is_not_its(
        here, monkeypatch):
    # K-claude-hesap: plan limits are read per provider, not per CLI.
    _made, client = here
    mine = provider(client, "claude_cli", "Claude Code")
    work, home = (client.post("/api/providers", json={
        "name": name, "kind": "claude_cli", "options": {"sign_in": "koloni"}}).json()["id"]
        for name in ("Work", "Home"))
    asked = []

    async def claude_turn(executable, timeout, home=None):
        asked.append(home)
        return {**info(0.05), "resetsAt": R}

    monkeypatch.setattr(app.limits, "claude_turn", claude_turn)
    client.post(f"/api/providers/{work}/limits/check")
    assert asked == [client.app.state.settings.runtime_root / "cli-homes" / work]
    assert shown(client, work) == ("a short run to read it", {"seven_day": 5})
    assert client.get(f"/api/providers/{home}/limits").json().get("unknown")
    # The user's own session says the user's own account's, which is not Work's nor Home's.
    send(client, week(93), key_of(client))
    assert shown(client, mine) == ("your Claude Code session", {"seven_day": 93})
    assert shown(client, work)[1] == {"seven_day": 5}
    assert client.get(f"/api/providers/{home}/limits").json().get("unknown")
