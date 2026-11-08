"""A stand-in for the agy CLI, driven by a plan.

FAKE_AGY_PLAN names a JSON file: {"record": path, "script": [...]}. Started the way the
real one was measured to be (7 Oct 2026: --input-format stream-json --output-format
stream-json -p=, the prompt as one JSON line on stdin), it prints one JSON event per line
- init, step_update, result - in the shape of the two streams kept in tests/agy_streams:
every event's fields are in an object of the event's own name, every step has its
`step_index`, an answer ends with a DONE that carries "\\n", and before a tool there is an
answer step that is DONE without a word. It really does what the script says in its
working folder:

    {"say": "text"}                            an answer, in two text deltas
    {"tool": "view_file", "parameters": {},    one of its own tools; "error": a failure;
     "output": "..."}                          "never_ends": it starts and is not heard of;
                                               "wait_for": it ends once this file is there
    {"tool": "run_command", "asks": true,      a tool that needs leave: refused without
     "parameters": {}, "output": "...",        --dangerously-skip-permissions, done with
     "touches": {"a.txt": "x"}}                it ("touches": the files it then writes);
                                               "refusal": other words for the refusal;
                                               "refused_done": the step ends DONE, the
                                               refusal its output (as R110 saw 1.4.x
                                               record it; the shape was not measured)
    {"koloni": "spawn_agent", "args": {}}      a tool of KOLONİ's server (B-310), as
                                               mcp__koloni__<tool>: called over the bridge its
                                               home's mcp_config.json names - reading only, if
                                               settings.json allows mcp(koloni/<tool>);
                                               "wrapped": through its call_mcp_tool (B-318), as
                                               {"ServerName", "ToolName", "Arguments"} (a guess:
                                               the shape was not measured)
    {"other": true}                            an event and a step type nobody knows
    {"hang": true} / {"exit": 3, "stderr": ".."} / {"error": "message"}
                                               (a hang is on record first: "hung")
    {"die": 7}                                 it crashes with that exit code (`die`)

A refused command is refused in the words that were measured, and named in the result's
`denied_actions`; how a refused write is worded was not measured (here: the same words).

Started with --dangerously-skip-permissions it holds itself to the hooks of the home it is
given, as 1.3.3 was measured to (24 Oct 2026): it reads <USERPROFILE>/.gemini/config/
hooks.json, says in <home>/.gemini/antigravity-cli/cli.log how many named hooks it loaded
(0 for a file that is not JSON) before it reads its prompt, and runs each matching
PreToolUse hook before a tool as agy does - through `cmd /c` (on Windows), in the folder of
hooks.json, the call on stdin - and obeys it: "deny" blocks the tool, a hook that fails,
prints no decision or outlives its timeout blocks it and ends the turn. Its record keeps
each hook run ("hooks") and the files of that folder as it found them ("config"). A tool
may say "unhooked" (its hooks are not run: the gate that is not there) or "remove" (a file
of that folder taken away first); the plan "hooks_loaded" (the number its log says).
Plan options: "model", "usage", "silent" (no text deltas: the answer is only in the
result), "replay" (a file of recorded events, printed line by line as they are - nothing
else is printed). `agy models` prints the plan's "models" (id<TAB>display name), or
"models_text" as it is, and reads nothing; `agy --version` the plan's "version" (1.4.9).

In either way of running, a home whose .gemini/config/mcp_config.json names a "koloni" server
has that server started once, before its prompt is read (as 1.4.9 was seen to, R103): its
record keeps the files of that folder ("config"), the allow rules of
.gemini/antigravity-cli/settings.json ("allowed"), the tools the server listed ("tools") and
what each call of one gave back ("results"); each listed tool's definition is written to
.gemini/antigravity-cli/mcp/koloni/<tool>.json, as 1.4.x was seen to read one (B-318), and
"{home}" in a tool's parameters is the home it runs in. Plan "second_bridge": its key is
presented once more, by a connection of its own (B-304), and it waits to be ended;
"ignore_allowed": its
settings' rules are not taken; "no_bridge": the server is never started; "foreign_koloni":
another server of that name answers each call (none reaches the bridge).
"""

import contextlib
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

plan = json.loads(Path(os.environ["FAKE_AGY_PLAN"]).read_text(encoding="utf-8"))
argv = sys.argv[1:]
cwd = Path.cwd()
record = {"argv": argv, "cwd": str(cwd), "stdin": None, "pid": os.getpid(),
          "env": dict(os.environ)}


def save() -> None:
    # Whole or not at all: two runs at once (a turn, and the page listing the models) each
    # wrote into the one file, and a reader found half of each.
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


def emit(name: str, fields: dict) -> None:
    print(json.dumps({"event": name, name: fields}), flush=True)


def die(code: int) -> None:
    """It crashes, a child of its own still holding its output open (denetim-010 #3). (The
    child ends by itself in 30 s.)"""
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                     stdout=sys.stdout, stderr=sys.stderr)
    sys.stdout.flush()
    os._exit(code)


if argv[:1] == ["--version"]:
    print(plan.get("version", "1.4.9"))
    sys.exit(0)

if argv[:1] == ["models"]:
    # "record_models": false - the record is then a turn's alone, whenever the models are listed.
    if plan.get("record_models", True):
        save()
    if plan.get("models_hang"):
        time.sleep(120)
    if "models_exit" in plan:
        sys.stderr.write(plan.get("stderr", "") + "\n")
        sys.exit(plan["models_exit"])
    print("Fetching available models...")
    if "models_text" in plan:
        sys.stdout.write(plan["models_text"])
        sys.exit(0)
    for name, shown in plan.get("models", [["gemini-3.8-flash-low", "Gemini 3.8 Flash (low)"]]):
        print(f"{name}\t{shown}")
    sys.exit(0)

if argv[:2] == ["-p", "/quota"]:
    # `agy -p "/quota" --output-format json` (1.4.7, 24 Oct 2026): what is left of its plan,
    # no model turn. The plan's "quota" (printed as JSON; a week of Gemini 8% used if none),
    # "quota_text" (printed as it is) or "quota_exit" with its "stderr". Not on record with
    # "record_models": false either: the page reads it while a turn runs.
    if plan.get("record_models", True):
        save()
    if "quota_exit" in plan:
        sys.stderr.write(plan.get("stderr", "") + "\n")
        sys.exit(plan["quota_exit"])
    # (resets a day on: a window that has reset by the time the page reads it is "stale")
    week = {"name": "Gemini Models", "buckets": [{"id": "gemini-weekly", "window": "weekly",
            "remaining_fraction": 0.92,
            "reset_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 86400))}]}
    quota = plan.get("quota", {"status": "SUCCESS", "num_turns": 0, "command": {
        "name": "usage", "data": {"groups": [week]}}})
    sys.stdout.write(plan.get("quota_text") or json.dumps(quota) + "\n")
    sys.exit(0)

free = "--dangerously-skip-permissions" in argv
groups: list[dict] = []  # its PreToolUse groups: {"matcher", "hooks"}
home = Path(os.environ.get("USERPROFILE") or os.environ["HOME"])
# Only a home of KOLONİ's (agy-*) is looked in: a try-out runs in the user's own.
ours = home.name.startswith("agy-")
config = home / ".gemini" / "config"
record["config"] = {one.name: one.read_text(encoding="utf-8", errors="replace")
                    for one in config.glob("*") if one.is_file()} if ours and config.is_dir() else {}
if free:
    try:
        named = json.loads((config / "hooks.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        named = {}  # measured: a file that is not JSON is passed over, and nothing said
    named = named if isinstance(named, dict) else {}
    groups = [group for one in named.values() if isinstance(one, dict)
              and one.get("enabled", True) for group in one.get("PreToolUse") or []]
    loaded = plan.get("hooks_loaded", len(named))
    groups = groups if loaded else []
    log = home / ".gemini" / "antigravity-cli" / "cli.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(f"I1024 11:49:04.862095       1 hooks_manager.go:53] loaded {loaded} named "
                   "hooks from 1 hooks.json file(s)\n", encoding="utf-8")
record["hooks"] = []
allowed, spec, bridge = [], None, None
with contextlib.suppress(OSError, ValueError, KeyError, TypeError):
    if ours:
        allowed = json.loads((home / ".gemini" / "antigravity-cli" / "settings.json").read_text(
            encoding="utf-8"))["permissions"]["allow"]
with contextlib.suppress(OSError, ValueError, KeyError, TypeError):
    if ours:
        spec = json.loads((config / "mcp_config.json").read_text(encoding="utf-8"))[
            "mcpServers"]["koloni"]
record["allowed"], record["results"] = allowed, []
allowed = [] if plan.get("ignore_allowed") else allowed  # (a rule it does not take)
save()  # (before its bridge: one stopped once its log is read is on record too)
if spec and not plan.get("no_bridge"):
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


if bridge:
    rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
    listed = rpc("tools/list", {})["result"]["tools"]
    record["tools"] = [one["name"] for one in listed]
    defined = home / ".gemini" / "antigravity-cli" / "mcp" / "koloni"
    defined.mkdir(parents=True, exist_ok=True)
    for one in listed:
        (defined / f"{one['name']}.json").write_text(json.dumps(one), encoding="utf-8")
    if plan.get("second_bridge"):  # (its key, as config held it, presented once more)
        door = json.loads(record["config"]["bridge.json"])
        socket.create_connection(("127.0.0.1", door["port"])).sendall(
            door["key"].encode() + b"\n")
        time.sleep(20)  # (KOLONİ ends it)
save()  # (one ended before it was given its prompt is on record too)

record["stdin"] = sys.stdin.buffer.read().decode("utf-8")
save()

if plan.get("replay"):
    for line in Path(plan["replay"]).read_text(encoding="utf-8").splitlines():
        print(line, flush=True)
    sys.exit(0)


def hooked(name: str, given: dict, at: int) -> tuple[str, str] | None:
    """Its PreToolUse hooks for one tool, run as agy runs them: None when all let it
    through, else ("deny", reason) or ("failed", what went wrong)."""
    for group in groups:
        matcher = group.get("matcher") or "*"
        if matcher != "*" and not re.fullmatch(matcher, name):
            continue
        for hook in group.get("hooks") or []:
            told = {"toolCall": {"name": name, "args": given}, "stepIdx": at,
                    "conversationId": "fake-conversation", "workspacePaths": [str(cwd)],
                    "transcriptPath": str(home / ".gemini" / "antigravity-cli" / "t.jsonl")}
            shell = (["cmd", "/c", hook["command"]] if sys.platform == "win32"
                     else ["sh", "-c", hook["command"]])
            ran = {"command": hook["command"], "timeout": hook.get("timeout"), "in": told}
            record["hooks"].append(ran)
            save()  # (a hook still at work is on record too)
            try:
                done = subprocess.run(shell, cwd=config, input=json.dumps(told).encode("utf-8"),
                                      capture_output=True, timeout=hook.get("timeout", 30))
            except subprocess.TimeoutExpired:
                ran["out"] = "timed out"
                save()
                return "failed", "the hook timed out"
            ran.update(code=done.returncode, out=done.stdout.decode("utf-8", "replace"),
                       err=done.stderr.decode("utf-8", "replace"))
            save()
            try:
                said = json.loads(done.stdout) if done.returncode == 0 else None
            except ValueError:
                said = None
            if not isinstance(said, dict) or said.get("decision") not in ("allow", "deny"):
                return "failed", f"the hook failed (exit code {done.returncode})"
            if said["decision"] == "deny":
                return "deny", f"denied by pre-tool hook: {said.get('reason') or ''}"
    return None


model = plan.get("model") or (argv[argv.index("--model") + 1] if "--model" in argv else "auto")
USAGE = {"input_tokens": 900, "output_tokens": 12}
index = 0


def step(kind: str, state: str, at: int | None = None, **fields) -> int:
    """One step_update; a new step takes the next index, `at` speaks of an earlier one."""
    global index
    if at is None:
        at, index = index, index + 1
    emit("step_update", {"step_index": at, "state": state, "step_type": kind, **fields})
    return at


emit("init", {"model": model, "cwd": str(cwd),
              "permission_mode": "bypass" if free else "request-review",
              "tools": ["view_file", "list_dir", "grep_search", "run_command", "write_to_file"]})
step("user_input", "DONE")
said: list[str] = []
denied: list[dict] = []

for action in plan.get("script", []):
    if "koloni" in action:  # (KOLONİ's tool, as a tool step of its own: `kolonis`)
        inner = action.get("args", {})
        action = {"mcp": action["koloni"], "args": inner, **({
            "tool": "call_mcp_tool", "parameters": {
                "ServerName": "koloni", "ToolName": action["koloni"], "Arguments": inner}}
            if action.get("wrapped") else {
            "tool": f"mcp__koloni__{action['koloni']}", "parameters": inner})}
    if "parameters" in action:
        action["parameters"] = json.loads(json.dumps(action["parameters"]).replace(
            "{home}", json.dumps(str(home))[1:-1]))
    if "say" in action:
        text = action["say"]
        said.append(text + "\n")
        if plan.get("silent"):
            continue
        half = len(text) // 2
        at = step("agent_response", "ACTIVE", text_delta=text[:half])
        step("agent_response", "ACTIVE", at, text_delta=text[half:])
        step("agent_response", "DONE", at, text_delta="\n", usage=USAGE)
    elif "tool" in action:
        name, given = action["tool"], action.get("parameters", {})
        step("agent_response", "DONE", usage=USAGE)  # it decided on a tool, without a word
        at = step("tool", "ACTIVE", tool_name=name, tool_info={"name": name, "parameters": given})
        if free and not action.get("unhooked"):
            if action.get("remove"):
                (config / action["remove"]).unlink(missing_ok=True)
            # ("hook_first": [name, args] its hook is told of first at the same step, its
            # answer passed over; "hook_name": the tool as its hook is told of it)
            if action.get("hook_first"):
                hooked(*action["hook_first"], at)
            blocked = hooked(action.get("hook_name", name), given, at)
            if blocked:
                step("tool", "ERROR", at, tool_name=name, tool_info={
                    "name": name, "parameters": given,
                    "error": {"type": "TOOL_ERROR", "message": blocked[1]}})
                if blocked[0] == "failed":  # measured: the tool does not run, the turn ends
                    emit("result", {"status": "ERROR", "response": "", "error": blocked[1],
                                    "usage": {}})
                    sys.exit(1)
                continue
        time.sleep(action.get("hold", 0))
        while "wait_for" in action and not Path(action["wait_for"]).exists():
            time.sleep(0.05)  # held until the test makes this file
        if action.get("never_ends"):
            continue
        if "mcp" in action:
            # Reading only, a call its settings do not allow is refused (measured, R103).
            if plan.get("foreign_koloni"):  # (another server named koloni answered it)
                step("tool", "DONE", at, tool_name=name, tool_info={
                    "name": name, "parameters": given, "output": "done elsewhere"})
                continue
            if bridge is None or (not free and f"mcp(koloni/{action['mcp']})" not in allowed):
                step("tool", "ERROR", at, tool_name=name, tool_info={
                    "name": name, "parameters": given, "error": {
                        "type": "TOOL_ERROR", "message": "permission check failed for mcp "
                        f"tool koloni/{action['mcp']}: user denied permission"}})
                continue
            answer = rpc("tools/call", {"name": action["mcp"], "arguments": action["args"]})
            record["results"].append(answer.get("result", answer))
            save()
            told = "".join(part.get("text", "") for part in
                           answer.get("result", {}).get("content", []))
            step("tool", "DONE", at, tool_name=name, tool_info={
                "name": name, "parameters": given, "output": told})
            continue
        if action.get("asks") and not free:
            # Nobody can be asked here: it refuses, and does nothing.
            line = given.get("CommandLine", name)
            if name == "run_command":
                denied.append({"action": "command", "display_name": "RunCommand"})
            refusal = action.get("refusal") or (
                f'permission check failed for command "{line}": user denied permission to '
                f"run command:\n{line}\nDo not attempt to circumvent this denial by rephrasing "
                "the command, using alternative tools/scripts (e.g. python, sh, curl), or "
                "accessing the same target resource. Proceed without performing this action.")
            step("tool", "DONE" if action.get("refused_done") else "ERROR", at, tool_name=name,
                 tool_info={"name": name, "parameters": given, **(
                     {"output": refusal} if action.get("refused_done") else
                     {"error": {"type": "TOOL_ERROR", "message": refusal}})})
        elif "error" in action:
            for touched, content in action.get("touches", {}).items():
                (cwd / touched).write_bytes(content.encode("utf-8"))
            step("tool", "ERROR", at, tool_name=name, tool_info={
                "name": name, "parameters": given,
                "error": {"type": "TOOL_ERROR", "message": action["error"]}})
        else:
            for touched, content in action.get("touches", {}).items():
                target = Path(touched) if Path(touched).is_absolute() else cwd / touched
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content.encode("utf-8"))
            step("tool", "DONE", at, tool_name=name, tool_info={
                "name": name, "parameters": given, "output": action.get("output", "")})
    elif action.get("other"):
        print(json.dumps({"event": "heartbeat", "heartbeat": {"n": 1}}), flush=True)
        step("planning", "ACTIVE", note="thinking")
    elif action.get("hang"):
        record["hung"] = True  # (all before it printed)
        save()
        time.sleep(120)
    elif "die" in action:
        die(action["die"])
    elif "exit" in action:
        sys.stderr.write(action.get("stderr", "") + "\n")
        sys.exit(action["exit"])
    elif "error" in action:
        emit("result", {"status": "ERROR", "response": "", "error": action["error"],
                        "usage": {}, "denied_actions": denied})
        sys.exit(1)

result = {"status": "SUCCESS", "response": said[-1] if said else "", "num_turns": 1,
          "usage": plan.get("usage", {"input_tokens": 2100, "output_tokens": 45})}
if denied:
    result["denied_actions"] = denied
emit("result", result)
