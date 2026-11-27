import asyncio
from collections import defaultdict

from sqlalchemy import func, select

from app.db.models import Event

# (event id, type, payload); the id is None for transient events.
Item = tuple[int | None, str, dict]


class Subscription:
    def __init__(
        self, bus: "EventBus", conversation_id: str, client: str | None = None, looking=True
    ):
        self._bus = bus
        self._conversation_id = conversation_id
        self.queue: asyncio.Queue[Item] = asyncio.Queue()
        # The page it is (its own id), and whether it has the chat on screen now (`look`).
        self.client, self.looking = client, looking

    async def __aenter__(self) -> "Subscription":
        self._bus._subs[self._conversation_id].add(self)
        return self

    async def __aexit__(self, *exc) -> None:
        self._bus._subs[self._conversation_id].discard(self)

    def __aiter__(self) -> "Subscription":
        return self

    async def __anext__(self) -> Item:
        return await self.queue.get()


class EventBus:
    """Persists events per conversation and fans them out to live subscribers.

    emit and emit_transient must be called from the event-loop thread.
    """

    def __init__(self, session_factory):
        self._factory = session_factory
        self._subs: dict[str, set[Subscription]] = defaultdict(set)

    def emit(self, conversation_id: str, run_id: str | None, type: str, payload: dict) -> int:
        with self._factory() as session:
            event = Event(
                conversation_id=conversation_id, run_id=run_id, type=type, payload=payload
            )
            session.add(event)
            session.commit()
            event_id = event.id
        self._fan_out(conversation_id, (event_id, type, payload))
        return event_id

    def emit_transient(self, conversation_id: str, type: str, payload: dict) -> None:
        self._fan_out(conversation_id, (None, type, payload))

    def _fan_out(self, conversation_id: str, item: Item) -> None:
        for sub in list(self._subs.get(conversation_id, ())):
            sub.queue.put_nowait(item)

    def watching(self, conversation_id: str) -> bool:
        """Whether the chat is open somewhere: a transient event reaches somebody."""
        return bool(self._subs.get(conversation_id))

    def looking(self, conversation_id: str) -> bool:
        """herdr's rule (28 Nov 2026): whether somebody looks at the chat now - a page that has it
        on screen, its tab seen and its window not known to be elsewhere (`look`). A page that
        never said counts as looking, as before; a hidden tab, or another page of KOLONİ's open
        over it, does not."""
        return any(getattr(sub, "looking", True) for sub in self._subs.get(conversation_id, ()))

    def look(self, conversation_id: str, client: str, looking: bool) -> bool:
        """What the page `client` says now of the chat: on screen or not. Whether a page of that
        id has the chat open - one that has not is not kept (it says it again as it opens)."""
        mine = [s for s in self._subs.get(conversation_id, ()) if getattr(s, "client", 0) == client]
        for sub in mine:
            sub.looking = looking
        return bool(mine)

    def subscribe(
        self, conversation_id: str, client: str | None = None, looking: bool = True
    ) -> Subscription:
        return Subscription(self, conversation_id, client, looking)

    def replay(self, conversation_id: str, after: int) -> list[tuple[int, str, dict]]:
        with self._factory() as session:
            rows = session.execute(
                select(Event.id, Event.type, Event.payload)
                .where(Event.conversation_id == conversation_id, Event.id > after)
                .order_by(Event.id)
            ).all()
        return [(row.id, row.type, row.payload) for row in rows]

    def last_id(self, conversation_id: str) -> int:
        with self._factory() as session:
            newest = session.scalar(
                select(func.max(Event.id)).where(Event.conversation_id == conversation_id)
            )
        return newest or 0
