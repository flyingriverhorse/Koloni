"""Slice 106's acceptance set: "work while I'm away". The Lead puts the night's jobs on a card;
only the user's Start starts them; each job works in a new chat and a copy of its own, so
nothing reaches the project before the user's Take in; a job that waits for the user's word,
or fails twice, never holds up the next; the night stops at its time, its money or Stop all;
and the morning is told once - a line in the chat, one notification."""

from datetime import timedelta

import pytest
from sqlalchemy import select

import app.web
from app import away
from app.agent import recover_interrupted
from app.db.models import AwayRun, BacklogTask, Run, now
from app.model_client import ModelUnavailable
from tests.test_agent_writes import edit
from tests.test_backlog_auto import tasks, until
from tests.test_chat_flow import text
from tests.test_spawn import call, spawn, step
from tests.test_team import team  # noqa: F401  (a fixture)

ORIGIN = {"Origin": "http://127.0.0.1:8790"}
PLAN = {"jobs": [{"title": "one", "line": "hello says hello"}, {"title": "two"}],
        "kept_out": ["secret/"]}


def evening(make_client, project_dir, steps, mode="full_auto", plan=None, **project):
    """The user's chat where the Lead puts its card; returns (client, model, pid, cid, card)."""
    client, model = make_client([step(call("plan_away", plan or PLAN)), text("card is up"),
                                 *steps])
    client.headers.update(ORIGIN)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    if project:
        assert client.patch(f"/api/projects/{pid}", json=project).status_code == 200
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json={"permission_mode": mode}).status_code == 200
    run_id = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "I'm going to sleep: do one and two"}).json()["run"]["id"]
    return client, model, pid, cid, run_id


def card(client, cid):
    (found,) = client.get(f"/api/conversations/{cid}/away").json()
    return found


def night(client, pid):
    return client.get(f"/api/projects/{pid}/away").json()


def ended(client, pid):
    return until(lambda: (n := night(client, pid)) and n["status"] == "ended" and n)


def test_the_card_starts_nothing_and_only_the_users_start_starts_the_jobs_in_copies(
        make_client, wait_run, project_dir):
    client, model, pid, cid, run_id = evening(make_client, project_dir, [
        spawn("Coder", "make hello say hello"), edit(), text("edited"), text("one done"),
        text("two done"), text("good morning")])
    wait_run(client, cid, run_id)
    planned = card(client, cid)
    assert planned["status"] == "planned" and planned["kept_out"] == ["secret"]
    assert [job["title"] for job in planned["jobs"]] == ["one", "two"]
    assert planned["money"] is None and planned["until"] is None  # (no limits of their own)
    # nothing started: no task, no other chat, no step of the model taken for it
    assert tasks(client, pid) == {} and len(model.calls) == 2
    # not from a page that says nothing of where it is from (an agent's command)
    started = client.post(f"/api/away/{planned['id']}/start", headers={"Origin": ""})
    assert started.status_code == 403 and night(client, pid) is None
    assert client.post(f"/api/away/{planned['id']}/start").json()["status"] == "running"
    # no task of the To-do list starts beside the night
    assert client.post(f"/api/projects/{pid}/backlog/next").status_code == 409
    done = ended(client, pid)
    assert done["why"] is None and done["counts"] == {"done": 2, "waits": 0, "failed": 0,
                                                       "stopped": 0, "not_started": 0}
    one, two = done["jobs"]
    assert (one["state"], one["files"], two["state"], two["files"]) == ("done", ["hello.py"],
                                                                         "done", [])
    # each in a chat of its own, and nothing in the project: a full-auto Coder's change too
    assert len({one["conversation_id"], two["conversation_id"], cid}) == 3
    assert (project_dir / "hello.py").read_bytes() == b"print('hi')\n"
    # the morning's one line, in the chat the card was in
    said = [m["content"] for m in client.get(f"/api/conversations/{cid}").json()["messages"]]
    assert said[-1] == "While you were away: 2 done - on the canvas"
    # ...which is the user's to read: the Lead's next turn there is not given it
    later = client.post(f"/api/conversations/{cid}/messages", json={"content": "morning"}).json()
    wait_run(client, cid, later["run"]["id"])
    assert "While you were away" not in str(model.calls[-1])
    # Take in is the user's: the kept copy goes in on their word
    (kept,) = one["kept"]
    assert client.post(f"/api/merges/{kept}/approve").status_code == 200
    assert (project_dir / "hello.py").read_bytes() == b"print('hello')\n"
    # its report on screen once: KOLONİ opened again does not go to it (only from the app's page)
    assert done["seen_at"] is None
    assert client.post(f"/api/away/{done['id']}/seen", headers={"Origin": ""}).status_code == 403
    assert client.post(f"/api/away/{done['id']}/seen").status_code == 204
    assert night(client, pid)["seen_at"]


def test_a_job_that_waits_for_the_users_word_holds_up_no_other(make_client, wait_run,
                                                               project_dir):
    # At "ask" a command waits: job one waits holding hello.py, job two edits it all the same
    run = step(call("run_command", {"command": "echo hi"}))
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [
        edit(), run, edit(id="w2"), text("two done"), text("one done")], mode="ask")
    wait_run(client, cid, run_id)
    client.post(f"/api/away/{card(client, cid)['id']}/start")
    done = ended(client, pid)
    one, two = done["jobs"]
    assert (one["state"], two["state"]) == ("waits", "done")
    assert done["counts"]["waits"] == 1 and one["why"] == 'Lead asks to run "echo hi"'
    ((ask),) = one["asks"]
    assert ask["kind"] == "commands"
    said = client.get(f"/api/conversations/{cid}").json()["messages"][-1]["content"]
    assert said == "While you were away: 1 done, 1 waits - on the canvas"
    # Allow and go on: the job's turn goes on where it stopped, and is done
    assert client.post(f"/api/commands/{ask['id']}/approve", json={"remember": False}
                       ).status_code == 200
    until(lambda: night(client, pid)["jobs"][0]["state"] == "done")
    assert (project_dir / "hello.py").read_bytes() == b"print('hi')\n"
    # (Live: the morning's line stayed "0 done, 2 wait", and the night's end its old time.)
    said = client.get(f"/api/conversations/{cid}").json()["messages"][-1]["content"]
    assert said == "While you were away: 2 done - on the canvas"
    assert night(client, pid)["ended_at"] > done["ended_at"]


def test_a_job_that_fails_is_tried_once_more_then_could_not_be_done_and_the_next_goes_on(
        make_client, wait_run, project_dir):
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [
        ModelUnavailable("model server unreachable: refused"),
        ModelUnavailable("model server unreachable: refused again"), text("two done")])
    wait_run(client, cid, run_id)
    client.post(f"/api/away/{card(client, cid)['id']}/start")
    done = ended(client, pid)
    one, two = done["jobs"]
    assert (one["state"], two["state"]) == ("failed", "done")
    assert "refused again" in one["why"]
    runs = client.get(f"/api/conversations/{one['conversation_id']}").json()["runs"]
    assert [r["status"] for r in runs] == ["failed", "failed"]  # tried once more, in its chat
    assert done["counts"]["failed"] == 1


def test_a_job_stopped_at_its_step_limit_says_so_in_words_not_by_koloni_s_code(
        make_client, wait_run, project_dir):
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [
        ModelUnavailable("refused"), ModelUnavailable("refused again"), text("two done")])
    wait_run(client, cid, run_id)
    client.post(f"/api/away/{card(client, cid)['id']}/start")
    chat = ended(client, pid)["jobs"][0]["conversation_id"]
    with client.app.state.session_factory() as session:
        assert away.turn_ended(session, Run(conversation_id=chat, error="step_limit"), "failed")
        session.commit()
    assert night(client, pid)["jobs"][0]["why"] == "stopped at its step limit"

def test_a_place_kept_out_is_refused_at_night_and_said_in_the_morning(make_client, wait_run,
                                                                     project_dir):
    (project_dir / "secret").mkdir()
    (project_dir / "secret" / "pay.py").write_bytes(b"pay = 1\n")
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [
        edit("secret/pay.py", "1", "2"), step(call("run_command", {"command": "del secret\\pay.py"},
                                                   "c2")),
        text("one done"), text("two done")])
    wait_run(client, cid, run_id)
    client.post(f"/api/away/{card(client, cid)['id']}/start")
    done = ended(client, pid)
    assert [job["state"] for job in done["jobs"]] == ["done", "done"]
    assert [t["what"] for t in done["tried"]] == ["Lead: edit_file secret/pay.py",
                                                  "Lead: run del secret\\pay.py"]
    results = [t["result"] for t in client.get(
        f"/api/conversations/{done['jobs'][0]['conversation_id']}").json()["tool_calls"]]
    assert all("secret is kept out:" in r for r in results)
    assert (project_dir / "secret" / "pay.py").read_bytes() == b"pay = 1\n"


def test_stop_all_cuts_the_job_at_work_keeps_its_copy_and_starts_no_other(
        make_client, wait_run, project_dir, gate):
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [
        edit(), gate.step(text("never"))])
    wait_run(client, cid, run_id)
    started = client.post(f"/api/away/{card(client, cid)['id']}/start").json()
    gate.wait_partial()
    assert night(client, pid)["jobs"][0]["state"] == "working"
    stopped = client.post(f"/api/away/{started['id']}/stop").json()
    assert stopped["status"] == "ended" and stopped["why"] == "Stopped by you."
    one, two = until(lambda: (n := night(client, pid))["jobs"][0]["kept"] and n["jobs"])
    # B-148: stopped, not failed - and still so once its cut turn is over
    until(lambda: client.get(f"/api/conversations/{one['conversation_id']}").json()[
        "runs"][-1]["status"] == "cancelled")
    one, two = (n := night(client, pid))["jobs"]
    assert (one["state"], one["why"], one["files"]) == ("stopped", "Stopped by you.", ["hello.py"])
    assert n["counts"] == {"done": 0, "waits": 0, "failed": 0, "stopped": 1, "not_started": 1}
    said = client.get(f"/api/conversations/{cid}").json()["messages"][-1]["content"]
    assert said == "While you were away: 0 done, 1 stopped, 1 not started - on the canvas"
    assert two["state"] == "next" and two["conversation_id"] is None
    gate.release()


def test_the_night_stops_at_its_time(make_client, wait_run, project_dir, gate):
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [
        gate.step(text("never")), text("again done")], plan={**PLAN, "until": "07:00"})
    wait_run(client, cid, run_id)
    started = client.post(f"/api/away/{card(client, cid)['id']}/start").json()
    gate.wait_partial()
    # (the clock's look: a job at work takes no step meanwhile)
    client.app.state.triggers.tick(now() + timedelta(days=1))
    done = ended(client, pid)
    assert done["why"].startswith("Stopped at ") and done["why"].endswith("the time you set.")
    assert done["jobs"][0]["state"] == "stopped" and done["id"] == started["id"]
    gate.release()
    # a stopped job is tried again as one that could not be done is, once its turn is over
    job = f"/api/away/{started['id']}/jobs/{done['jobs'][0]['task_id']}/again"
    until(lambda: client.post(job).status_code == 200)
    assert until(lambda: night(client, pid)["jobs"][0]["state"] == "done")


def test_the_night_stops_at_its_money_at_the_next_step(make_client, wait_run, project_dir,
                                                       monkeypatch, gate):
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [
        gate.step(edit()), text("never")], plan={**PLAN, "money": 5})
    wait_run(client, cid, run_id)
    client.post(f"/api/away/{card(client, cid)['id']}/start")
    gate.wait_partial()
    monkeypatch.setattr(away, "spent", lambda session, night: {
        "spent": 6.0, "currency": "USD", "at_least": False})
    gate.release()  # its edit is made; before its next step the money is looked at
    done = ended(client, pid)
    assert done["why"] == "Stopped at 6.00 of 5.00 USD, the spend limit."
    one, two = until(lambda: (n := night(client, pid))["jobs"][0]["kept"] and n["jobs"])
    assert (one["state"], one["why"], one["files"]) == ("stopped", done["why"], ["hello.py"])
    assert two["state"] == "next"


def test_one_notification_at_the_end_where_the_project_has_one(make_client, wait_run,
                                                              project_dir, monkeypatch):
    shown = []
    monkeypatch.setattr(app.web, "has_desktop", lambda: True)
    monkeypatch.setattr(app.web, "desktop", lambda title, said: shown.append(said))
    client, _model, pid, cid, run_id = evening(
        make_client, project_dir, [text("one done"), text("two done")], notify_desktop=True)
    wait_run(client, cid, run_id)
    client.post(f"/api/away/{card(client, cid)['id']}/start")
    ended(client, pid)
    until(lambda: shown)
    assert shown == ["Every job was looked at. While you were away: 2 done - on the canvas."]


def test_what_agents_propose_at_night_waits_for_the_morning(make_client, wait_run, project_dir):
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [
        step(call("add_task", {"title": "rate-limit the form"})), text("one done"),
        text("two done")])
    wait_run(client, cid, run_id)
    client.post(f"/api/away/{card(client, cid)['id']}/start")
    done = ended(client, pid)
    (proposed,) = done["proposed"]
    assert proposed["title"] == "rate-limit the form" and proposed["conversation_id"] is None


def test_the_card_is_changed_before_start_and_put_away_by_not_now(make_client, wait_run,
                                                                 project_dir):
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [])
    wait_run(client, cid, run_id)
    planned = card(client, cid)
    changed = client.patch(f"/api/away/{planned['id']}", json={
        "jobs": [{"title": "only this"}], "kept_out": ["a\\b/"], "until": "06:30",
        "money": None}).json()
    assert [j["title"] for j in changed["jobs"]] == ["only this"]
    assert changed["kept_out"] == ["a/b"] and changed["money"] is None
    assert client.patch(f"/api/away/{planned['id']}", json={"until": "25:00"}).status_code == 409
    assert client.post(f"/api/away/{planned['id']}/dismiss").json()["status"] == "dismissed"
    assert client.post(f"/api/away/{planned['id']}/start").status_code == 409


def test_no_card_from_a_turn_nobody_watches(make_client, wait_run, project_dir):
    from tests.test_trigger_scenarios import run_now, trigger

    client, model, pid, cid, run_id = evening(make_client, project_dir, [
        step(call("plan_away", PLAN, "p2")), text("tried")])
    wait_run(client, cid, run_id)
    planned = card(client, cid)
    started = run_now(client, trigger(client, pid, cid)["id"])
    snap = wait_run(client, cid, started)
    (result,) = [t["result"] for t in snap["tool_calls"] if t["run_id"] == started]
    assert "plan_away is the Orchestrator's, at a turn of the user's own" in result
    # nor is that turn's Lead told to call it
    assert told_when_offered(model) == [True, True, False, False]
    assert [c["status"] for c in client.get(f"/api/conversations/{cid}/away").json()] == [
        planned["status"]]


def test_a_night_left_running_by_a_restart_is_over_and_nothing_starts_again(
        make_client, wait_run, project_dir, gate):
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [gate.step(text("x"))])
    wait_run(client, cid, run_id)
    client.post(f"/api/away/{card(client, cid)['id']}/start")
    gate.wait_partial()
    factory = client.app.state.session_factory
    recover_interrupted(factory)
    with factory() as session:
        (found,) = session.scalars(select(AwayRun)).all()
        assert (found.status, found.why) == ("ended", away.CLOSED)
    gate.release()


def test_the_report_says_what_each_jobs_reviews_last_said(make_client, wait_run, project_dir):
    from app.db.models import Agent, Run

    client, _model, pid, cid, run_id = evening(make_client, project_dir, [text("one done"),
                                                                           text("two done")])
    wait_run(client, cid, run_id)
    client.post(f"/api/away/{card(client, cid)['id']}/start")
    one = ended(client, pid)["jobs"][0]
    with client.app.state.session_factory() as session:
        job_run = session.scalar(select(Run.id).where(Run.conversation_id == one["conversation_id"]))
        for name, found in (("Reviewer", [{"what": "x"}]), ("Tester", [{"what": "y"}, {"what": "z"}]),
                            ("Reviewer", []), ("Designer", [{"what": "w", "blocking": False}]),
                            ("Docs", [{"what": "v"}, {"what": "u", "blocking": False}])):
            session.add(Agent(run_id=job_run, role_name=name, depth=1, tools=[], status="completed",
                              findings=found))
            session.commit()
    assert night(client, pid)["jobs"][0]["checks"] == ["Reviewer: no findings",
                                                        "Tester: 2 findings left",
                                                        # B-192: a suggestion is none left
                                                        "Designer: 1 suggestion",
                                                        "Docs: 1 finding left, 1 suggestion"]


def test_the_job_at_work_says_what_it_does_now(make_client, wait_run, project_dir, gate):
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [
        spawn("Coder", "edit hello"), gate.step(text("edited")), text("one done"), text("two done")])
    wait_run(client, cid, run_id)
    client.post(f"/api/away/{card(client, cid)['id']}/start")
    gate.wait_partial()
    one = night(client, pid)["jobs"][0]
    assert (one["state"], one["now"]) == ("working", "Lead · spawn_agent")
    gate.release()
    assert ended(client, pid)["jobs"][0]["now"] is None


def test_a_change_in_a_place_kept_out_that_no_refusal_caught_is_said_in_the_morning(
        make_client, wait_run, project_dir):
    from app.db.models import Agent, Merge, Run

    client, _model, pid, cid, run_id = evening(make_client, project_dir, [text("one done"),
                                                                           text("two done")])
    wait_run(client, cid, run_id)
    client.post(f"/api/away/{card(client, cid)['id']}/start")
    one = ended(client, pid)["jobs"][0]
    assert night(client, pid)["tried"] == []
    # (a command that wrote there without naming it: its copy holds the file all the same)
    with client.app.state.session_factory() as session:
        job_run = session.scalar(select(Run.id).where(Run.conversation_id == one["conversation_id"]))
        lead = session.scalar(select(Agent.id).where(Agent.run_id == job_run))
        session.add(Merge(run_id=job_run, agent_id=lead, status="interrupted", kept_in="x",
                          files=[{"path": "secret/pay.py"}, {"path": "hello.py"}]))
        session.commit()
    done = night(client, pid)
    assert done["jobs"][0]["kept_out"] == ["secret/pay.py"]
    # (found in the morning, not refused at night: said apart)
    assert done["tried"] == [] and done["slipped"] == [
        {"task_id": one["task_id"], "what": "one: changed secret/pay.py in its copy"}]



def test_a_job_with_a_team_and_its_recipe_works_by_it_and_is_done_at_ready_for_you(
        make_client, wait_run, project_dir):
    from tests.test_chat_teams_scenarios import teams_of
    from tests.test_claim_scenarios import write
    from tests.test_recipe_run_scenarios import asked, one_step

    plan = {"jobs": [{"title": "build a", "team": "Web app", "recipe": "Just build"},
                     {"title": "two"}]}
    client, model = make_client({
        "Lead": [step(call("plan_away", plan)), text("card is up"), spawn("Coder", "build a"),
                 text("one done"), text("two done")],
        "Coder": [step(write("a.py", "a\n")), text("built")],
    })
    client.headers.update(ORIGIN)
    recipe = one_step(client, "Just build", "Coder")
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={"permission_mode": "full_auto"})
    run_id = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "sleep"}).json()["run"]["id"]
    wait_run(client, cid, run_id)
    client.post(f"/api/away/{card(client, cid)['id']}/start")
    one = ended(client, pid)["jobs"][0]
    snap = client.get(f"/api/conversations/{one['conversation_id']}").json()
    # its chat works with the card's team and recipe
    assert snap["conversation"]["teams_mode"] == "manual"
    assert [(t["team_id"], t["recipe_id"]) for t in snap["conversation"]["teams"]] == [
        (teams_of(client)["Web app"]["id"], recipe["id"])]
    # its Ready for you is no card it waits on: the job is done, its work kept for Take in
    assert one["state"] == "done" and asked(snap) is None
    assert one["files"] == ["a.py"] and len(one["kept"]) == 1
    assert not (project_dir / "a.py").exists()
    # only the evening's Lead is told to plan: not a job's own Lead, nor its sub-agent
    assert told_when_offered(model)[:2] == [True, True] and not any(told_when_offered(model)[2:])


NIGHT_TR = ("Uyumaya gidiyorum. Bu gece şunları bitir: (1) calc.average'a docstring ekle, (2) build/ "
            "klasörünü sil. .env'e dokunma.")


@pytest.mark.parametrize("said", [
    NIGHT_TR, "UYUMAYA GİDİYORUM, sabaha kadar şunu yap", "Ben yokken testleri düzelt", "yatıyorum, bu gece bitir şunu",
    "I'm going to bed: fix the login", "While I’m away, finish the docs", "Run it overnight", "Tonight, please do the docs"])
def test_a_going_away_phrase_is_a_cue(said):
    from app.agent import AWAY_CUES
    assert AWAY_CUES.search(said)


@pytest.mark.parametrize("said", [
    "config dosyası yokken uygulama çöküyor", "add time.sleep(1)", "worker is going out of memory",
    "şemaya uyumayan satırları atla", "deploy tonight's build", "Sleep mode bug",
    "Make the colours uyumlu with the logo", "eve gidiyorum diye bir log satırı ekle"])
def test_work_that_names_sleep_or_tonight_is_no_cue(said):
    # (The review: bare words fired on ordinary work.)
    from app.agent import AWAY_CUES
    assert not AWAY_CUES.search(said)


@pytest.mark.parametrize("said, noted", [
    (NIGHT_TR, True), ("I'm off to bed - overnight, finish the docs.", True),
    ("Make the colours uyumlu with the logo, and in harmony (uyum).", False)])
def test_a_message_that_may_say_the_user_goes_away_reminds_the_lead_of_its_card(
        make_client, wait_run, project_dir, said, noted):
    # B-121 (live, haiku): a natural Turkish night message - the Lead did the work at once, no card.
    # (A scripted model shows only what the Lead is told, not that it heeds it.)
    from app.agent import AWAY_NOTE
    client, model = make_client([step(call("plan_away", PLAN)), text("card is up")])
    client.headers.update(ORIGIN)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": said}).json()["run"]["id"]
    wait_run(client, cid, run_id)
    # (under the user's own words, which stay the last message: a CLI does what the last one asks)
    last = model.calls[0][-1]
    assert last["role"] == "user" and last["content"] == (f"{said}\n\n{AWAY_NOTE}" if noted else said)
    offered = next(t["function"] for t in model.tool_args[0] if t["function"]["name"] == "plan_away")
    assert "call this first and do none of that work yourself" in offered["description"]


def told_when_offered(model) -> list[bool]:
    """K-gece-dil: each step's system prompt holds the going-away rule exactly when plan_away
    goes out with it; returns, step by step, whether it did."""
    from app.agent import AWAY_PROMPT
    told = [AWAY_PROMPT in str(sent[0]["content"]) for sent in model.calls]
    assert told == ["plan_away" in {t["function"]["name"] for t in tools or ()}
                    for tools in model.tool_args]
    return told


def test_going_away_in_another_language_puts_the_card_and_does_nothing_else(
        make_client, wait_run, project_dir):
    # The user (27 Oct): a message in German, in words no cue lists - the Lead's own rule carries it.
    from app.agent import AWAY_CUES
    said = "Ich gehe schlafen, mach heute Nacht bitte: (1) Docstrings in hello.py, (2) lösch build/."
    assert not AWAY_CUES.search(said)
    client, model = make_client([step(call("plan_away", PLAN)), text("card is up")])
    client.headers.update(ORIGIN)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": said}).json()["run"]["id"]
    snap = wait_run(client, cid, run_id)
    assert card(client, cid)["status"] == "planned"
    assert [t["name"] for t in snap["tool_calls"]] == ["plan_away"]
    assert tasks(client, pid) == {} and night(client, pid) is None
    assert model.calls[0][-1]["content"] == said and told_when_offered(model) == [True, True]


@pytest.mark.no_po  # (the fast model's answers are the views, in order)
def test_each_job_is_assessed_on_its_copys_changes_and_the_report_follows_take_in(team, wait_run, project_dir):  # noqa: F811
    # B-123 (live): a copy job's view said it "worked directly in the project folder... no file change is
    # on record"; the job allowed in the morning had no view; after Take in its row said "nothing changed".
    from tests.test_tier_scenarios import tiered
    run = step(call("run_command", {"command": "echo hi"}))
    client, _default, fast = team([step(call("plan_away", PLAN)), text("card is up"),
                                   edit(), run, edit(id="w2"), text("two done"), text("one done")],
                                  [text("Two looks met."), text("One looks met.")])
    tiered(team, client)
    client.headers.update(ORIGIN)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={"permission_mode": "ask"})
    wait_run(client, cid, client.post(f"/api/conversations/{cid}/messages",
                                      json={"content": "sleep: do one and two"}).json()["run"]["id"])
    client.post(f"/api/away/{card(client, cid)['id']}/start")
    done = ended(client, pid)
    one, two = done["jobs"]
    given = fast.calls[0][1]["content"]
    assert "+print('hello')" in given and "its own copy of the project" in given
    assert "No change of a file is on record" not in given
    # the job that waited, allowed in the morning, is assessed too
    ((ask),) = one["asks"]
    client.post(f"/api/commands/{ask['id']}/approve", json={"remember": False})
    until(lambda: night(client, pid)["jobs"][0]["assessment"] == "One looks met.")
    # Take in: its row says what went in, and nothing is left in its copy
    (kept,) = two["kept"]
    assert client.post(f"/api/merges/{kept}/approve").status_code == 200
    two = night(client, pid)["jobs"][1]
    assert (two["kept"], two["taken"]) == ([], ["hello.py"])


def test_a_job_its_copy_cannot_do_waits_for_the_user_and_the_job_is_told_what_the_copy_leaves_out(
        make_client, wait_run, project_dir):
    # B-122 (live): "delete build/" found no build/ in the copy, did nothing, and was counted done.
    client, model, pid, cid, run_id = evening(make_client, project_dir, [
        text("build/ is not in my copy.\n\n**Needs the project itself: build/ is not in the copy**"),
        text("two done")])
    wait_run(client, cid, run_id)
    client.post(f"/api/away/{card(client, cid)['id']}/start")
    one, two = ended(client, pid)["jobs"]
    assert (one["state"], one["why"]) == ("waits", "Needs the project itself: build/ is not in the copy")
    assert two["state"] == "done"
    told = model.calls[2][-1]["content"]
    assert "The copy leaves out" in told and "build/" in told and "node_modules/" in told


def test_what_a_job_needs_of_the_project_is_read_in_time_linear_in_its_answer():
    # (A model's answer, read as its turn ends: "-\n" lines made the first pattern quadratic.)
    import time
    assert away.needs_project("Done.\n\n- **Needs the project itself: build/ is gone** ") == "build/ is gone"
    for odd in ("-\n" * 50_000, "*" * 50_000 + "\n", "Needs the project itself: a" + " *" * 25_000):
        began = time.monotonic()
        away.needs_project(odd)
        assert time.monotonic() - began < 0.5


def test_what_a_job_took_in_is_its_nights_not_later_work_in_its_chat(make_client, wait_run, project_dir):
    # (The review: a later turn of the job's chat, in the project, was said "taken in" from the night.)
    from tests.test_claim_scenarios import write
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [
        text("one done"), text("two done"),
        spawn("Coder", "write later.py"), step(write("later.py", "later\n")), text("written"), text("later")])
    wait_run(client, cid, run_id)
    client.post(f"/api/away/{card(client, cid)['id']}/start")
    one = ended(client, pid)["jobs"][0]
    later = client.post(f"/api/conversations/{one['conversation_id']}/messages",
                        json={"content": "write later.py"}).json()["run"]["id"]
    wait_run(client, one["conversation_id"], later)
    assert (project_dir / "later.py").exists()
    assert night(client, pid)["jobs"][0]["taken"] == []


def test_a_job_that_waits_for_a_question_after_a_refused_command_says_so_and_holds_off_no_new_night(
        make_client, wait_run, project_dir):
    # B-147 (live, R68/R69): an earlier night's job waiting for the user held a new night off for good
    # ("... is being worked on: the jobs start once nothing else of the To-do list is at work"); its
    # command refused, the job asked a question in its chat - in neither the report nor anywhere else.
    from app import backlog
    run = step(call("run_command", {"command": "echo hi"}))
    question = step(call("ask_user", {"question": "Fix the old tests too?", "options": ["Yes", "No"]}, "q1"))
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [
        edit(), run, edit(id="w2"), text("two done"), question, text("one done")], mode="ask")
    wait_run(client, cid, run_id)
    client.post(f"/api/away/{card(client, cid)['id']}/start")
    ((ask),) = ended(client, pid)["jobs"][0]["asks"]
    assert client.post(f"/api/commands/{ask['id']}/reject", json={}).status_code == 200
    one = until(lambda: (j := night(client, pid)["jobs"][0])["asks"] and j["asks"][0]["kind"] is None and j)
    assert (one["state"], one["why"]) == ("waits", "Lead asks you something (ask_user)")
    # Waiting for the user's word, it is not at work: a new night starts (its jobs, the next ones).
    with client.app.state.runner._factory() as session:
        assert backlog.busy(session, pid) is not None  # (the To-do list's own start: as before)
        later = AwayRun(project_id=pid, conversation_id=cid, run_id=run_id, jobs=[{"title": "three"}])
        session.add(later)
        session.commit()
        later_id = later.id
    started = client.post(f"/api/away/{later_id}/start")
    assert started.status_code == 200, started.text


def test_a_night_job_done_later_changes_its_own_nights_line_not_a_later_nights(make_client, wait_run, project_dir):
    # (The review, M2: the newest morning line was changed - a second night's, started from the same chat.)
    run = step(call("run_command", {"command": "echo hi"}))
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [
        edit(), run, edit(id="w2"), text("two done"), text("three done"), text("one done")], mode="ask")
    wait_run(client, cid, run_id)
    client.post(f"/api/away/{card(client, cid)['id']}/start")
    ((ask),) = ended(client, pid)["jobs"][0]["asks"]
    with client.app.state.runner._factory() as session:
        second = AwayRun(project_id=pid, conversation_id=cid, run_id=run_id, jobs=[{"title": "three"}])
        session.add(second)
        session.commit()
        second_id = second.id
    assert client.post(f"/api/away/{second_id}/start").status_code == 200
    until(lambda: client.get(f"/api/conversations/{cid}/away").json() and all(
        c["status"] != "running" for c in client.get(f"/api/conversations/{cid}/away").json()))
    lines = lambda: [m["content"] for m in client.get(f"/api/conversations/{cid}").json()["messages"] if m["role"] == "away"]  # noqa: E731
    assert lines() == ["While you were away: 1 done, 1 waits - on the canvas", "While you were away: 1 done - on the canvas"]
    assert client.post(f"/api/commands/{ask['id']}/approve", json={"remember": False}).status_code == 200
    until(lambda: lines()[0] == "While you were away: 2 done - on the canvas")
    assert lines()[1] == "While you were away: 1 done - on the canvas"


def to_do_evening(make_client, wait_run, project_dir, steps, jobs):
    """The Lead's card over the To-do list's tasks one and two (`jobs(one, two)` its jobs);
    returns (client, pid, cid, card, one, two)."""
    client, model = make_client([text("(the plan, below)"), text("card is up"), *steps])
    client.headers.update(ORIGIN)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    one, two = (client.post(f"/api/projects/{pid}/backlog", json={
        "title": title, "criteria": f"{title} is done"}).json()["id"] for title in ("one", "two"))
    model.steps[0] = step(call("plan_away", {"jobs": jobs(one, two)}))
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={"permission_mode": "full_auto"})
    run_id = client.post(f"/api/conversations/{cid}/messages",
                         json={"content": "I'm going to sleep: work through the To-do"}).json()["run"]["id"]
    wait_run(client, cid, run_id)
    return client, pid, cid, card(client, cid), one, two


def test_a_job_that_is_a_task_of_the_to_do_list_is_that_task_not_a_copy(make_client, wait_run, project_dir):
    # B-409 (live, R206): "work through the To-do" put each task on the list again, the real ones left to do.
    client, pid, _cid, planned, one, two = to_do_evening(
        make_client, wait_run, project_dir, [text("one done"), text("new done"), text("two done")],
        lambda one, two: [{"title": "do the first", "line": "said otherwise", "task_id": one},
                          {"title": "new"}, {"title": "two", "task_id": two}])
    # the card says what runs: the task's own words, not the Lead's
    assert [(job["title"], job["line"], job["task_id"]) for job in planned["jobs"]] == [
        ("one", "one is done", one), ("new", None, None), ("two", "two is done", two)]
    # the user's change keeps which task a job is; one not to do here, twice, or not OK'd yet
    # by the user (the Lead's at Full auto) is refused
    unseen = client.post(f"/api/projects/{pid}/backlog", json={"title": "unseen"}).json()["id"]
    with client.app.state.runner._factory() as session:
        session.get_one(BacklogTask, unseen).po = {"lead": "add"}
        session.commit()
    jobs = [{"title": job["title"], "task_id": job["task_id"]} for job in planned["jobs"]]
    for wrong in ([{"title": "x", "task_id": "nope"}], [jobs[0], jobs[0]],
                  [{"title": "x", "task_id": unseen}]):
        assert client.patch(f"/api/away/{planned['id']}", json={"jobs": wrong}).status_code == 409
    client.delete(f"/api/backlog/{unseen}")
    assert client.patch(f"/api/away/{planned['id']}", json={"jobs": jobs}).status_code == 200
    assert client.post(f"/api/away/{planned['id']}/start").status_code == 200
    done = ended(client, pid)
    assert [(job["task_id"], job["state"]) for job in done["jobs"]][::2] == [(one, "done"), (two, "done")]
    listed = client.get(f"/api/projects/{pid}/backlog").json()
    assert sorted(task["title"] for task in listed) == ["new", "one", "two"]  # (not five)
    assert all(task["status"] != "todo" for task in listed)


def test_a_task_the_night_never_started_is_the_to_do_lists_again(make_client, wait_run, project_dir):
    # (The review: a night stopped before it held the user's task for good - Run the backlog said
    # "no task of the backlog is todo".)
    client, pid, _cid, planned, one, _two = to_do_evening(
        make_client, wait_run, project_dir, [text("one done")],
        lambda one, two: [{"title": "one", "task_id": one}])
    assert client.patch(f"/api/away/{planned['id']}", json={"money": 0}).status_code == 200
    assert client.post(f"/api/away/{planned['id']}/start").status_code == 200
    done = ended(client, pid)
    assert done["why"] and done["counts"]["not_started"] == 1
    assert [(job["task_id"], job["state"]) for job in done["jobs"]] == [(one, "next")]
    started = client.post(f"/api/projects/{pid}/backlog/next")
    assert started.status_code == 200, started.text
