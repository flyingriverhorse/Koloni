"""C1 (0.1.11): message_agent's `how`.

- "reply" (the default): as ever - the sender waits for a turn of the receiver's on it, or leaves
  a note for one at work, or writes it into the running turn of a CLI it works for.
- "leave": the sender goes on. A receiver not at work takes it up now, in a turn of its own; one
  at work is handed it at its next step - and where its work ends before it read it, it takes it
  up in a turn of its own then (a real queue). Its reply comes to the sender as a note, as a
  background agent's report does.
- "now": into the running work of one at work - a CLI's turn through its door, C2's outcome told
  (`_steer_message`); else as "leave".

Offered only where the sender is woken by what comes later: the Orchestrator of an API model, as
`spawn_agent`'s background (`_background_offered`). Elsewhere it is sent as a reply, and said so.
Reach is `_reachable`'s alone: `how` only picks among what it lets (a CLI at work with no door -
agy - stays out of reach; one not at work is "leave" for "now" too). Every end of a left message
is told its sender: read, its reply, or why it was not taken up (C2's words).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import replace
from typing import TYPE_CHECKING

from app.agent.ctx import Ctx
from app.db.models import Agent, Message
from app.delivery import TAKEN, UNKNOWN
from app.team import quoted
from app.tools import ToolError

if TYPE_CHECKING:
    from app.agent import AgentRunner

log = logging.getLogger(__name__)

HOWS = ("reply", "leave", "now")
HOW_PROPERTY = {
    "type": "string",
    "enum": list(HOWS),
    "description": (
        'Optional. "reply" (the default): you wait for its reply. "leave": you go on at once - '
        "one not at work takes it up now in a turn of its own, one at work is handed it at its "
        "next step (or takes it up once its work ends); its reply comes to you as a note. "
        '"now": into the running work of one at work (a CLI\'s turn too); else as "leave".'
    ),
}
# (What a left message's receiver is doing: at work, it reads it at its next step.)
AT_WORK = ("queued", "running", "blocked", "waiting")
LOOK = 0.5  # seconds between looks at whether it was read, or its work ended

LEFT_NOW = (
    "left: {name} takes it up now in a turn of its own; its reply comes to you as a note. Go on "
    "with your own work."
)
LEFT_AT_WORK = (
    "left: {name} is at work and is handed this at its next step; if its work ends first, it "
    "takes it up in a turn of its own, and its reply comes to you as a note. Go on with your own "
    "work."
)
AS_REPLY = 'how "{how}" is only the Orchestrator\'s, of an API model: sent as "reply". '
NOT_TAKEN_UP = "KOLONİ: your message ({words}) did not reach {name}: {why}; it is not sent again."


def how_of(runner: AgentRunner, ctx: Ctx, how: object) -> tuple[str, str]:
    """`how` as it is taken, and what the sender is told of it: "reply" where it is not offered."""
    if how is None or how == "reply":
        return "reply", ""
    if how not in HOWS:
        raise ToolError('how is one of "reply", "leave", "now"')
    if not runner._background_offered(ctx):
        return "reply", AS_REPLY.format(how=how)
    return str(how), ""


async def left(
    runner: AgentRunner,
    ctx: Ctx,
    call_id: str,
    target: Ctx,
    kind: str,
    body: str,
    files: list,
    how: str,
) -> tuple[str, str]:
    """`_message` for "leave" and "now", past its reach and its limit: on record as a note for
    the receiver, and what comes of it its sender's later (`_taken_up`, in `_answers_out`: its
    turn is not over before every one is). Its note and the turn it may start each count to the
    turn's messages (`_within_limit`): room for both, or it is refused now."""
    if how == "now" and kind == "steer":  # (its CLI's turn, C2's outcome told)
        return await runner._steer_message(ctx, target, body, files)
    runner._within_limit(ctx, room=2)
    with runner._factory() as session:
        at_work = session.get_one(Agent, target.agent_id).status in AT_WORK
    runner._hand_files(ctx, files, target.agent_id)
    note = runner._send(ctx, target, body, delivered=False)
    runner._channel(ctx, ctx.agent_id, target.agent_id, "note", body)
    later = asyncio.ensure_future(_taken_up(runner, ctx, call_id, target, body, note))
    later.add_done_callback(_retrieved)
    runner._answers_out.setdefault(ctx.agent_id, []).append(later)
    return "succeeded", (LEFT_AT_WORK if at_work else LEFT_NOW).format(name=target.name)


def _retrieved(done: asyncio.Future) -> None:
    if not done.cancelled() and done.exception() is not None:
        log.warning("a left message's end was not told: %r", done.exception())


async def _taken_up(
    runner: AgentRunner, ctx: Ctx, call_id: str, target: Ctx, body: str, note: str
) -> tuple[str, str, str]:
    """A left message's life: read at its receiver's next step while it works (taken: told by
    `_nudge`, it wakes nobody); else, once its work is over, a turn of its own on it - the sender
    not waiting, in the receiver's turn lock and its place (`_reply_turn`, `_working`) - whose
    reply is the sender's note. (who, what it is told, a note's id), as `team_requests.woken`
    reads it; every end told its sender.
    shortcut: looked at every LOOK seconds, in memory - a restart loses the wait (the note stays
    on record, unread); wake it at its receiver's end if the looks are felt."""
    started = False
    try:
        while True:
            if await _read_while_at_work(runner, target, note):
                runner._message_went(ctx.agent_id, target, body, note, TAKEN)
                return target.name, "", note
            async with runner._turn_of(target.agent_id):
                if _read(runner, note):
                    continue  # (handed meanwhile, in another turn of its: taken)
                kind = next(
                    (k for one, k in runner._reachable(ctx) if one.agent_id == target.agent_id),
                    None,
                )
                if kind in ("note", "steer"):
                    continue  # (at work again: handed at its next step)
                if kind is None:
                    return _not_taken_up(runner, ctx, target, body, _why_not(runner, target))
                started = True
                status, result = await _turn(runner, ctx, target, kind, body, note)
            if status == "succeeded":
                await runner._add_to_guide(ctx, target, call_id, result)
            if not runner._is_above(target.agent_id, ctx):
                status, result = runner._reply_read(ctx, call_id, status, result)
            sender = runner._ctxs.get(ctx.agent_id, ctx)
            reply = runner._send(replace(ctx, agent_id=target.agent_id), sender, result, False)
            return target.name, result, reply
    except asyncio.CancelledError:
        # (The turn stopped, or its sender's work ended: on its record, never dropped unsaid.)
        with contextlib.suppress(Exception):
            if started:
                runner._message_went(ctx.agent_id, target, body, note, UNKNOWN)
            elif not _read(runner, note):
                _not_taken_up(runner, ctx, target, body, "the turn ended first")
        raise
    except Exception as exc:
        log.warning("agent %s: a message left for %s failed: %r", ctx.agent_id, target.name, exc)
        return _not_taken_up(runner, ctx, target, body, "an internal error")


async def _read_while_at_work(runner: AgentRunner, target: Ctx, note: str) -> bool:
    """Whether its receiver was handed the note - looked at while it is at work; False once its
    work is over (or it waits for nothing: one not at work)."""
    while True:
        with runner._factory() as session:
            status = session.get_one(Agent, target.agent_id).status
        if _read(runner, note):
            return True
        if status not in AT_WORK:
            return False
        await asyncio.sleep(LOOK)


def _why_not(runner: AgentRunner, target: Ctx) -> str:
    with runner._factory() as session:
        stopped = session.get_one(Agent, target.agent_id).status == "cancelled"
    return "it was stopped" if stopped else runner._message_why_not(target)


def _read(runner: AgentRunner, note: str) -> bool:
    with runner._factory() as session:
        return session.get_one(Message, note).delivered_at is not None


async def _turn(
    runner: AgentRunner, ctx: Ctx, target: Ctx, kind: str, body: str, note: str
) -> tuple[str, str]:
    """Its turn on the note, as `_message_turn`'s but its sender going on: a task of its own,
    on record as one its opener did not wait for (`_later_work`: Stop ends it, the turn's end
    waits for it), its sender's place lent and taken back once it is over (`_lend_slot`)."""
    work = asyncio.ensure_future(runner._reply_turn(ctx, target, kind, body, left=note))
    runner._later_work.setdefault(ctx.run_id, []).append(
        (ctx.agent_id, target.agent_id, ctx.cid, work)
    )
    runner._went_on.add(target.agent_id)  # (not its sender's to close: `_settle_session`)
    runner._lend_slot(ctx)
    try:
        return await work
    finally:
        if work.done():
            await runner._take_slot_back(runner._ctxs.get(ctx.agent_id, ctx))


def _not_taken_up(
    runner: AgentRunner, ctx: Ctx, target: Ctx, body: str, why: str
) -> tuple[str, str, str]:
    """A left message that was never taken up, told its sender - as a note, read as it comes."""
    said = NOT_TAKEN_UP.format(words=quoted(body[:200]), name=target.name, why=why)
    sender = runner._ctxs.get(ctx.agent_id, ctx)
    return target.name, said, runner._send(sender, sender, said, delivered=False, koloni=True)
