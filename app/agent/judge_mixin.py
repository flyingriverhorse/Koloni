"""K-yargıç: at Full auto, in a turn the user watches, a harmful-looking command is first checked
against what the user themself wrote before it waits for them on a card - `JudgeMixin`."""

import asyncio
import logging
from typing import TYPE_CHECKING

from sqlalchemy import literal_column, select

from app import judge, raw
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


class JudgeMixin:
    async def _judged(self: "AgentRunner", ctx: Ctx, command: str, cwd: str | None, reason: str,
                      asked_anyway: bool = False) -> tuple[str, dict | None]:
        """K-yargıç: `reason`, why `command` (run in `cwd`, as `with_cwd` judges it) waits for
        the user, checked first against the user's own words where the project says so
        (`Project.full_auto_check` "judge"): ("", record) - a line of theirs names it, and it
        runs with no card, that line on its record; (reason, record) - the check found none,
        and its card says so; (reason, None) - not checked: no reason, one asked at every level
        (`asked_anyway`, `harm_class` other than "soft"), a side of a comparison, not a watched
        Full auto turn, the check off, no project, the turn over its token limit, no Fast
        model that answers with no tools, no room on its provider, or any failure.
        What it reads: the user's preferences, this project's rules as saved (the column - never
        the folder's `.koloni/rules.md`, which a pull or a script may change), and their own
        messages in this chat (`Run.by_user`), each masked (`raw.hidden`) - never an agent's
        words, a tool's result or a file. One tool-less request of the Fast tier's first model
        (`ask_once`), in the turn's usage (`_own_request`); a verdict is kept for the turn by
        command and folder (`_judge_cache`)."""
        if (not reason or asked_anyway or ctx.run_id in self._sides
                or harm_class(with_cwd(command, cwd), False) != "soft"
                or not self._full_auto(ctx)):
            return reason, None
        with self._factory() as session:
            conversation = session.get_one(Conversation, ctx.cid)
            project = project_of(session, conversation)
            if project is None or project.full_auto_check != "judge":
                return reason, None
            key = (command.strip(), cwd)
            if key in (cache := self._judge_cache.setdefault(ctx.run_id, {})):
                return self._judgement(reason, cache[key])
            limit = project.turn_token_limit
            fast = asked_how_hard(session, would_run(
                session, find_role(session, LEAD), conversation), self.providers, "fast")
            if (limit and self._turn_spent(session, ctx.run_id)[0] > limit or fast is None
                    or not self._has_room(
                        session, session.get_one(Provider, fast[0].provider_id), project)):
                return reason, None
            asking, mode = self._on(session, ctx, *fast)
            messages = session.scalars(
                select(Message.content).join(Run, Run.id == Message.run_id).where(
                    Message.conversation_id == ctx.cid, Message.role == "user",
                    Message.agent_id.is_(None), Run.by_user.is_(True))
                .order_by(Message.created_at.desc(), literal_column("messages.rowid").desc())
                .limit(judge.MOST_MESSAGES)).all()
            texts = judge.said(raw.hidden(kept.preferences(session) or ""),
                               raw.hidden(project.rules or ""), list(map(raw.hidden, messages)))
        asked = judge.prompt(texts, {
            "command": raw.hidden(command), "where": raw.hidden(cwd) if cwd else "not known",
            "flagged_because": reason,
            "by": "Orchestrator" if not ctx.depth else raw.hidden(f"sub-agent {ctx.role}")})
        cache[key] = await self._judge_asks(ctx, asking, mode, asked, texts)
        return self._judgement(reason, cache[key])

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
        if got["verdict"] == "refuse":  # (slice 2 refuses it; until then it is a card)
            got = {"verdict": "ask", "quote": "", "source": "", "why": ""}
        return {**got, "model": f"{asking.provider} · {asking.model_name}"}

    @staticmethod
    def _judgement(reason: str, record: dict | None) -> tuple[str, dict | None]:
        """`_judged`'s answer from a record: no reason where it says run."""
        if record is None:
            return reason, None
        return ("" if record["verdict"] == "run" else reason), dict(record)
