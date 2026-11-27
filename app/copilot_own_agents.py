"""GitHub Copilot CLI's own sub-agents as KOLONİ's roles (0.1.11; Claude Code's are 89g's): a
Copilot Orchestrator run Native at protocol 4, asked through KOLONİ's hook, is given the roles the
user lets run inside the CLI (`Role.inside_cli`) as agents of its own (session.create's `agents`),
and opens one with its `task` tool.

Measured on Copilot 1.0.114 (27 Nov 2026, an empty COPILOT_HOME; cli-kendi-alt-ajanlari.md, C1-C6):
the session takes `agents.definitions` with `includedBuiltinAgents: []` and lists only those; its
task is called with {description, prompt, agent_type, name, mode: "sync"} (`name` its own must);
`subagent.started` names that call (`toolCallId`) and the role (`agentType`), the sub-agent on its
Lead's model; each tool of a sub-agent comes to KOLONİ's preToolUse hook, then as a permission
request in its Lead's session - as do its events, its own usage among them - each with the
sub-agent's `agentId` (absent for the Lead's); its Lead alone goes idle; a role's `tools` hold it
to those (one given none had every tool of the session's, never more); and KOLONİ's MCP bridge is
shared with it, started once - a sub-agent could reach KOLONİ's tools, its Lead's, through it: here
it may not. The hook's modifiedArgs is not applied to a sub-agent's command (C6): where its shell
starts is not known.

Here: what a role is given (`copilot_tools`), the session's fields (`OwnAgents.given`), the gate of
its task call and of a sub-agent's requests (`OwnAgents.gate`), and a sub-agent's events apart from
its Lead's (`OwnAgents.apart`, `OwnAgents.translator`) - on record as one call of `task`, its tools
under it, as Claude Code's Agent is (`ClaudeNativeClient._translator`).
shortcut: a sub-agent's create, edit and apply_patch are not measured (it wrote with PowerShell
in C6): they are asked as its Lead's are, by the forms its Lead's were measured in.
shortcut: a role is given no model of its own (the role's `model` is not measured in a definition:
one refused would stop the turn); it runs on its Lead's.
shortcut: at protocol 3 no role is offered, and nothing says so (Claude Code's `inside_not_given`).
shortcut: a kept session goes on (session.resume) given this turn's roles anew, as session.create
is - not measured that it takes them so; the gate holds it to this turn's alone all the same.
shortcut: a patch a sub-agent sends as a command (`_heredoc_patch`, `AgentRunner._runs_as_patch`)
is read against the project's root, though where its command runs is not known (C6); read it as
a command alone if a sub-agent is seen to send one.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import replace

from app.model_cli import _dict
from app.model_client import count_of
from app.model_session import COPILOT_PREFIX, CallTool, SessionResult, _sum

OnItem = Callable[[str, dict], Awaitable[None]]

# A role's tools (KOLONİ's names) as Copilot's own: only those its Lead is given (`COPILOT_TOOLS`),
# never its task nor KOLONİ's tools. apply_patch, the one file tool of models other than Claude
# (B-393), goes with either file tool: each file of a patch is asked as its Write or Edit, held to
# the role there (`_approve`). Not its grep or glob (as its Lead: a search reads secrets uncarded);
# nor list_dir's: its view reads a file's lines as it lists a folder - a role that may list but not
# read would be let read.
COPILOT_OF = {
    "read_file": ("view",),
    "write_file": ("create", "apply_patch"),
    "edit_file": ("edit", "apply_patch"),
    "run_command": ("powershell", "read_powershell", "stop_powershell", "list_powershell"),
}
# ...and what `_permit` asks `approve` of each (`CopilotNativeClient._from_hook`): what `_approve`
# holds a sub-agent to (`_Watch.roles`).
ASKED_AS = {
    "read_file": "Read",
    "write_file": "Write",
    "edit_file": "Edit",
    "run_command": "Bash",
}
# KOLONİ's answer to a permission request it lets through: this once, never for the session.
APPROVE_ONCE = {"kind": "approve-once"}
TASK = "task"
# What its task is called with (measured, C5): any other key - a model, a level, a context tier -
# would choose past KOLONİ's own pick of a model and its cards.
TASK_KEYS = frozenset({"description", "prompt", "agent_type", "name", "mode"})
# A model call's own usage (`assistant.usage`, a sub-agent's too: C6), as its run's counts name it.
CALL_COUNTS = {
    "input_tokens": "inputTokens",
    "output_tokens": "outputTokens",
    "cache_read": "cacheReadTokens",
    "cache_write": "cacheWriteTokens",
}
SUB_EVENTS = ("subagent.started", "subagent.completed", "subagent.failed")
# A sub-agent's events read as such; every other of one is its own, never its Lead's (`apart`).
SUB_KINDS = ("tool.execution_start", "tool.execution_complete", "permission.requested", *SUB_EVENTS)


def copilot_tools(tools: list[str], withheld: tuple[str, ...] = ()) -> tuple[list[str], list[str]]:
    """A role's tools as Copilot's own, and as `approve` is asked of them; less what its Lead's run
    is started without (read-only: view alone, as its Lead's), and none where its Lead's model is
    closed to agents."""
    if "agents" in withheld:
        return [], []
    off = {"write_file", "edit_file", "run_command"} if "read_only" in withheld else set()
    off |= {"write_file", "edit_file"} if "write" in withheld else set()
    off |= {"run_command"} if "run" in withheld else set()
    kept = [tool for tool in tools if tool in COPILOT_OF and tool not in off]
    return (
        list(dict.fromkeys(name for tool in kept for name in COPILOT_OF[tool])),
        list(dict.fromkeys(ASKED_AS[tool] for tool in kept)),
    )


def with_own_calls(result: SessionResult) -> SessionResult:
    """A Copilot turn's counts with its own sub-agents' spend (`own_calls`): each the larger of its
    turn's count by the checkpoint (a kept session's already less what it spent before:
    `copilot_since`) and its model calls' own usage summed, its sub-agents' with them - never the
    two added; as they are where no sub-agent spent.
    shortcut: whether the checkpoint holds its sub-agents' spend is not measured (C6): where it
    does, it stands; where not, the calls' sum does. Its AI credits (totalNanoAiu) are the
    checkpoint's alone (a call's `cost` and `copilotUsage` are not read: their form is not seen)."""
    if result.own_calls is None:
        return result
    calls: dict = result.own_calls

    def larger(field: str) -> int | None:
        known = [one for one in (getattr(result, field), calls.get(field)) if one is not None]
        return max(known) if known else None

    return replace(
        result,
        input_tokens=larger("input_tokens"),
        output_tokens=larger("output_tokens"),
        cache_read=larger("cache_read"),
        cache_write=larger("cache_write"),
        own_calls=None,
    )


class OwnAgents:
    """One Copilot turn's own sub-agents. `offered`: the roles given it, by name, with their
    Copilot tools (none at protocol 3, nor where none is given); `tasks`: its Lead's task calls
    KOLONİ let through, by call id - the role, what it was given, the sub-agent's agentId once it
    started, how it ended; `agents`: each sub-agent that started, by agentId, the task call it is
    on record under; `words`: each one's last; `refused`: the calls refused here (their failed end
    is not put on record again); `hooks`: whose each tool call is, by its preToolUse hook
    (`hooked`); `calls`: every model call's own usage, summed (`with_calls`); `pending`: its
    task calls whose card waits (`gate`). `asked`: its turn's calls asked about (`_converse`'s:
    one of them that ends did not run unasked); `call_tool`: its run's."""

    def __init__(self, asked: set[str], call_tool: CallTool) -> None:
        self.asked, self.call_tool = asked, call_tool
        self.offered: dict[str, list[str]] = {}
        self.asks: dict[str, Callable[[], bool] | None] = {}
        self.pending: set[str] = set()
        self.hooks: dict[str, str] = {}
        self.calls: dict[str, int | None] = {}
        self.spent_inside = False
        self.tasks: dict[str, dict] = {}
        self.agents: dict[str, str] = {}
        self.words: dict[str, str] = {}
        self.refused: set[str] = set()

    def given(self, session: dict, inside: dict[str, dict] | None) -> dict:
        """session.create at protocol 4 (grouped), with the roles as agents of its own and its
        task tool - none of its built-in agents - where any is given. Each only by its name, line,
        instructions and tools: never one with no tools (it would have every tool of the
        session's: measured)."""
        roles = {name: role for name, role in (inside or {}).items() if role.get("tools")}
        if not roles:
            return session
        self.offered = {name: list(role["tools"]) for name, role in roles.items()}
        self.asks = {name: role.get("asks") for name, role in roles.items()}
        tools = _dict(session.get("tools"))
        return {
            **session,
            "tools": {**tools, "availableTools": [*tools.get("availableTools", []), TASK]},
            "agents": {
                "definitions": [
                    {
                        "name": name,
                        "description": role["description"],
                        "prompt": role["prompt"],
                        "tools": list(role["tools"]),
                    }
                    for name, role in roles.items()
                ],
                "includedBuiltinAgents": [],
            },
        }

    def apart(self, event: dict) -> bool:
        """Whether an event of its is a sub-agent's that is no business of its Lead's turn: its
        words (kept, as its report where none comes), model, context, compaction, idle or error.
        Its tools, requests, start and end are read on (`translator`, `gate`). Each model call's
        own usage, its Lead's and its sub-agents', is summed (`with_calls`)."""
        agent, kind = str(event.get("agentId") or ""), event.get("type")
        data = _dict(event.get("data"))
        if agent and kind == "assistant.message":
            self.words[agent] = str(data.get("content") or "") or self.words.get(agent, "")
        if kind == "assistant.usage":
            for field, said in CALL_COUNTS.items():
                self.calls[field] = _sum(self.calls.get(field), count_of(data.get(said)))
            self.spent_inside |= bool(agent)
        return bool(agent) and kind not in SUB_KINDS

    def with_calls(self, result: SessionResult) -> SessionResult:
        """Its run's result, its checkpoint's counts as they are (a kept session's `spent` is kept
        from those: `copilot_since`), with its model calls' own usage summed where a sub-agent of
        its own spent (`own_calls`): what `with_own_calls` counts once its turn's are known."""
        return replace(result, own_calls=dict(self.calls)) if self.spent_inside else result

    def hooked(self, params: dict) -> dict:
        """A hook of its (`hooks.invoke`; `read` hands on every message's params, and only a hook's
        say a hookType): whose tool call a preToolUse's is, where it names a sub-agent - its request
        is that sub-agent's, whatever its envelope says. Its params, as they are."""
        given = _dict(params.get("input"))
        call, agent = given.get("toolCallId"), given.get("agentId") or params.get("agentId")
        if params.get("hookType") == "preToolUse" and call and agent:
            self.hooks[str(call)] = str(agent)
        return params

    def _agent(self, data: dict) -> str:
        """The sub-agent a permission request is of: its envelope's agentId, else its hook's
        (`hooked`); "" for its Lead's."""
        call = str(_dict(data.get("permissionRequest")).get("toolCallId") or "")
        return str(data.get("agentId") or self.hooks.get(call) or "")

    def translator(
        self, translate: Callable[[dict], list[dict]], ours: dict[str, str]
    ) -> Callable[[dict], list[dict]]:
        """Its Lead's translator (`CopilotNativeClient._translator`), its own sub-agents told
        apart: one started by a task call KOLONİ let through is that call, on record as a
        sub_agent item that ends with it; a call of a sub-agent's is never one of KOLONİ's own
        that the hook lets through (`ours`, `_kolonis`), whatever its start says."""

        def told(event: dict) -> list[dict]:
            kind, data = event.get("type"), _dict(event.get("data"))
            agent, call = str(event.get("agentId") or ""), str(data.get("toolCallId") or "")
            if kind in SUB_EVENTS:
                return self._sub_event(kind, agent, data)
            said = translate(event)
            if agent:
                ours.pop(call, None)
            if kind != "tool.execution_complete":
                return said
            if call in self.refused and data.get("success") is False and call not in self.tasks:
                return [one for one in said if one["type"] == "busy"]
            return self._task_ended(call, data, said)

        return told

    def _sub_event(self, kind: object, agent: str, data: dict) -> list[dict]:
        """A sub-agent started, or said it ended (`translator`). One whose start names no task call
        KOLONİ let open, still to start, as of that very role (its toolCallId and agentType:
        measured, C5) is none of KOLONİ's: never registered, so it may use nothing (`gate`)."""
        if kind != "subagent.started":
            if call := self.agents.get(agent):
                self.tasks[call]["ended"] = "failed" if kind == "subagent.failed" else "completed"
            return []
        call = str(data.get("toolCallId") or "")
        task = self.tasks.get(call)
        if (
            not agent
            or agent in self.agents
            or task is None
            or task["agent"] is not None
            or data.get("agentType") != task["type"]
        ):
            return []
        self.agents[agent], self.tasks[call]["agent"] = call, agent
        return [
            {
                "type": "item.started",
                "item": {
                    "type": "sub_agent",
                    "id": call,
                    "server": "copilot",
                    "tool": TASK,
                    "arguments": self.tasks[call]["given"],
                },
            }
        ]

    def _task_ended(self, call: str, data: dict, said: list[dict]) -> list[dict]:
        """Its Lead's task call ended: where its sub-agent started, the end of that sub-agent -
        its report what the call returned, else why it failed, else its last words; from now on
        it may use nothing (one still at work past its task call is followed by nobody). One that
        never started is a call like any other."""
        task = self.tasks.get(call)
        if not task or task["agent"] is None:
            return said
        self.agents.pop(task["agent"], None)
        failed = data.get("success") is False or task.get("ended") == "failed"
        text = (
            str(_dict(data.get("result")).get("content") or "")
            or str(_dict(data.get("error")).get("message") or "")
            or self.words.get(task["agent"], "")
        )
        return [
            *(one for one in said if one["type"] == "busy"),
            {
                "type": "item.completed",
                "item": {
                    "type": "sub_agent",
                    "id": call,
                    "status": "failed" if failed else "completed",
                    "text": text,
                },
            },
        ]

    async def gate(self, data: dict, request: dict, use_id: str, on_item: OnItem) -> dict | None:
        """KOLONİ's own answer to a request of its Lead's task call, or of a sub-agent's (`_agent`);
        None: one `_permit` judges as its Lead's are (`held`). Each of a sub-agent KOLONİ let open
        hangs under its task call (announced so first). A role KOLONİ's own rules would ask before
        opening now (`asks`: as spawn_agent's, `cards._asked_about`, at the level its chat is at as
        the request comes) is asked of `approve` first, as Claude Code's Agent is: a card at Ask,
        its call the sub-agent's record once let. One task call is answered once: asked again,
        while its card waits too (`pending`), it is refused."""
        agent = self._agent(data)
        kind, name = request.get("kind"), request.get("toolName")
        if not agent and not (kind == "hook" and name == TASK):
            return None
        parent = self.agents.get(agent)
        if parent:
            await on_item("announced", {"id": use_id, "parent": parent})
        given = request.get("toolArgs") if kind == "hook" else None
        why = (
            "KOLONİ declined this request: it asked again for a task call that was answered"
            if not agent and (use_id in self.tasks or use_id in self.pending)
            else self._why(agent, parent, kind, name, given)
        )
        self.asked.add(use_id)  # (refused too: it was asked about, it did not run unasked)
        if why is None and agent:
            return None
        if why is None:
            role = _dict(given)["agent_type"]
            if (asks := self.asks.get(role)) and asks():
                self.pending.add(use_id)
                try:
                    refused = await self._asked(use_id, given, on_item)
                finally:
                    self.pending.discard(use_id)
                if refused or use_id in self.tasks:  # (answered meanwhile: never twice)
                    return refused or {"kind": "reject", "feedback": "it was answered"}
            self.tasks[use_id] = {"type": role, "given": given, "agent": None}
            return APPROVE_ONCE
        self.refused.add(use_id)
        await on_item(
            "completed",
            {
                "type": "mcp_tool_call",
                "id": use_id,
                "server": "copilot",
                "tool": str(name or f"permission {kind}"),
                "arguments": given if isinstance(given, dict) else {},
                "status": "declined",
                "error": {"message": why},
            },
        )
        return {"kind": "reject", "feedback": why}

    async def _asked(self, use_id: str, given: object, on_item: OnItem) -> dict | None:
        """`gate`'s question to `approve` of a task call whose role is asked about; its refusal,
        or None where it is let."""
        await on_item("announced", {"id": use_id})
        asked = {"tool_name": TASK, "input": given, "tool_use_id": use_id}
        _ok, said = await self.call_tool("approve", json.dumps(asked))
        verdict = _dict(json.loads(said))
        if verdict.get("behavior") == "allow":
            return None
        return {"kind": "reject", "feedback": str(verdict.get("message") or "rejected")}

    def _why(
        self, agent: str, parent: str | None, kind: object, name: object, given: object
    ) -> str | None:
        """Why `gate` refuses a request (None: it does not). Its Lead's task call opens only a role
        offered this turn, while its Lead waits for it ("sync": a sub-agent at work past its Lead's
        turn would be followed by nobody). A sub-agent's: nothing of one KOLONİ did not let open;
        never KOLONİ's tools (its Lead's), nor a task of its own, nor a tool its role was not
        given - by Copilot's names (its tools as offered: `_permit` then asks each as its Lead's,
        held to its role in `_approve`)."""
        if not agent:
            role, mode = _dict(given).get("agent_type"), _dict(given).get("mode")
            if not isinstance(given, dict) or set(given) - TASK_KEYS:
                more = ", ".join(sorted(map(str, _dict(given).keys() - TASK_KEYS))) or "none"
                return (
                    "KOLONİ lets your task take only description, prompt, agent_type, name and "
                    f"mode (not {more}): a role's model and level are KOLONİ's to choose"
                )
            if not isinstance(role, str) or role not in self.offered:
                offered = ", ".join(self.offered) or "none"
                return (
                    "KOLONİ opens only the roles it gave you as agents of your own "
                    f"({offered}), by their name as agent_type"
                )
            if mode != "sync":
                return 'call task with mode "sync": KOLONİ follows an agent of yours while you wait'
            return None
        if parent is None:
            return "KOLONİ did not open this sub-agent of Copilot's own: it may use nothing"
        if kind == "mcp" or (isinstance(name, str) and name.startswith(COPILOT_PREFIX)):
            return (
                "KOLONİ's tools are its Orchestrator's: a sub-agent of Copilot's may not use them"
            )
        if kind != "hook":
            return None  # (its tool's own request after its hook's: judged in `_permit`)
        if name == TASK:
            return "a sub-agent of Copilot's own may not open one of its own"
        role = self.tasks[parent]["type"]
        if name not in self.offered[role]:
            return f"{role} may not use {name}: its role does not give it that tool"
        return None

    def held(self, data: dict, on_item: OnItem, call_tool: CallTool) -> tuple[OnItem, CallTool]:
        """`_permit`'s on_item and call_tool for a request: a sub-agent's hangs what it announces
        under its task call, and tells `approve` its role (`_approve` holds it to its tools); its
        Lead's as they are. A sub-agent's command never runs where KOLONİ put it: its hook's
        modifiedArgs is not applied (C6), so its folder is not known (no `new_shell`, whatever was
        read) - judged so. A file it deletes is no edit: only a role that runs commands may (as
        Claude Code's Edit deletes none) - else asked as a `Delete` its role does not give."""
        parent = self.agents.get(self._agent(data))
        if parent is None:
            return on_item, call_tool
        role = self.tasks[parent]["type"]
        runs = "powershell" in self.offered[role]

        async def told(phase: str, item: dict) -> None:
            await on_item(phase, {**item, "parent": parent} if phase == "announced" else item)

        async def asked(name: str, arguments: str) -> tuple[bool, str]:
            if name == "approve":
                said = _dict(json.loads(arguments))
                given, tool = _dict(said.get("input")), said.get("tool_name")
                if "new_shell" in given:
                    given = {**given, "new_shell": False}
                if tool == "Edit" and given.get("kind") == "delete" and not runs:
                    tool = "Delete"
                said = {**said, "tool_name": tool, "input": given, "agent_type": role}
                arguments = json.dumps(said)
            return await call_tool(name, arguments)

        return told, asked
