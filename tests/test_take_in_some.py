"""Take in of some of a card's files (T93-01: `files` was taken for nothing, and every file went
in): only the chosen ones are taken; the rest stay on the card - a turn's still asked about, a
kept copy's still kept - for Take in or Discard."""

import pytest

from app import copies
from tests.test_branch_snapshot import (  # noqa: F401  (fixtures)
    line,
    needs_merge_base,
    numbered,
    repo,
    run,
    runtime,
    worktrees,
)
from tests.test_chat_flow import text
from tests.test_claim_scenarios import write
from tests.test_copy_later_scenarios import again
from tests.test_copy_runner import at_work, card_of, kept_folders
from tests.test_copy_scenarios import files, one, seen
from tests.test_parallel import until
from tests.test_spawn import step
from tests.test_take_in_scenarios import ORIGIN, needs_git, repository

TWO = [step(write("a.txt", "A")), step(write("b.txt", "B", "w2"))]


def some(client, merge, *paths, **more):
    return client.post(
        f"/api/merges/{merge['id']}/approve",
        json={"files": list(paths), "shown": seen(merge), **more},
    )


def test_a_turns_card_takes_only_the_files_chosen_and_asks_on_about_the_rest(
    make_client, wait_run, project_dir
):
    client, _model, cid, run_id = one(
        make_client, project_dir, [*TWO, text("A done")], permission_mode="ask"
    )
    snap = until(client, cid, lambda s: [m["status"] for m in s["merges"]] == ["pending"])
    (card,) = snap["merges"]
    taken = some(client, card, "a.txt")
    assert taken.status_code == 200, taken.text
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"
    assert not (project_dir / "b.txt").exists()
    # The card is still asked about, with what is left on it.
    card = until(client, cid, lambda s: files(s["merges"][0]).get("a.txt") == "applied")["merges"][
        0
    ]
    assert card["status"] == "pending" and files(card) == {"a.txt": "applied", "b.txt": "ready"}
    # Discard the rest: what was taken stays taken, and the card says so.
    assert client.post(f"/api/merges/{card['id']}/reject").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert snap["merges"][0]["status"] == "applied"
    assert (project_dir / "a.txt").exists() and not (project_dir / "b.txt").exists()


def test_a_kept_copy_takes_only_the_files_chosen_and_keeps_the_rest(settings_env, project_dir):
    cid = at_work(settings_env, project_dir, TWO)
    with again(settings_env) as client:
        card = card_of(client, cid)
        taken = some(client, card, "b.txt")
        assert taken.status_code == 200, taken.text
        assert (project_dir / "b.txt").read_text(encoding="utf-8") == "B"
        assert not (project_dir / "a.txt").exists()
        card = card_of(client, cid)
        assert card["status"] == "kept" and files(card) == {"a.txt": "ready", "b.txt": "applied"}
        assert kept_folders(settings_env) != []
        rest = client.post(f"/api/merges/{card['id']}/approve", json={"shown": seen(card)})
        assert rest.status_code == 200 and rest.json()["status"] == "applied", rest.text
        assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"
        assert kept_folders(settings_env) == []


def test_files_that_are_not_the_cards_to_take_are_refused_not_ignored(settings_env, project_dir):
    cid = at_work(settings_env, project_dir, TWO)
    with again(settings_env) as client:
        card = card_of(client, cid)
        for chosen, said in (
            ([], "choose at least one file"),
            (["c.txt"], "not on this card to take: c.txt"),
        ):
            refused = some(client, card, *chosen)
            assert refused.status_code == 409 and said in refused.json()["detail"], refused.text
        check = client.post(f"/api/merges/{card['id']}/check", json={"files": ["a.txt"]})
        assert check.status_code == 409, check.text
        assert not (project_dir / "a.txt").exists() and not (project_dir / "b.txt").exists()
        assert card_of(client, cid)["status"] == "kept"


@needs_git
@pytest.mark.parametrize("offered", [True, False])
def test_a_turns_card_discarded_after_some_was_taken_offers_the_commit_of_that(
    make_client, wait_run, project_dir, offered
):
    # N10: the second session saw no commit (`commit_state` null) in a project with "Save each
    # sub-agent's work as a git commit" off, its default - as after any Take in. On, it is offered.
    from tests.test_take_in_scenarios import card, start

    repository(project_dir)
    client, _pid, cid, run_id = start(
        make_client,
        project_dir,
        [*TWO, text("A done")],
        project={"git_commit": offered},
        permission_mode="ask",
    )
    assert some(client, card(client, cid), "a.txt").status_code == 200
    merge = until(client, cid, lambda s: files(s["merges"][0]).get("a.txt") == "applied")["merges"][
        0
    ]
    assert merge["status"] == "pending" and merge["commit"] is None
    assert client.post(f"/api/merges/{merge['id']}/reject").status_code == 200
    (merge,) = wait_run(client, cid, run_id)["merges"]
    assert merge["status"] == "applied" and (merge["commit"] is None) is not offered, merge
    if not offered:
        return
    assert merge["commit"]["state"] == "offered", merge["commit"]
    made = client.post(f"/api/merges/{merge['id']}/commit", json={"message": "m"}).json()
    assert made["commit"]["state"] == "committed", made
    assert "a.txt" in made["commit"]["holds"] and "b.txt" not in made["commit"]["holds"]


@needs_git
@pytest.mark.parametrize("then", ["the rest", "discard"])
@pytest.mark.parametrize("restart", [False, True])
def test_a_kept_card_taken_in_two_steps_commits_the_agents_change_alone(
    settings_env, project_dir, then, restart
):
    # L1: what each file held before and after it was taken is kept for its commit - in memory
    # alone, it was lost with a kept copy's first step, and the commit took a.txt whole, the
    # user's own edits in it said to be the agent's. Kept on disk: a restart between keeps it.
    repository(project_dir)
    cid = at_work(settings_env, project_dir, TWO)

    def rest(client, card) -> None:
        if then == "the rest":
            done = client.post(f"/api/merges/{card['id']}/approve", json={"shown": seen(card)})
        else:
            done = client.post(f"/api/merges/{card['id']}/reject")
        assert done.status_code == 200 and done.json()["status"] == "applied", done.text
        assert card_of(client, cid)["commit"]["state"] == "offered"
        made = client.post(f"/api/merges/{card['id']}/commit", json={"message": "m"}).json()
        assert made["commit"]["state"] == "committed", made
        assert not made["commit"]["notes"], made["commit"]["notes"]
        assert ("b.txt" in made["commit"]["holds"]) == (then == "the rest")

    with again(settings_env) as client:
        pid = client.get(f"/api/conversations/{cid}").json()["conversation"]["project_id"]
        assert client.patch(f"/api/projects/{pid}", json={"git_commit": True}).status_code == 200
        assert some(client, card_of(client, cid), "a.txt").status_code == 200
        card = card_of(client, cid)
        assert card["status"] == "kept" and card["commit"] is None
        if not restart:
            rest(client, card)
    if restart:
        with again(settings_env) as client:
            rest(client, card)


@needs_merge_base
def test_a_kept_branch_copy_takes_no_files_alone(make_client, wait_run, repo):  # noqa: F811
    # L3: a branch's copy kept over a crash has a card with no `branch`: some of its files were
    # taken, and its Discard then dropped the branch. A branch goes in whole, kept or not.
    from app.agent import recover_copies
    from app.db.models import Agent

    numbered(repo)
    client, _model = make_client([text("hi")])
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(repo)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()[
        "run"
    ]["id"]
    (lead,) = wait_run(client, cid, run_id)["agents"]
    root = client.app.state.settings.runtime_root
    copy = copies.make_branch(repo, root, lead["id"], "x")
    with client.app.state.session_factory() as session:
        session.get_one(Agent, lead["id"]).copy = {
            "state": "own",
            "tree": str(copy.root),
            "on_branch": copy.branch,
            "start": list(copy.start),
            "snapshot": copy.snapshot_sha,
        }
        session.commit()
    line(copy.root, 9, "9-agent")
    (copy.root / "new.txt").write_text("new\n", encoding="utf-8")
    recover_copies(client.app.state.session_factory, root)
    (card,) = client.get(f"/api/conversations/{cid}").json()["merges"]
    assert card["status"] == "kept" and card["branch"] is None
    refused = some(client, card, "new.txt")
    assert refused.status_code == 409, refused.text
    assert "all of it goes here" in refused.json()["detail"]
    assert not (repo / "new.txt").exists()
    assert "koloni/x" in run(repo, "branch", "--list", "koloni/*") and len(worktrees(repo)) == 2
