"""The Orchestrator's reason for a card it answered for the user, or for a Scout's proposal it
decided at Full auto, is kept masked (`raw.hidden`) - as the judge's sentence is - so that Decided
for you and the decision log never show a secret it wrote."""

import json

from app import raw
from tests.test_agent_writes import wait_status
from tests.test_chat_flow import text
from tests.test_lead_decides import CODER, ask, fire, held, lead_timers, says, until_answered
from tests.test_spawn import begin
from tests.test_team import team  # noqa: F401  (a fixture)
from tests.test_tier_scenarios import tiered
from tests.test_todo_po import (
    ANSWER,
    FAILED,
    ended,  # noqa: F401  (a fixture)
    po,
    start,
    task,
    tasks,
)

KEY = "lead-why-secret-0123456789"


def known(monkeypatch):
    monkeypatch.setattr(raw, "_known", lambda fresh=False: raw.spellings([KEY]))


def test_the_reason_for_a_card_the_orchestrator_answered_is_kept_masked(
    make_client, wait_run, project_dir, monkeypatch
):
    known(monkeypatch)
    why = f"The key {KEY} sorts by date."
    client, _model = make_client(
        [CODER, ask(), says("By date", why=why), text("Sorted by date."), text("done")]
    )
    clock = held(client)
    cid, run_id = begin(client, project_dir, mode="auto_edit", when_away="lead", away_minutes=10)
    wait_status(client, cid, "waiting_approval")
    (timer,) = lead_timers(clock, 600.0)
    fire(client, timer)
    question = until_answered(client, cid)  # (QuestionOut, as the chat reads it)
    assert (question["answer"], question["lead_why"]) == ("by date", "The key *** sorts by date.")
    wait_run(client, cid, run_id)


def test_the_reason_for_a_proposal_the_orchestrator_decided_is_kept_masked(
    team,  # noqa: F811
    project_dir,
    ended,  # noqa: F811
    monkeypatch,
):
    known(monkeypatch)
    decided = {"decisions": [{"task": 1, "add": True, "why": f"Tests were promised; key {KEY}."}]}
    client, _default, _fast = team(
        [FAILED, text(ANSWER), text(json.dumps(decided)), text("one done")],
        [po(task("Write the parser tests", "the parser tests"))],
    )
    tiered(team, client)
    pid, _cid, run_id = start(client, project_dir, mode="full_auto")
    ended(run_id)
    (added,) = [one for one in tasks(client, pid) if one["title"] == "Write the parser tests"]
    assert (added["po"]["lead"], added["po"]["lead_why"]) == (
        "add",
        "Tests were promised; key ***.",
    )
