"""Slice 84e's acceptance set: discussions inside a recipe; the drawing sets the limit. Written
before the code. (Its rooms went with rooms, 0.1.10: a Room step drawn before is an "All at once"
group of its roles.)

Design: `tasarim/specs/2026-10-23-dilim-63-84-takimlar-tarifler-design.md` §6 item 5 (84e).

Contract:
- A discussion inside a recipe: its new members are the step's agents; it writes no files.
- The drawing sets the limit: a step opens as many agents as it draws (a role one, a team a role
  each), whatever the chat's "Sub-agents per turn"; the run's total is
  counted from the drawing (`recipe_run.cap`) and told with the step. Outside a recipe the
  chat's limit holds as before.
"""

import json
from types import SimpleNamespace

from app.config import load_settings
from app.main import create_app
from app.recipe_run import cap, slot_map
from app.schemas import RecipeGraph
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import OWN, teams_of
from tests.test_claims import edit
from tests.test_discussion import discuss
from tests.test_parallel import until
from tests.test_recipe_run_scenarios import READY, asked, by_call, made, manual, row
from tests.test_recipes_scenarios import graph
from tests.test_recipes_scenarios import step as part
from tests.test_spawn import begin, call, spawn, step

HI, YO = b"print('hi')\n", b"print('yo')\n"


def at_once(client, name, roles, end="in"):
    """One "all at once" group of a step a role."""
    return made(
        client,
        name,
        graph(
            [part(f"s{at}", role, {"role": role}, group="g") for at, role in enumerate(roles)],
            [("start", "g"), ("g", "end")],
            groups=[{"id": "g", "name": name}],
            ends=({"id": "end", "then": end},),
        ),
    )


def call_of(snap, name):
    return next((t["status"], t["result"]) for t in snap["tool_calls"] if t["name"] == name)


def test_a_teams_lead_asks_the_user_nothing_while_its_recipe_runs_its_roles_do_the_work(
    make_client, wait_run, project_dir
):
    """B-202 (live): a team's lead, with no tool that writes, asked the user to route its file
    work to a Coder - refused, told where its recipe is and that its roles do the work."""
    client, model = make_client(
        {
            "Lead": [
                step(
                    call("spawn_agent", {"role": "Web app lead", "task": "the page"}, "l1"),
                    call("spawn_agent", {"role": "Docs lead", "task": "the words"}, "l2"),
                ),
                text("done"),
            ],
            "Web app lead": [
                step(
                    call(
                        "ask_user",
                        {"question": "Please route this to a Coder step with file editing tools."},
                        "q",
                    )
                ),
                spawn("Coder", "change the greeting", "c"),
                text("web done"),
            ],
            "Coder": [edit("hi", "yo"), text("changed")],
            "Docs lead": [spawn("Docs writer", "write b.md", "d"), text("docs done")],
            "Docs writer": [
                step(call("write_file", {"path": "b.md", "content": "b\n"}, "w")),
                text("written"),
            ],
        }
    )
    teams = teams_of(client)
    build = made(
        client,
        "Just build",
        graph([part("do", "Build", {"role": "Coder"})], [("start", "do"), ("do", "end")]),
    )
    words = made(
        client,
        "Just write",
        graph([part("do", "Write", {"role": "Docs writer"})], [("start", "do"), ("do", "end")]),
    )
    cid, _run_id = manual(client, project_dir, (teams["Web app"], build), (teams["Docs"], words))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"], timeout=20)
    (refused,) = [(t["status"], t["result"]) for t in snap["tool_calls"] if t["name"] == "ask_user"]
    assert refused[0] == "denied" and "does not ask the user" in refused[1]
    assert "Build step, for Coder" in refused[1]
    assert not [q for q in snap["questions"] if "route" in q["question"]]  # never the user's card
    assert "ask the user nothing" in json.dumps(model.calls_of["Web app lead"][0])
    assert (project_dir / "b.md").exists() is False and (
        project_dir / "hello.py"
    ).read_bytes() == HI


# --- a discussion inside a step -----------------------------------------------------------------


def test_a_discussion_inside_a_recipe_is_its_steps_work(make_client, wait_run, project_dir):
    client, _model = make_client(
        {
            "Lead": [
                discuss("Is hello.py fine?", ["Reviewer", "Tester"], rounds=1),
                text("Fine by me."),
                text("done"),
            ],
            "Reviewer": [text("Looks fine.")],
            "Tester": [text("It prints hi.")],
        }
    )
    web = teams_of(client)["Web app"]
    cid, run_id = manual(
        client,
        project_dir,
        (web, at_once(client, "Talk it over", ["Reviewer", "Tester"], end="report")),
    )
    snap = wait_run(client, cid, run_id, timeout=15)
    status, said = call_of(snap, "discuss")
    assert status == "succeeded" and "at its end" in said
    assert row(snap)["status"] == "done"
    opened = [a["id"] for a in snap["agents"] if a["role_name"] in ("Reviewer", "Tester")]
    assert len(opened) == 2 and set(opened) <= set(row(snap)["agents"])


def test_no_cli_that_works_in_the_project_itself_joins_a_discussion_in_a_recipe(
    make_client, wait_run, project_dir, monkeypatch
):
    # (Gone on with later, such a member would write in the project itself: no Take in.)
    monkeypatch.setattr("app.agent.only_in_project", lambda model, tools=None: True)
    monkeypatch.setattr("app.agent.cards.only_in_project", lambda model, tools=None: True)
    monkeypatch.setattr(
        "app.agent.discussions_mixin.only_in_project", lambda model, tools=None: True
    )
    monkeypatch.setattr("app.agent.spawn_mixin.only_in_project", lambda model, tools=None: True)
    client, _model = make_client(
        {
            "Lead": [discuss("Is hello.py fine?", ["Reviewer", "Tester"], rounds=1), text("done")],
        }
    )
    web = teams_of(client)["Web app"]
    cid, run_id = manual(
        client, project_dir, (web, at_once(client, "Talk it over", ["Reviewer", "Tester"]))
    )
    snap = wait_run(client, cid, run_id)
    status, said = call_of(snap, "discuss")
    assert status == "failed" and "in the project itself" in said
    assert [a["name"] for a in snap["agents"]] == ["Lead"]


# --- the drawing sets the limit -----------------------------------------------------------------

SEVEN = (
    "Coder",
    "Reviewer",
    "Tester",
    "UI designer",
    "Security reviewer",
    "Docs writer",
    "Architect",
)


def test_a_seven_role_step_opens_all_seven_on_a_chat_that_lets_six(
    make_client, wait_run, project_dir
):
    client, _model = make_client(
        {
            "Lead": [
                step(
                    *(
                        call("spawn_agent", {"role": role, "task": "do your part"}, f"x{at}")
                        for at, role in enumerate(SEVEN)
                    )
                ),
                spawn("Coder", "one more", "extra"),
                text("done"),
            ],
            **{role: [text("my part is done")] for role in SEVEN},
        }
    )
    web = teams_of(client)["Web app"]
    cid, run_id = manual(
        client, project_dir, (web, at_once(client, "Everyone at once", SEVEN, end="report"))
    )
    snap = wait_run(client, cid, run_id, timeout=20)
    assert client.get(f"/api/conversations/{cid}").json()["conversation"]["spawn_max_agents"] == 6
    calls = by_call(snap)
    assert [status for status, _ in calls[:7]] == ["succeeded"] * 7
    # (The recipe is at its end by then: nothing more is opened for it.)
    assert calls[7][0] == "failed"
    assert row(snap)["status"] == "done"


def test_one_step_opens_as_many_as_it_draws_and_no_more(make_client, wait_run, project_dir, gate):
    client, _model = make_client(
        {
            "Lead": [
                step(
                    call("spawn_agent", {"role": "Coder", "task": "a"}, "c1"),
                    call("spawn_agent", {"role": "Coder", "task": "b"}, "c2"),
                ),
                text("done"),
            ],
            "Coder": [gate.step(text("built"))],
            "Coder 2": [text("built")],
        }
    )
    web = teams_of(client)["Web app"]
    build = made(
        client,
        "Just build",
        graph(
            [part("do", "Build it", {"role": "Coder"})],
            [("start", "do"), ("do", "end")],
            ends=({"id": "end", "then": "report"},),
        ),
    )
    cid, run_id = begin(
        client,
        project_dir,
        mode="auto_edit",
        spawn_approval="never",
        teams_mode="manual",
        spawn_max_agents=20,
        teams=[{"team_id": web["id"], "recipe_id": build["id"]}],
    )
    gate.wait_partial()
    until(client, cid, lambda s: [c for c in by_call(s) if c[0] == "failed"])
    gate.release()
    snap = wait_run(client, cid, run_id)
    refused = [said for status, said in by_call(snap) if status == "failed"]
    assert len(refused) == 1 and "Build it" in refused[0] and "draws 1" in refused[0]


class _AsksTwice(ScriptedModel):
    """A CLI session Lead (its spawn_agent answered "proposed" at once, K-paralel-spawn) that asks
    for the step's Coder again while the first one's card waits; the Coder only answers."""

    session = True

    def __init__(self):
        super().__init__([])
        self.said = []

    async def run_session(
        self,
        model_id,
        messages,
        tools,
        call_tool,
        on_text,
        on_message=None,
        effort=None,
        on_live=None,
    ):
        if "Your name here is Coder" in str(messages[0]["content"]):
            await on_text("built")
        elif not self.said:
            for task in ("a", "b"):
                self.said.append(
                    (await call_tool("spawn_agent", json.dumps({"role": "Coder", "task": task})))[
                        :2
                    ]
                )
            await on_text("asked")
        else:
            await on_text("done")
        return SimpleNamespace(input_tokens=5, output_tokens=1, model=None)


def test_one_more_of_a_step_whose_agents_card_waits_is_told_to_wait_for_the_users_approval(
    settings_env, project_dir
):
    # B-412: "Coder is already at work on it" of one whose card waited read as a step given up on.
    cli = _AsksTwice()
    with TestClient(
        create_app(load_settings(settings_env), model=cli), base_url="http://127.0.0.1:8790"
    ) as client:
        client.headers.update(OWN)
        build = made(
            client,
            "Just build",
            graph(
                [part("do", "Build it", {"role": "Coder"})],
                [("start", "do"), ("do", "end")],
                ends=({"id": "end", "then": "report"},),
            ),
        )
        cid, run_id = begin(
            client,
            project_dir,
            mode="ask",
            teams_mode="manual",
            teams=[{"team_id": teams_of(client)["Web app"]["id"], "recipe_id": build["id"]}],
        )
        # (Its card is looked for until it is there, not read once: a slow runner shows it later.)
        snap = until(
            client,
            cid,
            lambda s: len(cli.said) == 2 and any(a["status"] == "proposed" for a in s["agents"]),
            timeout=15,
        )
        (first, proposed), (second, refused) = cli.said
        assert first and proposed.startswith("proposed: Coder waits") and not second
        assert "Coder waits for the user's approval of its card" in refused, refused
        assert "already at work" not in refused
        (card,) = [a for a in snap["agents"] if a["status"] == "proposed"]
        assert client.post(f"/api/agents/{card['id']}/approve").status_code == 200
        until(client, cid, lambda s: s["runs"][0]["status"] == "completed", timeout=15)


def test_the_runs_total_comes_from_the_drawing():
    reviews = [
        part(f"r{at}", role, {"role": role}, group="g", done_when="no_findings")
        for at, role in enumerate(("Reviewer", "Tester", "UI designer", "Security reviewer"))
    ]
    # (A Room step drawn before 0.1.10: an "All at once" group of its three roles now.)
    looped = RecipeGraph.model_validate(
        graph(
            [
                part("meet", "Meet", {"room": ["Architect", "Coder", "UI designer"]}),
                part("build", "Build", {"role": "Coder"}),
                *reviews,
            ],
            [("start", "meet"), ("meet", "build"), ("build", "g"), ("g", "end")],
            loops=[{"from": "g", "to": "build", "rounds": 3}],
            groups=[{"id": "g", "name": "Reviews"}],
        )
    )

    def one_each(step):
        return [(getattr(step.who, "role", "x"),)]

    # The meeting's 3, then Build and its 4 reviews 4 times over (once, and 3 rounds back): 3 + 20.
    assert cap(looped, slot_map(looped, one_each)) == 23


def test_the_lead_is_told_what_the_step_draws_and_the_runs_total(
    make_client, wait_run, project_dir
):
    client, model = make_client({"Lead": [text("nothing to do")]})
    web = teams_of(client)["Web app"]
    cid, run_id = manual(
        client, project_dir, (web, at_once(client, "Fix it together", ["Coder", "Reviewer"]))
    )
    wait_run(client, cid, run_id)
    offered = next(
        t["function"] for t in model.tool_args[0] if t["function"]["name"] == "spawn_agent"
    )
    assert "for Coder, Reviewer: it draws 2 agents, 2 in all for the run" in offered["description"]


def test_the_chats_limit_still_holds_outside_a_recipe(make_client, wait_run, project_dir):
    client, _model = make_client(
        {
            "Lead": [spawn("Coder", "a", "c1"), spawn("Coder", "b", "c2"), text("done")],
            "Coder": [text("built")],
        }
    )
    cid, run_id = begin(
        client, project_dir, mode="full_auto", spawn_approval="never", spawn_max_agents=1
    )
    snap = wait_run(client, cid, run_id)
    calls = by_call(snap)
    assert calls[0][0] == "succeeded" and calls[1][0] == "failed" and "per turn" in calls[1][1]


# --- a Room step drawn before 0.1.10 -------------------------------------------------------------


def test_a_room_step_drawn_before_is_an_all_at_once_group_of_its_roles(
    make_client, wait_run, project_dir
):
    # Rooms are gone: saved (or in a folder's file) it reads as a group in its place - its arrows
    # still meet it - with a step of each role, which the Lead opens at once with spawn_agent.
    client, model = make_client({"Lead": [text("nothing to do")]})
    saved = made(
        client,
        "Meet on it",
        graph(
            [part("meet", "Design meeting", {"room": ["Coder", "Reviewer"]}, ask_me=True)],
            [("start", "meet"), ("meet", "end")],
        ),
    )
    # (saved: nothing keeps it from running)
    assert saved["agents"] == {"least": 2, "most": 2}, saved
    assert saved["graph"]["groups"] == [{"id": "meet", "name": "Design meeting"}]
    assert [(s["id"], s["who"], s["group"], s["ask_me"]) for s in saved["graph"]["steps"]] == [
        ("meet-1", {"role": "Coder"}, "meet", True),
        ("meet-2", {"role": "Reviewer"}, "meet", True),
    ]
    assert saved["graph"]["arrows"] == [
        {"from": "start", "to": "meet"},
        {"from": "meet", "to": "end"},
    ]
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], saved))
    wait_run(client, cid, run_id)
    offered = next(
        t["function"] for t in model.tool_args[0] if t["function"]["name"] == "spawn_agent"
    )
    assert "for Coder, Reviewer: it draws 2 agents, 2 in all for the run" in offered["description"]


def test_a_room_step_that_ran_in_0_1_9_still_runs(make_client):
    # Whatever a Room step could carry - a condition, a review with the builder among its roles,
    # a loop to it or from it - its recipe is still saved, as one that runs.
    client, _model = make_client({})
    build = part("build", "Build it", {"role": "Coder"})
    looked = part("look", "Code review", {"role": "Reviewer"}, done_when="no_findings")
    cases = {
        # (A group runs on no condition: the room's own is dropped, and the group always runs.)
        "on a problem": (
            [build, looked, part("meet", "Talk", {"room": ["Coder", "Tester"]}, when="problem")],
            [("start", "build"), ("build", "look"), ("look", "meet"), ("meet", "end")],
            [],
        ),
        # (A role that built works in the group; the others review.)
        "a review with its builder": (
            [
                build,
                part(
                    "meet", "Look at it", {"room": ["Coder", "Reviewer"]}, done_when="no_findings"
                ),
            ],
            [("start", "build"), ("build", "meet"), ("meet", "end")],
            [{"from": "meet", "to": "build", "rounds": 2}],
        ),
        "a loop back to it": (
            [part("meet", "Build together", {"room": ["Coder", "Tester"]}), looked],
            [("start", "meet"), ("meet", "look"), ("look", "end")],
            [{"from": "look", "to": "meet", "rounds": 2}],
        ),
    }
    for name, (steps, arrows, loops) in cases.items():
        saved = client.post(
            "/api/recipes",
            headers=OWN,
            json={"name": name, "graph": graph(steps, arrows, loops=loops)},
        )
        assert saved.status_code == 201, (name, saved.text)
        meet = [s for s in saved.json()["graph"]["steps"] if s["group"] == "meet"]
        assert all(s.get("when") is None for s in meet), name
        if name == "a review with its builder":
            assert [(s["who"]["role"], s["done_when"]) for s in meet] == [
                ("Coder", "done"),
                ("Reviewer", "no_findings"),
            ]


def test_a_folders_recipe_file_with_a_room_step_is_read_as_a_group(project_dir):
    from app.recipes import folder_recipes

    folder = project_dir / ".koloni" / "recipes"
    folder.mkdir(parents=True)
    drawn = graph(
        [part("meet", "Design meeting", {"room": ["Coder", "Reviewer"]})],
        [("start", "meet"), ("meet", "end")],
    )
    (folder / "meet.json").write_text(
        json.dumps({"name": "Meet", "graph": drawn}), encoding="utf-8"
    )
    found, broken = folder_recipes(str(project_dir))
    assert broken == []
    ((file, recipe),) = found
    assert file == "meet" and [g.id for g in recipe.graph.groups] == ["meet"]
    assert [(s.who.role, s.group) for s in recipe.graph.steps] == [
        ("Coder", "meet"),
        ("Reviewer", "meet"),
    ]


# What a Room step's converter leaves for the schema to refuse (0.1.10's review): a malformed one
# is said, never a failure of the page.
MALFORMED = {
    "a list for an id": [{"id": ["m"], "name": "m", "who": {"room": ["Coder", "Tester"]}}],
    "a room of 11 roles": [{"id": "m", "name": "m", "who": {"room": [f"R{n}" for n in range(11)]}}],
    "a room that is no list": [{"id": "m", "name": "m", "who": {"room": "Coder"}}],
}


def test_a_malformed_room_step_is_refused_as_any_malformed_recipe(make_client, project_dir):
    client, _model = make_client({})
    for name, steps in MALFORMED.items():
        drawn = {"version": 1, "steps": steps, "ends": [{"id": "end"}], "arrows": []}
        saved = client.post("/api/recipes", headers=OWN, json={"name": "x", "graph": drawn})
        assert saved.status_code == 422, (name, saved.text)
    for name, (groups, ends) in {"groups no list": (5, []), "ends no list": ([], "e")}.items():
        room = [{"id": "m", "name": "m", "who": {"room": ["Coder", "Tester"]}}]
        drawn = {"version": 1, "steps": room, "groups": groups}
        drawn["ends"] = ends
        saved = client.post("/api/recipes", headers=OWN, json={"name": "x", "graph": drawn})
        assert saved.status_code == 422, (name, saved.text)
    # A folder's file of such a shape is listed as broken, beside the rest.
    folder = project_dir / ".koloni" / "recipes"
    folder.mkdir(parents=True)
    drawn = {"version": 1, "steps": MALFORMED["a list for an id"], "groups": 5}
    (folder / "bad.json").write_text(json.dumps({"name": "Bad", "graph": drawn}), "utf-8")
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    listed = client.get(f"/api/recipes?project_id={pid}")
    assert listed.status_code == 200, listed.text
    assert [line.split(" is not read")[0] for line in listed.json()["broken"]] == [
        ".koloni/recipes/bad.json"
    ]
    assert listed.json()["recipes"]  # (KOLONİ's own still there)


def test_two_room_steps_of_one_role_are_saved_again_and_a_review_of_writers_only_says_so(
    make_client,
):
    client, _model = make_client({})
    # Named "<its name> · <role>", one of each name: saved again, as the board saves it.
    twice = graph(
        [
            part("a", "Meet", {"room": ["Coder", "Tester"]}),
            part("b", "Meet", {"room": ["Coder", "Tester"]}),
        ],
        [("start", "a"), ("a", "b"), ("b", "end")],
    )
    saved = made(client, "Twice", twice)
    assert [s["name"] for s in saved["graph"]["steps"]] == [
        "Meet · Coder",
        "Meet · Tester",
        "Meet · Coder 2",
        "Meet · Tester 2",
    ]
    again = client.put(
        f"/api/recipes/{saved['id']}",
        headers=OWN,
        json={"name": "Twice", "graph": saved["graph"]},
    )
    assert again.status_code == 200, again.text
    # A review whose every role works at a step of its own keeps its review: the recipe says
    # who would check its own work, rather than losing the review unseen.
    writers = graph(
        [
            part("build", "Build it", {"role": "Coder"}),
            part("test", "Test it", {"role": "Tester"}),
            part("meet", "Look", {"room": ["Coder", "Tester"]}, done_when="no_findings"),
        ],
        [("start", "build"), ("build", "test"), ("test", "meet"), ("meet", "end")],
    )
    refused = client.post("/api/recipes", headers=OWN, json={"name": "W", "graph": writers})
    assert refused.status_code == 422 and "would check its own work" in refused.text


def test_a_saved_recipe_that_no_longer_reads_is_listed_as_broken(make_client):
    # A Room step of 0.1.9 near the step limit is past it as a group: that recipe is said, the
    # list is not a failure.
    from app.db.models import Recipe

    client, _model = make_client({})
    steps = [part(f"s{n}", f"Step {n}", {"role": "Coder"}) for n in range(59)]
    drawn = graph(
        [*steps, part("meet", "Meet", {"room": ["Coder", "Tester"]})],
        [("start", "s0"), ("s0", "meet"), ("meet", "end")],
    )
    with client.app.state.session_factory() as session:
        session.add(Recipe(name="Too long now", graph=drawn))
        session.commit()
    listed = client.get("/api/recipes")
    assert listed.status_code == 200, listed.text
    assert any(line.startswith("Too long now is not read") for line in listed.json()["broken"])
    assert listed.json()["recipes"]


# --- review round (84e): the Take-in guarantee on every way --------------------------------------


def test_an_agent_beside_a_recipe_is_kept_for_the_user_and_its_kept_copy_is_not_the_recipes(
    settings_env, project_dir
):
    # A role the user named passes the step's door without being one of its agents: its work, kept
    # as a kept copy, is not the recipe's - taken in, it leaves the row as it was (after a restart too).
    from app.config import load_settings
    from app.main import create_app
    from tests.fakes import ScriptedModel
    from tests.keyed import TestClient
    from tests.test_copy_later_scenarios import again
    from tests.test_recipe_run_scenarios import write

    app_ = create_app(
        load_settings(settings_env),
        model=ScriptedModel(
            {
                # (Told twice the recipe's next step is left, B-83.)
                "Lead": [
                    spawn("Debugger", "debug it", "d"),
                    spawn("Coder", "build", "c"),
                    *[text("I stop here")] * 3,
                ],
                "Debugger": [step(write("b.py", "b\n", id="wb")), text("debugged")],
                "Coder": [step(write("a.py", "a\n")), text("built")],
            }
        ),
    )
    with TestClient(app_, base_url="http://127.0.0.1:8790") as client:
        client.headers.update(OWN)
        web = teams_of(client)["Web app"]
        two = made(
            client,
            "Build then test",
            graph(
                [
                    part("build", "Build it", {"role": "Coder"}),
                    part("test", "Test it", {"role": "Tester"}),
                ],
                [("start", "build"), ("build", "test"), ("test", "end")],
            ),
        )
        cid, run_id = begin(
            client,
            project_dir,
            mode="auto_edit",
            spawn_approval="never",
            teams_mode="manual",
            content="fix it, with the Debugger too",
            teams=[{"team_id": web["id"], "recipe_id": two["id"]}],
        )
        snap = until(client, cid, lambda s: s["runs"][0]["status"] == "completed")
        debugged = next(t["result"] for t in snap["tool_calls"] if t["name"] == "spawn_agent")
        assert debugged.startswith("Debugger finished") and "kept copy" in debugged
        assert not (project_dir / "b.py").exists() and not (project_dir / "a.py").exists()
    with again(settings_env) as client:
        snap = client.get(f"/api/conversations/{cid}").json()
        lead = next(a["id"] for a in snap["agents"] if a["depth"] == 0)
        kept = {m["agent_id"] == lead: m for m in snap["merges"] if m["status"] == "kept"}
        assert set(kept) == {True, False}
        assert (
            client.post(
                f"/api/merges/{kept[False]['id']}/approve", json={"choices": {}}
            ).status_code
            == 200
        )
        assert (project_dir / "b.py").exists() and not (project_dir / "a.py").exists()
        assert row(client.get(f"/api/conversations/{cid}").json())["status"] == "stopped"
        assert (
            client.post(f"/api/merges/{kept[True]['id']}/approve", json={"choices": {}}).status_code
            == 200
        )
        assert (project_dir / "a.py").exists()
        assert row(client.get(f"/api/conversations/{cid}").json())["status"] == "in"


def test_a_project_that_cannot_be_copied_runs_no_recipe(
    make_client, wait_run, project_dir, monkeypatch
):
    from app import copies

    monkeypatch.setattr(copies, "MAX_FILES", 0)
    client, _model = make_client({"Lead": [spawn("Coder", "build"), text("could not")]})
    web = teams_of(client)["Web app"]
    cid, run_id = manual(
        client, project_dir, (web, at_once(client, "Fix it together", ["Coder", "Reviewer"]))
    )
    snap = wait_run(client, cid, run_id)
    ((status, said),) = by_call(snap)
    assert status == "failed" and "could not be copied" in said and "Take in" in said
    assert (row(snap)["status"], "could not be copied" in row(snap)["why"]) == ("failed", True)
    assert [a["name"] for a in snap["agents"]] == ["Lead"]
