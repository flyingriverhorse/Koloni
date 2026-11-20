"""B-204: the Orchestrator alone is told never to ask the user in words and go on as if they
had answered - on an API model, as a CLI session and as a native CLI; a sub-agent is not."""

import json

from app.agent.context_mixin import ASK_PROMPT, ASKED_IN_WORDS
from tests.test_chat_flow import text
from tests.test_native_agent import native_app  # noqa: F401  (a fixture)
from tests.test_native_agent import start as start_native
from tests.test_session_agent import (
    session_app,  # noqa: F401  (a fixture)
    start,
)
from tests.test_spawn import role_id, spawn


def test_the_rule_decides_first_and_gives_no_leave_to_end_a_turn_on_a_question():
    # Review: a model takes the first remedy it reads (a card for every "is this OK?" would be
    # more asking); and a leave to end the turn on a question goes against a recipe's Lead
    # (RECIPE_RULES: never end your turn to ask) and a night job's, which nobody answers.
    assert ASKED_IN_WORDS.index("decide yourself") < ASKED_IN_WORDS.index("ask_user")
    assert "in the same turn" in ASKED_IN_WORDS and "fine" not in ASKED_IN_WORDS, ASKED_IN_WORDS


def instructions(stdin: str) -> str:
    """What a CLI was told it is: the instructions of the JSON document on its input."""
    return json.loads(stdin[stdin.index("\n\n{") + 2:])["instructions"]


def test_a_lead_on_an_api_model_is_told_and_its_sub_agent_on_a_session_is_not(
    session_app, wait_run, project_dir  # noqa: F811
):
    client, provider, default = session_app(
        [{"say": "Looks fine."}],
        default_steps=[spawn("Reviewer", "Review hello.py"), text("Reviewed.")])
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={"provider_id": provider["id"]})
    cid, run_id = start(client, project_dir, None)
    snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    lead = default.calls[0][0]["content"]
    assert ASK_PROMPT + " " + ASKED_IN_WORDS in lead, lead
    # (the Reviewer may ask too: it is told how, not this)
    reviewer = instructions(session_app.record()["stdin"])
    assert ASK_PROMPT in reviewer and ASKED_IN_WORDS not in reviewer, reviewer


def test_a_lead_as_a_session_is_told_and_its_sub_agent_on_an_api_model_is_not(
    session_app, wait_run, project_dir  # noqa: F811
):
    client, provider, default = session_app(
        [{"call": "spawn_agent", "args": {"role": "Reviewer", "task": "Review hello.py"}},
         {"say": "Reviewed."}],
        default_steps=[text("No problems.")])
    local = client.get("/api/providers").json()[0]
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={"provider_id": local["id"]})
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    lead = instructions(session_app.record()["stdin"])
    assert ASK_PROMPT + " " + ASKED_IN_WORDS in lead, lead
    reviewer = default.calls[0][0]["content"]
    assert ASK_PROMPT in reviewer and ASKED_IN_WORDS not in reviewer, reviewer


def test_a_native_cli_lead_is_told(native_app, wait_run, project_dir):  # noqa: F811
    client, provider, _ = native_app([{"say": "ok"}])
    cid, run_id = start_native(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    lead = instructions(native_app.record()["stdin"])
    assert ASK_PROMPT + " " + ASKED_IN_WORDS in lead, lead
