"""Slice 29b-3 (dilim 29 §2.6-3, -4): a member waits for an item another holds and is given what
came of it, rather than doing the same work; and an item that looks like one already on the
list is added all the same, with the question whether it is the same work."""

from types import SimpleNamespace

from tests.conftest import Gate
from tests.test_chat_flow import text
from tests.test_parallel import until
from tests.test_room_scenarios import LONG, add, finish, post, results, start, take, wait
from tests.test_spawn import call, step


def waited(snap):
    """The Reviewer's wait_for_item came back - not before its call is on record."""
    return [status for status, _ in results(snap, "Reviewer", "wait_for_item")][:1] == ["succeeded"]


def wait_for(item, id="wi"):
    return call("wait_for_item", {"item": item}, id)


def agent(snap, name):
    return next(a for a in snap["agents"] if a["name"] == name)


def test_a_member_waits_for_an_item_and_is_given_its_result(make_client, wait_run, project_dir):
    held = Gate()
    client, _model, cid, run_id, _room = start(make_client, project_dir, {
        "Coder": [step(add("Find why the greeting is wrong", None, "a1"), take(1, "t1")),
                  held.step(step(finish(1, "it printed hi: a typo", "f"))), text("Done.")],
        "Reviewer": [step(add("Write the notes", None, "a2"), take(2, "t2")),
                     step(wait_for(9, "w9"), wait_for(2, "w2"), wait_for(1, "w1")),
                     text("Done.")],
    })
    until(client, cid, lambda s: agent(s, "Reviewer")["status"] == "waiting", timeout=LONG)
    held.release()
    snap = wait_run(client, cid, run_id, timeout=LONG)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    missing, mine, waited = results(snap, "Reviewer", "wait_for_item")
    assert missing[0] == "failed" and "no item 9" in missing[1]
    assert mine[0] == "failed" and "yours" in mine[1]
    assert waited[0] == "succeeded" and "it printed hi: a typo" in waited[1]


def test_an_item_that_is_done_already_is_given_at_once_and_an_open_one_is_refused(
    make_client, wait_run, project_dir
):
    client, _model, cid, run_id, _room = start(make_client, project_dir, {
        "Coder": [step(add("Find why", None, "a1"), take(1, "t1"), add("Nobody's", None, "a2")),
                  step(finish(1, "found it", "f")), text("Done.")],
        "Reviewer": [text("Nothing to add."), step(wait_for(2, "w2")),
                     step(wait_for(1, "w1")), text("Done.")],
    })
    snap = wait_run(client, cid, run_id, timeout=LONG)
    nobodys, done = results(snap, "Reviewer", "wait_for_item")
    assert nobodys[0] == "failed" and "nobody holds" in nobodys[1]
    assert done[0] == "succeeded" and "found it" in done[1]


def test_an_item_like_one_on_the_list_is_added_and_the_adder_is_asked(
    make_client, wait_run, project_dir
):
    client, _model, cid, run_id, _room = start(make_client, project_dir, {
        "Coder": [step(add("Fix the greeting in hello.py", None, "a1"), take(1, "t1")),
                  step(finish(1, "fixed", "f")), text("Done.")],
        "Reviewer": [step(add("Fix greeting of hello.py", None, "a2"),
                          add("Write the release notes", None, "a3")), text("Done.")],
    })
    snap = wait_run(client, cid, run_id, timeout=LONG)
    like, other = results(snap, "Reviewer", "add_item")
    assert like[0] == "succeeded" and "added as item 2" in like[1]
    assert "looks like item 1, held by Coder" in like[1]
    assert "looks like" not in other[1]


def waiting(client, cid, name):
    return until(client, cid, lambda s: agent(s, name)["status"] == "waiting", timeout=LONG)


def test_the_wait_ends_when_the_holders_part_is_over_with_the_item_open(
    make_client, wait_run, project_dir
):
    held = Gate()
    client, _model, cid, run_id, _room = start(make_client, project_dir, {
        "Coder": [step(add("Find why", None, "a1"), take(1, "t1")), held.step(text("Done."))],
        "Reviewer": [text("Nothing to add."), step(wait_for(1)), text("Done.")],
    })
    waiting(client, cid, "Reviewer")
    held.release()
    snap = wait_run(client, cid, run_id, timeout=LONG)
    ((status, said),) = results(snap, "Reviewer", "wait_for_item")
    assert status == "succeeded" and "item 1 is nobody's again" in said


def test_a_post_ends_the_wait_before_the_item_is_closed(make_client, wait_run, project_dir):
    says, closes = Gate(), Gate()
    client, _model, cid, run_id, _room = start(make_client, project_dir, {
        "Coder": [step(add("Find why", None, "a1"), take(1, "t1")),
                  says.step(step(post("result", "halfway there"))),
                  closes.step(step(finish(1, "found it"))), text("Done.")],
        "Reviewer": [text("Nothing to add."), step(wait_for(1)), text("Done.")],
    })
    waiting(client, cid, "Reviewer")
    says.release()
    until(client, cid, waited, timeout=LONG)
    closes.release()
    snap = wait_run(client, cid, run_id, timeout=LONG)
    ((_status, said),) = results(snap, "Reviewer", "wait_for_item")
    assert "something was said in the room before item 1 was closed" in said


def test_a_holder_that_waits_itself_is_not_waited_for(make_client, wait_run, project_dir):
    held = Gate()
    client, _model, cid, run_id, _room = start(make_client, project_dir, {
        "Coder": [step(add("Find why", None, "a1"), take(1, "t1")), wait(), text("Done.")],
        "Reviewer": [text("Nothing to add."), held.step(step(wait_for(1))),
                     step(post("result", "go on")), text("Done.")],
    })
    waiting(client, cid, "Coder")
    held.release()
    snap = wait_run(client, cid, run_id, timeout=LONG)
    ((status, said),) = results(snap, "Reviewer", "wait_for_item")
    assert status == "failed" and "not at work itself (waiting for a post)" in said


def test_a_holder_that_waits_for_a_file_of_the_waiters_is_not_waited_for(
    make_client, wait_run, project_dir
):
    held, reads = Gate(), Gate()
    client, _model, cid, run_id, _room = start(make_client, project_dir, {
        "Coder": [step(add("Find why", None, "a1"), take(1, "t1")),
                  held.step(step(finish(1, "found it"))), text("Done.")],
        "Reviewer": [text("Nothing to add."), reads.step(step(wait_for(1))), text("Done.")],
    })
    runner = client.app.state.runner
    real = runner.claims.waiting

    def stuck(agent_id):  # the Coder waits for a file the Reviewer holds
        if runner._name_of(agent_id) != "Coder":
            return real(agent_id)
        return [SimpleNamespace(holder=next(
            one for one, ctx in runner._ctxs.items() if ctx.name == "Reviewer"))]

    runner.claims.waiting = stuck
    held.wait_partial()  # the Coder holds item 1
    reads.release()  # (the Reviewer's wait comes only now that `stuck` is in place)
    until(client, cid, lambda s: [status for status, _ in results(
        s, "Reviewer", "wait_for_item")][:1] == ["failed"], timeout=LONG)
    runner.claims.waiting = real
    held.release()
    snap = wait_run(client, cid, run_id, timeout=LONG)
    ((status, said),) = results(snap, "Reviewer", "wait_for_item")
    assert status == "failed" and "waiting for a file you hold" in said


def test_a_post_not_read_yet_is_handed_over_before_any_wait(make_client, wait_run, project_dir):
    reads, says, closes = Gate(), Gate(), Gate()
    client, _model, cid, run_id, _room = start(make_client, project_dir, {
        "Coder": [step(add("Find why", None, "a1"), take(1, "t1")),
                  says.step(step(post("question", "which file?"))),
                  closes.step(step(finish(1, "found it"))), text("Done.")],
        "Reviewer": [text("Nothing to add."), reads.step(step(wait_for(1))), text("Done.")],
    })
    reads.wait_partial()
    says.release()  # said while the Reviewer's step is under way: not given to it yet
    until(client, cid, lambda s: s["room_posts"], timeout=LONG)
    reads.release()
    until(client, cid, waited, timeout=LONG)
    closes.release()
    snap = wait_run(client, cid, run_id, timeout=LONG)
    ((_status, said),) = results(snap, "Reviewer", "wait_for_item")
    assert "you have not read yet" in said


def test_no_item_is_waited_for_while_the_work_is_shared_out(make_client, wait_run, project_dir):
    client, _model, cid, run_id, _room = start(make_client, project_dir, {
        "Coder": [step(add("Find why", None, "a1"), take(1, "t1")),
                  step(finish(1, "found it")), text("Done.")],
        "Reviewer": [step(wait_for(1)), text("Done.")],
    })
    snap = wait_run(client, cid, run_id, timeout=LONG)
    ((status, said),) = results(snap, "Reviewer", "wait_for_item")
    assert status == "failed" and "not available while the work is shared out" in said
