"""A stand-in for the claude and codex commands, driven by a plan file.

FAKE_CLI_PLAN names a JSON file: {"mode": ..., "answer": ..., "record": path}. The
script writes down how it was called (arguments, folder, what the folder holds,
stdin) and then behaves as the plan says.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

plan = json.loads(Path(os.environ["FAKE_CLI_PLAN"]).read_text(encoding="utf-8"))
if plan.get("spawn"):
    # Children at once, before anything is read - as a .cmd shim starts node (denetim-010 #5).
    # (Each ends by itself in 30 s, in case one got away.)
    kids = [subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL) for _ in range(plan["spawn"])]
    Path(plan["child_pid"]).write_text(" ".join(str(kid.pid) for kid in kids), encoding="utf-8")
argv = sys.argv[1:]
codex = "exec" in argv[:2]  # `codex exec`, or `codex --search exec`
stdin = sys.stdin.buffer.read().decode("utf-8")
cwd = Path.cwd()
Path(plan["record"]).write_text(json.dumps({
    "argv": argv,
    "cwd": str(cwd),
    "files": {f.name: f.read_text(encoding="utf-8") for f in cwd.iterdir() if f.is_file()},
    "stdin": stdin,
    "pid": os.getpid(),
    # Each picture given by its path (Codex's --image), as it was there.
    "images": [Path(argv[i + 1]).read_bytes().hex() for i, a in enumerate(argv) if a == "--image"],
    # Where it was pointed, whether with KOLONİ's stand-in token, and which keys it got.
    "sign_in": {"base_url": os.environ.get("ANTHROPIC_BASE_URL"),
                "placeholder": os.environ.get("ANTHROPIC_AUTH_TOKEN") == "koloni-local",
                **{name: os.environ.get(name) for name in (
                    "CLAUDE_CONFIG_DIR", "CODEX_HOME", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC")},
                **{name: name in os.environ for name in (
                    "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "OPENAI_API_KEY", "CODEX_API_KEY",
                    "CODEX_ACCESS_TOKEN", "CLAUDE_CODE_USE_BEDROCK")}},
}), encoding="utf-8")

mode = plan.get("mode", "ok")
if mode == "die":
    # It crashes, a child of its own still holding its output open (denetim-010 #3). (The
    # child ends by itself in 30 s.)
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                     stdout=sys.stdout, stderr=sys.stderr)
    os._exit(5)
if mode == "late_exit":
    # It got as far as starting up, then gave up with its reason on stderr.
    print(json.dumps({"type": "system", "subtype": "init"}), flush=True)
    sys.stderr.write("Error: the model gpt-nope does not exist\n")
    sys.exit(2)
if mode == "replay":
    # A recorded real stream, line for line; then it would go on working.
    sys.stdout.write(Path(plan["replay"]).read_text(encoding="utf-8"))
    sys.stdout.flush()
    time.sleep(120)
if mode == "exit":
    sys.stderr.write("warming up\nnot signed in: run the login command\n")
    sys.exit(3)
if mode == "garbage":
    print("this is not json")
    sys.exit(0)
if mode in ("hang", "hang_with_child"):
    if mode == "hang_with_child":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        Path(plan["child_pid"]).write_text(str(child.pid), encoding="utf-8")
    time.sleep(120)

answer = plan.get("answer", {"text": "hello", "tool_calls": []})
if codex:
    if mode == "reported_error":
        print(json.dumps({"type": "error", "message": "usage limit reached, try again later"}))
        sys.exit(1)
    print(json.dumps({"type": "thread.started", "thread_id": "t"}))
    # Measured 4 Nov 2026 (R182): every step run writes this as it starts, tried or not; and
    # one stderr line for each of its own tools its model tried, all off.
    print(json.dumps({"type": "item.completed", "item": {
        "id": "item_0", "type": "error",
        "message": "Code Mode is unavailable because code-mode host is disabled. Code mode will "
                   "fail closed; enable `features.code_mode_host` and install "
                   "`codex-code-mode-host`."}}))
    for _ in range(plan.get("refused", 0)):
        sys.stderr.write("2026-11-04T14:35:36.827041Z ERROR codex_core::tools::router: "
                         "error=code-mode host is disabled\n")
    if plan.get("searched"):
        # Measured on 10 Oct 2026: a search that really ran is an item of its own.
        print(json.dumps({"type": "item.completed", "item": {
            "id": "ws_1", "type": "web_search", "query": "q",
            "action": {"type": plan["searched"], "query": "q"}}}))
    print(json.dumps({"type": "item.completed",
                      "item": {"type": "agent_message", "text": "thinking about it"}}))
    print(json.dumps({"type": "item.completed",
                      "item": {"type": "agent_message", "text": json.dumps(answer)}}))
    if plan.get("usage", True):
        print(json.dumps({"type": "turn.completed",
                          "usage": {"input_tokens": 900, "cached_input_tokens": 100,
                                    "output_tokens": 30}}))
else:
    print(json.dumps({"type": "system", "subtype": "init", "tools": ["StructuredOutput"]}))
    if "limits" in plan:
        # Measured on 11 Oct 2026: every stream-json run says what is left of the plan.
        print(json.dumps({"type": "rate_limit_event", "rate_limit_info": plan["limits"]}))
    if mode == "native":
        # The model calls KOLONİ's tools as if they were its own; the real CLI would
        # answer "no such tool" and carry on for a long time.
        # The real stream has one event per content block, and the CLI answers each
        # call ("no such tool") before the next block of the same message arrives.
        usage = {"input_tokens": 50, "cache_read_input_tokens": 5, "output_tokens": 2}

        def block(message_id, content):
            print(json.dumps({"type": "assistant", "message": {
                "id": message_id, "usage": usage, "content": [content]}}), flush=True)

        def refused(call_id):
            print(json.dumps({"type": "user", "message": {"content": [{
                "type": "tool_result", "is_error": True, "tool_use_id": call_id,
                "content": "<tool_use_error>Error: No such tool available</tool_use_error>"}]}}),
                flush=True)

        block("msg_1", {"type": "thinking", "thinking": "..."})
        block("msg_1", {"type": "text", "text": "Editing now."})
        block("msg_1", {"type": "tool_use", "id": "toolu_1", "name": "edit_file",
                        "input": {"path": "hello.py", "old_string": "hi", "new_string": "hello"}})
        refused("toolu_1")
        block("msg_1", {"type": "tool_use", "id": "toolu_2", "name": "read_file",
                        "input": {"path": "hello.py"}})
        refused("toolu_2")
        time.sleep(0.4)
        # Told there is no such tool, it now tries something else: none of that counts.
        block("msg_2", {"type": "text", "text": "The tools are not available."})
        block("msg_2", {"type": "tool_use", "id": "toolu_3", "name": "write_file",
                        "input": {"path": "x", "content": "y"}})
        time.sleep(120)
    if mode == "reported_error":
        if "assistant_error" in plan:
            # The Agent SDK's assistant `error`: Claude Code's own word for why it failed.
            print(json.dumps({"type": "assistant", "message": {"content": []},
                              "error": plan["assistant_error"]}))
        print(json.dumps({"type": "result", "is_error": True,
                          "result": "Credit balance is too low"}))
        sys.exit(1)
    if plan.get("searched"):
        # Its search is a tool call of its own, answered in the stream.
        print(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "toolu_s", "name": plan["searched"],
             "input": {"query": "q"}}]}}))
        print(json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "toolu_s",
             "is_error": bool(plan.get("search_failed")), "content": "Web search results"}]}}))
    # Its own way of answering is a tool too; that one is not a request for KOLONİ.
    print(json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "toolu_0", "name": "StructuredOutput", "input": answer}]}}))
    result = {"type": "result", "is_error": False, "result": json.dumps(answer),
              "total_cost_usd": 0.5}
    if plan.get("structured", True):
        result["structured_output"] = answer
    if "model_usage" in plan:
        # Measured on 2026-10-06: the result names each model that took part.
        result["modelUsage"] = plan["model_usage"]
    if plan.get("usage", True):
        result["usage"] = {"input_tokens": 40, "cache_read_input_tokens": 60,
                           "cache_creation_input_tokens": 0, "output_tokens": 7}
    print(json.dumps(result))
