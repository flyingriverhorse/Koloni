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

from app import injection, proof, proof_kinds
from app.agent.ctx import Ctx
from app.db.models import Agent, Conversation, Message, Run, ShownFile
from app.proof import Change, Row

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
    for path, kind in [*((one.path, one.kind) for one in changes
                         if one.in_project and not one.deleted),
                       *((path, proof.kind_of(path)) for path in made)]:
        if kind in proof_kinds.KINDS and path not in found.get(kind, []):
            found.setdefault(kind, []).append(path)
    return found


def _shown(kinds) -> str:
    return ", ".join(proof_kinds.SHOWN[kind] for kind in kinds)


class KindsMixin:
    async def _proof_kinds(self: "AgentRunner", ctx: Ctx, held: "Proof") -> str | None:
        """Each kind of work the turn wrote, checked where the work is (`_ws`) - its rows replace
        the last pass's; a failed one is a fix round while Fix rounds are left."""
        held.rows = [one for one in held.rows if one["kind"] not in proof_kinds.KINDS]
        with self._factory() as session:
            made = list(session.scalars(select(ShownFile.path).join(
                Agent, Agent.id == ShownFile.agent_id).where(Agent.run_id == ctx.run_id)))
            asked = session.scalar(select(Message.content).where(
                Message.run_id == ctx.run_id, Message.role == "user").order_by(
                Message.created_at, literal_column("messages.rowid")).limit(1)) or ""
            before = proof.before_of(session, ctx.run_id)
            held.kinds_seen = proof.last_change(session, ctx.run_id)
        written, checks = _written(held.changes, made), held.checks
        if not written or not checks.own and checks.setting != "check":  # (Tests only: tests)
            return None
        ws, rows = self._ws(ctx), []
        for kind, paths in written.items():
            if kind not in checks.on:  # (off in Check by kind of work, or the recipe's step)
                rows.append(proof.row(kind, "note", (
                    proof_kinds.OFF_IN_RECIPE if checks.own else proof_kinds.NOT_CHECKED_KIND
                ).format(kind=proof_kinds.SHOWN[kind])))
                continue
            more = {"asked": asked} if kind == "docs" else {}
            rows += await asyncio.to_thread(proof_kinds.CHECKS[kind], ws, paths, before=before,
                                            **more)
        held.rows += rows
        failed = [one["text"] for one in rows if one["state"] == "failed"]
        if not failed or held.rounds >= held.most or held.recipe_spent:
            return None
        held.rounds += 1
        held.sent.append(f"{len(failed)} problem" + ("s" if len(failed) > 1 else "")
                         + " in what it wrote")
        more = f"\n+{len(failed) - MOST_TOLD} more" if len(failed) > MOST_TOLD else ""
        return proof_kinds.KINDS_TO_FIX.format(problems=injection.noted(
            "\n".join(f"- {one}" for one in failed[:MOST_TOLD]) + more, "agent"))

    def _kinds_left(self: "AgentRunner", session, run_id: str, cid: str, found: list[Change],
                    held: "Proof") -> list[Row]:
        """Where the turn wrote such files under Test and review and the kinds' last look does not
        stand for them: never made (the turn ended on an earlier step's nudge), or made before
        the last change - said, never an old result for the new work."""
        written = _written(found)
        on = proof.checks_of(session, session.get_one(Conversation, cid),
                             session.get(Run, run_id)).on
        if not set(written) & on:
            return []
        if held.kinds_seen is None:
            return [proof.row("kinds", "not_run", NOT_REACHED.format(kinds=_shown(written)))]
        later = proof.last_change(session, run_id)
        if later is not None and later > held.kinds_seen:
            return [proof.row("kinds", "not_run", NOT_AGAIN.format(kinds=_shown(written)))]
        return []
