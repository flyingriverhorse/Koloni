"""The user's question (24 Nov): a story's task run by a CLI Orchestrator whose context overflows
inside one turn - Codex answers it with an error - goes stuck with Fix it, and the story's next
task starts in a session of its own: a new topic, a new Codex thread, nothing of the stuck task
in what it is sent (`stories.topic_for`, the spec's rule 6).

shortcut: the error's shape is the stand-in's (`fake_codex_app_server.py` {"error": ...}: an
`error` notification, willRetry true then false, then `turn/completed` failed with that error and
`codexErrorInfo` null) - what Codex says when its context overflows was not measured live. Its
words below are a guess at Codex's own."""

import json

import pytest

from app.config import load_settings
from app.main import create_app
from app.model_native import CodexNativeClient
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_backlog_auto import until
from tests.test_codex_resume import FAKE, TID
from tests.test_todo_chat import do_in_chat, snap, story, task

OWN = {"Origin": "http://127.0.0.1:8790"}
OVERFLOW = (
    "Codex ran out of room in the model's context window. Start a new thread or clear earlier "
    "history before retrying."
)


@pytest.fixture
def codex_chat(settings_env, tmp_path, project_dir):
    """A project whose chat's Orchestrator is native Codex on its own sign-in for KOLONİ (its
    threads go on within a topic); the client, the project's id, the chat's id and the stand-in's
    record. A run whose input names a task's title follows that task's script."""
    settings = load_settings(settings_env)
    record, plan = tmp_path / "record.json", tmp_path / "plan.json"
    scripts = {
        "Write the parser": [{"error": OVERFLOW}],  # (first: a run that holds both follows it)
        "Write the docs": [{"say": "Done."}],
    }
    plan.write_text(
        json.dumps(
            {
                "record": str(record),
                "script": [{"say": "Done."}],
                "task_scripts": scripts,
                "thread_id": TID,
                "last_input": 9000,
                "window": 258400,
            }
        ),
        encoding="utf-8",
    )
    home = settings.runtime_root / "cli-homes" / "codex-own"
    cli = CodexNativeClient(
        None, None, timeout=30, launcher=FAKE, env={"FAKE_CLI_PLAN": str(plan)}, home=home
    )
    app = create_app(settings, model=ScriptedModel([]), clients={"Codex": cli})
    with TestClient(app, base_url="http://127.0.0.1:8790") as client:
        client.headers.update(OWN)
        provider = client.post(
            "/api/providers", json={"name": "Codex", "kind": "codex_cli", "mode": "native"}
        ).json()
        pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
        cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
        client.patch(
            f"/api/conversations/{cid}",
            json={"permission_mode": "full_auto", "provider_id": provider["id"]},
        )
        yield client, pid, cid, lambda: json.loads(record.read_text(encoding="utf-8"))


def test_after_a_task_stuck_on_an_overflow_the_storys_next_task_starts_afresh(codex_chat):
    client, pid, cid, record = codex_chat
    t1 = client.post(f"/api/projects/{pid}/backlog", json={"title": "Write the parser"}).json()
    t2 = client.post(f"/api/projects/{pid}/backlog", json={"title": "Write the docs"}).json()
    story(client, pid, "Parser", t1["id"], t2["id"])
    do_in_chat(client, pid, [t1["id"], t2["id"]], cid)
    until(lambda: task(client, t2["id"])["status"] == "review", seconds=90)
    runs = snap(client, cid)["runs"]
    assert [(r["task_id"], r["status"]) for r in runs] == [
        (t1["id"], "failed"),  # (its brief)
        (t1["id"], "failed"),  # (its one fix round, in its topic)
        (t2["id"], "completed"),
    ], [r["error"] for r in runs]
    # stuck, with why: Fix it is offered for it
    assert task(client, t1["id"])["status"] == "blocked"
    assert OVERFLOW.split(".")[0] in task(client, t1["id"])["stuck"]
    # the story's next task: a topic of its own, a new thread, sent nothing of the stuck one
    assert runs[0]["topic_id"] == runs[1]["topic_id"] != runs[2]["topic_id"]
    topics = {one["id"]: one for one in snap(client, cid)["topics"]}
    assert topics[runs[2]["topic_id"]]["story_id"] == topics[runs[0]["topic_id"]]["story_id"]
    seen = record()
    assert seen["thread_method"] == "thread/start"
    assert "Write the docs" in seen["stdin"] and "Write the parser" not in seen["stdin"]
