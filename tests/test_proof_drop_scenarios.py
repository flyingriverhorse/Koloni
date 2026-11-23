"""R, second round (the review's probes, the main session's rule): a drop against the project's last
green run - fewer tests run, more skipped - is "not this turn's change" only where that is shown;
anything the turn may have done is its own, as before R: a command that may write (in a recipe's
copy too, `git rm && git commit`, `git mv`), a test file edited with a skip or an xfail, a removal
of another turn's whose suite ended after its answer. A fake model and a scripted executor."""

import subprocess
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
