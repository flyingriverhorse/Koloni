"""Cards measured (0.1.7, the user: "evet ölçelim"): a command card records why it was asked, as the
gate saw it (`commands.asked_reason`), and when the user answered it from the app's own page
(`decided_at`); the Usage page's numbers (`cards.stats`), and the rule a delete the user approved
unchanged five times suggests (`cards.suggestions`) - saved by the user's click alone."""

import json
from datetime import timedelta

import pytest
from alembic import command as alembic

from app import cards, judge
from app.db.models import Agent, Command, Conversation, Project, Run, ToolCall, now
from app.db.session import make_engine, make_session_factory, upgrade_db
from tests.fakes import ScriptedExecutor
from tests.keyed import NO_ORIGIN, OWN
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


# --- what the Usage page says ------------------------------------------------------------------


def test_the_cards_of_a_period_by_reason_answer_and_check(db):
    with db() as session:
        turn(session, "r1", "c1", "p")
        turn(session, "r2", "c2", "q")
        card(session, "r1", "delete", decided=10)  # (approved)
        card(session, "r1", "delete", status="rejected", decided=30)
        card(session, "r1", "send", status="rejected", decided=None)  # (the turn ended)
        card(session, "r1", "rule", decided=20)
        card(session, "r1", "rule", decided=5, ago=timedelta(days=10))  # (before the period)
        card(session, "r1", None, decided=None)  # (no card: before 0.1.7, or none asked)
        card(session, "r1", None, decided=None, judged={"verdict": "run", "quote": "x"})
        card(session, "r1", "delete", decided=None, judged={"verdict": "ask"})
        card(session, "r1", None, status="refused", decided=None, judged={"verdict": "refuse"})
        card(session, "r2", "install", decided=40)  # (another project)
        session.commit()
        here = cards.stats(session, "p", now() - timedelta(days=7))
        everywhere = cards.stats(session, None, None)
    assert {k: here[k] for k in ("asked", "approved", "rejected", "unanswered")} == {
        "asked": 5,
        "approved": 2,
        "rejected": 1,
        "unanswered": 2,
    }
    assert [(one["reason"], one["asked"], one["approved"], one["rejected"]) for one in here[
        "by_reason"]] == [("delete", 3, 1, 1), ("send", 1, 0, 0), ("rule", 1, 1, 0)]  # fmt: skip
    assert here["by_reason"][0]["said"] == "Deletes or overwrites"
    assert here["decide_seconds"] == 20.0  # (10, 30, 20: answered ones only)
    assert here["checked"] == {"run": 1, "refuse": 1, "ask": 1}
    assert everywhere["asked"] == 7 and everywhere["by_reason"][-1]["reason"] == "rule"
    assert cards.stats(session_none := db(), "nowhere", None)["decide_seconds"] is None
    session_none.close()


# --- a rule suggested, never added by itself ---------------------------------------------------


def suggested(db, times, rules=None, **more):
    """`times` approvals more of a card (`card`'s `more`), and what is suggested then - under
    `rules` where given."""
    with db() as session:
        turn(session)
        for _one in range(times):
            card(session, "r", **more)
        project = session.get_one(Project, "p")
        if rules is not None:
            project.rules = rules
        session.commit()
        return cards.suggestions(session, project, project.rules or "")


def test_five_unchanged_approvals_suggest_a_rule_in_koloni_s_words(db):
    assert suggested(db, 4) == []
    (one,) = suggested(db, 1)  # (the fifth)
    assert one["rule"] == "You may delete ./build."
    assert (one["command"], one["cwd"], one["times"]) == ("rm -rf build", ".", 5)
    assert one["key"] == cards.key_of("p", "rm -rf build", ".")
    # The line holds as the user's own for the check of their words: a run stands on it.
    answer = json.dumps({"verdict": "run", "quote": one["rule"], "why": ""})
    assert judge.verdict(answer, judge.said(None, one["rule"], []))["verdict"] == "run"


@pytest.mark.parametrize(
    ("more", "rule"),
    [
        ({"cwd": "web"}, "You may delete ./web/build."),
        ({"command": "rm -rf build dist"}, "You may delete ./build and ./dist."),
        ({"command": "rm -rf a b/c", "cwd": "web"}, "You may delete ./web/a and ./web/b/c."),
        ({"command": "Remove-Item -Recurse -Force build"}, "You may delete ./build."),
        # (Review: a bare word names a path from the project's root, never "everything")
        ({"command": "rm -rf everything"}, "You may delete ./everything."),
        # (no rule: what was not answered by the user, or said no to, or what is no plain delete)
        ({"decided": None}, None),
        ({"status": "rejected"}, None),
        ({"ago": timedelta(days=31)}, None),
        ({"reason": "rule", "command": "pytest -q"}, None),
        ({"command": "rm -rf ../other"}, None),
        ({"command": "rm -rf *"}, None),
        ({"command": "rm -rf $HOME/x"}, None),
        ({"command": "rm -rf build; git push"}, None),
        ({"command": "rm -rf build-if"}, None),  # (a line with "if" is no run for the check)
        # (Review: a switch's value is no target - it names what was not deleted - nor is a switch
        # that reaches further a plain delete; a CLI's command whose folder is not known)
        ({"command": "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build"}, None),
        ({"command": "Remove-Item build -Exclude src"}, None),
        ({"command": "del /s build.log"}, None),
        ({"cwd": None}, None),
        # (Review: two commands on two lines, read as one once their spaces were made one; a
        # folder in the agent's words; a path through `..`; KOLONİ's own scratch; a dot file;
        # a command too long to be a plain delete)
        ({"command": "rm -rf build\nsrc"}, None),
        ({"command": "rm -rf build\r\nsrc"}, None),
        ({"command": "rm -rf build\x0csrc"}, None),
        ({"command": "rm -rf build\u2028src"}, None),
        ({"command": "./rm -rf build"}, None),  # (a script of the project's named rm)
        ({"command": "C:/x/rm.exe -rf build"}, None),
        ({"cwd": ""}, "You may delete ./build."),  # (the root, as a CLI's may be on record)
        ({"cwd": "all of src and"}, None),
        ({"cwd": "s\u0455rc"}, None),
        ({"cwd": "sub/.."}, None),
        ({"cwd": "web/"}, None),
        ({"command": "rm -rf x/../src"}, None),
        ({"command": "rm -rf build/."}, None),
        ({"command": "rm -rf build."}, None),
        ({"cwd": ".koloni/tmp"}, None),
        ({"command": "rm -rf src/.git"}, None),
        ({"command": "rm -rf " + "a" * 79 + " b"}, "You may delete ./" + "a" * 79 + " and ./b."),
        ({"command": "rm -rf " + "a" * 81}, None),
        ({"command": "rm -rf build" + " " * cards.MAX_RULE}, None),
    ],
)
def test_what_a_suggestion_names_and_what_suggests_none(db, more, rule):
    found = suggested(db, 5, **more)
    assert [one["rule"] for one in found] == ([rule] if rule else []), found


def test_a_rule_already_there_is_not_suggested_again(db):
    assert suggested(db, 5, rules="Be brief.\n- You may delete ./build.") == []


def test_a_rule_that_would_not_hold_where_it_is_saved_is_not_suggested(db):
    # (Under a heading that forbids, the check would never let a run stand on it.)
    assert suggested(db, 5, rules="Never do these:") == []
    # (A rule that only starts so is another one: this one is not there yet.)
    (one,) = suggested(db, 0, rules="You may delete ./build.log.")
    assert one["rule"] == "You may delete ./build."


def test_one_click_saves_the_rule_from_the_own_page_alone(make_client, project_dir):
    client, _model = make_client([])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    put = client.put(f"/api/projects/{pid}/rules", json={"rules": "Be brief."}, headers=OWN)
    assert put.status_code == 200, put.text
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    with client.app.state.session_factory() as session:
        session.add(Run(id="r", conversation_id=cid, status="completed"))
        session.flush()
        session.add(Agent(id="a-r", run_id="r", role_name="Lead", name="Lead", tools=[], depth=0))
        session.flush()
        for _one in range(5):
            card(session, "r")
        session.commit()
    read = client.get("/api/cards", params={"project_id": pid}).json()
    ((one,),) = [read["suggestions"]]
    assert (read["asked"], read["approved"], one["rule"]) == (5, 5, "You may delete ./build.")
    url = f"/api/projects/{pid}/card-suggestions/{one['key']}"
    assert client.post(url, headers=NO_ORIGIN).status_code == 403
    assert client.post(url, headers={"Origin": "http://evil.example"}).status_code == 403
    assert client.post(f"/api/projects/{pid}/card-suggestions/0000", headers=OWN).status_code == 404
    saved = client.post(url, headers=OWN)
    assert saved.json() == {"rules": "Be brief.\nYou may delete ./build."}, saved.text
    assert client.post(url, headers=OWN).json() == saved.json()  # (once there, as it is)
    assert client.get("/api/cards", params={"project_id": pid}).json()["suggestions"] == []
    rules = (project_dir / ".koloni" / "rules.md").read_text(encoding="utf-8")
    assert "You may delete ./build." in rules  # (as the Memory page saves them)


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


def test_the_page_asks_for_a_period_as_it_sends_it(make_client, project_dir):
    client, _model = make_client([])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    # (as `new Date(...).toISOString()` gives it: "2026-11-16T10:00:00.000Z")
    since = (now() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    read = client.get("/api/cards", params={"project_id": pid, "since": since})
    assert read.status_code == 200 and read.json()["asked"] == 0, read.text
    assert client.get("/api/cards", params={"project_id": "nowhere"}).status_code == 404


# S: any line of the user's words that names the path - allowed already (a "You may" one too
# many) or forbidden (one set against it): no word list tells the two apart (the review's misses
# and false refusals, each said by a list of words).
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
def test_a_delete_whose_path_the_users_words_name_is_never_suggested(db, rules):
    # (S, live: "Never delete ./zz096build." stood, five approvals suggested "You may delete
    # ./zz096build." and Add to rules wrote it under it - the two set against each other)
    assert suggested(db, 5, rules=rules) == []
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
def test_a_line_on_another_path_leaves_the_delete_suggested(db, rules):
    assert [one["rule"] for one in suggested(db, 5, rules=rules)] == ["You may delete ./build."]


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


def test_add_to_rules_refuses_a_delete_whose_path_the_users_preferences_name(
    make_client, project_dir
):
    from app.db.models import UserPreferences

    client, _model = make_client([])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    with client.app.state.session_factory() as session:
        session.add(Run(id="r", conversation_id=cid, status="completed"))
        session.flush()
        session.add(Agent(id="a-r", run_id="r", role_name="Lead", name="Lead", tools=[], depth=0))
        session.flush()
        for _one in range(5):
            card(session, "r")
        session.commit()
    (one,) = client.get("/api/cards", params={"project_id": pid}).json()["suggestions"]
    with client.app.state.session_factory() as session:
        session.merge(UserPreferences(id=1, text="Never delete ./build, whatever a rule says."))
        session.commit()
    assert client.get("/api/cards", params={"project_id": pid}).json()["suggestions"] == []
    refused = client.post(f"/api/projects/{pid}/card-suggestions/{one['key']}", headers=OWN)
    assert refused.status_code == 409 and "Never delete ./build" in refused.json()["detail"]
    assert not (project_dir / ".koloni" / "rules.md").exists()
