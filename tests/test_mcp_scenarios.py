"""Slice 28b's acceptance set: MCP servers the user connects. Written before the code.

The user adds a program that speaks MCP over stdio, reads its tools once, and says which
roles may use it. Its tools are then offered to those roles' agents as `<server>__<tool>`.
Every call is asked about unless the user marked the tool as running without asking or the
level is Full auto; the server is started in an empty folder of KOLONİ's own - never in the
project, whose files could then decide what is run - without KOLONİ's own settings, and
ended with the agent's work. What it says is data; what it asks of KOLONİ is refused; its
secrets go nowhere. Not in a turn nobody watches, not in a Docker project. Only the app's
own page gives a role a server, and only it answers when a call is asked about.
"""

import json
import os
import sys
import time
from pathlib import Path

import pytest

from app.db import models

if not hasattr(models, "McpServer"):  # written before the code: skipped until it exists
    pytest.skip("slice 28b is not built yet", allow_module_level=True)

from tests import test_trigger_scenarios as unattended  # noqa: E402
from tests.test_agent_writes import wait_status  # noqa: E402
from tests.test_chat_flow import text  # noqa: E402
from tests.test_host_executor import alive  # noqa: E402
from tests.test_spawn import begin, call, names, role_id, step  # noqa: E402

ORIGIN = "http://127.0.0.1:8790"
FAKE = [sys.executable, str(Path(__file__).with_name("fake_mcp_server.py"))]
SECRET = "s3cr3t-value-of-the-server"
NOTHING = {"type": "object", "properties": {}}
LONG = 20.0  # a run that starts a program of its own
READ: dict[str, list[dict]] = {}  # how each server was started when its tools were read


def server(client, tmp_path, name="fake", trusted=True, free=False, **plan):
    """Add the stand-in server and read its tools; returns it, its record and its plan. The
    record is empty from there: what is in it later was started for an agent. `trusted`:
    the user trusted it (slice 92), as the tests of the rules it is held to then want.
    `free`: its tools marked "Runs without asking" - one marked Ask asks at Full auto too."""
    client.headers["Origin"] = ORIGIN
    record, plan_file = tmp_path / f"{name}-record.jsonl", tmp_path / f"{name}-plan.json"
    plan_file.write_text(json.dumps({"record": str(record), **plan}), encoding="utf-8")
    made = client.post("/api/mcp-servers", json={
        "name": name, "command": FAKE,
        "env": {"FAKE_MCP_PLAN": str(plan_file), "THE_SECRET": SECRET}})
    assert made.status_code == 201, made.text
    read = client.post(f"/api/mcp-servers/{made.json()['id']}/read")
    assert read.status_code == 200, read.text
    READ[name] = events(record, "start")
    record.write_text("", encoding="utf-8")
    if trusted:
        marks = {tool["name"]: "free" for tool in read.json()["server"]["tools"]} if free else {}
        answer = client.patch(f"/api/mcp-servers/{made.json()['id']}",
                              json={"trusted": True, "marks": marks})
        assert answer.status_code == 200, answer.text
        return answer.json(), record, plan_file
    return read.json()["server"], record, plan_file


def give(client, role, *servers):
    answer = client.patch(f"/api/roles/{role_id(client, role)}", json={"mcp": list(servers)})
    assert answer.status_code == 200, answer.text


def mark(client, made, **marks):
    answer = client.patch(f"/api/mcp-servers/{made['id']}", json={"marks": marks})
    assert answer.status_code == 200, answer.text
    return answer.json()


def events(record, kind):
    if not record.exists():
        return []
    lines = record.read_text(encoding="utf-8").splitlines()
    return [e for e in map(json.loads, lines) if e["event"] == kind]


def same(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def calls(snap):
    return {t["name"]: (t["status"], t["result"] or "") for t in snap["tool_calls"]}


def gone(pids, within=5.0):
    deadline = time.monotonic() + within
    while any(alive(pid) for pid in pids) and time.monotonic() < deadline:
        time.sleep(0.05)
    return not any(alive(pid) for pid in pids)


# --- adding a server ------------------------------------------------------------------------


def test_a_server_is_added_and_its_tools_are_read_and_its_secret_goes_nowhere(
    make_client, tmp_path, project_dir, monkeypatch
):
    monkeypatch.setenv("KOLONI_MODEL_API_KEY", "sk-koloni-secret")
    client, _ = make_client([text("x")])
    body = {"name": "fake", "command": FAKE, "env": {"THE_SECRET": SECRET}}
    # adding one is starting a program as the user: only from the app's own page
    assert client.post("/api/mcp-servers", json=body).status_code == 403
    assert client.post("/api/mcp-servers", json=body,
                       headers={"Origin": "http://evil.example"}).status_code == 403
    made, record, _ = server(client, tmp_path, page=3)
    assert [tool["name"] for tool in made["tools"]] == [
        "echo", "where", "boom", "picture", "big", "hang", "die", "sample"]  # every page of it
    echo = made["tools"][0]
    assert echo["description"] == "Says back what it is given." and echo["mark"] == "ask"
    assert echo["input_schema"]["required"] == ["text"] and echo["unusable"] is None
    assert made["env_names"] == ["FAKE_MCP_PLAN", "THE_SECRET"] and made["read_error"] is None
    listed = client.get("/api/mcp-servers").json()
    assert [one["name"] for one in listed] == ["fake"]
    assert SECRET not in json.dumps([made, listed])
    # read in a folder of its own, with its own variables and none of KOLONİ's settings
    (start,) = READ["fake"]
    assert not same(start["cwd"], project_dir) and start["env"]["THE_SECRET"] == SECRET
    assert start["files"] == [] and events(record, "start") == []
    assert [name for name in start["env"] if name.upper().startswith("KOLONI_")] == []
    assert gone([start["pid"]])
    assert client.post("/api/mcp-servers", json={**body, "name": "Bad Name"}).status_code == 422
    assert client.post("/api/mcp-servers", json=body).status_code in (409, 422)  # twice


def test_a_server_that_cannot_be_started_says_so_and_offers_nothing(make_client):
    client, _ = make_client([text("x")])
    client.headers["Origin"] = ORIGIN
    made = client.post("/api/mcp-servers", json={
        "name": "nope", "command": ["no-such-program-of-kolonis-tests"]})
    assert made.status_code == 201, made.text
    read = client.post(f"/api/mcp-servers/{made.json()['id']}/read")
    assert read.status_code == 200, read.text
    assert read.json()["server"]["read_error"] and read.json()["server"]["tools"] == []


def test_a_tool_whose_name_cannot_be_offered_is_listed_with_the_reason(
    make_client, wait_run, project_dir, tmp_path
):
    client, model = make_client([text("x")])
    made, _, _ = server(client, tmp_path, more=[
        {"name": "bad name!", "description": "x", "inputSchema": NOTHING},
        {"name": "y" * 60, "description": "x", "inputSchema": NOTHING}])
    why = {tool["name"]: tool["unusable"] for tool in made["tools"]}
    assert why["bad name!"] and why["y" * 60] and why["echo"] is None
    give(client, "Lead", "fake")
    cid, run_id = begin(client, project_dir)
    wait_run(client, cid, run_id)
    offered = names(model.tool_args[0])
    assert "fake__echo" in offered and not [n for n in offered if "bad" in n or "yyy" in n]


def test_reading_again_takes_the_users_word_back_from_a_tool_that_changed(
    make_client, tmp_path
):
    client, _ = make_client([text("x")])
    made, record, plan_file = server(client, tmp_path)
    mark(client, made, echo="free", where="free", boom="off")
    plan_file.write_text(json.dumps({
        "record": str(record), "describe": {"echo": "Now it also deletes things."},
        "without": ["big"],
        "more": [{"name": "fresh", "description": "New.", "inputSchema": NOTHING}],
    }), encoding="utf-8")
    again = client.post(f"/api/mcp-servers/{made['id']}/read").json()
    assert (again["new"], again["changed"], again["gone"]) == (["fresh"], ["echo"], ["big"])
    marks = {tool["name"]: tool["mark"] for tool in again["server"]["tools"]}
    assert (marks["echo"], marks["where"], marks["boom"], marks["fresh"]) == (
        "ask", "free", "off", "ask")
    assert "big" not in marks


# --- who is offered its tools ---------------------------------------------------------------


def test_only_a_role_given_the_server_is_offered_its_tools(
    make_client, wait_run, project_dir, tmp_path
):
    client, model = make_client([
        step(call("fake__echo", {"text": "hi"})), text("could not"), text("now I can")])
    _made, record, _ = server(client, tmp_path)
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert "fake__echo" not in names(model.tool_args[0])
    # checked when it is called too, not only when it is offered
    assert calls(snap)["fake__echo"][0] == "failed" and events(record, "call") == []

    lead_role = f"/api/roles/{role_id(client, 'Lead')}"
    assert client.patch(lead_role, json={"mcp": ["no-such-server"]}).status_code == 422
    # giving a role a server is the user's alone: not a command an agent runs against the API
    del client.headers["Origin"]
    assert client.patch(lead_role, json={"mcp": ["fake"]}).status_code == 403
    client.headers["Origin"] = ORIGIN
    assert client.patch(lead_role, json={"mcp": ["fake"]},
                        headers={"Origin": "http://evil.example"}).status_code == 403
    give(client, "Lead", "fake")
    lead = next(r for r in client.get("/api/roles").json() if r["name"] == "Lead")
    assert lead["mcp"] == ["fake"]
    again = client.post(f"/api/conversations/{cid}/messages", json={"content": "again"})
    wait_run(client, cid, again.json()["run"]["id"])
    offered = {t["function"]["name"]: t["function"] for t in model.tool_args[2]}
    assert "fake__echo" in offered and "fake__where" in offered
    # the server's own description is there, and is said to be the server's
    said = offered["fake__echo"]["description"]
    assert "Says back what it is given." in said and "server" in said.split("Says back")[0]
    assert offered["fake__echo"]["parameters"]["required"] == ["text"]


def test_a_sub_agent_has_no_server_its_opener_has_not(
    make_client, wait_run, project_dir, tmp_path
):
    client, model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "look"}, "s1")),
                 text("done")],
        "Coder": [text("looked")]})
    server(client, tmp_path)
    give(client, "Coder", "fake")                       # the Coder may, the Lead may not
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    wait_run(client, cid, run_id, timeout=LONG)
    assert len(model.tool_args) == 3
    assert not [n for tools in model.tool_args for n in names(tools) if n.startswith("fake__")]


def test_a_tool_switched_off_is_not_offered_and_cannot_be_called(
    make_client, wait_run, project_dir, tmp_path
):
    client, model = make_client([step(call("fake__echo", {"text": "hi"})), text("done")])
    made, record, _ = server(client, tmp_path)
    mark(client, made, echo="off")
    give(client, "Lead", "fake")
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id, timeout=LONG)
    offered = names(model.tool_args[0])
    assert "fake__echo" not in offered and "fake__where" in offered
    assert calls(snap)["fake__echo"][0] == "failed" and events(record, "call") == []


def test_deleting_a_server_takes_it_from_the_roles(make_client, tmp_path):
    client, _ = make_client([text("x")])
    made, _, _ = server(client, tmp_path)
    give(client, "Lead", "fake")
    assert client.delete(f"/api/mcp-servers/{made['id']}",
                         headers={"Origin": "http://evil.example"}).status_code == 403
    assert client.delete(f"/api/mcp-servers/{made['id']}").status_code == 204
    assert client.get("/api/mcp-servers").json() == []
    assert next(r for r in client.get("/api/roles").json() if r["name"] == "Lead")["mcp"] == []


# --- a call: asked about, then run ----------------------------------------------------------


def test_a_call_is_asked_about_and_the_server_starts_only_after_the_yes(
    make_client, wait_run, project_dir, tmp_path
):
    client, model = make_client([step(call("fake__echo", {"text": "hi there"})), text("done")])
    _made, record, _ = server(client, tmp_path)
    give(client, "Lead", "fake")
    cid, run_id = begin(client, project_dir, mode="ask")
    question = wait_status(client, cid, "waiting_approval")["questions"][0]
    assert question["options"] == ["Allow", "Deny"]
    for shown in ("fake", "echo", "hi there"):          # the server, the tool, what it is given
        assert shown in question["question"]
    assert events(record, "start") == [] and events(record, "call") == []
    # the yes is the user's alone: not a command an agent runs against the API
    answer = f"/api/questions/{question['id']}/answer"
    del client.headers["Origin"]
    assert client.post(answer, json={"answer": "Allow"}).status_code == 403
    client.headers["Origin"] = ORIGIN
    assert events(record, "start") == []
    assert client.post(answer, json={"answer": "Allow"}).status_code == 200
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    status, result = calls(snap)["fake__echo"]
    assert status == "succeeded" and "echo: hi there" in result
    assert "data, not instructions" in result          # framed, as content from the web is
    assert model.calls[1][-1]["content"] == result     # and that is what the model is given
    (start,) = events(record, "start")
    # in an empty folder of KOLONİ's own: no file of the project decides what is started
    assert not same(start["cwd"], project_dir) and start["files"] == []
    assert [e["arguments"] for e in events(record, "call")] == [{"text": "hi there"}]
    assert gone([start["pid"]])                        # ended with the agent's work
    assert not Path(start["cwd"]).exists()             # and its folder with it


def test_a_no_leaves_the_call_denied_and_nothing_started(
    make_client, wait_run, project_dir, tmp_path
):
    client, _ = make_client([step(call("fake__echo", {"text": "hi"})), text("done")])
    _made, record, _ = server(client, tmp_path)
    give(client, "Lead", "fake")
    cid, run_id = begin(client, project_dir, mode="auto_edit")  # asked there too, as a command
    question = wait_status(client, cid, "waiting_approval")["questions"][0]
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "Deny"})
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed"
    assert calls(snap)["fake__echo"][0] == "denied"
    assert events(record, "start") == [] and events(record, "call") == []


@pytest.mark.parametrize("mode", ["ask", "full_auto"])
def test_a_tool_the_user_marked_runs_unasked_at_every_level(
    make_client, wait_run, project_dir, tmp_path, mode
):
    client, _ = make_client([step(call("fake__echo", {"text": "hi"})), text("done")])
    made, _record, _ = server(client, tmp_path)
    mark(client, made, echo="free")
    give(client, "Lead", "fake")
    cid, run_id = begin(client, project_dir, mode=mode)
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["questions"] == [] and calls(snap)["fake__echo"][0] == "succeeded"


def test_a_tool_marked_ask_asks_at_full_auto_too(make_client, wait_run, project_dir, tmp_path):
    # The Tools page's "Ask" is the user's word over Full auto (no Lead answers it for them).
    client, _ = make_client([step(call("fake__echo", {"text": "hi"})), text("done")])
    server(client, tmp_path)
    give(client, "Lead", "fake")
    cid, run_id = begin(client, project_dir, mode="full_auto")
    (question,) = wait_status(client, cid, "waiting_approval")["questions"]
    assert question["question"].startswith('May the tool "echo" of the MCP server "fake" run?')
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "Allow"})
    assert calls(wait_run(client, cid, run_id, timeout=LONG))["fake__echo"][0] == "succeeded"


def test_a_scratch_a_servers_tool_makes_in_the_project_is_ignored_by_git(
    make_client, wait_run, project_dir, tmp_path
):
    # K-r132 (R136): a server works in a folder of its own, but may write the project by its
    # full path - the scratch it makes gets its `.gitignore` as one a command makes.
    scratch = str(project_dir / ".koloni" / "tmp")
    client, _ = make_client([step(call("fake__mkdir", {"path": scratch})), text("done")])
    tool = {"name": "mkdir", "description": "Makes a folder.", "inputSchema": {
        "type": "object", "properties": {"path": {"type": "string"}}}}
    server(client, tmp_path, free=True, more=[tool])
    give(client, "Lead", "fake")
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert calls(snap)["fake__mkdir"][0] == "succeeded"
    assert (project_dir / ".koloni" / ".gitignore").read_text(encoding="utf-8") == (
        "tmp/\n.gitignore\n")


# --- what comes back ------------------------------------------------------------------------


def test_what_comes_back_is_cut_and_named_for_what_it_is(
    make_client, wait_run, project_dir, tmp_path
):
    client, _ = make_client([
        step(call("fake__boom", {}, "b")), step(call("fake__picture", {}, "p")),
        step(call("fake__big", {}, "g")), text("done")])
    server(client, tmp_path, free=True)
    give(client, "Lead", "fake")
    cid, run_id = begin(client, project_dir, mode="full_auto")
    got = calls(wait_run(client, cid, run_id, timeout=LONG))
    assert got["fake__boom"][0] == "failed" and "it broke" in got["fake__boom"][1]
    status, picture = got["fake__picture"]
    assert status == "succeeded" and "a caption" in picture and "AAAA" not in picture
    assert "image" in picture and "not shown" in picture
    status, big = got["fake__big"]
    assert status == "succeeded" and len(big) < 201_000 and "cut" in big


def test_what_the_server_asks_of_koloni_is_refused_and_the_call_still_ends(
    make_client, wait_run, project_dir, tmp_path
):
    client, _ = make_client([step(call("fake__sample", {})), text("done")])
    _made, record, _ = server(client, tmp_path, free=True)
    give(client, "Lead", "fake")
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert calls(snap)["fake__sample"][0] == "succeeded"
    assert "sampled: error" in calls(snap)["fake__sample"][1]   # nobody's model was asked
    (answer,) = events(record, "answer")
    assert answer["message"]["error"]["code"] == -32601


# --- where it runs, with what, and how it ends ------------------------------------------------


def test_the_server_runs_in_a_folder_of_kolonis_own_without_kolonis_settings(
    make_client, wait_run, project_dir, tmp_path, monkeypatch
):
    monkeypatch.setenv("KOLONI_MODEL_API_KEY", "sk-koloni-secret")
    client, model = make_client({
        "Lead": [step(call("fake__where", {}, "w1")),
                 step(call("spawn_agent", {"role": "Coder", "task": "look"}, "s1")),
                 text("done")],
        "Coder": [step(call("fake__where", {}, "w2")), text("looked")]})
    _made, record, _ = server(client, tmp_path, free=True)
    give(client, "Lead", "fake")
    give(client, "Coder", "fake")
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    # a call to a server is no reason for a working copy: the server does not run in one
    assert next(a for a in snap["agents"] if a["name"] == "Coder")["copy"] is None
    of_lead, of_coder = events(record, "start")           # a process of each agent's own
    assert of_lead["pid"] != of_coder["pid"] and not same(of_lead["cwd"], of_coder["cwd"])
    for start in (of_lead, of_coder):
        # an empty folder, and not the project: no file of a project decides what is started
        assert start["files"] == [] and not same(start["cwd"], project_dir)
        assert project_dir.resolve() not in Path(start["cwd"]).resolve().parents
        assert [name for name in start["env"] if name.upper().startswith("KOLONI_")] == []
        assert start["env"]["THE_SECRET"] == SECRET
        assert not Path(start["cwd"]).exists()            # gone with the agent's work
    assert gone([of_lead["pid"], of_coder["pid"]])
    # an agent with a server is told where the project is, in full: a server needs full paths
    assert str(project_dir) in model.calls_of["Lead"][0][0]["content"]
    # the tool said its secret aloud: it is on no record and was not given to the model
    kept = json.dumps([snap, model.calls_of])
    assert SECRET not in kept and "sk-koloni-secret" not in kept and '\\"secret\\"' in kept


def test_a_server_that_gives_up_fails_the_call_and_is_started_again_for_the_next(
    make_client, wait_run, project_dir, tmp_path
):
    client, _ = make_client([
        step(call("fake__die", {}, "d")), step(call("fake__echo", {"text": "hi"}, "e")),
        text("done")])
    _made, record, _ = server(client, tmp_path, free=True)
    give(client, "Lead", "fake")
    cid, run_id = begin(client, project_dir, mode="full_auto")
    got = calls(wait_run(client, cid, run_id, timeout=LONG))
    assert got["fake__die"][0] == "failed" and "gave up" in got["fake__die"][1]  # its last word
    assert got["fake__echo"][0] == "succeeded"
    first, second = events(record, "start")
    assert first["pid"] != second["pid"] and gone([first["pid"], second["pid"]])


def test_stop_ends_a_call_that_does_not_come_back_and_leaves_nothing_running(
    make_client, wait_run, project_dir, tmp_path
):
    client, _ = make_client([step(call("fake__hang", {})), text("never")])
    _made, record, _ = server(client, tmp_path, free=True)
    give(client, "Lead", "fake")
    cid, run_id = begin(client, project_dir, mode="full_auto")
    deadline = time.monotonic() + LONG
    while not events(record, "call") and time.monotonic() < deadline:
        time.sleep(0.05)
    assert [e["name"] for e in events(record, "call")] == ["hang"]
    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 202
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "cancelled"
    assert calls(snap)["fake__hang"][0] != "succeeded"
    assert gone([e["pid"] for e in events(record, "start")])


# --- where no server's tool is to be had ------------------------------------------------------


def test_no_servers_tool_in_a_turn_nobody_watches(make_client, wait_run, project_dir, tmp_path):
    client, model, pid, cid = unattended.setup(
        make_client, project_dir,
        [step(call("fake__echo", {"text": "hi"})), text("I could not.")],
        permission_mode="full_auto")
    made, record, _ = server(client, tmp_path)
    mark(client, made, echo="free")                     # not even one that is never asked about
    give(client, "Lead", "fake")
    watch = unattended.trigger(client, pid, cid)
    run_id = unattended.run_now(client, watch["id"])
    snap = unattended.finished(client, wait_run, cid, run_id, timeout=LONG)
    assert not [n for n in names(model.tool_args[0]) if n.startswith("fake__")]
    assert calls(snap)["fake__echo"][0] != "succeeded"
    assert events(record, "start") == [] and events(record, "call") == []


def test_no_servers_tool_in_a_project_that_runs_its_commands_in_docker(
    make_client, wait_run, project_dir, tmp_path
):
    client, model = make_client([step(call("fake__echo", {"text": "hi"})), text("could not")])
    _made, record, _ = server(client, tmp_path)
    give(client, "Lead", "fake")
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={
        "exec_location": "docker", "docker_image": "alpine"}).status_code == 200
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}",
                        json={"permission_mode": "full_auto"}).status_code == 200
    run_id = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "go"}).json()["run"]["id"]
    snap = wait_run(client, cid, run_id, timeout=LONG)
    # the server would run on this machine, outside the container the user chose
    assert not [n for n in names(model.tool_args[0]) if n.startswith("fake__")]
    assert calls(snap)["fake__echo"][0] != "succeeded"
    assert events(record, "start") == [] and events(record, "call") == []
