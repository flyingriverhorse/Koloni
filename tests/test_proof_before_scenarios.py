"""Kanıtlı bitiş S7 (plan decisions 14b, 19): a failing test that passes alone once is flaky (noted
in the project's memory, not sent back); one that fails on the code as it was before the turn too
was failing before (said, not sent back); a whole suite that passed is held to the project's last
green state; a bug fix's new test must fail on the old code. A fake model and a scripted executor."""

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app import copies, proof_before
from app.agent import before_mixin
from app.db.models import Memory
from tests import test_proof_ci_scenarios as ci_scenarios
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_writes import write
from tests.test_chat_flow import text
from tests.test_ci_commands import write as write_flow
from tests.test_proof_end_scenarios import PASS, begin, checked, run, texts

pytestmark = pytest.mark.no_po

PYTEST = "python -m pytest -q"
ONE = "tests/test_a.py::test_x"
TWO = "tests/test_b.py::test_y"


def failing(*ids):
    lines = "".join(f"FAILED {one} - assert 1 == 2\n" for one in ids)
    return Script([f"{lines}=== {len(ids)} failed, 3 passed in 0.1s ===\n"], exit_code=1)


def passing(n=4, skipped=0):
    return Script([f"{n} passed" + (f", {skipped} skipped" if skipped else "") + " in 0.1s\n"])


def rows_of(snap, run_id):
    return [
        r["text"]
        for m in snap["messages"]
        if m["role"] == "checked" and m["run_id"] == run_id
        for r in m["checked"]
    ]


def lines(executor):
    return [command for command, _cwd in executor.started]


def told(model, at):
    return json.dumps(model.calls[at], ensure_ascii=False)


def throwaways(client) -> list[Path]:
    where = copies.folder(client.app.state.runner.settings.runtime_root)
    return (
        [one for one in where.iterdir() if one.name.startswith("before-")]
        if where and (where.exists())
        else []
    )


def notes(client, test):
    with client.app.state.session_factory() as session:
        return session.scalars(
            select(Memory.text).where(
                Memory.about == f"flaky test: {test}", Memory.status == "active"
            )
        ).all()


def test_a_test_that_passes_alone_is_flaky_noted_and_not_sent_back(
    make_client, wait_run, project_dir
):
    executor = ScriptedExecutor([failing(ONE), passing(1)])
    client, model = make_client([write("a.py", "x = 1\n"), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    rows = texts(wait_run(client, cid, run_id))
    assert lines(executor) == [PYTEST, proof_before.alone(PYTEST, [ONE])]
    assert before_mixin.FLAKY.format(id=ONE) in rows, rows
    assert len(model.calls) == 2  # (nothing sent back)
    (said,) = notes(client, ONE)
    assert said.endswith("seen 1 times"), said


def test_a_flaky_note_counts_its_times(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([failing(ONE), passing(1), failing(ONE), passing(1)])
    client, _model = make_client(
        [write("a.py", "x = 1\n"), text("done"), write("a.py", "x = 2\n", "w2"), text("again")],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    wait_run(client, cid, run_id)
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "more"}).json()
    wait_run(client, cid, posted["run"]["id"])
    (said,) = notes(client, ONE)
    assert said.endswith("seen 2 times"), said


def test_failures_already_there_before_send_nothing_back(make_client, wait_run, project_dir):
    (project_dir / ".venv").mkdir()
    (project_dir / ".venv" / "kept.txt").write_text("the project's own\n", encoding="utf-8")
    executor = ScriptedExecutor([failing(ONE), failing(ONE), failing(ONE)])
    client, model = make_client([write("a.py", "x = 1\n"), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    rows = texts(wait_run(client, cid, run_id))
    assert before_mixin.BEFORE.format(n=1, m=0) in rows, rows
    assert len(model.calls) == 2  # (nothing sent back: not this turn's)
    # (The old code's run was in a throwaway copy - gone after; the project and its linked
    # .venv untouched.)
    assert executor.started[2][1] != str(project_dir)
    assert throwaways(client) == []
    assert (project_dir / ".venv" / "kept.txt").read_text(encoding="utf-8") == "the project's own\n"
    assert (project_dir / "a.py").read_text(encoding="utf-8") == "x = 1\n"


def test_a_new_failure_beside_an_old_one_names_only_the_new(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([failing(ONE, TWO), failing(ONE, TWO), failing(ONE), passing()])
    client, model = make_client(
        [write("a.py", "x = 1\n"), text("done"), write("a.py", "x = 2\n", "w2"), text("fixed")],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    rows = texts(wait_run(client, cid, run_id))
    assert before_mixin.BEFORE.format(n=1, m=1) in rows, rows
    nudge = told(model, 2)
    assert before_mixin.NOT_YOURS.format(ids=ONE).strip() in nudge


def test_last_turns_failures_fixed_now_are_said(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([failing(ONE), failing(ONE), failing(ONE), passing()])
    client, _model = make_client(
        [write("a.py", "x = 1\n"), text("done"), write("a.py", "x = 2\n", "w2"), text("fixed")],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    wait_run(client, cid, run_id)
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "fix it"}).json()
    rows = rows_of(wait_run(client, cid, posted["run"]["id"]), posted["run"]["id"])
    assert any(one.startswith("1 were failing at the last run (") for one in rows), rows


@pytest.mark.parametrize(
    ("old", "said", "state"),
    [
        (failing("tests/test_bug.py::test_calc"), before_mixin.CAUGHT, "passed"),
        (passing(1), before_mixin.NOT_CAUGHT, "failed"),
    ],
)
def test_a_bugfix_test_on_the_old_code(make_client, wait_run, project_dir, old, said, state):
    # (its related tests first, S6: the new test's file - then the whole suite, then the old code)
    executor = ScriptedExecutor([passing(1), passing(), old])
    client, _model = make_client(
        [
            write("calc.py", "x = 1\n"),
            write("tests/test_bug.py", "def test_calc(): pass\n", "w2"),
            text("fixed"),
        ],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, check_command=PYTEST, content="fix the crash in calc")
    rows = checked(wait_run(client, cid, run_id))
    assert (said, state) in [(r["text"], r["state"]) for r in rows], rows
    assert executor.started[2][0] == proof_before.alone(PYTEST, ["tests/test_bug.py"])
    assert executor.started[2][1] != str(project_dir) and throwaways(client) == []


def test_a_command_that_changed_the_project_means_no_before_run(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([PASS, failing(ONE), failing(ONE), passing()])
    client, _model = make_client(
        [
            write("a.py", "x = 1\n"),
            run("python gen.py"),
            text("done"),
            write("a.py", "x = 2\n", "w2"),
            text("fixed"),
        ],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    rows = texts(wait_run(client, cid, run_id))
    assert before_mixin.NO_BEFORE.format(why=before_mixin.CHANGED_BY_COMMAND) in rows, rows
    assert len(executor.started) == 4  # (the agent's, the suite, alone, the suite again: no old)


def test_the_last_green_state_holds_a_drop_in_tests_and_a_rise_in_skipped(
    make_client, wait_run, project_dir
):
    executor = ScriptedExecutor([passing(4), passing(3, skipped=2)])
    client, model = make_client(
        [
            write("a.py", "x = 1\n"),
            text("done"),
            write("a.py", "x = 2\n", "w2"),
            text("done"),
            text("I left it so"),
        ],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    wait_run(client, cid, run_id)
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "more"}).json()
    rows = rows_of(wait_run(client, cid, posted["run"]["id"]), posted["run"]["id"])
    assert "Tests went from 4 to 3 (1 removed)" in rows and "Skipped rose from 0 to 2" in rows
    assert "Tests went from 4 to 3 (1 removed)" in told(model, 4)


def green_ran(client):
    with client.app.state.session_factory() as session:
        from app.db.models import Project

        (green,) = session.scalars(select(Project.tests_green)).all()
    return next(iter(green.values()))["ran"]


def test_a_drop_the_answer_says_why_is_the_new_green_state(make_client, wait_run, project_dir):
    executor = ScriptedExecutor([passing(4), passing(3)])
    client, model = make_client(
        [
            write("a.py", "x = 1\n"),
            text("done"),
            write("a.py", "x = 2\n", "w2"),
            text("I removed the obsolete test of the old parser"),
        ],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    wait_run(client, cid, run_id)
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "more"}).json()
    snap = wait_run(client, cid, posted["run"]["id"])
    rows = [
        (r["text"], r["state"])
        for m in snap["messages"]
        if m["role"] == "checked" and m["run_id"] == posted["run"]["id"]
        for r in m["checked"]
    ]
    # (excused, still shown: a note quoting the answer - review of S7 - and nothing sent back)
    assert (
        before_mixin.EXCUSED.format(
            said="Tests went from 4 to 3 (1 removed)",
            why="I removed the obsolete test of the old parser",
        ),
        "note",
    ) in rows, rows
    assert not any(state == "failed" for _text, state in rows), rows
    assert len(model.calls) == 4 and green_ran(client) == 3


def test_an_excuse_that_names_no_test_hides_nothing(make_client, wait_run, project_dir):
    # (Review of S7's probe: 4 green, then 1 passed and 3 skipped - "Removed a stray debug
    # print." is no reason for either: both said, sent back, the green state kept.)
    executor = ScriptedExecutor([passing(4), passing(1, skipped=3), passing(1, skipped=3)])
    client, model = make_client(
        [
            write("a.py", "x = 1\n"),
            text("done"),
            write("a.py", "x = 2\n", "w2"),
            text("Removed a stray debug print."),
            text("left as it is"),
        ],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, check_command=PYTEST, fix_rounds=1)
    wait_run(client, cid, run_id)
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "more"}).json()
    rows = rows_of(wait_run(client, cid, posted["run"]["id"]), posted["run"]["id"])
    assert "Tests went from 4 to 1 (3 removed)" in rows and "Skipped rose from 0 to 3" in rows, rows
    assert "in a sentence that names the tests" in told(model, 4)
    assert green_ran(client) == 4


def test_a_rise_in_skipped_needs_skip_named(make_client, wait_run, project_dir):
    # (One removed and one skipped: the answer says why the one went - not why one is skipped.)
    executor = ScriptedExecutor([passing(4), passing(3, skipped=1), passing(3, skipped=1)])
    client, model = make_client(
        [
            write("a.py", "x = 1\n"),
            text("done"),
            write("a.py", "x = 2\n", "w2"),
            text("I removed the obsolete test of the old parser"),
            text("left as it is"),
        ],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, check_command=PYTEST, fix_rounds=1)
    wait_run(client, cid, run_id)
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "more"}).json()
    rows = rows_of(wait_run(client, cid, posted["run"]["id"]), posted["run"]["id"])
    assert "Skipped rose from 0 to 1" in rows, rows
    assert "Skipped rose from 0 to 1" in told(model, 4)


def test_a_test_that_passed_at_the_last_green_run_and_fails_now_is_a_regression(
    make_client, wait_run, project_dir
):
    executor = ScriptedExecutor([passing(4), failing(ONE), failing(ONE), passing(4), passing(4)])
    client, model = make_client(
        [
            write("a.py", "x = 1\n"),
            text("done"),
            write("a.py", "x = 2\n", "w2"),
            text("done"),
            write("a.py", "x = 3\n", "w3"),
            text("fixed"),
        ],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    wait_run(client, cid, run_id)
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "more"}).json()
    snap = wait_run(client, cid, posted["run"]["id"])
    second = [
        r["text"]
        for m in snap["messages"]
        if m["role"] == "checked" and m["run_id"] == posted["run"]["id"]
        for r in m["checked"]
    ]
    assert before_mixin.REGRESSION.format(id=ONE, by=" (by file)") in second or (
        "Tests passed" in " ".join(second)
    )
    assert "FAILED" in told(model, 4)  # (sent back: new on the old code, so this turn's)


def test_only_a_test_that_passed_at_the_green_run_is_a_regression(
    make_client, wait_run, project_dir
):
    green = Script(
        [
            "tests/test_a.py::test_x PASSED\ntests/test_a.py::test_y PASSED\n"
            "=== 2 passed in 0.1s ===\n"
        ]
    )
    z = "tests/test_a.py::test_z"
    # (one fix round: the second pass fails too, so the turn ends on its rows)
    executor = ScriptedExecutor([green, *[failing(ONE, z), failing(ONE, z), passing()] * 2])
    client, _model = make_client(
        [
            write("a.py", "x = 1\n"),
            text("done"),
            write("a.py", "x = 2\n", "w2"),
            text("done"),
            write("a.py", "x = 3\n", "w3"),
            text("fixed"),
        ],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, check_command=PYTEST, fix_rounds=1)
    wait_run(client, cid, run_id)
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "more"}).json()
    rows = rows_of(wait_run(client, cid, posted["run"]["id"]), posted["run"]["id"])
    # (z came after the green run: no regression; x passed then: named, by its id)
    assert [one for one in rows if one.startswith("Regression")] == [
        before_mixin.REGRESSION.format(id=ONE, by="")
    ], rows


def test_the_throwaway_copy_is_gone_after_stop_and_the_project_untouched(
    make_client, project_dir, gate
):
    import time

    from tests.conftest import scaled
    from tests.test_proof_end_scenarios import OWN

    (project_dir / ".venv").mkdir()
    (project_dir / ".venv" / "kept.txt").write_text("the project's own\n", encoding="utf-8")
    old = Script(["running\n"], hold=gate)
    executor = ScriptedExecutor([failing(ONE), failing(ONE), old])
    client, _model = make_client([write("a.py", "x = 1\n"), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    deadline = time.monotonic() + scaled(10)
    while len(executor.started) < 3:
        assert time.monotonic() < deadline, executor.started
        time.sleep(0.05)
    assert throwaways(client)  # (there, while its run runs)
    assert client.post(f"/api/runs/{run_id}/cancel", headers=OWN).status_code == 202
    while client.get(f"/api/conversations/{cid}").json()["runs"][0]["status"] == "running":
        assert time.monotonic() < deadline + scaled(10)
        time.sleep(0.05)
    deadline = time.monotonic() + scaled(10)
    while throwaways(client):
        assert time.monotonic() < deadline, throwaways(client)
        time.sleep(0.05)
    assert (project_dir / ".venv" / "kept.txt").read_text(encoding="utf-8") == "the project's own\n"
    assert (project_dir / "a.py").read_text(encoding="utf-8") == "x = 1\n"


def test_at_ask_with_a_guess_no_second_card_is_raised(
    make_client, wait_run, project_dir, monkeypatch
):
    from tests.test_agent_writes import wait_status
    from tests.test_proof_end_scenarios import OWN, guess

    guess(monkeypatch, PYTEST)
    executor = ScriptedExecutor([failing(ONE), passing()])
    client, _model = make_client(
        [write("a.py", "x = 1\n"), text("done"), write("a.py", "x = 2\n", "w2"), text("fixed")],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, mode="auto_edit")
    snap = wait_status(client, cid, "waiting_approval")
    (asked,) = [c for c in snap["commands"] if c["status"] == "proposed"]
    assert (
        client.post(
            f"/api/commands/{asked['id']}/approve", json={"remember": False}, headers=OWN
        ).status_code
        == 200
    )
    snap = wait_run(client, cid, run_id)
    assert lines(executor) == [PYTEST, PYTEST]  # (no run alone, none on the old code)
    assert before_mixin.NO_BEFORE.format(why=before_mixin.ASKS_AGAIN) in texts(snap)
    assert len([c for c in snap["commands"] if c["status"] in ("proposed", "rejected")]) == 0


@pytest.mark.parametrize(
    ("answer", "said"), [("done", True), ("I removed the obsolete test of the old parser", False)]
)
def test_a_removed_test_file_is_said_unless_the_answer_says_why(
    make_client, wait_run, project_dir, answer, said
):
    executor = ScriptedExecutor([passing(4), PASS, passing(3)])
    client, model = make_client(
        [
            write("a.py", "x = 1\n"),
            text("done"),
            run("git rm tests/test_old.py"),
            write("a.py", "x = 2\n", "w2"),
            text(answer),
            text("left as it is"),
        ],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    wait_run(client, cid, run_id)
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "more"}).json()
    rows = rows_of(wait_run(client, cid, posted["run"]["id"]), posted["run"]["id"])
    assert ("Tests went from 4 to 3 (1 removed)" in rows) is said, rows
    assert (
        before_mixin.EXCUSED.format(said="Tests went from 4 to 3 (1 removed)", why=answer) in rows
    ) is not said, rows


def test_an_unusual_test_name_a_run_printed_is_never_run_again(make_client, wait_run, project_dir):
    # (Review of S7's probe: the ids are what the run PRINTED - `$(...)` in a line run unasked
    # ran in PowerShell's double quotes; `--co` made the run alone a collect-only one.)
    crafted = "tests/test_a.py::t$(whoami)"
    executor = ScriptedExecutor(
        [
            Script(
                [f"FAILED {crafted} - boom\nFAILED --co\n=== 2 failed, 3 passed in 0.1s ===\n"],
                exit_code=1,
            ),
            passing(),
        ]
    )
    client, model = make_client(
        [write("a.py", "x = 1\n"), text("done"), write("a.py", "x = 2\n", "w2"), text("fixed")],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    snap = wait_run(client, cid, run_id)
    assert lines(executor) == [PYTEST, PYTEST], lines(executor)  # (no run alone, none on old code)
    assert before_mixin.UNUSUAL.format(ids=f"{crafted}, --co") in texts(snap), texts(snap)
    assert "FAILED" in told(model, 2)  # (sent back: not known to be anyone else's)
    assert notes(client, crafted) == [] and throwaways(client) == []


def test_a_run_alone_that_ran_no_tests_is_no_verdict(make_client, wait_run, project_dir):
    # (Collected only, exit 0: no test passed alone - never flaky; on to the old code, where it
    # passes: this turn's, sent back.)
    executor = ScriptedExecutor(
        [failing(ONE), Script([f"{ONE}\n\n1 test collected in 0.01s\n"]), passing(1), passing()]
    )
    client, model = make_client(
        [write("a.py", "x = 1\n"), text("done"), write("a.py", "x = 2\n", "w2"), text("fixed")],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    rows = texts(wait_run(client, cid, run_id))
    assert before_mixin.FLAKY.format(id=ONE) not in rows and notes(client, ONE) == [], rows
    assert executor.started[2][1] != str(project_dir)  # (the old code's run)
    assert "FAILED" in told(model, 2)


def test_the_old_code_in_the_throwaway_copy_is_its_bytes(make_client, wait_run, project_dir, gate):
    # (Review of S7's probe: written back as text, CRLF became CR CR LF on Windows - a
    # SyntaxError on the "old code" - and LF became CRLF.)
    import time

    from tests.conftest import scaled

    old = {
        "crlf.py": b'x = 1 + \\\r\n    2\r\nS = """a\r\nb"""\r\n',
        "lf.py": b'x = 1 + \\\n    2\nS = """a\nb"""\n',
    }
    for name, data in old.items():
        (project_dir / name).write_bytes(data)
    executor = ScriptedExecutor(
        [failing(ONE), failing(ONE), Script(["running\n"], hold=gate), passing()]
    )
    client, _model = make_client(
        [
            write("crlf.py", "x = 3\r\n"),
            write("lf.py", "x = 3\n", "w2"),
            text("done"),
            text("left as it is"),
        ],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    deadline = time.monotonic() + scaled(10)
    while len(executor.started) < 3:
        assert time.monotonic() < deadline, executor.started
        time.sleep(0.05)
    there = Path(executor.started[2][1])
    held = {name: (there / name).read_bytes() for name in old}
    gate.release()
    wait_run(client, cid, run_id)
    assert held == old
    for data in held.values():
        compile(data, "m.py", "exec")


def test_a_bugfix_test_with_an_unusual_name_is_not_run_on_the_old_code(
    make_client, wait_run, project_dir
):
    executor = ScriptedExecutor([passing(), passing()])
    client, _model = make_client(
        [
            write("calc.py", "x = 1\n"),
            write("tests/test_bug$(whoami).py", "def test_calc(): pass\n", "w2"),
            text("fixed"),
        ],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, check_command=PYTEST, content="fix the crash in calc")
    rows = texts(wait_run(client, cid, run_id))
    assert before_mixin.UNUSUAL.format(ids="tests/test_bug$(whoami).py") in rows, rows
    assert not any("$(" in one for one in lines(executor)), lines(executor)
    assert before_mixin.CAUGHT not in rows and before_mixin.NOT_CAUGHT not in rows


def test_the_green_state_keeps_the_passes_of_a_run_with_coverage_flags(
    make_client, wait_run, project_dir
):
    # (S7 with S9: KOLONİ's line has coverage's report flags - its passes are still its command's)
    from app.db.models import Project
    from tests.test_coverage_scenarios import Measuring, with_cov

    with_cov(project_dir)
    green = Script(
        [
            "tests/test_a.py::test_x PASSED\ntests/test_a.py::test_y PASSED\n"
            "=== 2 passed in 0.1s ===\n"
        ]
    )
    executor = Measuring([green], {"a.py": ([1], [])})
    client, _model = make_client([write("a.py", "x = 1\n"), text("done")], executor=executor)
    cid, run_id = begin(client, project_dir, check_command=PYTEST)
    wait_run(client, cid, run_id)
    assert "--cov" in executor.started[0][0], executor.started
    with client.app.state.session_factory() as session:
        (kept,) = session.scalars(select(Project.tests_green)).all()
    assert next(iter(kept.values()))["ids"] == [ONE, "tests/test_a.py::test_y"], kept


FORMAT = ci_scenarios.FLOW.replace("ruff check app", "ruff format --check .")
REFORMAT = "Would reformat: {file}\n1 file would be reformatted, 1 file already formatted\n"


def reformat(file):
    return Script([REFORMAT.format(file=file)], exit_code=1)


@pytest.mark.parametrize(
    "case",
    [
        "old file",
        "the turn's file",
        "the turn's nested file",
        "not on the old code",
        "no file named",
    ],
)
def test_a_ci_check_failing_only_where_the_turn_did_not_change_is_no_round(
    make_client, wait_run, project_dir, case
):
    # (CL-336 M: `ruff format --check .` failing on an old unformatted file the turn never
    # touched went to a fix round, then to the stronger model. It was failing before: said, not
    # sent back - but only where each finding is there on the old code too; one in the turn's
    # file, one the old code has not (a type error the turn caused), or none named: the turn's)
    write_flow(project_dir, FORMAT)
    (project_dir / "old.py").write_text("y   =  1\n", encoding="utf-8")
    mine = "pkg/a.py" if case == "the turn's nested file" else "a.py"
    now = {
        "old file": reformat("old.py"),
        "the turn's file": reformat("a.py"),
        "the turn's nested file": reformat("pkg/a.py"),
        "not on the old code": reformat("old.py"),
        "no file named": Script(["error: Failed to parse pyproject.toml\n"], exit_code=2),
    }[case]
    then = {"old file": [reformat("old.py")], "not on the old code": [Script(["ok\n"])]}
    executor = ScriptedExecutor([now, PASS, *then.get(case, []), Script(["ok\n"]), PASS])
    client, model = make_client(
        [
            write(mine, "x = 1\n"),
            text("done"),
            write(mine, "x = 2\n", "w2"),
            text("done"),
            write(mine, "x = 3\n", "w3"),
            text("fixed"),
        ],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir)
    ci_scenarios.approve(client, wait_run(client, cid, run_id), run_id)
    second, snap = ci_scenarios.again(client, wait_run, cid)
    rows = ci_scenarios.rows_of(snap, second)
    note = (
        "before",
        before_mixin.LINT_BEFORE.format(files="old.py", command="from CI: ruff format --check ."),
    )
    if case == "old file":
        assert note in rows and len(model.calls) == 4, rows  # (no round: nothing sent back)
        assert [one for one, _cwd in executor.started] == [
            "ruff format --check .",
            "python -m pytest -q",
            "ruff format --check .",
        ]
        assert executor.started[2][1] != str(project_dir)  # (on the old code: a copy)
    else:
        assert note not in rows and len(model.calls) == 6, rows  # (one round)
