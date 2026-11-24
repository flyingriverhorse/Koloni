"""Kanıtlı bitiş after a turn that changed nothing (N1, N2): right after a turn whose checks still
failed, it says so with those failing lines - Fix it stays under the newest turn - but not after a
turn undone, nor where the chat's checks are off now; and a change made after a run that saw none
of the turn's own on record is said untested. A fake model and a scripted executor."""

from app import proof
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_writes import write
from tests.test_chat_flow import text
from tests.test_proof_end_scenarios import (
    OWN,
    PASS,
    WRITES,
    begin,
    checked,
    failing,
    run,
    texts,
)

FIX = "The tests KOLONİ ran at the end of the last turn failed: `python check.py`. Fix it."


def said_in(client, cid, run_id):
    """A turn's Checked rows (none: no section)."""
    snap = client.get(f"/api/conversations/{cid}").json()
    return [
        r for m in snap["messages"] if m["run_id"] == run_id and m["checked"] for r in m["checked"]
    ]


def failed_then(make_client, wait_run, project_dir, *after):
    """A turn whose tests still fail after a round answered with no change; the Lead's `after`."""
    client, _model = make_client(
        [write("a.py", "x = 1\n"), text("done"), text("right as it is"), *after],
        executor=ScriptedExecutor([failing()]),
    )
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    return client, cid, run_id, checked(wait_run(client, cid, run_id))


def again(client, wait_run, cid, content):
    went = client.post(f"/api/conversations/{cid}/messages", json={"content": content}).json()
    wait_run(client, cid, went["run"]["id"])
    return said_in(client, cid, went["run"]["id"])


def test_a_fix_it_turn_that_changes_nothing_says_the_tests_still_fail(
    make_client, wait_run, project_dir
):
    # (N1: Fix it's turn answered with no change - no Checked section, no Fix it left under the
    # newest turn. Its turn says the last check still fails, with the failing run's row - its
    # command, what Fix it sends.)
    client, cid, _run_id, first = failed_then(make_client, wait_run, project_dir, text("it is"))
    rows = again(client, wait_run, cid, FIX)
    assert rows[1:] == [first[0], first[2]], rows
    assert (rows[0]["kind"], rows[0]["state"], rows[0]["text"]) == (
        "unchanged",
        "note",
        proof.UNCHANGED,
    ), rows
    assert rows[1]["command"] == "python check.py" and rows[2]["state"] == "failed", rows


def test_a_turn_that_changes_nothing_after_a_pass_says_nothing(make_client, wait_run, project_dir):
    client, _model = make_client(
        [write("a.py", "x = 1\n"), text("done"), text("ok")], executor=ScriptedExecutor([PASS])
    )
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    wait_run(client, cid, run_id)
    assert again(client, wait_run, cid, "and?") == []


def test_after_its_failing_turn_is_undone_a_question_says_nothing(
    make_client, wait_run, project_dir
):
    # (review: the failing work was undone - nothing of it is in the project to still fail)
    client, cid, run_id, _first = failed_then(make_client, wait_run, project_dir, text("x is 1"))
    assert client.post(f"/api/runs/{run_id}/undo", headers=OWN).status_code == 200
    assert not (project_dir / "a.py").exists()
    assert again(client, wait_run, cid, "what is x?") == []


def test_with_the_chats_checks_off_since_a_question_says_nothing(
    make_client, wait_run, project_dir
):
    client, cid, _run_id, _first = failed_then(make_client, wait_run, project_dir, text("x is 1"))
    patched = client.patch(f"/api/conversations/{cid}", json={"after_change": "off"}, headers=OWN)
    assert patched.status_code == 200, patched.text
    assert again(client, wait_run, cid, "what is x?") == []


def test_a_change_after_a_run_that_saw_none_on_record_is_said_untested(
    make_client, wait_run, project_dir
):
    # (N2: the run saw no change of the turn on record - a command's only - and the fix round's
    # write came after it, then the model broke: that write was never tested. It was not said.)
    executor = ScriptedExecutor([Script(["\n"]), failing()])
    client, _model = make_client(
        [run(WRITES), text("done"), write("a.py", "x = 3\n", "w2"), RuntimeError("broke")],
        executor=executor,
    )
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    rows = texts(wait_run(client, cid, run_id))
    assert "Tests not run on the last change: the turn failed before its end" in rows, rows
