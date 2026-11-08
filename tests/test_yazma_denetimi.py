"""K-yazma-denetimi: a file that tells later turns what they may do or runs by itself
(`project_view.standing`), written by a command that never named it, is put back after the
command - in a watched turn with a card that offers to keep it, while no approval is
answered; in an unwatched one refused. A commit asks first where git's hooks or config
changed in the turn."""

import asyncio
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import koloni
from app.agent import KEEP_CARDS, _command_names, _git_parts, _put_back, _restore, _Watch
from app.agent import merge as agent_merge
from app.commands import writes_git_config
from app.project_view import LINK as STANDING_LINK
from app.project_view import ProjectView, standing
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_commands import cmd
from tests.test_chat_flow import start_in_mode, text
from tests.test_codex_app_server_scenarios import ACCEPT, RUN, answers
from tests.test_native_agent import native_app, start  # noqa: F401  (a fixture)
from tests.test_parallel import until
from tests.test_spawn import call, step
from tests.test_take_in_scenarios import ORIGIN, card, needs_git, repository
from tests.test_take_in_scenarios import git as in_repo
from tests.test_take_in_scenarios import start as take_in_start
from tests.test_trigger_scenarios import NOBODY, allow, run_now, trigger

WORKFLOW = ".github/workflows/x.yml"
PTH = ".venv/Lib/site-packages/evil.pth"


def answer(client, question, word):
    said = client.post(f"/api/questions/{question['id']}/answer", json={"answer": word},
                       headers={"Origin": ORIGIN})
    assert said.status_code == 200, said.text


def open_card(client, cid):
    snap = until(client, cid, lambda s: [q for q in s["questions"] if q["status"] != "answered"],
                 timeout=20)
    (question,) = [q for q in snap["questions"] if q["status"] != "answered"]
    return snap, question


def test_the_set_is_the_standing_names_gits_hooks_and_config_and_pth_files(tmp_path):
    for rel in [WORKFLOW, "docs/AGENTS.md", ".git/hooks/pre-commit", ".git/config", PTH,
                ".claude/settings.json", ".claude/worktrees/w/a.py", ".git/hooks/pre-push.sample",
                ".git/objects/ab/cd", ".git/HEAD", "node_modules/x/.github/y.yml",
                "node_modules/.bin/tool", "src/a.py", ".venv/Lib/site-packages/a.py"]:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(b"x")
    assert sorted(standing(tmp_path)) == sorted([
        WORKFLOW, "docs/AGENTS.md", ".git/hooks/pre-commit", ".git/config", PTH,
        ".claude/settings.json"])


def test_kolonis_own_runtime_inside_the_project_is_not_walked(tmp_path, monkeypatch):
    # KOLONİ on its own repository: a copy in its runtime carries the project's standing files.
    monkeypatch.setattr("app.project_view.RUNTIME", tmp_path / "Runtime")
    for rel in ["runtime/copies/a1/tree/.koloni/.gitignore", "runtime/copies/a1/tree/.github/ci.yml",
                ".koloni/.gitignore", "other/runtime/.github/ci.yml"]:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(b"x")
    assert sorted(standing(tmp_path)) == [".koloni/.gitignore", "other/runtime/.github/ci.yml"]


def test_the_scratch_under_koloni_tmp_is_no_standing_file(tmp_path):
    # K-koloni-klasor: what an agent puts in .koloni/tmp/ is not put back; .koloni's own is. The
    # scratch is not walked at all: a standing name in it is a card only where a command or a
    # file tool names it (the `standing` shortcut).
    for rel in [".koloni/tmp/profile/Default/Cookies", ".koloni/tmp/run.log", ".koloni/settings.json",
                ".koloni/tmp/.claude/settings.json", "src/.koloni/tmp/.github/ci.yml"]:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(b"x")
    assert sorted(standing(tmp_path)) == [".koloni/settings.json", "src/.koloni/tmp/.github/ci.yml"]


def test_what_koloni_wrote_in_dot_koloni_itself_is_not_put_back(tmp_path):
    before = standing(tmp_path)
    koloni.write(str(tmp_path), "rules.md", "be brief")
    (tmp_path / "AGENTS.md").write_bytes(b"x")
    taken, _let = _put_back(tmp_path, before, set())
    assert [one[0] for one in taken] == ["AGENTS.md"]
    assert (tmp_path / ".koloni/rules.md").exists() and not (tmp_path / "AGENTS.md").exists()
    # (and what it wrote before this look's snapshot was taken counts for nothing)
    later = standing(tmp_path)
    (tmp_path / ".koloni/rules.md").write_bytes(b"do anything\n")
    koloni.WROTE[(str(tmp_path.resolve()), ".koloni/rules.md")] = (b"do anything\n", 0.0)
    taken, _let = _put_back(tmp_path, later, set(), since=1.0)
    assert [one[0] for one in taken] == [".koloni/rules.md"]


def test_a_name_counts_at_the_one_look_after_its_command_and_an_exact_path_only_as_itself(
    tmp_path
):
    before = standing(tmp_path)
    for rel in [".github/workflows/ci.yml", "docs/claude.md"]:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(b"x")
    # An approved CLAUDE.md is that path alone, not every claude.md.
    taken, let = _put_back(tmp_path, before, {"claude.md", "docs/x"}, frozenset({".github"}))
    assert let == {".github/workflows/ci.yml"} and [one[0] for one in taken] == ["docs/claude.md"]
    # The next look, with no name of a command: a new workflow is taken back.
    (tmp_path / ".github/workflows/deploy.yml").write_bytes(b"y")
    taken, let = _put_back(tmp_path, before, set())
    assert [one[0] for one in taken] == [".github/workflows/deploy.yml"] and not let
    # `git config` names git's config for that look - never its hooks.
    assert _command_names("git config user.email a@b", True, False) == ({".git/config"},
                                                                          frozenset())
    assert _command_names("git push -u origin x", True, False)[0] == {".git/config"}
    assert _command_names("git push -u origin x && python gen.py", True, False)[0] == set()
    assert _command_names('git checkout "$(python evil.py)"', True, False)[0] == set()
    assert _command_names("git -c core.hooksPath=tools/h checkout x", True, False)[0] == set()
    assert not writes_git_config("git config core.fsmonitor x > y")
    # Run unasked (agy's own, say), nothing it names stands.
    assert _command_names("git config core.fsmonitor cmd", False, False) == (set(), frozenset())
    # What a checkout or a pull changes there names nothing.
    assert _command_names("git checkout main", True, False)[1] == frozenset()
    # An install's .pth only where the install is all the command is.
    assert "*.pth" not in _command_names("pip install foo; python x.py", True, True)[1]
    # (a skill's script run unasked names nothing, whatever it says)
    assert _command_names("python s.py .github/workflows/x.yml", False, True) == (
        set(), frozenset())
    assert _command_names("git add .github/workflows/ci.yml", True, False) == (
        set(), frozenset({".github"}))
    # Nobody watching, the .pth an install adds stands (watched it is a card).
    assert "*.pth" in _command_names("pip install foo", True, True)[1]
    assert "*.pth" in _command_names("python -m pip install -e .", True, True)[1]
    assert "*.pth" not in _command_names("pip install foo", True, False)[1]
    assert "*.pth" not in _command_names("npm install foo", True, True)[1]


@pytest.mark.skipif(sys.platform != "win32", reason="a junction is Windows'")
def test_a_junction_at_a_standing_name_is_seen_and_taken_away_itself(tmp_path):
    project, elsewhere = tmp_path / "p", tmp_path / "elsewhere"
    project.mkdir()
    elsewhere.mkdir()
    (elsewhere / "settings.json").write_bytes(b"{}")
    before = standing(project)
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(project / ".claude"), str(elsewhere)],
                          capture_output=True)
    assert made.returncode == 0, made.stderr
    assert list(standing(project)) == [".claude"]
    taken, _let = _put_back(project, before, set())
    assert [one[0] for one in taken] == [".claude"] and taken[0][2] is None
    assert not os.path.lexists(project / ".claude")
    assert (elsewhere / "settings.json").read_bytes() == b"{}"  # (never through it)
    # One whose folder is gone is taken away too.
    subprocess.run(["cmd", "/c", "mklink", "/J", str(project / ".claude"), str(elsewhere)],
                   capture_output=True, check=True)
    shutil.rmtree(elsewhere)
    taken, _let = _put_back(project, before, set())
    assert taken[0][2] is None and not os.path.lexists(project / ".claude")
    # One that was there before and became a folder of files, or a file, is taken away - and
    # not made again: KOLONİ makes no link. The next look finds nothing more.
    for instead in ("a folder", "a file"):
        elsewhere.mkdir(exist_ok=True)
        subprocess.run(["cmd", "/c", "mklink", "/J", str(project / ".claude"), str(elsewhere)],
                       capture_output=True, check=True)
        linked = standing(project)
        os.rmdir(project / ".claude")
        if instead == "a folder":
            (project / ".claude").mkdir()
            (project / ".claude/settings.json").write_bytes(b"evil")
        else:
            (project / ".claude").write_bytes(b"evil")
        taken, _let = _put_back(project, linked, set())
        assert all(one[2] is None for one in taken), taken
        said = next(one[3] for one in taken if one[0] == ".claude")
        assert "KOLONİ does not make links: make it again yourself" in said
        assert not os.path.lexists(project / ".claude") and linked == {}
        assert _put_back(project, linked, set()) == ([], set())


def test_the_folder_core_hookspath_names_is_watched_and_counts_as_hooks(tmp_path):
    (tmp_path / ".git").mkdir()
    for hooks in [b".githooks", str(tmp_path / ".githooks").encode()]:  # (whole, too)
        (tmp_path / ".git/config").write_bytes(b"[core]\n\tbare = false\n\thooksPath = %s\n" % hooks)
        (tmp_path / ".githooks").mkdir(exist_ok=True)
        (tmp_path / ".githooks/pre-commit").write_bytes(b"#!/bin/sh\n")
        found = standing(tmp_path)
        assert ".githooks/pre-commit" in found, found
        changed = {**found, ".githooks/pre-commit": b"#!/bin/sh\necho evil\n"}
        assert _git_parts(changed, tmp_path)["hooks"] != _git_parts(found, tmp_path)["hooks"]
        assert _git_parts(changed, tmp_path)["config"] == _git_parts(found, tmp_path)["config"]


def test_keep_of_a_link_an_agent_made_writes_nothing(tmp_path):
    """Keep puts back what the agent left - where that was a link, KOLONİ makes none, and
    never writes what it holds a link as."""
    (tmp_path / ".claude").mkdir()
    said = _restore(tmp_path, ".claude/settings.json", STANDING_LINK + b"C:\\elsewhere")
    assert "KOLONİ makes no links" in said
    assert not (tmp_path / ".claude/settings.json").exists()


def test_what_was_put_back_is_in_a_siblings_snapshot_by_its_bytes(client, project_dir):
    """A sibling agent that writes other bytes there just after is still seen: what stands for
    it is what was put back, not the path."""
    runner = client.app.state.runner
    (project_dir / "AGENTS.md").write_bytes(b"orig")
    sibling = _Watch(ProjectView(project_dir))
    sibling.ctx = SimpleNamespace(root=str(project_dir))
    sibling.standing = {"AGENTS.md": b"evil one"}  # (as it last looked: the first agent's write)
    runner._watches["other"] = [sibling]
    try:
        asyncio.run(runner._stand_in_watches(
            str(project_dir), {"AGENTS.md": b"orig"}, [("AGENTS.md", b"evil one", None, None)]))
    finally:
        runner._watches.pop("other")
    assert sibling.standing == {"AGENTS.md": b"orig"}
    (project_dir / "AGENTS.md").write_bytes(b"evil two")  # (the sibling's own write)
    taken, _let = _put_back(project_dir, sibling.standing, set())
    assert [one[0] for one in taken] == ["AGENTS.md"]
    assert (project_dir / "AGENTS.md").read_bytes() == b"orig"


def test_a_turns_copies_are_bounded_and_old_ones_go(tmp_path, monkeypatch):
    project, keep_in = tmp_path / "p", tmp_path / "runtime" / "taken-back" / "run"
    project.mkdir()
    before = standing(project)
    (project / "AGENTS.md").write_bytes(b"x" * 100)
    monkeypatch.setattr(agent_merge, "TAKEN_BACK_BYTES", 50)
    taken, _let = _put_back(project, before, set(), keep_in=keep_in)
    # (Past the turn's room for copies it is put back all the same: no copy is ever a reason.)
    assert taken[0][2] is None and "no copy of the agent's version was kept" in taken[0][3]
    assert not (project / "AGENTS.md").exists()
    (project / "AGENTS.md").write_bytes(b"x" * 100)
    monkeypatch.setattr(agent_merge, "TAKEN_BACK_BYTES", 1000)
    taken, _let = _put_back(project, before, set(), keep_in=keep_in)
    assert taken[0][2] is None and not (project / "AGENTS.md").exists()
    (name, rel), = [line.split("\t") for line in
                    (keep_in / "paths.txt").read_text(encoding="utf-8").splitlines()]
    assert rel == "AGENTS.md" and (keep_in / name).read_bytes() == b"x" * 100
    old = time.time() - 15 * 86400
    os.utime(keep_in, (old, old))
    agent_merge._prune_taken_back(tmp_path / "runtime")
    assert not keep_in.exists()


def test_many_at_once_are_a_few_cards_and_the_rest_refused(make_client, wait_run, project_dir):
    many = {f".claude/agents/a{n:02}.md": "x" for n in range(KEEP_CARDS + 3)}
    executor = ScriptedExecutor([Script(["ok\n"], writes=many)])
    client, _model = make_client([cmd("python make.py"), text("done")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = until(client, cid, lambda s: len(s["questions"]) == KEEP_CARDS, timeout=20)
    assert not (project_dir / ".claude/agents").exists() or not any(
        (project_dir / ".claude/agents").iterdir())
    for question in snap["questions"]:
        answer(client, question, "Take back")
    snap = wait_run(client, cid, run_id, timeout=20)
    refused = [t for t in snap["tool_calls"] if t["name"] == "write_file" and t["status"] == "denied"]
    assert len(refused) == len(many)  # (3 refused at once, the rest by the user)


# --- a native CLI's command ------------------------------------------------------------------


def test_a_workflow_a_codex_command_writes_unnamed_is_taken_back_and_kept_on_the_users_word(
    native_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = native_app([
        {"run": "pytest -q", "touches": {WORKFLOW: "on: push\n"}},
        {"run": "git status"}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)  # at Full auto
    snap, question = open_card(client, cid)
    assert question["options"] == ["Keep", "Take back"]
    assert f"wrote `{WORKFLOW}` without naming it" in question["question"]
    assert not (project_dir / WORKFLOW).exists()  # taken back at once
    time.sleep(1.0)
    # The next request waits for the answer: `git status` is not answered, nor on record.
    assert answers(native_app) == [(RUN, ACCEPT)]
    assert [c["command"] for c in client.get(f"/api/conversations/{cid}").json()["commands"]] == [
        "pytest -q"]
    answer(client, question, "Keep")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert (project_dir / WORKFLOW).read_text(encoding="utf-8") == "on: push\n"
    assert answers(native_app) == [(RUN, ACCEPT), (RUN, ACCEPT)]
    kept = next(t for t in snap["tool_calls"] if t["result"] and t["result"].startswith("kept"))
    assert kept["status"] == "succeeded"


def test_a_new_hook_a_command_writes_is_deleted_and_stays_so_when_taken_back(
    native_app, wait_run, project_dir  # noqa: F811
):
    (project_dir / ".git" / "hooks").mkdir(parents=True)
    client, provider, _ = native_app([
        {"run": "pytest -q", "touches": {".git/hooks/pre-commit": "#!/bin/sh\necho hi\n"}},
        {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    _snap, question = open_card(client, cid)
    assert not (project_dir / ".git/hooks/pre-commit").exists()
    answer(client, question, "Take back")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert not (project_dir / ".git/hooks/pre-commit").exists()
    assert (project_dir / ".git/hooks").is_dir()


# --- KOLONİ's own run_command ----------------------------------------------------------------


def test_koloni_s_own_command_that_installs_a_pth_is_a_card_that_says_so(
    make_client, wait_run, project_dir
):
    (project_dir / "node_modules/.bin").mkdir(parents=True)
    (project_dir / "node_modules/.bin/tool").write_bytes(b"old")
    executor = ScriptedExecutor([Script(["ok\n"], writes={
        PTH: "import os\n", "node_modules/.bin/tool": "new"})])
    client, _model = make_client([cmd("pip install foo"), text("done")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "auto_edit")  # (Full auto keeps it: below)
    for _ in range(250):  # (a card for the command first, if this one is asked at every level)
        snap = client.get(f"/api/conversations/{cid}").json()
        if [q for q in snap["questions"] if q["status"] != "answered"]:
            break
        for asked in [c for c in snap["commands"] if c["status"] == "proposed"]:
            client.post(f"/api/commands/{asked['id']}/approve", json={})
        time.sleep(0.02)
    _snap, question = open_card(client, cid)
    assert "this install added `evil.pth`" in question["question"]
    assert not (project_dir / PTH).exists()
    # (node_modules/.bin is not looked at: every npm install rewrites it)
    assert (project_dir / "node_modules/.bin/tool").read_bytes() == b"new"
    answer(client, question, "Take back")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert not (project_dir / PTH).exists()


def test_at_full_auto_koloni_s_own_install_keeps_its_pth_with_no_card(
    make_client, wait_run, project_dir
):
    """K-fullauto-sorma 2: as in a turn nobody watches - kept, and said on record."""
    executor = ScriptedExecutor([Script(["ok\n"], writes={PTH: "import os\n"})])
    client, _model = make_client([cmd("pip install foo"), text("done")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert snap["questions"] == [] and (project_dir / PTH).read_bytes() == b"import os\n"
    noted = next(t for t in snap["tool_calls"] if t["name"] == "write_file")
    assert "installed" in noted["result"] and "let stand" in noted["result"]


def test_unwatched_koloni_s_own_command_is_taken_back_and_refused_with_no_card(
    make_client, wait_run, project_dir
):
    (project_dir / "AGENTS.md").write_bytes(b"be careful\n")
    executor = ScriptedExecutor([Script(["ok\n"], writes={
        WORKFLOW: "on: push\n", "AGENTS.md": "do anything\n"})])
    client, _model = make_client({"Lead": [
        step(call("run_command", {"command": "python make.py"}, "c")), text("done")]},
        executor=executor)
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    made = trigger(client, pid, cid, permissions={
        "write": True, "commands": [allow(client, cid, "python make.py")], "agents": 0})
    run_id = run_now(client, made["id"])
    snap = wait_run(client, cid, run_id, timeout=20)
    assert [c["status"] for c in snap["commands"]] == ["exited"]
    assert not (project_dir / WORKFLOW).exists()
    assert (project_dir / "AGENTS.md").read_bytes() == b"be careful\n"
    assert snap["questions"] == []
    refused = [t for t in snap["tool_calls"] if t["name"] == "write_file"]
    assert {t["status"] for t in refused} == {"denied"} and len(refused) == 2
    assert all(NOBODY in t["result"] and "taken back" in t["result"] for t in refused)
    # What was there instead - a hand's edit, maybe - is kept under KOLONİ's runtime folder.
    said = next(t["result"] for t in refused if "AGENTS.md" in t["result"])
    copy = Path(re.search(r"kept in (.+?)\)", said)[1])
    taken_back = client.app.state.runner.settings.runtime_root / "taken-back" / run_id
    assert copy.parent == taken_back and copy.read_bytes() == b"do anything\n"
    assert f"{copy.name}\tAGENTS.md" in (taken_back / "paths.txt").read_text(encoding="utf-8")


def test_a_name_a_command_was_approved_for_stands_at_its_own_look_only(
    native_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = native_app([
        {"run": "cp ci.yml .github/workflows/ci.yml", "touches": {".github/workflows/ci.yml": "ci"}},
        {"run": "pytest -q", "touches": {".github/workflows/deploy.yml": "deploy"}},
        {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    asked = until(client, cid, lambda s: [c for c in s["commands"] if c["status"] == "proposed"])
    (command,) = [c for c in asked["commands"] if c["status"] == "proposed"]
    client.post(f"/api/commands/{command['id']}/approve", json={})
    _snap, question = open_card(client, cid)
    assert ".github/workflows/deploy.yml" in question["question"]
    assert (project_dir / ".github/workflows/ci.yml").read_text(encoding="utf-8") == "ci"
    assert not (project_dir / ".github/workflows/deploy.yml").exists()
    answer(client, question, "Take back")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]


def test_a_card_at_a_project_limit_of_one_is_answered_and_the_turn_goes_on(
    native_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = native_app([
        {"run": "pytest -q", "touches": {WORKFLOW: "on: push\n"}},
        {"run": "git status"}, {"say": "ok"}])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={"max_agents": 1},
                        headers={"Origin": ORIGIN}).status_code == 200
    cid, run_id = start(client, project_dir, provider)
    _snap, question = open_card(client, cid)
    answer(client, question, "Keep")
    snap = wait_run(client, cid, run_id, timeout=20)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert answers(native_app) == [(RUN, ACCEPT), (RUN, ACCEPT)]


def test_stopped_during_a_card_nothing_is_left_to_hold_the_folder(
    make_client, wait_run, project_dir
):
    executor = ScriptedExecutor([Script(["ok\n"], writes={WORKFLOW: "x"}), Script(["ok\n"])])
    client, _model = make_client([cmd("python a.py"), cmd("python b.py", "k2"), text("done")],
                                 executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    open_card(client, cid)
    client.post(f"/api/runs/{run_id}/cancel", headers={"Origin": ORIGIN})
    wait_run(client, cid, run_id, timeout=20)
    assert not client.app.state.runner._keeps.get(str(project_dir))
    assert not (project_dir / WORKFLOW).exists()
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": "again"}).json()["run"]
    snap = wait_run(client, cid, run["id"], timeout=20)
    assert next(r for r in snap["runs"] if r["id"] == run["id"])["status"] == "completed"
    assert [c["status"] for c in snap["commands"]][-1] == "exited"


def test_a_trigger_turn_does_not_wait_on_another_conversations_card(
    make_client, wait_run, project_dir
):
    executor = ScriptedExecutor([Script(["ok\n"], writes={WORKFLOW: "x"}), Script(["ok\n"])])
    client, _model = make_client([cmd("python a.py"), cmd("python make.py", "k2"),
                                  text("B done"), text("A done")], executor=executor)
    client.headers["Origin"] = ORIGIN
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    _snap, question = open_card(client, cid)
    pid = client.get(f"/api/conversations/{cid}").json()["conversation"]["project_id"]
    other = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    made = trigger(client, pid, other, permissions={
        "write": False, "commands": [allow(client, other, "python make.py")], "agents": 0})
    unwatched = wait_run(client, other, run_now(client, made["id"]), timeout=20)
    assert unwatched["runs"][-1]["status"] == "completed"
    assert [c["status"] for c in unwatched["commands"]] == ["exited"]
    answer(client, question, "Take back")
    wait_run(client, cid, run_id, timeout=20)


# --- KOLONİ's Commit --------------------------------------------------------------------------


@needs_git
def test_what_a_git_checkout_changes_of_standing_files_is_a_card_like_any_write(
    make_client, wait_run, project_dir
):
    """The branch's content existed at the start, but refs and objects are the agent's to
    write too: a checkout is no proof of it."""
    (project_dir / ".github/workflows").mkdir(parents=True)
    (project_dir / ".github/workflows/ci.yml").write_bytes(b"main\n")
    repository(project_dir)
    in_repo(project_dir, "checkout", "-q", "-b", "other")
    (project_dir / ".github/workflows/ci.yml").write_bytes(b"other\n")
    in_repo(project_dir, "commit", "-q", "-am", "other")
    in_repo(project_dir, "checkout", "-q", "main")
    executor = ScriptedExecutor([Script(["Switched\n"], writes={
        ".github/workflows/ci.yml": "other\n"})])
    client, _model = make_client([cmd("git checkout other"), text("done")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    _snap, question = open_card(client, cid)
    assert "`.github/workflows/ci.yml`" in question["question"]
    ci = project_dir / ".github/workflows/ci.yml"
    assert ci.read_bytes().replace(b"\r\n", b"\n") == b"main\n"  # (as checked out)
    answer(client, question, "Keep")
    wait_run(client, cid, run_id, timeout=20)
    assert (project_dir / ".github/workflows/ci.yml").read_bytes() == b"other\n"


def test_past_the_turns_room_for_copies_an_unwatched_write_is_taken_back_all_the_same(
    make_client, wait_run, project_dir, monkeypatch
):
    monkeypatch.setattr(agent_merge, "TAKEN_BACK_BYTES", 0)
    executor = ScriptedExecutor([Script(["ok\n"], writes={".claude/settings.json": "{}"})])
    client, _model = make_client({"Lead": [
        step(call("run_command", {"command": "python make.py"}, "c")), text("done")]},
        executor=executor)
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    made = trigger(client, pid, cid, permissions={
        "write": False, "commands": [allow(client, cid, "python make.py")], "agents": 0})
    snap = wait_run(client, cid, run_now(client, made["id"]), timeout=20)
    assert not (project_dir / ".claude/settings.json").exists()
    (refused,) = [t for t in snap["tool_calls"] if t["name"] == "write_file"]
    assert refused["status"] == "denied"
    assert "no copy of the agent's version was kept" in refused["result"]


def test_git_config_a_command_writes_unasked_is_taken_back(
    native_app, wait_run, project_dir  # noqa: F811
):
    (project_dir / ".git").mkdir()
    (project_dir / ".git/config").write_bytes(b"[core]\n")
    client, provider, _ = native_app([
        {"run": "git config core.fsmonitor cmd", "unasked": True,
         "touches": {".git/config": "[core]\n\tfsmonitor = cmd\n"}}, {"say": "ok"}])
    cid, run_id = start(client, project_dir, provider)
    _snap, question = open_card(client, cid)
    assert "`.git/config`" in question["question"]
    assert (project_dir / ".git/config").read_bytes() == b"[core]\n"
    answer(client, question, "Take back")
    wait_run(client, cid, run_id)


PLANT = "open(r'{at}', 'a', encoding='utf-8', newline='').write({text!r})\n"
HOOK = "#!/bin/sh\necho ran > hook-ran.txt\n"


def kept_and_taken(make_client, project_dir, at, content):
    """A Coder's command writes `at` of the project's git folder by its full path, from its
    copy - the user keeps it on its card -, and its a.txt is taken in: the commit is offered."""
    (project_dir / "plant.py").write_text(
        PLANT.format(at=project_dir / ".git" / at, text=content), encoding="utf-8")
    (project_dir / "lines.txt").write_bytes(b"one\n")
    repository(project_dir)
    client, _pid, cid, _run_id = take_in_start(make_client, project_dir, [
        step(call("run_command", {"command": "python plant.py"}, "c")),
        step(call("write_file", {"path": "a.txt", "content": "A"}, "w")), text("A done")],
        project={"git_commit": True})
    _snap, question = open_card(client, cid)
    answer(client, question, "Keep")
    card(client, cid, "applied")  # (at Full auto: taken in unasked)
    snap = until(client, cid, lambda s: (s["merges"][0]["commit"] or {}).get("state") == "offered",
                 timeout=20)
    return client, snap["merges"][0]


@needs_git
def test_a_commit_after_a_hook_was_kept_asks_and_without_runs_no_hook(make_client, project_dir):
    client, merge = kept_and_taken(make_client, project_dir, "hooks/pre-commit", HOOK)
    assert (project_dir / ".git/hooks/pre-commit").read_text(encoding="utf-8") == HOOK
    asked = client.post(f"/api/merges/{merge['id']}/commit", json={"message": "take it"})
    assert asked.status_code == 200, asked.text
    assert asked.json()["commit"]["state"] == "offered"
    assert asked.json()["commit"]["asks"] == ["hooks"]
    done = client.post(f"/api/merges/{merge['id']}/commit",
                       json={"message": "take it", "hooks": "without"})
    assert done.status_code == 200, done.text
    assert done.json()["commit"]["state"] == "committed"
    assert not (project_dir / "hook-ran.txt").exists()  # an empty core.hooksPath


@needs_git
def test_a_commit_after_gits_config_was_kept_refuses_without(make_client, project_dir):
    client, merge = kept_and_taken(make_client, project_dir, "config", "\n[koloni]\n\tx = 1\n")
    asked = client.post(f"/api/merges/{merge['id']}/commit", json={"message": "take it"})
    assert asked.json()["commit"]["asks"] == ["config"]
    refused = client.post(f"/api/merges/{merge['id']}/commit",
                          json={"message": "take it", "hooks": "without"})
    assert refused.status_code == 409 and "`.git/config` was changed" in refused.text


@needs_git
def test_a_commit_asks_again_when_what_changed_is_other_and_with_them_runs_the_hook(
    make_client, project_dir
):
    client, merge = kept_and_taken(make_client, project_dir, "hooks/pre-commit", HOOK)
    # (a kept file is written with no mode - on Linux and macOS git runs no hook that is not
    # executable: the user makes it so)
    os.chmod(project_dir / ".git/hooks/pre-commit", 0o755)
    url = f"/api/merges/{merge['id']}/commit"
    assert client.post(url, json={"message": "take it"}).json()["commit"]["asks"] == ["hooks"]
    with open(project_dir / ".git/config", "a", encoding="utf-8") as config:
        config.write("\n[koloni]\n\tx = 1\n")  # (meanwhile)
    again = client.post(url, json={"message": "take it", "hooks": "with"}).json()["commit"]
    assert (again["state"], again["asks"]) == ("offered", ["hooks", "config"])
    done = client.post(url, json={"message": "take it", "hooks": "with"})
    assert done.status_code == 200 and done.json()["commit"]["state"] == "committed", done.text
    assert (project_dir / "hook-ran.txt").exists()  # (the control: with them, it runs)


@needs_git
def test_a_commit_where_nothing_of_git_changed_is_made_at_once(
    make_client, wait_run, project_dir
):
    (project_dir / "lines.txt").write_bytes(b"one\n")
    repository(project_dir)
    client, _pid, cid, _run_id = take_in_start(make_client, project_dir, [
        step(call("run_command", {"command": "python -c \"print(1)\""}, "c")),
        step(call("write_file", {"path": "a.txt", "content": "A"}, "w")), text("A done")],
        project={"git_commit": True})
    merge = card(client, cid, "applied")  # (at Full auto: taken in unasked)
    until(client, cid, lambda s: (s["merges"][0]["commit"] or {}).get("state") == "offered",
          timeout=20)
    done = client.post(f"/api/merges/{merge['id']}/commit", json={"message": "take it"})
    assert done.status_code == 200, done.text
    assert done.json()["commit"]["state"] == "committed" and not done.json()["commit"]["asks"]
