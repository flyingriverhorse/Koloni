"""Kanıtlı bitiş S5a: after a turn that wrote documents, diagrams, data, slides or config files
(0.1.7), KOLONİ checks with no model (`app.proof_kinds`; 0.1.7's Code style and types runs the
project's own tools, `_style`) - under Test and review, each kind the
project has on (Settings › This project › Checks and git › Check by kind of work). A sure problem
goes back to the Orchestrator as a fix round, one count with failing tests and the Reviewer's
findings (the project's Fix rounds). `KindsMixin._proof_kinds` is the gate's step after the tests
and before the review: a turn of documents alone runs no test and gets these checks."""

import asyncio
import json
import math
import posixpath
import time
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import literal_column, select

from app import browser, injection, koloni, proof, proof_kinds, proof_style
from app.agent.ctx import Ctx, _GateRefused
from app.db.models import Agent, Command, Conversation, Message, Run, ShownFile, now
from app.model_client import ToolCallRequest
from app.proof import Change, Row
from app.team import quoted
from app.tools import ToolError
from app.workspace import Workspace

if TYPE_CHECKING:
    from app.agent import AgentRunner
    from app.agent.proof_mixin import Proof

# What Checked says where the kinds' last look does not stand for the work.
NOT_REACHED = "Not checked: {kinds} - the turn ended before KOLONİ's check"
NOT_AGAIN = "Not checked on the last change: {kinds}"
MOST_TOLD = 20  # problems told the Orchestrator in one nudge, then "+N more"


def _written(changes: list[Change], made: Sequence[str] = ()) -> dict[str, list[str]]:
    """The turn's files in the project of each kind checked here, in their order - and the files
    its commands made that no change record holds (`made`: a deck or a Word file a script wrote,
    `ShownFile`), after them."""
    found: dict[str, list[str]] = {}
    style: list[str] = []
    for path, kind in [
        *((one.path, one.kind) for one in changes if one.in_project and not one.deleted),
        *((path, proof.kind_of(path)) for path in made),
    ]:
        # (Config's by the file's ending alone: a Makefile or a lock file is no file it reads.)
        if kind == "config" and not path.casefold().endswith(proof_kinds.CONFIG_FILES):
            continue
        # (0.1.7's Code style and types: code and screens by their ending - each its own kind too)
        if kind in ("code", "ui") and path.casefold().endswith(proof_style.STYLE_FILES):
            style += [path] if path not in style else []
        if kind in proof_kinds.WRITTEN and path not in found.get(kind, []):
            found.setdefault(kind, []).append(path)
    return {**found, proof_style.STYLE: style} if style else found


def _set_up(written: dict[str, list[str]], root: str | Path | None) -> dict[str, list[str]]:
    """`written` without Code style and types where no tool of it is set up for those files:
    a project with no linter hears nothing of it - not even that it is off."""
    paths = written.get(proof_style.STYLE)
    if paths and root is not None and proof_style.configured(Path(root), paths):
        return written
    return {kind: one for kind, one in written.items() if kind != proof_style.STYLE}


def _shown(kinds) -> str:
    return ", ".join(proof_kinds.SHOWN[kind] for kind in kinds)


class KindsMixin:
    async def _proof_kinds(self: "AgentRunner", ctx: Ctx, held: "Proof") -> str | None:
        """Each kind of work the turn wrote, checked where the work is (`_ws`) - its rows replace
        the last pass's; a failed one is a fix round while Fix rounds are left."""
        held.rows = [one for one in held.rows if one["kind"] not in proof_kinds.WRITTEN]
        with self._factory() as session:
            made = list(
                session.scalars(
                    select(ShownFile.path)
                    .join(Agent, Agent.id == ShownFile.agent_id)
                    .where(Agent.run_id == ctx.run_id)
                )
            )
            asked = (
                session.scalar(
                    select(Message.content)
                    .where(Message.run_id == ctx.run_id, Message.role == "user")
                    .order_by(Message.created_at, literal_column("messages.rowid"))
                    .limit(1)
                )
                or ""
            )
            before = proof.before_of(session, ctx.run_id)
            held.kinds_seen = proof.last_change(session, ctx.run_id)
        ws = self._ws(ctx)
        written = await asyncio.to_thread(_set_up, _written(held.changes, made), ws.root)
        checks = held.checks
        if not written or not checks.own and checks.setting != "check":  # (Tests only: tests)
            return None
        rows = []
        for kind, paths in written.items():
            if kind not in checks.on:  # (off in Check by kind of work, or the recipe's step)
                rows.append(
                    proof.row(
                        kind,
                        "note",
                        (
                            proof_kinds.OFF_IN_RECIPE
                            if checks.own
                            else proof_kinds.NOT_CHECKED_KIND
                        ).format(kind=proof_kinds.SHOWN[kind]),
                    )
                )
                continue
            if kind == proof_kinds.UI:  # (S5b: in KOLONİ's own browser)
                rows += await self._pages(ctx, ws, paths)
                continue
            if kind == proof_style.STYLE:  # (0.1.7: the project's own tools, as its tests go)
                rows += await self._style(ctx, ws, paths, held)
                continue
            more = {"asked": asked} if kind == "docs" else {}
            rows += await asyncio.to_thread(
                proof_kinds.CHECKS[kind], ws, paths, before=before, **more
            )
        held.rows += rows
        failed = [one["text"] for one in rows if one["state"] == "failed"]
        if not failed or not self._round_left(
            ctx,
            held,
            "kinds",
            frozenset(failed),
            f"{len(failed)} problem" + ("s" if len(failed) > 1 else "") + " in what it wrote",
        ):
            return None
        more = f"\n+{len(failed) - MOST_TOLD} more" if len(failed) > MOST_TOLD else ""
        return proof_kinds.KINDS_TO_FIX.format(
            problems=injection.noted(
                "\n".join(f"- {one}" for one in failed[:MOST_TOLD]) + more, "agent"
            )
        )

    async def _style(
        self: "AgentRunner", ctx: Ctx, ws: Workspace, paths: list[str], held: "Proof"
    ) -> list[Row]:
        """0.1.7, Code style and types: the project's own tools on the turn's files, where the work
        is (`proof_style.planned`) - each run as the project's test command is (`_style_may`):
        unasked at Full auto or where a rule of the user's covers it, at Ask and Auto-edit on one
        card a tool a turn (Always: never again in the project), in a turn nobody watches only on
        its trigger's leave. In a copy, in its one window, what one writes there (a cache) is put
        back. A problem on a line the turn wrote fails (a fix round, its words as data); the
        others are said. STYLE_SECONDS for them all.
        shortcut: not in the app-wide slot of KOLONİ's test runs - take it if a tsc or mypy run
        is seen to crowd the machine."""
        runs, notes = await asyncio.to_thread(proof_style.planned, ws.root, paths)
        rows = [proof.row(proof_style.STYLE, "note", one) for one in notes]
        if not runs:
            return rows
        theirs = await self._approved_tests(ctx) if "tests" in held.checks.on else []
        message_id, added = await asyncio.to_thread(self._style_record, ctx)
        if message_id is None:
            return [*rows, proof.row(proof_style.STYLE, "note", proof_style.NO_ANSWER)]
        until = time.monotonic() + proof_style.STYLE_SECONDS
        for run in runs:
            if any(proof_style.runs_tool(line, run.tool) for line, _folder in theirs):
                rows.append(
                    proof.row(
                        proof_style.STYLE, "note", proof_style.BY_THEIRS.format(tool=run.tool)
                    )
                )
                continue
            rows += await self._style_run(ctx, ws, run, held, message_id, until, added)
        return rows

    def _style_record(self: "AgentRunner", ctx: Ctx) -> tuple[str | None, dict[str, list[int]]]:
        """The Lead's last answer, which KOLONİ's runs go on (as its test runs do), and the lines
        the turn added or changed in each file (`proof.added_lines`)."""
        with self._factory() as session:
            message_id = session.scalar(
                select(Message.id)
                .where(
                    Message.agent_id == ctx.agent_id,
                    Message.run_id == ctx.run_id,
                    Message.role == "assistant",
                )
                .order_by(Message.created_at.desc(), literal_column("messages.rowid").desc())
                .limit(1)
            )
            return message_id, proof.added_lines(
                session, ctx.run_id, ctx.agent_id, self._sharing(ctx)
            )

    def _style_may(self: "AgentRunner", ctx: Ctx, run: "proof_style.Run") -> str:
        """As the project's test command (`ProofMixin._may_run_tests`): "ask" in a turn the user
        watches and is not away from - the level decides there, an Always rule covers it - else
        "run" only on its trigger's leave for this very line; else why not."""
        if self._watched(ctx.run_id) and not self._away_now(ctx):
            return "ask"
        refused = self._nobody_to_ask(
            ctx, "command", f"run {quoted(run.command)}", command=run.command, cwd=run.cwd
        )
        return "run" if refused == "" else refused or "nobody is there to ask"

    def _style_how(
        self: "AgentRunner", ctx: Ctx, run: "proof_style.Run", held: "Proof"
    ) -> str | list[Row]:
        """How a tool's command goes (`_style_may`: "ask" or "run"), or what is said instead: a
        no on its card this turn, a program the turn wrote itself (in .venv or node_modules: no
        install of the project's), no leave."""

        def note(why: str) -> list[Row]:
            return [proof.row(proof_style.STYLE, "note", f"{run.tool}: not run - {why}")]

        if held.style.get(run.tool) == "no":
            return note(proof_style.DECLINED)
        program = run.command.split()[0]
        install = posixpath.normpath(posixpath.join(run.cwd, program.split("/")[0]))
        if "/" in program and any(
            one.path.replace("\\", "/").startswith(f"{install}/") for one in held.changes
        ):
            return note(proof_style.WROTE_IT.format(folder=install))
        how = self._style_may(ctx, run)
        if how not in ("run", "ask"):
            said = proof_style.NEEDS_LEAVE.format(tool=run.tool, why=how)
            return [proof.row(proof_style.STYLE, "note", said)]
        return how

    async def _style_run(
        self: "AgentRunner",
        ctx: Ctx,
        ws: Workspace,
        run: "proof_style.Run",
        held: "Proof",
        message_id: str,
        until: float,
        added: dict[str, list[int]],
    ) -> list[Row]:
        """One tool's command, on record as KOLONİ's call on the Lead's last answer (its card
        there where one is asked) - at most one card a tool a turn: a no stands for the turn, a
        yes covers its later lines in it."""

        how = self._style_how(ctx, run, held)
        if isinstance(how, list):
            return how

        def note(why: str) -> list[Row]:
            return [proof.row(proof_style.STYLE, "note", f"{run.tool}: not run - {why}")]

        once = held.yes.setdefault(run.cwd, set())
        if held.style.get(run.tool) == "yes":  # (its card's yes this turn: this line too)
            once.add(run.command.strip())
        args = {"command": run.command, **({"cwd": run.cwd} if run.cwd != "." else {})}
        request = ToolCallRequest(
            f"{proof.PROOF_CALL}{uuid.uuid4().hex[:16]}",
            "run_command",
            json.dumps(args, ensure_ascii=False),
        )
        ((call_id, _payload),) = self._record_calls(ctx, message_id, [request])
        self._set_call(ctx.cid, call_id, status="running", started_at=now())

        async def given(args: dict) -> Workspace:  # (what is left of the time, once it may run)
            seconds = math.ceil(until - time.monotonic())
            if seconds < 1:
                raise ToolError(proof_style.PAST.format(seconds=proof_style.STYLE_SECONDS))
            args["timeout_seconds"] = seconds
            return ws

        copy = self._copies.get(self._works_in(ctx) or "")
        left: list[str] = []
        async with self._copy_held(copy):  # (one window of a copy: snapshot, run, put back)
            trace = await self._look_trace(copy) if copy is not None else None
            try:
                code, output, result, ended = await self._run_in_copy(
                    ctx,
                    ws,
                    run.command,
                    call_id,
                    ask=how == "ask",
                    once=once,
                    cwd=run.cwd,
                    seconds=proof_style.STYLE_SECONDS,
                    where=given,
                )
            except (_GateRefused, ToolError) as exc:
                self._set_call(ctx.cid, call_id, status="denied", result=str(exc), ended_at=now())
                return note(str(exc).removeprefix("error: "))
            except asyncio.CancelledError:
                self.commands.close_open(ctx.run_id, ctx.cid, calls=[call_id])
                self._set_call(
                    ctx.cid, call_id, status="interrupted", result=proof.STOPPED, ended_at=now()
                )
                raise
            finally:
                if trace is not None:
                    left.append(await self._look_untrace(ctx, trace))
        self._set_call(
            ctx.cid,
            call_id,
            status="denied" if ended == "rejected" else "failed" if code is None else "succeeded",
            result=result,
            ended_at=now(),
        )
        if ended == "rejected":
            held.style[run.tool] = "no"
            return note(proof_style.DECLINED)
        held.style[run.tool] = "yes"
        if ended == "failed_to_start":  # (its time gone, its folder not there: as it said)
            return note(result.removeprefix("error: "))
        rows = await asyncio.to_thread(proof_style.rows_of, run, code, output, ws.root, added)
        return rows + [proof.row(proof_style.STYLE, "note", one) for one in left if one]

    async def _pages(self: "AgentRunner", ctx: Ctx, ws: Workspace, paths: list[str]) -> list[Row]:
        """S5b: the turn's pages in a browser of KOLONİ's own, fenced as an agent's is (this
        machine's previews, the project's files), its profile and the screenshots in the
        project's scratch (`.koloni/tmp/checked/<run>/`) - never where the agents' browsers are
        swept (`browser.sweep`)."""
        command = browser.find_browser()
        try:
            koloni.scratch(ctx.folder)
            folder = self._scratch_folder(
                ctx, f"checked/{ctx.run_id}", "the pages are not looked at there"
            )
        except ToolError as exc:
            return [proof.row(proof_kinds.UI, "note", proof_kinds.PAGES_FAILED.format(why=exc))]

        async def start() -> browser.Browser:
            one = browser.Browser(folder, "pages")
            try:
                await one.start(command or [], ws, self._closed_ports())
            except BaseException:
                await one.close()
                raise
            return one

        return await proof_kinds.check_pages(
            start if command else None, ws, paths, self._preview_of(ctx), folder
        )

    def _preview_of(self: "AgentRunner", ctx: Ctx) -> str | None:
        """The chat's newest preview still running that serves the turn's work: one an agent
        started where the work is (its copy, or the project). shortcut: an earlier turn's agent
        no longer at work counts only as its Lead (depth 0), in a turn whose work is in the
        project - a sub-agent's preview served its own copy; ask the copy's root of the command
        if that misses one."""
        mine = self._works_in(ctx)
        with self._factory() as session:
            for url, agent_id, depth in session.execute(
                select(Command.preview_url, Command.agent_id, Agent.depth)
                .join(Run, Run.id == Command.run_id)
                .join(Agent, Agent.id == Command.agent_id)
                .where(
                    Run.conversation_id == ctx.cid,
                    Command.keep_running.is_(True),
                    Command.status == "running",
                    Command.preview_url.is_not(None),
                )
                .order_by(Command.started_at.desc(), literal_column("commands.rowid").desc())
            ):
                there = self._ctxs.get(agent_id)
                if (
                    self._works_in(there)
                    if there is not None
                    else None
                    if depth == 0
                    else "elsewhere"
                ) == mine:
                    return url
        return None

    def _kinds_left(
        self: "AgentRunner", session, run_id: str, cid: str, found: list[Change], held: "Proof"
    ) -> list[Row]:
        """Where the turn wrote such files under Test and review and the kinds' last look does not
        stand for them: never made (the turn ended on an earlier step's nudge), or made before
        the last change - said, never an old result for the new work."""
        project = self._project(session, cid)
        written = _set_up(_written(found), project.root_path if project is not None else None)
        on = proof.checks_of(
            session, session.get_one(Conversation, cid), session.get(Run, run_id)
        ).on
        if not set(written) & on:
            return []
        if held.kinds_seen is None:
            return [proof.row("kinds", "not_run", NOT_REACHED.format(kinds=_shown(written)))]
        later = proof.last_change(session, run_id)
        if later is not None and later > held.kinds_seen:
            return [proof.row("kinds", "not_run", NOT_AGAIN.format(kinds=_shown(written)))]
        return []
