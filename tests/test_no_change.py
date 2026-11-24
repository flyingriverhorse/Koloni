"""L1, "Done" but nothing changed (Codex's live run, 24 Nov): a sub-agent whose role writes that
finishes with no file change on KOLONİ's record has its result open with that fact - before its
report's own words - and its card says so (`Agent.changed_nothing`); a role that only reads is never
marked, nor is one that changed a file, or ran a command that may have changed one off the record."""

import json

import pytest

from app import ledger
from app.db.models import Agent, Command, FileChange, Merge, ToolCall
from tests.test_chat_flow import text
from tests.test_ledger_tests import factory  # noqa: F401 (a fixture)
from tests.test_spawn import begin, call, spawn, step


def results(snap):
    return [t["result"] for t in snap["tool_calls"] if t["name"] == "spawn_agent"]


def test_a_coder_done_with_no_file_changed_is_said_so_first_and_a_reviewer_is_not(
    make_client, wait_run, project_dir
):
    client, model = make_client(
        [
            spawn("Coder", "Add subtract to hello.py"),
            step(call("read_file", {"path": "hello.py"}, "r1")),
            text("## Done\nAdded subtract and two tests."),
            spawn("Reviewer", "Review hello.py", id="s2"),
            text("No problems found."),
            text("All done."),
        ]
    )
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)

    coder, reviewer = results(snap)
    assert coder.startswith(f"Coder finished.\n\n{ledger.NO_CHANGE}\n\n## Done\nAdded subtract"), (
        coder
    )
    assert "wrote 0" in coder  # (and KOLONİ's count under it says the same)
    assert ledger.NO_CHANGE not in reviewer, reviewer
    kids = {a["role_name"]: a for a in snap["agents"]}
    assert (kids["Coder"]["changed_nothing"], kids["Reviewer"]["changed_nothing"]) == (True, None)
    assert kids["Lead"]["changed_nothing"] is None
    # (its report on record stays its own words)
    assert kids["Coder"]["report"] == "## Done\nAdded subtract and two tests."
    # The Orchestrator is told what the line means.
    assert "KOLONİ: this agent changed no file" in model.calls[0][0]["content"]


def test_a_coder_that_wrote_a_file_is_not_marked(make_client, wait_run, project_dir):
    client, _ = make_client(
        [
            spawn("Coder", "Write x.txt"),
            step(call("write_file", {"path": "x.txt", "content": "x"}, "w1")),
            text("## Done\nWrote x.txt."),
            text("led"),
        ]
    )
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    assert (project_dir / "x.txt").read_text() == "x"
    (coder,) = results(snap)
    assert ledger.NO_CHANGE not in coder, coder
    assert snap["agents"][1]["changed_nothing"] is None


def change(s, path, status="applied", agent="t"):
    s.add(
        FileChange(
            run_id="r",
            agent_id=agent,
            path=path,
            kind="create",
            after_content="x",
            after_sha="0" * 64,
            status=status,
        )
    )
    s.commit()


def ran(s, command, status="exited"):
    s.add(
        Command(
            run_id="r",
            agent_id="t",
            command=command,
            cwd=".",
            location="host",
            status=status,
            exit_code=0,
            output="",
            timeout_seconds=60,
        )
    )
    s.commit()


def wrote(s, path, status="succeeded"):
    """A write call on record, as a CLI's write to a secret file is noted: no change row."""
    s.add(
        ToolCall(
            run_id="r",
            agent_id="t",
            message_id="m",
            seq=0,
            provider_call_id="p",
            name="write_file",
            arguments=json.dumps({"path": path}),
            status=status,
        )
    )
    s.commit()


def test_nothing_on_record_reads_and_test_runs_change_nothing(factory):  # noqa: F811
    with factory() as s:
        assert ledger.changed_nothing(s, "t")
        ran(s, "pytest -q")
        ran(s, "cat hello.py")
        ran(s, "python gen.py", status="rejected")  # (asked, never run)
        change(s, ".koloni/tmp/notes.md")  # (its scratch: none, as in `did`)
        wrote(s, ".koloni/tmp/notes.md")
        wrote(s, "a.py", status="failed")
        assert ledger.changed_nothing(s, "t")


@pytest.mark.parametrize(
    "made",
    [
        lambda s: change(s, "a.py"),
        lambda s: change(s, "a.py", status="in_copy"),
        lambda s: change(s, "a.py", status="rejected"),  # (made, then turned down)
        lambda s: ran(s, "python gen.py"),  # (may have written off the record)
        lambda s: ran(s, "sed -i s/a/b/ a.py"),
        lambda s: wrote(s, ".env"),  # (a secret file: on record by its call alone)
        lambda s: (
            s.add(Merge(run_id="r", agent_id="t", files=[{"path": "a.py", "kind": "modify"}])),
            s.commit(),
        ),
    ],
)
def test_a_change_of_any_kind_on_record_is_a_change(factory, made):  # noqa: F811
    with factory() as s:
        made(s)
        assert not ledger.changed_nothing(s, "t")


def test_a_change_by_an_agent_it_opened_is_its_too(factory):  # noqa: F811
    with factory() as s:
        s.add(Agent(id="k", run_id="r", role_name="Coder", tools=[], parent_agent_id="t", depth=1))
        s.commit()
        change(s, "a.py", agent="k")
        assert not ledger.changed_nothing(s, "t")


def test_a_go_on_counts_the_earlier_turns_it_goes_on_from(factory):  # noqa: F811
    # (told to go on, it may report what its earlier turn did: that is no claim of nothing)
    with factory() as s:
        s.add(Agent(id="g", run_id="r", role_name="Tester", tools=[], continues_id="t"))
        s.commit()
        assert ledger.changed_nothing(s, "g")
        change(s, "a.py")
        assert not ledger.changed_nothing(s, "g")
