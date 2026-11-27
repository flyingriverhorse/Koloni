"""What goes on while the turn's agents are at work: the Orchestrator held for them
(`_held_for_work`), a reply's several sub-agents opened together (`_together`), the sub-agents a
CLI opener did not wait for stopped (`_cancel_later`), and the user's messages queued behind the
turn (`_unread_messages`) - `AtWorkMixin`.
"""

import asyncio
import contextlib
import logging
from dataclasses import replace
from typing import TYPE_CHECKING

from sqlalchemy import literal_column, select

from app import recipe_run
from app.agent.ctx import Ctx
from app.agent.spawn_mixin import INTERNAL, SPAWN_ENDED, SPAWN_ENDED_SEE, SPAWN_REJECTED
from app.agent.words import AGENT_TERMINAL
from app.db.models import Agent, Message, Run, now
from app.model_client import ToolCallRequest
from app.tools import ToolError, parse_arguments
from app.tools_at_work import SPAWN_BACKGROUND_PROPERTY

if TYPE_CHECKING:
    from app.agent import AgentRunner

log = logging.getLogger(__name__)

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
    def _at_work_offered(self: "AgentRunner", ctx: Ctx, schemas: list[dict]) -> None:
        """`_offered`'s schemas, with what goes on beside the turn's agents where it is this
        agent's: spawn_agent's `background` (D1)."""
        if self._background_offered(ctx):
            for spawn in (s["function"] for s in schemas if s["function"]["name"] == "spawn_agent"):
                spawn["parameters"]["properties"]["background"] = SPAWN_BACKGROUND_PROPERTY

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

    async def _held_for_work(self: "AgentRunner", ctx: Ctx) -> str | None:
        """B-376: the Lead answered with agents of its turn still at work (a team's group just
        opened, one opened by a CLI that did not wait): it waits for them as for its own
        sub-agents, its place free, and what it is told then is returned. None: none was.
        shortcut: looked at every HOLD_LOOK seconds, not woken by their ends; an agent left
        at work on record by a bug holds the turn till Stop."""
        said = self._still_at_work(ctx)
        if said is None:
            return None
        async with self._handing_over(ctx):
            while self._still_at_work(ctx) is not None:
                await asyncio.sleep(HOLD_LOOK)
        return HELD_FOR_WORK.format(what=said)

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
            if told.done() and not told.cancelled():
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
