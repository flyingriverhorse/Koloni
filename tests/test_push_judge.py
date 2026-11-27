"""A push of your feature branch to the judge (0.1.11, the user's 27 Nov: "main push edilmesin,
açılan branch'in origin'ine push etme olabilir"): in a turn the user watches at Full auto, with a
judge model to answer, a plain `git push` of the checked-out branch to its own origin goes to Full
auto's judge in place of the list's card. Everything else stays the card: main, master or origin's
default branch, a force, a tag, another name or remote, git's config that sends it elsewhere,
origin's address, git's config or its hooks changed in the turn, a secret in what it sends - and
every push at Ask, Auto-edit, in a turn nobody watches, or with no judge to ask. Each origin here is
a bare repository beside the project: nothing reaches a network."""

import asyncio
import logging
import subprocess
import threading

import pytest

from app import push_judge
from app.commands import harms
from app.push_judge import at_start, refused, shape
from tests.conftest import scaled
from tests.fakes import Script
from tests.keyed import OWN
from tests.test_agent_commands import cmd
from tests.test_backlog_auto import until
from tests.test_chat_flow import text
from tests.test_full_auto_judge import JUDGE_ASKED, go, said
from tests.test_judge_scenarios import judging  # noqa: F401  (a fixture)
from tests.test_take_in_scenarios import needs_git, repository

pytestmark = [needs_git, pytest.mark.judge, pytest.mark.no_po]

BRANCH = "feature/login"
SECRET = "sk-test-7f3a9c2e5b8d1f4a6c0e9b2d"


def git(folder, *args):
    done = subprocess.run(["git", *args], cwd=folder, capture_output=True, text=True)
    assert done.returncode == 0, (args, done.stderr)
    return done.stdout.strip()


def bare(at):
    """A bare repository at `at`, empty."""
    git(at.parent, "init", "-q", "--bare", str(at))
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


@pytest.mark.parametrize("hook", ["pre-push", "reference-transaction", "pre-push.exe"])
def test_a_hook_written_in_the_turn_is_a_card(pushed, hook):
    start = at_start(pushed)
    (pushed / ".git" / "hooks" / hook).write_text("#!/bin/sh\nexit 0\n")
    assert "hooks changed" in refused(pushed, "", start, [])


def test_a_hook_in_the_folder_core_hookspath_names_is_a_card_too(pushed):
    (pushed / ".husky").mkdir()
    git(pushed, "config", "core.hooksPath", ".husky")
    start = at_start(pushed)
    assert refused(pushed, "", start, []) == ""
    (pushed / ".husky" / "pre-push").write_text("#!/bin/sh\nexit 0\n")
    assert "hooks changed" in refused(pushed, "", start, [])


def test_the_users_own_hook_from_before_the_turn_is_no_card(pushed):
    (pushed / ".git" / "hooks" / "pre-push").write_text("#!/bin/sh\nexit 0\n")
    assert refused(pushed, "", at_start(pushed), []) == ""


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
    git(pushed, "remote", "set-url", "origin", str(bare(pushed.parent / "empty.git")))
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


def test_risky_is_refused_and_the_agent_goes_on(judging, wait_run, pushed):
    client, _lead, judge, executor = judging(
        [cmd("git push"), text("left it")], [said("risky", "Not asked for.")], []
    )
    _, cid, run_id = go(client, pushed)
    (refused_one,) = wait_run(client, cid, run_id)["commands"]
    assert refused_one["status"] == "refused" and refused_one["judged"]["verdict"] == "refuse"
    assert executor.started == [] and len(judge.calls) == 1


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
    assert "changed in this turn" in caplog.text, caplog.text


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
