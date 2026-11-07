"""K-symphony - run the backlog (the user, 3 Nov): independent tasks at the same time, at most
two, dependent ones wait until what they wait for is done; Run the backlog queues every todo
task; a task not finished gets one fix round, then is stuck and the next goes on; a limit
pauses the run; the switch waits for the user's own turn."""

from types import SimpleNamespace

from sqlalchemy import select

from app import agent, backlog
from app.db.models import Agent, BacklogTask, Conversation, Merge, Project, Role, Run
from app.model_client import ModelUnavailable
from tests.test_agent_writes import write
from tests.test_backlog import setup
from tests.test_backlog_auto import auto, tasks, until, worked
from tests.test_chat_flow import text
from tests.test_claude_native import claude_app  # noqa: F401  (a fixture)
from tests.test_lead_decides import ask, held, lead_timers
from tests.test_mcp_scenarios import give, server
from tests.test_spawn import call, role_id, spawn, step


def run(client, pid):
    return client.post(f"/api/projects/{pid}/backlog/next")


def after(client, task_id, ids):
    return client.patch(f"/api/backlog/{task_id}", json={"after": ids})


def said(client, cid):
    return [m["content"] for m in client.get(f"/api/conversations/{cid}").json()["messages"]
            if m["role"] == "user"]


def test_independent_tasks_run_together_and_a_dependent_one_waits_until_done(make_client, wait_run, project_dir, gate):
    client, _model = make_client([gate.step(text("done")), gate.step(text("done")), text("done")])
    pid, (a, _b, c) = setup(client, project_dir, "a", "b", "c")
    assert after(client, c, [a]).json()["after"] == [a]
    started = run(client, pid).json()
    assert started["task_id"] == a
    seen = tasks(client, pid)
    assert (seen["a"]["status"], seen["b"]["status"]) == ("doing", "doing")
    assert (seen["c"]["status"], seen["c"]["queued"]) == ("todo", True)
    gate.release()
    worked(client, wait_run, pid, "a")
    worked(client, wait_run, pid, "b")
    # "done?" is not done: a's work may wait for Take in
    assert tasks(client, pid)["c"]["conversation_id"] is None
    client.patch(f"/api/backlog/{a}", json={"status": "done"})
    until(lambda: tasks(client, pid)["c"]["conversation_id"])
    assert worked(client, wait_run, pid, "c")["status"] == "review"


def test_what_a_task_waits_for_is_checked(client, project_dir, tmp_path):
    pid, (a, b, c) = setup(client, project_dir, "a", "b", "c")
    (tmp_path / "other").mkdir()
    other, (elsewhere,) = setup(client, tmp_path / "other", "x")
    assert after(client, a, [a]).status_code == 422
    assert after(client, a, [elsewhere]).status_code == 422
    assert after(client, b, [a]).status_code == 200 and after(client, c, [b]).status_code == 200
    circle = after(client, a, [c])  # c waits for b, which waits for a
    assert circle.status_code == 422 and "waits for it" in circle.json()["detail"]
    assert after(client, c, []).json()["after"] == []
    assert other != pid


def test_a_failed_turn_gets_one_fix_round(make_client, wait_run, project_dir):
    client, _model = make_client([ModelUnavailable("model server unreachable: refused"),
                                  text("fixed it")])
    pid, _ = setup(client, project_dir, "one")
    auto(client, pid, True)
    cid = tasks(client, pid)["one"]["conversation_id"]
    task = until(lambda: (t := tasks(client, pid)["one"])["status"] == "review" and t)
    fix = said(client, cid)[-1]
    assert fix.startswith("KOLONİ: this task is not finished: model server unreachable")
    assert task["conversation_id"] == cid and task["stuck"] is None
    assert client.get(f"/api/projects/{pid}/backlog/auto").json().items() >= {"on": True, "halt": None}.items()


def test_still_stuck_after_its_fix_round_it_says_why_and_the_next_starts(make_client, wait_run, project_dir, monkeypatch):
    monkeypatch.setattr(backlog, "MAX_PARALLEL", 1)
    client, _model = make_client([ModelUnavailable("model server unreachable: refused"),
                                  ModelUnavailable("model server unreachable: refused"),
                                  text("two done")])
    pid, _ = setup(client, project_dir, "one", "two")
    auto(client, pid, True)
    one = until(lambda: (t := tasks(client, pid)["one"])["status"] == "blocked" and t)
    assert one["stuck"].startswith("model server unreachable")
    assert sum(m.startswith("KOLONİ: this task is not finished") for m in said(client, one["conversation_id"])) == 1
    until(lambda: tasks(client, pid)["two"]["conversation_id"])
    assert worked(client, wait_run, pid, "two")["status"] == "review"
    # the user's word on it clears why
    client.patch(f"/api/backlog/{one['id']}", json={"status": "todo"})
    assert tasks(client, pid)["one"]["stuck"] is None


def test_an_orchestrator_that_says_it_could_not_finish_gets_its_fix_round(make_client, wait_run, project_dir):
    client, _model = make_client([text("Tried.\n\n**Not finished: the tests need a database.**"),
                                  text("done now")])
    pid, _ = setup(client, project_dir, "one")
    cid = run(client, pid).json()["conversation_id"]
    assert backlog.SAY_NOT_FINISHED in said(client, cid)[0]  # it is told how to say so
    until(lambda: tasks(client, pid)["one"]["status"] == "review")
    assert said(client, cid)[-1].startswith(
        "KOLONİ: this task is not finished: the tests need a database. ")


def test_a_check_failed_on_work_left_out_is_not_finished(make_client, wait_run, project_dir):
    client, _model = make_client([text("made it")])
    pid, _ = setup(client, project_dir, "one")
    cid = run(client, pid).json()["conversation_id"]
    snap = wait_run(client, cid, client.get(f"/api/conversations/{cid}").json()["runs"][0]["id"])
    with client.app.state.session_factory() as session:
        turn = session.get_one(Run, snap["runs"][0]["id"])
        assert backlog.not_finished(session, turn, "completed") is None
        session.add(Merge(run_id=turn.id, agent_id=snap["agents"][0]["id"], files=[],
                          check={"command": "pytest", "state": "failed"}))
        session.flush()
        assert backlog.not_finished(session, turn, "completed") == 'the check "pytest" did not pass'


def test_a_turn_stopped_by_the_token_limit_pauses_the_run_until_the_users_word(make_client, wait_run, project_dir):
    client, _model = make_client([text("done"), text("done")])
    pid, (one, two) = setup(client, project_dir, "one", "two")
    error = agent.OVER_LIMIT.format(used=1200, limit=1000)
    assert error.startswith(backlog.OVER_LIMIT)
    with client.app.state.session_factory() as session:
        task = session.get_one(BacklogTask, one)
        task.status, task.conversation_id = "doing", "c1"
        session.get_one(Project, pid).backlog_auto = True
        assert backlog.turn_ended(session, Run(conversation_id="c1", error=error), "failed")
        session.commit()
    assert tasks(client, pid)["one"]["status"] == "todo"  # no fix round: it would spend more
    assert client.get(f"/api/projects/{pid}/backlog/auto").json().items() >= {
        "on": True, "halt": f"Paused: {error}."}.items()
    client.patch(f"/api/backlog/{two}", json={"priority": "high"})  # (a change runs the chain)
    assert tasks(client, pid)["two"]["conversation_id"] is None
    # Run the backlog is the user's word: the pause is cleared, and the task stopped starts again
    run(client, pid)
    assert client.get(f"/api/projects/{pid}/backlog/auto").json()["halt"] is None
    assert worked(client, wait_run, pid, "two")["status"] == "review"
    assert worked(client, wait_run, pid, "one")["conversation_id"] != "c1"


def test_a_providers_limit_reached_by_the_orchestrator_pauses_the_run(make_client, wait_run, project_dir):
    client, _model = make_client([text("done")])
    pid, (one,) = setup(client, project_dir, "one")
    cid = run(client, pid).json()["conversation_id"]
    snap = wait_run(client, cid, client.get(f"/api/conversations/{cid}").json()["runs"][0]["id"])
    with client.app.state.session_factory() as session:
        turn = session.get_one(Run, snap["runs"][0]["id"])
        lead = session.get_one(Agent, snap["agents"][0]["id"])
        lead.failure = "rate_limited"
        session.get_one(BacklogTask, one).status = "doing"
        turn.error = "Claude Code: you've hit your limit"
        assert backlog.turn_ended(session, turn, "failed")
        session.commit()
    assert tasks(client, pid)["one"]["status"] == "todo"
    assert client.get(f"/api/projects/{pid}/backlog/auto").json()["halt"] == (
        "Paused: Claude Code: you've hit your limit.")


def test_by_itself_it_waits_for_the_users_turn_and_the_button_does_not(make_client, wait_run, project_dir):
    client, _model = make_client([text("one done")])
    pid, _ = setup(client, project_dir, "one")
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    with client.app.state.session_factory() as session:
        session.add(Run(conversation_id=cid, status="running"))  # the user's turn at work
        session.commit()
    auto(client, pid, True)
    assert tasks(client, pid)["one"]["conversation_id"] is None
    assert run(client, pid).json()["task_id"] == tasks(client, pid)["one"]["id"]
    assert worked(client, wait_run, pid, "one")["status"] == "review"


def test_turning_it_off_drops_what_was_queued(make_client, project_dir, monkeypatch):
    monkeypatch.setattr(backlog, "MAX_PARALLEL", 0)  # (nothing starts: what is queued stays)
    client, _model = make_client([])
    pid, _ = setup(client, project_dir, "one")
    assert run(client, pid).json() == {"task_id": None, "conversation_id": None}
    assert tasks(client, pid)["one"]["queued"]
    auto(client, pid, False)
    assert not tasks(client, pid)["one"]["queued"]


def test_a_marked_line_is_found_at_a_lines_start_only():
    assert backlog.marked("x\n- `Not finished:` no db `", backlog.NOT_FINISHED) == "no db"
    assert backlog.marked("it is Not finished: maybe", backlog.NOT_FINISHED) is None
    # B-350's small item: a name in backticks that starts why keeps its pair
    assert backlog.marked("Not finished: `rea.py` does not exist.", backlog.NOT_FINISHED) == (
        "`rea.py` does not exist.")
    assert backlog.marked("`Not finished: no db`", backlog.NOT_FINISHED) == "no db"
    for wrapped in ("`Not finished:` `rea.py` does not exist.",
                    "`Not finished: `rea.py` does not exist.`"):  # (one cut: both go)
        assert backlog.marked(wrapped, backlog.NOT_FINISHED) == "rea.py does not exist."


def test_the_backlogs_chats_start_at_the_level_and_on_the_model_its_page_chose(
        make_client, wait_run, project_dir):
    client, _model = make_client([text("done")])
    pid, _ = setup(client, project_dir, "one")
    choice = f"/api/projects/{pid}/backlog/choice"
    auto = client.get(f"/api/projects/{pid}/backlog/auto").json()
    # (K-r144: who changes the files - none chosen, as the project's new chats)
    assert (auto["permission_mode"], auto["lead_work"]) == ("ask", "delegates")
    assert client.put(choice, json={"permission_mode": "full_auto"},
                      headers={"Origin": "http://elsewhere.example"}).status_code == 403
    assert client.put(choice, json={"permission_mode": "ask", "provider_id": "nope"}
                      ).status_code == 422
    provider = client.get("/api/providers").json()[0]["id"]
    out = client.put(choice, json={"permission_mode": "full_auto", "provider_id": provider,
                                   "model_id": "small", "lead_work": "itself"}).json()
    assert (out["permission_mode"], out["provider_id"], out["model_id"], out["lead_work"]) == (
        "full_auto", provider, "small", "itself")
    cid = run(client, pid).json()["conversation_id"]
    chat = client.get(f"/api/conversations/{cid}").json()["conversation"]
    assert (chat["permission_mode"], chat["provider_id"], chat["model_id"],
            chat["lead_work"]) == ("full_auto", provider, "small", "itself")
    worked(client, wait_run, pid, "one")
    # `shape` (a night's job: as the evening chat) stands over the page's choice
    with client.app.state.session_factory() as session:
        task = backlog.add(session, pid, {"title": "night"}, "user")
        session.commit()

        def shape(chat):
            chat.permission_mode = "ask"

        night = backlog.start(session, task, client.app.state.bus, lambda _run: None, shape)
        assert session.get_one(Conversation, night).permission_mode == "ask"


# --- K-r135: a backlog task's turns hold to a night's rules, at any level (the user's word) ----


def full_auto(client, pid, **more):
    put = client.put(f"/api/projects/{pid}/backlog/choice",
                     json={"permission_mode": "full_auto", **more})
    assert put.status_code == 200, put.text


def test_at_full_auto_a_task_runs_its_tests_but_a_command_that_runs_another_waits(
        make_client, project_dir):
    client, _model = make_client([
        step(call("run_command", {"command": "echo tests pass"}, "k1")),
        step(call("run_command", {"command": "cmd /c echo hi"}, "k2")), text("done")])
    pid, _ = setup(client, project_dir, "one")
    full_auto(client, pid)
    cid = run(client, pid).json()["conversation_id"]
    until(lambda: tasks(client, pid)["one"]["waiting"])
    commands = client.get(f"/api/conversations/{cid}").json()["commands"]
    assert [(c["command"], c["status"]) for c in commands] == [
        ("echo tests pass", "exited"), ("cmd /c echo hi", "proposed")]
    runner = client.app.state.runner
    run_id = client.get(f"/api/conversations/{cid}").json()["runs"][0]["id"]
    assert run_id in runner._backlog_turns
    # the Lead answers none of its cards (at Full auto in a chat it would): stood down at once,
    # before the chat is read - this ctx has none
    assert runner._lead_may_answer(SimpleNamespace(run_id=run_id), "card", "", [], None,
                                   None)() is None


def test_at_full_auto_a_task_s_instruction_file_waits_for_the_user(make_client, project_dir):
    client, _model = make_client([write("AGENTS.md", "# Rules\n"), text("done")])
    pid, _ = setup(client, project_dir, "one")
    client.patch(f"/api/projects/{pid}", json={"lead_work": "itself"})  # (a scripted Lead writes)
    full_auto(client, pid)
    cid = run(client, pid).json()["conversation_id"]
    until(lambda: tasks(client, pid)["one"]["waiting"])
    change = client.get(f"/api/conversations/{cid}").json()["file_changes"][0]
    assert (change["path"], change["status"]) == ("AGENTS.md", "proposed")
    assert not (project_dir / "AGENTS.md").exists()


def test_a_cli_with_its_own_tools_is_refused_for_the_backlog(claude_app, project_dir):  # noqa: F811
    client, provider, _default = claude_app([{"say": "done"}])
    pid, _ = setup(client, project_dir, "one")
    refused = client.put(f"/api/projects/{pid}/backlog/choice",
                         json={"permission_mode": "ask", "provider_id": provider["id"]})
    said = "Claude works with its own tools, so backlog tasks can't run on it - choose another provider."
    assert refused.status_code == 422 and refused.json()["detail"] == said
    with client.app.state.session_factory() as session:  # (chosen before it was set so)
        session.get_one(Project, pid).backlog_provider_id = provider["id"]
        session.commit()
    # the page says it, and neither Run the backlog nor by itself starts anything
    assert client.get(f"/api/projects/{pid}/backlog/auto").json()["cannot_run"] == said
    assert (run(client, pid).status_code, run(client, pid).json()["detail"]) == (422, said)
    assert auto(client, pid, True).status_code == 422
    assert auto(client, pid, False).status_code == 200
    # nor on the default provider, none chosen
    client.put(f"/api/projects/{pid}/backlog/choice", json={"permission_mode": "ask"})
    assert client.get(f"/api/projects/{pid}/backlog/auto").json()["cannot_run"] is None
    client.post(f"/api/providers/{provider['id']}/default")
    assert run(client, pid).json()["detail"] == (
        "Default (Claude) works with its own tools, so backlog tasks can't run on it - "
        "choose a provider.")


def test_a_provider_put_first_since_the_run_began_pauses_it_with_why(
        claude_app, project_dir, monkeypatch):  # noqa: F811
    client, provider, _default = claude_app([{"say": "done"}])
    pid, (one,) = setup(client, project_dir, "one")
    monkeypatch.setattr(backlog, "MAX_PARALLEL", 0)  # (queued, not started yet)
    run(client, pid)
    client.post(f"/api/providers/{provider['id']}/default")
    monkeypatch.setattr(backlog, "MAX_PARALLEL", 2)
    client.patch(f"/api/backlog/{one}", json={"priority": "high"})  # (a change runs the chain)
    assert client.get(f"/api/projects/{pid}/backlog/auto").json()["halt"] == (
        "Paused: Default (Claude) works with its own tools, so backlog tasks can't run on it - "
        "choose a provider.")
    assert tasks(client, pid)["one"]["conversation_id"] is None
    assert not claude_app.ran()


def test_what_the_orchestrator_role_runs_on_is_what_is_checked(claude_app, project_dir):  # noqa: F811
    client, provider, _default = claude_app([{"say": "done"}])
    pid, _ = setup(client, project_dir, "one")
    lead = f"/api/roles/{role_id(client, 'Lead')}"
    client.patch(lead, json={"provider_id": provider["id"]})
    assert client.get(f"/api/projects/{pid}/backlog/auto").json()["cannot_run"] == (
        "The Orchestrator role's model (Claude) works with its own tools, so backlog tasks "
        "can't run on it - give the role another model.")
    # its own model elsewhere: a default with its own tools is no matter
    scripted = next(p for p in client.get("/api/providers").json() if p["id"] != provider["id"])
    client.patch(lead, json={"provider_id": scripted["id"]})
    client.post(f"/api/providers/{provider['id']}/default")
    assert client.get(f"/api/projects/{pid}/backlog/auto").json()["cannot_run"] is None


def test_the_orchestrator_s_list_passes_over_a_cli_with_its_own_tools(
        claude_app, wait_run, project_dir):  # noqa: F811
    client, provider, _default = claude_app([{"say": "done"}], default_steps=[text("done")])
    pid, _ = setup(client, project_dir, "one")
    with client.app.state.session_factory() as session:
        lead = session.scalar(select(Role).where(Role.name == "Lead"))
        lead.models = [{"provider_id": provider["id"], "model_id": None}]
        session.commit()
    assert client.get(f"/api/projects/{pid}/backlog/auto").json()["cannot_run"] is None
    run(client, pid)
    assert worked(client, wait_run, pid, "one")["status"] == "review"
    assert not claude_app.ran()


def test_a_sub_agent_on_a_cli_with_its_own_tools_is_refused_in_a_backlog_turn(
        claude_app, wait_run, project_dir):  # noqa: F811
    client, provider, _default = claude_app(
        [{"say": "done"}], default_steps=[spawn("Coder"), text("done")])
    pid, _ = setup(client, project_dir, "one")
    client.patch(f"/api/roles/{role_id(client, 'Coder')}", json={"provider_id": provider["id"]})
    cid = run(client, pid).json()["conversation_id"]
    worked(client, wait_run, pid, "one")
    (opened,) = [c for c in client.get(f"/api/conversations/{cid}").json()["tool_calls"]
                 if c["name"] == "spawn_agent"]
    assert "Claude cannot work on a backlog task" in opened["result"]
    assert not claude_app.ran()


def test_a_provider_with_no_model_to_run_is_refused_for_the_backlog(client, project_dir):
    pid, _ = setup(client, project_dir, "one")
    api = client.post("/api/providers", json={"name": "API", "kind": "anthropic",
                                              "api_key": "sk-test"}).json()
    put = client.put(f"/api/projects/{pid}/backlog/choice",
                     json={"permission_mode": "ask", "provider_id": api["id"]})
    assert put.status_code == 422 and "no default model" in put.json()["detail"]
    named = client.put(f"/api/projects/{pid}/backlog/choice",
                       json={"permission_mode": "ask", "provider_id": api["id"], "model_id": "m"})
    assert named.status_code == 200


def test_a_marker_with_nothing_after_it_is_no_reason():
    for said in ("Not finished: `", "Not finished:   ", "**Not finished:** ``` "):
        assert backlog.marked(said, backlog.NOT_FINISHED) is None, said
    assert backlog.marked("Not finished: `\nNot finished: no db", backlog.NOT_FINISHED) == "no db"
    task = SimpleNamespace(flow=None)
    backlog.set_flow(task, fix="")  # (a fix due for nothing would never come)
    assert task.flow is None


def test_at_full_auto_a_task_s_inline_code_waits_but_its_own_test_command_runs(
        make_client, project_dir):
    client, _model = make_client([
        step(call("run_command", {"command": 'python -c "import sys"'}, "k1")),
        step(call("run_command", {"command": 'node -e "1"'}, "k2")), text("done")])
    pid, _ = setup(client, project_dir, "one")
    with client.app.state.session_factory() as session:  # (the user's test command for the root)
        session.get_one(Project, pid).test_commands = {"./": 'python -c "import sys"'}
        session.commit()
    full_auto(client, pid)
    cid = run(client, pid).json()["conversation_id"]
    until(lambda: tasks(client, pid)["one"]["waiting"])
    commands = client.get(f"/api/conversations/{cid}").json()["commands"]
    assert [(c["command"], c["status"]) for c in commands] == [
        ('python -c "import sys"', "exited"), ('node -e "1"', "proposed")]


def test_a_backlog_task_s_turn_is_offered_no_mcp_tool(make_client, wait_run, project_dir,
                                                       tmp_path):
    client, model = make_client([text("done"), text("hi")])
    pid, _ = setup(client, project_dir, "one")
    server(client, tmp_path)
    give(client, "Lead", "fake")
    full_auto(client, pid)
    run(client, pid)
    worked(client, wait_run, pid, "one")
    # the user's own chat in the project is offered them
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    said = client.post(f"/api/conversations/{cid}/messages", json={"content": "hi"}).json()
    wait_run(client, cid, said["run"]["id"])
    names = [[t["function"]["name"] for t in tools or []] for tools in model.tool_args]
    assert not any(name.startswith("fake__") for name in names[0])
    assert any(name.startswith("fake__") for name in names[1])


def test_at_full_auto_a_sub_agent_s_question_waits_for_the_user_in_a_backlog_turn(
        make_client, project_dir):
    client, model = make_client([spawn("Coder", "sort the list"), ask(), text("never")])
    clock = held(client)
    pid, _ = setup(client, project_dir, "one")
    full_auto(client, pid)
    cid = run(client, pid).json()["conversation_id"]
    until(lambda: tasks(client, pid)["one"]["waiting"])
    (question,) = client.get(f"/api/conversations/{cid}").json()["questions"]
    assert question["status"] == "pending"
    assert lead_timers(clock, 0.0) == [] and lead_timers(clock, 600.0) == []  # nobody answers
    assert len(model.calls) == 2  # (the Lead was never asked to)
