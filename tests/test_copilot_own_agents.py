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
from tests.test_codex_app_server_scenarios import card_for
from tests.test_copilot_agent import copilot_native, start  # noqa: F401  (a fixture)
from tests.test_copilot_headless_scenarios import APPROVE, REJECT, answers
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


def test_a_role_inside_copilot_works_under_its_task_call_held_to_its_tools(
    copilot_native,
    wait_run,
    project_dir,  # noqa: F811
):
    client, provider = p4(
        copilot_native,
        [
            {
                **SYNC,
                "steps": [
                    {"read": "hello.py", "result": "print('hi')"},
                    {"shell": "Set-Content ran.txt x", "touches": {"ran.txt": "x"}},
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


def test_a_tool_its_role_gives_it_is_asked_as_its_leads_a_card_at_ask(
    copilot_native,
    wait_run,
    project_dir,  # noqa: F811
):
    client, provider = p4(
        copilot_native,
        [
            {
                "task": "koloni-runner",
                "mode": "sync",
                "steps": [{"shell": "Set-Content ran.txt x", "touches": {"ran.txt": "x"}}],
            },
            {"say": "Done."},
        ],
        RUNNER,
    )
    cid, run_id = start(client, project_dir, provider, mode="ask")
    asked = card_for(client, cid, "Set-Content ran.txt x")
    assert not (project_dir / "ran.txt").exists()
    assert client.post(f"/api/commands/{asked['id']}/approve", json={}).status_code == 200
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert (project_dir / "ran.txt").exists()
    sub = by_name(snap)["copilot__task"]
    (ran,) = [c for c in snap["tool_calls"] if c["id"] == snap["commands"][0]["tool_call_id"]]
    assert ran["parent_call_id"] == sub["id"], (ran, sub)


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
    own = OwnAgents(set())
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
        "data": {"toolCallId": "t1", "agentName": first},
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
        ("approve", {"tool_name": "Read", "agent_type": "koloni-x"}),
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
