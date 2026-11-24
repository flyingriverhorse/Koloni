"""tuval-kontrol-dongusu, round 2 (the review's HOLD: the canvas inferred rounds from the order
agents were opened in): KOLONİ writes the passes of its checks with the turn's Checked section -
each pass's tests, the looks it opened with their verdicts, why it went back, and the agents its
send-back had the Lead open. The canvas draws those. A fake model per role, a scripted executor."""

import pytest
from sqlalchemy import select

from app.db.models import Agent, Message, Run, ToolCall
from tests.fakes import ScriptedExecutor
from tests.test_agent_writes import write
from tests.test_chat_flow import text
from tests.test_proof_end_scenarios import PASS, begin, failing
from tests.test_proof_review_scenarios import BIG, CHECK, MERGE, hold
from tests.test_proof_test_ask_scenarios import TEST_A
from tests.test_spawn import spawn

pytestmark = pytest.mark.no_po


def passes(snap):
    (one,) = [m for m in snap["messages"] if m["role"] == "checked"]
    return one["passes"]


def ids(snap, *names):
    by = {a["name"]: a["id"] for a in snap["agents"]}
    return [by[name] for name in names]


def test_each_pass_says_its_tests_its_looks_why_it_went_back_and_who_fixed_it(
    make_client, wait_run, project_dir
):
    # (probes B and D: the tests fail and a Coder the Lead opens fixes them; then the Reviewer
    # holds and the Orchestrator fixes it itself - no agent; then MERGE)
    client, _model = make_client(
        {
            "Lead": [
                write("a.py", BIG),
                write("tests/test_a.py", TEST_A, "wt"),  # (a test with it: no ask for one)
                text("done"),
                spawn("Coder", "make the failing test pass", "c1"),
                text("fixed"),
                write("a.py", BIG + "y = 1\n", "w2"),
                text("fixed again"),
            ],
            "Coder": [write("b.py", "z = 1\n", "cw"), text("fixed it")],
            "Reviewer": [hold("a.py:3 divides by zero")],
            "Reviewer 2": [MERGE],
        },
        executor=ScriptedExecutor([failing(), PASS, PASS, PASS, PASS]),
    )
    cid, run_id = begin(client, project_dir, check_command=CHECK)
    snap = wait_run(client, cid, run_id)
    coder, first, second = ids(snap, "Coder", "Reviewer", "Reviewer 2")
    assert passes(snap) == [
        {
            "n": 1,
            "kind": "check",
            "tests": "failed",
            "looks": [],
            "why": "tests fail",
            "sent": "fix",
            "fixers": [coder],
            "diagnosis": None,
            "tier": None,
        },
        {
            "n": 2,
            "kind": "check",
            "tests": "passed",
            "looks": [{"agent_id": first, "role": "Reviewer", "verdict": "HOLD", "said": None}],
            "why": "1 blocking finding",
            "sent": "fix",
            "fixers": [],  # (the Orchestrator fixed it itself)
            "diagnosis": None,
            "tier": None,
        },
        {
            "n": 3,
            "kind": "check",
            "tests": "passed",
            "looks": [{"agent_id": second, "role": "Reviewer", "verdict": "MERGE", "said": None}],
            "why": None,
            "sent": None,
            "fixers": [],
            "diagnosis": None,
            "tier": None,
        },
    ], passes(snap)


def test_the_agent_written_for_the_ask_for_a_test_is_no_fixer(make_client, wait_run, project_dir):
    # (probe A: KOLONİ asks for a test - no fix round; the Lead opens a Coder to write it)
    client, _model = make_client(
        {
            "Lead": [
                write("a.py", "x = 1\n"),
                text("done"),
                spawn("Coder", "write a test for a.py", "c1"),
                text("done, with its test"),
            ],
            "Coder": [write("tests/test_a.py", TEST_A, "cw"), text("written")],
        },
        executor=ScriptedExecutor([PASS, PASS]),
    )
    cid, run_id = begin(client, project_dir, check_command=CHECK)
    snap = wait_run(client, cid, run_id)
    found = passes(snap)
    assert [(one["sent"], one["why"], one["fixers"]) for one in found] == [
        ("ask", None, []),
        (None, None, []),
    ], found


def test_only_the_leads_own_spawns_are_fixers_never_koloni_s_a_rooms_or_a_discussions(
    make_client, project_dir
):
    # (probe S4: a room's or a discussion's members, opened by those calls, stay outside the box)
    client, _model = make_client([])
    runner = client.app.state.runner
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    with client.app.state.session_factory() as session:
        session.add(Run(id="r", conversation_id=cid, status="completed"))
        session.flush()
        session.add(Message(id="m", conversation_id=cid, run_id="r", role="assistant"))
        session.flush()
        session.add(Agent(id="lead", run_id="r", role_name="Lead", name="Lead", tools=[], depth=0))
        session.flush()
        for seq, (name, provider_call) in enumerate(
            [
                ("spawn_agent", "call_1"),
                ("spawn_agent", "koloni_proof_review_x"),
                ("discuss", "call_2"),
                ("open_room", "call_3"),
                ("message_agent", "call_4"),  # (going on with an earlier agent opens it: `_go_on`)
            ]
        ):
            session.add(
                ToolCall(
                    id=f"t{seq}",
                    run_id="r",
                    agent_id="lead",
                    message_id="m",
                    seq=seq,
                    provider_call_id=provider_call,
                    name=name,
                    arguments="{}",
                    status="succeeded",
                )
            )
            session.flush()
            session.add(
                Agent(
                    id=f"a{seq}",
                    run_id="r",
                    role_name="Coder",
                    name=f"Coder {seq}",
                    tools=[],
                    depth=1,
                    parent_agent_id="lead",
                    tool_call_id=f"t{seq}",
                )
            )
        session.commit()
        assert session.scalars(select(Agent.id).where(Agent.run_id == "r")).all()
    assert runner._lead_opened("r", "lead") == ["a0", "a4"]
