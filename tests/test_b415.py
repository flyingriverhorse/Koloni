"""B-415 (live, run 7: three teams in manual mode, every agent a Codex session): KOLONİ stopped the
Web app lead's session as Codex began a tool of its own (collabAgentToolCall), with the Coder it had
opened for its Build step still at work. Its row was failed - "Web app lead ended before its end" -
though the Coder then wrote the page; the Lead heard back from its last lead while an agent still
worked in the copy, so Ready for you was never asked and nothing reached the project.

Now the row of a lead that ends with its step's agents at work ends once the last of them is back
(at the step they came to) - unless the Lead opened the lead again, which owns the row from then -
and the Lead asks Ready for you before its answer ends the turn."""

import asyncio
import contextlib
from types import SimpleNamespace

import pytest

from app.agent import AgentRunner
from app.config import load_settings
from app.main import create_app
from app.model_client import OwnStop
from tests.conftest import Gate
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import OWN, teams_of
from tests.test_claim_scenarios import write
from tests.test_parallel import until
from tests.test_recipe_run_scenarios import READY, answer, asked, manual, one_step, row, two_steps
from tests.test_spawn import begin, call, spawn, step

# As `CodexSessionClient._unwanted` says it.
STOPPED = "Codex began a tool of its own (collabAgentToolCall); the session was stopped"
BOTH_LEADS = step(call("spawn_agent", {"role": "Web app lead", "task": "the page"}, "l1"),
                  call("spawn_agent", {"role": "Docs lead", "task": "the words"}, "l2"))


class StoppedLead(ScriptedModel):
    """The Web app lead as a CLI session: it opens a Coder (answered as it starts, its report to
    come later), and KOLONİ stops the session before the Coder is back. Opened again, it thinks
    until `thinks` is released, and ends."""

    session = True

    def __init__(self, thinks: Gate | None = None):
        super().__init__([])
        self.thinks, self.runs = thinks, 0

    async def run_session(self, model_id, messages, tools, call_tool, on_text, on_message=None,
                          effort=None, on_live=None):
        self.runs += 1
        if self.runs == 1:
            await on_text("Opening the Coder.")
            await call_tool("spawn_agent", '{"role": "Coder", "task": "build a.py"}')
            raise OwnStop(STOPPED)
        while self.thinks is not None and not self.thinks.released:
            await asyncio.sleep(0.01)
        await on_text("Looked at what the Coder did.")
        return SimpleNamespace(input_tokens=5, output_tokens=1, model=None)


@contextlib.contextmanager
def two_teams(settings_env, project_dir, lead_steps, recipe, thinks=None):
    """Web app (`recipe`, its lead a StoppedLead) and Docs (one step): (client, cid, run_id, the
    Coder's gate)."""
    built = Gate()
    default = ScriptedModel({
        "Lead": lead_steps,
        "Docs lead": [spawn("Docs writer", "write b.md", "d"), text("docs done")],
        "Coder": [built.step(step(write("a.py", "a\n"))), text("built")],
        "Docs writer": [step(write("b.md", "b\n", id="w2")), text("written")],
    })
    app = create_app(load_settings(settings_env), model=default,
                     clients={"Session": StoppedLead(thinks)})
    try:
        with TestClient(app, base_url="http://127.0.0.1:8790") as client:
            client.headers["Origin"] = OWN["Origin"]
            session = client.post("/api/providers", json={"name": "Session", "kind": "claude_cli"})
            assert session.status_code == 201, session.text
            teams = teams_of(client)
            assert client.patch(f"/api/roles/{teams['Web app']['lead']['id']}",
                                json={"provider_id": session.json()["id"]}).status_code == 200
            build, words = recipe(client), one_step(client, "Just write", "Docs writer")
            cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never",
                                teams_mode="manual", teams=[
                                    {"team_id": teams["Web app"]["id"], "recipe_id": build["id"]},
                                    {"team_id": teams["Docs"]["id"], "recipe_id": words["id"]}])
            built.wait_partial()
            yield client, cid, run_id, built
    finally:
        built.release()
        if thinks is not None:
            thinks.release()


def stopped_lead(client, cid):
    snap = until(client, cid, lambda s: any(
        t["name"] == "spawn_agent" and t["status"] == "failed" for t in s["tool_calls"]))
    (lead,) = [t for t in snap["tool_calls"] if t["name"] == "spawn_agent"
               and t["status"] == "failed"]
    assert STOPPED in lead["result"]
    return snap


@pytest.mark.parametrize("recipe, status, why", [
    (lambda client: one_step(client, "Just build", "Coder"), "ready", None),
    # (A step after it, which nobody opens: the row fails where the Coder left it - its work is
    # still taken in, B-84.)
    (two_steps, "failed", "Web app lead ended before its end"),
])
def test_a_lead_stopped_while_its_coder_works_leaves_the_coders_work_to_take_in(
        settings_env, wait_run, project_dir, recipe, status, why):
    lead_steps = [BOTH_LEADS, text("done"), text("read the Coder's report"), text("taken in")]
    with two_teams(settings_env, project_dir, lead_steps, recipe) as (client, cid, run_id, built):
        snap = stopped_lead(client, cid)
        # Its Coder still works: the row is not failed under it.
        assert (row(snap)["status"], row(snap)["why"]) == ("running", None)
        built.release()
        snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"], timeout=30)
        assert (row(snap)["status"], row(snap)["why"]) == (status, why)
        answer(client, asked(snap), "Take in")
        snap = wait_run(client, cid, run_id, timeout=30)
    assert [row(snap, 0)["status"], row(snap, 1)["status"]] == ["in", "in"]
    assert (project_dir / "a.py").read_bytes() == b"a\n" and (project_dir / "b.md").exists()


@pytest.mark.parametrize("new_lead_ends_first", [False, True])
def test_a_lead_opened_again_before_the_coder_is_back_owns_the_rows_end(
        settings_env, wait_run, project_dir, new_lead_ends_first):
    # The live Lead, told "Web app lead failed", opens it again: the old Coder then finishes while
    # the new lead thinks - the old lead's end must not fail the row under the new one. Or the
    # new lead ends first: the Coder coming back then ends the row by the new lead's end.
    thinks = Gate()
    lead_steps = [BOTH_LEADS, spawn("Web app lead", "go on from the Coder's work", "l3"),
                  *(text(said) for said in ("done", "read", "taken in", "over", "more", "end"))]
    with two_teams(settings_env, project_dir, lead_steps, two_steps, thinks) as (
            client, cid, run_id, built):
        stopped_lead(client, cid)
        until(client, cid, lambda s: [a["status"] for a in s["agents"]
                                      if a["role_name"] == "Web app lead"][1:] == ["running"])
        first, then = (thinks, built) if new_lead_ends_first else (built, thinks)
        first.release()

        def over(s):
            if new_lead_ends_first:
                return [a["status"] for a in s["agents"]
                        if a["role_name"] == "Web app lead"][1:] == ["completed"]
            return any(a["role_name"] == "Coder" and a["status"] == "completed"
                       for a in s["agents"]) and row(s)["steps"][0]["state"] == "done"

        snap = until(client, cid, over)
        assert (row(snap)["status"], row(snap)["why"]) == ("running", None)  # the new lead's
        then.release()
        snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"], timeout=30)
        assert row(snap)["status"] == "stopped" and row(snap)["why"].startswith(
            "Web app lead 2 ended before its end")  # (the new lead's end, not the old one's)
        answer(client, asked(snap), "Take in")
        snap = wait_run(client, cid, run_id, timeout=30)
    assert (project_dir / "a.py").read_bytes() == b"a\n"


def test_a_ready_for_you_due_only_at_the_leads_end_is_asked_under_an_agents_call(
        make_client, wait_run, project_dir, monkeypatch):
    # One team, run by the Lead itself (no team lead): as its Coder came back another agent was
    # in the copy (said busy here once), so nobody asked - the Lead's end does, in the Coder's
    # call (the Lead has none: a card with no call is no card).
    busy = AgentRunner._busy_in_copy
    first = [True]

    def once(runner, lead):
        if first[0]:
            first[0] = False
            return True
        return busy(runner, lead)

    monkeypatch.setattr(AgentRunner, "_busy_in_copy", once)
    client, _model = make_client({
        "Lead": [spawn("Coder", "build a.py", "c"), text("done"), text("taken in")],
        "Coder": [step(write("a.py", "a\n")), text("built")],
    })
    cid, run_id = manual(client, project_dir,
                         (teams_of(client)["Web app"], one_step(client, "Just build", "Coder")))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"], timeout=30)
    coder = next(a for a in snap["agents"] if a["role_name"] == "Coder")
    assert asked(snap)["tool_call_id"] == coder["tool_call_id"]
    answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert row(snap)["status"] == "in" and (project_dir / "a.py").read_bytes() == b"a\n"
