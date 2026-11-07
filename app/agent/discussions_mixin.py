"""Discussions (`app.discussion`): one opened with discuss, its rounds of speeches and the posts
in its shared place, the user's word in it, and its end - `DiscussionsMixin`.
"""

import asyncio
import contextlib
from dataclasses import replace
from typing import TYPE_CHECKING, cast

from sqlalchemy import func, literal_column, select

from app import room as rooms
from app.agent.ctx import Ctx, _NobodyToAsk
from app.agent.words import (
    ANSWER_TOOLS,
    BACKLOG_NOT_THIS,
    LEADS_LATER,
    PAID_NO,
    PAID_UNATTENDED,
    TURN_ANSWERED,
    UNATTENDED_NOT_THIS,
)
from app.api.usage import past_its_limit
from app.db.models import (
    Agent,
    Conversation,
    Discussion,
    DiscussionMember,
    DiscussionPost,
    Message,
    Run,
    now,
    settings_of,
)
from app.discussion import (
    SPEECH_STEPS,
    WHY,
    fit,
    is_pass,
    memory,
    plan_discussion,
    speaking_prompt,
    transcript,
)
from app.model_native import CodexNativeClient
from app.providers import NotListed, allowed
from app.roles import (
    agent_roles,
    can_change_things,
    closed,
    effective_tools,
    find_agent_role,
    shown_name,
)
from app.serialize import discussion_out, discussion_post_out
from app.team import ONLY_IN_THE_PROJECT, only_in_project, would_run
from app.tools import ToolError

if TYPE_CHECKING:
    from app.agent import AgentRunner


class DiscussionsMixin:
    # --- discussions ---------------------------------------------------------

    def _posts(self: "AgentRunner", discussion_id: str) -> tuple[Discussion, list[str], str]:
        """A discussion, its members' agent ids in speaking order, and what was said."""
        with self._factory() as session:
            talk = session.get_one(Discussion, discussion_id)
            session.expunge(talk)
            members = list(session.scalars(
                select(DiscussionMember.agent_id)
                .where(DiscussionMember.discussion_id == discussion_id)
                .order_by(DiscussionMember.position)
            ))
            names = dict(session.execute(
                select(Agent.id, Agent.name).where(Agent.run_id == talk.run_id)).all())
            posts = session.scalars(
                select(DiscussionPost)
                .where(DiscussionPost.discussion_id == discussion_id)
                .order_by(DiscussionPost.created_at, literal_column("discussion_posts.rowid"))
            ).all()
            said = transcript([
                (p.round, p.kind, names.get(p.agent_id, "You") if p.agent_id else "You",
                 p.content)
                for p in posts
            ])
        return talk, members, said

    def _shared_place(self: "AgentRunner", ctx: Ctx) -> str:
        """What a speaker reads when its turn comes: the topic and all that was said."""
        talk, members, said = self._posts(ctx.discussion or "")
        others = [
            self._ctxs[agent_id].name for agent_id in members
            if agent_id != ctx.agent_id and agent_id in self._ctxs
        ]
        return speaking_prompt(talk.topic, others, said, talk.round, talk.max_rounds)

    def _post(
        self: "AgentRunner", cid: str, run_id: str, discussion_id: str, agent_id: str | None,
        number: int,
        content: str, kind: str = "said", passed: bool = False,
    ) -> dict:
        with self._factory() as session:
            post = DiscussionPost(
                discussion_id=discussion_id, agent_id=agent_id, round=number, kind=kind,
                content=content, passed=passed,
            )
            session.add(post)
            session.commit()
            payload = discussion_post_out(post)
        self.bus.emit(cid, run_id, "discussion_post.created", payload)
        return payload

    def _set_discussion(self: "AgentRunner", cid: str, discussion_id: str, **fields) -> None:
        with self._factory() as session:
            talk = session.get_one(Discussion, discussion_id)
            for key, value in fields.items():
                setattr(talk, key, value)
            session.commit()
            run_id, payload = talk.run_id, discussion_out(session, talk)
        self.bus.emit(cid, run_id, "discussion.updated", payload)

    def say_in_discussion(self: "AgentRunner", discussion_id: str, content: str) -> dict | None:
        """The user speaks in the shared place; None if the discussion is over."""
        if discussion_id not in self._ending or self._ending[discussion_id].is_set():
            return None
        with self._factory() as session:
            talk = session.get_one(Discussion, discussion_id)
            run_id, number = talk.run_id, talk.round
            cid = session.get_one(Run, run_id).conversation_id
        self._user_spoke[discussion_id] = True
        return self._post(cid, run_id, discussion_id, None, max(number, 1), content)

    def end_discussion(self: "AgentRunner", discussion_id: str) -> bool:
        """The user ends a discussion; False if it is already over."""
        ending = self._ending.get(discussion_id)
        if ending is None or ending.is_set():
            return False
        ending.set()
        return True

    async def _discuss(self: "AgentRunner", ctx: Ctx, call_id: str, args: dict) -> tuple[str, str]:  # noqa: C901
        """Open a discussion, let its members speak in rounds, and return what was said. In a
        recipe's step (slice 84e) the members it opens are the step's agents, as spawn_agent
        opens them: the step goes on as the discussion ends - it writes no file."""
        topic, invited, rounds = plan_discussion(args)
        with self._factory() as session:
            self._start_runs(session, ctx, None)
            if session.scalar(select(Discussion.id).where(
                Discussion.run_id == ctx.run_id, Discussion.status == "running"
            )):
                raise ToolError("another discussion is going on in this turn; wait for it")
            conversation = session.get_one(Conversation, ctx.cid)
            own = settings_of(session, conversation)
            mode, approval = conversation.permission_mode, own.spawn_approval
            max_depth, max_agents = own.spawn_max_depth, own.spawn_max_agents
            budget = own.discussion_budget
            states = dict(session.execute(
                select(Agent.id, Agent.status).where(Agent.run_id == ctx.run_id)).all())
            opened = session.scalar(
                select(func.count()).select_from(Agent).where(
                    Agent.run_id == ctx.run_id, Agent.depth > 0, Agent.status != "rejected",
                    Agent.id.not_in(self._in_recipe),
                )
            ) or 0
            recipe = self._in_a_recipe(ctx)
            named = self._names_past(session, ctx)
            teams = self._door(session, ctx)
            # (Those it may invite now: as spawn_agent's list, slice 62.)
            role_names = ", ".join(
                shown_name(r.name) for r in agent_roles(session) if not closed(r, teams, named))
            here = {
                c.name.casefold(): c for c in self._ctxs.values() if c.run_id == ctx.run_id
            }
            # Every invitation is checked before anything is opened or written down.
            plans: list[tuple] = []
            for name in invited:
                if name.casefold() == ctx.name.casefold():
                    raise ToolError("leave yourself out of `with`: you take part yourself")
                known = here.get(name.casefold())
                if known is not None:
                    state = self._answering.get(known.agent_id, states.get(known.agent_id))
                    if state not in ("completed", "failed", "waiting"):
                        # K-oda-takim: told once it waits (`_set_agent`): a coordinator at work
                        # waits for its team's agents before long.
                        self._discuss_later.setdefault(known.agent_id, set()).add(ctx.agent_id)
                        raise ToolError(
                            f"{known.name} cannot join now: only an agent that has finished "
                            "or is waiting can. You are told when it is waiting."
                        )
                    plans.append((known, None))
                    continue
                role = find_agent_role(session, name)
                if role is None:
                    if self._a_lead(session, ctx.cid, name):
                        raise ToolError(f"{name} is not at work yet: {LEADS_LATER}")
                    agents = ", ".join(c.name for c in here.values() if c is not ctx)
                    raise ToolError(
                        f"{name} is neither an agent of this turn nor a role. "
                        f"Agents: {agents or 'none yet'}. Roles: {role_names}."
                    )
                if ctx.run_id in self._answered:  # (B-376: none opened after the last answer)
                    raise ToolError(TURN_ANSWERED)
                # The same door as spawn_agent's and a room member's (slice 62).
                shut = closed(role, teams, named) or self._room_refused(session, ctx, role.name)
                if shut:
                    raise ToolError(f"{shut}. Roles: {role_names}.")
                new = sum(1 for _known, spec in plans if spec is not None)
                if self._level(ctx) + 1 > max_depth:
                    raise ToolError(
                        f"depth limit reached: no {role.name} can be opened below you. "
                        "Invite agents that already exist."
                    )
                # (In a recipe, what its step draws: slice 84e.)
                step = self._recipe_count(session, ctx, role, max_agents)
                if step is not None and step[0] + new >= step[1]:
                    raise ToolError(step[2])
                if step is None and opened + new >= max_agents:
                    raise ToolError(
                        f"limit of {max_agents} sub-agents per turn reached: no {role.name} "
                        "can be opened. Invite agents that already exist."
                    )
                tools = effective_tools(role.tools, self._caps(ctx))
                # A member opened here is an agent opened below the lead like any other.
                refused = self._nobody_to_ask(
                    ctx, "agent", f"open a {role.name} for a discussion", opening=new + 1)
                if refused:
                    raise _NobodyToAsk(refused)
                if refused is None and (approval == "always" or (
                    approval == "auto" and mode == "ask" and can_change_things(tools)
                )):
                    raise ToolError(
                        f"opening a {role.name} needs the user's approval: open it with "
                        "spawn_agent first, then invite it by its name"
                    )
                # shortcut: no `step` here (B-301's next provider): a recipe's discussion member
                # on a provider it cannot be a step on is refused below; pass it if that is seen.
                backlog_turn = ctx.run_id in self._backlog_turns
                would = would_run(session, role, conversation,
                                  unattended=refused is not None or backlog_turn, tools=tools)
                provider, model_name = would.provider, would.model_id
                # PAID_SWITCH: a move onto a provider paid per token is the user's word - on
                # spawn_agent's card, as a member needing approval is opened (above).
                if paid := self._paid_for(session, ctx, role, conversation, provider, tools):
                    said = self._paid_word.get((ctx.run_id, provider.id))
                    if said is False:
                        raise ToolError(PAID_NO.format(to=shown_name(provider.name)))
                    if refused is not None:
                        raise _NobodyToAsk(PAID_UNATTENDED.format(to=shown_name(provider.name)))
                    if said is None and approval != "never":
                        raise ToolError(f"opening a {role.name} needs the user's word ({paid}): "
                                        "open it with spawn_agent first, then invite it by its "
                                        "name")
                if refused is not None and self._cannot_be_held(None, provider):
                    raise _NobodyToAsk(UNATTENDED_NOT_THIS.format(provider=provider.name))
                if backlog_turn and self._cannot_be_held(None, provider):
                    raise ToolError(BACKLOG_NOT_THIS.format(provider=provider.name))
                try:
                    allowed(provider, model_name)
                except NotListed as exc:
                    raise ToolError(f"no {role.name} can be opened: {exc.to_agent}") from None
                if would.refused is not None:  # (B-385: a model closed to agents)
                    raise ToolError(would.refused.to_agent)
                if over := past_its_limit(session, provider):  # (81c, as for any sub-agent)
                    raise ToolError(over)
                if recipe and only_in_project(self.providers.client(provider, model_name), tools):
                    # (As `_propose`: gone on with later, it would write in the project itself.)
                    raise ToolError(ONLY_IN_THE_PROJECT.format(provider=shown_name(provider.name)))
                if refused is not None and self._cannot_be_held(
                    self.providers.client(provider, model_name)
                ):
                    raise _NobodyToAsk(UNATTENDED_NOT_THIS.format(provider=provider.name))
                plans.append((None, (
                    role, tools, provider.name,
                    self.providers.client(provider, model_name), provider.id, model_name,
                )))

            between = self._between(
                session, ctx, [spec[0].name for _known, spec in plans if spec is not None],
                [ctx.agent_id, *(known.agent_id for known, _spec in plans if known is not None)])
            if between and not self._leads_teams(session, ctx):
                raise ToolError(rooms.NOT_BETWEEN.format(teams=", ".join(between)))
        if any(spec is not None for _known, spec in plans):
            await self._recipe_copy_ready(ctx)
        members: list[tuple[Ctx, bool]] = []
        for known, spec in plans:
            if known is not None:
                members.append((known, False))
                continue
            role, tools, provider_name, model, provider_id, model_name = spec
            new_ctx = self._open_agent(
                ctx.run_id, ctx.cid, ctx.root, ctx.agent_id, role.name, tools, topic,
                ctx.depth + 1, status="waiting", instructions=role.instructions,
                parent_role=ctx.role, provider_name=provider_name, model=model,
                model_name=model_name, provider_id=provider_id,
                # (In a recipe: where a card of its step is put.)
                call_id=call_id if recipe else None,
            )
            self._set_agent(ctx.cid, new_ctx.agent_id, started_at=now())
            self._in_run(ctx, new_ctx, role)
            members.append((new_ctx, True))
        members.append((ctx, False))

        with self._factory() as session:
            talk = Discussion(
                run_id=ctx.run_id, agent_id=ctx.agent_id, tool_call_id=call_id, topic=topic,
                max_rounds=rounds,
            )
            session.add(talk)
            session.flush()
            session.add_all([
                DiscussionMember(
                    discussion_id=talk.id, agent_id=member.agent_id, position=position,
                    opened_here=new,
                )
                for position, (member, new) in enumerate(members)
            ])
            session.commit()
            talk_id, payload = talk.id, discussion_out(session, talk)
        self.bus.emit(ctx.cid, ctx.run_id, "discussion.created", payload)

        ending = self._ending[talk_id] = asyncio.Event()
        self._spent_in[talk_id] = 0
        left: dict[str, str] = {}  # agent id -> why it is out
        last_word: dict[str, str] = {}
        outcome = "round_limit"

        def over() -> bool:
            """Whether the speeches so far reported more than the budget: looked at
            between speeches, so the one that went over it is on record whole."""
            return budget is not None and self._spent_in[talk_id] > budget

        try:
            async with self._handing_over(ctx):
                for number in range(1, rounds + 1):
                    self._user_spoke[talk_id] = False
                    self._set_discussion(ctx.cid, talk_id, round=number)
                    passes: list[bool] = []
                    for member, _new in members:
                        if ending.is_set() or over() or len(members) - len(left) < 2:
                            break
                        if member.agent_id in left:
                            continue
                        said = await self._speak(member, talk_id, ending)
                        if said is None:
                            break  # the user ended it in the middle of this speech
                        ok, text_ = said
                        if not ok:
                            left[member.agent_id] = text_
                            with self._factory() as session:
                                row = session.scalar(select(DiscussionMember).where(
                                    DiscussionMember.discussion_id == talk_id,
                                    DiscussionMember.agent_id == member.agent_id,
                                ))
                                if row:
                                    row.status = "left"
                                    session.commit()
                            self._post(ctx.cid, ctx.run_id, talk_id, member.agent_id, number,
                                       text_, kind="left")
                            self._set_discussion(ctx.cid, talk_id)
                            continue
                        passed = is_pass(text_)
                        passes.append(passed)
                        text_ = fit(text_)
                        last_word[member.agent_id] = text_
                        self._post(ctx.cid, ctx.run_id, talk_id, member.agent_id, number,
                                   text_ or "(said nothing)", passed=passed)
                    if ending.is_set():
                        outcome = "ended_by_user"
                        break
                    if len(members) - len(left) < 2:
                        outcome = "too_few"
                        break
                    if over():
                        outcome = "budget"  # nobody else speaks, and no round begins
                        break
                    if passes and all(passes) and not self._user_spoke[talk_id]:
                        outcome = "agreed"
                        break
                # Over before the one who opened it takes its place back: from here on
                # nothing more can be said in it, and ending it has nothing left to end.
                self._ending.pop(talk_id, None)
                self._set_discussion(
                    ctx.cid, talk_id, status="ended", outcome=outcome, ended_at=now()
                )
        except BaseException as exc:
            # (A raise - Stop too - leaves none opened for it "waiting" for good.)
            for member, new in members:
                if new:
                    with contextlib.suppress(Exception):
                        self._set_agent(ctx.cid, member.agent_id, ended_at=now(), status=(
                            "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed"))
            raise
        finally:
            self._ending.pop(talk_id, None)
            self._user_spoke.pop(talk_id, None)
            self._spent_in.pop(talk_id, None)

        _talk, _members, said_all = self._posts(talk_id)
        kept = memory(topic, outcome, said_all)
        for member, new in members:
            if member is ctx:
                continue  # it gets the same as the result of its call
            self._send(ctx, member, kept, delivered=True)
            if new and member.agent_id in left:
                # Opened for the discussion and dropped out of it: that is not "done".
                self._set_agent(
                    ctx.cid, member.agent_id, status="failed", ended_at=now(),
                    error=left[member.agent_id],
                    report=last_word.get(member.agent_id) or None,
                )
            elif new:
                # Opened for the discussion: what it said last is all it has to show.
                self._set_agent(
                    ctx.cid, member.agent_id, status="completed", ended_at=now(),
                    report=last_word.get(member.agent_id) or None,
                )
        told = ""
        for member, new in members if recipe else ():
            if new:  # (Its step's places, as a room's members end theirs.)
                told = await self._after_step(ctx, member, member.agent_id not in left, self._found(
                    member, last_word.get(member.agent_id))) or told
        return "succeeded", f"The discussion ended: {WHY[outcome]}\n\n{said_all}{told}"

    async def _speak(
        self: "AgentRunner", member: Ctx, discussion_id: str, ending: asyncio.Event
    ) -> tuple[bool, str] | None:
        """One member's turn to speak. Returns (True, what it said), (False, why it
        dropped out), or None when the user ended the discussion in mid-speech."""
        # The one who opened it from inside a turn it was given is that turn: its lock
        # is its sender's already. Anyone else speaks only when no other turn has it -
        # and the user ending the discussion is not kept waiting for that.
        lock = None if member.in_turn else self._turn_of(member.agent_id)
        if lock is not None and not await self._unless_ended(lock, ending):
            return None
        try:
            return await self._speech(member, discussion_id, ending)
        finally:
            if lock is not None:
                lock.release()

    @staticmethod
    async def _unless_ended(lock: asyncio.Lock, ending: asyncio.Event) -> bool:
        """Take the lock, unless the discussion is ended first; whether it was taken."""
        taking = asyncio.ensure_future(lock.acquire())
        stop = asyncio.ensure_future(ending.wait())
        try:
            await asyncio.wait({taking, stop}, return_when=asyncio.FIRST_COMPLETED)
        except BaseException:
            taking.cancel()
            if taking.done() and not taking.cancelled() and taking.exception() is None:
                lock.release()
            raise
        finally:
            stop.cancel()
        if taking.done() and not taking.cancelled():
            return True
        taking.cancel()
        await asyncio.gather(taking, return_exceptions=True)
        if not taking.cancelled() and taking.exception() is None:
            lock.release()  # it came through just as the discussion was ended
        return False

    async def _speech(
        self: "AgentRunner", member: Ctx, discussion_id: str, ending: asyncio.Event
    ) -> tuple[bool, str] | None:
        if True:
            with self._factory() as session:
                previous = session.get_one(Agent, member.agent_id).status
            if previous not in ("completed", "failed", "waiting"):
                # It was invited while it waited, and has taken its own work up again:
                # it cannot be held to reading now, and one agent does not run twice.
                return False, "it went back to its own work"
            model = member.model
            if getattr(model, "native", False):
                # It cannot be held to reading with its own tools on: it speaks step by step.
                model = cast(CodexNativeClient, model).talker()
            turn = replace(
                member, answering=True, in_turn=True, own_calls=set(), speech_ids=[],
                discussion=discussion_id, max_steps=SPEECH_STEPS, model=model,
                tools=tuple(t for t in member.tools if t in ANSWER_TOOLS),
            )
            self._answering[member.agent_id] = previous
            cut = False

            async def speak() -> tuple[str, str | None]:
                # The wait for a place is part of the speech: the user ending the
                # discussion ends that too, and is not kept waiting for a place.
                async with self._working(turn):
                    self._set_agent(member.cid, member.agent_id, status="running")
                    return await self._run_child(turn)

            try:
                work = asyncio.ensure_future(speak())
                stop = asyncio.ensure_future(ending.wait())
                try:
                    await asyncio.wait({work, stop}, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    stop.cancel()
                    if not work.done():
                        cut = True
                        work.cancel()
                        await asyncio.gather(work, return_exceptions=True)
            finally:
                # It only spoke: it is what it was, also when it was cut off.
                self._answering.pop(member.agent_id, None)
                self._set_agent(member.cid, member.agent_id, status=previous)
            if cut:
                self._interrupt_open_calls(
                    member.run_id, member.cid, member.agent_id, only=turn.own_calls
                )
                return None
            status, error = work.result()
            with self._factory() as session:
                words = session.scalars(
                    select(Message.content)
                    .where(Message.id.in_(turn.speech_ids or []), Message.content != "")
                    .order_by(literal_column("messages.rowid").desc())
                ).first()
        if status != "completed":
            if error == "step_limit":
                return False, "it did not get to the point"
            return False, self._told(turn.agent_id, error)
        return True, (words or "").strip()
