"""Slice 26's fix round: an agent holds a place among the agents at work only while it
itself takes a model step or runs a tool - never while it waits for the user, for a
sub-agent, for another agent or for a file - whatever order its calls and the user's
decisions come in. Shown on the scenario the review found, on every order of approvals,
and on a few hundred small turns with random decisions and Stops, under a limit of one
and of two: at the end nothing runs, nothing waits and nobody holds a place.

Beside it: what else the review found - the line is advanced on the event loop and
never stops on an error, an unattended turn's minutes do not run while it stands in
line, the user's word is on record at once though its agent waits for a place, ending a
discussion needs no place, and a wait that is stopped is told to the other conversation.
"""

import asyncio
import itertools
import random
import re
import sqlite3
import threading
import time
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from alembic import command

import app.web
from app.agent import recover_interrupted, slots_mixin
from app.config import load_settings
from app.db.models import Agent, Command, Conversation, FileChange, Project, Run, WebRequest
from app.db.session import make_engine, make_session_factory, upgrade_db
from app.main import create_app
from app.model_client import ModelInfo
from tests.conftest import TERMINAL, Gate
from tests.fakes import Script, ScriptedExecutor
from tests.keyed import TestClient
from tests.test_agent_commands import cmd
from tests.test_board_scenarios import ORIGIN, board, go, on_board, project, talk
from tests.test_chat_flow import text
from tests.test_claim_scenarios import agent, write
from tests.test_discussion import TWO, discuss
from tests.test_max_agents import cancel, queued
from tests.test_migration_0002 import _config
from tests.test_parallel import until
from tests.test_recovery import seed
from tests.test_spawn import call, new_role, step
from tests.test_triggers import HeldClock, on_loop, run_now, trigger
from tests.test_triggers import until as until_true
from tests.test_web_tool_scenarios import Net, get

AGENT_OVER = {"completed", "failed", "cancelled", "rejected", "interrupted"}
FILES = ("a.txt", "b.txt", "docs/c.md")
COMMANDS = ("pytest -q", "npm test", "git status", "ls docs", "python -m build")


class Endless(ScriptedExecutor):
    """Every command prints a line and exits: no process is started."""

    def __init__(self):
        super().__init__([])

    async def start(self, *args, **kwargs):
        self.scripts.append(Script(["ok\n"]))
        return await super().start(*args, **kwargs)


class ByTask:
    """A model that does what the last thing said to it says, in [[double brackets]]:

    [[spawn N task]]  open N Coders at once, each told [[task]]
    [[nest]]          open one Coder told [[leaf]]
    [[hold name]]     stay in this step until the test lets the gate of that name go
    [[write path]]    write a file;  [[ask]]  ask the user;  [[leaf]]  just answer
    [[rand]]          any of these or a command, by the seeded dice - and whatever it
                      opens does the same

    After a tool's result it answers and is done (but for [[rand]], which may go on).
    """

    def __init__(self, rng: random.Random | None = None):
        self.rng = rng or random.Random(0)
        self.gates: dict[str, Gate] = {}
        self.ids = itertools.count()
        self.steps = 0

    def gate(self, name: str) -> Gate:
        return self.gates.setdefault(name, Gate())

    async def info(self) -> ModelInfo:
        return ModelInfo("fake-model", True)

    def _spawn(self, count: int, task: str):
        return step(*[
            call("spawn_agent", {"role": "Coder", "task": f"[[{task}]]"}, f"s{next(self.ids)}")
            for _ in range(count)
        ])

    def _write(self, path: str):
        return step(write(path, f"{next(self.ids)}\n", f"w{next(self.ids)}"))

    def _dice(self, has: set[str], taken: int):
        roll = self.rng.random()
        if taken >= 3 or roll < 0.3:
            return text("done")
        if "spawn_agent" in has and roll < 0.55:
            return self._spawn(self.rng.choice((1, 1, 2, 3)), "rand")
        if "write_file" in has and roll < 0.78:
            return self._write(self.rng.choice(FILES))
        if "run_command" in has and roll < 0.9:
            return step(call(
                "run_command", {"command": self.rng.choice(COMMANDS)}, f"k{next(self.ids)}"))
        if "ask_user" in has:
            return step(call("ask_user", {"question": "Go on?"}, f"q{next(self.ids)}"))
        return text("done")

    async def stream_step(self, model_id, messages, tools, on_delta, on_thinking=None):
        self.steps += 1
        said = [str(m.get("content") or "") for m in messages if m["role"] == "user"]
        told = re.findall(r"\[\[(.*?)\]\]", said[-1] if said else "")
        words = told[-1].split() if told else ["leaf"]
        last_user = max(i for i, m in enumerate(messages) if m["role"] == "user")
        taken = sum(m["role"] == "assistant" for m in messages[last_user:])
        if words[0] == "rand":
            await asyncio.sleep(self.rng.random() * 0.003)
            has = {tool["function"]["name"] for tool in tools or []}
            result = self._dice(has, taken)
        elif taken:
            result = text("done")
        elif words[0] == "spawn":
            result = self._spawn(int(words[1]), " ".join(words[2:]))
        elif words[0] == "nest":
            result = self._spawn(1, "leaf")
        elif words[0] == "write":
            result = self._write(words[1])
        elif words[0] == "ask":
            result = step(call("ask_user", {"question": "Go on?"}, f"q{next(self.ids)}"))
        elif words[0] == "hold":
            return await self.gate(words[1]).step(text("held and done"))(on_delta)
        else:
            result = text("done")
        if result.content:
            await on_delta(result.content)
        return result


@pytest.fixture
def told(settings_env):
    """An app around a ByTask model, asked from the app's own page: (client, model)."""
    opened: list[TestClient] = []

    def make(rng: random.Random | None = None, executor: ScriptedExecutor | None = None):
        model = ByTask(rng)
        client = TestClient(
            create_app(load_settings(settings_env), model=model,
                       executors=executor.factory if executor else None),
            base_url="http://127.0.0.1:8790")
        client.__enter__()
        client.headers["Origin"] = ORIGIN
        opened.append(client)
        return client, model

    yield make
    for client in opened:
        for gate in client.app.state.providers.override.gates.values():
            gate.release()
        client.__exit__(None, None, None)


def limited(client, project_dir, limit):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={"max_agents": limit}).status_code == 200
    return pid


def say(client, cid, content):
    return client.post(
        f"/api/conversations/{cid}/messages", json={"content": content}).json()["run"]["id"]


def proposed(snap):
    return [one["id"] for one in snap["agents"] if one["status"] == "proposed"]


def nobody_holds_anything(client, pid):
    """Nothing of a turn is left in the runner: no place, no line, no wait, no agent."""
    runner = client.app.state.runner
    assert board(client, pid)["running"] == 0
    assert (runner._placed, runner._line_up, runner._away) == (set(), [], set())
    assert (runner._ctxs, runner._slots, runner._settling) == ({}, {}, {})
    assert not any((runner._asks, runner._out, runner._held_up))


def see_through(client, cid, run_id, seconds=15.0):
    """Say yes to every sub-agent that is proposed until the turn is over."""
    deadline = time.monotonic() + seconds
    while True:
        snap = client.get(f"/api/conversations/{cid}").json()
        if next(r for r in snap["runs"] if r["id"] == run_id)["status"] in TERMINAL:
            return snap
        assert time.monotonic() < deadline, (
            "the turn never ended: "
            + str([(a["name"], a["status"]) for a in snap["agents"]]))
        for agent_id in proposed(snap):
            assert client.post(f"/api/agents/{agent_id}/approve").status_code in (200, 409)
        time.sleep(0.02)


# --- the place is never kept over a wait -----------------------------------------------


def test_two_sub_agents_approved_while_another_conversation_has_the_only_place(
    told, wait_run, project_dir
):
    """What the review found: the lead of A asks for two sub-agents in one step, both
    wait for the user, B's lead takes the one place, both are approved, B ends. The lead
    of A must not be found holding the place its own sub-agents stand in line for."""
    client, model = told()
    pid = limited(client, project_dir, 1)
    a = talk(client, pid, spawn_approval="always", spawn_max_parallel=3)
    b = talk(client, pid)
    run_a = say(client, a, "[[spawn 2 leaf]]")
    first, second = proposed(until(client, a, lambda s: len(proposed(s)) == 2))
    run_b = say(client, b, "[[hold b]]")
    model.gate("b").wait_partial()                       # B's lead has the one place
    for agent_id in (first, second):
        began = time.monotonic()
        said = client.post(f"/api/agents/{agent_id}/approve")
        # Answered at once, and with what is true: it is approved and waits for a place.
        assert said.status_code == 200 and said.json()["status"] == "queued"
        assert time.monotonic() - began < 2
        assert client.post(f"/api/agents/{agent_id}/approve").status_code == 409
    snap = client.get(f"/api/conversations/{a}").json()
    assert {x["name"]: x["status"] for x in snap["agents"]} == {
        "Lead": "waiting", "Coder": "queued", "Coder 2": "queued"}
    assert snap["runs"][0]["status"] == "running"        # nothing is asked of the user
    assert board(client, pid)["running"] == 1
    model.gate("b").release()
    assert wait_run(client, b, run_b)["runs"][0]["status"] == "completed"
    snap = wait_run(client, a, run_a)
    assert snap["runs"][0]["status"] == "completed"
    assert {x["name"]: x["status"] for x in snap["agents"]} == {
        "Lead": "completed", "Coder": "completed", "Coder 2": "completed"}
    nobody_holds_anything(client, pid)


@pytest.mark.parametrize("task", ["leaf", "nest"])
@pytest.mark.parametrize(
    "order", [order for n in (2, 3) for order in itertools.permutations(range(n))])
def test_sub_agents_opened_in_one_step_are_approved_in_any_order_under_a_limit_of_one(
    told, wait_run, project_dir, order, task
):
    """...and each of them may open one of its own ([[nest]]), which is asked about too."""
    client, model = told()
    pid = limited(client, project_dir, 1)
    a = talk(client, pid, spawn_approval="always", spawn_max_parallel=3, spawn_max_depth=2)
    b = talk(client, pid)
    run_a = say(client, a, f"[[spawn {len(order)} {task}]]")
    asked = proposed(until(client, a, lambda s: len(proposed(s)) == len(order)))
    run_b = say(client, b, "[[hold b]]")
    model.gate("b").wait_partial()
    for at in order:
        said = client.post(f"/api/agents/{asked[at]}/approve")
        assert (said.status_code, said.json()["status"]) == (200, "queued")
    assert board(client, pid)["running"] == 1            # B's lead, and nobody of A
    model.gate("b").release()
    assert wait_run(client, b, run_b)["runs"][0]["status"] == "completed"
    snap = see_through(client, a, run_a)
    assert snap["runs"][0]["status"] == "completed"
    assert {x["status"] for x in snap["agents"]} == {"completed"}
    assert len(snap["agents"]) == 1 + len(order) * (2 if task == "nest" else 1)
    nobody_holds_anything(client, pid)


@pytest.mark.parametrize("no", [0, 1, 2])
def test_a_no_among_the_decisions_needs_no_place_and_the_lead_goes_on_when_it_has_one(
    told, wait_run, project_dir, no
):
    client, model = told()
    pid = limited(client, project_dir, 1)
    a = talk(client, pid, spawn_approval="always", spawn_max_parallel=3)
    b = talk(client, pid)
    run_a = say(client, a, "[[spawn 3 leaf]]")
    asked = proposed(until(client, a, lambda s: len(proposed(s)) == 3))
    run_b = say(client, b, "[[hold b]]")
    model.gate("b").wait_partial()
    said = client.post(f"/api/agents/{asked[no]}/reject")
    assert (said.status_code, said.json()["status"]) == (200, "rejected")   # at once
    for at in set(range(3)) - {no}:
        assert client.post(f"/api/agents/{asked[at]}/approve").json()["status"] == "queued"
    assert board(client, pid)["running"] == 1
    model.gate("b").release()
    wait_run(client, b, run_b)
    snap = wait_run(client, a, run_a)
    assert snap["runs"][0]["status"] == "completed"
    assert sorted(x["status"] for x in snap["agents"]) == [
        "completed", "completed", "completed", "rejected"]
    nobody_holds_anything(client, pid)


def test_every_sub_agent_turned_down_while_the_project_is_full(told, wait_run, project_dir):
    """The lead has nobody to wait for: it stands in line itself, and says so."""
    client, model = told()
    pid = limited(client, project_dir, 1)
    a = talk(client, pid, spawn_approval="always", spawn_max_parallel=3)
    b = talk(client, pid)
    run_a = say(client, a, "[[spawn 2 leaf]]")
    asked = proposed(until(client, a, lambda s: len(proposed(s)) == 2))
    run_b = say(client, b, "[[hold b]]")
    model.gate("b").wait_partial()
    for agent_id in asked:
        assert client.post(f"/api/agents/{agent_id}/reject").json()["status"] == "rejected"
    snap = queued(client, a)
    assert snap["runs"][0]["status"] == "running" and board(client, pid)["running"] == 1
    model.gate("b").release()
    wait_run(client, b, run_b)
    assert wait_run(client, a, run_a)["runs"][0]["status"] == "completed"
    nobody_holds_anything(client, pid)


# --- many small turns ----------------------------------------------------------------------


def _decide(client, runner, dice, first: dict[str, list]):
    """Say something, by the dice, to whatever waits for the user right now - or leave
    it for the next look. (Read from the runner: faster than three snapshots a look.)
    `first`: what the first cards of a kind are told, in turn, before the dice - each answer
    the test asserts on is given at least once, whatever the dice throw (under load "Always
    run" was never thrown once). One answered too late (409) is given to the next card."""
    def some(waiting: dict) -> list[str]:
        try:
            return [one for one in list(waiting) if dice.random() < 0.7]
        except RuntimeError:  # it changed while it was read from this thread
            return []

    def told(kind: str, one: str, thrown):
        forced = bool(first[kind])
        word = first[kind].pop(0) if forced else thrown()
        verb, body = word if isinstance(word, tuple) else (word, None)
        answer = client.post(f"/api/{kind}/{one}/{verb}", json=body)
        if forced and answer.status_code == 409:
            first[kind].insert(0, word)
        return answer

    yes = lambda: "approve" if dice.random() < 0.7 else "reject"  # noqa: E731
    # A command: no, once, or "Always run" - after which that command is not asked about.
    command = lambda: "reject" if dice.random() < 0.3 else (  # noqa: E731
        "approve", {"remember": dice.random() < 0.3})
    sent = [told("agents", one, yes) for one in some(runner._spawn_decisions)]
    sent += [told("file-changes", one, yes) for one in some(runner._decisions)]
    sent += [told("commands", one, command) for one in some(runner.commands._decisions)]
    sent += [told("merges", one, yes) for one in some(runner._merge_decisions)]
    sent += [client.post(f"/api/questions/{one}/answer", json={"answer": "yes"})
             for one in some(runner._answers)]
    assert all(one.status_code in (200, 409) for one in sent), [one.text for one in sent]


@pytest.mark.parametrize("limit", [1, 2, 3, 4])
def test_a_few_hundred_small_turns_with_random_decisions_and_stops_leave_nothing_behind(  # noqa: C901
    told, project_dir, limit, seed=2026, each=50, stall=60.0
):
    """Three conversations of one project, `each` turns in each: every turn's agents do
    what the dice say (sub-agents at once, sub-agents of those, files that two of them
    want, questions, commands that are asked about until "Always run" is said), and the
    user's decisions, refusals and Stops come by the dice too.

    Under a limit of one and of two - and, the third time, under limits that move while
    the turns run: the project's (1 to 3) and its provider's (1, 2 or none), by the dice.
    The fourth time the project lets three work and its provider one: two conversations
    are on that provider, the third on one without a limit - its agents work beside."""
    moving, narrow = limit == 3, limit == 4
    client, model = told(random.Random(seed + limit), Endless())
    dice = random.Random(seed - limit)
    pid = limited(client, project_dir, 3 if narrow else limit)
    provider = client.get("/api/providers").json()[0]["id"]
    if moving or narrow:
        assert client.patch(
            f"/api/providers/{provider}", json={"max_running": 1 if narrow else 2}
        ).status_code == 200
    moved = 0
    runner = client.app.state.runner
    cids = [
        talk(client, pid, permission_mode="ask", spawn_approval="always",
             spawn_max_parallel=3, spawn_max_depth=2),
        talk(client, pid, spawn_approval="never", spawn_max_parallel=2, spawn_max_depth=2),
        talk(client, pid, permission_mode="ask", spawn_approval="auto", spawn_max_parallel=1),
    ]
    if narrow:
        other = client.post("/api/providers", json={
            "name": "other", "kind": "openai_compat", "base_url": "http://127.0.0.1:9/v1"})
        assert other.status_code == 201, other.text
        assert client.patch(f"/api/conversations/{cids[1]}", json={
            "provider_id": other.json()["id"]}).status_code == 200
    too_many: list[tuple[int, int]] = []
    in_line, at_once = [0], [0]
    let_in = runner.let_in

    def counted():
        before = set(runner._placed)
        let_in()
        in_line[0] = max(in_line[0], len(runner._line_up))
        at_once[0] = max(at_once[0], len(runner._placed))
        at_work = [runner._ctxs[one] for one in runner._placed if one in runner._ctxs]
        new = [runner._ctxs[one] for one in runner._placed - before if one in runner._ctxs]
        if new:
            # Nobody is let in beyond what its limits are at this moment (a limit that
            # was lowered may have more at work under it: those were there before).
            most, running = runner._limits(at_work)
            for ctx in new:
                for allowed, under in (
                    (most.get(ctx.cid), sum(one.root == ctx.root for one in at_work)),
                    (running.get(ctx.provider_id),
                     sum(one.provider_id == ctx.provider_id for one in at_work)),
                ):
                    if allowed and under > allowed:
                        too_many.append((under, allowed))

    runner.let_in = counted
    left, going = dict.fromkeys(cids, each), dict.fromkeys(cids)
    # Which turns the user stops, and after how many looks, is thrown once a turn, on dice of
    # its own: thrown at every look, a slower machine - its turns last more looks - stopped
    # more of them (Linux: 51 of 150), and the same seed threw other stops. (These seeds mark
    # 36 to 47 of the 150: more than 100 come to their end however many of those are stopped.)
    stops = random.Random(seed * limit)
    stop_in = dict.fromkeys(cids, 0)  # (0: not stopped)
    first: dict[str, list] = {"agents": ["reject"], "file-changes": ["approve", "reject"],
                              "commands": [("approve", {"remember": True}), "reject"], "merges": []}
    # Stuck, not slow: a busy machine takes longer for all of them (55-65 s alone, past a
    # total of 150 s in a full run), but a line that moves ends a turn every so often.
    moved_on = time.monotonic()
    while any(left.values()) or any(going.values()):
        assert time.monotonic() - moved_on < stall, (
            f"stuck with {left} turns to go: placed {runner._placed}, in line "
            f"{[ctx.name for ctx, _ in runner._line_up]}, away {runner._away}, "
            f"asks {runner._asks}, out {runner._out}, held up {runner._held_up}")
        for cid in cids:
            if going[cid] and not runner.is_active(going[cid]):
                going[cid], moved_on = None, time.monotonic()
            if going[cid] is None and left[cid]:
                going[cid], left[cid] = say(client, cid, "[[rand]]"), left[cid] - 1
                stop_in[cid] = stops.randint(1, 5) if stops.random() < 0.3 else 0
            elif going[cid] and stop_in[cid]:
                stop_in[cid] -= 1
                if not stop_in[cid]:
                    assert client.post(f"/api/runs/{going[cid]}/cancel").status_code in (202, 409)
        if moving and dice.random() < 0.1:
            where, new = dice.choice((
                (f"/api/projects/{pid}", {"max_agents": dice.choice((1, 2, 3))}),
                (f"/api/providers/{provider}", {"max_running": dice.choice((1, 2, None))}),
            ))
            assert client.patch(where, json=new).status_code == 200
            moved += 1
        _decide(client, runner, dice, first)
        time.sleep(0.002)

    assert too_many == []                                # nobody let in beyond a limit
    assert moved > 5 or not moving
    # ...and the provider's line did not hold up the agents of the other provider.
    assert at_once[0] > 1 or not narrow
    seen: dict[str, int] = {}
    for cid in cids:
        snap = client.get(f"/api/conversations/{cid}").json()
        assert len(snap["runs"]) == each
        assert {run["status"] for run in snap["runs"]} <= TERMINAL
        assert {one["status"] for one in snap["agents"]} <= AGENT_OVER
        assert not [c for c in snap["file_changes"] if c["status"] in ("proposed", "approved")]
        assert not [q for q in snap["questions"] if q["status"] == "pending"]
        assert not [m for m in snap["merges"] if m["status"] == "pending"]
        assert not [c for c in snap["commands"]
                    if c["status"] in ("proposed", "approved", "running")]
        for kind in ("runs", "agents", "file_changes", "questions", "merges", "commands"):
            for one in snap[kind]:
                key = f"{kind} {one['status']}"
                seen[key] = seen.get(key, 0) + 1
        seen["rules"] = seen.get("rules", 0) + len(snap["allowed_commands"])
        seen["deep"] = seen.get("deep", 0) + sum(one["depth"] == 2 for one in snap["agents"])
    nobody_holds_anything(client, pid)
    assert runner.claims_of(str(project_dir)) == []
    # It was not a quiet run: agents stood in line, sub-agents opened sub-agents, the user
    # said yes and no, turns were stopped, and most of them came to their end.
    print(f"limit {limit}: {model.steps} steps, {in_line[0]} in line at most, "
          f"{moved} changes of a limit, {seen}")
    assert in_line[0] >= 1 and seen["deep"] > 0 and model.steps > 3 * each
    for happened in ("runs completed", "runs cancelled", "agents rejected",
                     "file_changes applied", "file_changes rejected", "questions answered",
                     "commands exited", "commands rejected", "rules"):
        assert seen.get(happened, 0) > 0, (happened, seen)
    assert seen["runs completed"] > 2 * each


# --- a restart ---------------------------------------------------------------------------


def test_the_server_going_down_with_agents_in_line_leaves_none_of_them_at_work(
    settings_env, project_dir
):
    """...and what comes up again starts with every place free."""
    def up():
        model = ByTask()
        client = TestClient(
            create_app(load_settings(settings_env), model=model),
            base_url="http://127.0.0.1:8790")
        client.__enter__()
        client.headers["Origin"] = ORIGIN
        return client, model

    client, model = up()
    pid = limited(client, project_dir, 1)
    a, b = talk(client, pid), talk(client, pid, spawn_approval="never")
    say(client, a, "[[hold a]]")
    model.gate("a").wait_partial()
    say(client, b, "[[spawn 2 leaf]]")
    queued(client, b)
    client.__exit__(None, None, None)                    # the lead of B never got its place

    client, model = up()
    try:
        for cid in (a, b):
            snap = client.get(f"/api/conversations/{cid}").json()
            assert [run["status"] for run in snap["runs"]] == ["interrupted"]
            assert [one["status"] for one in snap["agents"]] == ["interrupted"]
        nobody_holds_anything(client, pid)
        run = say(client, b, "[[spawn 2 leaf]]")
        snap = until(client, b, lambda s: s["runs"][-1]["status"] in TERMINAL, timeout=10)
        assert next(r for r in snap["runs"] if r["id"] == run)["status"] == "completed"
        nobody_holds_anything(client, pid)
    finally:
        client.__exit__(None, None, None)


def test_a_restart_finds_agents_on_record_as_queued_and_closes_them(tmp_path):
    """The process died with them in line: nothing of it is `queued` or `running` after."""
    db = tmp_path / "r.db"
    upgrade_db(db)
    factory = make_session_factory(make_engine(db))
    with factory() as s:
        s.add(Project(id="p", name="p", root_path=str(tmp_path), max_agents=1))
        s.flush()
        s.add_all([Conversation(id="a", project_id="p"), Conversation(id="b", project_id="p")])
        s.flush()
        s.add_all([Run(id="ra", conversation_id="a", status="running"),
                   Run(id="rb", conversation_id="b", status="running")])
        s.flush()
        s.add_all([
            Agent(id="la", run_id="ra", role_name="Lead", tools=[], status="waiting"),
            Agent(id="ca", run_id="ra", role_name="Coder", tools=[], status="queued",
                  parent_agent_id="la", depth=1),
            Agent(id="lb", run_id="rb", role_name="Lead", tools=[], status="queued"),
        ])
        s.commit()
    assert recover_interrupted(factory) == 2
    with factory() as s:
        assert {run.id: run.status for run in s.query(Run)} == {
            "ra": "interrupted", "rb": "interrupted"}
        assert {one.status for one in s.query(Agent)} == {"interrupted"}
        assert all(one.ended_at is not None for one in s.query(Agent))


# --- the line is advanced on the event loop, and an error does not stop it ---------------


def test_changing_a_limit_lets_the_waiting_agents_in_on_the_event_loop(
    make_client, wait_run, project_dir
):
    first, second = Gate(), Gate()
    client, model, pid = project(
        make_client, project_dir,
        [first.step(text("A done")), second.step(text("B done")), text("C done")],
        max_agents=1)
    provider = client.get("/api/providers").json()[0]
    assert client.patch(
        f"/api/providers/{provider['id']}", json={"max_running": 1}).status_code == 200
    runner = client.app.state.runner
    loop_thread = on_loop(client, threading.get_ident)
    seen: list[tuple[int, bool]] = []
    let_in = runner.let_in

    def watched():
        try:
            asyncio.get_running_loop()
            on_the_loop = True
        except RuntimeError:  # a worker thread: there is no loop here
            on_the_loop = False
        seen.append((threading.get_ident(), on_the_loop))
        let_in()

    runner.let_in = watched
    a, b, c = talk(client, pid), talk(client, pid), talk(client, pid)
    run_a = go(client, a)
    first.wait_partial()
    run_b = go(client, b)
    queued(client, b)
    seen.clear()
    # The project's limit goes; the provider's still holds B. Then that goes too.
    assert client.patch(f"/api/projects/{pid}", json={"max_agents": 5}).status_code == 200
    assert seen == [(loop_thread, True)]
    assert agent(client.get(f"/api/conversations/{b}").json(), "Lead")["status"] == "queued"
    assert client.patch(
        f"/api/providers/{provider['id']}", json={"max_running": 2}).status_code == 200
    assert seen == [(loop_thread, True)] * 2
    second.wait_partial()                                # B's lead is at work beside A's
    run_c = go(client, c)
    queued(client, c)
    for gate in (first, second):
        gate.release()
    for cid, run in ((a, run_a), (b, run_b), (c, run_c)):
        assert wait_run(client, cid, run)["runs"][0]["status"] == "completed"
    assert all(where == (loop_thread, True) for where in seen)


def test_a_new_providers_limit_is_the_users_to_set_from_the_apps_own_page(client):
    new = {"name": "mine", "kind": "openai_compat", "base_url": "http://127.0.0.1:9/v1"}
    limited_ = {**new, "max_running": 2}
    assert client.post("/api/providers", json=limited_).status_code == 403
    made = client.post("/api/providers", json=limited_, headers={"Origin": ORIGIN})
    assert made.status_code == 201 and made.json()["max_running"] == 2
    # Without a limit it is made as it always was.
    assert client.post("/api/providers", json={**new, "name": "other"}).status_code == 201


def test_limits_that_cannot_be_read_do_not_break_the_turn_that_ends_nor_stop_the_line(
    make_client, wait_run, project_dir, monkeypatch
):
    monkeypatch.setattr(slots_mixin, "LOOK_AGAIN", 0.05)
    first = Gate()
    client, model, pid = project(
        make_client, project_dir, [first.step(text("A done")), text("B done")], max_agents=1)
    runner = client.app.state.runner
    a, b = talk(client, pid), talk(client, pid)
    run_a = go(client, a)
    first.wait_partial()
    run_b = go(client, b)
    queued(client, b)
    read, reads, failed = runner._limits, [], []

    def broken(ctxs):
        reads.append(len(ctxs))
        if len(failed) < 2:
            failed.append(1)
            raise RuntimeError("database is locked")
        return read(ctxs)

    runner._limits = broken
    first.release()
    snap = wait_run(client, a, run_a)
    # The turn that gave its place up ended as it would have: the error was not its own.
    assert (snap["runs"][0]["status"], snap["runs"][0]["error"]) == ("completed", None)
    assert wait_run(client, b, run_b)["runs"][0]["status"] == "completed"
    # One read for the whole line each time it is looked at, and a look after the failure.
    assert len(failed) == 2 and set(reads) == {1}
    assert board(client, pid)["running"] == 0 and runner._look_again is None


def test_the_limits_are_read_once_for_the_whole_line(make_client, wait_run, project_dir):
    first = Gate()
    client, model, pid = project(
        make_client, project_dir,
        [first.step(text("A done")), text("B done"), text("C done"), text("D done")],
        max_agents=1)
    runner = client.app.state.runner
    turns = [(cid, go(client, cid)) for cid in [talk(client, pid) for _ in range(4)][:1]]
    first.wait_partial()
    for _ in range(3):
        cid = talk(client, pid)
        turns.append((cid, go(client, cid)))
        queued(client, cid)
    read, reads = runner._limits, []

    def counted(ctxs):
        reads.append(len(ctxs))
        return read(ctxs)

    runner._limits = counted
    assert client.patch(f"/api/projects/{pid}", json={"max_agents": 1}).status_code == 200
    assert reads == [3]                                  # three in line, one read
    first.release()
    for cid, run in turns:
        assert wait_run(client, cid, run)["runs"][0]["status"] == "completed"


# --- nobody is passed by for good, and no place is given back twice ------------------------


class Line:
    """The runner's line with agents that are nothing but where they belong, on the
    app's event loop: a project is its conversation's id in capitals, the limits are
    what the test says (by conversation, by provider), and nothing is written down."""

    def __init__(self, client, projects: dict, providers: dict):
        self.runner, self.ids = client.app.state.runner, itertools.count()
        self.runner._limits = lambda ctxs: (projects, providers)
        self.runner._set_agent = lambda *args, **fields: None

    def one(self, cid, provider, run="r"):
        ctx = SimpleNamespace(agent_id=f"n{next(self.ids)}", run_id=run, cid=cid,
                              root=cid.upper(), provider_id=provider, name="")
        self.runner._ctxs[ctx.agent_id] = ctx
        return ctx

    def arrive(self, cid, provider):
        ctx = self.one(cid, provider)
        self.runner._line_up.append((ctx, asyncio.get_running_loop().create_future()))
        self.runner.let_in()
        return ctx

    def leave(self, ctx):
        self.runner._placed.discard(ctx.agent_id)
        self.runner.let_in()

    def placed(self, ctx) -> bool:
        return ctx.agent_id in self.runner._placed

    def away(self):
        runner = self.runner
        for name in [name for name in runner._ctxs if name.startswith("n")]:
            del runner._ctxs[name]
            runner._placed.discard(name)
            runner._away.discard(name)
        runner._line_up.clear()
        runner._slots.pop("r", None)
        del runner._limits, runner._set_agent


def test_an_agent_that_stands_under_two_limits_is_not_passed_by_for_good(told):
    """What the second review found: project X lets one agent work and provider P one.
    A, of X and on P, is first in line. Whenever X has room P is full, and a later agent
    of X on another provider took the room; whenever P has room X is full, and a later
    agent of another project took P - A was passed by 98 times and never got in. The
    room an agent in line waits for is kept for it: nobody that came later takes it."""
    client, _model = told()

    def work():
        line = Line(client, {"x": 1}, {"p": 1})
        try:
            in_x, on_p = line.arrive("x", "q"), line.arrive("y", "p")
            a = line.arrive("x", "p")
            assert line.placed(in_x) and line.placed(on_p) and not line.placed(a)
            # X has room and P is full: the next agent of X does not take what A waits for.
            line.leave(in_x)
            later = line.arrive("x", "q")
            assert not line.placed(a) and not line.placed(later)
            # Whoever needs none of that room goes in at once: another project on another
            # provider, and a project without a limit (Y) on a provider without one.
            assert line.placed(line.arrive("z", "r")) and line.placed(line.arrive("y", "q"))
            # ...and an agent on P does not take P while A waits for it.
            line.leave(on_p)
            assert line.placed(a) and not line.placed(later)
            assert not line.placed(line.arrive("y", "p"))
            line.leave(a)
            assert line.placed(later)                    # and then the next, in its order
            assert len(line.runner._placed) == 4
        finally:
            line.away()

    on_loop(client, work)


def test_an_agent_under_two_limits_gets_in_whichever_of_them_comes_free_first(told):
    """The same line, and the provider comes free first: A's project is full, so A keeps
    nothing on the provider and one later agent takes it. From the moment its project
    has room A keeps that place and one on the provider, and is in when that one ends."""
    client, _model = told()

    def work():
        line = Line(client, {"x": 1}, {"p": 1})
        try:
            in_x, on_p = line.arrive("x", "q"), line.arrive("y", "p")
            a, passes = line.arrive("x", "p"), line.arrive("y", "p")
            line.leave(on_p)
            assert line.placed(passes) and not line.placed(a)
            line.leave(in_x)
            later = [line.arrive("x", "q"), line.arrive("y", "p")]
            assert not line.placed(a) and not any(line.placed(one) for one in later)
            line.leave(passes)
            assert line.placed(a) and not any(line.placed(one) for one in later)
        finally:
            line.away()

    on_loop(client, work)


def test_an_agent_whose_provider_is_full_keeps_one_place_of_its_project_not_all(told):
    """A project that lets five work does not stand still behind agents whose provider
    is full of another project's: those waiting for one provider keep, together, as many
    of the project's places as that provider lets work - here one, the fifth."""
    client, _model = told()

    def work():
        line = Line(client, {"x": 5}, {"p": 1})
        try:
            on_p = line.arrive("y", "p")
            a, b = line.arrive("x", "p"), line.arrive("x", "p")
            assert line.placed(on_p) and not line.placed(a) and not line.placed(b)
            others = [line.arrive("x", "q") for _ in range(5)]
            assert [line.placed(one) for one in others] == [True, True, True, True, False]
            line.leave(on_p)
            assert line.placed(a) and not line.placed(b)         # five at work, and no more
            assert not line.placed(others[4])
        finally:
            line.away()

    on_loop(client, work)


def test_agents_waiting_for_one_provider_keep_no_more_room_than_it_lets_work(told):
    """What the third review found. A project lets six work, a provider one: an agent of
    the project is at work on it and five more wait for it - each kept a place of the
    project, so the next agent, on another provider, stood in line with five places
    idle. Only one of them can work at a time, and its place comes free with the
    provider's (the agent at work there is the project's own): they keep none."""
    client, _model = told()

    def work():
        line = Line(client, {"x": 6}, {"p": 1})
        try:
            on_p = line.arrive("x", "p")
            waiting = [line.arrive("x", "p") for _ in range(5)]
            assert line.placed(on_p) and not any(line.placed(one) for one in waiting)
            others = [line.arrive("x", "q") for _ in range(6)]
            assert [line.placed(one) for one in others] == [True] * 5 + [False]
            # The place the agent on P leaves is the first one's in line - not a later one's.
            line.leave(on_p)
            assert [line.placed(one) for one in waiting] == [True] + [False] * 4
            assert not line.placed(others[5]) and len(line.runner._placed) == 6
        finally:
            line.away()

    on_loop(client, work)


def test_an_agent_whose_project_is_full_keeps_nobody_off_its_provider(told):
    """What the third review found. Project X lets one agent work, and it is at work;
    W, of X, waits - and kept a place on its provider Q, which lets one work: V, of
    another project, stood in line for Q though nobody worked there, until X's agent
    ended. W cannot use Q while X is full: V goes in at once. Once X has room for W,
    its place there and one on Q are W's, and nobody who comes later takes them."""
    client, _model = told()

    def work():
        line = Line(client, {"x": 1}, {"q": 1})
        try:
            in_x = line.arrive("x", "p")
            w = line.arrive("x", "q")
            v = line.arrive("y", "q")
            assert line.placed(in_x) and not line.placed(w) and line.placed(v)
            line.leave(in_x)
            later = [line.arrive("x", "r"), line.arrive("y", "q")]
            assert not line.placed(w) and not any(line.placed(one) for one in later)
            line.leave(v)
            assert line.placed(w) and not any(line.placed(one) for one in later)
        finally:
            line.away()

    on_loop(client, work)


def test_a_place_another_call_of_the_agent_gave_up_is_not_given_back_a_second_time(told):
    """An agent is let in from the line, and before that call of its wakes another call
    begins to wait and gives the place up - then the turn is stopped. The call that
    stood in line holds nothing any more: the turn's places are as many as they were."""
    client, _model = told()
    done: list = []

    async def stopped_as_it_is_let_in():
        line = Line(client, {"x": 1}, {})
        try:
            runner = line.runner
            other, mine = line.arrive("x", None), line.one("x", None)
            slots = runner._slots["r"] = asyncio.Semaphore(2)
            taking = asyncio.ensure_future(runner._take(mine))
            await asyncio.sleep(0)
            assert [ctx for ctx, _came in runner._line_up] == [mine] and slots._value == 1
            line.leave(other)                            # let in - and not woken yet
            runner._step_aside(mine)                     # another call of its waits
            taking.cancel()                              # Stop
            await asyncio.gather(taking, return_exceptions=True)
            done.append((taking.cancelled(), slots._value, line.placed(mine)))
        except BaseException as exc:
            done.append(exc)
        finally:
            line.away()

    on_loop(client, lambda: asyncio.ensure_future(stopped_as_it_is_let_in()))
    until_true(lambda: done, "the call that stood in line is over")
    assert done == [(True, 2, False)]


# --- an unattended turn's minutes ----------------------------------------------------------


def test_the_minutes_of_an_unattended_turn_do_not_run_while_it_stands_in_line(
    make_client, wait_run, project_dir
):
    """A trigger's turn behind a full project is not stopped as over its minutes before
    its model was asked anything: the clock is put away while none of its agents has a
    place and one stands in line, and goes on with what was left when one has."""
    first = Gate()
    client, model, pid = project(
        make_client, project_dir, [first.step(text("A done")), text("looked")], max_agents=1)
    a, b = talk(client, pid), talk(client, pid)
    run_a = go(client, a)
    first.wait_partial()
    clock = client.app.state.runner.call_later = HeldClock()
    made = trigger(client, pid, b, budget={"steps": 15, "minutes": 7, "per_day": 24})
    run_b = run_now(client, made["id"])
    queued(client, b)
    until_true(lambda: clock.set and all(t.cancelled for t in clock.set),
               "the clock is put away while the turn stands in line")
    assert [t.delay for t in clock.set] == [7 * 60] and len(model.calls) == 1
    first.release()
    assert wait_run(client, a, run_a)["runs"][0]["status"] == "completed"
    snap = wait_run(client, b, run_b)
    assert (snap["runs"][0]["status"], snap["runs"][0]["error"]) == ("completed", None)
    again = clock.set[1]
    assert len(clock.set) == 2 and 7 * 60 - 30 < again.delay <= 7 * 60   # what was left
    until_true(lambda: again.cancelled, "the clock is put away with the turn")


def test_the_minutes_run_on_while_another_agent_of_the_turn_waits_for_a_file(
    make_client, wait_run, project_dir
):
    """The clock is put away only while the turn is kept waiting for room and nothing
    else: with one of its agents in line and another waiting for a file, the minutes
    run - they are what ends a wait for a file in a turn nobody watches (slice 19a)."""
    first = Gate()
    client, model, pid = project(
        make_client, project_dir, [first.step(text("A done")), text("looked")], max_agents=1)
    a, b = talk(client, pid), talk(client, pid)
    run_a = go(client, a)
    first.wait_partial()
    runner = client.app.state.runner
    clock = runner.call_later = HeldClock()
    run_b = run_now(client, trigger(
        client, pid, b, budget={"steps": 15, "minutes": 7, "per_day": 24})["id"])
    queued(client, b)
    until_true(lambda: clock.set and clock.set[-1].cancelled, "put away: it stands in line")

    def held_up(files: int):
        # Another agent of the turn, as `_claim` leaves it while it waits for a file.
        if files:
            runner._ctxs["other"] = SimpleNamespace(run_id=run_b)
            runner._held_up["other"] = files
        else:
            del runner._ctxs["other"], runner._held_up["other"]
        runner._clock(run_b)

    on_loop(client, lambda: held_up(1))
    until_true(lambda: len(clock.set) == 2, "the minutes run: an agent waits for a file")
    assert not clock.set[1].cancelled and clock.set[1].delay <= 7 * 60
    on_loop(client, lambda: held_up(0))
    until_true(lambda: clock.set[1].cancelled, "put away again: only the line is left")
    first.release()
    assert wait_run(client, a, run_a)["runs"][0]["status"] == "completed"
    snap = wait_run(client, b, run_b)
    assert (snap["runs"][0]["status"], snap["runs"][0]["error"]) == ("completed", None)


# --- the user's word is on record at once ---------------------------------------------------


def _a_full_project(make_client, project_dir, first_step, executor=None):
    """A's lead asks for something in ask mode, and B's lead has the one place."""
    held = Gate()
    client, model = make_client(
        {"Lead": [first_step, held.step(text("B done")), text("A done")]}, executor=executor)
    client.headers["Origin"] = ORIGIN
    pid = limited(client, project_dir, 1)
    a, b = talk(client, pid, permission_mode="ask"), talk(client, pid)
    run_a = go(client, a)
    snap = until(client, a, lambda s: s["runs"][0]["status"] == "waiting_approval")
    run_b = go(client, b)
    held.wait_partial()
    return client, held, snap, (a, run_a), (b, run_b)


def _at_once(client, path, **body):
    began = time.monotonic()
    said = client.post(path, **({"json": body} if body else {}))
    assert said.status_code == 200 and time.monotonic() - began < 2, said.text
    return said.json()


def test_a_change_approved_while_the_project_is_full_says_so_and_is_made_once(
    make_client, wait_run, project_dir
):
    client, held, snap, (a, run_a), (b, run_b) = _a_full_project(
        make_client, project_dir, step(write("a.txt", "A")))
    change = snap["file_changes"][0]["id"]
    assert _at_once(client, f"/api/file-changes/{change}/approve")["status"] == "approved"
    # A second click, and a reload: decided, not to be decided again, and not made yet.
    assert client.post(f"/api/file-changes/{change}/approve").status_code == 409
    assert client.post(f"/api/file-changes/{change}/reject").status_code == 409
    snap = queued(client, a)
    assert [c["status"] for c in snap["file_changes"]] == ["approved"]
    assert snap["runs"][0]["status"] == "running" and not (project_dir / "a.txt").exists()
    held.release()
    wait_run(client, b, run_b)
    snap = wait_run(client, a, run_a)
    assert [c["status"] for c in snap["file_changes"]] == ["applied"]
    assert (project_dir / "a.txt").read_text() == "A"
    assert [t["result"] for t in snap["tool_calls"]] == ["applied: a.txt (+1 -0)"]


def test_a_change_rejected_while_the_project_is_full_is_rejected_at_once(
    make_client, wait_run, project_dir
):
    client, held, snap, (a, run_a), (b, run_b) = _a_full_project(
        make_client, project_dir, step(write("a.txt", "A")))
    change = snap["file_changes"][0]["id"]
    assert _at_once(client, f"/api/file-changes/{change}/reject")["status"] == "rejected"
    assert client.post(f"/api/file-changes/{change}/approve").status_code == 409
    queued(client, a)                                    # its lead still needs a place to go on
    held.release()
    snap = wait_run(client, a, run_a)
    assert [c["status"] for c in snap["file_changes"]] == ["rejected"]
    assert snap["runs"][0]["status"] == "completed" and not (project_dir / "a.txt").exists()


def test_an_approved_change_whose_turn_is_stopped_in_line_is_not_left_approved(
    make_client, wait_run, project_dir
):
    """...nor called "rejected", which is the user's own no: it was never made, and when
    the yes was said stays on its record."""
    client, held, snap, (a, run_a), (b, run_b) = _a_full_project(
        make_client, project_dir, step(write("a.txt", "A")))
    change = snap["file_changes"][0]["id"]
    said = _at_once(client, f"/api/file-changes/{change}/approve")
    assert said["status"] == "approved" and said["decided_at"]
    queued(client, a)
    cancel(client, run_a)
    snap = wait_run(client, a, run_a)
    assert snap["runs"][0]["status"] == "cancelled"
    assert [(c["status"], c["decided_at"]) for c in snap["file_changes"]] == [
        ("discarded", said["decided_at"])]
    assert [t["status"] for t in snap["tool_calls"]] == ["interrupted"]
    assert not (project_dir / "a.txt").exists()
    held.release()
    wait_run(client, b, run_b)


def test_a_command_approved_while_the_project_is_full_says_so_and_runs_once(
    make_client, wait_run, project_dir
):
    executor = ScriptedExecutor([Script(["2 passed\n"])])
    client, held, snap, (a, run_a), (b, run_b) = _a_full_project(
        make_client, project_dir, cmd(), executor=executor)
    command_id = snap["commands"][0]["id"]
    said = _at_once(client, f"/api/commands/{command_id}/approve", remember=False)
    assert said["status"] == "approved"
    assert client.post(
        f"/api/commands/{command_id}/approve", json={"remember": False}).status_code == 409
    snap = queued(client, a)
    assert [c["status"] for c in snap["commands"]] == ["approved"] and executor.started == []
    held.release()
    wait_run(client, b, run_b)
    snap = wait_run(client, a, run_a)
    assert [c["status"] for c in snap["commands"]] == ["exited"]
    assert len(executor.started) == 1


def test_a_command_rejected_or_stopped_while_the_project_is_full(
    make_client, wait_run, project_dir
):
    executor = ScriptedExecutor([])
    client, held, snap, (a, run_a), (b, run_b) = _a_full_project(
        make_client, project_dir, cmd(), executor=executor)
    command_id = snap["commands"][0]["id"]
    assert _at_once(client, f"/api/commands/{command_id}/reject")["status"] == "rejected"
    held.release()
    snap = wait_run(client, a, run_a)
    assert [c["status"] for c in snap["commands"]] == ["rejected"] and executor.started == []


@pytest.mark.parametrize("remember", [False, True])
def test_an_approved_command_whose_turn_is_stopped_in_line_never_runs(
    make_client, wait_run, project_dir, remember
):
    """It is not "rejected" - the user said yes: it is interrupted, as its tool call is,
    and never started. And "Always run" is the user's word about later commands: the
    rule is there from the moment it is said, though this command never got its place."""
    executor = ScriptedExecutor([])
    client, held, snap, (a, run_a), (b, run_b) = _a_full_project(
        make_client, project_dir, cmd(), executor=executor)
    command_id = snap["commands"][0]["id"]
    said = _at_once(client, f"/api/commands/{command_id}/approve", remember=remember)
    assert said["status"] == "approved"
    rules = ["pytest"] if remember else []
    snap = queued(client, a)
    assert [rule["prefix"] for rule in snap["allowed_commands"]] == rules
    cancel(client, run_a)
    snap = wait_run(client, a, run_a)
    assert [(c["status"], c["started_at"]) for c in snap["commands"]] == [("interrupted", None)]
    assert [t["status"] for t in snap["tool_calls"]] == ["interrupted"]
    assert [rule["prefix"] for rule in snap["allowed_commands"]] == rules
    assert executor.started == []
    held.release()
    wait_run(client, b, run_b)


def test_a_restart_does_not_call_what_the_user_approved_rejected(tmp_path):
    """The process died with a change and a command approved and their agent in line."""
    db = tmp_path / "r.db"
    upgrade_db(db)
    factory = make_session_factory(make_engine(db))
    seed(factory, tmp_path)
    said_yes = datetime(2026, 10, 11, 9, 0, tzinfo=UTC)
    with factory() as s:
        change = s.get_one(FileChange, "f")
        change.status, change.decided_at = "approved", said_yes
        s.add_all([
            Command(id="yes", run_id="r1", agent_id="a", tool_call_id="t1", command="pytest",
                    location="host", timeout_seconds=60, status="approved"),
            Command(id="asked", run_id="r1", agent_id="a", tool_call_id="t2", command="ls",
                    location="host", timeout_seconds=60, status="proposed"),
        ])
        s.commit()
    recover_interrupted(factory)
    with factory() as s:
        change = s.get_one(FileChange, "f")
        assert (change.status, change.decided_at) == ("discarded", said_yes)
        assert {one.id: (one.status, one.started_at) for one in s.query(Command)} == {
            "yes": ("interrupted", None), "asked": ("rejected", None)}
    assert not (tmp_path / "f.txt").exists()


class NeverStarts(ScriptedExecutor):
    """Its start never comes back: a container being fetched, a working copy being made."""

    def __init__(self):
        super().__init__([])
        self.asked = threading.Event()

    async def start(self, *args, **kwargs):
        self.asked.set()
        await asyncio.Event().wait()


def _asked_in_ask_mode(make_client, project_dir, first_step, executor=None):
    """A lead that asks for something in ask mode, with nothing to stand in line for."""
    client, _model = make_client({"Lead": [first_step, text("done")]}, executor=executor)
    client.headers["Origin"] = ORIGIN
    pid = limited(client, project_dir, 1)
    cid = talk(client, pid, permission_mode="ask")
    run_id = go(client, cid)
    snap = until(client, cid, lambda s: s["runs"][0]["status"] == "waiting_approval")
    return client, pid, cid, run_id, snap


@pytest.mark.parametrize("remember", [False, True])
def test_an_approved_command_whose_start_never_comes_back_is_approved_and_never_rejected(
    make_client, wait_run, project_dir, remember
):
    """What the third review found: no place to wait for, so the yes was not written
    down; the start hung, the approve call answered "proposed" after five seconds, and
    Stop left the command "rejected" - with the rule "Always run" had written."""
    executor = NeverStarts()
    client, pid, cid, run_id, snap = _asked_in_ask_mode(
        make_client, project_dir, cmd(), executor)
    command_id = snap["commands"][0]["id"]
    said = _at_once(client, f"/api/commands/{command_id}/approve", remember=remember)
    assert said["status"] == "approved" and executor.asked.wait(5)
    assert client.post(
        f"/api/commands/{command_id}/approve", json={"remember": False}).status_code == 409
    cancel(client, run_id)
    snap = wait_run(client, cid, run_id)
    assert [(c["status"], c["started_at"]) for c in snap["commands"]] == [("interrupted", None)]
    assert [t["status"] for t in snap["tool_calls"]] == ["interrupted"]
    assert [rule["prefix"] for rule in snap["allowed_commands"]] == (
        ["pytest"] if remember else [])
    nobody_holds_anything(client, pid)


def test_a_command_nobody_is_asked_about_is_not_shown_as_waiting_nor_left_rejected(
    make_client, wait_run, project_dir
):
    """One that runs on a yes given before (here the level, Full auto): while its start
    is waited for it is "approved", not "proposed" with a card whose buttons answer 409 -
    and a turn stopped before it starts leaves it "interrupted": nobody said no."""
    executor = NeverStarts()
    client, _model = make_client({"Lead": [cmd(), text("never said")]}, executor=executor)
    client.headers["Origin"] = ORIGIN
    pid = limited(client, project_dir, 1)
    cid = talk(client, pid)
    run_id = go(client, cid)
    assert executor.asked.wait(5)
    snap = client.get(f"/api/conversations/{cid}").json()
    assert [(c["status"], c["started_at"]) for c in snap["commands"]] == [("approved", None)]
    cancel(client, run_id)
    snap = wait_run(client, cid, run_id)
    assert [(c["status"], c["started_at"]) for c in snap["commands"]] == [("interrupted", None)]
    nobody_holds_anything(client, pid)


def test_a_decision_given_while_the_limits_cannot_be_read_is_not_lost(
    make_client, wait_run, project_dir, monkeypatch
):
    """Whether the agent has to stand in line is read from the limits; if that read
    fails, the user's word - "Always run" too - is on record all the same, and the agent
    stands in line until the limits can be read."""
    monkeypatch.setattr(slots_mixin, "LOOK_AGAIN", 0.05)
    executor = ScriptedExecutor([Script(["2 passed\n"])])
    client, pid, cid, run_id, snap = _asked_in_ask_mode(
        make_client, project_dir, cmd(), executor)
    runner = client.app.state.runner
    read, failed = runner._limits, []

    def broken(ctxs):
        if len(failed) < 2:
            failed.append(1)
            raise RuntimeError("database is locked")
        return read(ctxs)

    runner._limits = broken
    said = _at_once(client, f"/api/commands/{snap['commands'][0]['id']}/approve", remember=True)
    assert said["status"] == "approved"
    snap = wait_run(client, cid, run_id)
    assert len(failed) == 2                              # asked whether it waits, and the line
    assert (snap["runs"][0]["status"], snap["runs"][0]["error"]) == ("completed", None)
    assert [c["status"] for c in snap["commands"]] == ["exited"]
    assert [rule["prefix"] for rule in snap["allowed_commands"]] == ["pytest"]
    nobody_holds_anything(client, pid)


def test_a_request_approved_in_line_and_never_sent_is_not_left_approved(
    make_client, wait_run, project_dir, monkeypatch
):
    """"approved" is what a request that went out is. One whose agent never got its
    place is "interrupted", as its call is - and when the yes was said stays."""
    net = Net(monkeypatch)
    client, held, snap, (a, run_a), (b, run_b) = _a_full_project(
        make_client, project_dir, step(get("https://example.com/x")))
    asked = snap["web_requests"][0]["id"]
    said = _at_once(client, f"/api/web-requests/{asked}/approve", remember=False)
    assert said["status"] == "approved" and said["decided_at"]
    queued(client, a)
    cancel(client, run_a)
    snap = wait_run(client, a, run_a)
    assert [(w["status"], w["decided_at"]) for w in snap["web_requests"]] == [
        ("interrupted", said["decided_at"])]
    assert [t["status"] for t in snap["tool_calls"]] == ["interrupted"] and net.asked == []
    held.release()
    wait_run(client, b, run_b)


def test_a_request_stopped_on_its_way_is_interrupted_and_one_that_went_out_stays_approved(
    make_client, wait_run, project_dir, monkeypatch
):
    net = Net(monkeypatch, {"example.com/a": (200, "text/plain", "ok")})
    answer, on_its_way = app.web.raw, threading.Event()

    async def raw(method, url, *more):
        if url.endswith("/hangs"):
            on_its_way.set()
            await asyncio.Event().wait()
        return await answer(method, url, *more)

    monkeypatch.setattr(app.web, "raw", raw)
    client, _model = make_client({"Lead": [
        step(get("https://example.com/a", "h1")), step(get("https://example.com/hangs", "h2")),
        text("never said")]})
    client.headers["Origin"] = ORIGIN
    pid = limited(client, project_dir, 1)
    cid = talk(client, pid, permission_mode="ask")
    run_id = go(client, cid)
    for count in (1, 2):
        snap = until(client, cid, lambda s, count=count: len(s["web_requests"]) == count
                     and s["web_requests"][-1]["status"] == "proposed")
        said = _at_once(
            client, f"/api/web-requests/{snap['web_requests'][-1]['id']}/approve",
            remember=False)
        assert said["status"] == "approved"
    assert on_its_way.wait(5)
    cancel(client, run_id)
    snap = wait_run(client, cid, run_id)
    assert [w["status"] for w in snap["web_requests"]] == ["approved", "interrupted"]
    assert [t["status"] for t in snap["tool_calls"]] == ["succeeded", "interrupted"]
    assert len(net.asked) == 1


def test_a_restart_does_not_leave_a_request_that_never_went_out_approved(tmp_path):
    """The process died with one request approved and its call not over, another that
    had gone out, and a third nobody had decided on."""
    db = tmp_path / "r.db"
    upgrade_db(db)
    factory = make_session_factory(make_engine(db))
    seed(factory, tmp_path)
    said_yes = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
    with factory() as s:
        s.add_all([
            WebRequest(id=id, run_id="r1", agent_id="a", tool_call_id=call, kind="http",
                       method="GET", target="https://example.com/", host="example.com",
                       status=status, decided_at=said_yes if status == "approved" else None)
            for id, call, status in (
                ("cut", "t1", "approved"), ("sent", "t3", "approved"), ("asked", "t2", "proposed"))
        ])
        s.commit()
    recover_interrupted(factory)
    with factory() as s:
        assert {one.id: one.status for one in s.query(WebRequest)} == {
            "cut": "interrupted", "sent": "approved", "asked": "rejected"}
        assert s.get_one(WebRequest, "cut").decided_at.replace(tzinfo=UTC) == said_yes


def test_a_change_approved_while_its_agents_turn_is_held_is_on_record_at_once(
    make_client, wait_run, project_dir
):
    """Not only a place is waited for before an approved change is made: another agent
    may hold this one's turn (it answers a message, it speaks in a discussion). The
    user's word is on record before that wait too - the answer comes at once, and a
    second click finds it decided."""
    client, model = make_client({"Lead": [step(write("a.txt", "A")), text("done")]})
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    a = talk(client, pid, permission_mode="ask")
    run_a = go(client, a)
    snap = until(client, a, lambda s: s["runs"][0]["status"] == "waiting_approval")
    change = snap["file_changes"][0]["id"]
    turn = on_loop(client, lambda: client.app.state.runner._turn_of(agent(snap, "Lead")["id"]))
    on_loop(client, lambda: asyncio.ensure_future(turn.acquire()))
    until_true(turn.locked, "the lead's turn is held")
    assert _at_once(client, f"/api/file-changes/{change}/approve")["status"] == "approved"
    assert client.post(f"/api/file-changes/{change}/approve").status_code == 409
    assert not (project_dir / "a.txt").exists()
    on_loop(client, turn.release)
    snap = wait_run(client, a, run_a)
    assert [c["status"] for c in snap["file_changes"]] == ["applied"]
    assert snap["runs"][0]["status"] == "completed"


def test_a_question_answered_while_the_project_is_full_is_answered_at_once(
    make_client, wait_run, project_dir
):
    client, held, snap, (a, run_a), (b, run_b) = _a_full_project(
        make_client, project_dir, step(call("ask_user", {"question": "Which one?"}, "q")))
    question = snap["questions"][0]["id"]
    said = _at_once(client, f"/api/questions/{question}/answer", answer="the first")
    assert (said["status"], said["answer"]) == ("answered", "the first")
    assert client.post(
        f"/api/questions/{question}/answer", json={"answer": "no, the second"}
    ).status_code == 409
    snap = queued(client, a)
    assert snap["runs"][0]["status"] == "running"
    held.release()
    snap = wait_run(client, a, run_a)
    assert snap["questions"][0]["answer"] == "the first"
    assert snap["runs"][0]["status"] == "completed"


def test_a_role_decided_while_the_project_is_full_is_off_its_card_at_once(
    make_client, wait_run, project_dir
):
    asks = new_role("Documenter", ["read_file"], description="Docs.")
    client, held, snap, (a, run_a), (b, run_b) = _a_full_project(
        make_client, project_dir, asks)
    call_id = snap["pending_roles"][0]["tool_call_id"]
    _at_once(client, f"/api/tool-calls/{call_id}/approve")
    assert client.post(f"/api/tool-calls/{call_id}/approve").status_code == 409
    snap = queued(client, a)
    assert snap["pending_roles"] == [] and snap["runs"][0]["status"] == "running"
    held.release()
    snap = wait_run(client, a, run_a)
    assert snap["runs"][0]["status"] == "completed"
    assert "Documenter" in [role["name"] for role in client.get("/api/roles").json()]


# --- ending a discussion needs no place ----------------------------------------------------


def test_the_user_ends_a_discussion_whose_speaker_stands_in_line_for_a_place(
    make_client, wait_run, project_dir
):
    speaking, held = Gate(), Gate()
    client, model = make_client({
        "Lead": [TWO, discuss("Go?", ["Coder", "Reviewer"]), held.step(text("B done")),
                 text("Carrying on.")],
        "Coder": [text("coder ready"), speaking.step(text("Yes."))],
        "Reviewer": [text("reviewer ready"), text("never said")],
    })
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    a, b = talk(client, pid, spawn_approval="never"), talk(client, pid)
    run_a = go(client, a)
    speaking.wait_partial()                              # the Coder speaks: one agent at work
    assert client.patch(f"/api/projects/{pid}", json={"max_agents": 1}).status_code == 200
    run_b = go(client, b)
    queued(client, b)                                    # B's lead is first in line
    speaking.release()
    held.wait_partial()                                  # ...and has the place: B's lead works
    snap = until(client, a, lambda s: agent(s, "Reviewer")["status"] == "queued")
    talked = snap["discussions"][0]
    assert talked["status"] == "running" and board(client, pid)["running"] == 1
    assert client.post(f"/api/discussions/{talked['id']}/end").status_code == 200
    # Ended while B's lead still has the one place: nobody waited for it.
    snap = until(client, a, lambda s: s["discussions"][0]["status"] == "ended", timeout=3)
    assert snap["discussions"][0]["outcome"] == "ended_by_user" and not held.released
    assert agent(snap, "Reviewer")["status"] == "completed"   # what it was before its turn
    held.release()
    for cid, run in ((b, run_b), (a, run_a)):
        assert wait_run(client, cid, run, timeout=10)["runs"][0]["status"] == "completed"
    assert len(model.calls_of["Reviewer"]) == 1          # it never got to speak
    nobody_holds_anything(client, pid)


# --- two conversations and one file --------------------------------------------------------


def test_a_wait_that_is_stopped_is_told_to_the_conversation_that_holds_the_file(
    make_client, wait_run, project_dir
):
    """The strip above the holder's conversation is read from the board when it is told
    to look again: it is told when the other conversation begins to wait, and when that
    wait is stopped - nothing the holder holds changed either time."""
    first = Gate()
    client, model, pid = project(
        make_client, project_dir,
        [step(write("a.txt", "A")), first.step(text("A done")), step(write("a.txt", "B"))])
    a, b = talk(client, pid), talk(client, pid)
    run_a = go(client, a)
    first.wait_partial()
    bus = client.app.state.bus
    heard: list[tuple[str, str]] = []
    transient = bus.emit_transient

    def listened(cid, kind, payload):
        heard.append((cid, kind))
        transient(cid, kind, payload)

    bus.emit_transient = listened
    run_b = go(client, b)
    until(client, b, lambda s: s["agents"] and agent(s, "Lead").get("waiting_for"))
    assert heard == [(a, "claims.changed")]
    assert len(board(client, pid)["conflicts"]) == 1
    cancel(client, run_b)
    assert wait_run(client, b, run_b)["runs"][0]["status"] == "cancelled"
    assert heard == [(a, "claims.changed")] * 2
    assert board(client, pid)["conflicts"] == []
    first.release()
    wait_run(client, a, run_a)


def test_the_agent_that_waited_is_told_which_conversation_held_the_file(
    make_client, wait_run, project_dir
):
    first = Gate()
    client, model, pid = project(
        make_client, project_dir,
        [step(write("a.txt", "A")), first.step(text("A done")),
         step(write("a.txt", "B")), text("B done")])
    a, b = talk(client, pid), talk(client, pid)
    run_a = go(client, a)
    first.wait_partial()
    assert client.patch(f"/api/conversations/{a}", json={"title": "The docs"}).status_code == 200
    run_b = go(client, b)
    until(client, b, lambda s: s["agents"] and agent(s, "Lead").get("waiting_for"))
    assert [x["status"] for x in on_board(board(client, pid), b)["agents"]] == ["blocked"]
    first.release()
    wait_run(client, a, run_a)
    snap = wait_run(client, b, run_b)
    (said,) = [t["result"] for t in snap["tool_calls"]]
    assert said.startswith('conflict: Lead (of the conversation "The docs") has finished with')


# --- the migration ---------------------------------------------------------------------------


def test_migration_0031_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0030")

    def columns(conn, table):
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}

    new = {"projects": {"max_agents"}, "providers": {"max_running"},
           "conversations": {"lane"}, "file_changes": {"outside_lane"}}
    with sqlite3.connect(db) as conn:
        assert not any(added & columns(conn, table) for table, added in new.items())
        conn.execute("INSERT INTO projects (id, name, root_path, created_at) "
                     "VALUES ('p', 'p', 'C:/p', '2026-10-11 10:00:00')")
        was = {table: columns(conn, table) for table in new}
    command.upgrade(cfg, "0031")
    with sqlite3.connect(db) as conn:
        assert all(columns(conn, table) == was[table] | added for table, added in new.items())
        # What was there has no limit; a change from before there were lanes was outside none.
        assert conn.execute("SELECT max_agents FROM projects").fetchall() == [(None,)]
        default = next(row[4] for row in conn.execute("PRAGMA table_info(file_changes)")
                       if row[1] == "outside_lane")
        assert default in ("0", "false", "(0)")
        conn.execute("UPDATE projects SET max_agents = 2")
    command.downgrade(cfg, "0030")
    with sqlite3.connect(db) as conn:
        assert {table: columns(conn, table) for table in new} == was
        assert conn.execute("SELECT id, name FROM projects").fetchall() == [("p", "p")]
