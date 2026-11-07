"""R175 (live, Copilot luna as a session Lead): B-382 - the Lead spent its steps checking what its
Coder had checked already and was cut at its limit, then told itself the Coder's answer "was not
delivered"; B-381 - after its summary a late report woke it for an empty last word."""

import asyncio
import json
from types import SimpleNamespace

from app.config import load_settings
from app.main import create_app
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_model_choice import ORIGIN
from tests.test_spawn import begin, role_id


class Session(ScriptedModel):
    """A CLI session for every agent: the Coder says it is done (`tells`: messaging the Lead
    first); the Lead runs `lead`."""

    session = True

    def __init__(self, lead, tells=None):
        super().__init__([])
        self.lead, self.tells, self.lead_runs, self.results = lead, tells, [], []

    async def run_session(self, model_id, messages, tools, call_tool, on_text, on_message=None,
                          effort=None, on_live=None):
        if "Your name here is Coder" in str(messages[0]["content"]):
            await asyncio.sleep(0.3)  # (its opener has gone on: it is answered "started")
            if self.tells:
                await call_tool("message_agent", json.dumps({"to": "Lead", "message": self.tells}))
            await on_text("Coder: done, tests pass.")
        else:
            self.lead_runs.append(messages)
            await self.lead(self, len(self.lead_runs), call_tool, on_text)
        return SimpleNamespace(input_tokens=5, output_tokens=1, model=None)


def run(settings_env, wait_run, project_dir, lead, lead_steps, tells=None):
    cli = Session(lead, tells)
    with TestClient(create_app(load_settings(settings_env), model=cli),
                    base_url="http://127.0.0.1:8790") as client:
        client.headers["Origin"] = ORIGIN
        assert client.patch(f"/api/roles/{role_id(client, 'Lead')}",
                            json={"max_steps": lead_steps}).status_code == 200
        cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
        return cli, wait_run(client, cid, run_id)


def test_a_session_lead_near_its_limit_is_told_with_a_tool_result_once(
    settings_env, wait_run, project_dir
):
    async def lead(cli, _n, call_tool, on_text):
        for n in range(1, 6):
            await on_text(f"step {n}.")
            cli.results.append((await call_tool("list_dir", "{}"))[1])
        await on_text("done")

    cli, snap = run(settings_env, wait_run, project_dir, lead, 4)
    told = cli.results
    assert "left" not in told[0]
    assert "you have 2 steps left" in told[1] and "write your report" in told[1]
    assert "you have 1 step left" in told[2] and "2 steps left" not in told[2]
    assert snap["runs"][0]["error"] == "stopped at its role's limit of 4 steps"


def test_a_lead_cut_at_its_limit_before_it_read_its_coders_answer_keeps_it_on_record(
    settings_env, wait_run, project_dir
):
    async def lead(_cli, n, call_tool, on_text):
        await on_text("Opening a Coder.")
        if n == 1:
            await call_tool("spawn_agent", json.dumps({"role": "Coder", "task": "build"}))
            await on_text("I wait for the Coder.")

    _cli, snap = run(settings_env, wait_run, project_dir, lead, 2)
    lead_row, coder = snap["agents"]
    assert (lead_row["status"], coder["status"]) == ("failed", "completed")
    # The Coder's answer came; it stays its note and report - not "not delivered" to the Lead.
    assert not [m for m in snap["messages"] if "was not delivered" in m["content"]]
    (note,) = [m for m in snap["messages"] if m["from_agent_id"] == coder["id"]]
    assert note["content"].startswith("Coder finished.\n\nCoder: done, tests pass.")
    assert [c["kind"] for c in snap["channel_messages"]
            if c["from_agent_id"] == coder["id"]] == ["report"]


def test_a_report_after_the_leads_summary_is_followed_by_a_word_to_give_the_summary_again(
    settings_env, wait_run, project_dir
):
    # B-381 (live): woken by a report that came after its summary, the Lead answered it alone
    # ("Understood. No additional task was requested."), and that was the chat's last word.
    async def lead(_cli, n, call_tool, on_text):
        if n == 1:
            await call_tool("spawn_agent", json.dumps({"role": "Coder", "task": "build"}))
            await on_text("Summary: the Coder builds it.")
        else:
            await on_text("Summary: the Coder built it, tests pass.")

    cli, snap = run(settings_env, wait_run, project_dir, lead, 10)
    assert len(cli.lead_runs) == 2
    *_, report, told = cli.lead_runs[1]
    assert "Coder: done, tests pass." in report["content"]
    assert "came after your answer" in told["content"] and "not a reply to them" in told["content"]
    lead_id = snap["agents"][0]["id"]
    said = [m["content"] for m in snap["messages"] if m["agent_id"] == lead_id]
    assert said[-1] == "Summary: the Coder built it, tests pass."


def test_a_lead_that_answered_its_coder_after_its_summary_still_ends_on_the_summary_again(
    settings_env, wait_run, project_dir
):
    # B-381's other way in: the Coder messages the Lead after its summary, and the Lead's reply
    # is an answer - the Coder's report after it wakes the Lead once more, told to say it whole.
    async def lead(_cli, n, call_tool, on_text):
        if n == 1:
            await call_tool("spawn_agent", json.dumps({"role": "Coder", "task": "build"}))
            await on_text("Summary: the Coder builds it.")
        else:
            await on_text(f"Lead answer {n}")

    cli, snap = run(settings_env, wait_run, project_dir, lead, 10, tells="Done: style.css.")
    assert [c["kind"] for c in snap["channel_messages"]] == ["task", "message", "reply", "report"]
    assert len(cli.lead_runs) == 3 and "came after your answer" in cli.lead_runs[2][-1]["content"]
    lead_id = snap["agents"][0]["id"]
    assert [m["content"] for m in snap["messages"] if m["agent_id"] == lead_id][-1] == (
        "Lead answer 3")
