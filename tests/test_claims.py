"""File claims beyond the acceptance set (slice 19a): the table by itself, and every place
the runner takes, waits for and lets go of a file.

The table (`app.claims`) is pure: no database, nothing waited for. The rest runs whole
turns on the scripted model; an agent is held at a step with a `Gate`.
"""

import asyncio
import json
import os

import pytest

from app.agent import AgentRunner, recover_interrupted
from app.claims import Claims, place
from app.db.models import Agent, Conversation, Project, Run
from app.db.session import make_engine, make_session_factory, upgrade_db
from app.model_client import ModelUnavailable
from tests.conftest import Gate
from tests.test_chat_flow import text
from tests.test_claim_scenarios import agent, calls, two, waits, write
from tests.test_claude_native import WRITE as CLAUDE_WRITE
from tests.test_claude_native import claude_app, hello  # noqa: F401  (a fixture)
from tests.test_claude_native import start as start_on
from tests.test_native_agent import native_app  # noqa: F401  (a fixture)
from tests.test_parallel import until
from tests.test_spawn import call, step
from tests.test_trigger_scenarios import run_now, trigger
from tests.test_triggers import HeldClock, on_loop

ORIGIN = "http://127.0.0.1:8790"
ROOT = "proj"


# --- the table by itself ------------------------------------------------------------------


@pytest.fixture
def root(tmp_path):
    folder = tmp_path / ROOT
    folder.mkdir()
    return folder


def test_a_free_file_is_taken_and_then_held_against_another_agent(root):
    table = Claims()
    assert table.take(root, "a.txt", "one") is None
    assert table.take(root, "a.txt", "one") is None          # its own already
    assert table.take(root, "a.txt", "two") == "one"         # held: nothing is taken
    assert table.holder(root, "a.txt") == "one"
    assert table.take(root, "b.txt", "two") is None          # another file does not wait
    assert table.of(root) == [("a.txt", "one"), ("b.txt", "two")]
    assert table.held_by("one") == ["a.txt"] and table.held_by("two") == ["b.txt"]


def test_waiters_get_the_file_in_the_order_they_came(root):
    table = Claims()
    table.take(root, "a.txt", "one")
    told: list[str] = []
    second = table.wait(root, "a.txt", "two", changed=lambda: told.append("two"))
    third = table.wait(root, "a.txt", "three", changed=lambda: told.append("three"))
    fourth = table.wait(root, "a.txt", "four", changed=lambda: told.append("four"))
    assert [w.holder for w in (second, third, fourth)] == ["one"] * 3

    assert table.release("one") == [second, third, fourth]
    assert (second.state, third.state, fourth.state) == ("held", "waiting", "waiting")
    assert table.holder(root, "a.txt") == "two"
    assert (third.holder, fourth.holder) == ("two", "two")   # whom they wait for now
    assert told == ["two", "three", "four"]                  # each was told

    table.release("two")
    assert (third.state, fourth.state, fourth.holder) == ("held", "waiting", "three")
    table.release("three")
    assert fourth.state == "held" and table.of(root) == [("a.txt", "four")]
    table.release("four")
    assert table.of(root) == [] and table.holder(root, "a.txt") is None


def test_an_agent_that_stops_waiting_is_not_given_the_file(root):
    table = Claims()
    table.take(root, "a.txt", "one")
    second = table.wait(root, "a.txt", "two")
    third = table.wait(root, "a.txt", "three")
    table.leave(second)
    table.release("one")
    assert (second.state, third.state) == ("waiting", "held")
    assert table.holder(root, "a.txt") == "three"
    assert table.waiting("two") == []


def test_an_agent_that_ends_while_it_waits_is_out_of_the_line(root):
    table = Claims()
    table.take(root, "a.txt", "one")
    table.wait(root, "a.txt", "two")
    table.release("two")                                      # stopped while it waited
    table.release("one")
    assert table.of(root) == []


def test_an_agent_takes_without_waiting_a_file_held_above_it_in_its_own_line(root):
    table = Claims()
    table.take(root, "a.txt", "lead")
    assert table.take(root, "a.txt", "coder", line=("lead",)) is None
    assert table.holder(root, "a.txt") == "coder"
    # a grandchild, from the agent it works for or from the one above that
    assert table.take(root, "a.txt", "helper", line=("coder", "lead")) is None
    assert table.take(root, "b.txt", "lead") is None
    assert table.take(root, "b.txt", "helper", line=("coder", "lead")) is None
    assert table.of(root) == [("a.txt", "helper"), ("b.txt", "helper")]
    # when it ends the file stays with the agent above it
    table.release("helper")
    assert table.of(root) == [("a.txt", "coder"), ("b.txt", "lead")]
    table.release("coder")
    assert table.of(root) == [("a.txt", "lead"), ("b.txt", "lead")]
    # an agent that is not of the line waits, as for any other
    assert table.take(root, "a.txt", "stranger") == "lead"
    assert table.take(root, "a.txt", "stranger", line=("someone else",)) == "lead"


def test_a_sibling_does_not_get_its_siblings_file_through_the_agent_both_work_for(root):
    table = Claims()
    table.take(root, "a.txt", "lead")
    assert table.take(root, "a.txt", "coder", line=("lead",)) is None
    # the lead is above the second one too - but the file is the first one's now
    assert table.take(root, "a.txt", "coder 2", line=("lead",)) == "coder"
    wait = table.wait(root, "a.txt", "coder 2", line=("lead",))
    table.release("coder")
    # the first is done: the file is the lead's again, which the second may take over
    assert wait.state == "held" and table.holder(root, "a.txt") == "coder 2"
    table.release("coder 2")
    assert table.of(root) == [("a.txt", "lead")]


def test_a_file_that_goes_back_up_is_still_waited_for_by_an_agent_outside_the_line(root):
    table = Claims()
    table.take(root, "a.txt", "lead")
    table.take(root, "a.txt", "coder", line=("lead",))
    told = []
    stranger = table.wait(root, "a.txt", "stranger", changed=lambda: told.append(1))
    assert stranger.holder == "coder"
    table.release("coder")
    assert (stranger.state, stranger.holder, told) == ("waiting", "lead", [1])
    table.release("lead")
    assert stranger.state == "held"


def test_an_agents_own_sub_agent_is_not_kept_behind_someone_waiting_for_that_agent(root):
    """Strictly in order this would never end: the lead waits for its second sub-agent,
    which would wait behind a stranger, who waits for the lead."""
    table = Claims()
    table.take(root, "a.txt", "lead")
    table.take(root, "a.txt", "coder", line=("lead",))
    stranger = table.wait(root, "a.txt", "stranger")
    second = table.wait(root, "a.txt", "coder 2", line=("lead",))
    table.release("coder")
    assert (stranger.state, second.state) == ("waiting", "held")
    assert stranger.holder == "coder 2"
    table.release("coder 2")
    table.release("lead")
    assert stranger.state == "held"


def test_two_agents_that_would_wait_for_each_other_are_found(root):
    table = Claims()
    table.take(root, "a.txt", "one")
    table.take(root, "b.txt", "two")
    assert table.cycle("one", "two") is None                  # nobody waits yet
    table.wait(root, "b.txt", "one")
    assert table.cycle("two", "one") == ("one", "two")       # one waits for two already


def test_a_cycle_of_three_is_found(root):
    table = Claims()
    for name, file in (("one", "a.txt"), ("two", "b.txt"), ("three", "c.txt")):
        table.take(root, file, name)
    table.wait(root, "b.txt", "one")                          # one -> two
    assert table.cycle("two", "three") is None
    table.wait(root, "c.txt", "two")                          # two -> three
    assert table.cycle("three", "one") == ("one", "two", "three")
    assert table.cycle("four", "one") is None                 # a fourth just waits


def test_a_cycle_through_an_agent_waiting_for_its_sub_agent_is_found(root):
    """The lead holds a.txt and waits for its sub-agent; the sub-agent waits for b.txt,
    which a stranger holds; the stranger must not wait for a.txt."""
    table = Claims()
    table.take(root, "a.txt", "lead")
    table.take(root, "b.txt", "stranger")
    table.awaiting("lead", "coder")
    table.wait(root, "b.txt", "coder", line=("lead",))
    assert table.cycle("stranger", "lead") == ("lead", "coder", "stranger")
    table.returned("lead", "coder")
    assert table.cycle("stranger", "lead") is None            # the sub-agent is back
    # counted: asked for twice, it is back when both are
    table.awaiting("lead", "coder")
    table.awaiting("lead", "coder")
    table.returned("lead", "coder")
    assert table.cycle("stranger", "lead") is not None


def test_a_waiter_left_waiting_for_an_agent_that_waits_for_it_is_told_at_once(root):
    """The file goes back to the agent its holder had it from - and that agent waits for
    the waiter: it is refused then, not left waiting for ever."""
    table = Claims()
    table.take(root, "a.txt", "lead")
    table.take(root, "a.txt", "coder", line=("lead",))
    table.take(root, "b.txt", "stranger")
    waits_for_a = table.wait(root, "a.txt", "stranger")       # stranger -> coder
    table.wait(root, "b.txt", "lead")                         # lead -> stranger
    table.release("coder")
    assert (waits_for_a.state, waits_for_a.through) == ("refused", ("lead", "stranger"))
    assert table.waiting("stranger") == []


def test_a_waiter_is_told_when_a_sub_agent_takes_the_file_from_the_agent_it_waits_for(root):
    """The one that counts for everyone else is the last to have taken the file: whoever
    waits is waiting for that one from then on, and is told so."""
    table = Claims()
    table.take(root, "a.txt", "lead")
    told = []
    stranger = table.wait(root, "a.txt", "stranger",
                          changed=lambda: told.append(stranger.holder))
    assert table.take(root, "a.txt", "coder", line=("lead",)) is None
    assert (stranger.state, stranger.holder, told) == ("waiting", "coder", ["coder"])
    table.take(root, "a.txt", "coder", line=("lead",))        # its own already: nothing new
    assert told == ["coder"]
    table.release("coder")
    assert (stranger.holder, told) == ("lead", ["coder", "lead"])


def test_a_waiter_is_refused_when_the_sub_agent_that_takes_the_file_waits_for_it(root):
    table = Claims()
    table.take(root, "a.txt", "lead")
    table.take(root, "b.txt", "stranger")
    waits_for_a = table.wait(root, "a.txt", "stranger")       # stranger -> lead
    table.awaiting("coder", "helper")
    table.wait(root, "b.txt", "helper", line=("coder", "lead"))   # coder -> helper -> stranger
    assert table.take(root, "a.txt", "coder", line=("lead",)) is None
    assert (waits_for_a.state, waits_for_a.through) == (
        "refused", ("coder", "helper", "stranger"))


@pytest.mark.skipif(os.name != "nt", reason="only Windows drops them from a name")
def test_a_dot_or_a_space_at_the_end_of_a_name_is_the_same_file_where_windows_drops_it(root):
    (root / "sub").mkdir()
    for form in ("new.txt.", "new.txt ", "new.txt. .", "NEW.TXT.."):
        assert place(root, form)[0] == place(root, "new.txt")[0], form
    assert place(root, "sub./new.txt")[0] == place(root, "sub/new.txt")[0]
    assert place(root, "new.txt")[0] != place(root, "new.tx")[0]
    table = Claims()
    assert table.take(root, "new.txt", "one") is None
    assert table.take(root, "new.txt.", "two") == "one"       # not a second file to write


def test_however_a_path_is_written_it_is_one_file(root):
    (root / "sub").mkdir()
    same = {place(root, form)[0] for form in ("a.txt", "./a.txt", "A.TXT", "sub/../a.txt")}
    assert same == {(str(root.resolve()).casefold(), "a.txt")}
    assert place(root, "./a.txt")[1] == "a.txt"               # and it is shown plainly
    assert place(root, "sub/b.txt")[0] == place(root, "SUB/B.txt")[0]
    if os.sep == "\\":  # where a backslash parts folders
        assert place(root, "sub\\b.txt")[0] == place(root, "sub/b.txt")[0]
    assert place(root, "a.txt")[0] != place(root, "b.txt")[0]
    table = Claims()
    table.take(root, "./A.TXT", "one")
    assert table.take(root, "a.txt", "two") == "one"
    assert table.holder(root, "sub/../a.txt") == "one"


def test_a_path_outside_the_project_is_nobodys_to_hold(root, tmp_path):
    outside = (tmp_path / "elsewhere.txt").as_posix()
    for path in ("../elsewhere.txt", outside, "", "   ", ".", None, 7):
        assert place(root, path) is None
    table = Claims()
    assert table.take(root, "../elsewhere.txt", "one") is None   # not a claim at all
    assert table.take(root, "../elsewhere.txt", "two") is None
    assert table.of(root) == [] and table.held_by("one") == []


def test_two_projects_do_not_share_a_file_by_its_name(root, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    table = Claims()
    assert table.take(root, "a.txt", "one") is None
    assert table.take(other, "a.txt", "two") is None
    assert table.of(root) == [("a.txt", "one")] and table.of(other) == [("a.txt", "two")]
    assert table.holder(other, "a.txt") == "two"


# --- whole turns ------------------------------------------------------------------------------

WRITER = ["list_dir", "read_file", "search", "write_file", "edit_file", "post_note"]


def held(gate, outcome):
    """A model step held at the gate, that then returns `outcome` - or raises it."""
    async def wait(on_delta):
        gate._partial_seen.set()
        while not gate.released:
            await asyncio.sleep(0.01)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return wait


def spawn(role, id="s"):
    return step(call("spawn_agent", {"role": role, "task": "work"}, id))


def read(path, id="r"):
    return step(call("read_file", {"path": path}, id))


def edit(old, new, id="e", path="hello.py"):
    return step(call("edit_file", {"path": path, "old_string": old, "new_string": new}, id))


def start(client, cid, **settings):
    # (the Lead writes itself in these tests: slice 48's default is off)
    settings = {"permission_mode": "full_auto", "spawn_approval": "never",
                "spawn_max_parallel": 2, "lead_hands_code": False, **settings}
    assert client.patch(f"/api/conversations/{cid}", json=settings,
                        headers={"Origin": ORIGIN}).status_code == 200  # the level is raised
    return client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()[
        "run"]["id"]


def snapshot(client, cid):
    return client.get(f"/api/conversations/{cid}").json()


def own_claims(snap):
    """The files this conversation's own agents hold. (A snapshot has the project's: an
    agent of another conversation that waited for one holds it from then on, and - since
    slice 19b - until what it changed in its working copy is in the project.)"""
    mine = {a["id"] for a in snap["agents"]}
    return [claim for claim in snap["claims"] if claim["agent_id"] in mine]


def said_first(result):
    """A write's result without what an agent is told once about its working copy."""
    status, said = result
    return status, said.split("\n")[0]


def two_conversations(make_client, project_dir, scripts, other_dir=None):
    """An app with two conversations - of one project, or of two. The leads share the
    scripted steps named "Lead" (first come, first served), so a test gives each lead a
    sub-agent of a name of its own to do the work: a Coder in one, a Writer in the other."""
    client, model = make_client(scripts)
    client.headers["Origin"] = ORIGIN
    made = client.post("/api/roles", json={"name": "Writer", "tools": WRITER})
    assert made.status_code == 201, made.text
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    there = pid if other_dir is None else client.post(
        "/api/projects", json={"root_path": str(other_dir)}).json()["id"]
    first = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    second = client.post(f"/api/projects/{there}/conversations").json()["id"]
    for cid in (first, second):  # (the leads write themselves: slice 48's default is off)
        assert client.patch(f"/api/conversations/{cid}",
                            json={"lead_hands_code": False}).status_code == 200
    return client, model, first, second


LEADS = [spawn("Coder"), spawn("Writer"), text("done"), text("done")]


def test_two_conversations_of_one_project_wait_for_each_other(
    make_client, wait_run, project_dir
):
    gate = Gate()
    client, model, first, second = two_conversations(make_client, project_dir, {
        "Lead": list(LEADS),
        "Coder": [step(write("shared.txt", "one")), gate.step(text("A done"))],
        "Writer": [step(write("shared.txt", "two")), text("B done")],
    })
    one = start(client, first)
    gate.wait_partial()
    other = start(client, second)
    snap = until(client, second, lambda s: waits(s, "Writer") is not None)
    assert waits(snap, "Writer") == ("Coder", "shared.txt")
    holder = agent(snapshot(client, first), "Coder")["id"]
    # the holder is an agent of the other conversation: both are told who holds the file
    assert snap["claims"] == [{"path": "shared.txt", "agent_id": holder}]
    assert agent(snap, "Writer")["waiting_for"]["agent_id"] == holder
    assert snapshot(client, first)["claims"] == snap["claims"]
    gate.release()
    wait_run(client, first, one)
    snap = wait_run(client, second, other)
    ((status, said),) = calls(snap, "Writer", "write_file")
    # the Writer never read the file: it is not told that it did - and it is told which
    # conversation the agent it waited for was of (it was not its own)
    assert status == "failed" and said == (
        'conflict: Coder (of the conversation "go") has finished with shared.txt, and you '
        "have not read it as it is now; read it again, then make your change")
    assert (project_dir / "shared.txt").read_text(encoding="utf-8") == "one"
    assert snap["claims"] == [] and snapshot(client, first)["claims"] == []


def test_two_projects_do_not_wait_for_each_other(make_client, wait_run, project_dir, tmp_path):
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    gate = Gate()
    client, model, first, second = two_conversations(make_client, project_dir, {
        "Lead": list(LEADS),
        "Coder": [step(write("shared.txt", "one")), gate.step(text("A done"))],
        "Writer": [step(write("shared.txt", "two")), text("B done")],
    }, other_dir=other_dir)
    one = start(client, first)
    gate.wait_partial()
    snap = wait_run(client, second, start(client, second))    # done while the Coder holds
    assert calls(snap, "Writer", "write_file")[0][0] == "succeeded"
    assert (other_dir / "shared.txt").read_text(encoding="utf-8") == "two"
    # each project is told of its own files only
    assert [c["path"] for c in snapshot(client, first)["claims"]] == ["shared.txt"]
    assert agent(snapshot(client, first), "Coder")["status"] == "running"
    gate.release()
    wait_run(client, first, one)


def _boom(*_args, **_kwargs):
    raise RuntimeError("a tool broke")


ENDINGS = {
    # how the holder's work ends -> (what it does after the gate, how it ends)
    "completed": ([text("A done")], "completed"),
    "failed": ([ModelUnavailable("the model is gone")], "failed"),
    "step limit": ([read("hello.py", f"r{n}") for n in range(30)], "failed"),
    "an exception in a tool": ([step(call("post_note", {"note": "x"}, "n"))], "failed"),
    "stopped": ([], "cancelled"),
}


@pytest.mark.parametrize("how", list(ENDINGS))
def test_however_an_agent_ends_its_files_are_free_and_the_waiter_goes_on(
    make_client, wait_run, project_dir, monkeypatch, how
):
    after, ended = ENDINGS[how]
    if how == "an exception in a tool":
        monkeypatch.setattr(AgentRunner, "_post_note", _boom)
    gate = Gate()
    first_after = after[0] if after else text("never said")
    client, model, first, second = two_conversations(make_client, project_dir, {
        "Lead": list(LEADS),
        "Coder": [step(write("shared.txt", "one")), held(gate, first_after), *after[1:]],
        "Writer": [step(write("shared.txt", "two")), text("B done")],
    })
    one = start(client, first)
    gate.wait_partial()
    other = start(client, second)
    until(client, second, lambda s: waits(s, "Writer") is not None)
    if how == "stopped":
        assert client.post(f"/api/runs/{one}/cancel").status_code in (200, 202)
    else:
        gate.release()
    snap = wait_run(client, first, one, timeout=15)
    gate.release()
    assert agent(snap, "Coder")["status"] == ended, agent(snap, "Coder")
    if how == "step limit":
        assert agent(snap, "Coder")["error"] == "step_limit"
    if ended == "failed":
        # B-322: what an agent that failed had changed is not taken unasked; it waits as a
        # kept copy, which holds no file (tests/test_copy_scenarios.py).
        assert [m["status"] for m in snap["merges"]] == ["kept"]
    assert own_claims(snap) == []
    snap = wait_run(client, second, other, timeout=15)
    assert snap["runs"][-1]["status"] == "completed"
    ((status, said),) = calls(snap, "Writer", "write_file")
    if ended == "completed":
        assert status == "failed" and "read it again" in said  # it went on, and looked first
    else:
        # Nothing of the Coder is in the project: there is no file to look at again, and
        # the waiter's own is written.
        assert status == "succeeded"
    assert snap["claims"] == [] and waits(snap, "Writer") is None
    assert all(a["status"] != "blocked" for a in snap["agents"])
    assert (project_dir / "shared.txt").read_text(encoding="utf-8") == (
        "one" if ended == "completed" else "two")


def test_a_file_is_free_as_soon_as_the_sub_agent_that_held_it_is_done(
    make_client, wait_run, project_dir
):
    """Not only when the whole turn is over: the lead is still at work."""
    gate = Gate()
    client, model, first, second = two_conversations(make_client, project_dir, {
        "Lead": [spawn("Coder"), gate.step(text("done"))],
        "Coder": [step(write("shared.txt", "one")), text("A done")],
    })
    run_id = start(client, first)
    gate.wait_partial()
    snap = snapshot(client, first)
    assert agent(snap, "Coder")["status"] == "completed" and snap["claims"] == []
    assert client.app.state.runner.claims.of(project_dir) == []
    gate.release()
    wait_run(client, first, run_id)


def test_a_lead_holds_its_files_until_its_turn_is_over_and_a_declined_sub_agent_changes_nothing(
    make_client, wait_run, project_dir
):
    gate = Gate()
    client, model, first, second = two_conversations(make_client, project_dir, {
        "Lead": [step(write("shared.txt", "lead")), spawn("Coder"), spawn("Writer"),
                 gate.step(text("done")), text("done")],
        "Writer": [step(write("shared.txt", "two")), text("B done")],
    })
    one = start(client, first, spawn_approval="always")
    proposed = until(client, first, lambda s: any(
        a["status"] == "proposed" for a in s["agents"]))
    other = start(client, second)
    snap = until(client, second, lambda s: waits(s, "Writer") is not None)
    assert waits(snap, "Writer") == ("Lead", "shared.txt")
    declined = next(a for a in proposed["agents"] if a["status"] == "proposed")
    assert client.post(f"/api/agents/{declined['id']}/reject").status_code == 200
    gate.wait_partial()                                        # the lead went on
    snap = snapshot(client, first)
    assert agent(snap, "Coder")["status"] == "rejected"
    assert [c["path"] for c in snap["claims"]] == ["shared.txt"]   # still the lead's
    gate.release()
    snap = wait_run(client, first, one)
    assert own_claims(snap) == []
    snap = wait_run(client, second, other)
    assert snap["claims"] == [] and waits(snap, "Writer") is None


def test_a_turn_over_its_budget_lets_go_of_its_files(make_client, wait_run, project_dir):
    """An unattended turn that may change files, stopped for taking more steps than it
    has: the agent of another conversation that waited for its file goes on."""
    gate = Gate()
    client, model, first, second = two_conversations(make_client, project_dir, {
        "Lead": [step(write("shared.txt", "one")), held(gate, read("hello.py")),
                 spawn("Writer"), text("done")],
        "Writer": [step(write("shared.txt", "two")), text("B done")],
    })
    pid = snapshot(client, first)["conversation"]["project_id"]
    made = trigger(client, pid, first,
                   permissions={"write": True, "commands": [], "agents": 0},
                   budget={"steps": 2, "minutes": 10, "per_day": 24})
    one = run_now(client, made["id"])
    gate.wait_partial()
    other = start(client, second)
    snap = until(client, second, lambda s: waits(s, "Writer") is not None)
    assert waits(snap, "Writer") == ("Lead", "shared.txt")
    gate.release()
    snap = wait_run(client, first, one, timeout=15)
    run = next(r for r in snap["runs"] if r["id"] == one)
    assert run["status"] == "failed" and run["error"].startswith("budget: stopped after 2")
    assert own_claims(snap) == []
    snap = wait_run(client, second, other, timeout=15)
    assert calls(snap, "Writer", "write_file")[0][0] == "failed"
    assert snap["claims"] == [] and waits(snap, "Writer") is None


def test_a_wait_in_a_turn_nobody_watches_is_not_a_wait_for_a_person_and_its_minutes_end_it(
    make_client, wait_run, project_dir
):
    gate = Gate()
    client, model, first, second = two_conversations(make_client, project_dir, {
        "Lead": [spawn("Coder"), step(write("shared.txt", "two")), text("done"), text("x")],
        "Coder": [step(write("shared.txt", "one")), gate.step(text("A done"))],
    })
    one = start(client, first)
    gate.wait_partial()
    clock = client.app.state.runner.call_later = HeldClock()
    pid = snapshot(client, second)["conversation"]["project_id"]
    made = trigger(client, pid, second,
                   permissions={"write": True, "commands": [], "agents": 0},
                   budget={"steps": 15, "minutes": 7, "per_day": 24})
    other = run_now(client, made["id"])
    snap = until(client, second, lambda s: waits(s, "Lead") is not None)
    assert waits(snap, "Lead") == ("Coder", "shared.txt")
    # it waits for an agent: not refused as something to ask about, and the turn is not
    # one that waits for the user
    assert agent(snap, "Lead")["status"] == "blocked"
    assert calls(snap, "Lead", "write_file") == [("running", "")]
    assert snap["runs"][-1]["status"] == "running"
    (timer,) = clock.set
    on_loop(client, timer.fire)                                # seven minutes are over
    snap = wait_run(client, second, other, timeout=15)
    run = snap["runs"][-1]
    assert run["status"] == "failed" and run["error"].startswith("budget: stopped after 7 min")
    assert waits(snap, "Lead") is None and agent(snap, "Lead")["status"] == "failed"
    # nothing was written: the waiter's change was not made, and the Coder's is in its
    # working copy until its work is over (slice 19b)
    assert not (project_dir / "shared.txt").exists()
    # the one it waited for holds the file as before
    assert [c["path"] for c in snapshot(client, first)["claims"]] == ["shared.txt"]
    gate.release()
    wait_run(client, first, one)


def test_a_restart_leaves_nobody_waiting_and_nothing_held(tmp_path):
    db = tmp_path / "r.db"
    upgrade_db(db)
    factory = make_session_factory(make_engine(db))
    waiting_for = {"agent_id": "a", "agent_name": "Coder", "path": "shared.txt"}
    with factory() as s:
        s.add(Project(id="p", name="p", root_path=str(tmp_path)))
        s.flush()
        s.add(Conversation(id="c", project_id="p"))
        s.flush()
        s.add(Run(id="r", conversation_id="c", status="running"))
        s.flush()
        s.add(Agent(id="a", run_id="r", role_name="Coder", name="Coder", tools=[]))
        s.add(Agent(id="b", run_id="r", role_name="Coder", name="Coder 2", tools=[],
                    status="blocked", waiting_for=waiting_for))
        s.commit()
    assert recover_interrupted(factory) == 1
    with factory() as s:
        waiter = s.get(Agent, "b")
        assert (waiter.status, waiter.waiting_for) == ("interrupted", None)
    # who held what was never written down: a new process starts with nothing held
    assert Claims().of(tmp_path) == []


def test_an_agent_that_waits_gives_up_its_place_and_the_count_is_exact_afterwards(
    make_client, wait_run, project_dir
):
    """Twenty turns, each with two places: one agent waits for a file while a third works
    in its place. When all three are done the lead is the only one with a place again,
    and exactly one place is free - none was lost, none was made."""
    client, model = make_client({})
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    runner = client.app.state.runner
    for round_ in range(20):
        first, second, woken, last = Gate(), Gate(), Gate(), Gate()
        model.by_agent.update({
            "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "A"}, "s1"),
                          call("spawn_agent", {"role": "Coder", "task": "B"}, "s2"),
                          call("spawn_agent", {"role": "Coder", "task": "C"}, "s3")),
                     last.step(text("done"))],
            "Coder": [step(write("shared.txt", "one")), first.step(text("A done"))],
            "Coder 2": [second.step(step(write("shared.txt", "two"))),
                        woken.step(text("B done"))],
            "Coder 3": [step(write("c.txt", "three")), text("C done")],
        })
        cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
        run_id = start(client, cid)
        first.wait_partial()
        second.release()
        until(client, cid, lambda s: waits(s, "Coder 2") is not None)
        snap = until(client, cid, lambda s: agent(s, "Coder 3")["status"] == "completed")
        # while it waits it has no place: the holder has one, the other is free
        assert runner._placed == {agent(snap, "Coder")["id"]}, round_
        assert runner._slots[run_id]._value == 1, round_
        first.release()
        woken.wait_partial()
        # the file is its own and it is at work again: with a place, like any agent
        assert runner._placed == {agent(snap, "Coder 2")["id"]}, round_
        assert runner._slots[run_id]._value == 1, round_
        assert agent(snapshot(client, cid), "Coder 2")["status"] == "running", round_
        woken.release()
        last.wait_partial()
        snap = snapshot(client, cid)
        assert runner._placed == {agent(snap, "Lead")["id"]}, round_
        assert runner._slots[run_id]._value == 1, round_
        assert not runner._held_up and runner.claims.of(project_dir) == [], round_
        last.release()
        wait_run(client, cid, run_id)
        (project_dir / "shared.txt").unlink()
        (project_dir / "c.txt").unlink()
    assert not runner._slots and not runner._placed            # nothing outlives its turn


def test_a_sibling_waits_for_its_sibling_though_the_lead_held_the_file_first(
    make_client, wait_run, project_dir
):
    first, second = Gate(), Gate()
    client, model = make_client({
        "Lead": [step(write("shared.txt", "lead")), two(), text("done")],
        "Coder": [step(write("shared.txt", "one")), first.step(text("A done"))],
        "Coder 2": [second.step(step(write("shared.txt", "two"))), text("B done")],
    })
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    run_id = start(client, cid)
    first.wait_partial()
    snap = snapshot(client, cid)
    # the Coder took it from the lead it works for, without waiting
    assert snap["claims"] == [{"path": "shared.txt", "agent_id": agent(snap, "Coder")["id"]}]
    assert [said_first(one) for one in calls(snap, "Coder", "write_file")] == [
        ("succeeded", "applied: shared.txt (+1 -1)")]
    second.release()
    snap = until(client, cid, lambda s: waits(s, "Coder 2") is not None)
    assert waits(snap, "Coder 2") == ("Coder", "shared.txt")
    first.release()
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed"
    assert (project_dir / "shared.txt").read_text(encoding="utf-8") == "one"
    assert snap["claims"] == []


def test_a_path_written_another_way_is_the_same_file_and_one_outside_is_refused_as_before(
    make_client, wait_run, project_dir
):
    first, second = Gate(), Gate()
    client, model = make_client({
        "Lead": [two(), text("done")],
        "Coder": [step(write("Shared.txt", "one")), first.step(text("A done"))],
        # (into a drive's root: never opened - another folder outside is asked about)
        "Coder 2": [step(write("../" * 40 + "outside.txt", "x", "w0")),
                    second.step(step(write("./SHARED.TXT", "two"))), text("B done")],
    })
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    run_id = start(client, cid)
    first.wait_partial()
    second.wait_partial()
    snap = snapshot(client, cid)
    status, said = calls(snap, "Coder 2", "write_file")[0]
    assert status == "failed" and "never opened" in said
    assert [c["path"] for c in snap["claims"]] == ["Shared.txt"]   # and nothing else
    second.release()
    snap = until(client, cid, lambda s: waits(s, "Coder 2") is not None)
    assert waits(snap, "Coder 2") == ("Coder", "Shared.txt")
    first.release()
    wait_run(client, cid, run_id)
    assert not (project_dir.parent / "outside.txt").exists()


def test_the_edit_that_waited_is_made_after_a_second_look_and_neither_edit_is_lost(
    make_client, wait_run, project_dir
):
    """Across two conversations, and in an order that is held, not hoped for: the waiter
    has read the file before the holder changes it. Its own edit would still apply to
    what the holder left - and is not made until it has looked again."""
    looked, changing, holding = Gate(), Gate(), Gate()
    client, model, first, second = two_conversations(make_client, project_dir, {
        "Lead": [spawn("Writer"), spawn("Coder"), text("done"), text("done")],
        "Coder": [changing.step(edit("'hi'", "'hello'")), holding.step(text("A done"))],
        "Writer": [read("hello.py", "r1"), looked.step(edit("print", "PRINT", "e1")),
                   read("hello.py", "r2"), edit("print", "PRINT", "e2"), text("B done")],
    })
    other = start(client, second)
    looked.wait_partial()                                      # the Writer has read it
    one = start(client, first)
    changing.release()
    holding.wait_partial()                                     # the Coder has changed it
    looked.release()
    snap = until(client, second, lambda s: waits(s, "Writer") is not None)
    assert waits(snap, "Writer") == ("Coder", "hello.py")
    holding.release()
    wait_run(client, first, one)
    snap = wait_run(client, second, other)
    (refused, said), (made, _) = calls(snap, "Writer", "edit_file")
    assert (refused, made) == ("failed", "succeeded")
    assert said == ('conflict: Coder (of the conversation "go") has finished with hello.py, '
                    "and the file is not as you last read it; read it again, then make your "
                    "change")
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "PRINT('hello')\n"


def test_after_a_wait_a_change_is_made_when_the_file_is_as_the_waiter_read_it(
    make_client, wait_run, project_dir
):
    """The holder gave the file back as it was (its changes were declined): the waiter
    read exactly that, so its change is made and put before the user - it is not sent to
    read again for nothing. (Since slice 19b the user is asked once per agent, for what
    it changed in its working copy, and the agent holds its files until they have said.)"""
    second = Gate()
    client, model = make_client({
        "Lead": [two(), text("done")],
        "Coder": [edit("'hi'", "'hello'"), text("A done")],
        "Coder 2": [read("hello.py"), second.step(edit("print", "PRINT")), text("B done")],
    })
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    run_id = start(client, cid, permission_mode="ask")

    def asked(s):
        return [m for m in s["merges"] if m["status"] == "pending"]

    snap = until(client, cid, asked)
    (held_card,) = asked(snap)
    second.release()
    until(client, cid, lambda s: waits(s, "Coder 2") is not None)
    assert client.post(f"/api/merges/{held_card['id']}/reject").status_code == 200
    # the Coder's are turned down; the file is as Coder 2 read it: its own change is
    # made, and is what the user is asked about now
    snap = until(client, cid, asked)
    (card,) = asked(snap)
    assert card["agent_id"] == agent(snap, "Coder 2")["id"]
    assert snap["claims"] == [{"path": "hello.py", "agent_id": agent(snap, "Coder 2")["id"]}]
    assert client.post(f"/api/merges/{card['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert [said_first(one) for one in calls(snap, "Coder 2", "edit_file")] == [
        ("succeeded", "applied: hello.py (+1 -1)")]
    assert (project_dir / "hello.py").read_text(encoding="utf-8") == "PRINT('hi')\n"
    assert [f["status"] for f in snap["file_changes"]] == ["rejected", "applied"]


def test_a_change_is_not_reverted_around_the_agent_that_is_changing_the_file_now(
    make_client, wait_run, project_dir
):
    client, model, first, second = two_conversations(make_client, project_dir, {
        "Lead": [step(write("shared.txt", "one")), text("done"),
                 spawn("Writer"), text("done")],
        "Writer": [step(write("shared.txt", "two")), text("B done")],
    })
    snap = wait_run(client, first, start(client, first))
    change = snap["file_changes"][0]
    assert change["status"] == "applied" and snap["claims"] == []
    # another agent now holds the file: its own change waits for the user (since slice
    # 19b in its working copy, asked about once its work is over), nothing is written
    # to the project yet - so nothing but the claim stands in the way of the revert
    other = start(client, second, permission_mode="ask")
    snap = until(client, second, lambda s: [m["status"] for m in s["merges"]] == ["pending"])
    refused = client.post(f"/api/file-changes/{change['id']}/revert")
    assert refused.status_code == 409 and "Writer is changing shared.txt" in refused.text
    assert (project_dir / "shared.txt").read_text(encoding="utf-8") == "one"
    assert client.post(f"/api/merges/{snap['merges'][0]['id']}/reject").status_code == 200
    wait_run(client, second, other)
    # when it is done the change is reverted as ever
    assert client.post(f"/api/file-changes/{change['id']}/revert").status_code == 200
    assert not (project_dir / "shared.txt").exists()


def test_a_change_is_still_reverted_while_the_agent_that_made_it_is_at_work(
    make_client, wait_run, project_dir
):
    """As before file claims: its own agent holding the file is not in the way."""
    gate = Gate()
    client, model = make_client([step(write("shared.txt", "one")), gate.step(text("done"))])
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    run_id = start(client, cid)
    gate.wait_partial()
    snap = snapshot(client, cid)
    assert [c["path"] for c in snap["claims"]] == ["shared.txt"]
    change = snap["file_changes"][0]
    assert client.post(f"/api/file-changes/{change['id']}/revert").status_code == 200
    gate.release()
    wait_run(client, cid, run_id)
    assert not (project_dir / "shared.txt").exists()


def test_a_turn_taken_to_carry_on_takes_a_file_and_lets_it_go_when_the_turn_is_over(
    make_client, wait_run, project_dir
):
    working, after = Gate(), Gate()
    client, model = make_client({
        "Lead": [spawn("Coder"),
                 step(call("message_agent", {"to": "Coder", "message": "one more"}, "m")),
                 after.step(text("done"))],
        "Coder": [text("first done"), step(write("c.txt", "more")),
                  working.step(text("second done"))],
    })
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    run_id = start(client, cid)
    working.wait_partial()
    snap = snapshot(client, cid)
    assert snap["claims"] == [{"path": "c.txt", "agent_id": agent(snap, "Coder")["id"]}]
    working.release()
    after.wait_partial()                                       # the turn on the message is over
    assert snapshot(client, cid)["claims"] == []
    after.release()
    wait_run(client, cid, run_id)


def test_a_turn_taken_to_answer_takes_nothing_and_leaves_what_the_agent_holds(
    make_client, wait_run, project_dir
):
    """An agent answering a message cannot write, so it takes no file there - and the end
    of that turn is not the end of its work: what it holds is still its own."""
    gate = Gate()
    client, model = make_client({
        "Lead": [step(write("shared.txt", "lead")), spawn("Coder"),
                 step(write("other.txt", "x", "w2")), text("It is mine."), text("done")],
        "Coder": [step(call("message_agent", {"to": "Lead", "message": "whose is it?"}, "m")),
                  gate.step(text("A done"))],
    })
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    run_id = start(client, cid)
    gate.wait_partial()                                        # the answer has been given
    snap = snapshot(client, cid)
    _first, (status, said) = calls(snap, "Lead", "write_file")
    assert status == "failed" and "not available while answering" in said
    assert not (project_dir / "other.txt").exists()
    assert snap["claims"] == [{"path": "shared.txt", "agent_id": agent(snap, "Lead")["id"]}]
    gate.release()
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed" and snap["claims"] == []


def test_who_holds_what_is_told_as_it_changes(make_client, wait_run, project_dir):
    client, model = make_client([step(write("a.txt", "x")), text("done")])
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    snap = wait_run(client, cid, start(client, cid))
    lead = snap["agents"][0]["id"]
    stream = client.get(f"/api/conversations/{cid}/events?after=0&once=true").text
    told = [json.loads(block.split("data: ", 1)[1]) for block in stream.split("\n\n")
            if "event: claims.changed" in block]
    assert told == [{"claims": [{"path": "a.txt", "agent_id": lead}]}, {"claims": []}]
    # an agent that changes nothing is told of nothing: a turn of reading has no such event
    model.steps.append(text("hello"))
    wait_run(client, cid, start(client, cid))
    again = client.get(f"/api/conversations/{cid}/events?after=0&once=true").text
    assert again.count("event: claims.changed") == 2


# --- Claude Code, which asks leave for its own write tool ----------------------------------


def _other_conversation(client, project_dir, provider):
    pid = client.get("/api/projects").json()[0]["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    # (Claude Code is the Lead that writes here: K-48 refuses one that hands code on)
    client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "full_auto", "provider_id": provider["id"], "lead_hands_code": False},
        headers={"Origin": ORIGIN})
    run = client.post(f"/api/conversations/{cid}/messages",
                      json={"content": "fix the greeting"}).json()["run"]
    return cid, run["id"]


def test_claude_codes_write_waits_for_the_agent_that_holds_the_file_and_is_then_allowed(
    claude_app, wait_run, project_dir  # noqa: F811
):
    gate = Gate()
    client, provider, default = claude_app(
        [{"say": "I will fix it."}, CLAUDE_WRITE, {"say": "Fixed."}],
        default_steps=[edit("'hi'", "'one'"), gate.step(text("done"))])
    client.headers["Origin"] = ORIGIN
    first, one = start_on(client, project_dir, None, "full_auto")
    gate.wait_partial()
    second, other = _other_conversation(client, project_dir, provider)
    snap = until(client, second, lambda s: waits(s, "Lead") is not None)
    assert waits(snap, "Lead") == ("Lead", "hello.py")
    assert agent(snap, "Lead")["status"] == "blocked"
    # the request is on record as a call that has not returned
    assert [(t["name"], t["status"], t["origin"]) for t in snap["tool_calls"]] == [
        ("edit_file", "running", "cli")]
    assert hello(project_dir) == "print('one')\n"
    gate.release()
    wait_run(client, first, one)
    snap = wait_run(client, second, other, timeout=15)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    # the file was as it was when Claude Code asked: allowed, and written by itself
    assert claude_app.record()["asked"][0]["behavior"] == "allow"
    assert hello(project_dir) == "print('hello')\n"
    assert [(t["status"], t["result"]) for t in snap["tool_calls"]][0] == (
        "succeeded",
        'waited for Lead (of the conversation "fix the greeting") to finish with hello.py')
    assert snap["claims"] == [] and waits(snap, "Lead") is None


def test_claude_codes_write_is_refused_after_the_wait_when_the_file_changed_meanwhile(
    claude_app, wait_run, project_dir  # noqa: F811
):
    gate = Gate()
    client, provider, default = claude_app(
        [{"say": "I will fix it."}, CLAUDE_WRITE, {"say": "It changed."}],
        default_steps=[edit("'hi'", "'one'"), held(gate, edit("'one'", "'two'", "e2")),
                       text("done")])
    client.headers["Origin"] = ORIGIN
    first, one = start_on(client, project_dir, None, "full_auto")
    gate.wait_partial()
    second, other = _other_conversation(client, project_dir, provider)
    until(client, second, lambda s: waits(s, "Lead") is not None)
    gate.release()
    wait_run(client, first, one)
    snap = wait_run(client, second, other, timeout=15)
    answer = claude_app.record()["asked"][0]
    assert answer["behavior"] == "deny"
    assert "Lead" in answer["message"] and "read it again" in answer["message"]
    assert hello(project_dir) == "print('two')\n"              # not written over
    assert [(t["name"], t["status"]) for t in snap["tool_calls"]] == [("edit_file", "failed")]
    assert "read it again" in snap["tool_calls"][0]["result"]
    assert snap["file_changes"] == []
    # it holds the file now, until its own work is over - which it is
    assert snap["claims"] == []


def test_claude_code_takes_the_file_it_asks_for_so_that_another_agent_waits_for_it(
    claude_app, wait_run, project_dir  # noqa: F811
):
    client, provider, default = claude_app(
        [CLAUDE_WRITE, {"tool": "Bash", "input": {"command": "pytest -q"},
                        "result": "2 passed"}, {"say": "Fixed."}],
        default_steps=[edit("'hello'", "'two'"), text("done")])
    client.headers["Origin"] = ORIGIN
    second, other = start_on(client, project_dir, provider, "ask")
    proposed = until(client, second, lambda s: any(
        f["status"] == "proposed" for f in s["file_changes"]))
    claude = agent(proposed, "Lead")["id"]
    assert proposed["claims"] == [{"path": "hello.py", "agent_id": claude}]
    assert client.post(
        f"/api/file-changes/{proposed['file_changes'][0]['id']}/approve").status_code == 200
    # Claude Code has written and now asks for its command: it still holds the file
    until(client, second, lambda s: any(c["status"] == "proposed" for c in s["commands"]))
    pid = client.get("/api/projects").json()[0]["id"]
    first = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    one = start(client, first)
    snap = until(client, first, lambda s: waits(s, "Lead") is not None)
    assert waits(snap, "Lead") == ("Lead", "hello.py")
    command = snapshot(client, second)["commands"][0]
    assert client.post(f"/api/commands/{command['id']}/reject").status_code == 200
    wait_run(client, second, other, timeout=15)
    snap = wait_run(client, first, one, timeout=15)
    ((status, said),) = calls(snap, "Lead", "edit_file")
    assert status == "failed" and "read it again" in said
    assert hello(project_dir) == "print('hello')\n"


# --- a CLI that does not ask before it writes ----------------------------------------------------


def test_a_cli_that_does_not_ask_changing_a_held_file_is_put_on_record_and_the_holder_told_once(
    native_app, wait_run, project_dir  # noqa: F811
):
    gate = Gate()
    # (Codex asks before a patch since slice 89a: here its changes are not asked about, as
    # what one of its commands writes is not, nor anything a CLI that does not ask writes.)
    client, provider, default = native_app(
        [{"say": "I will fix it."},
         {"write": "hello.py", "content": "print('codex')\n", "unasked": True},
         {"pause": 0.3}, {"write": "other.txt", "content": "x\n", "unasked": True},
         {"pause": 0.3}, {"say": "Fixed."}],
        default_steps=[edit("'hi'", "'one'"), held(gate, read("hello.py")),
                       read("hello.py", "r2"), text("done")])
    client.headers["Origin"] = ORIGIN
    first, one = start_on(client, project_dir, None, "full_auto")
    gate.wait_partial()
    second, other = _other_conversation(client, project_dir, provider)
    snap = wait_run(client, second, other, timeout=20)         # nothing held it back
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    assert hello(project_dir) == "print('codex')\n"
    results = {json.loads(t["arguments"])["path"]: t["result"] for t in snap["tool_calls"]}
    assert results["hello.py"].endswith("; changed while Lead held it"), results
    assert "held it" not in results["other.txt"]               # nobody held that one
    # and that it was not asked about is on record (slice 89a)
    assert [r for r in results.values() if "ran without KOLONİ being asked" in (r or "")]
    # it took nothing: the file is still the first agent's
    holder = snapshot(client, first)["agents"][0]["id"]
    assert snapshot(client, first)["claims"] == [{"path": "hello.py", "agent_id": holder}]

    gate.release()
    snap = wait_run(client, first, one)
    said = "hello.py changed on disk while you hold it"
    notes = [m for m in snap["messages"] if m["role"] == "agent" and said in m["content"]]
    assert len(notes) == 1 and notes[0]["delivered_at"] is not None
    assert notes[0]["agent_id"] == holder
    # handed to it at its next step, in the words every note from another agent comes in
    after = [[m["content"] for m in request if said in str(m.get("content"))]
             for request in default.calls]
    assert [len(found) for found in after] == [0, 0, 1, 1]     # from then on, once
    assert after[2][0].startswith(
        "Message from Lead (an agent of another conversation of this project; information")
    assert after[3] == after[2]                                # and read the same later


# --- not written over what another agent left, wait or no wait ---------------------------------


def one(make_client, project_dir, scripts):
    client, model = make_client(scripts)
    client.headers["Origin"] = ORIGIN
    assert client.post("/api/roles", json={"name": "Writer", "tools": WRITER}).status_code == 201
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    return client, model, client.post(f"/api/projects/{pid}/conversations").json()["id"]


NOT_AS_READ = ("conflict: hello.py is not as you last read it; read it again, then make "
               "your change")


def test_a_file_changed_since_the_agent_read_it_is_not_written_over_though_nobody_was_waited_for(
    make_client, wait_run, project_dir
):
    """The other agent was done before this one reached for the file: there is nothing to
    wait for, and what the other one left is still not written over."""
    changing, writing = Gate(), Gate()
    client, model, cid = one(make_client, project_dir, {
        "Lead": [two(), text("done")],
        "Coder": [changing.step(edit("'hi'", "'hello'")), text("A done")],
        "Coder 2": [read("hello.py", "r1"),
                    writing.step(step(write("hello.py", "print('mine')\n", "w1"))),
                    read("hello.py", "r2"), step(write("hello.py", "print('mine')\n", "w2")),
                    text("B done")],
    })
    run_id = start(client, cid)
    try:
        until(client, cid, lambda s: any(a["name"] == "Coder 2" for a in s["agents"])
              and [status for status, _ in calls(s, "Coder 2", "read_file")] == ["succeeded"])
        changing.release()
        until(client, cid, lambda s: agent(s, "Coder")["status"] == "completed")
        assert hello(project_dir) == "print('hello')\n"
        writing.release()
        snap = until(client, cid, lambda s: len(calls(s, "Coder 2", "read_file")) == 2)
    finally:
        changing.release()
        writing.release()
    # nobody was waited for, and nobody is named
    assert calls(snap, "Coder 2", "write_file")[0] == ("failed", NOT_AS_READ)
    assert waits(snap, "Coder 2") is None
    snap = wait_run(client, cid, run_id)
    # having looked again it writes: the file is its own decision now
    assert [status for status, _ in calls(snap, "Coder 2", "write_file")] == [
        "failed", "succeeded"]
    assert hello(project_dir) == "print('mine')\n"
    assert [f["status"] for f in snap["file_changes"]] == ["applied", "applied"]


@pytest.mark.parametrize("mode", ["full_auto", "ask"])
def test_an_agents_own_writes_one_after_another_are_made_and_a_file_it_never_read_as_before(
    make_client, wait_run, project_dir, mode
):
    client, model, cid = one(make_client, project_dir, [
        step(write("new.txt", "one", "w1")), step(write("new.txt", "two", "w2")),
        read("hello.py"), edit("'hi'", "'hello'"),
        step(write("hello.py", "print('whole')\n", "w3")),
        step(write("hello.py", "print('again')\n", "w4")),
        # one it never read, changed by nobody it waited for: written as it always was
        step(write("README.md", "mine\n", "w5")), text("done"),
    ])
    (project_dir / "README.md").write_text("theirs\n", encoding="utf-8")
    run_id = start(client, cid, permission_mode=mode)
    for _ in range(6 if mode == "ask" else 0):
        snap = until(client, cid, lambda s: any(
            f["status"] == "proposed" for f in s["file_changes"]))
        proposal = next(f for f in snap["file_changes"] if f["status"] == "proposed")
        assert client.post(f"/api/file-changes/{proposal['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert [f["status"] for f in snap["file_changes"]] == ["applied"] * 6
    assert [t["status"] for t in snap["tool_calls"]] == ["succeeded"] * 7
    assert (project_dir / "new.txt").read_text(encoding="utf-8") == "two"
    assert hello(project_dir) == "print('again')\n"
    assert (project_dir / "README.md").read_text(encoding="utf-8") == "mine\n"


def test_an_edit_made_on_what_the_file_holds_now_needs_no_second_look_when_nobody_was_waited_for(
    make_client, wait_run, project_dir
):
    """`edit_file` replaces one piece of what the file holds when it is made, or fails for
    not finding it: the other agent's lines are in the result either way."""
    changing, editing = Gate(), Gate()
    client, model, cid = one(make_client, project_dir, {
        "Lead": [two(), text("done")],
        "Coder": [changing.step(edit("'hi'", "'hello'")), text("A done")],
        "Coder 2": [read("hello.py", "r1"), editing.step(edit("print", "PRINT", "e1")),
                    edit("'hi'", "'hey'", "e2"), text("B done")],
    })
    run_id = start(client, cid)
    try:
        until(client, cid, lambda s: any(a["name"] == "Coder 2" for a in s["agents"])
              and [status for status, _ in calls(s, "Coder 2", "read_file")] == ["succeeded"])
        changing.release()
        until(client, cid, lambda s: agent(s, "Coder")["status"] == "completed")
        editing.release()
        snap = wait_run(client, cid, run_id)
    finally:
        changing.release()
        editing.release()
    made, lost = calls(snap, "Coder 2", "edit_file")
    assert said_first(made) == ("succeeded", "applied: hello.py (+1 -1)")
    # the piece it remembered is gone: it is told to read, and nothing is written
    assert lost[0] == "failed" and "old_string was not found" in lost[1]
    assert hello(project_dir) == "PRINT('hello')\n"


def test_a_file_that_changed_while_it_was_read_is_not_one_the_agent_has_seen(
    make_client, wait_run, project_dir, monkeypatch
):
    """Another agent wrote the file while this one was reading it: what it was shown may
    be either, so its next whole write is not made until it has read the file again."""
    import app.agent as runner_module

    real, reads = runner_module.run_read_tool, []

    def read_while_it_changes(ws, name, args, *search):  # (a search's limit and stop: slice 36)
        shown = real(ws, name, args, *search)
        if not reads:
            (project_dir / "hello.py").write_text("print('theirs')\n", encoding="utf-8")
        reads.append(args.get("path"))
        return shown

    monkeypatch.setattr(runner_module, "run_read_tool", read_while_it_changes)
    client, model, cid = one(make_client, project_dir, [
        read("hello.py", "r1"), step(write("hello.py", "print('mine')\n", "w1")),
        read("hello.py", "r2"), step(write("hello.py", "print('mine')\n", "w2")),
        text("done"),
    ])
    snap = wait_run(client, cid, start(client, cid))
    assert calls(snap, "Lead", "write_file") == [
        ("failed", NOT_AS_READ), ("succeeded", "applied: hello.py (+1 -1)")]
    assert hello(project_dir) == "print('mine')\n"


# --- an agent that waits to hear back from another holds its files meanwhile ------------------


def message(to, body, id="m"):
    return step(call("message_agent", {"to": to, "message": body}, id))


@pytest.mark.parametrize("through", ["a sub-agent at work", "a turn on a message"])
def test_a_file_is_not_waited_for_when_its_holder_waits_for_an_agent_that_waits_for_the_asker(
    make_client, wait_run, project_dir, through
):
    """Across two conversations of one project. The lead holds x.txt and does nothing
    until its Coder is back; the Coder waits for y.txt, which the Writer holds; the Writer
    then wants x.txt. That would never end, so the Writer is told at once."""
    holding = Gate()
    ask = [spawn("Coder")] if through == "a sub-agent at work" else [
        spawn("Coder"), message("Coder", "now y.txt")]
    work = [step(write("y.txt", "coder")), text("A done")]
    client, model, first, second = two_conversations(make_client, project_dir, {
        "Lead": [spawn("Writer"), step(write("x.txt", "lead")), *ask,
                 text("done"), text("done")],
        "Coder": work if through == "a sub-agent at work" else [text("ready"), *work],
        "Writer": [step(write("y.txt", "writer")),
                   holding.step(step(write("x.txt", "writer", "w2"))), text("B done")],
    })
    other = start(client, second)
    try:
        holding.wait_partial()                                 # the Writer holds y.txt
        one = start(client, first)
        snap = until(client, first, lambda s: waits(s, "Coder") is not None)
        assert waits(snap, "Coder") == ("Writer", "y.txt")
        assert agent(snap, "Lead")["status"] == "waiting"
        holding.release()
        snap = wait_run(client, second, other, timeout=10)
    finally:
        holding.release()
    _held, (status, said) = calls(snap, "Writer", "write_file")
    assert status == "failed" and said == (
        "error: Lead holds x.txt and is waiting for Coder, which is waiting for you, so "
        "waiting for the file would never end. Nothing was changed. Go on with what does "
        "not need this file; if this change is still to be made when you are done, say so "
        "in your report.")
    assert waits(snap, "Writer") is None
    assert all(a["status"] == "completed" for a in snap["agents"])
    snap = wait_run(client, first, one, timeout=10)
    assert snap["runs"][-1]["status"] == "completed"
    assert all(a["status"] == "completed" for a in snap["agents"])
    assert (project_dir / "x.txt").read_text(encoding="utf-8") == "lead"
    assert (project_dir / "y.txt").read_text(encoding="utf-8") == "writer"
    assert snap["claims"] == [] and client.app.state.runner.claims._out == {}


# --- the same line: an agent and the agents it works for ---------------------------------------


# A Coder and a Writer opened at once: the Coder's own Coder is then "Coder 2", whenever
# it is opened.
CODER_AND_WRITER = step(call("spawn_agent", {"role": "Coder", "task": "do A"}, "s1"),
                        call("spawn_agent", {"role": "Writer", "task": "do B"}, "s2"))


def test_a_file_goes_down_the_line_without_a_wait_and_back_up_it_as_each_agent_ends(
    make_client, wait_run, project_dir
):
    """The lead holds shared.txt. Its Coder takes it, and the Coder's own sub-agent takes
    it from the Coder: neither waits, and neither is told that it would wait for ever
    (the agents above are waiting for it). The lead's other sub-agent waits - for
    whichever of them has the file now. As each ends the file is the one's above it."""
    below, coder_on, sibling, last = Gate(), Gate(), Gate(), Gate()
    client, model, cid = one(make_client, project_dir, {
        "Lead": [step(write("shared.txt", "lead")), CODER_AND_WRITER,
                 last.step(text("done"))],
        "Coder": [step(write("shared.txt", "one")), spawn("Coder", "s3"),
                  coder_on.step(text("A done"))],
        "Writer": [sibling.step(step(write("shared.txt", "two"))), text("B done")],
        "Coder 2": [step(write("shared.txt", "three")), below.step(text("C done"))],
    })
    run_id = start(client, cid, spawn_max_parallel=3)
    gates = (below, coder_on, sibling, last)
    try:
        below.wait_partial()
        snap = snapshot(client, cid)
        ids = {a["name"]: a["id"] for a in snap["agents"]}
        assert agent(snap, "Coder 2")["parent_agent_id"] == ids["Coder"]
        for name in ("Coder", "Coder 2"):
            assert [said_first(one) for one in calls(snap, name, "write_file")] == [
                ("succeeded", "applied: shared.txt (+1 -1)")], name
        # nobody of the line was ever held up
        stream = client.get(f"/api/conversations/{cid}/events?after=0&once=true").text
        assert '"status":"blocked"' not in stream and '"status": "blocked"' not in stream
        assert snap["claims"] == [{"path": "shared.txt", "agent_id": ids["Coder 2"]}]
        sibling.release()
        snap = until(client, cid, lambda s: waits(s, "Writer") is not None)
        assert waits(snap, "Writer") == ("Coder 2", "shared.txt")
        below.release()
        # back with the Coder, which the sibling waits for now
        snap = until(client, cid, lambda s: waits(s, "Writer") == ("Coder", "shared.txt"))
        assert snap["claims"] == [{"path": "shared.txt", "agent_id": ids["Coder"]}]
        assert agent(snap, "Coder 2")["status"] == "completed"
        coder_on.release()
        last.wait_partial()
        # both sub-agents are done: the file is the lead's again, until its turn is over
        snap = snapshot(client, cid)
        assert snap["claims"] == [{"path": "shared.txt", "agent_id": ids["Lead"]}]
        ((status, said),) = calls(snap, "Writer", "write_file")
        assert status == "failed" and said.startswith(
            "conflict: Coder 2 and Coder has finished with shared.txt, and you have not")
        last.release()
        snap = wait_run(client, cid, run_id)
    finally:
        for gate in gates:
            gate.release()
    assert snap["claims"] == [] and snap["runs"][0]["status"] == "completed"
    assert (project_dir / "shared.txt").read_text(encoding="utf-8") == "three"


def test_with_one_place_the_agent_that_waits_for_a_file_lets_its_holders_work_go_on(
    make_client, wait_run, project_dir
):
    """One agent at a time. The Coder holds shared.txt and waits for its own sub-agent,
    which has no place yet: the Writer has it - and wants shared.txt. Kept, the
    place would hold everything up for ever; it is given, the sub-agent works, the Coder
    ends, and the one that waited has the file and a place. None is lost, none is made."""
    begun, below, coder_on, woken, last = Gate(), Gate(), Gate(), Gate(), Gate()
    client, model, cid = one(make_client, project_dir, {
        "Lead": [CODER_AND_WRITER, last.step(text("done"))],
        "Coder": [begun.step(step(write("shared.txt", "one"))), spawn("Coder", "s3"),
                  coder_on.step(text("A done"))],
        "Writer": [step(write("shared.txt", "two")), woken.step(text("B done"))],
        "Coder 2": [below.step(text("C done"))],
    })
    runner = client.app.state.runner
    run_id = start(client, cid, spawn_max_parallel=1)
    try:
        # the Writer is next for the place, before the Coder opens a sub-agent of its own
        until(client, cid, lambda s: any(
            a["name"] == "Writer" and a["status"] == "queued" for a in s["agents"]))
        begun.release()
        below.wait_partial()                                   # only with the place given
        snap = snapshot(client, cid)
        ids = {a["name"]: a["id"] for a in snap["agents"]}
        assert waits(snap, "Writer") == ("Coder", "shared.txt")
        assert agent(snap, "Coder")["status"] == "waiting"
        assert runner._placed == {ids["Coder 2"]} and runner._slots[run_id]._value == 0
        below.release()
        coder_on.wait_partial()
        assert runner._placed == {ids["Coder"]} and runner._slots[run_id]._value == 0
        assert waits(snapshot(client, cid), "Writer") == ("Coder", "shared.txt")
        coder_on.release()
        woken.wait_partial()
        assert runner._placed == {ids["Writer"]} and runner._slots[run_id]._value == 0
        assert agent(snapshot(client, cid), "Writer")["status"] == "running"
        woken.release()
        last.wait_partial()
        assert runner._placed == {ids["Lead"]} and runner._slots[run_id]._value == 0
        assert not runner._held_up and runner.claims.of(project_dir) == []
        last.release()
        snap = wait_run(client, cid, run_id)
    finally:
        for gate in (begun, below, coder_on, woken, last):
            gate.release()
    assert all(a["status"] == "completed" for a in snap["agents"])
    assert not runner._slots and not runner._placed
    assert (project_dir / "shared.txt").read_text(encoding="utf-8") == "one"


def test_an_agent_of_another_conversation_is_told_whom_it_waits_for_as_the_file_goes_down_a_line(
    make_client, wait_run, project_dir
):
    opening, working = Gate(), Gate()
    client, model, first, second = two_conversations(make_client, project_dir, {
        "Lead": [step(write("shared.txt", "lead")), opening.step(spawn("Coder")),
                 spawn("Writer"), text("done"), text("done")],
        "Coder": [step(write("shared.txt", "one")), working.step(text("A done"))],
        "Writer": [step(write("shared.txt", "two")), text("B done")],
    })
    one_ = start(client, first)
    try:
        opening.wait_partial()
        other = start(client, second)
        snap = until(client, second, lambda s: waits(s, "Writer") is not None)
        assert waits(snap, "Writer") == ("Lead", "shared.txt")
        opening.release()
        # the lead's Coder has the file now: that is the agent the Writer waits for
        snap = until(client, second, lambda s: waits(s, "Writer") == ("Coder", "shared.txt"))
        coder = agent(snapshot(client, first), "Coder")["id"]
        assert agent(snap, "Writer")["waiting_for"]["agent_id"] == coder
        assert snap["claims"] == [{"path": "shared.txt", "agent_id": coder}]
        working.release()
        wait_run(client, first, one_)
        snap = wait_run(client, second, other)
    finally:
        opening.release()
        working.release()
    ((status, said),) = calls(snap, "Writer", "write_file")
    assert status == "failed" and said.startswith(
        'conflict: Lead and Coder (of the conversation "go") has finished with shared.txt')
    assert (project_dir / "shared.txt").read_text(encoding="utf-8") == "one"


def test_a_wait_that_cannot_be_put_on_record_leaves_nobody_waiting(
    make_client, wait_run, project_dir, monkeypatch
):
    """The record of the wait fails to be written: the agent's work ends on that, and it
    is not left in the line for the file, nor counted as held up, with its place given."""
    holding, last = Gate(), Gate()
    real = AgentRunner._set_agent

    def not_blocked(self, cid, agent_id, **fields):
        if fields.get("status") == "blocked":
            raise RuntimeError("the record could not be written")
        return real(self, cid, agent_id, **fields)

    monkeypatch.setattr(AgentRunner, "_set_agent", not_blocked)
    client, model, cid = one(make_client, project_dir, {
        "Lead": [CODER_AND_WRITER, last.step(text("done"))],
        "Coder": [step(write("shared.txt", "one")), holding.step(text("A done"))],
        "Writer": [step(write("shared.txt", "two")), text("B done")],
    })
    runner = client.app.state.runner
    run_id = start(client, cid)
    try:
        holding.wait_partial()
        snap = until(client, cid, lambda s: any(
            a["name"] == "Writer" and a["status"] == "failed" for a in s["agents"]))
        ids = {a["name"]: a["id"] for a in snap["agents"]}
        assert not runner._held_up and runner.claims.waiting(ids["Writer"]) == []
        assert runner._placed == {ids["Coder"]} and runner._slots[run_id]._value == 1
        assert snap["claims"] == [{"path": "shared.txt", "agent_id": ids["Coder"]}]
        holding.release()
        last.wait_partial()
        assert runner._placed == {ids["Lead"]} and runner._slots[run_id]._value == 1
        last.release()
        snap = wait_run(client, cid, run_id)
    finally:
        holding.release()
        last.release()
    assert (project_dir / "shared.txt").read_text(encoding="utf-8") == "one"
    assert snap["claims"] == []


# --- a turn's files are free before the turn is told to be over -----------------------------------


@pytest.mark.parametrize("how", ["completed", "cancelled"])
def test_nothing_is_held_any_more_when_a_turn_is_said_to_be_over(
    make_client, wait_run, project_dir, how
):
    """Whoever hears that a turn is over and looks, sees no file of it held: the lead's
    files are let go before the end of the turn is told, not after."""
    gate = Gate()
    client, model, cid = one(make_client, project_dir, [
        step(write("a.txt", "x")), gate.step(text("done"))])
    run_id = start(client, cid)
    gate.wait_partial()
    if how == "cancelled":
        assert client.post(f"/api/runs/{run_id}/cancel").status_code in (200, 202)
    else:
        gate.release()
    snap = wait_run(client, cid, run_id)
    gate.release()
    assert snap["runs"][0]["status"] == how
    stream = client.get(f"/api/conversations/{cid}/events?after=0&once=true").text
    told = [(block.split("event: ", 1)[1].split("\n", 1)[0],
             json.loads(block.split("data: ", 1)[1]))
            for block in stream.split("\n\n") if "event: " in block and "data: " in block]
    names = [name for name, _ in told]
    freed = max(at for at, (name, data) in enumerate(told)
                if name == "claims.changed" and data == {"claims": []})
    assert freed < names.index("run.finished"), names


# --- a discussion ------------------------------------------------------------------------------


def test_an_agent_holding_a_file_opens_a_discussion_and_the_file_is_its_own_throughout(
    make_client, wait_run, project_dir
):
    """Speaking changes nothing, so it takes no file and waits for none; the one who
    opened the discussion holds what it held, an agent of another conversation waits for
    it all the while, and nothing hangs."""
    speaking = Gate()
    members = step(call("spawn_agent", {"role": "Coder", "task": "be ready"}, "s1"),
                   call("spawn_agent", {"role": "Reviewer", "task": "be ready"}, "s2"))
    talk = step(call("discuss", {"topic": "Is shared.txt right?", "with": ["Coder", "Reviewer"],
                                 "rounds": 1}, "d"))
    client, model, first, second = two_conversations(make_client, project_dir, {
        "Lead": [step(write("shared.txt", "lead")), members, talk,
                 speaking.step(text("It stays.")), spawn("Writer"),
                 step(write("shared.txt", "lead again", "w2")), text("done"), text("done")],
        "Coder": [text("ready"),
                  step(write("shared.txt", "coder", "w"), call("read_file", {"path": "shared.txt"},
                                                                 "r")),
                  text("I would change it.")],
        "Reviewer": [text("ready"), text("Leave it.")],
        "Writer": [step(write("shared.txt", "writer")), text("B done")],
    })
    one = start(client, first)
    try:
        speaking.wait_partial()                                # the others have spoken
        snap = snapshot(client, first)
        lead = agent(snap, "Lead")["id"]
        assert snap["claims"] == [{"path": "shared.txt", "agent_id": lead}]
        ((status, said),) = calls(snap, "Coder", "write_file")
        assert status == "failed" and "while you are in a discussion" in said
        assert all(a["status"] != "blocked" for a in snap["agents"])
        other = start(client, second)
        snap = until(client, second, lambda s: waits(s, "Writer") is not None)
        assert waits(snap, "Writer") == ("Lead", "shared.txt")
        speaking.release()
        snap = wait_run(client, first, one, timeout=10)
    finally:
        speaking.release()
    assert snap["runs"][0]["status"] == "completed"
    assert (snap["discussions"][0]["status"], snap["discussions"][0]["outcome"]) == (
        "ended", "round_limit")
    # after the discussion the file is still the lead's to change
    assert calls(snap, "Lead", "write_file")[1] == (
        "succeeded", "applied: shared.txt (+1 -1)")
    assert own_claims(snap) == []
    snap = wait_run(client, second, other, timeout=10)
    ((status, said),) = calls(snap, "Writer", "write_file")
    assert status == "failed" and (
        'Lead (of the conversation "go") has finished with shared.txt' in said)
    assert (project_dir / "shared.txt").read_text(encoding="utf-8") == "lead again"
    assert snap["claims"] == [] and waits(snap, "Writer") is None
