"""Triggers, for the user: make one, change it, switch it off, run it now, pause them all.
A trigger says what a turn may do with nobody watching, so only the user makes or changes
one: every route that changes something takes only a request that says it comes from the
app's own page (`require_own_origin`), and no agent has a tool for any of it. An agent only
proposes one (`propose_trigger`, slice 69): the user's Approve here makes it.

The one exception is the webhook itself, `POST /api/hooks/{key}`: it is meant to be called
by another program, so it asks for the trigger's key instead, and only from this machine.
"""

import contextlib

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, literal_column, select
from sqlalchemy.orm import Session

from app import triggers as kept
from app.api.deps import get_session, require_origin, require_own_origin
from app.db.models import (
    Conversation,
    Project,
    Trigger,
    TriggerChange,
    TriggerProposal,
    TriggerRun,
    now,
)
from app.schemas import (
    TriggerChangeOut,
    TriggerCreatedOut,
    TriggerIn,
    TriggerOut,
    TriggerPatch,
    TriggerProposalOut,
    TriggersPaused,
    TriggerStartedOut,
)

router = APIRouter(prefix="/api", tags=["triggers"])

THIS_MACHINE = ("127.0.0.1", "::1")


def _trigger(session: Session, trigger_id: str) -> Trigger:
    trigger = session.get(Trigger, trigger_id)
    if trigger is None:
        raise HTTPException(404, "trigger not found")
    return trigger


def _own_conversation(session: Session, project_id: str, conversation_id: str) -> str:
    conversation = session.get(Conversation, conversation_id)
    if conversation is None or conversation.project_id != project_id:
        raise kept.Invalid("a trigger belongs to a conversation of its own project")
    return conversation.id


def _watch(request: Request, trigger: Trigger) -> None:
    """A files trigger starts from the files as they are now. One whose pattern names too many
    by now (files made since it was checked) is saved already - not a 500: the clock's next
    look switches it off and says why."""
    with contextlib.suppress(kept.TooMany):
        request.app.state.triggers.watch(trigger.id)


@router.get("/projects/{project_id}/triggers", response_model=list[TriggerOut])
async def list_triggers(project_id: str, session: Session = Depends(get_session)):
    if session.get(Project, project_id) is None:
        raise HTTPException(404, "project not found")
    triggers = session.scalars(
        select(Trigger).where(Trigger.project_id == project_id)
        .order_by(Trigger.created_at, literal_column("triggers.rowid"))
    ).all()
    return [kept.out(session, trigger) for trigger in triggers]


@router.get("/projects/{project_id}/triggers/changes", response_model=list[TriggerChangeOut])
async def list_changes(project_id: str, session: Session = Depends(get_session)):
    """The newest fifty things done to the project's triggers, newest first - those of
    triggers that have since been deleted among them."""
    if session.get(Project, project_id) is None:
        raise HTTPException(404, "project not found")
    return kept.changes_of(session, TriggerChange.project_id == project_id)


def _today(request: Request):
    return kept.local_day(now(), request.app.state.triggers.zone)


def _proposal(session: Session, proposal_id: str) -> TriggerProposal:
    """An agent's proposal still waiting for the user's word: 404 or 409 otherwise."""
    proposal = session.get(TriggerProposal, proposal_id)
    if proposal is None:
        raise HTTPException(404, "no such proposal")
    if proposal.status != "proposed":
        raise HTTPException(409, f"this proposal was {proposal.status} already")
    return proposal


@router.post(
    "/projects/{project_id}/triggers", response_model=TriggerCreatedOut, status_code=201,
    dependencies=[Depends(require_own_origin)],
)
async def create_trigger(
    project_id: str, body: TriggerIn, request: Request, session: Session = Depends(get_session)
):
    return _create(project_id, body, request, session)


def _create(project_id: str, body: TriggerIn, request: Request, session: Session) -> dict:
    if session.get(Project, project_id) is None:
        raise HTTPException(404, "project not found")
    # (Made in the form from an agent's card: the card is done with, and approves no more.)
    proposal = _proposal(session, body.proposal_id) if body.proposal_id else None
    if proposal is not None and proposal.conversation_id != body.conversation_id:
        # (Its card is in that chat, of this project: a trigger made from it goes there.)
        raise HTTPException(422, "a proposed trigger's turns go into the conversation it was "
                                 "proposed in")
    key = None
    try:
        conversation_id = _own_conversation(session, project_id, body.conversation_id)
        kept.check_starts(session, conversation_id)
        trigger = Trigger(
            project_id=project_id, conversation_id=conversation_id,
            name=kept.check_name(body.name), kind=body.kind,
            config=kept.check_config(body.kind, body.config),
            message=kept.check_message(body.message),
            permissions=kept.check_leave(session, conversation_id, body.permissions),
            budget=body.budget.model_dump(), catch_up=body.catch_up, enabled=body.enabled,
            ends=kept.check_ends(body.ends, _today(request)), run_unchanged=body.run_unchanged,
        )
        if body.kind == "webhook":
            # Shown in this answer and never again: only its digest is kept.
            key, trigger.key_hash = kept.new_key()
        session.add(trigger)
        session.flush()
        kept.record_created(session, trigger)
        if body.kind == "files":
            # Before it is kept: a pattern that names too much makes no trigger.
            kept.listing(session.get_one(Project, project_id).root_path, trigger.config["glob"])
    except kept.Invalid as exc:
        raise HTTPException(422, str(exc)) from None
    except kept.TooMany as exc:
        raise HTTPException(422, str(exc)) from None
    if proposal is not None:
        proposal.status, proposal.trigger_id = "approved", trigger.id
    session.commit()
    _watch(request, trigger)
    request.app.state.triggers.announce(project_id)
    return {**kept.out(session, trigger), "key": key}


@router.get("/conversations/{cid}/trigger-proposals", response_model=list[TriggerProposalOut])
async def read_proposals(cid: str, session: Session = Depends(get_session)):
    """The triggers this chat's agents proposed, oldest first, decided or not (slice 69)."""
    if session.get(Conversation, cid) is None:
        raise HTTPException(404, "conversation not found")
    return kept.proposals_of(session, cid)


@router.post(
    "/trigger-proposals/{proposal_id}/approve", response_model=TriggerOut, status_code=201,
    dependencies=[Depends(require_own_origin)],
)
async def approve_proposal(
    proposal_id: str, request: Request, session: Session = Depends(get_session)
):
    """The user's Approve: the trigger is made as proposed, with the safest leave - it reads
    only, opens no sub-agent, has the usual budget. Anything more is the user's, in the form."""
    proposal = _proposal(session, proposal_id)
    project_id = session.get_one(Conversation, proposal.conversation_id).project_id
    if project_id is None:
        raise HTTPException(409, "this chat has no folder now: a trigger needs a project")
    # (Its permissions and budget left out: TriggerIn's own, the safest.)
    return _create(project_id, TriggerIn.model_validate({
        "name": proposal.name, "kind": proposal.kind, "conversation_id": proposal.conversation_id,
        "message": proposal.message, "config": proposal.config, "ends": proposal.ends,
        "proposal_id": proposal.id,
    }), request, session)


@router.post(
    "/trigger-proposals/{proposal_id}/reject", response_model=TriggerProposalOut,
    dependencies=[Depends(require_own_origin)],
)
async def reject_proposal(
    proposal_id: str, request: Request, session: Session = Depends(get_session)
):
    proposal = _proposal(session, proposal_id)
    proposal.status = "rejected"
    session.commit()
    project_id = session.get_one(Conversation, proposal.conversation_id).project_id
    if project_id is not None:
        request.app.state.triggers.announce(project_id)
    return kept.proposal_out(proposal)


@router.get("/triggers/paused", response_model=TriggersPaused)
async def read_paused(request: Request):
    return {"paused": request.app.state.triggers.paused()}


@router.put(
    "/triggers/paused", response_model=TriggersPaused,
    dependencies=[Depends(require_own_origin)],
)
async def set_paused(body: TriggersPaused, request: Request):
    """Pause every trigger of every project at once, or let them go on. Pausing also
    stops the unattended turns that are running."""
    request.app.state.triggers.pause(body.paused)
    return {"paused": request.app.state.triggers.paused()}


@router.get("/triggers/{trigger_id}", response_model=TriggerOut)
async def read_trigger(trigger_id: str, session: Session = Depends(get_session)):
    return kept.out(session, _trigger(session, trigger_id))


@router.patch(
    "/triggers/{trigger_id}", response_model=TriggerOut,
    dependencies=[Depends(require_own_origin)],
)
async def change_trigger(  # noqa: C901
    trigger_id: str, body: TriggerPatch, request: Request,
    session: Session = Depends(get_session),
):
    trigger = _trigger(session, trigger_id)
    again = False  # its times, or the files it starts from, are taken anew
    # How it stands now: whatever differs afterwards is written on its record.
    before, was_on = kept.standing(session, trigger), trigger.enabled
    try:
        if body.name is not None:
            trigger.name = kept.check_name(body.name)
        if body.message is not None:
            trigger.message = kept.check_message(body.message)
        if body.conversation_id is not None and body.conversation_id != trigger.conversation_id:
            trigger.conversation_id = _own_conversation(
                session, trigger.project_id, body.conversation_id)
            kept.check_starts(session, trigger.conversation_id)
            # Another conversation has another allow list: no rule of the first one's
            # stays ticked, and no host picked from it. (What is ticked for the new one
            # comes with `permissions`.)
            trigger.permissions = {
                **{key: value for key, value in trigger.permissions.items() if key != "hosts"},
                "commands": [],
            }
        if body.config is not None:
            config = kept.check_config(trigger.kind, body.config)
            again = again or config != trigger.config
            trigger.config = config
        if body.permissions is not None:
            trigger.permissions = kept.check_leave(
                session, trigger.conversation_id, body.permissions)
        if body.budget is not None:
            trigger.budget = body.budget.model_dump()
        if body.catch_up is not None:
            trigger.catch_up = body.catch_up
        if body.run_unchanged is not None:
            trigger.run_unchanged = body.run_unchanged
        # (null: no end. One left as it was is not checked again: a day since past is no error.)
        if "ends" in body.model_fields_set and body.ends != trigger.ends:
            trigger.ends = kept.check_ends(body.ends, _today(request))
            trigger.ran = 0  # its runs are counted from here
        if body.enabled is not None:
            if body.enabled and not trigger.enabled:
                # Switched on again: the count of failures starts over, and so does
                # what it waits for - nothing that passed while it was off is made up -
                # and the runs counted toward its end.
                trigger.failures, trigger.off_because, again = 0, None, True
                trigger.ran = 0
                if kept.end_reached(trigger, now(), request.app.state.triggers.zone):
                    raise kept.Invalid(kept.DAY_OVER)
            elif not body.enabled:
                trigger.off_because = None  # the user's doing, not KOLONİ's
            trigger.enabled = body.enabled
        if again:
            trigger.anchor_at = trigger.next_at = None
            project = session.get(Project, trigger.project_id)
            if trigger.kind == "files" and project is not None:
                # (A trigger whose project is gone is switched off at the next look.)
                kept.listing(project.root_path, trigger.config["glob"])
    except kept.Invalid as exc:
        raise HTTPException(422, str(exc)) from None
    except kept.TooMany as exc:
        raise HTTPException(422, str(exc)) from None
    # Touched by the user - "Back to every ..." sends nothing else: its own times again (93-B2).
    request.app.state.triggers.respace(trigger, 0, now())
    kept.record_changes(session, trigger, before, was_on)
    session.commit()
    if again:
        _watch(request, trigger)
    request.app.state.triggers.announce(trigger.project_id)
    return kept.out(session, trigger)


@router.delete(
    "/triggers/{trigger_id}", status_code=204, dependencies=[Depends(require_own_origin)],
)
async def delete_trigger(
    trigger_id: str, request: Request, session: Session = Depends(get_session)
):
    """Remove a trigger and the list of its runs. The turns it started stay in their
    conversation; one that is running is stopped. What was done to it stays on the
    project's record, and that it was deleted is added to it."""
    trigger = _trigger(session, trigger_id)
    project_id = trigger.project_id
    running = list(session.scalars(select(TriggerRun.run_id).where(
        TriggerRun.trigger_id == trigger_id, TriggerRun.outcome.is_(None),
        TriggerRun.run_id.is_not(None),
    )))
    session.execute(delete(TriggerRun).where(TriggerRun.trigger_id == trigger_id))
    kept.record(session, trigger, "deleted")
    session.delete(trigger)
    session.commit()
    request.app.state.triggers.removed(trigger_id, running)
    request.app.state.triggers.announce(project_id)


@router.post(
    "/triggers/{trigger_id}/run", response_model=TriggerStartedOut, status_code=202,
    dependencies=[Depends(require_own_origin)],
)
async def run_trigger(trigger_id: str, request: Request):
    """"Run now": the trigger's turn, with the trigger's permissions and nobody asked -
    what it would do by itself, for the user to see."""
    try:
        return {"run_id": request.app.state.triggers.run_now(trigger_id)}
    except kept.Refused as exc:
        raise HTTPException(exc.status, str(exc)) from None


@router.post(
    "/triggers/{trigger_id}/key", response_model=TriggerCreatedOut,
    dependencies=[Depends(require_own_origin)],
)
async def new_key(trigger_id: str, request: Request, session: Session = Depends(get_session)):
    """A webhook's key made anew: the old address stops at once, the new one is shown this
    once (only its digest is kept). For an address that got out."""
    trigger = _trigger(session, trigger_id)
    if trigger.kind != "webhook":
        raise HTTPException(422, "only a webhook trigger has a key")
    key, trigger.key_hash = kept.new_key()
    kept.record(session, trigger, "new key")
    session.commit()
    request.app.state.triggers.announce(trigger.project_id)
    return {**kept.out(session, trigger), "key": key}


@router.post(
    "/hooks/{key}", response_model=TriggerStartedOut, status_code=202,
    dependencies=[Depends(require_origin)],
)
async def webhook(key: str, request: Request):
    """Start a webhook trigger's turn. From this machine only; whoever does not have the
    key is told nothing but "not found". The body is handed to the agent as data."""
    if request.client is None or request.client.host not in THIS_MACHINE:
        raise HTTPException(403, "only from this machine")
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > kept.MAX_BODY_BYTES:
            break
    text = body.decode("utf-8", errors="replace")
    try:
        return {"run_id": request.app.state.triggers.hook(key, text)}
    except kept.Refused as exc:
        raise HTTPException(exc.status, str(exc)) from None
