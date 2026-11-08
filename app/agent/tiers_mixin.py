"""Providers, tiers and tokens: how hard a message is (`_by_how_hard`), the tokens and model a
step reports (`_count_tokens`, `_ran_on`), whether a provider may still run an agent, why a
model failed as its opener is told, and the advice of one tier up - `TiersMixin`.
"""

import asyncio
import contextlib
import logging
import re
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from app import earlier, web
from app import memory as kept
from app.agent.cards import _answer, _then, outside_a_copy
from app.agent.ctx import Ctx
from app.agent.words import MAX_WHY
from app.api.usage import month_spend
from app.db.models import Agent, Conversation, Message, Provider, Room, Run
from app.model_client import ModelClient, ModelUnavailable, OwnStop
from app.providers import TIERS, NotListed, allowed, ask_once, list_providers, mode_of, own_request
from app.roles import LEAD, find_role, shown_name, title_of
from app.serialize import agent_out, run_out
from app.team import DIFFICULTY, Entry, asked_how_hard, quoted, tier_of, tier_range, would_run

if TYPE_CHECKING:
    from app.agent import AgentRunner

log = logging.getLogger("app.agent")

# K-bekleyen: cards that start to wait within this of the first are one desktop notice.
WAITS_SECONDS = 2.0

# A side of a comparison (slice 54) works only in a copy of its own.
OUTSIDE_A_COPY = (
    "{provider} works with tools of its own that could change the project from outside a "
    "working copy: it cannot work in a side of a comparison"
)

# A job of a night's run while the user is away (slice 106, `app.away`): its one copy.
OUTSIDE_A_JOB = (
    "{provider} works with tools of its own that could change the project from outside a "
    "working copy: it cannot work on a job while you're away"
)

# B-396: why a model was switched off, on its row on the Models page.
REFUSED_OFF = "{provider} refused it: not available on your account"
# On its record, beside its level (`Agent.effort_note`): why Copilot's auto picked its model.
AUTO_PICKED = "Copilot's auto picked {model}: “{why}”"
# ...which the next pick's replaces, the rest of the note kept: one, the latest, on record.
AUTO_PICKED_SAID = re.compile(r" ?Copilot's auto picked [^“]*: “[^”]*”")
# ...where it was the one model of the list still on: the provider is in no tier from then on.
REFUSED_LAST = " - it was this provider's only model, so no tier uses it now"

# What the opener of a sub-agent that could not finish is told after that, where a model one
# tier above the one it ran on may be picked for its role. Advice: nothing is switched.
ONE_TIER_UP = "One tier up: {provider} · {model} ({tier}) - {how}."

# K-model-puan 3: after the last round a check may go back to the Lead at Full auto, the
# same advice names the way: a new agent of the role, one tier up (a tier is the user's own
# ladder: no card for it), in a copy of its own. Nothing is opened by KOLONİ itself.
REOPEN_UP = (
    'or open a new {role} for it with spawn_agent, tier="{tier}" and why: it starts in a copy '
    "of its own, so give it the whole task and what the check said"
)
TOP_TIER = "It ran on the {tier} tier: there is no tier above it."
# The one question a lead whose model follows the message is opened with: asked of the
# first fast model that can answer with no tools (`team.asked_how_hard`), as the system's
# word and again over the message. Its answer is that model's guess, and is shown as one.
HOW_HARD = (
    "You are asked one thing: how hard is the message below for a coding agent to carry "
    "out in a software project? Answer with one word - easy, normal or hard - then a "
    "colon and one sentence that says why. Do not carry the message out, and use no tools."
)
# How long the "how hard" question waits for the project's map, in seconds (K-zor-ipucu).
MAP_FOR_FACTS = 5.0


class TiersMixin:
    async def _by_how_hard(self: "AgentRunner", ctx: Ctx) -> Ctx:
        """Where the conversation has its lead's model follow the message: the first fast
        model of the team guide is asked once, with no tools, how hard the message is,
        and the lead of this turn runs on the first model of the tier that stands for
        (easy: fast, normal: balanced, hard: strongest) - with what that model said on
        its record, as that model's guess. Returns the lead as it runs from here.

        Nothing is moved, and nothing claimed, where no fast model can be asked, the
        request fails, its answer cannot be read, or no model has the tier: the lead
        runs where it would have. The request holds a place like any model step, on the
        provider it goes to; what it spent is on a record of its own, under the model
        that was asked (`_asked`); Stop ends it. Not in a turn nobody watches: such a
        turn runs where its trigger's conversation says, and one moved to a CLI that
        works with its own tools would not start there."""
        with self._factory() as session:
            conversation = session.get_one(Conversation, ctx.cid)
            # (A plan turn's model is the strongest one, chosen as it opened; a side of a
            # comparison's, the one the user chose for it.)
            if (not conversation.lead_auto or not self._watched(ctx.run_id)
                    or session.get_one(Run, ctx.run_id).plan_turn or ctx.run_id in self._sides):
                return ctx
            would = would_run(session, find_role(session, LEAD), conversation, tools=ctx.tools)
            fast = asked_how_hard(session, would, self.providers)
            message = session.scalar(
                select(Message.content)
                .where(Message.run_id == ctx.run_id, Message.role == "user")
            )
            if fast is None or not message:
                return ctx
            asking, mode = self._on(session, ctx, *fast)
            project_id = conversation.project_id
        # K-zor-ipucu: the map started with the turn (`_map_start`), a little while; shielded,
        # so a Stop here leaves it to the Lead's brief. shortcut: not ready by then, the facts
        # name no part; wait longer if a big project's parts are seen missing.
        parts_map = None
        if (making := self._map_tasks.get(ctx.run_id)) is not None:
            with contextlib.suppress(TimeoutError):
                parts_map = await asyncio.wait_for(asyncio.shield(making), MAP_FOR_FACTS)
        try:
            with self._factory() as session:
                facts = earlier.how_hard_facts(
                    session, ctx.root, project_id, ctx.run_id, message, parts_map)
        except Exception as exc:  # (the facts only help: no turn fails for them)
            log.warning("run %s: no facts for how hard: %r", ctx.run_id, exc)
            facts = earlier.NO_FACTS
        self._ctxs[ctx.agent_id] = asking  # its place is counted where the question goes
        try:
            async with self._working(asking):
                try:
                    said, answer = await ask_once(asking.model, fast[1], [
                        {"role": "system", "content": HOW_HARD},
                        # Said again where the message is, which stands under it as
                        # data: a CLI's own rules tell it to do what the user's turn asks.
                        {"role": "user",
                         "content": f"{HOW_HARD}\n\nThe message:\n{quoted(message)}\n\n{facts}"},
                    ])
                except BaseException:
                    self._asked(ctx, asking, mode, None)  # sent, and not heard out
                    raise
                self._asked(ctx, asking, mode, answer)
        except ModelUnavailable:
            return ctx
        finally:
            self._ctxs[ctx.agent_id] = ctx
        said = _answer(said)
        read = re.match(r"\W*(easy|normal|hard)\b\W*(.*)", said, re.IGNORECASE | re.DOTALL)
        if read is None:
            return ctx
        with self._factory() as session:
            # Looked up afresh: the permission level, a provider or the guide may have
            # changed while the question was out.
            target, moved = would_run(
                session, find_role(session, LEAD), session.get_one(Conversation, ctx.cid),
                tools=ctx.tools,
            ).pick(TIERS[DIFFICULTY.index(read[1].lower())])
            if target is None:
                return ctx
            ctx, mode = self._on(session, ctx, *target)
        self._ctxs[ctx.agent_id] = ctx
        said = kept.one_line(f"{read[1].lower()}: {read[2]}").rstrip(": ")
        self._set_agent(
            ctx.cid, ctx.agent_id, provider_name=ctx.provider, provider_mode=mode,
            # (The tier it runs at: one lower where its plan stepped it down, 81c.)
            model_id=ctx.model_name, model_from=None, tier=dict(target[0].tiers)[target[1]],
            # The model's words, cut to what a reason may be: nobody can be asked again.
            chosen_why=_then(said, moved)[:MAX_WHY],
        )
        return ctx

    def _on(self: "AgentRunner", session, ctx: Ctx, entry: Entry,
            model: str) -> tuple[Ctx, str | None]:
        """An agent as it stands on another provider and model of the team guide, and
        how that provider runs (a CLI's mode)."""
        provider = session.get_one(Provider, entry.provider_id)
        return replace(
            ctx, model=self.providers.client(provider, model), provider=provider.name,
            provider_id=provider.id, model_name=model,
        ), mode_of(provider)

    def _asked(self: "AgentRunner", ctx: Ctx, asking: Ctx, mode: str | None, answer) -> None:
        """The question a lead was opened with goes on record (`_own_request`), and on
        the lead, who was asked."""
        self._own_request(ctx, asking, mode, answer)
        self._set_agent(ctx.cid, ctx.agent_id, asked_how_hard={
            "provider_name": asking.provider, "model_id": asking.model_name})

    def _own_request(self: "AgentRunner", ctx: Ctx, asking: Ctx, mode: str | None, answer) -> None:
        """A request KOLONİ made of a model itself goes on record: on a record of its
        own, under the provider and model it went to - not on the lead's, which may run
        somewhere else. `answer`: what came back, with what it spent; None where it was
        sent and not heard out (Stop, a failure), which is recorded as a model step that
        ends that way is: what it spent is not known."""
        with self._factory() as session:
            # Under the provider's name now: one renamed while this run went on keeps its record
            # (the record goes by the name, which a rename takes along).
            now_named = session.get(Provider, asking.provider_id) if asking.provider_id else None
            own_request(session, now_named.name if now_named else asking.provider, mode,
                        asking.model_name, answer, run_id=ctx.run_id, agent_id=ctx.agent_id)
            session.commit()

    async def _tell_budget(self: "AgentRunner", cid: str) -> None:
        """At 80% of its monthly budget a project's desktop is told so, once a month, where
        the user has desktop notifications on (`notify_desktop`). Never fails the turn."""
        with contextlib.suppress(Exception):
            month = datetime.now(UTC).astimezone().strftime("%Y-%m")
            with self._factory() as session:
                project = self._project(session, cid)
                if (project is None or not project.notify_desktop
                        or project.monthly_budget is None or project.budget_told == month):
                    return
                spend = month_spend(session, project)
                if not spend["warn"]:
                    return
                # Told before it is shown: a failed toast loses this month's notice, and two
                # conversations ending together may both show it - rare, and only a notice.
                project.budget_told, title = month, f"KOLONİ — {project.name}"
                session.commit()
            used = int(spend["share"] * 100 + 1e-9)  # (0.29 * 100 is 28.999999999999996)
            least = "at least " if spend["at_least"] else ""
            await web.show(title, f"This project has used {least}{used}% of its monthly budget")

    def _tell_waits(self: "AgentRunner", ctx: Ctx, asked: asyncio.Future) -> None:
        """K-bekleyen: a card or a question that starts to wait for the user (`_users_word`)
        shows one desktop notice where the project has them on (`notify_desktop`) - those that
        start within `WAITS_SECONDS` of the first as one, none for what was answered meanwhile
        (by the user, or by the Lead for them). Never fails the turn.
        shortcut: it says who waits, not on what - a command or a question is an agent's words
        and may hold a secret; add each card's own KOLONİ-written title if users ask for it."""
        with contextlib.suppress(Exception):
            waiting = self._users_awaited.get(ctx.cid)
            if waiting is None:
                with self._factory() as session:
                    project = self._project(session, ctx.cid)
                    if project is None or not project.notify_desktop:
                        return
                    title = f"KOLONİ — {project.name}"
                later = self.call_later or asyncio.get_running_loop().call_later
                later(WAITS_SECONDS, self._show_waits, ctx.cid, title)
                waiting = self._users_awaited[ctx.cid] = []
            if any(asked is one for *_told, one in waiting):
                return  # (told again by the Lead that gave it up before its notice)
            question = any(asked is one for one in self._answers.values())
            who = ctx.name if ctx.depth and ctx.name else title_of(ctx.role)
            waiting.append((who, question, asked))

    def _show_waits(self: "AgentRunner", cid: str, title: str) -> None:
        still = [(who, question) for who, question, asked in self._users_awaited.pop(cid, [])
                 if not asked.done() and asked not in self._lead_taking]
        if not still or not self._toasts.take(cid):
            return
        (who, question), *more = still
        said = (f"{len(still)} cards wait for you" if more else
                f"{who} asks you a question" if question else f"{who} waits for you")

        async def show() -> None:
            with contextlib.suppress(Exception):
                await web.show(title, said)

        self._telling.add(task := asyncio.ensure_future(show()))
        task.add_done_callback(self._telling.discard)

    def _count_tokens(
        self: "AgentRunner", ctx: Ctx, sent: int | None, made: int | None, step: bool = True,
        read: int | None = None, written: int | None = None,
        nano_aiu: int | None = None, premium: float | None = None,
    ) -> None:
        """Add a model's reported usage to the agent, and to the run for its lead. Not a
        `step` of the agent's own (a web search the API made for it): what that sent is
        spent, but it is not the size of the agent's conversation. `read`, `written`:
        what of `sent` the provider says came from its cache and went into it."""
        if ctx.discussion in self._spent_in:
            # A speech: what it reports is held against the discussion's budget too.
            self._spent_in[ctx.discussion] += (sent or 0) + (made or 0)
        with self._factory() as session:
            agent = session.get_one(Agent, ctx.agent_id)
            holders = [agent, session.get_one(Run, ctx.run_id)] if ctx.depth == 0 else [agent]
            if sent is not None:
                # What was spent: every step's, added up - a step is paid for whole.
                agent.input_tokens_total = (agent.input_tokens_total or 0) + sent
            if read is not None:
                agent.cache_read_tokens = (agent.cache_read_tokens or 0) + read
            if written is not None:
                agent.cache_write_tokens = (agent.cache_write_tokens or 0) + written
            if nano_aiu is not None:  # (Copilot's own units: each run a session of its own)
                agent.nano_aiu = (agent.nano_aiu or 0) + nano_aiu
            if premium is not None:
                agent.premium_requests = (agent.premium_requests or 0) + premium
            # A member's steps while its room runs are the room's - and (K-oda-lead, S7) its
            # opener's while it follows it - as billed: all each step sent and wrote, as usage
            # and a turn's token limit count it. B-390: only while it runs - not what the agents
            # spent before it, nor (a coordinator taken up) after it.
            room = self._rooms.get(ctx.run_id)
            counted = room if room is not None and room.outcome is None and (
                ctx.agent_id in room.members) else (
                None if ctx.answering else self._following.get(ctx.agent_id))
            if counted is not None and counted.outcome is None and (
                    sent is not None or made is not None):
                row = session.get_one(Room, counted.id)
                row.tokens = (row.tokens or 0) + (sent or 0) + (made or 0)
            for holder in holders:
                if sent is not None and step:
                    # Each step resends the whole history, so the latest prompt size is
                    # the conversation's size; summing would count earlier turns again.
                    holder.input_tokens = sent
                if made is not None:
                    holder.output_tokens = (holder.output_tokens or 0) + made
            session.commit()
            agent_payload = agent_out(agent)
            run_payload = run_out(session.get_one(Run, ctx.run_id))
        self.bus.emit(ctx.cid, ctx.run_id, "agent.updated", agent_payload)
        if ctx.depth == 0:
            self.bus.emit(ctx.cid, ctx.run_id, "run.updated", run_payload)
        self._hold_room_to(ctx.run_id, "tokens", ctx.agent_id)

    def _ran_on(self: "AgentRunner", ctx: Ctx, model: str | None,
                why: str | None = None) -> None:
        """Put the model a CLI says it used on record: that, not the name it was asked
        for or the one in its settings, is what ran - in a turn taken on a message too.
        One Copilot's auto picked is marked so (`model_from` "auto": an agent going on from
        it asks for auto again, `_ran_on_before`, `_ctx_after`), with `why` it picked it."""
        if not model:
            return
        picked = "auto" if model != "auto" and getattr(ctx.model, "level_named", False) and (
            getattr(ctx.model, "command", "") == "copilot") else None
        with self._factory() as session:
            agent = session.get_one(Agent, ctx.agent_id)
            known = agent.model_id == model and agent.model_from == picked
            note = agent.effort_note
        self._reported.add(ctx.agent_id)
        if picked and why:  # (the CLI's words: one line each, cut, and no closing quote of ours)
            said = AUTO_PICKED.format(model=kept.one_line(model)[:200], why=kept.one_line(
                str(why)).replace("”", '"')[:MAX_WHY])
            others = AUTO_PICKED_SAID.sub("", note or "").strip()
            if f"{others} {said}".strip() != note:
                self._set_agent(ctx.cid, ctx.agent_id, effort_note=f"{others} {said}".strip())
        if known:
            return  # said again at every step: nothing new to tell anyone
        self._set_agent(ctx.cid, ctx.agent_id, model_id=model, model_from=picked)
        if ctx.depth == 0:
            self._update_run(ctx.run_id, ctx.cid, model_id=model)

    def _still_allowed(self: "AgentRunner", ctx: Ctx) -> None:
        """Before an agent takes a turn - its first, or one on a message: its provider
        may have been told since to run only the models listed for it. In a side of a
        comparison, one that could change the project from outside its copy does not run."""
        if ctx.run_id in self._sides and outside_a_copy(ctx.model):
            raise OwnStop(OUTSIDE_A_COPY.format(provider=shown_name(ctx.provider or "")))
        # shortcut: a night lets a CLI lead that works in its copy (Claude Code, Codex), each tool
        # it asks about judged; but Claude Code's Bash is not sandboxed - a command that writes
        # outside the copy without naming a path (`cd $HOME\...`, `%USERPROFILE%`) runs at Full
        # auto. Only Codex's sandbox keeps a CLI in its copy; hold Claude Code's Bash to the
        # copy (or ask its every command at night) if that is ever needed.
        if ctx.run_id in self._away_jobs and outside_a_copy(ctx.model):
            raise OwnStop(OUTSIDE_A_JOB.format(provider=shown_name(ctx.provider or "")))
        if ctx.provider_id is None:
            return
        with self._factory() as session:
            provider = session.get(Provider, ctx.provider_id)
            if provider is not None:
                allowed(provider, ctx.model_name)

    @staticmethod
    def _model_of(ctx: Ctx) -> ModelClient:
        if ctx.model is None:
            raise OwnStop("no model provider is set up")
        return ctx.model

    def _why(self: "AgentRunner", ctx: Ctx, exc: ModelUnavailable) -> str:
        """What a model's failure says, with its class kept for the agent's record: only
        from what the provider's side said. (A stop that is KOLONİ's own - a rule of
        its own, a setting of the user's, a CLI that cannot be started as this machine is
        set up - is not the provider's failure: no class, and so no advice.)
        B-396: a model the CLI refused as not on the account is switched off (`_refused`), and
        the agent may move to its tier's next (`_moved_on`), as on any failure of the provider."""
        if self._refused(ctx, exc) or not isinstance(exc, OwnStop):
            with self._factory() as session:
                provider = session.get(Provider, ctx.provider_id) if ctx.provider_id else None
                self._failed[ctx.agent_id] = (
                    str(exc), *self.providers.limits.why(provider, exc))
        # A model it may not run with is a setting: whose, so the user knows where to look.
        return f"{ctx.role}: {exc}" if isinstance(exc, NotListed) else str(exc)

    def _refused(self: "AgentRunner", ctx: Ctx, exc: ModelUnavailable) -> bool:
        """B-396 (live): Copilot CLI refuses a model of its card the account does not have
        ('Model "gpt-6.1-sol" from --model flag is not available.'; at session.create
        `CopilotNativeClient` says it as an OwnStop). Its row on the provider's list is switched
        off as the Models page's On does (`enabled`), with why (`off_why`): no tier offers it
        again, and the user may switch it back on - told so where it was the last one on
        (`REFUSED_LAST`). Only Copilot's words, in its own phrasing: whether the failure was
        such a refusal. R194: the model is the one the words name, wherever in them (a step's
        failure may say it after its CLI's name) - the agent's own, or its provider's default
        where the agent was given none by name."""
        said = re.search(r'Error: Model "([^"]+)" from --model flag is not available'
                         r"|Copilot can't use (\S+) on your account", str(exc))
        if said is None:
            return False
        model = said.group(1) or said.group(2)
        with self._factory() as session:
            provider = session.get(Provider, ctx.provider_id or "")
            if provider is None or provider.kind != "copilot_cli" or model != (
                    ctx.model_name or provider.default_model):
                return False
            rows = provider.models or []
            if any(m["name"] == model and m.get("enabled", True) for m in rows):
                why = REFUSED_OFF.format(provider=shown_name(provider.name)) + (
                    "" if any(m["name"] != model and m.get("enabled", True)
                              for m in rows) else REFUSED_LAST)
                provider.models = [{**m, "enabled": False, "off_why": why}
                                   if m["name"] == model else m for m in rows]
                session.commit()
        return True

    def _why_failed(
        self: "AgentRunner", agent_id: str, error: str | None
    ) -> tuple[str | None, datetime | None]:
        """What `_why` kept for an agent, for the error it was kept with and no other: an
        agent that ends another way - or well - has none."""
        said, failure, resets = self._failed.pop(agent_id, (None, None, None))
        return (failure, resets) if said is not None and said == error else (None, None)

    def _room(self: "AgentRunner", child: Ctx) -> str:
        """What the opener of an agent whose model failed is told last: why, as it is on
        record, and which other providers have room now. Advice: nothing is switched for
        it. Nothing for an agent KOLONİ's own rules stopped: no other provider helps there."""
        with self._factory() as session:
            agent = session.get_one(Agent, child.agent_id)
            if not agent.failure:
                return ""
            resets = agent.failure_resets_at
            why = f"Why it failed: {agent.failure}" + (
                f", resets {resets:%Y-%m-%d %H:%M} UTC. " if resets else ". ")
            return "\n\n" + why + self.providers.limits.room(
                session, list_providers(session), child.provider_id, agent.failure)

    def _one_tier_up(self: "AgentRunner", child: Ctx, after_check: bool = False) -> str:
        """What the opener of a sub-agent that could not finish is told after that: the
        first model of the tier above the one it ran on, where its role's rule lets the
        opener give that tier and one may be picked for it now. Advice: nothing is
        switched. Nothing in a turn nobody watches: no model is picked there.
        `after_check` (K-model-puan 3): after a check failed for the last time that goes
        to the Lead, how to open one there - and, at the top tier, that there is none."""
        if not self._watched(child.run_id) or child.provider_id is None:
            return ""
        with self._factory() as session:
            role = find_role(session, child.role)
            provider = session.get(Provider, child.provider_id)
            if role is None or provider is None or role.provider_id:
                return ""
            own = tier_of(provider, child.model_name)
            up = TIERS[TIERS.index(own) + 1] if own in TIERS[:-1] else None
            if up is None:
                return "\n\n" + TOP_TIER.format(tier=own) if after_check and own else ""
            if up not in tier_range(role):
                return ""
            found = would_run(
                session, role, session.get_one(Conversation, child.cid), tools=child.tools,
                tier=up,
            )
        if found.source != "tier" or found.model_id is None:
            return ""
        return "\n\n" + ONE_TIER_UP.format(
            provider=quoted(shown_name(found.provider.name)), model=quoted(found.model_id),
            tier=up, how=REOPEN_UP.format(role=child.role, tier=up) if after_check
            else f"give the job again with tier {up}",
        )

    def _told(self: "AgentRunner", agent_id: str, error: str | None) -> str:
        """Why an agent's turn failed, as another agent is told it."""
        return self._for_agents.pop(agent_id, None) or str(error)
