"""D2 (0.1.11) with a CLI as the Orchestrator (stand-in CLIs): Send now goes into the turn of a
CLI that takes a word while it works - Claude Code's user line, Codex's `turn/steer` and Copilot's
session.send with mode "immediate", measured on 27 Nov 2026 to be read in that turn - as the
user's own, once; and the turn does not
end before its Orchestrator read it: one that took none is run once more, the word its input.
C2: as its CLI shows it - taken: heard; not sent: a run more reads it; unknown: said in the chat,
never sent again."""

import pytest

from app import model_native
from app.agent import STEERED, USER_TOLD
from app.agent.words import WORD_MAYBE_UNREAD
from tests.test_claude_native import claude_app  # noqa: F401  (a fixture)
from tests.test_copilot_agent import copilot_native  # noqa: F401  (a fixture)
from tests.test_native_agent import native_app  # noqa: F401  (a fixture)
from tests.test_parallel import until
from tests.test_send_now import now
from tests.test_session_agent import session_app  # noqa: F401  (a fixture)
from tests.test_steer_at_work import at_work

OWN = {"Origin": "http://127.0.0.1:8790"}
WORD = "use blue"
TOLD = f"{STEERED}\n\n{USER_TOLD.format(words=f'"{WORD}"')}"


def started(client, project_dir, provider):
    """A chat on the CLI, its first message the user's own (a word sent now enters only such a
    turn)."""
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(
        f"/api/conversations/{cid}",
        json={
            "permission_mode": "full_auto",
            "provider_id": provider["id"],
            "lead_hands_code": False,
        },
        headers=OWN,
    )
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": "fix it"}, headers=OWN)
    return cid, run.json()["run"]["id"]


def test_send_now_into_claude_codes_turn_once(claude_app, wait_run, project_dir):  # noqa: F811
    client, provider, _model = claude_app(
        [{"say": "working"}, {"await_steer": 10}, {"say": "done"}]
    )
    cid, run_id = started(client, project_dir, provider)
    at_work(client, cid, name="Lead")
    posted = now(client, cid, WORD)
    assert posted.json()["run"]["id"] == run_id and posted.json()["queued_why"] is None
    snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (line,) = claude_app.record()["steered"]  # into its turn, once, as the user's own
    assert line["message"]["content"] == TOLD
    assert WORD not in claude_app.record()["stdin"]  # (its prompt: the turn's first message)
    assert client.app.state.runner._unheard.get(run_id) is None
    assert not [m for m in snap["messages"] if m["role"] == "koloni"]  # (taken: its echo)


def test_send_now_claude_code_never_echoes_is_unknown_said_and_never_sent_again(
    claude_app, wait_run, project_dir, monkeypatch
):  # noqa: F811
    monkeypatch.setattr(model_native, "LATE_SECONDS", 0.5)
    client, provider, _model = claude_app(
        [{"say": "working"}, {"await_steer": 10}, {"say": "done"}], echo="none", linger=True
    )
    cid, run_id = started(client, project_dir, provider)
    at_work(client, cid, name="Lead")
    assert now(client, cid, WORD).json()["run"]["id"] == run_id
    snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert len(snap["runs"]) == 1 and WORD not in claude_app.record()["stdin"]  # (no run more)
    said = [m["content"] for m in snap["messages"] if m["role"] == "koloni"]
    assert said == [WORD_MAYBE_UNREAD.format(name="Lead", words=f'"{WORD}"')]
    assert client.app.state.runner._unheard.get(run_id) is None


@pytest.mark.parametrize("ends", ["stop", "crash"])
def test_send_now_written_before_a_stop_or_a_crash_is_unknown_and_never_queued_again(
    claude_app, wait_run, project_dir, ends
):  # noqa: F811
    # C2: what is open as the run ends is unknown before the turn's end puts back what no step
    # read (`_shut_door`): written into its turn, it is said, never a turn of its own.
    end = {"sleep": 30} if ends == "stop" else {"die": 7}
    client, provider, _model = claude_app(
        [{"say": "working"}, {"await_steer": 10}, end], echo="none"
    )
    cid, run_id = started(client, project_dir, provider)
    at_work(client, cid, name="Lead")
    assert now(client, cid, WORD).json()["run"]["id"] == run_id
    until(client, cid, lambda _s: claude_app.record().get("steered"))
    if ends == "stop":
        assert client.post(f"/api/runs/{run_id}/cancel", headers=OWN).status_code == 202
    snap = wait_run(client, cid, run_id, timeout=30)
    runner = client.app.state.runner
    until(client, cid, lambda _s: run_id in runner._door_shut)
    snap = client.get(f"/api/conversations/{cid}").json()  # (after its door shut: no queue)
    assert [r["status"] for r in snap["runs"]] == ["cancelled" if ends == "stop" else "failed"]
    said = [m["content"] for m in snap["messages"] if m["role"] == "koloni"]
    assert WORD_MAYBE_UNREAD.format(name="Lead", words=f'"{WORD}"') in said, said
    assert runner._unheard.get(run_id) is None


def test_send_now_to_codex_by_turn_steer(native_app, wait_run, project_dir):  # noqa: F811
    client, provider, _model = native_app(
        [{"say": "working"}, {"await_steer": True}, {"say": "done"}]
    )
    cid, run_id = started(client, project_dir, provider)
    at_work(client, cid, name="Lead")
    assert now(client, cid, WORD).json()["run"]["id"] == run_id
    snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (steer,) = native_app.record()["steers"]
    assert steer["input"][0]["text"] == TOLD
    assert WORD not in native_app.record()["stdin"]  # (taken: its answer named its turn)


def test_send_now_codex_refuses_is_read_in_a_run_more(native_app, wait_run, project_dir):  # noqa: F811
    # C2: Codex's no (-32600, its turn over) - not sent: the word waits for a step that reads it
    client, provider, _model = native_app(
        [{"say": "working"}, {"await_steer": True}, {"say": "done"}],
        steer="reject",
        later_script=[{"say": "read your word"}],
        later_when=WORD,
    )
    cid, run_id = started(client, project_dir, provider)
    at_work(client, cid, name="Lead")
    assert now(client, cid, WORD).json()["run"]["id"] == run_id
    snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert WORD in native_app.record()["stdin"]  # its run more's input
    words = [m["content"] for m in snap["messages"] if m["role"] == "assistant"]
    assert words[-1] == "read your word", words
    assert not [m for m in snap["messages"] if m["role"] == "koloni"]


def test_send_now_to_a_cli_that_takes_none_while_it_works_is_its_next_runs_input(
    session_app, wait_run, project_dir, tmp_path
):  # noqa: F811
    # A session CLI (as agy's own session: measured 27 Nov 2026 on 1.5.18, a word written
    # while their turn runs is taken only after it) hears it in one more run, after its turn.
    go, runs = tmp_path / "go", tmp_path / "runs.log"
    client, provider, _default = session_app(
        [{"wait_for": str(go)}, {"say": "first answer"}],
        later_script=[{"say": "read your word"}],
        later_when=WORD,
        runs=str(runs),
    )
    cid, run_id = started(client, project_dir, provider)
    until(client, cid, lambda s: s["agents"] and s["agents"][0]["status"] == "running")
    assert now(client, cid, WORD).json()["run"]["id"] == run_id
    go.write_text("", encoding="utf-8")
    snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert runs.read_text(encoding="utf-8").split() == ["script", "later"]
    assert WORD in session_app.record()["stdin"]  # its next run's input
    assert [m["content"] for m in snap["messages"] if m["role"] == "assistant"][
        -1
    ] == "read your word"


def test_send_now_to_copilot_in_its_running_work(copilot_native, wait_run, project_dir):  # noqa: F811
    # Copilot takes a session.send with mode "immediate" into its running work (measured 27 Nov
    # 2026, 1.0.114 with an empty COPILOT_HOME); with none it would wait for the turn's end.
    client, provider = copilot_native([{"say": "working"}, {"await_send": True}, {"say": "done"}])
    cid, run_id = started(client, project_dir, provider)
    at_work(client, cid, name="Lead")
    copilot_native.rescript([{"say": "again"}])  # (a run more's, were there one)
    assert now(client, cid, WORD).json()["run"]["id"] == run_id
    (sent,) = until_sent(copilot_native)
    assert (sent["prompt"], sent["mode"]) == (TOLD, "immediate")
    snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert client.app.state.runner._unheard.get(run_id) is None  # heard, in this turn
    # (C2: its user.message named the send before its idle - taken: no run more)
    assert WORD not in copilot_native.record()["prompt"]
    assert not [m for m in snap["messages"] if m["role"] == "koloni"]


def until_sent(copilot):
    """What the stand-in Copilot was sent while its turn ran, once it is on its record."""
    from tests.test_backlog_auto import until as until_true

    return until_true(lambda: copilot.record().get("sent"))
