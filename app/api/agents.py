import asyncio
import os
import subprocess
import sys

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import memory as kept
from app import raw
from app.agent import (
    AGENT_TERMINAL,
    CHARS_PER_TOKEN,
    COMPACT_FLAG,
    _line_on_record,
    compact_at,
)
from app.agent.limits_mixin import STEPS_FLAG, app_steps
from app.api.deps import get_session, require_origin, require_own_origin
from app.changes import in_copy
from app.db.models import Agent, Conversation, Flag, Run, ToolCall
from app.model_client import ModelUnavailable
from app.schemas import (
    AgentOut,
    AnswerLanguage,
    Compaction,
    HandedOut,
    RawOut,
    SecretIn,
    StepLimit,
    SummaryIn,
    TellIn,
    ToolCallDecision,
    ToolCallOut,
    WorkingCopyOut,
)
from app.serialize import agent_out, tool_call_out

router = APIRouter(prefix="/api", tags=["agents"], dependencies=[Depends(require_origin)])

DECISION_TIMEOUT = 5.0


async def _settled(session: Session, row, still_open: str) -> None:
    """The agent task acts on the decision; answer once it has."""
    deadline = asyncio.get_running_loop().time() + DECISION_TIMEOUT
    while True:
        await asyncio.sleep(0.01)
        session.refresh(row)
        if row.status != still_open or asyncio.get_running_loop().time() > deadline:
            return


async def _decide_spawn(agent_id: str, decision: str, request: Request, session: Session) -> dict:
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404, "agent not found")
    if not request.app.state.runner.decide_spawn(agent_id, decision):
        raise HTTPException(409, "this agent is no longer waiting for a decision")
    await _settled(session, agent, "proposed")
    return agent_out(agent)


@router.get("/agents/{agent_id}/raw", response_model=RawOut)
async def raw_stream(
    agent_id: str, after: int = Query(0, ge=0), session: Session = Depends(get_session)
):
    """What the agent's CLI wrote itself, line by line: the lines numbered above `after`,
    the oldest first, as many as one answer carries (`more`: ask again for the rest).
    Only read: nothing is written anywhere for it."""
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404, "agent not found")
    kept = raw.read(agent_id, after)
    # A CLI is on record by how it ran; where that is not on record, by what it wrote.
    available = agent.provider_mode is not None or kept is not None
    return {"available": available, **(kept or {"lines": [], "dropped": 0, "more": False})}


@router.get("/agents/{agent_id}/handed", response_model=list[HandedOut])
def handed(agent_id: str, session: Session = Depends(get_session)):
    """B-366: the agents whose work its briefing carried (`handed_from`), in its order, each
    with its name and chat: the page holds only its own chat's agents. One no longer on
    record (its chat deleted) is left out."""
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404, "agent not found")
    ids = agent.handed_from or []
    found = {one.id: (one, chat) for one, chat in session.execute(
        select(Agent, Conversation)
        .join(Run, Run.id == Agent.run_id)
        .join(Conversation, Conversation.id == Run.conversation_id)
        .where(Agent.id.in_(ids))
    ).tuples()}
    return [{"agent_id": one.id, "agent_role": one.role_name, "agent_name": one.name,
             "conversation_id": chat.id, "conversation_title": chat.title,
             "at": one.ended_at or one.started_at or one.created_at}
            for one, chat in (found[i] for i in ids if i in found)]


def _copy_of(session: Session, agent_id: str) -> Agent:
    """The agent whose working copy this agent changes files in: itself, or the one above
    it that has one. 404 where there is none."""
    agent = session.get(Agent, agent_id)
    while agent is not None and (agent.copy or {}).get("state") == "parent":
        agent = session.get(Agent, agent.parent_agent_id) if agent.parent_agent_id else None
    if agent is None or (agent.copy or {}).get("state") != "own":
        raise HTTPException(404, "this agent works in no copy of its own")
    return agent


@router.get("/agents/{agent_id}/copy", response_model=WorkingCopyOut)
def working_copy(agent_id: str, request: Request, session: Session = Depends(get_session)):
    """What the agent's working copy holds that the project does not, as its work goes on
    (slice 70): each file once, with its diff. Only read."""
    owner = _copy_of(session, agent_id)
    folder = request.app.state.runner.copy_folder(owner.id)
    return {"agent_id": owner.id, "folder": str(folder) if folder else None,
            "files": in_copy(session, _line_on_record(session, owner.id))}


def open_folder(folder) -> None:
    """The system's file manager on a folder of KOLONİ's own: never a path from a request."""
    if sys.platform == "win32":
        os.startfile(folder, "explore")  # noqa: S606 (KOLONİ's own folder, in Explorer)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(folder)],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)


@router.post("/agents/{agent_id}/copy/open", status_code=204,
             dependencies=[Depends(require_own_origin)])
def open_copy(agent_id: str, request: Request, session: Session = Depends(get_session)):
    """The user's Open folder, from the app's own page: the copy's folder in the system's
    file manager, while its work goes on."""
    folder = request.app.state.runner.copy_folder(_copy_of(session, agent_id).id)
    if folder is None or not folder.is_dir():
        raise HTTPException(409, "its working copy is gone: its work is over")
    open_folder(folder)


@router.post("/agents/{agent_id}/approve", response_model=AgentOut,
             dependencies=[Depends(require_own_origin)])
async def approve_agent(agent_id: str, request: Request, session: Session = Depends(get_session)):
    return await _decide_spawn(agent_id, "approve", request, session)


@router.post("/agents/{agent_id}/reject", response_model=AgentOut,
             dependencies=[Depends(require_own_origin)])
async def reject_agent(agent_id: str, request: Request, session: Session = Depends(get_session)):
    return await _decide_spawn(agent_id, "reject", request, session)


@router.post("/agents/{agent_id}/tell", status_code=204,
             dependencies=[Depends(require_own_origin)])
async def tell_agent(agent_id: str, body: TellIn, request: Request,
                     session: Session = Depends(get_session)):
    """The user's own word to an agent while it works, from its window on the app's own page
    (89d C): into its CLI's turn, or its next step; 409 with why it cannot hear it."""
    if session.get(Agent, agent_id) is None:
        raise HTTPException(404, "agent not found")
    if not body.words.strip():
        raise HTTPException(422, "say something to it")
    if why := await request.app.state.runner.tell_at_work(agent_id, body.words.strip()):
        raise HTTPException(409, why)


@router.patch(
    "/agents/{agent_id}/summary", response_model=AgentOut,
    dependencies=[Depends(require_own_origin)],
)
async def correct_summary(
    agent_id: str, body: SummaryIn, request: Request, session: Session = Depends(get_session)
):
    """The user corrects an agent's working state, from the app's own page: what its model
    is told of its earlier work. Its model is sent their words from its next step on, and
    a later turn's lead goes on from them; what is on record is not changed. No longer
    than a quarter of its window (as a summary is written), and never 40 000 characters."""
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404, "agent not found")
    if request.app.state.runner.compacting(agent_id):
        # The summary being made would be written over the user's words.
        raise HTTPException(409, "its older part is being summarised: correct it once that is done")
    if not agent.summary or agent.summary_anchor is None:
        raise HTTPException(409, "nothing of this agent's history is summarised")
    if not agent.summary_correctable:
        raise HTTPException(409, "this sub-agent's work is over: nothing goes on from it")
    if body.summarised != agent.summarised:
        # Their words are of the older summary: in the place of the newer, what was summarised
        # in between would reach its model neither whole nor summarised.
        raise HTTPException(
            409, "it was summarised again since you began: edit the new working state")
    # (Never past the 40 000 that `SummaryIn` takes at all.)
    most = min(agent.context_window * CHARS_PER_TOKEN // 4 if agent.context_window else 40_000,
               40_000)
    if len(body.summary) > most:
        raise HTTPException(
            422, f"too long for this agent's window: a working state holds at most {most} "
            "characters here")
    if session.scalar(select(Agent.id).where(Agent.continues_id == agent_id).limit(1)):
        # Its words would reach no model: the one that goes on from it has its own.
        raise HTTPException(
            409, "a later agent goes on from this one: correct its working state there")
    cid = session.get_one(Run, agent.run_id).conversation_id
    await request.app.state.runner.correct_summary(cid, agent_id, body.summary)
    session.refresh(agent)
    return agent_out(agent)


@router.get("/compaction", response_model=Compaction)
def compaction(session: Session = Depends(get_session)):
    return {"compact_at": compact_at(session)}


@router.put(
    "/compaction", response_model=Compaction, dependencies=[Depends(require_own_origin)])
def set_compaction(body: Compaction, session: Session = Depends(get_session)):
    """Past what % of its window an agent KOLONİ compacts is summarised, in every project:
    the user's to say, from the app's own page. (Not a CLI's that goes on in its own session:
    it compacts that itself, `Agent.compacts_itself`.)"""
    row = session.get(Flag, COMPACT_FLAG)
    if row is None:
        session.add(Flag(name=COMPACT_FLAG, value=str(body.compact_at)))
    else:
        row.value = str(body.compact_at)
    session.commit()
    return body


@router.get("/steps", response_model=StepLimit)
def steps(request: Request, session: Session = Depends(get_session)):
    return {"max_steps": app_steps(session, request.app.state.settings.max_steps)}


@router.put("/steps", response_model=StepLimit, dependencies=[Depends(require_own_origin)])
def set_steps(body: StepLimit, session: Session = Depends(get_session)):
    """B-398: the most steps one agent takes on a job, in every project - the user's to say."""
    row = session.get(Flag, STEPS_FLAG)
    if row is None:
        session.add(Flag(name=STEPS_FLAG, value=str(body.max_steps)))
    else:
        row.value = str(body.max_steps)
    session.commit()
    return body


@router.get("/answer-in", response_model=AnswerLanguage)
def answer_in(session: Session = Depends(get_session)):
    return {"answer_in": kept.answer_in(session)}


@router.put("/answer-in", response_model=AnswerLanguage, dependencies=[Depends(require_own_origin)])
def set_answer_in(body: AnswerLanguage, session: Session = Depends(get_session)):
    """K-cevap-dili: the language every agent writes in, in every project; null is Auto. From
    the app's own page only: it goes into every agent's brief."""
    session.execute(delete(Flag).where(Flag.name == kept.ANSWER_IN))
    if body.answer_in:
        session.add(Flag(name=kept.ANSWER_IN, value=body.answer_in))
    session.commit()
    return body


@router.post(
    "/agents/{agent_id}/compact", response_model=AgentOut,
    dependencies=[Depends(require_own_origin)],
)
async def compact_agent(agent_id: str, request: Request, session: Session = Depends(get_session)):
    """The user's Compact now, from the app's own page: a lead whose turn is over has its
    older part summarised now, whatever its size (`AgentRunner.compact_now`); answered once
    that is done, with the agent - its `summarised` and `summary_note` say what came of it.
    Not while it is at work: it is compacted at its steps then, past the threshold."""
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404, "agent not found")
    runner = request.app.state.runner
    if agent.provider_mode == "step":  # (RunStatus says the same)
        raise HTTPException(409, "run step by step: each step is sent a trimmed history; "
                                 "not compacted")
    if agent.compacts_itself:
        raise HTTPException(409, "its CLI keeps what it is sent itself: KOLONİ does not "
                                 "compact it")
    if agent.depth > 0:
        raise HTTPException(409, "a sub-agent is compacted at its steps: nothing goes on from "
                                 "it once its work is over")
    if agent.status not in AGENT_TERMINAL:
        raise HTTPException(409, "at work: it is compacted at its next step past "
                                 f"{compact_at(session)}% of its window; compact it once its "
                                 "turn is over")
    if session.scalar(select(Agent.id).where(Agent.continues_id == agent_id).limit(1)):
        raise HTTPException(409, "a later agent goes on from this one: compact that one")
    if runner.compacting(agent_id):
        raise HTTPException(409, "its older part is being summarised already")
    try:
        await runner.compact_now(agent_id)
    except ModelUnavailable as exc:
        raise HTTPException(409, f"not compacted: {exc}") from None
    session.refresh(agent)
    return agent_out(agent)


async def _decide_role(call_id: str, decision: str, request: Request, session: Session) -> dict:
    """A role an agent asked to create, or a path outside the project, waits on its tool
    call."""
    call = session.get(ToolCall, call_id)
    if call is None:
        raise HTTPException(404, "tool call not found")
    runner = request.app.state.runner
    if runner.asks_outside(call_id) or runner.asks_skill(call_id):
        # Leave to go outside the project is the user's to give, from the app's own page:
        # not a command's that an agent runs against the app's address. And a skill: what
        # its agents are told, and scripts that may run unasked.
        require_own_origin(request)
    if not runner.decide_role(call_id, decision):
        raise HTTPException(409, "this tool call is not waiting for a decision")
    # Answered once the agent has heard: its call may go on for a while after that -
    # the agent may have to wait for a place among the agents at work first.
    deadline = asyncio.get_running_loop().time() + DECISION_TIMEOUT
    while runner.role_waits(call_id) and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.01)
    session.refresh(call)
    return tool_call_out(call)


@router.post("/tool-calls/{call_id}/approve", response_model=ToolCallOut,
             dependencies=[Depends(require_own_origin)])
async def approve_call(
    call_id: str, request: Request, body: ToolCallDecision | None = None,
    session: Session = Depends(get_session),
):
    return await _decide_role(call_id, body.scope if body else "approve", request, session)


@router.post("/tool-calls/{call_id}/reject", response_model=ToolCallOut,
             dependencies=[Depends(require_own_origin)])
async def reject_call(call_id: str, request: Request, session: Session = Depends(get_session)):
    return await _decide_role(call_id, "reject", request, session)


@router.post(
    "/tool-calls/{call_id}/secret", response_model=ToolCallOut,
    dependencies=[Depends(require_own_origin)],
)
async def give_secret(
    call_id: str, body: SecretIn, request: Request, session: Session = Depends(get_session)
):
    """The user's word on an agent's ask for a secret (slice 91), from the app's own page:
    its value - kept in memory for that turn's commands, never on record - or null for no.
    The answer is the call, which says only given or denied."""
    call = session.get(ToolCall, call_id)
    if call is None:
        raise HTTPException(404, "tool call not found")
    if not request.app.state.runner.give_secret(call_id, body.value):
        raise HTTPException(409, "this tool call is not waiting for a secret")
    await _settled(session, call, "pending")
    return tool_call_out(call)
