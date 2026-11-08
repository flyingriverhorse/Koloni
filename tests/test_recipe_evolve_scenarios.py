"""K-evrim slice 2: a recipe step of candidates (`WhoCandidates`). Up to N agents of one role each
do the whole task their own way, each in a copy of its own seeded from the recipe's; each that
finishes is scored by the project's measure command in its copy (the last line of its output, a
number 0-100). At Full auto KOLONİ picks the best; at Ask / Auto-edit a card shows the scores and
the user picks; with no score at all there is a card at every level. The losers' copies go, the
winner's is the recipe's from then on - its Take in takes the winner's work."""

import json

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app import copies, recipe_run
from app.db.models import Agent, ConversationTeam, FileChange
from app.recipes import problems
from app.schemas import RecipeGraph, RecipeStep
from tests.conftest import Gate
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import teams_of
from tests.test_claim_scenarios import write
from tests.test_parallel import until
from tests.test_recipe_run_scenarios import answer, asked, made, recipe_named, row
from tests.test_recipes_scenarios import graph
from tests.test_recipes_scenarios import step as part
from tests.test_spawn import begin, call, step

OWN = {"Origin": "http://127.0.0.1:8790"}
MEASURE = "python measure.py"
# Its length: the longer a.py, the better. A file saying "bad" is a measure that fails.
SCRIPT = ("import sys\nsaid = open('a.py', encoding='utf-8').read()\n"
          "sys.exit(1) if 'bad' in said else print('measuring', '\\n', len(said))\n")
BUILD = part("build", "Build it", {"candidates": "Coder", "most": 2})
ONE = graph([BUILD], [("start", "build"), ("build", "end")])
TWO = step(call("spawn_agent", {"role": "Coder", "task": "write a.py"}, "c1"),
           call("spawn_agent", {"role": "Coder", "task": "write a.py"}, "c2"))


def scripts(first, second):
    """The Lead opens two Coders in one reply; "Coder" writes `first` into a.py, "Coder 2"
    `second`."""
    return {"Lead": [TWO, text("done")],
            "Coder": [step(write("a.py", first)), text("built")],
            "Coder 2": [step(write("a.py", second, id="w2")), text("built")]}


def started(client, project_dir, mode, measure=MEASURE, drawn=ONE, ready=None, approval="never"):
    (project_dir / "measure.py").write_text(SCRIPT, encoding="utf-8")
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    if measure:
        assert client.patch(f"/api/projects/{pid}", json={"measure_command": measure},
                            headers=OWN).status_code == 200
    recipe = recipe_named(client, ready) if ready else made(client, "Tries", drawn)
    return begin(client, project_dir, mode=mode, spawn_approval=approval, teams_mode="manual",
                 teams=[{"team_id": teams_of(client)["Web app"]["id"],
                         "recipe_id": recipe["id"]}])


def measures(snap):
    return [c for c in snap["commands"] if c["command"] == MEASURE]


def approve_measures(client, cid, count):
    """The measure is asked about as any command at Auto-edit: the user's yes on each card."""
    done: set[str] = set()
    while len(done) < count:
        snap = until(client, cid, lambda s: any(
            c["status"] == "proposed" and c["id"] not in done for c in s["commands"]), timeout=30)
        for one in snap["commands"]:
            if one["status"] == "proposed" and one["id"] not in done:
                assert client.post(f"/api/commands/{one['id']}/approve",
                                   json={"remember": False}).status_code == 200
                done.add(one["id"])


def scores(client, snap):
    """Each candidate's measure, by its name, as its row keeps it."""
    names = {a["id"]: a["name"] for a in snap["agents"]}
    with client.app.state.runner._factory() as session:
        (state,) = session.scalars(select(ConversationTeam.state)).all()
    return {names[a]: one for a, one in state["scores"].items()}


def leftover_copies(client):
    root = client.app.state.runner.settings.runtime_root
    return [one for held in copies.folders(root) if held.is_dir() for one in held.iterdir()]


# --- the step as drawn ---------------------------------------------------------------------------

def test_candidates_are_two_to_five_of_a_role_with_a_target_of_0_to_100():
    assert RecipeStep.model_validate(BUILD).who.most == 2
    for who in ({"candidates": "Coder", "most": 1}, {"candidates": "Coder", "most": 6},
                {"candidates": "Coder", "most": 2, "target": 101},
                {"candidates": "Coder", "most": 2, "role": "Coder"}):
        with pytest.raises(ValidationError):
            RecipeStep.model_validate(part("a", "Build it", who))
    drawn = RecipeGraph.model_validate(graph(
        [part("b", "Build it", {"candidates": "Coder", "most": 3})], [("start", "b"), ("b", "end")]))
    assert recipe_run.size(drawn, {"b": [["b", ["Coder"]]]}, "b") == 3


def test_candidates_only_do_the_work(make_client):
    # (K-tarif-kol: one step of them may be in a group - `test_recipe_branches`.)
    client, _model = make_client({})
    drawn = RecipeGraph.model_validate(graph(
        [part("b", "Build it", {"candidates": "Coder", "most": 2}, group="g"),
         part("t", "Test it", {"role": "Tester"}, group="g"),
         part("c", "Pick", {"candidates": "Nobody", "most": 2}, done_when="no_findings")],
        [("start", "g"), ("g", "c"), ("c", "end")], groups=[{"id": "g", "name": "Both"}]))
    with client.app.state.runner._factory() as session:
        said = [one["msg"] for one in problems(session, drawn, client.app.state.providers)]
    assert not any(one.startswith("Build it") for one in said)
    assert "Pick: candidates do the work; a review is a step of its own" in said
    assert "Pick: “Nobody” is no role here" in said


def test_a_candidates_copy_starts_from_the_recipes(tmp_path):
    project, runtime = tmp_path / "p", tmp_path / "rt"
    project.mkdir()
    for name, said in (("same.txt", "same"), ("changed.txt", "old"), ("gone.txt", "bye")):
        (project / name).write_text(said, encoding="utf-8")
    recipe = copies.make(project, runtime, "lead")
    (recipe.root / "changed.txt").write_text("new", encoding="utf-8")
    (recipe.root / "made.txt").write_text("made", encoding="utf-8")
    (recipe.root / "gone.txt").unlink()
    mine = copies.make(project, runtime, "cand")
    assert copies.seed(mine, recipe) == []
    assert {p: k for p, k, _s in mine.changes()} == {
        "changed.txt": "changed", "made.txt": "new", "gone.txt": "deleted"}
    assert (mine.root / "same.txt").read_text(encoding="utf-8") == "same"
    assert not (project / "made.txt").exists()  # (the project is not touched)


# --- live ---------------------------------------------------------------------------------------

def test_at_full_auto_koloni_picks_the_best_and_its_work_goes_in(make_client, wait_run, project_dir):
    client, model = make_client(scripts("x\n", "a longer one\n"))
    cid, run_id = started(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id, timeout=60)
    state = row(snap)
    assert state["status"] == "in", state
    # B-384 (R188): told with its copy to run the measure word for word (`-B` was a card)
    assert ("run the project's measure command exactly as written, adding no flags: "
            "`python measure.py`. git does not work") in str(model.calls_of["Coder"][1])
    assert (project_dir / "a.py").read_text(encoding="utf-8") == "a longer one\n"
    # Each scored in its own copy, on its own record; the strip says the best.
    assert sorted(c["status"] for c in measures(snap)) == ["exited", "exited"]
    assert {name: one["score"] for name, one in scores(client, snap).items()} == {
        "Coder": 2.0, "Coder 2": 13.0}
    assert state["steps"][0]["best"] == 13.0 and state["steps"][0]["draws"] == {"Coder": 2}
    assert leftover_copies(client) == []  # (the loser's copy went, and the recipe's)


def test_the_winners_copy_holds_the_steps_before_and_the_steps_after_work_in_it(
        make_client, wait_run, project_dir):
    drawn = graph([part("spec", "Write the spec", {"role": "Spec writer"}), BUILD,
                   part("test", "Test it", {"role": "Tester"})],
                  [("start", "spec"), ("spec", "build"), ("build", "test"), ("test", "end")])
    held = Gate()
    client, _model = make_client({
        **scripts("x", "a longer one\n"),
        "Lead": [step(call("spawn_agent", {"role": "Spec writer", "task": "spec"}, "s1")), TWO,
                 step(call("spawn_agent", {"role": "Tester", "task": "test"}, "t1")), text("done")],
        "Spec writer": [step(write("spec.md", "the spec\n", id="ws")), text("written")],
        "Tester": [step(call("read_file", {"path": "a.py"}, "rd")), held.step(text("tested"))],
    })
    cid, run_id = started(client, project_dir, "full_auto", drawn=drawn)
    held.wait_partial()
    # Picked: the recipe's copy is the one it always was - the winner's work brought into it -
    # and no candidate holds a file any more (review 2, 6).
    runner = client.app.state.runner
    snap = until(client, cid, lambda s: any(a["name"] == "Tester" for a in s["agents"]))
    ids = {a["name"]: a["id"] for a in snap["agents"]}
    lead_copy = next(a["copy"] for a in snap["agents"] if a["name"] == "Lead")
    assert runner.claims.held_by(ids["Coder"]) == runner.claims.held_by(ids["Coder 2"]) == []
    assert ids["Lead"] in runner._copies and ids["Coder 2"] not in runner._copies
    held.release()
    snap = wait_run(client, cid, run_id, timeout=60)
    assert next(a["copy"] for a in snap["agents"] if a["name"] == "Lead") == lead_copy
    assert row(snap)["status"] == "in", row(snap)
    assert (project_dir / "spec.md").read_text(encoding="utf-8") == "the spec\n"
    assert (project_dir / "a.py").read_text(encoding="utf-8") == "a longer one\n"
    # The Tester after the pick worked in the winner's copy.
    read = next(t for t in snap["tool_calls"] if t["name"] == "read_file")
    assert "a longer one" in read["result"]
    with client.app.state.runner._factory() as session:
        records = dict(session.execute(select(Agent.name, FileChange.status).join(
            Agent, Agent.id == FileChange.agent_id)).tuples().all())
    assert records == {"Spec writer": "applied", "Coder 2": "applied", "Coder": "discarded"}
    assert leftover_copies(client) == []


def test_the_ready_evolve_recipe_runs_to_its_end_once_one_reaches_its_target(
        make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [step(*(call("spawn_agent", {"role": "Coder", "task": "write a.py"}, f"c{n}")
                        for n in (1, 2, 3))), text("done")],
        "Coder": [step(write("a.py", "x" * 50)), text("built")],
        "Coder 2": [step(write("a.py", "y" * 85, id="w2")), text("built")],
        "Coder 3": [step(write("a.py", "z" * 20, id="w3")), text("built")],
    })
    cid, run_id = started(client, project_dir, "full_auto", ready="Evolve")
    snap = wait_run(client, cid, run_id, timeout=90)
    state = row(snap)
    assert (state["status"], state["recipe"]) == ("in", "Evolve"), state
    assert (project_dir / "a.py").read_text(encoding="utf-8") == "y" * 85
    # 85 reached its target of 80: no round again, and nothing missed.
    first = state["steps"][0]
    assert (first["round"], first["best"], first["missed"], first["draws"]) == (
        0, 85.0, None, {"Coder": 3})
    assert len(measures(snap)) == 3 and leftover_copies(client) == []


def test_the_winners_work_never_writes_over_what_the_recipes_copy_changed_meanwhile(tmp_path):
    project, runtime = tmp_path / "p", tmp_path / "rt"
    project.mkdir()
    (project / "a.py").write_text("a", encoding="utf-8")
    (project / "b.py").write_text("b", encoding="utf-8")
    recipe = copies.make(project, runtime, "lead")
    winner = copies.make(project, runtime, "cand")
    was = recipe.snapshot()[0]
    mine = winner.snapshot()[0]
    (winner.root / "a.py").write_text("winner a", encoding="utf-8")
    (winner.root / "b.py").write_text("winner b", encoding="utf-8")
    (winner.root / "new.py").write_text("new", encoding="utf-8")
    (recipe.root / "b.py").write_text("the Lead's b", encoding="utf-8")  # (meanwhile)
    assert copies.bring(winner, recipe, winner.moved_since(mine), was) == ["b.py"]
    assert {p: (recipe.root / p).read_text(encoding="utf-8") for p in ("a.py", "b.py", "new.py")} == {
        "a.py": "winner a", "b.py": "the Lead's b", "new.py": "new"}


def test_a_candidates_step_is_refused_in_a_job_while_the_user_is_away(
        make_client, wait_run, project_dir):
    # Review 1: a night's job has one copy for all its agents - candidates would share it.
    from tests.test_away_scenarios import ORIGIN as AWAY_ORIGIN
    from tests.test_away_scenarios import card, ended
    from tests.test_recipe_run_scenarios import recipe_named

    plan = {"jobs": [{"title": "try it", "team": "Web app", "recipe": "Tries"}]}
    client, _model = make_client({
        "Lead": [step(call("plan_away", plan)), text("card is up"), TWO, text("one done")],
        "Coder": [step(write("a.py", "a\n")), text("built")],
    })
    client.headers.update(AWAY_ORIGIN)
    made(client, "Tries", ONE)
    assert recipe_named(client, "Tries")
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={"permission_mode": "full_auto"})
    run_id = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "sleep"}).json()["run"]["id"]
    wait_run(client, cid, run_id)
    client.post(f"/api/away/{card(client, cid)['id']}/start")
    one = ended(client, pid)["jobs"][0]
    snap = client.get(f"/api/conversations/{one['conversation_id']}").json()
    said = [t["result"] for t in snap["tool_calls"] if t["name"] == "spawn_agent"]
    assert said and all("Build it: candidates need the user watching and the recipe's own copy"
                        in (one or "") for one in said), said
    assert not [a for a in snap["agents"] if a["name"].startswith("Coder")]
    assert not (project_dir / "a.py").exists()


def test_a_measure_an_agents_command_would_be_asked_about_is_asked_at_full_auto_too(
        make_client, wait_run, project_dir):
    # Review 3: one that names the project (it could reach it from the copy) is asked at every
    # level, as an agent's own run_command would be - here declined, so no score.
    client, _model = make_client(scripts("x", "ab\n"))
    named = f'python "{project_dir / "measure.py"}"'
    cid, run_id = started(client, project_dir, "full_auto", measure=named)
    for _ in range(2):
        snap = until(client, cid, lambda s: any(c["status"] == "proposed" for c in s["commands"]),
                     timeout=30)
        asked_ = next(c for c in snap["commands"] if c["status"] == "proposed")
        call_ = next(t for t in snap["tool_calls"] if t["id"] == asked_["tool_call_id"])
        assert call_["why_asked"].startswith("it names the project folder"), call_
        assert client.post(f"/api/commands/{asked_['id']}/reject").status_code == 200
    card = asked(until(client, cid, lambda s: asked(s) and "Which" in asked(s)["question"], 30))
    assert "no score (the measure command was declined)" in card["question"]
    answer(client, card, "Stop")
    wait_run(client, cid, run_id, timeout=30)


def test_at_auto_edit_the_card_ranks_them_and_the_users_pick_goes_in(
        make_client, wait_run, project_dir):
    client, _model = make_client(scripts("x", "ab\n"))
    cid, run_id = started(client, project_dir, "auto_edit")
    approve_measures(client, cid, 1)  # (asked about as any command at this level, once a run)
    snap = until(client, cid, lambda s: asked(s) and "Which candidate" in asked(s)["question"],
                 timeout=30)
    card = asked(snap)
    assert "Coder 2 (Local): 3 · Coder (Local): 1" in card["question"]
    assert card["options"] == ["Coder 2", "Coder", "Stop"]
    answer(client, card, "Coder")
    snap = until(client, cid, lambda s: asked(s) and "Ready for you" in asked(s)["question"],
                 timeout=30)
    assert not (project_dir / "a.py").exists()  # (in the recipe's copy, till Take in)
    answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id, timeout=30)
    assert (project_dir / "a.py").read_text(encoding="utf-8") == "x"
    assert row(snap)["status"] == "in"
    assert leftover_copies(client) == []


def test_a_candidate_whose_measure_fails_is_left_out(make_client, wait_run, project_dir):
    client, _model = make_client(scripts("bad and long\n", "ok\n"))
    cid, run_id = started(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id, timeout=60)
    assert (project_dir / "a.py").read_text(encoding="utf-8") == "ok\n"
    assert {name: one["why"] for name, one in scores(client, snap).items()} == {"Coder": "the measure command failed (exit code 1)", "Coder 2": None}


def test_a_lead_that_opens_one_of_three_candidates_has_koloni_open_the_other_two(
        make_client, wait_run, project_dir):
    # R169: the Lead opened one Coder, and one alone was "picked".
    client, _model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "write a.py"}, "c1")),
                 text("done")],
        "Coder": [step(write("a.py", "x")), text("built")],
        "Coder 2": [step(write("a.py", "abc", id="w2")), text("built")],
        "Coder 3": [step(write("a.py", "ab", id="w3")), text("built")],
    })
    three = graph([part("build", "Build it", {"candidates": "Coder", "most": 3})],
                  [("start", "build"), ("build", "end")])
    cid, run_id = started(client, project_dir, "full_auto", drawn=three)
    snap = wait_run(client, cid, run_id, timeout=60)
    assert row(snap)["status"] == "in", row(snap)
    assert (project_dir / "a.py").read_text(encoding="utf-8") == "abc"
    assert len(measures(snap)) == 3
    first = next(t for t in snap["tool_calls"] if t["name"] == "spawn_agent"
                 and json.loads(t["arguments"])["task"] == "write a.py")
    assert "Build it takes 3 candidates, 1 opened: KOLONİ opened 2 more Coder" in first["result"]
    tasks = [a["task"] for a in snap["agents"] if a["name"] in ("Coder 2", "Coder 3")]
    assert all(one.startswith("KOLONİ opened you as one more candidate") for one in tasks)


def test_koloni_s_candidates_do_not_wait_forever_on_one_that_broke_before_it_started(
        make_client, wait_run, project_dir):
    # (Review: the Lead's candidate broke between its opening and its start - KOLONİ's two
    # waited for it to arrive, and the turn with them.)
    client, _model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "write a.py"}, "c1")),
                 text("done")],
        "Coder 2": [step(write("a.py", "abc", id="w2")), text("built")],
        "Coder 3": [step(write("a.py", "ab", id="w3")), text("built")],
    })
    runner, handed = client.app.state.runner, []
    hand_files = runner._hand_files

    def breaks_once(*args):
        if not handed:
            handed.append(True)
            raise RuntimeError("broke before it started")
        return hand_files(*args)

    runner._hand_files = breaks_once
    three = graph([part("build", "Build it", {"candidates": "Coder", "most": 3})],
                  [("start", "build"), ("build", "end")])
    cid, run_id = started(client, project_dir, "full_auto", drawn=three)
    snap = wait_run(client, cid, run_id, timeout=60)
    ended = {a["name"]: a["status"] for a in snap["agents"] if a["name"] in ("Coder 2", "Coder 3")}
    assert ended == {"Coder 2": "completed", "Coder 3": "completed"}, snap["agents"]


@pytest.mark.parametrize(("measure", "why"), [
    ("python -c \"print('oops')\"", "no number"), (None, "no measure command")])
def test_with_no_score_the_user_is_asked_and_nothing_is_picked_blind(
        make_client, wait_run, project_dir, measure, why):
    client, _model = make_client(scripts("x\n", "ab\n"))
    cid, run_id = started(client, project_dir, "auto_edit", measure)
    if measure:
        approve_measures(client, cid, 1)
    snap = until(client, cid, lambda s: asked(s) and "Which candidate" in asked(s)["question"],
                 timeout=30)
    card = asked(snap)
    assert f"Coder (Local): no score ({why}) · Coder 2 (Local): no score ({why})" in card["question"]
    assert card["options"] == ["Coder", "Coder 2", "Stop"]
    answer(client, card, "Stop")
    snap = wait_run(client, cid, run_id, timeout=30)
    assert row(snap)["status"] == "stopped" and not (project_dir / "a.py").exists()
