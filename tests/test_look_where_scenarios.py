"""k-bakis-yeri P: KOLONİ's look at a recipe's work (a recipe with no Review step of its own, at
Test and review) reads and runs where that work is - the recipe's copy, where the end gate's own
tests ran - never the project, which does not have it yet. A fake model per agent, a scripted
executor."""

import os

import pytest

from app.agent.stronger_mixin import ON_HOLD
from tests.fakes import ScriptedExecutor
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import OWN, teams_of
from tests.test_claim_scenarios import write
from tests.test_parallel import until
from tests.test_proof_end_scenarios import PASS
from tests.test_proof_review_scenarios import BIG, MERGE
from tests.test_recipe_run_scenarios import READY, answer, asked, made
from tests.test_recipes_scenarios import graph
from tests.test_recipes_scenarios import step as part
from tests.test_spawn import begin, call, spawn, step

pytestmark = pytest.mark.no_po

CHECK = "python check.py"
DONE = [text(f"done {i}") for i in range(3)]


def started(make_client, project_dir, mode, reviewer, scripts, **checks):
    """The user's own recipe - one step, Fix it (Coder), no Review step; its Checks step tests and
    reviews (and `checks`) - picked for Web app; its Coder writes a big calc.py; KOLONİ's Reviewer
    as given."""
    executor = ScriptedExecutor(scripts)
    client, model = make_client(
        {
            "Lead": [spawn("Coder", "fix it", "c1"), *DONE],
            "Coder": [step(write("calc.py", BIG)), text("fixed")],
            "Reviewer": reviewer,
        },
        executor=executor,
    )
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    patched = client.patch(f"/api/projects/{pid}", json={"check_command": CHECK}, headers=OWN)
    assert patched.status_code == 200, patched.text
    recipe = made(
        client,
        "Just fix it",
        {
            **graph([part("fix", "Fix it", {"role": "Coder"})], [("start", "fix"), ("fix", "end")]),
            "checks": {"tests": True, "review": True, **checks},
        },
    )
    web = teams_of(client)["Web app"]
    cid, run_id = begin(
        client,
        project_dir,
        mode=mode,
        spawn_approval="never",
        teams_mode="manual",
        teams=[{"team_id": web["id"], "recipe_id": recipe["id"]}],
    )
    return client, executor, cid, run_id


def calls_of(snap, name):
    (agent,) = [a for a in snap["agents"] if a["name"] == name]
    return {t["provider_call_id"]: t for t in snap["tool_calls"] if t["agent_id"] == agent["id"]}


def test_the_look_reads_and_runs_in_the_recipes_copy(make_client, project_dir):
    reads = step(
        call("read_file", {"path": "calc.py"}, "r1"),
        call("run_command", {"command": CHECK}, "r2"),
    )
    client, executor, cid, _run_id = started(
        make_client, project_dir, "auto_edit", [reads, MERGE], [PASS, PASS, PASS]
    )
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"], timeout=20)
    looked = calls_of(snap, "Reviewer")
    # (the file only the copy has: found, not "does not exist")
    assert looked["r1"]["status"] == "succeeded" and "x89 = 89" in looked["r1"]["result"], looked
    assert looked["r2"]["status"] == "succeeded", looked["r2"]
    # (every run - the gate's and the look's own - in the copy; the project untouched)
    here = os.path.realpath(project_dir)
    assert [cmd for cmd, _cwd in executor.started] == [CHECK, CHECK], executor.started
    assert all(os.path.realpath(cwd) != here for _c, cwd in executor.started), executor.started
    assert not (project_dir / "calc.py").exists()
    answer(client, asked(snap), "Take in")
    assert until(client, cid, lambda _s: (project_dir / "calc.py").exists(), timeout=20)


def test_what_the_looks_run_writes_in_the_copy_is_not_taken_in(make_client, project_dir):
    from tests.fakes import Script

    runs = step(call("run_command", {"command": CHECK}, "r2"))
    wrote = Script(PASS.chunks, writes={"htmlcov/index.html": "<html></html>\n"})
    client, executor, cid, _run_id = started(
        make_client, project_dir, "auto_edit", [runs, MERGE], [PASS, wrote, PASS]
    )
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"], timeout=20)
    assert calls_of(snap, "Reviewer")["r2"]["status"] == "succeeded", calls_of(snap, "Reviewer")
    answer(client, asked(snap), "Take in")
    assert until(client, cid, lambda _s: (project_dir / "calc.py").exists(), timeout=20)
    assert not (project_dir / "htmlcov").exists()


def held_rows(snap, run_id):
    return [
        r
        for m in snap["messages"]
        if m["role"] == "checked" and m["run_id"] == run_id
        for r in m["checked"]
    ]


@pytest.mark.parametrize("mode", ["full_auto", "auto_edit"])
def test_work_a_look_still_holds_is_not_taken_in_at_any_level(
    make_client, wait_run, project_dir, mode
):
    from tests.test_proof_review_scenarios import hold

    client, executor, cid, run_id = started(
        make_client,
        project_dir,
        mode,
        [hold("calc.py: the names are wrong")],
        [PASS, PASS, PASS],
        fix_rounds=0,
    )
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    rows = held_rows(snap, run_id)
    (kept,) = [r for r in rows if r["kind"] == "not_taken"]
    assert kept["text"] == f"Not taken in: {ON_HOLD}", rows
    assert kept["reason"] == "on_hold" and kept["merge_id"], kept
    assert not any(READY in q["question"] for q in snap["questions"]), snap["questions"]
    assert not (project_dir / "calc.py").exists()
    # (Fix it says why in KOLONİ's words, by the row's code)
    fixed = client.post(
        f"/api/runs/{run_id}/held/fix",
        json={"merge_id": kept["merge_id"], "reply": "rename them"},
        headers=OWN,
    )
    assert fixed.status_code == 202, fixed.text
    snap = until(client, cid, lambda s: len([m for m in s["messages"] if m["role"] == "user"]) > 1)
    said = [m["content"] for m in snap["messages"] if m["role"] == "user"][-1]
    assert "a look of KOLONİ's still held it" in said and "rename them" in said, said


def held_then_fix_it(
    make_client, wait_run, project_dir, second_look, lower=None, then=None, more=None
):
    """A recipe's big change a look holds (Fix rounds 0: kept, "Not taken in: on hold"), then
    Fix it: its turn's Lead changes one line of it in the kept copy (or does `then`, the agents
    of its turn `more`); the next look as given. `lower(client, pid, cid)`: done before Fix it."""
    from tests.test_proof_review_scenarios import hold

    executor = ScriptedExecutor([PASS for _ in range(10)])
    client, model = make_client(
        {
            "Lead": [spawn("Coder", "fix it", "c1"), text("done 0")],
            "Coder": [step(write("calc.py", BIG)), text("fixed")],
            "Reviewer": [hold("calc.py: the names are wrong"), second_look],
            "Reviewer 2": [second_look],
        },
        executor=executor,
    )
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    client.patch(
        f"/api/projects/{pid}", json={"check_command": CHECK, "fix_rounds": 1}, headers=OWN
    )
    recipe = made(
        client,
        "Just fix it",
        {
            **graph([part("fix", "Fix it", {"role": "Coder"})], [("start", "fix"), ("fix", "end")]),
            "checks": {"tests": True, "review": True, "fix_rounds": 0},
        },
    )
    web = teams_of(client)["Web app"]
    cid, run_id = begin(
        client,
        project_dir,
        mode="full_auto",
        spawn_approval="never",
        teams_mode="manual",
        teams=[{"team_id": web["id"], "recipe_id": recipe["id"]}],
    )
    snap = wait_run(client, cid, run_id)
    (kept,) = [r for r in held_rows(snap, run_id) if r["kind"] == "not_taken"]
    if lower is not None:
        lower(client, pid, cid)
    model.by_agent["Lead"] += then or [step(write("calc.py", FIXED, "w9")), text("renamed it")]
    model.by_agent["Lead"] += DONE
    for name, steps in (more or {}).items():
        model.by_agent.setdefault(name, []).extend(steps)
    client.patch(f"/api/conversations/{cid}", json={"lead_hands_code": False}, headers=OWN)
    went = client.post(
        f"/api/runs/{run_id}/held/fix",
        json={"merge_id": kept["merge_id"], "reply": "rename them"},
        headers=OWN,
    )
    assert went.status_code == 202, went.text
    second = went.json()["run_id"]
    return client, model, cid, second, wait_run(client, cid, second)


FIXED = BIG.replace("x1 = 1", "y1 = 1")


def test_fix_it_on_held_work_looks_at_the_whole_kept_work_and_a_merge_takes_it_in(
    make_client, wait_run, project_dir
):
    client, model, cid, second, snap = held_then_fix_it(make_client, wait_run, project_dir, MERGE)
    assert snap["runs"][-1]["status"] == "completed", snap["runs"][-1]["error"]
    rows = [r["text"] for r in held_rows(snap, second)]
    # (the fix is one line; the look is of the whole kept work, as Take in brings it)
    looks = [a for a in snap["agents"] if a["role_name"] == "Reviewer"]
    assert len(looks) == 2, ([a["name"] for a in looks], rows)
    asked = str(model.calls_of[looks[-1]["name"]][-1])  # (the second turn's look)
    assert "x89 = 89" in asked and "y1 = 1" in asked, asked[-600:]
    assert any(one.startswith("Review: Reviewer") and "MERGE" in one for one in rows), rows
    assert (project_dir / "calc.py").read_bytes() == FIXED.encode()


def test_fix_it_on_held_work_a_hold_keeps_it_held(make_client, wait_run, project_dir):
    from tests.test_proof_review_scenarios import hold

    client, model, cid, second, snap = held_then_fix_it(
        make_client, wait_run, project_dir, hold("calc.py: still wrong")
    )
    assert snap["runs"][-1]["status"] == "completed", snap["runs"][-1]["error"]
    rows = held_rows(snap, second)
    assert any(r["kind"] == "not_taken" and r["reason"] == "on_hold" for r in rows), [
        r["text"] for r in rows
    ]
    assert not (project_dir / "calc.py").exists()


def test_at_the_turns_end_a_hold_after_a_stronger_pass_keeps_the_copy_out(make_client):
    # (`_stronger_at_end`: the Orchestrator's answer changed nothing - the gate is not run again,
    # the stronger model's hand-off and its look may still come; a hold then keeps the work out,
    # as at the gate's end)
    import asyncio

    from app.agent.ctx import Ctx
    from app.agent.proof_mixin import Proof

    client, _model = make_client([])
    runner = client.app.state.runner
    held = Proof()
    held.verdict = "HOLD"
    runner._proofs["r"], runner._resumed["r"], runner._copies["lead"] = held, "lead", object()
    try:
        asyncio.run(runner._stronger_at_end(Ctx("r", "c", "x", "lead", "Lead", (), 0), "completed"))
        assert runner._held_back.get("r") == ON_HOLD
    finally:
        for one in (runner._proofs, runner._resumed, runner._held_back):
            one.pop("r", None)
        runner._copies.pop("lead", None)


def chat_off(client, _pid, cid):
    assert (
        client.patch(
            f"/api/conversations/{cid}", json={"after_change": "off"}, headers=OWN
        ).status_code
        == 200
    )


def no_teams(client, _pid, cid):
    """(The chat's teams set aside: its Lead works as one with none - here, a room.)"""
    said = client.patch(f"/api/conversations/{cid}", json={"teams": []}, headers=OWN)
    assert said.status_code == 200, said.text


def lowered_to_tests_only(client, pid, _cid):
    assert (
        client.patch(
            f"/api/projects/{pid}", json={"after_change": "tests"}, headers=OWN
        ).status_code
        == 200
    )


@pytest.mark.parametrize("lower", [chat_off, lowered_to_tests_only], ids=["chat_off", "tests_only"])
def test_fix_it_on_held_work_keeps_the_held_turns_checks(make_client, wait_run, project_dir, lower):
    # (B2: the Fix it turn has no recipe - its checks would follow the chat's switch or the
    # project's After a change, lowered since; the held work goes in by this gate alone)
    from tests.test_proof_review_scenarios import hold

    client, _model, cid, second, snap = held_then_fix_it(
        make_client, wait_run, project_dir, hold("calc.py: still wrong"), lower=lower
    )
    rows = held_rows(snap, second)
    assert any(r["kind"] == "review" and "HOLD" in r["text"] for r in rows), rows
    assert any(r["kind"] == "not_taken" for r in rows), [r["text"] for r in rows]
    assert not (project_dir / "calc.py").exists()


def test_a_room_in_a_fix_it_turn_takes_none_of_the_held_work_in(make_client, wait_run, project_dir):
    # (B4: a room the Fix it turn's Lead opens works in the kept copy - its end takes nothing in;
    # the turn's end check does, or keeps it held)
    from tests.test_proof_review_scenarios import hold
    from tests.test_room_open_scenarios import open_room

    client, _model, cid, second, snap = held_then_fix_it(
        make_client,
        wait_run,
        project_dir,
        hold("calc.py: still wrong"),
        lower=no_teams,
        then=[open_room(members=("Coder", "Tester")), text("the room is over")],
        more={"Coder": [text("Nothing to add.")], "Tester": [text("Nothing to add.")]},
    )
    assert snap["rooms"], [
        (t["name"], t["status"], (t["result"] or "")[:300])
        for t in snap["tool_calls"]
        if t["run_id"] == second
    ]
    assert not (project_dir / "calc.py").exists()
    assert any(r["kind"] == "not_taken" for r in held_rows(snap, second)), [
        r["text"] for r in held_rows(snap, second)
    ]


class _Unread:
    """A copy KOLONİ cannot read (`changes` fails), or whose put back leaves a file."""

    def __init__(self, left=()):
        self.left = list(left)

    def changes(self):
        if not self.left:
            raise OSError("the copy is gone")
        return []

    def snapshot(self, _keep):
        return {"a.txt": "x"}, {}

    def moved_since(self, _was):
        return list(self.left)

    def put_back(self, _paths, _was, _kept):
        return list(self.left)

    def save(self):
        pass


class _Runner:
    def __init__(self, copy):
        self._ctxs, self._copies = {"lead": object()}, {"lead": copy}

    def _works_in(self, _ctx):
        return "lead"


def test_a_looks_command_runs_only_where_what_it_writes_can_be_put_back():
    # (review: a copy that could not be read first never runs the command unkept; what the put
    # back left is said with its output, never dropped)
    import asyncio

    from app.agent.ctx import Ctx
    from app.agent.review_mixin import ReviewMixin
    from app.tools import ToolError

    look = Ctx("r", "c", "x", "look", "Reviewer", (), 1, parent_id="lead")
    with pytest.raises(ToolError, match="could not read the copy"):
        asyncio.run(ReviewMixin._look_trace(_Unread()))
    left = _Unread(["htmlcov/index.html"])
    trace = asyncio.run(ReviewMixin._look_trace(left))
    said = asyncio.run(ReviewMixin._look_untrace(_Runner(left), look, trace))
    assert "could not put back" in said and "htmlcov/index.html" in said, said


def test_a_tracked_file_the_gates_own_test_run_writes_in_the_copy_is_not_the_work(
    make_client, project_dir
):
    # (CL-345: a test that writes a tracked file - a.txt - run by KOLONİ's end check in the
    # recipe's copy: put back there, never taken in as the work. An agent's own run_command's
    # writes stay its work, by design.)
    from tests.fakes import Script

    (project_dir / "a.txt").write_text("as it was\n", encoding="utf-8")
    wrote = Script(PASS.chunks, writes={"a.txt": "written by a test\n"})
    client, executor, cid, _run_id = started(
        make_client, project_dir, "auto_edit", [MERGE], [wrote, PASS, PASS]
    )
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"], timeout=20)
    answer(client, asked(snap), "Take in")
    assert until(client, cid, lambda _s: (project_dir / "calc.py").exists(), timeout=20)
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "as it was\n", executor.started


def test_two_looks_commands_in_one_copy_leave_neither_ones_report(tmp_path):
    # (S1 of the review: the Reviewer's and the Security reviewer's runs at once - A writes its
    # report, B starts, A puts back, B puts back: B's snapshot held A's report and brought it
    # back as work. One window at a time in a copy, `_copy_lock`: B waits for A's put back.)
    import asyncio
    import contextlib

    from app import copies
    from app.agent.ctx import Ctx
    from app.agent.proof_mixin import ProofMixin
    from app.agent.review_mixin import ReviewMixin

    project, runtime = tmp_path / "proj", tmp_path / "rt"
    project.mkdir()
    runtime.mkdir()
    (project / "calc.py").write_text("x = 1\n", encoding="utf-8")
    copy = copies.make(project, runtime, "two-looks")

    class Runner:
        _ctxs, _copies, _copy_locks = {"lead": object()}, {"lead": copy}, {}
        _works_in = staticmethod(lambda _ctx: "lead")
        _copy_lock = ProofMixin._copy_lock
        _look_kept, _look_untrace = ReviewMixin._look_kept, ReviewMixin._look_untrace
        _look_trace = staticmethod(ReviewMixin._look_trace)

    runner = Runner()
    a = Ctx("r", "c", "x", "rev", "Reviewer", (), 1, parent_id="lead")
    b = Ctx("r", "c", "x", "sec", "Security reviewer", (), 1, parent_id="lead")

    async def both():
        (copy.root / "calc.py").write_text("x = 2  # the work\n", encoding="utf-8")
        a_in, a_go, b_in, b_go = (asyncio.Event() for _ in range(4))

        async def look_a():
            async with runner._look_kept(a, True):
                (copy.root / "report_a.xml").write_text("<a/>\n", encoding="utf-8")
                a_in.set()
                await a_go.wait()

        async def look_b():
            await a_in.wait()
            async with runner._look_kept(b, True):
                (copy.root / "report_b.xml").write_text("<b/>\n", encoding="utf-8")
                b_in.set()
                await b_go.wait()

        first, second = asyncio.ensure_future(look_a()), asyncio.ensure_future(look_b())
        await asyncio.wait_for(a_in.wait(), 30)
        # (B's command starts while A's still goes - or, held to the copy's one window, waits)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(b_in.wait(), 1)
        a_go.set()
        await asyncio.wait_for(first, 30)  # (A puts back first)
        b_go.set()
        await asyncio.wait_for(second, 30)

    try:
        asyncio.run(both())
        assert [path for path, _kind, _state in copy.changes()] == ["calc.py"], copy.changes()
        assert (copy.root / "calc.py").read_text(encoding="utf-8") == "x = 2  # the work\n"
    finally:
        copies.remove(runtime, "two-looks")


def test_a_run_waiting_for_the_machine_holds_up_no_looks_command_in_its_copy(
    make_client, tmp_path, monkeypatch
):
    # (review of k-bakis-yeri's lock: a run of KOLONİ's queued for the app-wide test slot held its
    # copy's lock all the while - every command of a look there, a `cat` too, waited behind it.
    # The window is taken once the run has the machine.)
    import asyncio

    from app import copies
    from app.agent.ctx import Ctx
    from app.agent.proof_later_mixin import Check, Slots
    from app.agent.proof_mixin import Proof
    from app.proof import TestRun

    client, _model = make_client([])
    runner = client.app.state.runner
    project, runtime = tmp_path / "proj", tmp_path / "rt"
    project.mkdir()
    runtime.mkdir()
    (project / "calc.py").write_text("x = 1\n", encoding="utf-8")
    copy = copies.make(project, runtime, "waits")
    lead = Ctx("r", "c", str(project), "lead", "Lead", (), 0)
    look = Ctx("r", "c", str(project), "look", "Reviewer", (), 1, parent_id="lead")
    ran = []

    async def run_in_copy(_ctx, ws, _line, _call_id, **more):
        await more["where"]({})  # (waits for the machine, as `_run_in_copy` does)
        ran.append(ws.root)
        return 0, "1 passed in 0.1s\n", "exit code 0", "exited"

    async def nothing(*_args, **_more):
        return None

    for name, value in {
        "_record_calls": lambda *_args: [("call1", {})],
        "_set_call": lambda *_args, **_more: None,
        "_sources_now": nothing,
        "_changed_said": nothing,
        "_always_kept": lambda *_args: None,
        "_timeout_on_record": lambda *_args: None,
        "_run_in_copy": run_in_copy,
    }.items():
        monkeypatch.setattr(runner, name, value)
    runner._copies["lead"], runner._ctxs["lead"], runner._recipe_copy["r"] = copy, lead, "lead"

    async def both():
        slot = Slots(1)
        await slot.acquire()  # (another run has the machine)
        check = Check("r", "c", "p", "tests", "pytest -q", ".", None)
        going = asyncio.ensure_future(
            runner._run_tests_now(
                lead, TestRun("pytest -q", ".", True), "run", Proof(), None, "m", check, (slot, 1)
            )
        )
        await asyncio.wait_for(check.started, 10)  # (past its card, waiting for the machine)
        async with asyncio.timeout(5):  # (the look's command goes on at once)
            async with runner._look_kept(look, True):
                pass
        slot.release()
        await asyncio.wait_for(going, 10)

    try:
        asyncio.run(both())
        assert ran == [copy.root]
    finally:
        for one in (runner._copies, runner._ctxs):
            one.pop("lead", None)
        runner._recipe_copy.pop("r", None)
        copies.remove(runtime, "waits")


def test_a_runs_window_waits_no_longer_than_its_wait_and_lets_go_of_the_lock_it_took(tmp_path):
    # (review of k-onceki-017: a run that had the app-wide slot waited for its copy's window with
    # no bound - every other run of KOLONİ's stood behind a look's long command; and its window was
    # let go by the lock its key found then, which a junction's path could make another one)
    import asyncio

    from app import copies
    from app.agent.proof_mixin import SLOT_BUSY, ProofMixin
    from app.tools import ToolError

    project, runtime = tmp_path / "proj", tmp_path / "rt"
    project.mkdir()
    runtime.mkdir()
    (project / "calc.py").write_text("x = 1\n", encoding="utf-8")
    copy = copies.make(project, runtime, "window")

    class Runner:
        _copy_locks: dict = {}
        _copy_lock = ProofMixin._copy_lock
        _window_open, _window_close = ProofMixin._window_open, ProofMixin._window_close

        async def _tests_put_back(self, *_args):
            return None

    runner = Runner()

    async def go():
        held = runner._copy_lock(copy)
        await held.acquire()  # (a look's command in the copy)
        taken: list[bool] = []
        with pytest.raises(ToolError, match=SLOT_BUSY):
            await runner._window_open(copy, {}, 0.05, taken)
        assert taken == [False] and held.locked()
        held.release()
        look: dict = {}
        await runner._window_open(copy, look, 5, [])
        runner._copy_locks.clear()  # (its path reads another way now: another key, another lock)
        await runner._window_close(copy, look)
        assert not held.locked()

    try:
        asyncio.run(go())
    finally:
        copies.remove(runtime, "window")
