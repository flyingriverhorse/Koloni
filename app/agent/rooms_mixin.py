"""The role and knowledge tools (`_create_role`, `_lookup`, `_learn`), a sub-agent's yes or no,
the channel between agents and a turn's last answer - `RoomsMixin`, named for the rooms it ran
until 0.1.10 (rooms are gone: a discussion lets agents talk, sub-agents work at once).
"""

import asyncio
import contextlib
import re
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from pydantic import ValidationError
from sqlalchemy import literal_column, select, text
from sqlalchemy.orm import Session

from app import knowledge, knows, web
from app import memory as kept
from app.agent.ctx import Ctx
from app.agent.words import LEADS_LATER
from app.api.usage import over_limit
from app.db.models import (
    ChannelMessage,
    Conversation,
    Message,
    ProjectKnowledge,
    Provider,
    Role,
    Run,
)
from app.model_client import ModelUnavailable
from app.providers import NotListed, allowed, ask_once, mode_of
from app.roles import (
    LEARN,
    LOOKUP,
    chat_teams,
    check_name,
    check_tools,
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
)
from app.tools import ToolError

if TYPE_CHECKING:
    from app.agent import AgentRunner

# The line, as the lead writes it: plain or in bold.
SAY_LINE = re.compile(r"^\*{0,2}Say:\*{0,2}\s*(.+)$")

# R179: what the chat is told once, a Codex Lead in native mode at a chat with a recipe. R188: it
# may open the team's roles over MCP, and then the recipe runs - only it often does not.
CODEX_NATIVE_NO_RECIPE = (
    "Codex in native mode often does the work itself instead of running "
    "this chat's teams and recipes — for them to run every time, switch its "
    "'How it runs' to step on the Models page."
)

ROLE_REJECTED = (
    "rejected: the user declined to create the role {name}. This is their decision, not a "
    "tool error: do not create it again under another name. Use an existing role, or stop "
    "and ask what they would like instead."
)


def _taken(session: Session, role: Role) -> str:
    """What an agent that would make a role of a name already taken is told."""
    if is_team_lead(session, role):  # (slice 63a: no agent is opened in one yet)
        return (
            f"there is already a role named {role.name}: a team's coordinator - "
            f"{LEADS_LATER}. Make no role for it"
        )
    return f"there is already a role named {role.name}; open a sub-agent in it with spawn_agent"


class RoomsMixin:
    def _native_no_recipe(self: "AgentRunner", ctx: Ctx) -> None:
        """R179 (live): a Codex Lead in native mode never started its chat's recipe - no team
        strip, no sub-agent, it wrote the code itself; in step mode it does. Said once a chat, as
        a Lead's turn starts (after `_by_how_hard`, which may move it to another model) - at a
        chat with a team, its recipe or none: either needs spawn_agent, which it never called."""
        if ctx.depth or not getattr(ctx.model, "native", False):
            return
        with self._factory() as session:
            provider = session.get(Provider, ctx.provider_id or "")
            if (
                provider is None
                or provider.kind != "codex_cli"
                or not self._rows(session, ctx.cid)
                or session.scalar(
                    select(Message.id)
                    .where(
                        Message.conversation_id == ctx.cid,
                        Message.role == "koloni",
                        Message.content == CODEX_NATIVE_NO_RECIPE,
                    )
                    .limit(1)
                )
            ):
                return
        self._koloni_line(ctx.cid, ctx.run_id, CODEX_NATIVE_NO_RECIPE)

    def decide_spawn(self: "AgentRunner", agent_id: str, decision: str) -> bool:
        """Deliver the user's approve/reject for a proposed sub-agent."""
        future = self._spawn_decisions.get(agent_id)
        if future is None or future.done():
            return False
        future.set_result(decision)
        return True

    def _channel(
        self: "AgentRunner", ctx: Ctx, sender: str, receiver: str, kind: str, content: str
    ) -> None:
        with self._factory() as session:
            message = ChannelMessage(
                run_id=ctx.run_id,
                from_agent_id=sender,
                to_agent_id=receiver,
                kind=kind,
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
                Message.agent_id == agent_id,
                Message.run_id == run_id,
                Message.role == "assistant",
                Message.content != "",
                Message.discussion_id.is_(None),
                Message.board_post_id.is_(None),
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
            run.plan = {
                "text": message.content,
                "status": "proposed",
                "model_id": run.model_id,
                "strongest": strongest,
                "why": None,
            }
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

    def _last_text(
        self: "AgentRunner", agent_id: str, final_only: bool, after: str | None = None
    ) -> str:
        """What an agent has to show for its work.

        For one that finished, its final answer and nothing else: what it said along
        the way is not a report. For one cut short, the last thing it said. With `after`,
        only what it wrote since that message counts.
        """
        query = select(Message.content).where(
            Message.agent_id == agent_id,
            Message.role == "assistant",
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

    async def _create_role(
        self: "AgentRunner", ctx: Ctx, call_id: str, args: dict
    ) -> tuple[str, str]:
        """Add a role to the user's list; in ask mode only after they agree."""
        description, instructions = args.get("description", ""), args.get("instructions", "")
        if not isinstance(description, str) or not isinstance(instructions, str):
            raise ToolError("description and instructions must be strings")
        name, tools, known = self._create_role_args(args)
        # An address it is to read is one more GET of this agent's, a topic to research one more
        # search too: only one that makes them, and the user is shown it below Full auto (the
        # card lists the sources).
        reads_web = bool(known) and knowledge.reads_web(known)
        if known and (missing := knowledge.web_tools(known) - set(ctx.tools)):
            raise ToolError(
                f"an address or a topic to learn from is a web request "
                f"({', '.join(sorted(missing))}), and the {ctx.role} role makes none: "
                "give the expert files of the project, or none"
            )
        with self._factory() as session:
            existing = find_role(session, name)
            project_id = session.get_one(Conversation, ctx.cid).project_id
            taken = (
                existing
                and _taken(session, existing)
                or (known and knows.folder_taken(session, project_id, known))
            )
            mode = session.get_one(Conversation, ctx.cid).permission_mode
        if taken:
            raise ToolError(taken)

        if mode == "ask" or (reads_web and mode != "full_auto"):
            proposal = {
                "tool_call_id": call_id,
                "run_id": ctx.run_id,
                "agent_id": ctx.agent_id,
                "name": name,
                "description": description.strip(),
                "instructions": instructions.strip(),
                "tools": tools,
                "knowledge": known,
            }
            decision = await self._create_role_card(ctx, call_id, proposal)
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
                name=name,
                description=description.strip(),
                instructions=instructions.strip(),
                tools=tools,
                created_by_agent=True,
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
        opened = (
            "It is in no team, and this chat keeps to its teams: it is opened only once the "
            "user names it or puts it in one of them."
            if held
            else "Open a sub-agent in it with spawn_agent."
        )
        if known:
            opened += (
                " It is an expert: it learns its sources when it is asked to (learn), or "
                "on its Knowledge tab."
            )
        return "succeeded", f'created role "{name}" with tools: {", ".join(tools)}. {opened}'

    def _create_role_args(self: "AgentRunner", args: dict) -> tuple[str, list[str], dict | None]:
        """`_create_role`'s name, tools and what it knows, as they were checked."""
        try:
            name = check_name(args.get("name"))
            tools = check_tools(args.get("tools", []))
            # K-uzman: an expert - what it knows and where it reads it; it reads only.
            known = (
                None
                if args.get("sources") is None and args.get("knows") is None
                else (
                    knowledge.checked(
                        Knowledge.model_validate(
                            {
                                "topic": args.get("knows") or name,
                                "sources": args.get("sources") or [],
                            }
                        ).model_dump()
                    )
                )
            )
            expert_tools(tools, known)
        except ValidationError as exc:
            raise ToolError(f"knows and sources: {exc.errors()[0]['msg']}") from None
        except ValueError as exc:
            raise ToolError(str(exc)) from None
        return name, tools, known

    async def _create_role_card(self: "AgentRunner", ctx: Ctx, call_id: str, proposal: dict) -> str:
        """`_create_role`'s card: the role put before the user, and their word on it."""
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
        return decision

    def _mapped(self: "AgentRunner", ctx: Ctx) -> list[dict]:
        """K-bilgi part 4: the knowledge its role uses as a map where it works."""
        with self._factory() as session:
            return [
                knows.knowledge_of(row)
                for row in knows.used_here(
                    session,
                    find_role(session, ctx.role),
                    session.get_one(Conversation, ctx.cid).project_id,
                    knows.MAP_MODE,
                )
            ]

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
            known = [
                knows.knowledge_of(row)
                for row in knows.used_here(
                    session,
                    find_role(session, ctx.role),
                    session.get_one(Conversation, ctx.cid).project_id,
                )
            ]
        if not known:
            raise ToolError(f"the {ctx.role} role uses no knowledge here any more")
        # (In a thread: it reads every page each knowledge kept.)
        return await asyncio.to_thread(knows.looked_up, ctx.folder, known, question, topic)

    async def _learn(self: "AgentRunner", ctx: Ctx, args: dict) -> tuple[str, str]:
        """K-uzman: an expert reads its sources again and has its guide written - as Learn on
        its Knowledge tab, on the model it learns with, else its own; once a turn. Its plain GETs
        go on the user's leave for its sources (`app.knowledge`; `_open_agent` gives it this only
        under an opener that makes web requests); never from a project whose network is off."""
        if LEARN not in ctx.tools:  # (no role lists it: the role's gate does not hold it)
            raise ToolError(
                "learn is not available while answering a message: if your guide is old, say so"
            )
        with self._factory() as session:
            project = self._project(session, ctx.cid)
            known = knows.known_here(
                session, find_role(session, ctx.role), project.id if project is not None else None
            )
            if known is None:
                raise ToolError(f"the {ctx.role} role has no sources to learn")
            # (Checked as it runs too: its sources may have changed since the step offered it.)
            if not knowledge.learns_itself(known):
                raise ToolError(
                    "this guide is learned only on the Knowledge page: say yours is "
                    "old or not learned yet"
                )
            no_network = (
                project is not None
                and project.exec_location == "docker"
                and (not project.docker_network)
            )
            searching = knowledge.searching(project)
            chosen, provider, model = self._learn_with(session, ctx, known)
            name, mode, key = provider.name, mode_of(provider), provider.api_key
        if switched := sorted(knowledge.web_tools(known) & self._off()):
            raise ToolError(
                f"nothing was learned: {', '.join(switched)} is switched off on the "
                "Tools page; only the user can switch it on"
            )
        if knowledge.reads_web(known) and no_network:
            raise ToolError(
                "this project's network access is off (its commands run in Docker "
                "without a network): only the user can switch it on"
            )
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
        record = await self._learn_now(
            ctx, known, client, model, provider, name, mode, key, searching, added
        )
        return "succeeded", (
            f"{knowledge.said_of(record)}. Your guide, as written now, is in "
            "your instructions from your next step."
        )

    def _learn_with(
        self: "AgentRunner", session: Session, ctx: Ctx, known: dict
    ) -> tuple[dict | None, Provider, str | None]:
        """`_learn`'s model: the one chosen for its sources (and that), else its own - with its
        provider."""
        chosen = known.get("learn_with")
        provider = session.get(Provider, chosen["provider_id"] if chosen else ctx.provider_id or "")
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
        return chosen, provider, model

    async def _learn_now(
        self: "AgentRunner",
        ctx: Ctx,
        known: dict,
        client,
        model: str | None,
        provider: Provider,
        name: str,
        mode: str | None,
        key: str | None,
        searching,
        added,
    ):
        """`_learn`'s learning itself, begun by its caller: the record of what was learned."""

        async def search(query: str) -> list[dict]:
            try:
                self._within(self._searches, ctx.cid, "10 searches")
            except ToolError as exc:
                raise web.WebError(str(exc)) from None
            return await searching(query)

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
                    said, answer = await ask_once(
                        client, model, messages, **knowledge.most_written(client)
                    )
                    return said, answer
                finally:  # (what it spent is this agent's, under the model asked)
                    self._own_request(ctx, cast(Ctx, asking), mode, answer)

            # shortcut: written in the project, and its brief read there; in a recipe's working
            # copy made before it, `search` reads the parts as they were - read the copy's own
            # if that is met.
            record = await knowledge.learn(
                ctx.folder,
                known,
                ask,
                price,
                f"{name} · {model}",
                search,
                added=added,
                # (nobody clicked: only what changed is written again)
                extend=False,
                write_in=write_in,
                tree=tree,
            )
        except knowledge.LearnError as exc:
            raise ToolError(f"nothing was learned: {exc}") from None
        except ModelUnavailable as exc:  # (one it may not run says why: `NotListed`)
            said = str(exc).replace(key, "[key]") if key else str(exc)
            knowledge.fail(ctx.folder, known, f"{name} isn't answering ({said})")
            raise ToolError(f"nothing was learned: {name} isn't answering ({said})") from None
        finally:
            knowledge.end(ctx.folder, known)
        return record
