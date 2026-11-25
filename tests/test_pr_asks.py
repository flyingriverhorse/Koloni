"""A branch's pull request asks origin what it holds (`AgentRunner._pr_asks`) only once its way is
a pull request - never at the end of a turn that may still be a merge - and once for both looks;
where origin does not answer, its card says that, not a count of commits it could not make."""

from app import git
from tests.test_chat_flow import text
from tests.test_dal_takim import github, on_branch, repo  # noqa: F401  (fixtures)
from tests.test_git_view import run as git_run
from tests.test_spawn import step
from tests.test_take_in_scenarios import card, edit, needs_git, root_runs

pytestmark = needs_git


def counted(monkeypatch):
    """Each time origin is asked what it holds (`git._origin_holds`, its ls-remote)."""
    asked = []
    real = git._origin_holds

    def holds(*args, **kwargs):
        asked.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(git, "_origin_holds", holds)
    return asked


def test_a_turn_end_whose_way_is_not_chosen_asks_origin_nothing(
    make_client, repo, github, monkeypatch
):
    asked = counted(monkeypatch)
    client, cid, _run_id = on_branch(
        make_client, repo, [step(edit("two", "TWO-agent")), text("A done")]
    )
    merge = card(client, cid)  # (GitHub's: the card asks which way)
    assert merge["branch"]["ask_way"] and asked == []


def test_where_origin_does_not_answer_the_card_says_so(make_client, repo, github, monkeypatch):
    bare, _log = github
    git_run(repo, "config", "remote.origin.pushurl", str(bare.parent / "gone.git"))
    asked = counted(monkeypatch)
    client, cid, _run_id = on_branch(
        make_client,
        repo,
        [step(edit("two", "TWO-agent")), text("A done")],
        project=root_runs(finish_way="pull_request"),
    )
    merge = card(client, cid)
    assert merge["branch"]["note"].startswith(
        "origin did not answer, so KOLONİ could not check what it holds ("
    )
    assert len(asked) == 1  # (once, for both of its looks)
