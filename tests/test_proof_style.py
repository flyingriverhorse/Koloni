"""Check by kind of work, 0.1.7's Code style and types: the project's own ruff, eslint, tsc and mypy -
where it sets one up and has it installed - on the files a turn changed, run as its test command is
(a card at Ask and Auto-edit where no rule covers it, one a tool a turn; not while nobody can be
asked). A problem on a line the turn wrote fails, the others are said. The tools are scripted
(`ScriptedExecutor`); one test runs this machine's own ruff through the shell as KOLONİ would."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app import proof, proof_style
from app.executors import host
from tests.conftest import scaled
from tests.fakes import Script, ScriptedExecutor
from tests.keyed import OWN
from tests.test_agent_writes import wait_status, write
from tests.test_chat_flow import text
from tests.test_proof_end_scenarios import PASS, begin, texts

RUFF = ".venv/Scripts/ruff.exe" if sys.platform == "win32" else ".venv/bin/ruff"
FIXED_LINE = f"{RUFF} check --no-cache --output-format=concise"
LINE = f"{FIXED_LINE} ./app.py"
NEW = "import os\nx = 1\n"
FIXED = "x = 1\n"
# (Its words around the lines it gives - a warning, a summary - are read past.)
RUFF_SAYS = Script(
    [
        "warning: `select` is deprecated\n"
        "app.py:1:8: F401 [*] `os` imported but unused\n"
        "hello.py:1:1: E501 Line too long (120 > 100)\n"
        "Found 2 errors.\n"
    ],
    exit_code=1,
)
RUFF_CLEAN = Script(["All checks passed!\n"])


def set_up(root: Path, ruff: bool = True) -> None:
    """A project that sets ruff up (pyproject's [tool.ruff]) and has it in its .venv."""
    (root / "pyproject.toml").write_text('[project]\nname = "x"\n\n[tool.ruff]\n', encoding="utf-8")
    if ruff:
        (root / RUFF).parent.mkdir(parents=True)
        (root / RUFF).write_text("", encoding="utf-8")


def nudges(model) -> list[str]:
    return [
        str(m["content"])
        for m in model.calls[-1]
        if m["role"] == "user" and str(m["content"]).startswith("Not the end yet: KOLONİ's")
    ]


# --- which tools, their lines, what they say ----------------------------------------------------


def test_each_tool_where_the_project_sets_it_up_and_has_it(tmp_path, monkeypatch):
    monkeypatch.setattr(proof_style, "_on_path", lambda _tool: False)
    (tmp_path / "pyproject.toml").write_text("[tool.ruff.lint]\n[tool.mypy]\n", encoding="utf-8")
    set_up_bin = tmp_path / RUFF
    set_up_bin.parent.mkdir(parents=True)
    set_up_bin.write_text("")
    node = "node_modules/.bin/{}.cmd" if sys.platform == "win32" else "node_modules/.bin/{}"
    (tmp_path / "web" / "node_modules" / ".bin").mkdir(parents=True)
    (tmp_path / "web" / node.format("eslint")).write_text("")
    (tmp_path / "web" / "eslint.config.js").write_text("")
    (tmp_path / "web" / "tsconfig.json").write_text("{}")
    runs, notes = proof_style.planned(
        tmp_path, ["a.py", "pkg/b.py", "web/src/x.ts", "web/y.js", "odd name.py", "README.md"]
    )
    assert runs == [
        proof_style.Run(
            "ruff",
            f"{RUFF} check --no-cache --output-format=concise ./a.py ./pkg/b.py",
            ".",
            ("a.py", "pkg/b.py"),
        ),
        proof_style.Run(
            "eslint",
            f"{node.format('eslint')} --format stylish --no-color ./src/x.ts ./y.js",
            "web",
            ("web/src/x.ts", "web/y.js"),
        ),
    ]
    assert notes == [
        "Code style not checked: odd name.py - a name KOLONİ does not put in a command line",
        "mypy: not checked - set up in this project, not installed here",
        "tsc: not checked - set up in this project, not installed here",
    ]
    # (none set up for a file: nothing at all is said of it)
    assert proof_style.configured(tmp_path, ["web/y.js"])
    assert not proof_style.configured(tmp_path / "web" / "src", ["x.py"])


def test_at_most_fifty_files_a_run(tmp_path):
    set_up(tmp_path)
    runs, notes = proof_style.planned(tmp_path, [f"m{n:02}.py" for n in range(53)])
    assert len(runs[0].files) == 50 and notes == [
        "ruff: 3 more files not checked - at most 50 a run"
    ]


@pytest.mark.parametrize(
    ("tool", "cwd", "output", "found"),
    [
        (
            "mypy",
            ".",
            'a.py:3: error: Name "x" is not defined  [name-defined]\na.py:3: note: see here\n',
            [("a.py", 3, 'mypy name-defined - Name "x" is not defined', True)],
        ),
        (
            "tsc",
            "web",
            "src/x.ts(4,7): error TS2322: Type 'a' is not assignable to type 'b'.\n",
            [("web/src/x.ts", 4, "tsc TS2322 - Type 'a' is not assignable to type 'b'.", True)],
        ),
        (
            "eslint",
            "web",
            "{root}/web/y.js\n  2:5  error  'q' is defined but never used  no-unused-vars\n"
            "  3:1  warning  Unexpected console statement  no-console\n\n✖ 2 problems\n",
            [
                ("web/y.js", 2, "eslint no-unused-vars - 'q' is defined but never used", True),
                ("web/y.js", 3, "eslint no-console - Unexpected console statement", False),
            ],
        ),
        ("ruff", ".", "error: Failed to parse pyproject.toml\n", []),
    ],
)
def test_what_each_tool_says_is_read_line_by_line(tmp_path, tool, cwd, output, found):
    said = proof_style.problems(tool, output.replace("{root}", str(tmp_path)), tmp_path, cwd)
    assert [tuple(one) for one in said] == found


def test_a_problem_on_a_line_the_turn_wrote_fails_the_others_are_said(tmp_path):
    run = proof_style.Run("ruff", LINE, ".", ("app.py",))
    output = RUFF_SAYS.chunks[0]
    rows = proof_style.rows_of(run, 1, output, tmp_path, {"app.py": [1, 2]})
    assert [(one["state"], one["text"]) for one in rows] == [
        ("failed", "app.py:1: ruff F401 - `os` imported but unused"),
        ("note", "ruff: 1 problems on lines this turn did not change"),
    ]
    # (the same problem on a line the turn did not write: said only)
    rows = proof_style.rows_of(run, 1, output, tmp_path, {"app.py": [2]})
    assert [one["state"] for one in rows] == ["note"]
    # (an exit with nothing read of its output, and one that never ended: said, never failed)
    assert [(one["state"], one["text"]) for one in proof_style.rows_of(run, 2, "boom", tmp_path, {})] == [
        ("note", "ruff: not checked - its output was not read (exit 2)")
    ]  # fmt: skip
    assert proof_style.rows_of(run, None, "", tmp_path, {})[0]["state"] == "note"
    rows = proof_style.rows_of(run, 0, "All checks passed!\n", tmp_path, {"app.py": [1]})
    assert [(one["state"], one["text"]) for one in rows] == [
        ("passed", "ruff: no problems on the lines this turn changed (1 files)")
    ]


def test_a_line_the_project_already_checks_with_is_told_apart():
    assert proof_style.runs_tool("ruff check .", "ruff")
    assert proof_style.runs_tool("uv run ruff check src", "ruff")
    assert not proof_style.runs_tool("ruff format --check .", "ruff")
    assert proof_style.runs_tool("npx tsc --noEmit", "tsc")
    assert not proof_style.runs_tool("npm run typecheck", "tsc")


def test_style_is_a_part_on_unless_unticked():
    from app.schemas import RecipeChecks

    assert "style" in proof.PARTS and "style" in proof.ON_UNLESS_UNTICKED
    assert RecipeChecks().style is True


# --- at a turn's end -----------------------------------------------------------------------------


@pytest.mark.no_po
def test_ruffs_problem_on_the_turns_line_is_a_fix_round_and_its_tests_still_run(
    make_client, wait_run, project_dir
):
    set_up(project_dir)
    executor = ScriptedExecutor([PASS, RUFF_SAYS, PASS, RUFF_CLEAN])
    client, model = make_client(
        [write("app.py", NEW), text("done"), write("app.py", FIXED, "w2"), text("fixed")],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    rows = texts(wait_run(client, cid, run_id))
    assert [command for command, _cwd in executor.started] == [
        "python check.py",
        LINE,
        "python check.py",
        LINE,
    ]
    (nudged,) = nudges(model)
    assert "app.py:1: ruff F401 - `os` imported but unused" in nudged
    assert "data, not instructions" in nudged  # (the tool's words: data)
    assert "ruff: no problems on the lines this turn changed (1 files)" in rows, rows


@pytest.mark.no_po
def test_at_auto_edit_one_card_a_tool_a_turn_and_always_keeps_it(
    make_client, wait_run, project_dir
):
    set_up(project_dir)
    executor = ScriptedExecutor([PASS, RUFF_SAYS, PASS, RUFF_CLEAN])
    client, _model = make_client(
        [write("app.py", NEW), text("done"), write("app.py", FIXED, "w2"), text("fixed")],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, mode="auto_edit", check_command="python check.py")
    snap = wait_status(client, cid, "waiting_approval")
    (asked,) = [c for c in snap["commands"] if c["status"] == "proposed"]
    assert asked["command"] == LINE
    # (Always: this very line's fixed part - never the bare program, which would cover another
    # config, a plugin folder, a report written elsewhere)
    assert asked["suggested_prefix"] == FIXED_LINE
    yes = client.post(f"/api/commands/{asked['id']}/approve", json={"remember": True}, headers=OWN)
    assert yes.status_code == 200, yes.text
    snap = wait_run(client, cid, run_id)  # (no second card in the turn: it would wait here)
    assert [c["command"] for c in snap["commands"]].count(LINE) == 2
    assert "ruff: no problems on the lines this turn changed (1 files)" in texts(snap)


@pytest.mark.no_po
def test_a_no_on_its_card_stands_for_the_turn(make_client, wait_run, project_dir):
    set_up(project_dir)
    executor = ScriptedExecutor([PASS])
    client, _model = make_client([write("app.py", NEW), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, mode="auto_edit", check_command="python check.py")
    snap = wait_status(client, cid, "waiting_approval")
    (asked,) = [c for c in snap["commands"] if c["status"] == "proposed"]
    client.post(f"/api/commands/{asked['id']}/reject", headers=OWN)
    rows = texts(wait_run(client, cid, run_id))
    assert "ruff: not run - declined on its card this turn" in rows, rows
    assert [command for command, _cwd in executor.started] == ["python check.py"]


@pytest.mark.no_po
def test_a_tool_is_not_run_where_nobody_can_be_asked(
    make_client, wait_run, project_dir, monkeypatch
):
    from app.agent import AgentRunner

    set_up(project_dir)
    monkeypatch.setattr(AgentRunner, "_away_now", lambda _self, _ctx: True)
    executor = ScriptedExecutor([PASS])
    client, _model = make_client([write("app.py", NEW), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    rows = texts(wait_run(client, cid, run_id))
    assert any(one.startswith("ruff: not checked - it needs your leave once") for one in rows), rows
    assert LINE not in [command for command, _cwd in executor.started]


@pytest.mark.no_po
def test_a_tool_the_projects_own_check_runs_is_not_run_again(make_client, wait_run, project_dir):
    set_up(project_dir)
    executor = ScriptedExecutor([PASS])
    client, _model = make_client([write("app.py", NEW), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command="ruff check .")
    rows = texts(wait_run(client, cid, run_id))
    assert proof_style.BY_THEIRS.format(tool="ruff") in rows, rows
    assert [command for command, _cwd in executor.started] == ["ruff check ."]


@pytest.mark.no_po
@pytest.mark.parametrize("configured", [False, True])
def test_none_set_up_says_nothing_and_set_up_not_installed_says_so(
    make_client, wait_run, project_dir, monkeypatch, configured
):
    if configured:
        set_up(project_dir, ruff=False)
        monkeypatch.setattr(proof_style, "_on_path", lambda _tool: False)  # (none on PATH)
    executor = ScriptedExecutor([PASS])
    client, _model = make_client([write("app.py", NEW), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    rows = texts(wait_run(client, cid, run_id))
    said = [one for one in rows if "ruff" in one or "style" in one]
    assert said == (
        ["ruff: not checked - set up in this project, not installed here"] if configured else []
    ), rows


@pytest.mark.no_po
def test_style_switched_off_says_so_and_runs_nothing(make_client, wait_run, project_dir):
    set_up(project_dir)
    executor = ScriptedExecutor([PASS])
    client, _model = make_client([write("app.py", NEW), text("done")], executor=executor)
    cid, run_id = begin(
        client, project_dir, check_command="python check.py", check_kinds={"style": False}
    )
    rows = texts(wait_run(client, cid, run_id))
    assert "Not checked: code style and types switched off for this project" in rows, rows
    assert [command for command, _cwd in executor.started] == ["python check.py"]


@pytest.mark.no_po
def test_past_its_time_a_tool_is_said_not_run(make_client, wait_run, project_dir, monkeypatch):
    set_up(project_dir)
    monkeypatch.setattr(proof_style, "STYLE_SECONDS", 0)
    executor = ScriptedExecutor([PASS])
    client, _model = make_client([write("app.py", NEW), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    rows = texts(wait_run(client, cid, run_id))
    assert "ruff: not run - past the 0 s of Code style and types" in rows, rows


# --- the real ruff, through the shell KOLONİ runs commands in ----------------------------------

REAL = Path(sys.executable).with_name("ruff.exe" if sys.platform == "win32" else "ruff")


@pytest.mark.skipif(not REAL.is_file(), reason="no ruff beside this Python")
@pytest.mark.parametrize("forced", [False, True], ids=["no-colour", "FORCE_COLOR"])
def test_the_real_ruffs_line_runs_in_koloni_s_shell_and_is_read(tmp_path, forced):
    import os
    import shutil

    set_up(tmp_path, ruff=False)
    (tmp_path / RUFF).parent.mkdir(parents=True)
    try:  # (the program in the project's .venv, as one holds it - a link where it may be)
        os.link(REAL, tmp_path / RUFF)
    except OSError:
        shutil.copyfile(REAL, tmp_path / RUFF)
        (tmp_path / RUFF).chmod(0o755)
    (tmp_path / "app.py").write_text(NEW, encoding="utf-8")
    (run,), _notes = proof_style.planned(tmp_path, ["app.py"])
    # (KOLONİ gives NO_COLOR; a FORCE_COLOR of the user's wins over it in ruff - read past)
    env = {**os.environ, "NO_COLOR": "1", **({"FORCE_COLOR": "1"} if forced else {})}
    done = subprocess.run(
        host.shell_argv(run.command),
        cwd=tmp_path,
        capture_output=True,
        timeout=120,
        check=False,
        env=env,
    )
    output = (done.stdout + done.stderr).decode("utf-8", "replace")
    rows = proof_style.rows_of(run, done.returncode, output, tmp_path, {"app.py": [1, 2]})
    assert ("failed", "app.py:1: ruff F401 - `os` imported but unused") in [
        (one["state"], one["text"]) for one in rows
    ], output
    assert not (tmp_path / ".ruff_cache").exists()  # (--no-cache: nothing of it left behind)


# --- in a recipe's copy: run there, what it writes put back ------------------------------------


def test_in_the_recipes_copy_a_tools_writes_are_put_back_never_taken_in(make_client, project_dir):
    import os

    from tests.test_chat_teams_scenarios import teams_of
    from tests.test_claim_scenarios import write as written
    from tests.test_parallel import until
    from tests.test_recipe_run_scenarios import READY, answer, asked, made
    from tests.test_recipes_scenarios import graph
    from tests.test_recipes_scenarios import step as part
    from tests.test_spawn import begin as begun
    from tests.test_spawn import spawn, step

    set_up(project_dir)
    # (a tool that writes a file of the project's - a cache, a report: never the work)
    cache = Script(RUFF_CLEAN.chunks, writes={"hello.py": "written by a tool\n"})
    executor = ScriptedExecutor([PASS, cache, PASS, RUFF_CLEAN, PASS, RUFF_CLEAN])
    client, _model = make_client(
        {
            "Lead": [spawn("Coder", "write it", "c1"), *[text(f"done {i}") for i in range(3)]],
            "Coder": [step(written("app.py", FIXED)), text("written")],
        },
        executor=executor,
    )
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    patched = client.patch(
        f"/api/projects/{pid}", json={"check_command": "python check.py"}, headers=OWN
    )
    assert patched.status_code == 200, patched.text
    recipe = made(
        client,
        "Write it",
        {
            **graph([part("w", "Write it", {"role": "Coder"})], [("start", "w"), ("w", "end")]),
            "checks": {"tests": True, "review": False},
        },
    )
    web = teams_of(client)["Web app"]
    cid, _run_id = begun(
        client,
        project_dir,
        mode="full_auto",
        spawn_approval="never",
        teams_mode="manual",
        teams=[{"team_id": web["id"], "recipe_id": recipe["id"]}],
    )
    until(client, cid, lambda s: s["runs"][-1]["status"] not in ("running", "queued"), timeout=30)
    assert [command for command, _cwd in executor.started][:2] == ["python check.py", LINE]
    here = os.path.realpath(project_dir)
    assert os.path.realpath(executor.started[1][1]) != here, executor.started  # (in the copy)
    snap = client.get(f"/api/conversations/{cid}").json()
    if asked(snap) and READY in asked(snap)["question"]:
        answer(client, asked(snap), "Take in")
    assert until(client, cid, lambda _s: (project_dir / "app.py").exists(), timeout=20)
    assert (project_dir / "hello.py").read_bytes() == b"print('hi')\n", executor.started


# --- the security review's round (HOLD): what never runs, what is read, what is offered ---------

NODE = "node_modules/.bin/eslint.cmd" if sys.platform == "win32" else "node_modules/.bin/eslint"
ESLINT_CLEAN = Script(["\n"])


def eslint_in(root: Path, folder: str) -> None:
    """`folder` with eslint set up and installed - the project's own, from before the turn."""
    (root / folder / "node_modules" / ".bin").mkdir(parents=True)
    (root / folder / NODE).write_text("@echo the project's\n", encoding="utf-8")
    (root / folder / "eslint.config.js").write_text("export default []\n", encoding="utf-8")


def an_eslint(folder: str) -> proof_style.Run:
    return proof_style.Run("eslint", f"{NODE} --format stylish --no-color ./x.js", folder, ())


@pytest.mark.parametrize(
    "written",
    [
        "admin/NODE_MODULES/.bin/eslint.cmd",  # (another case: one folder on Windows and macOS)
        "admin/Node_Modules/.bin/eslint",
        "admin/node_modules/eslint/bin/eslint.js",  # (what the .cmd shim runs)
        "admin/node_modules/.bin/eslint.cmd",
    ],
)
def test_a_program_the_turn_wrote_in_its_install_folder_is_never_run(tmp_path, written):
    eslint_in(tmp_path, "admin")
    said = proof_style.planted(tmp_path, tmp_path, an_eslint("admin"), ["admin/x.js", written])
    assert said == "this turn wrote in admin/node_modules: no install of the project's"
    # (the project's own, the turn writing elsewhere: it may run)
    assert proof_style.planted(tmp_path, tmp_path, an_eslint("admin"), ["admin/x.js"]) is None
    ruff = proof_style.Run("ruff", "ruff check ./a.py", ".", ("a.py",))  # (on PATH: none)
    assert proof_style.planted(tmp_path, tmp_path, ruff, [written]) is None


def test_a_program_through_a_link_is_judged_where_it_really_is(tmp_path):
    from tests.test_project_map import _link

    project, copy, outside = tmp_path / "p", tmp_path / "copy", tmp_path / "outside"
    eslint_in(project, "web")
    # (a copy's node_modules is a link into the project's: the project's own program)
    (copy / "web").mkdir(parents=True)
    _link(project / "web" / "node_modules", copy / "web" / "node_modules")
    assert proof_style.planted(copy, project, an_eslint("web"), ["web/x.js"]) is None
    # (one the turn made a link to a folder it wrote in, or out of the project: not run)
    (project / "admin" / "vendor" / ".bin").mkdir(parents=True)
    (project / "admin" / "vendor" / NODE.removeprefix("node_modules/")).write_text("x")
    _link(project / "admin" / "vendor", project / "admin" / "node_modules")
    wrote = ["admin/vendor/.bin/eslint.cmd", "admin/x.js"]
    assert "this turn wrote in" in proof_style.planted(project, project, an_eslint("admin"), wrote)
    eslint_in(outside, "x")
    (project / "far").mkdir()
    _link(outside / "x" / "node_modules", project / "far" / "node_modules")
    assert proof_style.planted(project, project, an_eslint("far"), ["far/x.js"]) == (
        f"its program is not in the project ({NODE})"
    )


@pytest.mark.no_po
@pytest.mark.skipif(sys.platform != "win32", reason="a file system that ignores case")
def test_one_yes_never_runs_an_eslint_the_turn_planted_under_another_case(
    make_client, wait_run, project_dir
):
    """The review's probe: web's card said yes, and the eslint the turn wrote in admin's
    NODE_MODULES ran unasked."""
    eslint_in(project_dir, "web")
    executor = ScriptedExecutor([PASS, ESLINT_CLEAN, ESLINT_CLEAN])
    client, _model = make_client(
        [
            write("web/y.js", "let y = 1\n", "w1"),
            write("admin/eslint.config.js", "export default []\n", "w2"),
            write("admin/NODE_MODULES/.bin/eslint.cmd", "@echo PLANTED %*\n", "w3"),
            write("admin/x.js", "let x = 1\n", "w4"),
            text("done"),
        ],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, mode="auto_edit", check_command="python check.py")
    snap = wait_status(client, cid, "waiting_approval")
    (asked,) = [c for c in snap["commands"] if c["status"] == "proposed"]
    assert asked["cwd"] == "web", asked
    assert (
        client.post(f"/api/commands/{asked['id']}/approve", json={}, headers=OWN).status_code == 200
    )
    rows = texts(wait_run(client, cid, run_id))
    assert not [cwd for _c, cwd in executor.started if Path(cwd).name == "admin"], executor.started
    said = "eslint: not run - this turn wrote in admin/node_modules: no install of the project's"
    assert said in rows, rows


@pytest.mark.no_po
def test_a_yes_is_that_line_in_that_folder_another_folders_eslint_asks_its_own(
    make_client, wait_run, project_dir
):
    from tests.test_parallel import until

    eslint_in(project_dir, "web")
    eslint_in(project_dir, "admin")
    executor = ScriptedExecutor([PASS, ESLINT_CLEAN, ESLINT_CLEAN])
    client, _model = make_client(
        [
            write("web/y.js", "let y = 1\n", "w1"),
            write("admin/x.js", "let x = 1\n", "w2"),
            text("done"),
        ],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, mode="auto_edit", check_command="python check.py")
    for folder in ("web", "admin"):
        snap = until(
            client,
            cid,
            lambda s, f=folder: any(
                c["status"] == "proposed" and c["cwd"] == f for c in s["commands"]
            ),
            timeout=10,
        )
        (asked,) = [c for c in snap["commands"] if c["status"] == "proposed"]
        assert (
            client.post(f"/api/commands/{asked['id']}/approve", json={}, headers=OWN).status_code
            == 200
        )
    rows = texts(wait_run(client, cid, run_id))
    assert sorted(Path(cwd).name for _c, cwd in executor.started[1:]) == ["admin", "web"], rows


@pytest.mark.no_po
def test_a_run_with_no_card_is_no_yes_when_the_level_drops_it_asks(
    make_client, wait_run, project_dir
):
    """Full auto ran ruff with no card; the user turns the level down before the fix round's
    pass: the same line asks - a yes is a card's only."""
    from tests.conftest import Gate

    set_up(project_dir)
    held = Gate()
    executor = ScriptedExecutor([PASS, RUFF_SAYS, PASS, RUFF_CLEAN])
    client, _model = make_client(
        [
            write("app.py", NEW),
            text("done"),
            held.step(write("app.py", FIXED, "w2")),
            text("fixed"),
        ],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    held.wait_partial()
    level = client.patch(
        f"/api/conversations/{cid}", json={"permission_mode": "auto_edit"}, headers=OWN
    )
    assert level.status_code == 200, level.text
    held.release()
    snap = wait_status(client, cid, "waiting_approval")
    (asked,) = [c for c in snap["commands"] if c["status"] == "proposed"]
    assert asked["command"] == LINE
    assert (
        client.post(f"/api/commands/{asked['id']}/approve", json={}, headers=OWN).status_code == 200
    )
    wait_run(client, cid, run_id)


@pytest.mark.no_po
@pytest.mark.parametrize("leave", [False, True])
def test_in_a_turn_nobody_watches_a_tool_runs_only_on_its_triggers_leave_for_the_line(
    make_client, wait_run, project_dir, leave
):
    from tests.test_triggers import allow, run_now, setup, trigger
    from tests.test_triggers import leave as given

    set_up(project_dir)
    executor = ScriptedExecutor([PASS, RUFF_CLEAN])
    client, _model, pid, cid = setup(
        make_client, project_dir, [write("app.py", FIXED), text("done")], executor=executor
    )
    patched = client.patch(
        f"/api/projects/{pid}", json={"check_command": "python check.py", "lead_work": "itself"}
    )
    assert patched.status_code == 200, patched.text
    rules = [allow(client, cid, "python check.py"), *([allow(client, cid, LINE)] if leave else [])]
    made = trigger(client, pid, cid, permissions=given(write=True, commands=rules))
    rows = texts(wait_run(client, cid, run_now(client, made["id"])))
    ran = [command for command, _cwd in executor.started]
    if leave:  # (its leave for this very line: run, unasked)
        assert ran == ["python check.py", LINE]
        assert "ruff: no problems on the lines this turn changed (1 files)" in rows, rows
    else:
        assert ran == ["python check.py"]
        assert any(one.startswith("ruff: not checked - it needs your leave once") for one in rows)


@pytest.mark.no_po
def test_a_part_test_that_does_not_run_this_turn_does_not_stand_for_the_tool(
    make_client, wait_run, project_dir
):
    """The CI lines the user approved run instead of the parts' commands (`_runs_found`): the
    whole project's `ruff check .` on the map does not run this pass - so ruff is not said to be
    run by the project's own check, and runs. (0.1.7: no check command that runs alone - the
    by-part chain's skip is approved CI.)"""
    from app import ci_commands
    from app.db.models import Project
    from tests.test_ci_commands import write as workflow

    set_up(project_dir)
    workflow(project_dir, "jobs:\n  ci:\n    steps:\n      - run: python -m pytest -q\n")
    executor = ScriptedExecutor([PASS, RUFF_CLEAN])
    client, _model = make_client([write("app.py", FIXED), text("done")], executor=executor)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    with client.app.state.session_factory() as session:  # (approved once, by Run these)
        approved = {
            "hash": ci_commands.fingerprint(project_dir),
            "commands": [{"command": "python -m pytest -q", "cwd": "."}],
            "said": [],
        }
        session.get_one(Project, pid).ci_commands = {"approved": approved}
        session.commit()
    cid, run_id = begin(client, project_dir, parts={"./": "ruff check ."})
    rows = texts(wait_run(client, cid, run_id))
    assert [command for command, _cwd in executor.started] == ["python -m pytest -q", LINE], rows
    assert proof_style.BY_THEIRS.format(tool="ruff") not in rows


@pytest.mark.no_po
def test_a_tool_waits_for_the_machines_test_slot_and_says_so_past_its_time(
    make_client, wait_run, project_dir, monkeypatch
):
    from app.agent import AgentRunner

    async def no_tests(_self, _ctx, _held):  # (the turn's own tests would wait for it too)
        return None

    monkeypatch.setattr(AgentRunner, "_proof_tests", no_tests)
    set_up(project_dir)
    monkeypatch.setattr(proof_style, "STYLE_SECONDS", 2)
    executor = ScriptedExecutor([])
    client, _model = make_client([write("app.py", FIXED), text("done")], executor=executor)
    slot = client.app.state.runner._test_slot
    slot.taken = 99  # (other turns' whole suites, going on - as many as Settings allow, and more)
    try:
        cid, run_id = begin(client, project_dir)
        rows = texts(wait_run(client, cid, run_id))
    finally:
        slot.taken = 0
    assert executor.started == [], executor.started
    assert "ruff: not run - another of KOLONİ's test runs held the machine past the wait" in rows


@pytest.mark.parametrize(
    "line",
    [
        "a.py:1: error: a" + " " * 16000 + "b",
        "a.py:1: error: a" + "\t" * 16000 + "b",
        "a" + ":1" * 8000,
        "a.ts(1,1): error TS1: " + " " * 16000 + "x",
        " " * 16000 + "1:1",
    ],
    ids=["mypy", "mypy-tabs", "colon", "tsc", "eslint"],
)
def test_a_long_line_is_read_in_time_linear_in_its_length(line):
    """B2: `_MYPY` was quadratic over a run of spaces, and held the GIL - every chat froze. Each
    parser over 2 and 16 KB lines, in a child process with a time limit: 8x the line, never
    near 64x the time."""
    tool = "tsc" if "TS1" in line else "eslint" if line.startswith(" ") else "mypy"
    probe = (
        "import sys, time\nfrom pathlib import Path\nfrom app import proof_style\n"
        "line, tool = sys.argv[1], sys.argv[2]\n"
        "def took(text):\n    t = time.perf_counter()\n"
        "    for _ in range(20):\n        proof_style.problems(tool, text, Path('.'), '.')\n"
        "    return time.perf_counter() - t\n"
        "short = line[:2048]\nprint(took(short), took(line))\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe, line, tool],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=Path(proof_style.__file__).parents[1],
        check=False,
    )
    short, long = map(float, done.stdout.split())
    # (the old mypy line: 0.26 s a 16 KB line, 5 s the 20 - far past either bound)
    room = 80 if os.environ.get("CI") else 20
    assert long < max(short, 0.01) * room, (short, long, done.stderr)


def test_colour_codes_are_read_past():
    # (FORCE_COLOR: ruff's colours, and the link it puts around a rule's code - OSC 8)
    link = "\x1b]8;;https://docs.astral.sh/ruff/rules/unused-import\x1b\\"
    said = (
        f"\x1b[1mapp.py\x1b[0m:1:8: \x1b[1;31m{link}F401\x1b]8;;\x1b\\\x1b[0m"
        " [*] `os` imported but unused\n"
    )
    (one,) = proof_style.problems("ruff", said, Path("."), ".")
    assert (one.path, one.line, one.said) == ("app.py", 1, "ruff F401 - `os` imported but unused")


def test_the_turns_lines_are_counted_as_the_tools_count_them():
    # (a form feed is no line of its own to ruff: the turn added line 2, never 3)
    assert proof.changed_lines("\x0c\nimport os\n", "\x0c\ny = 1\nimport os\n") == [2]
    assert proof.changed_lines("a\r\nb\r\n", "a\r\nB\r\n") == [2]
    assert proof.changed_lines("a\rb", "a\rb\rc") == [3]


def test_warnings_on_the_turns_lines_are_not_counted_as_elsewhere(tmp_path):
    run = proof_style.Run("eslint", "x", "web", ("web/y.js",))
    output = (
        f"{tmp_path}/web/y.js\n  2:5  warning  Unexpected console statement  no-console\n"
        "  9:1  error  'q' is defined but never used  no-unused-vars\n"
    )
    rows = proof_style.rows_of(run, 1, output, tmp_path, {"web/y.js": [2]})
    assert [(one["state"], one["text"]) for one in rows] == [
        ("note", "eslint: 1 warnings on the lines this turn changed"),
        ("note", "eslint: 1 problems on lines this turn did not change"),
    ]


@pytest.mark.parametrize(
    "config, said",
    [
        ('{"files": [], "references": [{"path": "./tsconfig.app.json"}]}', proof_style.NO_FILES),
        ('{"compilerOptions": {"composite": true}}', proof_style.COMPOSITE),
        ('{"compilerOptions": {', proof_style.NO_TSCONFIG),
        ('{\n  // checked\n  "compilerOptions": {"strict": true,},\n}', None),
    ],
)
def test_tsc_runs_only_on_a_tsconfig_that_checks_files_and_writes_nothing(tmp_path, config, said):
    (tmp_path / "web" / "node_modules" / ".bin").mkdir(parents=True)
    tsc = "node_modules/.bin/tsc.cmd" if sys.platform == "win32" else "node_modules/.bin/tsc"
    (tmp_path / "web" / tsc).write_text("")
    (tmp_path / "web" / "tsconfig.json").write_text(config, encoding="utf-8")
    runs, notes = proof_style.planned(tmp_path, ["web/src/a.ts"])
    if said is not None:  # (never a pass row for nothing checked)
        assert (runs, notes) == ([], [said])
        return
    ((_tool, line, cwd, _files),) = runs
    assert line == f"{tsc} --noEmit --pretty false --incremental false -p tsconfig.json"
    assert cwd == "web" and notes == []


def test_the_rule_a_card_offers_is_the_line_koloni_runs_and_covers_nothing_more(tmp_path):
    from app.commands import matches, suggest_prefix

    py = "a.py"
    lines = {
        "ruff": f"{RUFF} check --no-cache --output-format=concise ./{py}",
        "mypy": f"{RUFF.replace('ruff', 'mypy')} --no-error-summary --no-pretty "
        f"--cache-dir=.mypy_cache ./{py}",
        "eslint": f"{NODE} --format stylish --no-color ./a.js",
        "tsc": f"{NODE.replace('eslint', 'tsc')} --noEmit --pretty false --incremental false "
        "-p tsconfig.json",
    }
    escapes = {
        "ruff": ["--config C:/x/evil.toml", "--output-file C:/x/out.txt", "-o C:/x/out.txt"],
        "mypy": ["--python-executable C:/x/evil.exe", "--config-file C:/x/evil.ini",
                 "--cache-dir C:/x", "--junit-xml C:/x/out.xml"],
        "eslint": ["--resolve-plugins-relative-to C:/x", "-c C:/x/evil.js", "--rulesdir C:/x",
                   "-o C:/x/out.txt", "--config C:/x/evil.js"],
        "tsc": ["--outDir C:/x", "-p C:/x/tsconfig.json"],
    }  # fmt: skip
    assert suggest_prefix("./node_modules/.bin/eslint --format stylish ./a.js") == (
        "./node_modules/.bin/eslint --format stylish"
    )
    for tool, line in lines.items():
        offered = suggest_prefix(line)
        fixed = line.split(" ./")[0]
        assert offered == fixed, (tool, offered)
        assert matches(line, offered)  # (the line it was offered for)
        if " ./" in line:  # (and the same line on other files)
            assert matches(f"{fixed} ./b.py ./c.py", offered)
        program = line.split()[0]
        for escape in escapes[tool]:
            assert not matches(f"{fixed} {escape} ./b.py", offered), (tool, escape)
            # (nor an older rule of the bare program's)
            assert not matches(f"{program} {escape} ./b.py", program), (tool, escape)


@pytest.mark.no_po
def test_a_program_an_earlier_turn_planted_is_not_run_by_a_rule_either(
    make_client, wait_run, project_dir
):
    """B1 across turns: an Always rule matches by its text, in any folder - the eslint a turn
    wrote in admin's node_modules is never run by it in a later turn, while it holds what was
    written; the project's own install over it is the project's again."""
    from tests.test_proof_ci_scenarios import again

    eslint_in(project_dir, "web")
    planted = f"admin/{NODE}"
    executor = ScriptedExecutor([PASS, PASS, ESLINT_CLEAN, ESLINT_CLEAN, PASS, ESLINT_CLEAN])
    client, _model = make_client(
        [
            write("admin/eslint.config.js", "export default []\n", "w1"),
            write(planted, "@echo PLANTED %*\n", "w2"),
            text("done"),
            write("admin/x.js", "let x = 1\n", "w3"),
            text("done again"),
            write("admin/x.js", "let x = 2\n", "w4"),
            text("done once more"),
        ],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, mode="auto_edit", check_command="python check.py")
    wait_run(client, cid, run_id)
    assert (project_dir / planted).read_text() == "@echo PLANTED %*\n"
    # (an Always rule of web's eslint, said on a card before: the same text in admin)
    rule = f"{NODE} --format stylish --no-color"
    made = client.post(
        f"/api/conversations/{cid}/allowed-commands", json={"prefix": rule}, headers=OWN
    )
    assert made.status_code in (200, 201), made.text
    second, snap = again(client, wait_run, cid)
    assert not [cwd for _c, cwd in executor.started if Path(cwd).name == "admin"], executor.started
    said = "eslint: not run - this turn wrote in admin/node_modules: no install of the project's"
    rows = [
        row["text"]
        for m in snap["messages"]
        if m["role"] == "checked" and m["run_id"] == second
        for row in m["checked"]
    ]
    assert said in rows, rows
    # (the project's own install over it: theirs again - the rule runs it)
    (project_dir / planted).write_text("@echo the project's\n", encoding="utf-8")
    again(client, wait_run, cid)
    assert [Path(cwd).name for _c, cwd in executor.started].count("admin") == 1, executor.started


# --- the second session's round (W1, W2): a program an agent wrote, a name a shim runs bare ------


@pytest.mark.parametrize("name", ["node.cmd", "NODE.EXE", "python.exe", "node", "py.bat"])
def test_a_name_a_shim_runs_bare_written_where_it_runs_is_never_run(tmp_path, name):
    # W1: npm's tsc.cmd runs `node` - cmd.exe looked in the folder it runs in first
    eslint_in(tmp_path, "admin")
    said = proof_style.planted(tmp_path, tmp_path, an_eslint("admin"), [f"admin/{name}"])
    assert said == f"this turn wrote {name} in the folder it runs in"
    # (elsewhere, or another name: as before)
    assert proof_style.planted(tmp_path, tmp_path, an_eslint("admin"), [f"web/{name}"]) is None
    for other in ("admin/nodes.cmd", "admin/node.txt", "admin/src/node.cmd"):
        assert proof_style.planted(tmp_path, tmp_path, an_eslint("admin"), [other]) is None


def test_a_program_named_by_its_path_is_planted_by_itself_or_its_install_folder(tmp_path):
    (tmp_path / "web").mkdir()
    wrote = proof_style.wrote_program
    # (out of an install folder: the program, or a file Windows runs by its name, alone)
    assert wrote(tmp_path, ".", "./scripts/check", ["scripts/check.cmd"]) == "scripts/check"
    assert wrote(tmp_path, ".", "scripts/check", ["scripts/CHECK"]) == "scripts/check"
    assert wrote(tmp_path, ".", "scripts/check", ["scripts/check.txt", "scripts/x.cmd"]) is None
    # (in one: anything in it - what its shim runs is there too)
    tsc = "node_modules/.bin/tsc"
    assert wrote(tmp_path, "web", tsc, ["web/node_modules/typescript/bin/tsc"]) == (
        "web/node_modules"
    )
    assert wrote(tmp_path, "web", tsc, ["node_modules/.bin/tsc.cmd"]) is None
    assert wrote(tmp_path, ".", ".venv\\Scripts\\ruff.exe", [".venv/Lib/site-packages/x.py"]) == (
        ".venv"
    )


def test_a_program_named_in_quotes_is_found_as_its_shell_reads_it(tmp_path):
    # W2: a quoted program path with a space in it - one word, as `commands._words` reads it
    from app.command_runner import _planted
    from app.db.models import Agent, Conversation, FileChange, Project
    from app.db.models import Run as RunRow
    from app.db.session import make_engine, make_session_factory, upgrade_db
    from app.workspace import sha256_text

    upgrade_db(tmp_path / "k.db")
    factory = make_session_factory(make_engine(tmp_path / "k.db"))
    tool = tmp_path / "my tools" / "node_modules" / ".bin" / "tsc.cmd"
    tool.parent.mkdir(parents=True)
    tool.write_text("@echo PLANTED\n", encoding="utf-8")
    with factory() as session:
        session.add(Project(id="p", name="p", root_path=str(tmp_path)))
        session.flush()
        session.add(Conversation(id="c", project_id="p"))
        session.flush()
        session.add(RunRow(id="r", conversation_id="c", status="completed"))
        session.flush()
        session.add(Agent(id="a", run_id="r", role_name="Lead", tools=[]))
        session.flush()
        session.add(
            FileChange(
                run_id="r",
                agent_id="a",
                path="my tools/node_modules/.bin/tsc.cmd",
                kind="create",
                after_content="@echo PLANTED\n",
                after_sha=sha256_text("@echo PLANTED\n"),
                status="applied",
            )
        )
        session.commit()
    for line in (
        '"my tools/node_modules/.bin/tsc.cmd" -p x',
        "& 'my tools/node_modules/.bin/tsc.cmd'",
    ):
        assert _planted(factory, "c", tmp_path, line, ".") == (
            "an agent wrote its program (my tools/node_modules): no rule covers a program an "
            "agent wrote"
        ), line
    # (the project's own install over it: theirs again)
    tool.write_text("@echo the project's\n", encoding="utf-8")
    assert _planted(factory, "c", tmp_path, '"my tools/node_modules/.bin/tsc.cmd"', ".") is None


TSC = NODE.replace("eslint", "tsc")
TSC_LINE = f"{TSC} --noEmit --pretty false --incremental false -p tsconfig.json"


@pytest.mark.no_po
@pytest.mark.parametrize(
    ("written", "cwd", "asked"),
    [
        (f"sub096/{TSC}", "sub096", "sub096/node_modules"),  # (the review's Q4)
        (TSC, ".", "node_modules"),  # (over the project's own)
        ("sub096/notes.md", ".", None),  # (an install nobody wrote in: the rule covers it)
    ],
)
def test_an_always_rule_does_not_cover_a_program_an_agent_wrote(
    make_client, wait_run, project_dir, written, cwd, asked
):
    """W2: the root's tsc has an Always rule; a later turn runs the rule's very line where an
    agent wrote a tsc of its own - asked on a card, whatever the rule says, and said why."""
    from tests.test_agent_commands import cmd

    (project_dir / TSC).parent.mkdir(parents=True)
    (project_dir / TSC).write_text("@echo the project's\n", encoding="utf-8")
    executor = ScriptedExecutor([PASS, PASS, PASS, PASS])
    client, _model = make_client(
        [
            write(written, "@echo PLANTED %*\n", "w1"),
            text("done"),
            cmd(TSC_LINE, "k1", **({"cwd": cwd} if cwd != "." else {})),
            text("asked"),
        ],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, mode="auto_edit", check_command="python check.py")
    wait_run(client, cid, run_id)
    made = client.post(
        f"/api/conversations/{cid}/allowed-commands", json={"prefix": TSC_LINE}, headers=OWN
    )
    assert made.status_code in (200, 201), made.text
    second = client.post(f"/api/conversations/{cid}/messages", json={"content": "check"}).json()
    if asked is None:
        snap = wait_run(client, cid, second["run"]["id"])
        (ran,) = [one for one in snap["commands"] if one["command"] == TSC_LINE]
        assert ran["status"] == "exited", snap["commands"]
        return
    snap = wait_status(client, cid, "waiting_approval")
    (card,) = [one for one in snap["commands"] if one["command"] == TSC_LINE]
    assert card["status"] == "proposed", snap["commands"]
    assert card["danger"] == (
        f"an agent wrote its program ({asked}): no rule covers a program an agent wrote"
    )
    assert TSC_LINE not in [line for line, _cwd in executor.started]
    client.post(f"/api/commands/{card['id']}/reject")
    wait_run(client, cid, second["run"]["id"])


@pytest.mark.no_po
@pytest.mark.parametrize(
    ("mode", "line", "rule"),
    [
        ("auto_edit", TSC_LINE, TSC_LINE),
        ("full_auto", TSC_LINE, TSC_LINE),
        # (W6: a package runner's line - a trigger's leave is a rule of the very line)
        ("auto_edit", "npx tsc --noEmit", "npx tsc --noEmit"),
    ],
)
def test_a_triggers_leave_does_not_run_a_program_an_agent_wrote(
    make_client, wait_run, project_dir, mode, line, rule
):
    """W2 where nobody watches (the re-review's probe): a trigger with write leave and a ticked
    rule for tsc's line - the agent writes over the project's tsc and runs the line: refused,
    its why in the result, at any level."""
    from tests.test_agent_commands import cmd
    from tests.test_triggers import allow, leave, run_now, setup, trigger

    (project_dir / TSC).parent.mkdir(parents=True)
    (project_dir / TSC).write_text("@echo the project's\n", encoding="utf-8")
    executor = ScriptedExecutor([PASS, PASS, PASS, PASS])
    client, model, pid, cid = setup(
        make_client,
        project_dir,
        [write(TSC, "@echo PLANTED %*\n", "w1"), cmd(line, "k1"), text("done")],
        executor=executor,
        permission_mode=mode,
    )
    rules = [allow(client, cid, rule)]
    made = trigger(client, pid, cid, permissions=leave(write=True, commands=rules))
    snap = wait_run(client, cid, run_now(client, made["id"]))
    assert (project_dir / TSC).read_text() == "@echo PLANTED %*\n"
    assert line not in [one for one, _cwd in executor.started], executor.started
    (refused,) = [one for one in snap["commands"] if one["command"] == line]
    assert refused["status"] == "refused", snap["commands"]
    said = [str(m["content"]) for m in model.calls[-1] if m["role"] == "tool"]
    assert any(
        "an agent wrote its program (node_modules)" in one and "nobody is here to ask" in one
        for one in said
    ), said


@pytest.mark.no_po
@pytest.mark.parametrize(
    ("line", "written", "asked"),
    [
        ("npx tsc --noEmit", TSC, "node_modules"),  # (the second session's Q9b)
        ("npm exec tsc -- --noEmit", "node_modules/typescript/bin/tsc", "node_modules"),
        ("yarn tsc --noEmit", "node_modules/typescript/bin/tsc", "node_modules"),
        ("uv run ruff check .", RUFF, ".venv"),
        ("python -m mypy .", "mypy.py", "mypy.py"),  # (`-m` reads its folder's own first)
        # (the last look's probe: any module the tool imports - the standard one shadowed)
        ("python -m ruff check .", "subprocess.py", "subprocess.py"),
        ("python3.12 -m ruff check .", "click/__init__.py", "click"),
        (f"{RUFF.replace('ruff', 'python')} -m ruff check .", "subprocess.py", "subprocess.py"),
        ("bun x tsc --noEmit", "node_modules/typescript/bin/tsc", "node_modules"),
        ("yarn tsc --noEmit", ".yarnrc.yml", ".yarnrc.yml"),  # (its `yarnPath` runs)
        ("corepack pnpm exec tsc --noEmit", TSC, "node_modules"),
        (
            "node node_modules/typescript/bin/tsc --noEmit",
            "node_modules/typescript/lib/x.js",
            "node_modules",
        ),
        ("npx tsc --noEmit", "notes.md", None),  # (an install nobody wrote in: covered)
        ("uv run ruff check .", "src/venv_notes.py", None),
        ("python -m ruff check .", "src/app.py", None),  # (no module of its folder's)
        ("python -m pytest -q", "subprocess.py", None),  # (its tests run the project's code)
    ],
)
def test_a_package_runners_rule_does_not_cover_a_program_an_agent_wrote(
    make_client, wait_run, project_dir, line, written, asked
):
    """W6: `npx tsc` (the rule a card offers for `npx tsc --noEmit`), `npm exec tsc`, `uv run
    ruff` - a runner finds its program in the project's install itself: where an agent wrote
    there, its rule covers the line no more."""
    from app.commands import is_allowed, suggest_prefix
    from tests.test_agent_commands import cmd

    rule = suggest_prefix(line)
    assert is_allowed(line, [rule]), rule  # (a rule that covers the very line)
    (project_dir / TSC).parent.mkdir(parents=True)
    (project_dir / TSC).write_text("@echo the project's\n", encoding="utf-8")
    executor = ScriptedExecutor([PASS, PASS, PASS, PASS])
    client, _model = make_client(
        [write(written, "PLANTED\n", "w1"), text("done"), cmd(line, "k1"), text("asked")],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, mode="auto_edit", check_command="python check.py")
    wait_run(client, cid, run_id)
    made = client.post(
        f"/api/conversations/{cid}/allowed-commands", json={"prefix": rule}, headers=OWN
    )
    assert made.status_code in (200, 201), made.text
    second = client.post(f"/api/conversations/{cid}/messages", json={"content": "check"}).json()
    if asked is None:
        snap = wait_run(client, cid, second["run"]["id"])
        (ran,) = [one for one in snap["commands"] if one["command"] == line]
        assert ran["status"] == "exited", snap["commands"]
        return
    snap = wait_status(client, cid, "waiting_approval")
    (card,) = [one for one in snap["commands"] if one["command"] == line]
    assert card["status"] == "proposed", snap["commands"]
    assert card["danger"] == proof_style_planted(asked)
    assert line not in [one for one, _cwd in executor.started]
    client.post(f"/api/commands/{card['id']}/reject")
    wait_run(client, cid, second["run"]["id"])


def test_a_package_runner_finds_its_program_up_the_tree_or_anywhere_it_cannot_place(tmp_path):
    from app.command_runner import _runner_places

    reach = _runner_places(["npx", "tsc"], "web/app")
    places, anywhere = reach.places, reach.anywhere
    assert "web/app/node_modules" in places and "node_modules" in places and "web/.npmrc" in places
    assert not anywhere and not reach.reads_cwd and not reach.reads_path
    found = proof_style.planted_in
    assert found(tmp_path, places, anywhere, "web/Node_Modules/x/y.js") == "web/node_modules"
    assert found(tmp_path, places, anywhere, "api/node_modules/x.js") is None  # (not its own)
    # (an environment KOLONİ cannot place: any install folder of the project's - fails closed)
    reach = _runner_places(["poetry", "run", "ruff", "check"], ".")
    assert found(tmp_path, reach.places, reach.anywhere, "tools/env/Lib/site-packages/r.py") == (
        "tools/env/Lib/site-packages"
    )
    assert not reach.reads_cwd and reach.reads_path  # (its Python reads PYTHONPATH)
    reach = _runner_places(["corepack", "yarn", "tsc"], "web")
    assert found(tmp_path, reach.places, (), ".yarn/releases/yarn-4.cjs") == ".yarn"
    reach = _runner_places(["pnpm", "exec", "tsc"], "web")  # (its hooks run code)
    assert found(tmp_path, reach.places, (), ".pnpmfile.cjs") == ".pnpmfile.cjs"
    assert _runner_places(["pytest", "-q"], ".") is None
    assert _runner_places(["python", "x.py"], ".") is None


@pytest.mark.parametrize(
    ("words", "module", "reads_cwd", "reads_path"),
    [
        (["python", "-m", "ruff"], "ruff", True, True),
        (["python", "-mruff", "check"], "ruff", True, True),
        (["python", "-X", "dev", "-m", "ruff"], "ruff", True, True),
        (["py", "-3.12", "-m", "ruff"], "ruff", True, True),
        (["python", "-I", "-m", "ruff"], "ruff", False, False),  # (isolated: neither)
        (["python", "-Im", "ruff"], "ruff", False, False),
        (["python3.12", "-P", "-m", "ruff"], "ruff", False, True),  # (PYTHONPATH all the same)
        (["python", "-E", "-m", "ruff"], "ruff", True, False),
        (["python", "x.py", "-m", "ruff"], None, False, False),
        (["python", "-c", "import ruff"], None, False, False),
    ],
)
def test_python_m_reads_the_folder_it_runs_in_first_unless_told_not_to(
    words, module, reads_cwd, reads_path, monkeypatch
):
    # W6: `python -m ruff` imported a `subprocess.py` the agent wrote in its folder
    from app.command_runner import _python_module, _runner_places

    said = _python_module(words)
    assert (said and said[0]) == module
    if module:
        monkeypatch.delenv("PYTHONSAFEPATH", raising=False)
        reach = _runner_places(words, ".")
        assert (reach.reads_cwd, reach.reads_path) == (reads_cwd, reads_path)
        monkeypatch.setenv("PYTHONSAFEPATH", "1")
        # (under -E the variable is not read either)
        assert _runner_places(words, ".").reads_cwd is (reads_cwd and "-E" in words)


def _copy_db(tmp_path, writes: dict[str, str]):
    """A project in `tmp_path/p` whose agent wrote `writes` on record - and the copy
    `tmp_path/copy` that holds them."""
    from app.db.models import Agent, Conversation, FileChange, Project
    from app.db.models import Run as RunRow
    from app.db.session import make_engine, make_session_factory, upgrade_db
    from app.workspace import sha256_text

    upgrade_db(tmp_path / "k.db")
    factory = make_session_factory(make_engine(tmp_path / "k.db"))
    (tmp_path / "p").mkdir()
    for rel, said in writes.items():
        (tmp_path / "copy" / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "copy" / rel).write_text(said, encoding="utf-8")
    with factory() as session:
        session.add(Project(id="p", name="p", root_path=str(tmp_path / "p")))
        session.flush()
        session.add(Conversation(id="c", project_id="p"))
        session.flush()
        session.add(RunRow(id="r", conversation_id="c", status="completed"))
        session.flush()
        session.add(Agent(id="a", run_id="r", role_name="Coder", tools=[]))
        session.flush()
        for rel, said in writes.items():
            session.add(
                FileChange(
                    run_id="r",
                    agent_id="a",
                    path=rel,
                    kind="create",
                    after_content=said,
                    after_sha=sha256_text(said),
                    status="in_copy",
                )
            )
        session.commit()
    return factory


UVICORN = ".venv/Scripts/uvicorn.exe" if sys.platform == "win32" else ".venv/bin/uvicorn"


@pytest.mark.parametrize(
    ("line", "cwd", "written", "asked"),
    [
        ("python -m ruff --version", ".", "src/subprocess.py", "src/subprocess.py"),  # (A)
        ("python -m ruff --version", "sub", "subprocess.py", "subprocess.py"),  # (B)
        ("python -m ruff --version", "sub", "sitecustomize.py", "sitecustomize.py"),  # (C)
        (f"{UVICORN} app:app", ".", "src/subprocess.py", "src/subprocess.py"),  # (D)
        (f"{UVICORN} app:app", "sub", "sitecustomize.py", "sitecustomize.py"),
        ("uv run mypy .", "sub", "src/click/__init__.py", "src/click"),
        # (pytest's tests import the project's code anyway - not what runs before them)
        ("python -m pytest -q", "sub", "subprocess.py", None),
        ("python -m pytest -q", "sub", "src/sitecustomize.py", "src/sitecustomize.py"),
        (".venv/Scripts/pytest.exe -q", ".", "usercustomize.py", "usercustomize.py"),
        # (-E: PYTHONPATH is not read - the folder it runs in still is)
        ("python -E -m ruff --version", "sub", "subprocess.py", None),
        ("python -E -m ruff --version", ".", "subprocess.py", "subprocess.py"),
        ("python -m ruff --version", ".", "src/app/core.py", None),  # (no module of its own)
    ],
)
def test_in_a_copy_a_python_imports_what_its_pythonpath_holds_first(
    tmp_path, line, cwd, written, asked
):
    """W6, the final look's probe: in a working copy every command gets PYTHONPATH=<copy>;
    <copy>/src (`host.copy_python_path`) - a `subprocess.py` an agent wrote there ran under
    `python -m ruff` in any folder, a `sitecustomize.py` under every Python started there."""
    from app.command_runner import PLANTED, _planted

    factory = _copy_db(tmp_path, {written: "print('PLANTED')\n"})
    (tmp_path / "copy" / "sub").mkdir(exist_ok=True)
    said = _planted(factory, "c", (tmp_path / "copy").resolve(), line, cwd)
    assert said == (PLANTED.format(place=asked) if asked else None)
    # (the same writes in the project itself: no PYTHONPATH - only `-m`'s own folder)
    if written.startswith("src/") or cwd == "sub":
        assert _planted(factory, "c", (tmp_path / "p").resolve(), line, cwd) is None


def test_python_m_imports_a_module_its_folder_holds_before_the_standard_one(tmp_path):
    """The premise of `_python_module`, on this Python: a stand-in tool run by `-m` imports the
    `colorsys.py` written in its folder, not the standard one - under -P, not."""
    site, work = tmp_path / "site", tmp_path / "work"
    (site / "standin").mkdir(parents=True)
    (site / "standin" / "__init__.py").write_text("", encoding="utf-8")
    (site / "standin" / "__main__.py").write_text("import colorsys\nprint('ran')\n")
    work.mkdir()
    (work / "colorsys.py").write_text("print('PLANTED')\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONSAFEPATH"}
    env["PYTHONPATH"] = str(site)
    for flags, planted in (([], True), (["-P"], False)):
        done = subprocess.run(
            [sys.executable, *flags, "-m", "standin"],
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
            timeout=scaled(30),
        )
        assert ("PLANTED" in done.stdout) is planted and "ran" in done.stdout, (
            flags,
            done.stdout + done.stderr,
        )


def test_a_sitecustomize_on_pythonpath_runs_before_anything_under_p_too(tmp_path):
    """The premise of the copy's `sitecustomize` (W6): a Python started with a folder on
    PYTHONPATH imports its `sitecustomize.py` before the module it runs - under -P too, not
    under -E; one in the folder it runs in alone is not imported so."""
    site, work = tmp_path / "site", tmp_path / "work"
    (site / "standin").mkdir(parents=True)
    (site / "standin" / "__init__.py").write_text("", encoding="utf-8")
    (site / "standin" / "__main__.py").write_text("print('ran')\n", encoding="utf-8")
    work.mkdir()
    (work / "sitecustomize.py").write_text("print('PLANTED')\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONSAFEPATH"}
    for path, flags, planted in (
        ([work, site], ["-P"], True),
        ([work, site], ["-E"], False),
        ([site], [], False),
    ):
        env["PYTHONPATH"] = os.pathsep.join(map(str, path))
        argv = [sys.executable, *flags, "-c", "print('ran')"] if "-E" in flags else None
        done = subprocess.run(
            argv or [sys.executable, *flags, "-m", "standin"],
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
            timeout=scaled(30),
        )
        assert ("PLANTED" in done.stdout) is planted and "ran" in done.stdout, (
            flags,
            done.stdout + done.stderr,
        )


def test_what_python_m_imports_from_its_folder_before_the_tools_own():
    shadows = proof_style.shadows
    assert shadows(".", "subprocess.py") == "subprocess.py"
    assert shadows(".", "Click/__init__.py") == "Click"
    assert shadows("api", "api/json.py") == "api/json.py"
    assert shadows("api", "json.py") is None  # (another folder's)
    assert shadows(".", "app/core.py") is None  # (in a package of the project's own)
    assert shadows(".", "notes.md") is None
    # (`startup_only`: what `site` imports before anything - pytest's own run)
    assert shadows("src", "src/sitecustomize.py", startup_only=True) == "src/sitecustomize.py"
    assert shadows(".", "subprocess.py", startup_only=True) is None


def proof_style_planted(place: str) -> str:
    from app.command_runner import PLANTED

    return PLANTED.format(place=place)


# --- the second session's round (W3-W5): what a tool said, how long its lines take ------------


@pytest.mark.parametrize(
    ("line", "tool", "runs"),
    [
        ("pip install ruff", "ruff", False),
        ("echo ruff", "ruff", False),
        ("ruff --version", "ruff", False),
        ("pytest -q -k ruff", "ruff", False),
        ("npm install eslint", "eslint", False),
        ("npx eslint -v", "eslint", False),
        ("pytest -k mypy", "mypy", False),
        ("ruff format --check . && echo ok", "ruff", False),
        (".venv/Scripts/ruff.exe check", "ruff", True),
        ("ruff check . && ruff format --check .", "ruff", True),
        ("FORCE_COLOR=0 uv run --frozen ruff check src", "ruff", True),
        ("python -m mypy src", "mypy", True),
        ("cd web && npx tsc --noEmit", "tsc", True),
    ],
)
def test_a_check_line_runs_a_tool_only_as_a_commands_program(line, tool, runs):
    assert proof_style.runs_tool(line, tool) is runs


@pytest.mark.parametrize(
    ("tool", "output", "said"),
    [
        (
            "ruff",
            "lint096.py:1:7: invalid-syntax: Expected a parameter name\nFound 1 error.\n",
            "ruff invalid-syntax - Expected a parameter name",
        ),
        (
            "ruff",
            "lint096.py:1:7: SyntaxError: Expected ')'\n",
            "ruff invalid-syntax - Expected ')'",
        ),
        ("mypy", "lint096.py:1: error: invalid syntax  [syntax]\n", "mypy syntax - invalid syntax"),
        ("tsc", "lint096.py(1,7): error TS1005: ',' expected.\n", "tsc TS1005 - ',' expected."),
        (
            "eslint",
            "lint096.py\n  1:7  error  Parsing error: Unexpected token\n",
            "eslint - Parsing error: Unexpected token",
        ),
    ],
)
def test_a_file_a_tool_cannot_parse_is_a_problem_not_unread_output(tmp_path, tool, output, said):
    # W3: ruff's concise `invalid-syntax:` was "its output was not read (exit 1)"
    run = proof_style.Run(tool, "x", ".", ("lint096.py",))
    rows = proof_style.rows_of(run, 1, output, tmp_path, {"lint096.py": [1]})
    assert [(one["state"], one["text"]) for one in rows] == [("failed", f"lint096.py:1: {said}")]
    # (on a line the turn did not write: said, never a pass)
    rows = proof_style.rows_of(run, 1, output, tmp_path, {"lint096.py": [2]})
    assert [one["state"] for one in rows] == ["note"]


REPEATED = ("a = 1\n" * 1200, "".join("b = 2\n" if n % 10 == 0 else "a = 1\n" for n in range(1200)))


def test_a_file_too_large_to_compare_in_time_is_not_judged_and_never_passes(tmp_path):
    # W4: only the files a tool said a problem in are compared, while the kind's time lasts
    run = proof_style.Run("ruff", LINE, ".", ("app.py", "big.py", "quiet.py"))
    texts = {"app.py": ("", NEW), "big.py": REPEATED, "quiet.py": REPEATED}
    added = proof_style.Changed(texts, time.monotonic() + 60)
    output = "app.py:1:8: F401 [*] `os` imported but unused\nbig.py:5:1: E501 Line too long\n"
    rows = proof_style.rows_of(run, 1, output, tmp_path, added)
    assert [(one["state"], one["text"]) for one in rows] == [
        ("failed", "app.py:1: ruff F401 - `os` imported but unused"),
        ("note", "ruff: 1 problems not judged - too large to compare in time: big.py"),
    ]
    assert sorted(added._lines) == ["app.py", "big.py"]  # (quiet.py: never compared)
    # (the kind's time gone: nothing is compared, nothing passes)
    late = proof_style.Changed({"app.py": ("", NEW)}, time.monotonic() - 1)
    rows = proof_style.rows_of(run, 1, "app.py:1:8: F401 x\n", tmp_path, late)
    assert [one["state"] for one in rows] == ["note"] and "not judged" in rows[0]["text"]


GROWTH = """
import sys, time
from app.proof import changed_lines
lines, spread = int(sys.argv[1]), sys.argv[2] == "spread"
if spread:  # (every line its own, every 7th changed: anchored, exact)
    before = "".join(f"x{n} = {n}\\n" for n in range(lines))
    after = "".join(f"x{n} = {n + (n % 7 == 0)}\\n" for n in range(lines))
else:  # (one line repeated, every 10th changed: difflib's worst)
    before = "a = 1\\n" * lines
    after = "".join("b = 2\\n" if n % 10 == 0 else "a = 1\\n" for n in range(lines))
start = time.perf_counter()
said = changed_lines(before, after)
print(len(before), "none" if said is None else len(said), time.perf_counter() - start)
"""


@pytest.mark.parametrize(
    ("lines", "kind", "said"),
    [(400, "repeated", "40"), (2600, "repeated", "none"), (1300, "spread", "186")],
)
def test_comparing_a_files_lines_stays_short_whatever_its_size(lines, kind, said):
    """W4: autojunk-off difflib took 1.8 s on 1 000 repeated lines and grew past their square
    (2 600 such lines, 15.6 KB: about 30 s). In a child process, at most ~16 KB of input."""
    done = subprocess.run(
        [sys.executable, "-c", GROWTH, str(lines), kind],
        capture_output=True,
        text=True,
        timeout=scaled(60),
        cwd=Path(__file__).resolve().parents[1],
    )
    size, found, seconds = done.stdout.split()
    assert int(size) <= 16 * 1024 and found == said, done.stdout + done.stderr
    assert float(seconds) < (20 if os.environ.get("CI") else 5), done.stdout


@pytest.mark.parametrize(
    ("run", "texts", "gone", "said"),
    [
        # (pyproject's [tool.ruff]: its own part changed - another part did not change it)
        (
            ("ruff", ".", ("app.py",)),
            {"pyproject.toml": ("[tool.ruff]\n", "[tool.ruff]\nlint.ignore = ['F401']\n")},
            (),
            "pyproject.toml",
        ),
        (
            ("ruff", ".", ("app.py",)),
            {
                "pyproject.toml": (
                    '[project]\nname = "x"\n[tool.ruff]\n',
                    '[project]\nname = "y"\n[tool.ruff]\n',
                )
            },
            (),
            None,
        ),
        (
            ("ruff", ".", ("web/app.py",)),
            {"web/ruff.toml": ("", "exclude = ['*']\n")},
            (),
            "web/ruff.toml",
        ),
        (("ruff", ".", ("app.py",)), {"api/ruff.toml": ("", "exclude = ['*']\n")}, (), None),
        (("ruff", ".", ("app.py",)), {}, ("RUFF.toml",), "RUFF.toml"),
        (
            ("tsc", "web", ("web/a.ts",)),
            {"tsconfig.base.json": ("{}", '{"strict": false}')},
            (),
            "tsconfig.base.json",
        ),
        (
            ("mypy", ".", ("a.py",)),
            {"setup.cfg": ("[mypy]\n", "[mypy]\n[mypy-x.*]\nignore_errors = True\n")},
            (),
            "setup.cfg",
        ),
        (
            ("eslint", ".", ("a.js",)),
            {"package.json": ('{"name": "x"}', '{"name": "y"}')},
            (),
            None,
        ),
        (
            ("eslint", ".", ("a.js",)),
            {"package.json": ("{}", '{"eslintConfig": {"rules": {}}}')},
            (),
            "package.json",
        ),
    ],
)
def test_a_tools_settings_the_turn_changed_are_said_beside_what_it_found(run, texts, gone, said):
    # W5: the turn's `ignore = ["F401"]` made ruff quiet on its own lines
    tool, cwd, files = run
    note = proof_style.settings_changed(proof_style.Run(tool, "x", cwd, files), texts, gone)
    expected = proof_style.SETTINGS_CHANGED.format(tool=tool, path=said) if said else None
    assert note == expected


@pytest.mark.parametrize(
    ("tool", "output", "said"),
    [
        (
            "ruff",
            "\x1b[33mwarning\x1b[0m: No Python files found under the given path(s)\n",
            "ruff: not checked - it found none of the turn's files to check "
            "(No Python files found under the given path(s))",
        ),
        (
            "eslint",
            'a.js\n  0:0  warning  File ignored because of a matching ignore pattern. Use "--no-ignore"'
            " to override\n",
            "eslint: 1 of the turn's files not checked - its settings leave them out",
        ),
    ],
)
def test_a_tool_that_checked_none_of_the_files_never_passes(tmp_path, tool, output, said):
    # W5: a `force-exclude` over the turn's file: ruff ends 0, having checked nothing
    run = proof_style.Run(tool, "x", ".", ("a.js",))
    rows = proof_style.rows_of(run, 0, output, tmp_path, {"a.js": [1]})
    assert [(one["state"], one["text"]) for one in rows] == [("note", said)]


@pytest.mark.no_po
def test_ruffs_settings_the_turn_changed_are_said_on_its_row(make_client, wait_run, project_dir):
    set_up(project_dir)
    executor = ScriptedExecutor([PASS, RUFF_CLEAN])
    settings = '[project]\nname = "x"\n\n[tool.ruff]\nlint.ignore = ["F401"]\n'
    client, _model = make_client(
        [write("pyproject.toml", settings, "w0"), write("app.py", NEW), text("done")],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    rows = texts(wait_run(client, cid, run_id))
    assert "ruff's settings changed this turn (pyproject.toml) - the check runs by them" in rows
    assert "ruff: no problems on the lines this turn changed (1 files)" in rows, rows
