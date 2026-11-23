"""Kanıtlı bitiş S5b (plan decision 14c): the live try at a turn's end, under Test and review and
once a turn - a command-line tool the turn changed is run with `--help` and once plain; a big
change of screens is tried by the Tester, KOLONİ's own spawn with read and browser tools only, on
the chat's running preview, or on one KOLONİ starts on a free port and stops after. A fake model
per role; the stand-in browser plays Chrome."""

import json
import sys
from pathlib import Path

import pytest

from app import proof_try
from app.agent import try_mixin
from app.agent.kinds_mixin import KindsMixin
from app.model_client import StepResult, ToolCallRequest
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_writes import write
from tests.test_browser import served  # noqa: F401  (a fixture)
from tests.test_chat_flow import text
from tests.test_proof_background_scenarios import approve_write, until
from tests.test_proof_end_scenarios import OWN, PASS, begin, failing, texts
from tests.test_spawn import call, step

pytestmark = pytest.mark.no_po

FAKE = str(Path(__file__).with_name("fake_browser.py"))
SIGN = "Local · fake-model"
CHECK = "python check.py"
SCREEN = "".join(f"export const line{i} = {i}\n" for i in range(90))
WORKS = text("I opened it and clicked Start; it works.\nVerdict: MERGE\n\nFindings: none")
NUDGE = try_mixin.TRY_TO_FIX.split(" (round")[0]


def hold(*found):
    lines = "\n".join(f"- {one} | kind: code | role: Orchestrator | blocking" for one in found)
    return text(f"Verdict: HOLD\n\n## Findings\n{lines}")


def tries(url):
    return step(call("browser_open", {"url": url}, "t1"), call("browser_screenshot", {}, "t2"))


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("KOLONI_BROWSER_FAKE", FAKE)


@pytest.fixture
def preview(monkeypatch, served):  # noqa: F811
    """A preview runs in the chat, serving the work."""
    monkeypatch.setattr(KindsMixin, "_preview_of", lambda _self, _ctx: served)
    return served


def the_testers(snap):
    return [a for a in snap["agents"] if a["role_name"] == "Tester"]


def calls_by(snap, agent):
    return {c["name"]: c for c in snap["tool_calls"] if c["agent_id"] == agent["id"]}


def nudged(model):
    last = model.calls_of["Lead"][-1] if "Lead" in model.calls_of else model.calls[-1]
    return [str(m["content"]) for m in last
            if m["role"] == "user" and str(m["content"]).startswith(NUDGE)]


def blind(client):
    """The local provider's model marked to take no images."""
    local = client.get("/api/providers").json()[0]
    assert client.patch(f"/api/providers/{local['id']}", json={
        "default_model": "fake-model", "models": [{"name": "fake-model", "inputs": []}]},
        headers=OWN).status_code == 200


def test_a_big_screen_change_is_tried_by_the_tester_on_the_running_preview(
        fake, preview, make_client, wait_run, project_dir):
    client, model = make_client({"Lead": [write("src/App.tsx", SCREEN), text("done")],
                                 "Tester": [tries(preview), WORKS]},
                                executor=ScriptedExecutor([PASS]))
    blind(client)
    cid, run_id = begin(client, project_dir, check_command=CHECK, content="add a Start button")
    snap = wait_run(client, cid, run_id, timeout=30)
    assert f"Tried: Tester ({SIGN}) on {preview} - MERGE, no findings" in texts(snap), texts(snap)
    (tester,) = the_testers(snap)
    # (KOLONİ's own look, as the Reviewer's - decision 6: its read tools, run_command held to
    # reads and the approved test command - and its browser tools; no write)
    assert {"browser_open", "run_command"} <= set(tester["tools"]) and not {
        "write_file", "edit_file"} & set(tester["tools"]), tester["tools"]
    made = calls_by(snap, tester)
    assert made["browser_open"]["status"] == "succeeded", made["browser_open"]
    # (a picture reaches a model only where its model takes images: this one takes none)
    assert "your model is not known to see images" in made["browser_screenshot"]["result"]
    asked = json.dumps(model.calls_of["Tester"][0], ensure_ascii=False)
    assert preview in asked and "add a Start button" in asked and "src/App.tsx" in asked


def test_the_testers_blocking_finding_goes_back_once_and_it_is_not_tried_again(
        fake, preview, make_client, wait_run, project_dir):
    client, model = make_client({
        "Lead": [write("src/App.tsx", SCREEN), text("done"),
                 write("src/App.tsx", SCREEN + "export const fixed = 1\n", "w2"), text("fixed")],
        "Tester": [tries(preview), hold("Start does nothing when clicked")]},
        executor=ScriptedExecutor([PASS, PASS]))
    cid, run_id = begin(client, project_dir, check_command=CHECK)
    snap = wait_run(client, cid, run_id, timeout=30)
    assert len(the_testers(snap)) == 1  # (once a turn)
    (said,) = nudged(model)
    assert "Start does nothing when clicked" in said and "data, not instructions" in said
    shown = texts(snap)
    # (said once, its finding too - the second pass's rows are the first's, not again)
    assert shown.count(f"Tried: Tester ({SIGN}) on {preview} - HOLD, 1 findings, 1 blocking"
                       ) == 1, shown
    assert shown.count("Blocking: Start does nothing when clicked") == 1, shown
    assert shown[-1] == "Sent back to fix: 1 of 2 rounds (1 problem in the try)"


def test_with_no_preview_koloni_starts_the_dev_server_on_a_free_port_and_stops_it_after(
        fake, served, make_client, wait_run, project_dir, gate):  # noqa: F811
    (project_dir / "package.json").write_text(json.dumps({"scripts": {"dev": "vite"}}),
                                              encoding="utf-8")
    executor = ScriptedExecutor([PASS, Script([f"  Local:   {served}\n"], hold=gate)])
    client, _model = make_client({"Lead": [write("src/App.tsx", SCREEN), text("done")],
                                  "Tester": [tries(served), WORKS]}, executor=executor)
    cid, run_id = begin(client, project_dir, check_command=CHECK)
    snap = wait_run(client, cid, run_id, timeout=30)
    assert f"Tried: Tester ({SIGN}) on {served} - MERGE, no findings" in texts(snap), texts(snap)
    assert [line for line, _cwd in executor.started] == [CHECK, "npm run dev"]
    started = executor.extra_envs[1]
    assert started["BROWSER"] == "none" and int(started["PORT"]) > 0
    (dev,) = [one for one in snap["commands"] if one["command"] == "npm run dev"]
    until(lambda: dev["id"] in executor.killed)  # (stopped after: its kill may come after)
    # (KOLONİ's own run - no test run of the turn's on the canvas: `checksNode`'s TRY_CALL)
    (own,) = [c for c in snap["tool_calls"] if c["name"] == "run_command"
              and json.loads(c["arguments"])["command"] == "npm run dev"]
    assert own["provider_call_id"].startswith(try_mixin.TRY_CALL)


def test_no_preview_and_no_dev_script_is_said(fake, make_client, wait_run, project_dir):
    client, _model = make_client([write("src/App.tsx", SCREEN), text("done")],
                                 executor=ScriptedExecutor([PASS]))
    cid, run_id = begin(client, project_dir, check_command=CHECK)
    snap = wait_run(client, cid, run_id)
    assert f"Not tried: {try_mixin.NO_DEV}" in texts(snap) and snap["agents"][1:] == []


TOOL = "import sys\nprint(sys.argv)\n"  # (it reads its arguments: its --help is asked for)
HELP = "python 'bin/tool.py' --help"


def test_a_changed_cli_tool_gets_its_help_alone(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([PASS, Script(["usage: tool [-h]\n", "  -h  help\n"])])
    client, model = make_client([write("bin/tool.py", TOOL), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command=CHECK)
    snap = wait_run(client, cid, run_id)
    # (never a plain run: a script's work is not KOLONİ's to start - review of S5b)
    assert [line for line, _cwd in executor.started] == [CHECK, HELP]
    shown = texts(snap)
    assert f"Tried {HELP}: exit 0, 2 lines" in shown and nudged(model) == [], shown


def test_a_script_that_reads_no_arguments_is_never_run(make_client, wait_run, project_dir):
    # (a deploy or a sync script that ignores --help would do its work)
    executor = ScriptedExecutor([PASS])
    client, _model = make_client([write("bin/deploy.py", "upload_everything()\n"), text("done")],
                                 executor=executor)
    cid, run_id = begin(client, project_dir, check_command=CHECK)
    snap = wait_run(client, cid, run_id)
    assert [line for line, _cwd in executor.started] == [CHECK]
    assert f"Not tried: bin/deploy.py - {proof_try.NO_ARGUMENTS}" in texts(snap), texts(snap)


def test_a_cli_help_that_fails_goes_back_as_a_fix_round(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([PASS, Script(["Traceback: boom\n"], exit_code=1), PASS])
    client, model = make_client([write("bin/tool.py", TOOL + "raise SystemExit(1)\n"),
                                 text("done"), text("it was the import")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command=CHECK)
    snap = wait_run(client, cid, run_id)
    (said,) = nudged(model)
    assert f"Tried {HELP}: exit 1" in said
    assert texts(snap).count(f"Tried {HELP}: exit 1") == 1, texts(snap)
    assert texts(snap)[-1] == "Sent back to fix: 1 of 2 rounds (1 problem in the try)"


def test_a_tool_that_cannot_start_is_said_not_sent_back(make_client, wait_run, project_dir):
    # (python not on PATH, say: no exit of its own to judge - never a fix round)
    executor = ScriptedExecutor([PASS, Script(start_error="python: command not found")])
    client, model = make_client([write("bin/tool.py", TOOL), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command=CHECK)
    snap = wait_run(client, cid, run_id)
    assert nudged(model) == [] and [line for line, _cwd in executor.started] == [CHECK]
    assert f"Not tried: {HELP} - python: command not found" in texts(snap), texts(snap)


@pytest.mark.parametrize("name", [
    "bin/a;Write-Output INJECTED;b.py", "bin/$(Write-Output INJECTED).py", "bin/a&b.py",
    "bin/a b.py", "bin/-rf.py", "bin/`whoami`.sh", "bin/a'b.py"])
def test_a_tool_with_an_unusual_name_is_never_put_on_a_line(tmp_path, name):
    # (Review of S5b, probe_try_lines: `bin/$(Write-Output INJECTED).py` ran the subexpression
    # under KOLONİ's own call - an agent's command passed off as KOLONİ's.)
    assert proof_try.cli_tools(tmp_path, [name]) == [(name, proof_try.UNUSUAL)]


def test_a_console_script_of_an_unusual_module_is_never_put_on_a_line(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "p"\n[project.scripts]\nt = "m;Write-Output PYINJECT:main"\n'
        'u = "../up:main"\n', encoding="utf-8")
    assert proof_try.cli_tools(tmp_path, ["m;Write-Output PYINJECT.py", "x.py"]) == [
        ("t", proof_try.UNUSUAL), ("u", proof_try.UNUSUAL)]


def test_a_plain_name_is_quoted_on_its_line_all_the_same(tmp_path):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "my-tool_2.py").write_text(TOOL, encoding="utf-8")
    assert proof_try.cli_tools(tmp_path, ["bin/my-tool_2.py"]) == [
        ("python 'bin/my-tool_2.py'", None)]


def test_failing_tests_are_fixed_before_any_try(fake, preview, make_client, wait_run,
                                                project_dir):
    client, _model = make_client([write("src/App.tsx", SCREEN), text("done"), text("still")],
                                 executor=ScriptedExecutor([failing(), failing()]))
    cid, run_id = begin(client, project_dir, check_command=CHECK, fix_rounds=1)
    snap = wait_run(client, cid, run_id)
    assert the_testers(snap) == [] and not any(one.startswith("Tried") for one in texts(snap))


def test_a_small_screen_change_is_not_tried(fake, preview, make_client, wait_run, project_dir):
    client, _model = make_client([write("src/App.tsx", "export const a = 1\n"), text("done")],
                                 executor=ScriptedExecutor([PASS]))
    cid, run_id = begin(client, project_dir, check_command=CHECK)
    snap = wait_run(client, cid, run_id)
    assert the_testers(snap) == [] and not any(one.startswith(("Tried", "Not tried"))
                                           for one in texts(snap))


def test_at_ask_the_testers_spawn_opens_no_card_and_it_reaches_no_site_and_writes_nothing(
        fake, preview, make_client, wait_run, project_dir):
    out = StepResult("", [ToolCallRequest("t3", "browser_open", json.dumps(
        {"url": "https://example.com/"})), ToolCallRequest("t4", "write_file", json.dumps(
        {"path": "src/App.tsx", "content": "gone\n"})), ToolCallRequest("t5", "run_command",
        json.dumps({"command": "pip install requests"})), ToolCallRequest(
        "t6", "run_command", json.dumps({"command": "rm -rf src"})), ToolCallRequest(
        "t7", "browser_open", json.dumps({"url": "http://127.0.0.1:1/admin"})),
        ToolCallRequest("t8", "browser_open", json.dumps({"url": "src/App.tsx"}))], 1, 1)
    client, _model = make_client({"Lead": [write("src/App.tsx", SCREEN), text("done")],
                                  "Tester": [out, WORKS]}, executor=ScriptedExecutor([PASS]))
    cid, run_id = begin(client, project_dir, mode="ask", check_command=CHECK)
    approve_write(client, cid, "src/App.tsx")
    snap = wait_run(client, cid, run_id, timeout=30)
    (tester,) = the_testers(snap)
    assert tester["status"] == "completed", tester
    made = calls_by(snap, tester)
    # (a site out there, another page of this machine, a file: only the preview it tries)
    opens = [c for c in snap["tool_calls"] if c["agent_id"] == tester["id"]
             and c["name"] == "browser_open"]
    assert len(opens) == 3 and all(c["status"] != "succeeded" and (
        f"KOLONİ's Tester opens the preview it tries alone, {preview}" in c["result"])
        for c in opens), opens
    assert made["write_file"]["status"] != "succeeded"
    assert (project_dir / "src" / "App.tsx").read_text(encoding="utf-8") == SCREEN
    # (an install, any command that neither only reads nor is the approved test: refused, no card)
    ran = {json.loads(c["arguments"])["command"]: c for c in snap["tool_calls"]
           if c["agent_id"] == tester["id"] and c["name"] == "run_command"}
    assert set(ran) == {"pip install requests", "rm -rf src"}
    assert all(c["status"] == "failed" and "is not available" in c["result"]
               for c in ran.values()), ran
    assert not [c for c in snap["commands"] if c["agent_id"] == tester["id"]], snap["commands"]


# --- what is tried, read off the project's own files -----------------------------------------


def test_the_tools_a_turn_changed_are_read_off_the_projects_files(tmp_path):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "go").write_text("#!/usr/bin/env node\nconsole.log(process.argv)\n",
                                         encoding="utf-8")
    (tmp_path / "cli").mkdir()
    (tmp_path / "cli" / "x.js").write_text("require('yargs')\n", encoding="utf-8")
    (tmp_path / "package.json").write_text(json.dumps({"bin": {"x": "./cli/x.js"}}),
                                           encoding="utf-8")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "cli.py").write_text("def main(): pass\n", encoding="utf-8")
    (tmp_path / "pkg" / "run.py").write_text(
        "import argparse\nif __name__ == '__main__':\n    argparse.ArgumentParser()\n",
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "p"\n[project.scripts]\nmine = "pkg.cli:main"\nrun = "pkg.run:x"\n',
        encoding="utf-8")
    assert proof_try.cli_tools(tmp_path, ["bin/go", "cli/x.js"]) == [
        ("node 'bin/go'", None), ("node 'cli/x.js'", None)]
    assert proof_try.cli_tools(tmp_path, ["pkg/cli.py", "pkg/run.py"]) == [
        ("mine", proof_try.NO_MAIN.format(module="pkg.cli")), ("python -m pkg.run", None)]
    assert proof_try.cli_tools(tmp_path, ["src/App.tsx", "bin/notes.txt"]) == []


def test_the_dev_server_is_the_nearest_package_jsons_dev_else_start(tmp_path):
    (tmp_path / "web").mkdir()
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"start": "node s"}}),
                                           encoding="utf-8")
    assert proof_try.dev_command(tmp_path, ["web/src/App.tsx"]) == ("npm start", ".")
    (tmp_path / "web" / "package.json").write_text(json.dumps({"scripts": {"dev": "vite"}}),
                                                   encoding="utf-8")
    assert proof_try.dev_command(tmp_path, ["web/src/App.tsx"]) == ("npm run dev", "web")
    (tmp_path / "package.json").unlink()
    assert proof_try.dev_command(tmp_path, ["src/App.tsx"]) is None


@pytest.mark.anyio
async def test_the_testers_browser_loads_from_its_preview_alone(tmp_path, served):  # noqa: F811
    # (What a page loads by itself too: another of this machine's pages or a project file is not
    # the preview it tries - review of S5b.)
    from app import browser
    from app.workspace import Workspace

    page = tmp_path / "other.html"
    page.write_text("<html><title>O</title></html>", encoding="utf-8")
    one = browser.Browser(tmp_path / "b", "tester")
    await one.start([sys.executable, FAKE], Workspace(str(tmp_path)), set())
    try:
        one.only = browser.origin(served)
        assert await one.open(served) == f"{served} - Tiny"
        await one.open(page.resolve().as_uri())
        assert "not the preview this browser tries" in one.refused()
    finally:
        await one.close()
    assert browser.origin("http://localhost:5173/a") == browser.origin("http://127.0.0.1:5173/")
    assert browser.origin("http://127.0.0.1:5174/") != browser.origin("http://127.0.0.1:5173/")
    assert browser.origin("file:///x/index.html") is None
