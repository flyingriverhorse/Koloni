"""ORM row → JSON dict. API responses and event payloads share these shapes."""

from pathlib import PurePath

from sqlalchemy import select
from sqlalchemy.orm import object_session

from app.commands import SEARCHES_FOLDER, danger, harms, suggest_prefix, with_cwd
from app.db.models import (
    FOLLOWED,
    Agent,
    AllowedCommand,
    AllowedWeb,
    Attachment,
    ChannelMessage,
    Command,
    Conversation,
    FileChange,
    Merge,
    Message,
    Question,
    Role,
    Run,
    ToolCall,
    Topic,
    WebRequest,
    lead_work_of,
    settings_of,
)
from app.schemas import (
    AgentOut,
    AllowedCommandOut,
    AllowedWebOut,
    AttachmentOut,
    ChannelMessageOut,
    CommandOut,
    ConversationOut,
    FileChangeOut,
    MergeOut,
    MessageOut,
    QuestionOut,
    RoleOut,
    RunOut,
    ToolCallOut,
    TopicOut,
    WebRequestOut,
)
from app.workspace import unified_diff


def conversation_out(conversation: Conversation) -> dict:
    """With the sub-agent settings it follows, its folder's (`settings_of`), not its own."""
    out = ConversationOut.model_validate(conversation).model_dump(mode="json")
    session = object_session(conversation)
    if session is not None:
        own = settings_of(session, conversation)
        out |= {name: getattr(own, name) for name in FOLLOWED}
        out["lead_work"] = lead_work_of(session, conversation)
        out["lead_hands_code"] = out["lead_work"] == "delegates"
    return out


def tell_chats(session, bus, project_id: str) -> None:
    """Every chat of a project follows its settings (tek-ev): a page open on one shows them anew.
    shortcut: told to each chat not put away, one at a time, and not kept; a project of thousands
    of chats would want one project-wide event."""
    for chat in session.scalars(select(Conversation).where(
            Conversation.project_id == project_id, Conversation.archived_at.is_(None))):
        bus.emit_transient(chat.id, "conversation.updated", conversation_out(chat))


def run_out(run: Run) -> dict:
    return RunOut.model_validate(run).model_dump(mode="json")


def topic_out(topic: Topic) -> dict:
    return TopicOut.model_validate(topic).model_dump(mode="json")


def message_out(message: Message) -> dict:
    return MessageOut.model_validate(message).model_dump(mode="json")


def attachment_out(attachment: Attachment) -> dict:
    return AttachmentOut.model_validate(attachment).model_dump(mode="json")


def tool_call_out(call: ToolCall) -> dict:
    return ToolCallOut.model_validate(call).model_dump(mode="json")


def file_change_out(change: FileChange) -> dict:
    """A file change with its diff: three lines around each change. Its stored before/after
    text is read whole only by asking for that change (`GET /api/file-changes/{id}/diff`)."""
    diff, additions, deletions = unified_diff(
        change.before_content, change.after_content, change.path
    )
    return FileChangeOut.model_validate({
        "id": change.id,
        "run_id": change.run_id,
        "agent_id": change.agent_id,
        "origin": change.origin,
        "tool_call_id": change.tool_call_id,
        "path": change.path,
        "kind": change.kind,
        "status": change.status,
        "diff": diff,
        "additions": additions,
        "deletions": deletions,
        "created_at": change.created_at,
        "decided_at": change.decided_at,
        # (KOLONİ keeps an attached file under its id: `attachments.keep`)
        "attachment_id": PurePath(change.after_from).name if change.after_from else None,
    }).model_dump(mode="json")


def command_out(command: Command, live_output: str | None = None, held: bool = False) -> dict:
    """A command record; `live_output` replaces the stored output while it is running.
    `held`: its search reaches a secret file of its folder (`search_reason`), as the caller found
    (B-44, B-316) - not said unlooked."""
    return CommandOut.model_validate({
        "id": command.id,
        "run_id": command.run_id,
        "agent_id": command.agent_id,
        "origin": command.origin,
        "tool_call_id": command.tool_call_id,
        "command": command.command,
        "cwd": command.cwd,
        "location": command.location,
        "image": command.image,
        "status": command.status,
        "exit_code": command.exit_code,
        "output": command.output if live_output is None else live_output,
        "output_truncated": command.output_truncated,
        "timeout_seconds": command.timeout_seconds,
        "suggested_prefix": "" if command.keep_running or command.web_off
        else suggest_prefix(command.command),
        "web_off": command.web_off,
        # The card's reason, a send-off's too (R118: `danger` alone left a push's empty), and
        # one its call was given (R125: a branch switch, a copy's link - `why_asked`).
        # (Said on its card alone, while it waits: so a live event and a reload say the same.)
        "danger": harms(with_cwd(command.command, command.cwd)) or _why_asked(command)
        or (SEARCHES_FOLDER if held and command.status == "proposed" else ""),
        "keep_running": command.keep_running,
        "preview_url": command.preview_url,
        "created_at": command.created_at,
        "started_at": command.started_at,
        "ended_at": command.ended_at,
    }).model_dump(mode="json")


def _why_asked(command: Command) -> str:
    """The reason its tool call's card was given (`ToolCall.why_asked`), where the row is still
    in a session; "" for none. (Its call is in the session's identity map in a snapshot.)"""
    session = object_session(command)
    call = session.get(ToolCall, command.tool_call_id) if session and command.tool_call_id else None
    return (call.why_asked or "") if call else ""


def allowed_command_out(rule: AllowedCommand) -> dict:
    return AllowedCommandOut.model_validate({
        "id": rule.id, "conversation_id": rule.conversation_id, "prefix": rule.prefix,
        "danger": danger(rule.prefix), "created_at": rule.created_at,
    }).model_dump(mode="json")


def web_request_out(asked: WebRequest) -> dict:
    return WebRequestOut.model_validate(asked).model_dump(mode="json")


def allowed_web_out(rule: AllowedWeb) -> dict:
    return AllowedWebOut.model_validate(rule).model_dump(mode="json")


def command_event(command: Command) -> dict:
    """A command for an event payload: everything but output that was streamed.

    The output streams as command.output chunks and is stored once on the record;
    repeating up to 1 MiB of it in every stored event would double it.
    """
    payload = command_out(command)
    # A command that never started streamed nothing: its "output" is the reason, and
    # this event is the only way a connected client learns it.
    if command.status != "failed_to_start":
        del payload["output"]
    return payload


def agent_out(agent: Agent) -> dict:
    return AgentOut.model_validate(agent).model_dump(mode="json", by_alias=True)


def merge_out(merge: Merge) -> dict:
    return MergeOut.model_validate(merge).model_dump(mode="json")


def channel_message_out(message: ChannelMessage) -> dict:
    return ChannelMessageOut.model_validate(message).model_dump(mode="json")


def role_out(role: Role) -> dict:
    return RoleOut.model_validate(role).model_dump(mode="json")


def question_out(question: Question) -> dict:
    return QuestionOut.model_validate(question).model_dump(mode="json")


def discussion_out(session, discussion) -> dict:
    """A discussion with its members, in the order they speak."""
    from sqlalchemy import select

    from app.db.models import DiscussionMember
    from app.schemas import DiscussionOut

    members = session.scalars(
        select(DiscussionMember)
        .where(DiscussionMember.discussion_id == discussion.id)
        .order_by(DiscussionMember.position)
    ).all()
    return DiscussionOut.model_validate({
        **{column.name: getattr(discussion, column.name)
           for column in discussion.__table__.columns},
        "members": [
            {"agent_id": m.agent_id, "status": m.status, "opened_here": m.opened_here}
            for m in members
        ],
    }).model_dump(mode="json")


def discussion_post_out(post) -> dict:
    from app.schemas import DiscussionPostOut

    return DiscussionPostOut.model_validate(post).model_dump(mode="json")


def room_spent(session, room) -> dict:
    """What a room has used of its budget: the posts its members made, the tokens counted
    while it ran (`Room.tokens`, its members' and its follower's: `_count_tokens`; a model
    that reports nothing adds nothing), and the minutes its clock has counted - up to this
    moment, while it is counting. Tokens no model reported are not known: None, not nothing."""
    from sqlalchemy import func, select

    from app.db.models import RoomPost, now
    from app.room import POST_TYPES

    seconds = room.seconds + (
        (now() - room.clock_since).total_seconds() if room.clock_since else 0.0)
    return {
        "posts": session.scalar(select(func.count()).select_from(RoomPost).where(
            RoomPost.room_id == room.id, RoomPost.agent_id.is_not(None),
            RoomPost.type.in_(POST_TYPES))) or 0,
        "tokens": room.tokens,
        "minutes": round(max(0.0, seconds) / 60, 1),
    }


def room_out(session, room) -> dict:
    """A room with its members, in the order the user named them, and what it has spent."""
    from sqlalchemy import select

    from app.db.models import RoomItem, RoomMember, RoomPost
    from app.room import RUNNING, summary
    from app.schemas import RoomOut

    members = session.scalars(
        select(RoomMember).where(RoomMember.room_id == room.id).order_by(RoomMember.position)
    ).all()
    # What it came to: said once it is over - not read again with every post of a live room.
    done = [] if room.status in RUNNING else session.scalars(
        select(RoomItem.result).where(RoomItem.room_id == room.id, RoomItem.status == "done")
        .order_by(RoomItem.number)
    ).all()
    # (K-oda-lead: the sentence its opener ended it with, where it did)
    ended = None if room.status in RUNNING else session.scalar(
        select(RoomPost.text).where(RoomPost.room_id == room.id, RoomPost.type == "ended"))
    return RoomOut.model_validate({
        "id": room.id, "run_id": room.run_id, "goal": room.goal, "agent_id": room.agent_id,
        "status": room.status,
        "outcome": room.outcome, "why": room.why, "created_at": room.created_at,
        "ended_at": room.ended_at,
        "budget": {
            "posts": room.max_posts, "tokens": room.max_tokens, "minutes": room.max_minutes,
        },
        "spent": room_spent(session, room),
        "summary": ended or summary(done),
        "paused": room.paused,
        "lead_follows": room.lead_follows,
        "members": [
            {"agent_id": m.agent_id, "role": m.role, "status": m.status} for m in members
        ],
    }).model_dump(mode="json")


def room_item_out(item) -> dict:
    from app.schemas import RoomItemOut

    return RoomItemOut.model_validate(item).model_dump(mode="json")


def room_post_out(post) -> dict:
    from app.schemas import RoomPostOut

    return RoomPostOut.model_validate(post).model_dump(mode="json")


def board_post_out(post, read_by=()) -> dict:
    """A note on the shared notebook, with the agents that were handed it."""
    from app.schemas import BoardPostOut

    return BoardPostOut.model_validate({
        **{column.name: getattr(post, column.name) for column in post.__table__.columns},
        "read_by": list(read_by),
    }).model_dump(mode="json")

