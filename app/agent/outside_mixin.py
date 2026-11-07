"""Outside the project: the web tools (`app.web`) and their rules, the tools of the MCP servers
the user added (`app.mcp_client`), folders and files outside a copy or the project and the
cards that ask for them, a plain chat's reads, and which teams a turn picks - `OutsideMixin`.
"""

import asyncio
import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import literal_column, select

from app import knows, mcp_client, web
from app.agent.cards import _handed, _shows_a_key, folders_of, within
from app.agent.ctx import NO_FOLDER, Ctx, _NobodyToAsk
from app.agent.merge import _kept
from app.agent.words import (
    ANSWER_PREFIX,
    MAX_WHY,
    NETWORK_OFF,
    NOT_IN_THE_PART,
    SAME_MESSAGE,
    WEB_REJECTED,
)
from app.command_runner import CARRY_ON
from app.commands import new_web_rule, web_rules_here
from app.db.models import (
    AllowedWeb,
    Conversation,
    ConversationTeam,
    McpServer,
    Recipe,
    WebRequest,
    now,
    project_of,
)
from app.roles import LEAD, find_role, pickable
from app.serialize import allowed_web_out, conversation_out, web_request_out
from app.team import quoted
from app.tools import MAX_CHAT_TEAMS, MAX_QUESTION_CHARS, READ_TOOLS, WRITE_TOOLS, ToolError
from app.workspace import (
    LINKED_ELSEWHERE,
    SECRET_CARD,
    CliHome,
    Outside,
    Workspace,
    WorkspaceError,
    has_other_names,
    home_of,
    secret_named,
)

if TYPE_CHECKING:
    from app.agent import AgentRunner

# On the card of a plain chat's read by full path (`_plain_read`): what the user allows (86b).
PLAIN_CARD = "Only this, only now: this chat has no folder."

OUTSIDE_REJECTED = (
    "rejected: the user declined to let you open {path}, outside the project. This is "
    "their decision, not a tool error: do not reach it another way. " + CARRY_ON
)

SECRET_REJECTED = (
    "rejected: the user declined to let you open {path}, a secret file (keys, passwords). "
    "This is their decision, not a tool error: do not reach it another way. Go on without "
    "it, or ask what they would like instead."
)

OF_THE_PROJECT = (
    "{path!r} is a file of the project itself: use the path relative to your working copy"
)


class OutsideMixin:
    # --- the web tools (`app.web`) ---------------------------------------------

    async def _web(self: "AgentRunner", ctx: Ctx, call_id: str, name: str,  # noqa: C901
                   args: dict) -> tuple[str, str]:
        """A web search, an HTTP request or a notification: refused, asked about or let
        through as the turn stands, then made. Returns the call's status and its text.

        What is never reachable is refused first, before anybody is asked. A search and
        a request are asked about unless the conversation runs at full auto or has a
        rule for it; a notification is not - it goes only where the user said. In a turn
        nobody watches nothing is asked: the trigger allows it, or it is not done.
        """
        cid = ctx.cid
        with self._factory() as session:
            conversation = session.get_one(Conversation, cid)
            project = project_of(session, conversation)
            asks = conversation.permission_mode != "full_auto"
            # K-uzman: an expert's search (while answering) is asked below Full auto whatever
            # the rules, and never paid for by the search: the user switched on something
            # that costs.
            expert = knows.known_here(session, find_role(session, ctx.role), (
                project.id if project is not None else None)) is not None
            if project is None:  # a plain chat: the built-in search, and nowhere to notify
                search_url, order, search_agy = None, "builtin", False
                notify_url, form, on_desktop, title = None, "slack", False, "KOLONİ"
                no_network = False
            else:
                search_url, order = project.search_url, project.search_order
                search_agy = project.search_agy
                notify_url, form = project.notify_url, project.notify_format
                on_desktop, title = project.notify_desktop, f"KOLONİ — {project.name}"
                no_network = project.exec_location == "docker" and not project.docker_network
        # The user took the network from this project's commands: an agent's own tools
        # are not a way around that. (The user's own desktop is not the network.)
        network_off = NETWORK_OFF
        if no_network and not (name == "notify" and on_desktop):
            raise ToolError(network_off)
        try:
            if name == "notify":
                refused = self._nobody_to_ask(ctx, "notify", "send a notification")
                if refused:
                    return "failed", refused
                if not notify_url and not on_desktop:
                    raise ToolError("the user has set no notification address for this project")
                message = web.note(args.get("message"))
                # To the desktop and to the address, where the user set both: each is
                # tried, and what is said names the one that failed - never the address.
                went: list[str] = []
                failed: list[str] = []
                if on_desktop:
                    try:
                        if not self._toasts.take(cid):
                            raise ToolError(
                                "at most 6 desktop notifications a minute are shown for "
                                "one conversation: wait before the next"
                            )
                        went.append(await web.show(title, message))
                    except (ToolError, web.WebError) as exc:
                        failed.append(str(exc))
                if notify_url:
                    try:
                        if no_network:
                            raise ToolError(
                                f"not sent to the user's notification address: {network_off}"
                            )
                        self._within(self._requests, cid, "30 requests")
                        went.append(await web.notify(notify_url, message, form))
                    except (ToolError, web.WebError) as exc:
                        failed.append(str(exc))
                if not failed:
                    return "succeeded", " and ".join(went)
                why = "; ".join(failed)
                return "failed", f"{went[0]}, but: {why}" if went else f"error: {why}"
            if name == "web_search":
                query = args.get("query")
                if not isinstance(query, str) or not query.strip():
                    raise ToolError("missing required argument: query")
                query = web.query_of(query)
                refused = self._nobody_to_ask(ctx, "web", "search the web")
                if refused:
                    return "failed", refused
                # (K-fullauto-sorma: at Full auto the expert's search is not asked either -
                # it costs nothing, `paid=not expert`.)
                if refused is None and asks and (expert or not self._web_rules(cid)[0]):
                    asked = WebRequest(kind="search", target=query)
                    if await self._ask_web(ctx, call_id, asked) == "reject":
                        return "denied", WEB_REJECTED.format(what="search")
                self._within(self._searches, cid, "10 searches")
                # A search the API made is paid for in tokens: they are this agent's.
                return "succeeded", await web.search(
                    query, search_url, order,
                    lambda sent, made: self._count_tokens(ctx, sent, made, step=False),
                    agy=search_agy, paid=not expert,
                )
            verb, url, headers, body = web.planned(
                args.get("method"), args.get("url"), args.get("headers"), args.get("body")
            )
            # Before anything is put on record or asked: no leave covers an address that
            # is inside as it is written. A name is not looked up yet - that already
            # leaves this machine, and a name can carry data; it is looked up, and what
            # it stands for judged, once the request may go (`web.fetch`).
            web.host_of(url)
            # What a rule and a trigger name: the scheme, the host and the port, as one.
            host = web.rule_of(url)
            # With nobody watching, what the trigger names is asked with GET and HEAD
            # only: the name got on the list by a yes to "Always allow GET". And with
            # nothing of the agent's own on it: a body or a header carries anything out.
            reads = verb in ("GET", "HEAD")
            bare = body is None and not headers
            refused = self._nobody_to_ask(
                ctx, "host" if reads and bare else "",
                f"make a {'' if reads else verb + ' '}request to {host}"
                f"{'' if bare or not reads else ' with a body or headers of its own'}",
                host=host,
            )
            if refused:
                return "failed", refused
            unwatched = refused == ""
            # A rule is for a GET with nothing of the agent's own on it, here too.
            plain = verb == "GET" and bare
            # At Full auto only a bare GET or HEAD goes unasked - as in a job while the user is
            # away (K-fullauto-sorma): a body, a header or another verb carries anything out.
            if not unwatched and (asks or not (reads and bare)) and not (
                    plain and host in self._web_rules(cid)[1]):
                asked = WebRequest(
                    kind="http", method=verb, target=url, host=host,
                    headers=sorted(headers), body_chars=len(body) if body is not None else None,
                )
                if await self._ask_web(ctx, call_id, asked) == "reject":
                    return "denied", WEB_REJECTED.format(what="request")

            def may(other: str) -> bool:
                """Whether a redirect to another place is followed: a request to it
                needs the leave this one had - the trigger names it, or a rule of the
                conversation covers it. (The user's yes was for the one asked.)"""
                if unwatched:
                    return self._nobody_to_ask(ctx, "host", "", host=other) == ""
                return verb == "GET" and other in self._web_rules(cid)[1]

            self._within(self._requests, cid, "30 requests")
            return "succeeded", await web.request(
                verb, url, headers, args.get("body"), may if unwatched or asks else None
            )
        except web.WebError as exc:
            raise ToolError(str(exc)) from None

    def _within(self: "AgentRunner", rate: web.Rate, cid: str, most: str) -> None:
        if not rate.take(cid):
            raise ToolError(
                f"at most {most} a minute go out of one conversation: wait before the next"
            )

    def _web_rules(self: "AgentRunner", cid: str) -> tuple[bool, set[str]]:
        """What the conversation does on the web without asking, as it stands right
        now: whether it searches, and the hosts it makes GET requests to."""
        with self._factory() as session:
            rules = session.scalars(
                select(AllowedWeb).where(AllowedWeb.conversation_id == cid)
            ).all()
            return (
                any(rule.kind == "search" for rule in rules),
                {rule.host for rule in rules if rule.kind == "host"},
            )

    async def _ask_web(self: "AgentRunner", ctx: Ctx, call_id: str, asked: WebRequest) -> str:
        """Put a search or a request before the user and wait: "once", "always" or
        "reject". "always" keeps a rule for the conversation - searching, or GET from
        that host; for a request that is not a GET, or is one with a body or headers of
        the agent's own (no rule covers it), it is a yes for this once."""
        run_id, cid = ctx.run_id, ctx.cid
        with self._factory() as session:
            asked.run_id, asked.agent_id, asked.tool_call_id = run_id, ctx.agent_id, call_id
            session.add(asked)
            session.commit()
            asked_id, payload = asked.id, web_request_out(asked)
        self.bus.emit(cid, run_id, "web_request.updated", payload)
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._decisions[asked_id] = future
        self._update_run(run_id, cid, status="waiting_approval")

        def heard(decision: str, _waits: bool) -> None:
            # On record the moment the user has spoken: the agent may stand in line for
            # a place before anything goes out, and the decision is not asked for twice.
            with self._factory() as session:
                row = session.get_one(WebRequest, asked_id)
                row.status = "rejected" if decision == "reject" else "approved"
                row.decided_at = now()
                if row.kind in ("http", "page"):
                    row.target = _kept(web.kept_url, row.target)  # decided: as `web.kept` has it
                rule = None
                if decision == "always" and (row.kind in ("search", "page") or (
                    row.method == "GET" and not row.headers and row.body_chars is None
                )):
                    rule = ("search", "") if row.kind == "search" else (
                        "page" if row.kind == "page" else "host", row.host or "")
                    # (A site is the project's: one rule for it in any of its chats.)
                    conversation = session.get_one(Conversation, cid)
                    known = web_rules_here(conversation).where(
                        AllowedWeb.kind == rule[0], AllowedWeb.host == rule[1])
                    if session.scalar(known) is None:
                        session.add(new_web_rule(conversation, *rule))
                session.commit()
                payload = web_request_out(row)
            self.bus.emit(cid, run_id, "web_request.updated", payload)
            if rule:
                self.emit_web_rules(cid)

        try:
            return await self._users_word(ctx, future, heard)
        finally:
            self._decisions.pop(asked_id, None)
            self._update_run(run_id, cid, status="running")

    def emit_web_rules(self: "AgentRunner", cid: str | None, project_id: str | None = None) -> None:
        """The chat's web rules as they stand - and those of every other chat of its project
        the user has open, as they are not put on its record: a site is the project's. With
        no chat (a site changed in Settings, or kept on the project): `project_id`'s."""
        with self._factory() as session:
            if cid is not None:
                project_id = session.get_one(Conversation, cid).project_id
            chats = [cid] if project_id is None else [
                chat for chat in session.scalars(select(Conversation.id).where(
                    Conversation.project_id == project_id))
                if chat == cid or self.bus.watching(chat)]
            payloads = {chat: {"rules": [allowed_web_out(rule) for rule in session.scalars(
                web_rules_here(session.get_one(Conversation, chat))
                .order_by(AllowedWeb.created_at, literal_column("allowed_web.rowid")))]}
                for chat in chats}
        for chat, payload in payloads.items():
            if chat == cid:
                self.bus.emit(cid, None, "allowed_web.updated", payload)
            else:
                self.bus.emit_transient(chat, "allowed_web.updated", payload)

    # --- the tools of the MCP servers the user added (`app.mcp_client`) -------------

    def _mcp(self: "AgentRunner", ctx: Ctx) -> dict[str, tuple[McpServer, dict]]:
        """The tools of the user's MCP servers this agent may use right now, each with
        its server, by the name it is offered under: what is offered, and what a call is
        held to. Read off the record each time: a tool the user switches off, and a
        server they delete or switch off, is gone at once.

        A CLI that works with its own tools is offered them too, among KOLONİ's own over
        its MCP bridge (K-native-tools): KOLONİ runs each call, held to the same rules -
        the CLI is given no server, no command and no secret of one. None for a CLI that
        cannot be handed KOLONİ's tools (agy: `_native_work` says so); none
        in a turn nobody watches; none in a project that runs its commands in Docker
        (the server would run on this machine, outside the container the user chose);
        none in a turn taken to answer somebody, where an agent only reads; none in a side
        of a comparison, which changes nothing outside its copy before the user's choice."""
        if (not ctx.mcp or ctx.answering or not getattr(ctx.model, "collaborates", True)
                or not self._watched(ctx.run_id) or ctx.run_id in self._sides
                or ctx.run_id in self._away_jobs or ctx.run_id in self._backlog_turns):
            return {}
        with self._factory() as session:
            project = self._project(session, ctx.cid)
            if project is None or project.exec_location == "docker":
                return {}
            return mcp_client.usable(session.scalars(
                select(McpServer).where(McpServer.name.in_(ctx.mcp), McpServer.enabled)
                .order_by(McpServer.created_at, literal_column("mcp_servers.rowid"))
            ).all())

    async def _mcp_call(  # noqa: C901
        self: "AgentRunner", ctx: Ctx, call_id: str, name: str, server: McpServer, tool: dict,
        arguments: str, args: dict,
    ) -> tuple[str, str]:
        """A call of a tool of an MCP server: asked about, at every level, unless the user
        marked the tool as running without asking - and always, with the server's own words
        for it, while the user has not trusted it (92) - then run by
        the agent's own process of that server - started now, in an empty folder of its
        own, if it has none (never where the agent works: no file of a project decides
        what is started, and so no working copy is made for it). Nothing is started
        before the yes. Returns the call's status and its text: what the server said is
        data, framed and cut, its secrets hidden."""
        shown = f"{server.name} · {tool['name']}"
        if len(arguments) > mcp_client.MAX_CALL_ARGUMENTS:
            raise ToolError(
                f"the arguments have at most {mcp_client.MAX_CALL_ARGUMENTS} characters")
        try:
            json.dumps(args, allow_nan=False)
        except ValueError:
            # Python reads 1e999 and NaN as numbers; a server cannot be sent them as JSON.
            raise ToolError(
                "the arguments hold a number that is not finite (NaN, Infinity)") from None
        # Slice 92: a server not yet trusted is asked about at every level, whatever the mark;
        # a tool marked "Ask" is the user's word too, over Full auto.
        if not server.trusted or tool["mark"] != "free":
            # As it is sent - and what does not show in it written out: the user's yes
            # is to what they see.
            given = mcp_client.visible(json.dumps(args, ensure_ascii=False))
            if len(given) > 600:
                given = f"{given[:600]}… ({len(given)} characters: the call has all of it)"
            question = (f"May the tool {quoted(tool['name'])} of the MCP server "
                        f"{quoted(server.name)} run? It would be given: {given}")
            if not server.trusted:
                question += mcp_client.watched(server, tool, MAX_QUESTION_CHARS - len(question))
            _status, answer = await self._ask_user(ctx, call_id, {
                "question": question, "options": ["Allow", "Deny"],
            }, leave=True)
            if answer.removeprefix(ANSWER_PREFIX).strip().casefold() != "allow":
                return "denied", WEB_REJECTED.format(what="tool call")
            # As the server stands now: the user may have changed it while they were asked.
            found = self._mcp(ctx).get(name)
            if found is None:
                raise ToolError(f"{name} is no longer available")
            server, tool = found
        key = (ctx.agent_id, server.id)
        try:
            client = self._servers.get(key)
            # One started before the user changed the server is the program before: ended.
            if (client is None or not client.alive
                    or client.started_as != (server.command, server.env)):
                if client is not None:
                    await self._servers.pop(key).end()
                server, refused, yes = await self._mcp_may_start(ctx, call_id, name, server)
                if refused:
                    return "denied", refused
                client = self._servers[key] = await mcp_client.Client.start(
                    server.command, server.env, self.settings.mcp_home)
                if yes:  # kept once it started
                    with self._factory() as session:
                        if (row := session.get(McpServer, server.id)) is not None:
                            row.trusted_files = {p: d for p, d in yes.items() if d}
                            session.commit()
            failed, text = await client.call(tool["name"], args)
        except mcp_client.McpError as exc:
            # It was ended where it failed: the next call starts another.
            self._servers.pop(key, None)
            raise ToolError(f"the MCP server {quoted(server.name)} {exc}") from None
        told = ["The tool says it failed."] if failed else []
        if len(text) > mcp_client.MAX_RESULT:
            told.append(f"{len(text)} characters, cut at {mcp_client.MAX_RESULT}.")
        return "failed" if failed else "succeeded", "\n".join([*told, web.framed(
            text[:mcp_client.MAX_RESULT], f"result of the MCP tool {shown}")])

    async def _mcp_may_start(
        self: "AgentRunner", ctx: Ctx, call_id: str, name: str, server: McpServer,
    ) -> tuple[McpServer, str | None, dict | None]:
        """97: a server that runs code from a folder agents write in (`mcp_client.in_project`)
        is started only once the user says so - at every level, a tool that runs without
        asking too: an agent could have changed what it runs, and it runs as the user,
        outside every agent's card. The yes holds for that code as it is now
        (`trusted_files`, kept by the caller once it started); changed, it is asked about
        again. In one turn one such card of a server is up at a time, and its answer stands
        for the rest of the turn: a no for that server, a yes for that code as it was
        answered (not for code too big to hash: asked every time). Returns the server as it
        stands, why it is not started (None: it is), and what a yes was given to. (Nobody
        watching, `_ask_user` refuses: no server's tool is offered there anyway, `_mcp`.)"""
        said = self._mcp_said.setdefault(ctx.run_id, {})
        locks = self._mcp_asking.setdefault(ctx.run_id, {})
        async with locks.setdefault(server.id, asyncio.Lock()):
            while True:
                with self._factory() as session:
                    folders = mcp_client.agents_folders(session)
                    row = session.get(McpServer, server.id)
                    kept = row.trusted_files if row else {}
                files = await asyncio.to_thread(mcp_client.in_project, server.command, folders)
                if mcp_client.trusted(kept, files):
                    return server, None, None
                runs = mcp_client.runs(files)
                no = (f"The user said not to start the MCP server {quoted(server.name)}: it runs "
                      f"{runs} from a project agents can change.")
                if server.id in said and (not said[server.id][1] or (
                        said[server.id][0] == files and None not in files.values())):
                    return server, None if said[server.id][1] else no, files
                _status, answer = await self._ask_user(ctx, call_id, {
                    "question": f"The MCP server {quoted(server.name)} runs {runs} from your "
                                "project, which agents can change. Start it anyway?",
                    "options": ["Start it", "Don't start"],
                }, leave=True)
                if answer.removeprefix(ANSWER_PREFIX).strip().casefold() != "start it":
                    said[server.id] = (files, False)
                    return server, no, None
                found = self._mcp(ctx).get(name)
                if found is None:
                    raise ToolError(f"{name} is no longer available")
                server = found[0]
                # Changed while the user was asked (the code, or the server): asked again.
                if await asyncio.to_thread(
                        mcp_client.in_project, server.command, folders) == files:
                    said[server.id] = (files, True)
                    return server, None, files

    def _also_in(self: "AgentRunner", ctx: Ctx, write: bool = True) -> list[str]:
        """The folders outside the project this agent also works in, as the record has
        them now - and, not for a `write`, those it may only read in too (slice 75)."""
        listed, read = self._lists(ctx)
        return listed if write else [*listed, *read]

    def _lists(self: "AgentRunner", ctx: Ctx) -> tuple[list[str], list[str]]:
        """The folders to write in and those to read in only, as the record has them now -
        with those lent to this agent alone on an ask_folder card."""
        lent = self._lent.get(ctx.agent_id, {})
        with self._factory() as session:
            project = self._project(session, ctx.cid)
            conversation = session.get_one(Conversation, ctx.cid)

            def joined(access: str) -> list[str]:
                return list(dict.fromkeys([*folders_of(project, conversation, access),
                                           *(f for f, given in lent.items() if given == access)]))

            return joined("write"), joined("read")

    def _read_only_over(self: "AgentRunner", ctx: Ctx, target: Path) -> Path | None:
        """The folder to read in only that holds `target` where no folder to write in inside
        it does - the most specific list wins: a folder to write in around one to read in
        does not open it to changes - or None."""
        write, read = (list(map(Path, folders)) for folders in self._lists(ctx))
        for folder in read:
            if within(target, folder) and not any(
                within(target, w) and within(w, folder) for w in write
            ):
                return folder
        return None

    async def _outside(  # noqa: C901
        self: "AgentRunner", ctx: Ctx, call_id: str, ws: Workspace, name: str, args: dict
    ) -> Workspace:
        """Where a file tool or a command may go: the project, the folders the project
        and the conversation also work in (read off the record each time) - and a path
        outside all of them once the user says so, at every level: Full auto is leave
        for the project. The call is `pending` while it waits. What KOLONİ never opens
        is refused by the tool itself, nobody asked. A write of an agent that works in a
        copy (a sub-agent, a room's member) is asked about every time: the copy has none
        of these folders, and what is written there goes straight in. So is a command of
        a side of a comparison: before the user's choice nothing of it goes outside its copy."""
        # A change - a command too - goes unasked only into a folder to write in.
        changes = name in WRITE_TOOLS or name == "run_command"
        apart = name in WRITE_TOOLS or (name == "run_command" and (
            ctx.run_id in self._sides or ctx.run_id in self._away_jobs))
        listed = [] if self._copy_owner(ctx) and apart else self._also_in(ctx, write=changes)
        ws = Workspace(ws.root, ws.links, listed)
        path = args.get("cwd" if name == "run_command" else "path") or "."
        access = "write" if changes else "read"  # what "Allow this folder" gives
        try:
            target = ws.resolve(path)
        except Outside as exc:
            folder = exc.folder
        except CliHome as exc:
            # A CLI's settings for the whole computer (K-ev-klasoru): one file, read or written
            # on the user's word each time, at every level - no "Allow this folder", no rule.
            # shortcut: list_dir and search there are refused (a walk passes such a folder by,
            # and a search runs in a process of its own); open them the day a user needs them.
            # shortcut: a CLI with tools of its own reaching its home folder is refused
            # (`_native_outside`), and a command that names such a file is not held to this
            # card; the change's undo (`for_change`) is refused too - nothing grants it there.
            if name != "read_file" and name not in WRITE_TOOLS:
                return ws  # the tool says what is wrong with it
            await self._ask_outside(ctx, call_id, path, None, access, why=exc.card,
                                    shown=exc.real)
            return Workspace(ws.root, ws.links, ws.also, granted=exc.real)
        except (WorkspaceError, OSError):
            return ws  # the tool says what is wrong with it
        else:
            # An agent that works in a copy, at a path of the project itself - through a listed
            # folder that holds the project (slice 75), or by its full path before its copy is
            # made: as from the copy (below), refused - the project is changed by Take in only.
            owner = self._copy_owner(ctx)
            # (Not one through the copy's links into the project's own: `_shared` holds those.)
            linked = any(within(target, there) for there in ws.links.values())
            if owner is not None and self._copies.get(owner, True) is not None and (
                    Workspace(ctx.folder).is_own(target)) and not linked and (
                    not ws.is_own(target) or Path(path).is_absolute()
                    and self._copies.get(owner) is None) and not (
                    await self._reads_left_out(ctx, name, target)):  # (as below, `Outside`)
                raise ToolError(OF_THE_PROJECT.format(path=path))
            # K-buyuk-proje: another part, by its path in a copy of one part: not there - said
            # so, and where to read it, rather than "not found".
            copy = self._copies.get(owner or "")
            if copy is not None and copy.part and ws.is_own(target) and not os.path.lexists(
                    target) and not copy.holds(ws.rel(target)):
                raise ToolError(NOT_IN_THE_PART.format(
                    path=path, part=copy.part, project=copy.project))
            # A change in a folder to read in only that a folder to write in holds is
            # asked about all the same, at every level.
            over = (self._read_only_over(ctx, target)
                    if changes and not ws.is_own(target) else None)
            if over is not None:
                await self._ask_outside(ctx, call_id, path, target if target.is_dir()
                                        else target.parent, access)
            # So is a command that names a folder to read in only by its full path. (What
            # it names another way, or a program does unnamed, is not seen.)
            named = self._read_named(ctx, args.get("command")) if name == "run_command" else None
            if over is None and named is not None:
                await self._ask_outside(ctx, call_id, str(named), named, access)
            # A secret (.env, a key) is opened only on the user's word, each time and at every
            # level: what it holds goes to the model's provider - by a write too, whose
            # answer ("not found") tells what it holds. (Out of the project one is never
            # opened at all: `Workspace.resolve`. One that is not there holds nothing.)
            # shortcut: a command (`cat .env`) is not looked into for a secret: at Full auto
            # it runs unasked - upgrade when commands are held by what they read (slice 89).
            # shortcut: a hard link in the project is read as any file, though its other
            # name may be a secret's: an agent makes one only with a command, which can read
            # the secret itself, and package managers (pnpm) fill projects with them; hold
            # them with the commands (slice 89).
            # So is a file read_file would show a key in, whatever its name: asked, not
            # masked - an agent writes back what it read, and `***` would replace the key.
            # (A search hides such a key in its lines instead: `_read`.)
            # shortcut: a write's answer and a CLI's own Read and Grep are not looked into by
            # what a file holds; look there too if a key is seen to pass.
            # shortcut: a fake key of a test's (sk-test-...) is a card at every read and
            # refused nobody watching (the well-known samples are not: `holds_a_key`); let
            # one be allowed for the chat if that tires.
            if (name == "read_file" or name in WRITE_TOOLS) and target.is_file() and (
                secret_named(path, ws.rel(target)) or name == "read_file"
                and await asyncio.to_thread(_shows_a_key, ws, path)
            ):
                await self._ask_outside(ctx, call_id, path, None)
            return ws
        self._not_the_store(path, folder)
        if Workspace(ctx.folder).is_own(folder):
            real = Path(os.path.realpath(ws.root / path))
            if await self._reads_left_out(ctx, name, real):
                # Granted this path alone, for this call; a secret's name is still refused
                # (`Workspace.resolve`), and a key in it still asked about.
                ws = Workspace(ws.root, ws.links, [*ws.also, real])
                if name == "read_file" and await asyncio.to_thread(_shows_a_key, ws, path):
                    await self._ask_outside(ctx, call_id, path, None)
                return ws
            # An agent in a working copy, naming a file of the project itself: what it
            # changes goes into its copy, and is taken in from there.
            raise ToolError(OF_THE_PROJECT.format(path=path))
        await self._ask_outside(ctx, call_id, path, folder, access)
        # shortcut: "once" opens the path's whole folder for this one call - a search there
        # goes through all of it; hold it to the path alone if that is ever too much.
        return Workspace(ws.root, ws.links, [*ws.also, folder])

    async def _reads_left_out(self: "AgentRunner", ctx: Ctx, name: str, target: Path) -> bool:
        """K-kopya-git: whether a read tool may open a place of the project itself from the
        agent's copy - one a copy of what git tracks left out (`Copy.left_out`), or another part
        than the one a copy of a part holds (K-buyuk-proje). A read alone, never a change or a
        command.
        shortcut: KOLONİ's own read tools; a CLI's own Read there - another part's too - is as
        any read outside its copy: let its hook through too if CLIs are seen to need it."""
        copy = self._copies.get(self._copy_owner(ctx) or "")
        return name in READ_TOOLS and copy is not None and bool(copy.git or copy.part) and (
            await asyncio.to_thread(copy.left_out, target))

    def _read_named(self: "AgentRunner", ctx: Ctx, command: object) -> Path | None:
        """A folder to read in only (and not one to write in, too) that a command's text
        names by its full path - in any case, with either slash, quoted or not, and as a
        whole name: `D:\\ro` is not `D:\\robots` - or None."""
        if not isinstance(command, str):
            return None
        said = command.casefold().replace("/", "\\")
        write, read = self._lists(ctx)
        # (In a job while the user is away a folder to write in too: nothing of it leaves the
        # copy unasked - as a file tool's write there is asked, `_outside`.)
        night = ctx.run_id in self._away_jobs
        for folder in [*read, *(write if night else [])]:
            named = re.escape(folder.casefold().replace("/", "\\").rstrip("\\"))
            if (night or folder not in write) and re.search(
                    named + r"(?![^\\\s\"'`;|&<>(),])", said):
                return Path(folder)
        return None

    def _not_the_store(self: "AgentRunner", path: str, folder: Path, holds: bool = True) -> None:
        """The skills' store is never opened, nobody asked: as `never` has it for the app's
        own runtime folder, here also where a test's settings put it. Not `holds`: a folder
        for a list may hold it, as it may hold any place never opened (`listed_folder`)."""
        store = (self.settings.runtime_root / "skills").resolve()
        if folder.is_relative_to(store) or holds and store.is_relative_to(folder):
            raise ToolError(f"{path!r} is never opened: it holds KOLONİ's own store of skills")

    async def _ask_outside(self: "AgentRunner", ctx: Ctx, call_id: str, path: str,
                           folder: Path | None,
                           access: str = "write", why: str | None = None,
                           shown: Path | None = None) -> str:
        """Ask the user whether an agent may go to `path`, outside the project and the
        folders it also works in: the call is `pending` until they say. "folder" puts
        `folder` on the conversation's list for `access` - only one that is there (a new
        folder is allowed once: what it would hold is not known yet). No `folder`: any yes
        is for this one call - of `path`, a secret file in the project, or one named in a
        chat with no folder, which the card says `why` and `shown` where it leads. Their
        word ("once" or "folder"); _NobodyToAsk where nobody is there to ask, or the user
        says no."""
        why = why or (SECRET_CARD if folder is None else None)
        secret = why == SECRET_CARD
        wanted = (f"open {quoted(path)}, a secret file (keys, passwords)" if secret
                  else f"open {quoted(path)}, outside the project")
        refused = self._nobody_to_ask(ctx, "outside", wanted)
        if refused:
            raise _NobodyToAsk(refused)
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._outside_asks[call_id] = future
        # On the card: where the path really leads, which "Allow this folder" would open -
        # or, `shown`, the one file or folder a yes reads (no folder is opened by it).
        self._set_call(ctx.cid, call_id, status="pending",
                       outside_folder=str(shown) if shown else
                       str(folder) if folder and folder.is_dir() else None,
                       why_asked=why)
        self._update_run(ctx.run_id, ctx.cid, status="waiting_approval")

        def resolved(*_heard) -> None:
            # Once, and the moment the user has spoken: the agent may stand in line for
            # a place before it goes on, and the card is not left to be decided again.
            if self._outside_asks.pop(call_id, None) is not None:
                self._set_call(ctx.cid, call_id, status="running")

        try:
            word = await self._users_word(ctx, future, resolved)
        finally:
            resolved()
            self._update_run(ctx.run_id, ctx.cid, status="running")
        if word == "reject":
            rejected = SECRET_REJECTED if secret else OUTSIDE_REJECTED
            raise _NobodyToAsk(rejected.format(path=quoted(path)))
        if folder is not None and word == "folder" and folder.is_dir():
            field = "also_in" if access == "write" else "read_in"
            with self._factory() as session:
                conversation = session.get_one(Conversation, ctx.cid)
                if str(folder) not in getattr(conversation, field):
                    setattr(conversation, field, [*getattr(conversation, field), str(folder)])
                    session.commit()
                payload = conversation_out(conversation)
            self.bus.emit(ctx.cid, None, "conversation.updated", payload)
        return word

    def _add_dirs(self: "AgentRunner", ctx: Ctx) -> tuple[str, ...]:
        """The folders to write in that a CLI with tools of its own is given (`--add-dir`):
        none that holds a place KOLONİ never opens, or a folder to read in only."""
        write, read = self._lists(ctx)
        return tuple(f for f in write if _handed(f, write, read))

    async def _plain_read(self: "AgentRunner", ctx: Ctx, call_id: str, name: str,
                          args: dict) -> tuple[Workspace, dict]:
        """Where a chat with no folder reads a file, or lists a folder, the user names (slice
        86b): by its full path ("~" for the home folder), on the user's word each time, for
        that one call - put on no list - and the call's arguments with where it really
        leads. Judged as any path outside a project is: a secret, a place KOLONİ never opens
        or a hard link is refused, nobody asked."""
        path = args.get("path")
        path = home_of(path) if isinstance(path, str) else path
        if not isinstance(path, str) or not Path(path).is_absolute():
            raise ToolError(f"path: give the full path of the file or folder - {NO_FOLDER}")
        named = Path(os.path.abspath(path))
        # A root nothing named is in (it is never made): every path is judged as outside.
        ws = Workspace(self.settings.runtime_root / "no-folder",
                       also=[named if name == "list_dir" else named.parent])
        why = PLAIN_CARD
        try:
            target = ws.resolve(path)
        except CliHome as exc:  # (a file of a CLI's settings: its own card, for read_file only)
            if name != "read_file":
                raise ToolError(str(exc)) from None
            target, why = exc.real, exc.card
            ws = Workspace(ws.root, also=ws.also, granted=target)
        except WorkspaceError as exc:  # (a link that leads elsewhere too: named as it is)
            raise ToolError(str(exc)) from None
        if ws.is_own(target):  # (in the root: only through a link somebody made there)
            raise ToolError(f"{path!r} is never opened: it is in KOLONİ's own runtime")
        # (Before the card: the user is not asked for what would fail after their yes.)
        if target.is_file() and has_other_names(target):
            raise ToolError(f"{path!r} is not read: {LINKED_ELSEWHERE}")
        # The card names where it really leads ("DOCUME~1", "a\..\.."), as the user knows it.
        await self._ask_outside(ctx, call_id, str(target), None, "read", why=why, shown=target)
        return ws, {**args, "path": str(target)}

    def _no_pick(self: "AgentRunner", ctx: Ctx, conversation: Conversation) -> str | None:
        """Why this agent picks no team for the chat now (slice 84b); None: it may. A Lead on a
        CLI session is offered it with KOLONİ's other tools, over the MCP bridge (`_offered`);
        one that cannot be handed KOLONİ's tools is not."""
        if ctx.role != LEAD or ctx.depth or ctx.answering or ctx.run_id in self._sides or (
                not getattr(ctx.model, "collaborates", True)):
            return "pick_teams is the Orchestrator's, at its own work"
        if conversation.teams_mode == "manual":
            return ("this chat's teams are the user's (Manual): they are the teams you may use - "
                    f"open only those the message needs; {SAME_MESSAGE}; the user changes them "
                    "in Teams for this chat")
        if conversation.teams_mode != "lead":
            return "this chat works with no teams: open any role with spawn_agent"
        return None

    def _pick_teams(self: "AgentRunner", ctx: Ctx, args: dict) -> str:
        """The Lead's pick of the chat's teams, each with its recipe and why (slice 84b): the
        chat's rows from now on, in place of its picks before.
        shortcut: a plan turn's picks stand at once, before the user's yes (and after a no), and
        the plan card does not show them (design §3); hold them on the plan if that is felt."""
        picks = args.get("teams")
        if not isinstance(picks, list) or not 1 <= len(picks) <= MAX_CHAT_TEAMS or not all(
                isinstance(one, dict) for one in picks):
            raise ToolError(f"teams is a list of 1 to {MAX_CHAT_TEAMS} picks, each "
                            "{team, recipe (optional), why}")
        with self._factory() as session:
            conversation = session.get_one(Conversation, ctx.cid)
            if why_not := self._no_pick(ctx, conversation):
                raise ToolError(why_not)
            teams = {team.name.casefold(): team for team in pickable(session)}
            recipes = {r.name.casefold(): r for r in session.scalars(select(Recipe))}
            rows: list[ConversationTeam] = []
            said: list[str] = []
            for at, one in enumerate(picks):
                name = " ".join(str(one.get("team") or "").split())
                team = teams.get(name.casefold())
                if team is None:
                    raise ToolError(f"{name or 'a team'} is not a team you may pick. Teams: "
                                    f"{', '.join(t.name for t in teams.values()) or 'none'}")
                if any(row.team_id == team.id for row in rows):
                    raise ToolError(f"{team.name} is picked twice: once is enough")
                wanted = " ".join(str(one.get("recipe") or "").split())
                recipe = recipes.get(wanted.casefold())
                if wanted and recipe is None:
                    raise ToolError(f"{wanted} is not a recipe. Recipes: "
                                    f"{', '.join(r.name for r in recipes.values()) or 'none'}")
                why = " ".join(str(one.get("why") or "").split())
                if not why or len(why) > MAX_WHY:
                    raise ToolError(f"why is one sentence, at most {MAX_WHY} characters, "
                                    f"for {team.name}")
                rows.append(ConversationTeam(
                    team_id=team.id, recipe_id=recipe.id if recipe else None, picked_by="lead",
                    why=why, position=at))
                said.append(team.name)
            conversation.teams = rows
            session.commit()
            self._picked.add(ctx.run_id)
            payload = conversation_out(conversation)
            ways = [self._way(session, row, ctx.root) for row in rows]
        self.bus.emit(ctx.cid, None, "conversation.updated", payload)
        return (f"picked {', '.join(said)}: spawn_agent opens only their roles now - with a "
                "recipe, only its step's, one step after another: KOLONİ moves it on as the "
                "step's agents finish." + "".join(f"\n{way}" for way in ways if way))
