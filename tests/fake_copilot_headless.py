"""A stand-in for `copilot --headless --stdio` (slice 89c): JSON-RPC with Content-Length
framing, as measured on Copilot CLI 1.0.91 (24 Oct 2026). Started any other way it is the
session-mode stand-in (`fake_copilot_cli.py`), which the same provider's talker uses.

FAKE_CLI_PLAN names a JSON file: {"record": path, "script": [...]}; "handshake" ("ping":
the ping is refused, "version": it speaks protocol 2, "create": session.create is
refused, "model": it is refused for its model, "gone": it ends before answering, "silent": it never answers) makes the start go
wrong; "starts" names a file it adds each argv it is started with to. It writes down how
it was started, what session.create and session.send were given, and every answer KOLONİ
gave to a permission request ("answers"). Asked `account.getQuota`, at any point, it answers
the plan's "quota" ("quota_hang": never); asked `auth.getStatus`, signed in by gh unless "signed_in" is false; asked
`sandbox.getHostSupport`, the plan's "sandbox" (a shell step's "sandboxed": it ran in it). Its session
made on auto, "picked" is the model its auto picks, said with "picked_why" before its first step. Steps:

    {"say": "text"}                                   an assistant message
    {"shell": "pytest -q", "output": "ok", "exit": 0} a command, run only once approved
                                                      ("touches": files it writes;
                                                      "no_code": no exit code trailer)
    {"write": "a.py", "content": "x"}                 a file written once approved (its
                                                      tool "create", or "edit" if it is there)
    {"read": ".env", "result": "..."}                 its view tool, run once approved
    {"ask": {"kind": "url", ...}, "tool": "web_fetch"} any other permission request
    {"koloni": "read_notes", "args": {}}              a call to KOLONİ's MCP server, for real
    {"request": "userInput.request", "params": {}}    a JSON-RPC request of its own
    {"pause": s} / {"error": "message"} / {"exit": 3, "stderr": ".."}

A step with "unasked" runs without a permission request; "twice": the same request is
sent again under a new request id; "no_complete": a rejected tool is never said to be done;
"hooked": a hook of its own answered the request; "unapplied": it says it did not take
KOLONİ's answer; "bypass": the request asks to go outside its sandbox, for that reason. A shell step's "paths", "urls" and "redirect" are its possiblePaths,
possibleUrls and hasWriteFileRedirection; "readonly", the readOnly of its one `commands`
entry (else none); "cwd" is where it says it runs (1.0.91 says nothing of that); "shell_type" its
shellType ("powershell"; null: none said). A write ("delete": the file goes) has no fileEdits, as on 1.0.91, unless
"edits" gives them (true: what it will hold); "contents" is its newFileContents,
"resolved" its resolvedPath, "diff" its diff.
The plan's "aborted": its turn ends aborted. The plan's "usage": the data of each
session.usage_checkpoint it sends, in order, before its turn ends (none: none sent).
"""

import json
import os
import runpy
import subprocess
import sys
import time
from pathlib import Path

told = json.loads(Path(os.environ["FAKE_CLI_PLAN"]).read_text(encoding="utf-8")) \
    if os.environ.get("FAKE_CLI_PLAN") else {}
if told.get("starts"):  # every way it was started, one line each
    with open(told["starts"], "a", encoding="utf-8") as log:
        log.write(json.dumps(sys.argv[1:]) + "\n")
if "--version" in sys.argv[1:]:  # the plan's "version", if it names one
    print(f"GitHub Copilot CLI {told.get('version', '1.0.91-fake')}.")
    sys.exit(0)
if "--headless" not in sys.argv[1:]:
    runpy.run_path(str(Path(__file__).with_name("fake_copilot_cli.py")), run_name="__main__")
    sys.exit(0)

plan = json.loads(Path(os.environ["FAKE_CLI_PLAN"]).read_text(encoding="utf-8"))
argv = sys.argv[1:]
cwd = Path.cwd()
home = os.environ.get("COPILOT_HOME")
record = {
    "argv": argv, "cwd": str(cwd), "results": [], "answers": [], "replies": [],
    "env": {k: v for k, v in os.environ.items() if k.startswith("COPILOT_")},
    "home_was_empty": bool(home) and Path(home).is_dir() and not any(Path(home).iterdir()),
    "github_tokens": sorted(k for k in os.environ if k in ("GH_TOKEN", "GITHUB_TOKEN")),
    "names": sorted(os.environ),  # (the names only)
}
# What it says of whose account it is: nobody's business but the account's.
ACCOUNT = {"login": "someone-on-github", "email": "someone@example.com"}
stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
numbers = iter(range(1000, 10**6))


def save() -> None:
    Path(plan["record"]).write_text(json.dumps(record), encoding="utf-8")


def send(message: dict) -> None:
    body = json.dumps({"jsonrpc": "2.0", **message}).encode("utf-8")
    stdout.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
    stdout.flush()


def heard() -> dict:
    while (told := framed()).get("method") == "account.getQuota":
        # What is left of its plan, no turn (1.0.91, 24 Oct 2026), whenever it is asked -
        # alone or after a session's turn (89l): the plan's "quota" (none: refused), its
        # "quota_error" refusing it, or with "quota_hang" no answer at all.
        record["quota_asked"] = told.get("params")
        save()
        if plan.get("quota_hang"):
            continue
        if "quota_error" in plan or "quota" not in plan:
            send({"id": told["id"], "error": {"code": -32603, "message": plan.get(
                "quota_error", "no quota")}})
        else:
            send({"id": told["id"], "result": plan["quota"]})
    return told


def framed() -> dict:
    length = None
    while True:
        line = stdin.readline()
        if not line:
            sys.exit(0)  # ended
        if not line.strip():
            if length is not None:
                break
            continue
        name, _, value = line.decode("ascii").partition(":")
        if name.strip().lower() == "content-length":
            length = int(value)
    return json.loads(stdin.read(length))


def expect(method: str) -> dict:
    while (told := heard()).get("method") != method:
        pass
    return told


def event(kind: str, data: dict) -> None:
    send({"method": "session.event", "params": {"sessionId": "s1", "event": {
        "id": f"e{next(numbers)}", "timestamp": "2026-10-24T00:00:00Z", "type": kind,
        "data": data}}})


save()
if home:
    (Path(home) / "session-state").mkdir(exist_ok=True)  # it keeps its sessions in its home
started = expect("ping")
handshake = plan.get("handshake")
if handshake == "gone":
    sys.exit(0)
if handshake == "silent":
    time.sleep(120)
if handshake == "ping":
    send({"id": started["id"], "error": {"code": -32603, "message": "not ready"}})
    expect("never")
send({"id": started["id"], "result": {"message": "pong", "timestamp": "2026-10-24T00:00:00Z",
                                      "protocolVersion": 2 if handshake == "version" else 3}})
told = heard()  # (an account.getQuota alone is answered there; then it is ended)
if told.get("method") == "auth.getStatus":
    # Whether it is signed in, no turn (1.0.103, 24 Oct 2026): the plan's "signed_in"
    # (default yes), by gh's login, with whose account it is in its statusMessage.
    record["status_asked"] = told.get("params")
    save()
    signed_in = plan.get("signed_in", True)
    send({"id": told["id"], "result": {
        "isAuthenticated": signed_in, "authType": "gh-cli" if signed_in else None,
        "statusMessage": f"Logged in as {ACCOUNT['login']}" if signed_in else "Not logged in",
        **({"login": ACCOUNT["login"]} if signed_in else {})}})
    expect("never")
if told.get("method") == "sandbox.getHostSupport":
    # What this machine can sandbox (1.0.103, 24 Oct 2026, by REA): the plan's "sandbox",
    # else a sandbox that denies paths; "unknown": a Copilot that has no such method.
    record["sandbox_asked"] = True
    save()
    support = plan.get("sandbox", {"supported": True, "capabilities": [
        {"name": "denied_paths", "supported": True}]})
    send({"id": told["id"], **({"error": {"code": -32601, "message": "Unhandled method"}}
                               if support == "unknown" else {"result": support})})
    told = heard()
create = told if told.get("method") == "session.create" else expect("session.create")
record["create"] = create["params"]
save()
if handshake == "create":
    send({"id": create["id"], "error": {"code": -32602, "message": "unknown field mcpServers"}})
    expect("never")
if handshake == "model":  # the message seen live for a model not on the account (B-176, B-179); code a guess
    model = create["params"].get("model")
    send({"id": create["id"], "error": {"code": -32603, "message": (
        f'Request session.create failed with message: Model "{model}" is not available.')}})
    expect("never")
send({"id": create["id"], "result": {
    "sessionId": "s1", "workspacePath": str(Path(home or cwd) / "session-state" / "s1"),
    "authInfo": ACCOUNT}})
asked = expect("session.send")
record["prompt"] = asked["params"].get("prompt")
save()
send({"id": asked["id"], "result": {"messageId": "m1"}})
event("session.start", {"sessionId": "s1", "context": {"cwd": str(cwd)}})
if plan.get("picked") and create["params"].get("model") == "auto":
    plan["model"] = plan["picked"]
    event("session.auto_mode_resolved", {"chosenModel": plan["picked"],
                                         "selectionReason": plan.get("picked_why")})
spec = create["params"]["mcpServers"]["koloni"]
bridge = subprocess.Popen([spec["command"], *spec["args"]], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE)


def koloni(method: str, params: dict) -> dict:
    """Talk to KOLONİ's tool server the way Copilot would: through the bridge it was given."""
    assert bridge.stdin is not None and bridge.stdout is not None
    bridge.stdin.write((json.dumps({"jsonrpc": "2.0", "id": next(numbers), "method": method,
                                    "params": params}) + "\n").encode())
    bridge.stdin.flush()
    line = bridge.stdout.readline()
    if not line:
        raise SystemExit("the tool server closed the connection")
    return json.loads(line)


koloni("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
record["tools"] = [tool["name"] for tool in koloni("tools/list", {})["result"]["tools"]]
save()


def permitted(call: str, request: dict, action: dict) -> bool:
    """Ask KOLONİ for leave, as Copilot asks a client that said requestPermission: an event,
    answered by a request of the client's own."""
    if action.get("unasked"):
        return True
    approved = False
    for _ in range(2 if action.get("twice") else 1):
        request_id = f"r{next(numbers)}"
        event("permission.requested", {"requestId": request_id, "permissionRequest": {
            "toolCallId": call, **request}, **({"resolvedByHook": True}
                                               if action.get("hooked") else {})})
        if action.get("hooked"):  # a hook of its own said yes: nobody else is asked
            return True
        answer = expect("session.permissions.handlePendingPermissionRequest")
        params = answer["params"]
        assert params["sessionId"] == "s1" and params["requestId"] == request_id
        record["answers"].append({"kind": request["kind"], "result": params["result"]})
        save()
        # ("unapplied": it says it did not take the answer)
        send({"id": answer["id"], "result": {"success": not action.get("unapplied")}})
        if action.get("unapplied"):
            expect("never")
        event("permission.completed", {"requestId": request_id, "toolCallId": call,
                                       "result": {"kind": "approved"}})
        approved = params["result"].get("kind") == "approve-once"
    return approved


def tool(call: str, name: str, arguments: dict, request: dict | None, action: dict,
         work=None, result: str = "done", **start) -> None:
    event("tool.execution_start", {"toolCallId": call, "toolName": name,
                                   "arguments": arguments, **start})
    if request is not None and "bypass" in action:  # (its reason, as the SDK types it)
        request = {**request, "requestSandboxBypass": True,
                   "requestSandboxBypassReason": action["bypass"]}
    if request is not None and not permitted(call, request, action):
        if not action.get("no_complete"):  # (with it: never a word that it is done)
            event("tool.execution_complete", {"toolCallId": call, "success": False, "error": {
                "message": "The user rejected this tool call."}})
        return
    if work:
        work()
    # ("sandboxed": it ran in its sandbox, as REA saw 1.0.103 say it)
    event("tool.execution_complete", {"toolCallId": call, "success": True,
                                      "result": {"content": result}, **(
                                          {"toolTelemetry": {"sandboxApplied": True}}
                                          if action.get("sandboxed") else {})})


for number, action in enumerate(plan.get("script", [])):
    call = f"call_{number}"
    event("model.call_start", {"turnId": str(number), "model": plan.get("model", "auto")})
    if "say" in action:
        event("assistant.message", {"messageId": f"m{number}", "content": action["say"],
                                    "toolRequests": []})
    elif "shell" in action:
        def run(action=action) -> None:
            for touched, content in action.get("touches", {}).items():
                (cwd / touched).parent.mkdir(parents=True, exist_ok=True)
                (cwd / touched).write_bytes(content.encode("utf-8"))
        # ("no_code": its trailer left out, as B-377's command that could not start Python.)
        output = action.get("output", "") + ("" if action.get("no_code") else
                                             f"\n<shellId: 0 completed with exit code "
                                             f"{action.get('exit', 0)}>")
        # (The keys 1.0.91 sends, measured 24 Oct 2026; a later one may send where it runs.)
        tool(call, action.get("tool", "powershell"), {"command": action["shell"]}, {
            "kind": "shell", "fullCommandText": action["shell"], "intention": "Run it",
            "commands": [{"identifier": action["shell"].split()[0],
                          "readOnly": action["readonly"]}] if "readonly" in action else [],
            "commandSegments": [],
            **({"shellType": action.get("shell_type", "powershell")}
               if action.get("shell_type", "") is not None else {}),
            "possiblePaths": action.get("paths", []),
            "possibleUrls": [{"url": url} for url in action.get("urls", [])],
            "hasWriteFileRedirection": bool(action.get("redirect")),
            "canOfferSessionApproval": True,
            **({"resolvedWorkingDirectory": action["cwd"]} if "cwd" in action else {})},
            action, run, output)
    elif "write" in action or "delete" in action:
        target = cwd / (action.get("write") or action["delete"])
        content = action.get("content", "")
        there = target.exists()
        before = {"path": str(target), "content": target.read_text(encoding="utf-8")} if (
            there) else None
        after = None if "delete" in action else {"path": str(target), "content": content}

        def write(target=target, content=content, gone="delete" in action) -> None:
            if gone:
                target.unlink()
                return
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content.encode("utf-8"))
        # (The keys 1.0.91 sends, measured 24 Oct 2026: no fileEdits.)
        request = {"kind": "write", "fileName": str(target),
                   "intention": "Edit file" if there else "Create file",
                   "diff": action.get("diff", f"@@ -1 +1 @@\n+{content}"),
                   "canOfferSessionApproval": True,
                   # (What it says the file will hold: not always what it writes.)
                   "newFileContents": action.get("contents", content)}
        if action.get("edits") is True:  # as a later version may say it
            request["fileEdits"] = [
                {k: v for k, v in (("before", before), ("after", after)) if v}]
        elif "edits" in action:
            request["fileEdits"] = action["edits"]
        if "resolved" in action:
            request["resolvedPath"] = str(cwd / action["resolved"])
        tool(call, "edit" if there else "create", {"path": str(target)}, request, action, write)
    elif "read" in action:
        target = cwd / action["read"]
        tool(call, "view", {"path": str(target)}, {
            "kind": "read", "path": str(target), "intention": f"Read file: {target}"},
            action, None, action.get("result", "contents"))
    elif "ask" in action:
        tool(call, action.get("tool", "other"), action.get("args", {}), action["ask"], action)
    elif "koloni" in action:
        name, arguments = action["koloni"], action.get("args", {})

        def call_koloni(name=name, arguments=arguments) -> None:
            answer = koloni("tools/call", {"name": name, "arguments": arguments})
            record["results"].append(answer.get("result", answer))
            save()
        tool(call, f"koloni-{name}", arguments, {
            "kind": "mcp", "serverName": "koloni", "toolName": name, "toolTitle": name,
            "readOnly": False, "args": arguments}, action, call_koloni,
            mcpServerName="koloni", mcpToolName=name)
    elif "request" in action:
        number_asked = next(numbers)
        send({"id": number_asked, "method": action["request"],
              "params": {"sessionId": "s1", **action.get("params", {})}})
        while (told := heard()).get("id") != number_asked or "method" in told:
            pass
        record["replies"].append({"method": action["request"], "answer": told})
        save()
    elif "pause" in action:
        time.sleep(action["pause"])
    elif "error" in action:
        event("session.error", {"errorType": "model", "message": action["error"]})
        event("session.idle", {})
        expect("never")
    elif "exit" in action:
        sys.stderr.write(action.get("stderr", "") + "\n")
        sys.exit(action["exit"])

event("assistant.usage", {"model": plan.get("model", "auto"), "inputTokens": 10})
for checkpoint in plan.get("usage", []):
    event("session.usage_checkpoint", checkpoint)
event("session.idle", {"aborted": True} if plan.get("aborted") else {})
expect("never")  # a headless server stays until it is ended
