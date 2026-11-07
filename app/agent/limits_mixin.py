"""Limits and a turn nobody watches: the project's budget and minutes, a role's steps and tokens,
how near a turn is to a limit and how it is wrapped up, and who may be asked when the user is
not watching (`_nobody_to_ask`, `_leave`) - `LimitsMixin`.
"""

import asyncio
import time
from dataclasses import replace
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app import project_map, recipe_run
from app.agent.cards import _goes_on, _steps_of_chain
from app.agent.ctx import Ctx, _NobodyToAsk, _Unwatched
from app.agent.words import (
    ANSWER_PREFIX,
    BACKLOG_NOT_THIS,
    CONTINUE_WORDS,
    GIVEN_UNDONE,
    LEFT_UNDONE,
    MINUTE,
    NOBODY,
    STEPS_ASKED,
    STEPS_CONTINUE,
    STEPS_STOP,
    TEAM_STOPPED,
    UNATTENDED_NOT_THIS,
    USER_STOPPED_HERE,
)
from app.api.usage import month_spend
from app.commands import danger, is_exactly, ticked
from app.db.models import Agent, Conversation, Flag, OwnRequest, Project, Provider, Run, Trigger
from app.model_client import ModelClient, OwnStop
from app.providers import works_with_own_tools
from app.roles import find_role
from app.team import quoted
from app.workspace import standing_asks

if TYPE_CHECKING:
    from app.agent import AgentRunner

# An agent that came to what its role lets one agent use: KOLONİ's own rule (OwnStop).
ROLE_STEPS = "stopped at its role's limit of {limit} step{s}"
ROLE_TOKENS = "stopped at its role's limit of {limit} tokens: it used {used}"

# How a stop at the end of the steps given once more (K-devam-butce, `GIVEN_ONCE`) is on
# record (B-327: not "step_limit", whose words everywhere say the app's limit).
GIVEN_LIMIT = "stopped after the {steps} steps it was given"

# Near a limit (`_near_a_limit`): from this many steps left, or this share of the role's
# tokens spent. Fixed, as the signs' counts are.
WRAP_UP_STEPS = 2
WRAP_UP_SHARE = 0.9
WRAP_UP = (
    "KOLONİ: {near} before you are stopped. Start nothing new: finish what you are on, or "
    "leave it where you can say how it stands, and write your report - what you did and "
    "what is left."
)
# Told once to an agent whose project has used most of its monthly budget (`_near_budget`,
# 93-C6): what the user is warned of, so the agent spends no more than the job needs.
BUDGET_NEAR = (
    "KOLONİ: this project has used {least}{used}% of its monthly budget. Do what your task "
    "needs and nothing more: no extra checks, no work beyond it."
)
# How often a project's month is added up for it (`_near_budget`), not at every step.
# shortcut: an agent may be told up to this late; read it as tokens are counted if that is
# seen to matter.
BUDGET_EVERY = 60.0

BUDGET_STEPS = "budget: stopped after {steps} model steps, the most this trigger gives a turn"
BUDGET_MINUTES = (
    "budget: stopped after {minutes} minutes, the longest this trigger lets a turn run"
)
OVER_LIMIT = "this turn used {used} tokens, over the project's limit of {limit}"
# Where the stop cut a step or a CLI at work: what that had spent by then is not all known.
OVER_LIMIT_AT_LEAST = (
    "this turn used at least {used} tokens, over the project's limit of {limit}"
)
# What an agent is on record as having spent: all it sent and all it wrote.
SPENT = func.coalesce(Agent.input_tokens_total, 0) + func.coalesce(Agent.output_tokens, 0)
# The same of a request KOLONİ made itself in a turn: the turn spent it, no agent did.
ASKED = func.coalesce(OwnRequest.input_tokens, 0) + func.coalesce(OwnRequest.output_tokens, 0)

# R143: a team's lead's steps on top of the app's limit, for each step of its recipe
# (`_recipe_steps`): open the step's agents, wait for them, read what came back, one to spare.
LEAD_STEPS_PER_RECIPE_STEP = 4
# R147: each Ask for changes runs the recipe again from its loop's step, so it gives its runner
# the recipe's steps once more - for this many rounds at most: past them a loop the user keeps
# sending back stops at the limit, not runs on unbounded.
ASKED_ROUNDS_PAID = 3
# B-398: the Orchestrator's steps on top of the app's limit for each team row its chat has
# with a lead: open the lead, pass on its messages between teams, read its report, one to
# spare - the live run of five teams (a room, four leads, 13+ messages, the merge) ran out
# of 25 right after merging.
STEPS_PER_TEAM = 8

# B-398: Settings › The app's "Steps an agent may take" (the `flags` row STEPS_FLAG); without one,
# `config.max_steps`. Held to MOST_STEPS_RANGE.
STEPS_FLAG = "max_steps"
MOST_STEPS_RANGE = (5, 200)


def app_steps(session, default: int) -> int:
    """The most steps one agent takes on a job, as the user set it (STEPS_FLAG); a row that is
    no whole number counts for nothing, and one out of MOST_STEPS_RANGE is held to it."""
    row = session.get(Flag, STEPS_FLAG)
    try:
        low, high = MOST_STEPS_RANGE
        return min(high, max(low, int(row.value))) if row else default
    except ValueError:
        return default


class LimitsMixin:
    # --- a turn nobody is watching --------------------------------------------

    def _watch_the_budget(self: "AgentRunner", session, run: Run) -> None:
        """An unattended turn starts: from here on it is one, and its time is counted.
        A trigger that is gone gives it nothing - no step, and no leave."""
        trigger = session.get(Trigger, run.trigger_id) if run.trigger_id else None
        budget = trigger.budget if trigger else {}
        unwatched = self._unwatched[run.id] = _Unwatched(
            trigger.id if trigger else None, run.trigger_name or "",
            steps=int(budget.get("steps") or 0), minutes=int(budget.get("minutes") or 0),
        )
        unwatched.left = unwatched.minutes * MINUTE
        self._count_minutes(run.id)

    def _clock(self: "AgentRunner", run_id: str) -> None:
        """Who of a turn holds a place, or stands in line for one, has changed. For an
        unattended turn its minutes are looked at - once what is going on right now is
        through: a place that goes from one of its agents to the next stops no clock."""
        if run_id in self._unwatched:
            asyncio.get_running_loop().call_soon(self._count_minutes, run_id)
        elif run_id in self._rooms:
            asyncio.get_running_loop().call_soon(self._room_minutes, run_id)

    def _count_minutes(self: "AgentRunner", run_id: str) -> None:
        """An unattended turn's minutes are not counted while it is only kept waiting
        for room: one of its agents stands in line for a place (its project, or its
        provider, is full), none holds one and none waits for a file. Every other minute
        counts - one spent waiting for a file another agent holds too, also while
        another agent of the turn stands in line: the minutes are what ends that wait."""
        unwatched = self._unwatched.get(run_id)
        if unwatched is None or run_id in self._over:
            return
        kept_out = self._kept_out(run_id)
        at = asyncio.get_running_loop().time()
        if kept_out and unwatched.timer is not None:
            unwatched.timer.cancel()
            unwatched.timer, unwatched.left = None, unwatched.left - (at - unwatched.since)
        elif not kept_out and unwatched.timer is None:
            later = self.call_later or asyncio.get_running_loop().call_later
            unwatched.since = at
            unwatched.timer = later(
                max(0.0, unwatched.left), self._over_budget, run_id,
                BUDGET_MINUTES.format(minutes=unwatched.minutes),
            )

    def _kept_out(self: "AgentRunner", run_id: str) -> bool:
        """Whether a turn is only kept waiting for room right now: one of its agents
        stands in line for a place, none holds one and none waits for a file."""
        in_line = any(ctx.run_id == run_id and not came.done() for ctx, came in self._line_up)
        return in_line and not any(
            self._ctxs[agent].run_id == run_id
            for agent in (*self._placed, *(a for a, files in self._held_up.items() if files))
            if agent in self._ctxs
        )

    def _over_budget(self: "AgentRunner", run_id: str, why: str | int) -> None:
        """Stop a turn that has used up its budget the way Stop does - every agent,
        command and CLI of it ends with it - and have it recorded as failed, with `why`.
        (So is one that sent its planted test key out: 101.)"""
        task = self._tasks.get(run_id)
        if task is None or run_id in self._over:
            return
        self._over[run_id] = why
        task.cancel()

    def _why_over(self: "AgentRunner", run_id: str) -> str:
        """Why a turn over its budget was stopped. For the limit on tokens the sentence is
        made here, when everything of the turn has ended: what a step cut by the stop had
        reported is in the sum by now, and where an agent of the turn was cut before it
        said what it spent, the sum is only the least the turn used."""
        why = self._over[run_id]
        if isinstance(why, str):
            return why
        with self._factory() as session:
            used, cut = self._turn_spent(session, run_id)
        return (OVER_LIMIT_AT_LEAST if cut else OVER_LIMIT).format(used=used, limit=why)

    @staticmethod
    def _turn_spent(session, run_id: str) -> tuple[int, bool]:
        """What a turn is on record as having spent - its agents, and what KOLONİ asked
        itself for them (`OwnRequest`) - and whether any of that was cut short."""
        spent = [session.execute(
            select(func.sum(tokens), func.max(of.cut_short)).where(of.run_id == run_id)
        ).one() for tokens, of in ((SPENT, Agent), (ASKED, OwnRequest))]
        return sum(used or 0 for used, _cut in spent), any(cut for _used, cut in spent)

    def _cut(
        self: "AgentRunner", ctx: Ctx, sent: int | None = None, made: int | None = None,
        read: int | None = None, written: int | None = None,
    ) -> None:
        """A model step, or a CLI's run, ended without coming to its end - Stop, a limit,
        a failure: what it had reported by then is counted, and the agent is on record as
        one whose numbers are only part of what it used."""
        with self._factory() as session:
            session.get_one(Agent, ctx.agent_id).cut_short = True
            session.commit()
        if sent is not None or made is not None:
            self._count_tokens(ctx, sent, made, read=read, written=written)

    def _count_step(self: "AgentRunner", ctx: Ctx) -> None:
        """A model step of an unattended turn is about to be taken, by whichever of its
        agents: one more than its budget has, and the whole turn stops here. So does any
        turn - watched or not - that is over its project's limit on tokens. And a member
        of a room that has ended takes none: its work stops here, as the room's end
        stops it wherever else it is."""
        found = self._member_of(ctx)
        if found is not None and found[0].outcome is not None:
            raise asyncio.CancelledError
        self._hold_to_limit(ctx)
        unwatched = self._unwatched.get(ctx.run_id)
        if unwatched is None:
            return
        if unwatched.taken >= unwatched.steps:
            self._over_budget(ctx.run_id, BUDGET_STEPS.format(steps=unwatched.steps))
            raise asyncio.CancelledError
        unwatched.taken += 1

    def _hold_to_limit(self: "AgentRunner", ctx: Ctx) -> None:
        """Before a model step, or a CLI, is started: a turn whose agents (and a question
        KOLONİ asked a model for it) have reported more tokens than its project lets a
        turn use is stopped, as one over a trigger's
        budget is. Only what was reported counts - a model that reports nothing is not
        limited - and a CLI that keeps its own loop reports when it ends, so what it
        spends itself holds nothing back until then: it is checked before it starts and
        at each message of it, against what the turn's others have reported. A job while
        the user is away is held to its night's time and money too (`_hold_to_away`)."""
        self._hold_to_away(ctx)
        with self._factory() as session:
            limit = session.scalar(
                select(Project.turn_token_limit).join(
                    Conversation, Conversation.project_id == Project.id
                ).where(Conversation.id == ctx.cid)
            )
            used = limit and self._turn_spent(session, ctx.run_id)[0]
        if limit and used and used > limit:
            self._over_budget(ctx.run_id, limit)
            raise asyncio.CancelledError

    def _hold_to_role(self: "AgentRunner", ctx: Ctx, taken: int | None) -> None:
        """Before a model step, or a CLI, is started: an agent that has come to what its
        role lets one agent use stops here - that agent, not the turn (OwnStop: a rule of
        KOLONİ's own, so no class of failure and no advice about other providers).
        `taken`: the model steps of the job at hand so far (its task, or a turn on a
        message), as the app's own step limit counts them. Tokens: all the agent has
        reported, as the project's limit counts them - a model that reports nothing is
        not held. A CLI session is held at each message it writes (`_Transcript`), which
        is the step KOLONİ counts of it; one at work with its own tools takes none
        (`taken` is None). Either reports what it spent when it ends: by tokens it is
        held before it starts, a first or a later time. An agent of a team the user stopped
        stops here too (slice 84b-2: `stop_team`)."""
        if ctx.agent_id in self._halted:
            self._stopped_by_koloni(ctx)
            raise OwnStop(self._halt_why.get(ctx.agent_id, TEAM_STOPPED))
        # (K-devam-butce: a job on a budget given on top runs its steps, not the role's.)
        if taken is not None and ctx.role_steps is not None and (
                ctx.agent_id not in self._given_steps
                and taken + self._role_before(ctx) >= ctx.role_steps):
            self._stopped_by_koloni(ctx)
            raise OwnStop(ROLE_STEPS.format(
                limit=ctx.role_steps, s="" if ctx.role_steps == 1 else "s"))
        if ctx.role_tokens is None:
            return
        with self._factory() as session:
            used = session.scalar(select(SPENT).where(Agent.id == ctx.agent_id)) or 0
        if used > ctx.role_tokens:
            self._stopped_by_koloni(ctx)
            raise OwnStop(ROLE_TOKENS.format(limit=ctx.role_tokens, used=used))

    def _role_before(self: "AgentRunner", ctx: Ctx) -> int:
        """The steps of its own work an agent took before this job, told to go on (B-325) -
        in this turn, and (B-327) in the earlier turns it goes on from (`continues_id`), as
        their records have them (`_steps_of_chain`), read once."""
        if not self._role_counts(ctx):
            return 0
        if ctx.agent_id not in self._role_taken and ctx.continues_id:
            with self._factory() as session:
                self._role_taken[ctx.agent_id] = _steps_of_chain(session, ctx.continues_id)
        return self._role_taken.get(ctx.agent_id, 0)

    def _given_limit(self: "AgentRunner", ctx: Ctx) -> str:
        """How a stop at the end of a job's steps is on record: "step_limit" (the app's limit)
        or, on a budget given on top (K-devam-butce), the budget itself - the words that say
        the app's limit are not said of it (B-327)."""
        given = self._given_steps.get(ctx.agent_id)
        return "step_limit" if given is None else GIVEN_LIMIT.format(steps=given)

    def _role_counts(self: "AgentRunner", ctx: Ctx) -> bool:
        """Whether a job's steps add up with its agent's others against its role's limit. Not
        one with a limit of its own (a room's sharing step), nor a room member's: each time
        it is woken counts on its own, as before B-325."""
        room = self._rooms.get(ctx.run_id)
        return _goes_on(ctx) and not ctx.max_steps and not (
            room is not None and ctx.agent_id in room.members)

    def _role_now(self: "AgentRunner", ctx: Ctx) -> Ctx:
        """B-325: an agent with its role's limits as they stand now (the user may have changed
        them since it was made); a role gone keeps the ones it had. By name: an agent's record
        keeps no role id."""
        with self._factory() as session:
            role = find_role(session, ctx.role)
        return ctx if role is None else replace(
            ctx, role_steps=role.max_steps, role_tokens=role.max_tokens)

    def _stopped_by_koloni(self: "AgentRunner", ctx: Ctx) -> None:
        """An agent stopped by a limit, a rule or a count of KOLONİ's own: so it is in the
        track record (`app.record`), not as a failure."""
        self._set_agent(ctx.cid, ctx.agent_id, stopped_by_koloni=True)

    def _near_a_limit(self: "AgentRunner", ctx: Ctx) -> str:
        """What an agent is told before a step near the end of what it may do - one of its
        last steps, or most of its role's tokens spent - so that it ends with a report
        rather than being cut off in the middle of its work; "" when it is not near one.
        In an unattended turn its budget of steps, counted over all its agents, is a limit
        too. A CLI session is told with a tool result (B-382: `_session_loop`), its steps left
        kept at each message it writes (`_Transcript`). shortcut: a CLI with tools of its own
        is told only what its first prompt says - of tokens, not of steps: nothing reaches it
        between its steps. shortcut: a session's unattended budget below counts one step more
        than it has (its message is counted when it begins); count it apart if that matters."""
        left = self._steps_left.get(ctx.agent_id)
        unwatched = self._unwatched.get(ctx.run_id)
        if left is not None and unwatched is not None:
            # (this step is counted already: `_count_step`)
            left = min(left, unwatched.steps - unwatched.taken + 1)
        if left is not None and left <= WRAP_UP_STEPS:
            return WRAP_UP.format(near=f"you have {left} step{'' if left == 1 else 's'} left")
        if ctx.role_tokens is None:
            return ""
        with self._factory() as session:
            used = session.scalar(select(SPENT).where(Agent.id == ctx.agent_id)) or 0
        if used < ctx.role_tokens * WRAP_UP_SHARE:
            return ""
        return WRAP_UP.format(
            near=f"you have used {used} of the {ctx.role_tokens} tokens your role allows")

    def _near_budget(self: "AgentRunner", ctx: Ctx) -> str:
        """What an agent is told once, at its first step after its project's month came to
        the share of its budget the user is warned at (`month_spend`'s `warn`, 80%); "" for
        one told already, and where no budget is set or what was spent cannot be added up
        (prices in more than one currency: no share). Told once: not at every step. The
        month is added up at most every BUDGET_EVERY seconds for a project."""
        if ctx.agent_id in self._budget_told:
            return ""
        with self._factory() as session:
            project = self._project(session, ctx.cid)
            if project is None or project.monthly_budget is None:
                return ""
            at, said = self._budget_read.get(project.id, (None, ""))
            if at is None or time.monotonic() - at >= BUDGET_EVERY:
                spend = month_spend(session, project)
                said = BUDGET_NEAR.format(
                    least="at least " if spend["at_least"] else "",
                    used=int(spend["share"] * 100 + 1e-9),  # (0.29 * 100 is 28.99…)
                ) if spend["warn"] else ""
                self._budget_read[project.id] = (time.monotonic(), said)
        if said:
            self._budget_told.add(ctx.agent_id)
        return said

    def _step_limit(self: "AgentRunner", ctx: Ctx) -> int:
        """The most steps one agent takes on a job. In an unattended turn the trigger's
        budget, which counts all its agents together, is what holds. A job on a budget given
        on top (K-devam-butce) takes that many."""
        if (given := self._given_steps.get(ctx.agent_id)) is not None:
            return given
        unwatched = self._unwatched.get(ctx.run_id)
        if unwatched is None:
            return self._app_steps() + self._recipe_steps(ctx) + self._team_steps(ctx)
        return max(self._app_steps(), unwatched.steps)

    async def _more_steps(self: "AgentRunner", ctx: Ctx) -> bool:
        """B-397: a sub-agent - a team's coordinator too - that came to its step limit in a turn
        the user watches asks them on a card under the call that opened it: Continue gives it
        the project's `continue_steps` on top of the steps its job took (`_give_steps`), and it
        goes on where it is (True); Stop here ends it as before (False). At Full auto the Lead
        answers the card for the user (K-fullauto-sorma: a "card"), either way, once for each
        agent in a turn (`_budgeted`, as K-devam-butce): past that it ends. No card where nobody
        would be there to answer - a turn a trigger started, a night's job, a backlog task - nor
        for a job with a limit of its own (a room's sharing step), an answer, a turn on another's
        message (its sender waits for the reply), or a room member. Nor where its work is kept
        on a card of its own with Continue on it (B-322: that ends at once and holds nobody up).
        Its role's step limit still holds: Continue gives at most what the role has left, and
        none is asked where it has none left. A go on by message (`_go_on_gate`) counts as its
        once too. Over the project's month budget the Lead does not answer (`_lead_answers`).
        """
        if not await self._steps_card_offered(ctx):
            return False
        key = (ctx.run_id, ctx.name.casefold())
        taken = self._steps_used.get(ctx.agent_id, 0)
        with self._factory() as session:
            call_id = session.get_one(Agent, ctx.agent_id).tool_call_id
            project = self._project(session, ctx.cid)
            steps = project.continue_steps if project else self._app_steps()
        if (role := self._role_now(ctx).role_steps) is not None:
            steps = min(steps, role - self._role_before(ctx) - taken)
        if call_id is None or steps <= 0:
            return False
        go_on, ids = STEPS_CONTINUE.format(steps=steps), []
        try:
            _status, word = await self._ask_user(ctx, call_id, {
                "question": STEPS_ASKED.format(name=ctx.name, taken=taken, steps=steps),
                "options": [go_on, STEPS_STOP]}, leave=True, ids=ids, kind="card")
        except _NobodyToAsk:
            return False
        by_user = self._who_answered(ctx, ids) == "The user"
        if word.removeprefix(ANSWER_PREFIX) != go_on:
            if by_user:  # (the Lead's own Stop here is its decision: it knows it)
                self._stopped_here.add(key)
            return False
        self._budgeted[key] = self._give_steps(
            ctx, "the user's Continue" if by_user else "your call at Full auto", taken, steps)
        self._nudge(ctx, CONTINUE_WORDS.format(steps=steps))
        return True

    async def _steps_card_offered(self: "AgentRunner", ctx: Ctx) -> bool:
        """`_more_steps`: whether its card is asked at all."""
        if (not ctx.depth or ctx.max_steps or not _goes_on(ctx) or ctx.in_turn
                or ctx.agent_id in self._halted or not self._watched(ctx.run_id)
                or ctx.run_id in self._away_jobs or ctx.run_id in self._backlog_turns
                or self._member_of(ctx) is not None or await self._kept_card_comes(ctx)):
            return False
        return not ((ctx.run_id, ctx.name.casefold()) in self._budgeted and self._full_auto(ctx))

    def _left_undone(self: "AgentRunner", ctx: Ctx) -> str:
        """B-397 (c): what its opener is told of one that stopped at a step limit - so its part is
        handed on, not taken for done; never to go on where the user ended it on its card, nor
        where it had its more steps once in this turn (`_go_on_gate`)."""
        key = (ctx.run_id, ctx.name.casefold())
        if key in self._stopped_here:
            return USER_STOPPED_HERE
        return GIVEN_UNDONE if key in self._budgeted else LEFT_UNDONE

    def _team_steps(self: "AgentRunner", ctx: Ctx) -> int:
        """B-398: the Orchestrator's STEPS_PER_TEAM for each of its chat's team rows a lead runs
        (a row no lead runs is its own recipe's: `_recipe_steps`)."""
        if ctx.depth:
            return 0
        with self._factory() as session:
            return STEPS_PER_TEAM * sum(
                lead is not None for _row, _team, lead in self._rows(session, ctx.cid))

    def _app_steps(self: "AgentRunner") -> int:
        """The app's step limit, as Settings › The app has it (`app_steps`)."""
        with self._factory() as session:
            return app_steps(session, self.settings.max_steps)

    def _recipe_steps(self: "AgentRunner", ctx: Ctx) -> int:
        """R143: a team's lead runs its recipe step by step - opening each step's agents,
        waiting, reading what came back - and Feature's six steps did not fit in the app's
        limit: it has LEAD_STEPS_PER_RECIPE_STEP more for each step of its row's recipe. R147:
        so has the Lead for a row no lead runs (a one-team chat's) - from its first step, the
        recipe not begun yet - and either as much again for each Ask for changes on it, up to
        ASKED_ROUNDS_PAID. Read at each step: a recipe is sent back while its runner works."""
        if ctx.depth > 1:
            return 0
        steps = 0
        with self._factory() as session:
            for row, team, lead in self._rows(session, ctx.cid):
                if lead is not None if ctx.depth == 0 else not lead or lead.name != ctx.role:
                    continue
                if state := self._live_state(row, ctx.run_id):
                    asked = min(state.get("asked", 0), ASKED_ROUNDS_PAID)
                    steps += len(recipe_run.graph_of(state).steps) * (1 + asked)
                elif ctx.depth == 0 and (found := self._recipe_of(session, row, team)):
                    steps += len(found[1].steps)
        return LEAD_STEPS_PER_RECIPE_STEP * steps

    def _watched(self: "AgentRunner", run_id: str) -> bool:
        """Whether somebody is there to be asked: a turn the user started."""
        return run_id not in self._unwatched

    def _full_auto(self: "AgentRunner", ctx: Ctx) -> bool:
        """K-fullauto-sorma: a turn the user watches at Full auto (not a job while they are
        away): by their rule nothing asks there but harm - the Lead decides the rest.
        shortcut: a session per call, at every command look too; cache it per run once a
        turn is seen to feel it (the level may change mid-turn: read it then)."""
        if (not self._watched(ctx.run_id) or ctx.run_id in self._away_jobs
                or ctx.run_id in self._backlog_turns):
            return False
        with self._factory() as session:
            return session.get_one(Conversation, ctx.cid).permission_mode == "full_auto"

    def _unwatched_like(self: "AgentRunner", run_id: str) -> bool:
        """Whether a provider is picked as for a turn nobody watches - a trigger's, or a
        backlog task's (K-r135) - a CLI with its own tools passed over rather than refused."""
        return not self._watched(run_id) or run_id in self._backlog_turns

    def _standing_asks(self: "AgentRunner", run_id: str, standing: str | None, level: str) -> bool:
        """`standing_asks` - but in a backlog task's turn every such file is asked, an
        instruction file at Full auto too (K-r135: a night's rules)."""
        return standing_asks(standing, "ask" if run_id in self._backlog_turns else level)

    def _nobody_to_ask(
        self: "AgentRunner", ctx: Ctx, what: str, wanted: str, command: str | None = None,
        cwd: str = ".",
        opening: int = 1, host: str | None = None,
    ) -> str | None:
        """The one gate before anything that would wait for the user.

        None in a turn somebody is watching: the caller asks, or does not, as the
        conversation's settings say. In an unattended turn nothing is ever asked, and the
        conversation's level and allow list count for nothing: "" when the trigger's own
        permissions allow this - it is done without asking - and otherwise the words it
        is refused with. `what` is "write", "command" (the whole line, as it would run,
        in the project folder: it has to be, character for character, a rule the trigger
        has ticked on its conversation's allow list as that list stands now), "agent"
        (one more, or `opening` more, below the lead), "web" (a search), "host" (a GET or
        HEAD to `host` - scheme, name and port as `web.rule_of` writes them - which the
        trigger has to name, letter for letter) or "notify";
        anything else no trigger can allow. `wanted` says it in words, for the refusal.
        Read off the trigger each time: what the user takes back is gone at once.
        """
        unwatched = self._unwatched.get(ctx.run_id)
        if unwatched is None:
            return None
        with self._factory() as session:
            trigger = session.get(Trigger, unwatched.trigger_id) if unwatched.trigger_id else None
            leave = trigger.permissions if trigger and isinstance(trigger.permissions, dict) else {}
            lines = [rule.prefix for rule in ticked(session, trigger)] if leave else []
            tests = session.scalar(
                select(Project.test_commands)
                .join(Conversation, Conversation.project_id == Project.id)
                .where(Conversation.id == ctx.cid)) if what == "command" else None
            opened = session.scalar(
                select(func.count()).select_from(Agent).where(
                    Agent.run_id == ctx.run_id, Agent.depth > 0, Agent.status != "rejected"
                )
            ) or 0
        if what == "write":
            may = leave.get("write") is True
        elif what == "command":
            # A ticked rule of the conversation's allow list lets one command through:
            # the one that is its text. (With the user there the same rule also covers
            # that command with more arguments - `CommandRunner` reads it so, not this.)
            # So does the user's own test command, run in its part's folder (K-buyuk-proje).
            may = isinstance(command, str) and (cwd == "." and any(
                is_exactly(command, line) for line in lines
            ) or project_map.own_test(tests, command, cwd))
        elif what == "agent":
            most = leave.get("agents")
            may = isinstance(most, int) and not isinstance(most, bool) and opened + opening <= most
        elif what in ("web", "notify"):
            may = leave.get(what) is True
        elif what == "host":
            named = leave.get("hosts")
            may = isinstance(named, list) and host in [
                one.lower() for one in named if isinstance(one, str)
            ]
        else:
            may = False
        if may:
            return ""
        return NOBODY.format(trigger=quoted(unwatched.trigger_name), what=wanted)

    @staticmethod
    def _cannot_be_held(model: ModelClient | None, provider: Provider | None = None) -> bool:
        """Whether an agent would work with tools of its own, and so cannot be used where
        nobody is watching: only an agent that works with KOLONİ's tools runs there.

        Such a CLI has tools, web tools and sub-agents of its own, and KOLONİ sees of them
        only what it asks about: since 89a/b/c Codex, Claude Code and Copilot ask before
        each tool KOLONİ judges, and native agy through its hook, but what each does
        without asking (its own rules, agy that reads) is not held to a trigger. That goes
        for every one of them. Told by the client, and by how its provider is set up
        (`providers.OWN_TOOLS`) - either is enough.
        """
        return bool(getattr(model, "native", False)) or (
            provider is not None and works_with_own_tools(provider)
        )

    def _not_unattended(self: "AgentRunner", ctx: Ctx) -> str | None:
        """Why this agent's turn is not started: nobody is watching - a trigger's turn, or a
        backlog task's (K-r135) - and it would work with tools of its own. None when it may
        start."""
        backlog_turn = ctx.run_id in self._backlog_turns
        if self._watched(ctx.run_id) and not backlog_turn:
            return None
        with self._factory() as session:
            provider = session.get(Provider, ctx.provider_id) if ctx.provider_id else None
            if not self._cannot_be_held(ctx.model, provider):
                return None
        return (BACKLOG_NOT_THIS if backlog_turn else UNATTENDED_NOT_THIS).format(
            provider=ctx.provider or "This CLI")

    def _leave(self: "AgentRunner", run_id: str) -> dict:
        """What the trigger of an unattended turn allows, as it stands right now; nothing
        when the trigger is gone. Its `commands` are the lines themselves: the texts of
        the rules it has ticked that are still on its conversation's allow list."""
        unwatched = self._unwatched[run_id]
        with self._factory() as session:
            trigger = session.get(Trigger, unwatched.trigger_id) if unwatched.trigger_id else None
            if trigger is None or not isinstance(trigger.permissions, dict):
                return {}
            # (a rule stored before slice 90 for one that deletes covers nothing: not promised)
            lines = [rule.prefix for rule in ticked(session, trigger) if not danger(rule.prefix)]
            return {**trigger.permissions, "commands": lines}

    def _leave_in_words(self: "AgentRunner", run_id: str) -> str:
        """What the trigger of an unattended turn allows, for the agent's instructions."""
        leave = self._leave(run_id)
        lines = [line for line in leave.get("commands") or [] if isinstance(line, str)]
        most = leave.get("agents") if isinstance(leave.get("agents"), int) else 0
        hosts = [one for one in leave.get("hosts") or [] if isinstance(one, str)]
        off = self._off()  # (slice 61: a web tool switched off is not said to be allowed)
        if "http_request" in off:
            hosts = []
        return "; ".join([
            "read, search, look in the memory and write notes",
            "change files" if leave.get("write") is True else "change no file",
            # (`_nobody_to_ask`: the user's own test command runs unticked, `own_test`)
            ("run exactly these command lines in the project folder, and the project's own test "
             "command if it has one, and no other: " + ", ".join(quoted(line) for line in lines))
            if lines else "run no command but the project's own test command, if it has one",
            f"open {most} sub-agent(s) in all, held to the same" if most else "open no sub-agent",
            "search the web" if leave.get("web") is True and "web_search" not in off
            else "make no web search",
            ("make GET and HEAD requests to these and no other: " + ", ".join(hosts)
             + " (with no body and no headers)") if hosts
            else "make no HTTP request",
            "send the user a notification" if leave.get("notify") is True
            else "send no notification",
        ])
