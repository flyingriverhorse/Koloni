"""A stand-in for the GitHub Copilot CLI in a session, driven by a plan.

FAKE_CLI_PLAN names a JSON file: {"record": path, "script": [...]}. Like the real CLI it
reads its prompt on stdin, starts the MCP server named in --additional-mcp-config @file,
and prints one JSON event per line:

    {"say": "text"}                     an assistant message
    {"call": "read_file", "args": {}}   ask for a KOLONİ tool, run it over MCP
    {"own": "powershell"}               run a tool of its own (it must be stopped)
    {"find": "read_file"}               search for a tool with its own tool_search_tool, as its
                                        auto on a Claude model did live (B-410; shape assumed)
    {"error": "message"}                report an error and give up
    {"exit": 3, "stderr": "..."}        crash

The plan's "usage": the data of each session.usage_checkpoint it prints, in order, before its
result (none: none printed). "picked": started with `--model auto`, its auto picks that model
and says so first, with "picked_why" (session.auto_mode_resolved, as measured on 1.0.105).
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

plan = json.loads(Path(os.environ["FAKE_CLI_PLAN"]).read_text(encoding="utf-8"))
argv = sys.argv[1:]
stdin = sys.stdin.buffer.read().decode("utf-8")
home = os.environ.get("COPILOT_HOME")
record = {
    "argv": argv, "cwd": str(Path.cwd()), "stdin": stdin, "results": [],
    "env": {k: v for k, v in os.environ.items() if k.startswith("COPILOT_")},
    "home_was_empty": bool(home) and Path(home).is_dir() and not any(Path(home).iterdir()),
    "github_tokens": sorted(k for k in os.environ if k in ("GH_TOKEN", "GITHUB_TOKEN")),
}


def save() -> None:
    Path(plan["record"]).write_text(json.dumps(record), encoding="utf-8")


def emit(kind: str, data: dict | None = None, **top) -> None:
    print(json.dumps({"type": kind, "data": data or {}, **top}), flush=True)


save()
if home:
    (Path(home) / "session-state.json").write_text("{}", encoding="utf-8")  # it keeps state
model = plan.get("model", os.environ.get("COPILOT_MODEL", "auto"))
config_path = argv[argv.index("--additional-mcp-config") + 1].removeprefix("@")
spec = json.loads(Path(config_path).read_text(encoding="utf-8"))["mcpServers"]["koloni"]
bridge = subprocess.Popen([spec["command"], *spec["args"]], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE)
next_id = 0


def rpc(method: str, params: dict) -> dict:
    global next_id
    next_id += 1
    bridge.stdin.write((json.dumps(
        {"jsonrpc": "2.0", "id": next_id, "method": method, "params": params}) + "\n").encode())
    bridge.stdin.flush()
    line = bridge.stdout.readline()
    if not line:
        raise SystemExit("the tool server closed the connection")
    return json.loads(line)


rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
record["tools"] = [tool["name"] for tool in rpc("tools/list", {})["result"]["tools"]]
save()
emit("session.info", {"infoType": "configuration", "message": "Disabled tools: create, edit"})
if plan.get("picked") and "--model" in argv and argv[argv.index("--model") + 1] == "auto":
    model = plan["picked"]
    emit("session.auto_mode_resolved", {"chosenModel": model, "selectionReason": plan.get(
        "picked_why"), "routingMethod": "auto_v2", "fallback": False})
if not plan.get("no_tools_event"):
    emit("session.tools_updated", {"model": model})
emit("user.message", {"content": stdin[:50]})

for number, action in enumerate(plan.get("script", [])):
    emit("model.call_start", {"turnId": str(number), "model": model})
    if "say" in action:
        emit("assistant.message", {"content": action["say"], "toolRequests": []})
    elif "call" in action:
        name = action["call"]
        emit("assistant.message", {"content": action.get("before", ""), "toolRequests": [{
            "toolCallId": f"c{number}", "name": f"koloni-{name}", "mcpServerName": "koloni",
            "mcpToolName": name, "arguments": action.get("args", {})}]})
        emit("tool.execution_start", {"toolCallId": f"c{number}", "toolName": f"koloni-{name}",
                                      "mcpServerName": "koloni", "mcpToolName": name})
        answer = rpc("tools/call", {"name": name, "arguments": action.get("args", {})})
        record["results"].append(answer.get("result", answer))
        save()
        emit("tool.execution_complete", {"toolCallId": f"c{number}", "success": True})
    elif "tool" in action:
        # A tool of its own, used without asking (--allow-all-tools): do it, report it.
        call = f"c{number}"
        emit("tool.execution_start", {"toolCallId": call, "toolName": action["tool"],
                                      "arguments": action.get("args", {})})
        if "write" in action:
            target = Path.cwd() / action["write"][0]
            target.write_text(action["write"][1], encoding="utf-8", newline="\n")
        if action.get("pause"):
            time.sleep(action["pause"])
        emit("tool.execution_complete", {
            "toolCallId": call, "success": not action.get("fails", False),
            "result": {"content": action.get("result", "done")}})
    elif "request" in action:
        emit("assistant.message", {"content": "", "toolRequests": [{
            "toolCallId": f"c{number}", "name": action["request"], "arguments": {}}]})
        time.sleep(60)
    elif "find" in action:
        call = {"toolCallId": f"c{number}", "name": "tool_search_tool",
                "arguments": {"query": action["find"]}}
        emit("assistant.message", {"content": "", "toolRequests": [call]})
        emit("tool.execution_start", {"toolCallId": call["toolCallId"], "toolName": call["name"],
                                      "arguments": call["arguments"]})
        emit("tool.execution_complete", {"toolCallId": call["toolCallId"], "success": True,
                                         "result": {"content": f"koloni-{action['find']}"}})
    elif "own" in action:
        emit("tool.execution_start", {"toolCallId": f"c{number}", "toolName": action["own"]})
        time.sleep(60)
    elif "error" in action:
        emit("session.error", {"message": action["error"]})
        emit("result", exitCode=1, usage={"premiumRequests": 0})
        sys.exit(1)
    elif "exit" in action:
        sys.stderr.write(action.get("stderr", "") + "\n")
        sys.exit(action["exit"])

for checkpoint in plan.get("usage", []):
    emit("session.usage_checkpoint", checkpoint)
emit("result", exitCode=0, usage={"premiumRequests": 0, "totalApiDurationMs": 10})
