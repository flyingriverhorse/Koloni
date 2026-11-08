"""B-335: migration 0129 makes 0109, 0121 and 0122's changes again where a built-in role's tools
are the same set as before them, in any order; a list the user changed is left alone."""

import json
import sqlite3

from alembic import command

from app.roles import BUILTIN_ROLES
from tests.test_migration_0002 import _config
from tests.test_migration_0109 import _role

# An upgraded install's Lead before 0122: 0097 put propose_trigger last, 0125 gave view_image.
LEAD = ["list_dir", "read_file", "search", "view_image", "write_file", "edit_file", "show",
        "run_command", "web_search", "http_request", "notify", "spawn_agent", "create_role",
        "add_skill", "ask_user", "ask_folder", "message_agent", "open_room", "discuss",
        "read_backlog", "add_task", "change_task", "assess_task", "post_note", "read_notes",
        "remember", "recall", "propose_trigger"]
# A Debugger before 0121, in another order.
DEBUGGER = ["read_file", "list_dir", "search", "view_image", "write_file", "edit_file",
            "run_command", "message_agent", "ask_user", "post_note", "read_notes", "remember",
            "recall"]


def _upgraded(tmp_path, roles):
    tmp_path.mkdir(exist_ok=True)
    cfg = _config(db := tmp_path / "r.db")
    command.upgrade(cfg, "0128")
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM roles WHERE name IN ('Lead', 'Debugger')")
        for at, (name, tools) in enumerate(roles):
            _role(conn, str(at), name, tools, "as given")
    command.upgrade(cfg, "0129")
    with sqlite3.connect(db) as conn:
        return {name: json.loads(tools) for name, tools in conn.execute(
            "SELECT name, tools FROM roles WHERE name IN ('Lead', 'Debugger')")}


def test_an_upgraded_lead_and_debugger_get_what_they_missed_in_their_own_order(tmp_path):
    held = _upgraded(tmp_path, [("Lead", LEAD), ("Debugger", DEBUGGER)])
    for name in ("Lead", "Debugger"):
        # (its list is written after 0128, so diagram_image, which 0128 would have given it, is not there)
        assert set(held[name]) == set(BUILTIN_ROLES[name].tools) - {"diagram_image"}, name
    assert held["Lead"][-1] == "propose_trigger"
    assert held["Lead"][held["Lead"].index("http_request") + 1] == "browser_open"


def test_a_list_the_user_changed_is_left_alone(tmp_path):
    lead = [tool for tool in LEAD if tool != "notify"]
    assert _upgraded(tmp_path, [("Lead", lead)])["Lead"] == lead



def test_a_spec_writer_0109_skipped_gets_its_write_tools_and_words_then_spawn_agent(tmp_path):
    # (0109 then 0121 in one run: the row 0109's step rewrote is the one 0121's step finds)
    from tests.test_migration_0109 import M as M0109

    cfg = _config(db := tmp_path / "r.db")
    command.upgrade(cfg, "0128")
    was = ["search", "read_file", "list_dir", "view_image", "message_agent", "ask_user",
           "post_note", "read_notes", "remember", "recall"]
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM roles WHERE name = 'Spec writer'")
        _role(conn, "s", "Spec writer", was, M0109.SPEC_WAS)
    command.upgrade(cfg, "0129")
    with sqlite3.connect(db) as conn:
        tools, said = conn.execute(
            "SELECT tools, instructions FROM roles WHERE name = 'Spec writer'").fetchone()
    assert {"write_file", "edit_file", "spawn_agent"} <= set(json.loads(tools))
    assert said == M0109.SPEC_NOW


def test_a_list_in_the_very_order_it_was_is_the_users_and_later_tools_do_not_count(tmp_path):
    # (review of B-335: the page saves a role in that order - the user took the browser off)
    from tests.test_migration_0122 import M as M0122

    canonical = ["view_image", *dict(M0122.ROLES)["Lead"]]
    assert _upgraded(tmp_path / "a", [("Lead", canonical)])["Lead"] == canonical
    # (K-drawio's diagram_image, given whatever the list was, counts no more than view_image)
    held = _upgraded(tmp_path / "b", [("Lead", [*LEAD, "diagram_image"])])["Lead"]
    assert "browser_open" in held and "diagram_image" in held
