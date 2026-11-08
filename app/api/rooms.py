from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import room as rooms
from app import topics
from app.agent import TERMINAL
from app.api.deps import get_session, require_origin, require_own_origin
from app.api.usage import over_budget
from app.db.models import Conversation, Message, Project, Room, RoomMember, Run, now
from app.model_client import OwnStop
from app.schemas import RoomIn, RoomMoreIn, RoomOpenedOut, RoomOut, RoomPostIn, RoomPostOut
from app.serialize import conversation_out, message_out, room_out, run_out, topic_out

router = APIRouter(prefix="/api", tags=["rooms"])

OVER = "this room is over"


@router.post(
    "/conversations/{conversation_id}/rooms", response_model=RoomOpenedOut, status_code=201,
    dependencies=[Depends(require_own_origin)],
)
async def open_room(
    conversation_id: str, body: RoomIn, request: Request,
    session: Session = Depends(get_session),
):
    """The user opens a room: a turn of its own, whose message is the room's goal. Its
    members are opened without the card a sub-agent may need, on the models the user
    names here - so it is theirs to open, from the app's own page."""
    conversation = session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(404, "conversation not found")
    if conversation.project_id is None:
        raise HTTPException(409, "a room works in a copy of the chat's folder: this chat has "
                                 "no folder")
    goal = body.goal.strip()
    if not goal:
        raise HTTPException(422, "the goal is empty")
    if session.scalar(
        select(Run.id)
        .where(Run.conversation_id == conversation_id, Run.status.not_in(TERMINAL)).limit(1)
    ):
        raise HTTPException(
            409, "This conversation is at work. A room is a turn of its own: open it when "
            "the turn before it is over.")
    # (Its folder's sub-agent settings are the chat's: `settings_of`.)
    project = session.get_one(Project, conversation.project_id)
    if len(body.members) > project.spawn_max_agents:
        raise HTTPException(
            422, f"this conversation lets a turn open {project.spawn_max_agents} "
            "sub-agent(s) at most")
    members, spends = [], []
    for position, asked in enumerate(body.members):
        try:
            role, _tools, provider, _model, _moved = rooms.member_model(
                session, conversation, asked.role, asked.provider, asked.model, by_user=True)
        except (ValueError, OwnStop) as exc:
            raise HTTPException(422, str(exc)) from None
        spends.append(provider)
        members.append(RoomMember(
            position=position, role=role.name,
            provider_id=provider.id if asked.provider else None,
            model_id=(asked.model or "").strip() or None if asked.provider else None,
        ))
    # A room's members are models that spend: held back as a message is, and each held to
    # its provider's limit (81c). (Every room is opened from the app's own page: going on
    # over it is the user's word.)
    over = (over_budget(session, project, conversation)
            or over_budget(session, project, spends=spends))
    if over and not body.over_budget:
        raise HTTPException(409, f"this project is {over}: say to go on over it")
    # What it may spend: the project's, but for what the user says here.
    said = body.budget.model_fields_set if body.budget else set()
    limits = {
        key: getattr(body.budget, key) if key in said else getattr(project, f"room_{key}")
        for key in ("posts", "tokens", "minutes")
    }
    first = session.scalar(
        select(Message.id).where(Message.conversation_id == conversation_id).limit(1)
    ) is None
    topic, new = topics.for_message(session, conversation_id, goal, None, False)
    run = Run(
        conversation_id=conversation_id, topic_id=topic.id, status="running", started_at=now())
    session.add(run)
    session.flush()
    message = Message(conversation_id=conversation_id, run_id=run.id, role="user", content=goal)
    room = Room(
        run_id=run.id, goal=goal, max_posts=limits["posts"], max_tokens=limits["tokens"],
        max_minutes=limits["minutes"],
    )
    session.add_all([message, room])
    session.flush()
    for member in members:
        member.room_id = room.id
    session.add_all(members)
    if first:
        conversation.title = topics.title_from(goal) or conversation.title
    conversation.archived_at = None  # the user's own goal, as their message: it is back
    conversation.updated_at = now()
    session.commit()

    bus = request.app.state.bus
    run_payload, room_payload = run_out(run), room_out(session, room)
    bus.emit(conversation_id, run.id, "run.started", run_payload)
    if new:
        bus.emit(conversation_id, None, "topic.created", topic_out(topic))
    bus.emit(conversation_id, run.id, "message.created", message_out(message))
    bus.emit(conversation_id, run.id, "room.created", room_payload)
    bus.emit(conversation_id, None, "conversation.updated", conversation_out(conversation))
    request.app.state.runner.start(run.id)
    return {"run": run_payload, "room": room_payload}


def _room(session: Session, room_id: str) -> Room:
    room = session.get(Room, room_id)
    if room is None:
        raise HTTPException(404, "room not found")
    return room


@router.post(
    "/rooms/{room_id}/posts", response_model=RoomPostOut, status_code=201,
    dependencies=[Depends(require_own_origin)],
)
async def say(
    room_id: str, body: RoomPostIn, request: Request, session: Session = Depends(get_session)
):
    """The user speaks in the room; every member reads it at its next step."""
    _room(session, room_id)
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "there is nothing to say")
    post = request.app.state.runner.say_in_room(room_id, text)
    if post is None:
        raise HTTPException(409, OVER)
    return post


@router.post(
    "/rooms/{room_id}/end", response_model=RoomOut, dependencies=[Depends(require_origin)]
)
async def end(room_id: str, request: Request, session: Session = Depends(get_session)):
    """End the room now: its members still at work are stopped, and the turn's lead is
    given what came of it so far."""
    room = _room(session, room_id)
    if not request.app.state.runner.end_room(room_id):
        raise HTTPException(409, OVER)
    return room_out(session, room)


@router.post(
    "/rooms/{room_id}/pause", response_model=RoomOut,
    # (The user's, from the app's own page: not a member's command holding up its own room.)
    dependencies=[Depends(require_own_origin)],
)
async def pause(room_id: str, request: Request, session: Session = Depends(get_session)):
    """Pause the room (29c): its members finish the step at hand, then post nothing and ask
    no model, and its clock stands, until Resume. It can still be read and ended."""
    _room(session, room_id)
    room = request.app.state.runner.pause_room(room_id, True)
    if room is None:
        raise HTTPException(409, OVER)
    return room


@router.post(
    "/rooms/{room_id}/resume", response_model=RoomOut,
    dependencies=[Depends(require_own_origin)],
)
async def resume(room_id: str, request: Request, session: Session = Depends(get_session)):
    """Resume a paused room: its members go on where they stopped. Leave to spend again: the
    user's to give, from the app's own page."""
    _room(session, room_id)
    room = request.app.state.runner.pause_room(room_id, False)
    if room is None:
        raise HTTPException(409, OVER)
    return room


@router.post(
    "/rooms/{room_id}/follow", response_model=RoomOut,
    # (The user's, from the app's own page: the Lead's steps spend the room's budget.)
    dependencies=[Depends(require_own_origin)],
)
async def follow(room_id: str, request: Request, session: Session = Depends(get_session)):
    """K-oda-izle: let the turn's Lead follow the room the user opened, as it follows one it
    opened itself: it is given what is said, and may post, ask one more in or end it."""
    return _follow(session, room_id, request, True)


@router.post(
    "/rooms/{room_id}/unfollow", response_model=RoomOut,
    dependencies=[Depends(require_own_origin)],
)
async def unfollow(room_id: str, request: Request, session: Session = Depends(get_session)):
    """The Lead follows the room no further: it waits for its record, as before (its step at
    hand may finish)."""
    return _follow(session, room_id, request, False)


def _follow(session: Session, room_id: str, request: Request, on: bool) -> dict:
    _room(session, room_id)
    try:
        room = request.app.state.runner.follow_room(room_id, on)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    if room is None:
        raise HTTPException(409, OVER)
    return room


@router.post(
    "/rooms/{room_id}/more", response_model=RoomOut,
    dependencies=[Depends(require_own_origin)],
)
async def more(
    room_id: str, body: RoomMoreIn, request: Request, session: Session = Depends(get_session)
):
    """Add to a running room's budget. Leave to spend more: the user's to give, from the
    app's own page."""
    _room(session, room_id)
    added = body.model_dump(exclude_none=True)
    if not added:
        raise HTTPException(422, "say what to add: posts, tokens or minutes")
    room = request.app.state.runner.more_for_room(room_id, added)
    if room is None:
        raise HTTPException(409, OVER)
    return room
