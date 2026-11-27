"""The Orchestrator's own tools beside its agents' work: its plan shown to the user, the advisor,
its noted decisions, a pull request's feedback - `LeadToolsMixin` (0.1.11). Offered from
`AtWorkMixin._at_work_offered`, called through `AtWorkMixin._at_work_call`; what they keep of a
turn goes with it (`_lead_tools_forget`)."""

import asyncio
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import func, literal_column, select

from app import advisor, git, injection, masking, model_native, pr_feedback, push_judge
from app.agent.cards import _answer
from app.agent.ctx import Ctx
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
    READ_PR_FEEDBACK_SCHEMA,
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
        # Task 11: whether gh is installed and the project's origin is on GitHub, by the turn.
        self._on_github: dict[str, bool] = {}

    def _lead_tools_forget(self: "AgentRunner", run_id: str) -> None:
        """`_shut_door`: the turn is over - what its Orchestrator's tools kept of it goes."""
        self._advised.pop(run_id, None)
        self._on_github.pop(run_id, None)
        if (planned := self._planned.pop(run_id, None)) is not None:
            self._end_live(planned)

    def _at_work_open(self: "AgentRunner", ctx: Ctx) -> bool:
        """Whether the tools beside the turn's agents are this agent's - offered
        (`_at_work_offered`) and taken (`_at_work_call`) alike: the Orchestrator at its own work
        whose tools let it open agents - not a sub-agent, an answer, a discussion, a plan turn
        (`PLAN_TOOLS`), a comparison's side (`NOT_IN_A_SIDE`) or a role with no spawn_agent.
        update_plan and read_pr_feedback hold to more where they are called, as they are offered."""
        return not (ctx.depth or ctx.answering or ctx.discussion) and "spawn_agent" in ctx.tools

    def _lead_offered(self: "AgentRunner", ctx: Ctx, schemas: list[dict]) -> None:
        """`_at_work_offered`'s part: the tools of the Orchestrator at its own work that may open
        agents (spawn_agent is offered: not a plan turn, nor a comparison's side) - each where it
        is this one's. The same all through a turn: the tools are the prompt cache's first part."""
        if self._background_offered(ctx):  # (an API model's: a CLI's own plan is its own)
            schemas.append(UPDATE_PLAN_SCHEMA)
        schemas.append(ASK_ADVISOR_SCHEMA)
        schemas.append(NOTE_DECISION_SCHEMA)
        if self._on_github.get(ctx.run_id):
            schemas.append(READ_PR_FEEDBACK_SCHEMA)

    async def _lead_tool(self: "AgentRunner", ctx: Ctx, call_id: str, name: str, args: dict) -> str:
        """`_at_work_call`'s part for the Orchestrator's own tools, held to where they are offered
        (a model may name one it was not given)."""
        if name == "update_plan":
            return self._update_plan(ctx, args)
        if name == "ask_advisor":
            return await self._ask_advisor(ctx, args)
        if name == "note_decision":
            return self._note_decision(ctx, call_id, args)
        if name == "read_pr_feedback":
            return await self._read_pr_feedback(ctx, call_id, args)
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
        # (each step on one line, masked, what nobody sees taken out: `masking.masked`)
        plan = model_native._plan(
            [
                {**one, "step": masking.masked(str(one.get("step") or ""))}
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

    # --- Task 11: the turn's git, and read_pr_feedback ------------------------------------

    async def _git_start(self: "AgentRunner", ctx: Ctx) -> None:
        """The project's git as the turn begins (slice 70): what a CLI of it is told, and
        what its end is compared with. Once a turn, by its Lead, before any agent of the turn
        works (`_attempt`: where Stop is taken) - never at an agent's steps. A folder with no
        `.git` is not looked at (no thread); one that is, in a thread: `git.where` keeps to its
        own time limit.
        shortcut: also a turn none of whose agents turns out to be a CLI or run a command;
        which will is not known yet as it begins.
        Task 11 (0.1.11, moved here from `LoopMixin` to make room there): and, where gh is
        installed, whether the project's origin is on GitHub - read_pr_feedback is offered by it,
        the same all through the turn (`_pr_offered`). At Full auto, what a push goes by as it
        begins ("push", `push_judge.at_start`): a push of the feature branch the judge decides
        is compared with it (`_push_takes`) - a turn begun at another level has none: a card."""
        if ctx.root is None or ctx.run_id in self._git_at:
            return
        self._git_at[ctx.run_id] = None  # (None: no git, or not read - nothing to compare)
        if os.path.lexists(Path(ctx.root) / ".git"):
            self._git_at[ctx.run_id] = await asyncio.to_thread(git.where, Path(ctx.root))
        if self._git_at[ctx.run_id] is not None and not ctx.depth:  # (Task 11, `_pr_offered`)
            self._on_github[ctx.run_id] = await asyncio.to_thread(_on_github, Path(ctx.root))
        if (seen := self._git_at[ctx.run_id]) is not None and self._full_auto(ctx):
            seen["push"] = await asyncio.to_thread(push_judge.at_start, Path(ctx.root))

    async def _read_pr_feedback(self: "AgentRunner", ctx: Ctx, call_id: str, args: dict) -> str:
        """read_pr_feedback: one pull request's reviews, comments, line comments and checks, read
        with the user's own gh off the event loop (`pr_feedback.read`) - data, masked, cut, framed.
        Only where it was offered (gh installed, origin on GitHub: `_git_start`); else, or where gh
        is not logged in or the pull request is another repository's, refused with why."""
        raw = args.get("pr")
        if not isinstance(raw, str | int) or isinstance(raw, bool) or not str(raw).strip():
            raise ToolError("missing required argument: pr")
        root = Path(ctx.root or ".")
        if not self._on_github.get(ctx.run_id):
            _repo, why = await asyncio.to_thread(git.pr_ready, root)
            raise ToolError(f"read_pr_feedback is not available: {why or git.NO_ANSWER}")
        try:
            text, said = await asyncio.to_thread(pr_feedback.read, root, str(raw))
        except git.Refused as refused:
            raise ToolError(str(refused)) from None
        # (anyone on the internet writes there: the user is warned, as of a page or an MCP tool)
        self._orders(ctx, "web", "a pull request's reviews and comments", said, call_id)
        return text

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
        mask = advisor.mask  # (`\\"` read as `"`: escaped JSON hid a secret's shape)
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
        # (each string of its arguments masked as it is: JSON hid a secret's shape - `masked_call`)
        steps = [
            f"{name}({advisor.masked_call(arguments)}) -> {status}: "
            + advisor.masked_call(result or "")
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


def _on_github(root: Path) -> bool:
    """Whether gh is installed and the project's origin is on github.com - read from its config,
    never from GitHub: read_pr_feedback asks gh whether it is logged in when it is called."""
    return git.gh() is not None and git.github_remote(root)


def _line(text: str) -> str:
    """An agent's words as a noted decision keeps them: masked, on one line, cut."""
    shown = masking.masked(text)
    return shown if len(shown) <= LINE_MOST else shown[: LINE_MOST - 1] + "…"
