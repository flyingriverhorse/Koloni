"""Slice 84b-2's acceptance set: a chat's teams run by their recipes. Written before the code.

Design: `tasarim/specs/2026-10-23-dilim-63-84-takimlar-tarifler-design.md` §3, §4, §5 (M, N), §7
"Satır durumu (84b)".

Contract:
- A chat team's row with a recipe (its own, else its team's default) runs it in the turn: the Lead
  - beside another team, the team's lead - opens each step's roles itself with spawn_agent, and
  the server keeps it to the step: spawn_agent opens only the current step's roles (the step's,
  not the team's: a recipe may name a role of another team), refused with the recipe and its step
  named. The recipe is checked again as it starts (`app.recipes.problems`); one that cannot run
  is refused with why.
- A step is done when each of its roles has an agent that finished; an "all at once" group when
  all of its steps are. A review step (done when "no findings") whose report leaves findings goes
  back along its loop while rounds are left, else on: what is left goes to the user.
- "Ask me" on a step: KOLONİ's question card ("Go on" / "Stop") in the spawn call that finished
  it. An "in" end: one card for all the chat's teams, "Ready for you" ("Take in" / "Ask for
  changes"). Until Take in, the recipe's agents work in one working copy, nothing of it in the
  project; Take in takes it in.
- The row's `state` on the conversation: {"run_id", "team", "recipe", "status" (running / ready / done /
  in / failed / stopped / interrupted), "why", "steps": [{"id", "name", "state": done|now|next,
  "round"}], "agents": [ids]}. A failed step whose if_fails is "ask": "Try again" / "Skip" /
  "Stop". "Ask for changes" - or the user's own words - sends the rows back to their loop's step.
- Two or more rows: each team's lead (`lead_on`) is opened by the Lead and runs its row; the Lead
  opens only the leads (and the steps of a team whose lead is off).
- `POST /api/conversations/{id}/teams/{team_id}/stop` (the app's own page): that team's agents
  stop at their next step, its row "stopped"; the other teams go on.
- A restart: a row that was running says "Interrupted by a server restart".
"""

import pytest

from app.agent import recover_interrupted
from app.db.models import ConversationTeam, Team
from app.db.session import make_engine, make_session_factory, upgrade_db
from app.model_client import ModelUnavailable
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import OWN, teams_of
from tests.test_claim_scenarios import write
from tests.test_discussion import discuss
from tests.test_limits_scenarios import provider
from tests.test_parallel import until
from tests.test_recipes_scenarios import graph
from tests.test_recipes_scenarios import step as part
from tests.test_recovery import seed
from tests.test_spawn import begin, call, role_id, spawn, step

READY = "Ready for you"
FOUND = "Found one.\n\n## Findings\n- greet says Helo | kind: code | role: Coder\n"
NONE = "Fine.\n\nChecked: read greet.py\n\nFindings: none"


def made(client, name, drawn):
    saved = client.post("/api/recipes", json={"name": name, "graph": drawn}, headers=OWN)
    assert saved.status_code == 201, saved.text
    return saved.json()


def small_feature(client, rounds=1):
    return made(client, "Small feature", graph(
        [part("spec", "Write the spec", {"role": "Spec writer"}, ask_me=True),
         part("build", "Build it", {"role": "Coder"}),
         part("code", "Code review", {"role": "Reviewer"}, group="reviews", done_when="no_findings"),
         part("tests", "Test it", {"role": "Tester"}, group="reviews", done_when="no_findings")],
        [("start", "spec"), ("spec", "build"), ("build", "reviews"), ("reviews", "end")],
        loops=[{"from": "reviews", "to": "build", "rounds": rounds}],
        groups=[{"id": "reviews", "name": "Reviews"}]))


def recipe_named(client, name):
    return next(r for r in client.get("/api/recipes").json()["recipes"] if r["name"] == name)


def one_step(client, name, role):
    return made(client, name, graph([part("do", name, {"role": role})], [("start", "do"), ("do", "end")]))


def manual(client, project_dir, *rows):
    # (Auto-edit: at Full auto a recipe's cards go to the Lead or nobody - K-fullauto-sorma 2.)
    return begin(client, project_dir, mode="auto_edit", spawn_approval="never", teams_mode="manual",
                 teams=[{"team_id": team["id"], "recipe_id": recipe["id"]} for team, recipe in rows])


def asked(snap):
    return next((q for q in snap["questions"] if q["status"] == "pending"), None)


def answer(client, question, word):
    said = client.post(f"/api/questions/{question['id']}/answer", json={"answer": word}, headers=OWN)
    assert said.status_code == 200, said.text


def by_call(snap):
    """Each spawn call's (status, result), in order."""
    return [(t["status"], t["result"]) for t in snap["tool_calls"] if t["name"] == "spawn_agent"]


def row(snap, at=0):
    return snap["conversation"]["teams"][at]["state"]


def strip(state):
    return [(s["id"], s["state"], s["round"]) for s in state["steps"]]


def test_one_team_runs_its_recipe_step_by_step_and_its_work_waits_for_take_in(
    make_client, wait_run, project_dir
):
    client, model = make_client({
        "Lead": [
            spawn("Tester", "test it", "t0"),
            spawn("Spec writer", "write the spec", "s1"),
            spawn("Coder", "build greet.py", "c1"),
            step(call("spawn_agent", {"role": "Reviewer", "task": "review"}, "r1"),
                 call("spawn_agent", {"role": "Tester", "task": "test"}, "t1")),
            step(call("spawn_agent", {"role": "Coder", "task": "fix", "findings_from": "Reviewer"}, "c2")),
            step(call("spawn_agent", {"role": "Reviewer", "task": "review"}, "r2"),
                 call("spawn_agent", {"role": "Tester", "task": "test"}, "t2")),
            text("all done"),
        ],
        "Spec writer": [text("the spec")],
        "Coder": [step(write("greet.py", "print('Helo')\n")), text("built")],
        "Reviewer": [step(call("read_file", {"path": "greet.py"}, "rd")), text(FOUND)],
        "Tester": [text(NONE)],
        "Coder 2": [step(write("greet.py", "print('Hello')\n", id="w2")), text("fixed")],
        "Reviewer 2": [text(FOUND)],
        "Tester 2": [text(NONE)],
    })
    web, recipe = teams_of(client)["Web app"], small_feature(client)
    cid, run_id = manual(client, project_dir, (web, recipe))

    # The spec's "ask me": KOLONİ's card in the call that finished it.
    snap = until(client, cid, asked)
    card = asked(snap)
    assert "Write the spec" in card["question"] and card["options"] == ["Go on", "Ask for changes", "Stop"] and card["leave"]
    assert strip(row(snap))[:2] == [("spec", "now", 0), ("build", "next", 0)]
    # The step's roles, not the team's: Spec writer is in no Web app stage; Tester is a later step's.
    offered = next(t["function"] for t in model.tool_args[0] if t["function"]["name"] == "spawn_agent")
    assert "Spec writer" in offered["description"] and "- Tester" not in offered["description"]
    answer(client, card, "Go on")

    snap = until(client, cid, lambda s: asked(s) and "Ready for you" in asked(s)["question"])
    # The work is in the recipe's copy, not in the project, until Take in.
    assert not (project_dir / "greet.py").exists()
    state = row(snap)
    assert state["status"] == "ready"
    assert strip(state) == [("spec", "done", 0), ("build", "done", 1), ("reviews", "done", 1),
                            ("end", "now", 0)]
    assert len(state["agents"]) == 7
    card = asked(snap)
    assert card["options"] == ["Take in", "Ask for changes"]
    answer(client, card, "Take in")

    snap = wait_run(client, cid, run_id)
    assert (project_dir / "greet.py").read_bytes() == b"print('Hello')\n"
    assert (row(snap)["status"], row(snap)["team"], row(snap)["recipe"]) == ("in", "Web app", "Small feature")
    assert strip(row(snap))[-1] == ("end", "done", 0)
    calls = by_call(snap)
    refused = calls[0]
    assert refused[0] == "failed" and "Write the spec" in refused[1] and "Small feature" in refused[1]
    assert "Next: Build it" in calls[1][1]
    # The group goes on once both are done; its findings send it back once, then on.
    first_round = calls[3:5]
    assert any("back to Build it, round 1 of 1" in said for _, said in first_round)
    assert any("at its end" in said for _, said in calls[6:8])
    # The Reviewer read the Coder's change: they work in one copy.
    read = next(t for t in snap["tool_calls"] if t["name"] == "read_file")
    assert "Helo" in read["result"]
    # Its parts as they ran, for the canvas's work line - the loop back to Build it a pass of its
    # own - and which part is a group.
    names = {a["id"]: a["name"] for a in snap["agents"]}
    assert [(p["part"], sorted(names[a] for a in p["agents"])) for p in row(snap)["passes"]] == [
        ("spec", ["Spec writer"]), ("build", ["Coder"]), ("reviews", ["Reviewer", "Tester"]),
        ("build", ["Coder 2"]), ("reviews", ["Reviewer 2", "Tester 2"])]
    assert [s["group"] for s in row(snap)["steps"]] == [False, False, True, False]
    # B-107: the turn keeps its row as it left it; the chat's teams changed after do not change it.
    changed = client.patch(f"/api/conversations/{cid}", json={"teams_mode": "none", "teams": []}, headers=OWN)
    assert changed.status_code == 200, changed.text
    snap = client.get(f"/api/conversations/{cid}").json()
    assert snap["conversation"]["teams"] == []
    kept = next(r for r in snap["runs"] if r["id"] == run_id)["teams"]
    assert [(t["team_id"], t["state"]["status"], len(t["state"]["passes"])) for t in kept] == [(web["id"], "in", 5)]


def test_two_teams_run_by_their_leads_and_meet_in_one_ready_for_you(make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [
            spawn("Coder", "build it", "c0"),
            step(call("spawn_agent", {"role": "Web app lead", "task": "the page"}, "l1"),
                 call("spawn_agent", {"role": "Docs lead", "task": "the words"}, "l2")),
            text("both done"),
        ],
        "Web app lead": [spawn("Coder", "build a.py", "c"), text("web done")],
        "Docs lead": [spawn("Docs writer", "write b.md", "d"), text("docs done")],
        "Coder": [step(write("a.py", "a\n")), text("built")],
        "Docs writer": [step(write("b.md", "b\n", id="w2")), text("written")],
    })
    teams = teams_of(client)
    build, words = one_step(client, "Just build", "Coder"), one_step(client, "Just write", "Docs writer")
    cid, run_id = manual(client, project_dir, (teams["Web app"], build), (teams["Docs"], words))

    snap = until(client, cid, lambda s: asked(s) and "Ready for you" in asked(s)["question"])
    assert not (project_dir / "a.py").exists() and not (project_dir / "b.md").exists()
    assert [row(snap, 0)["status"], row(snap, 1)["status"]] == ["ready", "ready"]
    answer(client, asked(snap), "Take in")

    snap = wait_run(client, cid, run_id)
    assert (project_dir / "a.py").exists() and (project_dir / "b.md").exists()
    assert [row(snap, 0)["status"], row(snap, 1)["status"]] == ["in", "in"]
    refused = by_call(snap)[0]
    assert refused[0] == "failed" and "Web app lead" in refused[1]
    depth = {a["role_name"]: (a["depth"], a["parent_agent_id"]) for a in snap["agents"]}
    ids = {a["role_name"]: a["id"] for a in snap["agents"]}
    assert depth["Web app lead"][0] == 1 and depth["Coder"] == (2, ids["Web app lead"])
    assert depth["Docs writer"] == (2, ids["Docs lead"])
    assert ids["Coder"] in row(snap, 0)["agents"] and ids["Web app lead"] in row(snap, 0)["agents"]


def test_stop_ends_one_teams_agents_and_the_other_team_goes_on(make_client, wait_run, project_dir, gate):
    client, _model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Web app lead", "task": "the page"}, "l1"),
                      call("spawn_agent", {"role": "Docs lead", "task": "the words"}, "l2")),
                 text("one stopped")],
        "Web app lead": [spawn("Coder", "build a.py", "c"), text("never said")],
        "Docs lead": [spawn("Docs writer", "write b.md", "d"), text("docs done")],
        "Coder": [gate.step(step(write("a.py", "a\n"))), text("never said")],
        "Docs writer": [step(write("b.md", "b\n", id="w2")), text("written")],
    })
    teams = teams_of(client)
    build, words = one_step(client, "Just build", "Coder"), one_step(client, "Just write", "Docs writer")
    cid, run_id = manual(client, project_dir, (teams["Web app"], build), (teams["Docs"], words))
    gate.wait_partial()
    stop = f"/api/conversations/{cid}/teams/{teams['Web app']['id']}/stop"
    assert client.post(stop).status_code == 403
    assert client.post(stop, headers=OWN).status_code == 200
    gate.release()

    snap = until(client, cid, lambda s: asked(s) and "Ready for you" in asked(s)["question"])
    assert (row(snap, 0)["status"], row(snap, 0)["why"]) == ("stopped", "Stopped by you")
    assert row(snap, 1)["status"] == "ready"
    coder = next(a for a in snap["agents"] if a["role_name"] == "Coder")
    assert coder["status"] == "failed" and "stopped" in coder["error"].lower()
    answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id)
    assert (project_dir / "b.md").exists() and row(snap, 1)["status"] == "in"


def test_a_failed_step_asks_and_ready_for_you_can_send_it_back_with_the_users_words(
    make_client, wait_run, project_dir
):
    client, model = make_client({
        "Lead": [spawn("Coder", "build", "c1"), spawn("Coder", "build again", "c2"),
                 spawn("Coder", "make it blue", "c3"), text("done")],
        "Coder": [RuntimeError("its model broke")],
        "Coder 2": [step(write("a.py", "red\n")), text("built")],
        "Coder 3": [step(write("a.py", "blue\n", id="w2")), text("blue now")],
    })
    web, build = teams_of(client)["Web app"], one_step(client, "Just build", "Coder")
    cid, run_id = manual(client, project_dir, (web, build))

    snap = until(client, cid, asked)
    assert asked(snap)["options"] == ["Try again", "Skip", "Stop"]
    answer(client, asked(snap), "Try again")
    snap = until(client, cid, lambda s: asked(s) and "Ready for you" in asked(s)["question"])
    answer(client, asked(snap), "make it blue")
    snap = until(client, cid, lambda s: asked(s) and "Ready for you" in asked(s)["question"]
                 and len([q for q in s["questions"] if "Ready for you" in q["question"]]) == 2)
    assert not (project_dir / "a.py").exists()
    answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id)
    assert (project_dir / "a.py").read_bytes() == b"blue\n"
    calls = by_call(snap)
    assert "Open Coder again" in calls[0][1]
    # (B-115: the words to its step and to the Lead as the user's, not in the call's result)
    assert "Ask for changes at Ready for you" in calls[1][1] and "make it blue" not in calls[1][1]
    assert "goes on from Just build - KOLONİ adds the user's words to its task" in calls[1][1]
    assert '"make it blue"' in {a["name"]: a["task"] for a in snap["agents"]}["Coder 3"]
    card = {"role": "user", "content": "The user answered KOLONİ's card (Ready for you): make it blue"}
    assert card in model.calls_of["Lead"][2]
    assert row(snap)["status"] == "in"


def test_a_failed_steps_card_takes_only_one_of_its_options(make_client, wait_run, project_dir):
    # B-326 (live): any other word was taken, and the card asked again at once - 25 times in 3 minutes.
    client, _model = make_client({
        "Lead": [spawn("Coder", "build", "c1"), text("done")],
        "Coder": [RuntimeError("its model broke")],
    })
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], one_step(client, "Just build", "Coder")))
    card = asked(until(client, cid, asked))
    said = client.post(f"/api/questions/{card['id']}/answer", json={"answer": "maybe"}, headers=OWN)
    assert (said.status_code, said.json()["detail"]) == (
        422, "answer with one of its options: Try again, Skip, Stop")
    snap = client.get(f"/api/conversations/{cid}").json()
    assert [(q["id"], q["status"]) for q in snap["questions"]] == [(card["id"], "pending")]
    answer(client, card, "Skip")
    # (K-r144: a skipped step changed no file - nothing to take in, no Ready for you card.)
    snap = wait_run(client, cid, run_id)
    assert row(snap)["status"] == "done" and [q["id"] for q in snap["questions"]] == [card["id"]]


def test_a_step_whose_provider_is_out_of_its_limit_asks_to_run_there_on_one_with_room(
    make_client, wait_run, project_dir
):
    """B-88: Qoder ran out of credit at a step's first request; KOLONİ said who had room, and
    nobody could pick it. The step's card offers one, and Run there opens the step on it."""
    client, _model = make_client({
        "Lead": [text("hello"), spawn("Coder", "build", "c1"), spawn("Coder", "build again", "c2"),
                 text("done")],
        "Coder": [ModelUnavailable("Qoder exited with code 1: You've reached your credit usage limit")],
        "Coder 2": [step(write("a.py", "built\n")), text("built")],
    })
    client.headers.update(OWN)
    local = next(p for p in client.get("/api/providers").json() if p["name"] == "Local")
    assert client.patch(f"/api/providers/{local['id']}", json={"for_agents": True}).status_code == 200
    qoder = provider(client, "openai_compat", "Qoder")
    assert client.patch(f"/api/roles/{role_id(client, 'Coder')}", json={"provider_id": qoder}).status_code == 200
    # (A turn before, which ends well on Local: it is known to have room.)
    wait_run(client, *begin(client, project_dir, content="hello"))
    web, build = teams_of(client)["Web app"], one_step(client, "Just build", "Coder")
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="always",
                        teams_mode="manual", teams=[{"team_id": web["id"], "recipe_id": build["id"]}])
    # (Its first Coder is the user's to let open: always asked.)
    snap = until(client, cid, lambda s: any(a["status"] == "proposed" for a in s["agents"]))
    first = next(a for a in snap["agents"] if a["status"] == "proposed")
    assert client.post(f"/api/agents/{first['id']}/approve").status_code == 200
    snap = until(client, cid, asked)
    card = asked(snap)
    # (Local names no model of its own: its server's.)
    assert card["question"] == ("Web app: Coder can't run on Qoder (its limit is reached). Run Just "
                                "build on Local?")
    assert card["options"] == ["Run there", "Skip", "Stop"]
    answer(client, card, "Run there")
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    # The user's yes was the card's: the second Coder is not asked about again, and is on record
    # as their choice.
    second = next(a for a in snap["agents"] if a["name"] == "Coder 2")
    assert (second["provider_name"], second["chosen"], second["status"]) == ("Local", True, "completed")
    assert second["chosen_why"] == ("the user's choice: it could not run on Qoder (its limit is "
                                    "reached)")
    assert 'KOLONİ opens it on "Local", as the user chose' in by_call(snap)[0][1]
    answer(client, asked(snap), "Take in")
    assert row(wait_run(client, cid, run_id))["status"] == "in"


def test_a_recipe_that_cannot_run_any_more_is_refused_as_it_starts(make_client, wait_run, project_dir):
    client, _model = make_client({"Lead": [spawn("Coder", "build it"), text("could not")]})
    web = teams_of(client)["Web app"]
    helper = client.post("/api/roles", json={"name": "Helper", "tools": ["read_file"]}, headers=OWN)
    recipe = one_step(client, "Old one", "Helper")
    # Who names a role by its name: deleted since, the recipe names none.
    assert client.delete(f"/api/roles/{helper.json()['id']}", headers=OWN).status_code == 204
    cid, run_id = manual(client, project_dir, (web, recipe))
    snap = wait_run(client, cid, run_id)
    ((status, said),) = by_call(snap)
    assert status == "failed" and "Old one" in said and "“Helper” is no role here" in said
    assert [a["role_name"] for a in snap["agents"]] == ["Lead"]


def test_a_row_running_when_koloni_restarted_says_so(tmp_path):
    db = tmp_path / "r.db"
    upgrade_db(db)
    factory = make_session_factory(make_engine(db))
    seed(factory, tmp_path)
    with factory() as s:
        s.add(Team(id="t", name="Art"))
        s.flush()
        s.add_all([
            ConversationTeam(id="going", conversation_id="c", team_id="t", picked_by="user", position=0,
                             state={"run_id": "r1", "status": "running", "at": "build", "why": None}),
            ConversationTeam(id="over", conversation_id="c", team_id="t", picked_by="user", position=1,
                             state={"run_id": "r3", "status": "in", "at": "end", "why": None}),
        ])
        s.commit()
    recover_interrupted(factory)
    with factory() as s:
        states = {r.id: (r.state["status"], r.state["why"], r.state["at"]) for r in s.query(ConversationTeam)}
    assert states == {"going": ("interrupted", "Interrupted by a server restart", "build"),
                      "over": ("in", None, "end")}


def test_in_ask_mode_the_recipe_asks_once_at_ready_for_you(make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [spawn("Coder", "build"), text("done")],
        "Coder": [step(write("a.py", "a\n")), text("built")],
    })
    web, build = teams_of(client)["Web app"], one_step(client, "Just build", "Coder")
    cid, run_id = begin(client, project_dir, mode="ask", spawn_approval="never", teams_mode="manual",
                        teams=[{"team_id": web["id"], "recipe_id": build["id"]}])
    snap = until(client, cid, asked)
    # The Coder's write went into the recipe's copy unasked; the one card is Ready for you.
    assert READY in asked(snap)["question"] and not (project_dir / "a.py").exists()
    assert [m for m in snap["merges"] if m["status"] == "pending"] == []
    answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id)
    assert (project_dir / "a.py").read_bytes() == b"a\n" and row(snap)["status"] == "in"
    assert len(snap["questions"]) == 1


def test_at_full_auto_the_recipes_work_is_taken_in_by_itself_with_no_card(make_client, wait_run, project_dir):
    """K-fullauto-sorma 2: Ready for you asks nobody at Full auto; the Lead hears it was taken in."""
    client, _model = make_client({
        "Lead": [spawn("Coder", "build"), text("done")],
        "Coder": [step(write("a.py", "a\n")), text("built")],
    })
    web, build = teams_of(client)["Web app"], one_step(client, "Just build", "Coder")
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never",
                        teams_mode="manual", teams=[{"team_id": web["id"], "recipe_id": build["id"]}])
    snap = wait_run(client, cid, run_id)
    assert (project_dir / "a.py").read_bytes() == b"a\n" and row(snap)["status"] == "in"
    assert snap["questions"] == []
    assert "Full auto: the work is taken into the project" in by_call(snap)[0][1]


def test_a_recipe_that_changed_no_file_ends_with_no_take_in_card(make_client, wait_run, project_dir):
    """B-359 (live): a Room-only recipe agreed and wrote nothing, and Ready for you still asked
    "Take the work into the project?" - with nothing to take in, nobody is asked."""
    client, _model = make_client({"Lead": [spawn("Coder", "look"), text("done")],
                                  "Coder": [text("nothing to change")]})
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], one_step(client, "Just build", "Coder")))
    snap = wait_run(client, cid, run_id)
    assert snap["questions"] == [] and snap["merges"] == [] and row(snap)["status"] == "done"
    assert "it changed no file - nothing to take in" in by_call(snap)[0][1]


def test_at_full_auto_the_lead_answers_ask_me_and_the_work_goes_in_by_itself(
    make_client, wait_run, project_dir
):
    """K-fullauto-sorma 2: the Ask me card is the Lead's at once (its reason on record); the end
    asks nobody."""
    from tests.test_lead_decides import says
    client, _model = make_client({
        "Lead": [spawn("Spec writer", "write the spec", "s1"), says("Go on", "The spec covers it."),
                 spawn("Coder", "build it", "c1"), text("done")],
        "Spec writer": [text("the spec")],
        "Coder": [step(write("a.py", "a\n")), text("built")],
    })
    recipe = made(client, "Spec first", graph(
        [part("spec", "Write the spec", {"role": "Spec writer"}, ask_me=True),
         part("build", "Build it", {"role": "Coder"})],
        [("start", "spec"), ("spec", "build"), ("build", "end")]))
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never",
                        teams_mode="manual", teams=[{"team_id": teams_of(client)["Web app"]["id"],
                                                     "recipe_id": recipe["id"]}])
    snap = wait_run(client, cid, run_id, timeout=10)
    (card,) = snap["questions"]
    assert "Write the spec" in card["question"] and card["leave"]
    assert (card["answer"], card["lead_why"]) == ("Go on", "The spec covers it.")
    assert (project_dir / "a.py").exists() and row(snap)["status"] == "in"


def test_at_full_auto_a_failed_step_is_tried_once_more_then_skipped_with_no_card(
    make_client, wait_run, project_dir
):
    """K-fullauto-sorma 2: KOLONİ's own word, said to the Lead; Stop stays the user's."""
    client, _model = make_client({
        "Lead": [spawn("Coder", "build", "c1"), spawn("Coder", "build again", "c2"), text("done")],
        "Coder": [RuntimeError("its model broke")],
        "Coder 2": [RuntimeError("broke again")],
    })
    web, build = teams_of(client)["Web app"], one_step(client, "Just build", "Coder")
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never",
                        teams_mode="manual", teams=[{"team_id": web["id"], "recipe_id": build["id"]}])
    snap = wait_run(client, cid, run_id, timeout=10)
    assert snap["questions"] == []
    first, second = by_call(snap)
    assert "KOLONİ's word on" in first[1] and ": Try again." in first[1] and "Open Coder again" in first[1]
    assert ": Skip." in second[1] and row(snap)["status"] == "done"  # (K-r144: nothing to take in)


def test_at_full_auto_a_check_step_that_keeps_failing_is_never_skipped_and_the_user_decides(
    make_client, wait_run, project_dir
):
    """Review of K-fullauto-sorma 2: a review / tests step is tried once more, then the work
    stands unchecked - Ready for you stays the user's card, nothing is taken in by itself."""
    client, _model = make_client({
        "Lead": [spawn("Coder", "build", "c1"), spawn("Reviewer", "check", "r1"),
                 spawn("Reviewer", "check again", "r2"), text("done")],
        "Coder": [step(write("a.py", "a\n")), text("built")],
        "Reviewer": [RuntimeError("its model broke")],
        "Reviewer 2": [RuntimeError("broke again")],
    })
    recipe = made(client, "Build and review", graph(
        [part("build", "Build it", {"role": "Coder"}),
         part("check", "Check it", {"role": "Reviewer"}, done_when="no_findings")],
        [("start", "build"), ("build", "check"), ("check", "end")]))
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never",
                        teams_mode="manual", teams=[{"team_id": teams_of(client)["Web app"]["id"],
                                                     "recipe_id": recipe["id"]}])
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"], timeout=10)
    assert not (project_dir / "a.py").exists()
    assert (row(snap)["status"], row(snap)["why"]) == (
        "ready", "Check it failed (Reviewer 2), and nothing was checked")
    said = [result or "" for _status, result in by_call(snap)]  # (the card holds the last call)
    assert any(": Try again." in one for one in said) and not any(": Skip." in one for one in said)
    answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id)
    assert (project_dir / "a.py").exists() and row(snap)["status"] == "in"


def test_a_turn_that_ends_mid_recipe_stops_the_row_where_it_was_and_keeps_its_work(
    make_client, wait_run, project_dir
):
    client, model = make_client({
        "Lead": [spawn("Coder", "build"), text("I stop here"), text("still here"), text("no tester")],
        "Coder": [step(write("a.py", "a\n")), text("built")],
    })
    web = teams_of(client)["Web app"]
    two = made(client, "Build then test", graph(
        [part("build", "Build it", {"role": "Coder"}), part("test", "Test it", {"role": "Tester"})],
        [("start", "build"), ("build", "test"), ("test", "end")]))
    cid, run_id = manual(client, project_dir, (web, two))
    snap = wait_run(client, cid, run_id)
    # B-83: its answer was no end while Test it was left - told, an answer with no call is its why.
    told = "Not the end yet: the Build then test recipe's next step is Test it (Tester): open it with spawn_agent"
    calls = model.calls_of["Lead"]
    assert len(calls) == 3 and told in str(calls[2][-1]) and calls[2][-2]["content"] == "I stop here"
    assert (row(snap)["status"], row(snap)["why"]) == ("stopped", "rule broken: Test it was not done")
    assert [s["state"] for s in row(snap)["steps"]] == ["done", "skipped", "next"]
    assert not (project_dir / "a.py").exists()
    # What it made is a kept copy's card: the user's to take in or throw away.
    assert [m["status"] for m in snap["merges"]] == ["kept"]


def test_a_recipe_turn_ended_midway_keeps_its_work_and_take_in_takes_it_in(make_client, wait_run, project_dir):
    # B-67 (live, 25 Oct): the Lead asked the user mid-recipe, then ended its turn - the work is not lost.
    from pathlib import Path
    client, model = make_client({
        "Lead": [spawn("Coder", "build"),
                 step(call("ask_user", {"question": "Go on?", "options": ["go on with the recipe", "stop"]}, "q")),
                 *[text("I stop here")] * 3],
        "Coder": [step(write("a.py", "a\n")), text("built")],
    })
    web = teams_of(client)["Web app"]
    two = made(client, "Build then test", graph(
        [part("build", "Build it", {"role": "Coder"}), part("test", "Test it", {"role": "Tester"})],
        [("start", "build"), ("build", "test"), ("test", "end")]))
    cid, run_id = manual(client, project_dir, (web, two))
    answer(client, asked(until(client, cid, lambda s: asked(s) and "Go on?" in asked(s)["question"])),
           "go on with the recipe")
    snap = wait_run(client, cid, run_id)
    assert row(snap)["status"] == "stopped" and not (project_dir / "a.py").exists()
    # Its copy stays on disk, for the user's Take in (or Discard) on Ready for you.
    (kept,) = [m for m in snap["merges"] if m["status"] == "kept"]
    assert kept["kept_in"] and Path(kept["kept_in"]).exists()
    taken = client.post(f"/api/merges/{kept['id']}/approve", json={"choices": {}}, headers=OWN)
    assert taken.status_code == 200, taken.text
    assert (project_dir / "a.py").read_bytes() == b"a\n"
    assert row(client.get(f"/api/conversations/{cid}").json())["status"] == "in"
    # The Lead is told the recipe asks the user itself, and that Take in is the only way in.
    offered = next(t["function"] for t in model.tool_args[0] if t["function"]["name"] == "spawn_agent")
    assert "ask_user" in offered["description"] and "Take in" in offered["description"]


@pytest.mark.parametrize("mid", [False, True])
def test_a_recipes_kept_work_outlives_a_restart_and_take_in_puts_its_rows_in(settings_env, project_dir, mid):
    # B-67: "the copy is deleted when the server stops". Kept after its turn ended (or with the turn
    # still at work, `mid`), it is there after a restart; Take in brings it in and the row is in.
    from app.config import load_settings
    from app.main import create_app
    from tests.conftest import Gate
    from tests.fakes import ScriptedModel
    from tests.keyed import TestClient
    from tests.test_copy_later_scenarios import again
    held = Gate()
    app_ = create_app(load_settings(settings_env), model=ScriptedModel({
        "Lead": [spawn("Coder", "build"), *[text("I stop here")] * 3],
        "Coder": [step(write("a.py", "a\n")), held.step(text("built")) if mid else text("built")],
    }))
    with TestClient(app_, base_url="http://127.0.0.1:8790") as client:
        client.headers.update(OWN)
        web = teams_of(client)["Web app"]
        two = made(client, "Build then test", graph(
            [part("build", "Build it", {"role": "Coder"}), part("test", "Test it", {"role": "Tester"})],
            [("start", "build"), ("build", "test"), ("test", "end")]))
        cid, _run_id = manual(client, project_dir, (web, two))
        if mid:
            held.wait_partial()
        else:
            until(client, cid, lambda s: s["runs"][0]["status"] == "completed")
    held.release()
    with again(settings_env) as client:
        snap = client.get(f"/api/conversations/{cid}").json()
        assert row(snap)["status"] == ("interrupted" if mid else "stopped") and not (project_dir / "a.py").exists()
        (kept,) = [m for m in snap["merges"] if m["status"] == "kept"]
        assert kept["kept_in"]
        taken = client.post(f"/api/merges/{kept['id']}/approve", json={"choices": {}})
        assert taken.status_code == 200, taken.text
        assert (project_dir / "a.py").read_bytes() == b"a\n"
        assert row(client.get(f"/api/conversations/{cid}").json())["status"] == "in"


REVIEWS = ("Reviewer", "Security reviewer", "UI designer", "Tester")


def reviews(at):
    return step(*(call("spawn_agent", {"role": role, "task": "review"}, f"{role[:2]}{at}") for role in REVIEWS))


def test_the_ready_feature_recipe_runs_to_its_end_on_a_default_chat(make_client, wait_run, project_dir):
    # 11 agents in a turn on a chat that lets 6: while a recipe runs, the limit counts per step. (The
    # Lead approves itself: no "Reviewer 3" for an Approve step, batch-16.)
    client, _model = make_client({
        "Lead": [spawn("Spec writer", "write the spec", "s1"), spawn("Coder", "build", "c1"), reviews(1),
                 step(call("spawn_agent", {"role": "Coder", "task": "fix", "findings_from": "Reviewer"}, "c2")),
                 reviews(2), text("all done")],
        "Spec writer": [text("the spec")],
        "Coder": [step(write("greet.py", "print('Helo')\n")), text("built")],
        "Coder 2": [step(write("greet.py", "print('Hello')\n", id="w2")), text("fixed")],
        "Reviewer": [text(FOUND)], "Reviewer 2": [text(NONE)],
        **{f"{role}{n}": [text(NONE)] for role in REVIEWS[1:] for n in ("", " 2")},
    })
    web, feature = teams_of(client)["Web app"], recipe_named(client, "Feature")
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never", teams_mode="manual",
                        teams=[{"team_id": web["id"], "recipe_id": feature["id"]}])
    assert client.get(f"/api/conversations/{cid}").json()["conversation"]["spawn_max_agents"] == 6
    answer(client, asked(until(client, cid, asked)), "Go on")
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"], timeout=10)
    assert len(snap["agents"]) == 12 and not [c for c in by_call(snap) if c[0] == "failed"]
    assert [s["id"] for s in row(snap)["steps"]] == ["spec", "build", "reviews", "end"]
    answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id)
    assert (project_dir / "greet.py").read_bytes() == b"print('Hello')\n" and row(snap)["status"] == "in"
    # (R116: the review that sent the work back ran again too - its round, not only build's)
    assert [(s["id"], s["round"]) for s in row(snap)["steps"]] == [("spec", 0), ("build", 1), ("reviews", 1), ("end", 0)]


def test_one_step_opens_what_it_draws_whatever_the_chats_limit(make_client, wait_run, project_dir):
    # (Slice 84e: the drawing sets the limit; the chat's is for agents outside a recipe.)
    client, _model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Reviewer", "task": "review"}, "r1"),
                      call("spawn_agent", {"role": "Tester", "task": "test"}, "t1")), text("stopped")],
        "Reviewer": [text(NONE)], "Tester": [text(NONE)],
    })
    web = teams_of(client)["Web app"]
    both = made(client, "Two at once", graph(
        [part("code", "Code review", {"role": "Reviewer"}, group="g", done_when="no_findings"),
         part("tests", "Test it", {"role": "Tester"}, group="g", done_when="no_findings")],
        [("start", "g"), ("g", "end")], groups=[{"id": "g", "name": "Reviews"}]))
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never", teams_mode="manual",
                        spawn_max_agents=1, teams=[{"team_id": web["id"], "recipe_id": both["id"]}])
    snap = wait_run(client, cid, run_id)  # (K-r144: two reviews change no file - no card)
    assert not [said for status, said in by_call(snap) if status == "failed"]
    assert snap["questions"] == [] and row(snap)["status"] == "done"


# --- review round (84b-2) ---------------------------------------------------------------------


def two_steps(client):
    return made(client, "Build then test", graph(
        [part("build", "Build it", {"role": "Coder"}), part("test", "Test it", {"role": "Tester"})],
        [("start", "build"), ("build", "test"), ("test", "end")]))


def two_builds(client):
    """Two Coders at once: a step opens as many as it draws (slice 84e)."""
    return made(client, "Two builds", graph(
        [part("a", "Build a", {"role": "Coder"}, group="g"), part("b", "Build b", {"role": "Coder"}, group="g")],
        [("start", "g"), ("g", "end")], groups=[{"id": "g", "name": "Builds"}]))


def test_a_step_is_done_only_once_every_agent_of_it_has_finished(make_client, wait_run, project_dir, gate):
    client, _model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "a"}, "c1"),
                      call("spawn_agent", {"role": "Coder", "task": "b"}, "c2")), text("done")],
        "Coder": [gate.step(text("built a"))],
        "Coder 2": [step(write("b.txt", "b\n")), text("built b")],  # (K-r144: work to take in)
    })
    web = teams_of(client)["Web app"]
    cid, run_id = manual(client, project_dir, (web, two_builds(client)))
    gate.wait_partial()
    until(client, cid, lambda s: any(a["name"] == "Coder 2" and a["status"] == "completed" for a in s["agents"]))
    snap = client.get(f"/api/conversations/{cid}").json()
    assert asked(snap) is None and row(snap)["status"] == "running"
    gate.release()
    snap = until(client, cid, asked)
    assert READY in asked(snap)["question"]
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)


def test_a_teams_lead_has_its_own_roles_tools_and_its_agents_still_write(make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Web app lead", "task": "the page"}, "l1"),
                      call("spawn_agent", {"role": "Docs lead", "task": "the words"}, "l2")), text("done")],
        "Web app lead": [spawn("Coder", "build a.py", "c"), text("web done")],
        "Docs lead": [spawn("Docs writer", "write b.md", "d"), text("docs done")],
        "Coder": [step(write("a.py", "a\n")), text("built")],
        "Docs writer": [step(write("b.md", "b\n", id="w2")), text("written")],
    })
    teams = teams_of(client)
    build, words = one_step(client, "Just build", "Coder"), one_step(client, "Just write", "Docs writer")
    cid, run_id = manual(client, project_dir, (teams["Web app"], build), (teams["Docs"], words))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    lead = next(a for a in snap["agents"] if a["role_name"] == "Web app lead")
    assert "write_file" not in lead["tools"] and "run_command" not in lead["tools"]
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)
    assert (project_dir / "a.py").exists() and (project_dir / "b.md").exists()


def test_a_recipe_deleted_mid_run_runs_on_as_it_started(make_client, wait_run, project_dir, gate):
    client, _model = make_client({
        "Lead": [spawn("Coder", "build"), spawn("Tester", "test", "t"), text("done")],
        "Coder": [step(write("c.txt", "c\n")), gate.step(text("built"))], "Tester": [text("tested")],
    })
    web, recipe = teams_of(client)["Web app"], two_steps(client)
    cid, run_id = manual(client, project_dir, (web, recipe))
    gate.wait_partial()
    assert client.delete(f"/api/recipes/{recipe['id']}", headers=OWN).status_code == 204
    gate.release()
    snap = until(client, cid, asked)
    assert READY in asked(snap)["question"] and row(snap)["recipe"] == "Build then test"
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)


def test_take_in_that_leaves_files_out_is_not_in_the_project(make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [spawn("Coder", "build"), text("done")],
        "Coder": [step(call("edit_file", {"path": "hello.py", "old_string": "hi", "new_string": "yo"}, "e")),
                  text("built")],
    })
    web = teams_of(client)["Web app"]
    cid, run_id = manual(client, project_dir, (web, one_step(client, "Just build", "Coder")))
    snap = until(client, cid, asked)
    (project_dir / "hello.py").write_bytes(b"print('ho')\n")  # the same line, changed in the project meanwhile
    answer(client, asked(snap), "Take in")
    snap = until(client, cid, lambda s: any(m["status"] == "pending" for m in s["merges"]))
    merge = next(m for m in snap["merges"] if m["status"] == "pending")
    # B-128: the clash's card waits for the user in the Lead's name (the page's list has it as a
    # decision, frontend/src/chat/waiting.ts).
    assert merge["agent_id"] == next(a["id"] for a in snap["agents"] if a["depth"] == 0)
    assert client.post(f"/api/merges/{merge['id']}/reject", headers=OWN).status_code == 200
    snap = wait_run(client, cid, run_id)
    assert row(snap)["status"] == "stopped" and row(snap)["why"]


def test_a_trigger_turn_starts_no_recipe(make_client, wait_run, project_dir):
    from tests.test_trigger_scenarios import run_now, trigger
    client, _model = make_client({"Lead": [spawn("Coder", "build"), text("could not")]})
    client.headers["Origin"] = "http://127.0.0.1:8790"
    web = teams_of(client)["Web app"]
    recipe = one_step(client, "Just build", "Coder")
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json={
        "teams_mode": "manual", "teams": [{"team_id": web["id"], "recipe_id": recipe["id"]}]}).status_code == 200
    run_id = run_now(client, trigger(client, pid, cid)["id"])
    snap = wait_run(client, cid, run_id)
    ((status, said),) = by_call(snap)
    assert status == "failed" and "nobody is here" in said


def test_try_again_opens_a_steps_agent_anew_within_what_it_draws(make_client, wait_run, project_dir):
    # (Slice 84e: one that failed gives its place back; the user's Try again is the word for it.)
    broke = RuntimeError("its model broke")
    client, _model = make_client({
        "Lead": [spawn("Coder", "a", "c1"), spawn("Coder", "b", "c2"), spawn("Coder", "c", "c3"), text("done")],
        "Coder": [broke], "Coder 2": [broke], "Coder 3": [step(write("c.txt", "c\n")), text("built")],
    })
    web = teams_of(client)["Web app"]
    build = one_step(client, "Just build", "Coder")
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never", teams_mode="manual",
                        spawn_max_agents=1, teams=[{"team_id": web["id"], "recipe_id": build["id"]}])
    for _ in range(2):
        card = asked(until(client, cid, asked))
        answer(client, card, "Try again")
        until(client, cid, lambda s, card=card: asked(s) is None or asked(s)["id"] != card["id"])
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id)
    assert [status for status, _ in by_call(snap)] == ["failed", "failed", "succeeded"]


def test_stop_is_refused_once_the_work_waits_for_take_in(make_client, wait_run, project_dir):
    client, _model = make_client({"Lead": [spawn("Coder", "build"), text("done")],
                                  "Coder": [step(write("c.txt", "c\n")), text("built")]})
    web = teams_of(client)["Web app"]
    cid, run_id = manual(client, project_dir, (web, one_step(client, "Just build", "Coder")))
    snap = until(client, cid, asked)
    stopped = client.post(f"/api/conversations/{cid}/teams/{web['id']}/stop", headers=OWN)
    assert stopped.status_code == 409 and "Take in" in stopped.json()["detail"]
    answer(client, asked(snap), "Ask for changes: Take in")  # (the user's own words, even these, are no Take in)
    snap = wait_run(client, cid, run_id)
    assert row(snap)["status"] != "in"


def test_only_skip_skips_and_a_step_nobody_can_open_is_refused(make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [spawn("Coder", "build"), spawn("Reviewer", "review", "r"), text("done")],
        "Coder": [RuntimeError("its model broke")],
    })
    web = teams_of(client)["Web app"]
    cid, run_id = manual(client, project_dir, (web, one_step(client, "Just build", "Coder")))
    card = asked(until(client, cid, asked))
    assert card["options"] == ["Try again", "Skip", "Stop"]
    # (B-326: another word is refused, not asked again)
    assert client.post(f"/api/questions/{card['id']}/answer", json={"answer": "whatever you think"},
                       headers=OWN).status_code == 422
    answer(client, card, "Stop")
    wait_run(client, cid, run_id)
    # A step whose role is off is refused as the recipe starts.
    client2, _ = make_client({"Lead": [spawn("Helper", "help"), text("could not")]})
    helper = client2.post("/api/roles", json={"name": "Helper", "tools": ["read_file"]}, headers=OWN).json()
    off = one_step(client2, "Off one", "Helper")
    assert client2.patch(f"/api/roles/{helper['id']}", json={"enabled": False}, headers=OWN).status_code == 200
    cid, run_id = manual(client2, project_dir, (teams_of(client2)["Web app"], off))
    ((status, said),) = by_call(wait_run(client2, cid, run_id))
    assert status == "failed" and "no role that is on" in said


def test_a_declined_agent_does_not_use_up_its_step(make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [spawn("Coder", "a", "c1"), spawn("Coder", "b", "c2"), text("done")],
        "Coder 2": [step(write("c.txt", "c\n")), text("built")],
    })
    web = teams_of(client)["Web app"]
    build = one_step(client, "Just build", "Coder")
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="always", teams_mode="manual",
                        spawn_max_agents=1, teams=[{"team_id": web["id"], "recipe_id": build["id"]}])
    first = until(client, cid, lambda s: any(a["status"] == "proposed" for a in s["agents"]))
    proposed = next(a for a in first["agents"] if a["status"] == "proposed")
    assert client.post(f"/api/agents/{proposed['id']}/reject", headers=OWN).status_code == 200
    second = until(client, cid, lambda s: [a for a in s["agents"] if a["status"] == "proposed" and a["id"] != proposed["id"]])
    nxt = next(a for a in second["agents"] if a["status"] == "proposed" and a["id"] != proposed["id"])
    assert client.post(f"/api/agents/{nxt['id']}/approve", headers=OWN).status_code == 200
    snap = until(client, cid, asked)
    assert READY in asked(snap)["question"]
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)


# --- second review round (84b-2) --------------------------------------------------------------


def test_no_room_after_a_recipe_ended_either_its_copy_is_still_held(make_client, wait_run, project_dir):
    from tests.test_room_open_scenarios import WORK, open_room
    client, _model = make_client({
        "Lead": [spawn("Coder", "build"), open_room(), text("done")],
        "Coder": [step(write("a.py", "a\n")), text("built")],
        "Coder 2": WORK["Coder"], "Reviewer": WORK["Reviewer"],
    })
    web = teams_of(client)["Web app"]
    report = made(client, "Build, report", graph(
        [part("do", "Build", {"role": "Coder"})], [("start", "do"), ("do", "end")],
        ends=({"id": "end", "then": "report"},)))
    cid, run_id = manual(client, project_dir, (web, report))
    # (B-190: a report recipe whose step wrote a file ends at Take in; the room comes after.)
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"], timeout=15)
    assert not (project_dir / "a.py").exists()
    answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id, timeout=15)
    ((status, said),) = [(t["status"], t["result"]) for t in snap["tool_calls"] if t["name"] == "open_room"]
    assert status == "failed" and "recipe" in said


def test_a_step_agents_own_helpers_are_held_to_the_chats_limit_per_agent(make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [spawn("Coder", "build"), text("done")],
        "Coder": [step(*(call("spawn_agent", {"role": "Coder", "task": f"part {i}"}, f"n{i}") for i in range(4))),
                  text("built")],
        **{f"Coder {i}": [text("part done")] for i in range(2, 6)},
    })
    web = teams_of(client)["Web app"]
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never", teams_mode="manual",
                        spawn_max_agents=1,
                        teams=[{"team_id": web["id"], "recipe_id": one_step(client, "Just build", "Coder")["id"]}])
    snap = until(client, cid, lambda s: asked(s) or s["runs"][0]["status"] != "running", timeout=10)
    opened = [c for c in by_call(snap)[1:] if c[0] != "failed"]
    if asked(snap):
        answer(client, asked(snap), "Ask for changes")
    wait_run(client, cid, run_id, timeout=10)
    assert len(opened) <= 1


def pair(client, name, roles=("Coder", "Debugger"), **more):
    """The team Pair, whose one stage holds two roles of a kind: one place, which two agents may
    work at (slice 84e: a step draws each role of a team's stages) - and a one-step recipe by it
    (`name` None: none)."""
    team = client.post("/api/teams", json={"name": "Pair"}, headers=OWN).json()
    for role in client.get("/api/roles").json():
        if role["name"] in roles:
            assert client.patch(f"/api/roles/{role['id']}", json={"teams": [*role["teams"], team["id"]]},
                                headers=OWN).status_code == 200
    return name and made(client, name, graph([part("do", "Build", {"team": "Pair"}, **more)],
                                             [("start", "do"), ("do", "end")]))


def test_a_declined_agent_does_not_leave_a_finished_step_waiting(make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "a"}, "c1"),
                      call("spawn_agent", {"role": "Coder", "task": "b"}, "c2")), text("done")],
        "Coder": [step(write("a.py", "a\n")), text("built a")],
        "Coder 2": [text("built b")],
    })
    web = teams_of(client)["Web app"]
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="always", teams_mode="manual",
                        teams=[{"team_id": web["id"], "recipe_id": pair(client, "Just build")["id"]}])
    snap = until(client, cid, lambda s: len([a for a in s["agents"] if a["status"] == "proposed"]) == 2)
    first, second = sorted((a for a in snap["agents"] if a["status"] == "proposed"), key=lambda a: a["name"])
    assert client.post(f"/api/agents/{first['id']}/approve", headers=OWN).status_code == 200
    until(client, cid, lambda s: any(a["id"] == first["id"] and a["status"] == "completed" for a in s["agents"]))
    assert client.post(f"/api/agents/{second['id']}/reject", headers=OWN).status_code == 200
    snap = until(client, cid, lambda s: asked(s) or s["runs"][0]["status"] != "running", timeout=10)
    ready = asked(snap) and READY in asked(snap)["question"]
    if asked(snap):
        answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id, timeout=10)
    assert ready


def test_an_extra_agents_failure_does_not_fail_a_step_another_filled(make_client, wait_run, project_dir, gate):
    client, _model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "a"}, "c1"),
                      call("spawn_agent", {"role": "Coder", "task": "b"}, "c2")), text("done")],
        "Coder": [gate.step(step(call("read_file", {"path": "hello.py"}, "rd"))), RuntimeError("its model broke")],
        "Coder 2": [text("built b")],
    })
    web = teams_of(client)["Web app"]
    cid, run_id = manual(client, project_dir, (web, pair(client, "Build or stop", if_fails="stop")))
    until(client, cid, lambda s: any(a["name"] == "Coder 2" and a["status"] == "completed" for a in s["agents"]))
    gate.release()
    snap = until(client, cid, lambda s: asked(s) or s["runs"][0]["status"] != "running", timeout=10)
    if asked(snap):
        answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id, timeout=10)
    assert row(snap)["status"] != "failed"


def test_stop_answers_the_card_its_step_waits_on(make_client, wait_run, project_dir):
    client, _model = make_client({"Lead": [spawn("Coder", "build"), text("done")],
                                  "Coder": [RuntimeError("its model broke")]})
    web = teams_of(client)["Web app"]
    cid, run_id = manual(client, project_dir, (web, one_step(client, "Just build", "Coder")))
    until(client, cid, asked)
    assert client.post(f"/api/conversations/{cid}/teams/{web['id']}/stop", headers=OWN).status_code == 200
    snap = wait_run(client, cid, run_id)
    assert row(snap)["status"] == "stopped" and not [q for q in snap["questions"] if q["status"] == "pending"]


# --- third review round (84b-2) ---------------------------------------------------------------


@pytest.mark.parametrize(("word", "then"), [("Go on", "Build it"), ("Stop", "Stopped by you")])
def test_the_word_on_a_card_in_a_declined_agents_call_is_heard(make_client, wait_run, project_dir, word, then):
    client, _model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Spec writer", "task": "a"}, "s1"),
                      call("spawn_agent", {"role": "Spec writer", "task": "b"}, "s2")), text("done")],
        "Spec writer": [text("spec a")], "Spec writer 2": [text("spec b")],
    })
    web = teams_of(client)["Web app"]
    pair(client, None, ("Spec writer", "Translator"))
    two = made(client, "Spec then build", graph(
        [part("spec", "Write the spec", {"team": "Pair"}, ask_me=True), part("build", "Build it", {"role": "Coder"})],
        [("start", "spec"), ("spec", "build"), ("build", "end")]))
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="always", teams_mode="manual",
                        teams=[{"team_id": web["id"], "recipe_id": two["id"]}])
    snap = until(client, cid, lambda s: len([a for a in s["agents"] if a["status"] == "proposed"]) == 2)
    first, second = sorted((a for a in snap["agents"] if a["status"] == "proposed"), key=lambda a: a["name"])
    assert client.post(f"/api/agents/{first['id']}/approve", headers=OWN).status_code == 200
    until(client, cid, lambda s: any(a["id"] == first["id"] and a["status"] == "completed" for a in s["agents"]))
    assert client.post(f"/api/agents/{second['id']}/reject", headers=OWN).status_code == 200
    answer(client, asked(until(client, cid, asked)), word)
    snap = wait_run(client, cid, run_id, timeout=10)
    # (Go on: the turn then ends at the next step, which nobody opened.)
    assert then in (row(snap)["why"] or "")


def test_a_teams_lead_opens_no_more_planners_than_the_chat_allows(make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Web app lead", "task": "the page"}, "l1"),
                      call("spawn_agent", {"role": "Docs lead", "task": "the words"}, "l2")), text("done")],
        "Web app lead": [step(*(call("spawn_agent", {"role": "Planner", "task": f"plan {i}"}, f"p{i}") for i in range(4))),
                         text("web done")],
        "Docs lead": [text("docs done")],
        **{n: [text("a plan")] for n in ("Planner", "Planner 2", "Planner 3", "Planner 4")},
    })
    teams = teams_of(client)
    build, words = one_step(client, "Just build", "Coder"), one_step(client, "Just write", "Docs writer")
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never", teams_mode="manual",
                        spawn_max_agents=1,
                        teams=[{"team_id": teams["Web app"]["id"], "recipe_id": build["id"]},
                               {"team_id": teams["Docs"]["id"], "recipe_id": words["id"]}])
    snap = wait_run(client, cid, run_id, timeout=15)
    assert len([a for a in snap["agents"] if a["role_name"] == "Planner"]) <= 1


@pytest.mark.parametrize("two_teams", [False, True])
def test_a_step_agent_may_open_a_helper_with_one_team_or_two_and_no_more_below(
    make_client, wait_run, project_dir, two_teams
):
    # K-takim-kat: beside another team the levels are counted from the team's lead, its team's
    # own Lead there - at the chat's default of 2, a helper's helper is refused either way.
    leads = {
        "Lead": [step(call("spawn_agent", {"role": "Web app lead", "task": "the page"}, "l1"),
                      call("spawn_agent", {"role": "Docs lead", "task": "the words"}, "l2")),
                 text("both done")],
        "Web app lead": [spawn("Coder", "build", "c"), text("web done")],
        "Docs lead": [spawn("Docs writer", "write", "d"), text("docs done")],
        "Docs writer": [text("written")],
    } if two_teams else {"Lead": [spawn("Coder", "build", "c"), text("done")]}
    client, _model = make_client({
        **leads,
        "Coder": [spawn("Coder", "help", "h1"), text("built")],
        "Coder 2": [spawn("Coder", "help more", "h2"), text("helped")],
    })
    teams = teams_of(client)
    rows = [(teams["Web app"], one_step(client, "Just build", "Coder"))]
    if two_teams:
        rows.append((teams["Docs"], one_step(client, "Just write", "Docs writer")))
    cid, run_id = manual(client, project_dir, *rows)

    snap = wait_run(client, cid, run_id)
    depth = {a["role_name"] if a["role_name"] != "Coder" else a["name"]: a["depth"]
             for a in snap["agents"]}
    base = 1 if two_teams else 0
    assert (depth["Coder"], depth["Coder 2"]) == (base + 1, base + 2)
    assert "Coder 3" not in depth
    helped = next(t for t in snap["tool_calls"] if t["provider_call_id"] == "h2")
    assert helped["status"] == "failed" and "depth limit" in helped["result"]


def test_a_discussion_beside_another_team_opens_members_by_the_levels_from_the_teams_lead(
    make_client, wait_run, project_dir
):
    # K-takim-kat, as for spawn_agent: the step's agent (a level below its team's lead) may open
    # a member; its helper (two below) may not.
    client, _model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Web app lead", "task": "the plan"}, "l1"),
                      call("spawn_agent", {"role": "Docs lead", "task": "the words"}, "l2")),
                 text("both done")],
        "Web app lead": [spawn("Planner", "plan", "p"), text("web done")],
        "Docs lead": [spawn("Docs writer", "write", "d"), text("docs done")],
        "Docs writer": [text("written")],
        "Planner": [discuss("How to plan it?", ["Reviewer"], rounds=1, id="d1"), text("Short."),
                    spawn("Planner", "help", "h1"), text("planned")],
        "Reviewer": [text("Fine.")],
        "Planner 2": [discuss("And more?", ["Tester"], rounds=1, id="d2"), text("helped")],
    })
    teams = teams_of(client)
    # (The Lead picks: any role may be asked into the step's discussion.)
    plan = made(client, "Just plan", graph([part("do", "Plan", {"lead": True})], [("start", "do"), ("do", "end")]))
    cid, run_id = manual(client, project_dir, (teams["Web app"], plan),
                         (teams["Docs"], one_step(client, "Just write", "Docs writer")))

    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    answer(client, asked(snap), "Take in")  # (a row that failed: the user's word, nothing changed or not)
    snap = wait_run(client, cid, run_id)
    calls = {t["provider_call_id"]: t for t in snap["tool_calls"] if t["name"] == "discuss"}
    assert calls["d1"]["status"] == "succeeded", calls["d1"]["result"]
    assert calls["d2"]["status"] == "failed" and "depth limit" in calls["d2"]["result"]
    depth = {a["name"]: a["depth"] for a in snap["agents"]}
    assert (depth["Planner"], depth["Reviewer"], depth["Planner 2"]) == (2, 3, 3)
    assert "Tester" not in depth


def test_the_ready_quality_check_recipe_runs_the_tests_then_two_reviews_at_once_and_no_ui_designer(
        make_client, wait_run, project_dir):
    # B-172 (the user's): Review only, Quality's default, called a UI designer - not in Quality - and
    # never its Tester. Quality check, its default now: its Tester, then its Reviewer and Security
    # reviewer at once.
    reviewers = ("Reviewer", "Security reviewer")
    client, _model = make_client({
        "Lead": [spawn("Tester", "run the tests", "t1"),
                 step(*(call("spawn_agent", {"role": role, "task": "review"}, f"r{at}") for at, role in enumerate(reviewers))),
                 text("all checked")],
        "Tester": [text(NONE)], **{role: [text(NONE)] for role in reviewers}})
    quality = teams_of(client)["Quality"]
    assert quality["default_recipe_id"] == recipe_named(client, "Quality check")["id"]
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never", teams_mode="manual",
                        teams=[{"team_id": quality["id"], "recipe_id": None}])
    snap = wait_run(client, cid, run_id)
    assert not [c for c in by_call(snap) if c[0] == "failed"]
    assert [a["role_name"] for a in snap["agents"] if a["depth"] == 1] == ["Tester", *reviewers]
    # (0102: the tests passed - its Debugger, which runs only on a problem found, was never opened.)
    assert strip(row(snap)) == [("test", "done", 0), ("fix", "skipped", 0), ("reviews", "done", 0),
                                ("end", "done", 0)]
    assert [s["unmet"] for s in row(snap)["steps"]] == [None, "no problem found", None, None]
    assert "Skipped, no problem found: Find and fix the cause." in by_call(snap)[0][1]
    assert row(snap)["status"] == "done"


def test_the_users_choice_on_a_card_of_some_of_an_all_at_once_steps_roles_opens_only_those(
        make_client, wait_run, project_dir):
    # B-173 (live): the user chose "Only with the Reviewer", and the Review only recipe's "all at
    # once" step still opened the Reviewer, the Security reviewer and the UI designer (≈42k tokens).
    client, _model = make_client({
        "Lead": [step(call("ask_user", {"question": "Who reviews cart.py?",
                                        "options": ["Only with the Reviewer", "All three"]}, "q1")),
                 spawn("Reviewer", "review cart.py", "r1"), text("reviewed")],
        "Reviewer": [text(NONE)], "Security reviewer": [text(NONE)], "UI designer": [text(NONE)]})
    web = teams_of(client)["Web app"]
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never", teams_mode="manual",
                        teams=[{"team_id": web["id"], "recipe_id": recipe_named(client, "Review only")["id"]}])
    answer(client, asked(until(client, cid, asked)), "Only with the Reviewer")
    snap = wait_run(client, cid, run_id)
    assert [a["role_name"] for a in snap["agents"] if a["depth"] == 1] == ["Reviewer"]
    assert not [c for c in by_call(snap) if c[0] == "failed"]
    # Done without the places the user left out: to its end, which reports - and says so, on the
    # strip and to the Lead (no silent ✓).
    assert row(snap)["status"] == "done"
    assert [s["left_out"] for s in row(snap)["steps"]] == [["Security review", "UI review"], []]
    told = next(t["result"] for t in snap["tool_calls"] if t["name"] == "spawn_agent")
    assert "Left out by the user's choice: Security review, UI review." in told


def test_a_choice_that_names_a_role_not_opened_leaves_the_step_as_drawn(make_client, wait_run, project_dir):
    # (B-173's limit: "not" is not read. "Without the UI designer" names only the UI designer - the
    # Reviewer opened is not of it: the step opens all its roles, never only the one left out.)
    client, _model = make_client({
        "Lead": [step(call("ask_user", {"question": "Who reviews cart.py?",
                                        "options": ["Without the UI designer", "All three"]}, "q1")),
                 spawn("Reviewer", "review cart.py", "r1"), text("reviewed")],
        "Reviewer": [text(NONE)], "Security reviewer": [text(NONE)], "UI designer": [text(NONE)]})
    web = teams_of(client)["Web app"]
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never", teams_mode="manual",
                        teams=[{"team_id": web["id"], "recipe_id": recipe_named(client, "Review only")["id"]}])
    answer(client, asked(until(client, cid, asked)), "Without the UI designer")
    snap = wait_run(client, cid, run_id)
    assert sorted(a["role_name"] for a in snap["agents"] if a["depth"] == 1) == [
        "Reviewer", "Security reviewer", "UI designer"]
    assert row(snap)["status"] == "done"


# --- B-173's review: which answer chooses -----------------------------------------------------

CHOOSE = ["Only with the Reviewer", "All three"]


def choose(id="q1", options=CHOOSE):
    return step(call("ask_user", {"question": "Who reviews cart.py?", "options": options}, id))


def review_only(client, project_dir):
    web = teams_of(client)["Web app"]
    return begin(client, project_dir, mode="auto_edit", spawn_approval="never", teams_mode="manual",
                 teams=[{"team_id": web["id"], "recipe_id": recipe_named(client, "Review only")["id"]}])


def reviewers(snap):
    return sorted(a["role_name"] for a in snap["agents"] if a["depth"] == 1)


ALL_THREE = ["Reviewer", "Security reviewer", "UI designer"]
EVERY_REVIEW = {"Reviewer": [text(NONE)], "Security reviewer": [text(NONE)], "UI designer": [text(NONE)]}


def test_a_later_all_three_undoes_an_earlier_only_the_reviewer(make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [choose("q1"), choose("q2"), spawn("Reviewer", "review cart.py", "r1"), text("reviewed")],
        **EVERY_REVIEW})
    cid, run_id = review_only(client, project_dir)
    answer(client, asked(until(client, cid, asked)), "Only with the Reviewer")
    answer(client, asked(until(client, cid, lambda s: asked(s) and asked(s)["id"] != "q1" and asked(s))),
           "All three")
    assert reviewers(wait_run(client, cid, run_id)) == ALL_THREE


def test_an_answer_the_lead_gave_for_the_user_does_not_narrow(make_client, wait_run, project_dir):
    from app.db.models import Question
    from tests.conftest import Gate
    held = Gate()
    client, _model = make_client({
        "Lead": [choose(), held.step(spawn("Reviewer", "review cart.py", "r1")), text("reviewed")],
        **EVERY_REVIEW})
    cid, run_id = review_only(client, project_dir)
    card = asked(until(client, cid, asked))
    answer(client, card, "Only with the Reviewer")
    held.wait_partial()
    # (As K-vekil-karar puts it on record when the Lead answers for the user, who was away.)
    with client.app.state.runner._factory() as session:
        session.get_one(Question, card["id"]).lead_why = "The user is away."
        session.commit()
    held.release()
    assert reviewers(wait_run(client, cid, run_id)) == ALL_THREE


def build_and_review(client):
    """Build it, then a Reviewer and a Security reviewer at once, back to the build at most once."""
    return made(client, "Build and review", graph(
        [part("build", "Build it", {"role": "Coder"}),
         part("code", "Code review", {"role": "Reviewer"}, group="reviews", done_when="no_findings"),
         part("security", "Security review", {"role": "Security reviewer"}, group="reviews",
              done_when="no_findings")],
        [("start", "build"), ("build", "reviews"), ("reviews", "end")],
        loops=[{"from": "reviews", "to": "build", "rounds": 1}],
        groups=[{"id": "reviews", "name": "Reviews"}], ends=[{"id": "end", "then": "report"}]))


def test_a_card_answered_before_the_step_was_come_to_does_not_narrow_it(make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [choose(options=["Only with the Reviewer", "Both"]), spawn("Coder", "build it", "c1"),
                 spawn("Reviewer", "review it", "r1"), text("done")],
        "Coder": [text("built")], "Reviewer": [text(NONE)], "Security reviewer": [text(NONE)]})
    web = teams_of(client)["Web app"]
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never", teams_mode="manual",
                        teams=[{"team_id": web["id"], "recipe_id": build_and_review(client)["id"]}])
    # (Asked while the build was the step: not a choice for the reviews.)
    answer(client, asked(until(client, cid, asked)), "Only with the Reviewer")
    assert reviewers(wait_run(client, cid, run_id)) == ["Coder", "Reviewer", "Security reviewer"]


def test_a_loop_round_back_to_the_step_does_not_keep_its_narrowing(make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [spawn("Coder", "build it", "c1"), choose(options=["Only with the Reviewer", "Both"]),
                 spawn("Reviewer", "review it", "r1"),
                 step(call("spawn_agent", {"role": "Coder", "task": "fix", "findings_from": "Reviewer"}, "c2")),
                 spawn("Reviewer", "review it again", "r2"), text("done")],
        "Coder": [text("built")], "Coder 2": [text("fixed")], "Reviewer": [text(FOUND)],
        "Reviewer 2": [text(NONE)], "Security reviewer": [text(NONE)]})
    web = teams_of(client)["Web app"]
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never", teams_mode="manual",
                        teams=[{"team_id": web["id"], "recipe_id": build_and_review(client)["id"]}])
    answer(client, asked(until(client, cid, asked)), "Only with the Reviewer")
    snap = wait_run(client, cid, run_id)
    # Round one, the Reviewer alone; round two, as drawn.
    assert [a["role_name"] for a in snap["agents"] if a["depth"] == 1] == [
        "Coder", "Reviewer", "Coder", "Reviewer", "Security reviewer"]
    assert [s["left_out"] for s in row(snap)["steps"]] == [[], [], []]
