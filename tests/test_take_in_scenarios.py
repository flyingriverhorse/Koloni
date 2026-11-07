"""Slice 30's acceptance set: taking a sub-agent's work in. Written before the code.

A file both the agent and the project changed is merged line by line (git's own merge, on
the text the copy started from): different lines go together by themselves, the same lines
are asked about - with both sides' times, and nothing chosen for the user. The joined state
is written into the agent's copy and the project's check command runs there, before the
project is touched and before the user is asked. What was taken can then be committed, by
the user's own click, as a commit of those files alone.
"""

import json
import os
import shutil
import subprocess

import pytest

from app.db.models import Project

if not hasattr(Project, "check_command"):  # written before the code: skipped until it exists
    pytest.skip("slice 30 is not built yet", allow_module_level=True)

from tests.conftest import Gate  # noqa: E402
from tests.test_chat_flow import text  # noqa: E402
from tests.test_claim_scenarios import write  # noqa: E402
from tests.test_copy_scenarios import seen  # noqa: E402
from tests.test_parallel import until  # noqa: E402
from tests.test_spawn import call, step  # noqa: E402
from tests.test_trigger_scenarios import allow, run_now, trigger  # noqa: E402

ORIGIN = "http://127.0.0.1:8790"
LINES = "one\ntwo\nthree\nfour\nfive\nsix\nseven\n"
CHECK = "import os, sys\n" \
        "said = open('lines.txt', encoding='utf-8').read()\n" \
        "print('CWD=' + os.getcwd())\n" \
        "sys.exit(0 if all(word in said for word in sys.argv[1:]) else 1)\n"
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
LONG = 20.0


def edit(old, new, id="e", path="lines.txt"):
    return call("edit_file", {"path": path, "old_string": old, "new_string": new}, id)


def start(make_client, project_dir, coder, project=None, content="go", lead=None, **conversation):
    """A lead that opens one Coder, in a project with `lines.txt` and `check.py` in it;
    returns the client, the project's and the conversation's ids, and the run's."""
    (project_dir / "lines.txt").write_bytes(LINES.encode())
    (project_dir / "check.py").write_bytes(CHECK.encode())
    client, _model = make_client({
        "Lead": lead or [step(call("spawn_agent", {"role": "Coder", "task": "do it"}, "s")),
                         text("done")],
        "Coder": coder,
    })
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    if project:
        assert client.patch(f"/api/projects/{pid}", json=project).status_code == 200
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    settings = {"permission_mode": "full_auto", "spawn_approval": "never", **conversation}
    assert client.patch(f"/api/conversations/{cid}", json=settings).status_code == 200
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": content}).json()["run"]
    return client, pid, cid, run["id"]


def meanwhile(project_dir, old, new, path="lines.txt"):
    """The user changes the project's own file while the agent is at work in its copy."""
    target = project_dir / path
    target.write_bytes(target.read_bytes().replace(old.encode(), new.encode()))


def lines(project_dir, path="lines.txt"):
    return (project_dir / path).read_bytes().decode().split("\n")[:-1]


def card(client, cid, status="pending"):
    snap = until(client, cid, lambda s: [m["status"] for m in s["merges"]] == [status],
                 timeout=LONG)
    return snap["merges"][0]


def of(merge, path="lines.txt"):
    return next(f for f in merge["files"] if f["path"] == path)


def same(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def git(folder, *args):
    done = subprocess.run(["git", *args], cwd=folder, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def repository(folder):
    git(folder, "init", "-q", "-b", "main")
    git(folder, "config", "user.email", "user@example.com")
    git(folder, "config", "user.name", "The User")
    git(folder, "config", "commit.gpgsign", "false")
    # (A newer git - macOS's - runs its upkeep after a commit, in the background: a copy of the
    # git folder met its lock file come and go.)
    git(folder, "config", "maintenance.auto", "false")
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", "as it was")


# --- different lines go together by themselves ----------------------------------------------


@needs_git
def test_different_lines_of_one_file_go_together_and_it_is_one_change_that_can_be_undone(
    make_client, wait_run, project_dir
):
    held = Gate()
    client, _pid, cid, run_id = start(make_client, project_dir, [
        step(edit("two", "TWO-agent")), held.step(text("A done"))])
    held.wait_partial()
    meanwhile(project_dir, "six", "SIX-user")
    held.release()
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert [m["status"] for m in snap["merges"]] == ["applied"]       # nobody had to be asked
    assert lines(project_dir) == ["one", "TWO-agent", "three", "four", "five", "SIX-user", "seven"]
    # on record as one change, from what the project had to what it has now
    (change,) = [f for f in snap["file_changes"]
                 if f["path"] == "lines.txt" and f["status"] == "applied"]
    # (the snapshot carries a change's diff, not its texts) the agent's line is what this
    # record changed; the user's line was the project's already and is no part of it
    assert "+TWO-agent" in change["diff"] and "-two" in change["diff"]
    assert "+SIX-user" not in change["diff"] and "-six" not in change["diff"]
    assert (change["additions"], change["deletions"]) == (1, 1)
    assert client.post(f"/api/file-changes/{change['id']}/revert").status_code == 200
    assert lines(project_dir) == ["one", "two", "three", "four", "five", "SIX-user", "seven"]


@needs_git
def test_where_the_user_is_asked_a_file_that_went_together_says_so(
    make_client, wait_run, project_dir
):
    held = Gate()
    client, _pid, cid, run_id = start(make_client, project_dir, [
        step(edit("two", "TWO-agent")), held.step(text("A done"))], permission_mode="ask")
    held.wait_partial()
    meanwhile(project_dir, "six", "SIX-user")
    held.release()
    merge = card(client, cid)
    assert of(merge)["state"] == "merged" and merge["check"] is None   # no check command is set
    assert "SIX-user" in (project_dir / "lines.txt").read_text(encoding="utf-8")
    assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 200
    wait_run(client, cid, run_id, timeout=LONG)
    assert lines(project_dir)[1] == "TWO-agent" and lines(project_dir)[5] == "SIX-user"


# --- the same lines are asked about ---------------------------------------------------------


@needs_git
@pytest.mark.parametrize("choice, second", [("agent", "TWO-agent"), ("project", "TWO-user")])
def test_the_same_lines_are_asked_about_and_the_rest_of_both_sides_is_kept(
    make_client, wait_run, project_dir, choice, second
):
    held = Gate()
    client, _pid, cid, run_id = start(make_client, project_dir, [
        step(edit("two", "TWO-agent", "e1")), step(edit("six", "SIX-agent", "e2")),
        held.step(text("A done"))])
    held.wait_partial()
    meanwhile(project_dir, "two", "TWO-user")
    meanwhile(project_dir, "four", "FOUR-user")
    held.release()
    merge = card(client, cid)                                   # asked, even in full auto
    file = of(merge)
    assert file["state"] == "conflict" and file["whole"] is False
    shown = json.dumps(file)
    assert "TWO-agent" in shown and "TWO-user" in shown         # both sides of what clashes
    sides = file["sides"]
    assert sides["project"]["changed_at"] and sides["agent"]["changed_at"]
    assert sides["newer"] == "project"                          # the user's came last here
    assert sides["project"]["changed_at"] >= sides["agent"]["changed_at"]
    # nothing is chosen for the user: without their word nothing is taken
    assert client.post(f"/api/merges/{merge['id']}/approve").status_code in (409, 422)
    assert lines(project_dir)[1] == "TWO-user" and lines(project_dir)[5] == "six"
    assert client.post(f"/api/merges/{merge['id']}/approve",
                       json={"choices": {"lines.txt": choice}, "shown": seen(merge)}).status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["merges"][0]["status"] == "applied"
    # the choice is for what clashes; what each side changed elsewhere stays
    assert lines(project_dir) == ["one", second, "three", "FOUR-user", "five", "SIX-agent", "seven"]


@pytest.mark.parametrize("why", ["no git", "not text"])
def test_a_file_that_cannot_be_merged_line_by_line_is_asked_about_whole(
    make_client, wait_run, project_dir, monkeypatch, tmp_path, why
):
    if why == "no git":
        monkeypatch.setenv("PATH", str(tmp_path / "nothing-is-here"))
        coder, path = step(edit("two", "TWO-agent")), "lines.txt"
    else:
        (project_dir / "blob.bin").write_bytes(b"\x00\x01base\x00")
        coder = step(call("run_command", {"command": (
            "python -c \"open('blob.bin','wb').write(bytes([0,2,65,0]))\"")}, "c"))
        path = "blob.bin"
    held = Gate()
    client, _pid, cid, run_id = start(make_client, project_dir, [coder, held.step(text("A done"))])
    held.wait_partial()
    if why == "no git":
        meanwhile(project_dir, "six", "SIX-user")
    else:
        (project_dir / "blob.bin").write_bytes(b"\x00\x03user\x00")
    held.release()
    merge = card(client, cid)
    file = of(merge, path)
    assert file["state"] == "conflict" and file["whole"] is True and file["note"]
    if why == "no git":
        assert "git" in file["note"]                    # why it is the whole file, said
    assert client.post(f"/api/merges/{merge['id']}/approve",
                       json={"choices": {path: "agent"}, "shown": seen(merge)}).status_code == 200
    wait_run(client, cid, run_id, timeout=LONG)
    if why == "no git":                                 # the agent's file, whole: as it is today
        assert lines(project_dir) == ["one", "TWO-agent", "three", "four", "five", "six", "seven"]
    else:
        assert (project_dir / "blob.bin").read_bytes() == bytes([0, 2, 65, 0])


# --- the check: on the joined state, in the copy, before the user is asked --------------------


@needs_git
def test_the_check_runs_on_the_joined_state_in_the_copy_before_anything_is_taken(
    make_client, wait_run, project_dir
):
    held = Gate()
    client, _pid, cid, run_id = start(
        make_client, project_dir,
        [step(edit("two", "TWO-agent")), held.step(text("A done"))],
        project={"check_command": "python check.py TWO-agent SIX-user"})
    held.wait_partial()
    meanwhile(project_dir, "six", "SIX-user")
    held.release()
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (merge,) = snap["merges"]
    check = merge["check"]
    # it passed: it saw the agent's line and the user's together - that is the joined state
    assert (check["state"], check["exit_code"]) == ("passed", 0)
    assert check["command"] == "python check.py TWO-agent SIX-user"
    where = next(line for line in check["output"].splitlines() if line.startswith("CWD="))[4:]
    assert not same(where.strip(), project_dir)                 # in the copy, not the project
    assert merge["status"] == "applied"                         # full auto: taken once it passed
    assert lines(project_dir)[1] == "TWO-agent" and lines(project_dir)[5] == "SIX-user"


GO_ON = step(call("message_agent", {"to": "Coder", "message": "fix it"}, "m"))


@pytest.mark.parametrize("path, mode, carded", [
    ("AGENTS.md", "full_auto", False), ("docs/CLAUDE.md", "full_auto", False),
    (".claude/settings.json", "full_auto", True), ("AGENTS.md", "auto_edit", True)])
def test_a_copys_instruction_file_goes_in_at_full_auto_and_the_rest_still_waits(
    make_client, wait_run, project_dir, path, mode, carded
):
    """B-328 (K-fullauto-sorma 2.5 at Take in): a Coder's copy changing AGENTS.md at Full auto
    is taken in like any file; `.claude` (and every other standing name) still waits on the
    card, and below Full auto the instruction file does too."""
    client, _pid, cid, run_id = start(
        make_client, project_dir, [step(write(path, "x")), text("done")], permission_mode=mode)
    if not carded:
        snap = wait_run(client, cid, run_id, timeout=LONG)
        (merge,) = snap["merges"]
        assert merge["status"] == "applied" and of(merge, path)["state"] == "applied"
        assert (project_dir / path).read_text(encoding="utf-8") == "x"
        return
    merge = card(client, cid)
    assert "taken only on the user's word" in (of(merge, path)["note"] or "")
    assert not (project_dir / path).exists()
    assert client.post(f"/api/merges/{merge['id']}/reject").status_code == 200
    wait_run(client, cid, run_id, timeout=LONG)
    assert not (project_dir / path).exists()


def test_at_full_auto_a_failing_check_goes_back_to_the_lead_and_the_fix_is_taken_in(
    make_client, wait_run, project_dir
):
    """K-fullauto-sorma 2: told the check failed (with its output's end), the Lead has the Coder
    go on in its own copy (B-322); passing then, the work goes in with no card."""
    client, _pid, cid, run_id = start(
        make_client, project_dir,
        [step(write("a.txt", "A")), text("A done"), step(edit("two", "TWO")), text("fixed")],
        project={"check_command": "python check.py TWO"},
        lead=[step(call("spawn_agent", {"role": "Coder", "task": "do it"}, "s")), GO_ON,
              text("done")])
    snap = wait_run(client, cid, run_id, timeout=LONG)
    told = next(t["result"] for t in snap["tool_calls"] if t["name"] == "spawn_agent")
    assert "did not pass" in told and "tell Coder to go on" in told and "CWD=" in told
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A" and "TWO" in lines(project_dir)
    assert "applied" in [m["status"] for m in snap["merges"]]
    assert not [m for m in snap["merges"] if m["status"] in ("pending", "kept")]


def test_at_full_auto_a_check_that_keeps_failing_is_the_users_after_two_rounds(
    make_client, wait_run, project_dir
):
    client, _pid, cid, run_id = start(
        make_client, project_dir,
        [step(write("a.txt", "A")), text("A done"), text("tried"), text("tried again")],
        project={"check_command": "python check.py NEVER-THERE"},
        lead=[step(call("spawn_agent", {"role": "Coder", "task": "do it"}, "s")),
              GO_ON, step(call("message_agent", {"to": "Coder", "message": "fix it"}, "m2")),
              text("done")])
    snap = until(client, cid, lambda s: "pending" in [m["status"] for m in s["merges"]],
                 timeout=LONG)
    told = [t["result"] or "" for t in snap["tool_calls"]
            if t["name"] in ("spawn_agent", "message_agent")]
    assert sum("did not pass" in said for said in told) == 2  # twice to the Lead, then the card
    merge = next(m for m in snap["merges"] if m["status"] == "pending")
    assert (merge["check"]["state"], merge["check"]["exit_code"]) == ("failed", 1)
    assert not (project_dir / "a.txt").exists()
    assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 200
    wait_run(client, cid, run_id, timeout=LONG)
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"


def test_where_commands_are_asked_about_the_check_runs_before_the_card_and_again_on_a_click(
    make_client, wait_run, project_dir
):
    client, _pid, cid, run_id = start(
        make_client, project_dir, [step(write("a.txt", "A")), text("A done")],
        project={"check_command": "python check.py one"}, permission_mode="ask")
    merge = card(client, cid)
    snap = client.get(f"/api/conversations/{cid}").json()
    # B-355: the user's own check, in the copy, ran by itself before the card - nobody asked
    assert merge["check"]["state"] == "passed" and len(snap["commands"]) == 1
    del client.headers["Origin"]                        # the click is the page's own
    assert client.post(f"/api/merges/{merge['id']}/check").status_code == 403
    client.headers["Origin"] = ORIGIN
    assert client.post(f"/api/merges/{merge['id']}/check").status_code in (200, 202)
    snap = until(client, cid, lambda s: len(s["commands"]) == 2 and s["merges"][0]["check"][
        "state"] in ("passed", "failed"), timeout=LONG)
    assert snap["merges"][0]["check"]["state"] == "passed"
    assert snap["merges"][0]["status"] == "pending" and not (project_dir / "a.txt").exists()
    assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 200
    wait_run(client, cid, run_id, timeout=LONG)
    assert (project_dir / "a.txt").exists()


@pytest.mark.parametrize("ticked, taken", [(True, False), (False, True)])
def test_in_a_turn_nobody_watches_a_failed_check_takes_nothing_and_keeps_the_copy(
    make_client, wait_run, project_dir, ticked, taken
):
    (project_dir / "lines.txt").write_bytes(LINES.encode())
    (project_dir / "check.py").write_bytes(CHECK.encode())
    client, _model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "do it"}, "s")),
                 text("done")],
        "Coder": [step(write("a.txt", "A")), text("A done")]})
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    command = "python check.py NEVER-THERE"
    assert client.patch(f"/api/projects/{pid}", json={"check_command": command}).status_code == 200
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    rules = [allow(client, cid, command)] if ticked else []
    made = trigger(client, pid, cid, permissions={"write": True, "commands": rules, "agents": 1})
    run_id = run_now(client, made["id"])
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (merge,) = snap["merges"]
    assert (project_dir / "a.txt").exists() is taken
    if ticked:      # the trigger lets this very command run: it ran, failed, and nothing is taken
        assert merge["check"]["state"] == "failed"
        assert merge["status"] == "kept" and merge["kept_in"]    # there for the user
    else:           # it may not run here: taken as before, and said to be unchecked
        assert merge["check"]["state"] == "not_run" and merge["status"] == "applied"
    assert merge["commit"] is None                      # and nothing is ever committed here


# --- K-evrim review: a check the gates ask about (it deletes) -----------------------------------

# Exits 0; `rm -rf` is never reached - but it is what `harms` sees, as in `rm -rf dist && npm test`.
HARMS = "python check.py one || rm -rf dist"


def asked_command(client, cid):
    snap = until(client, cid, lambda s: any(c["status"] == "proposed" for c in s["commands"]),
                 timeout=LONG)
    one = next(c for c in snap["commands"] if c["status"] == "proposed")
    why = next(t for t in snap["tool_calls"] if t["id"] == one["tool_call_id"])["why_asked"]
    return one, why


@pytest.mark.parametrize("mode", ["ask", "auto_edit"])
def test_koloni_asks_before_its_own_check_that_deletes_and_the_users_click_runs_it(
    make_client, wait_run, project_dir, mode
):
    client, _pid, cid, run_id = start(
        make_client, project_dir, [step(write("a.txt", "A")), text("A done")],
        project={"check_command": HARMS}, permission_mode=mode)
    # B-355's check by itself asks first, with why; declined, it did not run - no failure.
    one, why = asked_command(client, cid)
    assert why == "Deletes files or disks."
    assert client.post(f"/api/commands/{one['id']}/reject").status_code == 200
    merge = card(client, cid)
    assert merge["check"]["state"] == "not_run"
    assert merge["check"]["note"] == "not run: declined on its card - Deletes files or disks."
    # The user's own click is its leave: it runs, unasked, as before.
    assert client.post(f"/api/merges/{merge['id']}/check").status_code == 200
    snap = until(client, cid, lambda s: s["merges"][0]["check"]["state"] == "passed",
                 timeout=LONG)
    assert [c["status"] for c in snap["commands"] if c["command"] == HARMS] == [
        "rejected", "exited"]
    assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 200
    wait_run(client, cid, run_id, timeout=LONG)
    assert (project_dir / "a.txt").exists()


def test_at_full_auto_a_check_declined_on_its_card_sends_no_work_back(
    make_client, wait_run, project_dir
):
    client, _pid, cid, run_id = start(
        make_client, project_dir, [step(write("a.txt", "A")), text("A done")],
        project={"check_command": HARMS})
    one, why = asked_command(client, cid)  # (once: no second card)
    assert why == "Deletes files or disks."
    assert client.post(f"/api/commands/{one['id']}/reject").status_code == 200
    merge = card(client, cid)  # (not taken unchecked: the user's card)
    assert merge["check"]["state"] == "not_run"
    assert client.app.state.runner._check_rounds.get(run_id, 0) == 0
    assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert [c["status"] for c in snap["commands"]] == ["rejected"]
    spawned = next(t for t in snap["tool_calls"] if t["name"] == "spawn_agent")
    assert "did not pass" not in spawned["result"] and (project_dir / "a.txt").exists()


def test_a_triggers_leave_for_the_very_check_still_runs_it_nobody_watching(
    make_client, wait_run, project_dir
):
    (project_dir / "lines.txt").write_bytes(LINES.encode())
    (project_dir / "check.py").write_bytes(CHECK.encode())
    client, _model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "do it"}, "s")),
                 text("done")],
        "Coder": [step(write("a.txt", "A")), text("A done")]})
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    # (Nobody watching, harm is the trigger's to judge, `_night_asks`; one naming the project folder
    # is asked at every level, `copy_reason` - a rule is one plain command.)
    named = f"python {(project_dir / 'check.py').as_posix()} one"
    assert client.patch(f"/api/projects/{pid}", json={"check_command": named}).status_code == 200
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    made = trigger(client, pid, cid, permissions={
        "write": True, "commands": [allow(client, cid, named)], "agents": 1})
    run_id = run_now(client, made["id"])
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (merge,) = snap["merges"]
    assert merge["check"]["state"] == "passed" and merge["status"] == "applied"
    assert [c["status"] for c in snap["commands"]] == ["exited"]


# --- the commit: the user's own click, of the files that were taken ---------------------------


@needs_git
def test_what_was_taken_is_committed_by_the_users_click_and_nothing_else_with_it(
    make_client, wait_run, project_dir
):
    (project_dir / "lines.txt").write_bytes(LINES.encode())
    (project_dir / "check.py").write_bytes(CHECK.encode())
    repository(project_dir)
    (project_dir / "other.txt").write_text("the user's own", encoding="utf-8")
    git(project_dir, "add", "other.txt")                # staged by the user, for a commit of theirs
    client, _pid, cid, run_id = start(
        make_client, project_dir,
        [step(write("a.txt", "A")), step(edit("two", "TWO-agent")), text("A done")],
        project={"git_commit": True}, permission_mode="ask")
    merge = card(client, cid)
    assert merge["commit"] is None                      # not before it is in the project
    assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)  # the turn does not wait for a commit
    offer = snap["merges"][0]["commit"]
    assert offer["state"] == "offered" and "Coder" in offer["message"] and offer["sha"] is None
    assert git(project_dir, "log", "--format=%s") == "as it was"      # nothing by itself
    said = "Take the Coder's work"
    del client.headers["Origin"]
    assert client.post(f"/api/merges/{merge['id']}/commit", json={"message": said}).status_code == 403
    client.headers["Origin"] = ORIGIN
    done = client.post(f"/api/merges/{merge['id']}/commit", json={"message": said})
    assert done.status_code == 200, done.text
    assert done.json()["commit"]["state"] == "committed"
    assert done.json()["commit"]["sha"] == git(project_dir, "rev-parse", "HEAD")
    assert git(project_dir, "log", "-1", "--format=%s|%an") == f"{said}|The User"
    assert sorted(git(project_dir, "show", "--name-only", "--format=", "HEAD").split()) == [
        "a.txt", "lines.txt"]
    assert git(project_dir, "diff", "--cached", "--name-only") == "other.txt"   # still theirs
    assert client.post(f"/api/merges/{merge['id']}/commit",
                       json={"message": "again"}).status_code == 409           # once


@needs_git
@pytest.mark.parametrize("stands_in_the_way", ["no branch", "a hook says no"])
def test_a_commit_that_cannot_be_made_says_why_and_leaves_the_work_in_the_project(
    make_client, wait_run, project_dir, stands_in_the_way
):
    (project_dir / "lines.txt").write_bytes(LINES.encode())
    (project_dir / "check.py").write_bytes(CHECK.encode())
    repository(project_dir)
    if stands_in_the_way == "no branch":
        git(project_dir, "checkout", "-q", "--detach")
    else:
        hook = project_dir / ".git" / "hooks" / "pre-commit"
        hook.write_bytes(b"#!/bin/sh\necho THE-HOOK-SAYS-NO >&2\nexit 1\n")
        hook.chmod(0o755)
    before = git(project_dir, "rev-parse", "HEAD")
    client, _pid, cid, run_id = start(
        make_client, project_dir, [step(write("a.txt", "A")), text("A done")],
        project={"git_commit": True}, permission_mode="ask")
    merge = card(client, cid)
    assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 200
    wait_run(client, cid, run_id, timeout=LONG)
    refused = client.post(f"/api/merges/{merge['id']}/commit", json={"message": "take it"})
    assert refused.status_code == 409
    if stands_in_the_way == "a hook says no":
        assert "THE-HOOK-SAYS-NO" in refused.text
    assert git(project_dir, "rev-parse", "HEAD") == before
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"  # taken, and not committed


@needs_git
@pytest.mark.parametrize("case", ["setting off", "not the top of the repository"])
def test_a_commit_is_offered_only_where_the_user_said_so_and_the_project_is_the_repository(
    make_client, wait_run, tmp_path, case
):
    top = tmp_path / "repo"
    project_dir = top if case == "setting off" else top / "part"
    project_dir.mkdir(parents=True)
    (project_dir / "hello.py").write_bytes(b"print('hi')\n")
    (project_dir / "lines.txt").write_bytes(LINES.encode())
    (project_dir / "check.py").write_bytes(CHECK.encode())
    repository(top)
    client, _pid, cid, run_id = start(
        make_client, project_dir, [step(write("a.txt", "A")), text("A done")],
        project={"git_commit": case != "setting off"}, permission_mode="ask")
    merge = card(client, cid)
    assert client.post(f"/api/merges/{merge['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    commit = snap["merges"][0]["commit"]
    if case == "setting off":
        assert commit is None
    else:  # where the commit would be, why there is none (K-alt-klasor-git)
        assert commit["state"] == "not_offered" and commit["sha"] is None
        assert "a subfolder of a git repository" in commit["message"]
    assert client.post(f"/api/merges/{merge['id']}/commit",
                       json={"message": "take it"}).status_code == 409
    assert git(top, "log", "--format=%s") == "as it was"


# --- only the app's own page sets what runs and what is committed ----------------------------


def test_the_check_command_and_the_commit_setting_are_the_users_alone(make_client, project_dir):
    client, _model = make_client({"Lead": [text("x")]})
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    for change in ({"check_command": "python -c pass"}, {"git_commit": True},
                   {"measure_command": " python measure.py "}):  # (K-evrim: it is run, too)
        assert client.patch(f"/api/projects/{pid}", json=change).status_code == 403
        assert client.patch(f"/api/projects/{pid}", json=change,
                            headers={"Origin": "http://evil.example"}).status_code == 403
        assert client.patch(f"/api/projects/{pid}", json=change,
                            headers={"Origin": ORIGIN}).status_code == 200
    kept = client.get("/api/projects").json()[0]
    assert (kept["check_command"], kept["git_commit"]) == ("python -c pass", True)
    assert kept["measure_command"] == "python measure.py"
    for name in ("check_command", "measure_command"):
        assert client.patch(f"/api/projects/{pid}", json={name: "x" * 501},
                            headers={"Origin": ORIGIN}).status_code == 422
    assert client.patch(f"/api/projects/{pid}", json={"measure_command": " "},
                        headers={"Origin": ORIGIN}).json()["measure_command"] is None


@needs_git
def test_a_new_file_git_ignores_is_a_row_not_offered_and_its_copy_is_not_kept(
        make_client, wait_run, project_dir, tmp_path):
    # B-189 (live): a generated data/clean.csv in .gitignore was taken in, and two teams' clashed.
    from app import copies
    from tests.test_copy_scenarios import one

    (project_dir / ".gitignore").write_text("*.log" + chr(10), encoding="utf-8")
    repository(project_dir)
    client, _model, cid, run_id = one(make_client, project_dir, [
        step(write("run.log", "made")), step(write("a.py", "x = 1" + chr(10))), text("done")])
    snap = wait_run(client, cid, run_id)
    assert (project_dir / "a.py").exists() and not (project_dir / "run.log").exists()
    ((merge,),) = [snap["merges"]]
    assert merge["status"] == "applied"
    assert {f["path"]: (f["state"], f["note"]) for f in merge["files"]}["run.log"] == (
        "left_out", copies.IGNORED)
    # (Not kept: no copy waits for the user's word, nor is one left on disk.)
    assert not [m for m in snap["merges"] if m["status"] == "kept"]
    assert not any(place.iterdir()) if (place := copies.folder(client.app.state.settings.runtime_root)
                                        ) and place.exists() else True
    told = next(t["result"] for t in snap["tool_calls"] if t["name"] == "spawn_agent")
    assert f"run.log ({copies.IGNORED})" in told
