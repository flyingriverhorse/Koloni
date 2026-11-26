"""Full auto's judge, 0.1.10 (as Claude Code's auto mode): where it asks you - each command it would
look at with no model to ask (it fails closed), and the rest of a turn's risky ones after 3 refusals
in a row or 20 in all - and where an "Always run" rule lets a line by unjudged: a narrow one, never a
broad one, nor one that runs a program an agent wrote."""

import pytest

from app import risk_judge
from app.agent.risk_judge_mixin import NO_MODEL, NOT_ASKED_LINE
from app.db.models import AllowedCommand
from tests.fakes import Script, ScriptedExecutor
from tests.keyed import OWN
from tests.test_agent_commands import cmd
from tests.test_agent_writes import write
from tests.test_chat_flow import text
from tests.test_full_auto_judge import (  # noqa: F401  (an autouse fixture)
    CAPPED,
    _no_python_path,
    card,
    go,
    koloni_lines,
    said,
)
from tests.test_judge_scenarios import judging  # noqa: F401  (a fixture)

pytestmark = [pytest.mark.judge, pytest.mark.no_po]


@pytest.mark.parametrize("mode", ["full_auto", "auto_edit"])
def test_with_no_model_to_ask_each_command_is_a_card_said_once(
    make_client, wait_run, project_dir, mode
):
    # (0.1.10, fails closed: it stood aside for the turn and the commands ran unasked - as Claude
    # Code's auto mode, a command no model could judge waits for you; below Full auto nothing of it)
    executor = ScriptedExecutor([])
    client, _model = make_client(
        [cmd("python a.py", id="k1"), cmd("python b.py", id="k2"), text("left")], executor=executor
    )
    _, cid, run_id = go(client, project_dir, mode=mode)
    whys = [card(client, cid)["danger"] for _ in range(2)]
    wait_run(client, cid, run_id)
    assert executor.started == []
    if mode == "auto_edit":
        assert not [one for one in whys if one and "judge" in one], whys
        assert koloni_lines(client, cid) == []
        return
    assert whys == [f"KOLONİ's judge: it could not be asked: {NO_MODEL}"] * 2
    assert koloni_lines(client, cid) == [NOT_ASKED_LINE.format(why=NO_MODEL)]


MAILS = said("risky", "It mails the logs.")


def test_a_command_that_ran_ends_a_row_of_refusals(judging, wait_run, project_dir):
    # (0.1.10: 3 in a row, as Claude Code's auto mode - the fourth risky one in a turn was a card,
    # however far apart the refusals; a command that runs ends a row)
    client, _lead, _judge, executor = judging(
        [
            cmd("python v1.py", id="k1"),
            cmd("python ok.py", id="k2"),
            *(cmd(f"python v{n}.py", id=f"k{n + 1}") for n in (2, 3, 4, 5)),
            text("left it"),
        ],
        [MAILS, said("fine"), *[MAILS] * 4],
        [Script([])],
    )
    _, cid, run_id = go(client, project_dir)
    asked = card(client, cid)
    snap = wait_run(client, cid, run_id)
    statuses = [one["status"] for one in snap["commands"]]
    assert statuses == ["refused", "exited", "refused", "refused", "refused", "rejected"], statuses
    assert asked["command"] == "python v5.py"
    assert koloni_lines(client, cid) == [CAPPED]
    assert [one[0] for one in executor.started] == ["python ok.py"]


def test_twenty_refusals_in_a_turn_ask_however_far_apart(
    judging, wait_run, project_dir, monkeypatch
):
    # (review of K1: refuse, run something, refuse... never reaches 3 in a row - 20 in all do,
    # here 3)
    monkeypatch.setattr(risk_judge, "MOST_REFUSED_IN_A_TURN", 3)
    client, _lead, _judge, executor = judging(
        [
            cmd("python v1.py", id="k1"),
            cmd("python ok1.py", id="k2"),
            cmd("python v2.py", id="k3"),
            cmd("python ok2.py", id="k4"),
            cmd("python v3.py", id="k5"),
            cmd("python v4.py", id="k6"),
            text("left it"),
        ],
        [MAILS, said("fine"), MAILS, said("fine"), MAILS, MAILS],
        [Script([])] * 2,
    )
    _, cid, run_id = go(client, project_dir)
    asked = card(client, cid)
    snap = wait_run(client, cid, run_id)
    assert asked["command"] == "python v4.py"
    assert [one["status"] for one in snap["commands"]].count("refused") == 3
    assert koloni_lines(client, cid) == [
        "Full auto's judge refused 3 commands this turn; each risky one asks you now."
    ]
    assert len(executor.started) == 2


def rule(client, pid, cid, prefix):
    """An "Always run" rule of the chat's, as one kept from a card or written by hand."""
    with client.app.state.session_factory() as session:
        session.add(AllowedCommand(conversation_id=cid, project_id=pid, prefix=prefix))
        session.commit()


def again(client, cid):
    """The chat's next turn: its run's id."""
    sent = client.post(f"/api/conversations/{cid}/messages", json={"content": "go on"}, headers=OWN)
    return sent.json()["run"]["id"]


@pytest.mark.parametrize(
    ("line", "broad"),
    [
        ("make build", False),
        ("make", True),
        ("npm install", True),
        ("docker run myimg", True),
        ("git remote -v", True),
    ],
)
def test_a_broad_rule_does_not_go_round_the_judge_a_narrow_one_does(
    judging, wait_run, project_dir, line, broad
):
    # (0.1.10, decision 6 - as Claude Code's auto mode: `make build` names its task and lets its
    # very line by unjudged; `make` names none, and `npm install`, `docker run`, `git remote` take
    # whatever they are handed - offered on a card, they cover anything. With the broad check
    # stubbed out, each went round the judge.)
    client, _lead, judge, executor = judging(
        [text("ok"), cmd(line), text("left it")], [said("risky", "Not asked for.")], [Script([])]
    )
    (project_dir / "Makefile").write_text("build:\n\techo hi\n", encoding="utf-8")
    pid, cid, first = go(client, project_dir, risky="ask")
    wait_run(client, cid, first)
    rule(client, pid, cid, line)
    run_id = again(client, cid)
    if not broad:
        (ran,) = wait_run(client, cid, run_id)["commands"]
        assert ran["status"] == "exited" and ran["judged"] is None and judge.calls == []
        assert executor.started[0][0] == line
        return
    asked = card(client, cid)
    wait_run(client, cid, run_id)
    assert asked["danger"] == "KOLONİ's judge: Not asked for." and len(judge.calls) == 1


@pytest.mark.parametrize(
    ("narrow", "line", "pre", "cwd"),
    [
        # (one word past the rule: a file its program is told to load, a variable, another task)
        ("npm test", "npm test -- --config=lib/v.js", ("lib/v.js", "// AGENTS-7731\n"), "."),
        ("npm test", "npm test -- --require ./lib/v.js", ("lib/v.js", "// AGENTS-7731\n"), "."),
        ("make build", "make build --eval=SHELL=./x.sh", ("x.sh", "echo AGENTS-7731\n"), "."),
        ("make build", "make build CC=./x.sh", ("x.sh", "echo AGENTS-7731\n"), "."),
        ("python manage.py", "python manage.py shell -c AGENTS7731", None, "."),
        # (a tool's run that builds the folder's code: no one file of it is looked at)
        ("cargo run", "cargo run", ("src/main.rs", "fn main() { /* AGENTS-7731 */ }\n"), "."),
        # (the same words in another folder run another file)
        ("python gen.py", "python gen.py", None, "sub"),
    ],
)
def test_a_narrow_rule_lets_only_its_very_line_by_at_the_root(
    judging, wait_run, project_dir, narrow, line, pre, cwd
):
    # (the review of K1: each of these ran with no judge under a narrow rule)
    steps = [text("ok"), *([write(*pre)] if pre else []), cmd(line, cwd=cwd), text("left it")]
    client, _lead, judge, executor = judging(steps, [said("risky", "Not asked for.")], [Script([])])
    (project_dir / "Makefile").write_text("build:\n\techo hi\n", encoding="utf-8")
    (project_dir / "package.json").write_text('{"scripts": {"test": "vitest"}}\n', "utf-8")
    for one in ("manage.py", "gen.py", "sub/gen.py"):
        (project_dir / one).parent.mkdir(exist_ok=True)
        (project_dir / one).write_text("print('mine')\n", encoding="utf-8")
    pid, cid, first = go(client, project_dir, risky="ask")
    wait_run(client, cid, first)
    rule(client, pid, cid, narrow)
    run_id = again(client, cid)
    asked = card(client, cid)
    wait_run(client, cid, run_id)
    assert asked["command"] == line and len(judge.calls) == 1, (asked, judge.calls)
    # (KOLONİ's own check of the turn's write may run the project's tests: not the line)
    assert line not in [one[0] for one in executor.started], executor.started


def test_a_to_do_tasks_turn_gets_no_rule_past_the_judge(judging, wait_run, project_dir):
    # (the review of K1: a To-do task's turn may run with nobody there - as a job while away)
    from tests.test_todo_chat import do_in_chat, ended

    client, _lead, judge, executor = judging(
        [text("ok"), cmd("make build"), text("task done")], [said("risky", "Not asked for.")], []
    )
    (project_dir / "Makefile").write_text("build:\n\techo hi\n", encoding="utf-8")
    pid, cid, first = go(client, project_dir, risky="ask")
    wait_run(client, cid, first)
    rule(client, pid, cid, "make build")
    task = client.post(f"/api/projects/{pid}/backlog", json={"title": "build"}, headers=OWN)
    client.headers.update(OWN)
    assert do_in_chat(client, pid, [task.json()["id"]], cid).status_code == 200
    asked = card(client, cid)
    ended(client, cid, 2)
    assert asked["command"] == "make build" and asked["danger"] == "KOLONİ's judge: Not asked for."
    assert executor.started == []


@pytest.mark.parametrize("line", ["python gen.py", "uv run python gen.py"])
def test_a_narrow_rule_does_not_go_round_the_judge_for_a_program_an_agent_wrote(
    judging, wait_run, project_dir, line
):
    # (no rule covers what an agent wrote - W2: the judge reads it; a runner's line whose file
    # KOLONİ does not find - `uv run python x.py` - is judged too, what it runs not known)
    client, _lead, judge, _executor = judging(
        [
            text("ok"),
            write("gen.py", "print('AGENTS-7731')\n"),
            cmd(line),
            text("done"),
        ],
        [said("fine")],
        [Script([])],
    )
    (project_dir / "gen.py").write_text("print('mine')\n", encoding="utf-8")
    pid, cid, first = go(client, project_dir)
    wait_run(client, cid, first)
    rule(client, pid, cid, line)
    run_id = again(client, cid)
    (ran,) = wait_run(client, cid, run_id)["commands"]
    assert ran["status"] == "exited" and len(judge.calls) == 1
    assert "AGENTS-7731" in judge.calls[0][0]["content"]
