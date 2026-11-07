"""Watching what changes: the files an agent's tools and commands change in its copy or in the
project, looked at and put on record (`_observe`, `_record_found`), what is taken back or
kept on a card, who is told, and a watch settled when a turn ends - `ObserveMixin`.
"""

import asyncio
import json
import os
import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select

from app import copies, koloni, mcp_client
from app.agent.cards import _changes_nothing, _unasked_note
from app.agent.ctx import Ctx, _NobodyToAsk, _Transcript, _Watch
from app.agent.merge import Taken, _as_dict, _command_names, _is_on_disk, _put_back, _restore
from app.agent.words import AGENT_TERMINAL, ANSWER_PREFIX, IN_THE_PROJECT, STEERED, UNFINISHED
from app.changes import DELETED_SHA
from app.commands import (
    MAX_STORED_OUTPUT,
    RECALL_HINT,
    OutputMask,
    installs,
    recallable,
    secret_values,
)
from app.db.models import Agent, Command, FileChange, ToolCall, now
from app.model_client import ToolCallRequest
from app.serialize import command_event, command_out, file_change_out
from app.team import quoted
from app.workspace import secret_in_project, sha256_text, unified_diff

if TYPE_CHECKING:
    from app.agent import AgentRunner

# K-48: a command of an Orchestrator that hands code on (`HANDED`) changed files: kept, on record
# as its own (`how`), and it is told once a turn.
LEAD_COMMAND = "changed by the Orchestrator's own command (it hands code on)"
HANDS_CODE_WROTE = (
    "Your own command changed {paths} - yours, as the Orchestrator, not a sub-agent's. It is "
    "kept, on record as yours; but the Orchestrator hands code on here: have a helper make "
    "changes to files - call spawn_agent with role Coder and the whole task."
)

# K-fikir-okunmamis: the agent that sent a message is told, where the turn it was sent into
# ended before it read it.
UNREAD_TOLD = ("KOLONİ: {name} finished its turn before it read your message ({words}); it is on "
               "its record, read if it is gone on with.")

# A tool of a CLI's own that it said it started and never said it ended.
NEVER_ENDED = "the CLI started this and never said how it ended: not known whether it finished"

# B-345, B-347: a native CLI's own tools its model looks at an image with (KOLONİ's view_image
# is never bridged to one), and the arguments that name the file (`AgentRunner._own_look`).
# Measured (REA R127, R128): Codex's imageView, Copilot's view, agy's file reading (its stream
# names it view_file, AbsolutePath; REA's note read_file). shortcut: Claude Code's Read of an
# image is not measured, nor Qoder's; take them off if a look is seen named otherwise.
IMAGE_LOOKS = frozenset({"codex__imageView", "copilot__view", "agy__view_file", "agy__read_file",
                         "claude__Read"})

# A CLI that does not ask before it writes cannot be made to wait: what it changed under
# another agent is put on record, and that agent is told.
CHANGED_WHILE_HELD = "changed while {name} held it"
CHANGED_UNDER_YOU = (
    "{path} changed on disk while you hold it: {name} works with tools of its own, "
    "which KOLONİ cannot hold back, and changed it. Read it again before you change it."
)

OBSERVED_RESULT_CHARS = 4000
MAX_CHANGES_PER_LOOK = 200
KEEP_CARDS = 10  # (K-yazma-denetimi: standing files taken back in one look, each on a card)


class ObserveMixin:
    async def _seen_by_watchers(
        self: "AgentRunner", ctx: Ctx, paths: set[str], copy: copies.Copy | None = None
    ) -> None:
        """Files KOLONİ wrote for one agent are not the doing of a CLI at work beside it:
        each such CLI's watch takes them in, and records only what else it finds.
        Beside it in the project, in whichever conversation: they share the folder - or,
        for files written in a working copy (`copy`), beside it in that copy."""
        if not paths:
            return
        if copy is None:
            await self.seen_in_project(ctx.folder, paths)
        beside = [watch for watches in list(self._watches.values()) for watch in watches]
        for watch in beside:
            if watch.ctx is None or watch.transcript is None or watch.copy is not copy or (
                copy is None and watch.ctx.root != ctx.root
            ):
                continue
            # Its own, or its sub-agent's: taken in when the call it made returns - but not
            # one whose call returned while it works (K-paralel-spawn: `_run_from_cli`).
            if watch.ctx.agent_id == ctx.agent_id or self._is_above(
                    watch.ctx.agent_id, ctx) and not self._answers_out.get(watch.ctx.agent_id):
                continue
            async with watch.looking:
                found = await asyncio.to_thread(watch.view.changes)
                watch.view.made -= paths  # (nor a document taken in: R161's outputs)
                own = [change for change in found if change[0] not in paths]
                self._record_found(
                    watch.ctx, watch.transcript, own, "changed by the CLI", copy=copy
                )

    async def seen_in_project(self: "AgentRunner", root: str, paths: set[str]) -> None:
        """Files KOLONİ wrote in a project - for an agent, or taking a change back for
        the user - are not the doing of a CLI at work in a copy of it: what the project
        holds now is what a change the CLI makes there (`_changed_in_project`) is told
        apart from. Nor are they of a native agent at work in the project, which is looked at
        first for a standing file written unnamed (`_standing_look`): they stand."""
        for watch in self._watches_in(root):
            if watch.ctx is not None and watch.transcript is not None:
                await self._standing_look(watch.ctx, watch.transcript, watch, but=paths)
        for watch in [watch for watches in list(self._watches.values()) for watch in watches]:
            if watch.project is None or watch.project.root != Path(root):
                continue
            if watch.unheld and watch.ctx is not None and watch.transcript is not None:
                # What else is found there was found by no look yet, and is its own.
                await self._look_at_project(watch.ctx, watch.transcript, watch, None, but=paths)
            else:
                async with watch.looking:
                    await asyncio.to_thread(watch.project.changes)

    def native_active(self: "AgentRunner", conversation_id: str) -> bool:
        """Whether an agent of this conversation is working with tools of its own."""
        return self._native.get(conversation_id, 0) > 0

    def _note(
        self: "AgentRunner", ctx: Ctx, transcript: "_Transcript | None", name: str, arguments: dict,
        status: str | None, result: str | None, message_id: str | None = None,
        parent: str | None = None,
    ) -> str:
        """Write down a tool the CLI used on its own; returns the call's id. `parent`:
        the call of the CLI's own sub-agent it was used in. (`transcript` None: on the
        message `message_id`.)"""
        if message_id is None:
            assert transcript is not None
            message_id = transcript.take()
        request = ToolCallRequest(f"cli_{uuid.uuid4().hex[:16]}", name, json.dumps(arguments))
        ((call_id, _payload),) = self._record_calls(
            ctx, message_id, [request], origin="cli", parent=parent
        )
        if status:
            self._set_call(ctx.cid, call_id, status=status, result=result,
                           started_at=now(), ended_at=now())
        else:
            self._set_call(ctx.cid, call_id, status="running", started_at=now())
        return call_id

    async def _standing_look(
        self: "AgentRunner", ctx: Ctx, transcript: "_Transcript", watch: "_Watch",
        command: str = "",
        but: set[str] | frozenset[str] = frozenset(), parent: str | None = None,
        approved: bool = False,
    ) -> None:
        """K-yazma-denetimi: a file of the project that tells later turns what they may do or
        runs by itself (`standing_files`), found written though no request the user said yes
        to named it, is put back at once (`_taken_back`). What stands: the paths of this
        agent's approved writes (`watch.named`); `but`, files KOLONİ has just written there
        itself; and at the look just after a `command` what it names (`_command_names`; its
        standing name only where the user `approved` it). Never another agent's names."""
        paths, names = _command_names(
            command, approved, not self._watched(ctx.run_id) or self._full_auto(ctx))
        paths |= watch.named | {one.casefold() for one in but}
        async with watch.looking:
            taken, let = await asyncio.to_thread(
                _put_back, Path(ctx.folder), watch.standing, paths, names, watch.since,
                self._taken_folder(ctx))
        kept = [rel for rel in let if "*.pth" in names and rel.endswith(".pth")]
        if taken or kept:
            self._taken_back(ctx, taken, transcript.take(), command, parent=parent, kept=kept)
        await self._stand_in_watches(ctx.folder, watch.standing, taken)

    async def _own_command_looked(
        self: "AgentRunner", ctx: Ctx, call_id: str, command: str, before: dict[str, bytes],
        since: float,
        ended: bool, approved: bool,
    ) -> None:
        """K-yazma-denetimi for a command KOLONİ ran itself (`run_command`): what it wrote of the
        project's standing files (`before`: as they were when it started, at `since`) is put
        back but for what it names where it was `approved` (`_command_names`: its card showed
        it; not a skill's script run unasked) - and the agent goes on once the user has said
        whether to keep it. Not `ended` (stopped, or it did not start): put back all the same,
        with no card and nothing waited for."""
        paths, names = _command_names(
            command, approved, not self._watched(ctx.run_id) or self._full_auto(ctx))
        taken, let = await asyncio.shield(asyncio.to_thread(
            _put_back, Path(ctx.folder), before, paths, names, since, self._taken_folder(ctx)))
        kept = [rel for rel in let if "*.pth" in names and rel.endswith(".pth")]
        cards: list[asyncio.Task] = []
        if taken or kept:
            with self._factory() as session:
                message_id = session.get_one(ToolCall, call_id).message_id
            cards = self._taken_back(ctx, taken, message_id, command, ask=ended, kept=kept)
        if cards:
            try:
                await self._keeps_answered(ctx, own=True)
            except asyncio.CancelledError:
                for card in cards:  # (stopped: no card of its is left to hold the folder)
                    card.cancel()
                raise
        await self._stand_in_watches(ctx.folder, before, taken)
        if let and ended:
            # (By their paths, for the agents at work beside it: what it was let write stands.)
            # shortcut: by the path, as KOLONİ's own writes are (`seen_in_project`) - a write of
            # another agent's there just then stands too; hand the bytes over if that is seen.
            await self.seen_in_project(ctx.folder, let)

    async def _stand_in_watches(
        self: "AgentRunner", root: str, now: dict[str, bytes], taken: "list[Taken]"
    ) -> None:
        """What was put back (`taken`) holds again what it held: so it is in the snapshot of
        every native agent at work in the project - by its bytes, as on disk (`now`), so that
        another write there is still a change to each."""
        put = [rel for rel, _theirs, failed, _said in taken if not failed]
        for watch in self._watches_in(root) if put else []:
            async with watch.looking:
                for rel in put:
                    if rel in now:
                        watch.standing[rel] = now[rel]
                    else:
                        watch.standing.pop(rel, None)

    def _taken_folder(self: "AgentRunner", ctx: Ctx) -> Path:
        """Where what a turn takes back is kept first, KOLONİ's own (`_keep_aside`)."""
        return self.settings.runtime_root / "taken-back" / ctx.run_id

    def _watches_in(self: "AgentRunner", root: str) -> list["_Watch"]:
        """The native agents at work in this project folder, in a copy of it too."""
        return [watch for watches in list(self._watches.values()) for watch in watches
                if watch.ctx is not None and watch.ctx.root and Path(watch.ctx.root) == Path(root)]

    def _taken_back(
        self: "AgentRunner", ctx: Ctx, taken: "list[Taken]", message_id: str, command: str = "",
        ask: bool = True,
        parent: str | None = None, kept: list[str] | None = None,
    ) -> list[asyncio.Task]:
        """Put on record what `_put_back` took back of an agent's (`taken`), and the `.pth`
        files its install added that were `kept` (nobody watching). With somebody watching,
        each file taken back is a card that offers to keep what the agent wrote
        (`_keep_or_not`, which it returns); with nobody - or `ask` False, its turn being
        over - it stays taken back, refused. One that could not be put back is said."""
        cards: list[asyncio.Task] = []
        held = self._keeps.setdefault(ctx.folder, {})
        for rel in kept or []:
            self._note(ctx, None, "write_file", {"path": rel}, "succeeded",
                       f"{quoted(command[:200])} installed {rel}: let stand - whether the install "
                       "ran was its own approval's", message_id, parent)
        for rel, theirs, failed, said in taken:
            wrote = f"{ctx.name} {'deleted' if theirs is None else 'wrote'} {rel} without naming it"
            if said:
                wrote += f" ({said})"
            if failed:
                self._note(ctx, None, "write_file", {"path": rel}, "failed",
                           f"{wrote}, and it could not be taken back: {failed}", message_id, parent)
                continue
            refused = self._nobody_to_ask(
                ctx, "standing file", f"write {quoted(rel)} without naming it: such a file tells "
                "later turns what they may do, or runs by itself")
            # shortcut: a card each for the first KEEP_CARDS of one look, the rest refused; ask
            # about them together if a CLI is seen to write many such files at once.
            if refused is not None or not ask or len(cards) >= KEEP_CARDS:
                why = refused or ("its turn was over" if not ask else
                                  f"more than {KEEP_CARDS} at once are not asked about one by one")
                self._note(ctx, None, "write_file", {"path": rel}, "denied",
                           f"{wrote}; it was taken back: {why}", message_id, parent)
                continue
            if rel in held:
                held[rel][1] = theirs  # (one card: the answer goes for what it wrote last)
                continue
            call_id = self._note(ctx, None, "write_file", {"path": rel}, None, None,
                                 message_id, parent)
            card = asyncio.ensure_future(self._keep_or_not(ctx, call_id, rel, command, said))
            held[rel] = [card, theirs, ctx.agent_id, ctx.run_id]
            cards.append(card)
        return cards

    async def _keep_or_not(
        self: "AgentRunner", ctx: Ctx, call_id: str, rel: str, command: str, said: str | None
    ) -> None:
        """The card of a standing file `_taken_back` took back: Keep puts what the agent wrote
        there again, as its change. (`said`: where that is kept meanwhile, say.)"""
        held = self._keeps[ctx.folder]
        try:
            theirs = held[rel][1]
            if rel.endswith(".pth") and command and installs(command):
                question = (f"{ctx.name} ran {quoted(command[:200])}: this install "
                            f"{'deleted' if theirs is None else 'added'} `{Path(rel).name}`: "
                            "keep or take back? (It is taken back until you say.)")
            else:
                question = (f"{ctx.name} {'deleted' if theirs is None else 'wrote'} `{rel}` "
                            "without naming it — taken back. Keep it?")
            if said:
                question += f" ({said[0].upper()}{said[1:]}.)"
            try:
                _status, answer = await self._ask_user(ctx, call_id, {
                    "question": mcp_client.visible(question), "options": ["Keep", "Take back"]},
                    leave=True)
            except _NobodyToAsk as exc:  # (as where nobody watches: it stays taken back)
                self._set_call(ctx.cid, call_id, status="denied", ended_at=now(),
                               result=f"taken back: {rel}: {exc}")
                return
            theirs = held[rel][1]
            if answer.removeprefix(ANSWER_PREFIX).strip().casefold() != "keep":
                self._set_call(ctx.cid, call_id, status="denied", ended_at=now(),
                               result=f"taken back: {rel} (the user's choice)")
                return
            failed = await asyncio.to_thread(_restore, Path(ctx.folder), rel, theirs)
            if failed is None:
                # (It stands now for every agent at work there: KOLONİ wrote it.)
                await self.seen_in_project(ctx.folder, {rel})
            self._set_call(ctx.cid, call_id, status="failed" if failed else "succeeded",
                           ended_at=now(), result=f"error: it could not be kept: {failed}"
                           if failed else f"kept: {rel}, as {ctx.name} left it (the user's choice)")
        except asyncio.CancelledError:
            self._set_call(ctx.cid, call_id, status="interrupted", ended_at=now(),
                           result=f"taken back: {rel} (the turn ended before the user answered)")
            raise
        finally:
            held.pop(rel, None)

    async def _keeps_answered(self: "AgentRunner", ctx: Ctx, own: bool = False) -> None:
        """Wait while a card of `_keep_or_not` of this turn is open in its project folder -
        one of this agent's, `own` -, holding no place meanwhile (`_users_word`: the card's
        answer takes one back). Never where nobody is there to answer; never cancels one."""
        if not ctx.root or not self._watched(ctx.run_id):
            return

        async def answered(cards: list[asyncio.Task]) -> str:
            await asyncio.wait(cards)
            return ""

        while cards := [card for card, _theirs, whose, run in self._keeps.get(ctx.root, {}).values()
                        if run == ctx.run_id and (not own or whose == ctx.agent_id)]:
            self._update_run(ctx.run_id, ctx.cid, status="waiting_approval")
            try:
                # (each card was told as it was asked, `_keep_or_not`)
                await self._users_word(ctx, asyncio.ensure_future(answered(cards)), tell=False)
            finally:
                self._update_run(ctx.run_id, ctx.cid, status="running")

    async def _look(
        self: "AgentRunner", ctx: Ctx, transcript: "_Transcript", watch: "_Watch", how: str,
        parent: str | None = None, command: str = "", approved: bool = False,
    ) -> set[str]:
        """Look at the project again, off the event loop, and record what differs.

        `parent`: the sub-agent of the CLI's own whose tool gave cause to look. What is
        found is put down to it - which is a guess, were the CLI itself changing files at
        the same moment. `command`: the command that gave cause, where one did - `approved`
        by the user."""
        # (First: a standing file put back is no change of its, and not on its record.)
        await self._standing_look(ctx, transcript, watch, command, parent=parent,
                                  approved=approved)
        async with watch.looking:
            found = await asyncio.to_thread(watch.view.changes)
            recorded = self._record_found(ctx, transcript, found, how, parent, watch.copy)
            made, watch.view.made = watch.view.made, set()
            await self._record_made(ctx, watch.view.root, made, watch.copy)
            # (Nor what changed closed to KOLONİ, beside one that changes nothing: not its.)
            closed = [] if _changes_nothing(ctx) else watch.view.blocked
            for relative in closed[:MAX_CHANGES_PER_LOOK]:
                # There, but closed to KOLONİ: say so rather than say nothing.
                self._note(ctx, transcript, "write_file", {"path": relative}, "succeeded",
                           f"{how}: {relative} (KOLONİ is not allowed to read it, so there "
                           "is no diff)", parent=parent)
            blocked = set(closed)
        if watch.copy is None and recorded:
            # B-199: its own in the project, not a change there of a CLI at work in a copy
            # beside it (`_look_at_project`, `IN_THE_PROJECT`).
            await self.seen_in_project(str(watch.view.root), recorded)
        return recorded | blocked

    def _record_found(
        self: "AgentRunner", ctx: Ctx, transcript: "_Transcript",
        found: list[tuple[str, str | None, str | None]], how: str,
        parent: str | None = None, copy: copies.Copy | None = None,
    ) -> set[str]:
        """Write down files that differ from what they last held; returns their paths.
        `copy`: the working copy they were found in - then the changes are on record
        as made there ("in_copy"), not as in the project, and only what the copy itself
        changes is written down: a file another agent's changes brought into it
        (`Copy.refresh`) is not the CLI's doing."""
        if copy is not None:
            found = [one for one in found if copy.state(one[0]) is not None]
        else:
            # What KOLONİ itself wrote in the project and is still as it wrote it
            # (`koloni.WROTE`: the scratch's `.koloni/.gitignore`, the page's rules) is not
            # the CLI's doing either.
            here = str(Path(ctx.folder).resolve())
            found = [one for one in found if (wrote := koloni.WROTE.get((here, one[0]))) is None
                     or wrote[0] != (None if one[2] is None else one[2].encode())]
        if _changes_nothing(ctx):  # (what changed beside it, at work at once: not its)
            return set()
        hidden = {one[0] for one in found if how == IN_THE_PROJECT and secret_in_project(one[0])}
        for relative in sorted(hidden)[:MAX_CHANGES_PER_LOOK]:
            # Maybe the user's own: what a secret file holds is kept nowhere and shown to no
            # model (the Observer reads the agent's changes) - its name only.
            self._note(ctx, transcript, "write_file", {"path": relative}, "succeeded",
                       f"{how}: {relative} (a secret file: KOLONİ keeps no copy of it)",
                       parent=parent)
        found = [one for one in found if one[0] not in hidden]
        if not found:
            return hidden
        message_id = transcript.take()  # one look is one step, however many files
        for relative, before, after in found[:MAX_CHANGES_PER_LOOK]:
            name = ("delete_file" if after is None
                    else "write_file" if before is None else "edit_file")
            call_id = self._note(ctx, transcript, name, {"path": relative}, None, None,
                                 message_id, parent)
            with self._factory() as session:
                row = FileChange(
                    run_id=ctx.run_id, agent_id=ctx.agent_id, tool_call_id=call_id,
                    path=relative,
                    kind="delete" if after is None else "create" if before is None else "modify",
                    before_content=before, after_content=after or "",
                    before_sha=sha256_text(before),
                    # A deleted file has no content to take a digest of.
                    after_sha=sha256_text(after) or DELETED_SHA,
                    status="in_copy" if copy else "applied",
                    decided_at=None if copy else now(), origin="cli",
                )
                session.add(row)
                session.commit()
                payload = file_change_out(row)
            self.bus.emit(ctx.cid, ctx.run_id, "file_change.created", payload)
            _, added, removed = unified_diff(before, after or "", relative)
            # (In a copy nothing was changed under anyone: taking it in compares.)
            under_whom = "" if copy else self._changed_under(ctx, relative)
            self._set_call(ctx.cid, call_id, status="succeeded", ended_at=now(),
                           result=f"{how}: {relative} (+{added} -{removed}){under_whom}")
        more = len(found) - MAX_CHANGES_PER_LOOK
        if more > 0:
            self._note(ctx, transcript, "files_changed", {"count": more}, "succeeded",
                       f"{more} more files changed at the same time; they are not recorded "
                       "one by one", message_id, parent)
        return hidden | {relative for relative, _before, _after in found}

    def _tell_hands_on(self: "AgentRunner", ctx: Ctx, watch: "_Watch", changed: set[str]) -> None:
        """K-48: a Lead whose own writes are refused (`_own_writes_refused`) changed files with
        a command: kept, on record as its own (`LEAD_COMMAND`); it is told so, the first time in
        its turn - into its turn (`steer`), else with its next KOLONİ tool result (a note).
        shortcut: what changed beside it while its command ran (the user's editor) is put down
        to the command too, as `_look` guesses; tell them apart if a Lead is told of one."""
        if watch.told_hands_on or not changed:
            return
        watch.told_hands_on = True
        named = ", ".join(quoted(one) for one in sorted(changed)[:10])
        words = HANDS_CODE_WROTE.format(paths=named + (" and more" if len(changed) > 10 else ""))

        async def tell() -> None:
            # (Not awaited by the look: Codex's answer to it is read by the loop it runs in.)
            if await self.steer(ctx, words) is not None:  # (busy, or its CLI hears no more)
                self._send(ctx, ctx, words, delivered=False, koloni=True)

        self._telling.add(task := asyncio.ensure_future(tell()))
        task.add_done_callback(self._telling.discard)

    def _changed_under(self: "AgentRunner", ctx: Ctx, relative: str) -> str:
        """A change found on disk, made by a CLI that does not ask first, is to a file
        another agent holds: nothing could be held back, so it is said. Returns what the
        change's record adds ("" when nobody else held the file), and leaves the holder
        a note for its next step - once, like any note."""
        holder = self.claims.holder(ctx.folder, relative)
        if holder is None or holder == ctx.agent_id or holder in self._line(ctx):
            return ""
        held_by = self._ctxs.get(holder)
        if held_by is not None:
            self._send(
                ctx, held_by, CHANGED_UNDER_YOU.format(path=relative, name=ctx.name),
                delivered=False,
            )
        return "; " + CHANGED_WHILE_HELD.format(name=self._name_of(holder))

    async def _observe(
        self: "AgentRunner", ctx: Ctx, transcript: "_Transcript", watch: "_Watch", phase: str,
        item: dict
    ) -> None:
        """Turn one thing a native CLI did with its own tools into KOLONİ's records."""
        kind = item.get("type")
        if kind == "live":  # (89j, `run_native`: shown, on no record)
            self._show_live(ctx, item)
            return
        self._touch(ctx)
        if kind == "skill_not_given":  # (B-151, `run_native`: said once, as a skill refused)
            self._note(ctx, transcript, "use_skill", {"name": item.get("name")}, "denied",
                       f"skill {item.get('name')} was not given to Claude Code: {item.get('why')}")
            return
        if kind == "bridge_not_started":  # (B-310, agy's `run_native`: before its task)
            watch.unbridged = True
            self._note(ctx, transcript, "koloni_tools", {}, "failed", str(item.get("why")))
            return
        if kind == "inside_not_given":  # (89g, `run_native`: they are KOLONİ's agents only)
            names = [watch.roles.pop(name, (name, []))[0] for name in item.get("names") or []]
            self._note(ctx, transcript, "claude__agents", {"roles": names}, "failed",
                       f"not offered inside Claude Code: {item.get('why')}")
            return
        if kind == "structured_report":  # (89p, 93-B6: `ClaudeNativeClient._control`)
            await self._observe_report(ctx, transcript, item)
            return
        if kind == "steer_unread":  # (89d: its turn ended on what `steer` sent it)
            self._observe_unread(ctx, transcript, item)
            return
        await self._observe_use(ctx, transcript, watch, phase, item, kind)

    async def _observe_report(self: "AgentRunner", ctx: Ctx, transcript: "_Transcript",
                              item: dict) -> None:
        """`_observe`: a report handed back in its schema (89p), or why none came."""
        if "asked_again" in item:
            status, said = "failed", ("its report did not keep to its schema, so it was "
                                      "asked once more: " + "; ".join(item["asked_again"]))
        elif "report" in item:
            status, said = "succeeded", ("its report came back in its schema: its findings "
                                         "are read from it")
        else:
            why = "; ".join(item.get("errors") or []) or "none came back"
            status, said = "failed", f"no report in its schema ({why}): its words are its " \
                                     "report"
        self._note(ctx, transcript, "report_schema", {}, status, said, transcript.said())
        if "report" in item:
            self._schema_reports[ctx.agent_id] = item["report"]  # (what `_found` reads)
            if item["report"]["report"].strip():  # (else its words stand: `report_line`)
                await transcript.on_text(item["report"]["report"].strip())  # (its last word)

    def _observe_unread(self: "AgentRunner", ctx: Ctx, transcript: "_Transcript",
                        item: dict) -> None:
        """`_observe`: its turn ended before it read what `steer` sent it (89d)."""
        words = str(item.get("text") or "").removeprefix(f"{STEERED}\n\n")
        self._note(ctx, transcript, "steer", {}, "failed",
                   f"{ctx.name or ctx.role} finished before it read: {words}")
        by = self._steered_by.pop(ctx.agent_id, None)
        if by is not None and by[1] == words and (sender := self._ctxs.get(by[0])):
            # (B: the agent that sent it is not left believing it was acted on.)
            self._send(sender, sender, UNREAD_TOLD.format(
                name=ctx.name or ctx.role, words=quoted(by[2][:200])),
                delivered=False, koloni=True)

    async def _observe_use(self: "AgentRunner", ctx: Ctx, transcript: "_Transcript",
                           watch: "_Watch", phase: str, item: dict, kind) -> None:
        """`_observe`, for one use of a tool (its id): announced, refused, a sub-agent of the
        CLI's own, the end of one asked about - else `_observe_done`."""
        use_id = str(item.get("id") or "")
        if phase == "announced":
            watch.announced.add(use_id)
            if item.get("parent"):
                watch.inside[use_id] = str(item["parent"])
            return
        if use_id and use_id in watch.denied:
            return  # refused before it acted: it did not happen
        under = watch.under(use_id)
        if kind == "sub_agent":
            self._observe_sub_agent(ctx, transcript, watch, phase, item, use_id, under)
            return
        if use_id in watch.asked and kind != "file_change":
            # A change that was approved, and then the CLI's own tool failed.
            call_id, change_id = watch.asked.pop(use_id)
            reason = str(_as_dict(item.get("error")).get("message") or "the tool failed")
            self._close_asked_change(ctx, call_id, change_id, None, reason[:500])
            return
        if use_id in watch.asked_other and phase == "completed":
            self._observe_other_end(ctx, watch, use_id, item)
            return
        await self._observe_done(ctx, transcript, watch, phase, item, kind, under)

    def _observe_sub_agent(self: "AgentRunner", ctx: Ctx, transcript: "_Transcript",
                           watch: "_Watch", phase: str, item: dict, use_id: str,
                           under) -> None:
        """`_observe`: a sub-agent of the CLI's own, started or ended."""
        if phase == "started":
            # A sub-agent of the CLI's own is not an agent of KOLONİ's: one tool call,
            # running for as long as the sub-agent works. Where leave for it was asked
            # in words, the call made for that question is the one.
            name = re.sub(r"[^A-Za-z0-9_-]", "_", f"{item.get('server')}__{item.get('tool')}")
            said = _as_dict(item.get("arguments"))
            # 89g: one of the roles offered to it: which, on its record beside what it asked
            # - by KOLONİ only: one the model wrote into its own input is not kept.
            given = {key: value for key, value in said.items() if key != "koloni_role"}
            asked = watch.asked_other.pop(use_id, None)
            if role := watch.roles.get(str(given.get("subagent_type"))):
                given = {**given, "koloni_role": role[0]}
            if asked and (role or "koloni_role" in said):
                self._set_call(ctx.cid, asked, arguments=json.dumps(given))
            watch.subs[use_id] = asked or self._note(
                ctx, transcript, name[:64], given, None, None, parent=under,
            )
            watch.at_work.add(use_id)
        elif use_id in watch.at_work:
            watch.at_work.discard(use_id)
            ended = {"completed": "succeeded", "failed": "failed"}
            self._set_call(
                ctx.cid, watch.subs[use_id], ended_at=now(),
                status=ended.get(str(item.get("status")), "interrupted"),
                result=str(item.get("text") or "")[:OBSERVED_RESULT_CHARS],
            )

    def _observe_other_end(self: "AgentRunner", ctx: Ctx, watch: "_Watch", use_id: str,
                           item: dict) -> None:
        """`_observe`: the end of a tool the CLI asked leave for in words."""
        call_id = watch.asked_other.pop(use_id)
        failed = bool(item.get("error")) or item.get("status") == "failed"
        said = "".join(
            str(block.get("text") or "")
            for block in _as_dict(item.get("result")).get("content") or []
            if isinstance(block, dict)
        )
        # (One the CLI never said the end of is not put down as done: `NEVER_ENDED`.)
        ended = item.get("status") == "interrupted"
        self._set_call(
            ctx.cid, call_id, ended_at=now(),
            status="interrupted" if ended else "failed" if failed else "succeeded",
            result=NEVER_ENDED if ended else said[:OBSERVED_RESULT_CHARS],
        )

    async def _observe_done(self: "AgentRunner", ctx: Ctx, transcript: "_Transcript",
                            watch: "_Watch", phase: str, item: dict, kind, under) -> None:
        """`_observe`: a command, a file change, an MCP tool or a web search of the CLI's."""
        if kind == "command_execution":
            await self._observe_command(ctx, transcript, watch, phase, item)
        elif kind == "file_change" and phase == "completed":
            await self._observe_changes(ctx, transcript, watch, item)
        elif kind == "mcp_tool_call" and phase == "completed":
            self._observe_mcp(ctx, transcript, watch, item, under)
        elif kind == "web_search" and phase == "completed":
            self._note(ctx, transcript, "web_search", {"query": str(item.get("query") or "")},
                       "succeeded", "", parent=under)

    def _observe_mcp(self: "AgentRunner", ctx: Ctx, transcript: "_Transcript",
                     watch: "_Watch", item: dict, under) -> None:
        """`_observe`: a tool of an MCP server the CLI used, done - refused, cut off, or ended."""
        error = item.get("error")
        said = "".join(
            str(block.get("text") or "")
            for block in _as_dict(item.get("result")).get("content") or []
            if isinstance(block, dict)
        )
        failed = bool(error) or item.get("status") == "failed"
        reason = _as_dict(error).get("message") or error
        # A name any model can be shown later: letters, digits, _ and - only.
        name = re.sub(r"[^A-Za-z0-9_-]", "_", f"{item.get('server')}__{item.get('tool')}")
        if item.get("status") in ("denied", "declined"):
            # The CLI itself refused its own tool, or KOLONİ declined a request of the
            # CLI's (`CodexNativeClient._decide`): on record as denied, never as done.
            why = (str(reason) if item["status"] == "declined"
                   else f"refused by the CLI: {reason or 'no reason given'}")
            self._note(
                ctx, transcript, name[:64], _as_dict(item.get("arguments")), "denied",
                why[:OBSERVED_RESULT_CHARS], parent=under,
            )
            return
        if item.get("status") == "interrupted":
            # It started, and the CLI never said how it ended: not put down as done.
            self._note(
                ctx, transcript, name[:64], _as_dict(item.get("arguments")),
                "interrupted", NEVER_ENDED, parent=under,
            )
            return
        self._observe_mcp_ended(ctx, transcript, watch, item, under, name, said, failed, reason)

    def _observe_mcp_ended(self: "AgentRunner", ctx: Ctx, transcript: "_Transcript",
                           watch: "_Watch", item: dict, under, name: str, said: str,
                           failed: bool, reason) -> None:
        """`_observe_mcp`: one that ran to its end, on record; an image it looked at, shown."""
        # (One it never asked about: Copilot's own tools, slice 89c; Claude Code's past
        # its hook, slice 89b.)
        unasked = f"{_unasked_note(ctx)}\n" if item.get("unasked") is True else ""
        result = unasked + (f"error: {reason}" if failed and reason else said)[
            :OBSERVED_RESULT_CHARS]
        call_id = self._note(
            ctx, transcript, name[:64], _as_dict(item.get("arguments")),
            "failed" if failed else "succeeded", result, parent=under,
        )
        if not failed and name in IMAGE_LOOKS:
            # Never put to KOLONİ: Codex's imageView (no request comes for it), agy's
            # reading only (no hook), and whatever the CLI says ran unasked.
            unasked = (name == "codex__imageView" or item.get("unasked") is True
                       or name.startswith("agy__") and bool(getattr(ctx.model, "reads", False)))
            self._own_look(ctx, transcript, watch, call_id, name,
                           _as_dict(item.get("arguments")), result, under, unasked)

    async def _observe_command(self: "AgentRunner", ctx, transcript, watch: "_Watch", phase,
                               item) -> None:
        cid, run_id = ctx.cid, ctx.run_id
        # Without an id a start and its end cannot be told to belong together.
        item_id = str(item.get("id") or f"anonymous-{phase}-{uuid.uuid4().hex}")
        under = watch.under(item_id)
        if item_id not in watch.commands:
            text = str(item.get("command") or "")
            call_id = self._note(ctx, transcript, "run_command", {"command": text}, None, None,
                                 parent=under)
            with self._factory() as session:
                row = Command(
                    run_id=run_id, agent_id=ctx.agent_id, tool_call_id=call_id, command=text,
                    cwd=None, location="host", status="running", started_at=now(),
                    timeout_seconds=0, origin="cli",
                )
                session.add(row)
                session.commit()
                watch.commands[item_id] = (call_id, row.id)
                payload = command_out(row)  # whole, as a client builds its row from it
            self.bus.emit(cid, run_id, "command.created", payload)
        if phase != "completed":
            return
        call_id, command_id = watch.commands.pop(item_id)
        # Hidden as KOLONİ's own commands' is, for the screen, the record and other agents.
        # (The CLI's own model has read it whole already.)
        mask = OutputMask(secret_values(os.environ))
        output = mask.hide(str(item.get("aggregated_output") or ""))
        code = item.get("exit_code")
        # A client that is watching gets the output before the command is closed.
        if output:
            self.bus.emit_transient(
                cid, "command.output", {"command_id": command_id, "text": output}
            )
        with self._factory() as session:
            row = session.get_one(Command, command_id)
            # (B-357: one its CLI was let run and never said a word of: `CodexNativeClient`.)
            row.status = ("failed_to_start" if item.get("never_started")
                          else "blocked" if item.get("blocked") else "exited")
            row.ended_at = now()
            row.exit_code = code if isinstance(code, int) else None
            row.output = output[:MAX_STORED_OUTPUT]
            row.output_truncated = len(output) > MAX_STORED_OUTPUT
            session.commit()
            payload = command_event(row)
        self.bus.emit(cid, run_id, "command.updated", payload)
        shown = output if len(output) <= OBSERVED_RESULT_CHARS else (
            output[:OBSERVED_RESULT_CHARS] + "\n[the rest is in the command's record]" + (
                RECALL_HINT.format(id=call_id) if getattr(ctx.model, "collaborates", True)
                and recallable("run_command", None, None, row.command) else ""))
        # A CLI that gives no exit code may still say the command failed.
        # K-48: or say it ended well where its sandbox refused it (`model_native.WRITE_REFUSED`).
        blocked = item.get("blocked")
        failed = bool(blocked) or row.exit_code is None and item.get("status") == "failed"
        ended = ("no exit code reported" if row.exit_code is None
                 else f"exit code {row.exit_code}")
        if item.get("sandboxed") is True:  # in its sandbox, kept from the secret files
            ended += ", sandboxed"
        if blocked:
            ended += f", {blocked}"
        # (One it never asked about - its own rules let it, say - is said to be.)
        unasked = f"{_unasked_note(ctx)}\n" if item.get("unasked") is True else ""
        result = f"{unasked}{ended}\n{shown}".rstrip()
        status = "failed" if failed else "succeeded"
        self._set_call(cid, call_id, status=status, ended_at=now(), result=result)
        self._counted(ctx, call_id, ToolCallRequest(
            call_id, "run_command", json.dumps({"command": row.command})), status, result,
            own=True)
        # A command can change files without saying so.
        lead = self._own_writes_refused(ctx, watch)
        changed = await self._look(
            ctx, transcript, watch, LEAD_COMMAND if lead else "changed by a command the CLI ran",
            under, row.command, item_id in watch.approved)
        if lead:
            self._tell_hands_on(ctx, watch, changed)
        watch.approved.discard(item_id)
        if watch.unheld:
            await self._look_at_project(ctx, transcript, watch, under)

    async def _observe_changes(self: "AgentRunner", ctx, transcript, watch: "_Watch", item) -> None:
        """The CLI says it changed files. What changed is read off the project itself
        (the CLI does not wait to be watched, and a path it names may be anywhere)."""
        root = watch.view.root.resolve()  # the project, or the copy it was started in
        use_id = str(item.get("id") or "")
        under = watch.under(use_id)
        # (A patch of Codex's was asked about file by file: `parts`, the id of each; and
        # `unasked`, those of its files it changed without being asked about them.)
        for named in [one for one in item.get("unasked") or [] if isinstance(one, str)]:
            self._note(ctx, transcript, "edit_file", {"path": named}, "succeeded",
                       f"{_unasked_note(ctx)}: {named}", parent=under)
        asked = [watch.asked.pop(one) for one in (use_id, *(item.get("parts") or ()))
                 if one in watch.asked]
        if asked:
            # The changes the user approved: each one's record is its proposal. Whatever
            # else is found is written down; these files are taken in, not recorded twice.
            await self._standing_look(ctx, transcript, watch, parent=under)  # (as `_look`)
            with self._factory() as session:
                paths = {change_id: session.get_one(FileChange, change_id).path
                         for _call, change_id in asked}
            async with watch.looking:
                found = await asyncio.to_thread(watch.view.changes)
                self._record_found(
                    ctx, transcript, [c for c in found if c[0] not in paths.values()],
                    "changed by the CLI", under, watch.copy,
                )
            declined = "the patch it was part of was declined" if item.get("declined") else None
            for call_id, change_id in asked:
                wrote = next((c for c in found if c[0] == paths[change_id]), None)
                self._close_asked_change(ctx, call_id, change_id, wrote, declined)
            return
        recorded = await self._look(ctx, transcript, watch, "changed by the CLI", under)
        # A step that ended in an error is on record as failed: what the looks find is
        # written down, and nothing it only named is said to have changed.
        failed = item.get("status") == "failed"
        for change in [c for c in item.get("changes") or [] if isinstance(c, dict)]:
            path, how = change.get("path"), change.get("kind")
            name = "write_file" if how == "add" else "edit_file"
            # A path that is not whole is one in the folder the CLI works in.
            target = root / str(path)
            try:
                relative = target.resolve().relative_to(root).as_posix()
            except (ValueError, OSError):
                straight = await self._changed_in_project(ctx, transcript, watch, target, under)
                # (A file of the project's that was looked at and not found changed: no note.)
                if straight is None and not failed:
                    where = "its working copy" if watch.copy else "the project folder"
                    self._note(ctx, transcript, name, {"path": str(path)}, "succeeded",
                               f"changed a file outside {where}; KOLONİ keeps no copy",
                               parent=under)
                continue
            if relative in recorded or how == "delete" or failed:
                continue  # on record now, or (a deletion) noticed at an earlier look
            why = ("already shown in the change before" if watch.view.covers(relative)
                   else "what it held before is not known, so there is no diff")
            self._note(ctx, transcript, name, {"path": relative}, "succeeded",
                       f"changed by the CLI: {relative} ({why})", parent=under)

    async def _changed_in_project(
        self: "AgentRunner", ctx: Ctx, transcript: "_Transcript", watch: "_Watch", target: Path,
        parent: str | None,
    ) -> bool | None:
        """A CLI at work in a copy says it changed a file by a path that is not in the
        copy. Where that is a file of the project itself, the change is one made in the
        project like any a CLI makes there: on record as that - not as in the copy -
        with what the file held before, so that it is seen and can be taken back. None
        where it is no file of the project's (or the project is not watched), False
        where nothing is found changed there."""
        if watch.project is None:
            return None
        try:
            relative = target.resolve().relative_to(Path(ctx.folder).resolve()).as_posix()
        except (ValueError, OSError):
            return None
        await self._look_at_project(ctx, transcript, watch, parent)
        return relative in watch.straight

    async def _look_at_project(
        self: "AgentRunner", ctx: Ctx, transcript: "_Transcript", watch: "_Watch",
        parent: str | None,
        but: set[str] | frozenset[str] = frozenset(),
    ) -> None:
        """Look at the project a CLI in a copy was made from, and put down to the CLI
        what differs there. `but`: files KOLONİ has just written there for somebody else
        (`_seen_by_watchers`), which are taken in and not put down to it.

        shortcut: whatever else changes the project while it works (the user's editor,
        another agent's command) is found here too and on its record, which says who is
        not known (`IN_THE_PROJECT`); Undo this turn leaves such a change to its own row.
        Tell them apart if that is ever wanted."""
        if watch.project is None:
            return
        async with watch.looking:
            found = await asyncio.to_thread(watch.project.changes)
        # All that is found, not one file alone: a look moves on what was last seen, so
        # what it is not asked about now would be found by no later look.
        watch.straight |= self._record_found(
            ctx, transcript, [one for one in found if one[0] not in but], IN_THE_PROJECT,
            parent,
        )

    async def _settle_watch(self: "AgentRunner", ctx: Ctx, watch: "_Watch") -> None:
        """The CLI is done, or was stopped: say how things it was given leave for ended
        when it never reported them. A change is read off the disk; a command KOLONİ did
        not run itself cannot be known to have finished."""
        # First what needs no look at the disk: a failure there must not leave these open.
        for call_id in list(watch.asked_other.values()):
            self._set_call(ctx.cid, call_id, status="interrupted", result=UNFINISHED,
                           ended_at=now())
        watch.asked_other.clear()
        # A sub-agent of its own that was never said to be done is not known to be.
        for use_id in list(watch.at_work):
            self._set_call(ctx.cid, watch.subs[use_id], status="interrupted", result=UNFINISHED,
                           ended_at=now())
        watch.at_work.clear()
        if watch.asked and watch.transcript is not None:
            # What is on disk now: the approved changes are closed by it and taken in,
            # so that the last look does not write them down a second time.
            found = await watch.look(watch.view.changes)
            with self._factory() as session:
                paths = {
                    change_id: session.get_one(FileChange, change_id).path
                    for _call, change_id in watch.asked.values()
                }
            mine = set(paths.values())
            self._record_found(
                ctx, watch.transcript, [c for c in found if c[0] not in mine],
                "changed by the CLI", copy=watch.copy,
            )
            for call_id, change_id in list(watch.asked.values()):
                wrote = next((c for c in found if c[0] == paths[change_id]), None)
                self._close_asked_change(ctx, call_id, change_id, wrote, None)
        watch.asked.clear()
        for call_id, command_id in list(watch.commands.values()):
            with self._factory() as session:
                row = session.get_one(Command, command_id)
                if row.status in ("proposed", "approved", "running"):
                    row.status, row.ended_at = "interrupted", now()
                    session.commit()
                payload = command_event(row)
            self.bus.emit(ctx.cid, ctx.run_id, "command.updated", payload)
            self._set_call(ctx.cid, call_id, status="interrupted", result=UNFINISHED,
                           ended_at=now())
        watch.commands.clear()

    def _close_asked_change(
        self: "AgentRunner", ctx: Ctx, call_id: str, change_id: str,
        wrote: tuple[str, str | None, str | None] | None, failure: str | None,
    ) -> None:
        """A change that was approved before the CLI made it: say how it ended."""
        with self._factory() as session:
            change = session.get_one(FileChange, change_id)
            if wrote is not None and wrote[2] is not None:
                # What is on disk is the record, should it differ from what was shown.
                change.after_content, change.after_sha = wrote[2], sha256_text(wrote[2])
            applied = failure is None and (wrote is not None or _is_on_disk(session, change))
            failure = failure or "it was approved, and the CLI never made the change"
            change.status, change.decided_at = ("applied" if applied else "failed"), now()
            session.commit()
            payload = file_change_out(change)
            _, added, removed = unified_diff(
                change.before_content, change.after_content, change.path
            )
            path = change.path
        self.bus.emit(ctx.cid, ctx.run_id, "file_change.updated", payload)
        self._set_call(
            ctx.cid, call_id, ended_at=now(),
            status="succeeded" if applied else "failed",
            result=(f"applied: {path} (+{added} -{removed})" if applied
                    else f"error: {failure}"),
        )

    def _settle_session(self: "AgentRunner", ctx: Ctx) -> None:
        """Close what a session that ended on its own left open: this agent's calls,
        changes, commands and questions, and any sub-agent still marked as at work."""
        self._interrupt_open_calls(
            ctx.run_id, ctx.cid, ctx.agent_id, ctx.calls_from, ctx.own_calls
        )
        if ctx.answering:
            return  # its sub-agents are at work for its own, unfinished call
        # Not those an opener did not wait for (`_run_from_cli`, the leads beside them too),
        # nor theirs: they work on, and what they report goes to the Lead (G2.5).
        going = self._went_on
        with self._factory() as session:
            agents = session.scalars(select(Agent).where(Agent.run_id == ctx.run_id)).all()
            below = {ctx.agent_id}
            for agent in agents:  # stored parents first
                if agent.parent_agent_id in below and agent.id not in going:
                    below.add(agent.id)
            left = [a.id for a in agents
                    if a.id in below - {ctx.agent_id} and a.status not in AGENT_TERMINAL]
        for agent_id in left:
            self._interrupt_open_calls(ctx.run_id, ctx.cid, agent_id)
            self._set_agent(
                ctx.cid, agent_id, status="failed", ended_at=now(),
                error="the agent that opened it stopped before it finished",
            )
