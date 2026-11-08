"""A room the user opens (`app.room`): its members and their work, following and pausing, its
items and posts, its clock and minutes, how it ends and what is taken from it; and the role
and knowledge tools beside it (`_create_role`, `_lookup`, `_learn`) - `RoomsMixin`.
"""

import asyncio
import contextlib
import re
from collections.abc import Callable
from dataclasses import replace
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from pydantic import ValidationError
from sqlalchemy import func, literal_column, or_, select, text
from sqlalchemy.orm import Session

from app import board, injection, knowledge, knows, observer, team_requests, web
from app import memory as kept
from app import room as rooms
from app.agent.cards import _answer, _places, lead_pick
from app.agent.ctx import Ctx, _Member, _NobodyToAsk, _Room
from app.agent.words import AGENT_TERMINAL, LEADS_LATER, MINUTE
from app.api.usage import over_limit, over_month, past_its_limit
from app.claims import place
from app.db.models import (
    Agent,
    ChannelMessage,
    Conversation,
    ConversationTeam,
    Message,
    ProjectKnowledge,
    Provider,
    Question,
    Role,
    Room,
    RoomItem,
    RoomMember,
    RoomPost,
    Run,
    Team,
    now,
    project_of,
    settings_of,
)
from app.model_client import ModelUnavailable, OwnStop
from app.providers import NotListed, allowed, ask_once, mode_of
from app.roles import (
    LEARN,
    LOOKUP,
    agent_roles,
    chat_teams,
    check_name,
    check_tools,
    closed,
    expert_tools,
    find_role,
    is_team_lead,
    landing_kind,
)
from app.schemas import Knowledge
from app.serialize import (
    channel_message_out,
    message_out,
    role_out,
    room_item_out,
    room_out,
    room_post_out,
    room_spent,
)
from app.team import quoted
from app.tools import ToolError

if TYPE_CHECKING:
    from app.agent import AgentRunner

# The line, as the lead writes it: plain or in bold.
SAY_LINE = re.compile(r"^\*{0,2}Say:\*{0,2}\s*(.+)$")

# R179: what the chat is told once, a Codex Lead in native mode at a chat with a recipe. R188: it
# may open the team's roles over MCP, and then the recipe runs - only it often does not.
CODEX_NATIVE_NO_RECIPE = ("Codex in native mode often does the work itself instead of running "
                          "this chat's teams and recipes — for them to run every time, switch its "
                          "'How it runs' to step on the Models page.")

ROLE_REJECTED = (
    "rejected: the user declined to create the role {name}. This is their decision, not a "
    "tool error: do not create it again under another name. Use an existing role, or stop "
    "and ask what they would like instead."
)


def _taken(session: Session, role: Role) -> str:
    """What an agent that would make a role of a name already taken is told."""
    if is_team_lead(session, role):  # (slice 63a: no agent is opened in one yet)
        return (f"there is already a role named {role.name}: a team's coordinator - "
                f"{LEADS_LATER}. Make no role for it")
    return f"there is already a role named {role.name}; open a sub-agent in it with spawn_agent"


class RoomsMixin:
    # --- a room the user opens (`app.room`) --------------------------------------------

    def _member_of(self: "AgentRunner", ctx: Ctx) -> tuple[_Room, _Member] | None:
        """The room this agent works in, with the member it is - or works for: a member's
        own sub-agent changes files under the member's items. None for everybody else,
        and for a member once its room is done with."""
        room = self._rooms.get(ctx.run_id)
        if room is None:
            return None
        for agent_id in (ctx.agent_id, *self._line(ctx)):
            if agent_id in room.members:
                return room, room.members[agent_id]
        return None

    async def _while_paused(self: "AgentRunner", ctx: Ctx) -> None:
        """29c: a member of a paused room - or an agent working for one - waits here, before a
        step or a tool, with its place free, until the user resumes the room or it ends."""
        found = self._member_of(ctx)
        # K-oda-lead: and the agent that follows the room it opened - it posts nothing either.
        room = found[0] if found else None if ctx.answering else self._following.get(ctx.agent_id)
        if room is None or room.go.is_set():
            return
        async with self._handing_over(ctx):
            await room.go.wait()

    def _set_room(self: "AgentRunner", room: _Room, **fields) -> None:
        """Bring a room's record up to date, and tell the page how it stands now."""
        with self._factory() as session:
            row = session.get_one(Room, room.id)
            for key, value in fields.items():
                setattr(row, key, value)
            session.commit()
            payload = room_out(session, row)
        self.bus.emit(room.lead.cid, room.lead.run_id, "room.updated", payload)

    def _set_member(self: "AgentRunner", room: _Room, member: _Member, state: str) -> None:
        member.state = state
        with self._factory() as session:
            session.get_one(RoomMember, member.row).status = state
            session.commit()
        self._set_room(room)

    async def _hold_room(self: "AgentRunner", lead: Ctx) -> None:
        """The room the user opened for this turn, if they opened one, from its opening
        until its copy is in the project: the turn's lead waits for all of it.

        Its members are opened as the lead's sub-agents. They share the work out first,
        in the order the user named them, a step each (`_share`); then all of them work
        at the same time (`_work`), each holding a place only while it takes a step or
        runs a tool, until the room ends (`_end_room`). Then what they changed in the
        room's one copy is taken into the project as any working copy's is, and the lead
        is given the room's record (`_close_room`).

        Stop ends the room as "cancelled" and takes nothing of it (the turn's end throws
        its copy away); so does a failure to open it, which fails the turn."""
        with self._factory() as session:
            room_id = session.scalar(select(Room.id).where(
                Room.run_id == lead.run_id, Room.status == "sharing"))
        if room_id is None:
            return
        room = self._rooms[lead.run_id] = _Room(room_id, lead)
        self._set_agent(lead.cid, lead.agent_id, status="waiting")
        # K-oda-izle: its life a task of its own, as an opener's room's is - until the user lets
        # the Lead follow it (`follow_room`): from there the Lead does, in steps of its own.
        life = room.life = asyncio.ensure_future(self._room_work(room))
        try:
            while not life.done() and not room.reads:  # (on and off again: it waits on)
                switched = asyncio.ensure_future(room.follow.wait())
                try:
                    await asyncio.wait([life, switched], return_when=asyncio.FIRST_COMPLETED)
                finally:
                    switched.cancel()
        except BaseException:
            life.cancel()
            await asyncio.shield(asyncio.gather(life, return_exceptions=True))
            raise
        if life.done():
            life.result()  # (a failure to open it fails the turn)
            await self._close_room(room)
        else:
            self._following[lead.agent_id] = room
            with self._factory() as session:
                goal = session.scalar(select(Message.id).where(
                    Message.run_id == lead.run_id, Message.role == "user"))
            # (After the turn's message, its goal - where it stays, step after step. What is said
            # in the room it is given as an opener is: as wait_for_room's answer.)
            self._nudges.setdefault(lead.agent_id, []).append((goal, rooms.LET_FOLLOW))
        self._set_agent(lead.cid, lead.agent_id, status="running")

    def _native_no_recipe(self: "AgentRunner", ctx: Ctx) -> None:
        """R179 (live): a Codex Lead in native mode never started its chat's recipe - no team
        strip, no sub-agent, it wrote the code itself; in step mode it does. Said once a chat, as
        a Lead's turn starts (after `_by_how_hard`, which may move it to another model) - at a
        chat with a team, its recipe or none: either needs spawn_agent, which it never called."""
        if ctx.depth or not getattr(ctx.model, "native", False):
            return
        with self._factory() as session:
            provider = session.get(Provider, ctx.provider_id or "")
            if provider is None or provider.kind != "codex_cli" or not self._rows(
                    session, ctx.cid) or session.scalar(
                    select(Message.id).where(
                        Message.conversation_id == ctx.cid, Message.role == "koloni",
                        Message.content == CODEX_NATIVE_NO_RECIPE).limit(1)):
                return
        self._koloni_line(ctx.cid, ctx.run_id, CODEX_NATIVE_NO_RECIPE)

    async def _lead_on_session(self: "AgentRunner", ctx: Ctx) -> None:
        """K-oda-izle: a Lead its message moved onto a CLI's session (`_by_how_hard`) - whose tools
        are given once, as it starts - follows the user's room no further: it waits for the room's
        end as it did before it was let follow it, and the room is closed as then."""
        room = self._following.get(ctx.agent_id)
        if room is None or not getattr(ctx.model, "session", False):
            return
        self._follow_no_further(room)
        life = cast(asyncio.Task, room.life)
        self._set_agent(ctx.cid, ctx.agent_id, status="waiting")
        await asyncio.wait([life])
        del self._following[ctx.agent_id]
        life.result()
        await self._close_room(room)
        self._set_agent(ctx.cid, ctx.agent_id, status="running")

    def _follow_no_further(self: "AgentRunner", room: _Room) -> None:
        """Its opener - or the Lead the user let follow it - reads the room no more, whatever is
        said or switched: its members are told so, and count on it no more (S3)."""
        room.read_out, room.reads = True, False
        self._settle_room(room)
        self._set_room(room, lead_follows="stopped")  # (K-oda-izle: shown by the user's switch)

    async def _run_room(self: "AgentRunner", room: _Room) -> str:
        """A room from its opening until its copy is in the project; returns the record
        its opener is given (`_close_room`). The user's room opens its members here; an
        agent's has them already (`_open_room`)."""
        await self._room_work(room)
        return await self._close_room(room)

    async def _room_work(self: "AgentRunner", room: _Room) -> None:
        """A room's work, from its opening until it ends (`_end_room`); a room its opener
        follows runs this as a task of its own, and the opener closes it (`_follow`)."""
        try:
            if not room.members:
                self._open_members(room)
            self._room_minutes(room.lead.run_id)  # its clock starts
            for member in list(room.members.values()):
                if room.outcome is None and member.state == "in":
                    await self._in_room(room, self._share, [member])
            if room.outcome is None:
                room.status = "working"
                self._set_room(room, status="working")
                await self._in_room(room, self._work, [
                    member for member in room.members.values() if member.state == "in"])
        except BaseException:
            self._room_cut(room)
            raise

    def _room_cut(self: "AgentRunner", room: _Room) -> None:
        """A room came to no end of its own: Stop, the app going down, or a failure."""
        self._stop_clock(room)
        self._set_room(
            room, status="interrupted" if self._closing else "cancelled", paused=False,
            ended_at=now(), seconds=room.seconds, clock_since=None, lead_follows="off",
        )

    def _open_members(self: "AgentRunner", room: _Room) -> None:
        """Open a room's members as the lead's sub-agents, in the order the user named
        them: one level below it, with their role's tools (never more than the lead's)
        and the room's, on the model `rooms.member_model` gives. The user asked for them
        by name, so nobody is asked again; the conversation's limit on sub-agents in a
        turn holds. OwnStop where one of them cannot be opened: no room is held with
        fewer members than the user named (what could be checked was, as it was asked
        for - this is for what changed in the moment since)."""
        lead = room.lead
        with self._factory() as session:
            conversation = session.get_one(Conversation, lead.cid)
            goal = session.get_one(Room, room.id).goal
            rows = session.scalars(
                select(RoomMember).where(RoomMember.room_id == room.id)
                .order_by(RoomMember.position)
            ).all()
            room.between = tuple(self._between(session, lead, [row.role for row in rows], []))
            plans: list[tuple] = []
            try:
                most = settings_of(session, conversation).spawn_max_agents
                if len(rows) > most:
                    raise ValueError(
                        f"this conversation lets a turn open {most} sub-agent(s) at most")
                for row in rows:
                    named = session.get(Provider, row.provider_id) if row.provider_id else None
                    if row.provider_id and named is None:
                        raise ValueError(f"the provider named for the {row.role} is gone")
                    role, tools, provider, model_name, moved = rooms.member_model(
                        session, conversation, row.role, named.name if named else None,
                        row.model_id, lead.tools, by_user=True,
                    )
                    plans.append((
                        row.id, role.name, tools, role.instructions, provider.name,
                        provider.id, model_name, self.providers.client(provider, model_name),
                        moved,
                    ))
            except ValueError as exc:
                raise OwnStop(f"the room could not be opened: {exc}") from None
        for (row_id, role, tools, instructions, provider, provider_id, model_name, model,
             moved) in plans:
            ctx = self._open_agent(
                lead.run_id, lead.cid, lead.root, lead.agent_id, role,
                [*rooms.talk_only(tools, room.between), *rooms.TOOLS],
                goal, lead.depth + 1, status="waiting", instructions=instructions,
                parent_role="user", provider_name=provider, model=model,
                model_name=model_name, provider_id=provider_id, chosen_why=moved,
            )
            if room.between:
                ctx = self._talk_only(room, ctx)
                self._set_agent(ctx.cid, ctx.agent_id, tools=list(ctx.tools))
            room.members[ctx.agent_id] = _Member(ctx, row_id)
            with self._factory() as session:
                session.get_one(RoomMember, row_id).agent_id = ctx.agent_id
                session.commit()
        self._set_room(room)

    async def _open_room(self: "AgentRunner", ctx: Ctx, call_id: str,
                         args: dict) -> tuple[str, str]:
        """An agent opens a room (`open_room`), and waits for it: the room's record is the
        call's answer. Its members are opened as sub-agents are, each under every limit
        and rule `_propose` holds a sub-agent to; where the user is asked for one of them
        they are asked for all, and one turned down leaves the room unopened. What the
        room may spend is the call's, never more than the conversation lets a room
        spend.

        In a recipe's step (slice 84e) its members are the step's agents - by spawn_agent's
        door, as many as the step draws, all of a Room step's roles - and the room works in
        the recipe's copy: nothing of it goes into the project but by the user's Take in
        (`_close_room`). The step goes on as the room is over (`_after_step`)."""
        goal, wanted, asked = rooms.plan_room(args)
        if self._member_of(ctx) is not None:
            raise ToolError(rooms.NO_ROOM_IN_A_ROOM)
        if not self._watched(ctx.run_id):
            raise ToolError(rooms.UNWATCHED)
        with self._factory() as session:
            self._start_runs(session, ctx, None)
            recipe = self._in_a_recipe(ctx)
            self._open_room_refused(session, ctx, recipe)
            at = self._room_step(session, ctx)

            def names(roles: list[str]) -> list[str]:
                return sorted(" ".join(one.split()).casefold() for one in roles)

            if at and names(wanted) != names(at[1]):
                raise ToolError(f"the {at[0]} step is a room of {', '.join(at[1])}: open it "
                                "with all of them, each once")
            conversation = session.get_one(Conversation, ctx.cid)
            if not at:  # (R178 review: a room of six past the turn's allowance is said up front)
                self._open_room_allowance(session, ctx, conversation, wanted)
            door, named = self._door(session, ctx), self._names_past(session, ctx)
            plans, leads = self._open_room_plans(session, ctx, conversation, at, wanted, named)
            between = self._open_room_between(session, ctx, at, plans, leads, door, named)
            limits = self._open_room_limits(session, conversation, asked)
        self._room_asked.add(ctx.run_id)
        try:
            await self._recipe_copy_ready(ctx)
            members, asks = self._open_room_members(ctx, call_id, goal, plans, leads)
            # One room, one word: a member that changes nothing still works beside the
            # ones that do, in their copy.
            ids = [child.agent_id for child, _role in members]
            try:
                turned_down = await self._users_no(ctx, ids) if asks else None
            except BaseException:
                # B-412 (live, Ask): a call that ended while its cards waited (a CLI that gave
                # up on it) left its members in the step's places - the next open_room refused.
                self._unopened(ctx, [child for child, _role in members])
                raise
            if turned_down is not None:
                self._unopened(ctx, [child for child, _role in members])
                await self._settle(ctx)
                raise ToolError(rooms.TURNED_DOWN.format(role=turned_down))
            with self._factory() as session:
                row = Room(
                    run_id=ctx.run_id, goal=goal, agent_id=ctx.agent_id,
                    max_posts=limits["posts"], max_tokens=limits["tokens"],
                    max_minutes=limits["minutes"],
                )
                session.add(row)
                session.commit()
                room = self._rooms[ctx.run_id] = _Room(row.id, ctx, between=tuple(between))
                payload = room_out(session, row)
        finally:
            self._room_asked.discard(ctx.run_id)
        self.bus.emit(ctx.cid, ctx.run_id, "room.created", payload)
        if at:  # (B-120: the room its Room step opened, which its Take in is on record as)
            def opened(row: ConversationTeam, team: Team, lead: Role | None,
                       state: dict) -> bool:
                if ids[0] not in state["agents"]:
                    return False
                state["room"] = room.id
                return True

            self._change_rows(ctx.cid, ctx.run_id, opened)
        for child, role_name in members:
            self._add_member(room, child, role_name)
        return await self._open_room_follow(ctx, room, args)

    def _open_room_refused(self: "AgentRunner", session, ctx: Ctx, recipe) -> None:
        """`_open_room`: why no room may be opened in this turn now, raised; else nothing."""
        if ctx.run_id in self._room_asked or ctx.run_id in self._rooms:
            raise ToolError(rooms.ONE_AT_A_TIME if recipe else rooms.ONE_A_TURN)
        if recipe and self._recipes_over(ctx):
            # (K-r146 lets a follow-up agent in after it, not a room: the room's copy would
            # be the recipe's, held till the turn ends.)
            raise ToolError("no room after this turn's recipe has ended: its copy is held "
                            "till the turn ends - open the agents you need with spawn_agent")
        if not recipe and session.scalar(
            select(Room.id).where(Room.run_id == ctx.run_id).limit(1)
        ):
            raise ToolError(rooms.ONE_A_TURN)

    def _open_room_allowance(self: "AgentRunner", session, ctx: Ctx, conversation,
                             wanted) -> None:
        """`_open_room`: a room of more members than the turn may still open, raised."""
        left = settings_of(session, conversation).spawn_max_agents - (session.scalar(
            select(func.count()).select_from(Agent).where(
                Agent.run_id == ctx.run_id, Agent.depth > 0, Agent.status != "rejected",
                Agent.id.not_in(self._in_recipe))) or 0)
        if len(wanted) > left:
            raise ToolError(f"this turn may open {max(left, 0)} more agents; the room "
                            f"needs {len(wanted)}. Open a smaller room, or do the rest "
                            "yourself")

    def _open_room_plans(self: "AgentRunner", session, ctx: Ctx, conversation, at, wanted,
                         named) -> tuple[list, set]:
        """`_open_room`: each wanted member's role and model, and the teams' coordinators
        among them (their ids)."""
        plans, leads = [], set()
        for name in wanted:
            # K-oda-takim: the Orchestrator names the teams' coordinators, as spawn_agent does.
            lead = None if at else self._team_lead(session, ctx, name)
            try:
                role, _tools, provider, model_name, moved = rooms.member_model(
                    session, conversation, name, None, None, ctx.tools, named_roles=named,
                    lead=lead)
            except (ValueError, OwnStop) as exc:
                raise ToolError(str(exc)) from None
            if lead is not None:
                # (Its team waits for the room: not one it runs at the same time.)
                if busy := session.scalar(select(Agent.name).where(
                        Agent.run_id == ctx.run_id, Agent.role_name == lead.name,
                        Agent.status.not_in(AGENT_TERMINAL)).limit(1)):
                    raise ToolError(rooms.COORDINATOR_AT_WORK.format(lead=busy))
                leads.add(lead.id)
            plans.append((role, provider, model_name,
                          self.providers.client(provider, model_name), moved))
        return plans, leads

    def _open_room_between(self: "AgentRunner", session, ctx: Ctx, at, plans, leads, door,
                           named) -> list:
        """`_open_room`: the teams a room is between, after each member is held to the door
        it opens by (raised where one may not be)."""
        # (A recipe's Room step is its row's: within its team.)
        between = [] if at else self._between(
            session, ctx, [role.name for role, *_rest in plans], [ctx.agent_id])
        # B-141: the Lead names a room between teams' members itself - it only talks: not
        # "hand it to its lead" for each.
        if between and not ctx.depth:
            door = door._replace(step=None)
        for role, *_rest in plans:
            # (a recipe's step: its roles only)
            if role.id not in leads and (shut := closed(role, door, named)):
                raise ToolError(self._to_its_lead(session, ctx, role) or shut)
        if leads and not between:  # (only a room between teams keeps it to talking)
            raise ToolError(rooms.COORDINATORS_MEET)
        if between and not self._leads_teams(session, ctx):
            raise ToolError(rooms.NOT_BETWEEN.format(teams=", ".join(between)))
        return between

    def _open_room_limits(self: "AgentRunner", session, conversation, asked) -> dict:
        """`_open_room`: what the room may spend - what was asked, never past the settings."""
        limits = {}
        for key in ("posts", "tokens", "minutes"):
            most = getattr(settings_of(session, conversation), f"room_{key}")
            limits[key] = most if key not in asked else (
                asked[key] if most is None else min(asked[key], most))
        return limits

    def _open_room_members(self: "AgentRunner", ctx: Ctx, call_id: str, goal, plans,
                           leads) -> tuple[list[tuple[Ctx, str]], bool]:
        """`_open_room`: each member proposed as a sub-agent is; and whether the user is asked.
        One that fails leaves none of them opened."""
        members: list[tuple[Ctx, str]] = []
        asks = False
        try:
            for role, provider, model_name, model, moved in plans:
                child, its = self._propose(
                    ctx, call_id, role, goal, provider, model_name, model, False, None,
                    why=moved or "", tiered=moved is not None)
                members.append((child, role.name))
                if role.id not in leads:  # (a coordinator here speaks for its team: no run)
                    self._in_run(ctx, child, role)
                asks = asks or its
        except BaseException:
            self._unopened(ctx, [child for child, _role in members])
            raise
        return members, asks

    async def _open_room_follow(self: "AgentRunner", ctx: Ctx, room,
                                args: dict) -> tuple[str, str]:
        """`_open_room`, once the room is open: its opener follows it, or waits for its record."""
        # K-oda-lead: it follows the room unless it asked not to - or is a CLI's session, whose
        # tools were given once, before it opened any room.
        # shortcut: a CLI session that opens a room waits for its record, as before; offer it the
        # follow tools from the start if one is seen to need them.
        if args.get("follow", True) in (False, "false") or getattr(ctx.model, "session", False):
            async with self._handing_over(ctx):
                said = await self._room_life(ctx, room)
            return "succeeded", await self._after_room(ctx, room, said)
        room.life = asyncio.ensure_future(self._room_work(room))
        self._following[ctx.agent_id] = room
        room.reads = True
        # R178 (the user): the room shows that its opener watches it - posts, invites, ends.
        self._set_room(room, lead_follows="on")
        return "succeeded", await self._follow(ctx, room)

    async def _room_life(self: "AgentRunner", ctx: Ctx, room: _Room) -> str:
        """An agent's room from its opening until its copy is in the project: its record."""
        try:
            return await self._run_room(room)
        finally:
            self._room_returned(ctx, room)

    async def _after_room(self: "AgentRunner", ctx: Ctx, room: _Room, said: str) -> str:
        """What the agent that opened a room is given once it is over: its record - and in a
        recipe's step, where the recipe is now."""
        if not self._in_a_recipe(ctx):
            return said
        # Its members end its step's places: one that left the room failed its part. (What
        # the last one is told is where the recipe is now.)
        # shortcut: Try again on a Room step opens the whole room again, which the places
        # its other members still hold refuse - Skip or Stop is left; let a room be opened
        # for the failed roles alone if that is met.
        told = ""
        for agent_id in room.members:
            with self._factory() as session:
                agent = session.get_one(Agent, agent_id)
                ok, report = agent.status != "failed", agent.report
            child = self._ctxs[agent_id]
            told = await self._after_step(ctx, child, ok, self._found(child, report)) or told
        return said + told

    async def _follow(self: "AgentRunner", ctx: Ctx, room: _Room, to_end: bool = False) -> str:
        """K-oda-lead: the agent that opened a room follows it - waits, holding no place, for
        a post of somebody else's it has not been given, and is given what was said since, as
        `rooms.said` frames it, with how the room stands. Once the room is over (or `to_end`,
        whatever is said), its record instead, the one time: from then on it is at its own work
        again, with its role's tools."""
        def new() -> bool:  # (what wakes it: `_post_room`)
            with self._factory() as session:
                return session.scalar(select(RoomPost.id).where(
                    RoomPost.room_id == room.id, RoomPost.number > room.seen,
                    or_(RoomPost.agent_id.is_(None), RoomPost.agent_id != ctx.agent_id),
                    or_(RoomPost.agent_id.is_(None), RoomPost.type == "question",
                        RoomPost.to_agent_id == ctx.agent_id),
                ).limit(1)) is not None

        life = cast(asyncio.Task, room.life)
        # With few of its steps left it follows no further: it waits for the record, and keeps
        # steps to go on from it. From then on it reads nothing: its members are told so, and
        # count on it no more (S3).
        left = self._steps_left.get(ctx.agent_id)
        to_end = to_end or (left is not None and left <= rooms.FOLLOW_RESERVE)
        if to_end and not room.read_out:
            self._follow_no_further(room)
        # K-oda-izle: the user stopped it following the room they opened - it reads nothing, and
        # waits for the room's end, or to be let follow it again.
        off = not room.reads and not to_end
        # (Its members only wait - for it, nobody else is at work: it is told so, once a time.)
        states = [member.state for member in room.members.values()]
        alone = "in" not in states and "waiting" in states and room.alone_at != room.seen
        if room.outcome is None and not life.done() and not to_end and not off and (
                new() or alone):
            told = self._followed(ctx, room)
            room.alone_at = room.seen if alone else room.alone_at
            return told
        said = None
        async with self._handing_over(ctx):
            if room.outcome is None and not life.done():
                room.heard.clear()
                heard = asyncio.ensure_future((room.follow if off else room.heard).wait())
                try:
                    await asyncio.wait([life] if to_end else [life, heard],
                                       return_when=asyncio.FIRST_COMPLETED)
                finally:
                    heard.cancel()
            if room.outcome is not None or life.done():
                # Over: it closes the room itself, holding no place - as when it only waited:
                # its copy taken in, the user's card on it (S4: never in a step of its own).
                await asyncio.wait([life])
                life.result()  # (a failure of the room's own is its opener's)
                try:
                    said = await self._close_room(room)
                finally:
                    self._room_returned(ctx, room)
        if said is None:  # (stopped meanwhile, it waits on)
            return self._followed(ctx, room) if room.reads else await self._follow(ctx, room)
        self._following.pop(ctx.agent_id, None)
        room.reads = False
        return await self._after_room(ctx, room, said)

    def _room_returned(self: "AgentRunner", ctx: Ctx, room: _Room) -> None:
        """The opener's waits on its room's members are over (`_add_member`)."""
        for agent_id in room.members:  # (and the ones invited since)
            self.claims.returned(ctx.agent_id, agent_id)

    def _followed(self: "AgentRunner", ctx: Ctx, room: _Room) -> str:
        """What the agent following the room it opened is told: the posts since it last looked
        (its own passed over), and how the room stands."""
        with self._factory() as session:
            row = session.get_one(Room, room.id)
            items, questions, names = self._room_lists(session, room, ctx.agent_id)
            posts = session.scalars(select(RoomPost).where(
                RoomPost.room_id == room.id, RoomPost.number > room.seen,
            ).order_by(RoomPost.number)).all()
            spent = room_spent(session, row)
            budget = {"posts": row.max_posts, "tokens": row.max_tokens,
                      "minutes": row.max_minutes}
        room.seen = posts[-1].number if posts else room.seen
        said = [rooms.said(post.number, names.get(post.agent_id or ""), post.type,
                           names.get(post.to_agent_id or ""), post.reply_to, post.text)
                for post in posts if post.agent_id != ctx.agent_id]
        members = [(one.ctx.name, one.state) for one in room.members.values()]
        told = rooms.followed(said, rooms.now(
            room.status, items, members, questions, spent, budget, opener=True))
        return self._noted_posts(ctx, posts, names, told)

    def _noted_posts(self: "AgentRunner", ctx: Ctx, posts, names: dict, told: str) -> str:
        """What its reader is told of a room's posts, after KOLONİ's note where a member's
        reads like orders - the user is warned (93-A4). The user's own words and what KOLONİ
        wrote of one that left are never looked at, as `_hand_posts` looks at none."""
        heard = [(f"a room post by {names.get(post.agent_id, 'a member')}", rules)
                 for post in posts if post.agent_id not in (None, ctx.agent_id)
                 and post.type != "left" and (rules := injection.scan(post.text, "agent"))]
        for where, rules in heard:
            self._warn(ctx, rules, "agent", where)
        return f"{injection.NOTE}\n{told}" if heard else told

    async def _follow_call(
        self: "AgentRunner", ctx: Ctx, call_id: str, room: _Room, name: str, args: dict
    ) -> tuple[str, str]:
        """One of the tools of the agent following the room it opened (`rooms.FOLLOW`). Once
        the room is over only wait_for_room does anything: it gives the record."""
        if name == "wait_for_room":
            return "succeeded", await self._follow(ctx, room)
        if room.outcome is not None:
            raise ToolError(rooms.FOLLOWED_OVER)
        if not room.reads:  # (K-oda-izle: the user stopped it following: it waits as told)
            return "failed", rooms.NOT_FOLLOWED.format(then=await self._follow(ctx, room))
        if name == "post_to_room":
            return await self._say(room, ctx, call_id, args)
        if name == "invite_to_room":
            return "succeeded", await self._invite(room, ctx, call_id, args)
        said = rooms.plan_summary(args)
        if self._end_room(room, "ended_by_opener"):
            self._post_room(room, ctx.agent_id, "ended", said)
        return "succeeded", await self._follow(ctx, room)

    async def _users_no(self: "AgentRunner", ctx: Ctx, asked: list[str]) -> str | None:
        """Ask the user for the proposed sub-agents that are to be a room's members, all
        at once: the name of the first one they turn down, or None when they approved
        every one. Each is on record as their word on it comes: approved, it waits for
        the others.
        shortcut: the Lead does not answer these for the user while they are away
        (K-vekil-karar: one sub-agent, `_see_through`, it does); give them `_lead_may_answer`
        if a night is seen waiting on a room's members."""
        loop = asyncio.get_running_loop()
        word: asyncio.Future[str] = loop.create_future()
        left = set(asked)

        def heard(agent_id: str, decided: asyncio.Future[str]) -> None:
            if decided.cancelled():
                return
            yes = decided.result() == "approve"
            self._paid_heard(agent_id, yes)
            self._set_agent(ctx.cid, agent_id, **(
                {"status": "waiting"} if yes else {"status": "rejected", "ended_at": now()}))
            left.discard(agent_id)
            if not word.done() and (not yes or not left):
                word.set_result("" if yes else self._ctxs[agent_id].name)

        for agent_id in asked:
            decided = self._spawn_decisions[agent_id] = loop.create_future()
            decided.add_done_callback(lambda done, agent_id=agent_id: heard(agent_id, done))
        self._update_run(ctx.run_id, ctx.cid, status="waiting_approval")
        try:
            return await self._users_word(ctx, word, back=False) or None
        finally:
            for agent_id in asked:
                self._spawn_decisions.pop(agent_id, None)
            self._update_run(ctx.run_id, ctx.cid, status="running")

    def _unopened(self: "AgentRunner", ctx: Ctx, children: list[Ctx]) -> None:
        """Sub-agents proposed for a room that is not opened after all: never started, they
        are on record as turned down with it - as `_close_agents` leaves one - and so use up
        none of the turn's sub-agents, nor a place in a recipe's step."""
        with self._factory() as session:
            still = session.scalars(select(Agent.id).where(
                Agent.id.in_([child.agent_id for child in children]),
                Agent.status.not_in(AGENT_TERMINAL))).all()
        for agent_id in still:
            self._set_agent(ctx.cid, agent_id, status="rejected", ended_at=now())
        for child in children:
            self._out_of_run(child)

    def _talk_only(self: "AgentRunner", room: _Room, ctx: Ctx) -> Ctx:
        """A member of a room as it works there; in one between teams (K-not-oda) it changes no
        file: no tool that writes or runs a command, and no MCP server's - which may do either
        (`_mcp`); so none for a sub-agent it opens."""
        if room.between:
            ctx = replace(ctx, tools=rooms.talk_only(ctx.tools, room.between), mcp=())
            self._set_agent(ctx.cid, ctx.agent_id, mcp=[])
        self._ctxs[ctx.agent_id] = ctx
        return ctx

    def _add_member(self: "AgentRunner", room: _Room, child: Ctx, role: str) -> _Member:
        """A sub-agent the user let be opened for an agent's room becomes its member: with
        the room's tools, last in its order, waiting for its part."""
        with self._factory() as session:
            row = RoomMember(
                room_id=room.id, position=len(room.members), role=role, agent_id=child.agent_id)
            session.add(row)
            session.commit()
            row_id = row.id
        ctx = self._talk_only(room, replace(child, tools=(*child.tools, *rooms.TOOLS)))
        self._set_agent(ctx.cid, ctx.agent_id, status="waiting", tools=list(ctx.tools))
        member = room.members[ctx.agent_id] = _Member(ctx, row_id)
        # Its opener goes nowhere until the room is over: a round of waits for files that
        # runs through it is found and refused, as for any sub-agent (`_see_through`).
        self.claims.awaiting(room.lead.agent_id, ctx.agent_id)
        self._set_room(room)
        return member

    async def _in_room(self: "AgentRunner", room: _Room, work: Callable,
                       members: list[_Member]) -> None:
        """Do a part of a room's work for these members at once, each as a task of its
        own that the room's end stops (`_end_room`): a member stopped that way just ends
        there, and what it left open is settled when the room is closed. Stop, or one
        of them breaking, stops them all - and is passed on."""
        room.tasks = [asyncio.ensure_future(self._part(room, work, member)) for member in members]
        try:
            awaited = 0
            while awaited < len(room.tasks):  # and one invited meanwhile (`_invite`)
                awaited = len(room.tasks)
                await asyncio.gather(*room.tasks)
        except BaseException as exc:
            # One that had not begun when the room ended is stopped like the others:
            # that is no Stop of the turn, and all of them are waited for.
            running = cast(asyncio.Task, asyncio.current_task())
            ended = isinstance(exc, asyncio.CancelledError) and room.outcome is not None
            for task in room.tasks:
                task.cancel()
            await asyncio.gather(*room.tasks, return_exceptions=True)
            if not ended or running.cancelling():
                raise
        finally:
            room.tasks = []

    async def _part(self: "AgentRunner", room: _Room, work: Callable, member: _Member) -> None:
        """One member's part of a room's work: stopped by the room's end, it just ends."""
        try:
            await work(room, member)
        except asyncio.CancelledError:
            if room.outcome is None:
                raise

    async def _share(self: "AgentRunner", room: _Room, member: _Member) -> None:
        """A member's one step before the work starts: it is offered what it may read
        with, the room's list and a word to the room - nothing that changes or runs
        anything, and no tool of an MCP server. What it says without a tool stays in its
        own conversation. A member whose model fails here has left the room."""
        ctx = member.ctx
        turn = replace(ctx, max_steps=1, mcp=(), tools=tuple(
            tool for tool in ctx.tools if tool in rooms.SHARING_READS or tool in rooms.SHARING))
        async with self._working(turn, queued=True):
            self._set_agent(ctx.cid, ctx.agent_id, status="running", started_at=now())
            status, error = await self._run_child(turn)
        if status == "completed" or error == "step_limit":
            # (One step, and tools called in it: "step_limit" is how that step ends.)
            self._set_agent(ctx.cid, ctx.agent_id, status="waiting")
        else:
            self._member_left(room, member, error)

    async def _work(self: "AgentRunner", room: _Room, member: _Member) -> None:
        """A member's work, from the end of the sharing round until the room is over: it
        works like any sub-agent, with its role's tools and the room's. Its work is over
        when it answers without calling a tool - it is "done", with those last words -
        and from then on it waits here: a question for it takes it back to work. One
        whose model fails, or that stops at a limit, has left the room."""
        ctx = member.ctx
        again: dict = {}
        while True:
            async with self._working(ctx, queued=True):
                # B-169: woken for a question another answered while it waited for its place, it
                # takes no step and says nothing: it is done again. (Asked another since, it works.)
                # shortcut: two woken at once, with places for both, each takes its step - the
                # question is open as both start; hold one back till the other has answered if met.
                asked = not again or member.answered or self._unread(room, member, question=True)
                member.answered = False
                if asked:
                    self._set_agent(ctx.cid, ctx.agent_id, status="running", **again)
                    status, error = await self._run_child(self._role_now(ctx))
                    # 29c: a last step that ended while paused says nothing in the room till
                    # Resume - its "done" could end the room and take its copy in. (Here, in its
                    # place: after the block, coming back from the wait would take a place again.)
                    await self._while_paused(ctx)
            if not asked:
                self._set_agent(ctx.cid, ctx.agent_id, status="completed")
                member.woken_by = None
                self._set_member(room, member, "done")
                self._settle_room(room)
                await member.wake.wait()
                member.wake.clear()
                continue
            last = self._last_text(ctx.agent_id, final_only=status == "completed")
            if status != "completed":
                self._member_left(room, member, error, last)
                return
            self._set_agent(
                ctx.cid, ctx.agent_id, status="completed", report=last or None, ended_at=now())
            self._leaves(room, member, "done", last or "(it said nothing)")
            await member.wake.wait()
            member.wake.clear()
            again = {"error": None, "ended_at": None}

    def _member_left(
        self: "AgentRunner", room: _Room, member: _Member, error: str | None, last: str = ""
    ) -> None:
        """A member failed - its model, or a limit it stopped at: it is out of the room."""
        ctx = member.ctx
        why = (
            f"It stopped after {self._app_steps()} steps." if error == "step_limit"
            else f"It failed: {self._told(ctx.agent_id, error)}"
        )
        self._set_agent(
            ctx.cid, ctx.agent_id, status="failed", error=error, report=last or None,
            ended_at=now(),
        )
        self._leaves(room, member, "left", why)

    def _leaves(self: "AgentRunner", room: _Room, member: _Member, state: str, said: str) -> None:
        """A member is out of the room's work - "done" or "left": the items it still
        held are nobody's again, the room is told (a post of KOLONİ's own, of that
        type), and whether the room can go on is looked at."""
        agent_id = member.ctx.agent_id
        with self._factory() as session:
            held = session.scalars(select(RoomItem).where(
                RoomItem.room_id == room.id, RoomItem.holder_agent_id == agent_id,
                RoomItem.status == "taken",
            )).all()
            for item in held:
                item.status, item.holder_agent_id = "open", None
            session.commit()
            payloads = [room_item_out(item) for item in held]
        for payload in payloads:
            self.bus.emit(room.lead.cid, room.lead.run_id, "room_item.updated", payload)
        if payloads and state == "left":
            numbers = ", ".join(str(payload["number"]) for payload in payloads)
            said += f" What it held is nobody's again: item {numbers}."
        self._set_member(room, member, state)
        # B-156: woken for a question asked of it by name, which it then left unanswered by a
        # post, its last words are the answer: nobody else will reply. Not one to nobody in
        # particular - another may answer that. (Woken by one and asked another while at work
        # again, its last words close only the one that woke it.)
        woken, member.woken_by = member.woken_by, None
        still = False
        if woken is not None and state == "done":
            with self._factory() as session:
                still = bool(session.scalar(select(RoomPost.open).where(
                    RoomPost.room_id == room.id, RoomPost.number == woken,
                    RoomPost.to_agent_id == agent_id)))
        self._post_room(room, agent_id, state, said, reply_to=woken if still else None)
        if state == "done" and (asked := self._unread(room, member, question=True)):
            # A question for it came while it took its last step: it goes back to work.
            member.woken_by = asked
            member.wake.set()
            self._set_member(room, member, "in")
        self._settle_room(room)

    def _settle_room(self: "AgentRunner", room: _Room) -> None:
        """Whether a room can go on, looked at as a member's work is over - or its opener reads
        it no more: with fewer than two members left, or nobody left to take a step, it ends."""
        if room.outcome is not None:
            return
        states = [one.state for one in room.members.values()]
        if sum(one != "left" for one in states) < rooms.MIN_MEMBERS:
            self._end_room(room, "too_few")
        elif all(one in ("done", "left") for one in states):
            # Nobody is left to take a step. With a question still open that is not
            # "agreed": too few - none - are left to answer it. (S3: but its opener, reading
            # the room, may answer one for it or for nobody in particular.)
            with self._factory() as session:
                unanswered = session.scalars(select(RoomPost.to_agent_id).where(
                    RoomPost.room_id == room.id, RoomPost.open)).all()
            if room.reads and any(to in (None, room.lead.agent_id) for to in unanswered):
                return
            if unanswered:
                self._end_room(room, "too_few", "unanswered")
            else:
                self._end_room(room, "agreed")

    def _unread(self: "AgentRunner", room: _Room, member: _Member,
                question: bool = False) -> int | None:
        """The number of something said in a room that this member has not been given yet -
        `question`: an open question that is for it, or for nobody in particular; None:
        nothing."""
        me = member.ctx.agent_id
        asked = (
            RoomPost.type == "question", RoomPost.open,
            or_(RoomPost.to_agent_id.is_(None), RoomPost.to_agent_id == me),
        ) if question else ()
        seen = select(RoomMember.seen).where(RoomMember.id == member.row).scalar_subquery()
        with self._factory() as session:
            return session.scalar(select(RoomPost.number).where(
                RoomPost.room_id == room.id, RoomPost.number > seen,
                or_(RoomPost.agent_id.is_(None), RoomPost.agent_id != me), *asked,
            ).order_by(RoomPost.number).limit(1))

    def _end_room(self: "AgentRunner", room: _Room, outcome: str,
                  reached: str | None = None) -> bool:
        """A room ends here, unless it has already: how is kept, its clock stands and
        what its members are doing is stopped - they are settled, and the room put on
        record as over, when the turn gets back to it (`_close_room`). Nothing here
        waits: from this call on no tool of the room does anything."""
        if room.outcome is not None:
            return False
        room.outcome, room.reached = outcome, reached
        room.go.set()  # (29c: ended while paused, nobody is held for a Resume)
        self._stop_clock(room)
        for task in room.tasks:
            task.cancel()
        return True

    async def _close_room(self: "AgentRunner", room: _Room) -> str:
        """A room is over: it ended of itself, or its opener or the user ended it (Stop and a
        failure never get here: `_room_cut`). Its members that were still at it are done
        with it - B-386 (live): a coordinator left "cancelled" was opened again as its
        team's "lead 2" - and one the user had not approved yet never started. The
        room goes on record as ended; what was changed in its copy is taken into the
        project the way a sub-agent's copy is (`_into_project`): unasked only where the
        room ended with every member's work over and the conversation asks about no
        change - else one card, which is the room's. Returns the opener's part: the
        room's record, with what of its changes did not reach the project. From there
        its members are the opener's sub-agents like any other."""
        lead = room.lead
        for member in room.members.values():
            ctx = member.ctx
            with self._factory() as session:
                status = session.get_one(Agent, ctx.agent_id).status
            if status not in AGENT_TERMINAL:
                self._settle_session(ctx)
                self._set_agent(ctx.cid, ctx.agent_id, ended_at=now(), status=(
                    "rejected" if status == "proposed" else "completed"))
        room.status = "ended"
        self._set_room(
            room, status="ended", outcome=room.outcome, why=room.reached, ended_at=now(),
            seconds=room.seconds, clock_since=None, paused=False, lead_follows="off",
        )
        copy = self._copies.get(lead.agent_id)
        not_taken = ""
        # (A sub-agent that opened it has the room's work in its own copy: that is taken
        # in when its own work is over, as any sub-agent's.) A room in a recipe (slice 84e)
        # worked in the recipe's copy, whoever opened it: it waits there for the user's Take
        # in, at Ready for you - never taken in here.
        if self._in_a_recipe(lead):
            not_taken = ("The room's changes are in the recipe's copy: they go into the project "
                         "only with the user's Take in, at the recipe's end.")
        elif copy is not None and lead.depth == 0:
            not_taken = await self._into_project(
                replace(lead, name="the room"), copy,
                "completed" if room.outcome == "agreed" else "failed", lambda: None,
            )
        for member in room.members.values():
            ctx = self._ctxs[member.ctx.agent_id]
            self._ctxs[ctx.agent_id] = replace(
                ctx, tools=tuple(tool for tool in ctx.tools if tool not in rooms.TOOLS))
        if room.between:
            # K-not-oda: what it decided reaches every team's agents, their leads among them, on
            # the notebook; each team applies it in its own work.
            with self._factory() as session:
                goal = session.get_one(Room, room.id).goal
                items, _questions, _names = self._room_lists(session, room, None)
                ended = session.scalar(select(RoomPost.text).where(
                    RoomPost.room_id == room.id, RoomPost.type == "ended"))
            decided = rooms.decided(
                room.between, room.outcome or "", goal, items, ended, room.reached)
            team_requests.decided(self, lead, room.between, goal, decided)  # (K-ortak-klasor)
            try:
                self._write_note(lead.run_id, lead.cid, None, board.cut(
                    decided, board.MAX_NOTE_CHARS), koloni=True)
                told = rooms.TOLD_BETWEEN
            except ToolError:  # (a full notebook: the opener is told it is not there)
                told = rooms.NOT_NOTED
            not_taken = " ".join(filter(None, [
                not_taken, told.format(teams=", ".join(room.between))]))
        del self._rooms[lead.run_id]
        record = self._room_record(room, not_taken)
        with self._factory() as session:
            users = session.get_one(Room, room.id).agent_id is None
        if users:
            # The Lead's next turns read it here (`told_of_rooms`) - a follower's too (K-oda-izle).
            # shortcut: a Lead that followed it is given it twice in the rest of this turn (its
            # call's answer, and after the turn's message); keep the first if that matters.
            self._set_room(room, told=record)
        return record

    def _room_lists(self: "AgentRunner", session, room: _Room,
                    reader: str | None) -> tuple[list, list, dict]:
        """A room's items and its open questions as an agent is told them, and its
        members' names by their ids: "you" for the agent that reads them."""
        names = {
            agent_id: "you" if agent_id == reader else member.ctx.name
            for agent_id, member in room.members.items()
        }
        # (K-oda-lead: its opener, which may post while it follows it)
        names[room.lead.agent_id] = "you" if room.lead.agent_id == reader else room.lead.name
        items = [
            (item.number, item.title, item.paths, item.status,
             names.get(item.holder_agent_id or ""), item.result)
            for item in session.scalars(
                select(RoomItem).where(RoomItem.room_id == room.id).order_by(RoomItem.number))
        ]
        questions = [
            (post.number, names.get(post.agent_id or "", board.USER),
             names.get(post.to_agent_id or ""), post.text)
            for post in session.scalars(
                select(RoomPost).where(RoomPost.room_id == room.id, RoomPost.open)
                .order_by(RoomPost.number))
        ]
        return items, questions, names

    def _room_now(self: "AgentRunner", ctx: Ctx, changed: bool = False) -> str:
        """How its room stands, for a member about to take a step: from the record, as
        it is this moment. "" for anybody else, and once the room has ended. `changed`:
        only when it stands otherwise than this member was last told (what was spent
        aside) - a CLI that keeps its own loop is told with a tool's result."""
        room = self._rooms.get(ctx.run_id)
        member = room.members.get(ctx.agent_id) if room is not None else None
        if room is None or member is None or room.outcome is not None:
            return ""
        with self._factory() as session:
            row = session.get_one(Room, room.id)
            items, questions, _names = self._room_lists(session, room, ctx.agent_id)
            spent = room_spent(session, row)
            budget = {
                "posts": row.max_posts, "tokens": row.max_tokens, "minutes": row.max_minutes}
        others = [
            (other.ctx.name, other.state) for other in room.members.values() if other is not member]
        stands = repr((room.status, items, others, questions))
        if changed and stands == member.told:
            return ""
        member.told = stands
        return rooms.now(room.status, items, others, questions, spent, budget)

    def _room_record(self: "AgentRunner", room: _Room, not_taken: str) -> str:
        """What the lead is given of a room that is over (`rooms.record`). Of a room in
        which a great deal was said, the newest posts that fit a quarter of what a
        model is given - and how many older ones are left out."""
        with self._factory() as session:
            mine = session.get_one(Room, room.id).agent_id is not None
            items, questions, names = self._room_lists(session, room, None)
            rows = session.scalars(
                select(RoomPost).where(RoomPost.room_id == room.id).order_by(RoomPost.number)
            ).all()
            posts = [
                rooms.said(
                    post.number, names.get(post.agent_id or ""), post.type,
                    names.get(post.to_agent_id or ""), post.reply_to, post.text,
                )
                for post in rows
            ]
        fits, size = len(posts), 0
        while fits and size + len(posts[fits - 1]) <= self.settings.context_char_budget // 4:
            fits -= 1
            size += len(posts[fits])
        if fits:
            posts = [f"[{fits} earlier post(s) are not shown]", *posts[fits:]]
        return self._noted_posts(room.lead, rows[fits:], names, rooms.record(
            [member.ctx.name for member in room.members.values()], room.outcome or "",
            room.reached, items, posts, questions, not_taken, mine,
            followed=room.lead.agent_id in self._following,
        ))

    def _hand_posts(self: "AgentRunner", ctx: Ctx) -> list[str]:
        """Hand a member of a room what was said in it since it was last handed any:
        written into its own conversation as it reads it, with its mark moved past - in
        one go, like the notebook's notes. Its own posts are passed over. Nothing in a
        turn taken to answer somebody: the room waits for its own work."""
        room = self._rooms.get(ctx.run_id)
        member = room.members.get(ctx.agent_id) if room is not None else None
        if room is None or member is None or ctx.answering:
            return []
        with self._factory() as session:
            row = session.get_one(RoomMember, member.row)
            posts = session.scalars(
                select(RoomPost).where(RoomPost.room_id == room.id, RoomPost.number > row.seen)
                .order_by(RoomPost.number)
            ).all()
            if not posts:
                return []
            row.seen = posts[-1].number
            names = {
                agent_id: "you" if agent_id == ctx.agent_id else other.ctx.name
                for agent_id, other in room.members.items()
            }
            names[room.lead.agent_id] = room.lead.name  # (K-oda-lead: its opener's posts)
            # A member's words may carry what it read elsewhere (93-A4); the user's and what
            # KOLONİ wrote of one that left are never looked at.
            heard = {post.id: (f"a room post by {names.get(post.agent_id or '', 'a member')}",
                               rules)
                     for post in posts if post.agent_id not in (None, ctx.agent_id)
                     and post.type != "left" and (rules := injection.scan(post.text, "agent"))}
            rows = [
                Message(
                    conversation_id=ctx.cid, run_id=ctx.run_id, agent_id=ctx.agent_id,
                    from_agent_id=post.agent_id, role="agent", status="complete",
                    delivered_at=now(), room_post_id=post.id,
                    content=(f"{injection.NOTE}\n" if post.id in heard else "") + rooms.handed(
                        post.number, names.get(post.agent_id or ""), post.type,
                        names.get(post.to_agent_id or ""), post.reply_to, post.text,
                    ),
                )
                for post in posts if post.agent_id != ctx.agent_id
            ]
            session.add_all(rows)
            session.commit()
            payloads = [message_out(message) for message in rows]
        for payload in payloads:
            self.bus.emit(ctx.cid, ctx.run_id, "message.created", payload)
        for where, rules in heard.values():
            self._warn(ctx, rules, "agent", where)
        return [payload["content"] for payload in payloads]

    def _post_room(
        self: "AgentRunner", room: _Room, agent_id: str | None, kind: str, text: str,
        to: str | None = None, reply_to: int | None = None,
    ) -> dict:
        """Put something said into a room, under the next number (the user's, with no
        agent). A reply to an open question of somebody else's closes it. Whoever waits
        for a post has one now; and a member whose work is over goes back to it for a
        question that is for it - or for nobody in particular. ToolError where it
        replies to a post that is not there. Nothing here waits: a post's number is
        taken and written in one go."""
        with self._factory() as session:
            target = session.scalar(select(RoomPost).where(
                RoomPost.room_id == room.id, RoomPost.number == reply_to,
            )) if reply_to is not None else None
            if reply_to is not None and target is None:
                raise ToolError(f"there is no post {reply_to} in the room")
            last = session.scalar(
                select(func.max(RoomPost.number)).where(RoomPost.room_id == room.id)) or 0
            post = RoomPost(
                room_id=room.id, number=last + 1, agent_id=agent_id, type=kind, text=text,
                to_agent_id=to, reply_to=reply_to, open=kind == "question",
            )
            session.add(post)
            closes = target is not None and target.open and target.agent_id != agent_id
            if target is not None and closes:
                target.open = False
            session.commit()
            payload = room_post_out(post)
            closed = room_post_out(target) if target is not None and closes else None
        self.bus.emit(room.lead.cid, room.lead.run_id, "room_post.created", payload)
        if closed is not None:
            self.bus.emit(room.lead.cid, room.lead.run_id, "room_post.updated", closed)
        # K-oda-lead: its opener, where it follows it, is woken for a question, for what is
        # said to it and for the user's word - not for every post (S7: each is a step of its).
        if agent_id != room.lead.agent_id and (
                agent_id is None or kind == "question" or to == room.lead.agent_id):
            room.heard.set()
        asker = room.members.get(target.agent_id or "") if target is not None and closes else None
        if agent_id == room.lead.agent_id and asker is not None and asker.state == "done":
            # (S3: its opener answered a question of one whose work is over: it reads it.)
            asker.answered = True
            asker.wake.set()
            self._set_member(room, asker, "in")
        for member in room.members.values():
            if member.ctx.agent_id == agent_id or room.outcome is not None:
                continue  # (said as it ends - its opener's word: nobody is woken for it)
            member.news.set()
            asked = kind == "question" and to in (None, member.ctx.agent_id)
            if member.state == "waiting" or (member.state == "done" and asked):
                if member.state == "done":
                    member.woken_by = payload["number"]
                    member.wake.set()
                self._set_member(room, member, "in")
        return payload

    def _hold_room_to(self: "AgentRunner", run_id: str, what: str,
                      agent_id: str | None = None) -> bool:
        """A room's members have spent something - "posts" or "tokens": the page is told
        how much, and where that limit of the room's budget is reached, the room ends.
        Whether it ended here. `agent_id`: whose spending it was - only a member's own
        counts (not a sub-agent's of its opening)."""
        room = self._rooms.get(run_id)
        if room is None or room.outcome is not None or (
            agent_id is not None and agent_id not in room.members
            and agent_id not in self._following
        ):
            return False
        with self._factory() as session:
            row = session.get_one(Room, room.id)
            limit = {"posts": row.max_posts, "tokens": row.max_tokens}[what]
            payload = room_out(session, row)
        self.bus.emit(room.lead.cid, run_id, "room.updated", payload)
        spent = payload["spent"][what]  # (None: nothing reported, nothing held to)
        return limit is not None and spent is not None and spent >= limit and self._end_room(
            room, "budget", what)

    def _stop_clock(self: "AgentRunner", room: _Room) -> None:
        if room.since is not None:
            room.seconds += asyncio.get_running_loop().time() - room.since
            room.since = None
        if room.timer is not None:
            room.timer.cancel()
            room.timer = None

    def _room_minutes(self: "AgentRunner", run_id: str) -> None:
        """A room's minutes are counted while it runs - not, like an unattended turn's
        (`_count_minutes`), while it is only kept waiting for room - and at its limit
        of them it ends. Looked at whenever who of the turn holds a place has changed."""
        room = self._rooms.get(run_id)
        if room is None or room.outcome is not None:
            return
        if self._kept_out(run_id) or not room.go.is_set():  # (29c: nor while paused)
            if room.since is not None:
                self._stop_clock(room)
                self._set_room(room, seconds=room.seconds, clock_since=None)
        elif room.since is None:
            room.since = asyncio.get_running_loop().time()
            self._set_room(room, clock_since=now())
            self._set_timer(room)

    def _set_timer(self: "AgentRunner", room: _Room) -> None:
        """What ends a room at its limit of minutes, set for what is left of them now."""
        if room.timer is not None:
            room.timer.cancel()
            room.timer = None
        with self._factory() as session:
            minutes = session.get_one(Room, room.id).max_minutes
        if minutes is None or room.since is None:
            return
        loop = asyncio.get_running_loop()
        later = self.call_later or loop.call_later
        left = minutes * MINUTE - room.seconds - (loop.time() - room.since)
        room.timer = later(max(0.0, left), self._end_room, room, "budget", "minutes")

    def _running_room(self: "AgentRunner", room_id: str) -> _Room | None:
        return next(
            (room for room in self._rooms.values() if room.id == room_id and room.outcome is None),
            None,
        )

    def say_in_room(self: "AgentRunner", room_id: str, text: str) -> dict | None:
        """The user speaks in a room; None if it is over. Every member reads it at its
        next step, and one that waits for a post is woken by it."""
        room = self._running_room(room_id)
        return self._post_room(room, None, "said", text) if room is not None else None

    def end_room(self: "AgentRunner", room_id: str) -> bool:
        """The user ends a room; False if it is over already."""
        room = self._running_room(room_id)
        return room is not None and self._end_room(room, "ended_by_user")

    def pause_room(self: "AgentRunner", room_id: str, paused: bool) -> dict | None:
        """29c: the user pauses a running room, or resumes it; None if it is over. Paused, its
        members finish the step or tool at hand and then hold (`_while_paused`): no model is
        asked and nothing is posted, and its clock stands. Resumed, they go on from there."""
        room = self._running_room(room_id)
        if room is None:
            return None
        if paused:
            room.go.clear()
            self._stop_clock(room)
            self._set_room(room, paused=True, seconds=room.seconds, clock_since=None)
        else:
            room.go.set()
            self._set_room(room, paused=False)
            self._room_minutes(room.lead.run_id)  # (its clock goes on)
        with self._factory() as session:
            return room_out(session, session.get_one(Room, room.id))

    def follow_room(self: "AgentRunner", room_id: str, on: bool) -> dict | None:
        """K-oda-izle: the user lets the turn's Lead follow the room they opened, as it follows one
        it opened itself (`_follow`) - it is woken from its wait for the room (`_hold_room`) - or
        stops it: from then on it reads and posts nothing there, its step at hand aside, until the
        room's record or until it is let follow it again. None if the room is over; ValueError
        where its Lead cannot follow it."""
        room = self._running_room(room_id)
        with self._factory() as session:
            row = session.get_one(Room, room_id)
            # (Opened a moment ago, its turn has not taken it up yet: not "over".)
            if room is None and row.status in rooms.RUNNING and all(
                    one.id != room_id for one in self._rooms.values()):
                raise ValueError(rooms.STARTING)
            if room is None:
                return None
            if row.agent_id is not None:
                raise ValueError(rooms.OPENER_FOLLOWS)
        # (Its model as it stands: one its message moves onto a CLI's session later follows no
        # further from there - `_lead_on_session`.)
        lead = self._ctxs.get(room.lead.agent_id, room.lead)
        if on and room.read_out:
            raise ValueError(rooms.FOLLOWS_NO_FURTHER)
        if on and getattr(lead.model, "session", False):
            raise ValueError(rooms.LEAD_ON_SESSION)
        room.reads = on
        if on:
            room.follow.set()
        else:
            room.follow.clear()
            self._settle_room(room)  # (S3: nobody counts on it to answer any more)
            for member in room.members.values():
                if member.state == "waiting" and member.awaits is None:
                    member.news.set()  # (it looks again: nobody else at work, it is told so)
        self._set_room(room, lead_follows="on" if on else "off")
        with self._factory() as session:
            return room_out(session, session.get_one(Room, room.id))

    def more_for_room(self: "AgentRunner", room_id: str,
                      more: dict[str, int | None]) -> dict | None:
        """The user adds to a running room's budget ("posts", "tokens", "minutes"); None
        if it is over. A limit the room does not have stays none."""
        room = self._running_room(room_id)
        if room is None:
            return None
        with self._factory() as session:
            row = session.get_one(Room, room.id)
            for key, added in more.items():
                had = getattr(row, f"max_{key}")
                if added and had is not None:
                    setattr(row, f"max_{key}", had + added)
            session.commit()
            payload = room_out(session, row)
        self.bus.emit(room.lead.cid, room.lead.run_id, "room.updated", payload)
        self._set_timer(room)
        return payload

    async def _room_call(
        self: "AgentRunner", ctx: Ctx, call_id: str, room: _Room, member: _Member, name: str,
        args: dict
    ) -> tuple[str, str]:
        """One of the room's own tools, for a member of it. Returns the call's status and
        its text. Nothing of a room that is over does anything."""
        if room.outcome is not None:
            raise ToolError(rooms.OVER)
        if name == "wait_for_post":
            return "succeeded", await self._wait_for_post(room, member, ctx)
        if name == "wait_for_item":
            return "succeeded", await self._wait_for_item(room, member, ctx, args)
        if name == "post_to_room":
            return await self._say(room, ctx, call_id, args)
        if name == "invite_to_room":
            return "succeeded", await self._invite(room, ctx, call_id, args)
        return "succeeded", self._item(room, ctx, name, args)

    def _item(self: "AgentRunner", room: _Room, ctx: Ctx, name: str, args: dict) -> str:
        """A member adds an item to its room's list, takes one, finishes or drops one it
        holds; returns what it is told. Nothing here waits (no await): an item is looked
        at and taken in one go, so two members never both come away with it."""
        title, paths = rooms.plan_item(args) if name == "add_item" else ("", [])
        shown: list[str] = []
        for path in paths:
            found = place(ctx.folder, path)
            if found is None:
                raise ToolError(f"{path!r} is not a file or a folder inside the project")
            if found[1] not in shown:
                shown.append(found[1])
        number = None if name == "add_item" else rooms.item_number(args)
        with self._factory() as session:
            items = session.scalars(
                select(RoomItem).where(RoomItem.room_id == room.id).order_by(RoomItem.number)
            ).all()
            if name == "add_item":
                item = RoomItem(room_id=room.id, number=len(items) + 1, title=title, paths=shown)
                session.add(item)
                told = (
                    f"added as item {item.number}. It is nobody's yet: "
                    f"take_item({item.number}) makes it yours."
                ) + rooms.looks_like(title, [
                    (one.number, one.title,
                     self._name_of(one.holder_agent_id) if one.holder_agent_id else None)
                    for one in items if one.status in ("open", "taken")])
            else:
                item = next((one for one in items if one.number == number), None)
                if item is None:
                    raise ToolError(f"there is no item {number} on the room's list")
                told = self._hold_item(session, ctx, items, item, name, args)
            session.commit()
            payload = room_item_out(item)
        kind = "room_item.created" if name == "add_item" else "room_item.updated"
        self.bus.emit(room.lead.cid, room.lead.run_id, kind, payload)
        if name in ("finish_item", "drop_item"):
            self._hand_on_files(ctx, payload["paths"])
            for other in room.members.values():
                if other.awaits == payload["number"]:
                    other.news.set()
        return told

    def _hand_on_files(self: "AgentRunner", ctx: Ctx, paths: list[str]) -> None:
        """An item is finished or dropped: the files its holder holds under it are let go
        as a member's are when its work is over (`_work_over`) - on to the lead, where
        they were changed in the room's copy - so that the next item over them is not
        kept waiting for one whose part in them is done."""
        under = _places(ctx.folder, paths)
        if not under:
            return
        owner = self._copy_owner(ctx)
        to = owner if owner and owner != ctx.agent_id and self._copies.get(owner) else None
        self.claims.hand_on(
            ctx.agent_id, to, lambda key: any(rooms.covers(one, key[1]) for one in under))
        self._claims_changed(ctx.root, ctx.cid)

    def _hold_item(
        self: "AgentRunner", session, ctx: Ctx, items: list[RoomItem], item: RoomItem, name: str,
        args: dict
    ) -> str:
        """Take an item, or close one that is held - in the caller's transaction. An
        item has one holder: one somebody holds is refused, by that agent's name, and so
        is one whose paths meet those of an item somebody else holds. Only its holder
        finishes or drops it."""
        me, number = ctx.agent_id, item.number
        if name != "take_item":
            said = rooms.words(args, "result" if name == "finish_item" else "why")
            if item.status != "taken" or item.holder_agent_id != me:
                raise ToolError(
                    f"item {number} is not yours: only an item you hold is finished or "
                    "dropped (take_item)")
            item.status, item.result = "done" if name == "finish_item" else "dropped", said
            return f"item {number} is {item.status}."
        if item.status == "taken" and item.holder_agent_id == me:
            raise ToolError(f"item {number} is yours already")
        if item.status == "taken":
            raise ToolError(
                f"item {number} is held by {self._name_of(item.holder_agent_id or '')}: an "
                "item has one holder. Take another, or add one for what is still to be done")
        if item.status != "open":
            raise ToolError(f"item {number} is {item.status}: nothing of it is left to take")
        mine = _places(ctx.folder, item.paths)
        for other in items:
            if (
                other.status == "taken" and other.holder_agent_id != me
                and rooms.overlap(mine, _places(ctx.folder, other.paths))
            ):
                raise ToolError(
                    f"item {number} covers files that item {other.number}, held by "
                    f"{self._name_of(other.holder_agent_id or '')}, covers too "
                    f"({', '.join(other.paths)}): two items over the same files are not "
                    "held at the same time")
        item.status, item.holder_agent_id = "taken", me
        over = f" You change files under it: {', '.join(item.paths)}." if item.paths else ""
        return f"item {number} is yours: {board.as_data(item.title)}.{over}"

    def _under_an_item(self: "AgentRunner", ctx: Ctx, path: str) -> None:
        """In a room a file is changed only under an item: one its member holds - the
        agent itself, or the member it works for - whose paths cover the file. ToolError
        for any other file, before it is waited for or anything is put on record."""
        found = self._member_of(ctx)
        if found is None:
            return
        room, member = found
        if room.outcome is not None:
            raise ToolError(rooms.OVER)
        with self._factory() as session:
            held = session.scalars(select(RoomItem.paths).where(
                RoomItem.room_id == room.id, RoomItem.status == "taken",
                RoomItem.holder_agent_id == member.ctx.agent_id,
            )).all()
        file = _places(ctx.folder, [path])
        over = [one for paths in held for one in _places(ctx.folder, paths)]
        if not file or not any(rooms.covers(one, file[0]) for one in over):
            raise ToolError(rooms.NO_ITEM.format(path=path))

    async def _say(self: "AgentRunner", room: _Room, ctx: Ctx, call_id: str,
                   args: dict) -> tuple[str, str]:
        """A member posts to its room. With a post that reaches the room's budget of
        them, the room ends. "blocked" asks the user, as `ask_user` does - the call
        waits for their answer, which goes into the room as their word on that post."""
        kind, said, to, reply_to = rooms.plan_post(args)
        to_id = None
        if to is not None:
            others = [
                one.ctx for one in room.members.values() if one.ctx.agent_id != ctx.agent_id]
            if room.reads and room.lead.agent_id != ctx.agent_id:
                others.append(room.lead)  # (K-oda-lead: its opener, which reads it)
            to_id = next(
                (one.agent_id for one in others if one.name.casefold() == to.casefold()), None)
            if to_id is None:
                raise ToolError(
                    f"there is no other member named {to} in the room. The others: "
                    f"{', '.join(one.name for one in others)}")
        number = self._post_room(room, ctx.agent_id, kind, said, to_id, reply_to)["number"]
        if self._hold_room_to(ctx.run_id, "posts"):
            return "succeeded", (
                f"posted as post {number}. With it the room's budget of posts is reached: "
                "the room ends here.")
        if kind != "blocked":
            return "succeeded", f"posted as post {number}: the others read it at their next step."
        # (As `ask_user`: a member's question is the Lead's to answer for the user, the Lead's
        # own never - B-181. The room gets the answer as given; the member hears whose it was.)
        ids: list[str] = []
        status, answer = await self._ask_user(ctx, call_id, {"question": said}, ids=ids,
                                              kind="ask_user" if ctx.depth else None)
        if room.outcome is None:
            with self._factory() as session:
                word = session.get_one(Question, ids[0]).answer
            self._post_room(room, None, "said", word, reply_to=number)
        return status, f"posted as post {number}. {answer}"

    async def _invite(self: "AgentRunner", room: _Room, ctx: Ctx, call_id: str, args: dict) -> str:  # noqa: C901
        """A member asks one more into its room (`invite_to_room`): opened as a sub-agent of
        the room's opener is, under the same rules, with the room's goal as its task. Once
        the work has started it joins it at once; while it is shared out, with the rest.
        With no role named, only why, the Lead picks one (K-29b2-davet: `_pick_member`)."""
        wanted, why = args.get("role") or None, args.get("why") or None
        if wanted is not None and (not isinstance(wanted, str) or not wanted.strip()):
            raise ToolError("argument role must be a role's name")
        if why is not None and not isinstance(why, str):
            raise ToolError("argument why must be a string")
        if wanted is None and (why is None or not why.strip()):
            raise ToolError(rooms.NAME_THE_ROLE)
        if len(room.members) >= rooms.MAX_MEMBERS:
            raise ToolError(rooms.FULL)
        picked = ""
        if wanted is None:
            wanted, because = await self._pick_member(room, ctx, cast(str, why))
            picked = rooms.PICKED.format(role=wanted, why=because)
        opener = room.lead
        with self._factory() as session:
            goal = session.get_one(Room, room.id).goal
            named = self._names_past(session, ctx)
            try:
                role, _tools, provider, model_name, moved = rooms.member_model(
                    session, session.get_one(Conversation, ctx.cid), wanted, None, None,
                    opener.tools, named_roles=named)
            except (ValueError, OwnStop) as exc:
                raise ToolError(str(exc)) from None
            # (In a recipe's step, as the room's opener would open it: one of the step's.)
            if shut := closed(role, self._door(session, opener), named):
                raise ToolError(shut)
            # (K-not-oda: its members kept their write tools; a recipe's room is its row's.)
            if not room.between and not self._in_a_recipe(opener) and self._between(
                    session, opener, [*(m.ctx.role for m in room.members.values()), role.name],
                    []):
                raise ToolError(rooms.NOT_INTO.format(role=role.name))
            model = self.providers.client(provider, model_name)
        task = goal + (f"\n\n{ctx.name} asked you in: {kept.one_line(why)}" if why else "")
        child, asks = self._propose(
            opener, call_id, role, task, provider, model_name, model, False, None,
            why=moved or "", tiered=moved is not None)
        self._in_run(opener, child, role)
        turned_down = await self._users_no(ctx, [child.agent_id]) if asks else None
        if asks:
            await self._settle(ctx)
        if turned_down is not None:
            self._out_of_run(child)
            raise ToolError(f"the user turned down the {role.name}: nobody was invited")
        if room.outcome is not None or len(room.members) >= rooms.MAX_MEMBERS:
            # Over, or full with another's guest, while the user was asked.
            self._unopened(ctx, [child])
            raise ToolError(rooms.OVER if room.outcome is not None else rooms.FULL)
        member = self._add_member(room, child, role.name)
        if room.status == "working":
            room.tasks.append(asyncio.ensure_future(self._part(room, self._work, member)))
        return f"{child.name} is in the room now, with its goal as its task.{picked}"

    async def _pick_member(self: "AgentRunner", room: _Room, ctx: Ctx, why: str) -> tuple[str, str]:
        """K-29b2-davet: one more is asked into a room with no role named, only why. The Lead's
        model is asked once, with no tools, which of the roles that could join should, and why -
        the room's goal and the asker's words quoted, as data; what comes back is taken only as
        one of those roles as written, with a reason (`lead_pick`). Its usage is on the Lead's
        record of its own (`_own_request`). ToolError, and nobody is invited, for anything else.
        shortcut: a Lead on a CLI (Claude Code, Codex, Copilot, agy) is not asked - a one-shot
        answer there is a session of its own; ask its `talker` once one is cheap.
        shortcut: it takes no place among the agents at work, as `_lead_answers` takes none; give
        it one if a busy local server is seen to queue it."""
        lead = self._lead_of(ctx.run_id)
        with self._factory() as session:
            conversation = session.get_one(Conversation, ctx.cid)
            goal = session.get_one(Room, room.id).goal
            named, door = self._names_past(session, ctx), self._door(session, room.lead)
            have = {member.ctx.role.casefold() for member in room.members.values()}
            roles = []
            for role in agent_roles(session):
                if role.name.casefold() in have or closed(role, door, named):
                    continue
                with contextlib.suppress(ValueError, OwnStop):
                    rooms.member_model(session, conversation, role.name, None, None,
                                       room.lead.tools, named_roles=named)
                    roles.append(role)
            provider = session.get(Provider, lead.provider_id or "") if lead else None
            # (Over the turn's or the month's budget, or the provider's limits: KOLONİ asks
            # nothing itself - as `_lead_answers` does not.)
            project = project_of(session, conversation)
            limit = project.turn_token_limit if project is not None else None
            spent = (
                "the turn's token limit is reached" if limit and self._turn_spent(
                    session, ctx.run_id)[0] > limit
                else over_month(session, project)
                or (past_its_limit(session, provider) if provider else None))
        names = [role.name for role in roles]
        if not roles:
            raise ToolError(rooms.NONE_TO_PICK)
        if lead is not None and ctx.agent_id == lead.agent_id:
            # (The Lead itself, following its room: its own model is not asked what it knows.)
            raise ToolError(rooms.NAME_A_ROLE.format(roles=", ".join(names)))
        if lead is None or lead.model is None or provider is None or mode_of(provider) or spent:
            raise ToolError(rooms.LEAD_CANNOT_PICK.format(
                why=spent or ("the Orchestrator works on a CLI" if provider and mode_of(provider)
                              else "no Orchestrator is at work"), roles=", ".join(names)))
        asked = [{"role": "user", "content": rooms.PICK.format(
            who=ctx.name, goal=quoted(goal), why=quoted(why),
            members=", ".join(member.ctx.name for member in room.members.values()),
            roles="\n".join(f"- {role.name}" + (f": {quoted(kept.one_line(role.description))}"
                                                 if kept.one_line(role.description) else "")
                            for role in roles))}]
        asking = lead
        try:
            model_id = lead.model_name or (await lead.model.info()).model_id
            asking = replace(lead, model_name=model_id)
            try:
                async with asyncio.timeout(observer.SECONDS):
                    said, answer = await ask_once(lead.model, model_id, asked)
            except BaseException:
                self._own_request(lead, asking, mode_of(provider), None)  # sent, not heard out
                raise
            self._own_request(lead, asking, mode_of(provider), answer)
        except Exception as exc:  # (not Stop: the asker stays in the room, told why)
            raise ToolError(rooms.LEAD_CANNOT_PICK.format(
                why=f"it did not answer: {exc}" if str(exc) else "it did not answer",
                roles=", ".join(names))) from None
        picked = lead_pick(_answer(said), names)
        if picked is None:
            raise ToolError(rooms.NOT_PICKED.format(roles=", ".join(names)))
        return picked

    async def _wait_for_post(self: "AgentRunner", room: _Room, member: _Member, ctx: Ctx) -> str:
        """A member waits for something to be said in its room that it has not been
        given - and for nothing if there is something already. While it waits it holds
        no place among the agents at work (`_handing_over`). Refused where no other
        member is at work: nobody but the user would wake it - unless another waits too,
        no question is open that this one could answer, and the room's minutes end it."""
        # B-201: cleared before the record is looked at - a post from here on, even one in
        # an await on the way to the wait, is one it wakes for.
        member.news.clear()
        if self._unread(room, member):
            return "there is something in the room you have not read yet: it follows."
        me = member.ctx.agent_id
        others = [other for other in room.members.values() if other is not member]
        with self._factory() as session:
            asked = session.scalar(select(RoomPost.id).where(
                RoomPost.room_id == room.id, RoomPost.type == "question", RoomPost.open,
                RoomPost.agent_id != me,
                or_(RoomPost.to_agent_id.is_(None), RoomPost.to_agent_id == me),
            ).limit(1)) is not None
            minutes = session.get_one(Room, room.id).max_minutes
        # (One that waits for a file this member holds is not at work: it waits for it.)
        # shortcut: members that all wait for a post, with no question open, wait for the
        # user's word, the End button or the room's minutes - so only in a room that has a
        # limit of minutes; end the room there if real models are seen to sit like that.
        alone = not any(
            other.state == "in"
            and not any(wait.holder == me for wait in self.claims.waiting(other.ctx.agent_id))
            for other in others)
        # (S3: its opener, reading the room, is one more at work - and is woken to look, for
        # nobody else will say anything.)
        # shortcut: one that then only waits too leaves them waiting for the user, the End
        # button or the room's minutes, as members that all wait do (above).
        if alone and not room.reads and (
                asked or minutes is None or not any(other.state == "waiting" for other in others)):
            raise ToolError(rooms.NOBODY_AT_WORK)
        if alone and room.reads:
            room.heard.set()
        # (Said since the clear: it does not wait, nor stand "waiting" with nobody to set it back.)
        if not member.news.is_set():
            self._set_member(room, member, "waiting")
            async with self._handing_over(ctx):
                await member.news.wait()
            if not self._unread(room, member):  # (K-oda-izle: its Lead stopped following)
                self._set_member(room, member, "in")
                return await self._wait_for_post(room, member, ctx)
        return "something was said in the room: it follows."

    async def _wait_for_item(self: "AgentRunner", room: _Room, member: _Member, ctx: Ctx,  # noqa: C901
                             args: dict) -> str:
        """A member waits for an item another member holds to be finished or dropped, and
        is given what came of it (`wait_for_item`) - at once for one closed already. Refused
        for its own item, for one nobody holds and for one whose holder is not at work
        itself: nobody would close it. Something said in the room meanwhile ends the wait
        too, as it ends `wait_for_post`'s."""
        number = rooms.item_number(args)

        def looked() -> RoomItem:
            with self._factory() as session:
                found = session.scalar(select(RoomItem).where(
                    RoomItem.room_id == room.id, RoomItem.number == number))
            if found is None:
                raise ToolError(f"there is no item {number} on the room's list")
            return found

        def closed(item: RoomItem) -> str | None:
            if item.status not in ("done", "dropped"):
                return None
            return (f"item {number} is {item.status} by "
                    f"{self._name_of(item.holder_agent_id or '')}. What came of it: "
                    f"{board.as_data(item.result or '')}")

        item = looked()
        if said := closed(item):
            return said
        if item.holder_agent_id == member.ctx.agent_id:
            raise ToolError(f"item {number} is yours: there is nobody else to wait for")
        holder = room.members.get(item.holder_agent_id or "")
        if holder is None:
            raise ToolError(f"nobody holds item {number}: take it yourself, or wait for a post")
        me = member.ctx.agent_id
        # (One that waits for a file this member holds is not at work: it waits for it.)
        if holder.state != "in" or any(
            wait.holder == me for wait in self.claims.waiting(holder.ctx.agent_id)
        ):
            state = "waiting for a file you hold" if holder.state == "in" else (
                rooms.STATE[holder.state])
            raise ToolError(
                f"item {number} is held by {holder.ctx.name}, which is not at work itself "
                f"({state}): nobody would close it. Ask it with post_to_room")
        # B-201: as `_wait_for_post`'s, cleared before the record is looked at.
        # shortcut: a close is woken for only from `awaits` on, set after `closed` was read;
        # set it first too if an await is ever put between them.
        member.news.clear()
        if self._unread(room, member):
            return "there is something in the room you have not read yet: it follows."
        member.awaits = number
        # shortcut: on record it waits as for a post ("waiting for a post", to the others
        # and on the room's node); give it a state of its own if that misleads anyone.
        self._set_member(room, member, "waiting")
        try:
            async with self._handing_over(ctx):
                await member.news.wait()
        finally:
            member.awaits = None
        if member.state == "waiting":  # (closed, not said: nobody's post set it back)
            self._set_member(room, member, "in")
        item = looked()
        if said := closed(item):
            return said
        if item.status == "open":
            return (f"item {number} is nobody's again: its holder's part in the room is over. "
                    "Take it yourself, or go on with your part.")
        return f"something was said in the room before item {number} was closed: it follows."

    def decide_spawn(self: "AgentRunner", agent_id: str, decision: str) -> bool:
        """Deliver the user's approve/reject for a proposed sub-agent."""
        future = self._spawn_decisions.get(agent_id)
        if future is None or future.done():
            return False
        future.set_result(decision)
        return True

    def _channel(self: "AgentRunner", ctx: Ctx, sender: str, receiver: str, kind: str,
                 content: str) -> None:
        with self._factory() as session:
            message = ChannelMessage(
                run_id=ctx.run_id, from_agent_id=sender, to_agent_id=receiver, kind=kind,
                content=content,
            )
            session.add(message)
            session.commit()
            payload = channel_message_out(message)
        self.bus.emit(ctx.cid, ctx.run_id, "channel.created", payload)

    @staticmethod
    def last_answer(session, run_id: str, agent_id: str) -> Message | None:
        """What the agent last wrote in the turn's chat, not in a shared place."""
        return session.scalar(
            select(Message)
            .where(
                Message.agent_id == agent_id, Message.run_id == run_id,
                Message.role == "assistant", Message.content != "",
                Message.discussion_id.is_(None), Message.board_post_id.is_(None),
                Message.room_post_id.is_(None),
            )
            .order_by(Message.created_at.desc(), literal_column("messages.rowid").desc())
            .limit(1)
        )

    def _take_plan(self: "AgentRunner", run_id: str, ctx: Ctx, strongest: bool) -> None:
        """A plan turn's last answer is its plan, put before the user to decide on. None
        written, there is nothing to approve: the turn ends as any other."""
        with self._factory() as session:
            run = session.get_one(Run, run_id)
            message = self.last_answer(session, run_id, ctx.agent_id)
            if message is None:
                return
            run.plan = {"text": message.content, "status": "proposed", "model_id": run.model_id,
                        "strongest": strongest, "why": None}
            session.commit()

    def _take_say(self: "AgentRunner", run_id: str, ctx: Ctx) -> None:
        """In a turn whose message asked for it, the `Say:` line that ends the lead's last
        answer is taken off the written answer into the message's `spoken`. Only a last
        line: nothing is cut out of the middle, and a lead that wrote none leaves it empty.
        (Not taken, it is not lost: the turn is over all the same, the line in the answer.)"""
        with contextlib.suppress(Exception), self._factory() as session:
            run = session.get(Run, run_id)
            if run is None or not run.spoken:
                return
            message = self.last_answer(session, run_id, ctx.agent_id)
            if message is None:
                return
            lines = message.content.rstrip().split("\n")
            said = SAY_LINE.match(lines[-1].strip())
            if said is None:
                return
            message.content = "\n".join(lines[:-1]).rstrip()
            message.spoken = said[1].strip()[:400]  # (what is said is cut; the answer is not)
            session.commit()
            self.bus.emit(ctx.cid, run_id, "message.completed", message_out(message))

    def _last_text(self: "AgentRunner", agent_id: str, final_only: bool,
                   after: str | None = None) -> str:
        """What an agent has to show for its work.

        For one that finished, its final answer and nothing else: what it said along
        the way is not a report. For one cut short, the last thing it said. With `after`,
        only what it wrote since that message counts.
        """
        query = select(Message.content).where(
            Message.agent_id == agent_id, Message.role == "assistant",
            Message.discussion_id.is_(None),  # said to a discussion, not reported
        )
        if not final_only:
            query = query.where(Message.content != "")
        with self._factory() as session:
            if after is not None:
                since = session.execute(
                    text("SELECT rowid FROM messages WHERE id = :id"), {"id": after}
                ).scalar_one()
                query = query.where(literal_column("messages.rowid") > since)
            content = session.scalar(
                query.order_by(
                    Message.created_at.desc(), literal_column("messages.rowid").desc()
                ).limit(1)
            )
        return (content or "").strip()

    async def _create_role(self: "AgentRunner", ctx: Ctx, call_id: str,  # noqa: C901
                           args: dict) -> tuple[str, str]:
        """Add a role to the user's list; in ask mode only after they agree."""
        description, instructions = args.get("description", ""), args.get("instructions", "")
        if not isinstance(description, str) or not isinstance(instructions, str):
            raise ToolError("description and instructions must be strings")
        try:
            name = check_name(args.get("name"))
            tools = check_tools(args.get("tools", []))
            # K-uzman: an expert - what it knows and where it reads it; it reads only.
            known = None if args.get("sources") is None and args.get("knows") is None else (
                knowledge.checked(Knowledge.model_validate(
                    {"topic": args.get("knows") or name, "sources": args.get("sources") or []}
                ).model_dump()))
            expert_tools(tools, known)
        except ValidationError as exc:
            raise ToolError(f"knows and sources: {exc.errors()[0]['msg']}") from None
        except ValueError as exc:
            raise ToolError(str(exc)) from None
        # An address it is to read is one more GET of this agent's, a topic to research one more
        # search too: only one that makes them, and the user is shown it below Full auto (the
        # card lists the sources).
        reads_web = bool(known) and knowledge.reads_web(known)
        if known and (missing := knowledge.web_tools(known) - set(ctx.tools)):
            raise ToolError(f"an address or a topic to learn from is a web request "
                            f"({', '.join(sorted(missing))}), and the {ctx.role} role makes none: "
                            "give the expert files of the project, or none")
        with self._factory() as session:
            existing = find_role(session, name)
            project_id = session.get_one(Conversation, ctx.cid).project_id
            taken = existing and _taken(session, existing) or (
                known and knows.folder_taken(session, project_id, known))
            mode = session.get_one(Conversation, ctx.cid).permission_mode
        if taken:
            raise ToolError(taken)
        refused = self._nobody_to_ask(ctx, "role", f"create the role {name}")
        if refused is not None:
            # At every level of the conversation: a new role is the user's to agree to.
            raise _NobodyToAsk(refused)

        if mode == "ask" or (reads_web and mode != "full_auto"):
            proposal = {
                "tool_call_id": call_id, "run_id": ctx.run_id, "agent_id": ctx.agent_id,
                "name": name, "description": description.strip(),
                "instructions": instructions.strip(), "tools": tools, "knowledge": known,
            }
            future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
            self._role_requests[call_id] = (ctx.cid, proposal, future)
            self.bus.emit(ctx.cid, ctx.run_id, "role_request.created", proposal)
            self._update_run(ctx.run_id, ctx.cid, status="waiting_approval")

            def resolved(*_heard) -> None:
                # Once, and the moment the user has spoken: the agent may stand in line
                # for a place before it goes on, and the card is not left to be decided
                # a second time.
                if self._role_requests.pop(call_id, None) is not None:
                    self.bus.emit(
                        ctx.cid, ctx.run_id, "role_request.resolved", {"tool_call_id": call_id}
                    )

            try:
                decision = await self._users_word(ctx, future, resolved)
            finally:
                resolved()
                self._update_run(ctx.run_id, ctx.cid, status="running")
            if decision == "reject":
                return "denied", ROLE_REJECTED.format(name=name)

        with self._factory() as session:
            existing = find_role(session, name)  # the user may have added it meanwhile
            if existing:
                raise ToolError(_taken(session, existing))
            if known and (taken := knows.folder_taken(session, project_id, known)):
                raise ToolError(taken)  # (and its knowledge's folder)
            # In no team (slice 84b): put in the chat's, the Lead would get round the teams the
            # user chose with a role of any tools; the user puts it in one on the Agents page.
            held = chat_teams(session, session.get_one(Conversation, ctx.cid)).teams
            role = Role(
                name=name, description=description.strip(), instructions=instructions.strip(),
                tools=tools, created_by_agent=True,
                kind=landing_kind(session, "plan") if known else landing_kind(session),
            )
            if known:  # (K-bilgi: the chat's project's knowledge; in a chat with no folder, every
                # project's, as an expert's was before)
                row = ProjectKnowledge(project_id=project_id, **knows.columns_of(known))
                session.add(row)
                session.flush()
                role.knows = [{"knowledge_id": row.id, "mode": knows.FULL}]
            session.add(role)
            session.commit()
            payload = role_out(role)
        self.bus.emit(ctx.cid, ctx.run_id, "role.created", payload)
        opened = ("It is in no team, and this chat keeps to its teams: it is opened only once the "
                  "user names it or puts it in one of them." if held else
                  "Open a sub-agent in it with spawn_agent.")
        if known:
            opened += (" It is an expert: it learns its sources when it is asked to (learn), or "
                       "on its Knowledge tab.")
        return "succeeded", f'created role "{name}" with tools: {", ".join(tools)}. {opened}'

    def _mapped(self: "AgentRunner", ctx: Ctx) -> list[dict]:
        """K-bilgi part 4: the knowledge its role uses as a map where it works."""
        with self._factory() as session:
            return [knows.knowledge_of(row) for row in knows.used_here(
                session, find_role(session, ctx.role),
                session.get_one(Conversation, ctx.cid).project_id, knows.MAP_MODE)]

    async def _lookup(self: "AgentRunner", ctx: Ctx, args: dict) -> str:
        """K-bilgi part 3: a question looked up in the pages of the knowledge its role uses here
        (`knows.looked_up`), as the role stands now."""
        if LOOKUP not in ctx.tools:  # (no role lists it: the role's gate does not hold it)
            raise ToolError(f"lookup is not available: the {ctx.role} role uses no knowledge here")
        question, topic = args.get("question"), args.get("topic")
        if not isinstance(question, str) or not question.strip():
            raise ToolError("question: say what you want to know")
        if topic is not None and not isinstance(topic, str):
            raise ToolError("topic: a knowledge's topic, as text")
        with self._factory() as session:
            known = [knows.knowledge_of(row) for row in knows.used_here(
                session, find_role(session, ctx.role),
                session.get_one(Conversation, ctx.cid).project_id)]
        if not known:
            raise ToolError(f"the {ctx.role} role uses no knowledge here any more")
        # (In a thread: it reads every page each knowledge kept.)
        return await asyncio.to_thread(knows.looked_up, ctx.folder, known, question, topic)

    async def _learn(self: "AgentRunner", ctx: Ctx, args: dict) -> tuple[str, str]:  # noqa: C901
        """K-uzman: an expert reads its sources again and has its guide written - as Learn on
        its Knowledge tab, on the model it learns with, else its own; once a turn. Its plain GETs
        go on the user's leave for its sources (`app.knowledge`; `_open_agent` gives it this only
        under an opener that makes web requests); in a turn nobody watches, only to a place the
        trigger names, and where the trigger lets it write (it writes `.koloni/knowledge`), and
        never from a project whose network is off."""
        if LEARN not in ctx.tools:  # (no role lists it: the role's gate does not hold it)
            raise ToolError("learn is not available while answering a message: if your guide "
                            "is old, say so")
        with self._factory() as session:
            project = self._project(session, ctx.cid)
            known = knows.known_here(session, find_role(session, ctx.role),
                                     project.id if project is not None else None)
            if known is None:
                raise ToolError(f"the {ctx.role} role has no sources to learn")
            # (Checked as it runs too: its sources may have changed since the step offered it.)
            if not knowledge.learns_itself(known):
                raise ToolError("this guide is learned only on the Knowledge page: say yours is "
                                "old or not learned yet")
            no_network = project is not None and project.exec_location == "docker" and (
                not project.docker_network)
            searching = knowledge.searching(project)
            chosen = known.get("learn_with")
            provider = session.get(Provider, chosen["provider_id"] if chosen else ctx.provider_id
                                   or "")
            if provider is None:
                raise ToolError("the model it learns with is gone: the user chooses another")
            model = chosen["model_id"] if chosen else ctx.model_name
            if chosen:  # (a model of its own to learn with, held as the Knowledge tab holds it)
                try:
                    allowed(provider, model)
                except NotListed as exc:
                    raise ToolError(f"nothing was learned: {exc}") from None
                if over := over_limit(session, provider):
                    raise ToolError(f"nothing was learned: the model it learns with is {over}")
            name, mode, key = provider.name, mode_of(provider), provider.api_key
        if switched := sorted(knowledge.web_tools(known) & self._off()):
            raise ToolError(f"nothing was learned: {', '.join(switched)} is switched off on the "
                            "Tools page; only the user can switch it on")
        urls = [one for one in known["sources"] if one.startswith(("http://", "https://"))]
        if knowledge.reads_web(known) and no_network:
            raise ToolError("this project's network access is off (its commands run in Docker "
                            "without a network): only the user can switch it on")
        refused = self._nobody_to_ask(ctx, "write", "write its guide in .koloni/knowledge")
        for url in urls:
            refused = refused or self._nobody_to_ask(
                ctx, "host", f"read {web.rule_of(url)} to learn", host=web.rule_of(url))
        if "web_search" in knowledge.web_tools(known):
            refused = refused or self._nobody_to_ask(ctx, "web", "search the web to learn")
        if refused:
            return "failed", refused

        async def search(query: str) -> list[dict]:
            try:
                self._within(self._searches, ctx.cid, "10 searches")
            except ToolError as exc:
                raise web.WebError(str(exc)) from None
            return await searching(query)

        def may(url: str) -> str | None:
            """Unwatched, a page a search found is read only on a site the trigger names."""
            return None if self._nobody_to_ask(ctx, "host", "", host=web.rule_of(url)) in (
                None, "") else "the trigger does not name this site"

        try:
            added = knowledge.additions(args.get("add"))
        except ValueError as exc:
            raise ToolError(str(exc)) from None
        once = (ctx.run_id, knowledge.folder_of(known))
        if once in self._learned_now:
            raise ToolError("it learned in this turn already: answer from that guide")
        self._within(self._requests, ctx.cid, "30 requests")
        client = self.providers.client(provider, model) if chosen else self._model_of(ctx)
        try:
            knowledge.begin(ctx.folder, known)
        except knowledge.LearnError as exc:
            raise ToolError(str(exc)) from None
        self._learned_now.add(once)
        try:
            model = model or (await client.info()).model_id
            with self._factory() as session:  # (by the model that answers: a default too)
                price = knowledge.price_of(session, session.get_one(Provider, provider.id), model)
                write_in = kept.write_in(session, knowledge.GUIDE_KEPT)
                tree = knowledge.tree_limits(session)
            asking = SimpleNamespace(provider=name, provider_id=provider.id, model_name=model)

            async def ask(messages: list[dict]):
                # (Each of its requests is one of the turn's: a big source makes many.)
                try:
                    self._within(self._requests, ctx.cid, "30 requests")
                except ToolError as exc:
                    raise knowledge.LearnError(str(exc)) from None
                answer = None
                try:
                    said, answer = await ask_once(client, model, messages,
                                                  **knowledge.most_written(client))
                    return said, answer
                finally:  # (what it spent is this agent's, under the model asked)
                    self._own_request(ctx, cast(Ctx, asking), mode, answer)

            # shortcut: written in the project, and its brief read there; in a recipe's working
            # copy made before it, `search` reads the parts as they were - read the copy's own
            # if that is met.
            record = await knowledge.learn(
                ctx.folder, known, ask, price, f"{name} · {model}", search, may, added,
                # (nobody clicked: only what changed is written again)
                extend=False, write_in=write_in, tree=tree)
        except knowledge.LearnError as exc:
            raise ToolError(f"nothing was learned: {exc}") from None
        except ModelUnavailable as exc:  # (one it may not run says why: `NotListed`)
            said = str(exc).replace(key, "[key]") if key else str(exc)
            knowledge.fail(ctx.folder, known, f"{name} isn't answering ({said})")
            raise ToolError(f"nothing was learned: {name} isn't answering ({said})") from None
        finally:
            knowledge.end(ctx.folder, known)
        return "succeeded", (f"{knowledge.said_of(record)}. Your guide, as written now, is in "
                             "your instructions from your next step.")
