"""herdr's rule (28 Nov 2026): a desktop notice - something waits for you, a background agent ended -
is shown only where nobody looks at the chat: a page that has it on screen, its tab seen and its
window not elsewhere. A hidden tab, or another page of KOLONİ's over the chat, is nobody looking."""

import asyncio

import pytest

import app.web
from app.events import EventBus
from tests.conftest import Gate
from tests.test_background_spawn import bg
from tests.test_chat_flow import text
from tests.test_done_notice import begin
from tests.test_spawn import step

OWN = {"Origin": "http://127.0.0.1:8790"}


def opened(bus, cid, client, looking=True):
    """A page's stream of the chat, as `stream_events` holds it."""
    sub = bus.subscribe(cid, client, looking)
    bus._subs[cid].add(sub)
    return sub


def test_looking_is_a_page_that_has_the_chat_on_screen_or_says_nothing():
    bus = EventBus(session_factory=None)
    assert not bus.looking("c")  # (nobody has it open)
    opened(bus, "c", "tab-1", looking=False)
    assert bus.watching("c") and not bus.looking("c")  # (open, hidden: nobody looks)
    opened(bus, "c", "tab-2")
    assert bus.looking("c")  # (one seen is enough)
    assert bus.look("c", "tab-2", False) and not bus.looking("c")
    assert not bus.look("c", "tab-9", True)  # (a page that has it not open is not kept)
    assert not bus.looking("c")
    bus._subs["c"].add(object())  # (a stream that never said: looking, as before)
    assert bus.looking("c")


def test_a_page_says_whether_it_looks_at_its_chat_only_from_kolonis_own_page(make_client):
    client, _model = make_client([])
    bus = client.app.state.bus
    sub = opened(bus, "c1", "tab-1")
    path = "/api/conversations/c1/looking"
    assert client.post(path, json={"client": "tab-1", "looking": False}).status_code == 403
    said = client.post(path, json={"client": "tab-1", "looking": False}, headers=OWN)
    assert said.status_code == 204 and not sub.looking and not bus.looking("c1")
    long = client.post(path, json={"client": "x" * 65, "looking": True}, headers=OWN)
    assert long.status_code == 422


@pytest.fixture
def shown(monkeypatch):
    said: list = []
    monkeypatch.setattr(app.web, "has_desktop", lambda: True)
    monkeypatch.setattr(app.web, "desktop", lambda title, said_: said.append(said_))
    return said


@pytest.mark.parametrize("looking", [True, False])
def test_a_background_agents_end_is_told_where_its_chat_is_open_but_not_looked_at(
    make_client, wait_run, project_dir, shown, looking
):
    gate = Gate()
    client, _model = make_client(
        {
            "Lead": [step(bg("Coder", "do A", "s1")), text("asked"), text("read")],
            "Coder": [gate.step(text("ok"))],
        }
    )
    _name, cid, run_id = begin(client, project_dir)
    opened(client.app.state.bus, cid, "tab-1", looking)  # (open in a tab, seen or hidden)
    gate.release()
    wait_run(client, cid, run_id)
    for _ in range(200):  # (shown off the event loop)
        if shown or looking:
            break
        client.portal.call(asyncio.sleep, 0.01)
    assert shown == ([] if looking else ["Coder finished"])


@pytest.mark.parametrize("looking", [True, False])
def test_what_waits_for_you_is_told_only_where_nobody_looks(make_client, shown, looking):
    client, _model = make_client([])
    runner = client.app.state.runner
    opened(client.app.state.bus, "c1", "tab-1", looking)

    async def waits():
        runner._users_awaited["c1"] = [("Coder", True, asyncio.get_running_loop().create_future())]
        runner._show_waits("c1", "KOLONİ — p")
        await asyncio.gather(*runner._telling)

    client.portal.call(waits)
    assert shown == ([] if looking else ["Coder asks you a question"])
