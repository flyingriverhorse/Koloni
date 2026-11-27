"""D2 (0.1.11), what its adversarial review found (each failed before its fix): a word about an
agent is never a turn of its own; a word Claude Code read steered in is not sent again to a session
it goes on in; Copilot's answer to a send is no reading of it; the Orchestrator answers a word
while its agents hold every place; a step that answers writes nothing; K5 quotes a push the user
asked for by Send now, and a later word takes it back."""

from app.agent.words import LISTEN, TOLD_UNREAD
from tests.conftest import Gate
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_commands import cmd
from tests.test_background_spawn import bg
from tests.test_chat_flow import text
from tests.test_claim_scenarios import setup
from tests.test_claude_resume import chat, fake  # noqa: F401  (fixtures)
from tests.test_copilot_agent import copilot_native  # noqa: F401  (a fixture)
from tests.test_judge_scenarios import begin as judged_begin
from tests.test_judge_scenarios import carded
from tests.test_parallel import statuses, until
from tests.test_said_so import QUOTED, repo  # noqa: F401  (a fixture)
from tests.test_send_now import now
from tests.test_send_now_cli import started
from tests.test_spawn import call, step
from tests.test_steer_at_work import at_work
from tests.test_take_in_scenarios import needs_git

ORIGIN = {"Origin": "http://127.0.0.1:8790"}


def test_a_word_about_an_agent_never_becomes_a_turn_and_unread_is_said(
    make_client, wait_run, project_dir
):
    lead_gate, coder_gate = Gate(), Gate()
    client, model, cid, run_id = setup(
        make_client,
        project_dir,
        {
            "Lead": [step(bg("Coder", "do A", "s1")), lead_gate.step(text("asked")), text("x")],
            "Coder": [coder_gate.step(text("A done"))],
        },
    )
    lead_gate.wait_partial()
    snap = until(client, cid, lambda s: statuses(s).get("Coder") == "running")
    coder = next(a for a in snap["agents"] if a["name"] == "Coder")["id"]
    told = client.post(
        f"/api/agents/{coder}/tell", json={"words": "it is wrong", "to_lead": True}, headers=ORIGIN
    )
    assert told.status_code == 204
    assert client.post(f"/api/runs/{run_id}/cancel", headers=ORIGIN).status_code == 202
    lead_gate.release()
    coder_gate.release()
    snap = wait_run(client, cid, run_id)
    assert [r["status"] for r in snap["runs"]] == ["cancelled"]  # no turn of a note's
    said = [m["content"] for m in snap["messages"] if m["role"] == "koloni"]
    assert TOLD_UNREAD.format(name="Coder", words='"it is wrong"') in said
    assert not [
        m for m in snap["messages"] if m["role"] == "user" and "it is wrong" in m["content"]
    ]


def test_a_word_claude_code_read_steered_in_is_not_sent_again_to_its_session(
    chat, fake, project_dir
):  # noqa: F811
    client, cid = chat.client, chat.cid
    fake(script=[{"say": "working"}, {"await_steer": 10}, {"say": "done"}])
    run_id = client.post(
        f"/api/conversations/{cid}/messages", json={"content": "turn two"}, headers=ORIGIN
    ).json()["run"]["id"]
    at_work(client, cid, name="Lead")
    # (its answer's row is open before the word: the word comes after it on record)
    until(
        client,
        cid,
        lambda s: any(m["role"] == "assistant" and m["run_id"] == run_id for m in s["messages"]),
        timeout=20,
    )
    assert now(client, cid, "WORD-ONCE please").json()["run"]["id"] == run_id
    until(client, cid, lambda s: s["runs"][-1]["status"] == "completed", timeout=30)
    fake(script=[{"say": "ok"}])
    chat("turn three")
    assert "--resume" in fake.starts()[-1]
    assert "WORD-ONCE" not in fake.stdin()  # (its session has it)


def test_copilots_answer_to_a_send_after_its_last_words_is_no_reading_of_it(
    copilot_native, wait_run, project_dir
):  # noqa: F811
    client, provider = copilot_native(
        [{"say": "working"}, {"say": "FINAL ANSWER"}, {"await_send": True}]
    )
    cid, run_id = started(client, project_dir, provider)
    at_work(client, cid, name="Lead")
    copilot_native.rescript([{"say": "read it"}])  # (its next run's: this one read its plan)
    assert now(client, cid, "LATE WORD").json()["run"]["id"] == run_id
    snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert "LATE WORD" in copilot_native.record()["prompt"]  # one more run reads it
    assert [m["content"] for m in snap["messages"] if m["role"] == "assistant"][-1] == "read it"


def test_the_orchestrator_answers_a_word_while_its_agents_hold_every_place(
    make_client, wait_run, project_dir
):
    a, b = Gate(), Gate()
    client, model, cid, run_id = setup(
        make_client,
        project_dir,
        {
            "Lead": [
                step(bg("Coder", "do A", "s1"), bg("Tester", "do B", "s2")),
                text("asked"),
                text("ANSWERED"),
                text("one back"),
                text("two back"),
            ],
            "Coder": [a.step(text("A done"))],
            "Tester": [b.step(text("B done"))],
        },
    )  # (spawn_max_parallel 2, the app's default: both places the agents')
    until(
        client,
        cid,
        lambda s: statuses(s) == {"Lead": "waiting", "Coder": "running", "Tester": "running"},
    )
    assert now(client, cid, "how is it going?").json()["queued_why"] is None
    snap = until(client, cid, lambda s: any(m["content"] == "ANSWERED" for m in s["messages"]))
    assert statuses(snap)["Coder"] == statuses(snap)["Tester"] == "running"
    a.release()
    b.release()
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    slots = client.app.state.runner._slots.get(run_id)
    assert slots is None or slots._value == 2


def test_with_one_place_too(make_client, wait_run, project_dir):
    a = Gate()
    client, model, cid, run_id = setup(
        make_client,
        project_dir,
        {
            "Lead": [step(bg("Coder", "do A", "s1")), text("asked"), text("ANSWERED"), text("e")],
            "Coder": [a.step(text("A done"))],
        },
        spawn_max_parallel=1,
    )
    until(client, cid, lambda s: statuses(s) == {"Lead": "waiting", "Coder": "running"})
    now(client, cid, "how is it going?")
    until(client, cid, lambda s: any(m["content"] == "ANSWERED" for m in s["messages"]))
    a.release()
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"


def test_a_step_that_answers_writes_nothing_through_any_tool(make_client, wait_run, project_dir):
    gate = Gate()
    client, model, cid, run_id = setup(make_client, project_dir, {"Lead": [gate.step(text("x"))]})
    gate.wait_partial()
    runner = client.app.state.runner
    lead = runner._lead_of(run_id)
    runner._listening.add(lead.agent_id)
    refused = [
        "write_file",
        "edit_file",
        "diagram_image",
        "run_command",
        "run_skill_script",
        "http_request",
        "github__create_or_update_file",
    ]
    assert all(runner._listen_refuses(lead, name) == LISTEN for name in refused)
    for name in ("remember", "add_task", "spawn_agent", "message_agent", "stop_agent", "read_file"):
        assert runner._listen_refuses(lead, name) is None
    runner._listening.discard(lead.agent_id)
    gate.release()
    wait_run(client, cid, run_id)


@needs_git
def test_a_push_asked_for_by_send_now_is_quoted_and_a_later_word_takes_it_back(
    make_client, wait_run, repo
):  # noqa: F811
    for words, quote in (
        (["Push it."], "Push it."),
        (["Push it.", "Wait, no - don't push yet."], None),
    ):
        gate = Gate()
        executor = ScriptedExecutor([Script(["pushed\n"])])
        client, _ = make_client(
            [gate.step(step(call("list_dir", {}, "l1"))), cmd("git push"), text("ok")],
            executor=executor,
        )
        _pid, cid, run_id = judged_begin(client, repo, "Fix the typo.", check="ask")
        gate.wait_partial()
        for one in words:  # (into its turn while it works: read at its next step)
            assert now(client, cid, one).json()["run"]["id"] == run_id
        gate.release()
        asked = carded(client, cid, run_id, wait_run)
        assert asked["command"] == "git push"
        if quote:
            assert asked["judged"] == {**QUOTED, "quote": quote, "action": "push"}
        else:
            assert asked["judged"] is None  # (the newest word that names it decides)


def test_a_word_put_in_its_own_turn_keeps_what_it_asked_of_a_spoken_answer(
    make_client, wait_run, project_dir
):
    gate = Gate()
    client, model, cid, run_id = setup(
        make_client, project_dir, {"Lead": [gate.step(text("never")), text("its own turn")]}
    )
    gate.wait_partial()
    spoken = {"language": "en-US", "style": "calm"}
    word = client.post(
        f"/api/conversations/{cid}/messages",
        json={"content": "and say it", "now": True, "spoken": spoken},
        headers=ORIGIN,
    ).json()["message"]
    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 202
    gate.release()
    snap = until(
        client, cid, lambda s: len(s["runs"]) == 2 and s["runs"][1]["status"] == "completed"
    )
    from app.db.models import Run

    with client.app.state.session_factory() as session:
        own = session.get_one(Run, snap["runs"][1]["id"])
        assert (own.spoken, own.plan_turn, own.by_user) == (spoken, False, True)
    assert next(m for m in snap["messages"] if m["id"] == word["id"])["run_id"] == own.id
