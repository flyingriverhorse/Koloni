"""Migration 0083 (batch-16): every team's lead whose tier rule is still the "balanced or stronger"
0073 gave it runs on the chat's model; one the user changed is left as it is; going back gives
the old rule back."""

import sqlite3

from alembic import command

from tests.test_migration_0002 import _config


def rules(db):
    with sqlite3.connect(db) as conn:
        return {team: (tier, low) for team, tier, low in conn.execute(
            "SELECT teams.name, roles.tier, roles.tier_min FROM teams "
            "JOIN roles ON roles.id = teams.lead_role_id")}


def test_every_untouched_lead_runs_on_the_chats_model_and_gets_its_rule_back_going_back(tmp_path):
    db = tmp_path / "fresh.db"
    cfg = _config(db)
    command.upgrade(cfg, "0082")
    assert rules(db)["Web app"] == (None, "balanced")
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE roles SET tier = 'strongest' WHERE id = (SELECT lead_role_id FROM teams "
                     "WHERE name = 'Docs')")
        conn.execute("UPDATE roles SET tier_min = 'fast' WHERE id = (SELECT lead_role_id FROM teams "
                     "WHERE name = 'Data')")
    before = rules(db)

    command.upgrade(cfg, "head")

    after = rules(db)
    assert (after["Docs"], after["Data"]) == (("strongest", "balanced"), (None, "fast"))
    assert all(rule == ("conversation", None) for name, rule in after.items() if name not in ("Docs", "Data"))

    command.downgrade(cfg, "0082")

    assert rules(db) == before
