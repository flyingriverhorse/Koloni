"""D2 (0.1.11) with a CLI as the Orchestrator (stand-in CLIs): Send now goes into the turn of a
CLI that takes a word while it works - Claude Code's user line and Codex's `turn/steer`, both
measured on 27 Nov 2026 to be read in that turn - as the user's own, once; and the turn does not
end before its Orchestrator read it: one that took none is run once more, the word its input."""

from app.agent import STEERED, USER_TOLD
from tests.test_claude_native import claude_app  # noqa: F401  (a fixture)
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
