"""§8 (0.1.9): Check what I said first lets a line of the user's run a delete without a card only on a
judge model whose measurement passed (`judge.MEASURED_MODELS`) - Claude Code's haiku, measured on 25
Nov 2026 - run as it was measured (`judge.measured`: its own service, a session or natively, no
setup or environment that points it elsewhere), and only where it is the user's pick or, none made,
the Fast tier's first - or where the project's old choice was "judge". Else the delete waits on its
card, and the model is not asked."""

import hashlib

import pytest

from app import judge
from app.config import load_settings
from app.db.models import Project, Provider
from app.main import create_app
from tests.fakes import Script, ScriptedExecutor, ScriptedModel
from tests.keyed import OWN, TestClient
from tests.test_agent_commands import cmd
from tests.test_chat_flow import text
from tests.test_judge_scenarios import RULE, begin, carded, verdict_line
from tests.test_team import ADDRESS, SECRET

pytestmark = [pytest.mark.judge, pytest.mark.no_po]
# The prompt haiku was measured with (scripts/measure_judge.py, 25 Nov 2026). Re-measure before
# changing it - then MEASURED_MODELS, and these digests.
ASKED_SHA = "1580e23df032c983a63e41976f5c14023bb11955e80ce2611818ff4685b04dff"
PROMPT_SHA = "c5b32d758f3094f822abdb03db5711bc9ce99a2e33abee6db5b817531196a674"


@pytest.fixture(autouse=True)
def _nothing_points_elsewhere(monkeypatch):
    """None of `judge.ELSEWHERE` in the environment the tests run from: a test that wants one sets
    it."""
    for name in judge.ELSEWHERE:
        monkeypatch.delenv(name, raising=False)


def test_the_measured_prompt_is_the_one_asked():
    said = judge.said("Keep it short.", "You may delete build/.", ["Tidy up, please."])
    command = {
        "command": "rm -rf build",
        "where": ".",
        "flagged_because": "Deletes files or disks.",
        "by": "Orchestrator",
    }
    again = "re-measure before changing it (scripts/measure_judge.py), then update MEASURED_MODELS"
    assert hashlib.sha256(judge.ASKED.encode()).hexdigest() == ASKED_SHA, again
    assert hashlib.sha256(judge.prompt(said, command).encode()).hexdigest() == PROMPT_SHA, again
    assert {("claude_cli", "haiku")} == judge.MEASURED_MODELS, again


def claude(**more) -> Provider:
    return Provider(name="Claude", kind="claude_cli", **more)


@pytest.mark.parametrize(
    ("provider", "model", "measured"),
    [
        (claude(), "haiku", True),
        (claude(mode="session"), "haiku", True),
        (claude(mode="native"), "haiku", True),
        # (a step's JSON framing was never measured; on the user's model server "haiku" is theirs)
        (claude(mode="step"), "haiku", False),
        (claude(base_url="http://127.0.0.1:9/v1"), "haiku", False),
        (claude(options={"own_setup": True}), "haiku", False),
        (claude(), "sonnet", False),
        (claude(), "Haiku", False),
        (Provider(name="Copilot", kind="copilot_cli"), "haiku", False),
        (Provider(name="Fast", kind="openai_compat", base_url=ADDRESS), "haiku", False),
    ],
)
def test_what_counts_as_the_measured_model(provider, model, measured):
    assert judge.measured(provider, model) is measured


@pytest.mark.parametrize("name", judge.ELSEWHERE)
def test_an_environment_that_points_claude_code_elsewhere_is_not_the_measured_model(
    monkeypatch, name
):
    monkeypatch.setenv(name, "1")
    assert not judge.measured(claude(), "haiku")


def test_the_box_and_a_measured_model_or_the_old_choice():
    box, unticked = (Project(judge_words=on, full_auto_check="ask") for on in (True, False))
    assert judge.words_on(box, True) and not judge.words_on(box, False)
    assert not judge.words_on(unticked, True)
    assert judge.words_on(Project(judge_words=True, full_auto_check="judge"), False)


@pytest.fixture
def app_with(settings_env):
    """An app whose Lead is scripted, with `providers` made as the Models page makes them, the
    model of each provider in `clients` a scripted one - no CLI started."""
    opened = []

    def make(providers, lead_steps, clients):
        executor = ScriptedExecutor([Script([]), Script([])])
        app = create_app(
            load_settings(settings_env),
            model=ScriptedModel(lead_steps),
            executors=executor.factory,
            clients=clients,
        )
        client = TestClient(app, base_url="http://127.0.0.1:8790")
        client.__enter__()
        opened.append(client)
        made = []
        for body in providers:
            got = client.post("/api/providers", headers=OWN, json={"for_agents": True, **body})
            assert got.status_code == 201, got.text
            made.append(got.json())
        return client, executor, made

    yield make
    for client in opened:
        client.__exit__(None, None, None)


def as_claude(model="haiku", **more) -> dict:
    """A Claude Code provider whose one model, `model`, is the Fast tier's."""
    models = [{"name": model, "tier": "fast"}]
    return {
        "name": "Claude",
        "kind": "claude_cli",
        "default_model": model,
        "models": models,
        **more,
    }


FAST = {
    "name": "Fast",
    "kind": "openai_compat",
    "base_url": ADDRESS,
    "api_key": SECRET,
    "default_model": "quick",
    "models": [{"name": "quick", "tier": "balanced"}],
}


@pytest.mark.parametrize("more", [{}, {"mode": "native"}], ids=["session", "native"])
def test_claude_codes_haiku_lets_a_line_of_the_users_run_a_delete(
    app_with, wait_run, project_dir, more
):
    asked = ScriptedModel([verdict_line("run", RULE)], model_id="haiku")
    client, executor, _ = app_with(
        [as_claude(**more)], [cmd("rm -rf build"), text("done")], {"Claude": asked}
    )
    # (the box ticked, and no old choice: only the measurement lets it work)
    _, cid, run_id = begin(client, project_dir, "tidy up", check="ask", words=True, rules=RULE)
    snap = wait_run(client, cid, run_id)
    (ran,) = snap["commands"]
    assert (ran["judged"]["kind"], ran["judged"]["verdict"]) == ("words", "run"), ran
    assert len(asked.calls) == 1 and executor.started[0][0] == "rm -rf build"
    # (Settings and the level menu read it so: the box works on this Judge model)
    assert client.get("/api/judge").json()["now"]["measured"] is True


@pytest.mark.parametrize(
    ("model", "more"),
    [("sonnet", {}), ("haiku", {"base_url": "http://127.0.0.1:9/v1"}), ("haiku", {"mode": "step"})],
    ids=["another-model", "a-model-server", "step"],
)
def test_a_model_not_run_as_measured_is_not_asked_and_the_delete_waits(
    app_with, wait_run, project_dir, model, more
):
    asked = ScriptedModel([verdict_line("run", RULE)], model_id=model)
    client, executor, _ = app_with(
        [as_claude(model, **more)], [cmd("rm -rf build"), text("left it")], {"Claude": asked}
    )
    _, cid, run_id = begin(client, project_dir, "tidy up", check="ask", words=True, rules=RULE)
    carded(client, cid, run_id, wait_run)
    assert asked.calls == [] and executor.started == []
    assert client.get("/api/judge").json()["now"]["measured"] is False


def test_a_fallback_to_haiku_while_the_chosen_judge_is_down_never_makes_the_check_live(
    app_with, wait_run, project_dir
):
    quick = ScriptedModel([verdict_line("run", RULE)], model_id="quick")
    haiku = ScriptedModel([verdict_line("run", RULE)], model_id="haiku")
    client, executor, (fast, _claude) = app_with(
        [FAST, as_claude()],
        [cmd("rm -rf build"), text("left it")],
        {"Fast": quick, "Claude": haiku},
    )
    chosen = {"provider_id": fast["id"], "model_id": "quick"}
    assert client.put("/api/judge", json=chosen, headers=OWN).status_code == 200
    with client.app.state.session_factory() as session:
        session.get_one(Provider, fast["id"]).enabled = False  # (switched off, or down)
        session.commit()
    now = client.get("/api/judge").json()["now"]
    assert (now["model_id"], now["measured"]) == ("haiku", False)
    _, cid, run_id = begin(client, project_dir, "tidy up", check="ask", words=True, rules=RULE)
    carded(client, cid, run_id, wait_run)
    assert haiku.calls == [] and quick.calls == [] and executor.started == []


@pytest.mark.parametrize(
    "answer",
    [
        RuntimeError("the CLI is not installed"),
        text("I think it is fine to run it.", i=5, o=5),
        text('{"verdict": "run"}', i=5, o=5),
    ],
    ids=["raises", "no-json", "no-quote"],
)
def test_haiku_failing_keeps_the_card(app_with, wait_run, project_dir, answer):
    haiku = ScriptedModel([answer], model_id="haiku")
    client, executor, _ = app_with(
        [as_claude()], [cmd("rm -rf build"), text("left it")], {"Claude": haiku}
    )
    _, cid, run_id = begin(client, project_dir, "tidy up", check="ask", words=True, rules=RULE)
    carded(client, cid, run_id, wait_run)
    assert executor.started == []
