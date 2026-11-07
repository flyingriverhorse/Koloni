"""A stand-in for a CLI agent in a session (Claude Code or Qoder), driven by a plan.

FAKE_CLI_PLAN names a JSON file: {"record": path, "script": [...]}. Like the real
CLIs it starts the one MCP server it is given (KOLONİ's bridge), asks it for its
tools, and then follows the script, printing the same stream events:

    {"say": "text"}                     an assistant text block
    {"call": "read_file", "args": {}}   announce a tool call, make it over MCP, print the result
    {"parallel": [{"call": ..}, ..]}    make several calls at once, then read the answers
    {"call_then_die": "x", "after": 1}  make a call and exit before it is answered
    {"hang": true}                      keep running until killed
    {"exit": 3, "stderr": "..."}        give up
    {"result_error": "..."}             finish with an error result
    {"emit": {...}}                     any other line of its stream, as given
    {"wait_for": "path"}                go on only once that file is there

Each action is a model message of its own, unless it names one ("message": "m1"): the
actions that name the same one are the pieces of one message.

A script that runs to its end finishes with a normal result.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

plan = json.loads(Path(os.environ["FAKE_CLI_PLAN"]).read_text(encoding="utf-8"))
argv = sys.argv[1:]


def save_record(record: dict) -> None:
    # Whole or not at all, as fake_agy_cli.py's: a CLI killed in the middle of writing left
    # the record empty, and a test reading it found no JSON.
    target = Path(plan["record"])
    mine = target.with_name(f"{target.name}.{os.getpid()}")
    mine.write_text(json.dumps(record), encoding="utf-8")
    # On Windows a record a reader has open cannot be replaced just then: tried again for
    # a fraction of a second, and then left as it was - the record is only a test's aid.
    for _ in range(10):
        try:
            os.replace(mine, target)
            return
        except PermissionError:
            time.sleep(0.03)
    mine.unlink(missing_ok=True)


if argv == ["--list-models"]:
    # Qoder's model list: plan "models_text" printed, "models_exit" its code, "models_hang".
    save_record({"argv": argv})
    if plan.get("models_hang"):
        time.sleep(120)
    sys.stdout.write(plan.get("models_text", ""))
    sys.stderr.write("account buzzy@example.com refused\n")  # (never to be shown)
    sys.exit(plan.get("models_exit", 0))
stdin = sys.stdin.buffer.read().decode("utf-8")
cwd = Path.cwd()
record = {
    "argv": argv, "cwd": str(cwd), "stdin": stdin, "pid": os.getpid(), "results": [],
    "env_tool_wait": os.environ.get("MCP_TOOL_TIMEOUT"),
    "files": sorted(f.name for f in cwd.iterdir()),
    # Where it was pointed, whether with KOLONİ's stand-in token, and which keys it got.
    "sign_in": {"base_url": os.environ.get("ANTHROPIC_BASE_URL"),
                "placeholder": os.environ.get("ANTHROPIC_AUTH_TOKEN") == "koloni-local",
                **{name: os.environ.get(name) for name in (
                    "CLAUDE_CONFIG_DIR", "CODEX_HOME", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC")},
                **{name: name in os.environ for name in (
                    "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "OPENAI_API_KEY", "CODEX_API_KEY",
                    "CODEX_ACCESS_TOKEN", "CLAUDE_CODE_USE_BEDROCK")}},
}


def save() -> None:
    save_record(record)


def emit(event: dict) -> None:
    print(json.dumps(event), flush=True)


config = json.loads(Path(argv[argv.index("--mcp-config") + 1]).read_text(encoding="utf-8"))
spec = config["mcpServers"]["koloni"]
env = {**os.environ, **spec.get("env", {}), **plan.get("bridge_env", {})}
bridge = subprocess.Popen([spec["command"], *spec["args"]], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, env=env)
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


try:
    rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
    listed = rpc("tools/list", {})["result"]["tools"]
except SystemExit as closed:
    record["refused"] = str(closed)
    save()
    sys.exit(4)
record["tools"] = [tool["name"] for tool in listed]
save()
if not plan.get("no_init"):
    emit({"type": "system", "subtype": "init", **(
        {"model": plan["model"]} if "model" in plan else {}),
          "tools": [f"mcp__koloni__{tool['name']}" for tool in listed] + plan.get("own_tools", [])})


def send(method: str, params: dict) -> int:
    global next_id
    next_id += 1
    bridge.stdin.write((json.dumps(
        {"jsonrpc": "2.0", "id": next_id, "method": method, "params": params}) + "\n").encode())
    bridge.stdin.flush()
    return next_id

# Started again to answer another agent, it follows "answer_script" when there is one - and,
# started again after its turn to read what came for it (a sub-agent's report), "later_script"
# once "later_when" is in what it is given.
# "task_scripts": {text: script} - a run whose input has the text follows that script (a
# sub-agent on the same CLI, by its task). "runs": a file each run writes which it followed.
script, which = plan.get("script", []), "script"
if "later_script" in plan and plan["later_when"] in stdin:
    script, which = plan["later_script"], "later"
elif "answer_script" in plan and ("Message from " in stdin or "You are in a discussion" in stdin):
    script, which = plan["answer_script"], "answer"
else:
    for text, own in plan.get("task_scripts", {}).items():
        if text in stdin:
            script, which = own, text
            break
if plan.get("runs"):
    with open(plan["runs"], "a", encoding="utf-8") as log:
        log.write(f"{which}\n")
for number, action in enumerate(script):
    # "message": the model message this piece belongs to - the real CLI writes a message
    # with text and several calls as one event each, all under the message's id.
    message_id = action.get("message") or f"msg_{number}"
    if "say" in action:
        emit({"type": "assistant",
              "message": {"id": message_id, "content": [{"type": "text", "text": action["say"]}]}})
    elif "call" in action:
        call_id = f"toolu_{number}"
        emit({"type": "assistant", "message": {"id": message_id, "content": [{
            "type": "tool_use", "id": call_id, "name": f"mcp__koloni__{action['call']}",
            "input": action.get("args", {})}]}})
        try:
            answer = rpc("tools/call", {"name": action["call"], "arguments": action.get("args", {})})
        except SystemExit:
            record["cut_off"] = True
            save()
            sys.exit(5)
        result = answer.get("result", answer)
        record["results"].append(result)
        save()
        emit({"type": "user", "message": {"content": [{
            "type": "tool_result", "tool_use_id": call_id,
            "content": result.get("content"), "is_error": result.get("isError", False)}]}})
    elif "parallel" in action:
        # One model message with several tool calls, all in flight together.
        for index, item in enumerate(action["parallel"]):
            emit({"type": "assistant", "message": {"id": message_id, "content": [{
                "type": "tool_use", "id": f"toolu_{number}_{index}",
                "name": f"mcp__koloni__{item['call']}", "input": item.get("args", {})}]}})
        for item in action["parallel"]:
            send("tools/call", {"name": item["call"], "arguments": item.get("args", {})})
        for _ in action["parallel"]:
            record["results"].append(json.loads(bridge.stdout.readline()).get("result"))
        save()
    elif "call_then_die" in action:
        emit({"type": "assistant", "message": {"id": message_id, "content": [{
            "type": "tool_use", "id": f"toolu_{number}",
            "name": f"mcp__koloni__{action['call_then_die']}", "input": action.get("args", {})}]}})
        send("tools/call", {"name": action["call_then_die"], "arguments": action.get("args", {})})
        time.sleep(action.get("after", 1))
        sys.stderr.write("fatal: the CLI crashed\n")
        sys.exit(9)
    elif action.get("hang"):
        time.sleep(120)
    elif "exit" in action:
        sys.stderr.write(action.get("stderr", "") + "\n")
        sys.exit(action["exit"])
    elif "result_error" in action:
        emit({"type": "result", "is_error": True, "result": action["result_error"]})
        sys.exit(1)
    elif "emit" in action:
        emit(action["emit"])
    elif "wait_for" in action:
        while not Path(action["wait_for"]).exists():
            time.sleep(0.02)

usage = plan.get("usage", {"input_tokens": 300, "cache_read_input_tokens": 200, "output_tokens": 40})
emit({"type": "result", "is_error": False, "result": "done", "usage": usage, "total_cost_usd": 1.0})
