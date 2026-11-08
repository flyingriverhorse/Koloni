"""Slice 88's acceptance set: a secret file inside the project is read only on the user's word.
Written before the code.

The live scenarios found it (B-35, 23 Oct): out of the project a secret (`.env`, a key file:
`app.workspace.is_secret`) is never opened, but inside the project an agent's `read_file` opened
the project's own `.env` and its values went to the model's provider. The user chose (b): "ask".

Contract:
- `read_file` of a secret file inside the project waits on a card at every permission level, Full
  auto too: the tool call is "pending" and its card names the file and why
  (`app.workspace.SECRET_CARD`, words like "a secret file (keys, passwords)"). `show` of one is
  refused outright: the view never serves a secret.
- Approved (`/api/tool-calls/{id}/approve`, scope "once"; any other scope is taken as once): it is
  read that once; the next read of it asks again. Nothing is remembered for it.
- Rejected: "denied", and none of the file's text is in what the model is sent.
- `search` never looks inside a secret file; its result says how many it left out, so the agent
  can ask to read one.
- `list_dir` still lists a secret file's name (a name is not the secret).
- A file that is not a secret is read as before, with no card.
- Not here (the implementer's tests): a trigger's turn, with nobody to ask, refuses; Claude Code's
  own Read of a secret file in the project is asked about the same way; Codex / agy / Copilot read
  with their own tools and cannot be held - the Folders page already says so.
"""

import json

import pytest

import app.workspace

if not hasattr(app.workspace, "SECRET_CARD"):  # written before the code: skipped until it exists
    pytest.skip("slice 88 is not built yet", allow_module_level=True)

from tests.test_agent_writes import wait_status  # noqa: E402
from tests.test_chat_flow import text  # noqa: E402
from tests.test_outside_folders_scenarios import ORIGIN, converse, project  # noqa: E402
from tests.test_spawn import call, step  # noqa: E402

SECRET = "OPENAI_API_KEY=sk-koloni-test-not-a-real-key"


def tool(name, args, id="t1"):
    return step(call(name, args, id))


@pytest.fixture
def with_secret(project_dir):
    (project_dir / ".env").write_text(SECRET + "\n", encoding="utf-8")
    return project_dir


def sent(model):
    """Everything the model was sent, as one text."""
    return json.dumps(model.calls)


@pytest.mark.parametrize("mode", ["ask", "full_auto"])
def test_reading_the_projects_env_waits_on_a_card_at_every_level(make_client, with_secret, mode):
    client, model = make_client([tool("read_file", {"path": ".env"}), text("ok")])
    cid, _run_id = converse(client, project(client, with_secret), mode=mode)
    snap = wait_status(client, cid, "waiting_approval")
    (pending,) = snap["tool_calls"]
    assert pending["status"] == "pending" and ".env" in json.dumps(pending)
    assert "sk-koloni-test" not in sent(model)


def test_approved_once_it_is_read_once_and_asked_again(make_client, wait_run, with_secret):
    client, model = make_client([tool("read_file", {"path": ".env"}, "r1"),
                                 tool("read_file", {"path": ".env"}, "r2"), text("ok")])
    cid, run_id = converse(client, project(client, with_secret), mode="full_auto")
    first = wait_status(client, cid, "waiting_approval")["tool_calls"][0]
    once = client.post(f"/api/tool-calls/{first['id']}/approve", json={"scope": "folder"},
                       headers={"Origin": ORIGIN})
    assert once.status_code == 200, once.text
    snap = wait_status(client, cid, "waiting_approval")  # a folder scope is taken as once
    assert [t["status"] for t in snap["tool_calls"]] == ["succeeded", "pending"]
    assert "sk-koloni-test" in sent(model)  # the read the user allowed
    client.post(f"/api/tool-calls/{snap['tool_calls'][1]['id']}/reject", headers={"Origin": ORIGIN})
    snap = wait_run(client, cid, run_id)
    assert snap["tool_calls"][1]["status"] == "denied"


def test_rejected_none_of_it_reaches_the_model(make_client, wait_run, with_secret):
    client, model = make_client([tool("read_file", {"path": ".env"}), text("ok")])
    cid, run_id = converse(client, project(client, with_secret), mode="full_auto")
    pending = wait_status(client, cid, "waiting_approval")["tool_calls"][0]
    client.post(f"/api/tool-calls/{pending['id']}/reject", headers={"Origin": ORIGIN})
    snap = wait_run(client, cid, run_id)
    assert snap["tool_calls"][0]["status"] == "denied"
    assert "sk-koloni-test" not in sent(model)


def test_search_never_looks_inside_a_secret_and_says_it_left_it_out(make_client, wait_run, with_secret):
    client, model = make_client([tool("search", {"pattern": "koloni-test"}), text("ok")])
    cid, run_id = converse(client, project(client, with_secret), mode="full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["tool_calls"][0]["status"] == "succeeded"
    result = model.calls[1][-1]["content"]
    assert "sk-koloni-test" not in result
    assert "secret" in result.lower()  # it says it left one out


def test_a_secret_files_name_is_still_listed(make_client, wait_run, with_secret):
    client, model = make_client([tool("list_dir", {"path": "."}), text("ok")])
    cid, run_id = converse(client, project(client, with_secret), mode="ask")
    wait_run(client, cid, run_id)
    listed = model.calls[1][-1]["content"]
    assert ".env" in listed and "sk-koloni-test" not in listed


def test_a_file_that_is_not_a_secret_is_read_with_no_card(make_client, wait_run, with_secret):
    client, model = make_client([tool("read_file", {"path": "hello.py"}), text("ok")])
    cid, run_id = converse(client, project(client, with_secret), mode="ask")
    snap = wait_run(client, cid, run_id)
    assert snap["tool_calls"][0]["status"] == "succeeded"
