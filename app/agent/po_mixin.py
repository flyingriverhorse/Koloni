"""The Assistant PO after a turn (the user, 6-7 Nov): follow-up tasks proposed for the To-do
list, and at Full auto in a watched turn the Lead's word on them - `PoMixin`."""

import asyncio
import logging
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app import backlog, earlier, injection, raw, topics
from app.agent.cards import _answer
from app.agent.ctx import Ctx, announce
from app.agent.questions_mixin import LEAD_LANGUAGE
from app.api.usage import over_month, past_its_limit
from app.db.models import BacklogTask, Conversation, Message, Project, Provider, Run, project_of
from app.limits import has_room
from app.providers import ask_once, mode_of
from app.roles import LEAD, find_role
from app.serialize import run_out
from app.team import Entry, Would, another_account_of, asked_how_hard, quoted, would_run

if TYPE_CHECKING:
    from app.agent import AgentRunner

log = logging.getLogger(__name__)
# Where a proposal's words read like orders (`injection.scan`): said so on its row.
WHERE = "a To-do proposal of the Assistant PO"


@dataclass(frozen=True)
class PoTurn:
    """What `_propose_tasks` needs of a turn that is over: its Lead as it ended, whether the
    Lead may decide at Full auto (a watched turn of the user's, not a night's nor a trigger's),
    and the providers whose pay-per-token use the user refused in it."""

    lead: Ctx
    decides: bool
    refused: frozenset[str]


@dataclass(frozen=True)
class _Asked:
    asking: Ctx
    mode: str | None
    record: str
    sources: str
    titles: list[str]
    turned_down: list[str]
    project_id: str
    full: bool


def po_entries(entries: list[Entry], spent: set[str], passed: set[str]) -> list[Entry]:
    """Of `entries`, by name, not those `passed` over or `spent` (no room, a limit, a plan's
    share) - nor another account of a CLI spent (`another_account_of`)."""
    gone = [entry for entry in entries if entry.name in spent]
    return [entry for entry in entries if entry.name not in spent | passed
            and not any(another_account_of(entry, one) for one in gone)]


class PoMixin:
    def _po_turn(self: "AgentRunner", ctx: Ctx, decides: bool) -> PoTurn:
        """Taken as the turn ends, while it still holds what it was told."""
        refused = {key[1] for key, yes in self._paid_word.items()
                   if key[0] == ctx.run_id and not yes}
        refused |= {key[1] for key, _other in self._paid_asked.values() if key[0] == ctx.run_id}
        return PoTurn(self._ctxs.get(ctx.agent_id, ctx), decides, frozenset(refused))

    def _po_later(self: "AgentRunner", turn: PoTurn) -> None:
        """Once the turn has let go of everything (`execute`'s `finally`): nothing waits for
        it - not the next turn, nor a compaction. Cancelled with the app; none as it closes."""
        if self._closing:
            return
        self._noting.add(task := asyncio.ensure_future(self._propose_tasks(turn)))
        task.add_done_callback(self._noting.discard)

    async def _propose_tasks(self: "AgentRunner", turn: PoTurn) -> None:
        """Where the project has it on (`suggest_tasks`) and the turn did something
        (`backlog.po_asked`): the first model of its tier (`suggest_tier`) that may be asked
        now (`_po_model`) is given the turn's record and the open tasks' titles, and proposes
        at most three follow-up tasks. Each whose words are an agent's or a tool's in the turn
        goes on the To-do list as proposed, the user's to add (`backlog.proposed`); at Full
        auto in a watched turn the Lead decides them (`_lead_decides`). Not over the month's
        budget, past the turn's limit, or while that provider is at work for an agent. It never
        fails anything: why nothing was proposed is in the log - and, where it was asked, on
        the turn's record for the canvas (`_po_noted`).
        shortcut: with no model of that tier nothing is proposed and no page says why, as with
        `_assess`; say it under the setting if users miss it."""
        ctx = turn.lead
        try:
            with self._factory() as session:
                asked = self._po_setup(session, turn)
            if asked is None:
                return
            po: dict = {"provider_name": asked.asking.provider,
                        "model_id": asked.asking.model_name, "heard": False}
            try:
                heard = await self._asked_once(ctx, asked.asking, asked.mode, [
                    {"role": "system", "content": backlog.PROPOSE},
                    {"role": "user", "content": backlog.propose_question(
                        asked.record, asked.titles, asked.turned_down)},
                ])
            except Exception:
                self._po_noted(ctx, po)  # sent, not heard out (not why: a provider's words)
                raise
            if heard is None:
                log.info("run %s: no To-do proposals: an agent is at work on that provider",
                         ctx.run_id)
                return
            said, answer = heard
            po |= {"heard": True, "model_id": answer.model or po["model_id"],
                   "input_tokens": answer.input_tokens, "output_tokens": answer.output_tokens}
            ids: list[str] = []
            try:
                found = backlog.proposed(said, asked.sources, asked.titles, asked.turned_down,
                                         ctx.run_id, po)
                ids = self._proposals_added(ctx, asked.project_id, found, po) if found else []
            finally:  # (heard out: on record however adding them went)
                self._po_noted(ctx, {**po, "proposed": len(ids)})
            if not ids:
                return
            announce(self._factory, self.bus, asked.project_id, "backlog.changed")
            if asked.full:
                await self._lead_decides(ctx, ids)
        except Exception as exc:  # (ModelUnavailable, a timeout, ...: no proposals)
            log.warning("run %s: no To-do proposals: %r", ctx.run_id, exc)

    def _po_setup(self: "AgentRunner", session, turn: PoTurn) -> _Asked | None:
        ctx = turn.lead
        conversation = session.get_one(Conversation, ctx.cid)
        project = project_of(session, conversation)
        if (project is None or not project.suggest_tasks or over_month(session, project)
                or not backlog.po_asked(session, session.get_one(Run, ctx.run_id))):
            return None
        limit = project.turn_token_limit
        if limit and self._turn_spent(session, ctx.run_id)[0] > limit:
            return None
        would = would_run(session, find_role(session, LEAD), conversation, tools=ctx.tools)
        picked = self._po_model(session, would, project, turn.refused)
        if picked is None:
            return None
        asking, mode = self._on(session, ctx, *picked)
        record, sources = backlog.po_record(
            session, ctx.run_id, self._turn_in_words(session, ctx), project.pass_env)
        titles = [task.title for task in backlog.ordered(session, project.id)
                  if task.status != "done"]
        return _Asked(asking, mode, record, sources, titles, list(project.po_rejected or []),
                      project.id, turn.decides and conversation.permission_mode == "full_auto")

    def _po_model(self: "AgentRunner", session, would: Would, project: Project,
                  refused: frozenset[str]):
        """The first model of the project's tier that may be asked with no tools
        (`asked_how_hard`), of those the user's word allows now: not down when last looked at,
        refused pay-per-token use in the turn, past its limit, past its plan's step-down share
        or with no room (`_has_room`) - nor, past those last, another account of its CLI
        (K-claude-hesap, as `Would.pick`)."""
        def spent(entry) -> bool:
            return (entry.name in would.past_limit or entry.name in would.plan_used
                    or not self._has_room(
                        session, session.get_one(Provider, entry.provider_id), project))

        out = {entry.name for entry in would.pick_from if spent(entry)}
        return asked_how_hard(session, replace(would, pick_from=po_entries(
            would.pick_from, out, {entry.name for entry in would.pick_from
                                   if entry.name in would.down or entry.provider_id in refused})),
            self.providers, project.suggest_tier)

    def _proposals_added(self: "AgentRunner", ctx: Ctx, project_id: str,
                         found: list[dict], po: dict) -> list[str]:
        """Each on the To-do list, proposed - where the setting is still on, and none like a
        task that is there now (another turn's may have come meanwhile): one dropped is on
        `po` too. One whose words read like orders (`injection`) is marked so - the Lead adds
        none of those - and the user warned in its chat."""
        warned: list[str] = []
        with self._factory() as session:
            project = session.get_one(Project, project_id)
            titles = [task.title for task in backlog.ordered(session, project_id)
                      if task.status != "done"] + list(project.po_rejected or [])
            ids = []
            if not project.suggest_tasks:
                log.info("run %s: To-do proposals dropped: the setting was turned off",
                         ctx.run_id)
                po.setdefault("dropped", []).extend(
                    {"title": one["title"][:80], "why": "the setting was turned off"}
                    for one in found)
            for one in found if project.suggest_tasks else []:
                if like := next((title for title in titles
                                 if backlog.alike(one["title"], title)), None):
                    backlog.dropped(ctx.run_id, one["title"], f"like {like[:80]!r}, there now",
                                    po)
                    continue
                titles.append(one["title"])
                fields = {key: value for key, value in one.items() if key != "why"}
                task = backlog.add(session, project_id, fields, "agent")
                rules = injection.scan("\n".join(filter(None, [*fields.values(), one["why"]])))
                task.po = {"chat": ctx.cid, "why": one["why"],
                           **({"injection": rules} if rules else {})}
                warned += rules
                session.flush()
                ids.append(task.id)
            session.commit()
        if warned:
            injection.warn(self._factory, self.bus, ctx.cid, ctx.run_id, None,
                           list(dict.fromkeys(warned)), "agent", WHERE)
        return ids

    async def _lead_decides(self: "AgentRunner", ctx: Ctx, ids: list[str]) -> None:
        """At Full auto the Lead's model is asked once, with no tools, whether each proposal
        goes on the To-do list, and why: added ones are todo - started by nobody's word but the
        user's (`backlog.unseen`) - the rest wait proposed, its word on them shown under
        "Decided for you" for the user's OK or Change. Not over the month's budget nor where the
        Lead's provider has no room; on a CLI only where the user lets the Lead answer while
        away (a request of their plan, as `_lead_answers`); not where the To-do list runs by
        itself; never one whose words read like orders. Anything else - no answer it can read
        included - and they wait for the user."""
        lead = ctx
        with self._factory() as session:
            conversation = session.get_one(Conversation, ctx.cid)
            project = session.get_one(Project, conversation.project_id)
            provider = session.get(Provider, lead.provider_id or "")
            tasks = [session.get_one(BacklogTask, task_id) for task_id in ids]
            ids = [task.id for task in tasks if not (task.po or {}).get("injection")]
            if (not ids or provider is None or lead.model is None or project.backlog_auto
                    or not self._has_room(session, provider, project)):
                return
            mode = mode_of(provider)
            if mode is not None and project.when_away != "lead":
                return
            users = topics.first_line(session.scalar(select(Message.content).where(
                Message.run_id == ctx.run_id, Message.role == "user",
                Message.agent_id.is_(None)).limit(1)))
            given = backlog.decide_question([task for task in tasks if task.id in ids]) + (
                LEAD_LANGUAGE.format(said=quoted(raw.hidden(users)[:200])) if users else "")
            project_id = project.id
        native = getattr(lead.model, "native", False)
        talker = getattr(lead.model, "talker", None) if native else None
        model = talker() if talker else lead.model
        if getattr(model, "native", False):
            return  # (a CLI that keeps tools of its own is not handed agents' words)
        heard = await self._asked_once(ctx, replace(lead, model=model), mode, [
            {"role": "user", "content": given}])
        decided = backlog.lead_decided(heard[0] if heard else "", len(ids))
        added = 0
        with self._factory() as session:
            # (Read again: the list may have been set to run by itself meanwhile.)
            if session.get_one(Project, project_id).backlog_auto:
                return
            for n, task_id in enumerate(ids, 1):
                task = session.get(BacklogTask, task_id)
                # (Not one the user decided meanwhile.)
                if n not in decided or task is None or task.status != "proposed":
                    continue
                add, why = decided[n]
                task.status = "todo" if add else task.status
                task.po = {**(task.po or {}), "lead": "add" if add else "no", "lead_why": why}
                added += add
            session.commit()
        if decided:
            announce(self._factory, self.bus, project_id, "backlog.changed")
            self._po_noted(ctx, {"lead_added": added})

    def _po_noted(self: "AgentRunner", ctx: Ctx, po: dict) -> None:
        """The Assistant PO's request after `ctx`'s turn, as it went, on the turn's record for
        the canvas (`Run.po`, `PoOut`): `po` over what is there. Never fails what comes after
        it (the proposals announced, the Lead's word): a chat deleted meanwhile has no run, and
        a busy database only loses the node."""
        try:
            with self._factory() as session:
                run = session.get(Run, ctx.run_id)
                if run is None:
                    return
                run.po = {**(run.po or {}), **po}
                session.commit()
                payload = run_out(run)
            self.bus.emit(ctx.cid, ctx.run_id, "run.updated", payload)
        except Exception as exc:
            log.warning("run %s: the Assistant PO's request not on its record: %r", ctx.run_id,
                        exc)

    def _has_room(self: "AgentRunner", session, provider: Provider, project: Project) -> bool:
        """Whether KOLONİ may spend a request on `provider` for the project now: under its month's
        budget and the provider's own limit, and its plan not known to be used up."""
        return not (over_month(session, project) or past_its_limit(session, provider)) and has_room(
            session, provider, self.providers.limits.last(provider), never_ran_is_room=True
        ) is not None

    async def _asked_once(self: "AgentRunner", ctx: Ctx, asking: Ctx, mode: str | None,
                          messages: list[dict]) -> tuple[str, Any] | None:
        """`messages` asked of `asking`'s model once, with no tools, as KOLONİ's own request in
        `ctx`'s turn (`_own_request`), in the summariser's time. What it said, its thinking
        taken off, and the answer as on record (what it spent); None, asking nothing, where an
        agent is at work on that provider now: the user's turn comes first, and this takes no
        place.
        shortcut: only looked at as it starts - an agent of a turn started meanwhile shares the
        provider with it; queue it behind them if a busy local server is seen to slow."""
        if any(self._ctxs[agent].provider_id == asking.provider_id
               for agent in self._placed if agent in self._ctxs):
            return None
        model: Any = asking.model
        name = asking.model_name or (await model.info()).model_id
        asking = replace(asking, model_name=name)
        try:
            async with asyncio.timeout(earlier.SUMMARISER_SECONDS):
                said, answer = await ask_once(model, name, messages)
        except BaseException:
            self._own_request(ctx, asking, mode, None)  # sent, not heard out
            raise
        self._own_request(ctx, asking, mode, answer)
        return _answer(said).strip(), answer
