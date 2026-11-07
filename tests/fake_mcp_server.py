"""A stand-in for an MCP server on stdio, driven by a plan.

FAKE_MCP_PLAN names a JSON file: {"record": path, ...}. It speaks JSON-RPC, one message a
line, as an MCP server does over stdio: `initialize`, `notifications/initialized`, `ping`,
`tools/list`, `tools/call`. Every time it starts, and every call it gets, is one JSON line
added to the record: {"event": "start", "cwd", "files", "env", "argv", "pid"}, {"event": "call",
"name", "arguments"}, {"event": "cancelled"}, {"event": "answer", "message"} (what the
client said to a request of the server's own).

Its tools:

    echo {"text"}     says the text back
    where             the folder it runs in, the names of KOLONİ's settings it can see, the
                      value of THE_SECRET and the arguments it was started with
    boom              a result that says it is an error
    picture           a line of text and an image
    big               300 000 characters
    hang              never answers (it goes on reading: it can be told it was cancelled)
    die               writes "fatal: gave up" to stderr and exits without an answer
    sample            asks the client for a model's answer (sampling/createMessage) first,
                      and says whether it was given one
    mkdir {"path"}    makes that folder (listed only through the plan's "more")

Plan options: "describe" ({tool: description} in place of its own), "without" (names it
does not list), "more" (further tools to list, as they are), "page" (so many tools to a
page of tools/list, the rest behind a cursor), "argv_on_stderr" (writes its arguments to
stderr and exits before it says hello).
"""

import json
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", newline="\n")
plan_file = Path(os.environ["FAKE_MCP_PLAN"])
plan = json.loads(plan_file.read_text(encoding="utf-8"))


def record(event: str, **more) -> None:
    with Path(plan["record"]).open("a", encoding="utf-8") as kept:
        kept.write(json.dumps({"event": event, **more}) + "\n")


def say(message: dict) -> None:
    print(json.dumps({"jsonrpc": "2.0", **message}), flush=True)


def heard() -> dict | None:
    line = sys.stdin.readline()
    return json.loads(line) if line else None


NOTHING = {"type": "object", "properties": {}}
TOOLS = [
    {"name": "echo", "description": "Says back what it is given.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}},
                     "required": ["text"]}},
    {"name": "where", "description": "Says where it runs.", "inputSchema": NOTHING},
    {"name": "boom", "description": "Fails.", "inputSchema": NOTHING},
    {"name": "picture", "description": "Shows a picture.", "inputSchema": NOTHING},
    {"name": "big", "description": "Says a great deal.", "inputSchema": NOTHING},
    {"name": "hang", "description": "Never answers.", "inputSchema": NOTHING},
    {"name": "die", "description": "Gives up.", "inputSchema": NOTHING},
    {"name": "sample", "description": "Asks for a model's answer.", "inputSchema": NOTHING},
]


def listed() -> list[dict]:
    now = json.loads(plan_file.read_text(encoding="utf-8"))  # the plan as it is at this read
    tools = [
        {**tool, "description": now.get("describe", {}).get(tool["name"], tool["description"])}
        for tool in TOOLS if tool["name"] not in now.get("without", [])
    ]
    return tools + now.get("more", [])


def text(said: str, **more) -> dict:
    return {"content": [{"type": "text", "text": said}], **more}


def call(name: str, arguments: dict) -> dict | None:
    if name == "echo":
        return text(f"echo: {arguments.get('text')}")
    if name == "mkdir":
        os.makedirs(arguments["path"], exist_ok=True)
        return text("made")
    if name == "where":
        return text(json.dumps({
            "cwd": os.getcwd(),
            "koloni": sorted(k for k in os.environ if k.upper().startswith("KOLONI_")),
            "secret": os.environ.get("THE_SECRET"),
            "argv": sys.argv[1:],
        }))
    if name == "boom":
        return text("it broke", isError=True)
    if name == "picture":
        return {"content": [{"type": "text", "text": "a caption"},
                            {"type": "image", "data": "AAAA", "mimeType": "image/png"}]}
    if name == "big":
        return text("x" * 300_000)
    if name == "hang":
        return None
    if name == "die":
        sys.stderr.write("fatal: gave up\n")
        sys.stderr.flush()
        sys.exit(3)
    if name == "sample":
        say({"id": "s1", "method": "sampling/createMessage", "params": {
            "messages": [{"role": "user", "content": {"type": "text", "text": "hello"}}],
            "maxTokens": 10}})
        while (told := heard()) is not None:
            if told.get("id") == "s1" and "method" not in told:
                record("answer", message=told)
                return text("sampled: error" if "error" in told else "sampled: result")
        sys.exit(0)
    return text(f"no tool named {name}", isError=True)


record("start", cwd=os.getcwd(), files=sorted(os.listdir()), env=dict(os.environ),
       argv=sys.argv[1:], pid=os.getpid())
if plan.get("argv_on_stderr"):
    sys.stderr.write(f"fatal: started with {' '.join(sys.argv[1:])}\n")
    sys.stderr.flush()
    sys.exit(3)
while (message := heard()) is not None:
    method, mid = message.get("method"), message.get("id")
    if method == "initialize":
        say({"id": mid, "result": {
            "protocolVersion": message.get("params", {}).get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake", "version": "1"}}})
    elif method == "ping":
        say({"id": mid, "result": {}})
    elif method == "tools/list":
        tools, size = listed(), plan.get("page")
        start = int(message.get("params", {}).get("cursor") or 0)
        end = start + size if size else len(tools)
        result = {"tools": tools[start:end]}
        if end < len(tools):
            result["nextCursor"] = str(end)
        say({"id": mid, "result": result})
    elif method == "tools/call":
        params = message.get("params", {})
        record("call", name=params.get("name"), arguments=params.get("arguments"))
        result = call(params.get("name"), params.get("arguments") or {})
        if result is not None:
            say({"id": mid, "result": result})
    elif method == "notifications/cancelled":
        record("cancelled")
    elif mid is not None and method:
        say({"id": mid, "error": {"code": -32601, "message": f"no method {method}"}})
time.sleep(0)  # stdin closed: the client is gone
