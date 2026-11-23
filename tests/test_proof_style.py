"""Check by kind of work, 0.1.7's Code style and types: the project's own ruff, eslint, tsc and mypy -
where it sets one up and has it installed - on the files a turn changed, run as its test command is
(a card at Ask and Auto-edit where no rule covers it, one a tool a turn; not while nobody can be
asked). A problem on a line the turn wrote fails, the others are said. The tools are scripted
(`ScriptedExecutor`); one test runs this machine's own ruff through the shell as KOLONİ would."""

import subprocess
import sys
from pathlib import Path

import pytest

from app import proof, proof_style
from app.executors import host
from tests.fakes import Script, ScriptedExecutor
from tests.keyed import OWN
from tests.test_agent_writes import wait_status, write
from tests.test_chat_flow import text
from tests.test_proof_end_scenarios import PASS, begin, texts

RUFF = ".venv/Scripts/ruff.exe" if sys.platform == "win32" else ".venv/bin/ruff"
LINE = f"{RUFF} check --no-cache --output-format=concise ./app.py"
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
    assert asked["suggested_prefix"] == RUFF  # (Always: the tool, never asked again)
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
def test_the_real_ruffs_line_runs_in_koloni_s_shell_and_is_read(tmp_path):
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
    done = subprocess.run(
        host.shell_argv(run.command), cwd=tmp_path, capture_output=True, timeout=120, check=False
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
