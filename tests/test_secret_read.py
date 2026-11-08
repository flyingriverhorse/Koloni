"""Slice 88's own pieces, beside its acceptance set (`test_secret_read_scenarios`): a trigger's
turn refuses a secret read, Claude Code's own Read is asked about as KOLONİ's read_file is,
`show` never shows a secret, and only the project's own names make a file one."""

import json
import os
import time

import pytest

from app.model_native import ClaudeNativeClient
from app.workspace import SECRET_CARD, Workspace, is_secret, secret_in_project, secret_named
from tests.test_agent_writes import wait_status
from tests.test_chat_flow import start_in_mode, text
from tests.test_claude_native import (
    FAKE,
    claude_app,  # noqa: F401  (a fixture)
    start,
    unattended,
)
from tests.test_outside_folders_scenarios import ORIGIN, conversation, converse, project
from tests.test_secret_read_scenarios import SECRET, sent, tool
from tests.test_spawn import call, step
from tests.test_triggers import NOBODY, leave, run_now, setup, trigger


def env(project_dir):
    (project_dir / ".env").write_text(SECRET + "\n", encoding="utf-8")


def test_the_card_says_why_and_a_folder_scope_opens_no_folder(make_client, wait_run, project_dir):
    env(project_dir)
    client, model = make_client([tool("read_file", {"path": ".env"}), text("ok")])
    pid = project(client, project_dir)
    cid, run_id = converse(client, pid, mode="full_auto")
    (pending,) = wait_status(client, cid, "waiting_approval")["tool_calls"]
    assert pending["why_asked"] == SECRET_CARD and pending["outside_folder"] is None
    client.post(f"/api/tool-calls/{pending['id']}/approve", json={"scope": "folder"},
                headers={"Origin": ORIGIN})
    assert wait_run(client, cid, run_id)["tool_calls"][0]["status"] == "succeeded"
    held = conversation(client, cid)
    assert held["also_in"] == [] and held["read_in"] == []


def test_rejected_the_agent_is_told_it_is_the_users_word(make_client, wait_run, project_dir):
    env(project_dir)
    client, model = make_client([tool("read_file", {"path": ".env"}), text("ok")])
    cid, run_id = converse(client, project(client, project_dir), mode="ask")
    pending = wait_status(client, cid, "waiting_approval")["tool_calls"][0]
    client.post(f"/api/tool-calls/{pending['id']}/reject", headers={"Origin": ORIGIN})
    said = wait_run(client, cid, run_id)["tool_calls"][0]["result"]
    assert "a secret file" in said and "outside the project" not in said


def test_a_triggers_turn_refuses_a_secret_read_and_says_why(make_client, wait_run, project_dir):
    env(project_dir)
    client, model, pid, cid = setup(
        make_client, project_dir, [tool("read_file", {"path": ".env"}), text("ok")],
        permission_mode="full_auto")
    run_id = run_now(client, trigger(client, pid, cid, permissions=leave(write=True))["id"])
    (refused,) = wait_run(client, cid, run_id, timeout=10)["tool_calls"]
    assert refused["status"] == "denied"
    assert NOBODY in refused["result"] and "a secret file" in refused["result"]
    assert "sk-koloni-test" not in sent(model)


def test_search_leaves_out_a_secret_it_is_pointed_at(make_client, wait_run, project_dir):
    env(project_dir)
    client, model = make_client([tool("search", {"pattern": "OPENAI", "path": ".env"}),
                                 text("ok")])
    cid, run_id = converse(client, project(client, project_dir), mode="ask")
    wait_run(client, cid, run_id)
    result = model.calls[1][-1]["content"]
    assert result.startswith("no matches") and "1 secret file" in result


def test_show_never_puts_a_secret_in_the_view(make_client, wait_run, project_dir):
    (project_dir / "credentials.md").write_text(SECRET + "\n", encoding="utf-8")
    client, model = make_client([tool("show", {"path": "credentials.md"}), text("ok")])
    cid, run_id = converse(client, project(client, project_dir), mode="full_auto")
    (shown,) = wait_run(client, cid, run_id)["tool_calls"]
    assert shown["status"] == "failed" and "secret" in shown["result"]


def test_only_the_projects_own_names_make_a_file_a_secret(tmp_path):
    root = tmp_path / "credentials" / "proj"  # a folder above the project named as a secret
    root.mkdir(parents=True)
    ws = Workspace(root)
    full = str(root / "hello.py")
    assert not secret_named(full, ws.rel(ws.resolve(full)))
    assert secret_named(".env", "config.txt")  # a link named .env, to another file
    assert secret_named(str(root / "x"), ".env")
    assert not secret_named("hello.py", "hello.py")


@pytest.mark.parametrize("rel", [
    ".env", ".ENV", ".Env", ".env.LOCAL", "ID_RSA", ".SSH/config", ".env.local", "sub/.env", "deploy/server.key", "certs/site.pem", "id_rsa",
    ".ssh/config", ".aws/credentials", ".git/config", "credentials", "secrets.json",
])
def test_in_the_project_these_are_secrets(rel):
    assert secret_in_project(rel)


@pytest.mark.parametrize("rel", [
    "app/credentials.py", "src/credentials/manager.ts", "lib/api_keys.py", "docs/token.txt",
    "config/credentials.json", ".env.example", ".env.sample", ".env.template",
    "deploy/server.key.example", ".venv/Lib/site-packages/certifi/cacert.pem",
    "node_modules/pkg/.env", "hello.py",
])
def test_in_the_project_these_hold_work(rel):
    assert not secret_in_project(rel)


def test_out_of_the_project_every_part_still_counts():
    for rel in ("C:/x/credentials/a.py", "C:/x/token.txt", "C:/x/.env.example",
                "C:/x/.venv/cacert.pem", "C:/x/api_keys.py"):
        assert is_secret(rel), rel


@pytest.mark.parametrize("path", [".ENV", ".Env.LOCAL", "ID_RSA", "sub/../.env", "sub/.env"])
def test_a_secret_is_asked_about_by_any_spelling(make_client, project_dir, path):
    env(project_dir)
    (project_dir / "sub").mkdir()
    env(project_dir / "sub")
    if not (project_dir / path).exists():  # (a case-sensitive disk: `.ENV` is a file of its own)
        (project_dir / path).write_text(SECRET + "\n", encoding="utf-8")
    client, model = make_client([tool("read_file", {"path": path}), text("ok")])
    cid, _ = converse(client, project(client, project_dir), mode="full_auto")
    (pending,) = wait_status(client, cid, "waiting_approval")["tool_calls"]
    assert pending["status"] == "pending" and pending["why_asked"] == SECRET_CARD
    assert "sk-koloni-test" not in sent(model)


def test_an_edit_of_a_secret_waits_on_the_card_and_tells_nothing(make_client, wait_run,
                                                                 project_dir):
    # old == new: "not found" or "already has this content" would tell a guess right or wrong
    env(project_dir)
    guess = {"path": ".env", "old_string": "KEY=sk-k", "new_string": "KEY=sk-k"}
    client, model = make_client([tool("edit_file", guess), text("ok")])
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    (pending,) = wait_status(client, cid, "waiting_approval")["tool_calls"]
    assert pending["why_asked"] == SECRET_CARD
    client.post(f"/api/tool-calls/{pending['id']}/reject", headers={"Origin": ORIGIN})
    wait_run(client, cid, run_id)
    told = model.calls[1][-1]["content"]
    assert told.startswith("rejected: the user declined") and "found" not in told
    assert (project_dir / ".env").read_text(encoding="utf-8") == SECRET + "\n"


def test_a_triggers_turn_refuses_an_edit_of_a_secret(make_client, wait_run, project_dir):
    env(project_dir)
    guess = {"path": ".env", "old_string": "KEY=sk-k", "new_string": "KEY=sk-k"}
    client, model, pid, cid = setup(make_client, project_dir, [tool("edit_file", guess),
                                                               text("ok")],
                                    permission_mode="full_auto")
    run_id = run_now(client, trigger(client, pid, cid, permissions=leave(write=True))["id"])
    (refused,) = wait_run(client, cid, run_id, timeout=10)["tool_calls"]
    assert refused["status"] == "denied" and NOBODY in refused["result"]
    assert "a secret file" in refused["result"] and "found" not in model.calls[1][-1]["content"]


def test_two_reads_of_a_secret_in_one_step_are_two_cards(make_client, wait_run, project_dir):
    env(project_dir)
    both = step(call("read_file", {"path": ".env"}, "a"), call("read_file", {"path": ".env"}, "b"))
    client, model = make_client([both, text("ok")])
    cid, run_id = converse(client, project(client, project_dir), mode="full_auto")
    seen: set[str] = set()
    for _ in range(2):
        asked = next_pending(client, cid, seen)
        assert asked["why_asked"] == SECRET_CARD
        client.post(f"/api/tool-calls/{asked['id']}/reject", headers={"Origin": ORIGIN})
    snap = wait_run(client, cid, run_id)
    assert [t["status"] for t in snap["tool_calls"]] == ["denied", "denied"]
    assert "sk-koloni-test" not in sent(model)


def test_a_secret_that_is_not_there_is_missing_with_no_card(make_client, wait_run, project_dir):
    client, model = make_client([tool("read_file", {"path": ".env"}), text("ok")])
    cid, run_id = converse(client, project(client, project_dir), mode="ask")
    (missing,) = wait_run(client, cid, run_id)["tool_calls"]
    assert missing["status"] == "failed" and "does not exist" in missing["result"]
    assert missing["why_asked"] is None


def test_a_hard_link_in_the_project_is_read_as_any_file(make_client, wait_run, project_dir):
    # Pins a known limit (`shortcut:` in `AgentRunner._outside`): its other name is not judged.
    env(project_dir)
    os.link(project_dir / ".env", project_dir / "notes.txt")
    client, model = make_client([tool("read_file", {"path": "notes.txt"}), text("ok")])
    cid, run_id = converse(client, project(client, project_dir), mode="full_auto")
    (read,) = wait_run(client, cid, run_id)["tool_calls"]
    assert read["status"] == "succeeded" and read["why_asked"] is None


# --- Claude Code's own Read ------------------------------------------------------------------


def read(path):
    return {"tool": "Read", "input": {"file_path": path}, "result": "x"}


def next_pending(client, cid, seen):
    """The first call that waits on a card and is not in `seen` (which it is added to)."""
    for _ in range(500):
        calls = client.get(f"/api/conversations/{cid}").json()["tool_calls"]
        fresh = [t for t in calls if t["status"] == "pending" and t["id"] not in seen]
        if fresh:
            seen.add(fresh[0]["id"])
            return fresh[0]
        time.sleep(0.02)
    raise AssertionError("no call waits on a card")


def test_claude_code_is_given_no_ask_rule_for_its_reads(tmp_path):
    # (Slice 89b: its PreToolUse hook hands every read to KOLONİ; a rule would ask twice.)
    argv = ClaudeNativeClient(launcher=FAKE)._native_arguments(tmp_path, tmp_path / "b.json")
    # (Its only settings switch the project's own hooks off: no permission rule.)
    assert json.loads(argv[argv.index("--settings") + 1]) == {"disableAllHooks": True}


def test_claude_codes_read_of_a_secret_waits_on_the_same_card(
    claude_app, wait_run, project_dir  # noqa: F811
):
    env(project_dir)
    client, provider, _ = claude_app([read("PROJECT/hello.py"), read("PROJECT/.env"),
                                      {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "full_auto")
    snap = wait_status(client, cid, "waiting_approval")
    (asked,) = [t for t in snap["tool_calls"] if t["status"] == "pending"]
    assert asked["name"] == "read_file" and asked["why_asked"] == SECRET_CARD
    client.post(f"/api/tool-calls/{asked['id']}/reject", headers={"Origin": ORIGIN})
    snap = wait_run(client, cid, run_id, timeout=20)
    verdicts = [one["behavior"] for one in claude_app.record()["asked"]]
    assert verdicts == ["allow", "deny"]  # hello.py is read with no card; .env is not read


def test_claude_codes_read_of_a_secret_allowed_is_allowed_once(
    claude_app, wait_run, project_dir  # noqa: F811
):
    env(project_dir)
    client, provider, _ = claude_app([read("PROJECT/.env"), read(".env"), {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "ask")
    seen: set[str] = set()
    for _ in range(2):  # each read asks again
        asked = next_pending(client, cid, seen)
        approved = client.post(f"/api/tool-calls/{asked['id']}/approve",
                               json={"scope": "folder"}, headers={"Origin": ORIGIN})
        assert approved.status_code == 200, approved.text
    wait_run(client, cid, run_id, timeout=20)
    assert [one["behavior"] for one in claude_app.record()["asked"]] == ["allow", "allow"]


def test_claude_codes_read_of_a_secret_in_a_triggers_turn_is_refused(
    claude_app, wait_run, project_dir  # noqa: F811
):
    env(project_dir)
    client, provider, _ = claude_app([read("PROJECT/.env"), {"say": "done"}])
    snap, _run, statuses = unattended(client, project_dir, provider, "full_auto", wait_run)
    assert "waiting_approval" not in statuses
    (verdict,) = claude_app.record()["asked"]
    assert verdict["behavior"] == "deny" and NOBODY in verdict["message"]


# --- a key by its shape, whatever the file's name (K-75-kalan) --------------------------------

KEY = "sk-proj-0123456789abcdefghijKLMN"  # (a key's shape: `sk-` and a digit)


@pytest.mark.parametrize("held", [f'OPENAI = "{KEY}"\n',
                                  "-----BEGIN OPENSSH PRIVATE KEY-----\nb3Blbg==\n"])
def test_a_file_that_shows_a_key_is_read_only_on_the_card(make_client, wait_run, project_dir,
                                                          held):
    (project_dir / "settings.py").write_text(f"DEBUG = True\n{held}", encoding="utf-8")
    client, model = make_client([tool("read_file", {"path": "settings.py"}), text("ok")])
    cid, run_id = converse(client, project(client, project_dir), mode="full_auto")
    (pending,) = wait_status(client, cid, "waiting_approval")["tool_calls"]
    assert pending["why_asked"] == SECRET_CARD
    client.post(f"/api/tool-calls/{pending['id']}/reject", headers={"Origin": ORIGIN})
    (refused,) = wait_run(client, cid, run_id)["tool_calls"]
    assert refused["status"] == "denied" and KEY not in sent(model) and "b3Blbg" not in sent(model)


JWT_SAMPLE = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4"
              "gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c")


def test_code_that_names_a_key_and_the_docs_samples_are_read_unasked_and_a_key_is_not(
    make_client, wait_run, project_dir
):
    (project_dir / "settings.py").write_text(
        'api_key = os.environ["OPENAI_API_KEY"]\npassword = getpass.getpass()\n'
        f'# e.g. AKIAIOSFODNN7EXAMPLE, or Bearer {JWT_SAMPLE}\n', encoding="utf-8")
    (project_dir / "keys.py").write_text(f'KEY = "{KEY}"\n', encoding="utf-8")
    client, model = make_client([tool("read_file", {"path": "settings.py"}),
                                 tool("read_file", {"path": "keys.py"}, "t2"), text("ok")])
    cid, run_id = converse(client, project(client, project_dir), mode="full_auto")
    # (and the other, with a key of its own, waits on the card)
    read, pending = wait_status(client, cid, "waiting_approval")["tool_calls"]
    assert read["status"] == "succeeded" and "os.environ" in read["result"]
    assert "AKIAIOSFODNN7EXAMPLE" in read["result"]
    assert pending["status"] == "pending" and pending["why_asked"] == SECRET_CARD


def test_a_search_hides_a_key_in_the_lines_it_finds_and_leaves_code_as_it_is(
    make_client, wait_run, project_dir
):
    code = ('api_key = os.environ["OPENAI_API_KEY"]  # OPENAI\n'
            "password = getpass()  # OPENAI\n")
    (project_dir / "settings.py").write_text(f'{code}OPENAI = "{KEY}"\n', encoding="utf-8")
    client, model = make_client([tool("search", {"pattern": "OPENAI"}), text("ok")])
    cid, run_id = converse(client, project(client, project_dir), mode="full_auto")
    (found,) = wait_run(client, cid, run_id)["tool_calls"]
    assert found["status"] == "succeeded" and "settings.py" in found["result"]
    assert KEY not in found["result"] and KEY not in sent(model)
    assert 'OPENAI = "***"' in found["result"]
    for line in code.splitlines():
        assert line in found["result"], line
