"""KOLONİ compacts a CLI lead whose next turn starts anew, sent the whole history (no session
kept to go on in: agy, a CLI as a session, Claude Code on the user's own folder, one that fell
back); one that goes on in its session compacts that itself (`Agent.compacts_itself`). Against
its role's window, else the catalogue's for its model; and whatever its size after a turn that
was refused for its size."""

import asyncio
import json
from pathlib import Path

import pytest

from app.config import load_settings
from app.main import create_app
from app.model_cli import CliStepClient
from app.model_native import ClaudeNativeClient, QoderNativeClient
from app.providers import ask_once
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_chat_flow import text
from tests.test_claude_native import FAKE, start
from tests.test_claude_resume import fake  # noqa: F401
from tests.test_spawn import role_id

ORIGIN = {"Origin": "http://127.0.0.1:8790"}
SUMMARY = "SUMMARY: the greeting was fixed"


@pytest.fixture
def cli_chat(settings_env, project_dir, wait_run, fake):  # noqa: F811
    opened = []

    def make(resumes: bool, window: int | None, qoder: bool = False):
        planned = fake(script=[{"say": "OLDWORD fixed it."}])
        cli = QoderNativeClient(launcher=FAKE, model="Qwen3.8-Flash", timeout=30,
                                env=dict(planned._env)) if qoder else ClaudeNativeClient(
            launcher=FAKE, timeout=30, env=dict(planned._env),
            home=fake.home if resumes else None)
        # What it is asked with its own tools off (`ask_once`): a step that, as agy's and Codex's,
        # takes no `max_tokens`.
        summariser = ScriptedModel([text(SUMMARY)])
        cli.talker = lambda: summariser
        app = create_app(load_settings(settings_env), model=ScriptedModel([]),
                         clients={"CLI": cli})
        client = TestClient(app, base_url="http://127.0.0.1:8790")
        client.__enter__()
        opened.append(client)
        provider = client.post("/api/providers", json={
            "name": "CLI", "kind": "qoder_cli" if qoder else "claude_cli",
            "mode": "native"}).json()
        if window:  # (None: its role sets none, as a new role's)
            assert client.patch(f"/api/roles/{role_id(client, 'Lead')}", headers=ORIGIN,
                                json={"context_window": window}).status_code == 200
        cid, run_id = start(client, project_dir, provider, "full_auto")
        wait_run(client, cid, run_id, timeout=30)

        def turn(words, said, fails=None):
            fake(script=[{"fail": fails} if fails else {"say": said}])
            run_id = client.post(f"/api/conversations/{cid}/messages",
                                 json={"content": words}).json()["run"]["id"]
            snap = wait_run(client, cid, run_id, timeout=30)
            if fails:
                assert snap["runs"][-1]["status"] == "failed", snap["runs"][-1]
                return snap["runs"][-1]["error"]
            assert snap["runs"][-1]["status"] == "completed", snap["runs"][-1]["error"]
            return [a for a in snap["agents"] if a["depth"] == 0]

        turn.summariser, turn.client = summariser, client
        return turn

    yield make
    for client in opened:
        client.__exit__(None, None, None)


@pytest.mark.parametrize("qoder", [False, True])  # (Claude Code on the user's own folder; Qoder)
def test_a_cli_lead_that_starts_anew_is_compacted_past_the_threshold(cli_chat, fake, qoder):  # noqa: F811
    turn = cli_chat(resumes=False, window=500, qoder=qoder)  # (its instructions alone fill that)
    assert turn("now the tests", "Tested.")[-1]["compacts_itself"] is False
    # (Summarised after its turn: the next waits for that, and goes on from it.)
    leads = turn("and the docs", "Documented.")
    assert leads[1]["summary"] == SUMMARY, leads[1]["summary_note"]
    told = fake.stdin()  # (the whole history, as it starts anew: its older part summarised)
    assert SUMMARY in told and "OLDWORD" not in told and "and the docs" in told
    assert len(turn.summariser.calls) >= 1


def catalogued(settings_env, window):
    """The runtime's copy of models.dev: the fake CLI's model, with this window."""
    root = Path(settings_env["KOLONI_RUNTIME_ROOT"])
    root.mkdir(parents=True, exist_ok=True)
    (root / "models_dev.json").write_text(json.dumps({"anthropic": {
        "id": "anthropic", "name": "Anthropic", "models": {"claude-fake-1": {
            "id": "claude-fake-1", "name": "Fake", "family": "claude-fake",
            "limit": {"context": window, "output": 100}}}}}), encoding="utf-8")


def test_with_no_window_on_its_role_it_is_compacted_against_the_catalogues(
        settings_env, cli_chat, fake):  # noqa: F811
    catalogued(settings_env, 500)  # (its instructions alone fill that)
    turn = cli_chat(resumes=False, window=None)
    turn("now the tests", "Tested.")
    leads = turn("and the docs", "Documented.")
    assert leads[1]["summary"] == SUMMARY, leads[1]["summary_note"]
    told = fake.stdin()
    assert SUMMARY in told and "OLDWORD" not in told and "and the docs" in told
    # (Looked up after its turn only: the window on its record is still none of KOLONİ's.)
    assert leads[1]["context_window"] is None


def test_with_no_window_known_anywhere_it_is_not(cli_chat, fake):  # noqa: F811
    turn = cli_chat(resumes=False, window=None)  # (the shipped catalogue has no claude-fake-1)
    turn("now the tests", "Tested.")
    turn("and the docs", "Documented.")
    assert not turn.summariser.calls and "OLDWORD" in fake.stdin()


TOO_LONG = "prompt is too long: 1200 tokens > 1000 maximum"  # (Anthropic's API's words)


@pytest.mark.parametrize("resumes", [False, True])
def test_a_turn_refused_for_its_size_is_summarised_for_the_next(cli_chat, fake, resumes):  # noqa: F811
    turn = cli_chat(resumes=resumes, window=10_000_000)  # (never past the threshold by itself)
    turn("now the tests", "Tested.")
    error = turn("and the docs", None, fails=TOO_LONG)
    assert TOO_LONG in error and "send your message again" in error, error
    # (The next turn waits for the summary, and starts anew from it: no session is left.)
    leads = turn("and the docs", "Documented.")
    told = fake.stdin()
    assert SUMMARY in told and "OLDWORD" not in told, (leads[-2]["summary_note"], told)
    assert "--resume" not in fake.starts()[-1]
    assert leads[-2]["summary"] == SUMMARY and len(turn.summariser.calls) == 1


def test_a_turn_that_failed_otherwise_is_not(cli_chat, fake):  # noqa: F811
    turn = cli_chat(resumes=False, window=10_000_000)
    turn("now the tests", "Tested.")
    error = turn("and the docs", None, fails="boom")
    assert "boom" in error and "send your message again" not in error
    turn("and the docs", "Documented.")
    assert not turn.summariser.calls and "OLDWORD" in fake.stdin()


def test_a_first_turn_refused_for_its_size_has_nothing_to_summarise(cli_chat, fake):  # noqa: F811
    turn = cli_chat(resumes=False, window=10_000_000)
    error = turn("now the tests", None, fails=TOO_LONG)
    assert TOO_LONG in error and "send your message again" not in error, error
    assert not turn.summariser.calls


def test_below_the_threshold_it_is_not(cli_chat, fake):  # noqa: F811
    turn = cli_chat(resumes=False, window=10_000_000)
    turn("now the tests", "Tested.")
    turn("and the docs", "Documented.")
    assert not turn.summariser.calls and "OLDWORD" in fake.stdin()


def test_a_cli_lead_that_goes_on_in_its_session_is_not(cli_chat, fake):  # noqa: F811
    turn = cli_chat(resumes=True, window=500)
    leads = turn("now the tests", "Tested.")
    assert "--resume" in fake.starts()[-1]
    assert leads[-1]["compacts_itself"] is True and leads[-1]["summary"] is None
    assert not turn.summariser.calls


def test_compact_now_on_a_cli_lead_that_starts_anew(cli_chat, fake):  # noqa: F811
    turn = cli_chat(resumes=False, window=10_000_000)  # (never past the threshold by itself)
    lead = turn("now the tests", "Tested.")[-1]
    compacted = turn.client.post(f"/api/agents/{lead['id']}/compact", headers=ORIGIN)
    assert compacted.status_code == 200, compacted.text
    assert compacted.json()["summary"] == SUMMARY
    turn("and the docs", "Documented.")
    told = fake.stdin()
    assert SUMMARY in told and "OLDWORD" not in told and "and the docs" in told


def test_a_cli_run_step_by_step_is_asked_a_summary_without_max_tokens():
    # N1: its provider switched to step by step between turns, Compact now asks its step,
    # which takes no `max_tokens` (`CliStepClient.stream_step`).
    class Step(CliStepClient):
        async def stream_step(self, model_id, messages, tools, on_delta, on_thinking=None,
                              effort=None):
            return text(SUMMARY)

    said, _answer = asyncio.run(ask_once(Step(), "m", [{"role": "user", "content": "x"}],
                                         max_tokens=10))
    assert said == SUMMARY
