"""What a piece of an agent's work carries, and the small state objects around a turn.

`Ctx` (the agent the work is done for), the refusals a gate raises, a turn's live transcript
(`_Transcript`), the watch over a copy (`_Watch`, `_Hold`), a room's members (`_Member`,
`_Room`), `TERMINAL`, `announce` / `announce_memory`, which tell the page what changed, and
`sent_effort` (the thinking level a step's model is sent).
A leaf: at run time it imports nothing else of `app.agent` (`app.triggers` takes `TERMINAL` and
`announce` at its top).
"""

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy import select

from app import copies
from app.db.models import Conversation, Message
from app.model_client import EFFORTS, ModelClient, ModelInfo, OwnStop
from app.model_session import SessionStop
from app.project_view import ProjectView
from app.serialize import message_out
from app.tools import ToolError

if TYPE_CHECKING:
    from app.agent import AgentRunner

TERMINAL = frozenset({"completed", "failed", "cancelled", "interrupted"})
FLUSH_SECONDS = 0.5
NO_FOLDER = (
    "this chat has no folder: nothing in it changes files or runs commands, and a file is "
    "read only by its full path, on the user's word. The user can pick a folder with the "
    "folder button at the top of the chat."
)


@dataclass(frozen=True)
class Ctx:
    """The agent a piece of work is being done for."""

    run_id: str
    cid: str
    # The project folder; None in a plain chat (slice 86a): no tool that needs one.
    root: str | None
    agent_id: str
    role: str
    tools: tuple[str, ...]
    depth: int
    instructions: str = ""
    task: str | None = None  # None for the lead
    parent_role: str | None = None
    # Where this agent's model steps go; fixed when it starts.
    model: ModelClient | None = None
    provider: str | None = None
    # What other agents call it, and the agent that opened it.
    name: str = ""
    parent_id: str | None = None
    # A turn taken to answer another agent: read-only, and nothing of the agent's own
    # unfinished work may be touched. `calls_from` is the last tool call before the turn.
    answering: bool = False
    calls_from: int = 0
    # A turn taken on another agent's message (to answer it, or to carry on): the sender
    # holds this agent's turn for as long as it lasts.
    in_turn: bool = False
    # Speaking in a discussion: which one, and the messages written in this speech (they
    # belong to the shared place, not to the agent's own conversation).
    discussion: str | None = None
    speech_ids: list | None = None
    # Fewer steps than a whole job gets, when this is a short turn.
    max_steps: int | None = None
    # The tool calls made in an answer turn, so that only they are settled if it fails.
    own_calls: set | None = None
    # The provider and the model name its client was built for, so that each new turn
    # of the agent can be held to what that provider may run now.
    provider_id: str | None = None
    model_name: str | None = None
    # The agent of an earlier turn of the topic it goes on from (`app.topics`): what
    # that one did and said, and the ones before it, is where its history begins.
    continues_id: str | None = None
    # How far its role lets one agent go, as the role stood when it was opened: model
    # steps, and tokens as its model reports them. None: no limit of the role's.
    role_steps: int | None = None
    role_tokens: int | None = None
    # The MCP servers (their names) whose tools it may use: its role's, and for a
    # sub-agent never one the agent that opened it has not.
    mcp: tuple[str, ...] = ()
    # How hard its model is asked to think (of EFFORTS); None: the model's own. Sent
    # only to a model that says it takes that level.
    effort: str | None = None
    # How many tokens its model reads at most, as its role sets it; None: as found.
    context_window: int | None = None
    # K-buyuk-proje: the part of the project it works in, as the map has it ("core/"): its
    # commands run there unless they say, and it is told the part's AGENTS.md. None: the whole.
    part: str | None = None

    @property
    def folder(self) -> str:
        """Its root, where what it does needs one: in a plain chat that is refused."""
        if self.root is None:
            raise ToolError(NO_FOLDER)
        return self.root


class _GateRefused(ToolError):
    """K-evrim review: KOLONİ's own run of a project command that a gate keeps from running
    unasked, or that the user declined on its card (`_run_in_copy`): it did not run."""


class _NobodyToAsk(ToolError):
    """Refused in a turn nobody is watching - or by the user's no to a path outside the
    project; on record as denied, not as failed."""


@dataclass
class _Unwatched:
    """An unattended turn: the trigger that started it and the budget it runs on."""

    trigger_id: str | None
    trigger_name: str
    steps: int  # model steps, all its agents together
    minutes: int
    taken: int = 0
    # The clock its minutes run on: not set while the turn is only kept waiting for
    # room. `left`: the seconds it still has; `since`: when the clock was last set.
    timer: asyncio.TimerHandle | None = None
    left: float = 0.0
    since: float = 0.0


class _Transcript:
    """What a CLI that keeps its own loop says, kept as assistant messages.

    Text goes into the message that is open; a tool call closes it and hangs off it
    (off an empty message, when the CLI called without saying anything first).

    A step is one message of the model with whatever calls it carries, as for a model
    asked step by step: where a session's stream says which message of the model it is
    writing (`of`), the further calls of that message hang off the same message here,
    and what it carries is counted once.
    """

    def __init__(self, runner: "AgentRunner", ctx: Ctx, limit: int | None, opened: int = 0):
        self._runner, self._ctx, self._limit = runner, ctx, limit
        self._open: str | None = None
        self._said: str | None = None  # the last message closed
        self.opened = opened  # (the steps it took: from those it took before, told to go on)
        # The message of the model that is being written, as its stream names it, and
        # the message here its calls hang off: None until the first of them.
        self._theirs: object = None
        self._calls: str | None = None
        self._last_flush = time.monotonic()

    def of(self, theirs: object) -> None:
        """What follows in a session's stream belongs to this message of the model."""
        if theirs != self._theirs:
            self._theirs, self._calls = theirs, None

    def _begin(self) -> str:
        runner, ctx = self._runner, self._ctx
        # (More text after a call, in one message of the model: counted with the call.)
        if self._calls is None:
            if self._limit is not None:
                # A session's messages are steps KOLONİ counts: held to the app's own
                # limit and to its role's. (With its own tools - no limit here - they
                # are not.) Read again at each: a recipe's runner's grows (R147).
                if self.opened >= (ctx.max_steps or runner._step_limit(ctx)):
                    runner._stopped_by_koloni(ctx)
                    raise SessionStop(runner._given_limit(ctx))
                try:
                    runner._hold_to_role(ctx, self.opened)
                except OwnStop as stop:
                    raise SessionStop(str(stop)) from None
            runner._count_step(ctx)
            self.opened += 1
            if self._limit is not None:
                # B-382: what it has left after this one, by the nearer limit, as `_steps` keeps
                # it - told with its next tool result once that is few (`_near_a_limit`).
                most = ctx.max_steps or runner._step_limit(ctx)
                if not ctx.max_steps and ctx.agent_id not in runner._given_steps and (
                        ctx.role_steps):
                    most = min(most, ctx.role_steps - runner._role_before(ctx))
                runner._steps_left[ctx.agent_id] = most - self.opened
        with runner._factory() as session:
            message = Message(
                conversation_id=ctx.cid, run_id=ctx.run_id, agent_id=ctx.agent_id,
                role="assistant", content="", status="streaming",
                discussion_id=ctx.discussion,
            )
            session.add(message)
            session.commit()
            self._open, payload = message.id, message_out(message)
        if ctx.speech_ids is not None:
            ctx.speech_ids.append(self._open)
        runner.bus.emit(ctx.cid, ctx.run_id, "message.created", payload)
        runner._live[self._open] = (ctx.cid, "")
        return self._open

    def end(self) -> None:
        """Close the open message, keeping whatever was written into it."""
        if self._open is None:
            return
        runner, ctx = self._runner, self._ctx
        content = runner._live.pop(self._open)[1]
        payload = runner._save_message(self._open, content, "complete")
        runner.bus.emit(ctx.cid, ctx.run_id, "message.completed", payload)
        self._said, self._open = self._open, None

    def take(self) -> str:
        """The id of the message a tool call belongs to; that message is closed."""
        message_id = self._open or self._calls or self._begin()
        self.end()
        if self._theirs is not None:
            self._calls = message_id
        return message_id

    def said(self) -> str:
        """The message a note at its end belongs to: the one open, else the last one said -
        not an empty one of its own, which would be its last word, its report (93-B6)."""
        return self.take() if self._open or not self._said else self._said

    async def on_text(self, text: str) -> None:
        runner, ctx = self._runner, self._ctx
        message_id = self._open or self._begin()
        content = runner._live[message_id][1] + text
        runner._live[message_id] = (ctx.cid, content)
        runner.bus.emit_transient(
            ctx.cid, "message.delta", {"message_id": message_id, "text": text}
        )
        if time.monotonic() - self._last_flush >= FLUSH_SECONDS:
            self._last_flush = time.monotonic()
            runner._save_message(message_id, content, "streaming")
        runner._touch(ctx)


class _Watch:
    """What KOLONİ keeps while it watches a native agent: the folder it works in as
    KOLONİ last saw it - the project, or for a sub-agent started in one its working
    copy (`copy`) - the agent's commands that are still running, and a lock so that
    two looks at the folder never overlap. Where the agent works is what its watch
    says, from its start to its end: `view.root`, and `copy` for what that means."""

    def __init__(self, view: ProjectView, copy: copies.Copy | None = None):
        self.view = view
        self.copy = copy
        # For an agent in a copy, the project as KOLONİ last saw it: what its CLI changes
        # there all the same, by a path outside its copy, is seen with what was before.
        self.project: ProjectView | None = None
        self.straight: set[str] = set()  # the project's files it was found to have changed
        # Its CLI is held to no folder (`_sandboxed`): a command of it can write there
        # without a path being named, so the project is looked at after each, and at its end.
        self.unheld = False
        # B-310: its CLI (agy) never took KOLONİ's bridge, so it runs the old way: with none of
        # KOLONİ's tools, a Lead that hands code on cannot, and writes itself.
        self.unbridged = False
        # K-yazma-denetimi: the project's standing files (`standing_files`) as they were let
        # stand - in the project, wherever it works - since `since` (monotonic), the paths of
        # them the user's yes to a write of its named (casefolded), and its commands the user
        # said yes to, by item id (what they name stands at the look after them): any other
        # change there is put back (`_standing_look`).
        self.standing: dict[str, bytes] = {}
        self.since = 0.0
        self.named: set[str] = set()
        self.approved: set[str] = set()
        # K-48: a Lead whose own writes are refused was told what its command changed.
        self.told_hands_on = False
        self.commands: dict[str, tuple[str, str]] = {}  # item id -> (call id, command id)
        # Ends its CLI's turn, with why (`run_native`'s `on_end`): Stop on one of its commands.
        self.end: Callable[[BaseException], None] | None = None
        self.looking = asyncio.Lock()
        # Whose work is being watched, and where it is written down.
        self.ctx: Ctx | None = None
        self.transcript: _Transcript | None = None
        # Its place among the agents with tools of their own: stepped away from while
        # a request of its CLI waits for a file another agent holds.
        self.hold: _Hold | None = None
        # For a CLI that asks leave first, by the id of its tool use: a change that was
        # approved (call id, change id), another tool that was allowed (call id), and
        # what was refused - which must not be written down as done when it reports.
        self.asked: dict[str, tuple[str, str]] = {}
        self.asked_other: dict[str, str] = {}
        self.denied: set[str] = set()
        # The tool uses the CLI has said it wants: leave is given for these and no others.
        self.announced: set[str] = set()
        # The CLI's own sub-agents: the call each is on record as, by the id of the tool
        # use that started it; the ones still at work; and for a tool use made inside
        # one, which one.
        self.subs: dict[str, str] = {}
        self.at_work: set[str] = set()
        self.inside: dict[str, str] = {}
        # 89g: the roles offered to its CLI as sub-agents of its own, by the name each is
        # offered by: the role's name, and the CLI's tools it may use.
        self.roles: dict[str, tuple[str, list[str]]] = {}

    def under(self, use_id: str) -> str | None:
        """The call of the sub-agent this tool use was made in, if it was made in one."""
        return self.subs.get(self.inside.get(use_id, ""))

    async def look(self, changes: Callable[[], list]) -> list:
        """A whole look at a folder it watches (`view.changes`, `project.changes`): no other
        overlaps it, and it walks every file in a thread - the server goes on meanwhile - to
        its end (`to_its_end`)."""

        async def locked() -> list:
            async with self.looking:
                return await asyncio.to_thread(changes)

        return await to_its_end(locked())


async def _through_stops(task: asyncio.Future) -> bool:
    """Wait for `task` to end, however many Stops cancel the waiter meanwhile (B-405) - never
    raising what it raised. Whether a Stop came: the waiter's cancel is taken back, for its
    caller to end as stopped."""
    stopped = False
    while not task.done():
        try:
            await asyncio.wait({task})
        except asyncio.CancelledError:
            stopped = True
            if (me := asyncio.current_task()) is not None:
                me.uncancel()
    return stopped


async def to_its_end[T](work: Awaitable[T]) -> T:
    """`work` awaited to its end: a Stop that comes meanwhile does not cut it short, and lands
    at the next wait after it - as it did when the work held the event loop."""
    job = asyncio.ensure_future(work)
    if await _through_stops(job) and (me := asyncio.current_task()) is not None:
        me.cancel()
    return job.result()


class _Hold:
    """The one place for an agent working with tools of its own, held by an agent that
    can step away from it - while KOLONİ runs a tool for it - and come back."""

    def __init__(self, lock: asyncio.Lock):
        self._lock, self._held, self._away = lock, False, 0

    async def take(self) -> None:
        await self._lock.acquire()
        self._held = True

    def give(self) -> None:
        if self._held:
            self._held = False
            self._lock.release()

    @contextlib.asynccontextmanager
    async def away(self):
        self._away += 1
        if self._away == 1:
            self.give()
        try:
            yield
        finally:
            self._away -= 1
            if self._away == 0:
                await self.take()


@dataclass
class _Member:
    """A member of a room, for as long as the room is not done with: its agent, and where
    it stands - "in" (at work), "waiting" (for a post), "done" (its work is over) or
    "left" (it failed)."""

    ctx: Ctx
    row: str  # its `RoomMember`
    state: str = "in"
    # Set when a post it has not been given is there: what `wait_for_post` waits for -
    # and `wait_for_item`, for the item numbered `awaits` to be closed.
    news: asyncio.Event = field(default_factory=asyncio.Event)
    awaits: int | None = None
    # Set when a question for it comes after its work was over: it goes on - and that
    # question's number, which its next last words answer where no post of its own did (B-156).
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    woken_by: int | None = None
    # Set when its opener answered a question of its after its work was over (S3): it reads it.
    answered: bool = False
    # How the room stood when it was last told (a CLI session is told only what is new).
    told: str = ""


@dataclass
class _Room:
    """A room that runs, or is over and has its copy still to be taken into the project:
    the turn's lead - who takes no part, and in whose name the room's one working copy
    is kept - and its members by their agents' ids, in the order the user named them."""

    id: str
    lead: Ctx
    members: dict[str, _Member] = field(default_factory=dict)
    status: str = "sharing"
    # How it ended, once it has - set before its members are stopped - and why, where
    # there is more to say (`Room.why`).
    outcome: str | None = None
    reached: str | None = None
    # What of it is being done right now: stopped when it ends.
    tasks: list[asyncio.Task] = field(default_factory=list)
    # Its minutes: the seconds counted so far, since when (the loop's time) they are
    # being counted now - None while its clock stands - and what ends it at its limit.
    seconds: float = 0.0
    since: float | None = None
    timer: asyncio.TimerHandle | None = None
    # K-not-oda: the teams its members come from, where no one team holds them all - a room
    # between teams, which talks and decides and changes no file (`_talk_only`). Set as it
    # opens: nobody of another team is invited into one within a team (`_invite`).
    between: tuple[str, ...] = ()
    # 29c: set while it may go on; cleared while the user has it paused (`_while_paused`).
    go: asyncio.Event = field(default_factory=lambda: _set(asyncio.Event()))
    # K-oda-lead: for one its opener follows - or the user's (K-oda-izle) - its life from opening
    # to record as a task of its own (`_room_life`); set at each post of somebody else's; the
    # number of the last post the opener was given.
    life: asyncio.Task | None = None
    heard: asyncio.Event = field(default_factory=asyncio.Event)
    seen: int = 0
    # While its opener follows it and reads what is said (not in its last steps, `FOLLOW_RESERVE`):
    # it is one more at work to its members - whom they may ask, and who may answer (S3).
    reads: bool = False
    # The last post it had been given when it was told its members only wait (`_follow`).
    alone_at: int = -1
    # K-oda-izle: set while the user lets the turn's Lead follow the room they opened (`reads`
    # too), which wakes it; and once its Lead follows it no further, whatever the user says.
    follow: asyncio.Event = field(default_factory=asyncio.Event)
    read_out: bool = False


def _set(event: asyncio.Event) -> asyncio.Event:
    event.set()
    return event


def announce_memory(session_factory, bus, project_id: str, but: str | None = None) -> None:
    """Tell whoever is watching a conversation of the project that its memory changed.
    Not kept with any conversation: the memory is the project's, and is read again."""
    announce(session_factory, bus, project_id, "memory.changed", but)


def announce(
    session_factory, bus, project_id: str | None, event: str, but: str | None = None
) -> None:
    """Tell whoever is watching a conversation of the project that something of the
    project's changed (its memory, its backlog): not kept, it is read again."""
    if project_id is None:  # (no project: `== None` would name every plain chat)
        return
    with session_factory() as session:
        watching = list(session.scalars(
            select(Conversation.id).where(Conversation.project_id == project_id)
        ))
    for cid in watching:
        if cid != but:
            bus.emit_transient(cid, event, {"project_id": project_id})


def sent_effort(ctx: "Ctx", info: ModelInfo) -> str | None:
    """The level that goes with an agent's model's work: its own, where its model takes it,
    else the nearest lower one it takes (a sub-agent moved to another model, whose levels
    differ); none where there is none below. Off goes only where Off itself was asked."""
    asked, takes = ctx.effort, info.efforts or ()
    if asked is None or asked == "off":
        return asked if asked in takes else None
    below = EFFORTS[EFFORTS.index(asked):0:-1]  # (from it down to Low: never Off)
    return next((level for level in below if level in takes), None)
