"""K-yargıç: at Full auto, in a turn the user watches, a harmful-looking command is first checked
against what the user themself wrote before it waits for them on a card - `JudgeMixin`."""

import asyncio
import hashlib
import json
import logging
from typing import TYPE_CHECKING

from sqlalchemy import literal_column, select

from app import away, judge, raw
from app import memory as kept
from app.agent.cards import _answer
from app.agent.ctx import Ctx
from app.commands import harm_class, with_cwd
from app.db.models import Conversation, Message, Provider, Run, project_of
from app.providers import ask_once
from app.roles import LEAD, find_role
from app.team import asked_how_hard, would_run

if TYPE_CHECKING:
    from app.agent import AgentRunner

log = logging.getLogger("app.agent")
# Said once in the chat when the check stands aside for the rest of a turn (`_judgement`).
CHECK_STOOD_ASIDE = ("Full auto's check of your words refused {count} this turn: until the turn "
                     "ends, each harmful-looking command waits for you on a card.")


class JudgeMixin:
    async def _judged(self: "AgentRunner", ctx: Ctx, command: str, cwd: str | None, reason: str,
                      asked_anyway: bool = False) -> tuple[str, dict | None]:
        """K-yargıç: `reason`, why `command` (run in `cwd`, as `with_cwd` judges it) waits for
        the user, checked first against the user's own words where the project says so
        (`Project.full_auto_check` "judge"): ("", record) - a line of theirs names it, and it
        runs with no card, that line on its record; (reason, record) - the check found none,
        and its card says so, or (record "refuse") a sentence of theirs forbids it, and it is
        neither asked nor run; (reason, None) - not checked: no reason, one asked at every level
        (`asked_anyway`, `harm_class` other than "soft"), a side of a comparison, not a watched
        Full auto turn, the check off or stood aside for the turn (`_stood_aside`), no project,
        the turn over its token limit, no Fast model that answers with no tools, no room on its
        provider, or any failure.
        What it reads: the user's preferences, this project's rules as saved (the column - never
        the folder's `.koloni/rules.md`, which a pull or a script may change), and their own
        messages in this chat (`Run.by_user`), each masked (`raw.hidden`) - never an agent's
        words, a tool's result or a file. One tool-less request of the Fast tier's first model
        (`ask_once`), in the turn's usage (`_own_request`); a verdict is kept for the turn by
        command, folder and those words as they are (`_judge_cache`: a rule taken away is asked
        again). Whatever goes wrong in it but a Stop is today's card."""
        try:
            return await self._judging(ctx, command, cwd, reason, asked_anyway)
        except Exception:
            log.warning("run %s: the check of the user's words failed", ctx.run_id, exc_info=True)
            return reason, None

    async def _judging(self: "AgentRunner", ctx: Ctx, command: str, cwd: str | None, reason: str,
                       asked_anyway: bool) -> tuple[str, dict | None]:
        """`_judged`'s work, which may raise. ☾ Away: in a job too, its chat at Full auto
        (`_away_full_auto`) - its check reads the chat the user went away from."""
        if (not reason or asked_anyway or ctx.run_id in self._sides
                or self._stood_aside(ctx.run_id)
                or harm_class(with_cwd(command, cwd), False) != "soft"
                or not (self._full_auto(ctx) or self._away_full_auto(ctx))):
            return reason, None
        with self._factory() as session:
            conversation = session.get_one(Conversation, ctx.cid)
            project = project_of(session, conversation)
            if project is None or project.full_auto_check != "judge":
                return reason, None
            # (A job's: the chat the user went away from - never its task's own words.)
            night = away.night_of(session, ctx.cid) if ctx.run_id in self._away_jobs else None
            texts = self._users_words(session, night.conversation_id if night else ctx.cid,
                                      project.rules)
            key = (command.strip(), cwd, hashlib.sha256(
                json.dumps(texts, sort_keys=True).encode()).hexdigest())
            if key in (cache := self._judge_cache.setdefault(ctx.run_id, {})):
                return self._judgement(ctx, reason, cache[key])
            limit = project.turn_token_limit
            fast = asked_how_hard(session, would_run(
                session, find_role(session, LEAD), conversation), self.providers, "fast")
            if (limit and self._turn_spent(session, ctx.run_id)[0] > limit or fast is None
                    or not self._has_room(
                        session, session.get_one(Provider, fast[0].provider_id), project)):
                return reason, None
            asking, mode = self._on(session, ctx, *fast)
        asked = judge.prompt(texts, {
            "command": raw.hidden(command), "where": raw.hidden(cwd) if cwd else "not known",
            "flagged_because": raw.hidden(reason),
            "by": "Orchestrator" if not ctx.depth else raw.hidden(f"sub-agent {ctx.role}")})
        cache[key] = await self._judge_asks(ctx, asking, mode, asked, texts)
        return self._judgement(ctx, reason, cache[key])

    @staticmethod
    def _users_words(session, cid: str, rules: str | None) -> dict[str, list[str]]:
        """What the judge reads (`judge.said`), each masked: the user's preferences, this
        project's `rules` as saved, and their own messages in chat `cid` - those whose turn the
        app's own page started (`Run.by_user`), not one KOLONİ or an agent wrote as theirs."""
        messages = session.scalars(
            select(Message.content).join(Run, Run.id == Message.run_id).where(
                Message.conversation_id == cid, Message.role == "user",
                Message.agent_id.is_(None), Run.by_user.is_(True))
            .order_by(Message.created_at.desc(), literal_column("messages.rowid").desc())
            .limit(judge.MOST_MESSAGES)).all()
        return judge.said(raw.hidden(kept.preferences(session) or ""), raw.hidden(rules or ""),
                          list(map(raw.hidden, messages)))

    async def _judge_asks(self: "AgentRunner", ctx: Ctx, asking: Ctx, mode: str | None,
                          asked: str, texts: dict[str, list[str]]) -> dict | None:
        """`_judged`'s one request: the record of what the judge said, or None where it failed,
        timed out or said nothing that can be read. Stop goes on as Stop."""
        try:
            try:
                async with asyncio.timeout(judge.JUDGE_SECONDS):
                    said, answer = await ask_once(asking.model, asking.model_name or "", [
                        {"role": "user", "content": asked}])
            except BaseException:
                self._own_request(ctx, asking, mode, None)  # sent, and not heard out
                raise
            self._own_request(ctx, asking, mode, answer)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("run %s: the check of the user's words failed", ctx.run_id, exc_info=True)
            return None
        got = judge.verdict(_answer(said), texts)
        if got is None:
            return None
        return {**got, "model": f"{asking.provider} · {asking.model_name}"}

    def _stood_aside(self: "AgentRunner", run_id: str) -> bool:
        """Whether the check stands aside for the rest of turn `run_id`: it refused
        MOST_REFUSED_IN_A_ROW commands in a row, or MOST_REFUSED_IN_A_TURN in all."""
        row, turn = self._judge_refused.get(run_id, (0, 0))
        return row >= judge.MOST_REFUSED_IN_A_ROW or turn >= judge.MOST_REFUSED_IN_A_TURN

    def _judgement(self: "AgentRunner", ctx: Ctx, reason: str,
                   record: dict | None) -> tuple[str, dict | None]:
        """`_judged`'s answer from a record: no reason where it says run; not checked where it
        failed, or the check stood aside since it was asked. Counted for the turn, by all its
        agents: a refusal (one kept for it too) in a row and in all, a run or an ask ends a row;
        the refusal that reaches a limit is one still, and the chat is told."""
        if record is None or self._stood_aside(ctx.run_id):
            return reason, None
        row, turn = self._judge_refused.get(ctx.run_id, (0, 0))
        refused = record["verdict"] == "refuse"
        row, turn = (row + 1, turn + 1) if refused else (0, turn)
        self._judge_refused[ctx.run_id] = (row, turn)
        if self._stood_aside(ctx.run_id):
            self._koloni_line(ctx.cid, ctx.run_id, CHECK_STOOD_ASIDE.format(
                count=f"{row} commands in a row" if row >= judge.MOST_REFUSED_IN_A_ROW
                else f"{turn} commands"))
        return ("" if record["verdict"] == "run" else reason), dict(record)
