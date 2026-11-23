"""Cards measured (0.1.7, the user: "evet ölçelim"): a command card records why it was asked, as the
gate saw it (`commands.asked_reason`), and when the user answered it from the app's own page
(`decided_at`); the Usage page's numbers (`cards.stats`), and the rule a delete the user approved
unchanged five times suggests (`cards.suggestions`) - saved by the user's click alone."""

import json
from datetime import timedelta

import pytest
from alembic import command as alembic

from app import cards, judge
from app.db.models import Agent, Command, Conversation, Project, Run, now
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
    with db() as session:
        turn(session, rules=rules)
        for _one in range(times):
            card(session, "r", **more)
        session.commit()
        project = session.get_one(Project, "p")
        return cards.suggestions(session, project, project.rules or "")


def test_five_unchanged_approvals_suggest_a_rule_in_koloni_s_words(db):
    assert suggested(db, 4) == []
    (one,) = suggested(db, 1)  # (the fifth)
    assert one["rule"] == "You may delete build."
    assert (one["command"], one["cwd"], one["times"]) == ("rm -rf build", ".", 5)
    assert one["key"] == cards.key_of("p", "rm -rf build", ".")
    # The line holds as the user's own for the check of their words: a run stands on it.
    answer = json.dumps({"verdict": "run", "quote": one["rule"], "why": ""})
    assert judge.verdict(answer, judge.said(None, one["rule"], []))["verdict"] == "run"


@pytest.mark.parametrize(
    ("more", "rule"),
    [
        ({"cwd": "web"}, "You may delete web/build."),
        ({"command": "rm -rf build dist"}, "You may delete build and dist."),
        ({"command": "Remove-Item -Recurse -Force build"}, "You may delete build."),
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
    ],
)
def test_what_a_suggestion_names_and_what_suggests_none(db, more, rule):
    found = suggested(db, 5, **more)
    assert [one["rule"] for one in found] == ([rule] if rule else []), found


def test_a_rule_already_there_is_not_suggested_again(db):
    assert suggested(db, 5, rules="Be brief.\n- You may delete build.") == []


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
    assert (read["asked"], read["approved"], one["rule"]) == (5, 5, "You may delete build.")
    url = f"/api/projects/{pid}/card-suggestions/{one['key']}"
    assert client.post(url, headers=NO_ORIGIN).status_code == 403
    assert client.post(url, headers={"Origin": "http://evil.example"}).status_code == 403
    assert client.post(f"/api/projects/{pid}/card-suggestions/0000", headers=OWN).status_code == 404
    saved = client.post(url, headers=OWN)
    assert saved.json() == {"rules": "Be brief.\nYou may delete build."}, saved.text
    assert client.post(url, headers=OWN).json() == saved.json()  # (once there, as it is)
    assert client.get("/api/cards", params={"project_id": pid}).json()["suggestions"] == []
    rules = (project_dir / ".koloni" / "rules.md").read_text(encoding="utf-8")
    assert "You may delete build." in rules  # (as the Memory page saves them)


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
