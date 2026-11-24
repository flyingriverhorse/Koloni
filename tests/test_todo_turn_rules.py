"""0.1.8 (the user, 24 Nov): a To-do task's turn in a chat is that chat's turn - its level, its
model (Claude Code too), its cards and its tools - not a night's: the rules K-r135 and B-350 held
a task's turn to at every level are gone from it. ☾ Away's jobs keep theirs; B-413's stop where
nothing moves stays."""

from sqlalchemy import select

from app.db.models import Role
from tests.test_backlog import setup
from tests.test_backlog_auto import until
from tests.test_chat_flow import text
from tests.test_claude_native import claude_app  # noqa: F401  (a fixture)
from tests.test_mcp_scenarios import give, server
from tests.test_spawn import call, role_id, spawn, step
from tests.test_todo_chat import do_in_chat, ended, snap, task, turns

OWN = {"Origin": "http://127.0.0.1:8790"}


def level(client, cid, mode):
    answer = client.patch(f"/api/conversations/{cid}", json={"permission_mode": mode}, headers=OWN)
    assert answer.status_code == 200, answer.text


def chat_of(client, pid, mode="ask"):
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    level(client, cid, mode)
    return cid


def test_a_todo_turn_asks_on_cards_as_the_chat_does(make_client, project_dir):
    # (A night's rule asked of a command that runs another program at every level, Full auto too
    # - here a pipe into python; the chat's Full auto asks only of harm.)
    client, _model = make_client(
        [step(call("run_command", {"command": "echo 1 | python"}, "k1")), text("done")]
    )
    pid, (a,) = setup(client, project_dir, "a")
    cid = chat_of(client, pid, "full_auto")
    do_in_chat(client, pid, [a], cid)
    (run,) = ended(client, cid, 1)
    assert run["status"] == "completed" and task(client, a)["status"] == "review"
    (ran,) = snap(client, cid)["commands"]
    assert (ran["command"], ran["status"]) == ("echo 1 | python", "exited"), ran


def test_at_ask_a_todo_turns_command_waits_on_its_card(make_client, project_dir):
    client, _model = make_client(
        [step(call("run_command", {"command": "echo hi"}, "k1")), text("done")]
    )
    pid, (a,) = setup(client, project_dir, "a")
    cid = chat_of(client, pid, "ask")
    do_in_chat(client, pid, [a], cid)
    until(lambda: turns(client, cid) and turns(client, cid)[-1]["status"] == "waiting_approval")
    (asked,) = [c for c in snap(client, cid)["commands"] if c["status"] == "proposed"]
    assert asked["command"] == "echo hi"
    until(lambda: client.get(f"/api/projects/{pid}/backlog").json()[0]["waiting"])
    assert (
        client.post(f"/api/commands/{asked['id']}/approve", json={}, headers=OWN).status_code == 200
    )
    ended(client, cid, 1)
    assert task(client, a)["status"] == "review"


def test_a_todo_turn_runs_on_claude_code(claude_app, project_dir):  # noqa: F811
    client, provider, _default = claude_app([{"say": "done"}])
    pid, (a,) = setup(client, project_dir, "a")
    client.patch(f"/api/roles/{role_id(client, 'Lead')}", json={"provider_id": provider["id"]})
    cid = do_in_chat(client, pid, [a]).json()["conversation_id"]
    (run,) = ended(client, cid, 1)
    assert run["status"] == "completed", run
    assert claude_app.ran() and task(client, a)["status"] == "review"
    assert "cannot work on a backlog task" not in str(snap(client, cid))


def test_a_sub_agent_on_claude_code_opens_in_a_todo_turn(claude_app, project_dir):  # noqa: F811
    client, provider, _default = claude_app(
        [{"say": "done"}], default_steps=[spawn("Coder"), text("done")]
    )
    pid, (a,) = setup(client, project_dir, "a")
    client.patch(f"/api/roles/{role_id(client, 'Coder')}", json={"provider_id": provider["id"]})
    cid = chat_of(client, pid, "full_auto")
    do_in_chat(client, pid, [a], cid)
    ended(client, cid, 1)
    (opened,) = [c for c in snap(client, cid)["tool_calls"] if c["name"] == "spawn_agent"]
    assert "cannot work on a backlog task" not in (opened["result"] or "")
    assert claude_app.ran()


def test_a_todo_turn_is_offered_the_chats_mcp_tools(make_client, project_dir, tmp_path):
    client, model = make_client([text("done")])
    pid, (a,) = setup(client, project_dir, "a")
    server(client, tmp_path)
    give(client, "Lead", "fake")
    cid = chat_of(client, pid, "full_auto")
    do_in_chat(client, pid, [a], cid)
    ended(client, cid, 1)
    names = [[t["function"]["name"] for t in tools or []] for tools in model.tool_args]
    assert any(name.startswith("fake__") for name in names[0])


def test_the_orchestrators_model_is_the_chats_own(claude_app, project_dir):  # noqa: F811
    # (A task's turn was given a model as nobody-watching turns are: a CLI with its own tools on
    # the Orchestrator's list was passed over - K-r135. Now as the chat's, first on the list.)
    client, provider, _default = claude_app([{"say": "done"}], default_steps=[text("done")])
    pid, (a,) = setup(client, project_dir, "a")
    with client.app.state.session_factory() as session:
        lead = session.scalar(select(Role).where(Role.name == "Lead"))
        lead.models = [{"provider_id": provider["id"], "model_id": None}]
        session.commit()
    cid = do_in_chat(client, pid, [a]).json()["conversation_id"]
    ended(client, cid, 1)
    assert claude_app.ran()


def test_a_todo_turn_going_round_asks_the_user_as_the_chats_turn_does(make_client, project_dir):
    # (A night's rule ended it with why, nobody asked: K-r135. Now a card waits in the chat - and
    # the task is not stuck meanwhile. B-413's stop where nothing moves still holds, unasked.)
    from tests.test_b413 import LOOP, circles
    from tests.test_parallel import until as until_snap
    from tests.test_recipe_run_scenarios import answer, asked

    client, _model = make_client([*circles(3 * LOOP), text("never said")])
    pid, (a,) = setup(client, project_dir, "a")
    cid = chat_of(client, pid, "full_auto")
    do_in_chat(client, pid, [a], cid)
    card = asked(until_snap(client, cid, asked, timeout=60))
    assert task(client, a)["status"] == "doing"
    answer(client, card, "Stop here")
    until(lambda: task(client, a)["status"] != "doing" or task(client, a)["stuck"])
