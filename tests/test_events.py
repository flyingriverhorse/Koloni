import pytest

from app.db.models import Conversation, Project
from app.db.session import make_engine, make_session_factory, upgrade_db
from app.events import EventBus

pytestmark = pytest.mark.anyio


@pytest.fixture
def bus(tmp_path):
    db = tmp_path / "e.db"
    upgrade_db(db)
    factory = make_session_factory(make_engine(db))
    with factory() as s:
        s.add(Project(id="p", name="p", root_path=str(tmp_path)))
        s.flush()
        s.add_all([Conversation(id="c", project_id="p"), Conversation(id="other", project_id="p")])
        s.commit()
    return EventBus(factory)


async def test_emit_persists_and_replays_after_cursor(bus):
    first = bus.emit("c", None, "a", {"n": 1})
    second = bus.emit("c", None, "b", {"n": 2})
    assert second > first
    assert bus.replay("c", first) == [(second, "b", {"n": 2})]
    assert bus.last_id("c") == second


async def test_subscriber_gets_persistent_and_transient_events(bus):
    async with bus.subscribe("c") as sub:
        eid = bus.emit("c", None, "a", {})
        bus.emit_transient("c", "message.delta", {"text": "x"})
        assert await anext(sub) == (eid, "a", {})
        assert await anext(sub) == (None, "message.delta", {"text": "x"})


async def test_transient_events_are_not_replayed(bus):
    bus.emit_transient("c", "message.delta", {"text": "x"})
    assert bus.replay("c", 0) == []


async def test_events_stay_inside_their_conversation(bus):
    async with bus.subscribe("other") as sub:
        bus.emit("c", None, "a", {})
        assert sub.queue.empty()
    assert bus.replay("other", 0) == [] and bus.last_id("other") == 0


async def test_no_plain_def_endpoint_sends_events():
    """A plain `def` endpoint runs in a worker thread, where the bus's queue put does not
    wake a waiting stream: other views saw it up to 15 s late (the next ping)."""
    import importlib
    import inspect
    import pkgutil

    from fastapi.routing import APIRoute

    import app.api as api

    sync = []
    for found in pkgutil.iter_modules(api.__path__):
        router = getattr(importlib.import_module(f"app.api.{found.name}"), "router", None)
        sync += [f"{found.name}.{route.endpoint.__name__}"
                 for route in getattr(router, "routes", ())
                 if isinstance(route, APIRoute)
                 and not inspect.iscoroutinefunction(route.endpoint)
                 and any(word in inspect.getsource(route.endpoint)
                         for word in (".bus", "announce("))]
    assert sync == []


async def test_the_page_listens_for_every_event_the_server_sends():
    """The page hears only the names in sse.ts `EVENT_TYPES`: `view.shown` and `notes.offered`
    were sent and never heard. (The names written in an emit or announce call, and the notes
    offer's constant.)"""
    import re
    from pathlib import Path

    from app import project_notes

    root = Path(__file__).parent.parent
    sent = {project_notes.OFFERED}
    for source in (root / "app").rglob("*.py"):
        sent |= set(re.findall(r'(?:emit|emit_transient|announce)\((?:[^()"]|\([^()]*\))*?'
                               r'"([a-z_]+\.[a-z_]+)"', source.read_text(encoding="utf-8")))
    listened = (root / "frontend/src/api/sse.ts").read_text(encoding="utf-8")
    heard = set(re.findall(r"^  '([a-z_.]+)',$", listened.split("] as const")[0], re.M))
    assert "view.shown" in sent and sent - heard == set()
