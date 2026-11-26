"""Cards measured (0.1.7): a command card records why it was asked, as the gate saw it
(`commands.asked_reason`), and when the user answered it from the app's own page (`decided_at`);
and which line of the user's words names a delete's target (`cards.mentioned`, for Check what I
said first). (0.1.10: Usage's Cards, its counts and the rules it suggested, are cut.)"""

import json
from datetime import timedelta

import pytest
from alembic import command as alembic

from app import cards, judge
from app.db.models import Agent, Command, Conversation, Project, Run, ToolCall, now
from app.db.session import make_engine, make_session_factory, upgrade_db
from tests.fakes import ScriptedExecutor
from tests.test_agent_commands import cmd
from tests.test_agent_writes import wait_status
from tests.test_chat_flow import start, start_in_mode, text
from tests.test_migration_0002 import _config


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "cards.db"
    upgrade_db(path)
    engine = make_engine(path)
    yield make_session_factory(engine)
    engine.dispose()


def turn(session, rid="r", cid="c", pid="p", rules=None) -> str:
    """A turn on record in project `pid` (made where it is not), and its lead's id."""
    if session.get(Project, pid) is None:
        session.add(Project(id=pid, name=pid, root_path=f"C:/{pid}", rules=rules))
    if session.get(Conversation, cid) is None:
        session.add(Conversation(id=cid, project_id=pid, title=cid))
    if session.get(Run, rid) is None:
        session.add(Run(id=rid, conversation_id=cid, status="completed"))
        session.flush()
        session.add(
            Agent(id=f"a-{rid}", run_id=rid, role_name="Lead", name="Lead", tools=[], depth=0)
        )
        session.flush()
    return f"a-{rid}"


def card(session, rid, reason="delete", command="rm -rf build", status="exited", decided=10.0,
         cwd=".", judged=None, ago=timedelta(0)):  # fmt: skip
    """A command on record: asked for `reason` (None: no card), answered after `decided` seconds
    (None: never), made `ago`."""
    at = now() - ago
    session.add(
        Command(
            run_id=rid,
            agent_id=f"a-{rid}",
            command=command,
            cwd=cwd,
            location="host",
            timeout_seconds=5,
            status=status,
            asked_reason=reason,
            judged=judged,
            created_at=at,
            decided_at=None if decided is None else at + timedelta(seconds=decided),
        )
    )


# --- why a card was asked: the gate's own family of it ---------------------------------------


def test_every_reason_the_gate_can_give_has_a_family(tmp_path):
    from app import commands, copies
    from tests.test_command_gate import GATE, tokens

    found = tokens(tmp_path)
    project, runtime = tmp_path / "proj", tmp_path / "runtime"
    own = copies.folders(runtime)[0] / "a" / "tree"
    worktrees = [str(project), str(tmp_path / "wt" / "x")]
    unnamed: set[str] = set()
    for line, *_rest in GATE["lines"][::7]:  # (every seventh: each family, in seconds)
        for token, value in found.items():
            line = line.replace(token, value)
        for said in (
            commands.harms(line),
            commands.copy_reason(line, True, str(project), runtime, own, ".", worktrees),
            commands.installs(line),
            commands.runs_another(line),
            commands.web_off_reason(line, ["http_request"]),
        ):
            if said and cards.family(said) == "other":
                unnamed.add(said[:60])
    assert not unnamed, sorted(unnamed)


@pytest.mark.parametrize(
    ("line", "reason"),
    [
        ("rm -rf build", "delete"),
        ("git push origin main", "send"),
        ("cat .env", "secret"),
        ("echo hi > AGENTS.md", "standing"),
        ("pytest -q", "rule"),
    ],
)
def test_a_card_says_why_it_was_asked_and_when_the_user_answered(
    make_client, wait_run, project_dir, line, reason
):
    client, _model = make_client([cmd(line), text("ok")], executor=ScriptedExecutor([]))
    cid, run_id = start(client, project_dir)
    asked = wait_status(client, cid, "waiting_approval")["commands"][0]
    with client.app.state.session_factory() as session:
        row = session.get_one(Command, asked["id"])
        assert (row.asked_reason, row.decided_at) == (reason, None)
    assert client.post(f"/api/commands/{asked['id']}/reject").status_code == 200
    wait_run(client, cid, run_id)
    with client.app.state.session_factory() as session:
        row = session.get_one(Command, asked["id"])
        assert row.status == "rejected" and row.decided_at is not None


def test_a_command_no_card_was_asked_for_has_no_reason(make_client, wait_run, project_dir):
    from tests.fakes import Script

    client, _model = make_client(
        [cmd("pytest -q"), text("ok")], executor=ScriptedExecutor([Script(["1 passed\n"])])
    )
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id)
    with client.app.state.session_factory() as session:
        row = session.get_one(Command, snap["commands"][0]["id"])
        assert (row.status, row.asked_reason, row.decided_at) == ("exited", None, None)


def test_a_turn_that_ends_with_its_card_open_is_no_answer(make_client, wait_run, project_dir):
    client, _model = make_client([cmd("rm -rf build"), text("ok")], executor=ScriptedExecutor([]))
    cid, run_id = start(client, project_dir)
    asked = wait_status(client, cid, "waiting_approval")["commands"][0]
    client.post(f"/api/runs/{run_id}/cancel")
    wait_run(client, cid, run_id)
    with client.app.state.session_factory() as session:
        row = session.get_one(Command, asked["id"])
        assert row.status == "rejected" and row.decided_at is None  # (KOLONİ's no, not yours)


@pytest.mark.parametrize(
    ("command", "cwd", "targets"),
    [
        ("rm -rf build", "web", ["web/build"]),
        ("rm -rf build dist", ".", ["build", "dist"]),
        ("rm -rf a b/c", "web", ["web/a", "web/b/c"]),
        ("Remove-Item -Recurse -Force build", ".", ["build"]),
        ("rm -rf everything", ".", ["everything"]),  # (a bare word: a path from the root)
        ("rm -rf build", "", ["build"]),  # (the root, as a CLI's may be on record)
        ("rm -rf " + "a" * 79 + " b", ".", ["a" * 79, "b"]),
        # (no plain delete: a switch's value or one that reaches further, a folder not known,
        # a script named rm, a folder in the agent's words, `..`, a dot file, KOLONİ's scratch)
        ("rm -rf ../other", ".", None),
        ("rm -rf *", ".", None),
        ("rm -rf $HOME/x", ".", None),
        ("Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build", ".", None),
        ("Remove-Item build -Exclude src", ".", None),
        ("del /s build.log", ".", None),
        ("rm -rf build", None, None),
        ("./rm -rf build", ".", None),
        ("C:/x/rm.exe -rf build", ".", None),
        ("rm -rf build", "all of src and", None),
        ("rm -rf build", "sѕrc", None),
        ("rm -rf build", "sub/..", None),
        ("rm -rf build", "web/", None),
        ("rm -rf x/../src", ".", None),
        ("rm -rf build/.", ".", None),
        ("rm -rf build.", ".", None),
        ("rm -rf build", ".koloni/tmp", None),
        ("rm -rf src/.git", ".", None),
        ("rm -rf " + "a" * 81, ".", None),
    ],
)
def test_what_a_delete_names_as_its_targets(command, cwd, targets):
    assert cards._targets(command, cwd) == targets


def test_the_migration_adds_and_drops_the_columns(tmp_path):
    import sqlite3

    db = tmp_path / "m.db"
    cfg = _config(db)
    alembic.upgrade(cfg, "0173")

    def columns():
        with sqlite3.connect(db) as conn:
            return [row[1] for row in conn.execute("PRAGMA table_info(commands)")]

    assert {"asked_reason", "decided_at"} <= set(columns())
    alembic.downgrade(cfg, "0172")
    assert not {"asked_reason", "decided_at"} & set(columns())


def test_a_clis_card_says_why_too(tmp_path):
    # (`ask_for`: a command a CLI runs with a tool of its own - the same gate, the same reason.)
    import asyncio

    from tests.test_disposable import runner_at

    runner, factory = runner_at(tmp_path, "auto_edit")
    with factory() as session:
        # (Review: on its card a CLI's own words - Codex's reason - never choose the family)
        session.get_one(ToolCall, "t3").why_asked = "Deletes the build folder"
        session.commit()
    shell = {"always": True, "why": "It runs another command through a shell"}
    for call, line, given, reason in (
        ("t0", "rm -rf build", {}, "delete"),
        ("t1", "make build", shell, "shell"),
        ("t2", "cat .env", {}, "secret"),
        ("t3", "python x.py", {"always": True}, "rule"),
        ("t4", "python y.py", {"always": True, "why": cards.CLI_ASKED}, "other"),
    ):
        _ran, command_id = asyncio.run(runner.ask_for("r", "c", "a", call, line, cwd=".", **given))
        with factory() as session:
            assert session.get_one(Command, command_id).asked_reason == reason, line


# S: any line of the user's words that names the path - one that allows it or one that forbids it:
# no word list tells the two apart (the review's misses and false refusals, each said by a list of
# words).
NAMES_BUILD = [
    "Never delete ./build.\nUse tabs.",
    "Use tabs.\n- Do not remove `build`",
    "Never delete these:\n\n- ./build\n- ./dist",
    "NEVER DELETE ./BUILD",
    "Never delete build/",
    "Never delete .\\build",
    "Never delete build\\",
    "## Never delete\n- ./build\n- ./dist",
    "Never delete these:\n\nNote the list.\n- ./build",
    "- Never delete:\n    - ./build",
    "- Never delete:\n\t- ./build",
    "Never delete build/keep.txt",
    "Never delete build*",
    "Never delete 'build'",
    "Keep ./build.",
    "./build klasörünü asla silme.",
    "> Never delete ./build",
    "No need to ask before deleting ./build.",
    "./build is not tracked - delete it freely.",
    "You may delete ./build, not ./src.",
    "./build is regenerated; nothing in it is kept.",
]


@pytest.mark.parametrize("rules", NAMES_BUILD)
def test_a_line_that_names_the_deletes_path_is_found(rules):
    assert cards.mentioned([rules], "rm -rf build", ".") is not None


@pytest.mark.parametrize(
    "rules",
    [
        "Never delete ./build-cache",
        "Never delete src/build",
        "Never delete ./builds.",
        "Never delete ./build.old",
    ],
)
def test_a_line_on_another_path_names_nothing(rules):
    assert cards.mentioned([rules], "rm -rf build", ".") is None


@pytest.mark.parametrize(
    ("rule", "command", "cwd"),
    [
        # (the second session's probes on 06fe8f3: a folder it is in, a pattern, a full path)
        ("Never delete anything under out.", "rm -rf out/build", "."),
        ("Never delete anything in `out/`.", "rm -rf out/build", "."),
        ("Never delete out/*", "rm -rf out/build", "."),
        ("Never delete **/build", "rm -rf out/build", "."),
        ("Never delete **/build", "rm -rf build", "."),
        ("Never delete any build folder.", "rm -rf out/build", "."),
        ("Never delete C:/proj/out/build", "rm -rf out/build", "."),
        ("Never delete /home/me/proj/out/build", "rm -rf out/build", "."),
        ("Never delete anything under out.", "rm -rf build", "out"),
        ("Never delete *.db", "rm -rf a.db", "data"),
    ],
)
def test_a_folder_it_is_in_a_pattern_or_a_full_path_names_it_too(rule, command, cwd):
    assert cards.mentioned([rule], command, cwd) == rule


@pytest.mark.parametrize(
    "rule",
    [
        "Never delete src/out/build",
        "Never delete *.py",
        "Never delete builds/*",
        # (wildcards and nothing else are no pattern: a list's `*`, a sum)
        "* Use tabs.",
        "Rate it 5 * 3 times.",
        "**",
    ],
)
def test_a_pattern_or_path_that_does_not_take_it_in_names_nothing(rule):
    assert cards.mentioned([rule], "rm -rf out/build", ".") is None


def test_a_long_line_of_patterns_is_read_in_time():
    # (≤ 16 KB, in a child process with a limit: a pattern too long for a path is not matched)
    import subprocess
    import sys

    from tests.conftest import scaled

    code = (
        "import time; from app import cards; t = time.monotonic(); "
        "cards.mentioned(['*a' * 8000, ('a' * 79 + '* ') * 200, '/a;' * 5000], 'rm -rf out/build', '.'); "
        "print(time.monotonic() - t)"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=scaled(60)
    )
    assert done.returncode == 0 and float(done.stdout) < 2, (done.stdout, done.stderr)


# --- §8: two lines that disagree about a delete (the check of the user's words) ---------------


def _against(rules: str, command: str, message: str = "") -> bool:
    said = judge.said(None, rules, [message] if message else [])
    return judge.set_against(said, lambda line: bool(cards.mentioned([line], command, ".")))


def test_a_line_that_forbids_the_same_delete_sets_a_run_against_it():
    assert _against("You may delete ./x.\nNever delete ./x.", "rm -rf ./x")
    assert _against("You may delete ./x.\n\nNever delete these:\n- ./x", "rm -rf ./x")
    assert not _against("You may delete build/ and dist/.", "rm -rf build")
    assert not _against("You may delete ./x.\nNever delete ./y.", "rm -rf ./x")
    # (wide on purpose - a wrong card is safe, a wrong run is not: a line of the chat that names
    # the target and sets a condition counts too)
    assert _against(
        "You may delete build/ and dist/.", "rm -rf build", "Clean the build before the tests"
    )


def test_a_heading_forbids_only_its_own_list():
    """Codex P2-3 (W1): a heading's scope ends at a blank line after its lines or the next heading
    - for a list's items, at a line of prose (as `judge._units` reads it) - not at the end of the
    words; a heading right under another is read with it."""
    for elsewhere in ("Never delete these:\n- ./archive", "Do not commit secrets:\n- .env"):
        for allowed in ("Disposable outputs:\nYou may delete ./build.", "You may delete ./build."):
            assert not _against(f"{elsewhere}\n\n{allowed}", "rm -rf ./build"), (elsewhere, allowed)
    # (its own list, and a line right under it, as before - a blank line between a heading and
    # its list, or between the list's items, parts neither)
    assert _against("Never delete these:\n- ./build\nYou may delete ./build.", "rm -rf ./build")
    assert _against("Never delete these:\n\n- ./a\n\n- ./build", "rm -rf ./build")
    assert not _against("Never delete these:\n- ./a\n\nKeep it tidy.\n- ./build", "rm -rf ./build")
    # (review of k-kucuk-019: a sub-heading never lifts the forbid of the heading it is under -
    # each of these ran `rm -rf ./build` beside "You may delete ./build." where 0.1.9 carded it)
    for nested in (
        "Never delete:\nOutputs:\n- ./build",
        "Do not delete the following:\nGenerated files:\n- ./build",
        "Never delete these:\n\nGenerated:\n- ./build",
        "Never delete:\n- ./data\nGenerated:\n- ./build",
        "Asla silme:\nÇıktılar:\n- ./build",
        "Ask me before deleting:\nOutputs:\n- ./build",
    ):
        assert _against(f"You may delete ./build.\n\n{nested}", "rm -rf ./build"), nested
    # (the judge's decision on the model's quote of the allowing line, as Codex's probe read it)
    for rules, decided in (
        ("Never delete these:\n- ./archive\n\nDisposable outputs:\nYou may delete ./build.", "run"),
        ("Never delete these:\n- ./archive\nDisposable outputs:\nYou may delete ./build.", "ask"),
        ("Never delete these:\n- ./build\nYou may delete ./build.", "ask"),
    ):
        assert _decided(rules, "You may delete ./build.", "rm -rf ./build") == decided, rules


def _decided(rules: str, quote: str, command: str) -> str:
    answer = json.dumps({"verdict": "run", "quote": quote, "why": ""})
    said = judge.said(None, rules, [])
    found = judge.verdict(answer, said, lambda line: bool(cards.mentioned([line], command, ".")))
    return found["verdict"] if found else ""


def test_a_delete_of_dot_slash_x_names_x():
    assert cards._targets("rm -rf ./x", ".") == ["x"]
    assert cards._targets("rm -rf ./", ".") is None and cards._targets("rm -rf ./*", ".") is None
