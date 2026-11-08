"""B-415 (live, run 7: three teams in manual mode, every agent a Codex session): KOLONİ stopped the
Web app lead's session as Codex began a tool of its own (collabAgentToolCall), with the Coder it had
opened for its Build step still at work. Its row was failed - "Web app lead ended before its end" -
though the Coder then wrote the page; the Lead heard back from its last lead while an agent still
worked in the copy, so Ready for you was never asked and nothing reached the project.

Now the row of a lead that ends with its step's agents at work ends once the last of them is back
(at the step they came to), and the Lead asks Ready for you before its answer ends the turn."""

import pytest

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
from tests.test_recipe_run_scenarios import READY, answer, asked, one_step, row, two_steps
from tests.test_spawn import begin, call, spawn, step

# As `CodexSessionClient._unwanted` says it.
STOPPED = "Codex began a tool of its own (collabAgentToolCall); the session was stopped"


class StoppedLead(ScriptedModel):
    """The Web app lead as a CLI session: it opens a Coder (answered as it starts, its report to
    come later), and KOLONİ stops the session before the Coder is back."""

    session = True

    def __init__(self):
        super().__init__([])

    async def run_session(self, model_id, messages, tools, call_tool, on_text, on_message=None,
                          effort=None, on_live=None):
        await on_text("Opening the Coder.")
        await call_tool("spawn_agent", '{"role": "Coder", "task": "build a.py"}')
        raise OwnStop(STOPPED)


@pytest.mark.parametrize("recipe, status, why", [
    (lambda client: one_step(client, "Just build", "Coder"), "ready", None),
    # (A step after it, which nobody opens: the row fails where the Coder left it - its work is
    # still taken in, B-84.)
    (two_steps, "failed", "Web app lead ended before its end"),
])
def test_a_lead_stopped_while_its_coder_works_leaves_the_coders_work_to_take_in(
        settings_env, wait_run, project_dir, recipe, status, why):
    built = Gate()
    default = ScriptedModel({
        "Lead": [step(call("spawn_agent", {"role": "Web app lead", "task": "the page"}, "l1"),
                      call("spawn_agent", {"role": "Docs lead", "task": "the words"}, "l2")),
                 text("done"), text("read the Coder's report"), text("taken in")],
        "Docs lead": [spawn("Docs writer", "write b.md", "d"), text("docs done")],
        "Coder": [built.step(step(write("a.py", "a\n"))), text("built")],
        "Docs writer": [step(write("b.md", "b\n", id="w2")), text("written")],
    })
    app = create_app(load_settings(settings_env), model=default, clients={"Session": StoppedLead()})
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
        snap = until(client, cid, lambda s: any(
            t["name"] == "spawn_agent" and t["status"] == "failed" for t in s["tool_calls"]))
        (lead,) = [t for t in snap["tool_calls"] if t["name"] == "spawn_agent"
                   and t["status"] == "failed"]
        assert STOPPED in lead["result"]
        # Its Coder still works: the row is not failed under it.
        assert (row(snap)["status"], row(snap)["why"]) == ("running", None)
        built.release()
        snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"], timeout=30)
        assert (row(snap)["status"], row(snap)["why"]) == (status, why)
        answer(client, asked(snap), "Take in")
        snap = wait_run(client, cid, run_id, timeout=30)
    assert [row(snap, 0)["status"], row(snap, 1)["status"]] == ["in", "in"]
    assert (project_dir / "a.py").read_bytes() == b"a\n" and (project_dir / "b.md").exists()
