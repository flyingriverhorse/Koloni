"""read_status (0.1.9): the Orchestrator reads from the records what waits for the user and what was
done - of its own project alone, every agent's word masked and quoted as data, the whole cut at
3 KB with a line that says so; offered to the Orchestrator at its own work, never a sub-agent."""

from app import injection, raw, status_now
from app.agent.status_tool_mixin import NOT_HERE
from app.db.away_models import Parked
from app.db.models import Agent, AwayRun, BacklogTask, Command, Merge, Question, Run
from app.model_client import StepResult, ToolCallRequest
from tests.test_chat_flow import text
from tests.test_decisions import ORDERS, chat
from tests.test_proof_end_scenarios import begin
from tests.test_run_checks_scenarios import tools_of
from tests.test_spawn import call, step
from tests.test_team import SECRET


def seed(client, pid, cid, tag, why="the tests need it"):
    """One of each thing read_status reads, in chat `cid` of project `pid`, each named by `tag`."""
    with client.app.state.session_factory() as session:
        run = Run(conversation_id=cid, status="completed")
        session.add(run)
        session.flush()
        record = {"on_branch": f"koloni/{tag}", "away": {"commits": 3}}
        lead = Agent(run_id=run.id, role_name="Lead", name="Lead", tools=[], copy=record)
        session.add(lead)
        session.flush()
        night = AwayRun(project_id=pid, conversation_id=cid, run_id=run.id, status="ended")
        job = BacklogTask(
            project_id=pid, title=f"{tag} job", status="doing", position=0, created_by="user"
        )
        session.add_all([night, job])
        session.flush()
        session.add_all(
            [
                Command(
                    run_id=run.id,
                    agent_id=lead.id,
                    command=f"python {tag}.py",
                    location="host",
                    status="proposed",
                    timeout_seconds=60,
                ),
                Question(run_id=run.id, agent_id=lead.id, question=f"{tag} asks?", options=[]),
                Question(
                    run_id=run.id,
                    agent_id=lead.id,
                    question=f"{tag} decided?",
                    options=["Yes", "No"],
                    status="answered",
                    answer="Yes",
                    lead_why=why,
                ),
                *(
                    BacklogTask(
                        project_id=pid,
                        title=f"{tag} {status}",
                        status=status,
                        position=1,
                        created_by="agent",
                    )
                    for status in ("proposed", "review")
                ),
                *(
                    Parked(
                        away_run_id=night.id,
                        task_id=job.id,
                        seq=seq,
                        kind=kind,
                        what=what,
                        data={},
                    )
                    for seq, (kind, what) in enumerate(
                        [("command", f"npm run {tag}"), ("push", f"push koloni/{tag}")], 1
                    )
                ),
                Merge(run_id=run.id, agent_id=lead.id, status="pending", files=[{"path": "a"}]),
            ]
        )
        session.commit()


def read(client, pid):
    with client.app.state.session_factory() as session:
        return status_now.answer(session, pid)


def test_it_reads_what_waits_and_what_was_done_of_its_own_project_alone(client, tmp_path):
    a, in_a = chat(client, tmp_path / "a")
    b, in_b = chat(client, tmp_path / "b")
    seed(client, a, in_a, "alpha")
    seed(client, b, in_b, "bravo")
    said = read(client, a)
    for one in (
        '"python alpha.py"',  # (a command's card)
        '"alpha asks?"',  # (a question's)
        '"npm run alpha"',  # (parked)
        '"push koloni/alpha"',  # (the morning's push)
        '"alpha proposed"',  # (To-do's proposal)
        '"alpha review"',  # (at "done?")
        '"koloni/alpha", 3 commits',  # (a branch, its commits on record)
        '"alpha decided?" -> "Yes"; why: "the tests need it"',  # (a decision)
        "Spent this month:",
    ):
        assert one in said, (one, said)
    assert "bravo" not in said and "alpha" not in read(client, b)
    assert said.startswith(status_now.HEAD) and len(said) <= status_now.MOST_CHARS


def test_an_empty_project_says_none_of_each_never_a_guess(client, tmp_path):
    pid, _cid = chat(client, tmp_path / "a")
    said = read(client, pid)
    for kind in ("Cards", "Parked while away", "To-do proposals", "Work kept, not taken in"):
        assert f"{kind}: none." in said
    assert "Decisions taken for the user, newest first: none yet." in said
    assert "None" not in said and "null" not in said


def test_a_secret_is_masked_and_words_that_read_like_orders_are_marked_as_data(
    client, tmp_path, monkeypatch
):
    monkeypatch.setattr(raw, "_known", lambda fresh=False: raw.spellings([SECRET]))
    pid, cid = chat(client, tmp_path / "a")
    seed(client, pid, cid, f"key {SECRET}", why=ORDERS)
    said = read(client, pid)
    assert SECRET not in said and raw.HIDDEN in said
    # (KOLONİ's note stands before the quotes: the words are never KOLONİ's own)
    assert f"why: ({injection.NOTE}) " in said and f'"{ORDERS}"' in said


def test_it_is_cut_at_3_kb_by_whole_lines_with_a_line_that_says_so(client, tmp_path):
    pid, cid = chat(client, tmp_path / "a")
    for n in range(8):
        seed(client, pid, cid, f"{n}" + "x" * 200)
    said = read(client, pid)
    assert len(said) <= status_now.MOST_CHARS
    assert said.splitlines()[-1].startswith("... ") and "more lines cut" in said
    lines = [f"line {n} " + "y" * 50 for n in range(100)]
    capped = status_now._capped(lines)
    assert (
        len(capped) <= status_now.MOST_CHARS
        and capped.splitlines()[:-1] == lines[: len(capped.splitlines()) - 1]
    )


def test_offered_to_the_orchestrator_never_to_a_sub_agent(make_client, wait_run, project_dir):
    def asks(id):
        return StepResult("", [ToolCallRequest(id, "read_status", "{}")], 1, 1)

    client, model = make_client(
        {
            "Lead": [
                asks("r1"),
                step(call("spawn_agent", {"role": "Coder", "task": "look"}, "s")),
                text("done"),
            ],
            "Coder": [asks("r2"), text("could not")],
        }
    )
    cid, run_id = begin(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert all("read_status" in one for one in tools_of(model, "Lead"))
    assert tools_of(model, "Coder") and not any(
        "read_status" in one for one in tools_of(model, "Coder")
    )
    lead, coder = sorted(
        (one for one in snap["tool_calls"] if one["name"] == "read_status"),
        key=lambda one: one["seq"],
    )
    assert lead["status"] == "succeeded" and lead["result"].startswith(status_now.HEAD)
    assert coder["status"] == "failed" and NOT_HERE in coder["result"]
