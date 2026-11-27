"""GitHub Copilot CLI's own sub-agents as KOLONİ's roles (0.1.11, `app.copilot_own_agents`): a
Copilot Orchestrator at protocol 4 is given the roles the user lets run inside the CLI as agents of
its own, opens one with its task tool - only as offered, while it waits - and each tool of the
sub-agent is asked through KOLONİ's hook, held to its role, and put on record under the task call.
The stand-in (`fake_copilot_headless.py`) speaks as Copilot 1.0.114 was measured to (27 Nov 2026):
a sub-agent's events, hooks and requests carry its agentId."""

import asyncio
import json

import pytest

from app.copilot_own_agents import APPROVE_ONCE, OwnAgents, copilot_tools
from tests.test_agent_writes import wait_status
from tests.test_codex_app_server_scenarios import card_for
from tests.test_copilot_agent import copilot_native, start  # noqa: F401  (a fixture)
from tests.test_copilot_headless_scenarios import APPROVE, REJECT, answers
from tests.test_copilot_resume import copilot  # noqa: F401  (a fixture)
from tests.test_send_now import now
from tests.test_send_now_cli import started
from tests.test_steer_at_work import at_work

ORIGIN = {"Origin": "http://127.0.0.1:8790"}
CHECKER = {
    "name": "Checker",
    "description": "Looks over the code",
    "instructions": "Check it.",
    "tools": ["read_file", "search", "list_dir", "ask_user"],
    "inside_cli": True,
}
RUNNER = {**CHECKER, "name": "Runner", "tools": ["read_file", "run_command"]}
WRITER = {**CHECKER, "name": "Writer", "tools": ["read_file", "write_file"]}
SYNC = {"task": "koloni-checker", "mode": "sync"}
STOPPED = "ran a tool of its own without KOLONİ being asked"


def p4(copilot_native, script, *roles, open_to_agents=True, **more):  # noqa: F811
    """A Copilot that speaks protocol 4, as 1.0.114 does, with these roles run inside the CLI - on
    a provider in the team guide (else its own sub-agents would run on a model closed to agents)."""
    client, provider = copilot_native(script, **{"protocol": 4, "version": "1.0.114", **more})
    opened = client.patch(f"/api/providers/{provider['id']}", json={"for_agents": open_to_agents})
    assert opened.status_code == 200, opened.text
    for role in roles:
        made = client.post("/api/roles", json=role, headers=ORIGIN)
        assert made.status_code == 201, made.text
    return client, provider


def run(client, project_dir, provider, wait_run, mode="full_auto"):  # noqa: F811
    cid, run_id = start(client, project_dir, provider, mode=mode)
    return cid, wait_run(client, cid, run_id)


def by_name(snap):
    return {call["name"]: call for call in snap["tool_calls"]}


def agents_of(copilot_native):  # noqa: F811
    made = copilot_native.record()["create"]
    return made.get("agents"), made["tools"]["availableTools"]


def test_roles_go_to_copilot_as_agents_of_its_own_only_with_none_of_its_built_in_ones(
    copilot_native,
    wait_run,
    project_dir,  # noqa: F811
):
    client, provider = p4(copilot_native, [{"say": "Done."}], CHECKER, RUNNER)
    _cid, snap = run(client, project_dir, provider, wait_run)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    given, tools = agents_of(copilot_native)
    assert given["includedBuiltinAgents"] == []
    by_role = {one["name"]: one for one in given["definitions"]}
    # its line, its instructions and its tools as Copilot's own - no model, none of KOLONİ's
    # tools, never its task (no sub-agent of a sub-agent's)
    assert by_role["koloni-checker"] == {
        "name": "koloni-checker",
        "description": "Looks over the code",
        "prompt": "Check it.",
        "tools": ["view"],
    }
    assert by_role["koloni-runner"]["tools"] == [
        "view",
        "powershell",
        "read_powershell",
        "stop_powershell",
        "list_powershell",
    ]
    for one in given["definitions"]:
        assert "task" not in one["tools"] and not any(t.startswith("koloni-") for t in one["tools"])
    assert tools.count("task") == 1


@pytest.mark.parametrize(
    "how",
    ["role off", "protocol 3", "asked every time", "closed to agents"],
)
def test_no_role_and_no_task_tool_where_none_may_be_offered(
    copilot_native,
    wait_run,
    project_dir,
    how,  # noqa: F811
):
    client, provider = p4(
        copilot_native,
        [{"say": "Done."}],
        {**CHECKER, "inside_cli": how != "role off"},
        **({"protocol": 3, "version": "1.0.91-fake"} if how == "protocol 3" else {}),
        open_to_agents=how != "closed to agents",
    )
    if how == "asked every time":
        pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
        cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
        settings = {"spawn_approval": "always", "permission_mode": "full_auto"}
        settings |= {"provider_id": provider["id"], "lead_hands_code": False}
        client.patch(f"/api/conversations/{cid}", json=settings, headers=ORIGIN)
        run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "x"}).json()
        snap = wait_run(client, cid, run_id["run"]["id"])
    else:
        _cid, snap = run(client, project_dir, provider, wait_run)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    made = copilot_native.record()["create"]
    available = made.get("tools", {}).get("availableTools") or made.get("availableTools")
    assert "agents" not in made and "task" not in available, made


@pytest.mark.parametrize("start_at", ["before", "after"])
def test_a_role_inside_copilot_works_under_its_task_call_held_to_its_tools(
    copilot_native,
    wait_run,
    project_dir,
    start_at,  # noqa: F811
):
    # (Measured both ways: its tool's start before its request (c4), and after it (c12).)
    client, provider = p4(
        copilot_native,
        [
            {
                **SYNC,
                "steps": [
                    {"read": "hello.py", "result": "print('hi')", "start": start_at},
                    {
                        "shell": "Set-Content ran.txt x",
                        "touches": {"ran.txt": "x"},
                        "start": start_at,
                    },
                    {"say": "It prints hi."},
                ],
                "result": "hello.py prints hi",
            },
            {"say": "Done."},
        ],
        CHECKER,
    )
    _cid, snap = run(client, project_dir, provider, wait_run)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert len(snap["agents"]) == 1  # not an agent of KOLONİ's
    calls = by_name(snap)
    sub = calls["copilot__task"]
    assert json.loads(sub["arguments"])["koloni_role"] == "Checker"
    assert (sub["status"], sub["result"], sub["origin"]) == (
        "succeeded",
        "hello.py prints hi",
        "cli",
    )
    read = calls["copilot__view"]
    assert (read["status"], read["parent_call_id"]) == ("succeeded", sub["id"])
    refused = calls["copilot__powershell"]
    assert (refused["status"], refused["parent_call_id"]) == ("denied", sub["id"])
    assert "koloni-checker may not use powershell" in refused["result"]
    assert not (project_dir / "ran.txt").exists() and snap["commands"] == []
    # the hook's requests: its task, the sub-agent's read, its command refused
    assert answers(copilot_native) == [("hook", APPROVE), ("hook", APPROVE), ("hook", REJECT)]
    # its words are its own, not its Lead's
    words = [m["content"] for m in snap["messages"] if m["role"] == "assistant"]
    assert "It prints hi." not in "".join(words) and "Done." in words, words


def test_at_ask_a_role_that_changes_things_is_a_card_and_so_is_each_tool_it_is_given(
    copilot_native,
    wait_run,
    project_dir,  # noqa: F811
):
    # (As spawn_agent's at Ask - `cards._asked_about` - and Claude Code's Agent: the card's call is
    # the sub-agent's record once allowed.)
    client, provider = p4(
        copilot_native,
        [
            {
                "task": "koloni-runner",
                "mode": "sync",
                "prompt": "Run the build.",
                "steps": [{"shell": "Set-Content ran.txt x", "touches": {"ran.txt": "x"}}],
            },
            {"say": "Done."},
        ],
        RUNNER,
    )
    cid, run_id = start(client, project_dir, provider, mode="ask")
    question = wait_status(client, cid, "waiting_approval")["questions"][0]
    assert "koloni-runner" in question["question"] and "Run the build." in question["question"]
    assert copilot_native.record()["answers"] == []  # (nothing opened before the answer)
    answered = client.post(
        f"/api/questions/{question['id']}/answer", json={"answer": "Allow"}, headers=ORIGIN
    )
    assert answered.status_code == 200, answered.text
    asked = card_for(client, cid, "Set-Content ran.txt x")
    assert not (project_dir / "ran.txt").exists()
    assert client.post(f"/api/commands/{asked['id']}/approve", json={}).status_code == 200
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert (project_dir / "ran.txt").exists()
    (sub,) = [c for c in snap["tool_calls"] if c["name"] == "copilot__task"]
    assert json.loads(sub["arguments"])["koloni_role"] == "Runner" and sub["status"] == "succeeded"
    (ran,) = [c for c in snap["tool_calls"] if c["id"] == snap["commands"][0]["tool_call_id"]]
    assert ran["parent_call_id"] == sub["id"], (ran, sub)


@pytest.mark.parametrize("answer", ["Deny", None])
def test_at_ask_a_role_that_only_reads_opens_with_no_card_and_one_denied_never_opens(
    copilot_native,
    wait_run,
    project_dir,
    answer,  # noqa: F811
):
    role, step = (RUNNER, {"shell": "Set-Content ran.txt x", "touches": {"ran.txt": "x"}})
    if answer is None:
        role, step = (CHECKER, {"read": "hello.py"})
    client, provider = p4(
        copilot_native,
        [
            {"task": f"koloni-{role['name'].lower()}", "mode": "sync", "steps": [step]},
            {"say": "ok"},
        ],
        role,
    )
    cid, run_id = start(client, project_dir, provider, mode="ask")
    if answer:
        question = wait_status(client, cid, "waiting_approval")["questions"][0]
        client.post(
            f"/api/questions/{question['id']}/answer", json={"answer": answer}, headers=ORIGIN
        )
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (task,) = [c for c in snap["tool_calls"] if c["name"] == "copilot__task"]
    if answer:
        assert task["status"] == "denied" and answers(copilot_native) == [("hook", REJECT)]
        assert not (project_dir / "ran.txt").exists()
    else:
        assert snap["questions"] == [] and task["status"] == "succeeded", snap["questions"]


def test_approve_holds_it_to_its_roles_tools_by_what_each_file_is_asked_as(
    copilot_native,
    wait_run,
    project_dir,  # noqa: F811
):
    # Writer's apply_patch is its, but a change to a file there is no write of a new one: its
    # Edit is refused by `_approve` (89g), on record by Copilot's name.
    patch = (
        "*** Begin Patch\n*** Update File: hello.py\n@@\n-print('hi')\n+print('bye')\n*** End Patch"
    )
    client, provider = p4(
        copilot_native,
        [{"task": "koloni-writer", "mode": "sync", "steps": [{"patch": patch}]}, {"say": "ok"}],
        WRITER,
    )
    _cid, snap = run(client, project_dir, provider, wait_run)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    calls = by_name(snap)
    refused = calls["copilot__Edit"]
    assert (
        refused["status"] == "denied" and refused["parent_call_id"] == calls["copilot__task"]["id"]
    )
    assert refused["result"] == (
        "Writer (inside GitHub Copilot CLI) may not use Edit: its role does not give it that tool"
    )
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('hi')\n"


@pytest.mark.parametrize(
    ("task", "why"),
    [
        ({"task": "general-purpose", "mode": "sync"}, "only the roles it gave you"),
        ({"task": "my-own-agent", "mode": "sync"}, "only the roles it gave you"),
        ({"task": "koloni-checker", "mode": "background"}, 'mode "sync"'),
        ({"task": "koloni-checker"}, 'mode "sync"'),
        ({"task": "koloni-checker", "mode": "sync", "args": {"agent_type": ["x"]}}, "only the"),
        # (Copilot's task takes more: each would choose past KOLONİ's pick of a model, its cards)
        ({**SYNC, "args": {"model": "claude-opus-4.5"}}, "not model"),
        ({**SYNC, "args": {"reasoning_effort": "xhigh"}}, "not reasoning_effort"),
        ({**SYNC, "args": {"context_tier": "long_context"}}, "not context_tier"),
        ({**SYNC, "args": {"surprise": 1}}, "not surprise"),
    ],
)
def test_its_task_opens_only_a_role_offered_and_only_while_it_waits(
    copilot_native,
    wait_run,
    project_dir,
    task,
    why,  # noqa: F811
):
    client, provider = p4(
        copilot_native,
        [{**task, "steps": [{"shell": "Set-Content ran.txt x", "touches": {"ran.txt": "x"}}]}],
        CHECKER,
    )
    _cid, snap = run(client, project_dir, provider, wait_run)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert answers(copilot_native) == [("hook", REJECT)]
    (refused,) = [c for c in snap["tool_calls"] if c["name"] == "copilot__task"]
    assert refused["status"] == "denied" and why in refused["result"], refused
    assert not (project_dir / "ran.txt").exists()


@pytest.mark.parametrize("start_at", ["before", "after"])
@pytest.mark.parametrize("koloni", ["spawn_agent", "read_notes"])
def test_a_sub_agent_may_never_use_kolonis_tools_which_are_its_leads(
    copilot_native,
    wait_run,
    project_dir,
    start_at,
    koloni,  # noqa: F811
):
    # (Measured: KOLONİ's bridge is shared with it, started once - its tools are its Lead's.)
    step = {
        "koloni": koloni,
        "args": {"role": "Coder", "task": "x"} if koloni == "spawn_agent" else {},
    }
    client, provider = p4(
        copilot_native,
        [{**SYNC, "steps": [{**step, "start": start_at}]}, {"say": "Done."}],
        CHECKER,
    )
    _cid, snap = run(client, project_dir, provider, wait_run)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert len(snap["agents"]) == 1  # nothing was opened
    assert copilot_native.record()["results"] == []  # the bridge was never called
    assert answers(copilot_native) == [("hook", APPROVE), ("hook", REJECT)]
    refused = by_name(snap)[f"copilot__koloni-{koloni}"]
    assert (
        refused["status"] == "denied"
        and "KOLONİ's tools are its Orchestrator's" in (refused["result"])
    )


@pytest.mark.parametrize(
    "step",
    [
        {"shell": "Set-Content ran.txt x", "touches": {"ran.txt": "x"}, "unasked": True},
        {"koloni": "read_notes", "args": {}, "unasked": True},
        {"koloni": "read_notes", "args": {}, "unasked": True, "start": "after"},
    ],
)
def test_a_tool_of_a_sub_agent_that_ran_unasked_stops_the_turn(
    copilot_native,
    wait_run,
    project_dir,
    step,  # noqa: F811
):
    client, provider = p4(
        copilot_native,
        [{"task": "koloni-runner", "mode": "sync", "steps": [step]}, {"say": "Done."}],
        RUNNER,
    )
    _cid, snap = run(client, project_dir, provider, wait_run)
    assert snap["runs"][0]["status"] == "failed", snap["runs"][0]
    assert STOPPED in snap["runs"][0]["error"], snap["runs"][0]["error"]


def test_a_sub_agent_opens_none_of_its_own(
    copilot_native,
    wait_run,
    project_dir,  # noqa: F811
):
    inner = {**SYNC, "steps": [{"shell": "Set-Content ran.txt x", "touches": {"ran.txt": "x"}}]}
    client, provider = p4(copilot_native, [{**SYNC, "steps": [inner]}, {"say": "Done."}], CHECKER)
    _cid, snap = run(client, project_dir, provider, wait_run)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert answers(copilot_native) == [("hook", APPROVE), ("hook", REJECT)]
    tasks = [c for c in snap["tool_calls"] if c["name"] == "copilot__task"]
    (refused,) = [c for c in tasks if c["status"] == "denied"]
    assert "may not open one of its own" in refused["result"]
    assert not (project_dir / "ran.txt").exists()


@pytest.mark.parametrize("unknown", [{"as": "koloni-other"}, {"started_call": "call_99"}])
def test_a_sub_agent_koloni_did_not_open_may_use_nothing(
    copilot_native,
    wait_run,
    project_dir,
    unknown,  # noqa: F811
):
    # (Its start names another role than the task call KOLONİ let through, or another call.)
    client, provider = p4(
        copilot_native,
        [{**SYNC, **unknown, "steps": [{"read": "hello.py"}]}, {"say": "Done."}],
        CHECKER,
    )
    _cid, snap = run(client, project_dir, provider, wait_run)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert answers(copilot_native) == [("hook", APPROVE), ("hook", REJECT)]
    refused = by_name(snap)["copilot__view"]
    assert (
        refused["status"] == "denied"
        and "KOLONİ did not open this sub-agent" in (refused["result"])
    )


def test_a_sub_agents_usage_model_and_idle_are_not_its_leads(
    copilot_native,
    wait_run,
    project_dir,  # noqa: F811
):
    big = {
        "totalPremiumRequests": 9,
        "accountingSnapshot": {"modelMetrics": {"m": {"usage": {"inputTokens": 99999}}}},
    }
    client, provider = p4(
        copilot_native,
        [
            {
                **SYNC,
                "steps": [
                    {"event": "model.call_start", "data": {"model": "sub-model"}},
                    {"event": "session.usage_checkpoint", "data": big},
                    {"event": "session.idle", "data": {}},  # (never its Lead's end)
                    {"say": "sub words"},
                ],
            },
            {"say": "Done."},
        ],
        CHECKER,
        model="lead-model",
    )
    _cid, snap = run(client, project_dir, provider, wait_run)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    lead = snap["agents"][0]
    assert (lead["input_tokens"], lead["premium_requests"]) == (None, None), lead
    assert lead["model_id"] != "sub-model", lead
    words = [m["content"] for m in snap["messages"] if m["role"] == "assistant"]
    assert words[-1] == "Done.", words  # (its turn went on past the sub-agent's idle)


@pytest.mark.parametrize("ghost", [False, True])
def test_a_sub_agents_words_never_count_a_word_sent_now_as_read(
    copilot_native,
    wait_run,
    project_dir,
    ghost,  # noqa: F811
):
    # (Its Lead's words after the send would: only a sub-agent of its own spoke - one KOLONİ let
    # open, or one never seen starting.)
    said = (
        {"event": "assistant.message", "data": {"content": "sub words"}, "agent": "ghost"}
        if ghost
        else {**SYNC, "steps": [{"say": "sub words"}]}
    )
    client, provider = p4(copilot_native, [{"say": "working"}, {"await_send": True}, said], CHECKER)
    cid, run_id = started(client, project_dir, provider)
    at_work(client, cid, name="Lead")
    copilot_native.rescript([{"say": "read it"}])  # (its next run's: this one read its plan)
    assert now(client, cid, "LATE WORD").json()["run"]["id"] == run_id
    snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert "LATE WORD" in copilot_native.record()["prompt"]  # one more run reads it
    words = [m["content"] for m in snap["messages"] if m["role"] == "assistant"]
    assert words[-1] == "read it" and "sub words" not in words, words


# --- the gate itself, past what the stand-in sends --------------------------------------------


def gate(own, data, request, use_id="u1"):
    told: list = []

    async def on_item(phase, item):
        told.append((phase, item))

    return asyncio.run(own.gate(data, request, use_id, on_item)), told


def opened(roles):
    """An OwnAgents given `roles` ({name: Copilot tools}), its task call t1 of the first let
    through and its sub-agent a1 started."""
    own = OwnAgents(set(), call_tool=None)  # (no role here is asked about: `asks`)
    own.given(
        {"tools": {"availableTools": []}},
        {n: {"description": "", "prompt": "", "tools": t} for n, t in roles.items()},
    )
    first = next(iter(roles))
    hook = {"kind": "hook", "toolName": "task", "toolArgs": {"agent_type": first, "mode": "sync"}}
    assert gate(own, {}, hook, "t1")[0] == APPROVE_ONCE
    started = {
        "type": "subagent.started",
        "agentId": "a1",
        "data": {"toolCallId": "t1", "agentName": first, "agentType": first},
    }
    assert own.translator(lambda _event: [], {})(started)[0]["item"]["id"] == "t1"
    return own


def test_kolonis_tools_are_refused_a_sub_agent_whatever_its_role_says():
    own = opened({"koloni-x": ["view", "koloni-spawn_agent"]})
    for request in (
        {"kind": "hook", "toolName": "koloni-spawn_agent", "toolArgs": {}},
        {"kind": "mcp", "serverName": "koloni", "toolName": "spawn_agent", "args": {}},
    ):
        answer, told = gate(own, {"agentId": "a1"}, request)
        assert answer["kind"] == "reject" and "Orchestrator's" in answer["feedback"], answer
        assert told[0] == ("announced", {"id": "u1", "parent": "t1"})
    # its Lead's own call of KOLONİ's tools is no business of the gate's
    lead = {"kind": "mcp", "serverName": "koloni", "toolName": "spawn_agent", "args": {}}
    assert gate(own, {}, lead)[0] is None


def test_the_gate_passes_a_sub_agents_own_tool_on_with_its_role_named_to_approve():
    own = opened({"koloni-x": ["view"]})
    hook = {"kind": "hook", "toolName": "view", "toolArgs": {"path": "a.py"}}
    assert gate(own, {"agentId": "a1"}, hook)[0] is None
    asked: list = []

    async def call_tool(name, arguments):
        asked.append((name, json.loads(arguments)))
        return True, "{}"

    async def on_item(phase, item):
        asked.append((phase, item))

    told, asking = own.held({"agentId": "a1"}, on_item, call_tool)
    asyncio.run(told("announced", {"id": "u1:0"}))
    asyncio.run(asking("approve", json.dumps({"tool_name": "Read", "agent_type": "forged"})))
    assert asked == [
        ("announced", {"id": "u1:0", "parent": "t1"}),
        ("approve", {"tool_name": "Read", "agent_type": "koloni-x", "input": {}}),
    ]
    # its Lead's: as they are
    assert own.held({}, on_item, call_tool) == (on_item, call_tool)


def test_a_roles_tools_as_copilots_own_and_as_approve_is_asked_of_them():
    from app.model_native import COPILOT_TOOLS

    names, held = copilot_tools(
        ["read_file", "write_file", "run_command", "web_search", "spawn_agent"]
    )
    assert set(names) <= set(COPILOT_TOOLS) and "task" not in names
    assert held == ["Read", "Write", "Bash"]
    assert copilot_tools(["read_file", "write_file", "run_command"], ("read_only",)) == (
        ["view"],
        ["Read"],
    )
    assert copilot_tools(["read_file", "run_command"], ("run",)) == (["view"], ["Read"])
    assert copilot_tools(["read_file"], ("agents",)) == ([], [])
    assert copilot_tools(["spawn_agent", "ask_user", "search"]) == ([], [])  # (none: not offered)
    # (its view reads a file as it lists a folder: a role that may only list is given none)
    assert copilot_tools(["list_dir"]) == ([], [])


def test_its_task_call_asked_again_is_refused_and_a_sub_agent_past_its_task_may_use_nothing():
    own = opened({"koloni-x": ["view"]})
    hook = {
        "kind": "hook",
        "toolName": "task",
        "toolArgs": {"agent_type": "koloni-x", "mode": "sync"},
    }
    answer, _told = gate(own, {}, hook, "t1")
    assert answer["kind"] == "reject" and "asked again" in answer["feedback"]
    view = {"kind": "hook", "toolName": "view", "toolArgs": {"path": "a.py"}}
    assert gate(own, {"agentId": "a1"}, view)[0] is None
    ended = {"type": "tool.execution_complete", "data": {"toolCallId": "t1", "success": True}}
    (done,) = own.translator(lambda _event: [], {})(ended)
    assert done["item"] == {"type": "sub_agent", "id": "t1", "status": "completed", "text": ""}
    answer, _told = gate(own, {"agentId": "a1"}, view, "u2")
    assert answer["kind"] == "reject" and "did not open this sub-agent" in answer["feedback"]


def test_a_refused_call_said_to_have_run_all_the_same_stays_on_record():
    own = opened({"koloni-x": ["view"]})
    shell = {"kind": "hook", "toolName": "powershell", "toolArgs": {"command": "x"}}
    assert gate(own, {"agentId": "a1"}, shell, "u3")[0]["kind"] == "reject"
    ran = [
        {"type": "busy", "id": "u3", "on": False},
        {"type": "item.completed", "item": {"id": "u3"}},
    ]
    translate = own.translator(lambda _event: list(ran), {})
    said = {"type": "tool.execution_complete", "agentId": "a1", "data": {"toolCallId": "u3"}}
    assert translate({**said, "data": {**said["data"], "success": True}}) == ran
    assert translate({**said, "data": {**said["data"], "success": False}}) == ran[:1]


def test_a_repeated_task_request_then_its_failed_end_still_ends_its_sub_agent():
    # (The review's P3: the repeat put the task call among the refused, and its failed end was
    # left off - its sub-agent kept working past it.)
    own = opened({"koloni-x": ["view"]})
    hook = {
        "kind": "hook",
        "toolName": "task",
        "toolArgs": {"agent_type": "koloni-x", "mode": "sync"},
    }
    assert gate(own, {}, hook, "t1")[0]["kind"] == "reject"
    failed = {"type": "tool.execution_complete", "data": {"toolCallId": "t1", "success": False}}
    (done,) = own.translator(lambda _event: [], {})(failed)
    assert done["item"]["status"] == "failed"
    view = {"kind": "hook", "toolName": "view", "toolArgs": {"path": "a.py"}}
    answer, _told = gate(own, {"agentId": "a1"}, view, "u9")
    assert answer["kind"] == "reject" and "did not open this sub-agent" in answer["feedback"]


def test_whose_request_it_is_its_hook_says_when_its_envelope_does_not():
    # (The review's P4: a sub-agent's request with no agentId on its envelope was its Lead's.)
    own = opened({"koloni-x": ["view"]})
    hook = {"hookType": "preToolUse", "input": {"toolCallId": "u5", "agentId": "a1"}}
    assert own.hooked(hook) is hook
    mcp = {"kind": "hook", "toolName": "koloni-spawn_agent", "toolArgs": {}, "toolCallId": "u5"}
    answer, _told = gate(own, {"agentId": None, "permissionRequest": mcp}, mcp, "u5")
    assert answer["kind"] == "reject" and "Orchestrator's" in answer["feedback"]


def test_a_start_naming_a_role_by_name_but_another_type_or_no_call_opens_nothing():
    # (The review's P8 and P9: measured, C5 - its start names the task call and the role's type.)
    for data in (
        {"toolCallId": "t1", "agentName": "koloni-x", "agentType": "general-purpose"},
        {"agentName": "koloni-x", "agentType": "koloni-x"},
    ):
        own = OwnAgents(set(), call_tool=None)
        own.given({"tools": {}}, {"koloni-x": {"description": "", "prompt": "", "tools": ["view"]}})
        hook = {
            "kind": "hook",
            "toolName": "task",
            "toolArgs": {"agent_type": "koloni-x", "mode": "sync"},
        }
        assert gate(own, {}, hook, "t1")[0] == APPROVE_ONCE
        started = {"type": "subagent.started", "agentId": "a1", "data": data}
        assert own.translator(lambda _event: [], {})(started) == [] and own.agents == {}, data


def test_a_sub_agents_command_runs_where_its_folder_is_not_known_and_a_delete_needs_its_shell():
    asked: list = []

    async def call_tool(name, arguments):
        asked.append(json.loads(arguments))
        return True, "{}"

    async def on_item(phase, item):
        pass

    own = opened({"koloni-x": ["view", "edit", "apply_patch"]})
    _told, asking = own.held({"agentId": "a1"}, on_item, call_tool)
    bash = {"tool_name": "Bash", "input": {"command": "git status", "new_shell": True}}
    delete = {"tool_name": "Edit", "input": {"file_path": "a.py", "kind": "delete"}}
    edit = {"tool_name": "Edit", "input": {"file_path": "a.py", "kind": "update"}}
    for one in (bash, delete, edit):
        asyncio.run(asking("approve", json.dumps(one)))
    assert asked[0]["input"]["new_shell"] is False  # (KOLONİ's prefix is not applied: C6)
    assert asked[1]["tool_name"] == "Delete" and asked[2]["tool_name"] == "Edit"
    runner = opened({"koloni-x": ["view", "edit", "apply_patch", "powershell"]})
    _told, asking = runner.held({"agentId": "a1"}, on_item, call_tool)
    asyncio.run(asking("approve", json.dumps(delete)))
    assert asked[-1]["tool_name"] == "Edit"


def turn_counts(checkpoint, calls=(), spent=None):
    """A Copilot turn's counts as its run reaches them: its root's checkpoint (`checkpoint`, the
    session's input tokens so far) with its model calls' own usage (`calls`: (agentId or None,
    input tokens)) carried out (`OwnAgents.with_calls`), its kept session's `spent` taken off
    (`copilot_since`, in `_keep`), then its own sub-agents' spend (`with_own_calls`, in
    `_native_work`); and what its session keeps as spent."""
    from app.copilot_own_agents import with_own_calls
    from app.model_session import SessionResult, copilot_since

    own = OwnAgents(set(), call_tool=None)
    for agent, tokens in calls:
        event = {"type": "assistant.usage", "data": {"inputTokens": tokens}}
        own.apart({**event, **({"agentId": agent} if agent else {})})
    since, kept = copilot_since(own.with_calls(SessionResult(checkpoint, None)), spent)
    return with_own_calls(since).input_tokens, kept


def test_a_sub_agents_own_usage_is_counted_in_its_turn_never_twice_nor_kept_as_spent():
    # (The review's Q4: the larger was taken before a kept session's spend came off, and kept.)
    # its root's checkpoint without the sub-agent's spend: the calls' sum counts, the checkpoint
    # alone is kept as spent
    first, kept = turn_counts(100, [(None, 100), ("a1", 400)])
    assert (first, kept["input_tokens"]) == (500, 100)
    # the next turn, gone on in that session: no sub-agent, the Lead's 100 (and 600) more
    assert turn_counts(200, [(None, 100)], kept)[0] == 100
    assert turn_counts(700, [(None, 600)], kept)[0] == 600
    # one whose checkpoint holds it: the checkpoint alone, never the two added
    assert turn_counts(500, [(None, 100), ("a1", 400)])[0] == 500
    # with no sub-agent, as before: the checkpoint less what was spent
    assert turn_counts(300, [(None, 999)], {"input_tokens": 100})[0] == 200
    own = OwnAgents(set(), call_tool=None)
    # its context is never its Lead's
    assert own.apart({"type": "session.usage_info", "agentId": "a1", "data": {}}) is True


def asking(answers):
    """A gate whose role is asked about (`asks`), each `approve` waiting for its turn in
    `answers` (asyncio events, then the verdict); and the task calls `approve` was asked of."""
    asked: list = []

    async def call_tool(name, arguments):
        asked.append(json.loads(arguments)["tool_use_id"])
        release, verdict = answers[len(asked) - 1]
        await release.wait()
        return True, json.dumps({"behavior": verdict})

    own = OwnAgents(set(), call_tool)
    own.given(
        {"tools": {}},
        {"koloni-w": {"description": "", "prompt": "", "tools": ["view"], "asks": lambda: True}},
    )
    return own, asked


TASK_HOOK = {
    "kind": "hook",
    "toolName": "task",
    "toolArgs": {"agent_type": "koloni-w", "mode": "sync", "name": "w", "prompt": "p"},
}


def test_one_task_call_asked_twice_while_its_card_waits_is_one_card_one_yes():
    # (The review's Q1 and Q1b: two cards, two yeses - the late one put the task back as not yet
    # started, and its sub-agent worked on past its task's end.)
    async def told(phase, item):
        pass

    async def twice():
        first, second = asyncio.Event(), asyncio.Event()
        own, asked = asking([(first, "allow"), (second, "allow")])
        one = asyncio.ensure_future(own.gate({}, TASK_HOOK, "t1", told))
        await asyncio.sleep(0)
        again = await own.gate({}, TASK_HOOK, "t1", told)  # (while its card waits)
        first.set()
        second.set()
        return own, asked, await one, again

    own, asked, one, again = asyncio.run(twice())
    assert asked == ["t1"] and one == APPROVE_ONCE, (asked, one)
    assert again["kind"] == "reject" and "asked again" in again["feedback"]
    start = {
        "type": "subagent.started",
        "agentId": "a1",
        "data": {"toolCallId": "t1", "agentType": "koloni-w"},
    }
    translate = own.translator(lambda _event: [], {})
    translate(start)
    assert gate(own, {}, TASK_HOOK, "t1")[0]["kind"] == "reject"  # (and once it has started)
    translate({"type": "tool.execution_complete", "data": {"toolCallId": "t1", "success": True}})
    view = {"kind": "hook", "toolName": "view", "toolArgs": {"path": "a.py"}}
    answer, _told = gate(own, {"agentId": "a1"}, view, "u9")
    assert answer["kind"] == "reject" and own.agents == {}, (answer, own.agents)


def test_whether_its_role_is_asked_about_is_read_as_its_task_comes():
    # (The review: decided once at the turn's start, a level tightened to Ask mid-turn showed no
    # card.)
    level = {"asks": False}
    asked: list = []

    async def call_tool(name, arguments):
        asked.append(json.loads(arguments)["tool_use_id"])
        return True, json.dumps({"behavior": "allow"})

    own = OwnAgents(set(), call_tool)
    own.given(
        {"tools": {}},
        {
            "koloni-w": {
                "description": "",
                "prompt": "",
                "tools": ["view"],
                "asks": lambda: level["asks"],
            }
        },
    )
    assert gate(own, {}, TASK_HOOK, "t1")[0] == APPROVE_ONCE and asked == []
    level["asks"] = True
    assert gate(own, {}, TASK_HOOK, "t2")[0] == APPROVE_ONCE and asked == ["t2"]


def test_a_level_tightened_to_ask_mid_turn_makes_its_role_a_card(
    copilot_native,
    wait_run,
    project_dir,  # noqa: F811
):
    # (A read of .env is a card at every level: while it waits the user tightens to Ask.)
    (project_dir / ".env").write_text("TOKEN=x\n", encoding="utf-8")
    client, provider = p4(
        copilot_native,
        [
            {"shell": "Get-Content .env", "quiet": True, "output": "TOKEN=x"},
            {**RUNNER_TASK, "steps": [{"say": "built"}]},
            {"say": "Done."},
        ],
        RUNNER,
    )
    cid, run_id = start(client, project_dir, provider)  # full_auto
    asked = wait_status(client, cid, "waiting_approval")["commands"][0]
    tightened = client.patch(
        f"/api/conversations/{cid}", json={"permission_mode": "ask"}, headers=ORIGIN
    )
    assert tightened.status_code == 200, tightened.text
    client.post(f"/api/commands/{asked['id']}/approve", json={})
    question = until_question(client, cid)
    assert "koloni-runner" in question["question"]
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "Allow"}, headers=ORIGIN)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]


def test_at_ask_a_sub_agents_git_read_asks_where_its_leads_runs(
    copilot_native,
    wait_run,
    project_dir,  # noqa: F811
):
    # (Its Lead's command is put in the project by KOLONİ's prefix; a sub-agent's is not: C6.)
    client, provider = p4(
        copilot_native,
        [
            {"shell": "git status"},
            {**RUNNER_TASK, "steps": [{"shell": "git status"}]},
            {"say": "ok"},
        ],
        RUNNER,
    )
    cid, run_id = start(client, project_dir, provider, mode="ask")
    question = until_question(client, cid)  # (its Lead's git read ran unasked before it)
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "Allow"}, headers=ORIGIN)
    from tests.test_parallel import until

    snap = until(client, cid, lambda s: any(c["status"] == "proposed" for c in s["commands"]))
    (lead,) = [c for c in snap["commands"] if c["status"] == "exited"]  # (unasked)
    (asked,) = [c for c in snap["commands"] if c["status"] == "proposed"]
    assert (lead["cwd"], asked["command"], asked["cwd"]) == (".", "git status", None), asked
    client.post(f"/api/commands/{asked['id']}/approve", json={})
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]


RUNNER_TASK = {"task": "koloni-runner", "mode": "sync"}


def until_question(client, cid):
    """The question waiting for the user, once it is shown."""
    from tests.test_parallel import until

    snap = until(client, cid, lambda s: bool(s["questions"]))
    return snap["questions"][0]


@pytest.mark.judge  # (Full auto's judge stands aside in tests unless marked: conftest)
def test_at_full_auto_a_sub_agents_git_line_is_judged_where_its_folder_is_not_known(
    copilot_native,
    wait_run,
    project_dir,
    monkeypatch,  # noqa: F811
):
    # (Its hook's modifiedArgs is not applied to a sub-agent's command - C6 -: never read as run at
    # the root, as its Lead's is, so its git is the judge's: `risk_judge.git_below`.)
    client, provider = p4(
        copilot_native,
        [
            {"shell": "git status"},
            {"task": "koloni-runner", "mode": "sync", "steps": [{"shell": "git status"}]},
            {"say": "Done."},
        ],
        RUNNER,
    )
    runner, judged = client.app.state.runner, []

    async def judging(ctx, command, cwd, root, known, takes=False):
        judged.append((command, cwd, known))
        return "", None

    monkeypatch.setattr(runner, "_risk_judging", judging)
    _cid, snap = run(client, project_dir, provider, wait_run)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert ("git status", None, False) in judged, judged
    lead, sub = sorted(snap["commands"], key=lambda c: c["cwd"] is None)
    assert (lead["cwd"], sub["cwd"]) == (".", None), snap["commands"]


def test_a_kept_session_keeps_its_checkpoint_as_spent_and_counts_its_sub_agent_in_its_turn(
    copilot,
    tmp_path,  # noqa: F811
):
    # (The review's Q4, through `run_native`'s own `_keep`: its spend is kept from the checkpoint,
    # its sub-agent's counted only in its turn - `with_own_calls`, in `_native_work`.)
    from app.copilot_own_agents import with_own_calls
    from tests.test_copilot_resume import FIRST, checkpoint

    inside = {"koloni-w": {"description": "d", "prompt": "p", "tools": ["view"]}}
    usage = {"event": "assistant.usage", "data": {"inputTokens": 400}}
    cli = copilot(
        script=[{"task": "koloni-w", "mode": "sync", "steps": [usage]}, {"say": "Done."}],
        usage=[checkpoint(100, 10, 1)],
        call_usage={"inputTokens": 100},
    )

    async def call_tool(name, arguments):
        return True, "{}"

    async def nothing(*_args):
        return None

    result = asyncio.run(
        cli.run_native(
            "gpt-6-luna",
            FIRST,
            [],
            str(tmp_path),
            call_tool,
            nothing,
            nothing,
            inside=inside,
            level="full_auto",
            keep=True,
        )
    )
    assert result.session and result.session["spent"]["input_tokens"] == 100, result
    assert with_own_calls(result).input_tokens == 500, result
