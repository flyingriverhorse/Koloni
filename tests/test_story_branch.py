"""0.1.8 (the user, 24 Nov: "story per branch + worktree"): in a git project a story's tasks run
one after another on the story's own branch, each in a worktree of it, nothing of it in the
project; Close the story runs KOLONİ's check on the branch - it passes: the branch is merged (or
a pull request opened, the project's way); it fails: the branch waits and the story's last task
is stuck with why, Fix it going on on the branch. A task of no story has a small branch of its
own, merged at its end as a team's is. No git: no branch, the work in the project."""

from tests.test_agent_writes import write
from tests.test_backlog import setup
from tests.test_backlog_auto import until
from tests.test_chat_flow import text
from tests.test_dal_takim import repo, worktrees  # noqa: F401  (a fixture)
from tests.test_git_view import run
from tests.test_take_in_scenarios import needs_git, root_runs
from tests.test_todo_chat import do_in_chat, ended, snap, story, task

pytestmark = needs_git
OWN = {"Origin": "http://127.0.0.1:8790"}


def chat_at(client, pid, mode="full_auto"):
    """A chat of the project at `mode`, whose Orchestrator writes the files itself."""
    assert client.patch(f"/api/projects/{pid}", json={"lead_work": "itself"}).status_code == 200
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    answer = client.patch(f"/api/conversations/{cid}", json={"permission_mode": mode}, headers=OWN)
    assert answer.status_code == 200, answer.text
    return cid


def branches(repo):
    return [line.strip(" *+") for line in run(repo, "branch", "--list", "koloni/*").splitlines()]


def two_tasks(make_client, repo, *more, second=None, project=None):
    """A story of two tasks done in a chat at Full auto: the first writes one.py, the second
    two.py (or `second`); `project`: the project's settings first."""
    client, _model = make_client(
        [
            write("one.py", "1\n", "w1"),
            text("one done"),
            second or write("two.py", "2\n", "w2"),
            text("two done"),
            *more,
        ]
    )
    pid, (t1, t2) = setup(client, repo, "one", "two")
    if project:
        assert client.patch(f"/api/projects/{pid}", json=project).status_code == 200
    s = story(client, pid, "Parser", t1, t2)
    cid = chat_at(client, pid)
    do_in_chat(client, pid, [t1, t2], cid)
    ended(client, cid, 2)
    return client, pid, cid, s, (t1, t2)


def test_a_storys_tasks_go_on_on_its_branch_and_close_merges_it(make_client, repo):
    client, pid, cid, s, (t1, t2) = two_tasks(make_client, repo)
    assert [r["status"] for r in snap(client, cid)["runs"]] == ["completed", "completed"]
    # one branch for the story, holding both tasks' work; nothing of it in the project yet
    (branch,) = branches(repo)
    assert branch.startswith("koloni/parser-")
    assert run(repo, "show", f"{branch}:one.py") == "1"
    assert run(repo, "show", f"{branch}:two.py") == "2"  # (on top of the first)
    assert not (repo / "one.py").exists() and not (repo / "two.py").exists()
    assert len(worktrees(repo)) == 1  # (its worktree goes with each turn; the branch stays)
    for task_id in (t1, t2):
        client.patch(f"/api/backlog/{task_id}", json={"status": "done"})
    closed = client.patch(f"/api/stories/{s}", json={"closed": True})
    assert closed.status_code == 200 and closed.json()["closed_at"] is None  # (its check first)
    until(lambda: client.get(f"/api/projects/{pid}/stories").json()["stories"][0]["closed_at"])
    assert (repo / "one.py").read_text() == "1\n" and (repo / "two.py").read_text() == "2\n"
    assert branches(repo) == [] and len(worktrees(repo)) == 1
    closing = snap(client, cid)["runs"][-1]
    assert closing["task_id"] is None and closing["status"] == "completed"
    assert closing["topic_id"] == snap(client, cid)["runs"][0]["topic_id"]  # (the story's topic)


def test_a_check_that_fails_at_close_leaves_the_branch_and_its_last_task_stuck(make_client, repo):
    # (the second task writes a test of its own that fails: the check at Close runs it)
    failing = write("test_two.py", "def test_two():\n    assert False\n", "w2")
    client, pid, cid, s, (t1, t2) = two_tasks(
        make_client, repo, text("fixed"), second=failing, project=root_runs()
    )
    for task_id in (t1, t2):
        client.patch(f"/api/backlog/{task_id}", json={"status": "done"})
    client.patch(f"/api/stories/{s}", json={"closed": True})
    until(lambda: task(client, t2)["status"] == "blocked")
    assert "did not pass on the story's branch" in task(client, t2)["stuck"]
    assert client.get(f"/api/projects/{pid}/stories").json()["stories"][0]["closed_at"] is None
    (branch,) = branches(repo)
    assert not (repo / "one.py").exists()
    # Fix it: one more round on the story's branch, in the task's topic
    assert client.post(f"/api/backlog/{t2}/fix", headers=OWN).status_code == 200
    runs = ended(client, cid, 4)
    assert runs[-1]["task_id"] == t2 and runs[-1]["topic_id"] == runs[1]["topic_id"]
    assert branches(repo) == [branch]


def test_a_task_of_no_story_has_a_branch_of_its_own_merged_at_its_end(make_client, repo):
    client, _model = make_client([write("lone.py", "x\n"), text("done")])
    pid, (a,) = setup(client, repo, "lone")
    cid = chat_at(client, pid)
    do_in_chat(client, pid, [a], cid)
    (turn,) = ended(client, cid, 1)
    assert turn["status"] == "completed", turn["error"]
    (merge,) = snap(client, cid)["merges"]
    assert merge["branch"]["name"].startswith("koloni/lone-") and merge["status"] == "applied"
    assert (repo / "lone.py").read_text() == "x\n" and branches(repo) == []
    assert task(client, a)["status"] == "review"


def test_with_no_git_a_storys_tasks_work_in_the_project_and_close_at_once(make_client, project_dir):
    client, _model = make_client([write("one.py", "1\n"), text("one done")])
    pid, (t1,) = setup(client, project_dir, "one")
    s = story(client, pid, "Parser", t1)
    cid = chat_at(client, pid)
    do_in_chat(client, pid, [t1], cid)
    ended(client, cid, 1)
    assert (project_dir / "one.py").read_text() == "1\n"
    client.patch(f"/api/backlog/{t1}", json={"status": "done"})
    closed = client.patch(f"/api/stories/{s}", json={"closed": True}).json()
    assert closed["closed_at"] and closed["state"] == "done"


def test_closed_again_after_its_branch_went_in_it_closes_at_once(make_client, repo):
    client, pid, cid, s, (t1, t2) = two_tasks(make_client, repo)
    for task_id in (t1, t2):
        client.patch(f"/api/backlog/{task_id}", json={"status": "done"})
    client.patch(f"/api/stories/{s}", json={"closed": True})
    until(lambda: client.get(f"/api/projects/{pid}/stories").json()["stories"][0]["closed_at"])
    turns = len(snap(client, cid)["runs"])
    # reopened, then closed again: its branch went in already - no turn, done at once
    assert client.patch(f"/api/stories/{s}", json={"closed": False}).json()["closed_at"] is None
    again = client.patch(f"/api/stories/{s}", json={"closed": True}).json()
    assert again["closed_at"] and len(snap(client, cid)["runs"]) == turns


def test_a_story_whose_branch_was_deleted_by_hand_closes_all_the_same(make_client, repo):
    client, pid, cid, s, (t1, t2) = two_tasks(make_client, repo)
    (branch,) = branches(repo)
    run(repo, "branch", "-D", branch)
    for task_id in (t1, t2):
        client.patch(f"/api/backlog/{task_id}", json={"status": "done"})
    client.patch(f"/api/stories/{s}", json={"closed": True})
    until(lambda: client.get(f"/api/projects/{pid}/stories").json()["stories"][0]["closed_at"])
    assert branches(repo) == [] and len(worktrees(repo)) == 1


def test_a_lone_tasks_fix_round_goes_on_on_its_branch(make_client, repo):
    from app.model_client import ModelUnavailable
    from tests.test_spawn import call, step

    client, _model = make_client(
        [
            write("lone.py", "x = 1\n"),
            ModelUnavailable("model server unreachable: refused"),
            step(call("read_file", {"path": "lone.py"}, "r1")),
            text("done"),
        ]
    )
    pid, (a,) = setup(client, repo, "lone")
    cid = chat_at(client, pid)
    do_in_chat(client, pid, [a], cid)
    runs = ended(client, cid, 2)
    assert [r["status"] for r in runs] == ["failed", "completed"], [r["error"] for r in runs]
    (read,) = [c for c in snap(client, cid)["tool_calls"] if c["name"] == "read_file"]
    assert "x = 1" in (read["result"] or "")  # (its first turn's work, kept on its branch)
    assert (repo / "lone.py").read_text() == "x = 1\n" and branches(repo) == []


def test_the_storys_next_task_reads_what_the_one_before_left_on_its_branch(make_client, repo):
    from tests.test_spawn import call, step

    read = step(call("read_file", {"path": "one.py"}, "r1"))
    client, pid, cid, _s, _ids = two_tasks(make_client, repo, text("two done"), second=read)
    (seen,) = [c for c in snap(client, cid)["tool_calls"] if c["name"] == "read_file"]
    assert seen["result"] and "1" in seen["result"] and not (repo / "one.py").exists()
