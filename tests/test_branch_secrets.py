"""S1 and its review (MEDIUM-2), a team's branch: what KOLONİ commits on it and pushes with a pull
request is looked at for one set of secrets (`secret_set.checked`) - the turn's, the environment's,
the values the projects pass to commands, and those KOLONİ keeps (`raw.known`). KOLONİ's own commit
leaves a file holding one out, the card says why, and the rest goes as the pull request; one
KOLONİ cannot read as a secret by its name - an ordinary MCP value - stays readable in a kept
reason (L-2)."""

from app import main, masking, raw
from app.db.models import McpServer
from tests.keyed import OWN
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
PASSED = "pv-0123456789abcdef-passed"
TOKEN = "tok-0123456789abcdef-mcp-value"


def left_out_of_the_pull_request(make_client, repo, bare, secret):
    """A Coder writes `secret` into keys.txt beside its work, which goes as a pull request: what
    went up to `bare`, once its card said the file was left out."""
    client, cid, _run_id = pr_run(
        make_client,
        repo,
        lambda: pushed_main(repo),
        tests=[write("keys.txt", f"k = {secret}\n", "w2"), own_test("TWO-agent")],
    )
    until(client, cid, lambda s: "holds a secret KOLONİ knows" in str(s["merges"]), timeout=LONG)
    until(client, cid, lambda _s: run(bare, "for-each-ref", "refs/heads/koloni/"), timeout=LONG)
    return run(bare, "log", "--all", "-p")


def test_a_secret_koloni_knows_never_goes_up_with_a_teams_pull_request(
    make_client, repo, github, monkeypatch
):
    bare, _log = github
    monkeypatch.setattr(raw, "_known", lambda fresh=False: raw.spellings([KEY]))
    pushed = left_out_of_the_pull_request(make_client, repo, bare, KEY)
    assert KEY not in pushed and "TWO-agent" in pushed


def test_a_value_the_project_passes_never_goes_up_with_a_teams_pull_request(
    make_client, repo, github, monkeypatch
):
    # (MEDIUM-2: what a project passes to its commands is exactly what an agent can see)
    bare, _log = github
    monkeypatch.setattr(main, "passed_values", lambda _factory: [PASSED])  # (`secret_set.passed`)
    pushed = left_out_of_the_pull_request(make_client, repo, bare, PASSED)
    assert PASSED not in pushed and "TWO-agent" in pushed


def test_the_values_a_project_passes_are_read_from_its_settings(client, tmp_path, monkeypatch):
    monkeypatch.setenv("MY_PASSED_VALUE", PASSED)
    root = tmp_path / "p"
    root.mkdir()
    pid = client.post("/api/projects", json={"root_path": str(root)}).json()["id"]
    changed = client.patch(
        f"/api/projects/{pid}", json={"pass_env": "MY_PASSED_VALUE"}, headers=OWN
    )
    assert changed.status_code == 200, changed.text
    assert main.passed_values(client.app.state.session_factory) == [PASSED]


def test_an_ordinary_mcp_value_stays_readable_in_a_kept_reason(client):
    # (L-2: masked where text is shown - the raw stream -, never in a reason KOLONİ keeps)
    with client.app.state.session_factory() as session:
        session.add(McpServer(name="srv", command=["x"], env={"NODE_ENV": "production"}))
        session.add(McpServer(name="gh", command=["x"], env={"GITHUB_TOKEN": TOKEN}))
        session.commit()
    raw.read_again()
    assert masking.masked("deploy to production") == "deploy to production"
    assert raw.hidden("deploy to production") == f"deploy to {raw.HIDDEN}"
    assert TOKEN not in masking.masked(f"use {TOKEN}")
