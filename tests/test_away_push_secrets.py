"""S1's review, a night's job on its branch (HIGH-1, MEDIUM-3): an MCP server's value no secret's
name holds (`NODE_ENV=production`, `HOME`, an address) and a value that reads as a word
(`not-needed`) stop and delete nothing; a real token is left out of KOLONİ's commit - the rest of
the work goes on, and the row and the chat say which file -; a secret in a file's name never goes
up. Nothing of a job's work is ever deleted for a secret KOLONİ knows."""

import subprocess
import sys
from pathlib import Path

from app import raw
from app.agent.away_branch_mixin import PUSH_NAMED
from app.away_branch import titled
from app.db.models import BacklogTask, McpServer
from tests.test_agent_writes import write
from tests.test_away_branch_scenarios import (
    MORNING,
    ONE,
    origin_of,
    repo,  # noqa: F401  (a fixture)
)
from tests.test_away_park import chat
from tests.test_away_park import run as command
from tests.test_away_push import name_of, night_with_origin, on_origin, push, row_now
from tests.test_away_scenarios import ended, evening, go_away
from tests.test_away_waiting import decide, waiting
from tests.test_backlog_auto import until
from tests.test_chat_flow import text
from tests.test_git_view import run
from tests.test_take_in_scenarios import needs_git

pytestmark = needs_git
TOKEN = "tok-0123456789abcdef-mcp-value"


def night(make_client, wait_run, repo, steps, env, before=True, plan=ONE):
    """An Away night in `repo` with an origin whose one job plays `steps`, an MCP server with `env`
    saved before it (or, not `before`, after it), `plan` the Scout's: (client, the night, the job,
    its push row, origin)."""
    origin = origin_of(repo)
    client, _model, pid, cid, run_id = evening(
        make_client,
        repo,
        steps,
        plan=plan,
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
        "GOOGLE_APPLICATION_CREDENTIALS": "C:/keys/gcp-service.json",
    }
    said = (
        f"ENV = 'production'\nLOGS = {home!r}\nAPI = 'https://api.github.com'\nKEY = 'not-needed'\n"
        "CREDS = 'C:/keys/gcp-service.json'\n"
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


def test_claude_codes_own_token_is_left_out_and_never_goes_up(
    make_client, wait_run, repo, monkeypatch
):
    # (M-A: CLAUDE_CODE_.* is a handle's name to HANDLE - its OAuth token went up)
    token = "sk-ant-oat01-" + "Q" * 40
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", token)
    steps = [
        write("token.txt", f"t = {token}\n", "w1"),
        write("new.txt", "new\n", "w2"),
        text("one done"),
    ]
    client, done, job, row, origin = night(make_client, wait_run, repo, steps, {})
    assert row is not None and "left out: token.txt" in row["what"], job
    assert ran(client, done, row)["decision"] == "run"
    pushed = at_origin(origin, job)
    assert "new.txt" in pushed and "token.txt" not in pushed and token not in pushed


def test_a_file_its_agent_committed_is_not_said_left_out_only_refused(make_client, wait_run, repo):
    # (Fable, 0.1.10: prov.txt, committed by the agent itself, was said "left out of the branch's
    # commit" too - it was on the branch; the push's refusal alone names it)
    steps = [
        write("prov.txt", f"token = {TOKEN}\n", "w1"),
        command("git add prov.txt", "c1"),
        command("git commit -m prov", "c2"),
        write("conf.txt", f"token = {TOKEN}\n", "w2"),
        text("one done"),
    ]
    client, done, job, row, origin = night(
        make_client, wait_run, repo, steps, {"GITHUB_TOKEN": TOKEN}
    )
    assert row is not None and "left out: conf.txt (" in row["what"], job
    assert "prov.txt" not in row["what"], row
    snap = client.get(f"/api/conversations/{job['conversation_id']}").json()
    lines = [m["content"] or "" for m in snap["messages"]]
    assert any("conf.txt left out" in line for line in lines), lines
    assert not any("prov.txt left out" in line for line in lines), lines
    after = ran(client, done, row)
    assert after["decision"] is None, after
    assert "prov.txt on the branch holds a secret KOLONİ knows" in after["result"], after
    assert on_origin(origin, name_of(job)) == ""


def test_a_file_left_out_then_committed_by_its_agent_is_not_left_out_any_more(
    make_client, wait_run, repo
):
    # (a later turn of the job carries the earlier one's record: what it left out is its own)
    steps = [
        write("conf.txt", f"token = {TOKEN}\n", "w1"),
        write("other.py", "x = 1\n", "w2"),  # (a push row: the branch changes a file)
        command(MORNING, "c1"),
        text("one done"),
        # (the going-on turn, once the parked line ran)
        command("git add conf.txt", "c2"),
        command("git commit -m conf", "c3"),
        text("went on"),
    ]
    client, done, job, row, _origin = night(
        make_client, wait_run, repo, steps, {"GITHUB_TOKEN": TOKEN}
    )
    assert row is not None and "left out: conf.txt (" in row["what"], job
    (line,) = [one for one in waiting(client, done["id"]) if one["kind"] == "command"]
    assert decide(client, done["id"], line["id"], "run").status_code == 200
    cid = job["conversation_id"]
    until(lambda: len(chat(client, cid)["runs"]) == 2)
    until(lambda: chat(client, cid)["runs"][1]["status"] == "completed")
    after = row_now(client, done)
    assert after["tip"] != row["tip"] and "left out" not in after["what"], after


def test_files_named_as_secrets_are_left_out_and_one_its_agent_committed_asks_a_second_run(
    make_client, wait_run, repo, settings_env
):
    # (W-1's review, 0.1.10: .env.sample and api_keys.json went up, no secret KOLONİ knows in them)
    steps = [
        write(".env.sample", "API_KEY=a-real-looking-value\n", "w1"),
        write("api_keys.json", '{"k": "v"}\n', "w2"),
        write("tokens.py", "x = 1\n", "w3"),
        write("credentials.yaml", "k: v\n", "w4"),
        command("git add credentials.yaml", "c1"),
        command("git commit -m creds", "c2"),
        text("one done"),
    ]
    client, done, job, row, origin = night(make_client, wait_run, repo, steps, {})
    assert row is not None and "left out: .env.sample, api_keys.json (" in row["what"], job
    assert "credentials.yaml" not in row["what"], row
    snap = client.get(f"/api/conversations/{job['conversation_id']}").json()
    lines = [m["content"] or "" for m in snap["messages"]]
    assert any(".env.sample, api_keys.json left out" in line for line in lines), lines
    asked = push(client, done, row)
    named = PUSH_NAMED.format(files="credentials.yaml")
    assert asked.status_code == 409 and named in asked.json()["detail"]["notes"], asked.text
    assert ran(client, done, row)["decision"] == "run"
    pushed = at_origin(origin, job)
    assert "tokens.py" in pushed and "credentials.yaml" in pushed, pushed
    assert ".env.sample" not in pushed and "api_keys.json" not in pushed, pushed
    # (never deleted: in the job's worktree still)
    kept = Path(settings_env["KOLONI_RUNTIME_ROOT"]).rglob(".env.sample")
    assert [one.read_text() for one in kept] == ["API_KEY=a-real-looking-value\n"]


def test_a_secret_in_a_files_name_never_goes_up(make_client, wait_run, repo):
    # (MEDIUM-3: known only in the morning, so committed at night - its name holds it)
    steps = [write(f"out-{TOKEN}.txt", "nothing secret inside\n", "w1"), text("one done")]
    client, done, job, row, origin = night(
        make_client, wait_run, repo, steps, {"GITHUB_TOKEN": TOKEN}, before=False
    )
    after = ran(client, done, row)
    assert after["decision"] is None and "holds a secret KOLONİ knows" in after["result"], after
    assert on_origin(origin, name_of(job)) == ""


TITLE = "zz152 A1 push [x](http://evil.example/t) @octocat `tick` <b>b</b>\x1b[31m\u202e"


def test_a_task_name_mentions_nobody_in_what_goes_up():
    # (R2: the Scout writes task names - a mention there would reach a stranger on GitHub)
    said = titled(TITLE)
    assert "@\u200doctocat" in said and "@octocat" not in said
    assert not any(ord(ch) < 32 or ch == "\u202e" for ch in said)
    assert said.startswith("zz152 A1 push [x](http://evil.example/t) @") and "`tick`" in said


def test_the_pushed_commits_subject_is_the_task_name_mentioning_nobody(make_client, wait_run, repo):
    client, done, job, row, origin = night_with_origin(make_client, wait_run, repo)
    with client.app.state.session_factory() as session:
        session.get_one(BacklogTask, job["task_id"]).title = TITLE
        session.commit()
    assert ran(client, done, row)["decision"] == "run"
    ref = f"refs/heads/{name_of(job)}"
    got = subprocess.run(
        ["git", "-C", str(origin), "log", "-1", "--format=%s", ref], capture_output=True
    )
    subject = got.stdout.decode("utf-8").strip()  # (as written: a zero-width joiner in it)
    assert subject == titled(TITLE) and "@octocat" not in subject


def test_a_secret_where_the_jobs_commit_subject_is_cut_is_masked_whole(
    make_client, wait_run, repo, monkeypatch
):
    # (masked, then cut at 72 characters: its head went into the job's commit before)
    monkeypatch.setenv("NIGHT_TOKEN", TOKEN)
    plan = {"jobs": [{"title": "t" * 60 + " " + TOKEN}], "kept_out": []}
    steps = [write("out.txt", "work\n", "w1"), text("one done")]
    night(make_client, wait_run, repo, steps, {}, plan=plan)
    (branch,) = run(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/koloni/").split()
    subject = run(repo, "log", "-1", "--format=%s", branch)
    assert TOKEN[:8] not in subject and "t" * 60 in subject, subject
