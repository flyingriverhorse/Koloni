"""run_checks (0.1.9): the Orchestrator asks for KOLONİ's checks in the middle of its turn and
waits for them - the end gate's own pass (`ProofMixin._proof_pass`) run now: the tests, the
types and style, the Reviewer, the live try. The answer's first line is green, red or not
complete (`checks_now.verdict`): a step the user tied to a condition ("if the tests pass,
commit") is taken on green alone. A red answer is no fix round - the turn's end sends the work
back as ever -, and a green one whose work is still the same at the end (`checks_now.identity`)
stands for it there: no second run after a commit. Offered to the Orchestrator at its own work
in a project only, a CLI's over KOLONİ's bridge as any of its tools - `ChecksToolMixin`."""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import literal_column, select

from app import checks_now, proof
from app.agent.ctx import Ctx
from app.agent.proof_mixin import NO_CHANGE_SEEN, Proof
from app.agent.words import PROOF_LEAD, RUN_CHECKS_LEAD
from app.db.models import Conversation, Message, Run, ToolCall
from app.tools import ToolError, _fn

if TYPE_CHECKING:
    from app.agent import AgentRunner

RUN_CHECKS_SCHEMA = _fn(
    "run_checks",
    "Run KOLONİ's checks on your work now - the project's tests, its type and style checks, the "
    "Reviewer and the live try, as the end of the turn runs them - and wait for the result. The "
    "first line of the answer is `CHECKS: green`, `CHECKS: red` or `CHECKS: not complete`. When "
    'the user tied a step to a condition ("if the tests pass", "if no problems are found", "if '
    'it is clean" ... commit / push / merge), call this first, wait for its answer and take that '
    "step only on `CHECKS: green`; otherwise fix the work or tell the user. Never assume the "
    "condition holds. A red answer is no fix round.",
    {},
    [],
)
NOT_HERE = (
    "run_checks is the Orchestrator's, at its own work in a project: KOLONİ checks this work "
    "at the end of the turn"
)
GOING = "run_checks is already running in this turn: wait for its answer"


class ChecksToolMixin:
    def _checks_offered(self: "AgentRunner", ctx: Ctx) -> bool:
        """Whether this agent is offered run_checks: the Orchestrator at its own work in a
        project - not a sub-agent, a plan (no commands there), an answer, a discussion, a side of
        a comparison, nor a CLI that cannot be handed KOLONİ's tools. The same all through a
        turn: its tools and words stay the prompt cache's prefix.
        shortcut: a CLI waits for a tool of KOLONİ's as long as its own limit says - 24 hours set
        for Claude Code and Codex; Copilot's, agy's and Qoder's not measured: a long test run may
        outlast it there. Hold it back from such a CLI once its limit is measured short."""
        return bool(
            ctx.depth == 0
            and ctx.root
            and not ctx.answering
            and not ctx.discussion
            and ctx.run_id not in self._sides
            and "run_command" in ctx.tools
            and getattr(ctx.model, "collaborates", True)
        )

    def _gate_ran(self: "AgentRunner", run_id: str) -> bool:
        """Whether the turn's end gate ran (`Proof.gated`) - not run_checks alone, whose pass
        is no end: an answer after it with no call is still checked (`LoopMixin`)."""
        return (held := self._proofs.get(run_id)) is not None and held.gated

    def _checks_schemas(self: "AgentRunner", ctx: Ctx) -> list[dict]:
        """`TalkMixin._offered`'s run_checks, where it is offered."""
        return [RUN_CHECKS_SCHEMA] if self._checks_offered(ctx) else []

    def _proof_lead(self: "AgentRunner", ctx: Ctx) -> str:
        """What the Orchestrator is told KOLONİ checks at the end - and, where it has run_checks,
        that a step tied to a condition waits for its green."""
        return PROOF_LEAD + (" " + RUN_CHECKS_LEAD if self._checks_offered(ctx) else "")

    def _proof_message(self: "AgentRunner", session, ctx: Ctx) -> str | None:
        """The message KOLONİ's own runs of a pass are on record under: the run_checks call's,
        while it asks (a CLI's call hangs off a message of its own); else the Lead's last
        answer. None: none on record."""
        held = self._proofs.get(ctx.run_id)
        if held is not None and held.asked_call is not None:
            return session.get_one(ToolCall, held.asked_call).message_id
        return session.scalar(
            select(Message.id)
            .where(
                Message.agent_id == ctx.agent_id,
                Message.run_id == ctx.run_id,
                Message.role == "assistant",
            )
            .order_by(Message.created_at.desc(), literal_column("messages.rowid").desc())
            .limit(1)
        )

    async def _work_identity(self: "AgentRunner", ctx: Ctx) -> str | None:
        """`checks_now.identity` of the Lead's work where it is: the project from the turn's
        first commit, its branch's worktree from where the branch began, or its plain copy."""
        copy = self._copies.get(self._works_in(ctx) or "")
        if copy is None:
            head = (self._git_at.get(ctx.run_id) or {}).get("head")
            return await asyncio.to_thread(checks_now.identity, Path(ctx.folder), head)
        if copy.branch:
            start = copy.snapshot_sha or (copy.start[1] if copy.start else None)
            return await asyncio.to_thread(checks_now.identity, copy.root, start)
        return await asyncio.to_thread(checks_now.identity, copy.root, None, copy)

    async def _checked_as_is(self: "AgentRunner", ctx: Ctx) -> bool:
        """Whether run_checks found this very work green - the same content, the same checks on
        - so the end gate need not run again (a `git commit` since rewrote nothing). Then a
        change on record since is that same content: as checked (`_checked_at_ready`)."""
        held = self._proofs.get(ctx.run_id)
        if held is None or held.checked_as is None or not self._checks_offered(ctx):
            return False
        with self._factory() as session:
            on = proof.checks_of(
                session, session.get_one(Conversation, ctx.cid), session.get(Run, ctx.run_id)
            ).on
        if held.checked_as != (await self._work_identity(ctx), on):
            return False
        with self._factory() as session:
            taken = proof.last_change(session, ctx.run_id) or NO_CHANGE_SEEN
        held.seen = taken if held.seen is not None else None
        held.kinds_seen = taken if held.kinds_seen is not None else None
        return True

    async def _run_checks(self: "AgentRunner", ctx: Ctx, call_id: str) -> str:
        """run_checks: the end gate's pass on the work as it stands, waited for - each command
        to its own limit, none going on after the answer, no fix round spent (`Proof.asked_call`
        while it runs) - and its answer. Unchanged since a green one: that one stands. At most
        Fix rounds + 1 passes a turn: past them, the last answer again."""
        if not self._checks_offered(ctx):
            raise ToolError(NOT_HERE)
        held = self._proofs.setdefault(ctx.run_id, Proof())
        if held.asked_call is not None:  # (a CLI may call twice at once)
            raise ToolError(GOING)
        held.asked_call, looks = call_id, held.review_rounds
        try:
            return await self._checks_asked(ctx, held)
        finally:
            held.asked_call, held.review_rounds = None, looks

    async def _checks_asked(self: "AgentRunner", ctx: Ctx, held: Proof) -> str:
        """`_run_checks` while its call holds the turn's checks (`Proof.asked_call`)."""
        if await self._checked_as_is(ctx):
            return (await self._checks_answer(ctx, held, None, checks_now.UNCHANGED_ASKED))[1]
        if held.asked_runs > held.most:
            return await self._checks_capped(ctx, held)
        # (What is checked is the work as the pass starts: a change while it runs is another.)
        before = await self._work_identity(ctx)
        ran, said = await self._proof_pass(ctx, True)
        if ran is None:
            return checks_now.answer(
                checks_now.NOT_COMPLETE, [], None, None, checks_now.NOTHING_TO_CHECK
            )
        held.asked_runs, held.asked_as = held.asked_runs + 1, before
        if said is not None and held.verdict == "HOLD":
            held.looked_at = None  # (a hold it never sent back: the end looks for itself)
        verdict, held.asked_said = await self._checks_answer(ctx, held, said)
        green = verdict == checks_now.GREEN and before is not None
        held.checked_as = (before, held.checks.on) if green else None
        return held.asked_said

    async def _checks_capped(self: "AgentRunner", ctx: Ctx, held: Proof) -> str:
        """Past the cap: the last pass's answer again only where the work is as that pass checked
        it; changed since, or not known, it is not complete (fail closed)."""
        capped = checks_now.CAPPED_ASKED.format(n=held.asked_runs)
        now = await self._work_identity(ctx)
        if now is not None and now == held.asked_as:
            return f"{held.asked_said}\n{capped}"
        return checks_now.answer(checks_now.NOT_COMPLETE, [], None, None, capped)

    async def _checks_answer(
        self: "AgentRunner", ctx: Ctx, held: Proof, said: str | None, note: str = ""
    ) -> tuple[str, str]:
        """The pass's verdict, and run_checks' answer from its rows (`checks_now.answer`), with
        where the checked work stands in git."""
        verdict = checks_now.verdict(
            held.rows,
            said,
            review=held.verdict,
            gone_tests=held.gone_tests,
            loosened=held.loosened,
            halted=held.halted,
        )
        copy = self._copies.get(self._works_in(ctx) or "")
        folder = copy.root if copy is not None else Path(ctx.folder)
        where = await asyncio.to_thread(checks_now.git_line, folder)
        return verdict, checks_now.answer(verdict, held.rows, said, where, note)
