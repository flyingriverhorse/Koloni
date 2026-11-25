"""S1's review, a night's job on its branch (HIGH-1, MEDIUM-3): an MCP server's value no secret's
name holds (`NODE_ENV=production`, `HOME`, an address) and a value that reads as a word
(`not-needed`) stop and delete nothing; a real token is left out of KOLONİ's commit - the rest of
the work goes on, and the row and the chat say which file -; a secret in a file's name never goes
up. Nothing of a job's work is ever deleted for a secret KOLONİ knows."""

import sys
from pathlib import Path

from app import raw
from app.db.models import McpServer
from tests.test_agent_writes import write
from tests.test_away_branch_scenarios import (
    ONE,
    origin_of,
    repo,  # noqa: F401  (a fixture)
)
from tests.test_away_push import name_of, on_origin, push, row_now
from tests.test_away_scenarios import ended, evening, go_away
from tests.test_away_waiting import waiting
from tests.test_chat_flow import text
from tests.test_git_view import run
from tests.test_take_in_scenarios import needs_git

pytestmark = needs_git
TOKEN = "tok-0123456789abcdef-mcp-value"


def night(make_client, wait_run, repo, steps, env, before=True):
    """An Away night in `repo` with an origin whose one job plays `steps`, an MCP server with `env`
    saved before it (or, not `before`, after it): (client, the night, the job, its push row,
    origin)."""
    origin = origin_of(repo)
    client, _model, pid, cid, run_id = evening(
        make_client,
        repo,
        steps,
        plan=ONE,
        check_command=f"{sys.executable} check.py",
        lead_work="itself",
    )
    wait_run(client, cid, run_id)

    def saved():
        with client.app.state.session_factory() as session:
            session.add(McpServer(name="srv", command=["some-mcp"], env=env))
            session.commit()
        raw.read_again()

    if before:
        saved()
    assert go_away(client, cid).status_code == 200
    done = ended(client, pid)
    if not before:
        saved()
    rows = [one for one in waiting(client, done["id"]) if one["kind"] == "push"]
    return client, done, done["jobs"][0], (rows or [None])[0], origin


def ran(client, done, row):
    """Run on a push row, Run anyway past what it notes: the row after."""
    answered = push(client, done, row)
    if answered.status_code == 409:
        answered = push(client, done, row, seen=answered.json()["detail"]["notes"])
    assert answered.status_code == 200, answered.text
    return row_now(client, done)


def at_origin(origin, job) -> str:
    """Every path and content of the job's branch on origin."""
    ref = f"refs/heads/{name_of(job)}"
    return run(origin, "ls-tree", "-r", "--name-only", ref) + run(origin, "log", "-p", ref)


def test_ordinary_values_of_an_mcp_server_stop_and_delete_nothing(make_client, wait_run, repo):
    # (live: NODE_ENV=production dropped a night's branch - "it held a secret given this turn")
    home = str(Path.home())
    env = {
        "NODE_ENV": "production",
        "HOME": home,
        "API_URL": "https://api.github.com",
        "OPENAI_API_KEY": "not-needed",
    }
    said = (
        f"ENV = 'production'\nLOGS = {home!r}\nAPI = 'https://api.github.com'\nKEY = 'not-needed'\n"
    )
    steps = [write("config.py", said, "w1"), text("one done")]
    client, done, job, row, origin = night(make_client, wait_run, repo, steps, env)
    assert job["state"] == "done" and row is not None, job
    assert ran(client, done, row)["decision"] == "run"
    assert "ENV = 'production'" in at_origin(origin, job)


def test_a_real_mcp_token_is_left_out_of_the_commit_and_the_rest_goes_on(
    make_client, wait_run, repo
):
    # (never the branch dropped whole: KOLONİ's commit leaves the file out, and says so)
    steps = [
        write("conf.txt", f"token = {TOKEN}\n", "w1"),
        write("other.py", "x = 1\n", "w2"),
        text("one done"),
    ]
    client, done, job, row, origin = night(
        make_client, wait_run, repo, steps, {"GITHUB_TOKEN": TOKEN}
    )
    assert job["state"] == "done" and row is not None, job
    assert "left out: conf.txt" in row["what"]
    snap = client.get(f"/api/conversations/{job['conversation_id']}").json()
    assert any("conf.txt left out" in (m["content"] or "") for m in snap["messages"])
    assert ran(client, done, row)["decision"] == "run"
    pushed = at_origin(origin, job)
    assert "other.py" in pushed and "conf.txt" not in pushed and TOKEN not in pushed


def test_a_secret_in_a_files_name_never_goes_up(make_client, wait_run, repo):
    # (MEDIUM-3: known only in the morning, so committed at night - its name holds it)
    steps = [write(f"out-{TOKEN}.txt", "nothing secret inside\n", "w1"), text("one done")]
    client, done, job, row, origin = night(
        make_client, wait_run, repo, steps, {"GITHUB_TOKEN": TOKEN}, before=False
    )
    after = ran(client, done, row)
    assert after["decision"] is None and "holds a secret KOLONİ knows" in after["result"], after
    assert on_origin(origin, name_of(job)) == ""
