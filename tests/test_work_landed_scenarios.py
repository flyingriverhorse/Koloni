"""B-205: the Orchestrator said the work was done when it was not in the project.

Contract:
- A recipe's agents work in one copy: what a step's agent wrote before it failed stays there, and
  the agent the user's Try again opens goes on from it - its opener is told what it wrote.
- A Lead that ends its turn before its recipe's end leaves the work as a kept copy with its files:
  the Take in card on Ready for you.
- At a working turn's end KOLONİ says where its work is, from the records - not the model's words:
  a "landed" message ("In the project: ...", "Not in the project yet: ...", "Nothing reached the
  project."), after the Lead's answer. The Lead is told what Take in put in the project.
"""

from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import teams_of
from tests.test_claim_scenarios import write
from tests.test_parallel import until
from tests.test_recipe_run_scenarios import (
    READY,
    answer,
    asked,
    by_call,
    made,
    manual,
    one_step,
    row,
)
from tests.test_recipes_scenarios import graph
from tests.test_recipes_scenarios import step as part
from tests.test_spawn import call, spawn, step


def landed(snap):
    return [m["content"] for m in snap["messages"] if m["role"] == "landed"]


def build_and_review(client):
    return made(client, "Build and review", graph(
        [part("build", "Build it", {"role": "Coder"}),
         part("review", "Review it", {"role": "Reviewer"}, done_when="no_findings")],
        [("start", "build"), ("build", "review"), ("review", "end")]))


def test_try_again_goes_on_from_what_the_failed_agent_wrote(make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [spawn("Coder", "build", "c1"), spawn("Coder", "build again", "c2"), text("done")],
        "Coder": [step(write("a.py", "a = 1\n")), RuntimeError("its model broke")],
        "Coder 2": [step(call("read_file", {"path": "a.py"}, "rd")), text("it is there")],
    })
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], one_step(client, "Just build", "Coder")))
    answer(client, asked(until(client, cid, asked)), "Try again")
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    # The new agent read the failed one's file: the copy is the recipe's, not the agent's.
    read = next(t for t in snap["tool_calls"] if t["name"] == "read_file")
    assert "a = 1" in read["result"]
    # Its opener is told from the record what the failed one wrote (K-kanit's line).
    assert 'wrote 1 ("a.py")' in by_call(snap)[0][1]
    answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id)
    assert (project_dir / "a.py").read_bytes() == b"a = 1\n"
    assert landed(snap) == ["In the project: a.py (+1 −0)."]
    # The Lead is told what Take in put in the project, for its answer.
    assert "In the project: a.py (+1 −0)." in by_call(snap)[1][1]


def test_a_turn_that_ends_before_its_recipes_end_keeps_its_work_for_take_in(make_client, wait_run, project_dir):
    client, _model = make_client({
        # (The Lead answers before it opens the Reviewer: the row is still at work.)
        "Lead": [spawn("Coder", "build", "c1"), text("Implemented and tested.")],
        "Coder": [step(write("a.py", "a = 1\n")), text("built")],
    })
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], build_and_review(client)))
    snap = wait_run(client, cid, run_id)
    assert not (project_dir / "a.py").exists()
    assert row(snap)["status"] == "stopped"
    merge = next(m for m in snap["merges"] if m["run_id"] == run_id)
    # A kept copy with its file: its Take in card waits on Ready for you (`keptToTake`).
    assert merge["status"] == "kept" and [f["path"] for f in merge["files"]] == ["a.py"]
    assert landed(snap) == [
        "Not in the project yet: a.py waits in Ready for you - Take in to apply it."]
    # After the Lead's answer: the turn's last word in the chat is KOLONİ's.
    assert [m["role"] for m in snap["messages"]][-2:] == ["assistant", "landed"]


def test_a_rejected_card_says_nothing_reached_the_project(
    make_client, wait_run, project_dir
):
    from tests.test_board_scenarios import ORIGIN
    from tests.test_copy_scenarios import one

    client, _model, cid, run_id = one(
        make_client, project_dir, [step(write("a.txt", "A")), text("A done")], permission_mode="ask")
    snap = until(client, cid, lambda s: [m["status"] for m in s["merges"]] == ["pending"])
    client.headers["Origin"] = ORIGIN
    assert client.post(f"/api/merges/{snap['merges'][0]['id']}/reject").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert landed(snap) == ["Nothing reached the project."]


def test_a_lead_that_writes_in_the_project_itself_is_said_in_it_and_a_plain_answer_is_not(
    make_client, wait_run, project_dir
):
    from tests.test_spawn import begin

    client, _model = make_client({"Lead": [step(write("b.py", "b = 1\nc = 2\n")), text("written"),
                                           text("just words")]})
    # (The Lead writes itself: slice 48's default hands code to a Coder.)
    cid, run_id = begin(client, project_dir, mode="auto_edit", lead_hands_code=False)
    snap = wait_run(client, cid, run_id)
    assert landed(snap) == ["In the project: b.py (+2 −0)."]
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "and?"},
                         headers={"Origin": "http://127.0.0.1:8790"}).json()
    snap = wait_run(client, cid, posted["run"]["id"])
    assert len(landed(snap)) == 1  # (a turn that changed no file: nothing said)


def test_files_waiting_are_named_up_to_three_and_the_rest_counted():
    from app.agent.merge import _named

    assert [_named(["a.py"]), _named(["a.py", "b.py"]), _named(["a.py", "b.py", "c.py"])] == [
        "a.py", "a.py and b.py", "a.py, b.py and c.py"]
    assert _named(["a", "b", "c", "d", "e"]) == "a, b, c and 2 more"


def test_a_file_changed_back_is_not_in_the_project_and_a_command_there_is_said(
    make_client, wait_run, project_dir
):
    from tests.fakes import Script, ScriptedExecutor
    from tests.test_spawn import begin

    client, _model = make_client({"Lead": [
        step(write("hello.py", "print('yo')\n")), step(write("hello.py", "print('hi')\n", id="w2")),
        step(call("run_command", {"command": "python make.py"}, "rc")), text("all done")]},
        executor=ScriptedExecutor([Script(["made\n"])]))
    cid, run_id = begin(client, project_dir, mode="full_auto", lead_hands_code=False)
    snap = wait_run(client, cid, run_id)
    assert [c["status"] for c in snap["commands"]] == ["exited"]
    # (What a command wrote in the project is on no record: "nothing reached" would not be true.)
    assert landed(snap) == ["No file change on record reached the project, but commands ran in it."]


def test_what_went_in_is_read_from_first_record_to_last_and_named_three_with_one_total():
    from app.agent.merge import _in_the_project, _went_in
    from app.db.models import FileChange
    from app.workspace import sha256_text

    def rec(path, before, after, kind="modify", after_from=None, sha=None):
        return FileChange(path=path, kind=kind, before_content=before, after_content=after,
                          after_sha=sha or sha256_text(after), after_from=after_from,
                          status="applied")

    went = _went_in([
        rec("made.py", None, "x\n", "create"), rec("made.py", "x\n", "", "delete"),  # made, deleted
        rec("back.py", "a\n", "b\n"), rec("back.py", "b\n", "a\n"),                 # changed back
        rec("gone.py", "a\n", "", "delete"),
        rec("logo.png", None, "(2 KB, image: logo.png as you sent it)", "create", "k1", "f" * 64),
        rec("a.py", "a\n", "a\nb\nc\n"), rec("b.py", None, "1\n", "create")])
    assert went == {"gone.py": "deleted", "logo.png": "binary", "a.py": (2, 0), "b.py": (1, 0)}
    assert _in_the_project(went) == (
        "In the project: gone.py (deleted), logo.png (binary), a.py and 1 more: +3 −0 in all.")
    assert _in_the_project({"server.py": (1, 1)}) == "In the project: server.py (+1 −1)."
    # (A merge file with no count - a branch's 31st, a mode-only change - is named, not counted.)
    assert _in_the_project({"a.py": (1, 1), "big.txt": None}) == (
        "In the project: a.py and big.txt: +1 −1 in all.")
    assert _in_the_project({"big.txt": None}) == "In the project: big.txt."
