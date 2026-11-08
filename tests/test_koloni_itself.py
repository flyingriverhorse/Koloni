"""K-56: what KOLONİ asks a model itself with no turn - the day's words, a recipe's draft, a
role's guide, a Check that runs a CLI - is on Usage as "KOLONİ itself", in its project's
budget and its provider's limits; never in one turn's."""

import sqlite3

from alembic import command
from sqlalchemy import select

from app.db.models import OwnRequest
from app.model_client import ModelUnavailable
from tests.test_budget_scenarios import PRICE, budget
from tests.test_chat_flow import text
from tests.test_day_note import MIDNIGHT
from tests.test_migration_0002 import _config
from tests.test_usage_scenarios import began, turn, usage


def words(client, pid, cid):
    said = client.post(f"/api/projects/{pid}/day/words",
                       json={"since": MIDNIGHT.isoformat(), "conversation_id": cid})
    return said


def itself(told):
    return next(row for row in told["by_start"] if row["started_by"] == "koloni")


def test_the_days_words_are_koloni_itself_in_its_projects_usage_and_budget(
    make_client, wait_run, project_dir,
):
    client, _model, pid, cid = began(make_client, project_dir, [
        text("done", 1_000_000, 0), text("A quiet day.", 1_000_000, 100_000)])
    run = turn(client, wait_run, cid)
    client.put("/api/prices", json=PRICE)
    assert words(client, pid, cid).status_code == 200
    told = usage(client, project_id=pid)
    mine = itself(told)
    # tokens as the model reported them, in no message, priced at the model's price
    assert (mine["runs"], mine["agents"], mine["input_tokens"], mine["output_tokens"]) == (
        0, 1, 1_000_000, 100_000)
    assert mine["cost"] == {"amount": 4.5, "currency": "USD"}
    # under its model with the turn's, and in no conversation
    (model,) = told["by_model"]
    assert (model["agents"], model["input_tokens"]) == (2, 2_000_000)
    assert [talk["agents"] for talk in told["by_conversation"]] == [1]
    # in the month's budget; never in one turn's summary, nor another project's
    assert budget(client, pid)["spent"] == 7.5
    assert all(row["started_by"] != "koloni" for row in usage(client, run_id=run["id"])["by_start"])
    assert usage(client, project_id="another")["by_start"] == []


def test_one_not_heard_out_is_on_record_as_unknown(make_client, wait_run, project_dir,
                                                    monkeypatch):
    client, _model, pid, cid = began(make_client, project_dir, [text("done")])
    turn(client, wait_run, cid)

    async def down(*_args, **_kwargs):
        raise ModelUnavailable("model server sent nothing for 120 seconds")

    monkeypatch.setattr("app.providers.ask_once", down)
    assert words(client, pid, cid).status_code == 502
    mine = itself(usage(client))
    # nothing made up: what it spent is not known
    assert (mine["agents"], mine["unknown_agents"], mine["input_tokens"]) == (1, 1, None)
    with client.app.state.session_factory() as session:
        asked = session.scalars(select(OwnRequest).where(OwnRequest.run_id.is_(None))).one()
        assert (asked.cut_short, asked.project_id, asked.agent_id) == (True, pid, None)


def test_a_recipes_draft_is_koloni_itself_in_no_project(make_client):
    client, _model = make_client([text('{"name": "x", "graph": {}}', 7, 2)])
    client.post("/api/recipes/draft", json={"text": "a coder"},
                headers={"Origin": "http://127.0.0.1:8790"})
    mine = itself(usage(client))
    assert (mine["input_tokens"], mine["output_tokens"]) == (7, 2)
    assert usage(client)["by_conversation"] == []


def test_migration_0096_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0096")
    at = "2026-10-27 10:00:00"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO own_requests (id, run_id, agent_id, provider_name, model_id, "
            "cut_short, created_at) VALUES ('kept', 'r', 'a', 'Local', 'm', 0, ?)", (at,))
        conn.execute(
            "INSERT INTO own_requests (id, provider_name, model_id, cut_short, created_at) "
            "VALUES ('itself', 'Local', 'm', 0, ?)", (at,))
    command.downgrade(cfg, "0098")
    with sqlite3.connect(db) as conn:
        left = [row[0] for row in conn.execute("SELECT id FROM own_requests")]
        columns = [row[1] for row in conn.execute("PRAGMA table_info(own_requests)")]
    # one with no turn has no place before it; one with a turn is kept as it was
    assert left == ["kept"] and "project_id" not in columns
    command.upgrade(cfg, "head")
