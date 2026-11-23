"""A look KOLONİ opened (S3's Reviewer, S11's diagnosis and fixer) is stopped by Stop this check -
said, the turn going on - but a cancel of the task awaiting it (KOLONİ closing, any cancel that is
not Stop this check) is that task's own: never swallowed as a stopped look (SonarCloud, PR #23)."""

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app.agent.review_mixin import STOPPED_LOOK, ReviewMixin
from app.agent.stronger_mixin import StrongerMixin

CTX = SimpleNamespace(agent_id="lead", run_id="r", cid="c")


class Runner:
    """What a look touches of the runner before its spawn ends: its answer on record, the call
    recorded, the spawn run (held until cancelled), the looks of the turn."""

    def __init__(self):
        self.started = asyncio.Event()
        self._looks: dict[str, set] = {}
        self._read_only_calls: set[str] = set()
        self._joins_copy: set[str] = set()
        self._try_calls: dict[str, str] = {}
        self._proofs: dict = {}
        self.stopped: list[str] = []

    @contextmanager
    def _factory(self):
        yield SimpleNamespace(scalar=lambda _query: "m1")

    def _record_calls(self, _ctx, _message_id, _requests):
        return [("call1", None)]

    async def _run_call(self, _ctx, _call_id, _request):
        self.started.set()
        await asyncio.Event().wait()

    def _turn_stopping(self) -> bool:
        return False

    def _look_stopped(self, _ctx, call_id):
        self.stopped.append(call_id)


LOOKS = {
    "review": lambda runner: ReviewMixin._review_look(runner, CTX, "Reviewer", "look"),
    "stronger": lambda runner: StrongerMixin._koloni_agent(runner, CTX, "fix", {}),
}


@pytest.mark.parametrize("kind", sorted(LOOKS))
def test_a_cancel_of_the_awaiting_task_is_never_swallowed(kind):
    async def main():
        runner = Runner()
        task = asyncio.ensure_future(LOOKS[kind](runner))
        await runner.started.wait()
        task.cancel()  # (KOLONİ closing: the task's own cancel reaches the look too)
        with pytest.raises(asyncio.CancelledError):
            await task
        assert runner.stopped == []  # (no "stopped" look said)
    asyncio.run(main())


@pytest.mark.parametrize("kind", sorted(LOOKS))
def test_stop_this_check_still_says_the_look_stopped(kind):
    async def main():
        runner = Runner()
        task = asyncio.ensure_future(LOOKS[kind](runner))
        await runner.started.wait()
        for going in runner._looks["r"]:
            going.cancel()  # (Stop this check: the look alone)
        return await task
    said = asyncio.run(main())
    assert said.not_run == STOPPED_LOOK if kind == "review" else said[:2] == ("failed", "stopped")
