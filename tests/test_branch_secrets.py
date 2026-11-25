"""S1, a team's branch: what KOLONİ commits on a branch and pushes with a pull request is looked at for
every secret KOLONİ knows (`raw.known`: its saved keys, the page's) - not only one given on a card in
the turn. A branch that holds one is not pushed: nothing goes up."""

from app import raw
from tests.test_agent_writes import write
from tests.test_dal_takim import (
    github,  # noqa: F401  (a fixture)
    own_test,
    pr_run,
    pushed_main,
    repo,  # noqa: F401  (a fixture)
    run,
)
from tests.test_parallel import until
from tests.test_take_in_scenarios import LONG, needs_git

pytestmark = needs_git
KEY = "sk-saved-provider-key-0123456789abcdef"


def test_a_secret_koloni_knows_never_goes_up_with_a_teams_pull_request(
    make_client, repo, github, monkeypatch
):
    bare, _log = github
    monkeypatch.setattr(raw, "_known", lambda fresh=False: raw.spellings([KEY]))
    client, cid, _run_id = pr_run(
        make_client,
        repo,
        lambda: pushed_main(repo),
        tests=[write("prov.txt", f"key = {KEY}\n", "w2"), own_test("TWO-agent")],
    )
    # (its card waits, saying why: the branch holds it - nothing of it went up)
    until(client, cid, lambda snap: "holds a secret" in str(snap["merges"]), timeout=LONG)
    assert KEY not in run(bare, "log", "--all", "-p", "--format=%B")
    assert run(bare, "for-each-ref", "refs/heads/koloni/") == ""
