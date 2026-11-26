"""S1 and its review (MEDIUM-2), a team's branch: what KOLONİ commits on it and pushes with a pull
request is looked at for one set of secrets (`secret_set.checked`) - the turn's, the environment's
and those KOLONİ keeps (`raw.known`), and the token or password each holds alone (M-B). KOLONİ's own
commit leaves a file holding one out, the card says why, and the rest goes as the pull request; one
KOLONİ cannot read as a secret by its name - an ordinary MCP value - stays readable in a kept
reason (L-2)."""

from types import SimpleNamespace

import pytest

from app import masking, raw, secret_set
from app.agent import merge
from app.away_branch import team_pr_body, titled
from app.commands import OutputMask
from app.db.models import McpServer
from tests.test_agent_writes import write
from tests.test_chat_flow import text
from tests.test_claim_scenarios import write as write_file  # (as a call: `step`)
from tests.test_dal_takim import (
    github,  # noqa: F401  (a fixture)
    on_branch,
    own_test,
    pr_run,
    pushed_main,
    repo,  # noqa: F401  (a fixture)
    run,
)
from tests.test_parallel import until
from tests.test_spawn import call, step
from tests.test_take_in_scenarios import LONG, card, needs_git

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


def test_an_environment_secret_never_goes_up_with_a_teams_pull_request(
    make_client, repo, github, monkeypatch
):
    # (MEDIUM-2: what a project passes to its commands - pass_env - is of the environment)
    bare, _log = github
    monkeypatch.setenv("DEPLOY_TOKEN", PASSED)
    pushed = left_out_of_the_pull_request(make_client, repo, bare, PASSED)
    assert PASSED not in pushed and "TWO-agent" in pushed


def test_a_word_in_the_environment_leaves_nothing_out(client, monkeypatch):
    # (M-B: pass_env=NODE_ENV, NODE_ENV=production - config.py was left out of the commit)
    monkeypatch.setenv("NODE_ENV", "production")
    raw.read_again()
    assert "production" not in secret_set.checked()


@pytest.fixture
def environment(monkeypatch):
    """The process's environment as given; nothing KOLONİ keeps."""

    def use(env):
        monkeypatch.setattr(secret_set.os, "environ", dict(env))
        monkeypatch.setattr(raw, "known", lambda: [])

    return use


def left_out(tmp_path, text, secrets) -> bool:
    """Whether KOLONİ's own commit leaves a file holding `text` out, `secrets` checked."""
    (tmp_path / "f.txt").write_text(text, encoding="utf-8")
    copy = SimpleNamespace(
        here=lambda path: tmp_path / path, every_secret=lambda: secrets, secrets=lambda: []
    )
    return bool(merge._secret_in(copy, "f.txt", True))


def test_an_addresss_password_and_a_token_in_a_longer_value_are_checked_alone(
    environment, tmp_path
):
    # (M-B: only the whole value was - a settings.py with the password, an .npmrc with the token
    # went into the commit)
    token = "ghp_" + "Q1" * 18
    environment(
        {
            "DATABASE_URL": "postgres://app:Sup3rS3cret%21@db:5432/app",
            "GIT_REMOTE": f"https://x-access-token:{token}@github.com/o/r.git",
            "LOCAL_DB": "postgres://postgres:postgres@db:5432/app",
        }
    )
    got = secret_set.checked()
    assert {"Sup3rS3cret%21", "Sup3rS3cret!", token} <= set(got)
    assert "postgres://postgres:postgres@db:5432/app" in got and "postgres" not in got
    assert left_out(tmp_path, "DATABASES = {'PASSWORD': 'Sup3rS3cret!', 'HOST': 'x'}\n", got)
    assert left_out(tmp_path, f"//npm.pkg.github.com/:_authToken={token}\n", got)
    assert not left_out(tmp_path, "psycopg2-binary  # the driver\n", got)


def test_a_token_in_an_mcp_servers_value_is_checked_alone(client):
    token = "ghp_" + "Z9" * 18
    with client.app.state.session_factory() as session:
        session.add(McpServer(name="srv", command=["x"], env={"ARGS": f"--token {token} -v"}))
        session.commit()
    raw.read_again()
    assert token in secret_set.checked()


def test_a_word_under_a_secrets_name_stays_a_secret(environment, tmp_path):
    # (the user's decision: `POSTGRES_PASSWORD=postgres` - a file holding it is left out of
    # KOLONİ's commit, never deleted; an ordinary value by an ordinary name is no secret)
    environment({"POSTGRES_PASSWORD": "postgres", "NODE_ENV": "production"})
    got = secret_set.checked()
    assert "postgres" in got and "production" not in got
    assert left_out(tmp_path, "psycopg2-binary  # postgresql driver\n", got)


@pytest.mark.parametrize(
    "token",
    [
        "glpat-" + "a1" * 10,
        "AIza" + "B" * 35,
        "hf_" + "Cc1" * 12,
        "npm_" + "Dd1" * 12,
        "sk_live_" + "Ee1" * 8,
    ],
)
def test_more_tokens_are_known_by_their_shape(token):
    # (GitLab's, Google's, Hugging Face's, npm's and Stripe's: masked, and checked by any name)
    assert OutputMask([]).hide(f"use {token} now") == f"use {raw.HIDDEN} now"
    assert secret_set.values({"SOME_SETTING": f"x={token}"}) == [f"x={token}", token]


def test_a_secrets_shape_is_checked_whatever_its_name(client, monkeypatch):
    # (M-B: GH=ghp_…, a DATABASE_URL with its password, GH_PAT, MY_TOKEN_FILE=ghp_…)
    ghp, pat, address = "ghp_" + "H" * 36, "ghp_" + "D" * 36, "postgresql://u:p4ssw0rd@db/x"
    with client.app.state.session_factory() as session:
        session.add(McpServer(name="db", command=["x"], env={"GH": ghp, "DATABASE_URL": address}))
        session.add(
            McpServer(name="web", command=["x"], env={"API_BASE": "https://api.github.com"})
        )
        session.commit()
    raw.read_again()
    assert {ghp, address} <= set(raw.known())
    assert "https://api.github.com" not in raw.known()
    assert secret_set.values({"GH_PAT": pat, "MY_TOKEN_FILE": ghp, "NODE_ENV": "production"}) == [
        pat,
        ghp,
    ]


def test_claude_codes_token_is_a_secret_and_its_other_handles_are_not():
    # (M-A: HANDLE holds CLAUDE_CODE_.*, which dropped CLAUDE_CODE_OAUTH_TOKEN)
    token = "sk-ant-oat01-" + "A" * 30
    env = {
        "CLAUDE_CODE_OAUTH_TOKEN": token,
        "CLAUDE_CODE_ENTRYPOINT": "cli-entrypoint",
        "VSCODE_GIT_ASKPASS_NONCE": "n0nce-" + "C" * 20,
    }
    assert secret_set.values(env) == [token]


def test_a_teams_pull_request_body_fences_what_an_agent_wrote():
    # (L-3: its notes went in as they were - an @mention or "Fixes #1" there acted on GitHub; the
    # check and the role's name too)
    check = "`x`` @me Fixes #3`: passed"
    body = team_pr_body("t", "Co`der @me", "koloni/x", {"a.py": "M"}, check, "Fixes #1 @me", [])
    assert "```\nFixes #1 @me\n```" in body and "```\na.py (M)\n```" in body
    assert f"```\n{check}\n```" in body and "### `` Co`der @me ``'s notes" in body
    assert (
        titled("Fixes #12, closes o/r#3 - see #5") == "Fixes #\u200d12, closes o/r#\u200d3 - see #5"
    )


def test_a_secret_where_the_notes_are_cut_is_masked_whole():
    # (masked, then cut: its head went up before)
    secret = "tok-0123456789abcdef-notes"
    body = team_pr_body("t", "Coder", "koloni/x", {}, "c", "n" * 3990 + secret, [secret])
    assert secret[:8] not in body and body.count(raw.HIDDEN) == 1


@pytest.mark.parametrize(
    ("said", "shown"),
    [
        ("Fixes https://github.com/o/r/issues/8", "Fixes https://github.com/o/r/issues/\u200d8"),
        ("Fixes GH-9", "Fixes GH-\u200d9"),
        ("_fixes #10", "_fixes #\u200d10"),
        ("fixes\t#11", "fixes#\u200d11"),
        ("Closes\u00a0#16", "Closes\u00a0#\u200d16"),
        ("fix #1\u200b7", "fix #\u200d17"),
        ("prefixes #3, see #5", "prefixes #3, see #5"),
    ],
)
def test_no_closing_keyword_closes_an_issue(said, shown):
    # (L-3's review: an issue's link, GH-9, a keyword after `_`, a tab dropped - `fixes#11`)
    assert titled(said) == shown


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


def test_a_known_secret_an_agent_committed_stops_the_merge_and_never_deletes_the_branch(
    make_client, wait_run, repo, monkeypatch
):
    # (HIGH-1 at the team merge's site: refused, shown, and the branch kept through a Stop -
    # never dropped whole as a secret given in the turn is. MEDIUM-2: a value the project passes)
    monkeypatch.setenv("DEPLOY_TOKEN", PASSED)
    commit = call("run_command", {"command": "git add token.txt && git commit -q -m mine"}, "c")
    client, cid, run_id = on_branch(
        make_client,
        repo,
        [step(write_file("token.txt", f"{PASSED}\n")), step(commit), text("A done")],
    )
    merge = card(client, cid)
    assert "holds a secret KOLONİ knows" in merge["branch"]["note"]
    assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 200
    assert not (repo / "token.txt").exists()  # (nothing merged: still asked)
    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 202
    wait_run(client, cid, run_id, timeout=LONG)
    assert run(repo, "branch", "--list", "koloni/*") != ""


def test_a_title_holding_a_secret_is_masked_before_a_mention_is_neutralised():
    # (R2: a joiner after the @ of p@ssw0rd would split the secret, and it would go up whole)
    secret = "p@ssw0rd-0123456789"
    assert titled(f"deploy with {secret} @octocat", [secret]) == "deploy with *** @\u200doctocat"


def test_a_path_or_a_session_by_a_secrets_name_is_no_secret_a_scan_stops_on():
    # (HIGH-1's class from another source: what a command is not given is what is looked for)
    env = {
        "GOOGLE_APPLICATION_CREDENTIALS": "C:/keys/gcp.json",
        "SSH_KEY_FILE": "~/.ssh/id_rsa",
        "GIT_ASKPASS": "C:/tools/askpass.exe",
        "WT_SESSION": "abcdef12-3456-7890",
        "CREDENTIAL_HELPER": "manager-core",
        "GITHUB_TOKEN": TOKEN,
    }
    assert secret_set.values(env) == [TOKEN]
