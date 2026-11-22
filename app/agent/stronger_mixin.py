"""Kanıtlı bitiş S11 (plan decisions 18, 19): the fix rounds spent and a test still failing,
KOLONİ hands the fix to the next stronger tier on the Models page (fast, balanced, strongest) -
the same role on that tier's model, for the same Fix rounds, each tier once a turn, always said.
What is not this turn's was told apart already (S7: flaky, failing before). The stronger model
first says what is wrong, read-only, in a line of its own (fix-incomplete, test-wrong,
approach-wrong), then fixes as that allows. Failing work is never taken in (`_not_taken`).
`StrongerMixin`."""

import asyncio
import json
import logging
import re
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import literal_column, select

from app import injection, ledger, proof, proof_before
from app.agent.ctx import Ctx
from app.db.models import Agent, Command, Conversation, FileChange, Merge, Message, Provider
from app.model_client import ToolCallRequest
from app.proof import Row
from app.roles import effective_tools, find_role
from app.team import TIERS, tier_of, would_run

if TYPE_CHECKING:
    from app.agent import AgentRunner
    from app.agent.proof_mixin import Proof

log = logging.getLogger(__name__)

FIX_INCOMPLETE, TEST_WRONG, APPROACH_WRONG = "fix-incomplete", "test-wrong", "approach-wrong"
DIAGNOSIS = re.compile(r"^\s*(?:#+\s*|[-*]\s+)?\**\s*Diagnosis\W*(fix-incomplete|test-wrong|"
                       r"approach-wrong)\b\W*(.*)$", re.IGNORECASE)
QUESTION = re.compile(r"^\s*(?:#+\s*|[-*]\s+)?\**\s*Question\W*(.+)$", re.IGNORECASE)
CODER = "Coder"  # (where the Orchestrator itself wrote the work: the role that writes code)
MOST_SAID = 300
HANDED = "Handed to {model} ({tier}) after {n} by {by}"
DIAGNOSED = "{model} says {verdict}: {why}"
NO_DIAGNOSIS = "{model} gave no diagnosis line: it goes on as fix-incomplete"
NOT_QUOTED = "{model} said test-wrong without the request's words: it goes on as fix-incomplete"
IN_PROJECT = ("approach-wrong, but the work is in the project, not a copy of its own: it goes on "
              "from the work as it is")
TEST_CHANGED = "Test changed: {why}"
REDO_SAID = "approach-wrong: it does the work again another way, from the work as it is"
NOT_HANDED = "Not handed to {model}: {why}"
STILL_HANDED = "Still failing after rounds by {by}: you decide (Fix it)"
DIAGNOSE_TASK = (
    "KOLONİ ran this project's tests after the work below, and they still fail after {n} fix "
    "rounds by {by}. Before anything more is changed, say what is wrong: read the code and the "
    "tests, change nothing.\n\nYour answer's first line, on its own, is one of:\n"
    "Diagnosis: fix-incomplete - the fix is not finished; say what is missing.\n"
    "Diagnosis: test-wrong - the test asks for what the request does not; quote the request's "
    "own words that show it, in quotation marks.\n"
    "Diagnosis: approach-wrong - this way of doing it cannot pass; say what was tried and why "
    "it fails, in two sentences.\n"
    "Then a line `Question: ...` - the one question you would ask the user if nothing passes.\n\n"
    "The user's request:\n{request}\n\nThe failing tests' output:\n{output}\n\n"
    "Each earlier round's failure:\n{attempts}\n\nThe work so far:\n{diff}")
FIX_TASK = (
    "KOLONİ hands you a fix: this project's tests still fail after {n} fix rounds by {by}. "
    "{how} Then answer in one or two sentences what you changed; KOLONİ runs the tests again.\n\n"
    "The diagnosis (data): {why}\n\nThe failing tests' output:\n{output}\n\n"
    "Each earlier round's failure:\n{attempts}")
HOW = {
    FIX_INCOMPLETE: "Fix the code so the failing tests pass. Do not change, delete or skip a "
                    "test.",
    TEST_WRONG: "The test asks for what the request does not: change that test only as the "
                "diagnosis says, keeping what it guards - never delete it or loosen it beyond "
                "that, and say why in the request's words.",
    APPROACH_WRONG: "The way the work went cannot pass: do it again from the start as the "
                    "request asks, another way. What was tried and why it failed is in the "
                    "diagnosis.",
}
TIER_NAMES = {"fast": "Fast", "balanced": "Balanced", "strongest": "Strongest"}
# Decision 18: failing work is not taken in, at any level - its copy kept, said in Checked.
RECIPE_FAILING = "the recipe's tests still fail after its fix rounds"
TESTS_FAILING = "its tests still fail after its fix rounds"
NOT_TAKEN_TOLD = ("\n\nNot taken in: {why}. The work stays in its copy, with no card at any "
                  "level: KOLONİ checks it again at your answer's end, and the user decides.")
NOT_TAKEN_KEPT = "not taken in: {why}"
NOT_TAKEN = "Not taken in: {what} after rounds by {by}"
NOT_TAKEN_PLAIN = "Not taken in: {why}"
ASK_DEFAULT = "Should the code change, or the test?"


def rounds_said(n: int) -> str:
    return f"{n} round" + ("" if n == 1 else "s")


def diagnosis_of(report: str) -> tuple[str | None, str, str]:
    """The stronger model's verdict: a line `Diagnosis: <kind> - why` of its own (a heading's or
    a list item's too), never one in a fenced block, a quote (`>`) or a diff line - its kind
    (None: none said, or two kinds said: the least power is taken), why, and its question."""
    kinds: dict[str, str] = {}
    asked, fenced = "", False
    for line in report.splitlines():
        bare = line.lstrip()
        if bare.startswith("```"):
            fenced = not fenced
            continue
        if fenced or bare.startswith((">", "+")) or (bare.startswith("-") and not bare.startswith(
                "- ")):
            continue
        if said := DIAGNOSIS.match(line):
            kinds.setdefault(said.group(1).lower(), said.group(2).strip())
        elif (one := QUESTION.match(line)) and not asked:
            asked = one.group(1).strip()
    if len(kinds) != 1:
        return None, "", asked[:MOST_SAID]
    ((kind, why),) = kinds.items()
    return kind, why[:MOST_SAID], asked[:MOST_SAID]


def quotes_request(why: str, request: str) -> bool:
    """Whether a test-wrong reason quotes the request: a quoted span of two words or more that is
    in it (whatever the case and spacing)."""
    folded = " ".join(request.split()).casefold()
    for span in re.findall(r"[\"“”'‘’]([^\"“”'‘’]{3,})[\"“”'‘’]", why):
        words = " ".join(span.split()).casefold()
        if len(words.split()) >= 2 and words in folded:
            return True
    return False


class StrongerMixin:
    async def _stronger(self: "AgentRunner", ctx: Ctx, held: "Proof") -> None:
        """At the end check's end, no step sending work back: where the rounds are spent and the
        last pass's own failures stand, each stronger tier in turn - a diagnosis, then its rounds
        - until the tests pass. Said in Checked; the turn's answer is not held for it."""
        if held.escalated or not held.left_failing or held.stopped or not (
                held.rounds >= held.most or held.recipe_spent):
            return None
        held.escalated = True
        await self._hand_up(ctx, held)
        if held.left_failing and self._works_in(ctx) is not None:
            # (decision 18: failing work in a copy of the turn's own is never taken in - kept)
            self._held_back.setdefault(ctx.run_id, TESTS_FAILING)
        elif not held.left_failing and held.handed and self._held_back.pop(ctx.run_id, None):
            await self._ready_at_end(ctx)  # (it passes now: Ready for you, as it would have)
        return None

    async def _hand_up(self: "AgentRunner", ctx: Ctx, held: "Proof") -> None:
        """Each stronger tier in turn, where Then a stronger model is on."""
        with self._factory() as session:
            project = self._project(session, ctx.cid)
            if project is None or not project.stronger_model:
                return None
            first = self._first_model(session, ctx)
        role, by_provider, by_model, _tier = first
        held.first_by = by_model or by_provider
        for tier, provider, model in self._stronger_tiers(ctx, held, first):
            if held.stopped or not held.left_failing:
                break
            await self._one_tier(ctx, held, role, tier, provider, model)
        return None

    async def _stronger_at_end(self: "AgentRunner", ctx: Ctx, status: str) -> None:
        """The Orchestrator's answer to the last round changed nothing: its turn ends, the gate
        not run again - the stronger model's hand-off still comes (`_stronger`)."""
        held = self._proofs.get(ctx.run_id)
        if held is None or status != "completed" or ctx.depth:
            return
        try:
            await self._stronger(ctx, held)
        except Exception as exc:  # (a hand-off that broke fails nothing of the turn)
            log.warning("run %s: the stronger model's hand-off failed: %r", ctx.run_id, exc)

    def _join_copy(self: "AgentRunner", call_id: str, agent_id: str) -> None:
        """A fixer KOLONİ opened in a turn whose recipe's copy holds the work: one of the
        recipe's agents, so it works in that copy (`_copy_owner`) and its work stays there
        for the check - never kept beside the recipe."""
        if call_id in self._joins_copy:
            self._in_recipe.add(agent_id)

    def _first_model(self: "AgentRunner", session, ctx: Ctx) -> tuple[str, str, str, str | None]:
        """The role whose work failed, the model it ran on and that model's tier: the newest
        kept change's agent (the Orchestrator's own: the Coder role, on its model)."""
        agent_id = session.scalar(select(FileChange.agent_id).where(
            FileChange.run_id == ctx.run_id).order_by(
            FileChange.created_at.desc(), literal_column("file_changes.rowid").desc()).limit(1))
        agent = session.get(Agent, agent_id or ctx.agent_id) or session.get_one(Agent, ctx.agent_id)
        role = agent.role_name if agent.depth and find_role(session, agent.role_name) else CODER
        own = session.scalar(select(Provider).where(Provider.name == agent.provider_name))
        tier = agent.tier or (tier_of(own, agent.model_id) if own is not None else None)
        return role, agent.provider_name or "", agent.model_id or "", tier

    def _stronger_tiers(self: "AgentRunner", ctx: Ctx, held: "Proof",
                        first: tuple[str, str, str, str | None]) -> list[tuple[str, str, str]]:
        """The tiers above the first model's (an untiered one: the strongest alone), each with
        the model it gives the role now (`Would.pick`): one it really holds at that tier, not one
        that already had rounds, not a tier tried this turn."""
        role_name, provider_name, model, at = first
        found = []
        with self._factory() as session:
            role = find_role(session, role_name)
            conversation = session.get_one(Conversation, ctx.cid)
            above = TIERS[TIERS.index(at) + 1:] if at in TIERS else TIERS[-1:]
            would = would_run(session, role, conversation, tools=effective_tools(
                role.tools, self._caps(ctx)) if role else None, step=self.providers)
            used = {(provider_name, model)}
            for tier in above:
                if tier in held.tiers_tried:
                    continue
                picked, _why = would.pick(tier)
                if picked is None:
                    continue
                entry, name = picked
                there = session.get_one(Provider, entry.provider_id)
                if tier_of(there, name) != tier or (there.name, name) in used:
                    continue
                used.add((there.name, name))
                found.append((tier, entry.name, name))
        return found

    async def _one_tier(self: "AgentRunner", ctx: Ctx, held: "Proof", role: str, tier: str,
                        provider: str, model: str) -> None:
        """One stronger tier: said; its diagnosis; then the Fix rounds, the tests run again after
        each, until they pass."""
        held.tiers_tried.append(tier)
        by = " and ".join([held.first_by, *held.handed])
        held.rows.append(proof.row("stronger", "note", HANDED.format(
            model=model, tier=TIER_NAMES[tier], n=rounds_said(held.rounds), by=by)))
        held.handed.append(model)
        kind, why = await self._diagnose(ctx, held, role, provider, model, by)
        for _round in range(held.most):
            status, said = await self._koloni_agent(ctx, "fix", {
                "role": role, "provider": provider, "model": model,
                "why": f"KOLONİ hands it the fix: the tests still fail after rounds by {by}",
                "task": FIX_TASK.format(n=held.rounds, by=by, how=HOW[kind],
                                        why=injection.noted(why, "agent"),
                                        output=self._failing_tail(held),
                                        attempts=self._attempts(held))})
            if status != "succeeded":
                held.rows.append(proof.row("stronger", "not_run", NOT_HANDED.format(
                    model=model, why=(said.removeprefix("error: ").strip().splitlines()
                                      or [status])[0][:MOST_SAID])))
                return
            await self._recheck(ctx, held)
            if not held.left_failing or held.stopped:
                return

    async def _diagnose(self: "AgentRunner", ctx: Ctx, held: "Proof", role: str, provider: str,
                        model: str, by: str) -> tuple[str, str]:
        """The stronger model's first answer: a verdict, read-only - read by its own line, never
        from what it quotes. No verdict, two, or a test-wrong without the request's words: the
        least power, fix-incomplete. approach-wrong where the work is in the project: so too."""
        with self._factory() as session:
            asked = session.scalar(select(Message.content).where(
                Message.run_id == ctx.run_id, Message.role == "user").order_by(
                Message.created_at, literal_column("messages.rowid")).limit(1)) or ""
            diff, _whole, _left = proof.turn_diff(session, ctx.run_id, ctx.agent_id, 12000,
                                                  self._sharing(ctx))
        status, report = await self._koloni_agent(ctx, "diagnose", {
            "role": role, "provider": provider, "model": model,
            "why": "KOLONİ asks it what is wrong before it changes anything",
            "task": DIAGNOSE_TASK.format(
                n=held.rounds, by=by, request=injection.noted(asked, "agent"),
                output=self._failing_tail(held), attempts=self._attempts(held),
                diff=injection.noted(diff or "(none on record)", "agent"))}, read_only=True)
        kind, why, question = diagnosis_of(report if status == "succeeded" else "")
        held.question = question or held.question
        if kind is None:
            held.rows.append(proof.row("stronger", "note", NO_DIAGNOSIS.format(model=model)))
            return FIX_INCOMPLETE, why
        held.diagnosis = (kind, why)
        held.rows.append(proof.row("stronger", "note", DIAGNOSED.format(
            model=model, verdict=kind, why=why or "no reason given")))
        if kind == TEST_WRONG and not quotes_request(why, asked):
            held.rows.append(proof.row("stronger", "note", NOT_QUOTED.format(model=model)))
            return FIX_INCOMPLETE, why
        if kind == TEST_WRONG:
            held.rows.append(proof.row("stronger", "note", TEST_CHANGED.format(why=why)))
        if kind == APPROACH_WRONG and self._works_in(ctx) is None:
            # shortcut: the work is in the project, which KOLONİ never reverts - redo from the
            # start only in a copy of the turn's own (`_redo_in_copy`).
            held.rows.append(proof.row("stronger", "note", IN_PROJECT))
            return FIX_INCOMPLETE, why
        if kind == APPROACH_WRONG:
            await self._redo_in_copy(ctx, held, why)
        return kind, why

    async def _redo_in_copy(self: "AgentRunner", ctx: Ctx, held: "Proof", why: str) -> None:
        """approach-wrong in a copy of the turn's own: the fixer does the work again another way.
        shortcut: the copy's changes are not dropped first (decision 19 drops them and starts a
        fresh copy from the start state); drop them through the copy's own snapshot / put-back
        and the FileChange statuses when this path is seen used."""
        held.rows.append(proof.row("stronger", "note", REDO_SAID))

    async def _recheck(self: "AgentRunner", ctx: Ctx, held: "Proof") -> None:
        """After a stronger model's round: the tests again on the work as it now stands."""
        with self._factory() as session:
            held.changes = proof.changes(session, ctx.run_id, ctx.agent_id, self._sharing(ctx))
        held.left_failing = []
        await self._proof_tests(ctx, held)

    async def _koloni_agent(self: "AgentRunner", ctx: Ctx, kind: str, args: dict,
                            read_only: bool = False) -> tuple[str, str]:
        """An agent KOLONİ opens on the Orchestrator's last answer, as its own spawn: its status
        and its report. `read_only`: held to reading, as S3's Reviewer is."""
        with self._factory() as session:
            message_id = session.scalar(select(Message.id).where(
                Message.agent_id == ctx.agent_id, Message.run_id == ctx.run_id,
                Message.role == "assistant").order_by(
                Message.created_at.desc(), literal_column("messages.rowid").desc()).limit(1))
        if message_id is None:
            return "failed", "the Orchestrator's answer is not on record"
        request = ToolCallRequest(f"{proof.PROOF_CALL}{kind}_{uuid.uuid4().hex[:12]}",
                                  "spawn_agent", json.dumps(args))
        ((call_id, _payload),) = self._record_calls(ctx, message_id, [request])
        if read_only:
            self._read_only_calls.add(call_id)
        else:
            self._joins_copy.add(call_id)  # (it works where the turn's work is: `_join_copy`)
        going = asyncio.ensure_future(self._run_call(ctx, call_id, request))
        self._looks.setdefault(ctx.run_id, set()).add(going)
        try:
            status, said = await going
        except asyncio.CancelledError:
            if not going.cancelled() or self._turn_stopping():
                raise
            held = self._proofs.get(ctx.run_id)
            if held is not None:
                held.stopped = True
            return "failed", "stopped"
        except Exception as exc:  # (a hand-off that broke is said, never the turn's failure)
            log.warning("run %s: KOLONİ's %s agent failed: %r", ctx.run_id, kind, exc)
            return "failed", str(exc) or type(exc).__name__
        finally:
            self._read_only_calls.discard(call_id)
            self._joins_copy.discard(call_id)
            self._looks.get(ctx.run_id, set()).discard(going)
        with self._factory() as session:
            agent = session.scalar(select(Agent).where(Agent.tool_call_id == call_id))
            report = agent.report if agent is not None else None
        return (status, report or said) if status == "succeeded" else (status, said)

    @staticmethod
    def _failing_tail(held: "Proof") -> str:
        tail = "\n\n".join("\n".join(output.rstrip().splitlines()[-40:])
                           for _run, output in held.left_failing)
        return injection.noted(tail.replace("```", "'''")[-4000:] or "(no output)", "agent")

    @staticmethod
    def _attempts(held: "Proof") -> str:
        return injection.noted("\n\n".join(held.attempts[-5:])[-4000:] or "(none kept)", "agent")

    def _recipe_held(self: "AgentRunner", ctx: Ctx, rows: list) -> str | None:
        """Why a recipe's work is held back at Ready for you (decision 18, CL-305): its test-to-
        fix loop ran to its last round and its newest test run on record failed - never taken
        in then, nor carded; None: it may go in.
        shortcut: a check that ran nothing (R3, R4's unshown bug) still waits on its Ready for you
        card - never taken in unasked either; fold it into this row if the card is felt."""
        if not self._recipe_spent(ctx):
            return None
        with self._factory() as session:
            for command, code in session.execute(select(Command.command, Command.exit_code).where(
                    Command.run_id == ctx.run_id, Command.status == "exited",
                    Command.exit_code.is_not(None)).order_by(
                    Command.started_at.desc(), literal_column("commands.rowid").desc())):
                if ledger.read_test(command):
                    return RECIPE_FAILING if code != 0 else None
        return None

    def _not_taken_row(self: "AgentRunner", session, run_id: str,
                       held: "Proof | None") -> list[Row]:
        """The held-back work's row (decision 18): how many tests still fail, after whose
        rounds, the stronger model's question - and its kept copy, for Take in anyway."""
        why = self._held_back.get(run_id)
        if why is None:
            return []
        merge_id = session.scalar(select(Merge.id).where(
            Merge.run_id == run_id, Merge.kept_in.is_not(None)).order_by(
            Merge.created_at.desc()).limit(1))
        ids = [one for run, output in (held.left_failing if held else [])
               for one in proof_before.failed_ids(run.command, output)]
        by = " and ".join(filter(None, [held.first_by if held else "", *(
            held.handed if held else [])]))
        what = (f"{len(ids)} test" + ("s still fail" if len(ids) != 1 else " still fails")
                if ids else "the tests still fail")
        made = proof.row("not_taken", "failed", NOT_TAKEN.format(what=what, by=by) if by and (
            held and held.left_failing) else NOT_TAKEN_PLAIN.format(why=why))
        made["question"] = (held.question if held else "") or ASK_DEFAULT
        if merge_id:
            made["merge_id"] = merge_id
        return [made]

    @staticmethod
    def _stronger_left(held: "Proof") -> list[Row]:
        """The failing line where stronger models had rounds and the tests still fail."""
        if not held.handed or not held.left_failing:
            return []
        return [proof.row("rounds", "failed", STILL_HANDED.format(
            by=" and ".join([held.first_by, *held.handed])))]

