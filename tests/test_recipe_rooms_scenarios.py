"""Slice 84e's acceptance set: rooms and discussions inside a recipe; the drawing sets the limit.
Written before the code.

Design: `tasarim/specs/2026-10-23-dilim-63-84-takimlar-tarifler-design.md` §6 item 5 (84e).

Contract:
- While a recipe runs, the Lead - or a team's lead - may open a room inside a step: its members
  are the step's roles (spawn_agent's door), they work in the recipe's one copy, and the room
  never takes its work into the project itself. Its members are the step's agents: the step goes
  on when the room is over. The project gets the work only through "Ready for you" -> Take in.
- A discussion inside a recipe: its new members are the step's agents; it writes no files.
- A step of kind Room (Who: {"room": [roles]}): its roles meet in one room. spawn_agent is
  refused there ("open_room"); open_room with all of its roles opens it. Saved, it is checked:
  2 to 4 roles that are here, not in an "all at once" group; it may be a loop's source or target.
- The drawing sets the limit: a step opens as many agents as it draws (a role one, a team a role
  each, a room a member each), whatever the chat's "Sub-agents per turn"; the run's total is
  counted from the drawing (`recipe_run.cap`) and told with the step. Outside a recipe the
  chat's limit holds as before.
"""

import json

from app.recipe_run import cap, slot_map
from app.schemas import RecipeGraph
from tests.conftest import Gate
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import OWN, teams_of
from tests.test_discussion import discuss
from tests.test_parallel import until
from tests.test_recipe_run_scenarios import READY, answer, asked, by_call, made, manual, row
from tests.test_recipes_scenarios import graph
from tests.test_recipes_scenarios import step as part
from tests.test_room_open_scenarios import WORK, open_room
from tests.test_room_scenarios import add, edit, finish, post, take, wait
from tests.test_spawn import begin, call, spawn, step
from tests.test_take_in_scenarios import needs_git, repository

HI, YO = b"print('hi')\n", b"print('yo')\n"


def at_once(client, name, roles, end="in"):
    """One "all at once" group of a step a role."""
    return made(client, name, graph(
        [part(f"s{at}", role, {"role": role}, group="g") for at, role in enumerate(roles)],
        [("start", "g"), ("g", "end")], groups=[{"id": "g", "name": name}],
        ends=({"id": "end", "then": end},)))


def meeting(client, roles=("Coder", "Reviewer")):
    return made(client, "Meet on it", graph(
        [part("meet", "Design meeting", {"room": list(roles)})], [("start", "meet"), ("meet", "end")]))


def call_of(snap, name):
    return next((t["status"], t["result"]) for t in snap["tool_calls"] if t["name"] == name)


# --- a room inside a step: the Take-in guarantee ----------------------------------------------


def test_a_room_inside_a_step_leaves_the_project_untouched_without_take_in(make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [open_room(), text("done")], **WORK,
    })
    web = teams_of(client)["Web app"]
    cid, run_id = manual(client, project_dir, (web, at_once(client, "Fix it together", ["Coder", "Reviewer"])))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"], timeout=15)
    # The room is over and its step with it: its work waits in the recipe's copy.
    assert (project_dir / "hello.py").read_bytes() == HI
    assert snap["rooms"][0]["status"] == "ended" and row(snap)["status"] == "ready"
    members = {m["agent_id"] for m in snap["rooms"][0]["members"]}
    assert members <= set(row(snap)["agents"]) and len(members) == 2
    assert not [m for m in snap["merges"] if m["status"] == "pending"]
    answer(client, asked(snap), "Ask for changes")  # (no Take in: the turn then ends)
    snap = wait_run(client, cid, run_id, timeout=15)
    assert (project_dir / "hello.py").read_bytes() == HI
    assert row(snap)["status"] == "stopped"
    status, said = call_of(snap, "open_room")
    assert status == "succeeded" and "Take in" in said and "at its end" in said


def test_a_room_step_runs_to_ready_for_you_and_take_in_takes_its_work_in(make_client, wait_run, project_dir):
    client, model = make_client({
        "Lead": [spawn("Coder", "fix it", "c0"), open_room(members=("Coder", "Tester"), id="o0"), open_room(),
                 text("done")],
        **WORK,
    })
    web = teams_of(client)["Web app"]
    cid, run_id = manual(client, project_dir, (web, meeting(client)))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"], timeout=15)
    assert (project_dir / "hello.py").read_bytes() == HI
    # The step strip says it is a room.
    assert [(s["name"], s["room"]) for s in row(snap)["steps"]] == [("Design meeting", True), ("You", False)]
    # The Lead was told the step is a room, with its roles.
    offered = next(t["function"] for t in model.tool_args[0] if t["function"]["name"] == "spawn_agent")
    assert "a room" in offered["description"] and "open_room" in offered["description"]
    answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id, timeout=15)
    assert (project_dir / "hello.py").read_bytes() == YO and row(snap)["status"] == "in"
    refused, partial = by_call(snap)[0], [t for t in snap["tool_calls"] if t["name"] == "open_room"][0]
    assert refused[0] == "failed" and "open_room" in refused[1]
    assert partial["status"] == "failed" and "Reviewer" in partial["result"]


@needs_git
def test_a_room_steps_take_in_is_the_rooms_and_its_commit_is_named_by_its_goal(make_client, wait_run, project_dir):
    # B-120 (live): the merge of a recipe's room step had no room_id, and its commit was offered as "Lead".
    repository(project_dir)
    client, _model = make_client({"Lead": [open_room(), text("done")], **WORK})
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], meeting(client)))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"], timeout=15)
    pid = snap["conversation"]["project_id"]
    assert client.patch(f"/api/projects/{pid}", json={"git_commit": True}, headers=OWN).status_code == 200
    answer(client, asked(snap), "Take in")
    snap = until(client, cid, lambda s: any(m["commit"] for m in s["merges"]), timeout=15)
    (merge,) = [m for m in snap["merges"] if m["status"] == "applied"]
    assert merge["room_id"] == snap["rooms"][0]["id"]
    assert merge["commit"]["message"] == "Room: Fix the greeting together"
    wait_run(client, cid, run_id, timeout=15)


def meet_then_build(client):
    return made(client, "Meet then build", graph(
        [part("meet", "Design meeting", {"room": ["Coder", "Reviewer"]}), part("build", "Build it", {"role": "Coder"})],
        [("start", "meet"), ("meet", "build"), ("build", "end")]))


def taken_in(make_client, project_dir, lead, recipe):
    """A recipe's turn taken in, with commits on: its merge once it is offered, and the snapshot."""
    repository(project_dir)
    client, _model = make_client({"Lead": [*lead, text("done")], **WORK, "Coder 2": [text("built")]})
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], recipe(client)))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"], timeout=15)
    pid = snap["conversation"]["project_id"]
    assert client.patch(f"/api/projects/{pid}", json={"git_commit": True}, headers=OWN).status_code == 200
    answer(client, asked(snap), "Take in")
    snap = until(client, cid, lambda s: any(m["commit"] for m in s["merges"]), timeout=15)
    until(client, cid, lambda s: s["runs"][0]["status"] == "completed", timeout=15)
    return next(m for m in snap["merges"] if m["status"] == "applied"), snap


@needs_git
def test_a_room_opened_inside_a_step_is_not_the_recipes_take_in(make_client, wait_run, project_dir):
    # (The review: the turn's newest room was taken for a Room step's, its goal for the commit.)
    merge, _snap = taken_in(make_client, project_dir, [open_room()],
                            lambda client: at_once(client, "Fix it together", ["Coder", "Reviewer"]))
    assert merge["room_id"] is None and not merge["commit"]["message"].startswith("Room:")


@needs_git
def test_a_room_step_beside_other_steps_does_not_name_the_whole_commit(make_client, wait_run, project_dir):
    merge, snap = taken_in(make_client, project_dir, [open_room(), spawn("Coder", "build it", "c1")], meet_then_build)
    assert merge["room_id"] == snap["rooms"][0]["id"]
    assert not merge["commit"]["message"].startswith("Room:")


def kept_then_taken(make_client, wait_run, project_dir, lead, recipe):
    """A recipe's turn ended at Ready for you without Take in (its work kept), its kept copy then
    taken in, with commits on: its merge once a commit is offered, and the snapshot."""
    repository(project_dir)
    client, _model = make_client({"Lead": [*lead, text("done")], **WORK, "Coder 2": [text("built")]})
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], recipe(client)))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"], timeout=15)
    pid = snap["conversation"]["project_id"]
    assert client.patch(f"/api/projects/{pid}", json={"git_commit": True}, headers=OWN).status_code == 200
    answer(client, asked(snap), "Ask for changes")  # (and the Lead ends its turn)
    snap = wait_run(client, cid, run_id, timeout=15)
    (kept,) = [m for m in snap["merges"] if m["status"] == "kept"]
    taken = client.post(f"/api/merges/{kept['id']}/approve", json={"choices": {}}, headers=OWN)
    assert taken.status_code == 200, taken.text
    snap = until(client, cid, lambda s: any(m["commit"] for m in s["merges"]), timeout=15)
    return next(m for m in snap["merges"] if m["id"] == kept["id"]), snap


@needs_git
def test_a_room_steps_work_kept_and_taken_in_later_is_the_rooms(make_client, wait_run, project_dir):
    # (batch-20: B-120's room was on a Take in at Ready for you only - not on its kept copy's.)
    merge, snap = kept_then_taken(make_client, wait_run, project_dir, [open_room()], meeting)
    assert merge["status"] == "applied" and merge["room_id"] == snap["rooms"][0]["id"]
    assert merge["commit"]["message"] == "Room: Fix the greeting together"


@needs_git
def test_a_room_step_beside_others_kept_and_taken_in_later_does_not_name_the_commit(make_client, wait_run, project_dir):
    merge, snap = kept_then_taken(make_client, wait_run, project_dir, [open_room(), spawn("Coder", "build it", "c1")],
                                  meet_then_build)
    assert merge["room_id"] == snap["rooms"][0]["id"]
    assert not merge["commit"]["message"].startswith("Room:")


def test_a_teams_lead_opens_a_room_in_its_step_and_its_work_is_the_recipes(make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Web app lead", "task": "the page"}, "l1"),
                      call("spawn_agent", {"role": "Docs lead", "task": "the words"}, "l2")), text("done")],
        "Web app lead": [open_room(), text("web done")],
        "Docs lead": [spawn("Docs writer", "write b.md", "d"), text("docs done")],
        "Docs writer": [step(call("write_file", {"path": "b.md", "content": "b\n"}, "w")), text("written")],
        **WORK,
    })
    teams = teams_of(client)
    lead = teams["Web app"]["lead"]
    assert client.patch(f"/api/roles/{lead['id']}", json={"tools": [*lead["tools"], "open_room"]},
                        headers=OWN).status_code == 200
    words = made(client, "Just write", graph([part("do", "Write", {"role": "Docs writer"})],
                                             [("start", "do"), ("do", "end")]))
    cid, run_id = manual(client, project_dir, (teams["Web app"], at_once(client, "Fix it together", ["Coder", "Reviewer"])),
                         (teams["Docs"], words))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"], timeout=20)
    assert (project_dir / "hello.py").read_bytes() == HI and not (project_dir / "b.md").exists()
    answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id, timeout=15)
    # Not a copy of the team lead's own, left behind: the room's work came in with the recipe's.
    assert (project_dir / "hello.py").read_bytes() == YO and (project_dir / "b.md").exists()


def test_a_teams_lead_asks_the_user_nothing_while_its_recipe_runs_its_roles_do_the_work(
        make_client, wait_run, project_dir):
    """B-202 (live): a team's lead, with no tool that writes, asked the user to route its file
    work to a Coder - refused, told where its recipe is and that its roles do the work."""
    client, model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Web app lead", "task": "the page"}, "l1"),
                      call("spawn_agent", {"role": "Docs lead", "task": "the words"}, "l2")), text("done")],
        "Web app lead": [step(call("ask_user", {"question": "Please route this to a Coder step "
                                                "with file editing tools."}, "q")),
                         spawn("Coder", "change the greeting", "c"), text("web done")],
        "Coder": [step(edit("hi", "yo")), text("changed")],
        "Docs lead": [spawn("Docs writer", "write b.md", "d"), text("docs done")],
        "Docs writer": [step(call("write_file", {"path": "b.md", "content": "b\n"}, "w")), text("written")],
    })
    teams = teams_of(client)
    build = made(client, "Just build", graph([part("do", "Build", {"role": "Coder"})],
                                             [("start", "do"), ("do", "end")]))
    words = made(client, "Just write", graph([part("do", "Write", {"role": "Docs writer"})],
                                             [("start", "do"), ("do", "end")]))
    cid, _run_id = manual(client, project_dir, (teams["Web app"], build), (teams["Docs"], words))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"], timeout=20)
    (refused,) = [(t["status"], t["result"]) for t in snap["tool_calls"] if t["name"] == "ask_user"]
    assert refused[0] == "denied" and "does not ask the user" in refused[1]
    assert "Build step, for Coder" in refused[1]
    assert not [q for q in snap["questions"] if "route" in q["question"]]   # never the user's card
    assert "ask the user nothing" in json.dumps(model.calls_of["Web app lead"][0])
    assert (project_dir / "b.md").exists() is False and (project_dir / "hello.py").read_bytes() == HI


# --- a discussion inside a step -----------------------------------------------------------------


def test_a_discussion_inside_a_recipe_is_its_steps_work(make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [discuss("Is hello.py fine?", ["Reviewer", "Tester"], rounds=1), text("Fine by me."), text("done")],
        "Reviewer": [text("Looks fine.")], "Tester": [text("It prints hi.")],
    })
    web = teams_of(client)["Web app"]
    cid, run_id = manual(client, project_dir, (web, at_once(client, "Talk it over", ["Reviewer", "Tester"], end="report")))
    snap = wait_run(client, cid, run_id, timeout=15)
    status, said = call_of(snap, "discuss")
    assert status == "succeeded" and "at its end" in said
    assert row(snap)["status"] == "done"
    opened = [a["id"] for a in snap["agents"] if a["role_name"] in ("Reviewer", "Tester")]
    assert len(opened) == 2 and set(opened) <= set(row(snap)["agents"])


def test_no_cli_that_works_in_the_project_itself_joins_a_discussion_in_a_recipe(
        make_client, wait_run, project_dir, monkeypatch):
    # (Gone on with later, such a member would write in the project itself: no Take in.)
    monkeypatch.setattr("app.agent.only_in_project", lambda model, tools=None: True)
    monkeypatch.setattr("app.agent.cards.only_in_project", lambda model, tools=None: True)
    monkeypatch.setattr("app.agent.discussions_mixin.only_in_project", lambda model, tools=None: True)
    monkeypatch.setattr("app.agent.spawn_mixin.only_in_project", lambda model, tools=None: True)
    client, _model = make_client({
        "Lead": [discuss("Is hello.py fine?", ["Reviewer", "Tester"], rounds=1), text("done")],
    })
    web = teams_of(client)["Web app"]
    cid, run_id = manual(client, project_dir, (web, at_once(client, "Talk it over", ["Reviewer", "Tester"])))
    snap = wait_run(client, cid, run_id)
    status, said = call_of(snap, "discuss")
    assert status == "failed" and "in the project itself" in said
    assert [a["name"] for a in snap["agents"]] == ["Lead"]


# --- the drawing sets the limit -----------------------------------------------------------------

SEVEN = ("Coder", "Reviewer", "Tester", "UI designer", "Security reviewer", "Docs writer", "Architect")


def test_a_seven_role_step_opens_all_seven_on_a_chat_that_lets_six(make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [step(*(call("spawn_agent", {"role": role, "task": "do your part"}, f"x{at}")
                        for at, role in enumerate(SEVEN))),
                 spawn("Coder", "one more", "extra"), text("done")],
        **{role: [text("my part is done")] for role in SEVEN},
    })
    web = teams_of(client)["Web app"]
    cid, run_id = manual(client, project_dir, (web, at_once(client, "Everyone at once", SEVEN, end="report")))
    snap = wait_run(client, cid, run_id, timeout=20)
    assert client.get(f"/api/conversations/{cid}").json()["conversation"]["spawn_max_agents"] == 6
    calls = by_call(snap)
    assert [status for status, _ in calls[:7]] == ["succeeded"] * 7
    # (The recipe is at its end by then: nothing more is opened for it.)
    assert calls[7][0] == "failed"
    assert row(snap)["status"] == "done"


def test_one_step_opens_as_many_as_it_draws_and_no_more(make_client, wait_run, project_dir, gate):
    client, _model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "a"}, "c1"),
                      call("spawn_agent", {"role": "Coder", "task": "b"}, "c2")), text("done")],
        "Coder": [gate.step(text("built"))], "Coder 2": [text("built")],
    })
    web = teams_of(client)["Web app"]
    build = made(client, "Just build", graph([part("do", "Build it", {"role": "Coder"})], [("start", "do"), ("do", "end")],
                                             ends=({"id": "end", "then": "report"},)))
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never", teams_mode="manual",
                        spawn_max_agents=20, teams=[{"team_id": web["id"], "recipe_id": build["id"]}])
    gate.wait_partial()
    until(client, cid, lambda s: [c for c in by_call(s) if c[0] == "failed"])
    gate.release()
    snap = wait_run(client, cid, run_id)
    refused = [said for status, said in by_call(snap) if status == "failed"]
    assert len(refused) == 1 and "Build it" in refused[0] and "draws 1" in refused[0]


def test_the_runs_total_comes_from_the_drawing():
    reviews = [part(f"r{at}", role, {"role": role}, group="g", done_when="no_findings")
               for at, role in enumerate(("Reviewer", "Tester", "UI designer", "Security reviewer"))]
    looped = RecipeGraph.model_validate(graph(
        [part("meet", "Meet", {"room": ["Architect", "Coder", "UI designer"]}), part("build", "Build", {"role": "Coder"}),
         *reviews],
        [("start", "meet"), ("meet", "build"), ("build", "g"), ("g", "end")],
        loops=[{"from": "g", "to": "build", "rounds": 3}], groups=[{"id": "g", "name": "Reviews"}]))

    def one_each(step):
        return [(role,) for role in step.who.room] if hasattr(step.who, "room") else [(getattr(step.who, "role", "x"),)]

    # The meeting's 3, then Build and its 4 reviews 4 times over (once, and 3 rounds back): 3 + 20.
    assert cap(looped, slot_map(looped, one_each)) == 23


def test_the_lead_is_told_what_the_step_draws_and_the_runs_total(make_client, wait_run, project_dir):
    client, model = make_client({"Lead": [text("nothing to do")]})
    web = teams_of(client)["Web app"]
    cid, run_id = manual(client, project_dir, (web, at_once(client, "Fix it together", ["Coder", "Reviewer"])))
    wait_run(client, cid, run_id)
    offered = next(t["function"] for t in model.tool_args[0] if t["function"]["name"] == "spawn_agent")
    assert "for Coder, Reviewer: it draws 2 agents, 2 in all for the run" in offered["description"]


def test_the_chats_limit_still_holds_outside_a_recipe(make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [spawn("Coder", "a", "c1"), spawn("Coder", "b", "c2"), text("done")],
        "Coder": [text("built")],
    })
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never", spawn_max_agents=1)
    snap = wait_run(client, cid, run_id)
    calls = by_call(snap)
    assert calls[0][0] == "succeeded" and calls[1][0] == "failed" and "per turn" in calls[1][1]


# --- a Room step is checked as it is saved ------------------------------------------------------


def saving(client, drawn):
    return client.post("/api/recipes", json={"name": "Meet", "graph": drawn}, headers=OWN)


def test_a_room_step_is_checked_as_it_is_saved(make_client):
    client, _model = make_client({})
    one = saving(client, graph([part("m", "Meet", {"room": ["Coder"]})], [("start", "m"), ("m", "end")]))
    seven = saving(client, graph([part("m", "Meet", {"room": list(SEVEN)})],
                                [("start", "m"), ("m", "end")]))
    nobody = saving(client, graph([part("m", "Meet", {"room": ["Coder", "Nobody"]})], [("start", "m"), ("m", "end")]))
    twice = saving(client, graph([part("m", "Meet", {"room": ["Coder", "coder"]})], [("start", "m"), ("m", "end")]))
    grouped = saving(client, graph([part("m", "Meet", {"room": ["Coder", "Reviewer"]}, group="g"),
                                    part("b", "Build", {"role": "Coder"}, group="g")],
                                   [("start", "g"), ("g", "end")], groups=[{"id": "g", "name": "At once"}]))
    for refused in (one, seven, nobody, twice, grouped):
        assert refused.status_code == 422, refused.text
        assert any(p.get("at") == "m" for p in refused.json()["detail"]), refused.text
    # A room may be a loop's target: findings go back to the meeting.
    looped = saving(client, graph(
        [part("m", "Meet", {"room": ["Coder", "Reviewer"]}), part("r", "Review", {"role": "Reviewer"}, done_when="no_findings")],
        [("start", "m"), ("m", "r"), ("r", "end")], loops=[{"from": "r", "to": "m", "rounds": 2}]))
    assert looped.status_code == 201, looped.text


# --- review round (84e): the Take-in guarantee on every way --------------------------------------


def test_a_room_inside_a_recipe_takes_in_one_more_of_its_steps_roles_and_its_work_stays_in_the_copy(
        make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [open_room(), text("done")],
        "Coder": [step(add("Change the greeting", ["hello.py"], "a1"), take(1, "t1")),
                  step(call("invite_to_room", {"role": "Architect"}, "i1")),
                  step(call("invite_to_room", {"role": "Debugger"}, "i2")),
                  step(edit("hi", "yo")), step(finish(1, "hello.py prints yo", "f1")), text("My part is done.")],
        "Reviewer": WORK["Reviewer"],
        "Debugger": [step(add("Debug it", ["b.py"], "a3"), take(3, "t3")),
                     step(call("write_file", {"path": "b.py", "content": "b\n"}, "w3")),
                     step(finish(3, "b.py written", "f3")), text("Done here.")],
    })
    web = teams_of(client)["Web app"]
    cid, run_id = manual(client, project_dir, (web, at_once(client, "Three of us", ["Coder", "Reviewer", "Debugger"])))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"], timeout=20)
    invites = [(t["status"], t["result"]) for t in snap["tool_calls"] if t["name"] == "invite_to_room"]
    # Not one of the step's roles: refused at the step's door. One of them: a member, and the step's.
    assert invites[0][0] == "failed" and "Architect" in invites[0][1]
    assert invites[1][0] == "succeeded"
    debugger = next(a["id"] for a in snap["agents"] if a["role_name"] == "Debugger")
    assert debugger in row(snap)["agents"]
    assert (project_dir / "hello.py").read_bytes() == HI and not (project_dir / "b.py").exists()
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id, timeout=15)
    assert (project_dir / "hello.py").read_bytes() == YO and (project_dir / "b.py").read_bytes() == b"b\n"


def test_a_room_in_a_recipe_that_ends_on_its_minutes_leaves_its_work_in_the_copy(make_client, wait_run, project_dir):
    from tests.test_triggers import HeldClock, on_loop
    held, clock = Gate(), HeldClock()
    client, _model = make_client({
        "Lead": [open_room(), text("done")],
        "Coder": [step(add("Change the greeting", ["hello.py"], "a1"), take(1, "t1")), step(edit("hi", "yo")),
                  held.step(text("never said"))],
        "Reviewer": [text("Nothing to add."), wait(), text("never said")],
    })
    client.app.state.runner.call_later = clock
    web = teams_of(client)["Web app"]
    cid, run_id = manual(client, project_dir, (web, meeting(client)))
    held.wait_partial()
    assert len(clock.set) == 1
    on_loop(client, clock.set[0].fire)
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"], timeout=20)
    held.release()
    assert snap["rooms"][0]["outcome"] == "budget" and (project_dir / "hello.py").read_bytes() == HI
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id, timeout=15)
    assert (project_dir / "hello.py").read_bytes() == YO


def test_a_room_steps_failed_member_is_skipped_or_stopped_never_tried_again_alone(
        make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [open_room(), text("done")],
        "Coder": WORK["Coder"], "Reviewer": [RuntimeError("its model broke")],
    })
    web = teams_of(client)["Web app"]
    cid, run_id = manual(client, project_dir, (web, meeting(client)))
    card = asked(until(client, cid, lambda s: asked(s) and "failed" in asked(s)["question"], timeout=20))
    assert card["options"] == ["Skip", "Stop"]
    answer(client, card, "Stop")
    snap = wait_run(client, cid, run_id, timeout=15)
    assert row(snap)["status"] == "stopped" and (project_dir / "hello.py").read_bytes() == HI


def test_a_room_step_two_of_whose_members_failed_asks_once_for_the_step(
        make_client, wait_run, project_dir):
    """B-203 (live): two members of a Room step ran out of steps - and the user was asked Skip
    or Stop twice for one step. One answer is the step's."""
    roles = ("Coder", "Reviewer", "Tester")
    client, _model = make_client({
        "Lead": [open_room(members=roles), text("done")],
        "Coder": WORK["Coder"], "Reviewer": [RuntimeError("its model broke")],
        "Tester": [RuntimeError("its model broke too")],
    })
    web = teams_of(client)["Web app"]
    cid, run_id = manual(client, project_dir, (web, meeting(client, roles)))
    card = asked(until(client, cid, lambda s: asked(s) and "failed" in asked(s)["question"], timeout=20))
    answer(client, card, "Skip")
    snap = wait_run(client, cid, run_id, timeout=15)
    # (Its room ended at once, two of three gone: nothing was written, so no Take in.)
    assert [q["id"] for q in snap["questions"]] == [card["id"]] and row(snap)["status"] == "done"


def test_an_agent_beside_a_recipe_is_kept_for_the_user_and_its_kept_copy_is_not_the_recipes(
        settings_env, project_dir):
    # A role the user named passes the step's door without being one of its agents: its work, kept
    # as a kept copy, is not the recipe's - taken in, it leaves the row as it was (after a restart too).
    from app.config import load_settings
    from app.main import create_app
    from tests.fakes import ScriptedModel
    from tests.keyed import TestClient
    from tests.test_copy_later_scenarios import again
    from tests.test_recipe_run_scenarios import write
    app_ = create_app(load_settings(settings_env), model=ScriptedModel({
        # (Told twice the recipe's next step is left, B-83.)
        "Lead": [spawn("Debugger", "debug it", "d"), spawn("Coder", "build", "c"), *[text("I stop here")] * 3],
        "Debugger": [step(write("b.py", "b\n", id="wb")), text("debugged")],
        "Coder": [step(write("a.py", "a\n")), text("built")],
    }))
    with TestClient(app_, base_url="http://127.0.0.1:8790") as client:
        client.headers.update(OWN)
        web = teams_of(client)["Web app"]
        two = made(client, "Build then test", graph(
            [part("build", "Build it", {"role": "Coder"}), part("test", "Test it", {"role": "Tester"})],
            [("start", "build"), ("build", "test"), ("test", "end")]))
        cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never", teams_mode="manual",
                            content="fix it, with the Debugger too",
                            teams=[{"team_id": web["id"], "recipe_id": two["id"]}])
        snap = until(client, cid, lambda s: s["runs"][0]["status"] == "completed")
        debugged = next(t["result"] for t in snap["tool_calls"] if t["name"] == "spawn_agent")
        assert debugged.startswith("Debugger finished") and "kept copy" in debugged
        assert not (project_dir / "b.py").exists() and not (project_dir / "a.py").exists()
    with again(settings_env) as client:
        snap = client.get(f"/api/conversations/{cid}").json()
        lead = next(a["id"] for a in snap["agents"] if a["depth"] == 0)
        kept = {m["agent_id"] == lead: m for m in snap["merges"] if m["status"] == "kept"}
        assert set(kept) == {True, False}
        assert client.post(f"/api/merges/{kept[False]['id']}/approve", json={"choices": {}}).status_code == 200
        assert (project_dir / "b.py").exists() and not (project_dir / "a.py").exists()
        assert row(client.get(f"/api/conversations/{cid}").json())["status"] == "stopped"
        assert client.post(f"/api/merges/{kept[True]['id']}/approve", json={"choices": {}}).status_code == 200
        assert (project_dir / "a.py").exists()
        assert row(client.get(f"/api/conversations/{cid}").json())["status"] == "in"


def test_a_project_that_cannot_be_copied_runs_no_recipe(make_client, wait_run, project_dir, monkeypatch):
    from app import copies
    monkeypatch.setattr(copies, "MAX_FILES", 0)
    client, _model = make_client({"Lead": [spawn("Coder", "build"), text("could not")]})
    web = teams_of(client)["Web app"]
    cid, run_id = manual(client, project_dir, (web, at_once(client, "Fix it together", ["Coder", "Reviewer"])))
    snap = wait_run(client, cid, run_id)
    ((status, said),) = by_call(snap)
    assert status == "failed" and "could not be copied" in said and "Take in" in said
    assert (row(snap)["status"], "could not be copied" in row(snap)["why"]) == ("failed", True)
    assert [a["name"] for a in snap["agents"]] == ["Lead"]


def test_a_room_step_its_lead_follows_ends_its_step_as_one_it_waits_for(
    make_client, wait_run, project_dir
):
    """K-oda-lead: followed, the room of a step is over the same way: its record and where the
    recipe is now come with whichever call of the Lead's sees its end."""
    held = Gate()
    client, _model = make_client({
        "Lead": [open_room(follow=True), step(call("wait_for_room", {}, "w")), text("done")],
        "Coder": WORK["Coder"],
        # (it tells the Lead, which wakes it)
        "Reviewer": [step(add("Review the greeting", id="a2"), take(2, "t2")),
                     step(post("result", "Reviewing it.", "p1", to="Lead")),
                     held.step(step(finish(2, "It prints yo, as asked.", "f2"))),
                     text("Looked at it: fine.")],
    })
    web = teams_of(client)["Web app"]
    cid, run_id = manual(client, project_dir, (web, at_once(client, "Fix it together", ["Coder", "Reviewer"])))
    until(client, cid, lambda s: any(t["name"] == "open_room" and t["status"] == "succeeded"
                                     for t in s["tool_calls"]), timeout=15)
    held.release()  # (the room ends once the Lead follows it)
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"], timeout=15)
    assert (project_dir / "hello.py").read_bytes() == HI
    assert snap["rooms"][0]["status"] == "ended" and row(snap)["status"] == "ready"
    answer(client, asked(snap), "Ask for changes")
    snap = wait_run(client, cid, run_id, timeout=15)
    assert (project_dir / "hello.py").read_bytes() == HI
    assert row(snap)["status"] == "stopped"
    status, said = call_of(snap, "open_room")
    assert status == "succeeded" and "The room you follow runs on" in said
    status, said = call_of(snap, "wait_for_room")
    assert status == "succeeded" and "Take in" in said and "at its end" in said
