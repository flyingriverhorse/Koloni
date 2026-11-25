"""§8 (0.1.9): Check what I said first lets a line of the user's run a delete without a card only on a
judge model whose measurement passed (`judge.MEASURED_MODELS`) - Claude Code's haiku, measured on 25
Nov 2026 -, or where the project's old choice was "judge". Its box (`Project.judge_words`) on, an
unmeasured model is never asked: the command waits on its card."""

from types import SimpleNamespace

import pytest

from app import judge
from app.config import load_settings
from app.main import create_app
from tests.fakes import Script, ScriptedExecutor, ScriptedModel
from tests.keyed import OWN, TestClient
from tests.test_agent_commands import cmd
from tests.test_chat_flow import text
from tests.test_judge_scenarios import RULE, begin, carded, verdict_line

pytestmark = [pytest.mark.judge, pytest.mark.no_po]


def test_the_measured_pair_is_claude_codes_haiku_by_its_kind_and_name():
    box = SimpleNamespace(judge_words=True, full_auto_check="ask")
    assert judge.words_on(box, ("claude_cli", "haiku"))
    for other in (("claude_cli", "sonnet"), ("copilot_cli", "haiku"), ("openai_compat", "haiku")):
        assert not judge.words_on(box, other), other
    unticked = SimpleNamespace(judge_words=False, full_auto_check="ask")
    assert not judge.words_on(unticked, ("claude_cli", "haiku"))


@pytest.fixture
def judged_on(settings_env):
    """An app whose Lead is a scripted model and whose Fast tier's first model is `model` of a
    Claude Code provider - a scripted one, no CLI started."""
    opened = []

    def make(model, lead_steps, judge_steps):
        lead, asked = ScriptedModel(lead_steps), ScriptedModel(judge_steps, model_id=model)
        executor = ScriptedExecutor([Script([])])
        app = create_app(
            load_settings(settings_env),
            model=lead,
            executors=executor.factory,
            clients={"Claude": asked},
        )
        client = TestClient(app, base_url="http://127.0.0.1:8790")
        client.__enter__()
        opened.append(client)
        made = client.post(
            "/api/providers",
            headers=OWN,
            json={
                "name": "Claude",
                "kind": "claude_cli",
                "for_agents": True,
                "default_model": model,
                "models": [{"name": model, "tier": "fast"}],
            },
        )
        assert made.status_code == 201, made.text
        return client, asked, executor

    yield make
    for client in opened:
        client.__exit__(None, None, None)


def test_claude_codes_haiku_lets_a_line_of_the_users_run_a_delete(judged_on, wait_run, project_dir):
    client, asked, executor = judged_on(
        "haiku", [cmd("rm -rf build"), text("done")], [verdict_line("run", RULE)]
    )
    # (the box ticked, and no old choice: only the measurement lets it work)
    _, cid, run_id = begin(client, project_dir, "tidy up", check="ask", words=True, rules=RULE)
    snap = wait_run(client, cid, run_id)
    (ran,) = snap["commands"]
    assert (ran["judged"]["kind"], ran["judged"]["verdict"]) == ("words", "run"), ran
    assert len(asked.calls) == 1 and executor.started[0][0] == "rm -rf build"
    # (Settings and the level menu read it so: the box works on this Judge model)
    assert client.get("/api/judge").json()["now"]["measured"] is True


def test_an_unmeasured_model_is_not_asked_and_the_delete_waits(judged_on, wait_run, project_dir):
    client, asked, executor = judged_on(
        "sonnet", [cmd("rm -rf build"), text("left it")], [verdict_line("run", RULE)]
    )
    _, cid, run_id = begin(client, project_dir, "tidy up", check="ask", words=True, rules=RULE)
    carded(client, cid, run_id, wait_run)
    assert asked.calls == [] and executor.started == []
    assert client.get("/api/judge").json()["now"]["measured"] is False
