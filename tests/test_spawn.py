"""Sub-agents: spawn_agent, create_role, the channel, limits and approval."""

import json
import os
import re
import tempfile
import time
from types import SimpleNamespace

import pytest

from app.model_client import ModelUnavailable, StepResult, ToolCallRequest
from app.roles import BUILTIN_ROLES, effective_tools
from tests.fakes import Script, ScriptedExecutor, ScriptedModel
from tests.test_agent_writes import wait_status
from tests.test_chat_flow import text

READ = ["list_dir", "read_file", "search", "view_image"]  # (28e)
NOTEBOOK = ["post_note", "read_notes"]
MEMORY = ["remember", "recall"]
REVIEWER = [*READ, "ask_user", "message_agent", *NOTEBOOK, *MEMORY]
# What it is offered: show too, after the file tools - every agent's at its own work (slice 39).
OFFERED_REVIEWER = [*READ, "show", *REVIEWER[len(READ):], "recall_output"]
# The roles a new database has: six, five more since 28a, nine since 43, one 33b, two 52, five and
# two experts of the user's own (K-takim-duzen, 0103), the Designer (K-belge-ciktilari), three for a
# site (K-site-roller): the built-in roles and 0103's two experts.
BUILT_IN = len(BUILTIN_ROLES) + 2


def call(name, args, id="c1"):
    return ToolCallRequest(id, name, json.dumps(args))


def step(*calls, content="", i=5, o=2):
    return StepResult(content, list(calls), i, o)


def spawn(role, task="do the thing", id="s1"):
    return step(call("spawn_agent", {"role": role, "task": task}, id))


def new_role(name, tools, id="r1", **more):
    return step(call("create_role", {"name": name, "tools": tools, **more}, id))


def begin(client, project_dir, mode="ask", content="please check my greeting", **settings):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    # (a level is raised only from the app's own page: this request says it is from there)
    patched = client.patch(f"/api/conversations/{cid}", json={"permission_mode": mode, **settings},
                           headers={"Origin": "http://127.0.0.1:8790"})
    assert patched.status_code == 200, patched.text
    # (The user's own message, from the app's own page: a role it names is opened, slice 81b.)
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": content},
                         headers={"Origin": "http://127.0.0.1:8790"}).json()
    return cid, posted["run"]["id"]


def reported(result: str) -> str:
    """A spawn_agent result without KOLONİ's line on a thin task (K-brief-kalitesi): a test's
    task is short, and the line is asserted once (`test_a_thin_task_is_said_to_its_opener`) -
    nor its record line (K-kanit), asserted in `test_child_runs_with_a_clean_context_...`."""
    return re.sub(r"\n\nWhat it did\b[^\n]*", "", result.split("\n\nKOLONİ: the task you gave")[0])


def names(tools):
    return [t["function"]["name"] for t in tools]


def role_id(client, name):
    return next(r["id"] for r in client.get("/api/roles").json() if r["name"] == name)


def test_a_role_the_lead_names_but_never_opened_is_said_so_under_its_answer(
    make_client, wait_run, project_dir
):
    # K-lead-andigi-rol (R114): "Reviewer confirmed" with no Reviewer opened; a question is no claim.
    client, model = make_client([
        text("Reviewer confirmed the change.\nShould I open a Tester?"),
        spawn("Reviewer"), text("No problems found."), text("Reviewer confirmed it."),
    ])
    cid, run_id = begin(client, project_dir)

    def koloni(snap):
        return [m["content"] for m in snap["messages"] if m["role"] == "koloni"]

    assert koloni(wait_run(client, cid, run_id)) == ["Reviewer was not opened this turn."]
    again = client.post(f"/api/conversations/{cid}/messages", json={"content": "again"},
                        headers={"Origin": "http://127.0.0.1:8790"}).json()["run"]["id"]
    # Opened this time: no line. KOLONİ's line is the user's to read, never the Lead's.
    assert koloni(wait_run(client, cid, again)) == ["Reviewer was not opened this turn."]
    assert "not opened this turn" not in json.dumps(model.calls)


def test_a_role_merely_named_is_not_said_so_but_one_the_lead_says_it_asked_is(
    make_client, wait_run, project_dir
):
    # B-331: a list of roles, a could / will, is no claim; "I asked Tester to run it" is one.
    client, _model = make_client([
        text("You could use Coder, Data analyst or Debugger for that. Tester and Reviewer "
             "will check it; Reviewer has access."),
        text("I asked Tester to run it."),
    ])
    cid, run_id = begin(client, project_dir)

    def koloni(snap):
        return [m["content"] for m in snap["messages"] if m["role"] == "koloni"]

    assert koloni(wait_run(client, cid, run_id)) == []
    again = client.post(f"/api/conversations/{cid}/messages", json={"content": "again"},
                        headers={"Origin": "http://127.0.0.1:8790"}).json()["run"]["id"]
    assert koloni(wait_run(client, cid, again)) == ["Tester was not opened this turn."]


# --- the child loop -----------------------------------------------------------


def test_child_runs_with_a_clean_context_and_its_report_returns(
    make_client, wait_run, project_dir
):
    client, model = make_client([
        step(call("read_file", {"path": "hello.py"}), content="Looking."),
        spawn("Reviewer", "Review hello.py for bugs"),
        text("No problems found."),
        text("The reviewer is happy."),
    ])
    cid, run_id = begin(client, project_dir)
    snap = wait_run(client, cid, run_id)

    assert "Hand a part of the work" in model.calls[0][0]["content"]  # the Lead's instructions
    child = model.calls[2]
    assert [m["role"] for m in child] == ["system", "user"]
    assert "You are the Reviewer sub-agent" in child[0]["content"]
    assert "Say plainly when you find none" in child[0]["content"]
    assert "Your task comes from the Orchestrator (your opener)" in child[0]["content"]
    assert child[1]["content"] == "Review hello.py for bugs"
    assert "greeting" not in json.dumps(child) and "Looking." not in json.dumps(child)

    back = model.calls[3][-1]
    assert back["role"] == "tool"
    # (K-kanit: what it did, counted by KOLONİ - none of it, beside a report that claims nothing)
    assert back["content"] == ("Reviewer finished.\n\nNo problems found.\n\nWhat it did, from "
                               "KOLONİ's record: read 0 files, wrote 0, ran 0 commands, 0 web."
                               "\n\nKOLONİ: the task you gave "
                               "Reviewer is short (24 characters); its report may miss what you "
                               "meant - next time say the goal, what done looks like, the files, "
                               "what to leave alone, and the report you want.")

    lead, kid = snap["agents"]
    assert (lead["depth"], kid["depth"], kid["parent_agent_id"]) == (0, 1, lead["id"])
    assert (lead["status"], kid["status"]) == ("completed", "completed")
    assert (kid["role_name"], kid["task"], kid["report"]) == (
        "Reviewer", "Review hello.py for bugs", "No problems found.")
    assert kid["started_at"] and kid["ended_at"]
    assert [(m["kind"], m["from_agent_id"], m["to_agent_id"], m["content"])
            for m in snap["channel_messages"]] == [
        ("task", lead["id"], kid["id"], "Review hello.py for bugs"),
        ("report", kid["id"], lead["id"], "No problems found.\n\nWhat it did, from KOLONİ's "
                                          "record: read 0 files, wrote 0, ran 0 commands, 0 web."),
    ]
    spawned = next(t for t in snap["tool_calls"] if t["name"] == "spawn_agent")
    assert spawned["status"] == "succeeded" and spawned["agent_id"] == lead["id"]
    # the call that opened the sub-agent is on its record, so the chat can show it there
    assert (lead["tool_call_id"], kid["tool_call_id"]) == (None, spawned["id"])
    assert snap["messages"][-1]["content"] == "The reviewer is happy."


def test_child_tools_are_the_intersection(make_client, wait_run, project_dir):
    client, model = make_client([
        spawn("Reviewer"),
        step(call("write_file", {"path": "x.txt", "content": "x"})),
        text("done"),
        text("ok"),
    ])
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    assert names(model.tool_args[1]) == OFFERED_REVIEWER
    assert snap["agents"][1]["tools"] == REVIEWER
    written = next(t for t in snap["tool_calls"] if t["name"] == "write_file")
    assert written["status"] == "failed"
    assert "write_file is not available to the Reviewer role" in written["result"]
    assert not (project_dir / "x.txt").exists()


def test_a_grandchild_has_its_roles_tools_capped_by_the_orchestrators_not_its_openers(
    make_client, wait_run, project_dir
):
    # B-333: the Planner cannot write, the Coder it opens can; the Lead's lack still holds.
    client, model = make_client([
        spawn("Planner"), spawn("Coder", id="s2"), text("coded"), text("planned"), text("led")])
    lead_tools = next(r for r in client.get("/api/roles").json() if r["name"] == "Lead")["tools"]
    client.patch(f"/api/roles/{role_id(client, 'Lead')}",
                 json={"tools": [t for t in lead_tools if t != "run_command"]})
    cid, run_id = begin(client, project_dir, mode="auto_edit")
    snap = wait_run(client, cid, run_id)
    lead, planner, coder = snap["agents"]
    assert planner["tools"] == [
        *READ, "spawn_agent", "create_role", "ask_user", "ask_folder", "message_agent",
        "discuss", "propose_trigger", *NOTEBOOK, *MEMORY]
    assert coder["tools"] == [t for t in effective_tools(BUILTIN_ROLES["Coder"].tools, None)
                              if t != "run_command"]
    assert "write_file" in coder["tools"]
    assert (coder["depth"], coder["parent_agent_id"]) == (2, planner["id"])
    assert "Your task comes from the Planner" in model.calls[2][0]["content"]
    assert [a["status"] for a in snap["agents"]] == ["completed"] * 3


def test_a_coder_an_architect_opens_writes_the_file(make_client, wait_run, project_dir):
    client, _ = make_client([
        spawn("Architect"), spawn("Coder", id="s2"),
        step(call("write_file", {"path": "x.txt", "content": "x"}, "w1")),
        text("coded"), text("designed"), text("led")])
    cid, run_id = begin(client, project_dir, mode="full_auto",
                        content="Architect, design it and hand the code to a Coder")
    snap = wait_run(client, cid, run_id)
    assert [a["role_name"] for a in snap["agents"]] == ["Lead", "Architect", "Coder"]
    written = next(t for t in snap["tool_calls"] if t["name"] == "write_file")
    assert written["status"] == "succeeded", written["result"]
    assert (project_dir / "x.txt").read_text() == "x"


def test_editing_a_role_does_not_change_an_agent_already_opened(
    make_client, wait_run, project_dir
):
    client, model = make_client([spawn("Reviewer"), text("r"), text("l")])
    cid, run_id = begin(client, project_dir, spawn_approval="always")
    kid = wait_status(client, cid, "waiting_approval")["agents"][1]
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={"tools": ["read_file"]})
    assert client.post(f"/api/agents/{kid['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert snap["agents"][1]["tools"] == REVIEWER
    assert names(model.tool_args[1]) == OFFERED_REVIEWER


def test_unknown_role_and_empty_task_are_tool_errors(make_client, wait_run, project_dir):
    client, _ = make_client([
        step(call("spawn_agent", {"role": "Nobody", "task": "x"}, "a"),
             call("spawn_agent", {"role": "Reviewer", "task": "   "}, "b"),
             call("spawn_agent", {"role": "reviewer"}, "c")),
        text("ok"),
    ])
    cid, run_id = begin(client, project_dir)
    snap = wait_run(client, cid, run_id)
    unknown, empty, missing = snap["tool_calls"]
    assert unknown["status"] == empty["status"] == missing["status"] == "failed"
    assert "unknown role: Nobody" in unknown["result"] and "Reviewer" in unknown["result"]
    assert "task" in empty["result"] and "task" in missing["result"]
    assert len(snap["agents"]) == 1 and snap["channel_messages"] == []
    assert snap["runs"][0]["status"] == "completed"


def test_an_agent_s_name_given_as_a_role_points_to_message_agent(make_client, wait_run, project_dir):
    # R154 (live): the Lead opened "Coder 2" and was told only "unknown role".
    client, _ = make_client([spawn("Reviewer", id="s1"), text("r"), spawn("Reviewer", id="s2"), text("r2"),
                             spawn("reviewer  2", id="s3"), text("ok")])
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    status, said = snap["tool_calls"][-1]["status"], snap["tool_calls"][-1]["result"]
    assert status == "failed" and said == "error: Reviewer 2 is an agent of this turn, not a role: message_agent reaches it"


TEMP = os.path.join(tempfile.gettempdir(), "koloni-cli-j1y3vywd")
# (A folder of the user's that only has the name in it is no CLI's temp folder.)
TASK = f"Project folder: {TEMP}\nRead `{TEMP.upper() if os.name == 'nt' else TEMP}{os.sep}calc.py` and D:{os.sep}koloni-cli-notes{os.sep}x."
# B-137 (live, session mode): "In the project folder (C:\\Users\\Murat\\AppData\\Local\\Temp\\koloni-cli-…" -
# its slashes doubled, as JSON escapes them.
DOUBLED = f"\nIn the project folder: {TEMP.replace(os.sep, os.sep * 2)}{os.sep * 2}hello.py"


class CliLead(ScriptedModel):
    """A CLI session for every agent, as Claude Code's (`session`): the Lead opens a Reviewer."""

    session = True

    def __init__(self):
        super().__init__([])

    async def run_session(self, model_id, messages, tools, call_tool, on_text, on_message=None, effort=None,
                           on_live=None):
        if "Your name here is Reviewer" not in str(messages[0]["content"]):
            await call_tool("spawn_agent", json.dumps({"role": "Reviewer", "task": TASK + DOUBLED}))
        await on_text("done")
        return SimpleNamespace(input_tokens=5, output_tokens=1, model=None)


def test_a_cli_leads_temp_folder_in_a_task_is_the_folder_it_works_in(settings_env, make_client, wait_run, project_dir):
    # B-81 (live, CC-S haiku): "Project folder: …\Temp\koloni-cli-j1y3vywd" in the Coder's task. Made
    # relative - the project's own path would lead an agent working in a copy out of it.
    from app.config import load_settings
    from app.main import create_app
    from tests.keyed import TestClient
    with TestClient(create_app(load_settings(settings_env), model=CliLead()), base_url="http://127.0.0.1:8790") as client:
        cid, run_id = begin(client, project_dir)
        task = wait_run(client, cid, run_id)["agents"][1]["task"]
    assert task == f"Project folder: ./\nRead `calc.py` and D:{os.sep}koloni-cli-notes{os.sep}x.\nIn the project folder: hello.py"
    # Opened by KOLONİ's own loop, which runs in no temp folder, a task is as it was written.
    client, _ = make_client([spawn("Reviewer", TASK), text("read"), text("done")])
    cid, run_id = begin(client, project_dir)
    assert wait_run(client, cid, run_id)["agents"][1]["task"] == TASK


def test_a_role_is_found_whatever_its_case(make_client, wait_run, project_dir):
    client, _ = make_client([spawn("reviewer"), text("r"), text("l")])
    cid, run_id = begin(client, project_dir)
    assert wait_run(client, cid, run_id)["agents"][1]["role_name"] == "Reviewer"


# --- limits -------------------------------------------------------------------


def test_depth_limit(make_client, wait_run, project_dir):
    client, _ = make_client([
        spawn("Planner"), spawn("Researcher", id="s2"), text("planned"), text("led")])
    cid, run_id = begin(client, project_dir, spawn_max_depth=1)
    snap = wait_run(client, cid, run_id)
    refused = snap["tool_calls"][1]
    assert refused["status"] == "failed" and "depth limit" in refused["result"]
    assert len(snap["agents"]) == 2
    assert snap["runs"][0]["status"] == "completed"


def test_agent_count_limit_counts_the_whole_tree(make_client, wait_run, project_dir):
    client, _ = make_client([
        spawn("Planner"), spawn("Researcher", id="s2"), text("found"), text("planned"),
        spawn("Reviewer", id="s3"), text("led")])
    cid, run_id = begin(client, project_dir, spawn_max_agents=2)
    snap = wait_run(client, cid, run_id)
    refused = snap["tool_calls"][2]
    assert refused["status"] == "failed"
    assert "limit of 2 sub-agents per turn" in refused["result"]
    assert len(snap["agents"]) == 3
    assert snap["runs"][0]["status"] == "completed"


def test_a_role_with_no_usable_tools_cannot_be_spawned(make_client, wait_run, project_dir):
    client, _ = make_client([
        spawn("Reviewer"), spawn("Runner", id="s2"), text("reviewed"), text("led")])
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}",
                 json={"tools": [*READ, "spawn_agent"]})
    # (Capped by what the Orchestrator may hand on, B-333: the Lead runs nothing here.)
    lead_tools = next(r for r in client.get("/api/roles").json() if r["name"] == "Lead")["tools"]
    client.patch(f"/api/roles/{role_id(client, 'Lead')}",
                 json={"tools": [t for t in lead_tools if t != "run_command"]})
    created = client.post("/api/roles", json={"name": "Runner", "tools": ["run_command"]})
    assert created.status_code == 201
    cid, run_id = begin(client, project_dir)
    snap = wait_run(client, cid, run_id)
    refused = snap["tool_calls"][1]
    assert refused["status"] == "failed" and "no tools" in refused["result"]
    assert len(snap["agents"]) == 2


# --- approval -----------------------------------------------------------------


def test_auto_asks_only_when_it_matters(make_client, wait_run, project_dir):
    client, model = make_client([spawn("Coder"), text("c"), text("l")])
    cid, run_id = begin(client, project_dir, mode="ask")
    snap = wait_status(client, cid, "waiting_approval")
    kid = snap["agents"][1]
    assert kid["status"] == "proposed" and kid["started_at"] is None
    assert snap["channel_messages"][0]["kind"] == "task"
    assert len(model.calls) == 1  # the child has not been given to the model
    approved = client.post(f"/api/agents/{kid['id']}/approve")
    assert approved.status_code == 200 and approved.json()["status"] != "proposed"
    assert client.post(f"/api/agents/{kid['id']}/approve").status_code == 409
    assert wait_run(client, cid, run_id)["agents"][1]["status"] == "completed"

    client, _ = make_client([spawn("Reviewer"), text("r"), text("l")])
    cid, run_id = begin(client, project_dir, mode="ask")
    assert wait_run(client, cid, run_id)["agents"][1]["status"] == "completed"

    client, _ = make_client([spawn("Coder"), text("c"), text("l")])
    cid, run_id = begin(client, project_dir, mode="auto_edit")
    assert wait_run(client, cid, run_id)["agents"][1]["status"] == "completed"


def test_always_and_never(make_client, wait_run, project_dir):
    client, _ = make_client([spawn("Reviewer"), text("r"), text("l")])
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="always")
    kid = wait_status(client, cid, "waiting_approval")["agents"][1]
    client.post(f"/api/agents/{kid['id']}/approve")
    assert wait_run(client, cid, run_id)["agents"][1]["status"] == "completed"

    client, _ = make_client([spawn("Coder"), text("c"), text("l")])
    cid, run_id = begin(client, project_dir, mode="ask", spawn_approval="never")
    assert wait_run(client, cid, run_id)["agents"][1]["status"] == "completed"


def test_reject_returns_the_users_decision(make_client, wait_run, project_dir):
    client, model = make_client([spawn("Coder"), text("understood")])
    cid, run_id = begin(client, project_dir, mode="ask")
    kid = wait_status(client, cid, "waiting_approval")["agents"][1]
    rejected = client.post(f"/api/agents/{kid['id']}/reject")
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    snap = wait_run(client, cid, run_id)
    assert snap["agents"][1]["status"] == "rejected" and snap["agents"][1]["ended_at"]
    assert snap["tool_calls"][0]["status"] == "denied"
    assert "not a tool error" in snap["tool_calls"][0]["result"]
    assert len(model.calls) == 2  # lead, lead: nothing was run for the child
    assert [m["kind"] for m in snap["channel_messages"]] == ["task"]
    assert client.post("/api/agents/nope/approve").status_code == 404


# --- failure, waiting, stopping ----------------------------------------------


def test_child_failure_does_not_end_the_parent(make_client, wait_run, project_dir):
    client, model = make_client([
        spawn("Reviewer"), ModelUnavailable("model server unreachable: refused"),
        text("I could not get a review.")])
    cid, run_id = begin(client, project_dir)
    snap = wait_run(client, cid, run_id)
    lead, kid = snap["agents"]
    assert kid["status"] == "failed" and "refused" in kid["error"]
    assert (lead["status"], snap["runs"][0]["status"]) == ("completed", "completed")
    assert snap["tool_calls"][0]["status"] == "failed"
    assert model.calls[2][-1]["content"].startswith(
        "Reviewer failed: model server unreachable: refused")


# (test_child_step_limit: B-397 asks the user first - tests/test_b397.py)


def test_parent_waits_then_resumes(make_client, wait_run, project_dir, gate):
    client, _ = make_client([spawn("Reviewer"), gate.step(text("fine")), text("l")])
    cid, run_id = begin(client, project_dir)
    gate.wait_partial()
    snap = client.get(f"/api/conversations/{cid}").json()
    assert [a["status"] for a in snap["agents"]] == ["waiting", "running"]
    assert snap["runs"][0]["status"] == "running"
    gate.release()
    assert [a["status"] for a in wait_run(client, cid, run_id)["agents"]] == ["completed"] * 2


def test_stop_cancels_the_whole_tree(make_client, wait_run, project_dir, gate):
    executor = ScriptedExecutor([Script(["x\n"], hold=gate)])
    client, _ = make_client([
        spawn("Coder"), spawn("Tester", id="s2"),
        step(call("run_command", {"command": "pytest"}))], executor=executor)
    cid, run_id = begin(client, project_dir, mode="full_auto")
    for _ in range(250):
        snap = client.get(f"/api/conversations/{cid}").json()
        if snap["commands"] and snap["commands"][0]["status"] == "running":
            break
        time.sleep(0.02)
    assert [a["status"] for a in snap["agents"]] == ["waiting", "waiting", "running"]
    client.post(f"/api/runs/{run_id}/cancel")
    snap = wait_run(client, cid, run_id)
    assert snap["commands"][0]["status"] == "killed"
    assert snap["commands"][0]["agent_id"] == snap["agents"][2]["id"]
    assert [a["status"] for a in snap["agents"]] == ["cancelled"] * 3
    assert snap["runs"][0]["status"] == "cancelled"
    assert {t["status"] for t in snap["tool_calls"]} == {"interrupted"}


def test_stop_while_a_spawn_waits_for_approval(make_client, wait_run, project_dir):
    client, _ = make_client([spawn("Coder")])
    cid, run_id = begin(client, project_dir, mode="ask")
    kid = wait_status(client, cid, "waiting_approval")["agents"][1]
    client.post(f"/api/runs/{run_id}/cancel")
    snap = wait_run(client, cid, run_id)
    assert [a["status"] for a in snap["agents"]] == ["cancelled", "rejected"]
    assert client.post(f"/api/agents/{kid['id']}/approve").status_code == 409


def test_child_file_requests_use_the_same_cards(make_client, wait_run, project_dir):
    client, _ = make_client([
        spawn("Coder"), step(call("write_file", {"path": "n.txt", "content": "new\n"})),
        text("written"), text("l")])
    cid, run_id = begin(client, project_dir, mode="ask", spawn_approval="never")
    snap = wait_status(client, cid, "waiting_approval")
    change = snap["file_changes"][0]
    # Since slice 19b a child's change is made in its working copy, and the user is asked
    # once for all of them when its work is over (tests/test_copy_scenarios.py).
    assert change["status"] == "in_copy" and change["agent_id"] == snap["agents"][1]["id"]
    assert not (project_dir / "n.txt").exists()
    client.headers["Origin"] = "http://127.0.0.1:8790"
    assert client.post(f"/api/merges/{snap['merges'][0]['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert (project_dir / "n.txt").read_bytes() == b"new\n"
    assert snap["file_changes"][0]["status"] == "applied"


def test_a_bug_inside_a_child_fails_only_the_child(make_client, wait_run, project_dir):
    async def broken(on_delta):
        raise RuntimeError("boom")

    client, model = make_client([spawn("Reviewer"), broken, text("carrying on")])
    cid, run_id = begin(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert snap["agents"][1]["status"] == "failed" and "boom" in snap["agents"][1]["error"]
    assert snap["runs"][0]["status"] == "completed"
    # the lead's own spawn call was answered, not swept up as unfinished
    assert snap["tool_calls"][0]["status"] == "failed"
    assert "Reviewer failed: internal error" in snap["tool_calls"][0]["result"]


# --- history and tokens -------------------------------------------------------


def test_next_turn_history_excludes_sub_agent_transcripts(make_client, wait_run, project_dir):
    client, model = make_client([
        spawn("Reviewer", "look closely"),
        step(call("read_file", {"path": "hello.py"}), content="child thinking"),
        text("child report"),
        text("first answer"),
        text("second answer"),
    ])
    cid, run_id = begin(client, project_dir)
    wait_run(client, cid, run_id)
    second = client.post(f"/api/conversations/{cid}/messages", json={"content": "and now?"}).json()
    wait_run(client, cid, second["run"]["id"])

    history = model.calls[-1]
    # (the blocks before the new message are KOLONİ's record of the turn before, with what its
    # sub-agent read (K-gecmis-zengin), and its note of it: G7)
    assert [m["role"] for m in history] == [
        "system", "user", "assistant", "tool", "assistant", "user", "user", "user"]
    assert history[-3]["content"].endswith('- files read: "hello.py"')
    assert history[-2]["content"].endswith('- KOLONİ: "This turn is done. Done: Reviewer."')
    assert history[2]["tool_calls"][0]["function"]["name"] == "spawn_agent"
    assert reported(history[3]["content"]) == "Reviewer finished.\n\nchild report"
    assert "child thinking" not in json.dumps(history)
    assert "read_file" not in json.dumps(history[1:])


def test_tokens_are_kept_per_agent(make_client, wait_run, project_dir):
    client, _ = make_client([
        step(call("spawn_agent", {"role": "Reviewer", "task": "t"}), i=5, o=2),
        text("r", 7, 4), text("l", 9, 1)])
    cid, run_id = begin(client, project_dir)
    snap = wait_run(client, cid, run_id)
    lead, kid = snap["agents"]
    assert (lead["input_tokens"], lead["output_tokens"]) == (9, 3)
    assert (kid["input_tokens"], kid["output_tokens"]) == (7, 4)
    run = snap["runs"][0]
    assert (run["input_tokens"], run["output_tokens"]) == (9, 3)


# --- create_role --------------------------------------------------------------


def test_an_agent_creates_a_role_and_uses_it_in_the_same_turn(
    make_client, wait_run, project_dir
):
    client, model = make_client([
        new_role("  Documenter ", ["write_file", "read_file"], description="Writes the docs.",
                 instructions="Keep it short."),
        spawn("Documenter", "document hello.py"),
        text("documented"),
        text("all done"),
    ])
    cid, run_id = begin(client, project_dir, mode="auto_edit")
    snap = wait_run(client, cid, run_id)

    role = next(r for r in client.get("/api/roles").json() if r["name"] == "Documenter")
    assert role["created_by_agent"] is True and role["builtin"] is False
    assert (role["description"], role["instructions"]) == ("Writes the docs.", "Keep it short.")
    assert role["tools"] == ["read_file", "write_file"]
    created = snap["tool_calls"][0]
    assert created["status"] == "succeeded" and 'created role "Documenter"' in created["result"]

    def roles_offered(tools):
        return next(t for t in tools if t["function"]["name"] == "spawn_agent")[
            "function"]["description"]

    assert "Reviewer — Reviews changes" in roles_offered(model.tool_args[0])
    assert "Documenter" not in roles_offered(model.tool_args[0])
    assert "Documenter — Writes the docs." in roles_offered(model.tool_args[1])
    assert snap["agents"][1]["tools"] == ["read_file", "write_file"]
    assert "Keep it short." in model.calls[2][0]["content"]
    assert snap["pending_roles"] == []


def test_create_role_refuses_a_taken_name_and_unknown_tools(make_client, wait_run, project_dir):
    client, _ = make_client([
        step(call("create_role", {"name": "reviewer", "tools": ["read_file"]}, "a"),
             call("create_role", {"name": "Pilot", "tools": ["fly"]}, "b"),
             call("create_role", {"name": "Idle", "tools": []}, "c"),
             call("create_role", {"name": " ", "tools": ["read_file"]}, "d")),
        text("ok"),
    ])
    cid, run_id = begin(client, project_dir, mode="auto_edit")
    taken, unknown, empty, nameless = wait_run(client, cid, run_id)["tool_calls"]
    assert {taken["status"], unknown["status"], empty["status"], nameless["status"]} == {"failed"}
    assert "already a role named Reviewer" in taken["result"]
    assert "unknown tool: fly" in unknown["result"]
    assert "at least one tool" in empty["result"]
    assert "name" in nameless["result"]
    assert len(client.get("/api/roles").json()) == BUILT_IN


def test_create_role_asks_first_in_ask_mode(make_client, wait_run, project_dir):
    client, _ = make_client([
        new_role("Documenter", ["read_file", "write_file"], description="Docs."), text("made")])
    cid, run_id = begin(client, project_dir, mode="ask")
    snap = wait_status(client, cid, "waiting_approval")
    assert all(r["name"] != "Documenter" for r in client.get("/api/roles").json())
    pending = snap["pending_roles"]
    call_id = snap["tool_calls"][0]["id"]
    assert pending == [{
        "tool_call_id": call_id, "run_id": run_id, "agent_id": snap["agents"][0]["id"],
        "name": "Documenter", "description": "Docs.", "instructions": "",
        "tools": ["read_file", "write_file"], "knowledge": None}]
    assert client.post("/api/tool-calls/nope/approve").status_code == 404
    assert client.post(f"/api/tool-calls/{call_id}/approve").status_code == 200
    assert client.post(f"/api/tool-calls/{call_id}/approve").status_code == 409
    snap = wait_run(client, cid, run_id)
    assert any(r["name"] == "Documenter" for r in client.get("/api/roles").json())
    assert snap["pending_roles"] == [] and snap["tool_calls"][0]["status"] == "succeeded"


def test_rejecting_a_role_creates_nothing(make_client, wait_run, project_dir):
    client, _ = make_client([new_role("Documenter", ["read_file"]), text("fine")])
    cid, run_id = begin(client, project_dir, mode="ask")
    snap = wait_status(client, cid, "waiting_approval")
    client.post(f"/api/tool-calls/{snap['tool_calls'][0]['id']}/reject")
    snap = wait_run(client, cid, run_id)
    assert snap["tool_calls"][0]["status"] == "denied"
    assert "not a tool error" in snap["tool_calls"][0]["result"]
    assert len(client.get("/api/roles").json()) == BUILT_IN and snap["pending_roles"] == []


def test_stopping_while_a_role_waits_creates_nothing(make_client, wait_run, project_dir):
    client, _ = make_client([new_role("Documenter", ["read_file"])])
    cid, run_id = begin(client, project_dir, mode="ask")
    snap = wait_status(client, cid, "waiting_approval")
    client.post(f"/api/runs/{run_id}/cancel")
    after = wait_run(client, cid, run_id)
    assert after["pending_roles"] == [] and len(client.get("/api/roles").json()) == BUILT_IN
    call_id = snap["tool_calls"][0]["id"]
    assert client.post(f"/api/tool-calls/{call_id}/approve").status_code == 409


def test_a_role_without_create_role_cannot_create_roles(make_client, wait_run, project_dir):
    client, _ = make_client([
        spawn("Coder"), new_role("Helper", ["read_file"]), text("c"), text("l")])
    cid, run_id = begin(client, project_dir, mode="auto_edit")
    snap = wait_run(client, cid, run_id)
    refused = snap["tool_calls"][1]
    assert refused["status"] == "failed"
    assert "create_role is not available to the Coder role" in refused["result"]
    assert len(client.get("/api/roles").json()) == BUILT_IN


def test_a_created_role_cannot_grant_more_than_the_orchestrator_has(
    make_client, wait_run, project_dir
):
    everything = [*READ, "write_file", "edit_file", "run_command", "spawn_agent", "create_role"]
    client, _ = make_client([
        spawn("Reviewer"), new_role("Omni", everything), spawn("Omni", id="s2"),
        text("o"), text("r"), text("l")])
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}",
                 json={"tools": [*READ, "spawn_agent", "create_role"]})
    lead_tools = next(r for r in client.get("/api/roles").json() if r["name"] == "Lead")["tools"]
    client.patch(f"/api/roles/{role_id(client, 'Lead')}", json={"tools": [
        t for t in lead_tools if t not in ("write_file", "edit_file", "run_command")]})
    cid, run_id = begin(client, project_dir, mode="auto_edit")
    snap = wait_run(client, cid, run_id)
    omni = snap["agents"][2]
    assert omni["role_name"] == "Omni"
    assert omni["tools"] == [*READ, "spawn_agent", "create_role"]


# --- review fixes -------------------------------------------------------------


def test_a_completed_child_reports_only_its_final_answer(make_client, wait_run, project_dir):
    # Narration from an earlier step is not a report: the child ended without one.
    client, model = make_client([
        spawn("Reviewer"),
        step(call("read_file", {"path": "hello.py"}), content="Let me read the file."),
        text(""),
        text("ok"),
    ])
    cid, run_id = begin(client, project_dir)
    snap = wait_run(client, cid, run_id)
    kid = snap["agents"][1]
    assert (kid["status"], kid["report"]) == ("completed", None)
    assert reported(model.calls[-1][-1]["content"]) == "Reviewer finished.\n\n(it ended without a report)"
    assert "Let me read the file." not in snap["channel_messages"][-1]["content"]


def test_a_failed_child_still_says_how_far_it_got(make_client, wait_run, project_dir):
    client, model = make_client([
        spawn("Reviewer"),
        step(call("read_file", {"path": "hello.py"}), content="Halfway there."),
        ModelUnavailable("model server unreachable: refused"),
        text("ok"),
    ])
    cid, run_id = begin(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert snap["agents"][1]["report"] == "Halfway there."
    assert "What it said last:\nHalfway there." in model.calls[-1][-1]["content"]


def test_a_rejected_sub_agent_does_not_use_up_the_limit(make_client, wait_run, project_dir):
    client, _ = make_client([spawn("Reviewer"), spawn("Reviewer", id="s2"), text("r"), text("l")])
    cid, run_id = begin(client, project_dir, spawn_approval="always", spawn_max_agents=1)
    kid = wait_status(client, cid, "waiting_approval")["agents"][1]
    client.post(f"/api/agents/{kid['id']}/reject")
    for _ in range(250):
        agents = client.get(f"/api/conversations/{cid}").json()["agents"]
        if len(agents) == 3 and agents[2]["status"] == "proposed":
            break
        time.sleep(0.02)
    client.post(f"/api/agents/{agents[2]['id']}/approve")
    snap = wait_run(client, cid, run_id)
    assert [a["status"] for a in snap["agents"]] == ["completed", "rejected", "completed"]


def test_stop_while_a_child_change_waits_settles_everything(make_client, wait_run, project_dir):
    # Since slice 19b the child's change waits in its working copy, asked about when its
    # work is over: the child is done by then, and Stop keeps its copy for the user (6 Nov).
    client, _ = make_client([
        spawn("Coder"), step(call("write_file", {"path": "n.txt", "content": "new\n"})),
        text("written")])
    cid, run_id = begin(client, project_dir, mode="ask", spawn_approval="never")
    wait_status(client, cid, "waiting_approval")
    client.post(f"/api/runs/{run_id}/cancel")
    snap = wait_run(client, cid, run_id)
    assert snap["file_changes"][0]["status"] == "in_copy"       # nobody rejected it
    assert [m["status"] for m in snap["merges"]] == ["kept"]
    assert [a["status"] for a in snap["agents"]] == ["cancelled", "completed"]
    assert {t["name"]: t["status"] for t in snap["tool_calls"]} == {
        "spawn_agent": "interrupted", "write_file": "succeeded"}
    assert not (project_dir / "n.txt").exists()


def test_a_sub_agents_role_request_waits_under_its_own_name(make_client, wait_run, project_dir):
    client, _ = make_client([
        spawn("Planner"), new_role("Documenter", ["read_file"]), text("planned"), text("led")])
    cid, run_id = begin(client, project_dir, mode="ask")
    snap = wait_status(client, cid, "waiting_approval")
    planner = snap["agents"][1]
    assert [r["agent_id"] for r in snap["pending_roles"]] == [planner["id"]]
    client.post(f"/api/tool-calls/{snap['pending_roles'][0]['tool_call_id']}/approve")
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    assert any(r["name"] == "Documenter" for r in client.get("/api/roles").json())


def test_a_folder_in_a_task_is_made_relative_only_where_it_is_that_folder_whole():
    # (The review of B-129, S5: proj.bak was cut, /mnt/home/u/proj rewritten, and proj/../x led out.)
    from app.agent import _path_in_text, _relative
    proj = os.path.join("C:" if os.name == "nt" else "/", "work", "proj")
    found = _path_in_text(proj)
    sep = os.sep
    assert _relative(f"Edit {proj}{sep}a.py, see `{proj}`", found) == "Edit a.py, see `./`"
    assert _relative(f"Keep {proj}.bak and {proj}-2", found) == f"Keep {proj}.bak and {proj}-2"
    assert _relative(f"Not x{proj}{sep}a.py", found) == f"Not x{proj}{sep}a.py"
    assert _relative(f"Up {proj}{sep}..{sep}x", found) == f"Up {proj}{sep}..{sep}x"


def test_a_thin_task_is_judged_by_its_length_and_what_it_names():
    # K-brief-kalitesi: short, or naming no file nor part and no report or check.
    from app.agent import thin_task
    assert thin_task("Review hello.py for bugs") == "short (24 characters)"
    assert thin_task("Look at the whole thing and do what seems right to you") == (
        "short (54 characters) and names no file or check")
    long = "Go through the greeting and make it friendlier for a first-time visitor. " * 3
    assert thin_task(long) == "names no file or check"
    assert thin_task(long + "Tell me what you changed.") is None
    assert thin_task(long + "It lives in src/greeting.py.") is None
    assert thin_task(long + "Work in ./ only.") is None
    assert thin_task(long, names_part=True) is None


def test_a_task_naming_the_copy_and_the_project_says_them_two_ways():
    # B-159 (live): "Project folder: ./ is NOT the project; … (the project is ./ …)" - both made "./".
    from app.agent import CLI_TEMP, _path_in_text, _said_from_here
    base = "C:" if os.name == "nt" else "/"
    proj, copy = os.path.join(base, "work", "proj"), os.path.join(base, "runtime", "copies", "a1", "tree")
    in_copy = [(_path_in_text(copy), "./"), (_path_in_text(proj), "the project folder"),
               (CLI_TEMP, "the caller's own temp folder")]
    said = _said_from_here(
        f"Project folder: {copy} is NOT the project; edit README.md (the project is {proj} itself).",
        in_copy)
    assert said == ("Project folder: ./ is NOT the project; edit README.md "
                    "(the project is the project folder itself).")
    assert proj not in said
    # The project named alone is still where the agent works (B-129), and a file under it relative.
    assert _said_from_here(f"Fix {proj}{os.sep}a.py in {proj}", in_copy) == "Fix a.py in ./"
    # (The review: in a command the project beside the copy stays a folder to run in, "./" - never words.)
    assert _said_from_here(f"Work in {copy}; then cd {proj} && npm test, or `npm --prefix {proj} test`.",
                           in_copy) == "Work in ./; then cd ./ && npm test, or `npm --prefix ./ test`."
    # A CLI's temp folder beside the project (the Docs lead's "./ hayır, ./"): the project is "./".
    temp = os.path.join(tempfile.gettempdir(), "koloni-cli-j1y3vywd")
    assert _said_from_here(f"Proje klasörü: {temp} hayır, proje klasörü: {proj}", [
        (_path_in_text(proj), "the project folder"), (CLI_TEMP, "the caller's own temp folder")]) == (
        "Proje klasörü: the caller's own temp folder hayır, proje klasörü: ./")


def test_line_breaks_a_model_wrote_out_are_real_ones():
    # B-352 (live): a Lead's task read "...before judging.\n\nYour job: ..." in Talk.
    from app.agent import _lines_written_out
    assert _lines_written_out(r"Read it before judging.\n\nYour job:\n- review") == (
        "Read it before judging.\n\nYour job:\n- review")
    # A path's stays: before a small letter, after a backslash (JSON-escaped); and a real break.
    assert _lines_written_out(r"Fix C:\notes\a.py.\n\nThen C:\\node_modules") == (
        "Fix C:\\notes\\a.py.\n\nThen C:\\\\node_modules")
    assert _lines_written_out(r"Fix C:\notes\Next.py") == r"Fix C:\notes\Next.py"
    assert _lines_written_out("Two\nlines\\n\\nNo") == "Two\nlines\\n\\nNo"


def test_a_task_with_its_breaks_written_out_reaches_the_child_and_talk_with_real_ones(
    make_client, wait_run, project_dir
):
    client, model = make_client([
        spawn("Reviewer", r"Read hello.py before judging.\n\nYour job: review it for bugs."),
        text("No problems found."),
        text("Done."),
    ])
    cid, run_id = begin(client, project_dir)
    snap = wait_run(client, cid, run_id)
    task = "Read hello.py before judging.\n\nYour job: review it for bugs."
    assert model.calls[1][1]["content"] == task
    assert snap["channel_messages"][0]["content"] == task


# --- B-387: Codex's own tools, off in step mode ------------------------------------

REFUSED = "File reads were blocked because the tool host returned 'code-mode host is disabled'."


def test_an_end_saying_codex_s_own_tools_were_refused_is_told_once_to_use_koloni_s(
        make_client, wait_run, project_dir):
    from app.agent import CODEX_TOOLS_OFF
    client, model = make_client({
        "Lead": [spawn("Reviewer"), text("Reviewed.")],
        "Reviewer": [text(REFUSED), step(call("list_dir", {})), text("No problems found.")]})
    model.command = "codex"  # (a Codex step client's; any other model is not told)
    cid, run_id = begin(client, project_dir)
    _lead, kid = wait_run(client, cid, run_id)["agents"]
    assert (kid["status"], kid["report"]) == ("completed", "No problems found.")
    assert model.calls_of["Reviewer"][1][-1] == {"role": "user", "content": CODEX_TOOLS_OFF}


def tried(*calls, content=""):
    """A Codex step whose stderr said its own tool was refused (`CodexCliClient.REFUSED`)."""
    return StepResult(content, list(calls), 5, 2, own_tools_refused=True)


def test_a_step_codex_s_own_tools_were_refused_in_is_told_once_and_goes_on(
        make_client, wait_run, project_dir):
    from app.agent import CODEX_TOOLS_OFF
    client, model = make_client({
        "Lead": [spawn("Reviewer"), text("Reviewed.")],
        "Reviewer": [tried(call("list_dir", {})), tried(call("list_dir", {}, "c2")),
                     text("No problems found.")]})
    cid, run_id = begin(client, project_dir)
    _lead, kid = wait_run(client, cid, run_id)["agents"]
    # (tried again, but with KOLONİ's tools asked for: it goes on, told once)
    assert (kid["status"], kid["report"]) == ("completed", "No problems found.")
    told = [m for one in model.calls_of["Reviewer"] for m in one if m["content"] == CODEX_TOOLS_OFF]
    assert len(model.calls_of["Reviewer"][1]) > 2 and told and all(m == told[0] for m in told)
    assert sum(m["content"] == CODEX_TOOLS_OFF for m in model.calls_of["Reviewer"][-1]) == 1


def test_an_agent_that_used_koloni_s_tools_may_quote_the_words(make_client, wait_run, project_dir):
    client, model = make_client({
        "Lead": [spawn("Reviewer"), text("Reviewed.")],
        "Reviewer": [step(call("list_dir", {})), text(REFUSED)]})
    model.command = "codex"
    cid, run_id = begin(client, project_dir)
    _lead, kid = wait_run(client, cid, run_id)["agents"]
    assert (kid["status"], kid["report"]) == ("completed", REFUSED)


def test_a_lead_told_may_answer_from_what_it_knows(make_client, wait_run, project_dir):
    client, _model = make_client([tried(), text("Hello from what I know.")])
    cid, run_id = begin(client, project_dir)
    (lead,) = wait_run(client, cid, run_id)["agents"]
    assert lead["status"] == "completed"


FAILED = ("could not work: Codex kept trying its own tools, which are off in step mode. Try "
          "running Codex as One session per agent (Models › Codex › How it runs).")


def test_three_steps_in_a_row_that_tried_codex_s_own_tools_fail(make_client, wait_run, project_dir):
    from app.agent import CODEX_TOOLS_OFF
    client, model = make_client({
        "Lead": [spawn("Reviewer"), text("It could not.")],
        "Reviewer": [tried(call("list_dir", {})), tried(content="I could not read the files."),
                     tried(), tried()]})
    cid, run_id = begin(client, project_dir)
    _lead, kid = wait_run(client, cid, run_id)["agents"]
    assert (kid["status"], kid["error"]) == ("failed", FAILED)
    # (tried again, told again: the third in a row with no call of KOLONİ's ends it)
    assert len(model.calls_of["Reviewer"]) == 4
    assert sum(m["content"] == CODEX_TOOLS_OFF for m in model.calls_of["Reviewer"][-1]) == 3


@pytest.mark.parametrize("asks", [step(call("list_dir", {})), tried(call("list_dir", {}))])
def test_a_step_with_a_call_of_koloni_s_starts_the_count_anew(asks, make_client, wait_run, project_dir):
    client, model = make_client({
        "Lead": [spawn("Reviewer"), text("Reviewed.")],
        "Reviewer": [tried(), tried(), asks, tried(), tried(), text("No problems found.")]})
    cid, run_id = begin(client, project_dir)
    _lead, kid = wait_run(client, cid, run_id)["agents"]
    # (a refused step that asked for KOLONİ's tools too is no try counted)
    assert (kid["status"], kid["report"]) == ("completed", "No problems found.")


@pytest.mark.parametrize("then", [REFUSED, "I could not read the files."])
def test_said_again_or_no_tool_used_after_it_counts_as_a_try(then, make_client, wait_run, project_dir):
    client, model = make_client({
        "Lead": [spawn("Reviewer"), text("It could not.")],
        "Reviewer": [text(REFUSED), text(then), text(then)]})
    model.command = "codex"
    cid, run_id = begin(client, project_dir)
    _lead, kid = wait_run(client, cid, run_id)["agents"]
    assert (kid["status"], kid["error"]) == ("failed", FAILED)


def test_told_to_go_on_in_the_same_turn_its_tries_start_anew(make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [spawn("Reviewer"),
                 step(call("message_agent", {"to": "Reviewer", "message": "go on"}, "m1")),
                 text("Reviewed.")],
        "Reviewer": [step(call("list_dir", {})), tried(), tried(), text("First look."),
                     tried(), text("Second look.")]})
    cid, run_id = begin(client, project_dir)
    _lead, kid = wait_run(client, cid, run_id)["agents"]
    # (its two tries of the job before are not its job's now: the third would have failed it)
    assert (kid["status"], kid["report"]) == ("completed", "Second look.")


def test_an_answer_with_no_call_of_koloni_s_is_no_try(make_client, wait_run, project_dir):
    client, model = make_client({
        "Lead": [spawn("Reviewer"), spawn("Coder", id="s2"), text("done")],
        "Reviewer": [tried(), tried(), tried(), text("It looked fine.")],
        "Coder": [step(call("message_agent", {"to": "Reviewer", "message": "How was it?"}, "m1")),
                  text("coded")]})
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["agents"][1]["error"] == FAILED  # (told, and with no call of KOLONİ's)
    assert model.calls_of["Coder"][1][-1]["content"] == "Reviewer replied:\n\nIt looked fine."


def test_tries_cost_steps_and_a_streak_ends_at_the_step_limit(make_client, wait_run, project_dir):
    client, _model = make_client([tried(), tried(), step(call("list_dir", {})), tried(), tried()])
    # (B-413: the Orchestrator's step limit is only one the user set - its role's)
    assert client.patch(f"/api/roles/{role_id(client, 'Lead')}", json={"max_steps": 4},
                        headers={"Origin": "http://127.0.0.1:8790"}).status_code == 200
    cid, run_id = begin(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert (snap["runs"][0]["status"], snap["runs"][0]["error"]) == (
        "failed", "stopped at its role's limit of 4 steps")
