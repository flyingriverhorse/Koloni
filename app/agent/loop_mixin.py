"""An agent's loop: opening an agent and its record, its attempts, the step loop for a model
asked step by step (`_loop`, `_steps`, `_model_step`) and for a CLI session (`_session_loop`),
its tool calls run together (`_run_tools`), and the project map and git at a turn's start -
`LoopMixin`.
"""

import asyncio
import base64
import contextlib
import json
import logging
import os
import re
import time
import uuid
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from sqlalchemy import func, or_, select

from app import (
    away,
    backlog,
    cli_surface,
    earlier,
    git,
    injection,
    knowledge,
    knows,
    project_map,
    raw,
    team_requests,
    web,
)
from app import memory as kept
from app.agent.cards import _at_a_step_limit, _goes_on, _in_its_chat, _role_asked
from app.agent.context_mixin import _koloni_compacts, _older
from app.agent.ctx import FLUSH_SECONDS, TERMINAL, Ctx, _Transcript, joined, sent_effort
from app.agent.summary import _size, compact_at
from app.agent.words import AGENT_TERMINAL, NATIVE_NEEDS_A_FOLDER
from app.db.models import (
    Agent,
    Conversation,
    FileChange,
    Message,
    Project,
    Provider,
    Question,
    Run,
    ToolCall,
    now,
)
from app.limits import classify
from app.model_client import (
    ModelClient,
    ModelInfo,
    ModelUnavailable,
    OwnStop,
    StepResult,
    ToolCallRequest,
    provider_call_id,
)
from app.model_session import CliSessionClient, SessionStop
from app.providers import mode_of
from app.roles import LEARN, LOOKUP, find_role, shown_name
from app.serialize import agent_out, message_out, run_out
from app.team import ClosedToAgents, quoted, tier_of
from app.tools import ToolError
from app.workspace import in_scratch

if TYPE_CHECKING:
    from app.agent import AgentRunner

log = logging.getLogger("app.agent")

# B-387 (live): Codex one step at a time (`talker`, `cli_surface.checked`) has its own tools off; a
# model that tries one anyway is refused with these words, and may end saying it could not read.
CODEX_OWN_TOOLS = "code-mode host is disabled"
CODEX_TOOLS_OFF = (
    'Codex\'s own tools are off here ("code-mode host is disabled"): do not try them. Use the '
    'tools listed under "tools" by writing a request for each into the "tool_calls" of your '
    "answer, as the rules at the top say - that works for every one of them. Go on with your "
    "task."
)
CODEX_TOOLS_FAILED = (
    "could not {work}: Codex kept trying its own tools, which are off when it runs one step at a "
    "time (in a discussion, or on a Codex version not measured with KOLONİ)."
)
# shortcut: 3 from three measured gpt-6-luna steps (6 Nov 2026: one in three tried its own tool
# first); raise it if live runs show longer streaks.
CODEX_TRIES = 3

# K-oda-takim: what the agent `discuss` was refused to is told once that one may join.
# shortcut: a CLI Lead hears it on its next run, after the report, not at once; send it by
# `steer` if that is seen to matter.
DISCUSS_NOW = "{name} is {state} now: discuss can take it in, if you still need it"

# The most of one answer kept to be sent back as it came (`_kept_blocks`), in characters.
MAX_BLOCKS = 200_000

# How an OpenAI-compatible server refuses a request too large for its window: llama-server
# ("the request exceeds the available context size"), OpenAI and vLLM ("maximum context
# length", "context_length_exceeded").
OVERFLOW = re.compile(
    # (The last as Anthropic's API says it: "prompt is too long: N tokens > M maximum".)
    # shortcut: its wording as remembered, not confirmed in its docs nor a live refusal; check.
    # shortcut: none for Qwen / DashScope, whose wording is neither confirmed in its docs nor
    # seen: its refusal is not taken as one for size (nothing is summarised for a second try).
    # shortcut: no other CLI's own wording is measured (Claude Code, Codex, agy; as a
    # session, natively or step by step): one that passes its service's words on is read, any
    # other refusal for size is not. Add each CLI's line once a live refusal is seen.
    r"exceeds the available context size|maximum context length|context_length_exceeded"
    r"|prompt is too long"
    # GitHub Copilot CLI's, read in its package's own code on 14 Nov 2026 with no model called
    # (`@github/copilot-win32-x64/app.js`, dated July): its `session.error` of errorType
    # "context_limit" ("The context window is full and the request cannot be processed. ...";
    # the type itself said after its words: `model_session.copilot_error`), its provider's
    # words, which its own code matches ("prompt token count of N exceeds the limit of M",
    # code `model_max_prompt_tokens_exceeded`), and a first input too large ("Initial inputs
    # exceed the model token limit of N tokens").
    # shortcut: the `copilot.exe` that runs (5 Nov) is compressed and could not be read, and no
    # live refusal was seen: these are the July bundle's. Check them at a live refusal.
    r"|\(context_limit\)|context window is full|model_max_prompt_tokens_exceeded"
    r"|prompt token count of \d+ exceeds the limit|inputs exceed the model token limit"
    # Seen live, the one refusal measured (14 Nov 2026: Copilot CLI 1.0.107 as a session,
    # gpt-6-luna on GitHub's default context tier, Windows; a 2.3 M-character message):
    # "Execution failed: Request exceeds the model's prompt budget after reserving output
    # (591842 tokens; limit 272000). Reduce context or compact before continuing." - its
    # `session.error`, classed "other" on its agent by its words (`limits.classify`), with no
    # class of its own on the failure (`CliSessionClient`: `result_is_its_error`).
    r"|exceeds the model's prompt budget",
    re.IGNORECASE,
)


def refused_for_size(exc: ModelUnavailable) -> bool:
    """Whether a failure is a refusal for its size (`OVERFLOW`) - read only in words that are
    the provider's or the CLI's own: never where the failure has a class of its own (a limit,
    no credit), nor where all that says why is the text of a CLI's `result`, which can be the
    model's words (`model_cli.RESULT_TEXT`: Claude Code's `is_error` result) - a
    page it read could have it say them, and have its history summarised and its turn run twice.
    shortcut: so no refusal of Claude Code's own is read at all - no recorded stream
    in tests/ has such a result, nor a field on it that says it is the CLI's own; read that
    field (a subtype, the assistant event's `error`) once a live refusal shows one."""
    return exc.failure is None and bool(OVERFLOW.search(str(exc)))


ROLE_WINDOW_LARGER = (
    " (the context window set in its role may be larger than the model's: set it smaller "
    "on the Agents page, or empty it to use the one found)"
)
# After a lead's turn that was refused for its size (`AgentRunner._lead_after`), where it
# could not be started again by itself (`_loop_again`).
SUMMARISED_FOR_NEXT = (
    " KOLONİ is summarising its earlier work: send your message again to go on from the summary."
)
# KOLONİ's line in the chat where it was (`_loop_again`), and what its failure says where it
# was refused for its size again after that.
STARTED_AGAIN = "Its context was full: its earlier work was summarised and the turn started again."
FULL_AGAIN = (
    " Its context filled again after KOLONİ summarised its earlier work and started the turn again."
)
FULL_AGAIN_DO = " Use Compact now or set a smaller context window on its role."
# Refused for its size with nothing a summary could stand for (the live refusal: a message of
# the user's larger than its model takes) - no number of the CLI's is read into a claim: its
# own line, before this, has them.
NOTHING_LEFT = (
    " Nothing of its earlier work is left to summarise: what it was sent - your messages and "
    "its last answer - is more than its model takes, as its own line above says. Send a "
    "shorter message, or use a model with a larger context window."
)

# A side of a comparison (slice 54) works only in a copy of its own.
NO_COPY_FOR_A_SIDE = (
    "the project could not be copied (too big, or a file of it could not be read): a side "
    "of a comparison works only in a copy of its own, and changed nothing"
)
# A job of a night's run while the user is away (slice 106, `app.away`): its one copy.
NO_COPY_FOR_A_JOB = (
    "the project could not be copied (too big, or a file of it could not be read): a job "
    "while you're away works only in a copy of its own, and changed nothing"
)

# Said on an agent's record where its service refused the level it was sent (a 400 naming
# `reasoning_effort`): the step was asked again without it, and none goes from then on.
EFFORT_REFUSED = (
    "{provider} refused reasoning level {asked}: this step was asked again without one, and "
    "none is sent to it until the provider is changed."
)
# Its model said which levels it takes instead (`StepResult.effort_instead`).
EFFORT_INSTEAD = "{model} does not take {asked}; sent {sent}"
# Its level where its model does not take it (`sent_effort`): the nearest lower one it does.
EFFORT_STEPPED = "{asked} → {sent}: the nearest lower level {model} takes."
EFFORT_NONE_BELOW = "{asked} → none: {model} takes no level at or below it."
# B-404: a model whose name fixes its level (`model_cli.level_in_name`) is sent none.
EFFORT_IN_NAME = "{asked} → none: {model} has its level in its name, and takes no other."
# Copilot's auto, which takes none either (`level_in_name`): Copilot picks its model and level.
EFFORT_COPILOT_AUTO = "{asked} → none: Copilot's auto picks the model and its level; none is sent."
# B-402: KOLONİ's own level for a sub-agent of an Auto role whose opener gave none
# (`spawn_mixin.AUTO_START`, under the role's most), said at its first step.
EFFORT_AUTO = "Thinking {level}, KOLONİ's default for Auto (the opener gave no level)."
EFFORT_AUTO_OFF = "Thinking Off (the role's most)."
EFFORT_AUTO_UNSENT = "KOLONİ's default for Auto, {level}: its model takes no levels: none is sent."
# Said on its record where a step was asked once more, with the same model, after a short
# failure of its provider (`model_client.brief`, 93-B3); the last such step.
RETRIED = "A step was asked again once, after a short failure of its provider: {why}"

# How much of each thing said in the turn the summariser is given (`_turn_in_words`), and of
# how many reports and files.
SAID_TO_SUMMARISER = 4000
LISTED_TO_SUMMARISER = 20


def _kept_blocks(result: StepResult) -> dict | None:
    """What of an answer is kept to be sent back as it came (`StepResult.blocks`): nothing
    where a call's arguments are kept masked (`_record_calls`: the secret would be kept here
    as it came), nor over MAX_BLOCKS.
    shortcut: an answer larger than that goes back rebuilt, without its thinking; keep such
    answers elsewhere if they are seen."""
    blocks = result.blocks
    if not blocks or any(call.name == "http_request" for call in result.tool_calls):
        return None
    return blocks if len(json.dumps(blocks)) <= MAX_BLOCKS else None


class LoopMixin:
    def _open_agent(
        self: "AgentRunner",
        run_id: str,
        cid: str,
        root: str | None,
        parent_id: str | None,
        role: str,
        tools: list[str],
        task: str | None,
        depth: int,
        status: str = "running",
        instructions: str = "",
        parent_role: str | None = None,
        call_id: str | None = None,
        provider_name: str | None = None,
        model: ModelClient | None = None,
        model_name: str | None = None,
        chosen: bool = False,
        provider_id: str | None = None,
        continues: tuple[str, str] | None = None,
        chosen_why: str | None = None,
        effort: str | None = None,
    ) -> Ctx:
        """Record a new agent and return the context its work is done in. `model_name`
        is the model it is to run on, where that is known before it has run. `continues`:
        the agent of an earlier turn it goes on from, as (id, name) - it has that name,
        which no agent of this turn may have already (ToolError). `effort`: its reasoning
        level, where not its role's (the conversation's for a lead, the one asked for a
        task)."""
        continues_id = continues[0] if continues else None
        with self._factory() as session:
            # How far its role lets one agent go, as the role stands now.
            limits = find_role(session, role)
            above = self._ctxs.get(parent_id or "")
            project_id = session.get_one(Conversation, cid).project_id
            known = knows.known_here(session, limits, project_id)
            # K-bilgi part 3: whoever uses a knowledge here asks it, never searches it itself.
            if root is not None and knows.used_here(session, limits, project_id):
                tools = [*tools, LOOKUP]
            # K-uzman: an expert's own - reading an address (researching a topic) only where
            # its opener's helpers may make web requests (and search): `_caps`, the
            # Orchestrator's tools since B-333, as for any tool a helper holds.
            # (slice 61: not with a web tool switched off on the Tools page) The code's is
            # scanned on the Knowledge page, with no model (K-bilgi 8); the Project notes are
            # written from the user's ticks (K-bilgi 6).
            if (
                known is not None
                and root is not None
                and knowledge.learns_itself(known)
                and (
                    not (needs := knowledge.web_tools(known))
                    or above is not None
                    and needs <= set(self._caps(above)) - self._off()
                )
            ):
                tools = [*tools, LEARN]
            # Its web search while answering, where the user switched it on - and its opener
            # searches too: through `_web`, asked as any search is.
            if (
                known is not None
                and known.get("search_answering")
                and above is not None
                and ("web_search" in self._caps(above))
            ):
                tools = [*tools, "web_search"]
            # R161 (live): with none, its "Not in my documents - allow a web search?"
            # (`knowledge.brief`) is asked with ask_user, which an expert made on the Agents page
            # was not given: it said "not in its sources" and asked nothing. Under an opener that
            # may ask, as any agent's question.
            if (
                known is not None
                and not {"web_search", "ask_user"} & set(tools)
                and (above is not None and "ask_user" in self._caps(above))
            ):
                tools = [*tools, "ask_user"]
            role_steps, role_tokens = (
                (limits.max_steps, limits.max_tokens) if limits else (None, None)
            )
            window = limits.context_window if limits else None
            effort = effort or (limits.effort if limits else None)
            # The MCP servers it may use: its role's, and like its tools never one the
            # agent that opens it has not (the lead, which nobody opens, has its role's).
            # (None at all for S3's Reviewer: an MCP server's tools may change things.)
            mcp = (
                [
                    name
                    for name in (limits.mcp if limits else [])
                    if parent_id is None or (above is not None and name in above.mcp)
                ]
                if call_id not in self._read_only_calls
                else []
            )
            # A role from before names were checked: its agents are named, and told what
            # they are, without what does not print.
            role = shown_name(role)
            taken = {
                name.casefold()
                for name in session.scalars(select(Agent.name).where(Agent.run_id == run_id))
            }
            name, count = role, 1
            while name.casefold() in taken:
                count += 1
                name = f"{role} {count}"
            if continues is not None and depth > 0:
                name = continues[1]
                if name.casefold() in taken:
                    raise ToolError(
                        f"an agent named {name} is in this turn already: message that one"
                    )
            provider = session.get(Provider, provider_id) if provider_id else None
            # K-skill-uyum: what of its role's skills it starts with, and why not the others -
            # on its record for its spawn card and the skills' track record (K-skill-puan).
            given, left_out = self._skill_split(session, role, tools, mcp, provider_id, model_name)
            agent = Agent(
                skills={"given": [skill.name for skill in given], "left_out": left_out}
                if given or left_out
                else None,
                run_id=run_id,
                parent_agent_id=parent_id,
                tool_call_id=call_id,
                provider_name=provider_name,
                provider_mode=mode_of(provider) if provider else None,
                model_id=model_name,
                chosen=chosen,
                chosen_why=chosen_why,
                tier=tier_of(provider, model_name) if provider else None,
                role_name=role,
                name=name,
                tools=tools,
                mcp=mcp,
                task=task,
                depth=depth,
                status=status,
                started_at=now() if status == "running" else None,
                continues_id=continues_id,
            )
            session.add(agent)
            session.commit()
            agent_id, payload = agent.id, agent_out(agent)
        self.bus.emit(cid, run_id, "agent.created", payload)
        ctx = Ctx(
            run_id,
            cid,
            root,
            agent_id,
            role,
            tuple(tools),
            depth,
            instructions,
            task,
            parent_role,
            model,
            provider_name,
            name,
            parent_id,
            provider_id=provider_id,
            model_name=model_name,
            continues_id=continues_id,
            role_steps=role_steps,
            role_tokens=role_tokens,
            mcp=tuple(mcp),
            effort=effort,
            context_window=window,
            # Its opener's part, unless spawn_agent gives it one (`_spawn_one`).
            # shortcut: one gone on with in a later turn is in its opener's part, not the one
            # it had (that is in memory only); keep it on its record if that misleads.
            part=above.part if above else None,
        )
        self._ctxs[agent_id] = ctx
        return ctx

    def _set_agent(self: "AgentRunner", cid: str, agent_id: str, **fields) -> None:
        if fields.get("status") in AGENT_TERMINAL:
            # Its work is over, however it ended: the files it held are let go first -
            # or, changed in a working copy, held on until that is taken in.
            self._work_over(agent_id)
        if "error" in fields:
            # Why its model failed goes on record with the error, and goes with it.
            fields["failure"], fields["failure_resets_at"] = self._why_failed(
                agent_id, fields["error"]
            )
        with self._factory() as session:
            agent = session.get_one(Agent, agent_id)
            if "copy" in fields:
                # K-buyuk-proje: the part of each copy it had, by tree, outlives a later copy's
                # record: a kept one is compared by its own (`_kept_as`). A copy made at a tree
                # says its own (None: whole) - one of before at that place is gone.
                parts = {
                    tree: part
                    for tree, part in {
                        **((agent.copy or {}).get("parts") or {}),
                        **fields["copy"].get("parts", {}),
                    }.items()
                    if part
                }
                fields["copy"] = {
                    **{k: v for k, v in fields["copy"].items() if k != "parts"},
                    **({"parts": parts} if parts else {}),
                }
            for key, value in fields.items():
                setattr(agent, key, value)
            session.commit()
            run_id, payload = agent.run_id, agent_out(agent)
        self.bus.emit(cid, run_id, "agent.updated", payload)
        # (K-yavas: a step or a call of it began, or a call ended - its own, not one of its answer
        # to a message or its speech beside its work, whose ctx `_ctxs` does not hold)
        if (
            "last_event_at" in fields
            and agent_id not in self._answering
            and (known := self._ctxs.get(agent_id)) is not None
        ):
            self._slow(known)
        status = fields.get("status")
        if status in ("waiting", "completed", "failed"):
            # K-oda-takim: an agent `discuss` was refused (at work) may join now: its asker is told.
            for asker in self._discuss_later.pop(agent_id, ()):
                if (told := self._ctxs.get(asker)) is not None:
                    self._nudge(
                        told,
                        DISCUSS_NOW.format(
                            name=payload["name"], state="waiting" if status == "waiting" else "done"
                        ),
                    )

    def _close_agents(
        self: "AgentRunner", run_id: str, cid: str, status: str, error: str | None
    ) -> None:
        """End every agent of a run that is still open, the way the run itself ended."""
        with self._factory() as session:
            still_open = session.scalars(
                select(Agent).where(Agent.run_id == run_id, Agent.status.not_in(AGENT_TERMINAL))
            ).all()
            for agent in still_open:
                waiting_to_start = agent.status == "proposed"
                agent.status = "rejected" if waiting_to_start else status
                agent.error = None if waiting_to_start else error
                # (The lead's: only an agent's own model's failure is ever kept for it.)
                agent.failure, agent.failure_resets_at = self._why_failed(agent.id, agent.error)
                agent.ended_at = now()
                agent.waiting_for = None
                # A turn stopped for its budget (`_over_budget`).
                if agent.status == "failed" and run_id in self._over:
                    agent.stopped_by_koloni = True
            session.commit()
            payloads = [agent_out(agent) for agent in still_open]
        for payload in payloads:
            self.bus.emit(cid, run_id, "agent.updated", payload)

    async def _loop_again(
        self: "AgentRunner", ctx: Ctx, info: ModelInfo, again: bool
    ) -> tuple[str, str | None]:
        """`_attempt`'s loop. `again` (the user's, 14 Nov 2026): refused for its size, a lead
        working alone has its older part summarised and is started again from the summary, in
        the same turn - once: refused so again, it fails, saying what to do.
        shortcut: a CLI's run is started anew, sent its history again (as its tests at Stop
        send a session back: `_session_loop`), not gone on with inside its own session; and
        what a CLI read by itself in the turn is in the summary only as KOLONİ recorded it.
        shortcut: a CLI's run that failed reported no tokens, so the turn's token limit does
        not see the first start; count it once a CLI says what a failed run spent."""
        try:
            return await self._loop(ctx, info)
        except ModelUnavailable as exc:
            refused = refused_for_size(exc)
            # (The lead as it runs now: its model may have changed since - `_steps_keep_model`.)
            if not (
                again
                and refused
                and await self._summarised_again(self._ctxs.get(ctx.agent_id, ctx), info)
            ):
                if refused:  # (what the summary after its turn goes by: `_summary_after`)
                    self._refused_size.add(ctx.agent_id)
                    self._refusal_says(ctx, exc, "" if again else None)
                raise
        await asyncio.sleep(0)  # (a Stop asked for meanwhile lands here: before the line is said)
        self._koloni_line(ctx.cid, ctx.run_id, STARTED_AGAIN)
        try:
            return await self._loop(ctx, info)
        except ModelUnavailable as exc:
            if refused_for_size(exc):
                self._refusal_says(ctx, exc, FULL_AGAIN)
            raise

    def _refusal_says(
        self: "AgentRunner", ctx: Ctx, exc: ModelUnavailable, before: str | None
    ) -> None:
        """`_loop_again`: what a refusal for its size says to the user besides the CLI's own
        line, after `before` (None: nothing - a turn not started again). Where nothing is left
        that a summary could stand for, that what it is sent is itself too large; else, after
        it was started again, what to do. Never for a model KOLONİ does not compact."""
        now = self._ctxs.get(ctx.agent_id, ctx)
        if before is None or not _koloni_compacts(now.model):
            return
        try:
            bare = not _older(self._history(now, None, quiet=True))
        except Exception:  # (what it says more never fails the turn)
            bare = False
        more = NOTHING_LEFT if bare else FULL_AGAIN_DO if before else ""
        if more:
            exc.args = (f"{exc}{before}{more}",)

    async def _attempt(
        self: "AgentRunner", ctx: Ctx, again: bool = False
    ) -> tuple[str, str | None]:
        run_id, cid = ctx.run_id, ctx.cid
        try:
            # Before it takes any place: the summary it waits for may need the last one.
            await self._after_idle(ctx)
            if ctx.root is not None:
                async with self.switching(ctx.root):
                    pass  # (K-dallar: not while the git map switches the project's branch)
            self._map_start(ctx)  # (not waited for: made while git is looked at, and after)
            await self._git_start(ctx)  # (the Lead's, once: before any agent of the turn works)
            # Before its first place: the question holds one of its own, where it goes.
            ctx = await self._by_how_hard(ctx)
            # In here: the lead may wait for room in its project, and Stop ends that too.
            # (`_take`, not `_settle`: its first place, not one given up for a wait.)
            await self._take(ctx)
            self._still_allowed(ctx)
            if (
                self._sides.get(run_id) == ctx.agent_id
                and await self._working_copy(ctx, ctx.agent_id) is None
            ):
                # Made before its first step: a side that cannot be copied changes nothing.
                return "failed", NO_COPY_FOR_A_SIDE
            if (
                self._away_jobs.get(run_id) == ctx.agent_id
                and await self._working_copy(ctx, ctx.agent_id) is None
            ):
                return "failed", NO_COPY_FOR_A_JOB  # (nor a job while the user is away)
            info = await self._model_of(ctx).info()
            self._update_run(run_id, cid, model_id=info.model_id)
            self._set_agent(cid, ctx.agent_id, model_id=info.model_id, model_from=info.model_from)
            self._native_no_recipe(ctx)
            return await self._loop_again(ctx, info, again)
        except asyncio.CancelledError:
            # Stop reaches the lead from wherever in the tree the work was.
            self._interrupt_open_calls(run_id, cid)
            if run_id in self._over and not self._closing:
                return "failed", self._why_over(run_id)  # stopped for going over its budget
            # The user pressed Stop, or the server is going down under the run - or its night
            # stopped (`cut`), with why.
            return ("interrupted" if self._closing else "cancelled"), self._away_cut.get(run_id)
        except ModelUnavailable as exc:
            why = self._why(ctx, exc)
            if isinstance(exc, ClosedToAgents):  # (R186: switched off - said in the chat too)
                self._koloni_line(cid, run_id, why)
            return "failed", why
        except Exception as exc:  # a bug in the loop must not leave the run hanging
            self._interrupt_open_calls(run_id, cid)
            return "failed", f"internal error: {exc!r}"

    @staticmethod
    def _turn_in_words(session, ctx: Ctx) -> str:
        """A turn as the summariser is given it: what was said in it - the message that
        started it, the lead's answer, its agents' reports (`earlier.said_in`) - each in
        quotes and cut to a size, and the names of the files that changed. Nothing a
        tool returned."""

        def quote(said: str) -> str:
            return quoted(
                said
                if len(said) <= SAID_TO_SUMMARISER
                else said[:SAID_TO_SUMMARISER] + " " + kept.CUT
            )

        lines = [
            f"The message of the trigger that started it: {quote(said)}"
            for said in session.scalars(
                select(Message.content).where(
                    Message.run_id == ctx.run_id, Message.role == "trigger"
                )
            )
        ]
        said = earlier.said_in(session, ctx.run_id)
        for agent, _at, words in said[:LISTED_TO_SUMMARISER]:
            who = (
                "The user's message"
                if agent is None
                else (
                    "The Orchestrator's answer"
                    if agent == ctx.name
                    else f"The report of the agent {quoted(shown_name(agent))}"
                )
            )
            lines.append(f"{who}: {quote(words)}")
        files = sorted(
            {
                path
                for path in session.scalars(
                    select(FileChange.path).where(
                        FileChange.run_id == ctx.run_id, FileChange.status == "applied"
                    )
                )
                if not in_scratch(path)
            }
        )
        if files:
            lines.append(
                "Files changed in the turn: "
                + ", ".join(quoted(path) for path in files[:LISTED_TO_SUMMARISER])
            )
        return "\n".join(lines)

    def _force_fail(self: "AgentRunner", run_id: str, error: str) -> str | None:
        """Last resort: mark the run failed without relying on anything else working."""
        try:
            with self._factory() as session:
                run = session.get(Run, run_id)
                if run is None:
                    return None
                if run.status not in TERMINAL:
                    run.status, run.error, run.ended_at = "failed", error, now()
                    backlog.turn_ended(session, run, "failed")
                    away.turn_ended(session, run, "failed")
                    session.commit()
                cid, payload = run.conversation_id, run_out(run)
            self.bus.emit(cid, run_id, "run.finished", payload)
            self._close_agents(run_id, cid, "failed", error)
            return cid
        except Exception:
            return None

    async def _git_start(self: "AgentRunner", ctx: Ctx) -> None:
        """The project's git as the turn begins (slice 70): what a CLI of it is told, and
        what its end is compared with. Once a turn, by its Lead, before any agent of the turn
        works (`_attempt`: where Stop is taken) - never at an agent's steps. A folder with no
        `.git` is not looked at (no thread); one that is, in a thread: `git.where` keeps to its
        own time limit.
        shortcut: also a turn none of whose agents turns out to be a CLI or run a command;
        which will is not known yet as it begins."""
        if ctx.root is None or ctx.run_id in self._git_at:
            return
        self._git_at[ctx.run_id] = None  # (None: no git, or not read - nothing to compare)
        if os.path.lexists(Path(ctx.root) / ".git"):
            self._git_at[ctx.run_id] = await asyncio.to_thread(git.where, Path(ctx.root))

    def _map_start(self: "AgentRunner", ctx: Ctx) -> None:
        """The project's map as the turn begins (K-buyuk-proje), for its Lead's brief: once a
        turn, made beside the turn - a scan may take its seconds (`project_map.scan`), and the
        turn never waits for it (`_map_told`)."""
        if ctx.root is not None and ctx.run_id not in self._map_tasks:
            self._map_tasks[ctx.run_id] = asyncio.create_task(self._map_made(ctx, ctx.root))

    async def _map_made(self: "AgentRunner", ctx: Ctx, root: str) -> dict | None:
        """The map with the user's test commands (`project_map.edited`); None for none."""
        try:
            with self._factory() as session:
                tests = (
                    session.scalar(
                        select(Project.test_commands)
                        .join(Conversation, Conversation.project_id == Project.id)
                        .where(Conversation.id == ctx.cid)
                    )
                    or {}
                )
            found = await asyncio.to_thread(project_map.scan, root)
            return project_map.edited(found, tests)
        except Exception as exc:  # (the map only helps: no turn fails for it)
            log.warning("run %s: no project map: %r", ctx.run_id, exc)
            return None

    def _map_now(self: "AgentRunner", ctx: Ctx) -> dict | None:
        """The turn's map if it is made by now; None: not (yet)."""
        task = self._map_tasks.get(ctx.run_id)
        return task.result() if task is not None and task.done() and not task.cancelled() else None

    def _map_told(self: "AgentRunner", ctx: Ctx) -> str | None:
        """The map's brief as the Lead's first step found it - ready then, or not said this
        turn - and the same at every later step, so the prompt's prefix holds."""
        if ctx.run_id not in self._maps:
            found = self._map_now(ctx)
            self._maps[ctx.run_id] = project_map.brief(found) if found else None
        return self._maps[ctx.run_id]

    async def _loop(self: "AgentRunner", ctx: Ctx, info: ModelInfo) -> tuple[str, str | None]:
        # (Not an answer's or a discussion's loop, which may run beside its own work's.)
        counts = _goes_on(ctx)
        if counts:
            self._steps_used[ctx.agent_id] = 0
            self._codex_tries.pop(ctx.agent_id, None)  # (B-387: each job its own tries)
        stopped = False  # (a Stop: `CancelledError` - not a failure, which `woken` sees)
        try:
            with raw.of(ctx.agent_id):  # what its CLI writes meanwhile is its raw stream
                return await self._loop_steps(ctx, info)
        except asyncio.CancelledError:
            stopped = True
            raise
        except Exception:
            if not (ctx.answering or ctx.discussion):  # (G2.5: an answer it asked for, the Lead's)
                await team_requests.woken(self, ctx, "failed")
            raise
        finally:
            await self._loop_end(ctx, counts, stopped)

    async def _loop_steps(self: "AgentRunner", ctx: Ctx, info: ModelInfo) -> tuple[str, str | None]:
        """`_loop`: its steps until the turn may end - not while an answer it did not wait for
        comes, its teams work, or a step is left to do."""
        calls = None
        while True:
            status, error = await self._steps_held(ctx, info)
            # B-413: its loop guard ended it - the turn's end: no team, answer or step
            # left is waited for or told.
            if ctx.agent_id in self._guard_ended:
                self._guard_ended.discard(ctx.agent_id)
                return status, error
            # B-397: at the app's step limit a sub-agent asks the user whether to go on, once
            # (`_more_steps`) - not at its role's, the user's own rule, nor at the end of the steps
            # given on top.
            if status != "completed" and error == "step_limit" and await self._more_steps(ctx):
                continue
            # K-takimlar-arasi: an answer it did not wait for comes now, and is read.
            if (
                not (ctx.answering or ctx.discussion)
                and await team_requests.woken(self, ctx, status)
                and status == "completed"
            ):
                self._answer_again.add(ctx.agent_id)  # (B-381)
                continue
            # B-376: nor is the Lead's answer the turn's end while any agent of it is
            # at work - whatever opened it, and whether anyone waits for it. (`calls` is
            # left as it was: its answer after the hold is still held to B-83's check.)
            if (
                status == "completed"
                and not ctx.depth
                and not (ctx.answering or ctx.discussion)
                and (held := await self._held_for_work(ctx))
            ):
                self._nudge(ctx, held)
                continue
            if (
                status == "completed"
                and not ctx.depth
                and not (ctx.answering or ctx.discussion)
                and (ready := await self._ready_at_end(ctx))
            ):
                self._nudge(ctx, ready.strip())
                continue
            # B-382 (live): nor is its stop at its step limit, which it had spent waiting
            # for its teams: they are waited for too, and the turn ends at that limit as
            # it was to - no step more of the Lead's.
            # shortcut: no closing summary after them (it would be a step past its limit);
            # the agent box says why it stopped. Give it one step more if that is missed.
            if (
                status != "completed"
                and not ctx.depth
                and not (ctx.answering or ctx.discussion)
                and _at_a_step_limit(error)
            ):
                await self._held_for_work(ctx)
            # B-83, B-90: its answer is no end while a recipe's step or a picked
            # team is left: it is told which, and goes on (a CLI's session anew),
            # within the steps it had. Told, an answer with no call is its why: it stands -
            # but where it was told before KOLONİ's end check ran (B-90's why no team: tarif
            # maliyeti T2, a small change made with no team), the check runs all the same, once.
            # Not on a recipe still at work (review of T2): its own end checks its work - a fix
            # round on half of it would go to an Orchestrator its step keeps from fixing it.
            answered = calls == self._calls_of(ctx)
            if status != "completed" or (
                answered and (self._gate_ran(ctx.run_id) or self._recipe_at_work(ctx))
            ):
                await self._stronger_at_end(ctx, status)  # (S11: as at the gate's end)
                return status, error
            # (and KOLONİ's end check, `_proof_left`)
            left = await (self._proof_left(ctx) if answered else self._end_left(ctx))
            if left is None:
                return status, error
            self._nudge(ctx, left)
            calls = self._calls_of(ctx)

    async def _ready_at_end(self: "AgentRunner", ctx: Ctx) -> str:
        """B-415 (live): Ready for you is asked as the Lead hears back from an agent - with
        another still in the copy then (a lead's agent outliving it, one answering a message)
        it was asked never: it is, before the Lead's answer ends the turn. In the call of the
        last lead it opened, else of the last agent it opened - a card is always in a call;
        with none, no recipe ran."""
        mine = [one for one in self._ctxs.values() if one.run_id == ctx.run_id and one.depth == 1]
        with self._factory() as session:
            called = set(
                session.scalars(
                    select(Agent.id).where(
                        Agent.id.in_([one.agent_id for one in mine]),
                        Agent.tool_call_id.is_not(None),
                    )
                )
            )
        opened = [one for one in reversed(mine) if one.agent_id in called]
        under = next(
            (one for one in opened if one.agent_id in self._leads), opened[0] if opened else None
        )
        return "" if under is None else await self._ready_for_you(ctx, under)

    async def _loop_end(self: "AgentRunner", ctx: Ctx, counts, stopped: bool) -> None:
        """`_loop`, however it ended: its counts kept, its MCP servers and the sub-agents it
        did not wait for ended."""
        if counts:
            used = self._steps_used.pop(ctx.agent_id, 0)
            if self._role_counts(ctx):
                self._role_taken[ctx.agent_id] = self._role_before(ctx) + used
            self._given_steps.pop(ctx.agent_id, None)  # (a budget is one job's)
        later = []
        if not (ctx.answering or ctx.discussion):
            team_requests.drop(self, ctx)
            # Stopped, the sub-agents it did not wait for stop with it - and the Lead's
            # however it ended: the turn's end comes next (its copies, its record), and
            # nobody above is left to read them. (A sub-opener that failed leaves them at
            # work: what they report goes to the Lead, G2.5 - `team_requests.woken`.)
            later = (
                self._cancel_later(ctx.run_id, ctx.agent_id) if (stopped or ctx.depth == 0) else []
            )
        try:
            # Its work is over, however it ended - Stop, and KOLONİ going down, too: the
            # MCP servers started for it end with it. (Not a turn in which it only
            # answered: it starts none there, and its own work may still be going on.)
            mine = [] if ctx.answering else [key for key in self._servers if key[0] == ctx.agent_id]
            if mine:
                # (Shielded: a second Stop does not leave one of them running.)
                await asyncio.shield(
                    asyncio.gather(
                        *(self._servers.pop(key).end() for key in mine), return_exceptions=True
                    )
                )
            await self._slow_ended(ctx)  # (K-yavas: before the turn's end is on record)
            if later:  # (last: a second Stop leaves nothing above undone)
                await self._stopped_later(later)
                later = []
        except asyncio.CancelledError:
            # A second Stop: the turn's end waits for them, and says how they ended.
            self._later_work.setdefault(ctx.run_id, []).extend(later)
            raise

    async def _steps_held(self: "AgentRunner", ctx: Ctx, info: ModelInfo) -> tuple[str, str | None]:
        """`_steps`; B-413: the Orchestrator's only step limit is its role's (OwnStop) - at it,
        it waits for its teams as it did at the app's (B-382, `_loop_steps`), as a session's
        stop (a SessionStop) always did. Any other OwnStop (a model the provider refused, say)
        goes on up, to what handles it."""
        try:
            return await self._steps(ctx, info)
        except OwnStop as stop:
            if ctx.depth or not _at_a_step_limit(str(stop)):
                raise
            return "failed", str(stop)

    async def _steps(self: "AgentRunner", ctx: Ctx, info: ModelInfo) -> tuple[str, str | None]:
        await self._steps_first(ctx)
        if ctx.root is None and getattr(ctx.model, "native", False):
            # (A sub-agent's client is its talker from its opening on: `_spawn`.)
            model = _in_its_chat(ctx, ctx.model)
            if getattr(model, "native", False):  # (agy reads where it likes: not run)
                return "failed", NATIVE_NEEDS_A_FOLDER.format(provider=ctx.provider or "this CLI")
            ctx = replace(ctx, model=model)
            self._steps_keep_model(ctx, model)
            info = await self._model_of(ctx).info()
        ctx, info = await self._steps_surface(ctx, info)
        # (A CLI's too: one that starts anew is sent the history KOLONİ compacted.)
        self._goes_on_from_summary(ctx, ctx.context_window or info.context_window)
        if getattr(ctx.model, "native", False):
            self._hold_to_role(ctx, None)
            return await self._native_loop(ctx, info)
        if getattr(ctx.model, "session", False):
            self._hold_to_limit(ctx)  # before it starts: its messages are held one by one
            self._hold_to_role(ctx, None)
            return await self._session_loop(ctx, info)
        # What the step before reported it sent: how full its context is. Before its
        # first step, what was last measured of it or of the agent it goes on from. (Where
        # that was summarised after its turn, nothing older than its last answer is left
        # to summarise: `_compact` asks nothing.)
        sent = self._sent_before(ctx)
        # The nearer of the app's and the role's step limits (one set for this job - a
        # speech - is its own, and says so itself; a budget given on
        # top, K-devam-butce, is the whole of it: `_step_limit`).
        role = (
            None
            if ctx.agent_id in self._given_steps
            else (ctx.role_steps and ctx.role_steps - self._role_before(ctx))
        )
        # (Told to go on, B-83: from the steps it took before - `_loop`.)
        taken = self._steps_used.get(ctx.agent_id, 0) if _goes_on(ctx) else 0
        # (The limit read at each step: a recipe's runner's grows as it starts its recipe and
        # as the user sends it back - R147, `_recipe_steps`.)
        # (B-413: none for the Orchestrator - its loop guard holds it: `_counted`, `_circled`.)
        while (limit := ctx.max_steps or self._step_limit(ctx)) is None or taken < limit:
            most = (
                None if ctx.max_steps else min((one for one in (limit, role) if one), default=None)
            )
            self._hold_to_role(ctx, taken)
            self._steps_left[ctx.agent_id] = None if most is None else most - taken
            result, message_id = await self._model_step(ctx, info, sent)
            if _goes_on(ctx):  # (once it came back: a refused step or a 429 is none it took)
                self._steps_used[ctx.agent_id] = taken + 1
            sent = result.input_tokens
            # B-387: tried again, a step that tried Codex's own tools still costs a step, so a
            # model that keeps trying ends within its step limit.
            if (tries := self._codex_tried(ctx, result)) is not None:
                if tries >= CODEX_TRIES:
                    return "failed", CODEX_TOOLS_FAILED.format(
                        work="review" if ctx.agent_id in self._reviews else "work"
                    )
                taken += 1
                continue
            if not result.tool_calls:
                return "completed", None
            await self._run_tools(ctx, info, message_id, result.tool_calls)
            if ctx.agent_id in self._stuck and (end := await self._circled(ctx)) is not None:
                return end
            taken += 1
        self._stopped_by_koloni(ctx)
        return "failed", self._given_limit(ctx)

    def _codex_tried(self: "AgentRunner", ctx: Ctx, result: StepResult) -> int | None:
        """B-387: a step in which Codex tried its own tools, which are off here - its stderr says
        so (`CodexCliClient.REFUSED`), else an end that says it (only of one that made no call of
        KOLONİ's: else it may quote them) - is told to use KOLONİ's. One that asked for KOLONİ's
        tools too goes on, told once. One that asked for none is tried again and told again: its
        tries in a row, which `_steps` fails at `CODEX_TRIES`; a step with any call of KOLONİ's
        starts the count anew. Told, a sub-agent's end with no call of KOLONİ's at all counts too
        (a Lead may answer from what it knows, and so may an answer or a discussion beside its
        work). None: a step that is no try."""
        refused = result.own_tools_refused or (
            getattr(ctx.model, "command", None) == "codex"
            and not result.tool_calls
            and CODEX_OWN_TOOLS in result.content
            and not self._calls_of(ctx)
        )
        told = ctx.agent_id in self._codex_tries
        if result.tool_calls:
            if refused and not told:
                self._nudge(ctx, CODEX_TOOLS_OFF)
            if refused or told:
                self._codex_tries[ctx.agent_id] = 0
            return None
        if not (refused or (told and ctx.depth > 0 and _goes_on(ctx) and not self._calls_of(ctx))):
            return None
        tries = self._codex_tries[ctx.agent_id] = self._codex_tries.get(ctx.agent_id, 0) + 1
        if tries < CODEX_TRIES:  # (the third ends it: nothing to tell)
            self._nudge(ctx, CODEX_TOOLS_OFF)
        return tries

    async def _steps_first(self: "AgentRunner", ctx: Ctx) -> None:
        """`_steps`, before its first: the files the user asked saved, and a sub-agent's
        brief from its map's knowledge."""
        if ctx.depth == 0 and ctx.root is not None and not ctx.answering and not ctx.discussion:
            await self._save_attached(ctx)  # (the user's "Save these to the project too")
        if ctx.depth and ctx.root is not None and ctx.agent_id not in self._about:
            # (In a thread: it reads every page its map's knowledge kept. `_history` reads it.)
            # Only for a role with a map: a thread is a wait, and with none the step runs on
            # as before - a CLI opener's spawn is answered with the report of a sub-agent that
            # is back by then (`_run_from_cli`), not "started".
            about = (
                await asyncio.to_thread(knows.about, ctx.folder, known, ctx.task or "")
                if (known := self._mapped(ctx))
                else ""
            )
            # Pages read from the web: looked at once, as a lookup's are (93-A4) - the user is
            # warned, and it stays the same at every step.
            if about and self._orders(
                ctx, "web", "its knowledge's pages, in its brief", web.inside(about)
            ):
                about = f"{injection.NOTE}\n{about}"
            self._about[ctx.agent_id] = about

    async def _steps_surface(
        self: "AgentRunner", ctx: Ctx, info: ModelInfo
    ) -> tuple[Ctx, ModelInfo]:
        """`_steps`: a CLI's version not measured, that did not answer its protocol's first
        request, runs the older way - the agent and its model's info as they now stand."""
        if (
            getattr(ctx.model, "native", False)
            and (model := await cli_surface.checked(ctx.model)) is not ctx.model
        ):
            # K-cli-surface: a version not measured that did not answer its protocol's first
            # request runs the older way, as in a plain chat above.
            ctx = replace(ctx, model=model)
            self._steps_keep_model(ctx, model)
            info = await self._model_of(ctx).info()
        return ctx, info

    def _steps_keep_model(self: "AgentRunner", ctx: Ctx, model) -> None:
        """`_steps`: the agent's kept context has the model it now runs on."""
        if (known := self._ctxs.get(ctx.agent_id)) is not None:
            self._ctxs[ctx.agent_id] = replace(known, model=model)

    async def _session_loop(
        self: "AgentRunner", ctx: Ctx, info: ModelInfo
    ) -> tuple[str, str | None]:
        """An agent whose model is a CLI session: the CLI keeps the loop, KOLONİ keeps
        the records. What the CLI says becomes assistant messages; every tool it asks
        for is recorded under the message before it and run the usual way."""
        before = self._steps_used.get(ctx.agent_id, 0) if _goes_on(ctx) else 0
        transcript = _Transcript(self, ctx, held=True, opened=before)

        async def call_tool(name: str, arguments: str) -> tuple[bool, str, list[dict]]:
            request = ToolCallRequest(f"cli_{uuid.uuid4().hex[:16]}", name, arguments)
            ((call_id, _payload),) = self._record_calls(ctx, transcript.take(), [request])
            status, output = await self._run_from_cli(ctx, call_id, request)
            picture = self._in_result.pop(call_id, None)
            images = (
                []
                if picture is None
                else [
                    {
                        "type": "image",
                        "mimeType": picture[0],
                        "data": base64.b64encode(picture[1]).decode(),
                    }
                ]
            )
            if ctx.agent_id in self._stuck and (end := await self._circled(ctx)) is not None:
                stop = SessionStop(end[1] or "")
                stop.ended = end[0]
                raise stop
            # The CLI keeps its own loop: a note left for it rides on the next result,
            # and so does word that a fact it was given no longer stands - and what the user
            # said to it since (`steer`), once.
            notes = (
                self._deliver(ctx)
                + self._no_longer_given(ctx)
                + self._heard_later.pop(ctx.agent_id, [])
            )
            # B-382: near its limit it is told to report, as a step is (`_near_a_limit`) - each
            # wording once: a session's tokens are known only at its end, so that one repeats.
            near = "" if ctx.answering or ctx.discussion else self._near_a_limit(ctx)
            if near in told_near:
                near = ""
            told_near.add(near)
            return (
                status == "succeeded",
                "\n\n".join(filter(None, [output, *notes, near])),  # pyrefly: ignore[no-matching-overload]  # (filter(None, ...))
                images,
            )

        told_near: set[str] = set()
        # (show as a step is given it, `_model_step`)
        offered = self._offered(
            ctx, ctx.tools, always=True, show=not ctx.answering and ctx.root is not None
        )
        # Its level, as a step's (`_model_step`); given only where there is one.
        effort = self._effort_sent(ctx, info)
        self._set_agent(ctx.cid, ctx.agent_id, effort=effort)
        ended, before = False, transcript.opened
        try:
            # shortcut: its pictures go once, with no retry without them as a step's
            # (`_sent_with_files`): a refusal fails the run; add one if that is seen.
            self._slow(ctx, arm=True)  # (K-yavas)
            usage = await cast(CliSessionClient, self._model_of(ctx)).run_session(
                info.model_id,
                self._history(ctx, offered),
                offered,
                call_tool,
                transcript.on_text,
                transcript.of,
                **({"effort": effort} if effort else {}),
                on_live=lambda item: self._show_live(ctx, item),
            )
            self._slow_off(ctx)
            ended = True
            self._count_tokens(
                ctx,
                usage.input_tokens,
                usage.output_tokens,
                # (A result that has no word of a cache: not known.)
                read=getattr(usage, "cache_read", None),
                written=getattr(usage, "cache_write", None),
                # (Copilot's: also when it speaks with `-p`, its talker)
                nano_aiu=getattr(usage, "nano_aiu", None),
                premium=getattr(usage, "premium_requests", None),
            )
            self._ran_on(ctx, usage.model, getattr(usage, "picked_why", None))
        except (SessionStop, ModelUnavailable) as exc:
            # The CLI is gone, but a tool it asked for may still be on record as
            # running, or a change may still be waiting for a decision nobody can give.
            self._settle_session(ctx)
            with contextlib.suppress(Exception):  # (B-410: the model it ran on, auto's pick too)
                self._ran_on(ctx, exc.model, exc.picked_why)
            if isinstance(exc, SessionStop):
                return exc.ended, str(exc) or None
            raise
        finally:
            self._slow_off(ctx)
            with contextlib.suppress(Exception):  # (a card never fails the run)
                self._reached(ctx, ended or transcript.opened > before)
            transcript.end()  # whatever it had written is kept, also on Stop or failure
            self._end_live(ctx)
            if _goes_on(ctx):
                self._steps_used[ctx.agent_id] = transcript.opened
            if not ended:
                self._cut(ctx)  # it says what it spent only at its end
        return "completed", None

    async def _model_step(
        self: "AgentRunner",
        ctx: Ctx,
        info: ModelInfo,
        sent: int | None = None,
    ) -> tuple[StepResult, str]:
        """One step of an agent asked step by step. `sent`: what the step before it
        reported it sent; past COMPACT_AT of the known window, the older part of its
        history is summarised first (`_compact`)."""
        run_id, cid = ctx.run_id, ctx.cid
        self._hold_to_limit(ctx)
        # The level that goes with this step (below), on its record: none where none goes,
        # nor to a service that refused one before (`EFFORT_REFUSED`); the one sent instead of
        # one its model said it does not take (`EFFORT_INSTEAD`).
        effort = (
            None if getattr(ctx.model, "refused_effort", False) else self._effort_sent(ctx, info)
        )
        effort = getattr(ctx.model, "effort_instead", {}).get(effort, effort)
        # (Anthropic's API too: KOLONİ's own compaction, not its server-side one, slice 77.)
        compacts = getattr(ctx.model, "compacts_itself", False)
        # A model that keeps its own context (a CLI) is measured against no window of the
        # role's where it says none: what it reports is not the size of what it holds.
        window = (
            None
            if compacts and not info.context_window
            else (ctx.context_window or info.context_window)
        )
        compactable = window is not None and not compacts
        self._set_agent(
            cid, ctx.agent_id, last_event_at=now(), effort=effort, context_window=window
        )
        # (Its message is begun before its history is built: a note handed over while it
        # is built (`_deliver`) comes after this step in every later one.)
        with self._factory() as session:
            message = Message(
                conversation_id=cid,
                run_id=run_id,
                agent_id=ctx.agent_id,
                role="assistant",
                content="",
                status="streaming",
                discussion_id=ctx.discussion,
            )
            session.add(message)
            session.commit()
            message_id = message.id
            payload = message_out(message)
            threshold = compact_at(session) / 100
        if ctx.speech_ids is not None:
            ctx.speech_ids.append(message_id)
        self.bus.emit(cid, run_id, "message.created", payload)
        self._live[message_id] = (cid, "")
        last_flush = time.monotonic()
        last_thinking = 0.0

        async def on_delta(text: str) -> None:
            nonlocal last_flush
            self._slow(ctx)
            content = joined(self._live[message_id][1], text)
            self._live[message_id] = (cid, content)
            self.bus.emit_transient(cid, "message.delta", {"message_id": message_id, "text": text})
            if time.monotonic() - last_flush >= FLUSH_SECONDS:
                last_flush = time.monotonic()
                self._save_message(message_id, content, "streaming")

        async def on_thinking(_text: str) -> None:
            nonlocal last_thinking
            self._slow(ctx)
            if time.monotonic() - last_thinking >= 1.0:
                last_thinking = time.monotonic()
                self.bus.emit_transient(
                    cid, "run.thinking", {"run_id": run_id, "agent_id": ctx.agent_id}
                )

        # What a client that hears of its tokens before the answer ends was told so far.
        early: dict[str, int | None] = {}
        ended = False
        try:
            self._slow(ctx, arm=True)  # (K-yavas: its model is asked from here to the step's end)
            # Only the tools this agent's role allows are offered to the model. The
            # roles are read at every step: one created a moment ago can be used now.
            # (and show, to every agent at its own work: it puts a file before the user -
            # but in a plain chat, which has none)
            offered = self._offered(ctx, ctx.tools, show=not ctx.answering and ctx.root is not None)
            tools = offered if info.tools_supported and offered else None
            client = self._model_of(ctx)
            more = self._model_step_more(ctx, client, effort, early)
            history = self._history(ctx, tools)
            if compactable and sent and sent >= window * threshold:
                # Meanwhile the agent says it is summarising (`_compact`).
                history = await self._compact(ctx, info, history, window, sent)
            try:
                result = await self._sent_with_files(
                    ctx,
                    client,
                    info.model_id,
                    history,
                    tools,
                    on_delta,
                    on_thinking,
                    message_id,
                    more,
                )
            except ModelUnavailable as exc:
                # (Not one too large to be read: that is summarised below, not asked again.)
                if (
                    exc.retry_in is not None
                    and not self._live[message_id][1]
                    and classify(exc)[0] != "credits_exhausted"
                    and not refused_for_size(exc)
                ):
                    # A short failure of its provider's before it wrote a word: asked once
                    # more, as it was, and said on its record. A second failure ends it.
                    # shortcut: not once text has come (it would be shown twice); clear the
                    # message and ask again there too if mid-answer drops are seen often.
                    await self._model_step_again(ctx, exc, early, exc.retry_in)
                    smaller = history
                else:
                    # Refused for its size (a step that fitted no more, a turn's first): its
                    # older part summarised, it is asked once more - also where its window
                    # is not known: the refusal says it is full.
                    smaller = (
                        await self._compact(ctx, info, history, window)
                        if (not compacts and refused_for_size(exc))
                        else history
                    )
                    # (Asked again only with less: the same size would be refused the same
                    # way.)
                    if smaller is history or sum(map(_size, smaller)) >= sum(map(_size, history)):
                        raise
                result = await client.stream_step(
                    info.model_id, smaller, tools, on_delta, on_thinking, **more
                )
            ended = True
        except ModelUnavailable as exc:
            self._model_step_larger(ctx, info, exc)
            raise
        finally:
            self._slow_off(ctx)
            # Also on cancel or failure: whatever text arrived is kept.
            content = self._live.pop(message_id)[1]
            payload = self._save_message(
                message_id, content, "complete", _kept_blocks(result) if ended else None
            )
            self.bus.emit(cid, run_id, "message.completed", payload)
            if not ended:
                self._cut(ctx, **early)  # a step is paid for as far as it got

        self._model_step_effort(ctx, info, result, effort)
        # Token counts are kept per agent; the run carries its lead agent's.
        self._count_tokens(
            ctx,
            result.input_tokens,
            result.output_tokens,
            read=result.cache_read,
            written=result.cache_write,
        )
        self._ran_on(ctx, result.model)
        return result, message_id

    @staticmethod
    def _model_step_larger(ctx: Ctx, info: ModelInfo, exc: ModelUnavailable) -> None:
        """`_model_step`, failed: where it was refused for its size, measured against a window
        its role sets above the one found, the failure says so."""
        # Refused for its size, measured against a window its role sets above the one
        # found (or none found): that may be why (59 §3b). The failure stays as it was.
        if (
            ctx.context_window
            and refused_for_size(exc)
            and ctx.context_window > (info.context_window or 0)
        ):
            exc.args = (f"{exc}{ROLE_WINDOW_LARGER}",)

    def _model_step_more(
        self: "AgentRunner", ctx: Ctx, client, effort, early: dict
    ) -> dict[str, object]:
        """`_model_step`: what goes with a step besides its history - the level, the client's
        early word on its tokens (into `early`), caching, and no thinking where it is lost."""
        more: dict[str, object] = {}
        if effort:
            more["effort"] = effort
        if getattr(client, "reports_early", False):
            more["so_far"] = lambda sent, made, read=None, written=None: early.update(
                sent=sent, made=made, read=read, written=written
            )
        if getattr(client, "caches", False):
            # Every step of an agent sends what the one before it sent, and more.
            more["cache"] = True
        if getattr(client, "replays_blocks", False) and ctx.discussion:
            # Told how its discussion stands at each step and never again, it would
            # have none of its thinking sent back (`_replayed`): none is asked for where
            # that is a choice. shortcut: make those notes append-only (or send the API's
            # `drop_block`) to keep a speaker's thinking.
            more["think"] = False
        return more

    async def _model_step_again(
        self: "AgentRunner", ctx: Ctx, exc: ModelUnavailable, early: dict, retry_in: float
    ) -> None:
        """`_model_step`, before a step is asked once more: said on its record, what the
        failed one read paid for, and its provider's wait waited."""
        self._set_agent(ctx.cid, ctx.agent_id, retry_note=RETRIED.format(why=exc))
        if early:  # (what the failed one said it read is paid for: `_cut`)
            self._count_tokens(
                ctx,
                early["sent"],
                early["made"],
                step=False,
                read=early["read"],
                written=early["written"],
            )
            early.clear()
        await asyncio.sleep(retry_in)

    def _model_step_effort(
        self: "AgentRunner", ctx: Ctx, info: ModelInfo, result: StepResult, effort
    ) -> None:
        """`_model_step`: a level its service refused, or took another of, on its record."""
        if result.effort_refused:
            self._set_agent(ctx.cid, ctx.agent_id, effort=None)
            self._effort_note(
                ctx, EFFORT_REFUSED.format(asked=effort, provider=ctx.provider or "Its provider")
            )
        elif result.effort_instead:
            asked, took = result.effort_instead
            self._set_agent(ctx.cid, ctx.agent_id, effort=took)
            self._effort_note(
                ctx,
                EFFORT_INSTEAD.format(model=info.model_id, asked=asked, sent=took or "no level"),
            )

    def _effort_sent(self: "AgentRunner", ctx: Ctx, info: ModelInfo) -> str | None:
        """`sent_effort`, and where that is not its own level, what was really sent said on its
        record. Not where its model's levels are not known at all - nothing is sent then, as
        said with its result."""
        effort = sent_effort(ctx, info)
        if ctx.effort is not None and getattr(ctx.model, "level_named", False):
            self._auto_effort.discard(ctx.agent_id)  # (Auto's or the role's: none goes, B-404)
            said = (
                EFFORT_COPILOT_AUTO
                if getattr(ctx.model, "command", "") == "copilot"
                else (EFFORT_IN_NAME)
            )
            self._effort_note(ctx, said.format(asked=ctx.effort, model=info.model_id))
        elif ctx.agent_id in self._auto_effort and ctx.effort is not None:
            self._auto_effort.discard(ctx.agent_id)
            level = ctx.effort.capitalize()  # (medium at most: `AUTO_START`)
            self._effort_note(
                ctx,
                EFFORT_AUTO_UNSENT.format(level=level)
                if not info.efforts
                else EFFORT_AUTO_OFF
                if ctx.effort == "off"
                else EFFORT_AUTO.format(level=level),
            )
        if ctx.effort is not None and effort != ctx.effort and info.efforts:
            self._effort_note(
                ctx,
                EFFORT_STEPPED.format(asked=ctx.effort, sent=effort, model=info.model_id)
                if effort
                else EFFORT_NONE_BELOW.format(asked=ctx.effort, model=info.model_id),
            )
        return effort

    def _effort_note(self: "AgentRunner", ctx: Ctx, said: str) -> None:
        """`said` of its level, once, after what its record says of it already: its opener's
        pick and reason (`EFFORT_PICKED`) stay."""
        with self._factory() as session:
            note = session.get_one(Agent, ctx.agent_id).effort_note
        if said not in (note or ""):
            self._set_agent(ctx.cid, ctx.agent_id, effort_note=f"{note} {said}" if note else said)

    def _cli_session(self: "AgentRunner", ctx: Ctx) -> dict | None:
        """27 / 93-C3: the Claude Code session its native turn may go on in - its own last
        run's, taken (a run that fails or is stopped leaves none), else that of the agent it
        goes on from (a later turn's lead), one step back only, as `_sent_before`."""
        with self._factory() as session:
            agent = session.get_one(Agent, ctx.agent_id)
            kept, agent.cli_session = agent.cli_session, None
            if kept is None and ctx.continues_id:
                earlier = session.get(Agent, ctx.continues_id)
                # (Taken from it too: no two runs go on in one session.
                # shortcut: Claude Code's --fork-session is not measured; fork one if needed.)
                if earlier is not None:
                    kept, earlier.cli_session = earlier.cli_session, None
            session.commit()
        return kept

    def _session_mark(self: "AgentRunner", ctx: Ctx) -> dict:
        """27: where the agent's record stood when its run returned, kept with its session
        (`_whole`): its last call's number, and the time."""
        with self._factory() as session:
            calls = (
                session.scalar(
                    select(func.max(ToolCall.seq)).where(ToolCall.agent_id == ctx.agent_id)
                )
                or 0
            )
        return {"agent": ctx.agent_id, "calls": calls, "at": now().isoformat()}

    def _whole(self: "AgentRunner", kept: dict) -> bool:
        """27: whether a kept session saw all its turn's history holds - `_history` places
        before its last answer, where a resumed one is sent nothing (`since_its_last_word`):
        nothing put on its agent's record after its run returned (a write taken back, a keep
        card), no note of before handed over since, and for a lead no question of its turn
        answered by another or for the user (B-145). Else it starts anew, sent everything."""
        try:
            at, agent_id, calls = (
                datetime.fromisoformat(kept["at"]),
                kept["agent"],
                int(kept["calls"]),
            )
        except (KeyError, TypeError, ValueError):
            return False
        with self._factory() as session:
            holder = session.get(Agent, agent_id)
            if holder is None or session.scalar(
                select(ToolCall.id)
                .where(ToolCall.agent_id == agent_id, ToolCall.seq > calls)
                .limit(1)
            ):
                return False
            if session.scalar(
                select(Message.id)
                .where(
                    Message.agent_id == agent_id,
                    Message.role == "agent",
                    Message.created_at <= at,
                    Message.delivered_at > at,
                )
                .limit(1)
            ):
                return False
            return (
                holder.depth > 0
                or session.scalar(
                    select(Question.id)
                    .where(
                        Question.run_id == holder.run_id,
                        Question.status == "answered",
                        or_(
                            Question.agent_id != agent_id,
                            Question.lead_why.is_not(None),
                            Question.leave,
                        ),
                    )
                    .limit(1)
                )
                is None
            )

    def _sent_before(self: "AgentRunner", ctx: Ctx) -> int | None:
        """What was last measured of an agent's context: its own last step (a turn on a
        message), else the last step of the agent it goes on from (a later turn's lead),
        which was sent what it is sent again now, and less."""
        with self._factory() as session:
            sent = session.get_one(Agent, ctx.agent_id).input_tokens
            if sent is None and ctx.continues_id:
                earlier = session.get(Agent, ctx.continues_id)
                sent = earlier.input_tokens if earlier else None
        return sent

    async def _run_tools(
        self: "AgentRunner",
        ctx: Ctx,
        info: ModelInfo,
        message_id: str,
        requests: list[ToolCallRequest],
    ) -> None:
        """Record every requested call first, then run them in order. Sub-agents asked
        for one after another are opened together and work at the same time. A model's id named
        as KOLONİ's own calls are (`koloni_...`, `cli_...`) is recorded as one of its own
        (`provider_call_id`), whatever client gave it: KOLONİ trusts those by their names."""
        requests = [replace(one, id=provider_call_id(one.id)) for one in requests]
        created = self._record_calls(ctx, message_id, requests)
        calls = [(made[0], request) for made, request in zip(created, requests, strict=True)]
        at = 0
        while at < len(calls):
            group = [calls[at]]
            if calls[at][1].name == "spawn_agent":
                while at + len(group) < len(calls) and (
                    calls[at + len(group)][1].name == "spawn_agent"
                ):
                    group.append(calls[at + len(group)])
            if calls[at][1].name == "spawn_agent":
                # B-87: the leads this message opens itself are not opened beside another too.
                self._asked_leads.setdefault(ctx.agent_id, set()).update(
                    _role_asked(request) for _id, request in group
                )
            if len(group) == 1:
                await self._call_or_later(ctx, *group[0])
            else:
                # K-rol-cogul: none starts work before all are opened or refused - one done at
                # once would end its recipe step with the others still to come. Nothing before
                # an agent is opened takes or waits for a place (`_take`, in `_see_through`):
                # the wait is for its siblings' checks alone, and a Stop cancels it.
                # (By call: another turn of the same agent - an answer - has groups of its own.)
                held = ({one[0] for one in group}, asyncio.Event())
                self._at_once.update(dict.fromkeys(held[0], held))
                try:
                    await self._together([self._opened_with(ctx, *one) for one in group])
                finally:
                    for one in group:
                        self._at_once.pop(one[0], None)
            at += len(group)
