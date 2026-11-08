"""A stand-in for `codex app-server`: JSON-RPC lines on stdin and stdout, as measured on
11 Oct 2026. FAKE_APP_SERVER says how it behaves: nothing (it answers), "hang" (it never
answers the read), "refuse" (it answers the read with an error), "gone" (it ends before
answering), "loud" (more notifications than anyone reads, then the answer). What it answers
also says how it was started; FAKE_APP_SERVER_STARTED names a file it adds its process id to.

With FAKE_CLI_PLAN it is Codex working natively instead (`native`).
"""

import json
import os
import subprocess
import sys
import time
import tomllib
from pathlib import Path

mode = os.environ.get("FAKE_APP_SERVER", "")
WINDOW = {"usedPercent": 7, "windowDurationMins": 10080, "resetsAt": int(time.time()) + 86400}
LIMITS = {"limitId": "codex", "primary": WINDOW, "secondary": None,
          "credits": {"hasCredits": True, "unlimited": False, "balance": "49675.89"},
          "planType": "pro", "rateLimitReachedType": None}
# What `account/updated` carries: nobody's business but the account's (`native`).
ACCOUNT = {"authMode": "chatgpt", "planType": "pro", "email": "someone@example.com",
           "accountId": "acct-4711-not-for-koloni"}
RUN_ASKED = "item/commandExecution/requestApproval"
PATCH_ASKED = "item/fileChange/requestApproval"


def say(message: dict) -> None:
    print(json.dumps({"jsonrpc": "2.0", **message}), flush=True)


def die(code: int) -> None:
    """It crashes, a child of its own still holding its output open (denetim-010 #3). (The
    child ends by itself in 30 s.)"""
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                     stdout=sys.stdout, stderr=sys.stderr)
    sys.stdout.flush()
    os._exit(code)


def native() -> None:  # noqa: C901
    """One thread and one turn, as Codex works natively for KOLONİ (slice 89a). FAKE_CLI_PLAN
    names a JSON file: {"record": path, "script": [...]}; "handshake" ("initialize",
    "thread", "policy", "gone"; "reviewer", "wider", "network", "full": its thread is not
    what was asked for) makes the start go wrong. It writes down how it was
    started and asked ("stdin" is the turn's text, which `codex exec` read on stdin), and
    each answer it got to a request of its own ("answers"). Steps of the script:

        {"say": "text"}                                  an agent message ("phase": its phase)
        {"run": "pytest", "output": "ok\\n", "exit": 0}   a command, done only when accepted
                                                         ("delta": what it prints first;
                                                         "hold": seconds; "touches" and
                                                         "removes": files it changes;
                                                         "die": an exit code - it crashes
                                                         once the command started, `die`)
        {"write": "a.py", "content": "x"}                a patch, applied only when accepted
                                                         ("kind"; "also": more files by
                                                         absolute path, same content)
        {"write_abs": "C:/elsewhere/x.txt", ...}         the same, by absolute path
        {"delete": "a.py"}                               a patch that deletes a file
        {"mcp": {"server": "s", "tool": "t", ...}}       a call to one of its own MCP servers
        {"web": "query"}                                 a web search
        {"koloni": "ask_user", "args": {...}}            a call to KOLONİ's MCP server, for real
        {"request": "item/tool/requestUserInput", "params": {...}}  another request of its own
        {"pause": s} / {"hang": true} / {"exit": 3, "stderr": ".."} / {"error": "message"}
        {"await_steer": true}                            it waits for a turn/steer ("steers")
                                                         not yet awaited - one that came while
                                                         it read for something else counts
        {"wait_for": "path"}                             it goes on once that file is there
        {"context": 34000, "window": 100000}             thread/tokenUsage/updated: its last
                                                         request's input, of that window
        {"plan": [{"step": "..", "status": "inProgress"}]}  turn/plan/updated
                                                         (both: "thread", another thread's)

    A run or a patch with "unasked" is not asked about; "thread": it is asked from that
    thread (one of its own agents'); "no_start": no item/started;
    "reason": the request says why; "twice": it is asked twice. A run's "cwd": where it is
    said to run. A patch's "grows": a file it adds once allowed (item/fileChange/patchUpdated).
    Every MCP tool call is asked first (mcpServer/elicitation/request): KOLONİ's always, a
    server's of its own with "elicit".
    """
    plan = json.loads(Path(os.environ["FAKE_CLI_PLAN"]).read_text(encoding="utf-8"))
    argv = sys.argv[1:]
    cwd = Path.cwd()
    record = {"argv": argv, "cwd": str(cwd), "stdin": "", "pid": os.getpid(), "results": [],
              "answers": [], "git_ceiling": os.environ.get("GIT_CEILING_DIRECTORIES"),
              "temp": [os.environ.get(name) for name in ("TMP", "TEMP", "TMPDIR")]}
    bridge = None
    numbers = iter(range(1000, 10**6))

    told: list[str] = []

    def logged(what: str) -> None:
        """When its run began and ended (its turn's end: it is ended, not left to exit),
        for tests of runs that take turns."""
        if plan.get("runs") and what not in told:
            told.append(what)
            with open(plan["runs"], "a", encoding="utf-8") as log:
                log.write(f"{what} {os.getpid()} {time.monotonic()}\n")

    logged("start")

    def save() -> None:
        Path(plan["record"]).write_text(json.dumps(record), encoding="utf-8")

    def heard(steer: bool = False) -> dict:
        """KOLONİ's next line; a `turn/steer` is answered as it comes (89d, measured 25 Oct:
        taken mid-command; "steer": "reject" refuses it, "late" answers after a second) and passed over, unless `steer`."""
        while True:
            line = sys.stdin.readline()
            if not line:
                sys.exit(0)  # ended
            told = json.loads(line)
            if told.get("method") != "turn/steer":
                return told
            record.setdefault("steers", []).append(told["params"])
            save()
            if plan.get("steer") == "late":  # (taken into its turn; answered after a second)
                time.sleep(1)
            if plan.get("steer") == "reject" or told["params"].get("expectedTurnId") != "turn_1":
                say({"id": told["id"], "error": {"code": -32600, "message": "no such turn"}})
            else:
                say({"id": told["id"], "result": {"turnId": "turn_1"}})
            if steer:
                return told

    def expect(method: str) -> dict:
        while (told := heard()).get("method") != method:
            pass
        return told

    def ask(method: str, params: dict) -> dict:
        """A request of its own; what KOLONİ answered, as it is written down."""
        number = next(numbers)
        say({"id": number, "method": method, "params": params})
        while True:
            told = heard()
            if told.get("id") == number and "method" not in told:
                answer = told["result"] if "result" in told else {"error": told.get("error")}
                # (and how many steers came before it: one after a no may find its turn over)
                record["answers"].append(
                    {"method": method, "itemId": params.get("itemId"), "answer": answer,
                     "steers_before": len(record.get("steers", []))})
                save()
                return answer

    def setting(name: str) -> str:
        wanted = f"mcp_servers.koloni.{name}="
        value = next(a[len(wanted):] for a in argv if a.startswith(wanted))
        return tomllib.loads(f"v = {value}")["v"]  # Codex reads these as TOML values

    def koloni(method: str, params: dict) -> dict:
        """Talk to KOLONİ's tool server the way Codex would: through the bridge it was given."""
        nonlocal bridge
        if bridge is None:
            bridge = subprocess.Popen([setting("command"), *setting("args")],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            koloni("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
            record["tools"] = [t["name"] for t in koloni("tools/list", {})["result"]["tools"]]
        number = next(numbers)
        assert bridge.stdin is not None and bridge.stdout is not None
        bridge.stdin.write((json.dumps(
            {"jsonrpc": "2.0", "id": number, "method": method, "params": params}) + "\n").encode())
        bridge.stdin.flush()
        line = bridge.stdout.readline()
        if not line:
            record["cut_off"] = True
            save()
            sys.exit(5)
        return json.loads(line)

    started = expect("initialize")
    if plan.get("handshake") == "gone":
        sys.exit(0)
    if plan.get("handshake") == "initialize":
        say({"id": started["id"], "error": {"code": -32600, "message": "unknown client"}})
        sys.exit(0)
    say({"id": started["id"], "result": {"userAgent": "codex_cli_rs/0.164.0-fake"}})
    expect("initialized")
    say({"method": "account/updated", "params": ACCOUNT})
    thread = expect("thread/start")
    record["thread"] = thread["params"]
    save()
    if plan.get("handshake") == "thread":
        say({"id": thread["id"], "error": {"code": -32600, "message": "unknown field cwd"}})
        expect("never")  # it waits to be ended
    handshake = plan.get("handshake")
    policy = "on-request" if handshake == "policy" else thread["params"].get("approvalPolicy")
    # What the user's own config.toml can make of the thread KOLONİ asked for.
    reviewer = "auto_review" if handshake == "reviewer" else (
        thread["params"].get("approvalsReviewer"))
    sandbox = {"type": "workspaceWrite", "writableRoots": [], "networkAccess": False,
               "excludeTmpdirEnvVar": False, "excludeSlashTmp": False}
    if handshake == "wider":
        sandbox["writableRoots"] = [str(Path.home())]
    if handshake == "network":
        sandbox["networkAccess"] = True
    if handshake == "full":
        sandbox = {"type": "dangerFullAccess"}
    elif thread["params"].get("sandbox") == "read-only" and handshake != "writable":
        sandbox = {"type": "readOnly", "networkAccess": False}  # (B-301: as its protocol names it)
    say({"id": thread["id"], "result": {
        "thread": {"id": "thr_1"}, "approvalPolicy": policy, "approvalsReviewer": reviewer,
        "cwd": thread["params"].get("cwd"), "model": thread["params"].get("model") or "gpt-fake",
        "modelProvider": "openai", "sandbox": sandbox}})
    say({"method": "thread/started", "params": {"thread": {"id": "thr_1"}}})
    turn = expect("turn/start")
    record["turn"] = {k: v for k, v in turn["params"].items() if k != "input"}
    record["stdin"] = "".join(part.get("text", "") for part in turn["params"]["input"])
    record["input"] = turn["params"]["input"]
    # Each picture given by its path (a localImage), as it was there.
    record["images"] = [Path(part["path"]).read_bytes().hex() for part in record["input"]
                        if part.get("type") == "localImage"]
    save()
    say({"id": turn["id"], "result": {"turn": {"id": "turn_1", "status": "inProgress",
                                               "items": []}}})
    ids = {"threadId": "thr_1", "turnId": "turn_1"}
    say({"method": "turn/started", "params": {**ids, "turn": {"id": "turn_1"}}})

    def item(phase: str, body: dict) -> None:
        say({"method": f"item/{phase}", "params": {**ids, "item": body}})

    # It thinks first: nothing of that is a record of KOLONİ's.
    item("started", {"id": "rs_0", "type": "reasoning", "summary": [], "content": []})
    item("completed", {"id": "rs_0", "type": "reasoning", "summary": ["thinking"],
                       "content": []})
    if plan.get("list_tools"):
        koloni("ping", {})

    def asked(method: str, item_id: str, action: dict, **more) -> bool:
        if action.get("unasked"):
            return True
        params = {**ids, "itemId": item_id, "startedAtMs": 0, "reason": action.get("reason"),
                  **({"threadId": action["thread"]} if "thread" in action else {}), **more}
        answer = ask(method, params)
        if action.get("twice"):  # the same request again, with no approval id of its own
            ask(method, params)
        return answer.get("decision") == "accept"

    def allowed_to_call(server: str, tool: str, arguments: dict) -> bool:
        """Measured on 0.164.0 (24 Oct 2026): at "untrusted" every MCP tool call is asked
        first, and runs only on "accept"."""
        answer = ask("mcpServer/elicitation/request", {
            **ids, "serverName": server, "mode": "form",
            "message": f'Allow the {server} MCP server to run tool "{tool}"?',
            "requestedSchema": {"type": "object", "properties": {}},
            "_meta": {"codex_approval_kind": "mcp_tool_call", "tool_params": arguments,
                      "persist": ["session", "always"]}})
        return answer.get("action") == "accept"

    def rejected(body: dict) -> None:
        item("completed", {**body, "status": "failed",
                           "error": {"message": "user rejected MCP tool call"}})

    # Started again after its turn to read what came for it (a sub-agent's report, K-paralel-spawn):
    # "later_script", once "later_when" is in what it is given. "task_scripts": {text: script},
    # a run whose input has the text follows that script (a sub-agent on Codex, by its task).
    script = plan.get("script", [])
    if "later_script" in plan and plan["later_when"] in record["stdin"]:
        script = plan["later_script"]
    else:
        script = next((own for text, own in plan.get("task_scripts", {}).items()
                       if text in record["stdin"]), script)
    awaited = 0  # steers an `await_steer` has taken
    for number, action in enumerate(script):
        item_id = f"item_{number}"
        if "say" in action:
            item("completed", {"id": item_id, "type": "agentMessage", "text": action["say"],
                               **({"phase": action["phase"]} if "phase" in action else {})})
        elif "run" in action:
            body = {"id": item_id, "type": "commandExecution", "command": action["run"],
                    "cwd": str(cwd), "commandActions": [], "status": "inProgress",
                    "aggregatedOutput": None, "exitCode": None}
            if not action.get("no_start"):
                item("started", body)
            if not asked(RUN_ASKED, item_id, action, command=action["run"],
                         cwd=action.get("cwd", str(cwd))):
                item("completed", {**body, "status": "declined"})
                continue
            if "delta" in action:
                say({"method": "item/commandExecution/outputDelta",
                     "params": {**ids, "itemId": item_id, "delta": action["delta"]}})
            if "die" in action:
                die(action["die"])
            time.sleep(action.get("hold", 0))
            for touched, content in action.get("touches", {}).items():  # it edits files
                (cwd / touched).parent.mkdir(parents=True, exist_ok=True)
                (cwd / touched).write_bytes(content.encode("utf-8"))
            for removed in action.get("removes", []):
                (cwd / removed).unlink()
            item("completed", {**body, "aggregatedOutput": action.get("output", ""),
                               "exitCode": action.get("exit", 0), "status": "completed"})
        elif "write" in action or "write_abs" in action or "delete" in action:
            target = (Path(action["write_abs"]) if "write_abs" in action
                      else cwd / (action.get("write") or action["delete"]))
            content = action.get("content", "")
            kind = ("delete" if "delete" in action
                    else action.get("kind") or ("update" if target.exists() else "add"))
            files = [(target, action["write"] if action.get("relative") else str(target), kind)]
            files += [(Path(more), more, "update" if Path(more).exists() else "add")
                      for more in action.get("also", [])]
            changes = [{
                "path": named, "kind": {"type": how, **({"move_path": None}
                                                       if how == "update" else {})},
                # A new file's diff is what it will hold; the rest are a diff of sorts.
                "diff": content if how == "add" else f"@@ -1 +1 @@\n+{content}",
            } for _path, named, how in files]
            body = {"id": item_id, "type": "fileChange", "changes": changes,
                    "status": "inProgress"}
            if not action.get("no_start"):
                item("started", body)
            if not asked(PATCH_ASKED, item_id, action, grantRoot=action.get("grant_root")):
                item("completed", {**body, "status": "declined"})
                continue
            if action.get("grows"):  # once allowed, the patch it applies holds one file more
                more = cwd / action["grows"]
                files.append((more, str(more), "add"))
                body["changes"] = [*changes, {"path": str(more), "kind": {"type": "add"},
                                              "diff": content}]
                say({"method": "item/fileChange/patchUpdated",
                     "params": {**ids, "itemId": item_id, "changes": body["changes"]}})
            for path, _named, how in files:
                if how == "delete":
                    path.unlink()
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content.encode("utf-8"))
            item("completed", {**body, "status": "completed"})
        elif "mcp" in action:
            call = action["mcp"]
            body = {"id": item_id, "type": "mcpToolCall", "server": call["server"],
                    "tool": call["tool"], "arguments": call.get("arguments", {})}
            item("started", {**body, "status": "inProgress"})
            # (A server of the user's is off on KOLONİ's line: "elicit" is one that is not.)
            if call.get("elicit") and not allowed_to_call(call["server"], call["tool"],
                                                          body["arguments"]):
                rejected(body)
                continue
            item("completed", {
                **body, "status": "failed" if call.get("error") else "completed",
                "error": {"message": call["error"]} if call.get("error") else None,
                "result": {"content": [{"type": "text", "text": call.get("result", "")}]}})
        elif "web" in action:
            item("completed", {"id": item_id, "type": "webSearch", "query": action["web"]})
        elif "begin" in action:  # an item of that type, begun, at work for "hold" s, then done
            item("started", {"id": item_id, "type": action["begin"], "status": "inProgress"})
            time.sleep(action.get("hold", 0))
            item("completed", {"id": item_id, "type": action["begin"], "status": "completed"})
            record.setdefault("done", []).append(item_id)
            save()
        elif "image" in action:  # (B-347: an image it looks at with its own tool, R128's item)
            item("completed", {"id": item_id, "type": "imageView", "path": action["image"]})
        elif "koloni" in action:
            body = {"id": item_id, "type": "mcpToolCall", "server": "koloni",
                    "tool": action["koloni"], "arguments": action.get("args", {})}
            item("started", {**body, "status": "inProgress"})
            if not allowed_to_call("koloni", action["koloni"], body["arguments"]):
                record["results"].append(None)
                save()
                rejected(body)
                continue
            answer = koloni("tools/call", {"name": action["koloni"],
                                           "arguments": action.get("args", {})})
            record["results"].append(answer.get("result", answer))
            save()
            item("completed", {**body, "status": "completed", "result": answer.get("result")})
        elif "request" in action:
            ask(action["request"], {**ids, "itemId": item_id, **action.get("params", {})})
        elif "context" in action:  # (its `total` is not what its context holds)
            say({"method": "thread/tokenUsage/updated", "params": {
                **ids, "threadId": action.get("thread", "thr_1"), "tokenUsage": {
                    "total": {"inputTokens": action["context"] * 9, "outputTokens": 10},
                    "last": {"inputTokens": action["context"], "cachedInputTokens": 0,
                             "outputTokens": 10},
                    "modelContextWindow": action.get("window")}}})
        elif "plan" in action:
            say({"method": "turn/plan/updated", "params": {
                **ids, "threadId": action.get("thread", "thr_1"), "explanation": None,
                "plan": action["plan"]}})
        elif "pause" in action:
            time.sleep(action["pause"])  # the time a model takes between two tools
        elif "wait_for" in action:
            while not Path(action["wait_for"]).exists():
                time.sleep(0.02)
        elif "await_steer" in action:  # (till one comes: a pipe's read has no timeout here)
            # (One read while it waited for an answer - `ask` - came already, as into Codex's
            # turn: K-48, a steer sent while its command was asked about.)
            while len(record.get("steers", [])) <= awaited:
                heard(steer=True)
            awaited = len(record["steers"])
        elif action.get("hang"):
            time.sleep(120)
        elif "exit" in action:
            sys.stderr.write(action.get("stderr", "") + "\n")
            logged("end")
            sys.exit(action["exit"])
        elif "error" in action:
            error = {"message": action["error"], "codexErrorInfo": None}
            say({"method": "error", "params": {**ids, "error": error, "willRetry": True}})
            say({"method": "error", "params": {**ids, "error": error, "willRetry": False}})
            logged("end")
            say({"method": "turn/completed", "params": {"threadId": "thr_1", "turn": {
                "id": "turn_1", "status": "failed", "items": [], "error": error}}})
            expect("never")

    usage = plan.get("usage", {"input_tokens": 4000, "cached_input_tokens": 3000,
                               "output_tokens": 120})
    if usage is not None:
        total = {"inputTokens": usage.get("input_tokens", 0),
                 "cachedInputTokens": usage.get("cached_input_tokens", 0),
                 "outputTokens": usage.get("output_tokens", 0), "reasoningOutputTokens": 0,
                 "totalTokens": 0}
        say({"method": "thread/tokenUsage/updated", "params": {
            **ids, "tokenUsage": {"total": total, "last": {**total, "inputTokens": 1}}}})
    say({"method": "account/rateLimits/updated", "params": {"rateLimits": LIMITS}})
    say({"method": "account/updated", "params": ACCOUNT})
    logged("end")
    say({"method": "turn/completed", "params": {"threadId": "thr_1", "turn": {
        "id": "turn_1", "status": "completed", "items": [], "error": None}}})
    expect("never")  # an app-server stays until it is ended


told = json.loads(Path(os.environ["FAKE_CLI_PLAN"]).read_text(encoding="utf-8")) \
    if os.environ.get("FAKE_CLI_PLAN") else {}
if told.get("starts"):  # every way it was started, one line each
    with open(told["starts"], "a", encoding="utf-8") as log:
        log.write(json.dumps(sys.argv[1:]) + "\n")
if sys.argv[1:] == ["--version"]:  # the plan's "version", if it names one
    print(f"codex-cli {told.get('version', '0.164.0-fake')}")
    sys.exit(0)
if sys.argv[-1] != "app-server":
    sys.exit(2)
if os.environ.get("FAKE_APP_SERVER_STARTED"):
    # One line for each time it is started, with which process it is.
    with open(os.environ["FAKE_APP_SERVER_STARTED"], "a", encoding="utf-8") as started:
        started.write(f"{os.getpid()}\n")
if os.environ.get("FAKE_CLI_PLAN"):
    native()
ready = False
for line in sys.stdin:
    asked = json.loads(line)
    if asked.get("method") == "initialize":
        say({"id": asked["id"], "result": {"userAgent": "fake"}})
    elif asked.get("method") == "initialized":
        ready = True
        # What it says unasked comes in between.
        say({"method": "remoteControl/status/changed", "params": {"status": "off"}})
    elif asked.get("method") == "account/rateLimits/read":
        say({"method": "account/updated", "params": {"id": 2}})
        # Many of them, and a request of its own that happens to carry the same id.
        for _ in range(250):
            say({"method": "account/updated", "params": {"id": 2}})
        say({"id": asked["id"], "method": "item/approval/request", "params": {}})
        if mode == "loud":
            for _ in range(40):
                say({"method": "log", "params": {"text": "x" * 50_000}})
        if mode == "hang":
            time.sleep(120)
        if mode == "gone":
            sys.exit(0)
        if mode == "refuse" or not ready:
            say({"id": asked["id"], "error": {"code": -32600, "message": "not signed in"}})
            continue
        say({"id": asked["id"], "result": {
            "ordinaryUsageAllowed": True, "rateLimits": LIMITS,
            "rateLimitsByLimitId": {"codex": LIMITS},
            "accountId": "2124e951-0000-4203-9983-37fbc3e8d981",
            "argv": sys.argv[1:],
            "sawKoloni": sorted(k for k in os.environ if k.upper().startswith("KOLONI_")),
        }})
