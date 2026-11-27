"""What goes on while the turn's agents are at work: the Orchestrator held for them
(`_held_for_work`), a reply's several sub-agents opened together (`_together`), the sub-agents a
CLI opener did not wait for stopped (`_cancel_later`), and the user's messages queued behind the
turn (`_unread_messages`) - `AtWorkMixin`.
"""

import asyncio
import contextlib
import json
import logging
from collections import Counter
from dataclasses import replace
from datetime import UTC
from typing import TYPE_CHECKING

from sqlalchemy import literal_column, or_, select

from app import away, injection, recipe_run, web
from app.agent.ctx import TERMINAL, Ctx
from app.agent.questions_mixin import USER_TOLD
from app.agent.spawn_mixin import INTERNAL, SPAWN_ENDED, SPAWN_ENDED_SEE, SPAWN_REJECTED
from app.agent.words import (
    AGENT_TERMINAL,
    COMMAND_ENDED,
    COMMAND_LATER,
    COMMANDS_FULL,
    HANDED,
    LISTEN,
    NOT_HEARD,
    STEERED,
    STILL_AT_WORK,
    STOP_ASKED,
    STOP_DONE,
    STOP_FINISHED,
    STOP_NONE,
    STOP_NOT_SPAWNED,
    STOP_NOT_YOURS,
    STOPPED_BY,
    TEAM_STOPPED,
    TOLD_UNREAD,
    USER_STOPPED,
    WHY_ENDING,
    WHY_NOT,
    WHY_TOPIC,
    WORD_MAYBE_UNREAD,
    YOU_STOPPED,
)
from app.command_runner import DRAIN_GRACE_SECONDS, KILL_SECONDS, OUTPUT_AT_MOST
from app.commands import OutputMask
from app.db.models import (
    Agent,
    Command,
    Conversation,
    ConversationTeam,
    Message,
    Question,
    Role,
    Run,
    Team,
    ToolCall,
    now,
    settings_of,
)
from app.delivery import NOT_SENT, UNKNOWN, Delivery
from app.model_client import OwnStop, ToolCallRequest
from app.proof import PROOF_CALL
from app.serialize import message_out, run_out
from app.team import quoted
from app.tools import ToolError, parse_arguments
from app.tools_at_work import (
    AGENTS_AT_WORK_SCHEMA,
    AT_WORK_HEAD,
    AT_WORK_LINE,
    AT_WORK_NONE,
    AT_WORK_SAID,
    COMMAND_BACKGROUND_PROPERTY,
    LEAD_TOOLS,
    NOT_OPEN,
    SAID_MOST,
    SPAWN_BACKGROUND_PROPERTY,
    STOP_AGENT_SCHEMA,
)

if TYPE_CHECKING:
    from app.agent import AgentRunner

log = logging.getLogger(__name__)
LEADS_STOP = STOPPED_BY.format(who="the Orchestrator")
# Task 7: KOLONİ's own notice when an agent nobody waited for ends - its name and how it ended.
DONE_FOUND = "{name} finished: {n} finding{s}"
DONE_SAID = "{name} {how}"
DONE_HOW = {"completed": "finished", "cancelled": "stopped", "interrupted": "stopped"}
STOP_WAIT = KILL_SECONDS + DRAIN_GRACE_SECONDS  # (stop_command's, as for a command that serves)

# B-376 (live): a Copilot Lead gave its last answer while a team's "All at once" group had just
# opened its Tester: the turn ended, the Tester was cancelled and the rule was broken. Its answer
# is held till every agent of the turn is back, then it is told so (`_held_for_work`).
AT_WORK = ("proposed", "queued", "running", "waiting")
HELD_FOR_WORK = (
    "Not the end yet: teams were still at work as you answered ({what}). KOLONİ "
    "waited for them: read what came back, then answer."
)
HOLD_LOOK = 0.5  # seconds between looks at whether they are back


class AtWorkMixin:
    def _at_work_init(self: "AgentRunner") -> None:
        """`AgentRunner.__init__`'s part for what goes on beside the turn's agents."""
        # D3: each sub-agent's own work while it runs (`_see_through_run`), and why one that was
        # stopped alone was (`stop_agent`).
        self._own_work: dict[str, asyncio.Task] = {}
        self._stopped_one: dict[str, str] = {}
        # D1: the API Orchestrator's background spawns answered "started" (`_said_at_once`).
        self._went_on_calls: set[str] = set()
        # Task 8: its background commands at work, by their call's id: (its turn, its task).
        self._commands_later: dict[str, tuple[str, asyncio.Task]] = {}
        # D2: the user's words sent into a turn that no step of its Orchestrator read yet (by
        # the turn), what wakes its waits for them, the turns whose door is shut, the
        # Orchestrators that answer one now (no writes), and what each was sent at its step.
        self._unheard: dict[str, list[str]] = {}
        self._word: dict[str, asyncio.Event] = {}
        self._door_shut: set[str] = set()
        self._listening: set[str] = set()
        self._seen_by: dict[str, list[str]] = {}
        # The user's words steered into its CLI's turn and taken there, or that may have been
        # (C2: `_word_went`), by chat - what a session it goes on in has (`_steered_marks`).
        self._steered_ids: dict[str, set[str]] = {}
        # The user's words to the Orchestrator about an agent that hears nothing (`to_lead`):
        # (its note's id, the agent's name, the words), by turn; and a word's spoken ask.
        self._told_lead: dict[str, list[tuple[str, str, str]]] = {}
        self._word_spoken: dict[str, dict | None] = {}
        self._lead_tools_init()  # (the Orchestrator's own tools: `LeadToolsMixin`)

    def _at_work_offered(self: "AgentRunner", ctx: Ctx, schemas: list[dict]) -> None:
        """`_offered`'s schemas, with what goes on beside the turn's agents where it is this
        agent's: spawn_agent's `background` (D1); stop_agent for the Orchestrator that may open
        agents (D3) - a CLI's too, over MCP."""
        if self._background_offered(ctx):
            for spawn in (s["function"] for s in schemas if s["function"]["name"] == "spawn_agent"):
                spawn["parameters"]["properties"]["background"] = SPAWN_BACKGROUND_PROPERTY
        if self._at_work_open(ctx) and any(s["function"]["name"] == "spawn_agent" for s in schemas):
            schemas.append(STOP_AGENT_SCHEMA)
            schemas.append(AGENTS_AT_WORK_SCHEMA)  # (D4: who of them is at work)
            self._lead_offered(ctx, schemas)
        if self._background_offered(ctx) and self._serving_not(ctx) is None:
            for run in (s["function"] for s in schemas if s["function"]["name"] == "run_command"):
                run["parameters"]["properties"]["background"] = COMMAND_BACKGROUND_PROPERTY

    def _command_offered_later(self: "AgentRunner", ctx: Ctx, request, args: dict) -> bool:
        """Task 8: whether this run_command is the API Orchestrator's in the background - where
        command_output and stop_command are its (`_serving_not`: not in a job nobody watches,
        not in an answer); else it runs as ever, whatever it asked."""
        return (
            request.name == "run_command"
            and args.get("background") is True
            and not args.get("keep_running")
            and self._background_offered(ctx)
            and self._serving_not(ctx) is None
        )

    async def _command_later(
        self: "AgentRunner", ctx: Ctx, call_id: str, request: ToolCallRequest, args: dict
    ) -> tuple[str, str]:
        """Task 8: the command started as its own call would run it - the same list, judge,
        cards, places kept out and copy (`_run_call` with it, in a task) - and answered at once;
        its record's result is what it printed once it ends, when a note of KOLONİ's wakes the
        Orchestrator (`team_requests.woken`). Held to the chat's spawn_max_parallel at once (its
        others named); stopped with stop_command, the turn's Stop, and the turn's end."""
        mine = [one for one, (run, _task) in self._commands_later.items() if run == ctx.run_id]
        with self._factory() as session:
            most = settings_of(session, session.get_one(Conversation, ctx.cid)).spawn_max_parallel
        if len(mine) >= most:
            raise ToolError(COMMANDS_FULL.format(n=len(mine), ids=", ".join(mine)))
        alone = {key: value for key, value in args.items() if key != "background"}
        later = replace(request, arguments=json.dumps(alone))
        task = asyncio.ensure_future(self._command_comes(ctx, call_id, later))
        self._commands_later[call_id] = (ctx.run_id, task)
        task.add_done_callback(lambda _done: self._commands_later.pop(call_id, None))
        self._answers_out.setdefault(ctx.agent_id, []).append(task)
        return "succeeded", COMMAND_LATER.format(id=call_id)

    async def _command_comes(
        self: "AgentRunner", ctx: Ctx, call_id: str, request: ToolCallRequest
    ) -> tuple[str, str, str]:
        """`_command_later`'s command, and KOLONİ's note at its end - for `woken`."""
        status, output = await self._run_call(ctx, call_id, request)
        opener = self._ctxs.get(ctx.agent_id, ctx)
        note = COMMAND_ENDED.format(id=call_id, status=status)
        return "command", output, self._send(ctx, opener, note, delivered=False, koloni=True)

    def _command_later_of(self: "AgentRunner", ctx: Ctx, given: str):
        """The background command of this Orchestrator's turn that `given` names - by its call's
        id, or its own record's: (its call's id, its record) - or None."""
        with self._factory() as session:
            command = session.scalar(
                select(Command).where(
                    Command.run_id == ctx.run_id,
                    Command.agent_id == ctx.agent_id,
                    or_(Command.tool_call_id == given, Command.id == given),
                )
            )
            later = self._commands_later.get(given)
            if command is None:  # (asked for before it is on record: its check, its card)
                return (given, None) if later is not None and later[0] == ctx.run_id else None
            if command.tool_call_id not in self._commands_later:
                return None
            session.expunge(command)
        return command.tool_call_id, command

    async def _command_later_call(
        self: "AgentRunner", ctx: Ctx, name: str, found: tuple, since: object
    ) -> str:
        """command_output and stop_command on one of its background commands (`_serving_call`)."""
        call_id, command = found
        if command is None and name == "command_output":
            return f"Command {call_id} has not started yet: it is being checked, or its card waits."
        if name == "stop_command":
            task = self._commands_later[call_id][1]
            task.cancel()  # (its process, with what it started, ends as the turn's Stop ends one)
            await asyncio.wait({task}, timeout=STOP_WAIT)
            return f"Command {call_id} is stopped."
        live = self.commands.live_outputs(ctx.cid).get(command.id)
        if live is None:  # (not started yet, or just over: its record's)
            return self.commands.output_of(command, since if isinstance(since, int) else None)
        start = (
            min(since, len(live)) if isinstance(since, int) else max(0, len(live) - OUTPUT_AT_MOST)
        )
        shown = live[start : start + OUTPUT_AT_MOST]
        end = start + len(shown)
        return (
            f"Command {call_id} ({command.command}) runs in the background. Characters "
            f"{start}-{end} of {len(live)} of its output; for what it prints next, call again "
            f"with since={end}:\n{shown}"
        )

    async def _at_work_call(
        self: "AgentRunner", ctx: Ctx, call_id: str, request: ToolCallRequest
    ) -> str:
        """`_tool_call_4`'s part for `AT_WORK_TOOLS`, held to the agent they are offered to (a
        CLI keeps the tools it was given at its start)."""
        name, args = request.name, parse_arguments(request.arguments)
        if not self._at_work_open(ctx):  # (as offered: update_plan, read_pr_feedback hold more)
            raise ToolError(f"{name} is not available: {NOT_OPEN}")
        if name == "agents_at_work":
            return self._agents_at_work(ctx)
        if name in LEAD_TOOLS:
            return await self._lead_tool(ctx, call_id, name, args)
        named = args.get("name")
        if not isinstance(named, str) or not named.strip():
            raise ToolError("missing required argument: name")
        named = " ".join(named.split())
        with self._factory() as session:
            found = session.scalar(
                select(Agent.id).where(
                    Agent.run_id == ctx.run_id, Agent.depth > 0, Agent.name == named
                )
            )
        if found is None:
            raise ToolError(STOP_NONE.format(name=named))
        if why := await self.stop_agent(found, by=ctx):
            raise ToolError(why)
        return STOP_DONE.format(name=named)

    async def stop_agent(self: "AgentRunner", agent_id: str, by: Ctx | None = None) -> str | None:
        """D3: one agent of the turn stopped - by the user from its box (`by` None), or by the
        Orchestrator that opened it with spawn_agent (`by`). Its own work ends at once (its task:
        `_see_through_run`), the helpers it opened with it (`_halt`): its cards close, what it
        changed is kept for the user's Take in as where it stops unfinished by itself (`_take_in`)
        and nothing of it reaches the project; its opener hears it ended, the rest of the turn
        goes on. Not KOLONİ's own look, nor a step of a team's recipe: their Stop is theirs. Why
        not, or None once stopped."""
        with self._factory() as session:
            agent = session.get(Agent, agent_id)
            call = session.get(ToolCall, agent.tool_call_id or "") if agent else None
            cid = session.get_one(Run, agent.run_id).conversation_id if agent else ""
        if agent is None:
            return STOP_NONE.format(name="that")
        mine = (
            call is not None
            and call.name == "spawn_agent"
            and not call.provider_call_id.startswith(PROOF_CALL)
            and agent_id not in self._in_recipe
        )
        if by is not None and not (
            mine and agent.parent_agent_id == by.agent_id and agent.run_id == by.run_id
        ):
            return STOP_NOT_YOURS.format(name=agent.name)
        work = self._own_work.get(agent_id)
        if agent.status in AGENT_TERMINAL or (work is not None and work.done()):
            return STOP_FINISHED.format(name=agent.name)
        if not mine:
            return STOP_NOT_SPAWNED.format(name=agent.name)
        if work is None:
            return STOP_ASKED.format(name=agent.name)
        why = self._stopped_one[agent_id] = (
            LEADS_STOP if by is not None else STOPPED_BY.format(who="the user")
        )
        self._halt(agent.run_id, [agent_id], why)  # (its helpers too; no try-again advice)
        work.cancel()
        if by is None:
            self._koloni_line(cid, agent.run_id, YOU_STOPPED.format(name=agent.name))
            if (opener := self._ctxs.get(agent.parent_agent_id or "")) is not None:
                self._send(opener, opener, USER_STOPPED.format(name=agent.name), False, koloni=True)
        return None

    async def _see_through_run(self: "AgentRunner", ctx: Ctx, child: Ctx) -> tuple[str, str | None]:
        """`_see_through`: the sub-agent's work, in its place among the agents at work - in a task
        of its own, which one Stop ends alone (`stop_agent`): then it ended "cancelled", and its
        opener goes on with that as with an agent that stopped unfinished. The turn's Stop goes
        through it as ever."""
        # (Started at once, as the call it was: work that never waits is over before its
        # opener goes on, as before it had a task of its own.)
        work = self._own_work[child.agent_id] = asyncio.Task(
            self._see_through_place(ctx, child), loop=asyncio.get_running_loop(), eager_start=True
        )
        try:
            return await work
        except asyncio.CancelledError:
            why = self._stopped_one.get(child.agent_id)
            task = asyncio.current_task()
            if why is None or (task is not None and task.cancelling()):
                if why is not None:  # (its own Stop, then the turn's: kept as the turn's keeps it)
                    await self._through_any_stop(child.run_id, self._stopped_in_copy(child))
                raise
            line = {child.agent_id}  # (and what hangs on its helpers' calls: their cards)
            while more := {a for a, one in self._ctxs.items() if one.parent_id in line} - line:
                line |= more
            for one in line:
                self._interrupt_open_calls(child.run_id, child.cid, one)
            return "cancelled", why
        finally:
            self._own_work.pop(child.agent_id, None)

    def _tell_done(self: "AgentRunner", ctx: Ctx, child_id: str) -> None:
        """An agent its opener did not wait for (a background one, a CLI's) is over: KOLONİ's own
        desktop notice - its name, how it ended, how many findings it reported; never a word of
        its own - where the project has notices on and nobody has its chat open
        (`bus.watching`), within `_toasts`. One waited for is said by its opener's next answer.
        Never fails the turn.
        shortcut: a hidden tab still counts as watching (its events stream); tell then too if
        a notice is missed there."""
        with contextlib.suppress(Exception):
            if self.bus.watching(ctx.cid):
                return
            with self._factory() as session:
                project = self._project(session, ctx.cid)
                child = session.get(Agent, child_id)
                if project is None or child is None or not project.notify_desktop:
                    return
                found = len(child.findings or [])
                said = (
                    DONE_FOUND.format(name=child.name, n=found, s="" if found == 1 else "s")
                    if child.status == "completed" and found
                    else DONE_SAID.format(name=child.name, how=DONE_HOW.get(child.status, "failed"))
                )
                title = f"KOLONİ — {project.name}"
            if not self._toasts.take(ctx.cid):
                return
            told = asyncio.ensure_future(web.show(title, said))
            self._telling.add(told)
            told.add_done_callback(self._telling.discard)

    async def _see_through_place(
        self: "AgentRunner", ctx: Ctx, child: Ctx
    ) -> tuple[str, str | None]:
        """`_see_through_run`'s work."""
        async with self._working(child, queued=True):
            self._set_agent(ctx.cid, child.agent_id, status="running", started_at=now())
            if why := await self._candidate_copy(child):
                return "failed", why
            try:
                ended, error = await self._run_child(child)
            except asyncio.CancelledError:
                # B-405: Stop (the turn's, Stop everything's) in its work in a copy - not its own
                # Stop (`stop_agent`): `_take_in` keeps that, as where it stops by itself.
                if child.agent_id not in self._stopped_one:
                    await self._through_any_stop(child.run_id, self._stopped_in_copy(child))
                raise
            if ended == "completed" and child.agent_id in self._candidates:
                # K-evrim: measured as its last act, its place still held - a card
                # for the command waits as for any command of its own.
                self._scored[child.agent_id] = await self._measure(child)
            return ended, error

    def _background_offered(self: "AgentRunner", ctx: Ctx) -> bool:
        """D1: whether this agent may open one in the background - the Orchestrator of an API
        model at its own work (a plan turn and a comparison's side have no spawn_agent). A CLI's
        always goes on (`_cli_call`); one under the Orchestrator waits for its own."""
        return not (
            ctx.depth
            or ctx.answering
            or ctx.discussion
            or getattr(ctx.model, "native", False)
            or getattr(ctx.model, "session", False)
        )

    def _background(self: "AgentRunner", ctx: Ctx, request: ToolCallRequest) -> bool:
        """Whether this call is a spawn_agent asked for in the background by one it is offered
        to (`_background_offered`) - else it waits as ever, whoever asks."""
        if request.name != "spawn_agent" or not self._background_offered(ctx):
            return False
        try:
            return parse_arguments(request.arguments).get("background") is True
        except ToolError:
            return False  # (its call refuses it with the reason)

    async def _call_or_later(
        self: "AgentRunner", ctx: Ctx, call_id: str, request: ToolCallRequest
    ) -> tuple[str, str]:
        """`_run_tools`' call: a background spawn_agent of the API Orchestrator is answered as
        a CLI's is - "started" at once, its report a note later (`_cli_call`)."""
        if self._background(ctx, request):
            return await self._cli_call(ctx, call_id, request)
        return await self._run_call(ctx, call_id, request)

    async def _held_for_work(self: "AgentRunner", ctx: Ctx, listens: bool = True) -> str | None:
        """B-376: the Lead answered with agents of its turn still at work (a team's group just
        opened, one opened by a CLI that did not wait): it waits for them as for its own
        sub-agents, its place free, and what it is told then is returned. None: none was.
        D2, `listens`: a word of the user's into the turn wakes it too - to answer it, told
        who is still at work (not at its step limit: B-382 holds it to the end, no step more).
        shortcut: looked at every HOLD_LOOK seconds, not woken by their ends; an agent left
        at work on record by a bug holds the turn till Stop."""
        said = self._still_at_work(ctx)
        if said is None:
            return None
        async with self._handing_over(ctx):
            while self._still_at_work(ctx) is not None and not (listens and self._word_in(ctx)):
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._word_comes(ctx), HOLD_LOOK)
            if listens and self._word_in(ctx):  # (before its wait ends: it takes no place)
                self._listening.add(ctx.agent_id)  # (its next step answers the word)
        if ctx.agent_id in self._listening and (now := self._still_at_work(ctx)) is not None:
            return STILL_AT_WORK.format(what=now)
        return HELD_FOR_WORK.format(what=said)

    # --- D2: the user's word into the open turn (Send now) ---------------------------------

    def takes_word(self: "AgentRunner", cid: str, topic_id: str | None) -> tuple[str | None, str]:
        """D2: the turn of this chat a word of the user's sent now enters - (its id, "") - or
        (None, why it waits in the queue instead); (None, "") where no turn is open: it starts
        its own. Read from the turn's record only (the runner's own sets of it are filled after
        waits of its start), with nothing awaited: `post_message` puts the word on record and
        `word_came` in the same block, so a turn that closes its door meanwhile has it or not."""
        with self._factory() as session:
            run = session.scalar(
                select(Run)
                .where(Run.conversation_id == cid, Run.status.not_in((*TERMINAL, "queued")))
                .order_by(Run.created_at, literal_column("runs.rowid"))
                .limit(1)
            )
            if run is None:
                return None, ""
            task = self._tasks.get(run.id)
            why = (
                WHY_ENDING
                if task is None or task.done() or run.id in self._door_shut
                else WHY_NOT.format(what="a job while you were away")
                if away.job_turn(session, run)
                else WHY_NOT.format(what="a To-do task's turn")
                if run.task_id
                else WHY_NOT.format(what="a plan turn")
                if run.plan_turn
                else WHY_NOT.format(what="a comparison")
                if run.compare_id
                else WHY_NOT.format(what="not one you started")
                if not run.by_user
                else WHY_TOPIC
                if run.topic_id != topic_id
                else ""
            )
        return (None, why) if why else (run.id, "")

    def word_came(
        self: "AgentRunner", run_id: str, message_id: str, words: str, spoken: dict | None = None
    ) -> None:
        """D2: a word of the user's is on record in the open turn (`takes_word`): its
        Orchestrator reads it at its next step (`_history`: a step that is taken now, or one
        that a wait of its gives way to), and its turn does not end before one has
        (`_door_closes`). Into the turn of a CLI that takes it while it works, at once.
        `spoken`: what it asked of a spoken answer, kept for a turn of its own (`_requeue`)."""
        self._unheard.setdefault(run_id, []).append(message_id)
        if spoken:  # (rare: kept only where it asked for one)
            self._word_spoken[message_id] = spoken
        self._word.setdefault(run_id, asyncio.Event()).set()
        lead = self._lead_of(run_id)
        if lead is not None and lead.agent_id in self._doors:
            asyncio.ensure_future(self._steer_word(lead, message_id, words))

    def _told_lead_word(
        self: "AgentRunner", lead: Ctx, note_id: str, name: str, words: str
    ) -> None:
        """`tell_at_work`'s word to the Orchestrator about an agent that hears nothing, left as
        KOLONİ's note: it wakes the Orchestrator's waits as a word of the user's does and holds
        the turn open till the note is read (`_word_in`) - never a turn of its own (it is no
        message of the user's); one the turn ends before reading is said in the chat
        (`_shut_door`)."""
        self._told_lead.setdefault(lead.run_id, []).append((note_id, name, words))
        self._word.setdefault(lead.run_id, asyncio.Event()).set()

    def _told_lead_unread(self: "AgentRunner", run_id: str) -> list[tuple[str, str, str]]:
        """Those of `_told_lead` whose note the Orchestrator was not handed yet."""
        told = self._told_lead.get(run_id)
        if not told:
            return []
        with self._factory() as session:
            read = set(
                session.scalars(
                    select(Message.id).where(
                        Message.id.in_([one[0] for one in told]), Message.delivered_at.is_not(None)
                    )
                )
            )
        left = self._told_lead[run_id] = [one for one in told if one[0] not in read]
        return left

    async def _steer_word(self: "AgentRunner", lead: Ctx, message_id: str, words: str) -> None:
        """`word_came`'s word into the Orchestrator's CLI turn as it runs, as the user's own
        (`steer`) - measured 27 Nov 2026: Claude Code 2.1.332 (a second user line), Codex 0.172
        (`turn/steer`) and Copilot 1.0.114 (`session.send`, mode "immediate") take it into that
        turn. What came of it, once its CLI shows it (C2: `_word_went`); its door shut, it stays
        unheard."""
        sent = await self._steer_sent(lead, USER_TOLD.format(words=quoted(words)), kept=True)
        if isinstance(sent, Delivery):
            sent.then(lambda outcome: self._word_went(lead, message_id, words, outcome))

    def _word_went(
        self: "AgentRunner", lead: Ctx, message_id: str, words: str, outcome: str
    ) -> None:
        """C2: a word of the user's steered into its Orchestrator's CLI turn - taken: heard;
        unknown: heard all the same, as it may have been read (never sent again), the user told
        so in the chat; not sent: unheard still - a step or run more reads it (`_door_closes`,
        `_requeue`). Either heard one is marked for a session it goes on in (`_steered_marks`)."""
        if outcome == NOT_SENT:
            return
        self._steered_ids.setdefault(lead.cid, set()).add(message_id)
        self._drop_heard(lead.run_id, [message_id])
        if outcome == UNKNOWN:
            name = lead.name or lead.role
            told = WORD_MAYBE_UNREAD.format(name=name, words=quoted(words))
            self._koloni_line(lead.cid, lead.run_id, told)

    def _steered_marks(self: "AgentRunner", ctx: Ctx, messages: list[dict]) -> None:
        """The words of the user's its CLI read steered into a turn of its (`_heard`), marked
        in what its run is sent (`steered`): a session it goes on in has them already, and is not
        sent them again (`since_its_last_word`); a new one is.
        shortcut: known by their text (`_history`'s rows carry no id), and while KOLONİ runs: a
        word steered before a restart is sent again once; a steered row trimmed from the history,
        or of another topic, can mark a later message of the same words, and one whose text
        `_history` changed (files said under it) is sent again. Key them by the message's id in
        `_history` if that is seen."""
        if ctx.depth or not (ids := self._steered_ids.get(ctx.cid)):
            return
        with self._factory() as session:
            said = Counter(session.scalars(select(Message.content).where(Message.id.in_(ids))))
        for one in messages:  # (oldest first: a later message of the same words is a new one)
            if one.get("role") == "user" and said[one.get("content")] > 0:
                said[one.get("content")] -= 1
                one["steered"] = True

    def _word_in(self: "AgentRunner", ctx: Ctx) -> bool:
        """Whether a word of the user's waits in this Orchestrator's turn, unread: one sent
        into it, or one about an agent that hears nothing (`_told_lead_word`)."""
        return not (ctx.depth or ctx.answering or ctx.discussion) and bool(
            self._unheard.get(ctx.run_id) or self._told_lead_unread(ctx.run_id)
        )

    def _word_comes(self: "AgentRunner", ctx: Ctx) -> "asyncio.Future[bool]":
        """What is done when a word of the user's comes into this turn from now on (looked at
        and armed in one block: none slips in between)."""
        came = self._word.setdefault(ctx.run_id, asyncio.Event())
        came.clear()
        return asyncio.ensure_future(came.wait())

    def _hearing(self: "AgentRunner", ctx: Ctx) -> None:
        """D2: the Orchestrator's model is asked now (`_slow`, arm): what it is sent was read
        in the same block (`_history`), with the user's words of its turn so far - heard once
        the step comes back (`_heard`). Never its answer's or its speech's, beside its work."""
        if not (ctx.depth or ctx.answering or ctx.discussion):
            self._seen_by[ctx.agent_id] = list(self._unheard.get(ctx.run_id, ()))

    def _heard(self: "AgentRunner", ctx: Ctx) -> None:
        """The Orchestrator's step came back: the words it was sent are heard (`_hearing`) -
        those steered into its CLI's turn, as its CLI showed them taken (`_word_went`)."""
        if not (ctx.depth or ctx.answering or ctx.discussion):
            self._drop_heard(ctx.run_id, self._seen_by.pop(ctx.agent_id, []))

    def _drop_heard(self: "AgentRunner", run_id: str, ids: list[str]) -> None:
        left = [one for one in self._unheard.get(run_id, ()) if one not in ids]
        if left:
            self._unheard[run_id] = left
        else:
            self._unheard.pop(run_id, None)

    def _door_closes(self: "AgentRunner", ctx: Ctx, status: str) -> bool:
        """D2, as the Orchestrator's loop would end (`_loop`): a word of the user's came that
        no step of its read - False, one step more, in which it answers it (`_listening`); else
        the door is shut: a word from now on starts its own turn. With nothing awaited from
        here to the turn's end on record that a word could come in by. Not its answer's loop."""
        if ctx.depth or ctx.answering or ctx.discussion:
            return True
        if status == "completed" and self._word_in(ctx):
            self._listening.add(ctx.agent_id)
            return False
        self._door_shut.add(ctx.run_id)
        return True

    async def _listen_steps(self: "AgentRunner", ctx: Ctx, info) -> tuple[str, str | None]:
        """`_loop`: its steps for a word that came as its loop ended. Where it only answered
        (no call), what was checked at its end stands; any call goes on as its loop does."""
        calls = self._calls_of(ctx)
        status, error = await self._steps_held(ctx, info)
        self._listening.discard(ctx.agent_id)
        if status != "completed" or self._calls_of(ctx) == calls:
            return status, error
        return await self._loop_steps(ctx, info, (status, error))

    def _listen_refuses(self: "AgentRunner", ctx: Ctx, name: str) -> str | None:
        """D2: a step that answers the user's word during the turn writes nothing - new work
        goes to an agent. shortcut: a CLI's own tools are only told so (its word); hold them in
        its hook too if a CLI Orchestrator is seen writing as it answers."""
        if ctx.agent_id in self._listening and (
            name in HANDED  # (write_file, edit_file, diagram_image)
            or name in ("run_command", "run_skill_script", "http_request")
            or "__" in name  # (an MCP server's tool: what it does is the server's)
        ):
            return LISTEN
        return None  # (remember and the To-do's tools go on: they ask or wait for the user's OK)

    def _shut_door(self: "AgentRunner", run_id: str, cid: str | None) -> None:
        """`execute`'s end, however the turn ended (the turn is on record as over by now): the
        words no step read - a Stop, a failure, a turn that never came to its loop - each go on
        in a turn of their own (`_requeue`); a word about an agent its note was not read of is
        said in the chat. Never raises: the rest of the turn's end goes on."""
        try:
            unheard = self._unheard.pop(run_id, [])
            unread = self._told_lead_unread(run_id)
            self._told_lead.pop(run_id, None)
            self._word.pop(run_id, None)
            # (Shut for good: a second Stop may leave the turn before it is on record as over.)
            # shortcut: a turn's id stays in the set for KOLONİ's life - drop it once the turn is
            # over on record if that is ever felt.
            self._door_shut.add(run_id)
            mine = {one for one, known in self._ctxs.items() if known.run_id == run_id}
            self._listening -= mine
            for agent_id in mine:
                for kept in (self._stopped_one, self._seen_by):
                    kept.pop(agent_id, None)
            if cid:
                for _note, name, words in unread:
                    self._koloni_line(
                        cid, run_id, TOLD_UNREAD.format(name=name, words=quoted(words))
                    )
                if unheard:
                    self._requeue(run_id, cid, unheard)
        except Exception:
            log.warning("run %s: its door did not close cleanly", run_id, exc_info=True)
        with contextlib.suppress(Exception):  # (after the words: they always go on)
            self._lead_tools_forget(run_id)  # (its plan shown, what its tools counted)

    def _requeue(self: "AgentRunner", run_id: str, cid: str, ids: list[str]) -> None:
        """Words of a turn none of its steps read, each into a turn of its own (`requeued`), in
        the order they were sent, started where nothing else of the chat is at work - only the
        user's own messages."""
        from app.api.conversations import requeued  # (it imports this package)

        with self._factory() as session:
            words = list(
                session.scalars(
                    select(Message)
                    .where(Message.id.in_(ids), Message.role == "user")
                    .order_by(Message.created_at, literal_column("messages.rowid"))
                )
            )
            spoken = [self._word_spoken.pop(word.id, None) for word in words]
            runs = requeued(session, session.get_one(Run, run_id), words, spoken)
            session.commit()
            sent = [
                (run_out(run), message_out(word)) for run, word in zip(runs, words, strict=True)
            ]
        for run_said, message_said in sent:
            self.bus.emit(cid, run_said["id"], "run.started", run_said)
            self.bus.emit(cid, run_said["id"], "message.created", message_said)
        self.start_next(cid)

    def _still_at_work(self: "AgentRunner", ctx: Ctx) -> str | None:
        """The turn's agents at work but its Lead, by team and where its recipe is - "Web app
        at All at once: Tester running" - and the rest by name. None: none is. One blocked on a
        file counts only where its holder lets go before the turn's end: one of another turn, or
        one still at work - not the Lead, nor one done, which hold theirs till then."""
        with self._factory() as session:
            busy = {
                one.id: one
                for one in session.scalars(
                    select(Agent)
                    .where(
                        Agent.run_id == ctx.run_id,
                        Agent.depth > 0,
                        Agent.status.in_((*AT_WORK, "blocked")),
                    )
                    .order_by(Agent.created_at)
                )
            }

            def lets_go(holder: str) -> bool:
                known = self._ctxs.get(holder)
                return (
                    known is None
                    or known.run_id != ctx.run_id
                    or (holder in busy and busy[holder].status != "blocked")
                )

            # (Nor one whose waits lead back to the Lead - a file it holds: that ends with it.)
            busy = {
                key: one
                for key, one in busy.items()
                if one.status != "blocked"
                or (
                    self.claims.cycle(ctx.agent_id, key) is None
                    and any(lets_go(wait.holder) for wait in self.claims.waiting(key))
                )
            }
            # B-415: and one a CLI opener did not wait for, ended on record but its call not
            # over yet - its step's row is moved on (`_after_step`) only then.
            closing = [
                self._ctxs[one[1]].name
                for one in self._later_work.get(ctx.run_id, ())
                if not one[3].done() and one[1] not in busy and one[1] in self._ctxs
            ]
            if not busy and not closing:
                return None
            said = [f"{name} finishing" for name in closing]
            for row, team, _lead in self._rows(session, ctx.cid):
                state = self._live_state(row, ctx.run_id) or self._apart_state(row, ctx.run_id)
                theirs = [busy.pop(one) for one in (state or {}).get("agents", []) if one in busy]
                if theirs:
                    at = ""
                    with contextlib.suppress(Exception):  # (a label: never the turn's failure)
                        if state and state.get("graph"):
                            graph = recipe_run.graph_of(state)
                            at = f" at {recipe_run.name_of(graph, state['at'])}"
                    said.append(
                        f"{team.name}{at}: "
                        + ", ".join(f"{one.name} {one.status}" for one in theirs)
                    )
            said += [f"{one.name} {one.status}" for one in busy.values()]
        return "; ".join(said)

    def _unread_messages(self: "AgentRunner", ctx: Ctx) -> list[str]:
        """K-fikir-okunmamis: the user's messages queued behind this turn (their own turns
        start after it) that this agent was not handed yet - handed here, once, in place of
        a new question card.
        shortcut: their turns still run after this one; fold them into it if they are seen
        to answer the same thing twice."""
        with self._factory() as session:
            rows = session.execute(
                select(Message.id, Message.content)
                .join(Run, Run.id == Message.run_id)
                .where(
                    Run.conversation_id == ctx.cid, Run.status == "queued", Message.role == "user"
                )
                .order_by(Message.created_at, literal_column("messages.rowid"))
            ).all()
        told = self._read_first.setdefault(ctx.agent_id, set())
        unread = [(id_, content) for id_, content in rows if id_ not in told]
        told.update(id_ for id_, _ in unread)
        return [content for _, content in unread]

    async def _opened_with(
        self: "AgentRunner", ctx: Ctx, call_id: str, request: ToolCallRequest
    ) -> tuple[str, str]:
        try:
            return await self._call_or_later(ctx, call_id, request)
        finally:
            self._arrive(call_id)  # (refused before it opened: the others go on)

    def _arrive(self: "AgentRunner", call_id: str) -> asyncio.Event | None:
        """A spawn call of a reply's several is opened (or refused): the event its siblings'
        agents start on once all are (`_run_tools`); None where it is asked for alone, or
        has arrived.
        shortcut: a CLI's spawn_agent calls come over MCP one at a time, not held so; hold them
        if a CLI Lead is seen ending a recipe step before its other agents opened."""
        held = self._at_once.pop(call_id, None)
        if held is None:
            return None
        held[0].discard(call_id)
        if not held[0]:
            held[1].set()
        return held[1]

    async def _start_with_others(self: "AgentRunner", call_id: str) -> None:
        """An agent just opened starts once its reply's others are opened too (`_arrive`).
        The last one yields once, so that those already waiting go before it: one place free,
        the first that waited takes it - not always the first asked for."""
        if (together := self._arrive(call_id)) is not None:
            await (asyncio.sleep(0) if together.is_set() else together.wait())

    @staticmethod
    async def _together(work: list) -> None:
        """Run several things at once; if one breaks, the rest are stopped with it."""
        tasks = [asyncio.ensure_future(one) for one in work]
        try:
            await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    def _cancel_later(self: "AgentRunner", run_id: str, agent_id: str | None = None) -> list[tuple]:
        """Stop the sub-agents CLI openers did not wait for - of one opener, or of the whole
        turn: nothing of them outlives what opened them. Returns them, for `_stopped_later`."""
        kept, ending = [], []
        for one in self._later_work.pop(run_id, []):
            (ending if agent_id in (None, one[0]) else kept).append(one)
        if kept:
            self._later_work[run_id] = kept
        for one in ending:
            one[3].cancel()
        return ending

    async def _stopped_later(self: "AgentRunner", ending: list[tuple]) -> None:
        """Wait for those `_cancel_later` stopped; one still open on record is `cancelled`
        the way any agent's work ends (`_set_agent`: what it held is let go)."""
        await asyncio.shield(asyncio.gather(*(one[3] for one in ending), return_exceptions=True))
        with self._factory() as session:
            rows = {
                agent_id: (run_id, status)
                for agent_id, run_id, status in session.execute(
                    select(Agent.id, Agent.run_id, Agent.status).where(
                        Agent.id.in_([one[1] for one in ending])
                    )
                )
            }
        for _opener, child_id, cid, _work in ending:
            if child_id not in rows:
                continue
            run_id, status = rows[child_id]
            # B-313: nor does a card of its own wait at Ready for you after it (a command) - of
            # one stopped; one that finished is left as it ended.
            if status != "completed":
                with contextlib.suppress(Exception):
                    self._interrupt_open_calls(run_id, cid, child_id)
            if status not in AGENT_TERMINAL:
                with contextlib.suppress(Exception):
                    self._set_agent(cid, child_id, status="cancelled", ended_at=now())

    async def _cli_call(
        self: "AgentRunner", ctx: Ctx, call_id: str, request: ToolCallRequest
    ) -> tuple[str, str]:
        """`_run_from_cli`'s call. K-paralel-spawn (measured 27 Oct): Claude Code runs the
        MCP calls of one message one after another, so its two spawn_agent calls ran one after
        the other. A spawn_agent is answered as soon as `_see_through` says so - "proposed"
        while its card waits for the user, "started" once it may start - and the CLI goes on;
        what came of it comes later as a note, as a request not waited for does
        (`team_requests`): with the CLI's next tool result (`_deliver`), or - its turn over -
        in one step more, which `team_requests.woken` holds the turn open for until every one
        is back. The call's own record still ends with the report. One refused before it is
        proposed, or one its opener waits for (`_see_through`), is answered as it ends."""
        if request.name != "spawn_agent" or ctx.answering or ctx.discussion:
            return await self._run_call(ctx, call_id, request)
        told = self._opening[call_id] = asyncio.get_running_loop().create_future()
        work = asyncio.ensure_future(
            self._said_at_once(ctx, call_id, request, told)
            if self._background_offered(ctx)
            else self._run_call(ctx, call_id, request)
        )
        try:
            await asyncio.wait((work, told), return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:
            work.cancel()
            raise
        finally:
            self._opening.pop(call_id, None)
        if work.done() or not told.done():
            return await work
        with self._factory() as session:
            child_id, name = session.execute(
                select(Agent.id, Agent.name).where(Agent.tool_call_id == call_id)
            ).one()
        later = asyncio.ensure_future(self._comes_later(ctx, child_id, name, work))

        def settled(done: asyncio.Future) -> None:
            if done.cancelled():  # stopped before its first step, it never awaited the work
                work.cancel()
            elif done.exception() is not None:  # (retrieved: whoever dropped it, it is said)
                log.warning(
                    "agent %s: the report of %s was not left for it: %r",
                    ctx.agent_id,
                    name,
                    done.exception(),
                )

        later.add_done_callback(settled)
        self._answers_out.setdefault(ctx.agent_id, []).append(later)
        self._later_work.setdefault(ctx.run_id, []).append((ctx.agent_id, child_id, ctx.cid, work))
        self._lend_slot(ctx)
        if self._background_offered(ctx):  # (D1: its next step reads its history from the record)
            self._went_on_calls.add(call_id)
            self._set_call(ctx.cid, call_id, status="succeeded", result=told.result())
        return "succeeded", told.result()

    async def _said_at_once(
        self: "AgentRunner",
        ctx: Ctx,
        call_id: str,
        request: ToolCallRequest,
        told: asyncio.Future,
    ) -> tuple[str, str]:
        """D1: the API Orchestrator's background spawn, whose record stays what it was told at
        once ("started", "proposed"): its steps read their history from the record, and the
        report comes as a note (`_comes_later`) - not twice. (A CLI's call record ends with the
        report: its CLI reads the call's own answer, not the record.)"""
        try:
            return await self._run_call(ctx, call_id, request)
        finally:
            # (Not one that was over before its opener went on: it was answered with its report.)
            if call_id in self._went_on_calls:
                self._went_on_calls.discard(call_id)
                self._set_call(ctx.cid, call_id, status="succeeded", result=told.result())

    async def _comes_later(
        self: "AgentRunner",
        ctx: Ctx,
        child_id: str,
        name: str,
        work: "asyncio.Future[tuple[str, str]]",
    ) -> tuple[str, str, str]:
        """What came of a sub-agent its CLI opener did not wait for, left for it as a note:
        (who, what it is told, the note's id), as `team_requests.woken` reads it.

        Whose word it is goes by where the text came from, never by what it says: KOLONİ's
        own only where the sub-agent never ran and the text is KOLONİ's fixed wording with
        nothing attached (the user's no, an internal error). Anything else - a report, and a
        no with other leads' reports after it (`_spawn`) - is the sub-agent's note, handed as
        data (`_from`), under a short KOLONİ word where the sub-agent did not finish."""
        try:
            status, said = await work
        except Exception as exc:  # (a bug of the call's: its opener hears of it, not nothing)
            log.warning("agent %s: spawn_agent %s failed: %r", ctx.agent_id, child_id, exc)
            status, said = "failed", INTERNAL
        await self._take_slot_back(ctx)
        self._tell_done(ctx, child_id)  # (Task 7: where nobody watches the chat)
        if self._stopped_one.get(child_id) == LEADS_STOP:
            raise asyncio.CancelledError  # (its own stop_agent's answer said it: nothing to read)
        opener = self._ctxs.get(ctx.agent_id, ctx)
        with self._factory() as session:
            child = session.get(Agent, child_id)
            ran = child is None or child.started_at is not None
            fixed = (
                said == INTERNAL
                or child is not None
                and said == SPAWN_REJECTED.format(role=child.role_name)
            )
        if status != "succeeded" and not ran and fixed:
            said = SPAWN_ENDED.format(name=name, status=status, said=said)
            return name, said, self._send(ctx, opener, said, delivered=False, koloni=True)
        if status != "succeeded":
            self._send(
                ctx,
                opener,
                SPAWN_ENDED_SEE.format(name=name, status=status),
                delivered=False,
                koloni=True,
            )
        return (
            name,
            said,
            self._send(replace(ctx, agent_id=child_id), opener, said, delivered=False),
        )

    def _nudge(self: "AgentRunner", ctx: Ctx, words: str) -> None:
        """`words` follow the agent's last message in what it sees from its next step on."""
        with self._factory() as session:
            last = session.scalar(
                select(Message.id)
                .where(
                    Message.run_id == ctx.run_id,
                    Message.agent_id == ctx.agent_id,
                    Message.role == "assistant",
                )
                .order_by(Message.created_at.desc(), literal_column("messages.rowid").desc())
                .limit(1)
            )
        self._nudges.setdefault(ctx.agent_id, []).append((last, words))

    async def steer(self: "AgentRunner", ctx: Ctx, words: str, kept: bool = False) -> str | None:
        """89d: `words` to an agent while it works - into its CLI's own turn at once
        (`STEERED`: Claude Code's, Codex's, Copilot's), with a CLI session's next KOLONİ tool
        result, or at its next step of KOLONİ's own; and from its next step or run on (`_nudge`,
        B-83) - not where they are `kept` in its conversation already (`_send`), which its later
        steps read. None once sent; why it cannot hear them where it cannot (agy's, a session's
        that hears nothing: B-164). One at a time to an agent (`_changing`).
        Only KOLONİ's own words around what the user decided, anything an agent wrote (a
        question, its options) `quoted()` inside them - never an agent's words as they are: a
        CLI's user line carries the user's authority."""
        sent = await self._steer_sent(ctx, words, kept)
        return sent if isinstance(sent, str) else None

    async def _steer_sent(
        self: "AgentRunner", ctx: Ctx, words: str, kept: bool = False
    ) -> "str | Delivery | None":
        """`steer`, with what was written into its CLI's turn where it was: what comes of it,
        once its CLI shows it (C2: `Delivery`) - one it refused is why it cannot hear them."""
        name = ctx.name or ctx.role
        if ctx.agent_id in self._changing:  # (one at a time while it is written: each is settled)
            return f"can't be sent now: another message to {name} is on its way"
        self._changing.add(ctx.agent_id)
        sent: Delivery | None = None
        try:
            door = self._doors.get(ctx.agent_id)
            if door is not None:
                sent = await door(f"{STEERED}\n\n{words}")
                if sent.outcome == NOT_SENT:
                    return NOT_HEARD.format(name=name)
            elif getattr(ctx.model, "native", False):
                return NOT_HEARD.format(name=name)
            elif getattr(ctx.model, "session", False):
                # shortcut: a session that calls no KOLONİ tool again hears it only on a re-run;
                # steer its CLI live too once a session's input is measured mid-turn.
                self._heard_later.setdefault(ctx.agent_id, []).append(words)
        finally:
            self._changing.discard(ctx.agent_id)
        if not kept:
            self._nudge(ctx, words)
        return sent

    def _lead_of(self: "AgentRunner", run_id: str) -> Ctx | None:
        """The turn's Lead, while it is at work."""
        return next(
            (one for one in self._ctxs.values() if one.run_id == run_id and not one.depth), None
        )

    def stop_cli(self: "AgentRunner", agent_id: str) -> bool:
        """B-357: Stop on a command a CLI runs with its own tool - whose process KOLONİ does not
        hold - ends that CLI's turn; the command is closed with the rest of it (also one still
        waiting for its place after the yes). False: the agent's CLI is not at work."""
        for watch in [w for watches in self._watches.values() for w in watches]:
            if watch.end and watch.ctx and watch.ctx.agent_id == agent_id:
                watch.end(OwnStop("you stopped its command"))
                return True
        return False

    async def _ready_at_end(self: "AgentRunner", ctx: Ctx) -> str:
        """B-415 (live): Ready for you is asked as the Lead hears back from an agent - with
        another still in the copy then (a lead's agent outliving it, one answering a message)
        it was asked never: it is, before the Lead's answer ends the turn. In the call of the
        last lead it opened, else of the last agent it opened - a card is always in a call;
        with none, no recipe ran."""
        mine = [one for one in self._ctxs.values() if one.run_id == ctx.run_id and one.depth == 1]
        with self._factory() as session:
            called = set(
                session.scalars(
                    select(Agent.id).where(
                        Agent.id.in_([one.agent_id for one in mine]),
                        Agent.tool_call_id.is_not(None),
                    )
                )
            )
        opened = [one for one in reversed(mine) if one.agent_id in called]
        under = next(
            (one for one in opened if one.agent_id in self._leads), opened[0] if opened else None
        )
        return "" if under is None else await self._ready_for_you(ctx, under)

    def _halt(
        self: "AgentRunner", run_id: str, agents: list[str], why: str, word: str = "Stop"
    ) -> None:
        """Agents of a turn - and the helpers they opened, at any depth - stop at their next
        step (`_hold_to_role`), saying `why`: a wait for a limit's reset ends (`_go_on_again`),
        and a card they wait on is answered `word`."""
        line = set(agents)
        while more := {
            a for a, known in self._ctxs.items() if known.parent_id in line and a not in line
        }:
            line |= more
        if not line:
            return
        self._halted.update(line)
        self._halt_why.update(dict.fromkeys(line, why))
        for agent_id in line:
            if woken := self._at_reset.get(agent_id):
                woken.set()
        self._close_cards(run_id, list(line), word)

    def _close_cards(self: "AgentRunner", run_id: str, agents: list[str], word: str) -> None:
        """The recipe cards these agents' calls wait on, answered `word` by KOLONİ - not the
        user's answer (`_who_answered`)."""
        if not agents:
            return
        with self._factory() as session:
            asked = session.scalars(
                select(Question.id)
                .join(Agent, Agent.tool_call_id == Question.tool_call_id)
                .where(
                    Question.status == "pending",
                    Question.leave,
                    Agent.id.in_(agents),
                    Agent.run_id == run_id,
                )
            ).all()
        for question_id in asked:
            if self.answer_question(question_id, word):  # (not one the user answered first)
                self._closed_cards.add((run_id, question_id))

    def stop_team(self: "AgentRunner", cid: str, team_id: str, finish: bool = False) -> str | None:
        """The user's Stop on a team of the chat: its row stops, and so does each of its
        agents at its next step (`_hold_to_role`); the other teams go on. Not once its work
        waits at Ready for you. A card its step waits on is answered "Stop" for the user: the
        spawn call it is put in goes on; and a wait for a limit's reset ends (`_go_on_again`).
        Returns why it is not stopped; None: it is. `finish`: the user's Finish now on a
        recipe's row - its loop goes round no more: the row is at Ready for you with what was
        found so far, its agents stopped as for Stop.
        shortcut: an agent stops at its next model step - a long command, a card it waits on,
        or a CLI between its messages runs on till then; and what the team changed stays in
        the turn's one copy, taken in with the other teams' at Take in. Cancel its calls and
        give each team a copy if felt. Finish now with no agent at work asks Ready for you
        only as the Lead hears back - else the turn ends with its work kept for Take in."""
        run_id = next((c.run_id for c in self._ctxs.values() if c.cid == cid), None)
        why: list[str | None] = ["this team is at work in no turn now"]

        def how(row: ConversationTeam, team: Team, lead: Role | None, state: dict) -> bool:
            if row.team_id != team_id:
                return False
            if state["status"] == recipe_run.READY:
                why[0] = "its work waits for your Take in or Ask for changes"
                return False
            if state["status"] != recipe_run.RUNNING:
                return False
            at = recipe_run.name_of(recipe_run.graph_of(state), state["at"]) if finish else ""
            state["status"], state["why"] = (
                (
                    recipe_run.READY,
                    (f"finished by you at its {at} step: what was found so far is left to you"),
                )
                if finish
                else (recipe_run.STOPPED, "Stopped by you")
            )
            stopping.extend(state["agents"])
            why[0] = None
            return True

        def apart(row: ConversationTeam, team: Team, lead: Role, state: dict | None) -> dict | None:
            return state if state and how(row, team, lead, state) else None

        stopping: list[str] = []
        if run_id is not None:
            self._change_rows(cid, run_id, how)
            if not finish:  # (B-101: a team with no recipe beside one)
                self._apart(cid, run_id, apart)
            self._halt(run_id, stopping, TEAM_STOPPED)
        return why[0]

    # --- D4: agents_at_work ------------------------------------------------------------------

    def _agents_at_work(self: "AgentRunner", ctx: Ctx) -> str:
        """agents_at_work: the agents of this turn at work now, below its Orchestrator - each
        one's name and role, how it stands and since when (this machine's clock), whether its
        opener went on without it, and its last words: masked, cut, quoted, after KOLONİ's note
        where they read like orders. Read from this turn's record only."""
        with self._factory() as session:
            rows = session.scalars(
                select(Agent)
                .where(
                    Agent.run_id == ctx.run_id,
                    Agent.depth > 0,
                    Agent.status.in_((*AT_WORK, "blocked")),
                )
                .order_by(Agent.created_at, literal_column("agents.rowid"))
            ).all()
            last = {
                one.id: session.scalar(
                    select(Message.content)
                    .where(
                        Message.agent_id == one.id,
                        Message.role == "assistant",
                        Message.content != "",  # (not the step it streams now)
                    )
                    .order_by(Message.created_at.desc(), literal_column("messages.rowid").desc())
                    .limit(1)
                )
                for one in rows
            }
        if not rows:
            return AT_WORK_NONE
        later = {one[1] for one in self._later_work.get(ctx.run_id, ())}
        at = now()
        lines = [AT_WORK_HEAD.format(n=len(rows))]
        for one in rows:
            since = one.started_at or one.created_at
            lines.append(
                AT_WORK_LINE.format(
                    name=one.name,
                    role=one.role_name,
                    status=AT_WORK_SAID.get(one.status, one.status),
                    at=since.replace(tzinfo=UTC).astimezone().strftime("%H:%M"),
                    minutes=max(0, int((at - since).total_seconds() // 60)),
                    later=", in the background" if one.id in later else "",
                    said=_last_said(last.get(one.id)),
                )
            )
        return "\n".join(lines)


def _last_said(words: str | None) -> str:
    """An agent's last words as agents_at_work gives them: masked, cut, quoted - after KOLONİ's
    note where they read like orders; "nothing yet" for none."""
    if not words or not words.strip():
        return "nothing yet"
    shown = OutputMask(()).hide(" ".join(words.split()))
    shown = shown if len(shown) <= SAID_MOST else shown[: SAID_MOST - 1] + "…"
    return f"{injection.NOTE} {quoted(shown)}" if injection.scan(words, "agent") else quoted(shown)
