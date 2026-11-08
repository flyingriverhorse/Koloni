import json

from app.model_client import StepResult, ToolCallRequest
from tests.test_chat_flow import start, text
from tests.test_spawn import role_id


def call(name, args, id="c1"):
    return ToolCallRequest(id, name, args)


def test_tool_result_reaches_the_next_model_step(make_client, wait_run, project_dir):
    client, model = make_client([
        StepResult("", [call("read_file", '{"path": "hello.py"}')], 10, 4),
        text("It prints hi.", 30, 5)])
    cid, run_id = start(client, project_dir, "what does hello.py do?")
    snap = wait_run(client, cid, run_id)
    tc = snap["tool_calls"][0]
    assert (tc["name"], tc["status"], tc["seq"]) == ("read_file", "succeeded", 1)
    assert "print('hi')" in tc["result"] and tc["started_at"] and tc["ended_at"]
    second = model.calls[1]
    assert second[-2]["role"] == "assistant" and second[-2]["tool_calls"] == [
        {"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "hello.py"}'}}]
    assert second[-1] == {"role": "tool", "tool_call_id": "c1", "content": tc["result"]}
    run = snap["runs"][0]
    assert run["status"] == "completed"
    assert (run["input_tokens"], run["output_tokens"]) == (30, 9)  # input: last step; output: sum
    # (two more since the web tools: a search and a request; no notify without an address;
    # and show, every agent's at its own work; and open_room, add_skill, ask_folder and the
    # backlog's four, the lead's; and ask_secret, with run_command; and plan_away, slice 106;
    # and recall_output, every agent's at its own work: K-gecmis-zengin; and the eight browser
    # tools, slice 51; and view_image, 28e; and diagram_image, K-drawio)
    assert model.tool_args[0] is not None and len(model.tool_args[0]) == 38


def test_tool_calls_are_kept_in_history_for_later_turns(make_client, wait_run, project_dir):
    client, model = make_client([
        StepResult("Let me look.", [call("list_dir", "{}")], 1, 1), text("One file."), text("Still one.")])
    cid, run_id = start(client, project_dir)
    wait_run(client, cid, run_id)
    again = client.post(f"/api/conversations/{cid}/messages", json={"content": "sure?"}).json()
    wait_run(client, cid, again["run"]["id"])
    roles = [m["role"] for m in model.calls[2]]
    assert roles == ["system", "user", "assistant", "tool", "assistant", "user"]
    assert model.calls[2][2]["content"] == "Let me look."


def test_invalid_json_arguments_become_a_tool_error_not_a_crash(make_client, wait_run, project_dir):
    client, model = make_client([StepResult("", [call("read_file", "{oops")], 1, 1), text("sorry")])
    cid, run_id = start(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed"
    assert snap["tool_calls"][0]["status"] == "failed"
    assert snap["tool_calls"][0]["arguments"] == "{oops"
    assert "arguments must be a JSON object" in snap["tool_calls"][0]["result"]
    assert model.calls[1][-2]["tool_calls"][0]["function"]["arguments"] == "{}"


def test_unknown_tool_and_escaping_path_are_reported_to_the_model(make_client, wait_run, project_dir):
    client, _ = make_client([
        StepResult("", [call("delete_everything", "{}", "a"), call("read_file", json.dumps({"path": "../" * 40 + "x"}), "b")], 1, 1),
        text("ok")])
    cid, run_id = start(client, project_dir)
    results = {t["name"]: t for t in wait_run(client, cid, run_id)["tool_calls"]}
    assert results["delete_everything"]["status"] == "failed"
    assert "unknown tool" in results["delete_everything"]["result"]
    assert results["read_file"]["status"] == "failed"
    assert "never opened" in results["read_file"]["result"]  # a drive's root
    assert [results["delete_everything"]["seq"], results["read_file"]["seq"]] == [1, 2]


def test_step_limit_fails_the_run(make_client, wait_run, project_dir):
    # (B-413: the Orchestrator's step limit is only one the user set - its role's)
    loop = [StepResult("", [call("list_dir", json.dumps({"path": f"d{i}"}), f"c{i}")], 1, 1)
            for i in range(25)]
    client, _ = make_client(loop)
    assert client.patch(f"/api/roles/{role_id(client, 'Lead')}", json={"max_steps": 20},
                        headers={"Origin": "http://127.0.0.1:8790"}).status_code == 200
    cid, run_id = start(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert (snap["runs"][0]["status"], snap["runs"][0]["error"]) == (
        "failed", "stopped at its role's limit of 20 steps")
    assert len(snap["tool_calls"]) == 20


def test_tools_are_withheld_when_the_model_does_not_support_them(make_client, wait_run, project_dir):
    client, model = make_client([text("plain")], tools_supported=False)
    cid, run_id = start(client, project_dir)
    wait_run(client, cid, run_id)
    assert model.tool_args == [None]


def test_old_tool_output_is_trimmed_when_history_exceeds_the_budget(
        make_client, wait_run, project_dir, settings_env, monkeypatch):
    from app.agent import (
        AWAY_PROMPT,
        BRIEF_PROMPT,
        HAND_ON_PROMPT,
        LANGUAGE_PROMPT,
        MESSAGE_PROMPT,
        PROVIDERS_PROMPT,
        REPORT_ONCE,
        TEAM_PROMPT,
    )
    from app.executors.host import SHELL_WRITES
    from app.roles import WHO_SPLITS

    # (The Lead's own instructions end with the split rule, K-rol-cogul: counted as they grew;
    # and the blanked read is said in a line, with its id: K-gecmis-zengin. The system
    # prompt's line on a refusal grew 77 characters, B-321, and the shell line, B-324 - counted
    # with Windows PowerShell's, whichever shell this machine has.)
    monkeypatch.setattr("app.executors.host._pwsh", lambda: None)
    settings_env["KOLONI_CONTEXT_CHARS"] = str(
        1620 + 77 + len(SHELL_WRITES) + len(WHO_SPLITS) + 1 + sum(len(told) + 2 for told in (
            LANGUAGE_PROMPT, MESSAGE_PROMPT, PROVIDERS_PROMPT, HAND_ON_PROMPT, TEAM_PROMPT,
            AWAY_PROMPT, BRIEF_PROMPT, REPORT_ONCE)) + len(" read big.txt (1 lines) (full: recall_output id=)") + 32)
    (project_dir / "big.txt").write_text("x" * 600 + "\n", encoding="utf-8")
    client, model = make_client([
        StepResult("", [call("read_file", '{"path": "big.txt"}', "a")], 1, 1),
        StepResult("", [call("read_file", '{"path": "hello.py"}', "b")], 1, 1),
        text("done")])
    cid, run_id = start(client, project_dir)
    wait_run(client, cid, run_id)
    assert "xxxx" in next(m for m in model.calls[1] if m["role"] == "tool")["content"]
    tool_msgs = [m for m in model.calls[2] if m["role"] == "tool"]
    # (said in a line made from its call: K-gecmis-zengin)
    assert tool_msgs[0]["content"].startswith("[older tool output removed to save context]")
    assert "print('hi')" in tool_msgs[1]["content"]


def test_a_queued_message_follows_the_whole_earlier_turn_in_history(
        make_client, wait_run, project_dir, gate):
    # The message is queued while the first turn is still working, so it is older than
    # the first turn's later messages; the model must still see the turns in order.
    client, model = make_client([
        gate.step(StepResult("", [call("list_dir", "{}")], 1, 1)), text("One file."), text("Hi.")])
    cid, run_id = start(client, project_dir, "first")
    queued = client.post(f"/api/conversations/{cid}/messages", json={"content": "second"}).json()
    gate.release()
    snap = wait_run(client, cid, queued["run"]["id"])
    assert [(m["role"], m.get("content")) for m in model.calls[2][1:]] == [
        ("user", "first"), ("assistant", ""), ("tool", "hello.py  (file, 12 bytes)"),
        ("assistant", "One file."), ("user", "second")]
    assert [m["content"] for m in snap["messages"] if m["content"]] == [
        "first", "One file.", "second", "Hi."]
