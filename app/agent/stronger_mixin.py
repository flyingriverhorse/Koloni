"""Kanıtlı bitiş S11 (plan decisions 18, 19): the fix rounds spent and a test still failing,
KOLONİ hands the fix to the next stronger tier on the Models page (fast, balanced, strongest) -
the same role on that tier's model, for the same Fix rounds, each tier once a turn, always said.
What is not this turn's was told apart already (S7: flaky, failing before). The stronger model
first says what is wrong, read-only, in a line of its own (fix-incomplete, test-wrong,
approach-wrong), then fixes as that allows. Failing work is never taken in (`_not_taken`).
`StrongerMixin`."""

import asyncio
import contextlib
import json
import logging
import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import literal_column, or_, select

from app import copies, injection, proof, proof_before
from app.agent.ctx import Ctx
from app.api.usage import over_limit, over_month
from app.db.models import Agent, Conversation, FileChange, Merge, Message, Provider, now
from app.model_client import ToolCallRequest
from app.proof import Row
from app.proof_related import PYTEST_FILES
from app.roles import effective_tools, find_role
from app.serialize import merge_out
from app.team import TIERS, tier_of, would_run

if TYPE_CHECKING:
    from app.agent import AgentRunner
    from app.agent.proof_mixin import Proof

log = logging.getLogger(__name__)

FIX_INCOMPLETE, TEST_WRONG, APPROACH_WRONG = "fix-incomplete", "test-wrong", "approach-wrong"
# (possessive spaces and stars: one run of spaces was tried split between each `\s*`)
DIAGNOSIS = re.compile(
    r"^\s*+(?:#+\s*+|[-*]\s++)?\**+\s*+Diagnosis\W*(fix-incomplete|test-wrong|"
    r"approach-wrong)\b\W*(.*)$",
    re.IGNORECASE,
)
QUESTION = re.compile(r"^\s*+(?:#+\s*+|[-*]\s++)?\**+\s*+Question\W*(.+)$", re.IGNORECASE)
CODER = "Coder"  # (where the Orchestrator itself wrote the work: the role that writes code)
MOST_SAID = 300
HANDED = "Handed to {model} ({tier}) after {n} by {by}"
DIAGNOSED = "{model} says {verdict}: {why}"
NO_DIAGNOSIS = "{model} gave no diagnosis line: it goes on as fix-incomplete"
NOT_QUOTED = "{model} said test-wrong without the request's words: it goes on as fix-incomplete"
IN_PROJECT = (
    "approach-wrong, but the work is in the project, not a copy of its own: it goes on "
    "from the work as it is"
)
TEST_CHANGED = "Test changed: {why}"
SKIPPED = "{tier} skipped: {why}"
NONE_HANDED = "No stronger model tried: {why}"
OVER_ITS_LIMIT = "over its limit"
TURN_LIMIT = "the turn's token limit is reached"
TESTS_TOUCHED = (
    "Not a pass: {model} changed a test without leave ({paths}) - its diagnosis was not test-wrong"
)
TEST_HELD = "Not a pass: the Reviewer held {model}'s test change"
TEST_UNREAD = "Not a pass: the Reviewer did not read {model}'s test change ({why})"
NO_LOOK = "no look"
# What steers which tests run, besides the tests: a test changed too, under the same leave.
# (pytest's own, as S6 reads them: pytest.toml first in pytest 9)
TEST_CONFIGS = frozenset({"conftest.py", *PYTEST_FILES, "noxfile.py", "package.json"})
TEST_CONFIG = re.compile(
    r"(?:vitest|vite|jest|playwright)\.config\.|vitest\.workspace\.|"
    r"karma\.conf\.|\.mocharc\."
)
NO_VERDICT = "Not handed further: the tests gave no verdict after its round (not run or not ended)"
# k-onceki-1 (K): its round's work failed Take in's own check - kept out (decision 18).
FIX_KEPT_OUT = (
    "Not taken in: {model}'s round - the project's check failed on it before Take in; "
    "it waits in its copy, on its card"
)
STARTED_OVER = "Started over in a fresh copy: {why}"
NOT_STARTED_OVER = "approach-wrong, but {why}: it goes on from the work as it is"
BRANCH_COPY = "the work is on a branch of its own, which KOLONİ does not start over"
NOT_COPIED = "the project could not be copied again"
NOT_HANDED = "Not handed to {model}: {why}"
# k-canli-016: until it passes, a stronger model's rounds stopped short of a pass.
STRONGER_HALTED = "{model}'s rounds stopped: {why}"
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
    "Each earlier round's failure:\n{attempts}\n\nThe work so far:\n{diff}"
)
FIX_TASK = (
    "KOLONİ hands you a fix: this project's tests still fail after {n} fix rounds by {by}. "
    "{how} Then answer in one or two sentences what you changed; KOLONİ runs the tests again.\n\n"
    "The diagnosis (data): {why}\n\nThe failing tests' output:\n{output}\n\n"
    "Each earlier round's failure:\n{attempts}"
)
HOW = {
    FIX_INCOMPLETE: "Fix the code so the failing tests pass. Do not change, delete or skip a test.",
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
# P: and so is work a look of KOLONİ's still holds after its fix rounds.
ON_HOLD = "on hold - a look's findings still stand after its fix rounds"
NOT_TAKEN_TOLD = (
    "\n\nNot taken in: {why}. The work stays in its copy, with no card at any "
    "level: change it and KOLONİ checks it again at your answer's end; else the "
    "user decides."
)
# k-sira-016: a fix round of KOLONİ's checks at Ready for you, in the recipe - its roles fix it.
FIX_IN_RECIPE = (
    "\n\nKOLONİ's checks send the recipe back, as Ask for changes would: {back} Its "
    "end runs them again before Ready for you."
)
NOT_TAKEN_KEPT = "not taken in: {why}"
NOT_TAKEN = "Not taken in: {what} after rounds by {by}"
NOT_TAKEN_PLAIN = "Not taken in: {why}"
ASK_DEFAULT = "Should the code change, or the test?"
ASK_HOLD = "What should change for the look's findings?"
RESUME_FAILED = (
    "Fix it could not go on in the kept work: {why}. This turn works in the project; "
    "the kept work still waits (Take in anyway)."
)
DECIDED = "it was decided since"
ON_ITS_WAY = "a fix of it is on its way already"
FIX_HELD = (
    "The last turn's work was not taken in: {why}. {question} My answer: "
    "{reply} Fix it - you work in that turn's copy, as it was left."
)
# (Fix it's words by the row's reason code, which KOLONİ sets - never by its text)
HELD_WHY = {"on_hold": "a look of KOLONİ's still held it"}
HELD_WHY_TESTS = "its tests still fail"


def steers_tests(path: str) -> bool:
    """Whether a file says which tests run, or how: a conftest anywhere, a test runner's config
    (`TEST_CONFIGS`, `TEST_CONFIG`) - conservative: changed without leave, the work stays held."""
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return name in TEST_CONFIGS or bool(TEST_CONFIG.match(name))


def _cancelled_outside() -> bool:
    """Whether the task awaiting a look is itself being cancelled (KOLONİ closing, a cancel that
    is not Stop this check): its look's cancel is that one's, never swallowed."""
    return (task := asyncio.current_task()) is not None and task.cancelling() > 0


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
        if (
            fenced
            or bare.startswith((">", "+"))
            or (bare.startswith("-") and not bare.startswith("- "))
        ):
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
        # (k-canli-016: until it passes, also where the rounds stopped for no progress - never
        # for a limit, which a stronger model would only spend more of.)
        if (
            held.escalated
            or not held.left_failing
            or held.stopped
            or not (
                held.rounds >= held.most or held.recipe_spent or held.halted == proof.NO_PROGRESS
            )
        ):
            return None
        held.escalated = True
        still = await self._hand_up(ctx, held)  # (its rounds may empty `left_failing`)
        if still and self._works_in(ctx) is not None:
            # (decision 18: failing work in a copy of the turn's own is never taken in - kept)
            self._held_back.setdefault(ctx.run_id, TESTS_FAILING)
        elif not still and held.handed:
            held.passed_by_stronger = True  # (its recipe's row still says findings were left)
            # (held before, at the Lead's end: never inside Ready for you, which asks nothing while
            # held - it asks now, these checks standing for it, k-sira-016; P: not while a look
            # still holds the fixed work - `_on_hold`)
            if held.verdict != "HOLD" and self._held_back.pop(ctx.run_id, None):
                self._mark_ready(ctx, held)
                await self._ready_at_end(ctx)
        return None

    async def _hand_up(self: "AgentRunner", ctx: Ctx, held: "Proof") -> bool:
        """Each stronger tier in turn, where Then a stronger model is on. Whether the tests
        still fail after them (`held.left_failing`)."""
        with self._factory() as session:
            project = self._project(session, ctx.cid)
            if project is None or not project.stronger_model:
                return bool(held.left_failing)
            first = self._first_model(session, ctx)
        role, by_provider, by_model, _tier = first
        held.first_by = by_model or by_provider
        tiers, said = self._stronger_tiers(ctx, held, first)
        held.rows += said
        for tier, provider, model in tiers:
            if held.stopped or held.no_more or not held.left_failing:
                break
            await self._one_tier(ctx, held, role, tier, provider, model)
        return bool(held.left_failing)

    async def _stronger_at_end(self: "AgentRunner", ctx: Ctx, status: str) -> None:
        """The Orchestrator's answer to the last round changed nothing: its turn ends, the gate
        not run again - the stronger model's hand-off still comes (`_stronger`)."""
        held = self._proofs.get(ctx.run_id)
        if held is None or status != "completed" or ctx.depth:
            return
        if held.until_passes and held.rounds and held.halted is None and held.left_failing:
            # (k-canli-016: until it passes, an answer that changed nothing is no progress - said,
            # and the stronger model's hand-off may come)
            held.halted = proof.NO_PROGRESS
        try:
            await self._stronger(ctx, held)
        except Exception as exc:  # (a hand-off that broke fails nothing of the turn)
            log.warning("run %s: the stronger model's hand-off failed: %r", ctx.run_id, exc)

    async def _on_hold(self: "AgentRunner", ctx: Ctx, held: "Proof") -> None:
        """P (decision 18's spirit): work in a copy of the turn's own that a look of KOLONİ's
        still holds after its fix rounds is never taken in by itself, at any level - kept, as
        failing work is ("Not taken in: on hold", Take in anyway or Fix it). A later look's
        MERGE lets it go: Ready for you asks now, as after a stronger model's pass."""
        if self._works_in(ctx) is None:
            return
        if held.verdict == "HOLD" and not held.left_failing:
            self._held_back[ctx.run_id] = ON_HOLD
        elif held.verdict != "HOLD" and self._held_back.get(ctx.run_id) == ON_HOLD:
            del self._held_back[ctx.run_id]  # (held at the Lead's end: never inside Ready for you)
            self._mark_ready(ctx, held)
            await self._ready_at_end(ctx)

    def _join_copy(self: "AgentRunner", call_id: str, agent_id: str) -> None:
        """A fixer KOLONİ opened in a turn whose recipe's copy holds the work: one of the
        recipe's agents, so it works in that copy (`_copy_owner`) and its work stays there
        for the check - never kept beside the recipe."""
        known = self._ctxs.get(agent_id)
        if (
            call_id in self._joins_copy
            and known is not None
            and (known.run_id in self._recipe_copy)
        ):
            self._in_recipe.add(agent_id)

    def held_fix(self: "AgentRunner", run_id: str, merge_id: str) -> str | None:
        """Why Fix it on this turn's "Not taken in" row cannot go on in its kept work; None: it
        can - the caller starts the turn (`resume_on`)."""
        with self._factory() as session:
            merge = session.get(Merge, merge_id)
            if merge_id in self._resume_in.values():
                return ON_ITS_WAY
            return (
                None
                if merge is not None and merge.run_id == run_id and self._undecided(merge)
                else DECIDED
            )

    def _undecided(self: "AgentRunner", merge: Merge) -> bool:
        """A kept copy still waiting for the user, nothing of it taken in."""
        return (
            merge.status == "interrupted"
            and bool(merge.kept_in)
            and (merge.id not in self._deciding)
            and not any(one["state"] == "applied" for one in merge.files)
        )

    def resume_on(self: "AgentRunner", run_id: str, merge_id: str) -> None:
        """The turn Fix it starts goes on in the kept work (`_resume_held`, at its start)."""
        self._resume_in[run_id] = merge_id

    def _resume_held(self: "AgentRunner", ctx: Ctx) -> None:
        """S11: a turn Fix it started - the kept copy is its Lead's copy again (B-322's way:
        loaded, its links back, its kept card withdrawn), and every agent of the turn works
        there; at its end it goes in as any copy's work, or is kept again. Where it cannot be,
        said, and the turn works in the project."""
        merge_id = self._resume_in.pop(ctx.run_id, None)
        if merge_id is None:
            return
        why, copy, payload = None, None, None
        with self._factory() as session:
            merge = session.get(Merge, merge_id)
            if merge is None or not self._undecided(merge) or not merge.kept_in:
                why = DECIDED
            else:
                try:
                    copy = copies.load(
                        Path(ctx.folder),
                        self.settings.runtime_root,
                        copies.named(self.settings.runtime_root, merge.kept_in),
                    )
                    copies.relink(copy)
                except (OSError, ValueError) as exc:
                    why = f"its copy could not be opened ({exc})"
                else:
                    merge.status, merge.files, merge.kept_in = "discarded", [], None
                    merge.check, merge.decided_at = None, now()
                    session.commit()
                    payload = merge_out(merge)
        if copy is None:
            self._koloni_line(ctx.cid, ctx.run_id, RESUME_FAILED.format(why=why or DECIDED))
            return
        self._copies[ctx.agent_id] = copy
        self._resumed[ctx.run_id] = ctx.agent_id
        self.bus.emit(ctx.cid, ctx.run_id, "merge.updated", payload)

    def _first_model(self: "AgentRunner", session, ctx: Ctx) -> tuple[str, str, str, str | None]:
        """The role whose work failed, the model it ran on and that model's tier: the newest
        kept change's agent (the Orchestrator's own: the Coder role, on its model)."""
        agent_id = session.scalar(
            select(FileChange.agent_id)
            .where(FileChange.run_id == ctx.run_id)
            .order_by(FileChange.created_at.desc(), literal_column("file_changes.rowid").desc())
            .limit(1)
        )
        agent = session.get(Agent, agent_id or ctx.agent_id) or session.get_one(Agent, ctx.agent_id)
        role = agent.role_name if agent.depth and find_role(session, agent.role_name) else CODER
        own = session.scalar(select(Provider).where(Provider.name == agent.provider_name))
        tier = agent.tier or (tier_of(own, agent.model_id) if own is not None else None)
        return role, agent.provider_name or "", agent.model_id or "", tier

    def _stronger_tiers(
        self: "AgentRunner", ctx: Ctx, held: "Proof", first: tuple[str, str, str, str | None]
    ) -> tuple[list[tuple[str, str, str]], list[Row]]:
        """The tiers above the first model's (an untiered one: the strongest alone), each with
        the model it gives the role now (`Would.pick`): one it really holds at that tier, not one
        that already had rounds, not a tier tried this turn - and none over its provider's limit,
        nor any over the project's month budget or the turn's token limit (each said)."""
        role_name, provider_name, model, at = first
        found: list[tuple[str, str, str]] = []
        said: list[Row] = []
        with self._factory() as session:
            role = find_role(session, role_name)
            conversation = session.get_one(Conversation, ctx.cid)
            project = self._project(session, ctx.cid)
            if why := over_month(session, project) or (
                TURN_LIMIT if self._review_over(session, project, ctx.run_id) else None
            ):
                return [], [proof.row("stronger", "not_run", NONE_HANDED.format(why=why))]
            above = TIERS[TIERS.index(at) + 1 :] if at in TIERS else TIERS[-1:]
            would = would_run(
                session,
                role,
                conversation,
                tools=effective_tools(role.tools, self._caps(ctx)) if role else None,
                step=self.providers,
            )
            used = {(provider_name, model)}
            for tier in above:
                if tier in held.tiers_tried:
                    continue
                tried = would.tried(tier)
                picked, _why = would.pick(tier)
                if picked is None:
                    if tried and all(entry.name in would.past_limit for entry, _n in tried):
                        said.append(
                            proof.row(
                                "stronger",
                                "not_run",
                                SKIPPED.format(tier=TIER_NAMES[tier], why=OVER_ITS_LIMIT),
                            )
                        )
                    continue
                entry, name = picked
                there = session.get_one(Provider, entry.provider_id)
                if tier_of(there, name) != tier or (there.name, name) in used:
                    continue
                if over_limit(session, there):
                    said.append(
                        proof.row(
                            "stronger",
                            "not_run",
                            SKIPPED.format(tier=TIER_NAMES[tier], why=OVER_ITS_LIMIT),
                        )
                    )
                    continue
                used.add((there.name, name))
                found.append((tier, entry.name, name))
        return found, said

    async def _one_tier(
        self: "AgentRunner",
        ctx: Ctx,
        held: "Proof",
        role: str,
        tier: str,
        provider: str,
        model: str,
    ) -> None:
        """One stronger tier: said; its diagnosis; then the Fix rounds, the tests run again after
        each, until they pass."""
        held.tiers_tried.append(tier)
        by = " and ".join([held.first_by, *held.handed])
        held.rows.append(
            proof.row(
                "stronger",
                "note",
                HANDED.format(
                    model=model, tier=TIER_NAMES[tier], n=rounds_said(held.rounds), by=by
                ),
            )
        )
        held.handed.append(model)
        kind, why = await self._diagnose(ctx, held, role, tier, model, by)
        if kind == APPROACH_WRONG:  # (started over: only the short note of what was tried)
            held.attempts = [f"Tried before, and why it failed: {why}"]
        for _round in range(held.most):
            status, said, fixer = await self._koloni_agent(
                ctx,
                "fix",
                {
                    "role": role,
                    "tier": tier,
                    "why": f"KOLONİ hands it the fix: the tests still fail after rounds by {by}",
                    "task": FIX_TASK.format(
                        n=held.rounds,
                        by=by,
                        how=HOW[kind],
                        why=injection.noted(why, "agent"),
                        output=self._failing_tail(held)
                        if kind != (APPROACH_WRONG)
                        else injection.noted("(the work starts over: none yet)", "agent"),
                        attempts=self._attempts(held),
                    ),
                },
            )
            if status != "succeeded":
                held.rows.append(
                    proof.row(
                        "stronger",
                        "not_run",
                        NOT_HANDED.format(
                            model=model,
                            why=(said.removeprefix("error: ").strip().splitlines() or [status])[0][
                                :MOST_SAID
                            ],
                        ),
                    )
                )
                return
            held.stronger_rounds += 1
            if self._round_kept_out(ctx, fixer):
                held.rows.append(proof.row("stronger", "failed", FIX_KEPT_OUT.format(model=model)))
            wanted = list(held.left_failing)
            before = self._failing_tests(held, wanted)  # (its counts as they were)
            await self._recheck(ctx, held)
            if held.stopped or held.left_failing:
                if halt := self._stronger_halt(ctx, held, before):
                    held.rows.append(
                        proof.row("stronger", "note", STRONGER_HALTED.format(model=model, why=halt))
                    )
                    return
                continue
            if why_not := await self._not_a_pass(ctx, held, kind, model, fixer, wanted):
                held.left_failing, held.no_more = wanted, True  # (no tier more: it stands held)
                held.rows.append(why_not)
            return

    def _stronger_halt(
        self: "AgentRunner", ctx: Ctx, held: "Proof", before: frozenset[str]
    ) -> str | None:
        """Until it passes (k-canli-016), a stronger model's rounds follow the same rule: no more
        where its round left the same tests failing (the next tier may try), or - no tier more -
        where the turn's rounds, the first model's and the stronger ones', reach the ceiling
        (`held.most`) or a limit is reached; None: one more. Numbered Fix rounds: None - their
        count bounds them."""
        if not held.until_passes:
            return None
        if self._failing_tests(held, held.left_failing) == before:
            return proof.NO_PROGRESS
        why = (
            proof.AT_CEILING.format(most=held.most)
            if (held.rounds + held.stronger_rounds >= held.most)
            else self._over_limits(ctx)
        )
        held.no_more = held.no_more or why is not None
        return why

    async def _diagnose(
        self: "AgentRunner", ctx: Ctx, held: "Proof", role: str, tier: str, model: str, by: str
    ) -> tuple[str, str]:
        """The stronger model's first answer: a verdict, read-only - read by its own line, never
        from what it quotes. No verdict, two, or a test-wrong without the request's words: the
        least power, fix-incomplete. approach-wrong where the work is in the project: so too."""
        with self._factory() as session:
            asked = (
                session.scalar(
                    select(Message.content)
                    .where(Message.run_id == ctx.run_id, Message.role == "user")
                    .order_by(Message.created_at, literal_column("messages.rowid"))
                    .limit(1)
                )
                or ""
            )
            diff, _whole, _left = proof.turn_diff(
                session, ctx.run_id, ctx.agent_id, 12000, self._sharing(ctx)
            )
        # (a tier, not a model named: KOLONİ's own hand-off within the user's rule - no card;
        # `_stronger_tiers` read the same pick)
        status, report, _agent = await self._koloni_agent(
            ctx,
            "diagnose",
            {
                "role": role,
                "tier": tier,
                "why": "KOLONİ asks it what is wrong before it changes anything",
                "task": DIAGNOSE_TASK.format(
                    n=held.rounds,
                    by=by,
                    request=injection.noted(asked, "agent"),
                    output=self._failing_tail(held),
                    attempts=self._attempts(held),
                    diff=injection.noted(diff or "(none on record)", "agent"),
                ),
            },
            read_only=True,
        )
        kind, why, question = diagnosis_of(report if status == "succeeded" else "")
        held.question = question or held.question
        if kind is None:
            held.rows.append(proof.row("stronger", "note", NO_DIAGNOSIS.format(model=model)))
            return FIX_INCOMPLETE, why
        held.diagnosis = (kind, why)
        held.rows.append(
            proof.row(
                "stronger",
                "note",
                DIAGNOSED.format(model=model, verdict=kind, why=why or "no reason given"),
            )
        )
        if kind == TEST_WRONG and not quotes_request(why, asked):
            held.rows.append(proof.row("stronger", "note", NOT_QUOTED.format(model=model)))
            return FIX_INCOMPLETE, why
        if kind == TEST_WRONG:
            held.rows.append(proof.row("stronger", "note", TEST_CHANGED.format(why=why)))
        if kind == APPROACH_WRONG and not await self._redo_in_copy(ctx, held, why):
            return FIX_INCOMPLETE, why
        return kind, why

    async def _redo_in_copy(self: "AgentRunner", ctx: Ctx, held: "Proof", why: str) -> bool:
        """approach-wrong (decision 19): the copy's changes dropped - on record as discarded,
        its folder gone (`_drop_copy`) - and a fresh copy made from the start state, the
        project (nothing of the work went in). Said. False where it cannot be: the work in the
        project (KOLONİ never reverts it), on a branch of its own, or not copied again."""
        owner = self._works_in(ctx)
        blocked = (
            IN_PROJECT
            if owner is None or self._copies.get(owner) is None
            else (
                NOT_STARTED_OVER.format(why=BRANCH_COPY)
                if ctx.run_id in self._branch_runs
                else None
            )
        )
        if blocked is None and owner is not None:
            self._drop_copy(owner)
            known = self._ctxs.get(owner)
            if known is None or await self._working_copy(known, owner) is None:
                blocked = NOT_STARTED_OVER.format(why=NOT_COPIED)
        if blocked is not None:
            held.rows.append(proof.row("stronger", "note", blocked))
            return False
        held.rows.append(proof.row("stronger", "note", STARTED_OVER.format(why=why)))
        return True

    async def _recheck(self: "AgentRunner", ctx: Ctx, held: "Proof") -> None:
        """After a stronger model's round: the tests again on the work as it now stands."""
        with self._factory() as session:
            held.changes = proof.changes(session, ctx.run_id, ctx.agent_id, self._sharing(ctx))
        held.left_failing, held.judging = [], True
        try:  # (J: the whole suite's own verdict - never one gone on after the answer)
            await self._proof_tests(ctx, held)
        finally:
            held.judging = False

    async def _koloni_agent(
        self: "AgentRunner", ctx: Ctx, kind: str, args: dict, read_only: bool = False
    ) -> tuple[str, str, str | None]:
        """An agent KOLONİ opens on the Orchestrator's last answer, as its own spawn: its status,
        its report and its id. `read_only`: held to reading, as S3's Reviewer is."""
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
        if message_id is None:
            return "failed", "the Orchestrator's answer is not on record", None
        request = ToolCallRequest(
            f"{proof.PROOF_CALL}{kind}_{uuid.uuid4().hex[:12]}",
            "spawn_agent",
            json.dumps(args, ensure_ascii=False),
        )
        ((call_id, _payload),) = self._record_calls(ctx, message_id, [request])
        if read_only:
            self._read_only_calls.add(call_id)
        else:
            self._joins_copy.add(call_id)  # (it works where the turn's work is: `_join_copy`)
        going = asyncio.ensure_future(self._run_call(ctx, call_id, request))
        self._looks.setdefault(ctx.run_id, set()).add(going)
        try:
            async with self._look_leaves_no_trace(ctx) if read_only else contextlib.nullcontext():
                status, said = await going
        except asyncio.CancelledError:
            if not going.cancelled() or self._turn_stopping() or _cancelled_outside():
                raise
            held = self._proofs.get(ctx.run_id)
            if held is not None:
                held.stopped = True
            return "failed", "stopped", None
        except Exception as exc:  # (a hand-off that broke is said, never the turn's failure)
            log.warning("run %s: KOLONİ's %s agent failed: %r", ctx.run_id, kind, exc)
            return "failed", str(exc) or type(exc).__name__, None
        finally:
            self._read_only_calls.discard(call_id)
            self._joins_copy.discard(call_id)
            self._looks.get(ctx.run_id, set()).discard(going)
        with self._factory() as session:
            agent = session.scalar(select(Agent).where(Agent.tool_call_id == call_id))
            report = agent.report if agent is not None else None
            agent_id = agent.id if agent is not None else None
        return (status, report or said if status == "succeeded" else said, agent_id)

    async def _not_a_pass(
        self: "AgentRunner",
        ctx: Ctx,
        held: "Proof",
        kind: str,
        model: str,
        fixer: str | None,
        wanted: list,
    ) -> Row | None:
        """Why a round whose tests pass is no pass (its row, with the failing command for Fix
        it); None: it is one. No verdict (a run not run, timed out, still running; S7's failed
        rows); a test (or what steers the tests) changed without a test-wrong verdict; a
        test-wrong change S3's look - whatever its size - did not MERGE afresh: held, not read
        (it failed, no verdict, the turn's limit)."""
        command = wanted[0][0].command if wanted else None
        # (J: a test changed without leave is said whatever ran - first, never hidden behind a
        # missing verdict; the test is no "New tests" of the turn then)
        touched = self._tests_touched(ctx, fixer) if kind != TEST_WRONG else []
        if touched:
            held.loosened += touched
            return proof.row(
                "stronger",
                "failed",
                TESTS_TOUCHED.format(model=model, paths=", ".join(touched[:5])),
                command,
                reason="touched",
            )
        if not self._handed_passed(held, wanted):
            return proof.row("stronger", "failed", NO_VERDICT, command, reason="no_verdict")
        if kind != TEST_WRONG:
            # (O: the look the failing tests held back, once, on the work as it passes now - the
            # gate's own rule: big or security-touching; an earlier MERGE stands, as in the gate.
            # A hold that stands keeps work in a copy out: `_on_hold`)
            await self._proof_review(ctx, held)
            return None
        held.verdict, held.looked_at, held.review_forced = None, None, True  # (a fresh look)
        try:
            await self._proof_review(ctx, held)
        finally:
            held.review_forced = False
        if held.verdict == "HOLD":
            return proof.row(
                "stronger", "failed", TEST_HELD.format(model=model), command, reason="held"
            )
        if held.verdict != "MERGE":
            said = [one["text"] for one in held.rows if one["kind"] == "review"]
            return proof.row(
                "stronger",
                "failed",
                TEST_UNREAD.format(model=model, why=said[-1] if said else NO_LOOK),
                command,
                reason="unread",
            )
        return None

    def _round_kept_out(self: "AgentRunner", ctx: Ctx, fixer: str | None) -> bool:
        """K: whether a round's work (its agent's, and those it opened) did not reach the project
        - its copy waiting on a card or kept (Take in's own check failed on it)."""
        if fixer is None:
            return False
        with self._factory() as session:
            line = select(Agent.id).where(or_(Agent.id == fixer, Agent.parent_agent_id == fixer))
            return (
                session.scalar(
                    select(Merge.id)
                    .where(
                        Merge.run_id == ctx.run_id,
                        Merge.agent_id.in_(line),
                        Merge.status.in_(("pending", "interrupted")),
                    )
                    .limit(1)
                )
                is not None
            )

    def _tests_touched(self: "AgentRunner", ctx: Ctx, fixer: str | None) -> list[str]:
        """The test files a round's agent (and those it opened) changed or deleted (`is_test`) -
        not one it added, by its first record (k-onceki-1, J: a new test loosens none, written
        again or not) - and what steers the tests, added too (a conftest that leaves a test out).
        shortcut: one a command rewrote (`sed -i`) has no FileChange; read the copy's moved files
        if that is seen. And a brand-new test module that patches the code under test as it is
        imported is not counted - adding tests stays allowed; read new tests' imports if one is
        seen."""
        if fixer is None:
            return []
        with self._factory() as session:
            line = select(Agent.id).where(or_(Agent.id == fixer, Agent.parent_agent_id == fixer))
            first: dict[str, str] = {}
            for path, kind in session.execute(
                select(FileChange.path, FileChange.kind)
                .where(FileChange.run_id == ctx.run_id, FileChange.agent_id.in_(line))
                .order_by(FileChange.created_at, literal_column("file_changes.rowid"))
            ):
                first.setdefault(path, kind)  # (a delete, then a create: the delete counts)
        return sorted(
            {
                path
                for path, kind in first.items()
                if steers_tests(path) or (proof.is_test(path) and kind != "create")
            }
        )

    @staticmethod
    def _handed_passed(held: "Proof", wanted: list) -> bool:
        """Whether every run that failed has a passed row now and no test row failed (decision
        18: a pass, not a lack of a failure - a run not run, timed out or still running is none;
        S7's count drop, skipped rise or regression is a failure)."""
        passed = {
            one["command"]
            for one in held.rows
            if one["kind"] == "tests" and one["state"] == "passed"
        }
        failed = any(one["kind"] == "tests" and one["state"] == "failed" for one in held.rows)
        return not failed and all(run.command in passed for run, _output in wanted)

    @staticmethod
    def _failing_tail(held: "Proof") -> str:
        tail = "\n\n".join(
            "\n".join(output.rstrip().splitlines()[-40:]) for _run, output in held.left_failing
        )
        return injection.noted(tail.replace("```", "'''")[-4000:] or "(no output)", "agent")

    @staticmethod
    def _attempts(held: "Proof") -> str:
        return injection.noted("\n\n".join(held.attempts[-5:])[-4000:] or "(none kept)", "agent")

    async def _not_yet_ready(self: "AgentRunner", ctx: Ctx, rows: list) -> str | None:
        """k-sira-016: why Ready for you is not asked now - what the Lead is told instead; None:
        it is. KOLONİ's end checks run first, on the work where it is (the recipe's copy): a fix
        round goes to the Lead (its words, no card); work they left failing after the rounds
        and the stronger models is never taken in nor carded (decision 18, S11). Asked: its
        Checked section is said first, so the card comes after it. A fix round - one
        `_round_left` granted, counted there alone (Fix rounds or until it passes; none once
        `held.halted`) - sends the rows back to work, as a wordless Ask for changes: at their end
        no role is opened, and the Lead may not write (delegates) - the recipe's own roles fix
        it, in its copy."""
        rounds = was.rounds if (was := self._proofs.get(ctx.run_id)) else 0
        if (said := await self._proof_left(ctx)) is not None:
            fixing = (was := self._proofs.get(ctx.run_id)) is not None and was.rounds > rounds
            back = self._rows_to(ctx, "Ask for changes", "") if fixing else ""
            return f"\n\n{said}" + (FIX_IN_RECIPE.format(back=back) if back else "")
        if was := self._proofs.get(ctx.run_id):  # (not again at the Lead's end, `_proof_left`)
            self._mark_ready(ctx, was)
        if held := self._recipe_held(ctx, rows) or self._held_back.get(ctx.run_id):
            self._held_back[ctx.run_id] = held
            return NOT_TAKEN_TOLD.format(why=held)
        if ctx.run_id in self._proofs:
            self._say_checked(ctx.cid, ctx.run_id, ctx.root is not None)
        return None

    def _recipe_held(self: "AgentRunner", ctx: Ctx, rows: list) -> str | None:
        """Why a recipe's work is held back at Ready for you (decision 18, CL-305): its test-to-
        fix loop ran to its last round and its newest test run on record failed - never taken
        in then, nor carded; None: it may go in.
        shortcut: a check that ran nothing (R3, R4's unshown bug) still waits on its Ready for you
        card - never taken in unasked either; fold it into this row if the card is felt."""
        from app.agent import FINDINGS_LEFT  # (where S4 keeps it; this module is imported first)

        if (held := self._proofs.get(ctx.run_id)) is not None and held.passed_by_stronger:
            return None

        left = any((state.get("why") or "").startswith(FINDINGS_LEFT) for _team, state in rows)
        return RECIPE_FAILING if left and self._recipe_spent(ctx) else None

    def _not_taken_row(
        self: "AgentRunner", session, run_id: str, held: "Proof | None"
    ) -> list[Row]:
        """The held-back work's row (decision 18): how many tests still fail, after whose
        rounds, the stronger model's question - and its kept copy, for Take in anyway."""
        why = self._held_back.get(run_id)
        if why is None:
            return []
        lead = session.scalar(select(Agent.id).where(Agent.run_id == run_id, Agent.depth == 0))
        merge_id = session.scalar(
            select(Merge.id)
            .where(
                Merge.run_id == run_id,
                Merge.agent_id == lead,
                Merge.kept_in.is_not(None),
                Merge.status == "interrupted",
            )
            .order_by(Merge.created_at.desc())
            .limit(1)
        )
        ids = [
            one
            for run, output in (held.left_failing if held else [])
            for one in proof_before.failed_ids(run.command, output)
        ]
        by = " and ".join(
            filter(None, [held.first_by if held else "", *(held.handed if held else [])])
        )
        what = (
            f"{len(ids)} test" + ("s still fail" if len(ids) != 1 else " still fails")
            if ids
            else "the tests still fail"
        )
        made = proof.row(
            "not_taken",
            "failed",
            NOT_TAKEN.format(what=what, by=by)
            if by and (held and held.left_failing)
            else NOT_TAKEN_PLAIN.format(why=why),
        )
        if why == ON_HOLD:
            made["question"], made["reason"] = ASK_HOLD, "on_hold"
        else:
            made["question"] = (held.question if held else "") or ASK_DEFAULT
        if merge_id:
            made["merge_id"] = merge_id
        return [made]

    @staticmethod
    def _stronger_left(held: "Proof") -> list[Row]:
        """The failing line where stronger models had rounds and the tests still fail."""
        if not held.handed or not held.left_failing:
            return []
        return [
            proof.row(
                "rounds",
                "failed",
                STILL_HANDED.format(by=" and ".join([held.first_by, *held.handed])),
                held.left_failing[0][0].command,
                reason="still",
            )
        ]  # (Fix it's command, as a failing tests row's)
