"""A longer discussion and its budget (slice 29a), beyond the acceptance set: when the budget
is looked at, that each discussion has the whole of it, what a member keeps, a restart, who
may set it, and the migration.
"""

import sqlite3

import pytest
from alembic import command

from app.config import load_settings
from app.main import create_app
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_chat_flow import text
from tests.test_discussion import TWO, discuss, said
from tests.test_long_discussion_scenarios import ORIGIN, back, spent
from tests.test_migration_0002 import _config
from tests.test_spawn import begin, call, step
from tests.test_spawn import spawn as open_one

# --- when the budget is looked at -------------------------------------------------------------


def test_a_speech_that_goes_over_the_budget_is_heard_out_and_the_next_never_starts(
    make_client, wait_run, project_dir
):
    client, model = make_client({
        "Lead": [TWO, discuss("Is hello.py fine?", ["Coder", "Reviewer"]),
                 text("It stopped there.")],
        # It looks the file up first. That step alone is over the budget: it still speaks.
        "Coder": [text("ready"), step(call("read_file", {"path": "hello.py"}, "f1"), i=120, o=0),
                  spent("It prints hi.", 10)],
        "Reviewer": [text("ready"), text("never said")],
    })
    cid, run_id = begin(client, project_dir, mode="full_auto", discussion_budget=100)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert said(snap) == [(1, "Coder", "It prints hi.", False)]
    (talk,) = snap["discussions"]
    assert (talk["status"], talk["outcome"], talk["round"]) == ("ended", "budget", 1)
    assert [m["status"] for m in talk["members"]] == ["in", "in", "in"]   # nobody left it
    assert len(model.calls_of["Reviewer"]) == 1         # its own job, and no speech
    assert back(model).startswith(
        "The discussion ended: its speakers' models reported more tokens than its budget "
        "allows.\n\nRound 1\nCoder: It prints hi.")


@pytest.mark.parametrize("last, outcome, rounds, coder_spoke", [
    (50, "agreed", 2, 2),       # 50 and 50: at the budget is not over it, and it goes on
    (51, "budget", 1, 1),       # one more, said by the last of the round: no round 2 begins
])
def test_only_over_the_budget_ends_it_and_then_no_new_round_begins(
    make_client, wait_run, project_dir, last, outcome, rounds, coder_spoke
):
    client, model = make_client({
        "Lead": [open_one("Coder", id="s1"), discuss("Go on?", ["Coder"]),
                 spent("And I say no.", last), spent("PASS", 0), text("Done.")],
        "Coder": [text("ready"), spent("I say yes.", 50), spent("PASS", 0)],
    })
    cid, run_id = begin(client, project_dir, mode="full_auto", discussion_budget=100)
    snap = wait_run(client, cid, run_id)
    (talk,) = snap["discussions"]
    assert (talk["outcome"], talk["round"]) == (outcome, rounds)
    assert said(snap)[:2] == [(1, "Coder", "I say yes.", False), (1, "Lead", "And I say no.", False)]
    assert len(model.calls_of["Coder"]) == 1 + coder_spoke


def test_over_the_budget_is_how_it_ended_also_where_everyone_in_the_round_passed(
    make_client, wait_run, project_dir
):
    client, model = make_client({
        "Lead": [open_one("Coder", id="s1"), discuss("Go on?", ["Coder"]),
                 spent("PASS", 60), text("Done.")],
        "Coder": [text("ready"), spent("PASS", 50)],
    })
    cid, run_id = begin(client, project_dir, mode="full_auto", discussion_budget=100)
    snap = wait_run(client, cid, run_id)
    (talk,) = snap["discussions"]
    # The budget is looked at before agreement is: what is said of the ending is true of it,
    # and a round nobody added to is not called agreement where the budget was over.
    assert (talk["outcome"], talk["round"]) == ("budget", 1)
    assert back(model).startswith("The discussion ended: its speakers' models reported more")


def test_each_discussion_has_the_whole_budget(make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [open_one("Coder", id="s1"),
                 discuss("First?", ["Coder"], rounds=1, id="d1"), spent("one", 30),
                 discuss("Second?", ["Coder"], rounds=1, id="d2"), spent("two", 30),
                 text("Done.")],
        "Coder": [text("ready"), spent("a", 40), spent("b", 40)],
    })
    cid, run_id = begin(client, project_dir, mode="full_auto", discussion_budget=100)
    snap = wait_run(client, cid, run_id)
    # 70 in each: together they would be over, and neither is
    assert [talk["outcome"] for talk in snap["discussions"]] == ["round_limit", "round_limit"]


def test_a_member_keeps_how_the_discussion_ended(make_client, wait_run, project_dir):
    client, model = make_client({
        "Lead": [open_one("Coder", id="s1"), discuss("Tabs or spaces?", ["Coder"]),
                 step(call("message_agent", {"to": "Coder", "message": "Go on then."}, "m1")),
                 text("done")],
        "Coder": [text("ready"), spent("Tabs.", 150), text("On it.")],
    })
    cid, run_id = begin(client, project_dir, mode="full_auto", discussion_budget=100)
    snap = wait_run(client, cid, run_id)
    assert snap["discussions"][0]["outcome"] == "budget"
    # carried on afterwards, the Coder is told why it was over before the Lead spoke
    kept = [m["content"] for m in model.calls_of["Coder"][2]
            if 'The discussion "Tabs or spaces?" ended' in m["content"]]
    assert len(kept) == 1
    assert "ended: its speakers' models reported more tokens than its budget allows." in kept[0]
    assert kept[0].endswith("Round 1\nCoder: Tabs.")


# --- a restart ---------------------------------------------------------------------------------


def test_after_a_restart_the_budget_and_how_a_discussion_ended_are_as_they_were(
    settings_env, wait_run, project_dir
):
    def opened(steps):
        return TestClient(create_app(load_settings(settings_env), model=ScriptedModel(steps)),
                          base_url="http://127.0.0.1:8790")

    with opened({
        "Lead": [open_one("Coder", id="s1"), discuss("Before?", ["Coder"]), text("Over.")],
        "Coder": [text("ready"), spent("Much.", 150)],
    }) as client:
        cid, run_id = begin(client, project_dir, mode="full_auto", discussion_budget=100)
        wait_run(client, cid, run_id)
    with opened({
        "Lead": [discuss("And after?", ["Reviewer"]), text("Over again.")],
        "Reviewer": [spent("As much.", 150)],
    }) as client:
        snap = client.get(f"/api/conversations/{cid}").json()
        assert snap["conversation"]["discussion_budget"] == 100
        assert [(t["status"], t["outcome"]) for t in snap["discussions"]] == [("ended", "budget")]
        # and a discussion of the next turn is held to it, from nothing
        run_id = client.post(f"/api/conversations/{cid}/messages",
                             json={"content": "once more"}).json()["run"]["id"]
        snap = wait_run(client, cid, run_id)
        assert [t["outcome"] for t in snap["discussions"]] == ["budget", "budget"]
        assert [what for _round, _who, what, _passed in said(snap)] == ["Much.", "As much."]


# --- the setting -------------------------------------------------------------------------------


def test_the_budget_is_set_only_from_the_apps_own_page(client, project_dir):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    change = f"/api/conversations/{client.post(f'/api/projects/{pid}/conversations').json()['id']}"
    # a command an agent runs against the app's address says nothing of where it is from
    for more in (None, 9_000_000):
        assert client.patch(change, json={"discussion_budget": more}).status_code == 403
    # (none by default: the user, 6 Nov)
    assert client.get(change).json()["conversation"]["discussion_budget"] is None
    own = {"Origin": ORIGIN}
    # its other settings are changed as before, and leave the budget as it is
    assert client.patch(change, json={"spawn_max_parallel": 3}, headers=own).json()[
        "discussion_budget"] is None
    for bad in (True, "5000", 2**53 + 1):
        assert client.patch(change, json={"discussion_budget": bad}, headers=own).status_code == 422
    assert client.patch(change, json={"discussion_budget": 1}, headers=own).json()[
        "discussion_budget"] == 1


def test_migration_0038_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0037")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO projects (id, name, root_path, created_at) "
                     "VALUES ('p', 'p', 'C:/p', '2026-10-13 10:00:00')")
        conn.execute("INSERT INTO conversations (id, project_id, title, created_at, updated_at) "
                     "VALUES ('c', 'p', 't', '2026-10-13 10:00:00', '2026-10-13 10:00:00')")
    command.upgrade(cfg, "0038")
    with sqlite3.connect(db) as conn:
        # a conversation from before has the budget a new one starts with, and may have none
        assert conn.execute("SELECT discussion_budget FROM conversations").fetchall() == [
            (200_000,)]
        conn.execute("UPDATE conversations SET discussion_budget = NULL")
    command.downgrade(cfg, "0037")
    with sqlite3.connect(db) as conn:
        assert "discussion_budget" not in [
            row[1] for row in conn.execute("PRAGMA table_info(conversations)")]
        assert conn.execute("SELECT id, title FROM conversations").fetchall() == [("c", "t")]
