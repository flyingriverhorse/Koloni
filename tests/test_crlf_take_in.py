"""T1: a job's branch in a repository git checks out with CRLF (`core.autocrlf=true`, git's Windows
default) where the project's files are LF: git stores the two alike, so the project's file is not
"changed on both sides" - Take in is offered, and what it writes keeps the project's own line ends.
A real change of the project's meanwhile is still one. (`core.autocrlf` is read on every platform:
a checkout with it true writes CRLF on Linux too.)"""

import pytest

from tests.test_agent_writes import edit
from tests.test_away_branch_scenarios import branch_night, repo  # noqa: F401  (a fixture)
from tests.test_chat_flow import text
from tests.test_git_view import run as git_run
from tests.test_take_in_scenarios import needs_git

pytestmark = needs_git
MINE = b"print('hi')\nprint('mine')\n"


def night(make_client, wait_run, repo, autocrlf, meanwhile=None):
    """A night whose job edits hello.py on its branch, git's `core.autocrlf` as given (`meanwhile`:
    what the user does after it): (client, the job's chat, its kept work's card, its files by
    path)."""
    git_run(repo, "config", "core.autocrlf", autocrlf)
    assert git_run(repo, "status", "--porcelain") == ""
    client, _model, _pid, _done, job = branch_night(
        make_client, wait_run, repo, [edit(), text("one done")]
    )
    if meanwhile is not None:
        meanwhile(repo)
    snap = client.get(f"/api/conversations/{job['conversation_id']}").json()
    (merge,) = snap["merges"]
    return client, job["conversation_id"], merge, {one["path"]: one for one in merge["files"]}


@pytest.mark.parametrize("autocrlf", ["true", "false"])
def test_line_ends_alone_are_no_change_of_the_projects_and_take_in_keeps_them(
    make_client, wait_run, repo, autocrlf
):
    client, _cid, merge, files = night(make_client, wait_run, repo, autocrlf)
    assert set(files) == {"hello.py"} and files["hello.py"]["state"] == "ready", files
    assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 200
    assert (repo / "hello.py").read_bytes() == b"print('hello')\n"  # (LF, as the project's was)


def test_a_real_change_of_the_projects_is_still_a_conflict(make_client, wait_run, repo):
    client, cid, merge, _files = night(
        make_client, wait_run, repo, "true", lambda repo: (repo / "hello.py").write_bytes(MINE)
    )
    client.post(f"/api/merges/{merge['id']}/approve")  # (shown again: nothing taken)
    assert (repo / "hello.py").read_bytes() == MINE
    (again,) = client.get(f"/api/conversations/{cid}").json()["merges"]
    assert {one["path"]: one["state"] for one in again["files"]} == {"hello.py": "conflict"}
