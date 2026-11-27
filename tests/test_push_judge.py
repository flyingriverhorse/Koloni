"""A push of your feature branch to the judge (0.1.11, the user's 27 Nov: "main push edilmesin,
açılan branch'in origin'ine push etme olabilir"): in a turn the user watches at Full auto, with a
judge model to answer, a plain `git push` of the checked-out branch to its own origin goes to Full
auto's judge in place of the list's card. Everything else stays the card: main, master or origin's
default branch, a force, a tag, another name or remote, git's config that sends it elsewhere,
origin's address or git's config changed in the turn, a hook a push runs, a secret in what it sends
- and every push at Ask, Auto-edit, in a turn nobody watches, or with no judge to ask. Each origin here is
a bare repository beside the project: nothing reaches a network."""

import asyncio
import logging
import subprocess
import threading

import pytest

from app import push_judge
from app.commands import harm_class, harms, standing_asked
from app.push_judge import at_start, refused, shape
from app.risk_judge import REFUSED
from tests.conftest import scaled
from tests.fakes import Script
from tests.keyed import OWN
from tests.test_agent_commands import cmd
from tests.test_backlog_auto import until
from tests.test_chat_flow import text
from tests.test_claude_native import claude_app  # noqa: F401  (a fixture)
from tests.test_full_auto_judge import JUDGE_ASKED, go, said
from tests.test_judge_scenarios import judged_by_local, judging  # noqa: F401  (a fixture)
from tests.test_take_in_scenarios import needs_git, repository

pytestmark = [needs_git, pytest.mark.judge, pytest.mark.no_po]

BRANCH = "feature/login"
SECRET = "sk-test-7f3a9c2e5b8d1f4a6c0e9b2d"


def git(folder, *args):
    done = subprocess.run(["git", *args], cwd=folder, capture_output=True, text=True)
    assert done.returncode == 0, (args, done.stderr)
    return done.stdout.strip()


def bare(at, head="main"):
    """A bare repository at `at`, empty; its HEAD names `head` (origin's default branch)."""
    git(at.parent, "init", "-q", "--bare", "-b", head, str(at))
    return at


def commit(root, name, content, message="a change"):
    (root / name).write_text(content)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)


@pytest.fixture
def pushed(project_dir, monkeypatch):
    """The project a repository on `feature/login` with a commit of its own; its origin a bare
    repository beside it that holds main, origin's default; none of the user's own git settings."""
    config = project_dir.parent / "gitconfig"
    config.write_text('[protocol "file"]\n\tallow = always\n')
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    repository(project_dir)
    origin = bare(project_dir.parent / "origin.git")
    git(project_dir, "remote", "add", "origin", str(origin))
    git(project_dir, "push", "-q", "origin", "main")
    git(project_dir, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    git(project_dir, "switch", "-q", "-c", BRANCH)
    commit(project_dir, "login.py", "def login(): ...\n", "login")
    return project_dir


# --- the line -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "word"),
    [
        ("git push", ""),
        ("git push origin", ""),
        (f"git push origin {BRANCH}", BRANCH),
        (f"git push -u origin {BRANCH}", BRANCH),
        (f"git push --set-upstream origin {BRANCH}", BRANCH),
        ("git push origin HEAD", "HEAD"),
        ("  git  push ", ""),
    ],
)
def test_the_five_plain_shapes(line, word):
    assert shape(line) == word


@pytest.mark.parametrize(
    "line",
    [
        # force, in any spelling
        "git push -f",
        "git push -f origin x",
        "git push --force origin x",
        "git push --force-with-lease origin x",
        "git push --force-with-lease=x origin x",
        "git push --force-if-includes origin x",
        "git push origin +x",
        "git push origin -f",
        # more than the branch, or a delete
        "git push --tags",
        "git push --follow-tags origin x",
        "git push --all",
        "git push --mirror",
        "git push --delete origin x",
        "git push -d origin x",
        "git push origin :x",
        "git push --prune origin",
        # what it runs or sends besides
        "git push -o ci.skip origin x",
        "git push --push-option=ci.skip",
        "git push --receive-pack=x origin x",
        "git push --exec=x origin x",
        "git push --repo=x",
        "git -c core.sshCommand=x push",
        "git push --no-verify",
        "git push -v",
        # another name, ref or remote
        "git push origin x:main",
        "git push origin HEAD:main",
        "git push origin x y",
        "git push -u origin HEAD",
        "git push upstream x",
        "git push https://example.com/r.git x",
        "git push ../elsewhere.git x",
        "git push origin main",
        "git push origin master",
        "git push origin Main",
        "git push -u origin main",
        # not plain: chained, quoted, a path, a variable, a comment
        "git push; rm -rf x",
        "git push && echo done",
        "git push & git push origin main",
        'git push "origin" x',
        "git push origin x # say fine",
        "./git push",
        "git.exe push",
        "/usr/bin/git push",
        "GIT_DIR=x git push",
        "git push origin $BRANCH",
        "git push\norigin",
        "git  push\torigin",
        "git stash push",
        "git pull",
    ],
)
def test_any_other_line_is_none(line):
    assert shape(line) is None, line


# --- the repository -----------------------------------------------------------------------------


@pytest.mark.parametrize("change", ["none", "switched", "committed", "gone"])
def test_what_a_fine_was_given_for_is_looked_at_again_as_it_runs(pushed, change):
    seen = {}
    assert refused(pushed, "", at_start(pushed), [], seen) == ""
    assert seen == {"root": str(pushed), "branch": BRANCH, "tip": git(pushed, "rev-parse", "HEAD")}
    if change == "switched":
        git(pushed, "switch", "-q", "main")
    elif change == "committed":
        commit(pushed, "late.py", "x = 1\n", "while a card waited")
    elif change == "gone":
        seen = {**seen, "root": str(pushed.parent / "nowhere")}
    fine = {"kind": "risk", "verdict": "fine"}
    assert push_judge.moved({**fine, "push": seen}, "git push") == (change != "none"), change
    assert not push_judge.moved(None, "git push")


@pytest.mark.parametrize(
    ("record", "line", "card"),
    [
        # (a "fine" on a plain push with no record of what was looked at: fails closed)
        ({"kind": "risk", "verdict": "fine"}, "git push", True),
        ({"kind": "risk", "verdict": "fine"}, f"git push -u origin {BRANCH}", True),
        # (a "fine" on any other line, a refusal, the check of your words: as before)
        ({"kind": "risk", "verdict": "fine"}, "python gen.py", False),
        ({"kind": "risk", "verdict": "fine"}, "git push --force", False),
        ({"kind": "risk", "verdict": "refuse"}, "git push", False),
        ({"kind": "said", "verdict": "ask"}, "git push", False),
        (None, "git push", False),
    ],
)
def test_a_fine_on_a_push_with_no_record_of_what_was_looked_at_is_a_card(record, line, card):
    assert push_judge.moved(record, line) == card


def test_a_plain_push_of_the_feature_branch_is_not_refused(pushed):
    start = at_start(pushed)
    assert start is not None and start["url"] and start["default"] == "main", start
    for word in ("", BRANCH, "HEAD"):
        assert refused(pushed, word, start, [SECRET.encode()]) == "", word


def test_no_record_of_the_turns_start_is_a_card(pushed):
    assert refused(pushed, "", None, [])
    assert refused(pushed, "", {**at_start(pushed), "url": ""}, [])
    assert refused(pushed, "", {**at_start(pushed), "config": None}, [])


@pytest.mark.parametrize("onto", ["main", "master"])
def test_main_and_master_are_cards(pushed, onto):
    git(pushed, "switch", "-q", "-C", onto, "main")
    start = at_start(pushed)
    for word in ("", onto, "HEAD"):
        assert refused(pushed, word, start, []), (onto, word)


def test_origins_default_branch_is_a_card_as_it_is_now_and_as_it_was(pushed):
    git(pushed, "switch", "-q", "-c", "trunk")
    git(pushed, "push", "-q", "origin", "trunk")
    git(pushed, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
    start = at_start(pushed)
    assert start["default"] == "trunk"
    assert "origin's default" in refused(pushed, "", start, [])
    # (an agent's write of origin/HEAD meanwhile does not make trunk a feature branch)
    git(pushed, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    assert "origin's default" in refused(pushed, "trunk", start, [])


@pytest.mark.parametrize("line", ["git push", "git push origin develop", "git push origin HEAD"])
@pytest.mark.parametrize("local", ["none", "deleted", "stale"])
def test_the_branch_origin_itself_names_its_default_is_a_card(pushed, line, local):
    # (the review's P2: origin's HEAD is develop, and this repository's origin/HEAD says nothing
    # of it, or says main - origin itself is asked)
    git(pushed, "switch", "-q", "-c", "develop", "main")
    git(pushed, "push", "-q", "origin", "develop")
    git(pushed.parent / "origin.git", "symbolic-ref", "HEAD", "refs/heads/develop")
    if local == "none":
        git(pushed, "symbolic-ref", "-d", "refs/remotes/origin/HEAD")
    elif local == "deleted":
        git(pushed, "remote", "set-head", "origin", "-d")
    commit(pushed, "c.txt", "c\n")
    found = refused(pushed, shape(line), at_start(pushed), [])
    assert "origin does not say its default branch, or it is this one" in found, (line, found)


def test_an_origin_whose_head_names_no_branch_is_a_card(pushed):
    git(pushed.parent / "origin.git", "symbolic-ref", "HEAD", "refs/heads/gone")
    assert "does not say its default" in refused(pushed, "", at_start(pushed), [])


def test_a_detached_head_is_a_card(pushed):
    git(pushed, "switch", "-q", "--detach")
    assert refused(pushed, "", at_start(pushed), [])
    assert refused(pushed, "HEAD", at_start(pushed), [])


@pytest.mark.parametrize("word", ["other", "v1", f"refs/heads/{BRANCH}", "refs/tags/v1"])
def test_a_name_but_the_branch_checked_out_is_a_card(pushed, word):
    git(pushed, "branch", "other")
    git(pushed, "tag", "v1")
    assert "another one" in refused(pushed, word, at_start(pushed), [])


@pytest.mark.parametrize(
    ("key", "value", "why"),
    [
        (f"branch.{BRANCH}.merge", "refs/heads/main", "another upstream"),
        (f"branch.{BRANCH}.remote", "upstream", "another remote"),
        (f"branch.{BRANCH}.pushRemote", "upstream", "another remote"),
        ("remote.pushDefault", "upstream", "another remote"),
        ("push.default", "matching", "push.default"),
        ("push.default", "nothing", "push.default"),
        ("remote.origin.push", f"refs/heads/{BRANCH}:refs/heads/main", "sends more"),
        ("remote.origin.mirror", "true", "sends more"),
        ("push.followTags", "true", "sends more"),
        ("push.pushOption", "ci.skip", "sends more"),
        ("remote.origin.receivepack", "git-receive-pack", "sends more"),
        ("push.recurseSubmodules", "on-demand", "submodules"),
        ("submodule.recurse", "true", "submodules"),
        ("hook.audit.event", "pre-push", "hooks of its own"),
    ],
)
def test_gits_config_that_sends_it_elsewhere_or_more_is_a_card(pushed, key, value, why):
    git(pushed, "config", key, value)
    found = refused(pushed, "", at_start(pushed), [])
    assert why in found, (key, found)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("push.default", "current"),
        ("push.default", "simple"),
        (f"branch.{BRANCH}.merge", f"refs/heads/{BRANCH}"),
        (f"branch.{BRANCH}.remote", "origin"),
        ("remote.origin.mirror", "false"),
        ("push.followTags", "false"),
        ("push.recurseSubmodules", "check"),
        ("submodule.recurse", "false"),
    ],
)
def test_gits_config_that_keeps_it_to_the_branch_on_origin_is_no_card(pushed, key, value):
    git(pushed, "config", key, value)
    assert refused(pushed, "", at_start(pushed), []) == ""


@pytest.mark.parametrize("how", ["set-url", "pushurl", "insteadOf"])
def test_origins_address_changed_in_the_turn_is_a_card(pushed, how):
    start = at_start(pushed)
    elsewhere = bare(pushed.parent / "elsewhere.git")
    git(pushed, "push", "-q", str(elsewhere), "main")
    if how == "set-url":
        git(pushed, "remote", "set-url", "origin", str(elsewhere))
    elif how == "pushurl":
        git(pushed, "config", "remote.origin.pushurl", str(elsewhere))
    else:
        git(pushed, "config", f"url.{elsewhere}.pushInsteadOf", str(pushed.parent / "origin.git"))
    assert "changed in this turn" in refused(pushed, "", start, [])


def test_gits_config_changed_in_the_turn_is_a_card(pushed):
    start = at_start(pushed)
    git(pushed, "config", "core.sshCommand", "ssh -o ProxyCommand=x")
    assert "changed in this turn" in refused(pushed, "", start, [])


@pytest.mark.parametrize("hook", ["pre-push", "reference-transaction", "pre-push.exe", "PRE-PUSH"])
@pytest.mark.parametrize("when", ["in the turn", "before it"])
def test_a_hook_a_push_runs_is_a_card(pushed, hook, when):
    # (the user's own too: an unchanged hook can run what an agent wrote - husky's stubs, LFS's)
    start = at_start(pushed) if when == "in the turn" else None
    (pushed / ".git" / "hooks" / hook).write_text("#!/bin/sh\nexit 0\n")
    found = refused(pushed, "", start or at_start(pushed), [])
    assert "hook would run" in found, (hook, found)


@pytest.mark.parametrize("folder", [".husky", ".husky/_"])
def test_a_hook_in_the_folder_core_hookspath_names_is_a_card_too(pushed, folder):
    (pushed / folder).mkdir(parents=True)
    git(pushed, "config", "core.hooksPath", folder)
    assert refused(pushed, "", at_start(pushed), []) == ""
    (pushed / folder / "pre-push").write_text('#!/bin/sh\n. "$(dirname "$0")/h"\n')
    assert "hook would run" in refused(pushed, "", at_start(pushed), [])


def test_a_hook_a_push_does_not_run_and_the_samples_are_no_card(pushed):
    (pushed / ".git" / "hooks" / "post-commit").write_text("#!/bin/sh\nexit 0\n")
    (pushed / ".git" / "hooks" / "pre-push.sample").write_text("#!/bin/sh\nexit 0\n")
    assert refused(pushed, "", at_start(pushed), []) == ""


@pytest.mark.parametrize("legacy", ["remotes", "branches"])
def test_an_origin_git_reads_from_its_old_files_is_a_card(pushed, legacy):
    # (the review's P3, P3b: `.git/remotes/origin`'s `Push:` maps the branch to main)
    origin = (pushed.parent / "origin.git").as_posix()
    git(pushed, "remote", "remove", "origin")
    (pushed / ".git" / legacy).mkdir(exist_ok=True)
    (pushed / ".git" / legacy / "origin").write_text(
        f"URL: {origin}\nPush: refs/heads/{BRANCH}:refs/heads/main\n"
        if legacy == "remotes"
        else f"{origin}#main\n"
    )
    found = refused(pushed, "", at_start(pushed), [])
    assert found, found
    # (whatever git makes of those files: with no `remote.origin.url` in its config, a card)
    url = {"remote.origin.url": ["x"]}
    assert push_judge._redirects({}, BRANCH) == "git's config does not name origin's address"
    assert push_judge._redirects(url, BRANCH) == ""


@pytest.mark.parametrize("where", ["in the project", "beside it"])
def test_a_config_file_git_reads_from_the_project_is_a_card(pushed, where):
    # (the review's p11b: your `.git/config` includes `../.gitconfig`, a file of the project an agent
    # may write unasked - a `pushInsteadOf` there sends the next turn's push elsewhere)
    shared = pushed / ".gitconfig" if where == "in the project" else pushed.parent / "shared.cfg"
    git(
        pushed,
        "config",
        "include.path",
        "../.gitconfig" if where == "in the project" else str(shared),
    )
    start = at_start(pushed)  # (the next turn begins: what the agent wrote there is read then)
    elsewhere = bare(pushed.parent / "elsewhere.git")
    git(pushed, "push", "-q", str(elsewhere), "main")
    origin = git(pushed, "remote", "get-url", "origin").replace("\\", "\\\\")  # (as git writes it)
    shared.write_text(f'[url "{elsewhere.as_posix()}"]\n\tpushInsteadOf = {origin}\n')
    assert git(pushed, "remote", "get-url", "--push", "origin") == elsewhere.as_posix()
    found = refused(pushed, "", at_start(pushed), [])
    if where == "beside it":  # (a file out of the project: compared within the turn, as any)
        assert "changed in this turn" in refused(pushed, "", start, []), start
    if where == "in the project":
        assert "a file of the project" in found, found
    else:
        assert found == "", found


def test_an_origin_in_the_project_is_a_card(pushed):
    # (its own hooks run on this machine as the push lands, and they are files of the project)
    inside = bare(pushed / "up.git")
    git(pushed, "push", "-q", str(inside), "main")
    git(pushed, "remote", "set-url", "origin", "up.git")
    assert "folder in the project" in refused(pushed, "", at_start(pushed), [])


def test_a_file_address_is_a_card(pushed):
    git(pushed, "remote", "set-url", "origin", (pushed.parent / "origin.git").as_uri())
    assert "file: address" in refused(pushed, "", at_start(pushed), [])


@pytest.mark.parametrize("where", ["file", "message", "an earlier commit"])
def test_a_secret_in_what_it_sends_is_a_card(pushed, where):
    if where == "file":
        commit(pushed, "config.py", f"KEY = '{SECRET}'\n")
    elif where == "message":
        commit(pushed, "b.py", "x = 1\n", f"use {SECRET}")
    else:
        commit(pushed, "config.py", f"KEY = '{SECRET}'\n")
        commit(pushed, "config.py", "KEY = None\n", "take it out")
    assert "holds a secret" in refused(pushed, "", at_start(pushed), [SECRET.encode()])


@pytest.mark.parametrize("how", ["an orphan branch", "an unrelated history merged in"])
def test_a_secret_in_a_root_commit_is_a_card(pushed, how):
    # (the review's P1, P1b: `diff-tree` lists a root commit's files only with `--root`)
    if how == "an orphan branch":
        git(pushed, "switch", "-q", "--orphan", "fresh")
        commit(pushed, "cfg.py", f"KEY = '{SECRET}'\n", "init")
        commit(pushed, "b.txt", "b\n", "more")
        word = "fresh"
    else:
        git(pushed, "switch", "-q", "--orphan", "side")  # (an empty tree: git's switch)
        commit(pushed, "cfg.py", f"KEY = '{SECRET}'\n", "side root")
        git(pushed, "rm", "-q", "cfg.py")
        commit(pushed, "s.txt", "s\n", "side clean")
        git(pushed, "switch", "-q", BRANCH)
        git(pushed, "merge", "-q", "--allow-unrelated-histories", "-m", "merge side", "side")
        word = BRANCH
    assert "holds a secret" in refused(pushed, word, at_start(pushed), [SECRET.encode()])


def test_what_origin_holds_already_is_not_counted(pushed):
    commit(pushed, "config.py", f"KEY = '{SECRET}'\n")
    git(pushed, "push", "-q", "origin", BRANCH)
    commit(pushed, "c.py", "y = 2\n")
    assert refused(pushed, "", at_start(pushed), [SECRET.encode()]) == ""


def test_a_remote_tracking_ref_written_over_hides_no_secret(pushed):
    # (counted against what origin itself says it holds: anything may write refs/remotes)
    commit(pushed, "config.py", f"KEY = '{SECRET}'\n")
    git(pushed, "update-ref", f"refs/remotes/origin/{BRANCH}", "HEAD")
    git(pushed, "update-ref", "refs/remotes/origin/main", "HEAD")
    assert "holds a secret" in refused(pushed, "", at_start(pushed), [SECRET.encode()])


def test_more_commits_than_it_looks_at_is_a_card(pushed, monkeypatch):
    monkeypatch.setattr(push_judge, "MOST_COMMITS", 1)
    commit(pushed, "c.py", "y = 2\n")
    assert "more than 1 commits" in refused(pushed, "", at_start(pushed), [])


def test_an_origin_that_holds_nothing_to_count_from_is_a_card(pushed):
    # (its main is a commit of another history: nothing here to count from)
    alien, other = bare(pushed.parent / "alien.git"), pushed.parent / "other"
    other.mkdir()
    (other / "x.txt").write_text("x\n")
    repository(other)
    git(other, "push", "-q", str(alien), "main")
    git(pushed, "remote", "set-url", "origin", str(alien))
    assert "holds none" in refused(pushed, "", at_start(pushed), [])


def test_an_origin_that_does_not_answer_is_a_card(pushed):
    git(pushed, "remote", "set-url", "origin", str(pushed.parent / "gone.git"))
    assert refused(pushed, "", at_start(pushed), [])


# --- the gate: a watched Full auto turn with a judge ---------------------------------------------


@pytest.mark.parametrize(
    "line", ["git push", f"git push -u origin {BRANCH}", "git push origin HEAD"]
)
def test_fine_pushes_the_feature_branch_unasked(judging, wait_run, pushed, line):
    client, _lead, judge, executor = judging(
        [cmd(line), text("pushed")], [said("fine", "The user asked for it.")], [Script([])]
    )
    _, cid, run_id = go(client, pushed)
    (ran,) = wait_run(client, cid, run_id)["commands"]
    assert ran["status"] == "exited" and executor.started[0][0] == line, ran
    assert (ran["judged"]["kind"], ran["judged"]["verdict"]) == ("risk", "fine")
    assert len(judge.calls) == 1 and JUDGE_ASKED in judge.calls[0][0]["content"]


@pytest.mark.parametrize("word", ["approve", "reject"])
def test_risky_is_the_lists_push_card_never_a_refusal(judging, wait_run, pushed, word):
    # (the coordinator's 27 Nov: a push is never lost without a word - the plain push card the list
    # gave before the judge took pushes; no refusal, so none counted towards its limits)
    client, lead, judge, executor = judging(
        [cmd("git push"), text("left it")],
        [said("risky", "Not asked for.")],
        [Script([])] if word == "approve" else [],
    )
    _, cid, run_id = go(client, pushed)

    def proposed():
        snap = client.get(f"/api/conversations/{cid}").json()
        return [one for one in snap["commands"] if one["status"] == "proposed"]

    (asked,) = until(proposed, 30)
    assert asked["danger"] == harms("git push", False) and asked["judged"] is None, asked
    path = f"/api/commands/{asked['id']}/{word}"
    assert client.post(path, json={}, headers=OWN).status_code == 200
    (ran,) = wait_run(client, cid, run_id)["commands"]
    want = ("exited", ["git push"]) if word == "approve" else ("rejected", [])
    assert (ran["status"], [one[0] for one in executor.started]) == want, ran
    assert ran["judged"] is None and len(judge.calls) == 1
    assert REFUSED not in str(lead.calls[-1])


def test_another_risky_command_is_still_refused_beside_a_risky_push(judging, wait_run, pushed):
    # (K3's delete the judge calls risky: refused, as before - the push after it: its card)
    client, lead, judge, executor = judging(
        [cmd("rm -rf src", id="k1"), cmd("git push", id="k2"), text("left it")],
        [said("risky", "Not asked for."), said("risky", "Not asked for.")],
        [],
    )
    _, cid, run_id = go(client, pushed)

    def proposed():
        snap = client.get(f"/api/conversations/{cid}").json()
        return [one for one in snap["commands"] if one["status"] == "proposed"]

    (asked,) = until(proposed, 30)
    assert asked["command"] == "git push" and asked["judged"] is None, asked
    assert client.post(f"/api/commands/{asked['id']}/reject", headers=OWN).status_code == 200
    refused_one, pushed_one = wait_run(client, cid, run_id)["commands"]
    assert (refused_one["status"], refused_one["judged"]["verdict"]) == ("refused", "refuse")
    assert (pushed_one["status"], pushed_one["judged"]) == ("rejected", None)
    assert lead.calls[1][-1]["content"] == REFUSED and executor.started == []
    assert len(judge.calls) == 2


def card(client, cid):
    """The command waiting on its card, turned down - a ceiling of 30 s, not 5: a push's look at
    git, before the judge and again after it, is some 20 git calls, seconds under load."""

    def proposed():
        snap = client.get(f"/api/conversations/{cid}").json()
        return [one for one in snap["commands"] if one["status"] == "proposed"]

    (asked,) = until(proposed, 30)
    assert client.post(f"/api/commands/{asked['id']}/reject", headers=OWN).status_code == 200
    return asked


def unjudged_card(client, cid, run_id, wait_run, judge, executor, line):
    asked = card(client, cid)
    wait_run(client, cid, run_id)
    assert asked["command"] == line and asked["danger"] == harms(line, False), asked
    assert not asked["judged"] or asked["judged"]["kind"] != "risk", asked
    assert not [one for one in judge.calls if JUDGE_ASKED in one[0]["content"]]
    assert executor.started == []
    return asked


@pytest.mark.parametrize(
    ("onto", "line"),
    [
        ("main", "git push"),
        ("main", "git push origin HEAD"),
        (BRANCH, "git push origin main"),
        (BRANCH, f"git push --force origin {BRANCH}"),
        (BRANCH, "git push --tags"),
        (BRANCH, f"git push upstream {BRANCH}"),
        (BRANCH, "git push origin other"),
    ],
)
def test_main_and_what_is_not_plain_stay_the_lists_card_at_full_auto(
    judging, wait_run, pushed, onto, line
):
    git(pushed, "switch", "-q", onto)
    git(pushed, "branch", "other")
    client, _lead, judge, executor = judging([cmd(line), text("left")], [said("fine")], [])
    _, cid, run_id = go(client, pushed)
    unjudged_card(client, cid, run_id, wait_run, judge, executor, line)


@pytest.mark.parametrize("mode", ["ask", "auto_edit"])
def test_ask_and_auto_edit_keep_the_lists_card(judging, wait_run, pushed, mode):
    client, _lead, judge, executor = judging([cmd("git push"), text("left")], [said("fine")], [])
    _, cid, run_id = go(client, pushed, mode=mode)
    asked = card(client, cid)
    wait_run(client, cid, run_id)
    assert asked["danger"] == harms("git push") and asked["judged"] is None
    assert judge.calls == [] and executor.started == []


@pytest.mark.parametrize("why", ["no model", "switch off"])
def test_with_no_judge_to_decide_it_is_the_lists_card(judging, wait_run, pushed, monkeypatch, why):
    client, _lead, judge, executor = judging([cmd("git push"), text("left")], [], [])
    if why == "no model":
        monkeypatch.setattr("app.agent.risk_judge_mixin.judge_pick", lambda *_a, **_k: None)
    pid = client.post("/api/projects", json={"root_path": str(pushed)}).json()["id"]
    if why == "switch off":
        off = client.patch(f"/api/projects/{pid}", json={"full_auto_judge": False}, headers=OWN)
        assert off.status_code == 200
    _, cid, run_id = go(client, pushed)
    unjudged_card(client, cid, run_id, wait_run, judge, executor, "git push")


def test_a_to_do_tasks_turn_keeps_the_lists_card(judging, wait_run, pushed):
    from tests.test_todo_chat import do_in_chat, ended

    client, _lead, judge, executor = judging([cmd("git push"), text("done")], [said("fine")], [])
    pid = client.post("/api/projects", json={"root_path": str(pushed)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(
        f"/api/conversations/{cid}", json={"permission_mode": "full_auto"}, headers=OWN
    ).is_success
    task_id = client.post(
        f"/api/projects/{pid}/backlog", json={"title": "ship the login"}, headers=OWN
    ).json()["id"]
    client.headers.update(OWN)
    assert do_in_chat(client, pid, [task_id], cid).status_code == 200
    asked = card(client, cid)
    ended(client, cid, 1)
    assert asked["danger"] == harms("git push", False) and asked["judged"] is None
    assert not [one for one in judge.calls if JUDGE_ASKED in one[0]["content"]]
    assert executor.started == []


@pytest.mark.parametrize("change", ["origin", "hook"])
def test_origin_or_a_hook_changed_in_the_turn_is_the_lists_card(
    judging, wait_run, pushed, change, caplog
):
    caplog.set_level(logging.INFO, "app.agent")

    async def changed_then_push(_on_delta):
        # (after the turn began: what it goes by was read then)
        if change == "origin":
            elsewhere = bare(pushed.parent / "elsewhere.git")
            git(pushed, "push", "-q", str(elsewhere), "main")
            git(pushed, "remote", "set-url", "origin", str(elsewhere))
        else:
            (pushed / ".git" / "hooks" / "pre-push").write_text("#!/bin/sh\nexit 0\n")
        return cmd("git push")

    client, _lead, judge, executor = judging([changed_then_push, text("left")], [said("fine")], [])
    _, cid, run_id = go(client, pushed)
    unjudged_card(client, cid, run_id, wait_run, judge, executor, "git push")
    why = "changed in this turn" if change == "origin" else "hook would run"
    assert why in caplog.text, caplog.text


def test_a_secret_of_this_machine_in_what_it_sends_is_the_lists_card(
    judging, wait_run, pushed, monkeypatch, caplog
):
    caplog.set_level(logging.INFO, "app.agent")
    token = "ghp_" + "a1B2c3D4e5" * 4
    monkeypatch.setenv("PUSH_TEST_TOKEN", token)
    commit(pushed, "settings.py", f"TOKEN = '{token}'\n")
    client, _lead, judge, executor = judging([cmd("git push"), text("left")], [said("fine")], [])
    _, cid, run_id = go(client, pushed)
    unjudged_card(client, cid, run_id, wait_run, judge, executor, "git push")
    assert "holds a secret" in caplog.text, caplog.text


def test_your_push_it_goes_to_the_judge_on_the_feature_branch(judging, wait_run, pushed):
    # (K5's quoted card is the fallback: here the judge, which reads your words too, decides)
    client, _lead, judge, executor = judging(
        [cmd("git push"), text("pushed")], [said("fine", "Asked for.")], [Script([])]
    )
    _, cid, run_id = go(client, pushed, "Push it.")
    (ran,) = wait_run(client, cid, run_id)["commands"]
    assert ran["status"] == "exited" and ran["judged"]["kind"] == "risk", ran
    assert len(judge.calls) == 1


def test_your_push_it_the_judge_does_not_call_fine_is_k5s_quoted_card(judging, wait_run, pushed):
    # (never refused: you asked for it - the one-click card quotes you, as before the judge)
    client, _lead, judge, executor = judging(
        [cmd("git push"), text("left")], [said("risky", "Not sure it was asked.")], []
    )
    _, cid, run_id = go(client, pushed, "Push it.")
    asked = card(client, cid)
    wait_run(client, cid, run_id)
    assert (asked["judged"]["kind"], asked["judged"]["quote"]) == ("said", "Push it."), asked
    assert len(judge.calls) == 1 and executor.started == []


def test_your_push_it_on_main_keeps_k5s_quoted_card(judging, wait_run, pushed):
    git(pushed, "switch", "-q", "main")
    client, _lead, judge, executor = judging([cmd("git push"), text("left")], [said("fine")], [])
    _, cid, run_id = go(client, pushed, "Push it.")
    asked = unjudged_card(client, cid, run_id, wait_run, judge, executor, "git push")
    assert (asked["judged"]["kind"], asked["judged"]["quote"]) == ("said", "Push it."), asked


@pytest.mark.parametrize("changed", ["level", "switch"])
def test_a_fine_lifts_nothing_once_the_level_or_the_switch_changed_while_it_looked(
    judging, wait_run, pushed, changed
):
    looked, release = threading.Event(), threading.Event()

    async def held(_on_delta):
        looked.set()
        await asyncio.to_thread(release.wait, scaled(20))
        return said("fine", "Asked for.")

    client, _lead, judge, executor = judging([cmd("git push"), text("left")], [held], [])
    pid, cid, run_id = go(client, pushed)
    assert looked.wait(scaled(10))
    path, body = (
        (f"/api/conversations/{cid}", {"permission_mode": "auto_edit"})
        if changed == "level"
        else (f"/api/projects/{pid}", {"full_auto_judge": False})
    )
    assert client.patch(path, json=body, headers=OWN).is_success
    release.set()
    asked = card(client, cid)
    wait_run(client, cid, run_id)
    assert asked["command"] == "git push" and asked["judged"] is None, asked
    assert len(judge.calls) == 1 and executor.started == []


def test_a_job_while_away_never_puts_a_push_to_the_judge(judging, wait_run, pushed):
    from tests.test_away_scenarios import ended, proposed_in, to_do

    client, _lead, judge, executor = judging(
        [
            to_do({"jobs": [{"title": "one"}]}),
            text("on your To-do"),
            cmd("git push"),
            text("waits"),
        ],
        [said("fine")] * 3,
        [],
    )
    pid, cid, run_id = go(client, pushed, "do one while I sleep")
    wait_run(client, cid, run_id)
    gone = client.post(
        f"/api/conversations/{cid}/away", json={"task_ids": proposed_in(client, cid)}, headers=OWN
    )
    assert gone.status_code == 200, gone.text
    # (in a repository a job works on a branch of its own, where its own push is refused - or,
    # anywhere else, parked: never the judge's, never run)
    ended(client, pid)
    assert executor.started == []
    assert not [one for one in judge.calls if JUDGE_ASKED in one[0]["content"]]


def test_claude_codes_push_of_the_feature_branch_runs_through_the_judge(
    claude_app,  # noqa: F811
    wait_run,
    pushed,
):
    client, cli, default = claude_app(
        [{"tool": "Bash", "input": {"command": "git push"}, "result": ""}, {"say": "pushed"}],
        default_steps=[said("fine", "Asked for.")],
    )
    judged_by_local(client, cli)
    _, cid, run_id = go(client, pushed, provider=cli)
    snap = wait_run(client, cid, run_id, 30)
    (ran,) = snap["commands"]
    assert ran["status"] != "proposed" and ran["origin"] == "cli", ran
    assert (ran["judged"]["kind"], ran["judged"]["verdict"]) == ("risk", "fine")
    assert len(default.calls) == 1
    assert claude_app.record()["asked"][0]["behavior"] == "allow"


@pytest.mark.parametrize(
    "line",
    [
        "git remote add origin https://example.com/x.git",
        "git remote set-url origin https://example.com/x.git",
        "git remote set-url --push origin https://example.com/x.git",
        "git remote -v set-url origin https://example.com/x.git",
        "git remote remove origin",
        "git remote rm origin",
        "git remote rename origin old",
        "git remote rename upstream origin",
        "git remote set-head origin -d",
        "git remote set-head origin develop",
        "git remote set-branches origin main",
        "git remote add -t main origin https://example.com/x.git",
        "git remote set-url 'origin' https://example.com/x.git",
        # (a quote inside the name, an escape: the shell may make it origin - any name not plain)
        "git remote set-url ori''gin https://example.com/x.git",
        'git remote set-url ori""gin https://example.com/x.git',
        'git remote set-url "ori"gin https://example.com/x.git',
        "git remote set-url o`rigin https://example.com/x.git",
        "git remote set-url $R https://example.com/x.git",
        "git remote rename x ori''gin",
        # (git's words in any case: a case-blind disk finds the program)
        "git remote Set-Url origin https://example.com/x.git",
        "git REMOTE set-url origin https://example.com/x.git",
    ],
)
def test_a_git_remote_that_changes_origin_is_asked_at_every_level(line):
    # (the review's p9: an origin set in one turn was the next turn's origin - its card now)
    assert harm_class(line, False) == "always" and standing_asked(line, False) == ".git", line


@pytest.mark.parametrize(
    "line",
    [
        "git remote add upstream https://example.com/x.git",
        "git remote add -t main -m main upstream https://example.com/x.git",
        "git remote rename origin-old old",
        "git remote set-url upstream https://example.com/origin",
        "git remote remove upstream",
        "git remote -v",
        "git remote get-url origin",
        "git remote show origin",
    ],
)
def test_a_git_remote_of_another_remote_or_a_read_is_as_before(line):
    # (`add`'s `-t` / `-m` values are no remote: `add -t main upstream x` is upstream's)
    assert harm_class(line, False) == "" and not standing_asked(line, False), line


def test_an_agents_origin_change_is_a_card_in_the_turn_it_makes_it(judging, wait_run, pushed):
    line = f"git remote set-url origin {pushed.parent / 'other.git'}"
    client, _lead, judge, executor = judging([cmd(line), text("left")], [said("fine")], [])
    _, cid, run_id = go(client, pushed)
    asked = card(client, cid)
    wait_run(client, cid, run_id)
    assert asked["command"] == line and asked["danger"].startswith("Names .git"), asked
    assert judge.calls == [] and executor.started == []


def test_a_branch_moved_between_the_fine_and_the_run_is_the_lists_card(
    judging, wait_run, pushed, monkeypatch
):
    # (`_keeps_answered` may hold the command on another card after the judge's fine: the gate
    # looks at the branch and its commit again just before it runs - `push_judge.moved`)
    client, _lead, judge, executor = judging([cmd("git push"), text("left")], [said("fine")], [])
    runner = client.app.state.runner
    refuses = runner._risk_refuses

    def then_committed(ctx, why, record):
        commit(pushed, "late.py", "x = 1\n", "while a card waited")
        return refuses(ctx, why, record)

    monkeypatch.setattr(runner, "_risk_refuses", then_committed)
    _, cid, run_id = go(client, pushed)
    asked = card(client, cid)
    wait_run(client, cid, run_id)
    assert asked["command"] == "git push" and asked["judged"] is None, asked
    assert len(judge.calls) == 1 and executor.started == []


def test_claude_codes_push_that_moved_before_it_ran_is_the_lists_card(
    claude_app,  # noqa: F811
    wait_run,
    pushed,
    monkeypatch,
):
    client, cli, default = claude_app(
        [{"tool": "Bash", "input": {"command": "git push"}, "result": ""}, {"say": "left"}],
        default_steps=[said("fine", "Asked for.")],
    )
    judged_by_local(client, cli)
    runner = client.app.state.runner
    refuses = runner._risk_refuses

    def then_switched(ctx, why, record):
        git(pushed, "switch", "-q", "main")
        return refuses(ctx, why, record)

    monkeypatch.setattr(runner, "_risk_refuses", then_switched)
    _, cid, run_id = go(client, pushed, provider=cli)
    asked = card(client, cid)
    wait_run(client, cid, run_id, 30)
    assert asked["command"] == "git push" and asked["origin"] == "cli", asked
    assert asked["judged"] is None and len(default.calls) == 1


@pytest.mark.parametrize("where", ["host", "docker"])
def test_a_push_in_docker_is_the_lists_card(judging, pushed, monkeypatch, where):
    # (its git, its config and its hooks are the container's: what KOLONİ looked at is not)
    from app.agent.ctx import Ctx
    from app.db.models import Project

    client, *_ = judging([], [], [])
    runner = client.app.state.runner
    pid = client.post("/api/projects", json={"root_path": str(pushed)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    with client.app.state.session_factory() as session:
        session.get_one(Project, pid).exec_location = where
        session.commit()
    monkeypatch.setattr(runner, "_full_auto", lambda _ctx: True)
    monkeypatch.setitem(runner._git_at, "r", {"push": at_start(pushed)})
    ctx = Ctx(run_id="r", cid=cid, root=str(pushed), agent_id="a", role="Lead", tools=(), depth=0)
    found = (harms("git push", False), None)
    got = client.portal.call(runner._push_takes, ctx, "git push", ".", pushed, found, True)
    assert (got is not None) == (where == "host"), got
