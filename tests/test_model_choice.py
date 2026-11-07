"""Slice 25c beside its acceptance set (tests/test_model_choice_scenarios.py): the edges of
the reason for a pick, of what may be picked for a role, of the table of who uses what, of
a role's limits and of the note to a model that takes a conversation over."""

import sqlite3
from types import SimpleNamespace

import pytest
from alembic import command

from app.agent import TRIMMED, _taken_from, _trim_to_budget
from app.config import load_settings
from app.main import create_app
from app.model_client import ModelUnavailable
from tests.fakes import ScriptedModel
from tests.keyed import NO_ORIGIN, TestClient
from tests.test_chat_flow import text
from tests.test_migration_0002 import _config
from tests.test_model_cli import gone
from tests.test_session_agent import session_app, start  # noqa: F401  (a fixture)
from tests.test_spawn import begin, call, reported, role_id, step
from tests.test_team import results, team  # noqa: F401  (a fixture)

# (What agents may pick is the user's to change, from the app's own page: slice 81a.)
OWN = {"Origin": "http://127.0.0.1:8790"}

ORIGIN = "http://127.0.0.1:8790"
WHY = "The bug is subtle: it needs the stronger model."


def pick(role, provider=None, model=None, why=None, id="s1"):
    more = {key: value for key, value in (("provider", provider), ("model", model), ("why", why))
            if value is not None}
    return call("spawn_agent", {"role": role, "task": "do the thing", **more}, id)


def table(client, cid=None):
    told = client.get("/api/roles/models", params={"conversation_id": cid} if cid else None)
    assert told.status_code == 200, told.text
    return {row["role"]: row for row in told.json()}


# --- the reason for a pick -------------------------------------------------------------------


def test_a_reason_is_kept_as_one_line_and_one_too_long_or_not_in_words_is_refused(
    team, wait_run, project_dir  # noqa: F811
):
    client, default, fast = team(
        [step(pick("Reviewer", "Fast", why="x" * 301, id="a")),
         step(pick("Reviewer", "Fast", why=["because"], id="b")),
         step(pick("Reviewer", "Fast", why="  The bug\n is   subtle.\t", id="c")), text("done")],
        [text("looked")])
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    (long, said_long), (not_words, said_not), (taken, _) = results(snap)
    assert (long, not_words, taken) == ("failed", "failed", "succeeded")
    assert "at most 300 characters" in said_long and "why must be a string" in said_not
    (reviewer,) = snap["agents"][1:]
    assert reviewer["chosen_why"] == "The bug is subtle."


def test_a_reason_is_asked_only_of_a_pick_that_could_be_had(team, wait_run, project_dir):  # noqa: F811
    client, default, fast = team([
        step(pick("Reviewer", "Paid Api", id="a")), step(pick("Reviewer", "Fast", "nope", id="b")),
        step(pick("Coder", "Codex", id="c")), text("did it myself")])
    cid, run_id = begin(client, project_dir, mode="ask", spawn_approval="never")
    said = [told for _status, told in results(wait_run(client, cid, run_id))]
    # each is told what stands in its way, and not to give a reason for what cannot be had
    assert "no provider named Paid Api" in said[0] and "no model named nope" in said[1]
    assert "Full auto" in said[2]
    assert not any("give why" in told for told in said)


def test_a_reason_of_spaces_alone_is_no_reason(team, wait_run, project_dir):  # noqa: F811
    client, default, fast = team([step(pick("Reviewer", "Fast", why="  \n ")), text("done")])
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    ((status, said),) = results(snap)
    # told to give one, as when it gave none - not that a string is no string
    assert status == "failed" and said.startswith("error: give why: say in one sentence")
    assert len(snap["agents"]) == 1 and fast.calls == []


@pytest.mark.parametrize("may_pick", [["Fast"], []])
def test_naming_what_the_role_gets_anyway_passes_whatever_may_be_picked_for_it(
    team, wait_run, project_dir, may_pick  # noqa: F811
):
    client, default, fast = team([step(pick("Reviewer", " local ")), text("r"), text("done")])
    listed = [team.providers[name]["id"] for name in may_pick]
    assert client.patch(f"/api/roles/{role_id(client, 'Reviewer')}",
                        json={"pick_from": listed}).status_code == 200
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    # no choice was made: nothing to be had from the role's list, and no reason to give
    assert results(snap)[0][0] == "succeeded", results(snap)
    kid = snap["agents"][1]
    assert (kid["provider_name"], kid["chosen"], kid["chosen_why"]) == ("Local", False, None)


def test_the_roles_own_provider_and_model_can_be_named_though_no_agent_may_pick_them(
    team, wait_run, project_dir  # noqa: F811
):
    client, default, fast = team([
        step(pick("Reviewer", "Paid Api", "gold", id="a")),
        step(pick("Reviewer", "Paid Api", "silver", id="b")), text("done")])
    team.stubs["Paid Api"].steps.append(text("looked"))
    assert client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={
        "provider_id": team.providers["Paid Api"]["id"], "pick_from": []}).status_code == 200
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    (same, _), (other, said) = results(snap)
    # the role's provider on the model it would get: named or not, that is where it runs
    assert same == "succeeded" and snap["agents"][1]["chosen"] is False
    # another model of it is a pick - and nothing may be picked for this role
    assert other == "failed" and "no other model can be chosen here" in said


def test_b193_naming_the_roles_own_cli_with_no_model_is_no_pick_where_koloni_names_its_model(
    team, wait_run, project_dir  # noqa: F811
):
    client, default, fast = team([step(pick("Reviewer", "Codex")), text("done")])
    codex = team.providers["Codex"]["id"]
    client.headers["Origin"] = ORIGIN  # (what agents may use: the user's, from the app's page)
    assert client.patch(f"/api/providers/{codex}", json={
        "models": [{"name": "gpt-a", "tier": "balanced"}]}).status_code == 200
    assert client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={
        "provider_id": codex, "pick_from": []}).status_code == 200
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    # where it runs anyway (on gpt-a, B-193's stand-in): no pick, so none refused for an empty list
    # (and opened there - where a Reviewer cannot work, its CLI's own tools being what they are)
    assert "no other model can be chosen here" not in results(snap)[0][1]
    assert (snap["agents"][1]["provider_name"], snap["agents"][1]["chosen"]) == ("Codex", False)


# --- what may be picked for a role ------------------------------------------------------------


def test_a_roles_list_is_kept_cleared_and_loses_a_provider_that_is_deleted(team):  # noqa: F811
    client, _default, _fast = team([])
    reviewer, coder = role_id(client, "Reviewer"), role_id(client, "Coder")
    fast, codex = team.providers["Fast"]["id"], team.providers["Codex"]["id"]
    kept = client.patch(f"/api/roles/{reviewer}", json={"pick_from": [fast, codex, fast]})
    assert kept.status_code == 200 and kept.json()["pick_from"] == [fast, codex]
    assert client.patch(f"/api/roles/{coder}", json={"pick_from": [codex]}).status_code == 200
    assert client.patch(f"/api/roles/{coder}", json={"pick_from": "Fast"}).status_code == 422
    # another field changed: the list stays as it is
    assert client.patch(f"/api/roles/{reviewer}", json={"description": "x"}).json()[
        "pick_from"] == [fast, codex]

    assert client.delete(f"/api/providers/{codex}").status_code == 204
    listed = {role["name"]: role["pick_from"] for role in client.get("/api/roles").json()}
    # a list of one becomes none - not "all": nothing is widened by a deletion
    assert (listed["Reviewer"], listed["Coder"], listed["Tester"]) == ([fast], [], None)

    assert client.patch(f"/api/roles/{reviewer}", json={"pick_from": None}).json()[
        "pick_from"] is None
    assert client.post(f"/api/roles/{coder}/reset").json()["pick_from"] is None


def test_the_team_guide_is_the_most_a_roles_list_can_give(team, wait_run, project_dir):  # noqa: F811
    client, default, fast = team(
        [step(pick("Reviewer", "Paid Api", why=WHY, id="a")), text("did it myself")])
    paid, quick = team.providers["Paid Api"]["id"], team.providers["Fast"]["id"]
    assert client.patch(f"/api/roles/{role_id(client, 'Reviewer')}",
                        json={"pick_from": [paid, quick]}).status_code == 200
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    ((status, said),) = results(snap)
    # in the role's list, but not ticked in the guide: not to be picked, and not named
    assert status == "failed" and said == (
        "error: for the Reviewer role: there is no provider named Paid Api to choose. "
        'You can choose: "Fast" - or leave provider out.')
    assert table(client, cid)["Reviewer"]["pick_from"] == ["Fast"]
    assert team.stubs["Paid Api"].calls == []


# --- one table: who uses what -----------------------------------------------------------------


def test_the_table_without_a_conversation_says_what_a_new_one_would_use(team):  # noqa: F811
    client, _default, _fast = team([])
    fast = team.providers["Fast"]["id"]
    reviewer = role_id(client, "Reviewer")
    client.patch(f"/api/roles/{reviewer}", json={"provider_id": fast})
    rows = table(client)
    assert [row["role"] for row in client.get("/api/roles/models").json()][:6] == [
        "Lead", "Planner", "Coder", "Tester", "Reviewer", "Researcher"]
    # the role's provider on its default model; the rest on the app's default provider,
    # whose model nobody named: not known, and not made up
    assert (rows["Reviewer"]["provider_name"], rows["Reviewer"]["model_id"],
            rows["Reviewer"]["source"]) == ("Fast", "quick", "role")
    assert (rows["Lead"]["provider_name"], rows["Lead"]["model_id"],
            rows["Lead"]["source"]) == ("Local", None, "default")
    assert client.get("/api/roles/models", params={"conversation_id": "nope"}).status_code == 404
    # its provider deleted, a role's choice counts as none - as when an agent is opened
    assert client.delete(f"/api/providers/{fast}").status_code == 204
    assert table(client)["Reviewer"]["source"] == "default"


def only_quick(client, provider_id):
    """ "Only these models" on a provider, with one model in its list."""
    limited = client.patch(f"/api/providers/{provider_id}", headers=OWN,
                           json={"models": [{"name": "quick"}], "only_listed": True})
    assert limited.status_code == 200, limited.text


def test_the_table_says_a_role_would_not_run_in_the_words_its_opener_is_told(
    team, wait_run, project_dir  # noqa: F811
):
    client, default, fast = team([step(pick("Reviewer")), text("did it myself")])
    fast_id = team.providers["Fast"]["id"]
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}",
                 json={"provider_id": fast_id, "model_id": "deep"})
    only_quick(client, fast_id)
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    ((status, said),) = results(wait_run(client, cid, run_id))
    rows = table(client, cid)
    row = rows["Reviewer"]
    # still the role's own choice - and what would happen to it is said beside it
    assert (row["provider_name"], row["model_id"], row["source"]) == ("Fast", "deep", "role")
    assert status == "failed" and said == "error: " + row["cannot_run"]
    assert row["cannot_run"].startswith('Fast does not run with the model "deep" here')
    assert rows["Coder"]["cannot_run"] is None and fast.calls == []


def test_the_table_says_so_when_the_lead_itself_would_not_run(team, wait_run, project_dir):  # noqa: F811
    client, default, fast = team([])
    fast_id = team.providers["Fast"]["id"]
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={"provider_id": fast_id, "model_id": "deep"})
    assert table(client, cid)["Lead"]["cannot_run"] is None
    only_quick(client, fast_id)
    row = table(client, cid)["Lead"]
    assert (row["provider_name"], row["model_id"], row["source"]) == (
        "Fast", "deep", "conversation")
    assert row["cannot_run"].startswith('Fast does not run with the model "deep" here')
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": "hi"}).json()["run"]
    ended = wait_run(client, cid, run["id"])["runs"][0]
    # and so it goes: the turn does not start on that model
    assert ended["status"] == "failed" and "runs only with the models listed" in ended["error"]
    assert fast.calls == []


def test_the_table_says_which_pick_could_not_be_opened_now_as_its_picker_is_told(
    team, wait_run, project_dir  # noqa: F811
):
    client, default, fast = team([step(pick("Reviewer", "Codex", id="b", why="It reads well.")),
                                  text("again")])
    # As native Codex is since slice 89a: it asks first, at every level, but looks at files
    # only by running commands - and since B-301 it is started read-only for a role that may
    # not run them, reading with KOLONİ's tools: a Reviewer may be given it.
    team.stubs["Codex"].asks = True
    team.stubs["Codex"].looks_by_running = True
    team.stubs["Codex"].starts_read_only = True
    cid, run_id = begin(client, project_dir, mode="ask", spawn_approval="never")
    wait_run(client, cid, run_id)
    rows = table(client, cid)
    # listed, and to be had for a role that may write and run, and for a Reviewer too
    assert "Codex" in rows["Coder"]["pick_from"] and rows["Coder"]["cannot_pick"] == {}
    assert rows["Reviewer"]["cannot_pick"] == {}
    # a new conversation starts at the same level: so does the table without one
    pid = client.get("/api/projects").json()[0]["id"]
    fresh = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert table(client)["Reviewer"] == table(client, fresh)["Reviewer"] == rows["Reviewer"]
    # and the pick, as the table says, opens it (the stand-in is never run through)
    assert team.stubs["Codex"].started == 1


# --- how far one agent of a role may go -------------------------------------------------------


def test_a_roles_limit_is_the_users_to_change_from_the_apps_own_page(client):
    coder = role_id(client, "Coder")
    patch = lambda body, **more: client.patch(f"/api/roles/{coder}", json=body, **more)  # noqa: E731
    # a request that does not say where it is from - a command an agent runs - is not the user
    assert patch({"max_steps": 3}).status_code == 403
    assert patch({"max_tokens": 9000}, headers={"Origin": "http://evil.example"}).status_code == 403
    own = {"Origin": ORIGIN}
    saved = patch({"max_steps": 3, "max_tokens": 9000}, headers=own)
    assert (saved.json()["max_steps"], saved.json()["max_tokens"]) == (3, 9000)
    # nothing of it changed: the rest of the role is saved as before, and the limit stays
    assert patch({"description": "x", "max_steps": 3}).status_code == 200
    assert patch({"max_steps": None}).status_code == 403            # nor is it taken away
    assert client.post(f"/api/roles/{coder}/reset", headers=NO_ORIGIN).status_code == 403
    for wrong in (0, -1, True, "5", 2.5):
        assert patch({"max_steps": wrong}, headers=own).status_code == 422, wrong
        assert patch({"max_tokens": wrong}, headers=own).status_code == 422, wrong
    cleared = patch({"max_steps": None}, headers=own).json()
    assert (cleared["max_steps"], cleared["max_tokens"]) == (None, 9000)
    assert client.post(f"/api/roles/{coder}/reset", headers=own).json()["max_tokens"] is None


def test_a_limit_is_not_taken_away_by_deleting_its_role_and_making_it_again(client):
    own = {"Origin": ORIGIN}
    helper = {"name": "Helper", "tools": ["read_file"]}
    # a role that names a limit is the user's to make, and with a limit it is the user's to delete
    assert client.post("/api/roles", json={**helper, "max_steps": 3},
                       headers=NO_ORIGIN).status_code == 403
    made = client.post("/api/roles", json={**helper, "max_steps": 3}, headers=own)
    assert made.status_code == 201, made.text
    assert client.delete(f"/api/roles/{made.json()['id']}", headers=NO_ORIGIN).status_code == 403
    # nor moved out of the way: a role is opened by its name
    assert client.patch(f"/api/roles/{made.json()['id']}", json={"name": "Aside"}).status_code == 403
    kept = client.get("/api/roles").json()[-1]
    assert (kept["name"], kept["max_steps"]) == ("Helper", 3)
    assert client.delete(f"/api/roles/{made.json()['id']}", headers=own).status_code == 204
    # one without a limit is made and deleted as before
    plain = client.post("/api/roles", json=helper)
    assert plain.status_code == 201 and plain.json()["max_steps"] is None
    assert client.delete(f"/api/roles/{plain.json()['id']}").status_code == 204


def looks(n):
    return step(call("list_dir", {}, f"c{n}"), i=5, o=2)


def test_the_leads_own_limit_ends_the_turn_and_is_no_failure_of_its_model(
    make_client, wait_run, project_dir
):
    client, model = make_client([looks(1), looks(2), text("never said")])
    client.headers["Origin"] = ORIGIN
    assert client.patch(f"/api/roles/{role_id(client, 'Lead')}",
                        json={"max_steps": 1}).status_code == 200
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    run, lead = snap["runs"][0], snap["agents"][0]
    assert (run["status"], run["error"]) == ("failed", "stopped at its role's limit of 1 step")
    assert (lead["status"], lead["error"], lead["failure"]) == ("failed", run["error"], None)
    assert len(model.calls) == 1


def test_a_stop_at_the_roles_limit_brings_no_advice_about_other_providers(
    team, wait_run, project_dir  # noqa: F811
):
    client, default, fast = team({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "look"}, "s")), text("ok")],
        "Coder": [looks(1), looks(2)],
    })
    client.headers["Origin"] = ORIGIN
    client.patch(f"/api/roles/{role_id(client, 'Coder')}", json={"max_tokens": 5})
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    ((status, said),) = results(snap)
    # (and KOLONİ's record line, K-kanit - as under a report)
    assert status == "failed" and reported(said) == (
        "Coder failed: stopped at its role's limit of 5 tokens: it used 7")
    assert said.endswith("\n\nWhat it did, from KOLONİ's record: read 0 files, wrote 0, ran 0 "
                         "commands, 0 web.")
    assert snap["agents"][1]["failure"] is None       # KOLONİ's own rule, not its model's failure


def test_a_model_that_reports_no_tokens_is_not_held_by_the_token_limit(
    make_client, wait_run, project_dir
):
    silent = step(call("list_dir", {}, "c1"), i=None, o=None)
    client, model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "look"}, "s")), text("ok")],
        "Coder": [silent, step(content="looked", i=None, o=None)],
    })
    client.headers["Origin"] = ORIGIN
    client.patch(f"/api/roles/{role_id(client, 'Coder')}", json={"max_tokens": 1})
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    assert snap["agents"][1]["status"] == "completed" and len(model.calls_of["Coder"]) == 2


class Session(ScriptedModel):
    """Stands in for a CLI session, which keeps its own loop: each run writes five
    messages, with a tool call after each but the last, and reports what it used when
    it ends."""

    session = True

    def __init__(self):
        super().__init__([])
        self.started = 0

    async def run_session(self, model_id, messages, tools, call_tool, on_text, on_message=None, on_live=None):
        self.started += 1
        self.offered = [tool["function"]["name"] for tool in tools]
        for n in range(1, 5):
            await on_text(f"step {n}.")
            await call_tool("list_dir", "{}")
        await on_text("step 5: done.")
        return SimpleNamespace(input_tokens=50, output_tokens=5, model=None)


def coder_on_a_session(settings_env, wait_run, project_dir, limits, lead_steps,
                       mode="full_auto"):
    """A turn whose Coder runs on a CLI session, with these limits on the Coder role."""
    cli = Session()
    default = ScriptedModel([
        step(call("spawn_agent", {"role": "Coder", "task": "look"}, "s")), *lead_steps])
    app = create_app(load_settings(settings_env), model=default, clients={"Cli": cli})
    with TestClient(app, base_url="http://127.0.0.1:8790") as client:
        client.headers["Origin"] = ORIGIN
        made = client.post("/api/providers", json={"name": "Cli", "kind": "claude_cli"})
        assert made.status_code == 201, made.text
        assert client.patch(f"/api/roles/{role_id(client, 'Coder')}", json={
            "provider_id": made.json()["id"], **limits}).status_code == 200
        cid, run_id = begin(client, project_dir, mode=mode, spawn_approval="never")
        return cli, wait_run(client, cid, run_id)


def test_a_cli_session_is_held_by_its_roles_steps_message_by_message(
    settings_env, wait_run, project_dir
):
    cli, snap = coder_on_a_session(
        settings_env, wait_run, project_dir, {"max_steps": 2}, [text("the lead goes on")])
    coder = snap["agents"][1]
    # KOLONİ counts a session's messages as its steps: after two, the third is not written
    assert (coder["status"], coder["error"], coder["failure"]) == (
        "failed", "stopped at its role's limit of 2 steps", None)
    assert [m["content"] for m in snap["messages"] if m["agent_id"] == coder["id"]] == [
        "step 1.", "step 2."]
    assert [t["status"] for t in snap["tool_calls"] if t["name"] == "list_dir"] == [
        "succeeded"] * 2
    ((status, said),) = results(snap)
    assert status == "failed" and said.startswith(
        "Coder failed: stopped at its role's limit of 2 steps")
    assert snap["runs"][0]["status"] == "completed"                # the turn goes on


def test_a_cli_session_at_its_own_work_is_offered_show(settings_env, wait_run, project_dir):
    """B-62: the Inspector listed show, the session agent said it had none."""
    cli, _snap = coder_on_a_session(settings_env, wait_run, project_dir, {}, [text("ok")])
    assert "show" in cli.offered, cli.offered


def test_a_real_cli_session_is_ended_at_its_roles_steps(session_app, wait_run, project_dir):  # noqa: F811
    script = [{"call": "list_dir"} for _ in range(5)] + [{"hang": True}]
    client, provider, _ = session_app(script)
    assert client.patch(f"/api/roles/{role_id(client, 'Lead')}", json={"max_steps": 2},
                        headers={"Origin": ORIGIN}).status_code == 200
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=30)
    assert (snap["runs"][0]["status"], snap["runs"][0]["error"]) == (
        "failed", "stopped at its role's limit of 2 steps")
    assert len(snap["tool_calls"]) == 2
    assert gone(session_app.record()["pid"])  # and its process with it


def limited_session(session_app, wait_run, project_dir, script):  # noqa: F811
    """A turn on a CLI session whose role lets one agent take two steps."""
    client, provider, _ = session_app(script)
    assert client.patch(f"/api/roles/{role_id(client, 'Lead')}", json={"max_steps": 2},
                        headers={"Origin": ORIGIN}).status_code == 200
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=30)
    said = [m for m in snap["messages"] if m["role"] == "assistant"]
    return snap, (snap["runs"][0]["status"], snap["runs"][0]["error"]), said


def test_a_message_of_a_cli_session_with_two_calls_is_one_step(session_app, wait_run, project_dir):  # noqa: F811
    """What the third review found: the calls were counted, not the messages. "Let me
    look." with two calls and then the answer stopped at a limit of two steps - the
    second call had opened an empty message of its own - where a model asked step by
    step completes. The stream names the message each piece belongs to."""
    look = [{"say": "Let me look.", "message": "m1"},
            {"call": "list_dir", "message": "m1"},
            {"call": "read_file", "args": {"path": "hello.py"}, "message": "m1"}]
    snap, ended, said = limited_session(
        session_app, wait_run, project_dir, [*look, {"say": "It prints hi."}])
    assert ended == ("completed", None)
    assert [m["content"] for m in said] == ["Let me look.", "It prints hi."]
    # both calls hang off the one message that carried them
    assert [(t["name"], t["status"], t["message_id"]) for t in snap["tool_calls"]] == [
        ("list_dir", "succeeded", said[0]["id"]), ("read_file", "succeeded", said[0]["id"])]


def test_calls_made_at_once_in_one_message_of_a_cli_session_are_one_step(session_app, wait_run, project_dir):  # noqa: F811
    """...for its role's limit and for the app's own (25 steps): the same count."""
    at_once = {"parallel": [{"call": "list_dir"} for _ in range(30)]}
    snap, ended, said = limited_session(
        session_app, wait_run, project_dir, [at_once, {"say": "Thirty looks."}])
    assert ended == ("completed", None)
    assert [m["content"] for m in said] == ["", "Thirty looks."]
    assert {(t["status"], t["message_id"]) for t in snap["tool_calls"]} == {
        ("succeeded", said[0]["id"])} and len(snap["tool_calls"]) == 30


def test_three_messages_of_a_cli_session_with_a_call_each_stop_after_the_second(session_app, wait_run, project_dir):  # noqa: F811
    script = [piece for name in ("one", "two", "three") for piece in (
        {"say": name, "message": name}, {"call": "list_dir", "message": name})]
    snap, ended, said = limited_session(
        session_app, wait_run, project_dir, [*script, {"hang": True}])
    assert ended == ("failed", "stopped at its role's limit of 2 steps")
    assert [m["content"] for m in said] == ["one", "two"] and len(snap["tool_calls"]) == 2


def test_a_cli_session_is_held_by_tokens_before_it_starts_again(
    settings_env, wait_run, project_dir
):
    cli, snap = coder_on_a_session(settings_env, wait_run, project_dir, {"max_tokens": 10}, [
        step(call("message_agent", {"to": "Coder", "message": "and again"}, "m")), text("done")])
    coder = snap["agents"][1]
    by_name = {t["name"]: (t["status"], t["result"]) for t in snap["tool_calls"]}
    # what it used was not known until it ended: its first run went through
    assert by_name["spawn_agent"][0] == "succeeded" and coder["input_tokens"] == 50
    # asked to go on, it is over its role's tokens: not started a second time
    assert by_name["message_agent"] == (
        "failed", "Coder could not reply: stopped at its role's limit of 10 tokens: it used 55")
    assert cli.started == 1 and snap["runs"][0]["status"] == "completed"


def test_a_cli_session_with_no_steps_of_its_role_left_is_not_started_again(
    settings_env, wait_run, project_dir
):
    """B-325 (live, Qoder): told to go on at its role's limit, it could not reply - and the
    words did not say why or what to do. (At Full auto too: B-401.)"""
    cli, snap = coder_on_a_session(settings_env, wait_run, project_dir, {"max_steps": 2}, [
        step(call("message_agent", {"to": "Coder", "message": "go on"}, "m")), text("done")],
        mode="auto_edit")
    by_name = {t["name"]: (t["status"], t["result"]) for t in snap["tool_calls"]}
    assert by_name["message_agent"] == ("failed", (
        "Coder is at its role's limit of 2 steps; more steps are the user's to give: ask them "
        "to raise the limit in the role's settings. Nothing was sent to it."))
    assert cli.started == 1 and snap["runs"][0]["status"] == "completed"


# --- a model that takes a conversation over ---------------------------------------------------


def lead(provider, model, mode=None, model_from=None):
    return SimpleNamespace(
        provider_name=provider, model_id=model, provider_mode=mode, model_from=model_from)


@pytest.mark.parametrize("before, now_on, told", [
    (lead("Local", "qwen"), lead("Fast", "quick"), "Local · qwen"),
    # a model nobody named, or one read from the CLI's settings: the provider alone
    (lead("Codex", "codex default", "step"), lead("Local", "qwen"), "Codex"),
    (lead("Codex", "gpt-6", "native", "settings"), lead("Local", "qwen"), "Codex"),
    (lead("Local", None), lead("Fast", "quick"), "Local"),
    # one API provider, another model: its names are the ones KOLONİ asks by
    (lead("Local", "qwen"), lead("Local", "llama"), "Local · qwen"),
    (lead("Local", "qwen"), lead("Local", "qwen"), None),
    (lead("Local", "qwen"), lead("Local", None), None),
    # a CLI reports its model by another name than it was asked by: not told apart
    (lead("Claude", "claude-sonnet-5", "session"), lead("Claude", "sonnet", "session"), None),
    (lead("Claude", "claude-sonnet-5", "session"), lead("Claude", "claude default", "session"),
     None),
    (None, lead("Local", "qwen"), None),            # the first turn: nobody led before
    (lead(None, None), lead("Local", "qwen"), None),  # a lead from before this was on record
])
def test_whose_conversation_a_lead_takes_over_is_read_off_the_two_leads_records(
    before, now_on, told
):
    assert _taken_from(before, now_on) == told


@pytest.mark.parametrize("second, told", [
    # the turn in between never answered: there is nothing of it to take over
    (ModelUnavailable("the server is down"), None),
    # it answered: the third turn does take the conversation over from it
    (text("second answer"), "Fast · fast-model"),
])
def test_a_lead_is_told_of_the_last_lead_that_answered_before_it(
    team, wait_run, project_dir, second, told  # noqa: F811
):
    client, default, fast = team([text("first answer"), text("third answer")], [second])
    cid, run_id = begin(client, project_dir)
    wait_run(client, cid, run_id)
    for provider_id in (team.providers["Fast"]["id"], None):      # to Fast, and back to Local
        client.patch(f"/api/conversations/{cid}", json={"provider_id": provider_id})
        posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "and now?"})
        wait_run(client, cid, posted.json()["run"]["id"])
    assert "Local · big-model; you are taking it over." in fast.calls[0][0]["content"]
    last = default.calls[1][0]["content"].splitlines()[-1]
    if told is None:
        assert "earlier turns" not in default.calls[1][0]["content"]
    else:
        assert last == (
            f"The earlier turns of this conversation were with {told}; you are taking it over.")


def test_trimming_says_how_many_results_it_blanked_out():
    result = lambda n: {"role": "tool", "content": f"{n}" * 100}  # noqa: E731
    messages = [{"role": "system", "content": "s"}, result(1), result(2), result(3)]
    assert _trim_to_budget(messages, 1000) == 0
    assert _trim_to_budget([dict(m) for m in messages], 250) == 1  # one gone, and it fits
    assert _trim_to_budget(messages, 150) == 2
    assert messages[3]["content"].startswith("3")  # the newest is cut, not blanked


def test_a_model_taking_over_a_history_that_was_cut_is_told_how_much_is_left_out(
    team, wait_run, project_dir, settings_env  # noqa: F811
):
    settings_env["KOLONI_CONTEXT_CHARS"] = "2000"   # less than the instructions alone
    (project_dir / "big.txt").write_text("line\n" * 300, encoding="utf-8")
    reads = [step(call("read_file", {"path": "big.txt"}, f"r{n}")) for n in range(3)]
    client, default, fast = team([*reads, text("first answer")], [text("second answer")])
    cid, run_id = begin(client, project_dir, mode="full_auto")
    wait_run(client, cid, run_id)
    client.patch(f"/api/conversations/{cid}", json={"provider_id": team.providers["Fast"]["id"]})
    second = client.post(f"/api/conversations/{cid}/messages", json={"content": "and now?"}).json()
    wait_run(client, cid, second["run"]["id"])
    system = fast.calls[0][0]["content"]
    assert system.splitlines()[-1] == (
        "The earlier turns of this conversation were with Local · big-model; you are taking "
        "it over. 2 older tool results are left out to fit.")
    # the model that read them itself was told nothing of the kind, cut or not
    assert "left out to fit" not in str(default.calls)


def test_what_is_cut_of_the_takers_own_work_is_no_part_of_what_it_is_told_it_took_over(
    team, wait_run, project_dir, settings_env  # noqa: F811
):
    settings_env["KOLONI_CONTEXT_CHARS"] = "2000"
    (project_dir / "big.txt").write_text("line\n" * 300, encoding="utf-8")
    reads = [step(call("read_file", {"path": "big.txt"}, f"r{n}")) for n in range(3)]
    client, default, fast = team([text("first answer")], [*reads, text("second answer")])
    cid, run_id = begin(client, project_dir, mode="full_auto")
    wait_run(client, cid, run_id)
    client.patch(f"/api/conversations/{cid}", json={"provider_id": team.providers["Fast"]["id"]})
    second = client.post(f"/api/conversations/{cid}/messages", json={"content": "and now?"}).json()
    wait_run(client, cid, second["run"]["id"])
    told = [request[0]["content"] for request in fast.calls]
    # the history it took over was whole; its own reads are cut as it goes (two by the
    # last step), and its instructions say the same at every step of the turn
    assert len(told) == 4 and len(set(told)) == 1
    assert told[0].endswith("were with Local · big-model; you are taking it over.")
    # (each said in a line made from its call: K-gecmis-zengin)
    assert sum(str(m["content"]).startswith(f"{TRIMMED} read big.txt (300 lines)")
               for m in fast.calls[3]) == 2


# --- the migration ----------------------------------------------------------------------------


def test_migration_0032_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0031")

    def columns(conn, table):
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}

    new = {"roles": {"pick_from", "max_steps", "max_tokens"}, "agents": {"chosen_why"}}
    with sqlite3.connect(db) as conn:
        assert not any(added & columns(conn, table) for table, added in new.items())
        conn.execute(
            "INSERT INTO roles (id, name, description, instructions, tools, builtin, "
            "created_by_agent, created_at, updated_at) VALUES ('r', 'Mine', '', '', '[]', 0, 0, "
            "'2026-10-12 10:00:00', '2026-10-12 10:00:00')")
        was = {table: columns(conn, table) for table in new}
    command.upgrade(cfg, "0032")
    with sqlite3.connect(db) as conn:
        assert all(columns(conn, table) == was[table] | added for table, added in new.items())
        # a role from before: everything in the guide may be picked, and it has no limit
        assert conn.execute("SELECT pick_from, max_steps, max_tokens FROM roles").fetchall() == [
            (None, None, None)]
        conn.execute("UPDATE roles SET pick_from = '[]', max_steps = 3")
    command.downgrade(cfg, "0031")
    with sqlite3.connect(db) as conn:
        assert {table: columns(conn, table) for table in new} == was
        assert conn.execute("SELECT id, name FROM roles").fetchall() == [("r", "Mine")]
