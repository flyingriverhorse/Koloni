"""KOLONİ compacts a CLI lead whose next turn starts anew, sent the whole history (no session
kept to go on in: agy, a CLI as a session, Claude Code on the user's own folder, one that fell
back); one that goes on in its session compacts that itself (`Agent.compacts_itself`). Against
its role's window, else the catalogue's for its model; and whatever its size after a turn that
was refused for its size."""

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import catalog, models_dev
from app.agent import STARTED_AGAIN, AgentRunner, _LeadTurn, _sends_again, _summary_after
from app.agent.loop_mixin import FULL_AGAIN, FULL_AGAIN_DO, NOTHING_LEFT, refused_for_size
from app.config import load_settings
from app.main import create_app
from app.model_cli import RESULT_TEXT, CliStepClient
from app.model_client import ModelUnavailable
from app.model_native import ClaudeNativeClient
from app.providers import ask_once
from tests.conftest import scaled
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_chat_flow import text
from tests.test_claude_native import FAKE, WRITE, hello, start
from tests.test_claude_resume import fake  # noqa: F401
from tests.test_spawn import role_id

ORIGIN = {"Origin": "http://127.0.0.1:8790"}
SUMMARY = "SUMMARY: the greeting was fixed"


@pytest.fixture
def cli_chat(settings_env, project_dir, wait_run, fake):  # noqa: F811
    opened = []

    def make(resumes: bool, window: int | None, summary=None):
        planned = fake(script=[{"say": "OLDWORD fixed it."}])
        cli = ClaudeNativeClient(
            launcher=FAKE,
            timeout=30,
            env=dict(planned._env),
            home=fake.home if resumes else None,
        )
        # What it is asked with its own tools off (`ask_once`): a step that, as agy's and Codex's,
        # takes no `max_tokens`.
        summariser = ScriptedModel(summary or [text(SUMMARY)])
        cli.talker = lambda: summariser
        app = create_app(load_settings(settings_env), model=ScriptedModel([]), clients={"CLI": cli})
        client = TestClient(app, base_url="http://127.0.0.1:8790")
        client.__enter__()
        opened.append(client)
        provider = client.post(
            "/api/providers",
            json={"name": "CLI", "kind": "claude_cli", "mode": "native"},
        ).json()
        if window:  # (None: its role sets none, as a new role's)
            assert (
                client.patch(
                    f"/api/roles/{role_id(client, 'Lead')}",
                    headers=ORIGIN,
                    json={"context_window": window},
                ).status_code
                == 200
            )
        cid, run_id = start(client, project_dir, provider, "full_auto")
        wait_run(client, cid, run_id, timeout=30)

        def send(words, said, fails=None, how="complain", first=(), then=None):
            """A turn begun: its run's id. `fails` with `said`: its CLI's first start of the
            turn is refused so (and, resumed, the one its client then starts anew by itself),
            and the next one says that. `how`: "complain", in words of the CLI's own (its
            stderr); "fail", in its `result`, which can be its model's words."""
            at = len(fake.starts()) + (3 if resumes else 2)
            fake(
                script=[*first, {how: fails} if fails else {"say": said}],
                **(
                    {"at_start": {str(at): then or [{"say": said}]}}
                    if fails and (said or then)
                    else {}
                ),
            )
            return client.post(
                f"/api/conversations/{cid}/messages", json={"content": words}
            ).json()["run"]["id"]

        def turn(words, said, fails=None, how="complain", first=()):
            snap = wait_run(client, cid, send(words, said, fails, how, first), timeout=30)
            turn.snap = snap
            if fails and not said:
                assert snap["runs"][-1]["status"] == "failed", snap["runs"][-1]
                return snap["runs"][-1]["error"]
            assert snap["runs"][-1]["status"] == "completed", snap["runs"][-1]["error"]
            return [a for a in snap["agents"] if a["depth"] == 0]

        turn.summariser, turn.client, turn.send, turn.cid = summariser, client, send, cid
        return turn

    yield make
    for client in opened:
        client.__exit__(None, None, None)


def test_a_cli_lead_that_starts_anew_is_compacted_past_the_threshold(cli_chat, fake):  # noqa: F811
    # (Claude Code on the user's own folder: it starts each turn anew.)
    turn = cli_chat(resumes=False, window=500)  # (its instructions alone fill that)
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
    (root / "models_dev.json").write_text(
        json.dumps(
            {
                "anthropic": {
                    "id": "anthropic",
                    "name": "Anthropic",
                    "models": {
                        "claude-fake-1": {
                            "id": "claude-fake-1",
                            "name": "Fake",
                            "family": "claude-fake",
                            "limit": {"context": window, "output": 100},
                        }
                    },
                }
            }
        ),
        encoding="utf-8",
    )


def test_with_no_window_on_its_role_it_is_compacted_against_the_catalogues(
    settings_env, cli_chat, fake
):  # noqa: F811
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
FULL_WORDS = "The context window is full and the request cannot be processed."  # (Copilot's)


@pytest.mark.parametrize("resumes", [False, True])
def test_a_turn_refused_for_its_size_is_summarised_and_started_again_once(
    cli_chat, fake, resumes, caplog
):  # noqa: F811
    turn = cli_chat(resumes=resumes, window=10_000_000)  # (never past the threshold by itself)
    turn("now the tests", "Tested.")
    before = len(fake.starts())
    leads = turn("and the docs", "Documented.", fails=TOO_LONG)
    # (The same turn and the same lead, started anew from the summary: no session is left.)
    assert len(leads) == 3 and leads[-1]["summary"] == SUMMARY, (leads[-1], caplog.text)
    # (Resumed, its client had started it anew once by itself already: `run_native`.)
    assert len(fake.starts()) == before + (3 if resumes else 2), fake.starts()[before:]
    assert "--resume" not in fake.starts()[-1]
    told = fake.stdin()
    assert SUMMARY in told and "OLDWORD" not in told and "and the docs" in told
    assert len(turn.summariser.calls) == 1
    said = [m["content"] for m in turn.snap["messages"] if m["role"] == "koloni"]
    assert said == [STARTED_AGAIN], said
    assert [m["content"] for m in turn.snap["messages"] if m["role"] == "user"].count(
        "and the docs"
    ) == 1  # (the user wrote it once)


def test_refused_again_after_that_it_ends_failed_and_is_not_started_a_third_time(
    cli_chat, fake, caplog
):  # noqa: F811
    turn = cli_chat(resumes=False, window=10_000_000)
    turn("now the tests", "Tested.")
    before = len(fake.starts())
    error = turn("and the docs", None, fails=TOO_LONG)
    # (Refused at once, with all before its last answer summarised: nothing more to summarise.)
    assert TOO_LONG in error and error.endswith(FULL_AGAIN + NOTHING_LEFT), (error, caplog.text)
    assert "send your message again" not in error
    assert len(fake.starts()) == before + 2 and len(turn.summariser.calls) == 1
    # (Its summary stands: a next turn goes on from it, and none is made again after it.)
    turn("and the docs", "Documented.")
    assert SUMMARY in fake.stdin() and len(turn.summariser.calls) == 1


def test_refused_again_after_it_worked_on_it_says_what_to_do(cli_chat, fake, wait_run):  # noqa: F811
    turn = cli_chat(resumes=False, window=10_000_000)
    turn("now the tests", "Tested.")
    before = len(fake.starts())
    run_id = turn.send(
        "and the docs", None, fails=TOO_LONG, then=[{"say": "Half of it."}, {"complain": TOO_LONG}]
    )
    run = wait_run(turn.client, turn.cid, run_id, timeout=30)["runs"][-1]
    assert run["status"] == "failed", run
    assert run["error"].endswith(FULL_AGAIN + FULL_AGAIN_DO), run["error"]
    assert len(fake.starts()) == before + 2


# (The last two are no refusal for its size: a line KOLONİ could not read or start, `_fits`.)
@pytest.mark.parametrize(
    "why",
    [
        "boom",
        "Claude Code sent a line too long to read",
        "its line is 40000 characters, too long for Windows (32767 at most)",
    ],
)
def test_a_turn_that_failed_otherwise_is_not(cli_chat, fake, why):  # noqa: F811
    turn = cli_chat(resumes=False, window=10_000_000)
    turn("now the tests", "Tested.")
    before = len(fake.starts())
    error = turn("and the docs", None, fails=why)
    assert why in error and "send your message again" not in error
    assert len(fake.starts()) == before + 1
    turn("and the docs", "Documented.")
    assert not turn.summariser.calls and "OLDWORD" in fake.stdin()


def test_refused_for_its_size_with_no_older_part_nothing_is_said_of_a_summary(cli_chat, fake):  # noqa: F811
    # (After one turn only: what is before its last answer is the user's, never summarised.)
    turn = cli_chat(resumes=False, window=10_000_000)
    error = turn("now the tests", None, fails=TOO_LONG)
    assert TOO_LONG in error and error.endswith(NOTHING_LEFT), error
    assert not turn.summariser.calls and len(fake.starts()) == 2


def test_a_refusal_in_words_that_may_be_its_models_is_not_taken_as_one(cli_chat, fake):  # noqa: F811
    # (Its `result` with is_error: a page it read could have its model say these words.)
    turn = cli_chat(resumes=False, window=10_000_000)
    turn("now the tests", "Tested.")
    before = len(fake.starts())
    error = turn("and the docs", None, fails=FULL_WORDS, how="fail")
    assert error.endswith(FULL_WORDS), error  # (the plain failure: nothing promised)
    assert len(fake.starts()) == before + 1 and not turn.summariser.calls
    assert not [m for m in turn.snap["messages"] if m["role"] == "koloni"]
    turn("and the docs", "Documented.")
    assert not turn.summariser.calls and "OLDWORD" in fake.stdin()


def test_a_refusal_with_a_class_of_its_own_is_no_refusal_for_its_size():
    refused = ModelUnavailable(TOO_LONG)
    assert refused_for_size(refused) is True
    for failure in (RESULT_TEXT, ("rate_limited", None)):
        other = ModelUnavailable(TOO_LONG)
        other.failure = failure
        assert refused_for_size(other) is False, failure
    assert refused_for_size(ModelUnavailable("boom")) is False


def test_a_lead_not_working_alone_is_not_started_again_but_summarised_for_the_next(
    cli_chat, fake, monkeypatch, caplog
):  # noqa: F811
    monkeypatch.setattr(AgentRunner, "_alone", lambda self, ctx: False)
    turn = cli_chat(resumes=False, window=10_000_000)
    turn("now the tests", "Tested.")
    before = len(fake.starts())
    error = turn("and the docs", None, fails=TOO_LONG)
    assert TOO_LONG in error and "send your message again" in error, (error, caplog.text)
    assert len(fake.starts()) == before + 1
    assert not [m for m in turn.snap["messages"] if m["role"] == "koloni"]
    leads = turn("and the docs", "Documented.")  # (it waits for the summary made after)
    told = fake.stdin()
    assert SUMMARY in told and "OLDWORD" not in told, (leads[-2]["summary_note"], told, caplog.text)
    assert len(turn.summariser.calls) == 1


def test_where_no_summary_can_be_made_it_is_not_started_again(cli_chat, fake):  # noqa: F811
    turn = cli_chat(resumes=False, window=10_000_000, summary=[ModelUnavailable("it is down")])
    turn("now the tests", "Tested.")
    before = len(fake.starts())
    error = turn("and the docs", None, fails=TOO_LONG)
    # (Nothing is promised: why no summary was made is on its agent.)
    assert error.endswith(TOO_LONG), error
    assert len(fake.starts()) == before + 1 and len(turn.summariser.calls) == 1
    lead = [a for a in turn.snap["agents"] if a["depth"] == 0][-1]
    assert "it is down" in lead["summary_note"]


def test_stop_while_it_is_summarised_stops_the_turn_and_nothing_starts_again(
    cli_chat, fake, wait_run
):  # noqa: F811
    async def held(_on_delta):
        await asyncio.sleep(3600)  # (until Stop cancels it)

    turn = cli_chat(resumes=False, window=10_000_000, summary=[held])
    turn("now the tests", "Tested.")
    before = len(fake.starts())
    run_id = turn.send("and the docs", None, fails=TOO_LONG)
    deadline = time.monotonic() + scaled(30)
    while not turn.summariser.calls:
        assert time.monotonic() < deadline, "its summary was never asked for"
        time.sleep(0.05)
    assert turn.client.post(f"/api/runs/{run_id}/cancel", headers=ORIGIN).status_code == 202
    snap = wait_run(turn.client, turn.cid, run_id, timeout=30)
    assert snap["runs"][-1]["status"] == "cancelled", snap["runs"][-1]
    assert len(fake.starts()) == before + 1
    assert not [m for m in snap["messages"] if m["role"] == "koloni"]


def test_what_it_wrote_before_it_was_refused_stands_once_after_it_is_started_again(
    cli_chat, fake, project_dir, caplog
):  # noqa: F811
    turn = cli_chat(resumes=False, window=10_000_000)
    turn("now the tests", "Tested.")
    before = len(fake.starts())
    turn("and the docs", "Documented.", fails=TOO_LONG, first=[WRITE])
    assert len(fake.starts()) == before + 2, caplog.text
    # (Its write of the first start is in the project and on record once: the second start
    # is the same agent of the same turn, told of it by its history.)
    assert hello(project_dir) == WRITE["write"][1]
    changes = [c for c in turn.snap["file_changes"] if c["run_id"] == turn.snap["runs"][-1]["id"]]
    assert [(c["path"], c["status"]) for c in changes] == [("hello.py", "applied")], changes
    assert "hello.py" in fake.stdin() and SUMMARY in fake.stdin()


def test_stop_after_it_was_started_again_stops_the_turn(cli_chat, fake, wait_run):  # noqa: F811
    turn = cli_chat(resumes=False, window=10_000_000)
    turn("now the tests", "Tested.")
    before = len(fake.starts())
    run_id = turn.send("and the docs", None, fails=TOO_LONG, then=[{"sleep": 120}])
    deadline = time.monotonic() + scaled(30)
    while len(fake.starts()) < before + 2:
        assert time.monotonic() < deadline, "it was never started again"
        time.sleep(0.05)
    assert turn.client.post(f"/api/runs/{run_id}/cancel", headers=ORIGIN).status_code == 202
    snap = wait_run(turn.client, turn.cid, run_id, timeout=30)
    assert snap["runs"][-1]["status"] == "cancelled", snap["runs"][-1]
    assert len(fake.starts()) == before + 2
    assert [m["content"] for m in snap["messages"] if m["role"] == "koloni"] == [STARTED_AGAIN]


def test_only_a_lead_working_alone_is_started_again(cli_chat):
    turn = cli_chat(resumes=False, window=10_000_000)
    lead = turn("now the tests", "Tested.")[-1]
    runner = turn.client.app.state.runner
    ctx = SimpleNamespace(run_id=lead["run_id"], agent_id=lead["id"])
    assert runner._alone(ctx) is True
    runner._recipe_copy[ctx.run_id] = "x"  # (a recipe's row)
    assert runner._alone(ctx) is False
    del runner._recipe_copy[ctx.run_id]
    # (Any other agent of the turn: a sub-agent, at work or back.)
    assert runner._alone(SimpleNamespace(run_id=ctx.run_id, agent_id="another")) is False


def a_turn(**kind):
    t = _LeadTurn()
    for flag in ("planning", "unattended", "run_compare", "job", "todo_turn"):
        setattr(t, flag, kind.get(flag, False))
    return t


def test_which_turns_are_summarised_after_a_refusal_for_their_size():
    assert _summary_after(a_turn(), "failed", True) is True
    assert _summary_after(a_turn(), "failed", False) is None
    assert _summary_after(a_turn(), "cancelled", True) is None
    # Nobody is there to send the message again: a To-do task's turn, a night's job, a
    # trigger's turn; nor a plan's, nor a side of a comparison.
    for kind in ("job", "todo_turn", "unattended", "planning", "run_compare"):
        assert _summary_after(a_turn(**{kind: True}), "failed", True) is None, kind


def test_only_a_turn_the_user_watches_is_started_again():
    assert _sends_again(a_turn()) is True
    for kind in ("job", "todo_turn", "unattended", "planning", "run_compare"):
        assert _sends_again(a_turn(**{kind: True})) is False, kind


def test_a_completed_turn_is_looked_at_past_the_threshold_as_before():
    assert _summary_after(a_turn(), "completed", False) is False
    for kind in ("job", "todo_turn"):
        assert _summary_after(a_turn(**{kind: True}), "completed", False) is False, kind
    for kind in ("unattended", "planning", "run_compare"):
        assert _summary_after(a_turn(**{kind: True}), "completed", False) is None, kind


@pytest.mark.parametrize(
    "kind, service",
    [("claude_cli", "anthropic"), ("codex_cli", "openai"), ("copilot_cli", "github-copilot")],
)
def test_a_clis_model_has_its_vendors_catalogued_window(kind, service):
    copy = models_dev.clean(
        {
            service: {
                "id": service,
                "name": service,
                "models": {
                    "m-1": {"id": "m-1", "name": "M", "limit": {"context": 500, "output": 100}}
                },
            }
        }
    )
    assert catalog.facts(kind, None, "m-1", copy)[0]["context_window"] == 500
    assert catalog.facts(kind, None, "m-2", copy)[0]["context_window"] is None
    # (On a model server of the user's own, the model is that server's: not the vendor's.)
    assert catalog.facts(kind, "http://127.0.0.1:8080/v1", "m-1", copy)[0]["context_window"] is None


def test_agys_models_have_none():
    assert (
        catalog.facts("agy_cli", None, "Qwen3.8-Flash", models_dev.load(None))[0]["context_window"]
        is None
    )


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
        async def stream_step(
            self, model_id, messages, tools, on_delta, on_thinking=None, effort=None
        ):
            return text(SUMMARY)

    said, _answer = asyncio.run(
        ask_once(Step(), "m", [{"role": "user", "content": "x"}], max_tokens=10)
    )
    assert said == SUMMARY
