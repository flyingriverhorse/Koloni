"""A stand-in for Claude Code working natively, driven by a plan.

FAKE_CLI_PLAN names a JSON file: {"record": path, "script": [...]}. Like the real CLI with
--input-format stream-json (slice 89b) it reads lines on stdin: KOLONİ's `initialize`
control request (with its PreToolUse hook), then the prompt as a user message, then its
answers. It starts the MCP servers of --mcp-config. Before each of its own tools it sends
`hook_callback`; where the hook says "ask", `can_use_tool` - each with the fields measured
on 2.1.310 (24 Oct 2026). The plan's top level may say "initialize": "error" | "silent" |
"die" (it refuses, never answers, or exits with a complaint), "hooks_applied": false (it
answers without taking the hook) and "account": {...}, given back in its answer. "version"
is what its --version says (2.1.310 by default) and "commands" the user's own commands and
skills its answer lists (none with --disable-slash-commands; KOLONİ's plugin's are added).

    {"say": "text"}
    {"tool": "Write", "input": {...}, "write": ["a.txt", "x"], "result": "ok"}
        its own tool: announce it, ask the hook (and then `can_use_tool`, if the hook says
        "ask"), do it ("write": really write the file; "delete": really remove it), then
        report the result ("error": the tool fails; "agent_type": the hook is told it is
        used in that sub-agent of --agents). "unhooked": the hook is not asked (a
        tool it runs past it); "prompt": `can_use_tool` is sent all the same; "no_id":
        neither names the tool use; "cancel": seconds after `can_use_tool` it withdraws it
        (control_cancel_request) and does not run the tool
    {"koloni": "spawn_agent", "args": {...}}   one of KOLONİ's own tools, over MCP ("parent",
        "agent_type": used in that sub-agent, where a hook's "ask" sends `can_use_tool`)
    {"system": {"subtype": "task_notification", ...}}   a system event, as given
    {"result_for": "toolu_sub", "result": "..."}   the result of a tool left "open"
    {"task": "text", "parent": "toolu_sub"}   the task a sub-agent is handed, as it is shown
    {"hang": true}
    {"die": 7}                          it crashes with that exit code (`die`)
    {"sleep": 3}                        seconds of silence
    {"emit": {...}}                     any other line of its stream, as given
    {"fail": "reason"}                  finish with an error result
    {"await_steer": 5}                  up to 5 seconds for a user line after the prompt (89d)

"CWD" anywhere in the script stands for the folder the CLI was started in.

A tool use is named toolu_<its place in the script>, or by "id". One of its own sub-agents
is its Agent tool: what the sub-agent says and does carries "parent", the id of that tool
use. "open" leaves a tool without its result for now (a sub-agent working in the foreground).

The record: "hooks" the hook's answers, "asked" the answers to `can_use_tool`, "init" the
`initialize` request, "stdin" the prompt, "interrupted" whether KOLONİ sent `interrupt`,
"steered" the user lines after the prompt, "context_asked" each `get_context_usage` (answered
with the plan's "context", or as not supported). With "second_turn_on_steer" a steer heard takes
one more turn after its result; with "linger" it stays after its result, as the real CLI waits.

89m: given a Stop hook at `initialize`, at the script's end it sends that hook (with
`stop_hook_active` true once it was sent back, as measured on 2.1.311); each answer goes in the
record's "stops". On a "block" it works on: the plan's "after_block" holds one script for each
time it is sent back (none left: it stops again at once).

"structured" (89p): what its results hand back with --json-schema, one each (`hand_in`;
"gave_up": a result that says its own schema retries ran out), each after the first only on a
user line, "again_say" said before it; "handed" the hook's word on each StructuredOutput.
"""

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

# Asked, by the Models page (slice 40), whether it has a sign-in status and whether it is
# signed in: said, and nothing recorded.
if sys.argv[1:] == ["--help"]:
    print("Commands:")
    print("  auth  Manage authentication")
    sys.exit(0)
if sys.argv[1:] == ["auth", "status"]:
    print(json.dumps({"loggedIn": True, "authMethod": "claude.ai"}))
    sys.exit(0)
if sys.argv[1:] == ["--version"]:
    told = json.loads(Path(os.environ["FAKE_CLI_PLAN"]).read_text(encoding="utf-8")) \
        if os.environ.get("FAKE_CLI_PLAN") else {}
    print(f"{told.get('version', '2.1.310')} (Claude Code)")
    sys.exit(0)

argv = sys.argv[1:]
plan = json.loads(Path(os.environ["FAKE_CLI_PLAN"]).read_text(encoding="utf-8"))
cwd = Path.cwd()
# "CWD" in the script: the folder it was started in, which a test cannot always know; and
# "PLUGIN_DIR" its --plugin-dir.
plugged = argv[argv.index("--plugin-dir") + 1] if "--plugin-dir" in argv else "no-plugin"
for part in ("script", "after_block"):
    plan[part] = json.loads(json.dumps(plan.get(part, [])).replace("CWD", cwd.as_posix())
                            .replace("PLUGIN_DIR", Path(plugged).as_posix()))
record = {"argv": argv, "cwd": str(cwd), "stdin": "", "asked": [], "hooks": [], "results": [],
          "init": None, "interrupted": False,
          "env_tool_wait": os.environ.get("MCP_TOOL_TIMEOUT"),
          "git_ceiling": os.environ.get("GIT_CEILING_DIRECTORIES"),
          "canary": os.environ.get("KOLONI_CANARY_KEY"),  # (101's planted test key)
          # Where it was pointed, whether with KOLONİ's stand-in token, and which keys it got.
          "sign_in": {"base_url": os.environ.get("ANTHROPIC_BASE_URL"),
                      "placeholder": os.environ.get("ANTHROPIC_AUTH_TOKEN") == "koloni-local",
                      **{name: os.environ.get(name) for name in (
                          "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC")},
                      **{name: name in os.environ for name in (
                          "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK")}}}
lock = threading.Lock()


def save() -> None:
    with lock:
        Path(plan["record"]).write_text(json.dumps(record), encoding="utf-8")


def emit(event: dict) -> None:
    with lock:
        print(json.dumps(event), flush=True)


def die(code: int) -> None:
    """It crashes, a child of its own still holding its output open (denetim-010 #3). (The
    child ends by itself in 30 s.)"""
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                     stdout=sys.stdout, stderr=sys.stderr)
    sys.stdout.flush()
    os._exit(code)


save()
# 27: every start's line, after the record's ("<record>.starts", one JSON line each). Its session
# is the plan's "session_id"; a --resume (Qoder's -r) of one not in its "sessions" ends it before
# anything (as the real CLI is guessed to: not measured) - or, with "resume_late", once it has
# connected to its MCP server. "no_session": [exit code, stderr] it ends with then (Qoder's, as
# measured 5 Nov 2026: tests/qoder_streams/no-session.txt).
with open(plan["record"] + ".starts", "a", encoding="utf-8") as starts:
    starts.write(json.dumps(argv) + "\n")
resumed = next((argv[argv.index(flag) + 1] for flag in ("--resume", "-r") if flag in argv), None)
unknown_session = resumed is not None and resumed not in plan.get("sessions", [])
if unknown_session and not plan.get("resume_late"):
    code, said = plan.get("no_session") or (
        1, f"No conversation found with session ID: {resumed}")
    sys.stderr.write(said.replace("{id}", resumed) + "\n")
    sys.exit(code)
if "--input-format" not in argv or argv[argv.index("--input-format") + 1] != "stream-json":
    sys.stderr.write("started without --input-format stream-json: no control protocol\n")
    sys.exit(2)

lines: "queue.Queue[dict | None]" = queue.Queue()


steered = threading.Event()


def listen() -> None:
    """Every line KOLONİ writes. An interrupt is taken at once, as the real CLI takes it
    while a tool is at work; so is a user line after the prompt (89d: read in the turn it
    comes in, measured 25 Oct); the rest waits for the script."""
    prompted = False
    for raw in sys.stdin.buffer:
        try:
            message = json.loads(raw)
        except ValueError:
            continue
        request = message.get("request") or {}
        if message.get("type") == "control_request" and request.get("subtype") == "interrupt":
            record["interrupted"] = True
            save()
            emit({"type": "control_response", "response": {
                "subtype": "success", "request_id": message.get("request_id"), "response": {}}})
            os._exit(0)
        if message.get("type") == "control_request" and \
                request.get("subtype") == "get_context_usage":
            # (89j: answered at once as well; "context" the plan's answer, else not supported)
            with lock:
                record.setdefault("context_asked", []).append(request)
            save()
            told = plan.get("context")
            emit({"type": "control_response", "response": {
                "subtype": "success", "request_id": message.get("request_id"), "response": told}
                if told else {"subtype": "error", "request_id": message.get("request_id"),
                              "error": "get_context_usage is not supported in this context"}})
            continue
        if message.get("type") == "user" and prompted:
            with lock:
                record.setdefault("steered", []).append(message)
            save()
            steered.set()
            continue
        prompted = prompted or message.get("type") == "user"
        lines.put(message)
    lines.put(None)


threading.Thread(target=listen, daemon=True).start()


def next_line() -> dict:
    message = lines.get()
    if message is None:
        save()
        sys.exit(0)  # its input has ended
    return message


init = next_line()
record["init"] = init
save()
if plan.get("initialize") == "silent":
    while True:
        next_line()
if plan.get("initialize") == "error":
    emit({"type": "control_response", "response": {
        "subtype": "error", "request_id": init.get("request_id"),
        "error": "unknown hook event: PreToolUse"}})
    while True:
        next_line()
if plan.get("initialize") == "die":
    sys.stderr.write("Error: this build cannot take hooks from its host\n")
    sys.stderr.flush()
    os._exit(3)
hook_id = init["request"]["hooks"]["PreToolUse"][0]["hookCallbackIds"][0]
stop_id = (init["request"]["hooks"].get("Stop") or [{}])[0].get("hookCallbackIds", [None])[0]
commands =[] if "--disable-slash-commands" in argv else plan.get(
    "commands", [{"name": "deep-research", "description": "a built-in"}])
if "--plugin-dir" in argv:
    # (KOLONİ removes the folder after the run: what was in it is recorded now.)
    given = Path(argv[argv.index("--plugin-dir") + 1])
    record["plugin"] = sorted(p.relative_to(given).as_posix() for p in given.rglob("*")
                              if p.is_file())
    record["plugin_json"] = json.loads(
        (given / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    record["skill_md"] = {p.parent.name: p.read_text(encoding="utf-8")
                          for p in given.glob("skills/*/SKILL.md")}
    commands += [{"name": f"{record['plugin_json']['name']}:{p.name}"}
                 for p in (given / "skills").iterdir()]
    save()
emit({"type": "control_response", "response": {
    "subtype": "success", "request_id": init.get("request_id"), "response": {
        "commands": commands,
        "hooks_applied": plan.get("hooks_applied", True),
        **({"account": plan["account"]} if plan.get("account") else {})}}})
prompt = next_line()
content = prompt["message"]["content"]
# With pictures, blocks: the prompt's text, then an image block for each.
record["stdin"] = content if isinstance(content, str) else content[0]["text"]
record["images"] = [] if isinstance(content, str) else content[1:]
save()

config = json.loads(Path(argv[argv.index("--mcp-config") + 1]).read_text(encoding="utf-8"))
record["mcp_config"] = config
spec = config["mcpServers"]["koloni"]
bridge = subprocess.Popen([spec["command"], *spec["args"]], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE)
next_id = 0
asked_number = 0


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


def control(request: dict, cancel: float | None = None) -> dict | None:
    """A control request of its own to KOLONİ, and KOLONİ's answer; with `cancel`, that
    many seconds later it is withdrawn instead, and None."""
    global asked_number
    asked_number += 1
    number = f"cli_{asked_number}"
    emit({"type": "control_request", "request_id": number, "request": request})
    if cancel is not None:
        time.sleep(cancel)
        emit({"type": "control_cancel_request", "request_id": number})
        return None
    while True:
        message = next_line()
        response = message.get("response") or {}
        if message.get("type") == "control_response" and response.get("request_id") == number:
            return response["response"] if "response" in response \
                else {"error": response.get("error")}


def hooked(name: str, given: dict, use_id: str | None,
           kind: str | None = None) -> tuple[str | None, str | None]:
    """The hook's word on a tool: "allow", "deny" or "ask"; and its reason. `kind`: the
    sub-agent of its own (one of --agents) the tool is used in, as measured on 2.1.311."""
    told = {"session_id": "fake-session", "transcript_path": "C:/Users/someone/.claude/x.jsonl",
            "cwd": str(cwd), "prompt_id": "fake-prompt", "permission_mode": "default",
            "hook_event_name": "PreToolUse", "tool_name": name,
            "tool_input": given, **({"tool_use_id": use_id} if use_id else {}),
            **({"agent_id": "fake-agent", "agent_type": kind} if kind else {})}
    answer = control({"subtype": "hook_callback", "callback_id": hook_id, "input": told,
                      **({"tool_use_id": use_id} if use_id else {})}) or {}
    record["hooks"].append(answer)
    save()
    out = answer.get("hookSpecificOutput") or {}
    return out.get("permissionDecision"), out.get("permissionDecisionReason")


def prompted(name: str, given: dict, use_id: str | None, cancel: float | None) -> dict:
    # (As measured on 2.1.310: these fields, and no permission_suggestions.)
    verdict = control({"subtype": "can_use_tool", "tool_name": name, "display_name": name,
                       "input": given, "description": name, "decision_reason": "ok",
                       "decision_reason_type": "hook", "decision_reason_hook_event": "PreToolUse",
                       "decision_reason_hook_source": "settings",
                       **({"tool_use_id": use_id} if use_id else {})}, cancel)
    if verdict is None:
        record["cancelled"] = record.get("cancelled", 0) + 1
        save()
        return {"behavior": "deny", "message": "cancelled"}
    record["asked"].append(verdict)
    save()
    return verdict


rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
record["tools"] = [tool["name"] for tool in rpc("tools/list", {})["result"]["tools"]]
save()
if unknown_session:  # ("resume_late": only once its MCP server is in)
    emit({"type": "result", "is_error": True, "result": "No conversation found"})
    sys.exit(1)
# (Its own: where its memory and its socket are, and its session - kept only to resume it, 27.)
emit({"type": "system", "subtype": "init", "model": plan.get("model", "claude-fake-1"),
      "tools": ["Task", "Bash", "Read", "Write", "Edit", "Monitor"], "permissionMode": "default",
      "session_id": plan.get("session_id", "fake-session"),
      "messaging_socket_path": "C:/Users/someone/.claude/sock",
      "memory_paths": ["C:/Users/someone/.claude/CLAUDE.md"]})



def actions():
    """The script; then, given a Stop hook (89m), its end: on a block, the next script of
    "after_block" and its end again."""
    yield from plan["script"]
    again = iter(plan["after_block"])
    while stop_id:
        answer = control({"subtype": "hook_callback", "callback_id": stop_id, "input": {
            "session_id": "fake-session", "transcript_path": "C:/Users/someone/.claude/x.jsonl",
            "cwd": str(cwd), "permission_mode": "default", "hook_event_name": "Stop",
            "stop_hook_active": bool(record.get("stops"))}}) or {}
        record.setdefault("stops", []).append(answer)
        save()
        if answer.get("decision") != "block":
            return
        yield from next(again, [])


for number, action in enumerate(actions()):
    message = {"id": f"msg_{number}", "content": []}
    if "say" in action:
        message["content"].append({"type": "text", "text": action["say"]})
        # one of its own sub-agents speaking: the event names the tool use it runs under
        emit({"type": "assistant", "message": message,
              "parent_tool_use_id": action.get("parent")})
    elif "tool" in action:
        use_id = action.get("id", f"toolu_{number}")
        given = action.get("input", {})
        emit({"type": "assistant", "message": {**message, "content": [
            {"type": "tool_use", "id": use_id, "name": action["tool"], "input": given}]},
            "parent_tool_use_id": action.get("parent")})
        allowed, said = True, action.get("result", "done")
        decision, reason = (None, None) if action.get("unhooked") else hooked(
            action["tool"], given, None if action.get("no_id") else use_id,
            action.get("agent_type"))
        if decision == "deny":
            allowed, said = False, reason or "denied"
        elif decision == "ask" or action.get("prompt"):
            verdict = prompted(action["tool"], given, None if action.get("no_id") else use_id,
                               action.get("cancel"))
            allowed = verdict.get("behavior") == "allow"
            if not allowed:
                said = verdict.get("message", "denied")
        elif decision not in ("allow", None):
            allowed, said = False, f"the hook said {decision!r}"
        if allowed and "write" in action:
            path = Path(action["write"][0])
            path = path if path.is_absolute() else cwd / path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(action["write"][1], encoding="utf-8", newline="\n")
        if allowed and "delete" in action:
            (cwd / action["delete"]).unlink()
        if allowed and action.get("pause"):
            time.sleep(action["pause"])
        failed = not allowed or bool(action.get("error"))
        if action.get("silent") or (action.get("open") and allowed):
            continue  # it never says how its tool ended, or says so later
        emit({"type": "user", "parent_tool_use_id": action.get("parent"), "message": {"content": [{
            "type": "tool_result", "tool_use_id": use_id, "is_error": failed,
            "content": action["error"] if action.get("error") and allowed else said}]}})
    elif "result_for" in action:
        emit({"type": "user", "message": {"content": [{
            "type": "tool_result", "tool_use_id": action["result_for"],
            "is_error": bool(action.get("error")),
            "content": action.get("error") or action.get("result", "done")}]}})
    elif "task" in action:
        emit({"type": "user", "parent_tool_use_id": action.get("parent"),
              "message": {"content": [{"type": "text", "text": action["task"]}]}})
    elif "system" in action:
        emit({"type": "system", **action["system"]})
    elif "koloni" in action:
        use_id = f"toolu_{number}"
        name = f"mcp__koloni__{action['koloni']}"
        emit({"type": "assistant", "message": {**message, "content": [{
            "type": "tool_use", "id": use_id, "name": name, "input": action.get("args", {})}]},
            "parent_tool_use_id": action.get("parent")})
        decision, reason = hooked(name, action.get("args", {}), use_id, action.get("agent_type"))
        if decision == "ask" and action.get("agent_type"):
            verdict = prompted(name, action.get("args", {}), use_id, None)
            decision, reason = verdict.get("behavior"), verdict.get("message")
        if decision == "allow":
            answer = rpc("tools/call", {"name": action["koloni"],
                                        "arguments": action.get("args", {})})
            record["results"].append(answer.get("result", answer))
            save()
        emit({"type": "user", "message": {"content": [{
            "type": "tool_result", "tool_use_id": use_id, "is_error": decision != "allow",
            "content": "ok" if decision == "allow" else reason or "denied"}]}})
    elif action.get("hang"):
        time.sleep(120)
    elif "die" in action:
        die(action["die"])
    elif "sleep" in action:
        time.sleep(action["sleep"])
    elif "await_steer" in action:
        steered.wait(action["await_steer"])
    elif "emit" in action:
        emit(action["emit"])  # any other line of its stream, as given
    elif "fail" in action:
        emit({"type": "result", "is_error": True, "result": action["fail"]})
        sys.exit(1)

def hand_in(given) -> dict:
    """With --json-schema (89p): its answer as its StructuredOutput tool, through the hook as
    any of its tools, and the result's `structured_output` (none where `given` is None)."""
    if given is not None:
        use_id = f"toolu_so_{len(record['hooks'])}"
        emit({"type": "assistant", "message": {"id": use_id, "content": [
            {"type": "tool_use", "id": use_id, "name": "StructuredOutput", "input": given}]},
            "parent_tool_use_id": None})
        record.setdefault("handed", []).append(hooked("StructuredOutput", given, use_id)[0])
        save()
        emit({"type": "user", "message": {"content": [{
            "type": "tool_result", "tool_use_id": use_id, "is_error": False,
            "content": "Structured output provided successfully"}]}})
    return {} if given is None else {"structured_output": given}


# "structured": what each of its results hands back, the next only on a user line after one
# (93-B6: KOLONİ asking for it again).
answers = plan.get("structured", [None])
for number, given in enumerate(answers):
    if number:
        if not steered.wait(10):
            break
        steered.clear()
        if plan.get("again_say"):  # what it says as it hands it in again
            emit({"type": "assistant", "message": {"id": f"msg_again_{number}", "content": [
                {"type": "text", "text": plan["again_say"]}]}, "parent_tool_use_id": None})
    if given == "gave_up":  # (its own schema retries ran out: the Agent SDK's subtype)
        emit({"type": "result", "subtype": "error_max_structured_output_retries",
              "is_error": True, "usage": {"input_tokens": 400, "output_tokens": 30}})
        continue
    handed = hand_in(given)
    emit({"type": "result", "subtype": "success", "is_error": False, "result": "",
          "usage": {"input_tokens": 400, "cache_read_input_tokens": 100, "output_tokens": 30},
          # its own price, filled in even against a local model (measured on 2.1.311, 27 Oct)
          "total_cost_usd": 0.027, **handed})
if plan.get("second_turn_on_steer") and steered.is_set():
    # (89d, not measured: a steer after its last word, taken as a turn of its own)
    emit({"type": "assistant", "message": {"id": "msg_late", "content": [
        {"type": "text", "text": "heard it late"}]}, "parent_tool_use_id": None})
    emit({"type": "result", "subtype": "success", "is_error": False, "result": "",
          "usage": {"input_tokens": 50, "output_tokens": 5}})
if plan.get("linger"):
    time.sleep(120)  # as the real CLI waits on its input for more
if plan.get("exits"):  # gone at once after its result, its input still open
    sys.stdout.flush()
    os._exit(0)
