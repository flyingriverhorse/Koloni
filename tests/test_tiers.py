"""Slice 28a's edges: what the acceptance set (tests/test_tier_scenarios.py) leaves open."""

import pytest
from sqlalchemy import select

from app.db.models import Agent, OwnRequest, Provider, Role
from app.model_client import ModelUnavailable
from app.roles import seed_builtin_roles
from tests.test_board_scenarios import go, talk
from tests.test_chat_flow import text
from tests.test_max_agents import cancel, queued
from tests.test_spawn import begin, call, role_id, step
from tests.test_team import results, team  # noqa: F401  (a fixture)
from tests.test_tier_scenarios import ORIGIN, WHY, role_tier, spawn, tiered
from tests.test_trigger_scenarios import run_now, trigger


def table(client, cid=None):
    return {row["role"]: row for row in client.get(
        "/api/roles/models", params={"conversation_id": cid} if cid else None).json()}


# --- a tier on a model ----------------------------------------------------------------------


def test_agents_read_a_models_tier_beside_it_and_a_model_without_one_reads_as_before():
    from app.team import describe, guide

    listed = describe(guide([Provider(
        id="fast", name="Fast", kind="openai_compat", for_agents=True, default_model="quick",
        models=[{"name": "quick", "tier": "fast"}, {"name": "plain", "note": None},
                {"name": "deep", "note": "slow", "tier": "balanced"}])]))
    assert 'Models: "quick" (fast tier), "plain", "deep" (balanced tier; "slow").' in listed


def test_a_models_tier_stays_when_something_else_of_its_provider_is_saved(team):  # noqa: F811
    client, _default, _fast = team([text("x")])
    _local, fast = tiered(team, client)
    kept = client.patch(f"/api/providers/{fast}", json={"note": "Another note."}).json()
    assert kept["models"] == [{"name": "quick", "note": None, "tier": "fast", "agents": True, "enabled": None, "off_why": None,
                               "inputs": None, "context": None},
                              {"name": "deep", "note": None, "tier": "balanced",
                               "agents": True, "enabled": None, "off_why": None, "inputs": None, "context": None}]
    # and a list sent without one takes it away again
    cleared = client.patch(f"/api/providers/{fast}", json={"models": [{"name": "quick"}]}).json()
    assert cleared["models"] == [{"name": "quick", "note": None, "tier": None, "agents": True, "enabled": None, "off_why": None,
                                  "inputs": None, "context": None}]


# --- a role's tier --------------------------------------------------------------------------


def test_the_table_says_when_a_roles_tier_has_no_model_and_what_decided_then(team):  # noqa: F811
    client, _default, _fast = team([text("x")])
    client.headers["Origin"] = ORIGIN                 # no model has a tier here
    role_tier(client, "Reviewer", "strongest")
    row = table(client)["Reviewer"]
    assert (row["provider_name"], row["source"], row["tier"]) == ("Local", "default", "strongest")
    assert table(client)["Tester"]["tier"] == "balanced"  # its own, since slice 43


def test_a_tier_is_looked_for_only_among_what_may_be_picked_for_the_role(team):  # noqa: F811
    client, _default, _fast = team([text("x")])
    local, _fast_id = tiered(team, client)
    role_tier(client, "Reviewer", "balanced")
    assert table(client)["Reviewer"]["source"] == "tier"
    assert client.patch(f"/api/roles/{role_id(client, 'Reviewer')}",
                        json={"pick_from": [local["id"]]}).status_code == 200
    row = table(client)["Reviewer"]                   # Fast, which has the balanced one, is out
    assert (row["provider_name"], row["source"]) == ("Local", "default")


def test_a_lead_with_a_tier_runs_on_it_as_the_table_says(team, wait_run, project_dir):  # noqa: F811
    client, default, fast = team([], [text("the lead answers")])
    tiered(team, client)
    role_tier(client, "Lead", "balanced")
    cid, run_id = begin(client, project_dir)
    snap = wait_run(client, cid, run_id)
    lead = snap["agents"][0]
    assert (lead["provider_name"], lead["chosen"], lead["chosen_why"]) == ("Fast", False, None)
    assert ("Fast", "deep") in team.asked and default.calls == []
    row = table(client, cid)["Lead"]
    assert (row["provider_name"], row["model_id"], row["source"]) == ("Fast", "deep", "tier")


def test_resetting_a_built_in_role_gives_it_the_tier_it_came_with(team):  # noqa: F811
    # (81b: it came with none - the Lead picks, fast to strongest - and its own kind of work.)
    client, _default, _fast = team([text("x")])
    client.headers["Origin"] = ORIGIN
    for name, kind in (("Debugger", "build"), ("Coder", "build"), ("Lead", "plan")):
        assert client.patch(f"/api/roles/{role_id(client, name)}", json={
            # (a kind is a category's key since 63b: one the role does not come with)
            "tier": "fast", "tier_min": "balanced", "kind": "write"}).status_code == 200
        reset = client.post(f"/api/roles/{role_id(client, name)}/reset").json()
        assert (reset["tier"], reset["tier_min"], reset["tier_max"], reset["kind"]) == (
            None, None, None, kind), name


def test_a_role_of_the_users_own_keeps_a_built_in_one_of_its_name_from_being_added(team):  # noqa: F811
    client, _default, _fast = team([text("x")])
    with client.app.state.session_factory() as session:
        built_in = session.scalar(select(Role).where(Role.name == "Debugger"))
        session.delete(built_in)
        session.add(Role(name="debugger", description="mine", instructions="", tools=["search"]))
        session.commit()
        seed_builtin_roles(session)                    # as at the next start
        named = session.scalars(select(Role).where(Role.name.ilike("debugger"))).all()
    assert [(role.name, role.builtin, role.tier) for role in named] == [("debugger", False, None)]


# --- how hard the job is --------------------------------------------------------------------


def test_a_tier_is_one_of_three_and_is_not_given_with_a_provider(team, wait_run, project_dir):  # noqa: F811
    # (Slice 81b: `tier` took `difficulty`'s place; a model named is the pick, and decides.)
    client, default, fast = team([
        step(call("spawn_agent", {"role": "Coder", "task": "t", "provider": "Fast",
                                  "model": "quick", "tier": "strongest", "why": WHY}, "b")),
        step(spawn("Coder", "impossible", WHY, id="c")),
        text("done")])
    tiered(team, client)
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    (first, named), (second, said) = results(snap)
    assert (first, second) == ("failed", "failed") and len(snap["agents"]) == 1
    assert "give tier or provider, not both" in named
    assert "tier is one of: fast, balanced, strongest" in said


def test_a_role_with_its_own_model_is_given_no_tier(team, wait_run, project_dir):  # noqa: F811
    client, default, fast = team([step(spawn("Coder", "strongest", WHY)), text("done")])
    _local, fast_id = tiered(team, client)
    assert client.patch(f"/api/roles/{role_id(client, 'Coder')}", json={
        "provider_id": fast_id, "model_id": "deep"}).status_code == 200
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    ((status, said),) = results(snap)
    assert status == "failed" and "own model" in said and len(snap["agents"]) == 1


def test_a_tier_the_role_may_not_have_is_said_before_why_is_asked_for(team, wait_run, project_dir):  # noqa: F811
    # B-91: "give why with tier", then with a why "runs on its own model: leave tier out" -
    # two rounds where one says it.
    client, default, fast = team([step(spawn("Coder", "strongest")), text("done")])
    _local, fast_id = tiered(team, client)
    assert client.patch(f"/api/roles/{role_id(client, 'Coder')}", json={
        "provider_id": fast_id, "model_id": "deep"}).status_code == 200
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    ((status, said),) = results(wait_run(client, cid, run_id))
    assert status == "failed" and "own model" in said and "give why" not in said


def test_a_tier_within_the_rule_is_not_asked_about(team, wait_run, project_dir):  # noqa: F811
    # The range is the user's leave: a tier in it is the Lead's to give, and not a pick of a
    # model the user is asked about (one named by provider still is).
    client, default, fast = team([step(spawn("Coder", "balanced", WHY)), text("done")], [text("ok")])
    tiered(team, client)
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    coder = snap["agents"][1]
    assert (coder["status"], coder["tier"], coder["chosen"], coder["chosen_why"]) == (
        "completed", "balanced", False, WHY)
    assert ("Fast", "deep") in team.asked


def test_an_opener_is_told_when_the_tier_it_gave_changed_nothing(team, wait_run, project_dir):  # noqa: F811
    client, default, fast = team([step(spawn("Coder", "fast", WHY)), text("done")], [text("ok")])
    local, _fast_id = tiered(team, client)
    # the fast model is Fast's, which may not be picked for a Coder: it runs where it would
    assert client.patch(f"/api/roles/{role_id(client, 'Coder')}",
                        json={"pick_from": [local["id"]]}).status_code == 200
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    ((status, said),) = results(snap)
    assert status == "succeeded" and said.endswith(
        "\n\ntier fast changed nothing: no model of that tier may be picked for this role now, "
        "so it ran where it would without one.")
    assert (snap["agents"][1]["provider_name"], snap["agents"][1]["tier"]) == ("Local", None)


def test_after_the_users_no_nothing_is_said_of_a_tier_that_changed_nothing(
    team, wait_run, project_dir  # noqa: F811
):
    from tests.test_agent_writes import wait_status

    client, _default, _fast = team([step(spawn("Coder", "fast", WHY)), text("done")])
    local, _fast_id = tiered(team, client)
    assert client.patch(f"/api/roles/{role_id(client, 'Coder')}",
                        json={"pick_from": [local["id"]]}).status_code == 200
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="always")
    kid = wait_status(client, cid, "waiting_approval")["agents"][1]
    client.post(f"/api/agents/{kid['id']}/reject")
    ((status, said),) = results(wait_run(client, cid, run_id))
    assert status == "denied" and "changed nothing" not in said   # no agent was opened


# --- a tier that cannot be had where the agent would really run decides nothing ---------------


def strongest_on_codex(team, client):  # noqa: F811
    """The only strongest model there is is native Codex's: a CLI at work with its own
    tools, which does not ask before it writes or runs."""
    client.headers["Origin"] = ORIGIN
    assert client.patch(f"/api/providers/{team.providers['Codex']['id']}", json={
        "models": [{"name": "max", "tier": "strongest"}]}).status_code == 200


def test_in_a_turn_nobody_watches_a_tier_does_not_land_on_a_cli_with_its_own_tools(
    team, wait_run, project_dir  # noqa: F811
):
    client, default, fast = team([step(spawn("Coder")), text("the coder looked"), text("done")])
    strongest_on_codex(team, client)
    role_tier(client, "Lead", "strongest")
    role_tier(client, "Coder", "strongest")
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}",
                        json={"permission_mode": "full_auto"}).status_code == 200
    # with the user there both run on it, which is what the table says
    rows = table(client, cid)
    assert [(rows[role]["provider_name"], rows[role]["source"]) for role in ("Lead", "Coder")] == [
        ("Codex", "tier")] * 2
    made = trigger(client, pid, cid, permissions={"write": False, "commands": [], "agents": 1})
    snap = wait_run(client, cid, run_now(client, made["id"]))
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    lead, coder = snap["agents"]
    # the tier decided nothing there: the next rule did, for the lead and for whom it opened
    assert (lead["provider_name"], coder["provider_name"], coder["status"]) == (
        "Local", "Local", "completed")
    assert team.stubs["Codex"].started == 0


def test_a_tier_lands_on_codex_for_a_coder_the_opener_leaves_no_commands(
    team, wait_run, project_dir  # noqa: F811
):
    # Before B-301 the tier passed Codex over (a Coder without run_command could not look at
    # files there); now Codex is started read-only for it and reads with KOLONİ's tools.
    client, default, fast = team([step(spawn("Coder")), text("the coder looked"), text("done")])
    real_codex(team.stubs["Codex"])
    strongest_on_codex(team, client)
    role_tier(client, "Coder", "strongest")
    # a Lead that may run no command leaves none to whom it opens
    lead = next(role for role in client.get("/api/roles").json() if role["name"] == "Lead")
    assert client.patch(f"/api/roles/{lead['id']}", json={
        "tools": [tool for tool in lead["tools"] if tool != "run_command"]}).status_code == 200
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    coder = snap["agents"][1]
    assert (coder["provider_name"], coder["chosen"]) == ("Codex", False)
    assert table(client, cid)["Coder"]["provider_name"] == "Codex"
    assert team.stubs["Codex"].started == 1


def real_codex(stub):
    """The stand-in as native Codex is: it asks first (89a), looks at files only by running
    commands, and is started read-only for a role short of the write and command tools (B-301)."""
    stub.asks, stub.looks_by_running, stub.starts_read_only = True, True, True


def test_a_reviewer_whose_own_model_is_codex_runs_there_read_only(
    team, wait_run, project_dir  # noqa: F811
):
    # B-301 (live, R93): "The Reviewer role cannot work on Codex: ... write files and run
    # commands". Read-only, it reads with KOLONİ's tools: nothing stands in its way now.
    client, default, fast = team([step(spawn("Reviewer")), text("did it myself")])
    real_codex(team.stubs["Codex"])
    client.headers["Origin"] = ORIGIN
    for role in ("Reviewer", "Coder"):
        assert client.patch(f"/api/roles/{role_id(client, role)}", json={
            "provider_id": team.providers["Codex"]["id"]}).status_code == 200
    cid, run_id = begin(client, project_dir, mode="ask", spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    row = table(client, cid)["Reviewer"]
    assert (row["provider_name"], row["source"]) == ("Codex", "role")
    assert (row["cannot_run"], row["cannot_pick"]) == (None, {})
    assert table(client, cid)["Coder"]["cannot_run"] is None  # at Ask too
    # opened, and the CLI is started (the stand-in fails it: it never runs here)
    reviewer = snap["agents"][1]
    assert reviewer["provider_name"] == "Codex" and team.stubs["Codex"].started == 1


def test_the_table_says_before_any_run_where_a_role_could_be_no_recipe_step_and_no_room_member(
    team, wait_run, project_dir  # noqa: F811
):
    """B-89: an agy Reviewer refused as a recipe's step, a Codex Coder as a room's member -
    found only as they ran. The table says it with the words the opener would be told."""
    from app.room import member_model
    from app.team import ONLY_IN_THE_PROJECT

    client, default, fast = team([text("done")])
    client.headers["Origin"] = ORIGIN
    assert client.patch(f"/api/roles/{role_id(client, 'Coder')}", json={
        "provider_id": team.providers["Codex"]["id"]}).status_code == 200
    rows = table(client)
    # (The stand-in is a CLI of its own tools not started in a copy, as native agy is.)
    assert rows["Coder"]["cannot_step"] == ONLY_IN_THE_PROJECT.format(provider="Codex")
    with client.app.state.session_factory() as session, pytest.raises(ValueError) as refused:
        member_model(session, None, "Coder", None, None, by_user=True)
    assert rows["Coder"]["cannot_room"] == str(refused.value)
    assert (rows["Tester"]["cannot_step"], rows["Tester"]["cannot_room"]) == (None, None)


# --- one tier up, said to the opener --------------------------------------------------------


def test_what_is_one_tier_up_is_said_from_the_model_the_agent_ran_on(team, wait_run,  # noqa: F811
                                                                     project_dir):
    looks = [step(call("list_dir", {}, f"c{n}")) for n in range(2)]
    client, default, fast = team(
        [step(spawn("Coder", "balanced", WHY, id="a")), step(spawn("Reviewer", id="b")),
         text("the reviewer finished"), text("done")], looks)
    tiered(team, client)
    role_tier(client, "Reviewer", "strongest")  # on Local, which answers it
    assert client.patch(f"/api/roles/{role_id(client, 'Coder')}",
                        json={"max_steps": 1}).status_code == 200
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    (coder, said), (reviewer, heard) = results(wait_run(client, cid, run_id))
    # it ran on the balanced model: the strongest is within its range (81b), and is named
    assert coder == "failed" and said.endswith(
        'One tier up: "Local" · "big-model" (strongest) - give the job again with tier strongest.')
    # an agent that finished is given no advice
    assert reviewer == "succeeded" and "tier" not in heard


# --- the lead's own model, by how hard the message is ---------------------------------------


def by_model(client):
    return {(row["provider_name"], row["model_id"]): row
            for row in client.get("/api/usage").json()["by_model"]}


def price(client, model, each):
    assert client.put("/api/prices", json={
        "model_id": model, "input": each, "output": each, "currency": "USD"}).status_code == 200


def test_the_question_is_paid_for_under_the_model_that_was_asked_and_is_not_in_the_conversation(
    team, wait_run, project_dir  # noqa: F811
):
    from app.agent import HOW_HARD

    client, default, fast = team(
        [text("the lead answers", i=50, o=7)], [text("Hard - it touches many files.", i=40, o=9)])
    tiered(team, client)
    price(client, "quick", 1)
    price(client, "big-model", 10)
    cid, run_id = begin(client, project_dir, lead_auto=True, content="rewrite the parser")
    snap = wait_run(client, cid, run_id)
    # said as the system's word and again where the message is, which is under it as data -
    # with what KOLONİ knows of it, here nothing (K-zor-ipucu)
    assert fast.calls == [[
        {"role": "system", "content": HOW_HARD},
        {"role": "user", "content": HOW_HARD + '\n\nThe message:\n"rewrite the parser"'
                                    "\n\nFacts: none found."}]]
    assert not fast.tool_args[0]  # (no tools: one word and why)
    assert [m["content"] for m in snap["messages"]] == ["rewrite the parser", "the lead answers"]
    lead, run = snap["agents"][0], snap["runs"][0]
    assert lead["chosen_why"] == "hard: it touches many files." and lead["chosen"] is False
    assert lead["asked_how_hard"] == {"provider_name": "Fast", "model_id": "quick"}
    # the lead's numbers, and the turn's, are the lead's own work: the question is not in them
    assert (lead["input_tokens"], lead["output_tokens"]) == (50, 7)
    assert (run["input_tokens"], run["output_tokens"]) == (50, 7)
    # it is spent all the same: under the model that was asked, at that model's price
    spent = by_model(client)
    assert set(spent) == {("Fast", "quick"), ("Local", "big-model")}
    asked, ran = spent["Fast", "quick"], spent["Local", "big-model"]
    assert (asked["input_tokens"], asked["output_tokens"], asked["unknown_agents"]) == (40, 9, 0)
    assert asked["cost"] == {"amount": 0.000049, "currency": "USD"}
    assert (ran["input_tokens"], ran["output_tokens"]) == (50, 7)
    assert ran["cost"] == {"amount": 0.00057, "currency": "USD"}


def test_the_question_is_given_the_files_parts_and_steps_of_similar_jobs_it_names(
    team, wait_run, project_dir  # noqa: F811
):
    from app.agent import HOW_HARD

    core = project_dir / "core"
    core.mkdir()
    (core / "pyproject.toml").write_text("[project]\nname = 'core'\n", encoding="utf-8")
    for name in ("etl.py", "load.py"):
        (core / name).write_text("x = 1\n", encoding="utf-8")
    client, default, fast = team(
        [step(call("list_dir", {}, "l")), text("one"), text("two")],
        [text("hard: a loader"), text("normal: two files")])
    tiered(team, client)
    cid, run_id = begin(client, project_dir, lead_auto=True, content="fix the etl loader")
    wait_run(client, cid, run_id)
    asked = "fix the etl loader in core/etl.py and core/load.py"
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": asked},
                         headers={"Origin": ORIGIN}).json()["run"]["id"]
    snap = wait_run(client, cid, run_id)
    assert fast.calls[1][1]["content"] == HOW_HARD + f'\n\nThe message:\n"{asked}"\n\n' + "\n".join([
        "Facts:",
        'Files it names that are in the project: 2 ("core/etl.py", "core/load.py")',
        'Parts of the project it touches: "core/" (3 files)',
        # the first turn's Orchestrator: a look and its answer
        "Steps the Orchestrator took on similar earlier jobs: median 2 (of 1)",
    ])
    # the answer is read as before: one word, then why
    assert snap["agents"][-1]["chosen_why"].startswith("normal: two files")


def test_a_question_an_api_answered_keeps_its_price_when_the_lead_then_runs_on_a_cli(
    team, wait_run, project_dir  # noqa: F811
):
    from tests.fakes import ScriptedModel

    client, default, fast = team([], [text("hard: it needs care", i=40, o=9)])
    local, _fast_id = tiered(team, client)
    # the strongest model is a CLI's now (one step at a time): a plan, with no price for a token
    assert client.patch(f"/api/providers/{local['id']}",
                        json={"models": [{"name": "big-model"}]}).status_code == 200
    client.app.state.providers.named["Plan"] = ScriptedModel(
        [text("the lead answers", i=50, o=7)], model_id="cli-strong")
    assert client.post("/api/providers", json={
        "name": "Plan", "kind": "codex_cli", "mode": "step", "for_agents": True,
        "models": [{"name": "cli-strong", "tier": "strongest"}]}).status_code == 201
    price(client, "quick", 1)
    price(client, "cli-strong", 10)
    cid, run_id = begin(client, project_dir, lead_auto=True)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert snap["agents"][0]["provider_name"] == "Plan"
    spent = by_model(client)
    assert spent["Fast", "quick"]["cost"] == {"amount": 0.000049, "currency": "USD"}
    ran = spent["Plan", "cli-strong"]
    assert (ran["input_tokens"], ran["output_tokens"], ran["cost"]) == (50, 7, None)


def test_the_question_counts_toward_the_turns_limit_and_not_toward_the_lead_roles(
    team, wait_run, project_dir  # noqa: F811
):
    client, default, fast = team(
        [step(call("list_dir", {}, "c1"), i=5, o=2), text("never said")],
        [text("hard: it needs care", i=40, o=9)])
    tiered(team, client)
    # one agent of the Lead role may use 20 tokens: its own step's 7 are well inside that
    assert client.patch(f"/api/roles/{role_id(client, 'Lead')}",
                        json={"max_tokens": 20}).status_code == 200
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={"turn_token_limit": 50}).status_code == 200
    cid, run_id = begin(client, project_dir, lead_auto=True)
    run = wait_run(client, cid, run_id)["runs"][0]
    # the question's 49 and the lead's 7 are what the turn spent
    assert (run["status"], run["error"]) == (
        "failed", "this turn used 56 tokens, over the project's limit of 50")


@pytest.mark.parametrize("said, read", [
    ("<think>Is it hard? It looks easy.</think>\n\nhard: it needs care", "hard: it needs care"),
    ("<THINK>\nnormal?\n</THINK>Easy - a greeting", "easy: a greeting"),
    ("This is hard.", None),                          # not an answer: nothing is read into it
    ("<think>hard", None),
])
def test_what_a_model_thinks_first_is_not_its_answer_and_nothing_else_is_read_into_one(
    team, wait_run, project_dir, said, read  # noqa: F811
):
    client, default, fast = team(
        [text("the lead answers")], [text(said), text("the lead answers")])
    tiered(team, client)
    cid, run_id = begin(client, project_dir, lead_auto=True)
    lead = wait_run(client, cid, run_id)["agents"][0]
    assert lead["chosen_why"] == read
    # who was asked is on the lead either way: an answer nothing came of is not hidden
    assert lead["asked_how_hard"] == {"provider_name": "Fast", "model_id": "quick"}


def test_a_cli_that_cannot_speak_without_its_own_tools_is_never_asked_how_hard_it_is(
    team, wait_run, project_dir  # noqa: F811
):
    client, default, fast = team(
        [text("first"), text("second")], [text("hard: it needs care")])
    local, fast_id = tiered(team, client)
    # The first fast model there is now is a CLI's that works with its own tools - and
    # whose way of speaking with them off still has them (the stand-in's is itself).
    codex, stub = team.providers["Codex"]["id"], team.stubs["Codex"]
    assert stub.talker() is stub
    assert client.patch(f"/api/providers/{codex}", json={
        "models": [{"name": "mini", "tier": "fast"}]}).status_code == 200
    assert client.post(f"/api/providers/{codex}/default").status_code == 200
    # Full auto, and a Lead may write and run: nothing else keeps that CLI from a pick
    cid, run_id = begin(client, project_dir, mode="full_auto", lead_auto=True,
                        provider_id=local["id"])
    assert table(client, cid)["Lead"]["cannot_pick"] == {}
    assert table(client, cid)["Lead"]["asks_how_hard"] == {
        "provider_name": "Fast", "model_id": "quick"}
    snap = wait_run(client, cid, run_id)
    lead = snap["agents"][0]
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    # the user's message was not handed to it: the next fast model was asked
    assert stub.calls == [] and stub.started == 0 and len(fast.calls) == 1
    assert (lead["asked_how_hard"], lead["chosen_why"]) == (
        {"provider_name": "Fast", "model_id": "quick"}, "hard: it needs care")

    # with no other fast model nobody is asked, and the table says so
    assert client.patch(f"/api/providers/{fast_id}", json={"models": [
        {"name": "quick"}, {"name": "deep", "tier": "balanced"}]}).status_code == 200
    assert table(client, cid)["Lead"]["asks_how_hard"] is None
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "and now?"})
    lead = wait_run(client, cid, posted.json()["run"]["id"])["agents"][1]
    assert (lead["provider_name"], lead["asked_how_hard"], lead["chosen_why"]) == (
        "Local", None, None)
    assert stub.calls == [] and len(fast.calls) == 1
    # a conversation that does not follow the message has nobody to say it of
    assert client.patch(f"/api/conversations/{cid}", json={"lead_auto": False}).status_code == 200
    assert table(client, cid)["Lead"]["asks_how_hard"] is None


def test_of_the_real_clis_only_agy_still_has_its_own_tools_when_they_are_to_be_off():
    """What `team.asked_how_hard` goes by, for the clients as they are built (none is
    started here): agy, however it is set to run, speaks as a CLI that reads where it
    likes; Codex, Claude Code and Copilot speak with none of their own tools."""
    from app.model_agy import AgyClient
    from app.model_native import ClaudeNativeClient, CodexNativeClient, CopilotNativeClient

    for agy in (AgyClient(reads=True), AgyClient(reads=False)):
        assert agy.native and agy.talker().native and agy.talker().reads
    for cli in (CodexNativeClient(), ClaudeNativeClient(), CopilotNativeClient()):
        assert cli.native and not getattr(cli.talker(), "native", False)


def test_where_the_lead_goes_is_looked_up_again_when_the_answer_is_there(
    team, wait_run, project_dir, gate  # noqa: F811
):
    client, default, fast = team(
        [text("the lead answers")], [gate.step(text("hard: it needs care"))])
    local, _fast_id = tiered(team, client)
    # the only strongest model is on a provider that is gone by the time the answer is there
    assert client.patch(f"/api/providers/{local['id']}",
                        json={"models": [{"name": "big-model"}]}).status_code == 200
    paid = team.providers["Paid Api"]["id"]
    assert client.patch(f"/api/providers/{paid}", json={
        "for_agents": True, "models": [{"name": "gold", "tier": "strongest"}]}).status_code == 200
    cid, run_id = begin(client, project_dir, lead_auto=True)
    gate.wait_partial()
    assert client.delete(f"/api/providers/{paid}").status_code == 204
    gate.release()
    snap = wait_run(client, cid, run_id)
    lead = snap["agents"][0]
    # it runs where it otherwise would, and nothing is claimed
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert (lead["provider_name"], lead["chosen_why"]) == ("Local", None)
    assert team.stubs["Paid Api"].calls == []


def test_a_question_that_fails_or_a_tier_nobody_has_leaves_the_lead_where_it_was(
    team, wait_run, project_dir  # noqa: F811
):
    client, default, fast = team(
        [text("first"), text("second")],
        [ModelUnavailable("the server is down"), text("normal: nothing special")])
    local, fast_id = tiered(team, client)
    cid, run_id = begin(client, project_dir, lead_auto=True)
    lead = wait_run(client, cid, run_id)["agents"][0]
    assert (lead["provider_name"], lead["chosen_why"], lead["status"]) == (
        "Local", None, "completed")
    # nobody has a balanced model now: "normal" has nowhere to go
    assert client.patch(f"/api/providers/{fast_id}", json={"models": [
        {"name": "quick", "tier": "fast"}]}).status_code == 200
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "and now?"})
    lead = wait_run(client, cid, posted.json()["run"]["id"])["agents"][1]
    assert (lead["provider_name"], lead["chosen_why"]) == ("Local", None)
    assert (len(default.calls), len(fast.calls)) == (2, 2)


def test_the_question_stands_in_line_where_the_provider_it_goes_to_is_full(
    team, wait_run, project_dir, gate  # noqa: F811
):
    client, default, fast = team(
        [text("B's lead answers")], [gate.step(text("A done")), text("hard: it needs care")])
    _local, fast_id = tiered(team, client)
    assert client.patch(f"/api/providers/{fast_id}", json={"max_running": 1}).status_code == 200
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    a, b = talk(client, pid, provider_id=fast_id), talk(client, pid, lead_auto=True)
    run_a = go(client, a)
    gate.wait_partial()                               # A's lead holds Fast's only place
    run_b = go(client, b)
    queued(client, b)
    assert len(fast.calls) == 1 and default.calls == []   # nobody was asked anything for B
    gate.release()
    assert wait_run(client, a, run_a)["runs"][0]["status"] == "completed"
    lead = wait_run(client, b, run_b)["agents"][0]
    assert (lead["provider_name"], lead["chosen_why"]) == ("Local", "hard: it needs care")
    assert len(fast.calls) == 2 and len(default.calls) == 1


def test_stop_ends_a_turn_while_it_is_being_asked_how_hard_it_is(team, wait_run,  # noqa: F811
                                                                project_dir, gate):
    client, default, fast = team([], [gate.step(text("hard: never heard"))])
    tiered(team, client)
    cid, run_id = begin(client, project_dir, lead_auto=True)
    gate.wait_partial()
    cancel(client, run_id)
    snap = wait_run(client, cid, run_id)
    lead = snap["agents"][0]
    assert snap["runs"][0]["status"] == "cancelled" and default.calls == []
    assert (lead["status"], lead["provider_name"], lead["chosen_why"]) == (
        "cancelled", "Local", None)
    assert lead["asked_how_hard"] == {"provider_name": "Fast", "model_id": "quick"}
    # what the question spent before it was cut is not known, and its own record says so -
    # not the lead's, which sent nothing
    with client.app.state.session_factory() as session:
        assert session.scalar(select(Agent.cut_short).where(Agent.id == lead["id"])) is False
        (asked,) = session.scalars(select(OwnRequest)).all()
        assert (asked.agent_id, asked.provider_name, asked.model_id, asked.cut_short) == (
            lead["id"], "Fast", "quick", True)
        assert (asked.input_tokens, asked.output_tokens) == (None, None)
    row = by_model(client)["Fast", "quick"]
    assert (row["input_tokens"], row["output_tokens"], row["unknown_agents"]) == (None, None, 1)


def test_a_turn_stopped_while_it_stands_in_line_for_the_question_leaves_no_record_of_one(
    team, wait_run, project_dir, gate  # noqa: F811
):
    client, default, fast = team([], [gate.step(text("A done"))])
    _local, fast_id = tiered(team, client)
    assert client.patch(f"/api/providers/{fast_id}", json={"max_running": 1}).status_code == 200
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    a, b = talk(client, pid, provider_id=fast_id), talk(client, pid, lead_auto=True)
    run_a = go(client, a)
    gate.wait_partial()                               # A's lead holds Fast's only place
    run_b = go(client, b)
    queued(client, b)
    cancel(client, run_b)
    lead = wait_run(client, b, run_b)["agents"][0]
    # nothing went out: nobody is on record as asked, and nothing as spent
    assert (lead["status"], lead["asked_how_hard"]) == ("cancelled", None)
    with client.app.state.session_factory() as session:
        assert session.scalars(select(OwnRequest)).all() == []
    gate.release()
    wait_run(client, a, run_a)


def test_in_a_turn_nobody_watches_nobody_is_asked_how_hard_it_is(team, wait_run, project_dir):  # noqa: F811
    client, default, fast = team([text("looked it over")])
    tiered(team, client)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json={"lead_auto": True}).status_code == 200
    snap = wait_run(client, cid, run_now(client, trigger(client, pid, cid)["id"]))
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert fast.calls == [] and snap["agents"][0]["chosen_why"] is None


def test_a_tier_says_why_each_one_before_its_pick_was_passed_over_in_sentences():
    """B-76: Codex, passed over for a role with no commands, was not said; the Lead's reason
    and the tier's were joined with ".;"."""
    from app.agent import _then
    from app.team import PICK_NEEDS_THE_TOOLS, Entry, Would

    def entry(name):
        return Entry(name, name, "x", "api", None, (("m", None),), None, tiers=(("m", "balanced"),))

    would = Would(None, None, "tier", [entry("Local"), entry("Codex"), entry("Claude")],  # type: ignore[arg-type]
                  cannot_pick={"Codex": PICK_NEEDS_THE_TOOLS.format(role="Reviewer", provider="Codex")},
                  down={"Local": "Local was not answering when last looked at"})
    found, moved = would.pick("balanced")
    assert found is not None and found[0].name == "Claude"
    assert moved == ("Codex cannot be chosen for the Reviewer role; Local was not answering when "
                     "last looked at: the next balanced model")
    # not on the Lead's own row, where a reason reads as the guess of how hard the message is
    from dataclasses import replace
    assert replace(would, says_blocked=False).pick("balanced")[1] == (
        "Local was not answering when last looked at: the next balanced model")
    assert _then("Check hello.py.", "local was down") == "Check hello.py. Local was down"
    assert _then("", "local was down") == "local was down" and _then("Check it", None) == "Check it"


def test_b193_a_cli_named_no_model_runs_its_lists_balanced_one_not_its_own_default(make_client):
    from app.providers import stand_in
    from app.roles import find_role
    from app.team import would_run

    # (live: a new chat on "Default (Claude Code)" ran the Lead on claude-fable-5-1, its dearest)
    listed = [{"name": "claude-fable", "tier": "strongest"},
              {"name": "claude-sonnet", "tier": "balanced"}, {"name": "claude-haiku", "tier": "fast"}]
    client, _model = make_client([])
    with client.app.state.session_factory() as session:
        session.add(Provider(name="Claude Code", kind="claude_cli", position=-1, models=listed))
        session.commit()
        assert would_run(session, find_role(session, "Lead"), None).model_id == "claude-sonnet"
    cli = {"name": "C", "kind": "codex_cli"}
    assert stand_in(Provider(**cli, models=[listed[0], listed[2]])) == "claude-haiku"  # the cheaper
    assert stand_in(Provider(**cli, models=[{"name": "a"}, {"name": "b"}])) == "a"
    assert stand_in(Provider(**cli, models=None)) is None  # its own default runs: said so
    assert stand_in(Provider(name="L", kind="openai_compat", models=listed)) is None


def test_only_the_leads_own_pick_leaves_out_who_its_tier_passed_over(make_client):
    from app.roles import find_role
    from app.team import would_run

    client, _model = make_client([])
    with client.app.state.session_factory() as session:
        said = {name: would_run(session, find_role(session, name), None).says_blocked
                for name in ("Lead", "Reviewer")}
    assert said == {"Lead": False, "Reviewer": True}


def test_the_table_says_where_a_roles_agents_could_run_instead_and_with_what_model(
    team  # noqa: F811
):
    """The chat's team picker offers a step's role only providers it could be that step on,
    with a model they may run (batch-18 review)."""
    client, default, fast = team([text("done")])
    client.headers["Origin"] = ORIGIN
    ids = {name: provider["id"] for name, provider in team.providers.items()}
    # Paid Api runs only its listed models now, and its default is not one of them
    assert client.patch(f"/api/providers/{ids['Paid Api']}", json={
        "only_listed": True, "models": [{"name": "silver"}]}).status_code == 200
    on = {one["provider_id"]: one for one in table(client)["Coder"]["run_on"]}
    assert (on[ids["Paid Api"]]["model_id"], on[ids["Paid Api"]]["step"]) == ("silver", True)
    assert (on[ids["Fast"]]["model_id"], on[ids["Fast"]]["step"], on[ids["Fast"]]["room"]) == (
        "quick", True, True)
    # (the stand-in works in the project itself, with tools of its own)
    assert (on[ids["Codex"]]["step"], on[ids["Codex"]]["room"]) == (False, False)


def test_past_its_plan_share_a_cli_steps_down_on_its_own_plan_or_another_kind_never_another_account():
    # K-claude-hesap (security review): the step-down did not ask whose plan the lower model was on.
    from app.team import Entry, Would

    def entry(name, kind, tiers):
        return Entry(name, name, kind, "cli", None, tuple((m, None) for m, _ in tiers), None,
                     tiers=tiers)

    work = entry("Work", "claude_cli", (("opus", "strongest"),))
    home = entry("Home", "claude_cli", (("sonnet", "balanced"),))
    codex = entry("Cx", "codex_cli", (("gpt", "balanced"),))
    would = Would(None, None, "tier", [work, home, codex],  # type: ignore[arg-type]
                  plan_used={"Work": "Work's weekly plan 90% used"}, steps=("balanced", "strongest"))
    found, moved = would.pick("strongest")
    assert found is not None and found[0].name == "Cx" and "balanced instead of strongest" in moved
    # With only the other account below, it stays where it was.
    assert Would(None, None, "tier", [work, home],  # type: ignore[arg-type]
                 plan_used=would.plan_used, steps=would.steps).pick("strongest")[0][0].name == "Work"
