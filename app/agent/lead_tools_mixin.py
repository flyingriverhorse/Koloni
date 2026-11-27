"""The Orchestrator's own tools beside its agents' work: its plan shown to the user, the advisor,
its noted decisions, a pull request's feedback - `LeadToolsMixin` (0.1.11). Offered from
`AtWorkMixin._at_work_offered`, called through `AtWorkMixin._at_work_call`; what they keep of a
turn goes with it (`_lead_tools_forget`)."""

from typing import TYPE_CHECKING

from app import model_native
from app.agent.ctx import Ctx
from app.commands import OutputMask
from app.tools import ToolError
from app.tools_at_work import PLAN_SHOWN, UPDATE_PLAN_SCHEMA

if TYPE_CHECKING:
    from app.agent import AgentRunner


class LeadToolsMixin:
    def _lead_tools_init(self: "AgentRunner") -> None:
        """`_at_work_init`'s part for the Orchestrator's own tools."""
        # Task 5: the Orchestrator whose plan is shown, by its turn - its plan goes with the turn.
        self._planned: dict[str, Ctx] = {}

    def _lead_tools_forget(self: "AgentRunner", run_id: str) -> None:
        """`_shut_door`: the turn is over - what its Orchestrator's tools kept of it goes."""
        if (planned := self._planned.pop(run_id, None)) is not None:
            self._end_live(planned)

    def _lead_offered(self: "AgentRunner", ctx: Ctx, schemas: list[dict]) -> None:
        """`_at_work_offered`'s part: the tools of the Orchestrator at its own work that may open
        agents (spawn_agent is offered: not a plan turn, nor a comparison's side) - each where it
        is this one's. The same all through a turn: the tools are the prompt cache's first part."""
        if self._background_offered(ctx):  # (an API model's: a CLI's own plan is its own)
            schemas.append(UPDATE_PLAN_SCHEMA)

    async def _lead_tool(self: "AgentRunner", ctx: Ctx, call_id: str, name: str, args: dict) -> str:
        """`_at_work_call`'s part for the Orchestrator's own tools, held to where they are offered
        (a model may name one it was not given)."""
        if name == "update_plan":
            return self._update_plan(ctx, args)
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
