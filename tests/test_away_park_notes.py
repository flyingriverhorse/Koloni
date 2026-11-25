"""☾ Away, park and continue: what the second session met live (F411). The morning list warns of a
file an agent wrote that any part of a line runs - chained, wrapped, grouped, or a line it cannot
read whole; the secrets held back from the lines that ran are said once in the going-on message,
not in each line's result."""

import pytest

from app import parked
from app.agent.risk_judge_mixin import MOST_PARTS, named_files
from tests.test_agent_writes import write
from tests.test_away_going_on import going_on_turn, morning
from tests.test_away_park import run
from tests.test_away_waiting import decide, waiting
from tests.test_chat_flow import text
from tests.test_spawn import spawn


def test_the_secrets_held_back_are_said_once_not_in_each_result(
    make_client, wait_run, project_dir, monkeypatch
):  # P4
    monkeypatch.setenv("PARK_NOTES_TOKEN", "a-value-never-said")
    client, _pid, done, cid = morning(
        make_client,
        wait_run,
        project_dir,
        [run("echo first"), run("echo second", "c2"), text("one done"), text("went on")],
    )
    rows = waiting(client, done["id"])
    for row in rows:
        assert decide(client, done["id"], row["id"], "run").status_code == 200
    said, _going = going_on_turn(client, cid)
    assert said.count("held back") == 1, said
    # (KOLONİ's own sentence, after the decisions - not in a line's quoted output)
    assert "PARK_NOTES_TOKEN" in said.split("Go on with the task.")[-1]
    assert said.endswith(
        " - the user can pass one in Settings › This project › Commands and secrets)"
    )
    results = [row["result"] for row in waiting(client, done["id"])]
    assert all(result and "held back" not in result for result in results), results


FORMS = [
    "python hello.py && python q096.py",  # (a chain)
    "python hello.py; python q096.py",
    "type hello.py | python q096.py",  # (a pipe)
    'cmd /c "python q096.py"',  # (a shell handed it)
    'bash -c "python q096.py"',
    'pwsh -c "python q096.py"',
    "(python q096.py)",  # (a subshell, a group)
    "cd tools && python q096.py",  # (in the folder a cd of it goes to)
]


@pytest.mark.parametrize("line", FORMS)
def test_every_file_a_chained_wrapped_or_grouped_line_runs_is_found(tmp_path, line):  # P1
    for name in ("hello.py", "q096.py", "tools/q096.py"):
        (tmp_path / name).parent.mkdir(exist_ok=True)
        (tmp_path / name).write_text("print(1)\n")
    found = [
        path.relative_to(tmp_path.resolve()).as_posix() for path in named_files(tmp_path, line, ".")
    ]
    assert found[-1] in ("q096.py", "tools/q096.py"), found


# L-1: what runs code no word of the line names as a file - stdin to a shell, an expression, a
# package runner, find's -exec, a test runner (the tests an agent wrote)
UNNAMED = [
    "sh < evil.sh",
    "cat evil.sh | sh",
    "iex (gc evil.ps1 -Raw)",
    "Invoke-Expression (Get-Content evil.ps1 -Raw)",
    "npx tsx evil.ts",
    "find . -name x -exec ./evil.sh {} ;",
    "pytest",
    "python -m pytest -q",
    "npm test",
    "vitest run",
    'python -c "import evil"',
]


@pytest.mark.parametrize(
    "line",
    [
        "cd $HOME && python q.py",
        "(python q.py",
        " && ".join(["echo a"] * (MOST_PARTS + 1)),
        *UNNAMED,
    ],
)
def test_a_line_not_read_whole_is_none(tmp_path, line):  # P1: fails closed - the list warns
    assert named_files(tmp_path, line, ".") is None


@pytest.mark.parametrize(
    ("line", "warned"),
    [
        ("python hello.py && python q096.py", "q096.py"),  # (hello.py is the user's own)
        ('cmd /c "python q096.py"', "q096.py"),
        ("python hello.py && echo done", None),
        ("cd $X && python q096.py", parked.UNREAD_FILES),
    ],
)
def test_the_morning_list_warns_of_any_file_an_agent_wrote_that_the_line_runs(
    make_client, wait_run, project_dir, line, warned
):  # P1, live: `python hello.py && python q096.py` ran with no warning
    client, _pid, done, _cid = morning(
        make_client,
        wait_run,
        project_dir,
        [
            spawn("Coder", "write it"),
            write("q096.py", "print('q')\n"),
            text("written"),
            run(line),
            text("one done"),
        ],
        mode="auto_edit",
    )
    (row,) = waiting(client, done["id"])
    assert row["wrote"] == warned
