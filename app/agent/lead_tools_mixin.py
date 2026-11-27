"""The Orchestrator's own tools beside its agents' work: its plan shown to the user, the advisor,
its noted decisions, a pull request's feedback - `LeadToolsMixin` (0.1.11). Offered from
`AtWorkMixin._at_work_offered`, called through `AtWorkMixin._at_work_call`; what they keep of a
turn goes with it (`_lead_tools_forget`)."""

import asyncio
import logging
from typing import TYPE_CHECKING

from sqlalchemy import func, literal_column, select

from app import advisor, injection, masking, model_native
from app.agent.cards import _answer
from app.agent.ctx import Ctx
from app.commands import OutputMask
from app.db.models import Conversation, Project, ToolCall
from app.db.turn_models import NotedDecision
from app.model_client import OwnStop
from app.providers import ask_once
from app.roles import LEAD, find_role
from app.team import quoted, would_run
from app.tools import ToolError
from app.tools_at_work import (
    ASK_ADVISOR_SCHEMA,
    LINE_MOST,
    NOTE_DECISION_SCHEMA,
    NOTED,
    NOTED_FULL,
    NOTED_MOST,
    PLAN_SHOWN,
    UPDATE_PLAN_SCHEMA,
)

if TYPE_CHECKING:
    from app.agent import AgentRunner

log = logging.getLogger("app.agent")
LATE = "it did not answer in time, or could not be asked"


class LeadToolsMixin:
    def _lead_tools_init(self: "AgentRunner") -> None:
        """`_at_work_init`'s part for the Orchestrator's own tools."""
        # Task 5: the Orchestrator whose plan is shown, by its turn - its plan goes with the turn.
        self._planned: dict[str, Ctx] = {}
        # Task 9: how many times the advisor was asked, by the turn (`advisor.ASKS_MOST`).
        self._advised: dict[str, int] = {}

    def _lead_tools_forget(self: "AgentRunner", run_id: str) -> None:
        """`_shut_door`: the turn is over - what its Orchestrator's tools kept of it goes."""
        self._advised.pop(run_id, None)
        if (planned := self._planned.pop(run_id, None)) is not None:
            self._end_live(planned)

    def _lead_offered(self: "AgentRunner", ctx: Ctx, schemas: list[dict]) -> None:
        """`_at_work_offered`'s part: the tools of the Orchestrator at its own work that may open
        agents (spawn_agent is offered: not a plan turn, nor a comparison's side) - each where it
        is this one's. The same all through a turn: the tools are the prompt cache's first part."""
        if self._background_offered(ctx):  # (an API model's: a CLI's own plan is its own)
            schemas.append(UPDATE_PLAN_SCHEMA)
        schemas.append(ASK_ADVISOR_SCHEMA)
        schemas.append(NOTE_DECISION_SCHEMA)

    async def _lead_tool(self: "AgentRunner", ctx: Ctx, call_id: str, name: str, args: dict) -> str:
        """`_at_work_call`'s part for the Orchestrator's own tools, held to where they are offered
        (a model may name one it was not given)."""
        if name == "update_plan":
            return self._update_plan(ctx, args)
        if name == "ask_advisor":
            return await self._ask_advisor(ctx, args)
        if name == "note_decision":
            return self._note_decision(ctx, call_id, args)
        raise ToolError(f"unknown tool: {name}")

    def _update_plan(self: "AgentRunner", ctx: Ctx, args: dict) -> str:
        """update_plan: the API Orchestrator's plan, shown to the user as its own words - over the
        chat and in its window, as a CLI's plan is (`_show_live`) - each step masked and cut, at
        most PLAN_STEPS. Gone with the turn (`_lead_tools_forget`). Changes nothing else."""
        if not self._background_offered(ctx):
            raise ToolError("update_plan is not available: a CLI shows its own plan")
        steps = args.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ToolError("steps: the plan's steps, each {step, status}")
        mask = OutputMask(()).hide
        plan = model_native._plan(
            [
                {**one, "step": mask(" ".join(str(one.get("step") or "").split()))}
                for one in steps[: model_native.PLAN_STEPS]
                if isinstance(one, dict)
            ]
        )
        if not plan["plan"]:
            raise ToolError("steps: the plan's steps, each {step, status}")
        self._planned[ctx.run_id] = ctx
        self._show_live(ctx, plan)
        done = sum(one["status"] == "completed" for one in plan["plan"])
        return PLAN_SHOWN.format(k=min(done + 1, len(plan["plan"])), m=len(plan["plan"]))

    # --- Task 9: ask_advisor ---------------------------------------------------------------

    async def _ask_advisor(self: "AgentRunner", ctx: Ctx, args: dict) -> str:
        """ask_advisor: a second model's advice, at most `advisor.ASKS_MOST` times a turn (counted
        as it is asked, before anything is awaited: a CLI may call twice at once). Who is asked
        is `advisor.pick`'s - only a model that answers with its tools off, on another provider
        than the Orchestrator's unless the user chose it - and what it is sent is masked, as data
        (`advisor.prompt`); its request is KOLONİ's own in the turn (`_own_request`: under its
        model on Usage, in the turn's spend). Where none can be asked now - no model, no room, the
        turn past its token limit, no answer in its time - the Orchestrator is told why and goes
        on: never a failure, never a wait. Its answer is data: masked, cut, quoted, marked where
        it reads like orders."""
        summary, question = args.get("summary"), args.get("question")
        if not isinstance(question, str) or not question.strip():
            raise ToolError("missing required argument: question")
        if not isinstance(summary, str):
            raise ToolError("missing required argument: summary")
        asked = self._advised.get(ctx.run_id, 0)
        if asked >= advisor.ASKS_MOST:
            raise ToolError(advisor.TOO_MANY)
        self._advised[ctx.run_id] = asked + 1
        found = self._advisor_of(ctx)
        if isinstance(found, str):
            return advisor.NOT_NOW.format(why=found)
        asking, mode, steps = found
        mask = OutputMask(()).hide
        at_work = self._still_at_work(ctx)
        sent = advisor.prompt(
            advisor.cut(mask(summary), advisor.SUMMARY_MOST),
            advisor.cut(mask(question), advisor.QUESTION_MOST),
            [advisor.cut(mask(one), advisor.STEP_MOST) for one in steps],
            mask(at_work) if at_work else None,
        )
        said = await self._advice(ctx, asking, mode, sent)
        if said is None or not said.strip():
            return advisor.NOT_NOW.format(why=LATE if said is None else "it gave no answer")
        answer = advisor.cut(mask(said.strip()), advisor.ANSWER_MOST)
        # (looked at as written, every rule: a model of another provider's, not an agent's)
        marked = f"{injection.NOTE}\n" if injection.scan(said) else ""
        return advisor.ANSWERED.format(
            who=f"{asking.provider} · {asking.model_name}", answer=marked + quoted(answer)
        )

    def _advisor_of(self: "AgentRunner", ctx: Ctx) -> "tuple[Ctx, str | None, list[str]] | str":
        """Whom the advisor is now, how its provider runs, and the Orchestrator's last steps to
        send it - or why none can be asked (`_risk_no_room`'s, as Full auto's judge is held)."""
        with self._factory() as session:
            conversation = session.get_one(Conversation, ctx.cid)
            try:
                would = would_run(session, find_role(session, LEAD), conversation)
            except OwnStop:  # (no provider at all)
                return advisor.NO_MODEL
            picked = advisor.pick(
                session, would, self.providers, advisor.chosen(session), ctx.provider_id
            )
            if picked is None:
                return advisor.NO_MODEL
            project = session.get(Project, conversation.project_id or "")
            if project is not None and (why := self._risk_no_room(session, ctx, picked, project)):
                return why
            asking, mode = self._on(session, ctx, *picked)
            calls = session.execute(
                select(ToolCall.name, ToolCall.arguments, ToolCall.status, ToolCall.result)
                .where(
                    ToolCall.run_id == ctx.run_id,
                    ToolCall.agent_id == ctx.agent_id,
                    ToolCall.name != "ask_advisor",  # (its own answers are not sent back to it)
                )
                .order_by(literal_column("tool_calls.rowid").desc())
                .limit(advisor.STEPS_MOST)
            ).all()
        steps = [
            f"{name}({arguments}) -> {status}: {result or ''}"
            for name, arguments, status, result in reversed(calls)
        ]
        return asking, mode, steps

    async def _advice(
        self: "AgentRunner", ctx: Ctx, asking: Ctx, mode: str | None, sent: str
    ) -> str | None:
        """The advisor's one request, tool-less, in its time (a CLI's start counts in it): what it
        said, its thinking taken off - None where it did not answer in time or failed. On record
        as KOLONİ's own request either way; Stop goes on as Stop."""
        try:
            try:
                limit = advisor.API_SECONDS if mode is None else advisor.CLI_SECONDS
                async with asyncio.timeout(limit):
                    said, answer = await ask_once(
                        asking.model,
                        asking.model_name or "",
                        [
                            {"role": "system", "content": advisor.ADVICE},
                            {"role": "user", "content": sent},
                        ],
                    )
            except BaseException:
                self._own_request(ctx, asking, mode, None)  # sent, and not heard out
                raise
            self._own_request(ctx, asking, mode, answer)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("run %s: the advisor was not answered", ctx.run_id, exc_info=True)
            return None
        return _answer(said)

    # --- Task 10: note_decision --------------------------------------------------------------

    def _note_decision(self: "AgentRunner", ctx: Ctx, call_id: str, args: dict) -> str:
        """note_decision: a row of Decided for you (`app.decisions`) - who and when KOLONİ's, what
        and why the Orchestrator's words, masked, on one line, cut at LINE_MOST. It only adds:
        nothing here changes or deletes a row, and the row changes nothing by itself; its OK and
        Change are the user's, from the app's own page (`api.decisions`). At most NOTED_MOST a
        turn, counted on record (nothing awaited between the count and the row).
        shortcut: Ready for you reads the row when it reads its log again (its chips, a focus, the
        board's count every 5 s); send an event if a row is seen to come late."""
        what, why = args.get("what"), args.get("why")
        if not isinstance(what, str) or not what.strip():
            raise ToolError("missing required argument: what")
        if not isinstance(why, str) or not why.strip():
            raise ToolError("missing required argument: why")
        with self._factory() as session:
            count = session.scalar(
                select(func.count())
                .select_from(NotedDecision)
                .where(NotedDecision.run_id == ctx.run_id)
            )
            if (count or 0) >= NOTED_MOST:
                raise ToolError(NOTED_FULL)
            row = NotedDecision(
                run_id=ctx.run_id,
                agent_id=ctx.agent_id,
                tool_call_id=call_id,
                what=_line(what),
                why=_line(why),
            )
            session.add(row)
            session.commit()
            return NOTED.format(id=row.id, what=quoted(row.what))


def _line(text: str) -> str:
    """An agent's words as a noted decision keeps them: masked, on one line, cut."""
    shown = masking.masked(text)
    return shown if len(shown) <= LINE_MOST else shown[: LINE_MOST - 1] + "…"
