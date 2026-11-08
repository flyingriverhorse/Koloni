import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/conversations", tags=["events"])

PING_SECONDS = 15


def frame(event_id: int | None, type: str, payload: dict) -> str:
    head = f"id: {event_id}\n" if event_id is not None else ""
    return f"{head}event: {type}\ndata: {json.dumps(payload)}\n\n"


@router.get("/{conversation_id}/events")
async def stream_events(
    conversation_id: str, request: Request, after: int | None = None, once: bool = False
):
    """Server-sent events for one conversation.

    Replays persisted events after the cursor, then stays open. `once` closes the
    stream after the replay (for tests and debugging).
    """
    bus = request.app.state.bus
    runner = request.app.state.runner
    cursor = after if after is not None else int(request.headers.get("last-event-id") or 0)

    async def generate():
        nonlocal cursor
        async with bus.subscribe(conversation_id) as sub:
            # Deltas are not persisted, so a reconnecting client is sent the full text
            # of anything still streaming. It is captured at subscribe time (deltas from
            # here on arrive through the subscription) and sent after the replay, once
            # the client knows the message it belongs to.
            live = runner.live_messages(conversation_id)
            outputs = runner.commands.live_outputs(conversation_id)
            shown = runner.live_agents(conversation_id)
            for event_id, type, payload in bus.replay(conversation_id, cursor):
                cursor = event_id
                yield frame(event_id, type, payload)
            for message_id, content in live.items():
                yield frame(None, "message.sync", {"message_id": message_id, "content": content})
            for command_id, output in outputs.items():
                yield frame(None, "command.sync", {"command_id": command_id, "output": output})
            for one in shown:  # (89j: what agents' CLIs last said of their context and plan)
                yield frame(None, "agent.live", one)
            if once:
                return
            while True:
                try:
                    event_id, type, payload = await asyncio.wait_for(
                        anext(sub), timeout=PING_SECONDS
                    )
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                if event_id is not None:
                    if event_id <= cursor:
                        continue
                    cursor = event_id
                yield frame(event_id, type, payload)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
