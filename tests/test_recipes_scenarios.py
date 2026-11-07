"""Slice 84a's acceptance set: recipes - the steps of a piece of work, drawn on the Agents page's
Recipes tab, checked by the server as they are saved, three of them ready. Running one is 84b's.
Written before the code.

Design: `tasarim/specs/2026-10-23-dilim-63-84-takimlar-tarifler-design.md` §1, §2 (Recipes), §6
item 3, §7, §9; a folder's own recipes in its `.koloni/recipes/` (86's design §4).

Contract:
- A recipe's `graph` (version 1): `steps` ({"id", "name", "who", "done_when", "if_fails",
  "ask_me", "group"}), `groups` (steps that run all at once), `ends` ({"id", "then": "in" |
  "report"}), `arrows` ({"from", "to"}; "start" is the user's message) and `loops` ({"from",
  "to", "rounds"}). Who is {"role": name}, {"team": name} (its stages) or {"lead": true}.
- `GET /api/recipes[?project_id=]` -> {"recipes": [...], "broken": [lines], "writer": {"why"}}:
  KOLONİ's own (the three ready ones, Feature, Bugfix and Review only, first) and, with a
  project, its folder's `.koloni/recipes/*.json`; "writer" says why "Or write it" cannot ask
  the Lead's model (null: it can).
- `POST /api/recipes`, `PUT` / `DELETE /api/recipes/{id}`: the user's, from the app's own page.
  A ready one is neither changed nor deleted (409): it is copied. A name is one recipe's (409).
- Saved only when it holds: a start and an end, every step reached, a round limit on every
  loop, every Who an existing role or team or the Lead. A 422 says what, at which step
  (`detail`: [{"loc", "msg", "at": node id}]).
- `POST /api/projects/{pid}/recipes`, `PUT` / `DELETE .../recipes/{file}`: a recipe kept in the
  folder's `.koloni/recipes/<file>.json`, written by the page alone; a broken file is said.
- `POST /api/recipes/draft` {"text"}: the Lead's model asked once for a recipe's draft
  ({"name", "graph"}); nothing is saved.
- A team's `default_recipe_id` (one of KOLONİ's recipes) is set with `PATCH /api/teams/{id}`;
  kept only, 84b uses it. A recipe deleted leaves no team with it.
"""

import json
import sys

import pytest
from sqlalchemy import delete

from app.db import models

if not hasattr(models, "Recipe"):  # written before the code: skipped until it exists
    pytest.skip("slice 84a is not built yet", allow_module_level=True)

from tests.test_agent_writes import wait_status, write  # noqa: E402
from tests.test_chat_flow import start_in_mode, text  # noqa: E402
from tests.test_outside_folders_scenarios import junction  # noqa: E402
from tests.test_team import team  # noqa: E402, F401  (a fixture)
from tests.test_tier_scenarios import ORIGIN, tiered  # noqa: E402

OWN = {"Origin": ORIGIN}
END = {"id": "end", "then": "in"}


def graph(steps, arrows, loops=(), groups=(), ends=(END,)):
    return {"version": 1, "steps": list(steps), "groups": list(groups), "ends": list(ends),
            "arrows": [{"from": a, "to": b} for a, b in arrows], "loops": list(loops)}


def step(id, name, who=None, **more):
    # (Whole, as the server gives it back.)
    return {"id": id, "name": name, "who": who or {"lead": True}, "done_when": "done",
            "if_fails": "ask", "ask_me": False, "group": None, **more}


# Build it, review it, back to the build at most twice, then ask me before it goes in.
SMALL = graph(
    [step("a", "Build it", {"role": "Coder"}),
     step("b", "Review it", {"role": "Reviewer"}, done_when="no_findings")],
    [("start", "a"), ("a", "b"), ("b", "end")],
    loops=[{"from": "b", "to": "a", "rounds": 2}],
)


def listed(client, **params):
    answer = client.get("/api/recipes", params=params)
    assert answer.status_code == 200, answer.text
    return answer.json()


def by_name(client, **params):
    return {r["name"]: r for r in listed(client, **params)["recipes"]}


def save(client, name, body, **more):
    return client.post("/api/recipes", json={"name": name, "graph": body, **more}, headers=OWN)


def problems(answer):
    assert answer.status_code == 422, answer.text
    return {(p.get("at"), p["msg"]) for p in answer.json()["detail"]}


# --- ready recipes -------------------------------------------------------------------------------


def test_three_ready_recipes_come_first_and_hold(make_client):
    client, _ = make_client([])
    recipes = listed(client)["recipes"]
    assert [r["name"] for r in recipes[:3]] == ["Feature", "Bugfix", "Review only"]
    assert all(r["ready"] and r["project_id"] is None for r in recipes[:3])
    feature = recipes[0]["graph"]
    # The user's flow: spec, build, four reviews at once, at most two rounds of fixes, ask me.
    (reviews,) = feature["groups"]
    assert len([s for s in feature["steps"] if s["group"] == reviews["id"]]) == 4
    assert [(loop["to"], loop["rounds"]) for loop in feature["loops"]] == [("build", 2)]
    assert [end["then"] for end in feature["ends"]] == ["in"]
    review_only = recipes[2]["graph"]
    assert [end["then"] for end in review_only["ends"]] == ["report"]
    # Each one would be saved as it is: it passes the server's own check.
    for ready in recipes[:3]:
        copy = save(client, f"{ready['name']} copy", ready["graph"])
        assert copy.status_code == 201, copy.text
        assert copy.json()["ready"] is False


def test_a_ready_recipe_is_copied_never_changed_or_deleted(make_client):
    client, _ = make_client([])
    feature = by_name(client)["Feature"]
    changed = client.put(f"/api/recipes/{feature['id']}",
                         json={"name": "Feature", "graph": SMALL}, headers=OWN)
    assert changed.status_code == 409 and "copy" in changed.json()["detail"]
    assert client.delete(f"/api/recipes/{feature['id']}", headers=OWN).status_code == 409
    assert by_name(client)["Feature"]["graph"] == feature["graph"]


# --- the user's recipes --------------------------------------------------------------------------


def test_a_drawn_recipe_is_saved_changed_and_deleted_from_the_page_alone(make_client):
    client, _ = make_client([])
    assert client.post("/api/recipes", json={"name": "Mine", "graph": SMALL}).status_code == 403
    made = save(client, "Mine", SMALL)
    assert made.status_code == 201, made.text
    mine = made.json()
    assert (mine["name"], mine["ready"], mine["graph"]) == ("Mine", False, SMALL)
    assert save(client, "mine", SMALL).status_code == 409  # one recipe a name
    assert save(client, "Feature", SMALL).status_code == 409
    renamed = client.put(f"/api/recipes/{mine['id']}", json={"name": "Mine too", "graph": SMALL},
                         headers=OWN)
    assert renamed.status_code == 200 and renamed.json()["name"] == "Mine too"
    assert client.delete(f"/api/recipes/{mine['id']}").status_code == 403
    assert client.delete(f"/api/recipes/{mine['id']}", headers=OWN).status_code == 204
    assert "Mine too" not in by_name(client)


def test_a_recipe_needs_a_start_and_an_end_and_every_step_reached(make_client):
    client, _ = make_client([])
    found = problems(save(client, "Broken", graph(
        [step("a", "Build it"), step("b", "Lost one")], [("a", "end")], ends=())))
    assert ("start", "Your message leads nowhere: draw an arrow from it to the first step") in found
    assert (None, "The recipe has no end: add one (+ Ask me)") in found
    assert ("b", "Lost one is not reached from Your message") in found
    # An arrow to an end that is not drawn: said, not taken for one.
    found = problems(save(client, "Broken", graph([step("a", "Build it")], [("start", "a")])
                          | {"arrows": [{"from": "start", "to": "a"}, {"from": "a", "to": "x"}],
                             "ends": []}))
    assert any(at == "a" and "x" in msg for at, msg in found)


def test_a_step_with_no_name_is_said_with_the_rest_that_keeps_it_from_running(make_client):
    # R57 (small): the request's own check said the empty name alone; the others came only after it.
    client, _ = make_client([])
    found = problems(save(client, "Nameless", graph(
        [step("a", " "), step("b", "Lost one")], [("start", "a"), ("a", "end")])))
    assert ("a", "A step's name is 1 to 60 printable characters") in found
    assert ("b", "Lost one is not reached from Your message") in found
    # two of them: each said so, and not as two steps of one name
    found = problems(save(client, "Nameless", graph(
        [step("a", ""), step("b", "")], [("start", "a"), ("a", "b"), ("b", "end")])))
    assert sorted(found) == [("a", "A step's name is 1 to 60 printable characters"),
                             ("b", "A step's name is 1 to 60 printable characters")]


def test_every_loop_has_a_round_limit_of_one_to_five(make_client):
    client, _ = make_client([])
    no_limit = {**SMALL, "loops": [{"from": "b", "to": "a"}]}
    assert ("b", "Review it: its loop back to Build it has no round limit (1 to 5)") in problems(
        save(client, "Loops", no_limit))
    too_many = {**SMALL, "loops": [{"from": "b", "to": "a", "rounds": 6}]}
    assert save(client, "Loops", too_many).status_code == 422


def test_every_who_is_a_role_or_team_here_or_the_lead(make_client):
    client, _ = make_client([])
    body = graph([step("a", "Build it", {"role": "Wizard"}), step("b", "Check it", {"team": "Nope"}),
                  step("c", "Lead it", {"role": "Lead"}), step("d", "Team", {"team": "Web app"})],
                 [("start", "a"), ("a", "b"), ("b", "c"), ("c", "d"), ("d", "end")])
    found = problems(save(client, "Who", body))
    assert ("a", "Build it: “Wizard” is no role here") in found
    assert ("b", "Check it: “Nope” is no team here") in found
    assert ("c", "Lead it: “Lead” is no role here") in found  # the Lead picks: {"lead": true}
    assert not any(at == "d" for at, _ in found)
    # A team's lead runs its team: no step names it.
    body["steps"][2]["who"] = {"role": "Web app lead"}
    assert ("c", "Lead it: “Web app lead” is no role here") in problems(save(client, "Who", body))


def test_steps_at_the_same_time_go_on_together(make_client):
    client, _ = make_client([])
    body = graph(
        [step("a", "Build it", {"role": "Coder"}),
         step("r1", "Code review", {"role": "Reviewer"}, group="g"),
         step("r2", "Security review", {"role": "Security reviewer"}, group="g")],
        [("start", "a"), ("a", "g"), ("g", "end")],
        loops=[{"from": "g", "to": "a", "rounds": 1}],
        groups=[{"id": "g", "name": "All at once, wait for all"}],
    )
    assert save(client, "Together", body).status_code == 201
    # A step of a group goes on with its group, and a group holds a step.
    body["arrows"].append({"from": "r1", "to": "end"})
    body["groups"].append({"id": "h", "name": "Empty"})
    body["arrows"].append({"from": "a", "to": "h"})
    found = problems(save(client, "Together 2", body))
    assert ("r1", "Code review goes on with its group, not by an arrow of its own") in found
    assert ("h", "Empty has no step") in found


def test_an_arrow_back_is_a_loop_with_no_limit_and_refused(make_client):
    client, _ = make_client([])
    body = {**SMALL, "loops": [], "arrows": [{"from": a, "to": b} for a, b in (
        ("start", "a"), ("a", "b"), ("b", "a"), ("b", "end"))]}
    assert ("b", "Review it: its arrow back to Build it makes a loop with no round limit; use "
                 "Loop back") in problems(save(client, "Circle", body))


def test_a_loop_goes_back_once_from_a_part_and_never_inside_its_own_group(make_client):
    client, _ = make_client([])
    found = problems(save(client, "L", {**SMALL, "loops": [{"from": "a", "to": "b", "rounds": 2}]}))
    assert ("a", "Build it: its loop goes forward to Review it; a loop goes back") in found
    found = problems(save(client, "L", {**SMALL, "loops": [{"from": "b", "to": "b", "rounds": 2}]}))
    assert ("b", "Review it: its loop goes back to itself") in found
    found = problems(save(client, "L", {**SMALL, "loops": [
        {"from": "b", "to": "a", "rounds": 1}, {"from": "b", "to": "a", "rounds": 2}]}))
    assert ("b", "Review it has two loops back; keep one") in found
    found = problems(save(client, "L", {**SMALL, "arrows": [*SMALL["arrows"],
                                                             {"from": "a", "to": "b"}]}))
    assert ("a", "Build it: two arrows to Review it") in found
    together = graph(
        [step("a", "Build it"), step("r1", "Code review", group="g"),
         step("r2", "UI review", group="g")],
        [("start", "a"), ("a", "g"), ("g", "end")],
        loops=[{"from": "r1", "to": "r2", "rounds": 1}],
        groups=[{"id": "g", "name": "At once"}],
    )
    found = problems(save(client, "L", together))
    assert ("r1", "Code review: its loop back stays inside its group") in found
    together["loops"] = [{"from": "r1", "to": "g", "rounds": 1}]
    assert ("r1", "Code review: its loop back stays inside its group") in problems(
        save(client, "L", together))
    together["loops"] = [{"from": "r1", "to": "a", "rounds": 1}]  # back out of it: a loop
    assert save(client, "L", together).status_code == 201


def test_every_step_leads_to_an_end(make_client):
    client, _ = make_client([])
    body = graph([step("a", "Build it"), step("b", "Lost one")],
                 [("start", "a"), ("start", "b"), ("a", "end")])
    found = problems(save(client, "Dead", body))
    assert ("b", "Lost one leads to no end") in found
    assert not any(at == "a" for at, _ in found)


def test_two_steps_of_one_name_are_refused_each_at_its_step(make_client):
    """B-108: two "New step"s were saved; which one the recipe means would not be told."""
    client, _ = make_client([])
    body = graph([step("a", "Review it"), step("b", "review  it")],
                 [("start", "a"), ("a", "b"), ("b", "end")])
    assert problems(save(client, "Twice", body)) == {
        ("a", "Two steps are named Review it: give each its own name"),
        ("b", "Two steps are named review it: give each its own name")}


def test_a_drawing_is_kept_as_drawn(make_client):
    client, _ = make_client([])
    odd = {**SMALL, "steps": [{**SMALL["steps"][0], "colour": "red"}, SMALL["steps"][1]]}
    assert save(client, "Odd", odd).status_code == 422  # nothing but what a recipe holds
    assert save(client, "Old", {**SMALL, "version": 2}).status_code == 422


def test_where_a_part_was_dragged_is_kept_and_only_a_number_on_the_board(make_client):
    # K-tarif-surukle: a step, group or end may say where the user put it; one that says
    # nothing (an old recipe) is given back as it was, with no pos.
    client, _ = make_client([])
    a, b = SMALL["steps"]
    placed = {**SMALL, "steps": [{**a, "pos": {"x": 12, "y": -40.5}}, b],
              "ends": [{**END, "pos": {"x": 0, "y": 300}}]}
    made = save(client, "Placed", placed)
    assert made.status_code == 201, made.text
    assert made.json()["graph"] == {**placed, "steps": [{**a, "pos": {"x": 12.0, "y": -40.5}}, b],
                                    "ends": [{**END, "pos": {"x": 0.0, "y": 300.0}}]}
    assert save(client, "Old one", SMALL).json()["graph"] == SMALL
    for bad in ({"x": "12", "y": 0}, {"x": True, "y": 0}, {"x": 1e6, "y": 0}, {"x": 0},
                {"x": 0, "y": 0, "z": 0}, [0, 0]):
        odd = {**SMALL, "steps": [{**a, "pos": bad}, b]}
        assert save(client, f"Odd {bad}", odd).status_code == 422, bad
    # NaN and Infinity, which no JSON encoder writes but a hand-made body can hold.
    for word in ("NaN", "Infinity", "-Infinity"):
        body = json.dumps({"name": "Odd", "graph": placed}).replace('"x": 12,', f'"x": {word},')
        assert word in body
        sent = client.post("/api/recipes", content=body, headers={
            **OWN, "Content-Type": "application/json"})
        assert sent.status_code == 422, word


# --- a folder's own recipes ----------------------------------------------------------------------


def test_a_recipe_kept_in_the_folder_is_written_read_and_removed(make_client, project_dir):
    client, _ = make_client([])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert not (project_dir / ".koloni").exists()  # opening a folder writes nothing
    path = f"/api/projects/{pid}/recipes"
    assert client.post(path, json={"name": "Ship it", "graph": SMALL}).status_code == 403
    made = client.post(path, json={"name": "Ship it", "graph": SMALL}, headers=OWN)
    assert made.status_code == 201, made.text
    assert (made.json()["project_id"], made.json()["file"]) == (pid, "ship-it")
    kept = project_dir / ".koloni" / "recipes" / "ship-it.json"
    assert json.loads(kept.read_text(encoding="utf-8")) == {"name": "Ship it", "graph": SMALL}
    assert client.post(path, json={"name": "Ship  IT", "graph": SMALL},
                       headers=OWN).status_code == 409  # the same file
    # Not every folder's: listed with this project only.
    assert "Ship it" in by_name(client, project_id=pid) and "Ship it" not in by_name(client)
    # Checked as KOLONİ's own are.
    assert client.post(path, json={"name": "Bad", "graph": {**SMALL, "arrows": []}},
                       headers=OWN).status_code == 422
    changed = client.put(f"{path}/ship-it", json={"name": "Ship it now", "graph": SMALL},
                         headers=OWN)
    assert changed.status_code == 200 and changed.json()["name"] == "Ship it now"
    assert client.delete(f"{path}/ship-it", headers=OWN).status_code == 204
    assert not (project_dir / ".koloni").exists()


def test_a_broken_recipe_file_is_said_and_not_used(make_client, project_dir):
    client, _ = make_client([])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    folder = project_dir / ".koloni" / "recipes"
    folder.mkdir(parents=True)
    (folder / "broken.json").write_text("{not json", encoding="utf-8")
    (folder / "wrong.json").write_text(json.dumps({"name": "Wrong", "graph": {"version": 9}}),
                                       encoding="utf-8")
    (folder / "good.json").write_text(json.dumps({"name": "Good", "graph": SMALL}),
                                      encoding="utf-8")
    (folder / "notes.txt").write_text("not a recipe", encoding="utf-8")
    read = listed(client, project_id=pid)
    assert [r["name"] for r in read["recipes"] if r["project_id"]] == ["Good"]
    assert len(read["broken"]) == 2
    assert all(line.startswith(".koloni/recipes/") and " is not read - " in line
               for line in read["broken"])


def test_a_file_the_page_could_not_change_is_said_not_listed(make_client, project_dir):
    client, _ = make_client([])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    folder = project_dir / ".koloni" / "recipes"
    folder.mkdir(parents=True)
    whole = json.dumps({"name": "Fine", "graph": SMALL})
    for name in ("Foo Bar.json", ".json", "Ship-It.json"):
        (folder / name).write_text(whole, encoding="utf-8")
    (folder / "huge.json").write_text(" " * (300 * 1024) + whole, encoding="utf-8")
    read = listed(client, project_id=pid)
    assert [r for r in read["recipes"] if r["project_id"]] == []
    named = [line for line in read["broken"] if "its file name is not letters, digits and dashes"
             in line]
    assert len(named) == 3
    assert any(line.startswith(".koloni/recipes/huge.json") and "larger than 256 KiB" in line
               for line in read["broken"])


@pytest.mark.parametrize("name", ["CON", "nul", "Com1", "LPT¹"])
def test_a_name_windows_keeps_for_a_device_is_said(make_client, project_dir, name):
    client, _ = make_client([])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    made = client.post(f"/api/projects/{pid}/recipes", json={"name": name, "graph": SMALL},
                       headers=OWN)
    assert made.status_code == 422 and "Windows keeps" in made.json()["detail"]


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are Windows'")
def test_a_recipes_folder_that_leads_elsewhere_is_said(make_client, project_dir, tmp_path):
    client, _ = make_client([])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "x.json").write_text(json.dumps({"name": "Far", "graph": SMALL}),
                                      encoding="utf-8")
    (project_dir / ".koloni").mkdir()
    junction(project_dir / ".koloni" / "recipes", elsewhere)
    read = listed(client, project_id=pid)
    assert [r for r in read["recipes"] if r["project_id"]] == []
    assert len(read["broken"]) == 1 and read["broken"][0].startswith(".koloni/recipes is not read")


def test_an_agent_never_writes_a_recipe_into_the_folder_unasked(make_client, project_dir):
    client, _ = make_client([write(".koloni/recipes/x.json", "{}\n"), text("Done.")])
    cid, _run_id = start_in_mode(client, project_dir, "full_auto")
    change = wait_status(client, cid, "waiting_approval")["file_changes"][0]
    assert (change["status"], change["path"]) == ("proposed", ".koloni/recipes/x.json")
    assert not (project_dir / ".koloni").exists()


@pytest.mark.parametrize("name", ["../../x", "..", "con", "a/b"])
def test_a_recipes_name_never_leaves_the_folder(make_client, project_dir, name):
    client, _ = make_client([])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    made = client.post(f"/api/projects/{pid}/recipes", json={"name": name, "graph": SMALL},
                       headers=OWN)
    if made.status_code == 201:
        assert (project_dir / ".koloni" / "recipes" / f"{made.json()['file']}.json").is_file()
    else:
        assert made.status_code == 422
    assert not list(project_dir.parent.glob("*.json")) and not list(project_dir.glob("*.json"))
    assert not list((project_dir / ".koloni").glob("*.json"))
    assert client.put(f"/api/projects/{pid}/recipes/..%2F..%2Fx", json={
        "name": "x", "graph": SMALL}, headers=OWN).status_code in (404, 405, 422)


# --- "Or write it" -------------------------------------------------------------------------------


DRAWN = {"name": "Spec then code", "graph": graph(
    [step("s", "Write the spec", {"role": "Spec writer"}, ask_me=True),
     step("c", "Code it", {"role": "Coder"})],
    [("start", "s"), ("s", "c"), ("c", "end")])}


def test_or_write_it_asks_the_leads_model_once_and_saves_nothing(make_client):
    client, model = make_client([text(f"Here it is:\n```json\n{json.dumps(DRAWN)}\n```")])
    assert listed(client)["writer"]["why"] is None
    sentence = "First the spec writer, then the coder; ask me before it goes in."
    assert client.post("/api/recipes/draft", json={"text": sentence}).status_code == 403
    before = len(by_name(client))
    drawn = client.post("/api/recipes/draft", json={"text": sentence}, headers=OWN)
    assert drawn.status_code == 200, drawn.text
    assert (drawn.json()["name"], drawn.json()["graph"]) == (DRAWN["name"], DRAWN["graph"])
    assert drawn.json()["model_id"] == "fake-model" and drawn.json()["provider_name"]
    assert len(model.calls) == 1
    asked = str(model.calls[0])
    # The sentence as data, the roles and teams it may name.
    assert json.dumps(sentence) in asked and "Spec writer" in asked and "Web app" in asked
    assert len(by_name(client)) == before


def test_or_write_it_asks_the_first_balanced_model_and_keeps_the_loops_named(team):  # noqa: F811
    """B-69: drawn by the strongest model, and "at most 2 rounds back to Coder" left out."""
    client, default, fast = team([], [text(json.dumps(DRAWN))])
    tiered(team, client)  # balanced: Fast · deep
    drawn = client.post("/api/recipes/draft", json={"text": "Coder, then Reviewer, at most 2 "
                                                     "rounds back to Coder"}, headers=OWN)
    assert drawn.status_code == 200, drawn.text
    assert (drawn.json()["provider_name"], drawn.json()["model_id"]) == ("Fast", "deep")
    assert default.calls == [] and len(fast.calls) == 1
    assert "each loop the sentence names" in str(fast.calls[0])


def test_or_write_it_may_draw_a_role_step_of_more_than_one(make_client):
    """K-rol-cogul: "at most N" of a role (`most`) is told, and a draft with it is read."""
    two = {"name": "Two coders", "graph": graph([step("c", "Code it", {"role": "Coder", "most": 2})],
                                                [("start", "c"), ("c", "end")])}
    client, model = make_client([text(json.dumps(two))])
    drawn = client.post("/api/recipes/draft", json={"text": "two coders at once, each a part"},
                        headers=OWN)
    assert drawn.status_code == 200, drawn.text
    assert drawn.json()["graph"]["steps"][0]["who"] == {"role": "Coder", "most": 2}
    assert '"most": 2 to 5' in model.calls[0][0]["content"]


def test_an_answer_that_is_no_recipe_is_said(make_client):
    client, _ = make_client([text("I would start with a spec.")])
    drawn = client.post("/api/recipes/draft", json={"text": "do it well"}, headers=OWN)
    assert drawn.status_code == 502 and "not a recipe" in drawn.json()["detail"]


def test_with_no_model_the_lead_may_run_on_or_write_it_says_why(make_client):
    client, model = make_client([text("never")])
    local = client.get("/api/providers").json()[0]
    assert client.patch(f"/api/providers/{local['id']}", json={
        "models": [{"name": "other"}], "only_listed": True}, headers=OWN).status_code == 200
    why = listed(client)["writer"]["why"]
    assert why and "Models page" in why
    drawn = client.post("/api/recipes/draft", json={"text": "do it"}, headers=OWN)
    assert drawn.status_code == 409 and drawn.json()["detail"] == why
    assert model.calls == []


def test_with_no_provider_at_all_or_write_it_says_why(make_client):
    client, model = make_client([text("never")])
    # (The page keeps the last provider; a new install may have none yet.)
    with client.app.state.session_factory() as session:
        session.execute(delete(models.Provider))
        session.commit()
    why = listed(client)["writer"]["why"]
    assert why == "There is no model to ask: add a provider on the Models page."
    drawn = client.post("/api/recipes/draft", json={"text": "do it"}, headers=OWN)
    assert drawn.status_code == 409 and drawn.json()["detail"] == why
    assert model.calls == []


# --- a team's default recipe ---------------------------------------------------------------------


def test_a_teams_default_recipe_is_kept_and_goes_with_the_recipe(make_client):
    client, _ = make_client([])
    # (Every ready team has a default since 0103: a team of the user's own has none.)
    web = client.post("/api/teams", json={"name": "Art"}, headers=OWN).json()
    assert web["default_recipe_id"] is None
    mine = save(client, "Mine", SMALL).json()
    set_ = client.patch(f"/api/teams/{web['id']}", json={"default_recipe_id": mine["id"]},
                        headers=OWN)
    assert set_.status_code == 200 and set_.json()["default_recipe_id"] == mine["id"]
    # Its other settings are left as they were, and an unknown recipe is not one.
    renamed = client.patch(f"/api/teams/{web['id']}", json={"lead_on": False}, headers=OWN)
    assert renamed.json()["default_recipe_id"] == mine["id"]
    assert client.patch(f"/api/teams/{web['id']}", json={"default_recipe_id": "nope"},
                        headers=OWN).status_code == 422
    assert client.delete(f"/api/recipes/{mine['id']}", headers=OWN).status_code == 204
    web = next(t for t in client.get("/api/teams").json() if t["name"] == "Art")
    assert web["default_recipe_id"] is None
    feature = by_name(client)["Feature"]
    client.patch(f"/api/teams/{web['id']}", json={"default_recipe_id": feature["id"]}, headers=OWN)
    cleared = client.patch(f"/api/teams/{web['id']}", json={"default_recipe_id": None},
                           headers=OWN)
    assert cleared.json()["default_recipe_id"] is None
