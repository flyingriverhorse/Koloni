"""Files the user attached (slice 85b): what a step sends of them, what an agent is told and
reads of them, where they are saved, and the files handed between agents; and, beside them,
recall's output and the shared notes an agent reads - `AttachmentsMixin`.
"""

import asyncio
import contextlib
import hashlib
import os
import re
import tempfile
import threading
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import literal_column, select
from sqlalchemy.orm import Session

from app import attachments, board, catalog, evolve, injection, models_dev, topics, views, web
from app import room as rooms
from app.agent.cards import _who
from app.agent.ctx import Ctx
from app.agent.summary import _without
from app.changes import apply_change
from app.commands import MAX_STORED_OUTPUT, OutputMask, recallable, secret_values
from app.db.models import (
    Agent,
    Attachment,
    BoardPost,
    Command,
    FileChange,
    Provider,
    Run,
    ToolCall,
    now,
)
from app.model_client import REFUSES_FILES, TOO_BIG, ModelUnavailable, StepResult
from app.providers import CLI_NAMES, HTTP_KINDS, IMAGE_CLIS, mode_of
from app.serialize import attachment_out, file_change_out
from app.team import quoted
from app.tools import MAX_LINE_CHARS, ToolError
from app.workspace import Workspace, WorkspaceError, secret_in_project, stands_over_later_turns

if TYPE_CHECKING:
    from app.agent import AgentRunner

# What a model took or refused is written by one agent at a time (`_learned`).
_LEARNING = threading.Lock()


def _free_name(ws: Workspace, name: str, taken: set[str]) -> str | None:
    """Where a file the user attached is saved: docs/attachments/<date>-<name> (this machine's
    date: the folder reads in the order they came), or "… (2)" and on where that is there;
    None for a name no file may have (a device's, a stream's)."""
    name = f"{date.today().isoformat()}-{name}"
    stem, suffix, number = Path(name).stem, Path(name).suffix, 2
    rel = f"docs/attachments/{name}"
    try:
        views._vetted(rel)
        while rel in taken or ws.resolve(rel).exists():
            rel, number = f"docs/attachments/{stem} ({number}){suffix}", number + 1
    except (views.Refused, WorkspaceError):
        return None
    return rel


def _sent_files(history: list[dict]) -> list[dict]:
    """The files a request carries as they are (`files`)."""
    return [one for message in history for one in message.get("files") or ()]


class AttachmentsMixin:
    # --- files the user attached (slice 85b) ---------------------------------

    async def _sent_with_files(
        self: "AgentRunner", ctx: Ctx, client, model_id: str, history: list[dict], tools, on_delta,
        on_thinking, message_id: str, more: dict,
    ) -> StepResult:
        """A step whose history carries files sent as they are. A model that refuses a kind
        of them before it writes a word has that on its provider's record, and the step is
        asked again at once without it - a video as its frames, an image as its words - and
        told to say so: the message is not lost. What it took is put on record too. Refused
        for its size (an image too big, the request too large) the step goes again with none
        of them, and nothing is put on record: that is no word of what the model takes.
        shortcut: every step of the turn sends the turn's files again - the APIs keep nothing
        between requests; send them once and refer to them if a provider can keep them."""
        who, showing = _who(ctx), self._showing.setdefault(ctx.agent_id, {})
        while True:
            kinds = {one["kind"] for one in _sent_files(history)}
            try:
                result = await client.stream_step(
                    model_id, history, tools, on_delta, on_thinking, **more)
            except ModelUnavailable as exc:
                said = str(exc)
                big = TOO_BIG.search(said)
                written = self._live[message_id][1]
                if not kinds or written or not (big or REFUSES_FILES.search(said)):
                    self._reached(ctx, bool(written))
                    raise
                if big:
                    showing |= {one["id"]: f"not shown to {who}: the request was too large"
                                for one in _sent_files(history)}
                    history = _without(_without(history, "video", "big"), "image", "big")
                    continue
                kind = "video" if "video" in kinds else "image"
                showing |= {one["id"]: f"{len(one['frames'])} frames shown to {who}: the video "
                            "was refused" if one["frames"] else f"not shown to {who}: refused"
                            for one in _sent_files(history) if one["kind"] == kind}
                self._learned(ctx, kind, False)
                history = _without(history, kind)
                continue
            for kind in kinds:
                self._learned(ctx, kind, True)
            self._reached(ctx, True)
            return result

    def _files_of(self: "AgentRunner", session: Session, ctx: Ctx) -> list[Attachment]:
        """The files an agent may read and hand on: the Lead, those sent with the chat's
        messages; a sub-agent, those handed to it. Not a video's frames: they go with it."""
        rows = session.scalars(select(Attachment).where(
            Attachment.conversation_id == ctx.cid, Attachment.message_id.is_not(None),
            Attachment.frame_of.is_(None),
        ).order_by(Attachment.created_at, literal_column("attachments.rowid"))).all()
        mine = [one for one in rows if ctx.agent_id in one.given_to]
        return list(rows) if ctx.depth == 0 else mine

    def _takes(self: "AgentRunner", session: Session, ctx: Ctx, in_result: bool = False,
               ) -> tuple[set[str], str | None, int]:
        """What this agent's model is sent as it is besides text: what was said or found
        it takes (`catalog.inputs`), by a client that sends files - an API's, or a CLI's with
        an image input of its own (`IMAGE_CLIS`). And the name of a CLI that has none, whose
        model is sent nothing whatever it takes; and the largest picture it is sent.
        `in_result` (B-344): a picture in a CLI session's MCP tool result, which every
        session CLI is handed, as base64."""
        provider = session.get(Provider, ctx.provider_id) if ctx.provider_id else None
        if provider is None:
            return set(), None, attachments.MAX_SENT
        if provider.kind not in (*HTTP_KINDS, *IMAGE_CLIS) and not in_result:
            return set(), CLI_NAMES.get(provider.kind, provider.kind), attachments.MAX_SENT
        if (provider.kind == "codex_cli" and mode_of(provider) == "step"
                and "," in tempfile.gettempdir()):
            # Its --image splits a path at each comma, and the copies are in that folder.
            return set(), ("Codex, whose --image cannot take a path with a comma as this "
                           "machine's temporary folder has,"), attachments.MAX_SENT
        # Claude Code sends a picture as base64, a third larger, and has no retry without it
        # in a session or natively: none is sent whose base64 would pass Anthropic's limit.
        most = attachments.MAX_SENT * 3 // 4 if provider.kind == "claude_cli" or in_result else (
            attachments.MAX_SENT)
        said = catalog.inputs(provider, catalog.model_key(provider, ctx.model_name),
                              models_dev.load(self.settings.runtime_root))
        takes = {kind for kind, (yes, _by) in said.items() if yes}
        # A model nobody described is sent an image once, and what it does is learned.
        takes |= {"image"} if "image" not in said else set()
        # (Anthropic's API takes no video, whatever a mark says, nor a CLI: its frames go.)
        return (takes if provider.kind == "openai_compat" else takes - {"video"}), None, most

    def _told_files(self: "AgentRunner", session: Session, ctx: Ctx, files: list[Attachment],
                    now: bool, off: frozenset[str] = frozenset(),
                    ) -> tuple[str, list[dict], dict[str, str]]:
        """What an agent is told of files - a line each - and those its model is sent as
        they are. `now`: they came with this turn's message; then also, for each picture
        or video, what became of it for this agent's model, in words for its card.
        shortcut: an earlier turn's images are told of, not sent again at every step; send
        them again if a Lead is seen to need an old one."""
        takes, without, most = self._takes(session, ctx)
        who = _who(ctx)
        seen: dict[str, str] = {}
        frames: dict[str, list[Attachment]] = {}
        for frame in session.scalars(select(Attachment).where(
                Attachment.frame_of.in_([one.id for one in files])).order_by(
                    Attachment.created_at, literal_column("attachments.rowid"))):
            frames.setdefault(frame.frame_of or "", []).append(frame)

        def sent(one: Attachment, card: str | None = None) -> dict | None:
            """`id`: the file whose card it is - a frame's is its video's."""
            card = card or one.id
            path = attachments.path_of(self.settings.runtime_root, one.conversation_id, one.id)
            return None if path is None else {
                "id": card, "name": one.name, "kind": one.kind, "mime": one.mime,
                "path": str(path),
                "frames": [p for f in frames.get(one.id, []) if (p := sent(f, card))]}

        lines, parts = [], []
        for one in files:
            got = frames.get(one.id, [])
            if one.kind == "executable":
                shown = "Only its name and size are known: it is never read or run."
            elif one.kind == "image" and one.size > most:
                shown = (f"It is over {attachments.size_text(most)}, too big to be shown to a "
                         "model as it is: only its name and summary are given.")
                seen[one.id] = f"not shown to {who}: over {attachments.size_text(most)}"
            elif one.kind == "image" and "image" in takes:
                shown = "It is shown to you with the message." if now else (
                    "It was shown to you in its turn.")
                parts += [sent(one)] if now else []
                seen[one.id] = f"shown to {who}"
            elif one.kind == "video" and "video" in takes and one.size <= attachments.MAX_SENT:
                shown = "It is sent to your model as it is." if now else "It was sent in its turn."
                parts += [sent(one)] if now else []
                seen[one.id] = f"sent to {who} as it is"
            elif one.kind == "video" and got and "image" in takes:
                shown = (f"{len(got)} frames of it, taken evenly through it, are shown to you as "
                         "images; your model is not known to watch video.")
                parts += [sent(f, one.id) for f in got] if now else []
                seen[one.id] = f"{len(got)} frames shown to {who}"
            elif one.kind in ("image", "video"):
                what = "images" if one.kind == "image" or got else "video"
                shown = (attachments.NOT_GIVEN.format(what=what, cli=without) if without
                         else attachments.NOT_SEEN.format(what=what)) + "."
                seen[one.id] = f"not shown to {who}: " + (
                    f"{without} is given no {what} by KOLONİ" if without
                    else f"its model is not known to see {what}")
            else:
                shown = "Read it with read_attachment." if "read_attachment" not in off and (
                    attachments.folder(
                    self.settings.runtime_root, one.conversation_id) / f"{one.id}.txt").is_file(
                ) else ""
            lines.append(attachments.line_of(one.name, one.kind, one.size, one.summary, shown))
        return "\n".join(lines), [part for part in parts if part], seen if now else {}

    def _shown(self: "AgentRunner", ctx: Ctx, seen: dict[str, str]) -> None:
        """What became of each picture and video for this agent's model, on its record for
        its card (`Attachment.shown_to`): written only when it changed."""
        if not seen:
            return
        with self._factory() as session:
            rows = [row for row in session.scalars(select(Attachment).where(
                Attachment.id.in_(list(seen)))) if row.shown_to.get(ctx.agent_id) != seen[row.id]]
            for row in rows:
                row.shown_to = {**row.shown_to, ctx.agent_id: seen[row.id]}
            session.commit()
            payloads = [attachment_out(row) for row in rows]
        for payload in payloads:
            self.bus.emit(ctx.cid, ctx.run_id, "attachment.updated", payload)

    def _reached(self: "AgentRunner", ctx: Ctx, reached: bool) -> None:
        """What `_history` found of each picture of the request just made, on its card once
        it is known whether the model was reached (`_shown`). Not reached - its CLI never
        started, or it failed before its model said a word - a picture its card says nothing
        of yet for this agent is said not shown; one an earlier step showed stays shown."""
        if reached:
            self._shown(ctx, self._showing.pop(ctx.agent_id, {}))
            return
        seen = self._showing.get(ctx.agent_id, {})
        if not seen:
            return
        with self._factory() as session:
            known = {row.id for row in session.scalars(select(Attachment).where(
                Attachment.id.in_(list(seen)))) if ctx.agent_id in row.shown_to}
        self._shown(ctx, {aid: said if said.startswith("not ") else (
            f"not shown to {_who(ctx)}: its model was not reached")
            for aid, said in seen.items() if aid not in known})

    def _named_files(self: "AgentRunner", ctx: Ctx, names: object) -> list[Attachment]:
        """The files an agent names, among those it may read; ToolError for one it may not."""
        if names in (None, "", []):
            return []
        names = [names] if isinstance(names, str) else names
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            raise ToolError("attachments: a list of the attached files' names")
        with self._factory() as session:
            files = {one.name: one for one in self._files_of(session, ctx)}  # (the latest)
            session.expunge_all()
        for name in names:
            if name not in files:
                raise ToolError(f"no attached file is named {quoted(name)}: " + (
                    f"the files are {', '.join(map(quoted, files))}" if files
                    else "you have none"))
        return [files[name] for name in dict.fromkeys(names)]

    def _hand_files(self: "AgentRunner", ctx: Ctx, files: list[Attachment], agent_id: str) -> None:
        """Files handed on to an agent: on their record, for it to read, and on the canvas."""
        if not files:
            return
        with self._factory() as session:
            rows = [session.get_one(Attachment, one.id) for one in files]
            for row in rows:
                if agent_id not in row.given_to:
                    row.given_to = [*row.given_to, agent_id]
            session.commit()
            payloads = [attachment_out(row) for row in rows]
        for payload in payloads:
            self.bus.emit(ctx.cid, ctx.run_id, "attachment.updated", payload)

    def _learned(self: "AgentRunner", ctx: Ctx, kind: str, took: bool) -> None:
        """What a model did with a file sent as it is, on its provider's record: once taken,
        it is not written again; a refusal is, and that kind is not sent to it again (until
        the user takes what was tried away, on the Models page)."""
        with _LEARNING, self._factory() as session:  # (two agents' at once: neither lost)
            provider = session.get(Provider, ctx.provider_id) if ctx.provider_id else None
            if provider is None:
                return
            name = catalog.model_key(provider, ctx.model_name)
            tried = dict(provider.tried_inputs or {})
            if took and kind in tried.get(name, {}):
                return
            tried[name] = {**tried.get(name, {}), kind: took}
            provider.tried_inputs = tried
            session.commit()

    def _read_attachment(self: "AgentRunner", ctx: Ctx, args: dict) -> str:
        name, start = args.get("name"), args.get("start", 1)
        if not isinstance(name, str) or not name.strip():
            raise ToolError("missing required argument: name")
        one = self._named_files(ctx, [name])[0]
        start = start if isinstance(start, int) and not isinstance(start, bool) else 1
        if one.kind == "executable":
            return f"{one.name} is a program or script: only its name and size are known."
        if one.kind in ("image", "video"):
            return (f"{one.name} is {'an image' if one.kind == 'image' else 'a video'} and has no "
                    "text. Where your model sees it, it was shown to you with its message.")
        text = attachments.text_of(self.settings.runtime_root, one.conversation_id, one.id)
        if text is None:
            return f"{one.name}: {one.summary}. No text of it is given."
        # A framed file (a GitHub issue's) keeps its frame's first line - and the note before it
        # - on every page, as `_recall_output` keeps its note: that line whole, not words of it
        # any file's first line could hold, to be said again as if KOLONİ said it.
        head = text.split("\n", 2)[:2]
        head = head[:1 + (head[0] == injection.NOTE and len(head) > 1)]
        framed = head[-1] == web.FRAMES[0].format(what=attachments.ISSUE) and start > len(head)
        return ("\n".join(head) + "\n" if framed else "") + attachments.page(text, start)

    def _recall_output(self: "AgentRunner", ctx: Ctx, args: dict) -> str:
        """K-gecmis-zengin: the whole output of an earlier call, by its id - a command's as it was
        kept (hidden again: `OutputMask`), any other's result as it was shown. Only of what this
        agent's history could hold: this conversation, its topic, no side of a comparison that
        is not its own (`topics.in_history`) - and, below the lead, its own (its chain's) calls
        and its leads'. The id is the model's word; the rest is the run's. Not what `recallable`
        keeps back."""
        wanted, start = args.get("id"), args.get("start", 1)
        if not isinstance(wanted, str) or not wanted.strip():
            raise ToolError("missing required argument: id")
        start = start if isinstance(start, int) and not isinstance(start, bool) else 1
        # (One answer for an id that is not there and one that is not its own: nothing to tell.)
        unknown = ToolError("no earlier output of this conversation has that id")
        if not re.fullmatch(r"[0-9a-f]{32}", wanted.strip()):
            raise unknown
        with self._factory() as session:
            turn = session.get(Run, ctx.run_id)
            topic_id = turn.topic_id if turn else None
            found = select(ToolCall).join(Run, Run.id == ToolCall.run_id).join(
                Agent, Agent.id == ToolCall.agent_id).where(
                ToolCall.id == wanted.strip(), Run.conversation_id == ctx.cid,
                Run.topic_id == topic_id if topic_id else Run.topic_id.is_(None),
                topics.in_history(ctx.run_id))
            if ctx.depth > 0:
                own = [ctx.agent_id, *(link.id for link, _turn in topics.chain(
                    session, ctx.agent_id))] if ctx.continues_id else [ctx.agent_id]
                found = found.where(ToolCall.agent_id.in_(own) | (Agent.depth == 0))
            call = session.scalar(found)
            command = session.scalar(select(Command).where(
                Command.tool_call_id == call.id)) if call is not None else None
        if call is None:
            raise unknown
        if call.status in ("pending", "running"):
            raise ToolError("that call has not returned yet")
        if call.name == "recall":
            raise ToolError("what the memory held then is not given again: look it up with recall")
        if not recallable(call.name, call.outside_folder, call.why_asked,
                          command.command if command else None):
            raise ToolError("that was read on the user's word, for that once: ask for it again "
                            "with the tool it was read with")
        if command is not None:
            text = OutputMask(secret_values(os.environ)).hide(command.output) or "(no output)"
            if command.output_truncated:
                text = f"(KOLONİ kept only its first {MAX_STORED_OUTPUT // 2**20} MiB)\n{text}"
        else:
            text = call.result or "(no result)"
        # (A line longer than a page is given in pieces: `page` takes a first line whole.)
        text = "\n".join(line[at:at + MAX_LINE_CHARS] for line in text.splitlines()
                         for at in range(0, len(line) or 1, MAX_LINE_CHARS))
        # Outside text that read like orders keeps its word on every page, not on the first only.
        flagged = command is None and text.startswith(injection.NOTE)
        return (f"{injection.NOTE}\n" if flagged and start > 1 else "") + attachments.page(
            text, start)

    async def _save_attached(self: "AgentRunner", ctx: Ctx) -> None:
        """The user's "Save these to the project too" (slice 23), done by KOLONİ before the
        Lead's first step: each file a new one in docs/attachments/, as an ordinary change -
        no card, the tick was the user's word (but one at every level for a name later turns
        would obey), on the change record, undone with the turn. Under a name no file there
        has, vetted as any written name is; a program and a secret file (by its name) are not
        saved."""
        with self._factory() as session:
            wanted = [one for one in self._files_of(session, ctx) if one.keep_in_project]
            session.expunge_all()
        if not wanted:
            return
        self._kept_in_project(wanted)  # (once, whatever comes of it)
        if self._nobody_to_ask(ctx, "write", "save files into the project"):
            return
        ws, taken = Workspace(ctx.folder), set()
        for one in wanted:
            source = attachments.path_of(self.settings.runtime_root, ctx.cid, one.id)
            rel = None if source is None or one.kind == "executable" or secret_in_project(
                one.name) else _free_name(ws, one.name, taken)
            if rel is None or source is None:
                continue
            taken.add(rel)
            data = source.read_bytes()
            with self._factory() as session:
                change = FileChange(
                    run_id=ctx.run_id, agent_id=ctx.agent_id, tool_call_id=None, path=rel,
                    kind="create", before_content=None,
                    after_content=data.decode("utf-8") if one.kind == "text" else (
                        f"({attachments.size_text(one.size)}, {one.kind}: {one.name} as you "
                        "attached it in the chat)"),
                    before_sha=None, after_sha=hashlib.sha256(data).hexdigest(),
                    after_from=str(source))
                session.add(change)
                session.commit()
                change_id, payload = change.id, file_change_out(change)
            self.bus.emit(ctx.cid, ctx.run_id, "file_change.created", payload)
            decision = "approve"
            if stands_over_later_turns(ws, rel):
                future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
                self._decisions[change_id] = future
                self._update_run(ctx.run_id, ctx.cid, status="waiting_approval")
                try:
                    decision = await self._users_word(
                        ctx, future, self._change_heard(ctx, change_id))
                finally:
                    self._decisions.pop(change_id, None)
                    self._update_run(ctx.run_id, ctx.cid, status="running")
            with self._factory() as session:
                change = session.get_one(FileChange, change_id)
                if decision == "reject":
                    change.status, change.decided_at = "rejected", change.decided_at or now()
                    session.commit()
                else:
                    with contextlib.suppress(WorkspaceError):  # (on its record as failed)
                        apply_change(session, ws, change, self.settings.runtime_root)
                payload = file_change_out(change)
            self.bus.emit(ctx.cid, ctx.run_id, "file_change.updated", payload)

    def _kept_in_project(self: "AgentRunner", files: list[Attachment]) -> None:
        """Asked about once: not offered to save again."""
        with self._factory() as session:
            for one in files:
                session.get_one(Attachment, one.id).keep_in_project = False
            session.commit()

    def _read_notes(self: "AgentRunner", ctx: Ctx) -> str:
        """The notebook as this agent knows it: what it wrote and what it was handed.
        What it has not been handed yet is not repeated here: it reaches the agent once,
        the usual way, right after this result."""
        with self._factory() as session:
            seen = session.scalar(
                select(Agent.board_seen).where(Agent.id == ctx.agent_id)) or 0
            reads = self._reader(session, ctx)
            posts = [post for post in session.scalars(
                select(BoardPost).where(BoardPost.run_id == ctx.run_id).order_by(BoardPost.seq)
            ) if reads(post)]
            names = dict(session.execute(
                select(Agent.id, Agent.name).where(Agent.run_id == ctx.run_id)).all())
            # (The Lead's, of every team: the whole turn's, then a team's together, in the chat's
            # order of its teams.)
            order = {team.id: at for at, (_row, team, _lead) in enumerate(
                self._rows(session, ctx.cid))} if ctx.depth == 0 else {}
            known = [
                (
                    post.seq,
                    board.labelled("You" if post.agent_id == ctx.agent_id
                                   else names.get(post.agent_id, "another agent") if post.agent_id
                                   else board.USER, post),
                    post.created_at, post.content,
                )
                for post in sorted(posts, key=lambda post: (
                    -1 if post.team_id is None else order.get(post.team_id, len(order))))
                if post.seq <= seen or post.agent_id == ctx.agent_id
            ]
            # The Lead was given a short block of the turn before (`board.pushed`): here is all.
            before = self._notes_before(session, ctx) if ctx.depth == 0 else []
            if before:
                names |= dict(session.execute(select(Agent.id, Agent.name).where(
                    Agent.run_id == before[0].run_id)).all())
        listed = board.listing(known, len(posts) - len(known))
        return listed + "\n\n" + board.carried(
            [(board.who_wrote(post, names), post.content) for post in before]) if before else listed

    @staticmethod
    def _notes_before(session, ctx: Ctx) -> list[BoardPost]:
        """The notebook of the turn before this one in the Lead's history (of its topic)."""
        turn = session.get(Run, ctx.run_id)
        topic_id = turn.topic_id if turn else None
        turns = list(session.scalars(
            select(Run.id)
            .where(Run.conversation_id == ctx.cid, Run.started_at.is_not(None),
                   Run.topic_id == topic_id if topic_id else Run.topic_id.is_(None))
            .where(topics.in_history(ctx.run_id))
            .order_by(Run.created_at, literal_column("runs.rowid"))
        ))
        at = turns.index(ctx.run_id) if ctx.run_id in turns else 0
        return list(session.scalars(select(BoardPost).where(
            BoardPost.run_id == turns[at - 1]).order_by(BoardPost.seq))) if at > 0 else []

    def _noted_for_team(self: "AgentRunner", session, ctx: Ctx, team_id: str) -> str:
        """K-devir-5: what a team's new lead is given of the notebook of the turn before
        (`_notes_before`): the notes a team's lead wrote for this team or for every team, and
        what a room between teams decided (KOLONİ's note of it) - not KOLONİ's note of the
        turn's end (the Lead has that, `board.pushed`), nor the user's (their words stand in
        the history as they were). Newest first, at most `board.FOR_TEAM_MOST`; "" for none."""
        before = self._notes_before(session, ctx)
        if not before:
            return ""
        leads = {lead.name for _row, _team, lead in self._rows(session, ctx.cid) if lead}
        by_lead = set(session.scalars(select(Agent.id).where(
            Agent.run_id == before[0].run_id, Agent.role_name.in_(leads))))
        # (A room's decision is KOLONİ's note that starts with its own constant words.)
        posts = [post for post in reversed(before) if (
            post.agent_id in by_lead and (post.everyone or post.team_id == team_id))
            or (post.koloni and post.content.startswith(rooms.DECIDED.partition("{")[0]))
            or (post.koloni and post.content.startswith(evolve.ROUND_RESULT))  # (K-evrim)
        ][:board.FOR_TEAM_MOST]
        if not posts:
            return ""
        names = dict(session.execute(
            select(Agent.id, Agent.name).where(Agent.run_id == before[0].run_id)).all())
        return board.for_team([(board.who_wrote(post, names), post.created_at, post.content)
                               for post in posts])
