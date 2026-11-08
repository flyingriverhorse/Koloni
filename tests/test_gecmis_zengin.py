"""K-gecmis-zengin: an earlier turn's record (ledger), a left-out result's gist, recall_output."""

import json
import time
from datetime import datetime

from sqlalchemy import select, update

from app import injection, ledger
from app.agent import TRIMMED, _compacted, _in_words, _Record, _theirs
from app.commands import RECALL_HINT, recallable
from app.db.models import Agent, Command, Compare, FileChange, Run, ToolCall
from app.model_client import StepResult
from tests.fakes import Script, ScriptedExecutor
from tests.test_chat_flow import text
from tests.test_native_agent import native_app, start  # noqa: F401
from tests.test_spawn import begin, call, spawn, step

SECRET = "sk-test-0123456789abcdefghijklmnop"
LONG = "".join(f"line {n:05}\n" for n in range(2000))  # 22 000 characters: cut for the model
OWN = {"Origin": "http://127.0.0.1:8790"}
UNKNOWN = "error: no earlier output of this conversation has that id"


def said(messages, head=ledger.HEAD):
    return [m["content"] for m in messages if str(m.get("content") or "").startswith(head)]


def recalled(model, start=None):
    """A step that asks recall_output for the call the history's last hint names."""
    async def ask(_on_delta):
        last = next(str(m["content"]) for m in reversed(model.calls[-1])
                    if "recall_output id=" in str(m["content"]))
        wanted = last.split("recall_output id=", 1)[1].split(")", 1)[0]
        return StepResult("", [call("recall_output", {"id": wanted, **(
            {"start": start} if start else {})}, "rc")], 5, 2)
    return ask


def call_of(client, agent, name="run_command"):
    """A step that asks recall_output for `agent`'s call, as its id stands in the record."""
    async def ask(_on_delta):
        with client.app.state.session_factory() as session:
            wanted = session.scalar(select(ToolCall.id).join(Agent, Agent.id == ToolCall.agent_id)
                                    .where(Agent.name == agent, ToolCall.name == name))
        return StepResult("", [call("recall_output", {"id": wanted}, f"rc-{agent}")], 5, 2)
    return ask


def again(client, model, cid, wanted, **sent):
    """A later turn whose agent asks recall_output for `wanted`; its call as on record."""
    model.steps += [step(call("recall_output", {"id": wanted, **sent}, "rc")), text("done")]
    return client.post(f"/api/conversations/{cid}/messages", json={"content": "and then?"},
                       headers=OWN).json()["run"]["id"]


def recall_in(snap):
    return [c for c in snap["tool_calls"] if c["name"] == "recall_output"]


def commanded(make_client, wait_run, project_dir, output=LONG, command="python make.py"):
    """A turn that ran one command; (client, model, cid, its call's id)."""
    client, model = make_client([step(call("run_command", {"command": command}, "c1")),
                                 text("done")], executor=ScriptedExecutor([Script([output])]))
    cid, run_id = begin(client, project_dir, mode="full_auto")
    return client, model, cid, wait_run(client, cid, run_id)["tool_calls"][0]["id"]


# --- A: the record of a turn ----------------------------------------------------------------


def test_a_turns_record_follows_it_and_is_said_the_same_at_every_later_turn(
    make_client, wait_run, project_dir
):
    executor = ScriptedExecutor([
        Script(["....F\n", "==== 1 failed, 4 passed in 0.2s ====\n"], exit_code=1),
        Script(["ok\n"])])
    client, model = make_client([
        step(call("read_file", {"path": "hello.py"}, "r1")),
        step(call("write_file", {"path": "hello.py", "content": "print('hello')\nprint(1)\n"},
                  "w1")),
        step(call("run_command", {"command": "python -m pytest -q"}, "t1")),
        step(call("run_command", {"command": "git status"}, "g1")),
        text("first answer"), text("second answer"), text("third answer")],
        executor=executor)
    cid, run_id = begin(client, project_dir, mode="full_auto", lead_hands_code=False)
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    for words in ("and now?", "and then?"):
        posted = client.post(f"/api/conversations/{cid}/messages", json={"content": words})
        wait_run(client, cid, posted.json()["run"]["id"])
    second, third = model.calls[-2], model.calls[-1]
    expected = "\n".join([
        ledger.HEAD,
        '- files changed: "hello.py" (+2 -1)',
        '- files read: "hello.py"',
        '- commands: "python -m pytest -q" (exit 1), "git status" (exit 0)',
        '- last tests: "python -m pytest -q" exit 1, "1 failed, 4 passed in 0.2s"'])
    assert said(second) == [expected]
    # the same words, in the same place, a turn later (none for the second turn, which did
    # nothing of the kind): the cache keeps what is before them
    assert said(third) == [expected]
    at = [m["content"] for m in second].index(expected)
    assert second[at - 1]["content"] == "first answer"  # (right after the turn it is of)
    assert third[:at + 1] == second[:at + 1]


def test_a_sub_agents_record_is_of_its_own_chain_only(make_client, wait_run, project_dir):
    (project_dir / "other.txt").write_text("other\n", encoding="utf-8")
    client, model = make_client({
        "Lead": [spawn("Coder", "look at hello"), spawn("Reviewer", "look at other", "s2"),
                 text("first"),
                 step(call("message_agent", {"to": "Coder", "message": "go on"}, "m1")),
                 text("second")],
        "Coder": [step(call("read_file", {"path": "hello.py"}, "r1")), text("read hello"),
                  text("went on")],
        "Reviewer": [step(call("read_file", {"path": "other.txt"}, "r2")), text("read other")]})
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    wait_run(client, cid, run_id)
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "go on"})
    wait_run(client, cid, posted.json()["run"]["id"])
    assert said(model.calls_of["Coder"][-1]) == [f'{ledger.HEAD}\n- files read: "hello.py"']
    # the Lead's is of the whole turn
    assert said(model.calls_of["Lead"][-2]) == [
        f'{ledger.HEAD}\n- files read: "hello.py", "other.txt"']


def test_the_leads_record_says_where_a_sub_agents_command_output_is(make_client, wait_run, project_dir):
    # R105 (live): the Lead saw the Coder's command cut short ("pri…") and no id to recall it by.
    command = "python -c \"import time; time.sleep(0); print('printed after the long sleep')\""
    client, model = make_client({
        "Lead": [spawn("Coder", "run it"), text("first")],
        "Coder": [step(call("run_command", {"command": command}, "c1")), text("ran")],
    }, executor=ScriptedExecutor([Script(["printed after the long sleep\n"])]))
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    ran = next(c for c in wait_run(client, cid, run_id)["tool_calls"] if c["name"] == "run_command")
    model.by_agent["Lead"] += [recalled(model), text("done")]
    later = client.post(f"/api/conversations/{cid}/messages", json={"content": "its output?"},
                        headers=OWN).json()["run"]["id"]
    snap = wait_run(client, cid, later)
    record = said(model.calls_of["Lead"][-2])[0]
    assert f'(exit 0){RECALL_HINT.format(id=ran["id"])}' in record
    assert record == said(model.calls_of["Lead"][-1])[0]  # (the same bytes a step later)
    assert "printed after the long sleep" in recall_in(snap)[0]["result"]


def test_a_folded_sub_agent_command_keeps_its_recall_id(make_client, wait_run, project_dir):
    # B-316 (live): past the first MOST, commands were only counted ("+10 more"), with no id - the
    # Debugger command the Lead needed was among them, out of its reach.
    many = ledger.MOST + 3
    client, model = make_client({
        "Lead": [spawn("Coder", "run them"), text("first")],
        "Coder": [*(step(call("run_command", {"command": f"python step{n}.py"}, f"c{n}"))
                    for n in range(many)), text("ran")],
    }, executor=ScriptedExecutor([Script([f"out {n}\n"]) for n in range(many)]))
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    ran = [c for c in wait_run(client, cid, run_id)["tool_calls"] if c["name"] == "run_command"]
    model.by_agent["Lead"] += [text("done")]
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "and?"})
    wait_run(client, cid, posted.json()["run"]["id"])
    record = said(model.calls_of["Lead"][-1])[0]
    assert len(ran) == many and all(one["id"] in record for one in ran)
    assert '"python step10.py" (exit 0) id=' in record and "more" not in record


def test_a_command_line_in_the_record_is_masked(make_client, wait_run, project_dir, monkeypatch):
    monkeypatch.setenv("KG_TEST_API_KEY", SECRET)
    client, model, cid, _id = commanded(make_client, wait_run, project_dir, "ok\n",
                                        f"python make.py --key {SECRET}")
    model.steps += [text("again")]
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "and now?"})
    wait_run(client, cid, posted.json()["run"]["id"])
    assert said(model.calls[-1]) == [
        f'{ledger.HEAD}\n- commands: "python make.py --key ***" (exit 0)']


def test_compaction_takes_the_record_in_as_koloni_s_never_as_the_users():
    record = _Record(role="user", content=f"{ledger.HEAD}\n- files read: \"a.py\"")
    assert not _theirs(record)
    assert _in_words(record).startswith("KOLONİ: ") and "the user's words" not in _in_words(record)
    history = [{"role": "system", "content": "s"}, {"role": "user", "content": "hi"},
               {"role": "assistant", "content": "done"}, record,
               {"role": "user", "content": "and now?"}]
    kept = _compacted(history, 4, "it read a.py")
    assert record not in kept and {"role": "user", "content": "hi"} in kept


def test_a_spawn_result_says_what_the_agent_and_those_it_opened_did_by_the_record(
    make_client, wait_run, project_dir
):
    # K-kanit: the Coder claims more than it did; the line under its report counts what it did.
    writes = [step(call("write_file", {"path": f"{n}.py", "content": "x = 1\n"}, f"w{n}"))
              for n in "abcd"]
    client, model = make_client({
        "Lead": [spawn("Coder", "fix it"), text("done")],
        "Coder": [step(call("read_file", {"path": "hello.py"}, "r1")), *writes,
                  step(call("run_command", {"command": "git status"}, "g1")),
                  spawn("Tester", "run the tests", "s2"), text("All verified, tests pass.")],
        "Tester": [step(call("run_command", {"command": "python -m pytest -q"}, "t1")),
                   text("ran: python -m pytest -q - 1 failed")],
        "Reviewer": [text("looked")],
    }, executor=ScriptedExecutor([Script(["ok\n"]),
                                  Script(["==== 1 failed, 4 passed ====\n"], exit_code=1)]))
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    back = next(m["content"] for m in model.calls_of["Lead"][-1] if m["role"] == "tool")
    assert ("All verified, tests pass.\n\nWhat it did (with the 1 agent it opened), from KOLONİ's "
            'record: read 1 file, wrote 4 ("a.py", "b.py", "c.py", +1 more), ran 2 commands '
            "(1 failed), last test run failed (exit 1), 0 web.") in back
    coder = next(a["id"] for a in snap["agents"] if a["name"] == "Coder")
    tester = next(a["id"] for a in snap["agents"] if a["name"] == "Tester")
    with client.app.state.session_factory() as session:
        # A CLI whose reads KOLONİ does not see: no zero is said (a read on record still is),
        # and nothing where nothing is known.
        assert ledger.did(session, coder, seen=False) == (
            "What it did (with the 1 agent it opened), from KOLONİ's record: read 1 file, wrote 4 "
            '("a.py", "b.py", "c.py", +1 more), ran 2 commands (1 failed), last test run failed '
            "(exit 1).")
        assert ledger.did(session, tester) == (
            "What it did, from KOLONİ's record: read 0 files, wrote 0, ran 1 command (1 failed), "
            "last test run failed (exit 1), 0 web.")
        # `pytest | tail` ends 0 whatever the tests did: its output's count says failed.
        session.execute(update(Command).where(Command.agent_id == tester).values(exit_code=0))
        assert "last test run failed (exit 0)" in ledger.did(session, tester)
        session.execute(update(Command).values(output="==== 5 passed ===="))
        assert ('last test run passed ("python -m pytest -q", exit 0: checked already - no need '
                "to run it again)") in ledger.did(session, tester)
        # (Only of a command that is a test run: one that names a test tool may run nothing.)
        tests = update(Command).where(Command.agent_id == tester)
        session.execute(tests.values(command="echo pytest"))
        said = ledger.did(session, tester)
        assert "last test run passed" in said and "no need" not in said
        session.execute(tests.values(command=r".venv\Scripts\python.exe -m unittest -q"))
        assert "no need to run it again" in ledger.did(session, tester)
        assert "no need to run it again" in ledger.did(session, coder)
        # B-382: a file of its that changed after the run was not seen by it - it may be needed.
        session.execute(update(Command).values(created_at=datetime(2000, 1, 1)))
        said = ledger.did(session, coder)
        assert "last test run passed" in said and "no need" not in said
        session.execute(update(Command).values(status="rejected"))
        session.execute(update(FileChange).values(status="rejected"))
        assert ledger.did(session, tester, seen=False) is None


# --- B: a left-out result's gist ------------------------------------------------------------


def test_trimming_keeps_the_record_and_says_what_a_left_out_read_was(
    make_client, wait_run, project_dir, settings_env
):
    settings_env["KOLONI_CONTEXT_CHARS"] = "2500"
    (project_dir / "big.txt").write_text("line\n" * 300, encoding="utf-8")
    client, model = make_client([
        step(call("read_file", {"path": "big.txt"}, "r1")),
        step(call("read_file", {"path": "hello.py"}, "r2")), text("read it"), text("again")])
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    read_id = snap["tool_calls"][0]["id"]
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "and now?"})
    wait_run(client, cid, posted.json()["run"]["id"])
    sent = [str(m["content"]) for m in model.calls[-1]]
    assert f"{TRIMMED} read big.txt (300 lines){RECALL_HINT.format(id=read_id)}" in sent
    assert f'{ledger.HEAD}\n- files read: "big.txt", "hello.py"' in sent


def test_a_gist_is_made_from_the_call_alone():
    assert ledger.gist("read_file", '{"path": "app/x.py"}',
                       "     1\tx\n[showing lines 1-320 of 320]") == "read app/x.py (320 lines)"
    assert ledger.gist("read_file", '{"path": "a.py", "offset": 5}',
                       "[showing lines 5-9 of 40]") == "read a.py (lines 5-9 of 40)"
    assert ledger.gist("run_command", '{"command": "pytest -q"}',
                       "exit code 1 (0.3s)\nF") == "ran `pytest -q`: exit 1"
    assert ledger.gist("search", '{"pattern": "foo"}', "a.py:1: foo\nb.py:7: foo()") == (
        'search "foo": 2 matches')
    assert ledger.gist("search", '{"pattern": "foo"}', "no matches") == 'search "foo": 0 matches'
    assert ledger.gist("spawn_agent", "{}", "Reviewer finished.") is None
    assert ledger.gist("read_file", "not json", "x") is None


# --- C: recall_output -----------------------------------------------------------------------


def test_recall_output_gives_a_long_commands_whole_output_page_by_page(
    make_client, wait_run, project_dir
):
    executor = ScriptedExecutor([Script([LONG])])
    client, model = make_client([
        step(call("run_command", {"command": "python make.py"}, "c1"))], executor=executor)
    model.steps += [recalled(model), recalled(model, start=401), text("done")]
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    ran, first, second = snap["tool_calls"]
    assert RECALL_HINT.format(id=ran["id"]) in ran["result"] and "line 00500" not in ran["result"]
    assert first["status"] == "succeeded" and first["result"].startswith("(lines 1-400 of 2000)")
    assert "line 00399" in first["result"] and "read again with start 401" in first["result"]
    assert second["result"].startswith("(lines 401-800 of 2000)\nline 00400")


def test_recall_output_gives_nothing_of_another_conversation(make_client, wait_run, project_dir):
    client, model, _cid, theirs = commanded(make_client, wait_run, project_dir)
    model.steps += [step(call("recall_output", {"id": theirs}, "rc")), text("nothing")]
    other, other_run = begin(client, project_dir, mode="full_auto")
    (asked,) = wait_run(client, other, other_run)["tool_calls"]
    assert (asked["status"], asked["result"]) == ("failed", UNKNOWN)


def test_recall_output_gives_nothing_of_another_topic(make_client, wait_run, project_dir):
    client, model, cid, earlier = commanded(make_client, wait_run, project_dir)
    model.steps += [step(call("recall_output", {"id": earlier}, "rc")), text("nothing")]
    posted = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "something else", "new_topic": True}, headers=OWN)
    (asked,) = recall_in(wait_run(client, cid, posted.json()["run"]["id"]))
    assert asked["result"] == UNKNOWN


def test_recall_output_gives_nothing_of_a_comparison_side_not_chosen(
    make_client, wait_run, project_dir
):
    client, model, cid, side = commanded(make_client, wait_run, project_dir)
    with client.app.state.session_factory() as session:  # (the turn as a side never chosen)
        compare = Compare(conversation_id=cid, sides=[])
        session.add(compare)
        session.flush()
        session.get_one(Run, session.get_one(ToolCall, side).run_id).compare_id = compare.id
        session.commit()
    (asked,) = recall_in(wait_run(client, cid, again(client, model, cid, side)))
    assert asked["result"] == UNKNOWN


def test_a_sub_agent_recalls_its_leads_output_and_never_a_siblings(
    make_client, wait_run, project_dir
):
    executor = ScriptedExecutor([Script([LONG]), Script(["coder's\n"])])
    client, model = make_client({
        "Lead": [step(call("run_command", {"command": "python make.py"}, "c0")),
                 spawn("Coder", "build it"), spawn("Reviewer", "check it", "s2"), text("done")],
        "Coder": [step(call("run_command", {"command": "python build.py"}, "c1")),
                  text("built")],
        "Reviewer": []}, executor=executor)
    model.by_agent["Reviewer"] += [call_of(client, "Lead"), call_of(client, "Coder"),
                                   text("checked")]
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never",
                        lead_hands_code=False)
    snap = wait_run(client, cid, run_id, timeout=10)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    leads, siblings = recall_in(snap)
    assert leads["status"] == "succeeded"
    assert leads["result"].startswith("(lines 1-400 of 2000)")
    assert siblings["result"] == UNKNOWN


def test_recall_output_hides_a_secret_again_that_was_none_when_kept(
    make_client, wait_run, project_dir, monkeypatch
):
    late = "late-0123456789abcdefghijklmnop"
    client, model, cid, ran = commanded(make_client, wait_run, project_dir,
                                        LONG[:11000] + f"token {late}\n" + LONG[11000:])
    monkeypatch.setenv("KG_LATE_API_KEY", late)  # (a secret only now)
    (asked,) = recall_in(wait_run(client, cid, again(client, model, cid, ran, start=1001)))
    assert "token ***" in asked["result"] and late not in asked["result"]


def test_recall_output_keeps_a_secret_hidden(make_client, wait_run, project_dir, monkeypatch):
    monkeypatch.setenv("KG_TEST_API_KEY", SECRET)
    middle = LONG[:11000] + f"token {SECRET}\n" + LONG[11000:]
    executor = ScriptedExecutor([Script([middle])])
    client, model = make_client([
        step(call("run_command", {"command": "python make.py"}, "c1"))], executor=executor)
    model.steps += [recalled(model, start=1001), text("done")]
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    _ran, asked = snap["tool_calls"]
    assert "token ***" in asked["result"] and SECRET not in json.dumps(snap)


def test_what_the_user_let_be_read_once_is_neither_recalled_nor_offered_again():
    assert recallable("read_file", None, None, None)
    assert recallable("run_command", None, "in a working copy", "python make.py")
    assert not recallable("recall", None, None, None)  # (what the memory held then)
    assert not recallable("read_file", "C:/Users/x", None, None)  # outside the project
    assert not recallable("read_file", None, "a secret file", None)  # on a secret file's card
    assert not recallable("run_command", None, None, "type .env")  # a command naming one


def test_a_recall_of_what_the_memory_held_is_refused(make_client, wait_run, project_dir):
    client, model = make_client([step(call("recall", {"query": "greeting"}, "m1")), text("none")])
    cid, run_id = begin(client, project_dir, mode="full_auto")
    looked = wait_run(client, cid, run_id)["tool_calls"][0]["id"]
    (asked,) = recall_in(wait_run(client, cid, again(client, model, cid, looked)))
    assert asked["result"].startswith("error: what the memory held then is not given again")


def test_a_command_that_names_a_secret_is_not_given_again_nor_its_id_said(
    make_client, wait_run, project_dir
):
    (project_dir / ".env").write_text("A=1\n", encoding="utf-8")
    client, model = make_client([step(call("run_command", {"command": "type .env"}, "c1")),
                                 text("done")], executor=ScriptedExecutor([Script([LONG])]))
    cid, run_id = begin(client, project_dir, mode="full_auto")
    for _ in range(500):  # (asked at every level: slice 90)
        commands = client.get(f"/api/conversations/{cid}").json()["commands"]
        if commands and commands[0]["status"] == "proposed":
            break
        time.sleep(0.02)
    assert client.post(f"/api/commands/{commands[0]['id']}/approve", json={"remember": False},
                       headers=OWN).status_code == 200
    ran = wait_run(client, cid, run_id)["tool_calls"][0]
    assert "characters omitted" in ran["result"] and "recall_output" not in ran["result"]
    (asked,) = recall_in(wait_run(client, cid, again(client, model, cid, ran["id"])))
    assert asked["result"].startswith("error: that was read on the user's word")


def test_a_flagged_result_keeps_its_note_on_a_later_page(make_client, wait_run, project_dir):
    client, model = make_client([step(call("read_file", {"path": "hello.py"}, "r1")),
                                 text("read")])
    cid, run_id = begin(client, project_dir, mode="full_auto")
    read = wait_run(client, cid, run_id)["tool_calls"][0]["id"]
    with client.app.state.session_factory() as session:  # (as `_run_call` keeps one flagged)
        session.get_one(ToolCall, read).result = f"{injection.NOTE}\n" + LONG
        session.commit()
    (asked,) = recall_in(wait_run(client, cid, again(client, model, cid, read, start=401)))
    assert asked["result"].startswith(f"{injection.NOTE}\n(lines 401-800 of 2001)")


def test_recall_output_switched_off_is_not_offered(make_client, wait_run, project_dir):
    client, model = make_client([text("hi")])
    assert client.put("/api/builtin-tools/recall_output", json={"on": False},
                      headers=OWN).status_code == 200
    cid, run_id = begin(client, project_dir, mode="full_auto")
    wait_run(client, cid, run_id)
    assert "recall_output" not in [t["function"]["name"] for t in model.tool_args[0]]


def test_a_native_cli_is_offered_recall_output_and_gets_a_command_back_whole(
    native_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = native_app([
        {"run": "python make.py", "output": LONG, "exit": 1}, {"say": "Made."}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=30)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (ran,) = [c for c in snap["tool_calls"] if c["name"] == "run_command"]
    native_app.rescript([{"koloni": "recall_output", "args": {"id": ran["id"], "start": 1801}},
                         {"say": "Read it."}])
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "and the end?"})
    wait_run(client, cid, posted.json()["run"]["id"], timeout=30)
    seen = native_app.record()
    assert seen["tools"][-1] == "recall_output"  # (offered through its bridge, KOLONİ's MCP)
    got = seen["results"][0]["content"][0]["text"]
    assert got.startswith("(lines 1801-2000 of 2000)\nline 01800") and "line 01999" in got
    # the turn before, as KOLONİ's record, in what it was given
    assert '- commands: \\"python make.py\\" (exit 1)' in seen["stdin"]
