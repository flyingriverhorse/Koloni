"""Slice 106's review, as tests: what a night job while the user is away may do unasked (a turn
nobody watches: no MCP tool, no folder of the chat's beside its copy, nothing that deletes or
leaves the machine), the places kept out as paths, the limits (its time over a change of summer
time, its money as Usage counts it, one hour a job), and the night's ends - a stop, a restart, a
chat deleted - leaving nothing at work and nothing started by itself."""

import json
import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

import app.web
from app import away, backlog
from app.agent import recover_interrupted
from app.db.models import AwayRun, BacklogTask, Message
from app.model_client import StepResult, ToolCallRequest
from tests.test_agent_writes import edit
from tests.test_away_scenarios import ORIGIN, PLAN, card, ended, evening, night
from tests.test_backlog_auto import tasks, until
from tests.test_chat_flow import text
from tests.test_claude_native import claude_app  # noqa: F401  (a fixture)
from tests.test_mcp_scenarios import give, server
from tests.test_spawn import call, step
from tests.test_triggers import zone_with_summer_time


def run(command, id="k", **more):
    return step(call("run_command", {"command": command, **more}, id))


def job_chat(client, pid, at=0):
    return client.get(f"/api/conversations/{night(client, pid)['jobs'][at]['conversation_id']}").json()


def start(client, cid):
    started = client.post(f"/api/away/{card(client, cid)['id']}/start")
    assert started.status_code == 200, started.text
    return started.json()


# --- 2, 5, 6: a night job is held as a turn nobody watches -----------------------------------


def test_no_mcp_tool_of_koloni_s_is_offered_at_night(make_client, wait_run, project_dir, tmp_path):
    client, model, pid, cid, run_id = evening(make_client, project_dir, [
        text("one done"), text("two done"), text("morning")])
    wait_run(client, cid, run_id)
    server(client, tmp_path)
    give(client, "Lead", "fake")
    start(client, cid)
    ended(client, pid)
    later = client.post(f"/api/conversations/{cid}/messages", json={"content": "hi"}).json()
    wait_run(client, cid, later["run"]["id"])
    names = [[t["function"]["name"] for t in tools or []] for tools in model.tool_args]
    # the jobs' turns were offered none of the server's tools; the chat's own next turn is
    assert not any(name.startswith("fake__") for tools in names[2:4] for name in tools)
    assert any(name.startswith("fake__") for name in names[4])


def test_a_cli_s_own_mcp_tool_waits_for_the_user_at_night(claude_app, wait_run, project_dir):  # noqa: F811
    client, provider, _default = claude_app(
        [{"tool": "mcp__files__write_file", "input": {"path": "x.txt"}, "result": "ok"},
         {"say": "done"}],
        default_steps=[step(call("plan_away", {"jobs": [{"title": "one"}]})), text("card")])
    client.headers.update(ORIGIN)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={"permission_mode": "full_auto"})
    wait_run(client, cid, client.post(f"/api/conversations/{cid}/messages",
                                      json={"content": "sleep"}).json()["run"]["id"])
    # the jobs run on the chat's own model: Claude Code, at Full auto
    client.patch(f"/api/conversations/{cid}", json={"provider_id": provider["id"]})
    start(client, cid)
    one = until(lambda: (n := night(client, pid))["jobs"][0]["state"] == "waits" and n["jobs"][0])
    snap = client.get(f"/api/conversations/{one['conversation_id']}").json()
    assert snap["conversation"]["provider_id"] == provider["id"]
    assert "mcp__files__write_file" in snap["questions"][0]["question"]


def test_a_command_in_another_of_the_chat_s_folders_waits_at_night(make_client, wait_run,
                                                                    project_dir, tmp_path):
    shelf = tmp_path / "shelf"
    shelf.mkdir()
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [
        run("echo hi", cwd=str(shelf)), text("one done"), text("two done")])
    assert client.patch(f"/api/projects/{pid}", json={"also_in": [str(shelf)]}).status_code == 200
    wait_run(client, cid, run_id)
    # (the card's chat was made before the folder: its jobs' chats start with the folder's)
    start(client, cid)
    one = until(lambda: (n := night(client, pid))["jobs"][0]["state"] == "waits" and n["jobs"][0])
    snap = client.get(f"/api/conversations/{one['conversation_id']}").json()
    assert snap["conversation"]["also_in"] and snap["commands"] == []


def test_at_full_auto_a_job_runs_its_tests_but_a_push_a_delete_and_a_post_wait(
        make_client, wait_run, project_dir):
    # (a job that waits gives its place to the next: the steps go one job after the other)
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [
        run("echo tests pass"), run("git push origin main", "k2"), run("rm -rf build", "k3"),
        step(call("http_request", {"method": "POST", "url": "https://example.com/x",
                                   "body": "a"}, "h"))],
        plan={"jobs": [{"title": "one"}, {"title": "two"}, {"title": "three"}]})
    wait_run(client, cid, run_id)
    start(client, cid)
    done = ended(client, pid)
    assert [job["state"] for job in done["jobs"]] == ["waits", "waits", "waits"]
    one = job_chat(client, pid)
    assert [(c["command"], c["status"]) for c in one["commands"]] == [
        ("echo tests pass", "exited"), ("git push origin main", "proposed")]
    assert done["jobs"][0]["asks"][0]["text"] == 'Lead asks to run "git push origin main"'
    assert [c["status"] for c in job_chat(client, pid, 1)["commands"]] == ["proposed"]
    assert [r["status"] for r in job_chat(client, pid, 2)["web_requests"]] == ["proposed"]


# --- 3: the chat the card was in is deleted ---------------------------------------------------


def test_a_deleted_card_chat_leaves_a_job_chat_s_later_turn_working(make_client, wait_run,
                                                                    project_dir, gate):
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [
        gate.step(text("one done")), text("two done"), text("later in the job chat")])
    wait_run(client, cid, run_id)
    start(client, cid)
    gate.wait_partial()
    assert client.patch(f"/api/conversations/{cid}", json={"archived": True}).status_code == 200
    (refused,) = client.post("/api/conversations/delete", json={"ids": [cid]}).json()["refused"]
    assert "stop it first" in refused["why"]  # while its night runs
    gate.release()
    one = ended(client, pid)["jobs"][0]
    assert client.post("/api/conversations/delete", json={"ids": [cid]}).json()["deleted"] == [cid]
    later = client.post(f"/api/conversations/{one['conversation_id']}/messages",
                        json={"content": "go on"}).json()
    snap = wait_run(client, one["conversation_id"], later["run"]["id"])
    assert snap["runs"][-1]["status"] == "completed", snap["runs"][-1]


# --- 4, 13: after the night nothing of it starts by itself; Try again is the user's ------------


def test_after_a_stop_the_list_working_itself_starts_no_job_of_the_night(make_client, wait_run,
                                                                         project_dir, gate):
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [
        gate.step(text("never"))], plan={**PLAN, "until": "07:00"})
    wait_run(client, cid, run_id)
    assert client.put(f"/api/projects/{pid}/backlog/auto", json={"on": True}).status_code == 200
    start(client, cid)
    gate.wait_partial()
    first = job_chat(client, pid)["messages"][0]["content"]
    assert backlog.AWAY_JOB in first  # (a job of the night is told so)
    client.app.state.triggers.tick(datetime.now(UTC) + timedelta(days=1))
    ended(client, pid)
    gate.release()
    until(lambda: job_chat(client, pid)["runs"][0]["status"] != "running")
    # the switch is on, the next task is todo: it stays the user's
    assert tasks(client, pid)["two"]["conversation_id"] is None
    # ...nor by Start the next: what became of it is the night's report's
    assert client.post(f"/api/projects/{pid}/backlog/next").status_code == 409
    client.post(f"/api/projects/{pid}/backlog", json={"title": "mine"})
    started = client.post(f"/api/projects/{pid}/backlog/next")
    assert started.json()["task_id"] == tasks(client, pid)["mine"]["id"]
    said = client.get(f"/api/conversations/{started.json()['conversation_id']}").json()
    assert backlog.AWAY_JOB not in said["messages"][0]["content"]


def test_try_again_is_a_turn_of_the_user_s_and_not_while_one_is_at_work(
        make_client, wait_run, project_dir, gate):
    from app.model_client import ModelUnavailable

    client, _model, pid, cid, run_id = evening(make_client, project_dir, [
        ModelUnavailable("down"), ModelUnavailable("down again"), text("two done"),
        gate.step(text("again done"))])
    wait_run(client, cid, run_id)
    away_id = start(client, cid)["id"]
    one = ended(client, pid)["jobs"][0]
    assert one["state"] == "failed"
    again = client.post(f"/api/away/{away_id}/jobs/{one['task_id']}/again")
    assert again.status_code == 200, again.text
    gate.wait_partial()
    said = [m["content"] for m in job_chat(client, pid)["messages"] if m["role"] == "user"]
    assert said[-1] == away.AGAIN and "not in a copy" in away.AGAIN
    # a turn of its chat at work: no second one (were the job said to have failed again)
    with client.app.state.session_factory() as session:
        session.get_one(BacklogTask, one["task_id"]).away_state = "failed"
        session.commit()
    busy = client.post(f"/api/away/{away_id}/jobs/{one['task_id']}/again")
    assert busy.status_code == 409 and "at work" in busy.json()["detail"]
    gate.release()


# --- 7, 8: the time and the places kept out --------------------------------------------------


def test_seven_in_the_morning_over_a_change_of_summer_time():
    zone = zone_with_summer_time()  # (CET; summer time ends on 25 Oct 2026 at 03:00)
    evening_ = datetime(2026, 10, 24, 21, 0, tzinfo=UTC)  # 23:00 summer time
    assert away.until_at("07:00", evening_, zone) == datetime(2026, 10, 25, 6, 0, tzinfo=UTC)
    summer = datetime(2026, 7, 1, 21, 0, tzinfo=UTC)
    assert away.until_at("07:00", summer, zone) == datetime(2026, 7, 2, 5, 0, tzinfo=UTC)


def test_a_place_kept_out_is_matched_as_a_path():
    night_ = AwayRun(kept_out=["db"], jobs=[], tried=[])
    root = "C:/work/shop"
    assert away.kept_out(night_, command="npm run dbg-tool") is None
    assert away.kept_out(night_, command="python -m mydb") is None
    assert away.kept_out(night_, command="cat ./db/x.sql") == "db"
    assert away.kept_out(night_, command="sqlite3 --file=db\\x.sql") == "db"
    assert away.kept_out(night_, path="src/../db/x.sql") == "db"
    assert away.kept_out(night_, path="C:\\work\\shop\\db\\x.sql", root=root) == "db"
    assert away.kept_out(night_, path="dbx/y") is None


def test_a_kept_out_pattern_or_a_place_outside_is_refused_and_a_full_path_made_relative(
        make_client, wait_run, project_dir, tmp_path):
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [])
    wait_run(client, cid, run_id)
    planned = card(client, cid)
    for wrong in ("src/payments/*", str(tmp_path / "elsewhere"), "../up"):
        answer = client.patch(f"/api/away/{planned['id']}", json={"kept_out": [wrong]})
        assert answer.status_code == 409, wrong
    made = client.patch(f"/api/away/{planned['id']}",
                        json={"kept_out": [str(project_dir / "src" / "payments"), "db/one/"]})
    assert made.json()["kept_out"] == ["src/payments", "db/one"]


def test_a_command_run_in_a_place_kept_out_is_refused(make_client, wait_run, project_dir):
    (project_dir / "secret").mkdir()
    (project_dir / "secret" / "pay.py").write_bytes(b"pay = 1\n")
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [
        run("echo hi", cwd="secret"), text("one done"), text("two done")])
    wait_run(client, cid, run_id)
    start(client, cid)
    done = ended(client, pid)
    assert [t["what"] for t in done["tried"]] == ["Lead: run echo hi in secret"]
    assert job_chat(client, pid)["commands"] == []


# --- 10: the money as Usage counts it; one hour a job; a plan counts no money -----------------


def test_the_night_stops_at_its_money_as_usage_counts_it(make_client, wait_run, project_dir):
    big = StepResult("", [ToolCallRequest("w1", "edit_file", json.dumps(
        {"path": "hello.py", "old_string": "hi", "new_string": "hello"}))], 1_000_000, 500_000)
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [big, text("never")],
                                               plan={**PLAN, "money": 5})
    client.put("/api/prices", json={"model_id": "fake-model", "input": 3, "output": 15,
                                    "currency": "USD"})
    wait_run(client, cid, run_id)
    start(client, cid)
    done = ended(client, pid)
    assert done["why"] == "Stopped at 10.50 of 5.00 USD, the spend limit."
    assert done["spent"] == 10.5 and done["jobs"][1]["state"] == "next"


def test_a_job_that_works_an_hour_is_cut_and_the_next_goes_on(make_client, wait_run, project_dir,
                                                              gate, monkeypatch):
    # The night ends nearly a day on: an hour later is past the job's hour, never past the night's end.
    until = (datetime.now() - timedelta(minutes=1)).strftime("%H:%M")
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [
        gate.step(edit()), text("never"), text("two done")], plan={**PLAN, "until": until})
    wait_run(client, cid, run_id)
    start(client, cid)
    gate.wait_partial()
    later = datetime.now(UTC) + timedelta(minutes=away.JOB_MINUTES + 1)
    monkeypatch.setattr(away, "now", lambda: later)
    monkeypatch.setattr(backlog, "now", lambda: later)  # (the next job starts then)
    gate.release()  # its next step: past its hour
    done = ended(client, pid)
    one, two = done["jobs"]
    assert (one["state"], one["why"]) == ("failed", away.JOB_TOO_LONG)
    assert two["state"] == "done" and done["why"] is None and done["job_minutes"] == 60


def test_a_card_with_no_time_has_no_stop_time_and_the_clock_never_ends_it(
        make_client, wait_run, project_dir, gate):
    # The user, 6 Nov: no default stop time - the jobs run until done, the money spent or a
    # job's hour, never stopped by the clock.
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [
        gate.step(text("one done")), text("two done")])
    wait_run(client, cid, run_id)
    assert card(client, cid)["until"] is None
    start(client, cid)
    gate.wait_partial()
    with client.app.state.session_factory() as session:
        (found,) = session.scalars(select(AwayRun)).all()
        assert found.until is None
        assert away.over(session, found, datetime.now(UTC) + timedelta(days=3)) is None
    gate.release()
    done = ended(client, pid)
    assert done["why"] is None and done["until"] is None and done["counts"]["done"] == 2


def test_a_card_with_no_money_has_no_spend_limit(make_client, wait_run, project_dir,
                                                 monkeypatch):
    # The user, 6 Nov: no default spend limit - a plan counts no dollars; only a figure the user
    # gave, or what the month's budget has left, stops the jobs for money.
    client, _model, _pid, cid, run_id = evening(make_client, project_dir, [])
    wait_run(client, cid, run_id)
    assert card(client, cid)["money"] is None
    monkeypatch.setattr(away, "spent", lambda session, night: {
        "spent": 1000.0, "currency": "USD", "at_least": False})
    with client.app.state.session_factory() as session:
        (found,) = session.scalars(select(AwayRun)).all()
        assert away.over(session, found) is None


@pytest.mark.parametrize(("asked", "most"), [(None, 3), (1, 1), (7, 3)])
def test_the_months_budget_still_caps_the_cards_money(make_client, wait_run, project_dir,
                                                       asked, most):
    client, _model, _pid, cid, run_id = evening(make_client, project_dir, [], monthly_budget=3,
                                               plan={**PLAN, "money": asked})
    wait_run(client, cid, run_id)
    assert card(client, cid)["money"] == most


def test_a_budget_set_before_start_caps_the_jobs_and_stops_them_once_spent(
        make_client, wait_run, project_dir, gate, monkeypatch):
    # Review of the no-default-money change: a budget set after the card was planned, or the
    # card's field emptied, still holds the jobs - at what is left of it when Start is pressed.
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [
        gate.step(text("one done")), text("never")])
    wait_run(client, cid, run_id)
    assert card(client, cid)["money"] is None
    assert client.patch(f"/api/projects/{pid}", json={"monthly_budget": 3}).status_code == 200
    start(client, cid)
    gate.wait_partial()
    assert card(client, cid)["money"] == 3
    monkeypatch.setattr(away, "spent", lambda session, night: {
        "spent": 3.0, "currency": "USD", "at_least": False})
    with client.app.state.session_factory() as session:
        (found,) = session.scalars(select(AwayRun)).all()
        assert away.over(session, found) == "Stopped at 3.00 of 3.00 USD, the spend limit."
    gate.release()
    assert ended(client, pid)["why"] == "Stopped at 3.00 of 3.00 USD, the spend limit."


def test_the_card_says_when_its_jobs_run_on_a_plan(make_client, wait_run, project_dir):
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [])
    wait_run(client, cid, run_id)
    assert card(client, cid)["on_plan"] is None and card(client, cid)["currency"] == "USD"
    local = client.get("/api/providers").json()[0]
    assert client.patch(f"/api/providers/{local['id']}", json={"plan": True}).status_code == 200
    assert card(client, cid)["on_plan"] == local["name"]


# --- 12, nits: how a night ends ---------------------------------------------------------------


def test_a_restart_ends_the_night_with_its_line_and_its_one_notification(
        make_client, wait_run, project_dir, gate):
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [gate.step(text("x"))],
                                               notify_desktop=True)
    wait_run(client, cid, run_id)
    start(client, cid)
    gate.wait_partial()
    notes: list = []
    factory = client.app.state.session_factory
    recover_interrupted(factory, notes)
    with factory() as session:
        (found,) = session.scalars(select(AwayRun)).all()
        said = session.scalars(select(Message.content).where(
            Message.conversation_id == cid, Message.role == "away")).all()
    assert (found.status, found.why) == ("ended", away.CLOSED)
    assert said == ["While you were away: 0 done, 1 could not be done, 1 not started - on the "
                    "canvas"]
    assert [note[-1] for note in notes] == [f"{away.CLOSED} {said[0]}."]
    gate.release()


def test_the_morning_line_is_at_the_bottom_of_the_chat(make_client, wait_run, project_dir, gate):
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [
        gate.step(text("one done")), text("evening reply"), text("two done")])
    wait_run(client, cid, run_id)
    start(client, cid)
    gate.wait_partial()
    later = client.post(f"/api/conversations/{cid}/messages", json={"content": "hi"}).json()
    wait_run(client, cid, later["run"]["id"])
    gate.release()
    ended(client, pid)
    last = client.get(f"/api/conversations/{cid}").json()["messages"][-1]
    assert (last["role"], last["run_id"]) == ("away", later["run"]["id"])


def test_start_waits_for_a_task_at_work_and_puts_away_other_cards(make_client, wait_run,
                                                                   project_dir, gate):
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [
        gate.step(text("task done")), step(call("plan_away", PLAN, "p2")), text("second card")])
    wait_run(client, cid, run_id)
    client.post(f"/api/projects/{pid}/backlog", json={"title": "by hand"})
    assert client.post(f"/api/projects/{pid}/backlog/next").status_code == 200
    gate.wait_partial()
    refused = client.post(f"/api/away/{card(client, cid)['id']}/start")
    assert refused.status_code == 409 and "is being worked on" in refused.json()["detail"]
    gate.release()
    until(lambda: tasks(client, pid)["by hand"]["status"] == "review")
    other = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    wait_run(client, other, client.post(f"/api/conversations/{other}/messages",
                                        json={"content": "sleep too"}).json()["run"]["id"])
    first, second = card(client, cid), card(client, other)
    assert client.post(f"/api/away/{second['id']}/start").status_code == 200
    assert card(client, cid)["status"] == "dismissed" and first["status"] == "planned"


@pytest.fixture(autouse=True)
def no_desktop(monkeypatch):
    monkeypatch.setattr(app.web, "has_desktop", lambda: True)
    monkeypatch.setattr(app.web, "desktop", lambda title, said: None)


def test_what_sends_work_off_the_machine_is_told_apart_from_what_does_not():
    from app.commands import sends_off

    for sends in ("git push origin main", "git -C web push", "npm publish", "twine upload dist/*",
                  "curl -X POST https://x", "curl --data a=1 https://x", "npx vercel deploy",
                  "scp a.zip host:", "pytest -q && git push",
                  "curl https://x.test/a.json", "gh pr list"):  # (a night job asks about a fetch)
        assert sends_off(sends), sends
    for stays in ("pytest -q", "npm run test", "npm run dbg-tool", "git status",
                  "python -m build", "cargo build --release"):
        assert not sends_off(stays), stays


# --- the safety re-check: what leaves the machine, and the places kept out --------------------


def test_a_wrapper_or_a_shell_and_any_request_from_the_command_line_count_as_leaving():
    from app.commands import installs, runs_another, sends_off

    for wrapped in ('cmd /c git push', 'bash -c "git push"', 'powershell -c "git push"',
                    "env git push", "sudo git push", "timeout 60 git push", "GIT_X=1 git push",
                    "pytest -q && cmd /c del x", "ssh host ls"):
        assert runs_another(wrapped), wrapped
    assert not runs_another("pytest -q && npm test")
    for sends in ("curl -XPOST https://h", "curl -sd x https://h", "curl -dfoo https://h",
                  "curl -Ff=@a https://h", "curl -sSfT a https://h", "curl.exe -d x https://h",
                  "Invoke-WebRequest https://x -Method:Post", 'curl "https://h/?k=$(cat a.py)"',
                  "wget https://h/x", "aws s3 cp a s3://b", "az storage blob upload -f a",
                  "gsutil cp a gs://b", "rclone copy . r:b", "nc h 80", "kubectl apply -f a",
                  "terraform apply", "vercel --prod", "docker buildx build --push .",
                  "helm push c oci://r", "gradle publish", "mvn deploy", "git send-email a"):
        assert sends_off(sends), sends
    for one in ("pip install x", "python -m pip install -r r.txt", "uv sync", "npm i", "pnpm add x",
                "yarn install", "poetry add x"):
        assert installs(one), one
    assert not installs("npm run build") and not installs("pip list")


def test_at_night_a_wrapped_command_waits_and_an_install_waits_where_the_copy_links_in(
        make_client, wait_run, project_dir):
    (project_dir / "node_modules").mkdir()
    (project_dir / "node_modules" / "x.js").write_bytes(b"1\n")
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [
        run("cmd /c echo hi"), run("npm install left-pad", "k2")])
    wait_run(client, cid, run_id)
    start(client, cid)
    done = ended(client, pid)
    assert [job["state"] for job in done["jobs"]] == ["waits", "waits"]
    assert [c["status"] for c in job_chat(client, pid)["commands"]] == ["proposed"]
    assert [c["status"] for c in job_chat(client, pid, 1)["commands"]] == ["proposed"]


# K-r147 (live): agents run their tests piped into a filter - REA's lines.
TESTS_PIPED = ["python -m unittest -q 2>&1 | Select-Object -Last 8",
               "python -m unittest discover -s tests 2>&1 | Select-Object -Last 20"]


def test_a_pipe_into_a_filter_runs_nothing_else_and_any_other_stage_does():
    from app.commands import runs_another

    for seen in (*TESTS_PIPED, "pytest 2>&1 | tail -n 5", "pytest | sort -n -t, -k2", "git log | grep fix | wc -l", "pytest | findstr FAIL",
                 "pytest | sort | more", "pytest | Out-String", "pytest | Format-Table",
                 "pytest | Measure-Object -Line", "ls | Sort-Object Length",
                 "ls | Where-Object Length -gt 10", "pytest | tee", "pytest *>&1 | head",
                 "pytest | tee -a .koloni/tmp/out.txt", "pytest -q && npm test"):
        assert not runs_another(seen), seen
    for runs in ("pytest | iex", "pytest | Invoke-Expression", "cat x | sh", "cat x | bash",
                 "cat x | powershell", "cat x | cmd", "ls | xargs rm", "cat x.py | python",
                 "ls | ForEach-Object { $_ }", "ls | Where-Object { $_.Length -gt 1 }",
                 "ls | %{ $_ }", "ls | % Name", "pytest | tee out.txt", "pytest | sort -o x.py",
                 "pytest | sort /o x.py", "pytest | sort --compress-program=x",
                 "pytest | sort --co=./x.sh", "pytest | sort -T tmp", "pytest | sort -nT tmp",
                 "pytest | sort --temporary-directory=t",
                 r"pytest | .\head.exe", "pytest |", "pytest | & python x", "pytest |& python x",
                 "pytest | Select-Object -First (iex 'x')", "pytest | Select-Object -First $n",
                 "pytest | Select-Object @{e={iex x}}",
                 # a filter's name given to something else in the line is no filter
                 "sal grep cmd; ls | grep /c calc", "Set-Alias wc iex; ls | wc",
                 "alias head=sh; ls | head",
                 # a shell stays a shell: pwsh joins every word after -c into its script
                 *(f'powershell -Command "{one}"' for one in TESTS_PIPED),
                 'pwsh -c "git push" origin', 'pwsh -c "cmd /c" calc',
                 'pwsh -c "pip install" evilpkg', 'pwsh -c "python -c" "print(1)"',
                 'cmd /c "pytest | findstr FAIL"', 'bash -c "pytest | tail"'):
        assert runs_another(runs), runs


def test_at_night_a_test_piped_into_a_filter_runs_and_one_piped_into_python_waits(
        make_client, wait_run, project_dir):
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [
        run("echo tests pass 2>&1 | Select-Object -Last 8"),
        text("one done"), run("echo print(1) | python", "k2")])
    wait_run(client, cid, run_id)
    start(client, cid)
    done = ended(client, pid)
    assert [job["state"] for job in done["jobs"]] == ["done", "waits"]
    assert [c["status"] for c in job_chat(client, pid)["commands"]] == ["exited"]
    assert [c["status"] for c in job_chat(client, pid, 1)["commands"]] == ["proposed"]


def test_kept_out_words_from_the_cwd_the_copy_s_full_paths_redirects_and_patterns():
    night_ = AwayRun(kept_out=["secret", "src/payments", "db.sqlite"], jobs=[], tried=[])
    root, copy = "C:/Users/me/proj", "C:/Users/me/AppData/Local/KOLONI/copies/abc/x"
    found = lambda command, cwd=None: away.kept_out(  # noqa: E731
        night_, command=command, root=(root, copy), cwd=cwd)
    assert found("rm payments/x.py", cwd="src") == "src/payments"
    assert found(r"del ..\secret\k.txt", cwd="src") == "secret"
    assert found(copy.replace("/", "\\").join(("rm ", r"\secret\a"))) == "secret"
    assert found(f"Remove-Item {copy}/src/payments -Recurse") == "src/payments"
    # (`secret.` is `secret` on Windows only, which drops a name's last dot)
    dotted = [r"copy a secret.\b"] if os.name == "nt" else []
    for redirect in (r"echo x>secret\a.txt", "type nul>db.sqlite", "rm secret|x",
                     r"echo x >> secret\a", *dotted):
        assert found(redirect), redirect
    assert found("rm s*") == "secret" and found("rm -r src/*/x") == "src/payments"
    assert found("rm *.py") is None and found("npm run dbg-tool") is None


def test_a_place_outside_the_project_is_refused_on_the_card(make_client, wait_run, project_dir):
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [])
    wait_run(client, cid, run_id)
    planned = card(client, cid)
    for outside in ("/etc", "~/.ssh", r"\\server\share"):
        answer = client.patch(f"/api/away/{planned['id']}", json={"kept_out": [outside]})
        assert answer.status_code == 409 and "outside the project" in answer.json()["detail"], outside


def test_at_night_a_command_naming_another_folder_of_the_chat_waits(make_client, wait_run,
                                                                   project_dir, tmp_path):
    shelf = tmp_path / "shelf"
    shelf.mkdir()
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [
        run(f"echo x > {shelf / 'y.txt'}"), text("one done"), text("two done")])
    assert client.patch(f"/api/projects/{pid}", json={"also_in": [str(shelf)]}).status_code == 200
    wait_run(client, cid, run_id)
    start(client, cid)
    until(lambda: night(client, pid)["jobs"][0]["state"] == "waits")
    assert not (shelf / "y.txt").exists()


def test_a_job_is_cut_by_the_loop_s_clock_while_no_step_of_it_comes(make_client, wait_run,
                                                                    project_dir, gate):
    from tests.test_triggers import HeldClock

    client, _model, pid, cid, run_id = evening(make_client, project_dir, [
        edit(), gate.step(text("never")), text("two done")])
    wait_run(client, cid, run_id)
    clock = client.app.state.runner.call_later = HeldClock()
    start(client, cid)
    gate.wait_partial()  # (its step never returns: no step looks at the hour)
    (timer,) = [t for t in clock.set if t.delay > 60]
    assert timer.delay <= away.JOB_MINUTES * 60
    client.portal.call(timer.fire)
    one = until(lambda: (n := night(client, pid))["jobs"][0]["kept"] and n["jobs"][0])
    assert (one["state"], one["why"], one["files"]) == ("failed", away.JOB_TOO_LONG, ["hello.py"])
    assert ended(client, pid)["jobs"][1]["state"] == "done"
    gate.release()


def test_remember_in_a_job_rests_on_its_copy_s_lines(make_client, wait_run, project_dir):
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [
        edit(), step(call("read_file", {"path": "hello.py"}, "r")),
        step(call("remember", {"text": "it says hello", "file": "hello.py", "start_line": 1},
                  "m")), text("one done"), text("two done")])
    wait_run(client, cid, run_id)
    start(client, cid)
    ended(client, pid)
    (said,) = [t for t in job_chat(client, pid)["tool_calls"] if t["name"] == "remember"]
    assert said["status"] == "succeeded", said["result"]

    def stands():
        (note,) = [r for r in client.get(f"/api/projects/{pid}/memory").json()["journal"]
                   if r["text"] == "it says hello"]
        return note["source_state"]

    # the lines it rests on are the copy's: in the project once the job is taken in
    assert stands() == "changed"
    (kept,) = night(client, pid)["jobs"][0]["kept"]
    assert client.post(f"/api/merges/{kept}/approve").status_code == 200
    assert stands() == "unchanged"


def test_a_job_that_waited_keeps_its_places_kept_out_after_the_night(make_client, wait_run,
                                                                    project_dir):
    (project_dir / "secret").mkdir()
    (project_dir / "secret" / "pay.py").write_bytes(b"pay = 1\n")
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [
        run("git push origin main"), text("two done"), edit("secret/pay.py", "1", "2", "w9"),
        text("one done")])
    wait_run(client, cid, run_id)
    start(client, cid)
    one = ended(client, pid)["jobs"][0]
    assert one["state"] == "waits"
    (ask,) = one["asks"]
    client.post(f"/api/commands/{ask['id']}/reject")  # the morning: it goes on
    until(lambda: night(client, pid)["jobs"][0]["state"] == "done")
    edits = [t for t in job_chat(client, pid)["tool_calls"] if t["name"] == "edit_file"]
    assert "secret is kept out:" in edits[0]["result"]
