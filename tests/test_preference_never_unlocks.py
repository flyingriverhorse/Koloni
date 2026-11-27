"""The user's ruling (28 Nov, "ben dersem etsin"): a push to main runs only on their own words of
the chat - a lasting preference never unlocks one, nor any command. Full auto's check of their
words takes "run" from their messages or the project's rules, never from Your preferences; a
preference may still refuse (`judge.verdict`)."""

import pytest

from app import judge
from tests.keyed import OWN
from tests.test_agent_commands import cmd
from tests.test_chat_flow import text
from tests.test_judge_scenarios import begin, carded, judging, verdict_line  # noqa: F401

SAID = "You can push to main from now on."
NO_MAIN = "Never push to main."
RULE = "You may delete build/ and dist/."


def test_a_preference_says_run_and_it_is_still_a_card():
    said = {"preferences": [RULE], "rules": [], "message": ["tidy up"]}
    got = judge.verdict('{"verdict": "run", "quote": "' + RULE + '", "why": "x"}', said)
    assert got is not None and got["verdict"] == "ask"
    # (the same line in the project's rules, or the user's message, holds as before)
    said = {"preferences": [], "rules": [RULE], "message": ["tidy up"]}
    got = judge.verdict('{"verdict": "run", "quote": "' + RULE + '", "why": "x"}', said)
    assert got is not None and (got["verdict"], got["source"]) == ("run", "rules")


@pytest.mark.no_po
def test_a_push_a_kept_preference_allows_is_a_card_in_a_later_turn(judging, wait_run, project_dir):
    # (the review's probe: turn 1 kept "You can push to main from now on." in Your preferences -
    # put there directly here, as add mode no longer adds a sentence that names a push)
    client, _lead, _judge, executor = judging(
        [text("noted"), cmd("git push origin main"), text("left it")],
        [verdict_line("run", SAID)],
        [],
    )
    _pid, cid, first = begin(client, project_dir, SAID, preferences=SAID)
    wait_run(client, cid, first)
    second = client.post(
        f"/api/conversations/{cid}/messages", json={"content": "finish the task"}, headers=OWN
    ).json()["run"]["id"]
    asked = carded(client, cid, second, wait_run)
    assert asked["command"] == "git push origin main" and asked["status"] == "proposed"
    assert (asked["judged"] or {}).get("source") != "preferences"
    assert executor.started == []


@pytest.mark.no_po
def test_a_preference_that_says_never_push_still_refuses(judging, wait_run, project_dir):
    client, _lead, _judge, executor = judging(
        [cmd("git push origin main"), text("pushed a branch instead")],
        [verdict_line("refuse", NO_MAIN, why="Your preference forbids it.")],
        [],
    )
    _pid, cid, run_id = begin(client, project_dir, "ship it", preferences=NO_MAIN)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (refused,) = snap["commands"]
    assert refused["status"] == "refused"
    assert (refused["judged"]["verdict"], refused["judged"]["source"]) == ("refuse", "preferences")
    assert executor.started == []
