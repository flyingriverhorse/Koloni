"""Who is at work: the places agents take to run (a model step or a tool), lent and taken back,
queued on the project's limits, let in when one is free, and the waits that give a place up
(`_step_aside`, `_settle`) - `SlotsMixin`.
"""

import asyncio
import contextlib
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.agent.ctx import Ctx
from app.db.models import Agent, Conversation, Project, Provider
from app.providers import most_at_once

if TYPE_CHECKING:
    from app.agent import AgentRunner

# How soon the line of agents waiting for room is looked at again when the limits could
# not be read.
LOOK_AGAIN = 1.0


class SlotsMixin:
    # --- who is at work ------------------------------------------------------

    async def _take(self: "AgentRunner", ctx: Ctx, queued: bool = False,
                    shown: bool = True) -> None:
        """Take one of the turn's places for agents at work, waiting for a free one -
        and then for room in its project and on its provider, where the user has said
        how many agents may be at work there at once: until there is, it is `queued`,
        the lead too, and its model is asked nothing. `shown`: False for a place taken
        after the agent's work is over (`_note_what_it_found`): the agent's record says
        how its work ended, and standing in line here does not change that."""
        if ctx.agent_id in self._placed:
            return  # it has its place: a second one would never be given back
        slots = self._slots[ctx.run_id]
        if queued and slots.locked():
            self._set_agent(ctx.cid, ctx.agent_id, status="queued")
        await slots.acquire()
        came: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._line_up.append((ctx, came))
        try:
            self.let_in()
            self._clock(ctx.run_id)
            if not came.done():
                if shown:
                    self._set_agent(ctx.cid, ctx.agent_id, status="queued",
                                    queued_on=self._queued_on(ctx))
                await came
                if shown:
                    self._set_agent(ctx.cid, ctx.agent_id, status="running", queued_on=None)
        except BaseException:
            # Stopped while it waited, or just as it was let in: the place is another's.
            self._line_up = [one for one in self._line_up if one[1] is not came]
            if shown:
                with contextlib.suppress(Exception):  # (nothing here hides the Stop)
                    self._set_agent(ctx.cid, ctx.agent_id, queued_on=None)
            # Only what this call holds: let in and stepped aside again by another call
            # of the agent before this one woke, its place was given back there.
            # (A Stop cancels `came` too: done, and never let in.)
            if not came.done() or came.cancelled() or ctx.agent_id in self._placed:
                self._placed.discard(ctx.agent_id)
                self._free_slot(ctx)
            self._clock(ctx.run_id)
            self.let_in()
            raise

    def _give(self: "AgentRunner", ctx: Ctx) -> None:
        if ctx.agent_id in self._placed:
            self._placed.discard(ctx.agent_id)
            self._free_slot(ctx)
            self._clock(ctx.run_id)
            self.let_in()

    def _free_slot(self: "AgentRunner", ctx: Ctx) -> None:
        """The turn's place of an agent that gives up its place - none where it lent it already
        (`_lend_slot`)."""
        if ctx.agent_id in self._slot_lent:
            self._slot_lent.discard(ctx.agent_id)
        else:
            self._slots[ctx.run_id].release()

    def _lend_slot(self: "AgentRunner", ctx: Ctx) -> None:
        """A CLI opener whose sub-agents work while its CLI goes on (`_run_from_cli`): it stays
        at work on its provider and in its project (`_placed`: the processes that run), but its
        place among the turn's agents at once (the chat's setting, `_slots`) is theirs - as
        `_handing_over` gave it, without being `waiting`. Taken back when the last of them
        is back, where the turn has a place free (`_take_slot_back`); else at its next `_give`.
        shortcut: where none was free then, each such opener - nested, or beside another - may
        keep the turn one over the chat's setting until it next gives up its place (its turn
        over, a wait); its provider's and its project's limits hold all the same. Wait for a
        place there if that is seen."""
        if ctx.agent_id in self._placed and ctx.agent_id not in self._slot_lent:
            self._slot_lent.add(ctx.agent_id)
            self._slots[ctx.run_id].release()

    async def _take_slot_back(self: "AgentRunner", ctx: Ctx) -> None:
        """The last of the sub-agents a CLI opener lent its turn's place to is back: it takes
        that place again - only one free now, never waiting for one (no await before taking:
        `acquire` on a free semaphore does not wait)."""
        slots = self._slots.get(ctx.run_id)
        if (ctx.agent_id in self._slot_lent and slots is not None and not slots.locked()
                and not any(one[0] == ctx.agent_id and not one[3].done()
                            for one in self._later_work.get(ctx.run_id, ()))):
            self._slot_lent.discard(ctx.agent_id)
            await slots.acquire()

    def _limits(self: "AgentRunner",
                ctxs: list[Ctx]) -> tuple[dict[str, int | None], dict[str, int]]:
        """How many agents the user lets work at once - in the project of each of these
        agents' conversations (by conversation), and on each of their providers. None:
        as many as come. A provider's is never None: unset, its kind's (`most_at_once`).
        Read once for all of them."""
        providers = {ctx.provider_id for ctx in ctxs if ctx.provider_id}
        with self._factory() as session:
            most = session.execute(
                select(Conversation.id, Project.max_agents)
                .join(Project, Conversation.project_id == Project.id)
                .where(Conversation.id.in_({ctx.cid for ctx in ctxs}))
            ).all()
            each = {provider.id: most_at_once(provider) for provider in
                    session.scalars(select(Provider).where(Provider.id.in_(providers)))
                    } if providers else {}
        return {cid: limit for cid, limit in most}, each

    def _queued_on(self: "AgentRunner", ctx: Ctx) -> dict | None:
        """What an agent let in by nobody waits for, where that is its provider: as many of
        its agents at work in the whole app as it lets work at once (its node: "queued ·
        Codex full (2/2)"). None: its project is full, or the room is kept for one before it.
        shortcut: said once as it gets in line, not again while it waits - a limit changed
        meanwhile, or its project becoming what holds it, leaves the line as it was; say it
        again in `let_in` if that is seen."""
        try:
            most = self._limits([ctx])[1].get(ctx.provider_id or "")
        except Exception:
            return None
        at_work = sum(self._ctxs[agent].provider_id == ctx.provider_id
                      for agent in self._placed if agent in self._ctxs)
        if not most or not ctx.provider or at_work < most:
            return None
        return {"provider": ctx.provider, "at_work": at_work, "most": most}

    def _fit(self: "AgentRunner", line: list[Ctx], most: dict, each: dict) -> list[bool]:
        """For each of these agents, in the order they came: whether there is room for
        it now in its project and on its provider. Counted from who holds a place -
        there is no second count - and from the room kept for those before it.

        The rule, project first: an agent that has to stay in line keeps a place of its
        project - unless that project's agents on its provider, at work or keeping a
        place, already are as many as the provider lets work (when one of them leaves,
        both come free at once) - and a place on its provider only once its project has
        room for it. So nobody who came later takes what it waits for; those waiting
        for one provider never keep more of a project than that provider can use; and
        an agent whose project is full keeps nobody off its provider.

        (Keeping nothing where the agent cannot work yet would be no rule at all: one
        limit of an agent under two is always full while it waits. The one place that
        stands idle is its project's, while another project's agent has its provider.)"""
        count: Counter = Counter()
        for agent in self._placed:
            if agent in self._ctxs:
                at_work = self._ctxs[agent]
                count["project", at_work.root] += 1
                count["provider", at_work.provider_id] += 1
                count[at_work.root, at_work.provider_id] += 1
        fits: list[bool] = []
        for ctx in line:
            here, there = most.get(ctx.cid), each.get(ctx.provider_id)
            project, provider = ("project", ctx.root), ("provider", ctx.provider_id)
            room = not here or count[project] < here
            fits.append(room and (not there or count[provider] < there))
            if fits[-1] or not there or count[ctx.root, ctx.provider_id] < there:
                count[project] += 1
                count[ctx.root, ctx.provider_id] += 1
            if fits[-1] or room:
                count[provider] += 1
        return fits

    def _full(self: "AgentRunner", ctx: Ctx) -> bool:
        """Whether this agent would have to stand in line now: its project, or its
        provider, has as many agents at work as the user lets it - counting the room
        kept for those in line already. It never raises: limits that cannot be read are
        no room (`let_in` lets nobody in on a guess)."""
        waiting = [one for one, came in self._line_up if not came.done()]
        try:
            most, each = self._limits([*waiting, ctx])
        except Exception:
            return True
        return not self._fit([*waiting, ctx], most, each)[-1]

    def let_in(self: "AgentRunner") -> None:
        """Give the agents waiting for room their places, in the order they came, as far
        as there is room now: whenever an agent leaves its place, and when the user
        changes a limit. (No await between looking and placing: nobody slips in.)

        An agent that has to stay in line keeps room for itself (`_fit` says which):
        nobody who came later takes what it waits for. (Without that, an agent under
        two limits never found both free at once - whenever one had room, a later agent
        took it.) Whoever needs none of that room goes in at once.

        It never raises - it is called where a place is given up, also on the way out of
        a turn that is ending. If the limits cannot be read, nobody is let in on a guess:
        the line is looked at again shortly."""
        waiting = [one for one in self._line_up if not one[1].done()]
        if not waiting:
            return
        try:
            most, each = self._limits([ctx for ctx, _came in waiting])
        except Exception:
            if self._look_again is None:
                self._look_again = asyncio.get_running_loop().call_later(
                    LOOK_AGAIN, self._let_in_again)
            return
        fits = self._fit([ctx for ctx, _came in waiting], most, each)
        for one, room in zip(waiting, fits, strict=True):
            if room:
                ctx, came = one
                self._line_up.remove(one)
                self._placed.add(ctx.agent_id)
                self._clock(ctx.run_id)  # before it is woken: its minutes count from here
                came.set_result(None)

    def _let_in_again(self: "AgentRunner") -> None:
        self._look_again = None
        self.let_in()

    def at_work(self: "AgentRunner", root: str) -> int:
        """How many agents of a project hold a place among the agents at work now."""
        return sum(
            self._ctxs[agent].root == root for agent in self._placed if agent in self._ctxs
        )

    def asking(self: "AgentRunner", agent_id: str) -> bool:
        """Whether this agent waits for the user's word on something now."""
        return bool(self._asks.get(agent_id))

    def copy_folder(self: "AgentRunner", agent_id: str) -> Path | None:
        """The folder of the working copy this agent made, while its work goes on; None
        where it has none (any more)."""
        copy = self._copies.get(agent_id)
        return copy.root if copy is not None else None

    # An agent holds a place only while it itself takes a model step or runs a tool.
    # While it waits - for the user's word (`_asks`), for another agent (`_out`), for a
    # file (`_held_up`) - it holds none. Every wait begins with `_step_aside` and ends with
    # `_settle`, and nothing else takes a place back: so the rule does not rest on what
    # one call of an agent saw before it waited, whatever its other calls did meanwhile.
    # (`_take` itself is called for a place that is not taken *back*: an agent's first,
    # in `_attempt` and `_working`, and in `_native_loop`, which says why.)

    def _waits(self: "AgentRunner", agent_id: str) -> bool:
        """Whether an agent waits for anything now, in any of its calls."""
        return bool(
            self._asks.get(agent_id) or self._out.get(agent_id) or self._held_up.get(agent_id)
        )

    def _step_aside(self: "AgentRunner", ctx: Ctx) -> None:
        """A wait of an agent's begins (it is counted already): the place it holds is
        another's, and it is owed one when it waits for nothing any more. An agent that
        holds none - another call of its gave it up, its work is over - leaves none."""
        if ctx.agent_id in self._placed:
            self._away.add(ctx.agent_id)
            self._give(ctx)

    async def _settle(
        self: "AgentRunner", ctx: Ctx, queued: bool = True, first: Callable[[], None] | None = None,
    ) -> bool:
        """A wait of an agent's has ended (it is no longer counted): the agent takes a
        place again, if it left one and waits for nothing else. Whether it has one now.

        One call of an agent at a time, and not while the agent answers somebody (one
        turn of an agent at a time). And looked at again when the place is there: the
        agent may stand in line for a while, and a wait that another call of its began
        meanwhile gave up nothing, for there was nothing to give - so the place is given
        up here. `first`: called once, before anything is waited for - a place, the
        agent's turn, another call of its that is taking the place - when something has
        to be: the user's word is on record before the first of those waits.
        shortcut: counted by agent, not by call - while one call of a CLI that asks for
        two things at once waits, its other call goes on without a place; count by call
        if such a call ever does long work."""
        agent_id = ctx.agent_id
        if self._waits(agent_id) or agent_id not in self._away:
            return agent_id in self._placed and not self._waits(agent_id)
        # (A turn taken on a message is the turn its sender holds: nobody else is in it.)
        turn = None if ctx.in_turn else self._turn_of(agent_id)
        settling = self._settling.setdefault(agent_id, asyncio.Lock())

        def short() -> bool:
            return agent_id not in self._placed and (
                self._slots[ctx.run_id].locked() or self._full(ctx))

        # (Where none of these is so, nothing below gives way to anything else: a free
        # lock and a free place are taken without a wait.)
        in_the_way = (turn is not None and turn.locked()) or settling.locked()
        waits = short()
        if (in_the_way or waits) and first is not None:
            first()
        async with turn or contextlib.nullcontext(), settling:
            if self._waits(agent_id) or agent_id not in self._away:
                return agent_id in self._placed and not self._waits(agent_id)
            if in_the_way:
                waits = short()  # as it is now: its turn was waited for meanwhile
            await self._take(ctx, queued)
            if self._waits(agent_id):
                self._give(ctx)
                self._set_agent(ctx.cid, agent_id, status=(
                    "blocked" if self._held_up.get(agent_id)
                    else "waiting" if self._out.get(agent_id) else "running"))
                return False
            self._away.discard(agent_id)
            if waits:
                self._set_agent(ctx.cid, agent_id, status="running")
            return True

    async def _users_word(
        self: "AgentRunner", ctx: Ctx, asked: asyncio.Future[str],
        heard: Callable[[str, bool], None] | None = None, back: bool = True, tell: bool = True,
    ) -> str:
        """Wait for the user's word on what an agent asked for - a decision, an answer.
        Meanwhile the agent holds no place among the agents at work, as one that waits
        for a file holds none: the place is another's until the word is there.

        `heard`: called with the word as soon as it is there, before anything is waited
        for - a place, or the agent's turn - and with whether something has to be: what
        the user said is on record at once, however long the agent then stands in line
        ("waiting for a place" is what its record says in either case; shortcut: a turn
        another agent holds is short, give it words of its own if that is ever seen
        to last). `back`: False where the next wait
        follows at once (a sub-agent the user said yes to): no place is taken between.
        `tell`: False where what it waits on was told on the desktop already (`_tell_waits`)."""
        self._asks[ctx.agent_id] = self._asks.get(ctx.agent_id, 0) + 1
        if tell:
            self._tell_waits(ctx, asked)
        self._step_aside(ctx)
        # K-lead-bekliyor (R116): a Lead that asked the user stood "working" for as long as
        # the user was away. One at work that waits for the user's word is "waiting", as one
        # that waits for its sub-agents is - and at work again once it has the word and a
        # place. (Not with `back` False: the sub-agent's wait that follows says "waiting" itself.)
        # shortcut: a message to it meanwhile is routed as to one waiting on sub-agents
        # (`_reachable`: an answer turn; a CLI Lead's door is not used) - the step's calls run
        # one after another, so a sub-agent of its own is not at work while it asks; look here
        # if a team member is seen unable to reach a Lead that asks.
        with self._factory() as session:
            stood = back and session.get_one(Agent, ctx.agent_id).status == "running"
        if stood:
            self._set_agent(ctx.cid, ctx.agent_id, status="waiting")
        try:
            word = await asked
        finally:
            self._asks[ctx.agent_id] = self._asks.get(ctx.agent_id, 1) - 1
        if not back:
            return word
        told = False

        def in_line() -> None:
            # The user has spoken: what the agent waits for now is a place, and the
            # turn says so at once.
            nonlocal told
            told = True
            if heard is not None:
                heard(word, True)
            self._update_run(ctx.run_id, ctx.cid, status="running")

        try:
            await self._settle(ctx, first=in_line)
        finally:
            if told:
                # Its caller says "running" again as this returns (nothing is awaited in
                # between): one more is counted for that to take off.
                self._asking[ctx.run_id] = self._asking.get(ctx.run_id, 0) + 1
        if heard is not None and not told:
            heard(word, False)
        # At work again, whether "waiting" was set here or by the sub-agents it also waited
        # for (`_handing_over`); `_settle` said "running" itself where it had to wait for a place.
        if not self._waits(ctx.agent_id):
            with self._factory() as session:
                still = session.get_one(Agent, ctx.agent_id).status == "waiting"
            if still:
                self._set_agent(ctx.cid, ctx.agent_id, status="running")
        return word

    def _turn_of(self: "AgentRunner", agent_id: str) -> asyncio.Lock:
        return self._turns.setdefault(agent_id, asyncio.Lock())

    @contextlib.asynccontextmanager
    async def _working(self: "AgentRunner", ctx: Ctx, queued: bool = False, shown: bool = True):
        """An agent at work holds a place; one that must wait for a place is `queued`."""
        await self._take(ctx, queued, shown)
        try:
            yield
        finally:
            self._give(ctx)

    @contextlib.asynccontextmanager
    async def _handing_over(self: "AgentRunner", ctx: Ctx):
        """While an agent waits for others - its sub-agents, or a reply - it is `waiting`
        and its place is free for them. It takes a place again when the last is back."""
        waits = self._out[ctx.agent_id] = self._out.get(ctx.agent_id, 0) + 1
        if waits == 1:
            self._set_agent(ctx.cid, ctx.agent_id, status="waiting")
        self._step_aside(ctx)
        try:
            yield
        except asyncio.CancelledError:
            self._out[ctx.agent_id] -= 1  # the turn is being stopped: nothing to go back to
            raise
        except BaseException:
            await self._back_to_work(ctx)  # a refusal is a result: the agent goes on
            raise
        else:
            await self._back_to_work(ctx)

    async def _back_to_work(self: "AgentRunner", ctx: Ctx) -> None:
        self._out[ctx.agent_id] -= 1
        if self._out[ctx.agent_id] > 0:
            return
        if self._held_up.get(ctx.agent_id):
            return  # it still waits for a file: `_claim` takes its place when that is its own
        # (One the user still owes a word stays "waiting": `_users_word` says "running" after.)
        if await self._settle(ctx, queued=False):
            self._set_agent(ctx.cid, ctx.agent_id, status="running")
