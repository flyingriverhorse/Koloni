"""☾ Away, a job's push in the morning (0.1.9): where the project has an origin, a done job's branch
waits under Waiting for you; Run pushes ONE commit by KOLONİ (`git.push_one`) whose tree is the tip
on record - never the user's uncommitted work -, a pull request where the project's way says so.
H3: a branch moved or gone since, a secret KOLONİ knows in it, a name origin has, main not pushed -
nothing goes up, the row waits; git's config changed, a second Run. Reject, Take in and Discard
close the row. Every repository here is made by the test, in its folder - origin a bare one."""

import pytest
from sqlalchemy import select

from app import git, parked
from app.agent.away_branch_mixin import PUSH_CONFIG
from app.db.models import Agent
from app.model_client import ModelUnavailable
from tests.test_agent_writes import edit, write
from tests.test_away_branch_scenarios import (
    branch_night,
    name_of,
    origin_of,
    repo,  # noqa: F401  (a fixture)
)
from tests.test_away_scenarios import ORIGIN
from tests.test_away_waiting import waiting
from tests.test_chat_flow import text
from tests.test_git_view import run as git_run
from tests.test_take_in_scenarios import needs_git

pytestmark = needs_git

STEPS = [edit(), write("new.txt", "new\n", "w2"), text("one done")]


def night_with_origin(make_client, wait_run, repo, steps=STEPS, before=None, **project):
    """A night whose one job leaves `steps`' work on its branch, the project's main on a bare
    origin (`before`: what is done to the project first): (client, the night, the job, its push
    row, origin)."""
    origin = origin_of(repo)
    if before is not None:
        before(repo)
    client, _model, _pid, done, job = branch_night(make_client, wait_run, repo, steps, **project)
    rows = [one for one in waiting(client, done["id"]) if one["kind"] == "push"]
    return client, done, job, (rows or [None])[0], origin


def push(client, done, row, word="run", seen=()):
    return client.post(
        f"/api/away/{done['id']}/waiting/{row['id']}",
        json={"word": word, "seen": list(seen)},
        headers=ORIGIN,
    )


def row_now(client, done):
    (row,) = [one for one in waiting(client, done["id"]) if one["kind"] == "push"]
    return row


def on_origin(origin, name):
    return git_run(origin, "branch", "--list", name)


def test_run_pushes_one_commit_by_koloni_whose_tree_is_the_tips(make_client, wait_run, repo):
    client, done, job, row, origin = night_with_origin(make_client, wait_run, repo)
    name, tip = name_of(job), job["branch"]["tip"]
    main = git_run(origin, "rev-parse", "main")
    assert row["closed"] is None and row["decision"] is None
    assert push(client, done, row).status_code == 200
    row = row_now(client, done)
    assert row["decision"] == "run" and row["result"].startswith(f"Pushed {name} to origin as ")
    sha = git_run(origin, "rev-parse", f"refs/heads/{name}")
    assert git_run(origin, "rev-parse", f"{sha}^{{tree}}") == git_run(
        repo, "rev-parse", f"{tip}^{{tree}}"
    )
    assert git_run(origin, "log", "-1", "--format=%ae %P", sha) == f"koloni@localhost {main}"
    with client.app.state.session_factory() as session:
        pushed = [
            agent.copy["away"]["push"]
            for agent in session.scalars(select(Agent))
            if "push" in ((agent.copy or {}).get("away") or {})
        ]
    assert [(one["state"], one["sha"]) for one in pushed] == [("pushed", sha)]
    # (the branch and its worktree stay: Take in is still the user's)
    assert git_run(repo, "rev-parse", name) == tip and job["kept"]


def test_a_dirty_start_does_not_send_the_users_file(make_client, wait_run, repo):
    def dirty(repo):
        (repo / "mine.txt").write_text("USER-UNCOMMITTED\n")

    client, done, job, row, origin = night_with_origin(make_client, wait_run, repo, before=dirty)
    asked = push(client, done, row)
    assert asked.status_code == 409
    notes = asked.json()["detail"]["notes"]
    assert any("began from your folder" in one for one in notes)
    assert push(client, done, row, seen=notes).status_code == 200
    sent = git_run(origin, "ls-tree", "-r", "--name-only", f"refs/heads/{name_of(job)}").split()
    assert "new.txt" in sent and "mine.txt" not in sent


def tip_moved(repo, name):
    later = git_run(repo, "commit-tree", f"{name}^{{tree}}", "-p", name, "-m", "later")
    git_run(repo, "update-ref", f"refs/heads/{name}", later)


def branch_deleted(repo, name):
    git_run(repo, "update-ref", "-d", f"refs/heads/{name}")


def name_on_origin(repo, name):
    other = git_run(repo, "commit-tree", "HEAD^{tree}", "-m", "someone else's")
    git_run(repo, "push", "-q", "origin", f"{other}:refs/heads/{name}")


def main_unpushed(repo):
    (repo / "local.txt").write_text("not pushed\n")
    git_run(repo, "add", "local.txt")
    git_run(repo, "commit", "-qm", "local, not pushed")


@pytest.mark.parametrize(
    ("before", "after", "want"),
    [
        (None, tip_moved, "moved since the job ended"),
        (None, branch_deleted, "is gone: nothing was pushed"),
        (None, name_on_origin, "git push failed"),
        (main_unpushed, None, "push main first"),
    ],
    ids=["tip_moved", "branch_deleted", "name_on_origin", "main_unpushed"],
)
def test_h3_refuses_and_pushes_nothing(make_client, wait_run, repo, before, after, want):
    client, done, job, row, origin = night_with_origin(make_client, wait_run, repo, before=before)
    name = name_of(job)
    if after is not None:
        after(repo, name)
    was = on_origin(origin, name)
    answered = push(client, done, row)
    if answered.status_code == 409:  # (main_unpushed: your commits are noted first - then refused)
        answered = push(client, done, row, seen=answered.json()["detail"]["notes"])
    assert answered.status_code == 200, answered.text
    row = row_now(client, done)
    # (the row waits again, why on it - to try once that is set right)
    assert row["decision"] is None and want in row["result"], row["result"]
    assert on_origin(origin, name) == was


def test_a_secret_koloni_knows_in_what_goes_up_is_refused(make_client, wait_run, repo, monkeypatch):
    secret = "tok-0123456789abcdef-the-users-own"
    steps = [write("new.txt", f"key = {secret}\n", "w2"), text("one done")]
    client, done, job, row, origin = night_with_origin(make_client, wait_run, repo, steps=steps)
    monkeypatch.setenv("KOLONI_TEST_API_TOKEN", secret)  # (known by the morning's process)
    assert push(client, done, row).status_code == 200
    row = row_now(client, done)
    assert row["decision"] is None and "holds a secret KOLONİ knows" in row["result"]
    assert on_origin(origin, name_of(job)) == ""


def test_config_changed_asks_a_second_click(make_client, wait_run, repo):
    client, done, job, row, origin = night_with_origin(make_client, wait_run, repo)
    git_run(repo, "config", "koloni.test", "changed")
    asked = push(client, done, row)
    assert asked.status_code == 409 and asked.json()["detail"]["notes"] == [PUSH_CONFIG]
    assert row_now(client, done)["decision"] is None and on_origin(origin, name_of(job)) == ""
    assert push(client, done, row, seen=[PUSH_CONFIG]).status_code == 200
    assert row_now(client, done)["decision"] == "run" and on_origin(origin, name_of(job))


def test_reject_keeps_the_branch_and_closes_the_row(make_client, wait_run, repo):
    client, done, job, row, origin = night_with_origin(make_client, wait_run, repo)
    assert push(client, done, row, "reject").status_code == 200
    row = row_now(client, done)
    assert row["decision"] == "reject" and row["result"].endswith("stays as it is")
    assert git_run(repo, "rev-parse", name_of(job)) == job["branch"]["tip"]
    assert on_origin(origin, name_of(job)) == ""


@pytest.mark.parametrize("word", ["approve", "reject"])
def test_take_in_all_or_discard_deletes_the_branch_and_closes_the_row(
    make_client, wait_run, repo, word
):
    client, done, job, row, _origin = night_with_origin(make_client, wait_run, repo)
    (kept,) = job["kept"]
    assert client.post(f"/api/merges/{kept}/{word}", headers=ORIGIN).status_code == 200
    assert git_run(repo, "branch", "--list", name_of(job)) == ""
    assert row_now(client, done)["closed"] == parked.PUSH_TAKEN
    assert push(client, done, row).status_code == 409
    if word == "approve":
        assert (repo / "new.txt").read_text() == "new\n"


def test_a_pull_request_only_where_finish_way_says(make_client, wait_run, repo, monkeypatch):
    opened = []
    monkeypatch.setattr(git, "pr_ready", lambda project: ("owner/repo", None))

    def open_pr(project, repo_name, branch, into, title, body, folder):
        opened.append((repo_name, branch, into, title))
        return "https://github.com/owner/repo/pull/7"

    monkeypatch.setattr(git, "open_pr", open_pr)
    client, done, job, row, _origin = night_with_origin(
        make_client, wait_run, repo, finish_way="pull_request"
    )
    assert row["what"].endswith(" · opens a pull request into main")
    assert push(client, done, row).status_code == 200
    assert opened == [("owner/repo", name_of(job), "main", "one")]
    assert row_now(client, done)["result"].endswith(
        "pull request: https://github.com/owner/repo/pull/7"
    )


def test_no_push_row_for_a_job_that_failed(make_client, wait_run, repo):
    client, done, job, row, _origin = night_with_origin(
        make_client,
        wait_run,
        repo,
        steps=[edit(), ModelUnavailable("refused"), ModelUnavailable("refused again")],
    )
    assert job["state"] == "failed" and row is None
