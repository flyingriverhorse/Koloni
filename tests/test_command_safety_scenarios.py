"""Slice 90's acceptance set: command safety. Written before the code.

Found by the REA session in main's code (`AGENT_CHAT.md` CL-20261023-R04), ideas from hermes and
paperclip (MIT):
- an "Always run" rule covered the destructive form too: `rm` -> `rm -rf /home/x`, `git push` ->
  `git push --force`;
- a command gets this machine's whole environment, and what it printed went to the screen, the
  record and the model as it was: `env` showed every key;
- (from slice 88) a command that opens a secret file of the project by its name (`type .env`)
  ran unasked in Full auto.

Contract:
- A command that deletes or cannot be undone (`app.commands.danger`) is offered no rule, no rule
  covers it, and none can be written by hand; its card says what it does (`CommandOut.danger`).
- A command that names a secret file (`app.workspace.secret_in_project` for a path in the
  project, `is_secret` out of it) is asked at every level, Full auto too - KOLONİ's own
  `run_command` and Claude Code's own Bash alike.
- A secret a command prints - a value of a variable named like one, a key KOLONİ knows, a known
  token shape - is `***` in the record and in what the model is sent, also when it arrives cut
  between two chunks of output.
"""

import time

import pytest

from app.db.models import AllowedCommand
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_commands import approve, cmd
from tests.test_agent_writes import wait_status
from tests.test_chat_flow import start, start_in_mode, text
from tests.test_claude_native import claude_app  # noqa: F401  (a fixture)
from tests.test_claude_native import start as start_claude

ORIGIN = {"Origin": "http://127.0.0.1:8790"}
SECRET = "s3cr3t-value-ABCDEFGH"


def waiting(client, cid, count):
    """The conversation's commands once the `count`-th of them waits for the user."""
    for _ in range(250):
        snap = wait_status(client, cid, "waiting_approval")
        if len(snap["commands"]) >= count and snap["commands"][count - 1]["status"] == "proposed":
            return snap["commands"]
        time.sleep(0.02)
    raise AssertionError("the command never waited")


def test_a_rule_never_covers_the_destructive_form(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([Script(["ok\n"]), Script(["forced\n"]), Script(["gone\n"])])
    client, _ = make_client([
        cmd("git push origin main", "k1"), cmd("git push --force origin main", "k2"),
        cmd("rm -rf build", "k3"), text("done")], executor=executor)
    cid, run_id = start(client, project_dir)
    # (K-fullauto-sorma: a push sends off this machine - no rule is offered, and one written
    # by hand does not cover it either: `git push origin main` asks with the rule there.)
    assert client.post(f"/api/conversations/{cid}/allowed-commands",
                       json={"prefix": "git push"}, headers=ORIGIN).status_code == 201
    first = waiting(client, cid, 1)[0]
    # (R118: the record carries the card's reason for a push too, once `danger` alone)
    assert first["suggested_prefix"] == "" and "sends work off" in first["danger"]
    approve(client, first["id"], remember=True)

    forced = waiting(client, cid, 2)[1]  # the rule `git push` is there, and it still asks
    assert forced["suggested_prefix"] == "" and "remote" in forced["danger"]
    approve(client, forced["id"])
    removed = waiting(client, cid, 3)[2]
    assert removed["suggested_prefix"] == "" and "Deletes" in removed["danger"]
    approve(client, removed["id"])
    snap = wait_run(client, cid, run_id)
    assert [r["prefix"] for r in snap["allowed_commands"]] == ["git push"]
    assert [c["status"] for c in snap["commands"]] == ["exited"] * 3


def test_such_a_rule_cannot_be_put_on_the_list_by_hand(make_client, project_dir):
    client, _ = make_client([text("hi")])
    cid, _run = start(client, project_dir)
    refused = client.post(f"/api/conversations/{cid}/allowed-commands",
                          json={"prefix": "rm -rf dist"}, headers=ORIGIN)
    assert refused.status_code == 422 and "asked every time" in refused.text
    kept = client.post(f"/api/conversations/{cid}/allowed-commands",
                       json={"prefix": "git push"}, headers=ORIGIN)
    assert kept.status_code == 201


@pytest.mark.parametrize("line", ["type .env", "Get-Content -Path config/.env", "cat id_rsa"])
def test_a_command_naming_a_secret_file_is_asked_in_full_auto_too(
        make_client, wait_run, project_dir, line):
    executor = ScriptedExecutor([])
    client, model = make_client([cmd(line), text("Understood.")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    asked = waiting(client, cid, 1)[0]
    assert "secret" in asked["danger"] and asked["suggested_prefix"] == ""
    assert client.post(f"/api/commands/{asked['id']}/reject").json()["status"] == "rejected"
    snap = wait_run(client, cid, run_id)
    assert executor.started == [] and snap["tool_calls"][0]["status"] == "denied"


def test_a_rule_naming_a_secret_file_still_leaves_its_command_asked(
        make_client, wait_run, project_dir):
    """B-206: a rule stored for `type .env` before slice 90 (none can be written now) does not
    skip its card; nor is "Always run" offered for it."""
    executor = ScriptedExecutor([])
    client, _ = make_client([cmd("type .env"), text("Understood.")], executor=executor)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    with client.app.state.session_factory() as session:
        session.add(AllowedCommand(conversation_id=cid, project_id=pid, prefix="type .env"))
        session.commit()
    run_id = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "hi"}).json()["run"]["id"]
    asked = waiting(client, cid, 1)[0]
    assert "secret" in asked["danger"] and asked["suggested_prefix"] == ""
    assert client.post(f"/api/commands/{asked['id']}/reject").json()["status"] == "rejected"
    wait_run(client, cid, run_id)
    assert executor.started == []


def test_an_ordinary_command_still_runs_unasked_in_full_auto(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([Script(["2 passed\n"])])
    client, _ = make_client([cmd("pytest -q"), text("done")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["commands"][0]["status"] == "exited" and len(executor.started) == 1


def test_claude_codes_own_bash_naming_a_secret_file_is_asked_in_full_auto_too(
        claude_app, wait_run, project_dir):  # noqa: F811
    bash ={"tool": "Bash", "input": {"command": "cat .env"}, "result": "x"}
    client, provider, _ = claude_app([bash, {"say": "done"}])
    cid, run_id = start_claude(client, project_dir, provider, "full_auto")
    asked = waiting(client, cid, 1)[0]
    assert asked["origin"] == "cli" and "secret" in asked["danger"]
    client.post(f"/api/commands/{asked['id']}/reject")
    wait_run(client, cid, run_id)
    assert [v["behavior"] for v in claude_app.record()["asked"]] == ["deny"]


def test_a_printed_secret_reaches_neither_the_model_nor_the_record(
        make_client, wait_run, project_dir, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", SECRET)
    executor = ScriptedExecutor([Script(["GITHUB_TOKEN=s3cr3t-va", "lue-ABCDEFGH\nPATH=x\n"])])
    client, model = make_client([cmd("env"), text("done")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id)
    stored = snap["commands"][0]["output"]
    result = model.calls[1][-1]["content"]
    assert SECRET not in stored and SECRET not in result
    assert "GITHUB_TOKEN=***" in stored and "PATH=x" in stored
    assert "GITHUB_TOKEN=***" in result
