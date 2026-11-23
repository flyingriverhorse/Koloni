"""Kanıtlı bitiş S5a: after a turn that wrote documents, diagrams, data or slides, KOLONİ checks
with no model (`app.proof_kinds`) - under Test and review, each kind the project has on (Settings ›
This project › Checks and git › Check by kind of work). A sure problem goes back to the
Orchestrator as a fix round, one count with failing tests and the Reviewer's findings (the
project's Fix rounds). `KindsMixin._proof_kinds` is the gate's step after the tests and before the
review: a turn of documents alone runs no test and gets these checks."""

import asyncio
from collections.abc import Sequence
from typing import TYPE_CHECKING

from sqlalchemy import literal_column, select

from app import browser, injection, koloni, proof, proof_kinds
from app.agent.ctx import Ctx
from app.db.models import Agent, Command, Conversation, Message, Run, ShownFile
from app.proof import Change, Row
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
    for path, kind in [
        *((one.path, one.kind) for one in changes if one.in_project and not one.deleted),
        *((path, proof.kind_of(path)) for path in made),
    ]:
        if kind in proof_kinds.WRITTEN and path not in found.get(kind, []):
            found.setdefault(kind, []).append(path)
    return found


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
        written, checks = _written(held.changes, made), held.checks
        if not written or not checks.own and checks.setting != "check":  # (Tests only: tests)
            return None
        ws, rows = self._ws(ctx), []
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
        written = _written(found)
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
