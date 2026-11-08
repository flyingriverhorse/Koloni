"""Batch-13: how a recipe's run ends (REA R43-R47, `tasarim/plans/canli-test-senaryolari.md` §6).

- B-82: a recipe turn stopped with Stop keeps the recipe's copy - Take in or Discard on Ready for
  you - after a refresh and a restart too; nothing of it is in the project before Take in.
- B-84: in multi-team work Ready for you waits for every picked team, not only the started ones -
  asked early, its card held the call the Lead waited on before opening the next team's lead.
  A team that failed or stopped before Take in, whose work went in with the one copy, is in.
- B-83: an answer that ends a recipe's run before its end is no end: its runner (the Lead, a
  team's lead; a CLI session too) is told the next step, at most twice a row, within the steps it
  had; told, an answer with no call is its why and stands. Ended anyway, the steps left are
  "skipped" - on the row's why and its step strip.
- B-90: in Manual a picked team has to work: the Lead's answer without it is told so, twice;
  then the team is shown as not started. The Lead deciding that worked with no team says why.
"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.db.models import Conversation, ConversationTeam
from app.tools import ToolError
from tests.fakes import ScriptedModel
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import OWN, no_recipe, teams_of
from tests.test_claim_scenarios import write
from tests.test_parallel import until
from tests.test_recipe_run_scenarios import READY, answer, asked, made, manual, one_step, row
from tests.test_recipes_scenarios import graph
from tests.test_recipes_scenarios import step as part
from tests.test_spawn import begin, call, spawn, step


def build_then_test(client):
    return made(client, "Build then test", graph(
        [part("build", "Build it", {"role": "Coder"}), part("test", "Test it", {"role": "Tester"})],
        [("start", "build"), ("build", "test"), ("test", "end")]))


def kept_of(snap):
    (kept,) = [m for m in snap["merges"] if m["status"] == "kept"]
    return kept


def test_stop_keeps_the_recipes_copy_and_take_in_takes_it_in(make_client, wait_run, project_dir, gate):
    client, _model = make_client({
        "Lead": [spawn("Coder", "build"), gate.step(text("never said"))],
        "Coder": [step(write("a.py", "a\n")), text("built")],
    })
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], build_then_test(client)))
    gate.wait_partial()
    client.post(f"/api/runs/{run_id}/cancel", headers=OWN)
    snap = wait_run(client, cid, run_id)
    assert (row(snap)["status"], row(snap)["why"], row(snap)["ended_ready"]) == ("stopped", "Stopped", False)
    # Kept, not taken: the project is untouched until the user's Take in.
    assert not (project_dir / "a.py").exists()
    taken = client.post(f"/api/merges/{kept_of(snap)['id']}/approve", json={"choices": {}}, headers=OWN)
    assert taken.status_code == 200, taken.text
    assert (project_dir / "a.py").read_bytes() == b"a\n"
    assert row(client.get(f"/api/conversations/{cid}").json())["status"] == "in"


def test_discard_after_stop_throws_the_recipes_copy_away(make_client, wait_run, project_dir, gate):
    client, _model = make_client({
        "Lead": [spawn("Coder", "build"), gate.step(text("never said"))],
        "Coder": [step(write("a.py", "a\n")), text("built")],
    })
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], build_then_test(client)))
    gate.wait_partial()
    client.post(f"/api/runs/{run_id}/cancel", headers=OWN)
    kept = kept_of(wait_run(client, cid, run_id))
    gate.release()
    thrown = client.post(f"/api/merges/{kept['id']}/reject", headers=OWN)
    assert thrown.status_code == 200, thrown.text
    snap = client.get(f"/api/conversations/{cid}").json()
    assert [m["status"] for m in snap["merges"]] == ["rejected"]
    assert not (project_dir / "a.py").exists() and not Path(kept["kept_in"]).exists()


def test_stop_during_take_in_keeps_only_what_did_not_go_in(make_client, wait_run, project_dir, monkeypatch):
    # B-82's review: Stop while Take in writes the copy into the project.
    from app.agent import AgentRunner
    seen = AgentRunner._seen_by_watchers

    async def stop_there(self, ctx, paths, copy=None):
        await seen(self, ctx, paths, copy)
        if copy is None and "a.py" in paths:  # (a.py is in the project now)
            self.cancel(ctx.run_id)
            await asyncio.sleep(0.1)

    monkeypatch.setattr(AgentRunner, "_seen_by_watchers", stop_there)
    client, _model = make_client({"Lead": [spawn("Coder", "build"), text("done")],
                                  "Coder": [step(write("a.py", "a\n")), text("built")]})
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], one_step(client, "Just build", "Coder")))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "cancelled" and (project_dir / "a.py").read_bytes() == b"a\n"
    # Whatever card is left offers nothing that is in the project already.
    offered = [f["path"] for m in snap["merges"] if m["status"] in ("pending", "kept")
               for f in m["files"] if f["state"] != "applied"]
    assert "a.py" not in offered


def test_a_next_turn_leaves_a_stopped_rows_kept_work_for_take_in(make_client, wait_run, project_dir, gate):
    # B-90's review: a next turn without the team wrote "waiting" over the row whose work was
    # kept - Ready for you lost its Take in / Discard, and a Take in never set the row in.
    client, _model = make_client({
        "Lead": [spawn("Coder", "build"), gate.step(text("never said")),
                 step(write("c.txt", "c\n", id="w9")), text("did it myself"), text("never")],
        "Coder": [step(write("a.py", "a\n")), text("built")],
    })
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], build_then_test(client)))
    gate.wait_partial()
    client.post(f"/api/runs/{run_id}/cancel", headers=OWN)
    wait_run(client, cid, run_id)
    gate.release()
    later = client.post(f"/api/conversations/{cid}/messages", headers=OWN,
                        json={"content": "and c.txt"}).json()["run"]["id"]
    snap = wait_run(client, cid, later)
    assert (row(snap)["status"], row(snap)["run_id"]) == ("stopped", run_id)
    taken = client.post(f"/api/merges/{kept_of(snap)['id']}/approve", json={"choices": {}}, headers=OWN)
    assert taken.status_code == 200, taken.text
    assert row(client.get(f"/api/conversations/{cid}").json())["status"] == "in"


def test_a_stopped_recipes_copy_outlives_a_restart(settings_env, project_dir):
    from app.config import load_settings
    from app.main import create_app
    from tests.conftest import Gate
    from tests.fakes import ScriptedModel
    from tests.keyed import TestClient
    from tests.test_copy_later_scenarios import again
    held = Gate()
    app_ = create_app(load_settings(settings_env), model=ScriptedModel({
        "Lead": [spawn("Coder", "build"), held.step(text("never said"))],
        "Coder": [step(write("a.py", "a\n")), text("built")],
    }))
    with TestClient(app_, base_url="http://127.0.0.1:8790") as client:
        client.headers.update(OWN)
        cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], build_then_test(client)))
        held.wait_partial()
        client.post(f"/api/runs/{run_id}/cancel")
        until(client, cid, lambda s: s["runs"][0]["status"] == "cancelled")
    held.release()
    with again(settings_env) as client:
        snap = client.get(f"/api/conversations/{cid}").json()
        assert row(snap)["status"] == "stopped" and not (project_dir / "a.py").exists()
        assert kept_of(snap)["kept_in"]
        taken = client.post(f"/api/merges/{kept_of(snap)['id']}/approve", json={"choices": {}})
        assert taken.status_code == 200, taken.text
        assert (project_dir / "a.py").read_bytes() == b"a\n"
        assert row(client.get(f"/api/conversations/{cid}").json())["status"] == "in"


SCRIPTS = {
    "Web app lead": [spawn("Coder", "build a.py", "c"), text("web done")],
    "Docs lead": [spawn("Docs writer", "write b.md", "d"), text("docs done")],
    "Quality lead": [spawn("Tester", "test it", "t"), text("tested")],
    "Coder": [step(write("a.py", "a\n")), text("built")],
    "Docs writer": [step(write("b.md", "b\n", id="w2")), text("written")],
    "Tester": [text("Fine.\n\nFindings: none")],
}


def rows_of(client, three):
    teams = teams_of(client)
    rows = [(teams["Web app"], one_step(client, "Just build", "Coder")),
            (teams["Docs"], one_step(client, "Just write", "Docs writer"))]
    return rows + ([(teams["Quality"], one_step(client, "Just test", "Tester"))] if three else [])


def refused_beside(lead_id="l2"):
    """Web app's lead, and beside it Docs' lead refused (a tier with no why, as live): Docs has
    not started when Web app is at its end."""
    return step(call("spawn_agent", {"role": "Web app lead", "task": "the page"}, "l1"),
                call("spawn_agent", {"role": "Docs lead", "task": "the words", "tier": "fast"}, lead_id))


def as_picked(monkeypatch):
    """Every row of the chat has to work in the turn, as when the Lead picked them in it or a night's
    card gave them (`_teams_for`) - for the tests of what KOLONİ does with such teams: opens their leads
    beside, tells the Lead of one left, holds Ready for you. (B-161: in Manual none has to; the Lead
    opens those the message concerns.)"""
    from app.agent import AgentRunner
    monkeypatch.setattr(AgentRunner, "_teams_for", lambda self, session, ctx: {
        team.id for _row, team, _lead in self._rows(session, ctx.cid)})


def test_ready_for_you_waits_for_a_team_not_started_yet(make_client, wait_run, project_dir, monkeypatch):
    # B-84 (live, 25 Oct): with Docs' lead not started, Ready for you was asked in Web app's lead's
    # call - and the Lead got that call's result, to open Docs' lead, only after the user's Take in.
    client, _model = make_client({
        "Lead": [refused_beside(), spawn("Docs lead", "the words", "l3"), text("all done")], **SCRIPTS})
    as_picked(monkeypatch)
    rows = rows_of(client, False)
    cid, run_id = manual(client, project_dir, *rows)
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    assert [row(snap, 0)["status"], row(snap, 1)["status"]] == ["ready", "ready"]
    assert not (project_dir / "a.py").exists()
    answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id)
    assert [row(snap, 0)["status"], row(snap, 1)["status"]] == ["in", "in"]
    assert (project_dir / "a.py").exists() and (project_dir / "b.md").exists()
    assert len([q for q in snap["questions"] if READY in q["question"]]) == 1


def together(name, result, started, of=3):
    """A lead's first step, held until all `of` teams' leads are at work: alone, it fails."""
    async def held(on_delta):
        started.add(name)
        for _ in range(300):
            if len(started) == of:
                return result
            await asyncio.sleep(0.01)
        raise AssertionError(f"{name} was at work alone: {sorted(started)}")
    return held


def test_the_teams_leads_work_at_the_same_time_opened_by_koloni_beside_the_first(
    make_client, wait_run, project_dir, monkeypatch
):
    # B-87 (live, 25 Oct): the Lead opened each team's lead in a message of its own and waited for it.
    started: set[str] = set()
    client, model = make_client({
        # It asks for the others too, after: they are not opened twice.
        "Lead": [spawn("Web app lead", "the page", "l1"), spawn("Docs lead", "the words", "l2"), text("all done")],
        **SCRIPTS,
        **{lead: [together(lead, script[0], started), *script[1:]] for lead, script in SCRIPTS.items()
           if lead.endswith(" lead")},
    })
    as_picked(monkeypatch)
    # (Room for the three at once in "Agents at the same time".)
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never", teams_mode="manual",
                        spawn_max_parallel=4, teams=[{"team_id": team["id"], "recipe_id": recipe["id"]}
                                                     for team, recipe in rows_of(client, True)])
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    assert [row(snap, at)["status"] for at in range(3)] == ["ready"] * 3
    # Three leads at once in the recipe's copy: nothing of it in the project before Take in.
    assert not (project_dir / "a.py").exists() and not (project_dir / "b.md").exists()
    answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id)
    assert [row(snap, at)["status"] for at in range(3)] == ["in"] * 3
    assert (project_dir / "a.py").exists() and (project_dir / "b.md").exists()
    leads = [a for a in snap["agents"] if a["role_name"].endswith(" lead")]
    assert sorted(a["role_name"] for a in leads) == ["Docs lead", "Quality lead", "Web app lead"]
    first, again = [t for t in snap["tool_calls"] if t["name"] == "spawn_agent" and t["agent_id"] == leads[0]["parent_agent_id"]
                    and t["provider_call_id"] in ("l1", "l2")]
    assert "KOLONİ opened Docs lead, Quality lead at the same time" in first["result"]
    assert "docs done" in first["result"] and "tested" in first["result"]
    assert again["status"] == "failed" and "Docs lead is not opened again" in again["result"]
    # The others were given the user's message.
    docs = model.calls_of["Docs lead"][0]
    assert "KOLONİ opened you at the same time as Web app lead" in docs[1]["content"]


def test_in_manual_the_lead_is_told_to_open_its_leads_in_one_message_and_they_work_side_by_side(
        make_client, wait_run, project_dir):
    # (The review of B-161: nothing is opened beside in Manual - a lead opened in a later message waits for
    # the first one's whole recipe. Two opened in one message work at the same time.)
    from app.agent import SAME_MESSAGE
    started: set[str] = set()
    client, model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Web app lead", "task": "the page"}, "l1"),
                      call("spawn_agent", {"role": "Docs lead", "task": "the words"}, "l2")), text("done")],
        **SCRIPTS,
        **{lead: [together(lead, SCRIPTS[lead][0], started, of=2), *SCRIPTS[lead][1:]]
           for lead in ("Web app lead", "Docs lead")},
    })
    cid, run_id = manual(client, project_dir, *rows_of(client, False))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    assert [row(snap, at)["status"] for at in range(2)] == ["ready", "ready"]
    spawn_of = next(t["function"] for t in model.tool_args[0] if t["function"]["name"] == "spawn_agent")
    assert SAME_MESSAGE in spawn_of["description"]
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)


def test_teams_the_lead_picked_in_its_turn_have_to_work_their_leads_opened_beside(make_client, wait_run, project_dir):
    # (B-161: what `as_picked` stands for, unpatched - the Lead's own pick_teams, then one lead: KOLONİ opens the other.)
    from tests.test_chat_teams_scenarios import pick
    client, model = make_client({
        "Lead": [pick({"team": "Web app", "recipe": "Just build", "why": "the page"}, {"team": "Docs", "why": "its words"}),
                 spawn("Web app lead", "the page", "l1"), text("done")], **SCRIPTS})
    one_step(client, "Just build", "Coder")
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never", teams_mode="lead")
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id)
    assert sorted(a["role_name"] for a in snap["agents"] if a["depth"] == 1) == ["Docs lead", "Web app lead"]
    assert model.calls_of["Docs lead"][0][1]["content"].startswith("KOLONİ opened you at the same time as Web app lead")


def test_a_lead_refused_before_it_opens_opens_none_beside_it(make_client, wait_run, project_dir, monkeypatch):
    # B-87's review: the others were opened beside a call that failed, and their reports lost
    # with it - while a later spawn of theirs was told the report came with that call.
    client, _model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Web app lead", "task": "the page", "tier": "fast"}, "l0")),
                 spawn("Web app lead", "the page", "l1"), text("all done")], **SCRIPTS})
    as_picked(monkeypatch)
    cid, run_id = manual(client, project_dir, *rows_of(client, False))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id)
    refused, opened = [t for t in snap["tool_calls"] if t["provider_call_id"] in ("l0", "l1")]
    assert refused["status"] == "failed" and "beside" not in refused["result"]
    assert "KOLONİ opened Docs lead at the same time" in opened["result"] and "docs done" in opened["result"]
    assert sorted(a["role_name"] for a in snap["agents"] if a["role_name"].endswith(" lead")) == [
        "Docs lead", "Web app lead"]


def test_a_lead_being_opened_beside_another_is_not_opened_twice(make_client, project_dir, gate, monkeypatch):
    # B-87's review: a CLI Lead's two spawns at once (MCP calls, listed in no message first).
    client, _model = make_client({"Lead": [gate.step(text("held"))]})
    as_picked(monkeypatch)
    manual(client, project_dir, *rows_of(client, False))
    gate.wait_partial()
    runner = client.app.state.runner
    lead = next(c for c in runner._ctxs.values() if c.depth == 0)
    beside = runner._leads_beside(lead, "c1", {"role": "Web app lead"})
    assert [one["role"] for one in beside] == ["Docs lead"]
    with pytest.raises(ToolError, match="if that call fails, ask for Docs lead again"):
        runner._leads_beside(lead, "c2", {"role": "Docs lead"})  # being opened, not on record yet
    runner._beside[lead.agent_id]["docs lead"] = ("k1", None)
    with pytest.raises(ToolError, match="its report comes - or came - with that call's result"):
        runner._leads_beside(lead, "c2", {"role": "Docs lead"})  # at work
    runner._beside[lead.agent_id]["docs lead"] = (None, "succeeded")
    with pytest.raises(ToolError, match="Docs lead is not opened again"):
        runner._leads_beside(lead, "c3", {"role": "Docs lead"})  # done, its team not started
    runner._beside[lead.agent_id]["docs lead"] = (None, "failed")
    assert runner._leads_beside(lead, "c4", {"role": "Docs lead"}) == []  # opened again, alone
    gate.release()


def test_teams_picked_for_an_earlier_message_are_not_opened_beside(make_client, wait_run, project_dir):
    # B-87's review: the Lead deciding, a later "fix the button" opened every team's lead.
    client, model = make_client({"Lead": [spawn("Web app lead", "the button", "l1"), text("fixed")], **SCRIPTS})
    rows = rows_of(client, True)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", headers=OWN, json={
        "permission_mode": "auto_edit", "spawn_approval": "never", "teams_mode": "lead"})
    with client.app.state.session_factory() as session:  # (as the Lead's pick_teams left them)
        session.get_one(Conversation, cid).teams = [ConversationTeam(
            team_id=team["id"], recipe_id=recipe["id"], picked_by="lead", why="earlier", position=at)
            for at, (team, recipe) in enumerate(rows)]
        session.commit()
    run_id = client.post(f"/api/conversations/{cid}/messages", headers=OWN,
                         json={"content": "fix the button"}).json()["run"]["id"]
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id)
    assert [a["role_name"] for a in snap["agents"] if a["role_name"].endswith(" lead")] == ["Web app lead"]
    assert len(model.calls_of["Lead"]) == 2  # (and not told the others have to work)


def test_a_team_whose_work_went_in_with_the_copy_is_in_not_failed(make_client, wait_run, project_dir):
    # B-84: "failed: Web app lead ended before its end" though its cart.py was in the project.
    client, model = make_client({
        "Lead": [step(spawn("Web app lead", "the page", "l1").tool_calls[0],
                      spawn("Docs lead", "the words", "l2").tool_calls[0]), text("all done")],
        **SCRIPTS,
        # (It ends at its Test it step, told twice where its recipe is.)
        "Web app lead": [spawn("Coder", "build a.py", "c"), text("web done"), text("done"), text("done")],
    })
    teams = teams_of(client)
    cid, run_id = manual(client, project_dir, (teams["Web app"], build_then_test(client)),
                         (teams["Docs"], one_step(client, "Just write", "Docs writer")))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    assert row(snap, 0)["status"] in ("failed", "stopped") and row(snap, 1)["status"] == "ready"
    # The one copy goes in whole: the card says Web app's part goes in with Docs'.
    assert "Take in also takes in what Web app left before it stopped." in asked(snap)["question"]
    answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id)
    assert (project_dir / "a.py").exists() and (project_dir / "b.md").exists()
    assert [row(snap, 0)["status"], row(snap, 1)["status"]] == ["in", "in"]
    # B-83: a team's lead is told its recipe's next step too; ended anyway, it skipped it.
    assert row(snap, 0)["why"] == "Web app lead ended before its end: rule broken: Test it was not done"
    assert [s["state"] for s in row(snap, 0)["steps"]] == ["done", "skipped", "next"]
    assert "the Build then test recipe's next step is Test it" in str(model.calls_of["Web app lead"][2][-1])


class Session(ScriptedModel):
    """A CLI session for every agent (live B-83 was on Claude Code's): the Lead opens a Coder
    once and then only answers; the Coder writes a.py."""

    session = True

    def __init__(self):
        super().__init__([])
        self.lead = []

    async def run_session(self, model_id, messages, tools, call_tool, on_text, on_message=None, effort=None,
                           on_live=None):
        if "Your name here is Coder" in str(messages[0]["content"]):
            await call_tool("write_file", json.dumps({"path": "a.py", "content": "a\n"}))
            await on_text("built")
        else:
            self.lead.append(messages)
            if len(self.lead) == 1:
                await call_tool("spawn_agent", json.dumps({"role": "Coder", "task": "build"}))
            await on_text(f"I stop here ({len(self.lead)})")
        return SimpleNamespace(input_tokens=5, output_tokens=1, model=None)


def test_a_cli_session_lead_that_skips_a_step_is_told_then_ready_for_you_says_so(settings_env, project_dir):
    # B-83 (live, CC-S): the Lead ended after Coder without opening the Check step, three times.
    from app.config import load_settings
    from app.main import create_app
    from tests.keyed import TestClient
    cli = Session()
    with TestClient(create_app(load_settings(settings_env), model=cli), base_url="http://127.0.0.1:8790") as client:
        client.headers.update(OWN)
        cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], build_then_test(client)))
        snap = until(client, cid, lambda s: s["runs"][0]["status"] == "completed")
    # Its session is run anew with what it was told after its answer; answering with no call again
    # is its why, which stands (the review: no second time for nothing).
    assert len(cli.lead) == 2
    assert "the Build then test recipe's next step is Test it (Tester)" in cli.lead[1][-1]["content"]
    assert cli.lead[1][-2]["content"] == "I stop here (1)"
    assert (row(snap)["status"], row(snap)["why"]) == ("stopped", "rule broken: Test it was not done")
    assert not (project_dir / "a.py").exists() and kept_of(snap)["kept_in"]


def test_a_picked_team_that_never_started_is_shown_waiting_and_its_work_kept(make_client, wait_run, project_dir):
    # B-84: Ready for you named only the teams that started. (The Lead is told twice to open it.)
    # (B-161: the teams the Lead's own pick_teams gave, unpatched.)
    from tests.test_chat_teams_scenarios import pick
    client, _model = make_client({"Lead": [
        pick({"team": "Web app", "recipe": "Just build", "why": "the page"},
             {"team": "Docs", "recipe": "Just write", "why": "its words"}),
        refused_beside(), text("done"), text("done"), text("done")], **SCRIPTS})
    rows_of(client, False)  # (its recipes)
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never", teams_mode="lead")
    snap = wait_run(client, cid, run_id)
    assert (row(snap, 1)["status"], row(snap, 1)["team"], row(snap, 1)["recipe"]) == ("waiting", "Docs", "Just write")
    assert [s["state"] for s in row(snap, 1)["steps"]] == ["next", "next"]
    # The Web app's work is kept for Take in; nothing is in the project.
    assert row(snap, 0)["status"] == "stopped" and not (project_dir / "a.py").exists()
    assert [m["status"] for m in snap["merges"]] == ["kept"]


def product(client, project_dir, content="please check my greeting"):
    team = no_recipe(client, "Product")["Product"]  # (0103 gives Product Spec: none here)
    return begin(client, project_dir, mode="auto_edit", spawn_approval="never", teams_mode="manual",
                 content=content, teams=[{"team_id": team["id"], "recipe_id": None}])


def test_a_team_that_has_to_work_the_lead_skips_is_asked_for_twice_then_named(make_client, wait_run, project_dir):
    # B-90 (live): Manual with Product picked, the Lead did the work itself; Product owner never opened.
    # (B-161: in Manual that is the Lead's choice - here Product has to work, picked by the Lead's own
    # pick_teams, unpatched.)
    # (Told, it works on again by itself - then, told a second time, only answers: that stands.)
    from tests.test_chat_teams_scenarios import pick
    client, model = make_client({"Lead": [pick({"team": "Product", "why": "its tasks"}),
                                          step(write("a.txt", "a\n")), text("I did it myself"),
                                          step(write("b.txt", "b\n", id="w2")), text("still me"),
                                          text("done"), text("never")]})
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never", teams_mode="lead")
    snap = wait_run(client, cid, run_id)
    calls = model.calls_of["Lead"]
    told = "the Product team has to work on this message and did not: open one of its roles ("
    assert len(calls) == 6 and told in calls[3][-1]["content"] and told in calls[5][-1]["content"]
    assert (row(snap)["status"], row(snap)["team"]) == ("waiting", "Product")


@pytest.mark.parametrize("content", ["fix the typo in a.txt", "Product'a iş yok: fix the typo in a.txt"])
def test_in_manual_a_team_is_the_leads_to_open_or_leave_named_or_not(make_client, wait_run, project_dir, content):
    # B-153 (the user: "Lead picks the relevant teams"): Manual's teams are those the Lead may use - for a
    # message that is none of theirs it does the work itself, and is not told a team has to. B-161 (live):
    # "Web app'e iş yok" opened the Web app, named - a team named is no team that has to work either.
    client, model = make_client({"Lead": [step(write("a.txt", "a\n")), text("I did it myself"), text("never")]})
    cid, run_id = product(client, project_dir, content=content)
    snap = wait_run(client, cid, run_id)
    assert len(model.calls_of["Lead"]) == 2
    assert not any("has to work on this message" in str(m) for m in model.calls_of["Lead"][-1])
    assert snap["conversation"]["teams"][0]["state"] is None


def test_in_manual_a_thanks_is_no_work_a_team_has_to_do(make_client, wait_run, project_dir):
    # B-90's review: every message in Manual cost two more Lead runs, a "thanks" too.
    client, model = make_client({"Lead": [text("You're welcome."), text("never")]})
    cid, run_id = product(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert len(model.calls_of["Lead"]) == 1 and snap["conversation"]["teams"][0]["state"] is None


def test_told_to_go_on_the_lead_goes_on_within_the_steps_it_had(make_client, wait_run, project_dir, monkeypatch):
    # B-83/B-90's review: each time it was told, it had a fresh step limit.
    from app.agent import AgentRunner
    monkeypatch.setattr(AgentRunner, "_step_limit", lambda self, ctx: 3)
    as_picked(monkeypatch)
    client, model = make_client({"Lead": [step(write("a.txt", "a\n")), text("me"),
                                          step(write("b.txt", "b\n", id="w2")), text("never")]})
    cid, run_id = product(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert len(model.calls_of["Lead"]) == 3
    assert snap["runs"][0]["status"] == "failed" and "step" in snap["runs"][0]["error"]


def test_in_manual_a_team_whose_role_was_opened_ran(make_client, wait_run, project_dir):
    client, model = make_client({"Lead": [spawn("Product owner", "add the tasks"), text("added")],
                                 "Product owner": [text("three tasks")]})
    cid, run_id = product(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert len(model.calls_of["Lead"]) == 2 and snap["conversation"]["teams"][0]["state"] is None


@pytest.mark.parametrize("worked", [True, False])
def test_the_lead_deciding_with_no_team_after_work_says_in_a_line_why(make_client, wait_run, project_dir, worked):
    # B-90 (live): "0 teams · Lead decides" - the Lead did the work and never said why no team.
    client, model = make_client({
        "Lead": [*([spawn("Coder", "build")] if worked else []), text("done"), text("No team: a one-line fix.")],
        "Coder": [step(write("a.py", "a\n")), text("built")],
    })
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never", teams_mode="lead")
    wait_run(client, cid, run_id)
    calls = model.calls_of["Lead"]
    if not worked:  # (a question answered needs no team)
        assert len(calls) == 1
        return
    assert len(calls) == 3 and "you picked no team for this message, which asked for work: say in one line why" in (
        calls[2][-1]["content"])
