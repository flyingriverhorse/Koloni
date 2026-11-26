"""The app's own clock: every few seconds each night that runs while its user is away (slice
106) is looked at, and each project's day is sent where its notifications go.

The clock is never read in here: `Triggers.tick(now)` is handed the time, by the app's own
loop every few seconds and by tests directly. Everything that touches the runner or the
event bus happens on the app's event loop, whichever thread asks.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import datetime, time, timedelta, tzinfo

from sqlalchemy import select

from app import away, web
from app.agent import announce
from app.db.models import AwayRun, Project, now

# The server's own log: what goes wrong at a look, with nobody there to see it.
log = logging.getLogger("uvicorn.error")

TICK_SECONDS = 5.0


def local_day(moment: datetime, zone: tzinfo | None = None):
    """The calendar day a moment falls on by the local clock."""
    return moment.astimezone(zone).date()


class Triggers:
    """The app's clock: the nights while the user is away, and the day's summary."""

    def __init__(
        self, session_factory, bus, runner, day_note: Callable, zone: tzinfo | None = None
    ):
        self._factory = session_factory
        self.bus = bus
        self.runner = runner
        # (session, project, since, runner, until) -> the day's text (`app.api.day.day_note`).
        self._day_note = day_note
        # The day's summaries on their way: held so they are not collected half sent.
        # shortcut: one still on its way when the app stops is dropped unsaid (marked sent);
        # cancel and log them at shutdown if that is ever seen.
        self._sending: set[asyncio.Task] = set()
        # Where "local" is for times of day (None: here).
        self.zone = zone
        self._loop: asyncio.AbstractEventLoop | None = None

    # --- the app's loop -----------------------------------------------------------------

    def attach(self, loop: asyncio.AbstractEventLoop | None) -> None:
        self._loop = loop

    def _on_loop(self, work: Callable):
        """Do something on the app's event loop and return what it returns: at once when
        called there, and from any other thread by handing it over and waiting."""
        if self._loop is None:
            raise RuntimeError("the app is not running: no turn can be started")
        try:
            here = asyncio.get_running_loop()
        except RuntimeError:
            here = None
        if here is self._loop:
            return work()

        async def call():
            return work()

        return asyncio.run_coroutine_threadsafe(call(), self._loop).result(60)

    async def run_forever(self) -> None:
        """Look at the clock every few seconds, for as long as the app runs."""
        while True:
            await asyncio.sleep(TICK_SECONDS)
            # One look that failed (the database busy, say) is not the last look.
            with contextlib.suppress(Exception):
                await self.look(now())
            with contextlib.suppress(Exception):  # the same: the next look tries again
                self.day_notes(now())

    def _nights(self, moment: datetime) -> None:
        """Each night that runs while its user is away (slice 106) is looked at, at each look
        of the clock: past its time it stops, a job that has worked
        too long is cut, and with no job at work the next one starts (`away.go_on`)."""
        with self._factory() as session:
            for project_id in session.scalars(
                select(AwayRun.project_id).where(AwayRun.status == "running")
            ).all():
                if away.go_on(session, project_id, self.runner, moment):
                    announce(self._factory, self.bus, project_id, "backlog.changed")

    def day_notes(self, moment: datetime) -> None:
        """Send each project's day (`app.api.day`) where its notifications go, once its
        time of day has come: once a day, counted from that day's own midnight. Each day
        is marked sent before it goes, so one that fails is not tried again every few
        seconds - nor one that could not be counted, which keeps no other project's from
        going: why is in the server's log, never the address. It goes off the clock: a
        slow address never makes the clock late. An app that comes up after the time sends
        it then, late; one that was closed all evening sends that day's the next day, once,
        counted to its own end and said to be late - the last such day only, never a
        backlog of every day it was closed."""
        day = local_day(moment, self.zone)
        yesterday = day - timedelta(days=1)
        clock = moment.astimezone(self.zone).strftime("%H:%M")

        def midnight(of):  # that day's first moment by the local clock
            at = datetime.combine(of, time())
            return at.replace(tzinfo=self.zone) if self.zone else at.astimezone()

        with self._factory() as session:
            late = session.scalars(
                select(Project).where(
                    Project.day_note_at.is_not(None), Project.day_note_sent < yesterday
                )
            ).all()
            due = session.scalars(
                select(Project).where(
                    Project.day_note_at.is_not(None),
                    Project.day_note_at <= clock,
                    (Project.day_note_sent.is_(None)) | (Project.day_note_sent != day),
                )
            ).all()
            for project, of, until in [
                *((one, yesterday, midnight(day)) for one in late),
                *((one, day, None) for one in due),
            ]:
                name, note = project.name, None
                try:
                    text = self._day_note(session, project, midnight(of), self.runner, until)
                    note = (
                        project.notify_url,
                        project.notify_format,
                        project.notify_desktop,
                        text[: web.MAX_NOTE],
                    )
                except Exception as exc:
                    session.rollback()
                    log.warning(
                        "the day's summary of %s could not be counted: %s", name, type(exc).__name__
                    )
                project.day_note_sent = of
                session.commit()
                if note:
                    sending = asyncio.create_task(self._send_note(name, *note))
                    self._sending.add(sending)
                    sending.add_done_callback(self._sending.discard)

    async def _send_note(
        self, name: str, url: str | None, form: str, on_desktop: bool, text: str
    ) -> None:
        ways = ([("desktop", web.show(f"KOLONİ — {name}", text))] if on_desktop else []) + (
            [("address", web.notify(url, text, form))] if url else []
        )
        for way, sending in ways:
            try:
                await sending
            except Exception as exc:
                log.warning(
                    "the day's summary of %s was not sent to the %s: %s",
                    name,
                    way,
                    exc if isinstance(exc, web.WebError) else type(exc).__name__,
                )

    async def look(self, moment: datetime) -> None:
        """One look, on the app's loop."""
        self._tick(moment)

    def tick(self, moment: datetime) -> None:
        """`look` from another thread (a test)."""
        self._on_loop(lambda: self._tick(moment))

    def _tick(self, moment: datetime) -> None:
        with contextlib.suppress(Exception):  # (the next look tries again)
            self._nights(moment)
