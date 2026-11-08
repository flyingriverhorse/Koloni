"""agy's PreToolUse hook for KOLONİ (slice 89e): it asks KOLONİ about one tool call.

agy runs it before every tool, with the call as JSON on stdin, and obeys the
{"decision", "reason"} it prints (measured on agy 1.3.3, 24 Oct 2026). It hands the call
to KOLONİ's door for this run - a loopback port that wants a key first, both read from the
JSON file named as its one argument ({"port", "key"}), as `mcp_bridge` reads its own - and
prints KOLONİ's answer. Anything else (no file, no door, no answer) is a deny and a
non-zero exit: either blocks the tool. Standard library only: it is started with a bare
interpreter.
"""

import json
import socket
import sys


def asked(call: object) -> dict:
    """KOLONİ's answer to one tool call: {"decision", "reason"}."""
    with open(sys.argv[1], encoding="utf-8") as config:
        told = json.load(config)
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": "approve", "arguments": call}}
    with socket.create_connection(("127.0.0.1", int(told["port"])), timeout=10) as door:
        door.settimeout(None)  # a card can stay open for as long as the user thinks
        door.sendall(str(told["key"]).encode("ascii") + b"\n"
                     + json.dumps(request).encode("utf-8") + b"\n")
        with door.makefile("rb") as answers:
            reply = next(one for one in map(json.loads, answers) if one.get("id") == 1)
    result = reply["result"]
    said = json.loads(result["content"][0]["text"])
    if result.get("isError") or said.get("decision") not in ("allow", "deny"):
        raise ValueError(f"KOLONİ answered no decision: {result}")
    return {"decision": said["decision"], "reason": str(said.get("reason") or "")}


def main() -> int:
    try:
        print(json.dumps(asked(json.loads(sys.stdin.buffer.read().decode("utf-8")))))
        return 0
    except Exception as exc:  # whatever it is, the tool does not run
        print(json.dumps({"decision": "deny", "reason": f"KOLONİ could not be asked: {exc!r}"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
