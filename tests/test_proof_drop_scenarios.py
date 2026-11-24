"""R, second round (the review's probes, the main session's rule): a drop against the project's last
green run - fewer tests run, more skipped - is "not this turn's change" only where that is shown;
anything the turn may have done is its own, as before R: a command that may write (in a recipe's
copy too, `git rm && git commit`, `git mv`), a test file edited with a skip or an xfail, a removal
of another turn's whose suite ended after its answer. A fake model and a scripted executor."""

import subprocess
import sys
import time

import pytest
from sqlalchemy import select

from app.agent import before_mixin, stronger_mixin
from app.db.models import Project
from tests.conftest import scaled
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_writes import write
from tests.test_chat_flow import text
from tests.test_proof_before_scenarios import CALC_TESTS, PYTEST, passing, second_turn
from tests.test_proof_end_scenarios import begin, run

pytestmark = pytest.mark.no_po

ONE_LEFT = "def test_one():\n    pass\n"
DROP = "Tests went from 48 to 47 (1 removed)"
NOT_OURS = before_mixin.NOT_OURS.format(said=DROP)


def rows_of(snap, run_id):
    return [
        r
        for m in snap["messages"]
        if m["role"] == "checked" and m["run_id"] == run_id
        for r in m["checked"]
    ]


def said(rows):
    return [(r["text"], r["state"]) for r in rows]


def settled(client, cid, run_id):
    """Its Checked rows once none is running (a suite gone on after the answer has ended)."""
    deadline = time.monotonic() + scaled(20)
    while True:
        rows = rows_of(client.get(f"/api/conversations/{cid}").json(), run_id)
        if rows and not any(r["state"] == "running" for r in rows):
            return rows
        assert time.monotonic() < deadline, said(rows)
        time.sleep(0.05)


def green(client):
    with client.app.state.session_factory() as session:
        (tests_green,) = session.scalars(select(Project.tests_green)).all()
    return [one["ran"] for one in (tests_green or {}).values()]


def git(root, *args):
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=scaled(60),
    )
    assert done.returncode == 0, (args, done.stdout, done.stderr)


def committed(root):
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "init")


@pytest.mark.parametrize("in_git", [False, True], ids=["plain", "git"])
def test_a_command_in_a_recipes_copy_that_rewrites_a_test_file_is_the_turns(
    make_client, wait_run, project_dir, in_git
):
    # (Probe A: the recipe's Coder, in its copy, runs a script that rewrites tests/test_calc.py
    # with one test of two, and fixes calc.py by a tool. Before: "not this turn's change", taken
    # in, the green state 47. Now sent back, and held after its round: why, said.)
    from tests.test_chat_teams_scenarios import OWN, teams_of
    from tests.test_recipe_run_scenarios import made
    from tests.test_recipes_scenarios import graph
    from tests.test_recipes_scenarios import step as part
    from tests.test_spawn import spawn

    (project_dir / "tests").mkdir(exist_ok=True)
    (project_dir / "tests" / "test_calc.py").write_text(CALC_TESTS, encoding="utf-8")
    if in_git:
        committed(project_dir)
    client, _model = make_client(
        {
            "Lead": [
                write("a.py", "x = 1\n"),
                text("done"),
                spawn("Coder", "fix it", "c1"),
                *[text(f"done {i}") for i in range(4)],
            ],
            "Coder": [
                run("python regen_tests.py", "k1"),
                write("calc.py", "x = 2\n", "w3"),
                text("fixed"),
            ],
            "Coder 2": [text("nothing to change")],
        },
        executor=ScriptedExecutor(
            [
                passing(48),
                Script(["ok\n"], writes={"tests/test_calc.py": ONE_LEFT}),
                *[passing(47)] * 8,
            ]
        ),
    )
    cid, run_id = begin(client, project_dir, check_command=PYTEST, fix_rounds=1)
    wait_run(client, cid, run_id)
    recipe = made(
        client,
        "Just fix it",
        {
            **graph([part("fix", "Fix it", {"role": "Coder"})], [("start", "fix"), ("fix", "end")]),
            "checks": {"tests": True, "review": False},
        },
    )
    patched = client.patch(
        f"/api/conversations/{cid}",
        json={
            "spawn_approval": "never",
            "teams_mode": "manual",
            "teams": [{"team_id": teams_of(client)["Web app"]["id"], "recipe_id": recipe["id"]}],
        },
        headers=OWN,
    )
    assert patched.status_code == 200, patched.text
    second = client.post(
        f"/api/conversations/{cid}/messages", json={"content": "fix"}, headers=OWN
    ).json()["run"]["id"]
    rows = rows_of(wait_run(client, cid, second), second)
    assert (DROP, "failed") in said(rows) and (NOT_OURS, "note") not in said(rows), said(rows)
    # (the counts alone failing after its round: not taken in, and why - "removed", Fix it's words)
    (held,) = [r for r in rows if r["kind"] == "not_taken"]
    assert held["reason"] == "removed", held
    assert held["text"] == f"Not taken in: {stronger_mixin.TESTS_REMOVED}", held
    assert (project_dir / "calc.py").exists() is False and green(client) == [48]


class GitExecutor(ScriptedExecutor):
    """Runs a `git …` line for real (each part of `&&`), in its folder; scripts for the rest."""

    async def start(self, command_id, command, cwd, copy=None, links=None, secrets=None, env=None):
        if command.startswith("git "):
            for part in command.split(" && "):
                git(cwd, *part.split()[1:])
        return await super().start(command_id, command, cwd, copy, links, secrets, env)


@pytest.mark.parametrize(
    "line",
    [
        "git rm -q tests/test_old.py && git commit -qm drop",  # (a committed deletion: no "D")
        "git mv tests/test_old.py tests/old_helpers.py",  # (a rename to a file that is no test)
        "python tidy_tests.py",  # (probe B: rewrites a test file the turn also edited by a tool)
    ],
    ids=["committed_rm", "git_mv", "rewrites_an_edited_file"],
)
def test_a_command_in_the_project_that_takes_a_test_away_is_the_turns(
    make_client, wait_run, project_dir, line
):
    (project_dir / "tests").mkdir(exist_ok=True)
    (project_dir / "tests" / "test_old.py").write_text("def test_old():\n    pass\n", "utf-8")
    (project_dir / "tests" / "test_calc.py").write_text(CALC_TESTS, encoding="utf-8")
    (project_dir / "a.py").write_text("x = 0\n", encoding="utf-8")
    committed(project_dir)
    edit = write("tests/test_calc.py", CALC_TESTS + "\n\ndef test_three():\n    pass\n", "w2")
    client, _model = make_client(
        [
            write("a.py", "x = 1\n"),
            text("done"),
            *([edit] if line.startswith("python") else []),
            run(line, "k2"),
            write("a.py", "x = 2\n", "w3"),
            text("done"),
            *[text(f"done again {i}") for i in range(3)],
        ],
        executor=GitExecutor(
            [
                passing(48),
                Script(["ok\n"], writes={"tests/test_calc.py": ONE_LEFT}),
                *[passing(47)] * 6,
            ]
        ),
    )
    cid, run_id = begin(client, project_dir, check_command=PYTEST, fix_rounds=1)
    wait_run(client, cid, run_id)
    git(project_dir, "add", "-A")
    git(project_dir, "commit", "-qm", "turn 1")
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "more"}).json()
    wait_run(client, cid, posted["run"]["id"])
    rows = said(settled(client, cid, posted["run"]["id"]))
    assert (DROP, "failed") in rows and (NOT_OURS, "note") not in rows, rows
    assert green(client) == [48], rows


def test_a_turns_own_removal_whose_suite_ends_after_its_answer_is_held_to_green(
    make_client, wait_run, project_dir
):
    # (Probe D: turn N takes test_two out of tests/test_calc.py by a tool - its related run passes
    # and the whole suite ends after the answer. Before: never held to green, and turn N+1, which
    # changes a.py only, got "48 -> 47 - not this turn's change". Now N's own Checked says the drop,
    # the green state stays 48, and N+1 is not told the drop is another's: it is sent back.)
    (project_dir / "tests").mkdir(exist_ok=True)
    (project_dir / "tests" / "test_calc.py").write_text(CALC_TESTS, encoding="utf-8")
    client, _model = make_client(
        [
            write("a.py", "x = 1\n"),
            text("done"),
            write("tests/test_calc.py", ONE_LEFT, "w2"),
            text("tidied the tests"),
            write("a.py", "x = 2\n", "w3"),
            text("done"),
            text("done again"),
        ],
        executor=ScriptedExecutor([passing(48), passing(1), passing(47), *[passing(47)] * 4]),
    )
    cid, run_id = begin(client, project_dir, check_command=PYTEST, fix_rounds=1)
    wait_run(client, cid, run_id)
    second = client.post(f"/api/conversations/{cid}/messages", json={"content": "tidy"}).json()
    wait_run(client, cid, second["run"]["id"])
    rows_n = said(settled(client, cid, second["run"]["id"]))
    assert (DROP, "failed") in rows_n and green(client) == [48], rows_n
    third = client.post(f"/api/conversations/{cid}/messages", json={"content": "more"}).json()
    wait_run(client, cid, third["run"]["id"])
    rows_n1 = said(settled(client, cid, third["run"]["id"]))
    assert (NOT_OURS, "note") not in rows_n1 and (DROP, "failed") in rows_n1, rows_n1
    assert green(client) == [48]


@pytest.mark.parametrize(
    "edited",
    [
        CALC_TESTS.replace("def test_two", "@pytest.mark.xfail\ndef test_two"),
        "import pytest\npytestmark = pytest.mark.skip\n" + CALC_TESTS,
    ],
    ids=["xfail", "pytestmark_skip"],
)
def test_a_test_file_weakened_by_lines_added_is_the_turns(
    make_client, wait_run, project_dir, edited
):
    # (Probe E: a recipe's Coder adds lines that the count of definitions does not read - an
    # xfail, a module's skip mark. 48 green -> 47: sent back, not taken in.)
    rows, taken, _model = second_turn(make_client, wait_run, project_dir, edited, (47,))
    assert (DROP, "failed") in rows and (NOT_OURS, "note") not in rows, rows
    assert not taken, rows


# R, third round: by test id - the probes that slipped past a list of words, each a turn's own.
CALC = CALC_TESTS.replace("def test_two", "{mark}def test_two")


@pytest.mark.parametrize(
    ("ini", "edited"),
    [
        # (an existing `addopts = -m "not slow"`: a test marked slow is deselected)
        (
            '[pytest]\naddopts = -m "not slow"\nmarkers = slow\n',
            "import pytest\n" + CALC.format(mark="@pytest.mark.slow\n"),
        ),
        (None, "import pytest\n" + CALC.format(mark='@pytest.mark.usefixtures("gpu")\n')),
        (None, "from tests.markers import later\n" + CALC.format(mark="@later\n")),
        (None, CALC_TESTS + "\ntest_two = None\n"),
        (None, "import sys\n" + CALC_TESTS + '\ndelattr(sys.modules[__name__], "test_two")\n'),
        (None, CALC_TESTS + '\nglobals().pop("test_two")\n'),
    ],
    ids=["slow_deselected", "skipping_fixture", "skip_alias", "rebound", "delattr", "globals_pop"],
)
def test_a_test_gone_from_a_file_the_turn_touched_is_the_turns(
    make_client, wait_run, project_dir, ini, edited
):
    from tests.test_proof_before_scenarios import GREEN

    if ini:
        (project_dir / "pytest.ini").write_text(ini, encoding="utf-8")  # (there before the turn)
    now = [one for one in GREEN if one != "tests/test_calc.py::test_two"]
    rows, taken, _model = second_turn(make_client, wait_run, project_dir, edited, (47,), ids=now)
    assert (DROP, "failed") in rows and (NOT_OURS, "note") not in rows and not taken, rows


def test_a_runner_that_lists_no_ids_leaves_a_drop_the_turns(make_client, wait_run, project_dir):
    # (with no ids listed, nothing shows where the tests went: the turn's, as before R)
    rows, _taken, _model = second_turn(
        make_client,
        wait_run,
        project_dir,
        CALC_TESTS + "\n\ndef test_three():\n    pass\n",
        (46,),
        by_hand=lambda: (project_dir / "tests" / "test_old.py").unlink(),
    )
    said = "Tests went from 48 to 46 (2 removed)"
    assert (said, "failed") in rows, rows  # (no ids: the turn's)


def test_a_test_file_the_turn_made_is_the_turns_wherever_the_tests_went(
    make_client, wait_run, project_dir
):
    # (test_old.py's tests deleted by hand, listed by id - but the turn made a test file: a new
    # spec's `.only` switches the others off, wherever they live - the turn's, fail safe)
    from tests.test_proof_before_scenarios import GREEN

    rows, _taken, _model = second_turn(
        make_client,
        wait_run,
        project_dir,
        "def test_new():\n    pass\n",
        (46,),
        by_hand=lambda: (project_dir / "tests" / "test_old.py").unlink(),
        ids=[one for one in GREEN if "test_old" not in one] + ["tests/test_new.py::test_new"],
        path="tests/test_new.py",
    )
    assert ("Tests went from 48 to 46 (2 removed)", "failed") in rows, rows


def test_a_tests_file_is_found_from_the_runs_folder_or_its_end():
    from app.agent.before_mixin import _touched

    assert _touched("tests/test_calc.py::test_one", ".", {"tests/test_calc.py"})
    assert _touched("tests/a.py::t", "web", {"web/tests/a.py"})
    assert _touched("a.py::t", ".", {"web/a.py"})  # (a rootdir elsewhere: any doubt, touched)
    assert _touched("src/a.test.ts", ".", {"src/a.test.ts"})  # (vitest's and jest's: the file)
    assert not _touched("tests/test_old.py::test_a", ".", {"tests/test_calc.py", "a.py"})


def test_ids_that_do_not_add_up_to_the_count_leave_the_drop_the_turns(
    make_client, wait_run, project_dir
):
    # (review: a turn's own removal riding on one made outside - test_old.py's tests deleted by
    # hand, the turn's own test_two gone too, and ids that do not show it: a file id still listed,
    # as vitest's and jest's are, 45 listed for 44 counted. What is missing cannot be told - the
    # turn's; read by the ids alone, only test_old.py's were missing: "not this turn's change")
    from tests.test_proof_before_scenarios import GREEN

    rows, _taken, _model = second_turn(
        make_client,
        wait_run,
        project_dir,
        CALC_TESTS.replace("def test_two", "def helper_two"),
        (44,),
        by_hand=lambda: (project_dir / "tests" / "test_old.py").unlink(),
        ids=[one for one in GREEN if "test_old" not in one],
        total=44,
    )
    assert ("Tests went from 48 to 44 (4 removed)", "failed") in rows, rows


# R, third look: the id paths that let a turn's own drop through (review probes r3).
def test_a_tests_data_file_the_turn_shortened_is_the_turns(make_client, wait_run, project_dir):
    # (tests/data/cases.json feeds test_more.py's parametrize: the missing id lives in an untouched
    # module - but a file of the tests folder that is no test module steers which tests run)
    from tests.test_proof_before_scenarios import GREEN

    (project_dir / "tests" / "data").mkdir(parents=True)
    (project_dir / "tests" / "data" / "cases.json").write_text("[1, 2, 3]\n", encoding="utf-8")
    now = [one for one in GREEN if one != "tests/test_more.py::test_7"]
    rows, taken, _m = second_turn(
        make_client, wait_run, project_dir, "[1, 2]\n", (47,), ids=now, path="tests/data/cases.json"
    )
    assert (DROP, "failed") in rows and not taken, rows


def test_a_test_file_renamed_by_hand_then_cut_by_the_turn_is_the_turns(
    make_client, wait_run, project_dir
):
    # (test_old.py renamed by hand to test_new.py, then the turn takes test_a out of it: the
    # missing ids are test_old.py's - untouched - but test_new.py, which it touched, had no test at
    # the green run: nothing to hold it to)
    from tests.test_proof_before_scenarios import GREEN

    def rename():
        three = "def test_a():\n    pass\n\ndef test_b():\n    pass\n\ndef test_c():\n    pass\n"
        (project_dir / "tests" / "test_new.py").write_text(three, encoding="utf-8")
        (project_dir / "tests" / "test_old.py").unlink()

    now = [one for one in GREEN if "test_old" not in one] + [
        "tests/test_new.py::test_b",
        "tests/test_new.py::test_c",
    ]
    rows, taken, _m = second_turn(
        make_client,
        wait_run,
        project_dir,
        "def test_b():\n    pass\n\ndef test_c():\n    pass\n",
        (47,),
        by_hand=rename,
        ids=now,
        path="tests/test_new.py",
    )
    assert (DROP, "failed") in rows and not taken, rows


@pytest.mark.skipif(sys.platform not in ("win32", "darwin"), reason="a disk that ignores case")
def test_a_test_files_path_in_another_case_is_the_same_file(make_client, wait_run, project_dir):
    from tests.test_proof_before_scenarios import GREEN

    now = [one for one in GREEN if one != "tests/test_calc.py::test_two"]
    rows, taken, _m = second_turn(
        make_client,
        wait_run,
        project_dir,
        "def test_one():\n    pass\n",
        (47,),
        ids=now,
        path="Tests/test_calc.py",
    )
    assert (DROP, "failed") in rows and not taken, rows


def test_a_test_another_module_deletes_is_the_turns(make_client, wait_run, project_dir):
    # (a touched test module that deletes another's test on import - the missing id lives in the
    # untouched one: it touched a test file, the drop is its own)
    from tests.test_proof_before_scenarios import GREEN

    edited = CALC_TESTS + "\nimport tests.test_more as _m\ndel _m.test_7\n"
    now = [one for one in GREEN if one != "tests/test_more.py::test_7"]
    rows, taken, _m = second_turn(make_client, wait_run, project_dir, edited, (47,), ids=now)
    assert (DROP, "failed") in rows and not taken, rows


def test_tests_moved_by_hand_into_a_file_the_turn_then_cuts_are_the_turns(
    make_client, wait_run, project_dir
):
    # (fourth look: by hand, test_old.py's test_a/b/c move INTO test_calc.py and test_old.py goes;
    # the turn then takes test_a out of test_calc.py: 48 -> 47. The missing ids are test_old.py's,
    # untouched, and test_calc.py had ids at the green run - by ids alone, outside. It touched a
    # test file: the turn's.)
    from tests.test_proof_before_scenarios import GREEN

    moved = CALC_TESTS + "".join(f"\n\ndef test_{n}():\n    pass\n" for n in "abc")

    def move():
        (project_dir / "tests" / "test_calc.py").write_text(moved, encoding="utf-8")
        (project_dir / "tests" / "test_old.py").unlink()

    now = [one for one in GREEN if "test_old" not in one] + [
        "tests/test_calc.py::test_b",
        "tests/test_calc.py::test_c",
    ]
    rows, taken, _m = second_turn(
        make_client,
        wait_run,
        project_dir,
        moved.replace("def test_a():\n    pass\n", ""),
        (47,),
        by_hand=move,
        ids=now,
    )
    assert (DROP, "failed") in rows and not taken, rows
