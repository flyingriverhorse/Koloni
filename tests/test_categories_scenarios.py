"""Slice 63b: roles' categories are the user's - the four built-in ones renamed and recoloured, new
ones added and put in order, an empty one deleted. A role's kind is its category's key; a
category is a label to find roles by, and changes no team's stages, nor what a role is told.

Contract:
- `GET /api/categories` → `[{key, name, colour}]` in order; `POST {name, colour}`,
  `PATCH /{key} {name?, colour?}`, `PUT {order}` answer the list; `DELETE /{key}` → 204, or 409
  while a role is in it. Every write from the app's own page only.
- A name is 1 to 40 printable characters, unique whatever its case; a colour is one of the
  palette's names.
- A role's kind, given or changed, is a category's key (else 422); left out, "build".
"""

import re
import sqlite3

from alembic import command

from tests.test_chat_flow import text
from tests.test_migration_0002 import _config
from tests.test_spawn import begin, new_role, role_id
from tests.test_team_stages_scenarios import OWN, STAGES, new_team, teams

FOUR = [{"key": "plan", "name": "Plan", "colour": "violet"},
        {"key": "build", "name": "Build", "colour": "amber"},
        {"key": "check", "name": "Check", "colour": "green"},
        {"key": "write", "name": "Write & keep up", "colour": "blue"}]
# KOLONİ's four, and after Build the three of migration 0103 (K-takim-duzen) - deleted as the user's
# are, once empty.
BUILT_IN = [*FOUR[:2], {"key": "data", "name": "Data", "colour": "teal"},
            {"key": "ml", "name": "ML", "colour": "rose"}, {"key": "ops", "name": "Ops", "colour": "olive"},
            *FOUR[2:]]
URL = "/api/categories"


def listed(client):
    return client.get(URL).json()


def add(client, name, colour="rose"):
    made = client.post(URL, json={"name": name, "colour": colour}, headers=OWN)
    assert made.status_code == 201, made.text
    return next(one for one in made.json() if one["name"] == name)


def test_the_four_built_in_categories_are_there_in_order(make_client):
    client, _ = make_client([])
    assert listed(client) == BUILT_IN


def test_a_category_is_added_renamed_recoloured_and_put_in_order_from_the_own_page(make_client):
    client, _ = make_client([])
    assert client.post(URL, json={"name": "Research", "colour": "rose"}).status_code == 403
    research = add(client, "Research")
    assert [one["name"] for one in listed(client)][-1] == "Research"
    for body in ({"name": "", "colour": "rose"}, {"name": "x" * 41, "colour": "rose"},
                 {"name": "bell\x07", "colour": "rose"}, {"name": "Ops", "colour": "pink"}):
        assert client.post(URL, json=body, headers=OWN).status_code == 422, body
    # Unique whatever its case, a built-in one's too.
    assert client.post(URL, json={"name": "research", "colour": "teal"}, headers=OWN).status_code == 409
    assert client.post(URL, json={"name": "PLAN", "colour": "teal"}, headers=OWN).status_code == 409

    write = f"{URL}/write"
    assert client.patch(write, json={"name": "Docs & upkeep"}).status_code == 403
    renamed = client.patch(write, json={"name": "Docs & upkeep", "colour": "teal"}, headers=OWN)
    assert renamed.status_code == 200, renamed.text
    assert {"key": "write", "name": "Docs & upkeep", "colour": "teal"} in renamed.json()
    assert client.patch(write, json={"name": "Plan"}, headers=OWN).status_code == 409
    assert client.patch(f"{URL}/nope", json={"name": "X"}, headers=OWN).status_code == 404

    order = [research["key"], *(one["key"] for one in BUILT_IN)]
    assert client.put(URL, json={"order": order}).status_code == 403
    assert client.put(URL, json={"order": order[:-1]}, headers=OWN).status_code == 422
    put = client.put(URL, json={"order": order}, headers=OWN)
    assert [one["key"] for one in put.json()] == order == [one["key"] for one in listed(client)]


def test_a_role_is_put_in_a_category_by_its_key_and_only_an_empty_one_goes(make_client):
    client, _ = make_client([])
    research = add(client, "Research")
    coder = f"/api/roles/{role_id(client, 'Coder')}"
    assert client.patch(coder, json={"kind": "nope"}, headers=OWN).status_code == 422
    assert client.patch(coder, json={"kind": research["key"]}, headers=OWN).status_code == 200
    # Left out, a new role's is "build".
    made = client.post("/api/roles", json={"name": "Helper", "tools": ["read_file"]}, headers=OWN)
    assert made.json()["kind"] == "build"

    gone = client.delete(f"{URL}/{research['key']}")
    assert gone.status_code == 403
    held = client.delete(f"{URL}/{research['key']}", headers=OWN)
    assert held.status_code == 409 and "Research holds 1 role: move them" in held.json()["detail"]
    assert client.patch(coder, json={"kind": "build"}, headers=OWN).status_code == 200
    assert client.delete(f"{URL}/{research['key']}", headers=OWN).status_code == 204
    assert listed(client) == BUILT_IN


def test_the_four_built_in_categories_are_renamed_but_never_deleted(make_client):
    # ("check" says who reports findings: deleting it, once empty, would end that for every reviewer.)
    client, _ = make_client([])
    for one in FOUR:
        for role in client.get("/api/roles").json():
            if role["kind"] == one["key"] and not role["name"].endswith(" lead"):
                client.patch(f"/api/roles/{role['id']}", json={"kind": "plan" if one["key"] != "plan" else "build"},
                             headers=OWN)
        refused = client.delete(f"{URL}/{one['key']}", headers=OWN)
        assert refused.status_code == 409, one
        assert "it can be renamed and recoloured, not deleted" in refused.json()["detail"]
    assert listed(client) == BUILT_IN


def test_there_are_200_categories_at_most(make_client):
    client, _ = make_client([])
    for n in range(200 - len(BUILT_IN)):
        add(client, f"C{n}")
    assert client.post(URL, json={"name": "One more", "colour": "rose"}, headers=OWN).status_code == 409


def test_a_role_an_agent_makes_lands_in_a_category_whatever_kind_it_says(make_client, wait_run, project_dir):
    client, _ = make_client([new_role("Scout", ["read_file"], kind="Ship it"), text("done")])
    cid, run_id = begin(client, project_dir, mode="full_auto")
    wait_run(client, cid, run_id)
    scout = next(r for r in client.get("/api/roles").json() if r["name"] == "Scout")
    assert scout["created_by_agent"] and scout["kind"] == "build"


def test_a_category_changes_no_teams_stages_nor_a_roles_kind(make_client):
    client, _ = make_client([])
    for key in ("plan", "build", "check", "write"):
        assert client.patch(f"{URL}/{key}", json={"name": f"Mine {key}"}, headers=OWN).status_code == 200
    # The roles keep their keys (a check role is still told the findings' format), and the
    # teams their stages; a new team's stages are named as before.
    roles = {r["name"]: r for r in client.get("/api/roles").json()}
    assert (roles["Reviewer"]["kind"], roles["Coder"]["kind"]) == ("check", "build")
    assert [s["name"] for s in teams(client)["Web app"]["stages"]] == STAGES
    assert [s["name"] for s in new_team(client)["stages"]] == STAGES


def test_migration_0079_makes_a_category_of_every_kind_a_role_has(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0078")
    kinds = {"c": "build", "s": "C#", "q": "QA/Test", "p": "Plan", "k": "lead", "l": "lead"}
    with sqlite3.connect(db) as conn:
        for at, (rid, name) in enumerate((("c", "Coder"), ("s", "Sharp"), ("q", "Checker"),
                                          ("p", "Boss"), ("k", "Captain"), ("l", "Art lead"))):
            made = f"2026-10-25 10:00:0{at}"
            conn.execute(
                "INSERT INTO roles (id, name, description, instructions, tools, builtin, "
                "created_by_agent, kind, mcp, skills, created_at, updated_at) "
                "VALUES (?, ?, '', '', '[]', 0, 0, ?, '[]', '[]', ?, ?)", (rid, name, kinds[rid], made, made))
        conn.execute("INSERT INTO teams (id, name, created_at, lead_role_id) "
                     "VALUES ('g', 'Art', '2026-10-25 10:00:00', 'l')")

    command.upgrade(cfg, "head")
    with sqlite3.connect(db) as conn:
        made = conn.execute("SELECT key, name, colour FROM categories ORDER BY position").fetchall()
        now = dict(conn.execute("SELECT id, kind FROM roles"))
    # The user's own words are categories named as they were (numbered where a name is taken),
    # under keys of their own that an address carries whole; their roles have those keys. A user's
    # role whose kind read "lead" is an ordinary role in a category named so; a team's lead is in none.
    assert made[:7] == [(c["key"], c["name"], c["colour"]) for c in BUILT_IN]
    own = {name: key for key, name, _colour in made[7:]}
    assert list(own) == ["C#", "QA/Test", "Plan 2", "lead"]
    assert all(re.fullmatch(r"[0-9a-f]{32}", key) for key in own.values())
    assert [now[rid] for rid in "csqpkl"] == ["build", own["C#"], own["QA/Test"], own["Plan 2"],
                                               own["lead"], "lead"]

    command.downgrade(cfg, "0078")
    with sqlite3.connect(db) as conn:
        assert not conn.execute(
            "SELECT name FROM sqlite_master WHERE name = 'categories'").fetchall()
        # Going back, a role has its words again (a taken name's number with them).
        back = dict(conn.execute("SELECT id, kind FROM roles"))
    assert {rid: back[rid] for rid in kinds} == {**kinds, "p": "Plan 2"}


def test_a_category_of_odd_words_is_renamed_and_deleted_by_its_key(make_client):
    # (The words "C#" or "QA/Test" in the address would reach another category, or none.)
    client, _ = make_client([])
    made = add(client, "QA/Test")
    assert re.fullmatch(r"[0-9a-f]{32}", made["key"])
    assert client.patch(f"{URL}/{made['key']}", json={"name": "C#"}, headers=OWN).status_code == 200
    assert client.delete(f"{URL}/{made['key']}", headers=OWN).status_code == 204
