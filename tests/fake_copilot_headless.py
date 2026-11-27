"""A stand-in for `copilot --headless --stdio` (slice 89c): JSON-RPC with Content-Length
framing, as measured on Copilot CLI 1.0.91 (24 Oct 2026). Started any other way it is the
session-mode stand-in (`fake_copilot_cli.py`), which the same provider's talker uses.

FAKE_CLI_PLAN names a JSON file: {"record": path, "script": [...]}; "handshake" ("ping":
the ping is refused, "version": it speaks protocol 2, "create": session.create is
refused, "model": it is refused for its model, "tier": for its routing, "gone": it ends before answering, "silent": it never answers) makes the start go
wrong; "starts" names a file it adds each argv it is started with to. It writes down how
it was started, what session.create and session.send were given, and every answer KOLONİ
gave to a permission request ("answers"). Asked `status.get`, at any point, it says the plan's
"version" ("status_hang": no answer; "status_error": refused); a plain `--version` says the plan's
"updated" if it names one (the package Copilot updated itself to in the user's home, not the one
KOLONİ runs), else its "version". Its ping and `status.get` say the plan's "protocol" (default 3;
"handshake": "version" makes only the ping say 2). Asked `models.list`, at any point, it answers the plan's
"models" (none: []) and its "auto" (Auto's tiers, as 1.0.114 said them on 24 Nov 2026: test_copilot_offers.MEASURED_AUTO;
none: no "auto"), "models_error" refusing it, "models_hang" never answering it. Given no "koloni" MCP server in session.create, it opens no bridge. A
shell step's "{cwd}" in its output is the folder it works in. Asked `account.getQuota`, at any point, it answers
the plan's "quota" ("quota_hang": never); asked `auth.getStatus`, signed in by gh unless "signed_in" is false; asked
`sandbox.getHostSupport`, the plan's "sandbox" (a shell step's "sandboxed": it ran in it). Its session
made on auto (or fusion), "picked" is the model it picks, said with "picked_why" before its first step. Steps:

    {"say": "text"}                                   an assistant message
    {"shell": "pytest -q", "output": "ok", "exit": 0} a command, run only once approved
                                                      ("touches": files it writes;
                                                      "no_code": no exit code trailer)
    {"write": "a.py", "content": "x"}                 a file written once approved (its
                                                      tool "create", or "edit" if it is there)
    {"read": ".env", "result": "..."}                 its view tool, run once approved
    {"patch": "*** Begin Patch\n..."}                its apply_patch (1.0.105, non-Claude models):
                                                      the patch's text as its arguments, call id
                                                      "custom_call_N", one write request with a
                                                      fileEdit a file; each file written once
                                                      approved (what a file will hold: its "+"
                                                      and " " lines, a whole-file hunk)
    {"ask": {"kind": "url", ...}, "tool": "web_fetch"} any other permission request
    {"tool_call": "view", "args": {...}}              any tool of its own by name (no request but
                                                      its hook's; "native": a request it also sends)
    {"koloni": "read_notes", "args": {}}              a call to KOLONİ's MCP server, for real
    {"request": "userInput.request", "params": {}}    a JSON-RPC request of its own
    {"pause": s} / {"error": "message"} / {"exit": 3, "stderr": ".."}
    {"event": "assistant.usage", "data": {...}}       any event of its session, as it is ("agent":
                                                      with that agentId, never said to start)
    {"task": "koloni-checker", "mode": "sync", "steps": [...], "result": "its report"}
                                                      its task tool (0.1.11, measured on 1.0.114):
                                                      asked as any tool; once let through, a
                                                      sub-agent of its own ("agent": its agentId,
                                                      default "agent-<call>") runs "steps" - each
                                                      event, hook and request of them with that
                                                      agentId (a hook's input names it, its type
                                                      and its parent; its sessionId the agent's) -
                                                      between subagent.started (toolCallId the
                                                      task call's, "started_call": false none,
                                                      or another named) and subagent.completed
                                                      ("failed": subagent.failed); then the
                                                      task call ends with "result". "args": more
                                                      of its arguments; "as": the agentName and
                                                      agentType its start says (default the
                                                      task's).

A step with "unasked" runs without a permission request; "twice": the same request is
sent again under a new request id; "no_complete": a rejected tool is never said to be done;
"hooked": a hook of its own answered the request; "unapplied": it says it did not take
KOLONİ's answer; "bypass": the request asks to go outside its sandbox, for that reason. A shell step's "paths", "urls" and "redirect" are its possiblePaths,
possibleUrls and hasWriteFileRedirection; "readonly", the readOnly of its one `commands`
entry (else none); "cwd" is where it says it runs (1.0.91 says nothing of that); "shell_type" its
shellType ("powershell"; null: none said); "args", more arguments of its tool call (a "shellId"
names a shell to run in); "parent", a parentToolCallId on its start. A step's "start": its
tool.execution_start comes "after" KOLONİ answered its request, or "none" at all (else before
it, as Copilot 1.0.67's agent loop sends it). A write ("delete": the file goes) has no fileEdits, as on 1.0.91, unless
"edits" gives them (true: what it will hold); "contents" is its newFileContents,
"resolved" its resolvedPath, "diff" its diff.
The plan's "aborted": its turn ends aborted. The plan's "usage": the data of each
session.usage_checkpoint it sends, in order, before its turn ends (none: none sent); its
"usage_info", of each session.usage_info (measured live on 1.0.114, 24 Nov 2026: tokenLimit,
currentTokens, systemTokens, conversationTokens, toolDefinitionsTokens, messagesLength,
isInitial); its "call_usage", its one assistant.usage's (default {"inputTokens": 10}); its
"compaction", the data of one session.compaction_complete, sent before them.

Sessions (1.0.114, measured 23 Nov 2026): a new one is named the plan's "session_id" (default
"s1"); its events are written to its home's `session-state/<id>/events.jsonl` once it is sent its
prompt. Asked `session.resume` (kept in "resume", as session.create's in "create") it goes on in
the one named where that file is in its home, else refuses it ("Session not found"); with the
plan's "resume_as" it says it went on in that session instead.

Protocol 4 (1.0.114, measured 20 Nov 2026): session.create may come grouped (KOLONİ's bridge
under mcp.servers). Given hooks (grouped `hooks.hasHandlers`, flat `hooks: true`) it asks the
client `hooks.invoke`: sessionStart after session.send, and preToolUse for each tool after its
tool.execution_start ({cwd, sessionId, timestamp in ms, toolName, toolArgs, toolCallId}; the
plan's "hook_session" names another session), each kept in "hooks". The hook's answer, under
`output`: "ask" sends a permission request of kind "hook" (its toolArgs the modified ones, or
the original with a step's "hook_shows": "original"; "then_native": its normal request follows
for the same toolCallId, a shell's naming "native_command" if given); "allow" runs it unasked;
"deny" denies it; an error, or an output that is no object, denies it as a hook that errored;
nothing said (`{}`, an answer not under `output`) fails OPEN, as Copilot does: today's flow,
where a "quiet" shell step runs unasked (1.0.114 asks no read-only command). What runs is the
modified arguments: each command run is kept in "ran". A shell's completion says its exit code
in shellExecution ("no_code": none); "trailer": false leaves out its `<shellId...>` line.
"""

import json
import os
import re
import runpy
import subprocess
import sys
import time
from pathlib import Path

told = (
    json.loads(Path(os.environ["FAKE_CLI_PLAN"]).read_text(encoding="utf-8"))
    if os.environ.get("FAKE_CLI_PLAN")
    else {}
)
if told.get("starts"):  # every way it was started, one line each
    with open(told["starts"], "a", encoding="utf-8") as log:
        log.write(json.dumps(sys.argv[1:]) + "\n")
if "--version" in sys.argv[1:]:  # the plan's "version", if it names one
    print(f"GitHub Copilot CLI {told.get('updated', told.get('version', '1.0.91-fake'))}.")
    sys.exit(0)
if "--headless" not in sys.argv[1:]:
    runpy.run_path(str(Path(__file__).with_name("fake_copilot_cli.py")), run_name="__main__")
    sys.exit(0)

plan = json.loads(Path(os.environ["FAKE_CLI_PLAN"]).read_text(encoding="utf-8"))
argv = sys.argv[1:]
cwd = Path.cwd()
home = os.environ.get("COPILOT_HOME")
record = {
    "argv": argv,
    "cwd": str(cwd),
    "results": [],
    "answers": [],
    "replies": [],
    "hooks": [],
    "ran": [],
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
    while (told := framed()).get("method") in ("account.getQuota", "status.get", "models.list"):
        if told["method"] == "models.list":
            record["models_asked"] = True
            save()
            if "models_error" in plan:
                send({"id": told["id"], "error": {"code": -32603, "message": plan["models_error"]}})
            elif not plan.get("models_hang"):
                auto = {"auto": plan["auto"]} if "auto" in plan else {}
                send({"id": told["id"], "result": {"models": plan.get("models", []), **auto}})
            continue
        if told["method"] == "status.get":  # (its package's version: 1.0.67's app.js, `Vbo`)
            if plan.get("status_error"):
                send({"id": told["id"], "error": {"code": -32601, "message": "Unhandled method"}})
            elif not plan.get("status_hang"):
                send(
                    {
                        "id": told["id"],
                        "result": {
                            "version": plan.get("version", "1.0.91-fake"),
                            "protocolVersion": plan.get("protocol", 3),
                        },
                    }
                )
            continue
        # What is left of its plan, no turn (1.0.91, 24 Oct 2026), whenever it is asked -
        # alone or after a session's turn (89l): the plan's "quota" (none: refused), its
        # "quota_error" refusing it, or with "quota_hang" no answer at all.
        record["quota_asked"] = told.get("params")
        save()
        if plan.get("quota_hang"):
            continue
        if "quota_error" in plan or "quota" not in plan:
            send(
                {
                    "id": told["id"],
                    "error": {"code": -32603, "message": plan.get("quota_error", "no quota")},
                }
            )
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


SID = plan.get("session_id", "s1")  # (the session's: the one it goes on in, once resumed)
# The sub-agents of its own at work (its task tool), the innermost last, each with its type: the
# events of the innermost carry its agentId, its hooks name it (measured on 1.0.114, 27 Nov 2026).
AGENTS: list[dict] = []


def event(kind: str, data: dict) -> None:
    send(
        {
            "method": "session.event",
            "params": {
                "sessionId": SID,
                "event": {
                    "id": f"e{next(numbers)}",
                    "timestamp": "2026-10-24T00:00:00Z",
                    "type": kind,
                    "data": data,
                    **({"agentId": AGENTS[-1]["id"]} if AGENTS else {}),
                },
            },
        }
    )


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
send(
    {
        "id": started["id"],
        "result": {
            "message": "pong",
            "timestamp": "2026-10-24T00:00:00Z",
            "protocolVersion": 2 if handshake == "version" else plan.get("protocol", 3),
        },
    }
)
told = heard()  # (an account.getQuota alone is answered there; then it is ended)
if told.get("method") == "auth.getStatus":
    # Whether it is signed in, no turn (1.0.103, 24 Oct 2026): the plan's "signed_in"
    # (default yes), by gh's login, with whose account it is in its statusMessage.
    record["status_asked"] = told.get("params")
    save()
    signed_in = plan.get("signed_in", True)
    send(
        {
            "id": told["id"],
            "result": {
                "isAuthenticated": signed_in,
                "authType": "gh-cli" if signed_in else None,
                "statusMessage": f"Logged in as {ACCOUNT['login']}"
                if signed_in
                else "Not logged in",
                **({"login": ACCOUNT["login"]} if signed_in else {}),
            },
        }
    )
    expect("never")
if told.get("method") == "sandbox.getHostSupport":
    # What this machine can sandbox (1.0.103, 24 Oct 2026, by REA): the plan's "sandbox",
    # else a sandbox that denies paths; "unknown": a Copilot that has no such method.
    record["sandbox_asked"] = True
    save()
    support = plan.get(
        "sandbox",
        {"supported": True, "capabilities": [{"name": "denied_paths", "supported": True}]},
    )
    send(
        {
            "id": told["id"],
            **(
                {"error": {"code": -32601, "message": "Unhandled method"}}
                if support == "unknown"
                else {"result": support}
            ),
        }
    )
    told = heard()
while told.get("method") not in ("session.create", "session.resume"):
    told = heard()
create = told
record["create" if told["method"] == "session.create" else "resume"] = create["params"]
save()
if told["method"] == "session.resume":
    asked_for = str(create["params"].get("sessionId"))
    if not (Path(home or cwd) / "session-state" / asked_for / "events.jsonl").is_file():
        send(
            {
                "id": create["id"],
                "error": {
                    "code": -32603,
                    "message": "Failed to load session events: Session not found",
                },
            }
        )
        expect("never")
    SID = plan.get("resume_as", asked_for)
if handshake == "create":
    send({"id": create["id"], "error": {"code": -32602, "message": "unknown field mcpServers"}})
    expect("never")
if (
    handshake == "model"
):  # the message seen live for a model not on the account (B-176, B-179); code a guess
    model = create["params"].get("model")
    send(
        {
            "id": create["id"],
            "error": {
                "code": -32603,
                "message": (
                    f'Request session.create failed with message: Model "{model}" is not available.'
                ),
            },
        }
    )
    expect("never")
if handshake == "tier":  # the message seen live for Fusion High on a plan without it (21 Nov 2026)
    send(
        {
            "id": create["id"],
            "error": {
                "code": -32603,
                "message": (
                    "Request session.create failed with message: session construction failed: model "
                    'resolution leaf failed: Auto preference "hydrafusion" is disabled: This tier is not '
                    "available for the user's Copilot plan.; choose an enabled Auto preference or another "
                    "model"
                ),
            },
        }
    )
    expect("never")
send(
    {
        "id": create["id"],
        "result": {
            "sessionId": SID,
            "workspacePath": str(Path(home or cwd) / "session-state" / SID),
            "authInfo": ACCOUNT,
        },
    }
)
asked = expect("session.send")
record["prompt"] = asked["params"].get("prompt")
save()
send({"id": asked["id"], "result": {"messageId": "m1"}})
if home:  # (its events, where a resume finds them)
    kept = Path(home) / "session-state" / SID
    kept.mkdir(parents=True, exist_ok=True)
    with open(kept / "events.jsonl", "a", encoding="utf-8") as events:
        print(json.dumps({"prompt": record["prompt"]}), file=events)
event("session.start", {"sessionId": SID, "context": {"cwd": str(cwd)}})
made = create["params"]
hooks_on = made.get("hooks") is True or (
    isinstance(made.get("hooks"), dict) and made["hooks"].get("hasHandlers") is True
)


def invoke(hook_type: str, more: dict) -> dict:
    """Ask the client's hook, as Copilot does (a request of its own); its answer, kept."""
    number, session_id = next(numbers), plan.get("hook_session", SID)
    given = {"cwd": str(cwd), "sessionId": session_id, "timestamp": int(time.time() * 1000), **more}
    if AGENTS:  # (a sub-agent's: its own id as its input's sessionId, measured)
        given = {
            **given,
            "sessionId": AGENTS[-1]["id"],
            "agentId": AGENTS[-1]["id"],
            "agentType": AGENTS[-1]["type"],
            "parentAgentId": session_id,
        }
    send(
        {
            "id": number,
            "method": "hooks.invoke",
            "params": {"sessionId": session_id, "hookType": hook_type, "input": given},
        }
    )
    while (told := heard()).get("id") != number or "method" in told:
        pass
    record["hooks"].append(
        {"hookType": hook_type, "input": given, "answer": told, "answered_at": time.time()}
    )
    save()
    return told


if hooks_on:
    invoke("sessionStart", {"source": "new", "initialPrompt": record["prompt"]})
if plan.get("picked") and create["params"].get("model") in ("auto", "fusion"):
    plan["model"] = plan["picked"]
    event(
        "session.auto_mode_resolved",
        {"chosenModel": plan["picked"], "selectionReason": plan.get("picked_why")},
    )
spec = (made.get("mcpServers") or made.get("mcp", {}).get("servers") or {}).get("koloni")
bridge = (
    subprocess.Popen(
        [spec["command"], *spec["args"]], stdin=subprocess.PIPE, stdout=subprocess.PIPE
    )
    if spec
    else None
)


def koloni(method: str, params: dict) -> dict:
    """Talk to KOLONİ's tool server the way Copilot would: through the bridge it was given."""
    assert bridge is not None and bridge.stdin is not None and bridge.stdout is not None
    bridge.stdin.write(
        (
            json.dumps({"jsonrpc": "2.0", "id": next(numbers), "method": method, "params": params})
            + "\n"
        ).encode()
    )
    bridge.stdin.flush()
    line = bridge.stdout.readline()
    if not line:
        raise SystemExit("the tool server closed the connection")
    return json.loads(line)


if bridge:
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
        event(
            "permission.requested",
            {
                "requestId": request_id,
                "permissionRequest": {"toolCallId": call, **request},
                **({"resolvedByHook": True} if action.get("hooked") else {}),
            },
        )
        if action.get("hooked"):  # a hook of its own said yes: nobody else is asked
            return True
        answer = expect("session.permissions.handlePendingPermissionRequest")
        params = answer["params"]
        assert params["sessionId"] == SID and params["requestId"] == request_id
        record["answers"].append({"kind": request["kind"], "result": params["result"]})
        save()
        # ("unapplied": it says it did not take the answer)
        send({"id": answer["id"], "result": {"success": not action.get("unapplied")}})
        if action.get("unapplied"):
            expect("never")
        event(
            "permission.completed",
            {"requestId": request_id, "toolCallId": call, "result": {"kind": "approved"}},
        )
        approved = params["result"].get("kind") == "approve-once"
    return approved


def pre_tool(call: str, name: str, arguments: object) -> tuple[str | None, object, str]:
    """Its preToolUse hook, where the client has hooks: (its decision, the arguments the tool
    runs with, why). None: it said nothing, and today's flow goes on (failing open)."""
    if not hooks_on:
        return None, arguments, ""
    told = invoke("preToolUse", {"toolName": name, "toolArgs": arguments, "toolCallId": call})
    result = told.get("result")
    if "error" in told or not isinstance(result, dict):
        return "errored", arguments, ""
    if "output" not in result or result["output"] is None:
        return None, arguments, ""  # (a flat answer was ignored, measured)
    output = result["output"]
    if not isinstance(output, dict):
        return "errored", arguments, ""
    decision = output.get("permissionDecision")
    return (
        decision if decision in ("allow", "deny", "ask") else None,
        # (a sub-agent's command is not modified: measured on 1.0.114, C6)
        arguments if AGENTS else output.get("modifiedArgs", arguments),
        str(output.get("permissionDecisionReason") or ""),
    )


def patched(text: str) -> list[list]:
    """Each file a patch names, what it will hold (None: it goes) and where it moves to (None:
    nowhere)."""
    files: list[list] = []
    for line in text.split("\n"):
        header = re.fullmatch(r"\*\*\* (Add|Update|Delete) File: (.+)", line)
        if header:
            files.append([header[2], None if header[1] == "Delete" else "", None])
        elif files and line.startswith("*** Move to: "):
            files[-1][2] = line[len("*** Move to: ") :]
        elif files and files[-1][1] is not None and line[:1] in ("+", " "):
            files[-1][1] += line[1:] + "\n"
    return files


def tool(
    call: str,
    name: str,
    arguments: dict | str,
    request: dict | None,
    action: dict,
    work=None,
    result: str = "done",
    shell: int | None = None,
    **start,
) -> None:
    began = {"toolCallId": call, "toolName": name, "arguments": arguments, **start}
    if action.get("start") not in ("after", "none"):
        event("tool.execution_start", began)
    if request is not None and "bypass" in action:  # (its reason, as the SDK types it)
        request = {
            **request,
            "requestSandboxBypass": True,
            "requestSandboxBypassReason": action["bypass"],
        }
    decision, ran, why = pre_tool(call, name, arguments)
    refused = "The user rejected this tool call."
    if decision == "ask":
        approved = permitted(
            call,
            {
                "kind": "hook",
                "toolName": name,
                "toolArgs": arguments if action.get("hook_shows") == "original" else ran,
                "hookMessage": why or f"Allow {name}?",
                "workingDirectory": str(cwd),
            },
            action,
        )
        if approved and action.get("then_native") and request is not None:
            if request["kind"] == "shell":
                request = {
                    **request,
                    "fullCommandText": action.get(
                        "native_command", ran.get("command") if isinstance(ran, dict) else None
                    ),
                }
            approved = permitted(call, request, {})
        refused = "Denied by user via preToolUse hook prompt: rejected"
    elif decision in ("deny", "errored"):
        approved = False
        refused = (
            "Denied by preToolUse hook (hook errored)"
            if decision == "errored"
            else f"Denied by preToolUse hook: {why}"
        )
    else:
        approved = (
            decision == "allow"
            or request is None
            or bool(action.get("quiet"))
            or (permitted(call, request, action))
        )
    if action.get("start") == "after":
        event("tool.execution_start", began)
    if not approved:
        if not action.get("no_complete"):  # (with it: never a word that it is done)
            event(
                "tool.execution_complete",
                {"toolCallId": call, "success": False, "error": {"message": refused}},
            )
        return
    if isinstance(ran, dict) and "command" in ran:
        record["ran"].append(ran["command"])
        save()
    if work:
        work()
    # ("sandboxed": it ran in its sandbox, as REA saw 1.0.103 say it)
    event(
        "tool.execution_complete",
        {
            "toolCallId": call,
            "success": True,
            "result": {"content": result},
            **({"toolTelemetry": {"sandboxApplied": True}} if action.get("sandboxed") else {}),
            **({"shellExecution": {"exitCode": shell}} if shell is not None else {}),
        },
    )


def flat(script: list) -> list:
    """The script with each task's steps between its begin and its end, which share one dict."""
    steps: list = []
    for one in script:
        if "task" in one:
            mark = {"task_of": one}
            steps += [{"task_begin": mark}, *flat(one.get("steps", [])), {"task_end": mark}]
        else:
            steps.append(one)
    return steps


skipped = None  # (a task refused: its steps, to its end, never run)
after_idle: list[dict] = []  # (C2: the user.message of a send it takes after its idle)
for number, action in enumerate(flat(plan.get("script", []))):
    call = f"call_{number}"
    if skipped is not None:
        skipped = None if action.get("task_end") is skipped else skipped
        continue
    event("model.call_start", {"turnId": str(number), "model": plan.get("model", "auto")})
    if "say" in action:
        event(
            "assistant.message",
            {"messageId": f"m{number}", "content": action["say"], "toolRequests": []},
        )
    elif "await_send" in action:
        # A session.send while its turn runs (1.0.114, 27 Nov 2026: with mode "immediate" it is
        # taken into the running work): answered with its message's id; "sent" on record. C2,
        # measured: then a user.message naming that id, before its idle - "taken": "after_idle"
        # after it (a turn of its own), false never.
        told = expect("session.send")
        record.setdefault("sent", []).append(told.get("params"))
        save()
        send({"id": told["id"], "result": {"messageId": f"sent{number}"}})
        said = {"content": told["params"].get("prompt"), "messageId": f"sent{number}"}
        taken = action.get("taken", True)
        if taken is True:
            event("user.message", said)
        elif taken == "after_idle":
            after_idle.append(said)
    elif "shell" in action:

        def run(action=action) -> None:
            for touched, content in action.get("touches", {}).items():
                (cwd / touched).parent.mkdir(parents=True, exist_ok=True)
                (cwd / touched).write_bytes(content.encode("utf-8"))

        # ("no_code": its trailer left out, as B-377's command that could not start Python.)
        output = action.get("output", "").replace("{cwd}", str(cwd)) + (
            ""
            if action.get("no_code") or action.get("trailer") is False
            else f"\n<shellId: 0 completed with exit code {action.get('exit', 0)}>"
        )
        # (The keys 1.0.91 sends, measured 24 Oct 2026; a later one may send where it runs.)
        tool(
            call,
            action.get("tool", "powershell"),
            {"command": action["shell"], **action.get("args", {})},
            {
                "kind": "shell",
                "fullCommandText": action["shell"],
                "intention": "Run it",
                "commands": [
                    {"identifier": action["shell"].split()[0], "readOnly": action["readonly"]}
                ]
                if "readonly" in action
                else [],
                "commandSegments": [],
                **(
                    {"shellType": action.get("shell_type", "powershell")}
                    if action.get("shell_type", "") is not None
                    else {}
                ),
                "possiblePaths": action.get("paths", []),
                "possibleUrls": [{"url": url} for url in action.get("urls", [])],
                "hasWriteFileRedirection": bool(action.get("redirect")),
                "canOfferSessionApproval": True,
                **({"resolvedWorkingDirectory": action["cwd"]} if "cwd" in action else {}),
            },
            action,
            run,
            output,
            None if action.get("no_code") else action.get("exit", 0),
            **({"parentToolCallId": action["parent"]} if "parent" in action else {}),
        )
    elif "write" in action or "delete" in action:
        target = cwd / (action.get("write") or action["delete"])
        content = action.get("content", "")
        there = target.exists()
        before = (
            {"path": str(target), "content": target.read_text(encoding="utf-8")}
            if (there)
            else None
        )
        after = None if "delete" in action else {"path": str(target), "content": content}

        def write(target=target, content=content, gone="delete" in action) -> None:
            if gone:
                target.unlink()
                return
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content.encode("utf-8"))

        # (The keys 1.0.91 sends, measured 24 Oct 2026: no fileEdits.)
        request = {
            "kind": "write",
            "fileName": str(target),
            "intention": "Edit file" if there else "Create file",
            "diff": action.get("diff", f"@@ -1 +1 @@\n+{content}"),
            "canOfferSessionApproval": True,
            # (What it says the file will hold: not always what it writes.)
            "newFileContents": action.get("contents", content),
        }
        if action.get("edits") is True:  # as a later version may say it
            request["fileEdits"] = [{k: v for k, v in (("before", before), ("after", after)) if v}]
        elif "edits" in action:
            request["fileEdits"] = action["edits"]
        if "resolved" in action:
            request["resolvedPath"] = str(cwd / action["resolved"])
        tool(call, "edit" if there else "create", {"path": str(target)}, request, action, write)
    elif "patch" in action:
        files = patched(action["patch"])
        edits = [
            {
                k: v
                for k, v in (
                    (
                        "before",
                        {"path": str(cwd / path), "content": (cwd / path).read_text("utf-8")}
                        if (cwd / path).exists()
                        else None,
                    ),
                    (
                        "after",
                        None if content is None else {"path": str(cwd / path), "content": content},
                    ),
                )
                if v
            }
            for path, content, _to in files
        ]

        def apply(files=files) -> None:
            for path, content, to in files:
                if content is None or to:
                    (cwd / path).unlink()
                if content is not None:
                    (cwd / (to or path)).parent.mkdir(parents=True, exist_ok=True)
                    (cwd / (to or path)).write_bytes(content.encode("utf-8"))

        tool(
            f"custom_{call}",
            "apply_patch",
            action["patch"],
            {
                "kind": "write",
                "fileName": str(cwd / files[0][0]),
                "intention": "Apply patch",
                "diff": action["patch"],
                "canOfferSessionApproval": True,
                "fileEdits": edits,
            },
            action,
            apply,
            f"Modified {len(files)} file(s)",
        )
    elif "read" in action:
        target = cwd / action["read"]
        tool(
            call,
            "view",
            {"path": str(target)},
            {"kind": "read", "path": str(target), "intention": f"Read file: {target}"},
            action,
            None,
            action.get("result", "contents"),
        )
    elif "ask" in action:
        tool(call, action.get("tool", "other"), action.get("args", {}), action["ask"], action)
    elif "tool_call" in action:
        tool(
            call,
            action["tool_call"],
            action.get("args", {}),
            action.get("native"),
            action,
            None,
            action.get("result", "done"),
        )
    elif "koloni" in action:
        name, arguments = action["koloni"], action.get("args", {})

        def call_koloni(name=name, arguments=arguments) -> None:
            answer = koloni("tools/call", {"name": name, "arguments": arguments})
            record["results"].append(answer.get("result", answer))
            save()

        tool(
            call,
            f"koloni-{name}",
            arguments,
            {
                "kind": "mcp",
                "serverName": "koloni",
                "toolName": name,
                "toolTitle": name,
                "readOnly": False,
                "args": arguments,
            },
            action,
            call_koloni,
            mcpServerName="koloni",
            mcpToolName=name,
        )
    elif "request" in action:
        number_asked = next(numbers)
        send(
            {
                "id": number_asked,
                "method": action["request"],
                "params": {"sessionId": SID, **action.get("params", {})},
            }
        )
        while (told := heard()).get("id") != number_asked or "method" in told:
            pass
        record["replies"].append({"method": action["request"], "answer": told})
        save()
    elif "pause" in action:
        time.sleep(action["pause"])
    elif "error" in action:
        event(
            "session.error",
            {"errorType": action.get("error_type", "model"), "message": action["error"]},
        )
        event("session.idle", {})
        expect("never")
    elif "exit" in action:
        sys.stderr.write(action.get("stderr", "") + "\n")
        sys.exit(action["exit"])
    elif "event" in action:
        # ("agent": as a sub-agent's of its own, one never said to start)
        ghost = [{"id": action["agent"], "type": ""}] if "agent" in action else []
        AGENTS.extend(ghost)
        event(action["event"], action.get("data", {}))
        del AGENTS[len(AGENTS) - len(ghost) :]
    elif "task_begin" in action:
        mark = action["task_begin"]
        task, mark["call"] = mark["task_of"], call
        # (its arguments as measured on 1.0.114, C5: `name` its own must)
        given = {
            "description": task.get("description", "Look it over"),
            "prompt": task.get("prompt", "Read hello.py and say what it prints."),
            "agent_type": task["task"],
            "name": task["task"],
            **({"mode": task["mode"]} if "mode" in task else {}),
            **task.get("args", {}),
        }
        event("tool.execution_start", {"toolCallId": call, "toolName": "task", "arguments": given})
        decision, _ran, _why = pre_tool(call, "task", given)
        hooked_task = {"kind": "hook", "toolName": "task", "toolArgs": given, "hookMessage": "?"}
        if decision != "ask" or not permitted(call, hooked_task, task):
            event(
                "tool.execution_complete",
                {"toolCallId": call, "success": False, "error": {"message": "rejected"}},
            )
            skipped = mark
            continue
        named = task.get("started_call", call)
        AGENTS.append({"id": task.get("agent", f"agent-{call}"), "type": task["task"]})
        event(
            "subagent.started",
            {
                **({"toolCallId": named} if named else {}),
                "agentName": task.get("as", task["task"]),
                "agentType": task.get("as", task["task"]),
                "agentDisplayName": task["task"],
                "agentDescription": "",
                "executionMode": "sync",
                "model": plan.get("model", "auto"),
            },
        )
    elif "task_end" in action:
        task = action["task_end"]["task_of"]
        event(
            "subagent.failed" if task.get("failed") else "subagent.completed",
            {"agentName": task["task"]},
        )
        AGENTS.pop()
        event(
            "tool.execution_complete",
            {
                "toolCallId": action["task_end"]["call"],
                "success": True,
                "result": {"content": task.get("result", "its report")},
            },
        )

event(
    "assistant.usage",
    {"model": plan.get("model", "auto"), **plan.get("call_usage", {"inputTokens": 10})},
)
if "compaction" in plan:
    event("session.compaction_complete", plan["compaction"])
for info in plan.get("usage_info", []):
    event("session.usage_info", info)
for checkpoint in plan.get("usage", []):
    event("session.usage_checkpoint", checkpoint)
event("session.idle", {"aborted": True} if plan.get("aborted") else {})
for said in after_idle:
    event("user.message", said)
expect("never")  # a headless server stays until it is ended
