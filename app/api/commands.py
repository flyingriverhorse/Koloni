import asyncio
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import triggers
from app.api.deps import get_session, require_origin, require_own_origin
from app.commands import MAX_RULE, rules_here, tidy_rule
from app.db.models import AllowedCommand, Command, Conversation
from app.schemas import AllowedCommandOut, CommandOut, FrameOut
from app.serialize import allowed_command_out, command_out

router = APIRouter(prefix="/api", tags=["commands"], dependencies=[Depends(require_origin)])

DECISION_TIMEOUT = 5.0
# Where a server's page may send the frame check: this machine only, a few times at most.
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
MOST_REDIRECTS = 5


class ApproveIn(BaseModel):
    # Also add this command's prefix to the conversation's allow list.
    remember: bool = False


class RuleIn(BaseModel):
    # The command, as it is to be run; tidied to one space between its words.
    prefix: str = Field(max_length=4 * MAX_RULE)


async def _decide(command_id: str, decision: str, request: Request, session: Session) -> dict:
    command = session.get(Command, command_id)
    if command is None:
        raise HTTPException(404, "command not found")
    runner = request.app.state.runner
    if not runner.commands.decide(command_id, decision):
        raise HTTPException(409, "this command is no longer waiting for a decision")
    # The agent task acts on the decision; answer once it has.
    deadline = asyncio.get_running_loop().time() + DECISION_TIMEOUT
    while True:
        await asyncio.sleep(0.01)
        session.refresh(command)
        if command.status != "proposed" or asyncio.get_running_loop().time() > deadline:
            return command_out(command)


@router.post("/commands/{command_id}/approve", response_model=CommandOut,
             dependencies=[Depends(require_own_origin)])  # (and "always": a rule)
async def approve(
    command_id: str, body: ApproveIn, request: Request, session: Session = Depends(get_session)
):
    return await _decide(command_id, "always" if body.remember else "once", request, session)


@router.post("/commands/{command_id}/reject", response_model=CommandOut,
             dependencies=[Depends(require_own_origin)])
async def reject(command_id: str, request: Request, session: Session = Depends(get_session)):
    return await _decide(command_id, "reject", request, session)


@router.post(
    "/commands/{command_id}/stop", response_model=CommandOut,
    dependencies=[Depends(require_own_origin)],
)
async def stop(command_id: str, request: Request, session: Session = Depends(get_session)):
    """Stop a command that keeps running (a dev server), with every process it started.
    The user's, from the app's own page: answered at once, "killed" follows on its record.
    One a CLI runs with its own tool ends that CLI's turn (B-357)."""
    command = session.get(Command, command_id)
    if command is None:
        raise HTTPException(404, "command not found")
    runner = request.app.state.runner
    if not runner.commands.stop(command_id) and not (
            command.origin == "cli" and command.status in ("approved", "running")
            and runner.stop_cli(command.agent_id)):
        raise HTTPException(409, "this command is not running")
    return command_out(command)


@router.get("/commands/{command_id}/frame", response_model=FrameOut)
async def frame(command_id: str, session: Session = Depends(get_session)):
    """Whether the page a command serves lets KOLONİ show it in a frame. Asks only its own
    address on this machine, as its output said it, and where that sends it on this
    machine; None where nothing answers, or it sends elsewhere (nothing is asked there)."""
    command = session.get(Command, command_id)
    if command is None:
        raise HTTPException(404, "command not found")
    if not command.preview_url:
        return {"frameable": None}
    url = httpx.URL(command.preview_url)
    try:
        async with httpx.AsyncClient(timeout=3, follow_redirects=False, trust_env=False) as client:
            for _hop in range(MOST_REDIRECTS + 1):
                async with client.stream("GET", url) as answer:
                    headers = answer.headers
                if not answer.is_redirect:
                    break
                url = url.join(headers["location"])
                if url.scheme != "http" or url.host not in LOOPBACK:
                    return {"frameable": None}
            else:
                return {"frameable": None}
    except httpx.HTTPError:
        return {"frameable": None}
    ancestors = re.search(
        r"frame-ancestors([^;]*)", headers.get("content-security-policy", ""), re.IGNORECASE)
    # shortcut: frame-ancestors naming KOLONİ's own address is taken as a no; upgrade if one does.
    refused = "x-frame-options" in headers or (ancestors and "*" not in ancestors[1].split())
    return {"frameable": not refused}


@router.post(
    "/conversations/{conversation_id}/allowed-commands", response_model=AllowedCommandOut,
    status_code=201, responses={200: {"model": AllowedCommandOut}},
    dependencies=[Depends(require_own_origin)],
)
async def add_rule(
    conversation_id: str, body: RuleIn, request: Request, response: Response,
    session: Session = Depends(get_session),
):
    """Put a command on a conversation's allow list by hand, as "Always run" does when a
    command is approved: the conversation's own turns then run it without asking, and a
    trigger of that conversation can tick it. It says what may run unasked, so it is
    taken only from the app's own page. A rule that is already there is answered with
    (200), not made twice."""
    conversation = session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(404, "conversation not found")
    if conversation.project_id is None:
        raise HTTPException(422, "a chat with no folder runs no command")
    try:
        prefix = tidy_rule(body.prefix)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    there = rules_here(conversation).where(AllowedCommand.prefix == prefix)
    rule = session.scalar(there)
    if rule is None:
        rule = AllowedCommand(
            conversation_id=conversation_id, project_id=conversation.project_id, prefix=prefix)
        session.add(rule)
        try:
            session.commit()
        except IntegrityError:  # put there by somebody else just now
            session.rollback()
            rule = session.scalars(there).one()
            response.status_code = 200
        else:
            request.app.state.runner.commands.emit_rules(conversation_id)
    else:
        response.status_code = 200
    return allowed_command_out(rule)


@router.delete("/allowed-commands/{rule_id}", status_code=204,
               dependencies=[Depends(require_own_origin)])
async def remove_rule(rule_id: str, request: Request, session: Session = Depends(get_session)):
    """Take a rule off its conversation's allow list. A trigger that had it ticked may
    no longer run it, from this moment (`commands.ticked` reads the list as it is); that
    is also written on the trigger, for the user to look over."""
    rule = session.get(AllowedCommand, rule_id)
    if rule is None:
        raise HTTPException(404, "rule not found")
    conversation_id = rule.conversation_id
    projects = triggers.rule_removed(session, rule)
    session.delete(rule)
    session.commit()
    request.app.state.runner.commands.emit_rules(conversation_id)
    for project_id in projects:
        request.app.state.triggers.announce(project_id)
    return Response(status_code=204)
