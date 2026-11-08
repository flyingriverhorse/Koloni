"""K-evrim-model (the user, 5 Nov): a step of candidates says whose their models are - "auto"
(the default: the Lead gives each one, the same or not), "same" (each on the role's own) or the
user's list (candidate N on its Nth). The user's model in the recipe is their word for that run:
no card for it, paid per token or not; a paid model the Lead picks is asked about as any pick."""

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.db.models import BoardPost
from app.evolve import ROUND_RESULT, table
from app.recipes import problems
from app.schemas import RecipeGraph, RecipeStep, WhoCandidates
from tests.conftest import Gate
from tests.test_chat_flow import text
from tests.test_claim_scenarios import write
from tests.test_parallel import until
from tests.test_recipe_evolve_scenarios import MEASURE, SCRIPT, started
from tests.test_recipe_run_scenarios import made, row
from tests.test_recipes_scenarios import graph
from tests.test_recipes_scenarios import step as part
from tests.test_spawn import begin, call, step
from tests.test_team import team  # noqa: F401  (a fixture)

ORIGIN = {"Origin": "http://127.0.0.1:8790"}
WHY = "a second opinion from another model"


def drawn(models):
    return graph([part("build", "Build it", {"candidates": "Coder", "most": 2, "models": models})],
                 [("start", "build"), ("build", "end")])


def lead(first=None, second=None):
    """The Lead opens two Coders in one reply, each with the spawn arguments given."""
    return [step(call("spawn_agent", {"role": "Coder", "task": "write a.py", **(first or {})}, "c1"),
                 call("spawn_agent", {"role": "Coder", "task": "write a.py", **(second or {})}, "c2")),
            text("done")]


def coder(said, id="w1"):
    return [step(write("a.py", said, id=id)), text("built")]


def ids(team, client):  # noqa: F811
    local = client.get("/api/providers").json()[0]["id"]
    return local, team.providers["Fast"]["id"]


def agents(snap):
    """Each candidate's provider (the model it was built for is `team.asked`)."""
    return {a["name"]: a["provider_name"] for a in snap["agents"][1:]}


# --- the step as drawn ---------------------------------------------------------------------------

def test_models_are_auto_unless_said_and_a_list_has_one_a_candidate_at_most():
    build = WhoCandidates.model_validate({"candidates": "Coder", "most": 2})
    assert build.models == "auto"
    assert "models" not in build.model_dump()  # (an old recipe's file reads as it did)
    assert WhoCandidates.model_validate({"candidates": "Coder", "most": 2,
                                         "models": "same"}).models == "same"
    one = {"provider_id": "p", "model_id": "m"}
    for models in ("random", [], [one, one, one], [{"provider_id": "p", "model": "m"}]):
        with pytest.raises(ValidationError):
            RecipeStep.model_validate(part("b", "B", {"candidates": "Coder", "most": 2,
                                                      "models": models}))


def test_each_model_is_one_agents_may_use(team):  # noqa: F811
    client, _default, _fast = team([])
    local, fast = ids(team, client)
    paid = team.providers["Paid Api"]["id"]  # (not ticked for agents)
    picks = [{"provider_id": fast, "model_id": "deep"}, {"provider_id": local, "model_id": None}]
    with client.app.state.runner._factory() as session:
        assert problems(session, RecipeGraph.model_validate(drawn(picks)), client.app.state.providers) == []
        said = [one["msg"] for one in problems(session, RecipeGraph.model_validate(drawn(
            [{"provider_id": paid, "model_id": "gold"}, {"provider_id": fast, "model_id": "nope"}])),
            client.app.state.providers)]
    assert said[0] == ("Build it: candidate 1's model: its provider is gone, or agents may not "
                       "use it")
    assert said[1].startswith("Build it: candidate 2's model: Fast has no model named nope.")
    # B-388 (R183): nor one the spawn would refuse, working with tools of its own in the
    # project itself (`only_in_project`: here the Codex stub, never started in a copy).
    codex = team.providers["Codex"]["id"]
    with client.app.state.runner._factory() as session:
        said = [one["msg"] for one in problems(session, RecipeGraph.model_validate(drawn(
            [{"provider_id": local, "model_id": None}, {"provider_id": codex, "model_id": None}])),
            client.app.state.providers)]
    assert said == ["Build it: candidate 2's model: Codex works with tools of its own in the "
                    "project itself, so it can't run in a recipe's copy"]


def test_the_card_and_the_strip_say_each_ones_model():
    assert table({"Coder": 61.0, "Coder 2": 85.0}, {}, {"Coder 2": "gpt-luna", "Coder": "sonnet"}
                 ) == "Coder 2 (gpt-luna): 85 · Coder (sonnet): 61"


# --- live ---------------------------------------------------------------------------------------

def test_i_pick_each_runs_each_on_its_model_unasked_and_the_lead_cannot_change_it(
        team, wait_run, project_dir):  # noqa: F811
    # The Lead names a model for the first: left aside, and said so. Fast is paid per token and
    # no model of the Coder's: the user's pick in the recipe is their word - at Full auto with
    # spawn approval "auto" nobody is asked.
    client, _default, fast_model = team(
        {"Lead": lead({"provider": "Local", "why": WHY}), "Coder 2": coder("a longer one\n", "w2")},
        {"Coder": coder("x\n")})
    local, fast = ids(team, client)
    client.headers.update(ORIGIN)
    cid, run_id = started(client, project_dir, "full_auto", approval="auto", drawn=drawn(
        [{"provider_id": fast, "model_id": "deep"}, {"provider_id": local, "model_id": None}]))
    snap = wait_run(client, cid, run_id, timeout=60)
    assert row(snap)["status"] == "in", row(snap)
    assert snap["questions"] == []
    assert agents(snap) == {"Coder": "Fast", "Coder 2": "Local"}
    assert ("Fast", "deep") in team.asked and len(fast_model.calls) == 2
    first = next(t for t in snap["tool_calls"] if t["name"] == "spawn_agent")
    assert "provider, model and tier were left aside" in first["result"]
    coder_1 = next(a for a in snap["agents"] if a["name"] == "Coder")
    assert coder_1["chosen_why"] == "the recipe's model for candidate 1"
    # The strip says this round's, each with its model.
    assert row(snap)["steps"][0]["scores"] == "Coder 2 (Local): 13 · Coder (deep): 2"


def test_same_runs_all_on_the_roles_model_whatever_the_lead_names(
        team, wait_run, project_dir):  # noqa: F811
    client, local_model, fast_model = team(
        {"Lead": lead({"provider": "Fast", "model": "deep", "why": WHY}),
         "Coder": coder("x\n"), "Coder 2": coder("a longer one\n", "w2")})
    client.headers.update(ORIGIN)
    cid, run_id = started(client, project_dir, "full_auto", drawn=drawn("same"))
    snap = wait_run(client, cid, run_id, timeout=60)
    assert row(snap)["status"] == "in", row(snap)
    assert agents(snap) == {"Coder": "Local", "Coder 2": "Local"}
    assert not fast_model.calls
    assert any("All run on the role's own model" in str(m["content"])
               for call_ in local_model.calls_of["Lead"] for m in call_)
    first = next(t for t in snap["tool_calls"] if t["name"] == "spawn_agent")
    assert "provider, model and tier were left aside" in first["result"]


def test_auto_lets_the_leads_pick_through_and_a_paid_one_is_asked_at_full_auto(
        team, wait_run, project_dir):  # noqa: F811
    client, local_model, fast_model = team(
        {"Lead": lead({"provider": "Fast", "model": "deep", "why": WHY}),
         "Coder 2": coder("a longer one\n", "w2")},
        {"Coder": coder("x\n")})
    client.headers.update(ORIGIN)
    cid, run_id = started(client, project_dir, "full_auto", approval="auto", drawn=drawn("auto"))
    snap = until(client, cid, lambda s: any(a["status"] == "proposed" for a in s["agents"]))
    asked = next(a for a in snap["agents"] if a["status"] == "proposed")
    assert (asked["name"], asked["provider_name"], asked["model_id"]) == ("Coder", "Fast", "deep")
    assert client.post(f"/api/agents/{asked['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id, timeout=60)
    assert row(snap)["status"] == "in", row(snap)
    assert agents(snap) == {"Coder": "Fast", "Coder 2": "Local"}
    assert ("Fast", "deep") in team.asked and len(fast_model.calls) == 2
    assert any("Their models are yours to choose" in str(m["content"])
               for call_ in local_model.calls_of["Lead"] for m in call_)


def test_a_candidate_declined_at_its_card_is_said_on_the_rounds_pick_card(
        team, wait_run, project_dir):  # noqa: F811
    # B-388: one candidate fewer, for any reason, is said - here the user's no to a paid pick.
    client, _local, fast_model = team(
        {"Lead": lead({"provider": "Fast", "model": "deep", "why": WHY}),
         "Coder 2": coder("a longer one\n", "w2")})
    client.headers.update(ORIGIN)
    cid, run_id = started(client, project_dir, "full_auto", approval="auto", drawn=drawn("auto"))
    snap = until(client, cid, lambda s: any(a["status"] == "proposed" for a in s["agents"]))
    asked = next(a for a in snap["agents"] if a["status"] == "proposed")
    assert client.post(f"/api/agents/{asked['id']}/reject").status_code == 200
    snap = wait_run(client, cid, run_id, timeout=60)
    assert not fast_model.calls
    # (On any call's result: where Coder 2 finished before the no - a fast macOS runner - the pick
    # card comes on a later call than c2.)
    assert any("Coder 2 (Local): 13. Coder was not opened: it was declined. Which candidate's work "
               "goes on?" in (t["result"] or "") for t in snap["tool_calls"]), [
        t["result"] for t in snap["tool_calls"]]


def test_auto_koloni_own_candidates_follow_the_lead_onto_the_tiers_other_models(
        team, wait_run, project_dir):  # noqa: F811
    # The Lead opens one of two, on Fast · deep: KOLONİ's other takes the next balanced model.
    client, _default, _fast = team(
        {"Lead": [step(call("spawn_agent", {"role": "Coder", "task": "write a.py",
                                            "provider": "Fast", "model": "deep", "why": WHY},
                            "c1")), text("done")]},
        {"Coder": coder("x\n"), "Coder 2": coder("a longer one\n", "w2")})
    _local, fast = ids(team, client)
    client.headers.update(ORIGIN)
    assert client.patch(f"/api/providers/{fast}", json={"models": [
        {"name": "deep", "tier": "balanced"}, {"name": "quick", "tier": "balanced"}]}
    ).status_code == 200
    cid, run_id = started(client, project_dir, "full_auto", drawn=drawn("auto"))
    snap = wait_run(client, cid, run_id, timeout=60)
    assert row(snap)["status"] == "in", row(snap)
    assert agents(snap) == {"Coder": "Fast", "Coder 2": "Fast"}
    assert {("Fast", "deep"), ("Fast", "quick")} <= set(team.asked)
    other = next(a for a in snap["agents"] if a["name"] == "Coder 2")
    assert other["chosen_why"].startswith("KOLONİ's own candidate, on the next model")


def test_a_model_the_user_unticks_mid_run_is_not_opened_and_that_is_said(
        team, wait_run, project_dir):  # noqa: F811
    # The recipe started with Fast for agents; before the candidates open, the user unticks it.
    held = Gate()
    client, _default, fast_model = team(
        {"Lead": [step(call("spawn_agent", {"role": "Spec writer", "task": "spec"}, "s1")),
                  *lead()],
         "Spec writer": [held.step(step(write("spec.md", "the spec\n", id="ws"))),
                         text("written")],
         "Coder": coder("a longer one\n", "w2")})  # (the one opened, candidate 2)
    local, fast = ids(team, client)
    client.headers.update(ORIGIN)
    cid, _run_id = started(client, project_dir, "full_auto", drawn=graph(
        [part("spec", "Write the spec", {"role": "Spec writer"}),
         part("build", "Build it", {"candidates": "Coder", "most": 2, "models": [
             {"provider_id": fast, "model_id": "deep"}, {"provider_id": local, "model_id": None}]})],
        [("start", "spec"), ("spec", "build"), ("build", "end")]))
    held.wait_partial()
    assert client.patch(f"/api/providers/{fast}", json={"for_agents": False}).status_code == 200
    held.release()
    snap = until(client, cid, lambda s: any(
        t["provider_call_id"] == "c1" and t["status"] == "failed" for t in s["tool_calls"]),
        timeout=30)
    first = next(t for t in snap["tool_calls"] if t["provider_call_id"] == "c1")
    assert ("not opened: the recipe's model for candidate 1 cannot be had now (its provider is "
            "gone, or agents may not use it)") in first["result"]
    assert not fast_model.calls
    # B-388 (R183): the round's card and its note say why one candidate is on them, not two.
    snap = wait_run(client, cid, _run_id, timeout=60)
    unopened = ("Coder was not opened: the recipe's model for candidate 1 cannot be had now (its "
                "provider is gone, or agents may not use it) - the user changes it on the Agents "
                "page (Recipes)")
    second = next(t for t in snap["tool_calls"] if t["provider_call_id"] == "c2")
    # (The card, at Full auto KOLONİ's word on it.)
    assert f"Coder (Local): 13. {unopened}. Which candidate's work goes on?" in second["result"]
    with client.app.state.runner._factory() as session:
        (note,) = session.scalars(select(BoardPost.content).where(
            BoardPost.koloni, BoardPost.content.startswith(ROUND_RESULT))).all()
    assert note.endswith(f"\n- {unopened}")


def test_a_recipe_the_lead_picked_is_no_word_of_the_users_its_pick_is_asked(
        team, wait_run, project_dir):  # noqa: F811
    # Lead decides: the Lead attaches an "I pick each" recipe with Fast (paid per token) - its
    # entry is still the candidate's, but asked as the Lead's own pick at Full auto.
    client, _default, _fast = team(
        {"Lead": [step(call("pick_teams", {"teams": [
            {"team": "Web app", "recipe": "Tries", "why": "it builds"}]}, "p1")), *lead()],
         "Coder 2": coder("a longer one\n", "w2")},
        {"Coder": coder("x\n")})
    local, fast = ids(team, client)
    client.headers.update(ORIGIN)
    (project_dir / "measure.py").write_text(SCRIPT, encoding="utf-8")
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={"measure_command": MEASURE}).status_code == 200
    made(client, "Tries", drawn(
        [{"provider_id": fast, "model_id": "deep"}, {"provider_id": local, "model_id": None}]))
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="auto",
                        teams_mode="lead")
    snap = until(client, cid, lambda s: any(a["status"] == "proposed" for a in s["agents"]),
                 timeout=30)
    asked = next(a for a in snap["agents"] if a["status"] == "proposed")
    assert (asked["name"], asked["provider_name"]) == ("Coder", "Fast")
    assert asked["chosen_why"].startswith("the recipe's model for candidate 1")
    # (Each of its entries is the Lead's pick: Coder 2's on Local is asked too.)
    for name in ("Coder", "Coder 2"):
        snap = until(client, cid, lambda s, name=name: any(
            a["name"] == name and a["status"] == "proposed" for a in s["agents"]), timeout=30)
        one = next(a for a in snap["agents"] if a["name"] == name)
        assert client.post(f"/api/agents/{one['id']}/approve").status_code == 200
    assert row(wait_run(client, cid, run_id, timeout=60))["status"] == "in"


def test_auto_koloni_own_candidates_take_no_paid_model_the_roles_own_is_not(
        team, wait_run, project_dir):  # noqa: F811
    # The ladder: Local · big-model, then Fast · quick (paid per token). The Lead names Local's:
    # KOLONİ's other is not moved onto Fast - it runs on the role's own.
    client, _default, fast_model = team(
        {"Lead": [step(call("spawn_agent", {"role": "Coder", "task": "write a.py",
                                            "provider": "Local", "model": "big-model",
                                            "why": WHY}, "c1")), text("done")],
         "Coder": coder("x\n"), "Coder 2": coder("a longer one\n", "w2")})
    local, fast = ids(team, client)
    client.headers.update(ORIGIN)
    for one, name in ((local, "big-model"), (fast, "quick")):
        assert client.patch(f"/api/providers/{one}", json={"models": [
            {"name": name, "tier": "balanced"}]}).status_code == 200
    cid, run_id = started(client, project_dir, "full_auto", drawn=drawn("auto"))
    snap = wait_run(client, cid, run_id, timeout=60)
    assert row(snap)["status"] == "in", row(snap)
    assert agents(snap) == {"Coder": "Local", "Coder 2": "Local"} and not fast_model.calls
