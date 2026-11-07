"""Slice 91 (A3): a secret the agent never sees. Written before the code.

The agent asks for a variable by its name and says why (`ask_secret`); the user types its
value on a card; the value is kept in memory for that turn only and goes into the
environment of the turn's commands - never into the chat, the record, the events or the
model. What the commands print is hidden. Design: `tasarim/specs/
2026-10-23-referans-fikirleri-design.md`, row A3.
"""

import asyncio
import json
import logging

import pytest

from app.executors import docker
from app.executors.docker import DockerExecutor, docker_argv
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_commands import cmd
from tests.test_agent_writes import wait_status
from tests.test_chat_flow import start_in_mode, text
from tests.test_claim_scenarios import setup as copy_setup
from tests.test_host_executor import py
from tests.test_spawn import call, step
from tests.test_triggers import everything_kept, run_now, setup, trigger, until

NAME = "STRIPE_API_KEY"
# Long enough to be looked for, and no token's shape: only knowing it hides it.
SECRET = "plain-words-given-ninety-one"
ORIGIN = {"Origin": "http://127.0.0.1:8790"}
PRINTS = f"import os; print('key=' + str(os.environ.get('{NAME}')))"


def ask(name=NAME, why="to charge the test card", id="a"):
    return step(call("ask_secret", {"name": name, "why": why}, id))


def give(client, call_id, value=SECRET, headers=ORIGIN):
    return client.post(f"/api/tool-calls/{call_id}/secret", json={"value": value},
                       headers=headers)


def asked(client, cid):
    (card,) = [t for t in wait_status(client, cid, "waiting_approval")["tool_calls"]
               if t["status"] == "pending"]
    return card


def results(snap, run_id=None):
    return [(t["name"], t["status"], t["result"] or "") for t in snap["tool_calls"]
            if run_id in (None, t["run_id"])]


# --- give: the command has it, its output is hidden, the model is told only "given" ----------


def test_given_the_turns_command_has_it_its_output_hides_it_and_the_model_sees_only_given(
    make_client, wait_run, project_dir
):
    client, model = make_client([ask(), cmd(py(PRINTS, project_dir)), text("charged")])
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    card = asked(client, cid)
    assert card["name"] == "ask_secret" and json.loads(card["arguments"]) == {
        "name": NAME, "why": "to charge the test card"}
    assert give(client, card["id"]).status_code == 200
    snap = wait_run(client, cid, run_id, timeout=20)
    (_, given_status, given), (_, ran, output) = results(snap)
    assert given_status == "succeeded" and given.startswith(f"{NAME} was given")
    # It was in the command's environment (else "key=None"), and hidden in what it printed.
    assert ran == "succeeded" and "key=***" in output
    assert SECRET not in json.dumps(snap) and SECRET not in json.dumps(model.calls)


def test_a_given_name_is_not_said_to_be_held_back(make_client, wait_run, project_dir,
                                                  monkeypatch):
    monkeypatch.setenv(NAME, "the-machines-own-value")  # held back from commands (103)
    executor = ScriptedExecutor([Script(["ok\n"])])
    client, _ = make_client([ask(), cmd("pytest -q"), text("done")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    give(client, asked(client, cid)["id"])
    said = results(wait_run(client, cid, run_id))[1][2]
    (given,) = executor.envs
    assert given.pop("KOLONI_CANARY_KEY").startswith("sk-koloni-canary-")  # (101: planted too)
    assert given == {NAME: SECRET}
    assert NAME not in said and "the-machines-own-value" not in said


def test_denied_the_model_is_told_so_and_the_command_does_not_have_it(
    make_client, wait_run, project_dir
):
    client, _ = make_client([ask(), cmd(py(PRINTS, project_dir)), text("ok")])
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    assert give(client, asked(client, cid)["id"], None).status_code == 200
    (_, status, said), (_, _, output) = results(wait_run(client, cid, run_id, timeout=20))
    assert status == "denied" and said.startswith(f"rejected: the user declined to give {NAME}")
    assert "key=None" in output


# --- it ends with the turn ------------------------------------------------------------------


def test_the_next_turns_command_does_not_have_it(make_client, wait_run, project_dir):
    script = py(PRINTS, project_dir)
    client, _ = make_client([ask(), cmd(script), text("one"), cmd(script, id="k2"),
                             text("two")])
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    give(client, asked(client, cid)["id"])
    assert "key=***" in results(wait_run(client, cid, run_id, timeout=20))[1][2]
    assert client.app.state.runner._secrets_given == {}
    again = client.post(f"/api/conversations/{cid}/messages", json={"content": "again"})
    snap = wait_run(client, cid, again.json()["run"]["id"], timeout=20)
    assert "key=None" in results(snap, again.json()["run"]["id"])[-1][2]


def test_a_stopped_turn_drops_it(make_client, wait_run, project_dir, gate):
    client, _ = make_client([ask(), gate.step(text("held"))])
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    give(client, asked(client, cid)["id"])
    gate.wait_partial()
    assert client.app.state.runner._secrets_given == {run_id: {NAME: SECRET}}
    client.post(f"/api/runs/{run_id}/cancel")
    wait_run(client, cid, run_id)
    until(lambda: client.app.state.runner._secrets_given == {}, "the secret dropped")


def test_a_restart_drops_it(make_client, wait_run, project_dir):
    client, _ = make_client([ask(), text("given")])
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    give(client, asked(client, cid)["id"])
    wait_run(client, cid, run_id)
    client.__exit__(None, None, None)
    # The same database, a new KOLONİ: nothing of it was kept to be found again.
    again, _ = make_client([cmd(py(PRINTS, project_dir)), text("ok")])
    assert SECRET.encode() not in everything_kept(again)
    run = again.post(f"/api/conversations/{cid}/messages", json={"content": "go on"}).json()
    snap = wait_run(again, cid, run["run"]["id"], timeout=20)
    assert "key=None" in results(snap, run["run"]["id"])[-1][2]


# --- who may give it, and for what ----------------------------------------------------------


def test_only_the_apps_own_page_gives_it_and_only_on_a_secrets_card(
    make_client, wait_run, project_dir, tmp_path
):
    shelf = tmp_path / "shelf"
    shelf.mkdir()
    client, _ = make_client([
        step(call("ask_folder", {"path": str(shelf), "access": "read", "why": "notes"}, "f")),
        ask(), text("ok")])
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    folder = asked(client, cid)
    assert give(client, folder["id"]).status_code == 409  # not a secret's card
    client.post(f"/api/tool-calls/{folder['id']}/reject", headers=ORIGIN)
    card = asked(client, cid)
    assert give(client, card["id"], headers={}).status_code == 403
    short = give(client, card["id"], "abc1234")  # too short to be hidden in what is printed
    assert short.status_code == 422 and "abc1234" not in short.text
    assert client.app.state.runner._secrets_given == {}
    give(client, card["id"], None)
    wait_run(client, cid, run_id)


@pytest.mark.parametrize("name", ["stripe key", "1KEY", "KOLONI_MODEL_API_KEY", ""])
def test_a_name_that_is_no_variable_or_kolonis_own_is_refused_unasked(
    make_client, wait_run, project_dir, name
):
    client, _ = make_client([ask(name), text("ok")])
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    (_, status, said), = results(wait_run(client, cid, run_id))
    assert status == "failed" and said.startswith("error: name:")


def test_an_unattended_turn_is_refused_nobody_is_here_to_give_it(
    make_client, wait_run, project_dir
):
    client, _, pid, cid = setup(make_client, project_dir, [ask(), text("went on")])
    run_id = run_now(client, trigger(client, pid, cid)["id"])
    (_, status, said), = results(wait_run(client, cid, run_id))
    assert status == "denied" and "nobody is here to ask" in said


# --- Docker: by its name, never its value on the command line -------------------------------


@pytest.mark.anyio
async def test_a_container_gets_it_by_its_name_from_the_clients_environment(
    monkeypatch, tmp_path
):
    started = []

    async def fine(argv, timeout):
        return 0, "27.0"

    async def spawn(*argv, **given):
        started.append((list(argv), given.get("env")))

    monkeypatch.setattr(docker, "_exec", fine)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    docker.forget_status()
    await DockerExecutor(tmp_path, "alpine", False).start(
        "k1", "ls", tmp_path, secrets={NAME: SECRET})
    docker.forget_status()
    (argv, env), = started
    assert argv[argv.index("-e") + 1] == NAME and SECRET not in " ".join(argv)
    assert env[NAME] == SECRET and env.get("PATH")
    assert "-e" not in docker_argv("n", "alpine", tmp_path, tmp_path, False, "ls")


# --- never anywhere else --------------------------------------------------------------------


def test_the_value_is_nowhere_but_in_the_commands_environment(
    make_client, wait_run, project_dir, caplog
):
    """A whole turn with a known value: given, used by a real command that prints it, and by
    one that writes it into a file the agent then reads. It is in no row, no file KOLONİ
    keeps, no event, no log line and nothing the model was sent."""
    caplog.set_level(logging.DEBUG)
    writes = f"import os; open('cfg91.txt', 'w').write(os.environ['{NAME}'])"
    client, model = make_client([
        ask(), cmd(py(PRINTS, project_dir)), cmd(py(writes, project_dir), id="k2"),
        step(call("read_file", {"path": "cfg91.txt"}, "r1")), text("charged")])
    bus, events = client.app.state.bus, []
    emit, transient = bus.emit, bus.emit_transient

    def seen(*args, **kwargs):
        events.append(json.dumps([args, kwargs], default=str))

    bus.emit = lambda *a, **k: (seen(*a, **k), emit(*a, **k))[1]
    bus.emit_transient = lambda *a, **k: (seen(*a, **k), transient(*a, **k))[1]
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    card = asked(client, cid)
    answered = give(client, card["id"])
    snap = wait_run(client, cid, run_id, timeout=20)
    # It was there: the command printed it, hidden; the other wrote it, read back hidden.
    assert "key=***" in results(snap)[1][2]
    assert (project_dir / "cfg91.txt").read_text() == SECRET
    assert results(snap)[3][:2] == ("read_file", "succeeded") and "***" in results(snap)[3][2]
    assert any("key=***" in event for event in events)
    assert SECRET not in answered.text
    assert SECRET not in json.dumps(snap)
    assert SECRET not in json.dumps(model.calls)
    assert not [event for event in events if SECRET in event]
    assert SECRET not in caplog.text
    client.__exit__(None, None, None)  # all of it written down
    runtime = client.app.state.settings.runtime_root
    kept = [path for path in runtime.rglob("*") if path.is_file()
            and SECRET.encode() in path.read_bytes()]
    assert kept == []


# --- the review's round: every other way out --------------------------------------------------


def test_a_file_in_a_working_copy_that_holds_it_is_not_taken_into_the_project(
    make_client, wait_run, project_dir
):
    """A sub-agent's command writes the key into a file of its copy: at take-in the file is
    refused - no diff, no change on record - and stays in the copy."""
    writes = f"import os; open('env91.txt', 'w').write('K=' + os.environ['{NAME}'])"
    client, _, cid, run_id = copy_setup(make_client, project_dir, {
        "Lead": [ask(), step(call("spawn_agent", {"role": "Coder", "task": "set it"}, "s")),
                 text("done")],
        # (Its script beside the project: one named by the project's path is the project's,
        # asked about from a copy - K-kopya-istem. It writes in the copy, where it runs.)
        "Coder": [cmd(py(writes, project_dir.parent)), text("set")],
    })
    give(client, asked(client, cid)["id"])
    snap = wait_run(client, cid, run_id, timeout=20)
    (merge,) = snap["merges"]
    (held,) = [f for f in merge["files"] if f["path"] == "env91.txt"]
    assert held["state"] == "refused" and held["diff"] is None
    assert "secret given this turn" in held["note"]
    assert not (project_dir / "env91.txt").exists()
    assert SECRET not in json.dumps(snap)
    client.__exit__(None, None, None)
    assert SECRET.encode() not in everything_kept(client)


def test_what_hides_secrets_everywhere_knows_a_given_one_at_once(
    make_client, wait_run, project_dir, gate
):
    """The app-wide masker (a CLI's raw stream, the Observer, a CLI's own commands) hides a
    value the moment it is given - not a second later, when its list is read again."""
    from app import raw
    from app.commands import OutputMask, secret_values

    client, _ = make_client([ask(), gate.step(text("held"))])
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    card = asked(client, cid)
    assert raw.hidden(f"cat: {SECRET}") == f"cat: {SECRET}"  # (and its list read just now)
    give(client, card["id"])
    gate.wait_partial()
    assert raw.hidden(f"cat: {SECRET}") == "cat: ***"
    # as a CLI's own command is hidden (`_observe_command`)
    assert OutputMask(secret_values({})).hide(f"{SECRET}\n") == "***\n"
    gate.release()
    wait_run(client, cid, run_id)


@pytest.mark.parametrize("name", [
    "PATH", "NODE_OPTIONS", "PYTHONSTARTUP", "GIT_SSH_COMMAND", "BASH_ENV", "DOCKER_HOST",
    "LD_PRELOAD", "HTTPS_PROXY", "NPM_CONFIG_REGISTRY", "JAVA_TOOL_OPTIONS", "COMSPEC"])
def test_a_variable_that_changes_what_runs_is_refused(make_client, wait_run, project_dir, name):
    client, _ = make_client([ask(name), text("ok")])
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    (_, status, said), = results(wait_run(client, cid, run_id))
    assert status == "failed" and said.startswith(f"error: name: {name} changes what runs")


@pytest.mark.parametrize("name", ["GITHUB_TOKEN", "NPM_TOKEN", "PIP_INDEX_URL"])
def test_a_secret_by_its_usual_name_is_asked_for(make_client, wait_run, project_dir, name):
    client, _ = make_client([ask(name), text("ok")])
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    give(client, asked(client, cid)["id"], None)
    assert results(wait_run(client, cid, run_id))[0][1] == "denied"


def test_a_file_holding_it_written_otherwise_is_hidden_in_a_tool_result_too(
    make_client, wait_run, project_dir
):
    """As a command's output is: URL-encoded too (`OutputMask`'s spellings)."""
    value = "p@ss word/ninety-one"
    writes = ("import os, urllib.parse; open('url91.txt', 'w').write("
              f"urllib.parse.quote(os.environ['{NAME}'], safe=''))")
    client, model = make_client([ask(), cmd(py(writes, project_dir)),
                                 step(call("read_file", {"path": "url91.txt"}, "r1")),
                                 text("ok")])
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    give(client, asked(client, cid)["id"], value)
    snap = wait_run(client, cid, run_id, timeout=20)
    quoted = "p%40ss%20word%2Fninety-one"
    assert (project_dir / "url91.txt").read_text() == quoted
    assert results(snap)[2][:2] == ("read_file", "succeeded")
    assert quoted not in json.dumps(snap) and quoted not in json.dumps(model.calls)


def test_a_read_stopped_midway_is_recorded_hidden(
    make_client, wait_run, project_dir, monkeypatch
):
    import threading

    from app import agent as agent_module

    (project_dir / "cfg91.txt").write_text(SECRET, encoding="utf-8")
    reading, done = threading.Event(), threading.Event()
    read = agent_module.run_read_tool

    def slow(*args, **kwargs):
        reading.set()
        done.wait(10)
        return read(*args, **kwargs)

    monkeypatch.setattr(agent_module, "run_read_tool", slow)
    client, _ = make_client([ask(), step(call("read_file", {"path": "cfg91.txt"}, "r1")),
                             text("ok")])
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    give(client, asked(client, cid)["id"])
    assert reading.wait(10)
    client.post(f"/api/runs/{run_id}/cancel")
    done.set()
    snap = wait_run(client, cid, run_id)
    assert SECRET not in json.dumps(snap)


def test_a_late_word_after_the_turn_is_over_keeps_nothing(make_client, wait_run, project_dir):
    client, _ = make_client([ask(), text("ok")])
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    card = asked(client, cid)
    runner = client.app.state.runner
    asking = runner._secret_asks[card["id"]]
    client.post(f"/api/runs/{run_id}/cancel")
    wait_run(client, cid, run_id)
    # Were the ask still there once the turn is over, a word on it keeps nothing.
    runner._secret_asks[card["id"]] = (run_id, NAME, asyncio.Future(loop=asking[2].get_loop()))
    runner.give_secret(card["id"], SECRET)
    assert runner._secrets_given == {}
