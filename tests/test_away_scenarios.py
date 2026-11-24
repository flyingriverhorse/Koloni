"""Slice 106's acceptance set, as ☾ Away: "work while I'm away". The Orchestrator puts the work on
To-do; only the user's Go away starts it, once the chat they went away from has finished its
turn; each task works in a new chat and a copy of its own, so nothing reaches the project before
the user's Take in; a task that waits for the user's word, or fails twice, never holds up the
next; Away lasts until they are back, or stops at its time, its money or Stop all; and they come
back to one summary in the chat."""

import re
from datetime import timedelta

import pytest
from sqlalchemy import select

import app.web
from app import away
from app.agent import recover_interrupted
from app.db.models import AwayRun, Run, now
from app.model_client import ModelUnavailable
from tests.test_agent_writes import edit
from tests.test_backlog_auto import tasks, until
from tests.test_chat_flow import text
from tests.test_spawn import call, spawn, step
from tests.test_team import team  # noqa: F401  (a fixture)

ORIGIN = {"Origin": "http://127.0.0.1:8790"}
PLAN = {
    "jobs": [{"title": "one", "line": "hello says hello"}, {"title": "two"}],
    "kept_out": ["secret/"],
}
OFFER = {"kept_out": ["secret/"]}


def to_do(plan=PLAN):
    """The Orchestrator's step that puts `plan`'s jobs on To-do (add_task), in order."""
    return step(
        *(
            call(
                "add_task",
                {"title": job["title"], **({"criteria": job["line"]} if job.get("line") else {})},
                f"t{i}",
            )
            for i, job in enumerate(plan["jobs"])
        )
    )


def evening(make_client, project_dir, steps, mode="full_auto", plan=None, **project):
    """The user's chat whose Orchestrator puts the work on To-do; its Go away (`go_away`) takes
    `plan`'s places kept out and limits. Returns (client, model, pid, cid, run_id)."""
    plan = plan or PLAN
    client, model = make_client([to_do(plan), text("on your To-do"), *steps])
    client.headers.update(ORIGIN)
    client.away_given = {key: plan[key] for key in ("kept_out", "until", "money") if key in plan}
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    if project:
        assert client.patch(f"/api/projects/{pid}", json=project).status_code == 200
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert (
        client.patch(f"/api/conversations/{cid}", json={"permission_mode": mode}).status_code == 200
    )
    # (A job runs at the level of the chat gone from: `mode`.)
    client.todo_mode = mode
    run_id = client.post(
        f"/api/conversations/{cid}/messages", json={"content": "I'm going to sleep: do one and two"}
    ).json()["run"]["id"]
    return client, model, pid, cid, run_id


def proposed_in(client, cid):
    """The ids of the tasks proposed in chat `cid` and not decided yet, in To-do's order."""
    pid = client.get(f"/api/conversations/{cid}").json()["conversation"]["project_id"]
    return [
        t["id"]
        for t in client.get(f"/api/projects/{pid}/backlog").json()
        if t["proposed_in"] == cid and t["status"] == "proposed"
    ]


def go_away(client, cid, **given):
    """The user's Go away from chat `cid`: the tasks proposed there ticked, with the evening's
    places kept out and limits."""
    return client.post(
        f"/api/conversations/{cid}/away",
        json={"task_ids": proposed_in(client, cid), **getattr(client, "away_given", {}), **given},
    )


def night(client, pid):
    return client.get(f"/api/projects/{pid}/away").json()


def looked_at(found):
    return found["status"] == "ended" or all(
        job["state"] not in ("working", "next") for job in found["jobs"]
    )


def ended(client, pid):
    """Away once each of its tasks was looked at - then the user is back - or once it stopped."""
    found = until(lambda: (n := night(client, pid)) and looked_at(n) and n)
    if found["status"] == "running":
        assert client.post(f"/api/away/{found['id']}/back", headers=ORIGIN).status_code == 200
    return until(lambda: (n := night(client, pid))["status"] == "ended" and n)


SPAN = re.compile(r"^While you were away \(\d\d:\d\d – \d\d:\d\d\): ")


def summary(said):
    """The summary's words after its time span."""
    assert SPAN.match(said), said
    return SPAN.sub("", said)


def lines(client, cid):
    return [
        summary(m["content"])
        for m in client.get(f"/api/conversations/{cid}").json()["messages"]
        if m["role"] == "away"
    ]


def test_nothing_starts_before_go_away_and_go_away_works_the_to_do_in_copies(
    make_client, wait_run, project_dir
):
    client, model, pid, cid, run_id = evening(
        make_client,
        project_dir,
        [
            spawn("Coder", "make hello say hello"),
            edit(),
            text("edited"),
            text("one done"),
            text("two done"),
            text("good morning"),
        ],
    )
    wait_run(client, cid, run_id)
    # nothing started: the work proposed on To-do from this chat, no other chat, no step of the
    # model taken for it
    assert {title: (t["status"], t["proposed_in"]) for title, t in tasks(client, pid).items()} == {
        "one": ("proposed", cid),
        "two": ("proposed", cid),
    } and len(model.calls) == 2
    # not from a page that says nothing of where it is from (an agent's command)
    started = client.post(
        f"/api/conversations/{cid}/away",
        json={"task_ids": proposed_in(client, cid)},
        headers={"Origin": ""},
    )
    assert started.status_code == 403 and night(client, pid) is None
    started = go_away(client, cid).json()
    assert started["status"] == "running" and started["kept_out"] == ["secret"]
    assert [job["title"] for job in started["jobs"]] == ["one", "two"]
    assert started["money"] is None and started["until"] is None  # (no limits of their own)
    # a job of the night is no task to give to a chat meanwhile
    ids = [job["task_id"] for job in started["jobs"]]
    given = client.post(f"/api/projects/{pid}/backlog/do-in-chat", json={"task_ids": ids[:1]})
    assert given.status_code == 422
    done = ended(client, pid)
    assert done["why"] is None and done["counts"] == {
        "done": 2,
        "waits": 0,
        "failed": 0,
        "stopped": 0,
        "not_started": 0,
    }
    one, two = done["jobs"]
    assert (one["state"], one["files"], two["state"], two["files"]) == (
        "done",
        ["hello.py"],
        "done",
        [],
    )
    # each in a chat of its own, and nothing in the project: a full-auto Coder's change too
    assert len({one["conversation_id"], two["conversation_id"], cid}) == 3
    assert (project_dir / "hello.py").read_bytes() == b"print('hi')\n"
    # the one summary, in the chat they went away from
    said = [m["content"] for m in client.get(f"/api/conversations/{cid}").json()["messages"]]
    assert summary(said[-1]) == "2 of 2 To-do done"
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


def test_a_job_that_waits_for_the_users_word_holds_up_no_other(make_client, wait_run, project_dir):
    # At "ask" a command waits: job one waits holding hello.py, job two edits it all the same
    run = step(call("run_command", {"command": "echo hi"}))
    client, _model, pid, cid, run_id = evening(
        make_client,
        project_dir,
        [edit(), run, edit(id="w2"), text("two done"), text("one done")],
        mode="ask",
    )
    wait_run(client, cid, run_id)
    go_away(client, cid)
    done = ended(client, pid)
    one, two = done["jobs"]
    assert (one["state"], two["state"]) == ("waits", "done")
    assert done["counts"]["waits"] == 1 and one["why"] == 'Lead asks to run "echo hi"'
    ((ask),) = one["asks"]
    assert ask["kind"] == "commands"
    said = client.get(f"/api/conversations/{cid}").json()["messages"][-1]["content"]
    assert summary(said) == "1 of 2 To-do done · 1 waits"
    # Allow and go on: the job's turn goes on where it stopped, and is done
    assert (
        client.post(f"/api/commands/{ask['id']}/approve", json={"remember": False}).status_code
        == 200
    )
    until(lambda: night(client, pid)["jobs"][0]["state"] == "done")
    assert (project_dir / "hello.py").read_bytes() == b"print('hi')\n"
    # (Live: the morning's line stayed "0 done, 2 wait", and the night's end its old time.)
    said = client.get(f"/api/conversations/{cid}").json()["messages"][-1]["content"]
    assert summary(said) == "2 of 2 To-do done"
    assert night(client, pid)["ended_at"] > done["ended_at"]


def test_a_job_that_fails_is_tried_once_more_then_could_not_be_done_and_the_next_goes_on(
    make_client, wait_run, project_dir
):
    client, _model, pid, cid, run_id = evening(
        make_client,
        project_dir,
        [
            ModelUnavailable("model server unreachable: refused"),
            ModelUnavailable("model server unreachable: refused again"),
            text("two done"),
        ],
    )
    wait_run(client, cid, run_id)
    go_away(client, cid)
    done = ended(client, pid)
    one, two = done["jobs"]
    assert (one["state"], two["state"]) == ("failed", "done")
    assert "refused again" in one["why"]
    runs = client.get(f"/api/conversations/{one['conversation_id']}").json()["runs"]
    assert [r["status"] for r in runs] == ["failed", "failed"]  # tried once more, in its chat
    assert done["counts"]["failed"] == 1


def test_a_job_stopped_at_its_step_limit_says_so_in_words_not_by_koloni_s_code(
    make_client, wait_run, project_dir
):
    client, _model, pid, cid, run_id = evening(
        make_client,
        project_dir,
        [ModelUnavailable("refused"), ModelUnavailable("refused again"), text("two done")],
    )
    wait_run(client, cid, run_id)
    go_away(client, cid)
    chat = ended(client, pid)["jobs"][0]["conversation_id"]
    with client.app.state.session_factory() as session:
        assert away.turn_ended(session, Run(conversation_id=chat, error="step_limit"), "failed")
        session.commit()
    assert night(client, pid)["jobs"][0]["why"] == "stopped at its step limit"


def test_a_place_kept_out_is_refused_at_night_and_said_in_the_morning(
    make_client, wait_run, project_dir
):
    (project_dir / "secret").mkdir()
    (project_dir / "secret" / "pay.py").write_bytes(b"pay = 1\n")
    client, _model, pid, cid, run_id = evening(
        make_client,
        project_dir,
        [
            edit("secret/pay.py", "1", "2"),
            step(call("run_command", {"command": "del secret\\pay.py"}, "c2")),
            text("one done"),
            text("two done"),
        ],
    )
    wait_run(client, cid, run_id)
    go_away(client, cid)
    done = ended(client, pid)
    assert [job["state"] for job in done["jobs"]] == ["done", "done"]
    assert [t["what"] for t in done["tried"]] == [
        "Lead: edit_file secret/pay.py",
        "Lead: run del secret\\pay.py",
    ]
    results = [
        t["result"]
        for t in client.get(f"/api/conversations/{done['jobs'][0]['conversation_id']}").json()[
            "tool_calls"
        ]
    ]
    assert all("secret is kept out:" in r for r in results)
    assert (project_dir / "secret" / "pay.py").read_bytes() == b"pay = 1\n"


def test_stop_all_cuts_the_job_at_work_keeps_its_copy_and_starts_no_other(
    make_client, wait_run, project_dir, gate
):
    client, _model, pid, cid, run_id = evening(
        make_client, project_dir, [edit(), gate.step(text("never"))]
    )
    wait_run(client, cid, run_id)
    started = go_away(client, cid).json()
    gate.wait_partial()
    assert night(client, pid)["jobs"][0]["state"] == "working"
    stopped = client.post(f"/api/away/{started['id']}/stop").json()
    assert stopped["status"] == "ended" and stopped["why"] == "Stopped by you."
    one, two = until(lambda: (n := night(client, pid))["jobs"][0]["kept"] and n["jobs"])
    # B-148: stopped, not failed - and still so once its cut turn is over
    until(
        lambda: (
            client.get(f"/api/conversations/{one['conversation_id']}").json()["runs"][-1]["status"]
            == "cancelled"
        )
    )
    one, two = (n := night(client, pid))["jobs"]
    assert (one["state"], one["why"], one["files"]) == ("stopped", "Stopped by you.", ["hello.py"])
    assert n["counts"] == {"done": 0, "waits": 0, "failed": 0, "stopped": 1, "not_started": 1}
    said = client.get(f"/api/conversations/{cid}").json()["messages"][-1]["content"]
    assert summary(said) == "0 of 2 To-do done · 1 stopped · 1 not started"
    assert two["state"] == "next" and two["conversation_id"] is None
    gate.release()


def test_the_night_stops_at_its_time(make_client, wait_run, project_dir, gate):
    client, _model, pid, cid, run_id = evening(
        make_client,
        project_dir,
        [gate.step(text("never")), text("again done")],
        plan={**PLAN, "until": "07:00"},
    )
    wait_run(client, cid, run_id)
    started = go_away(client, cid).json()
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


def test_the_night_stops_at_its_money_at_the_next_step(
    make_client, wait_run, project_dir, monkeypatch, gate
):
    client, _model, pid, cid, run_id = evening(
        make_client, project_dir, [gate.step(edit()), text("never")], plan={**PLAN, "money": 5}
    )
    wait_run(client, cid, run_id)
    go_away(client, cid)
    gate.wait_partial()
    monkeypatch.setattr(
        away, "spent", lambda session, night: {"spent": 6.0, "currency": "USD", "at_least": False}
    )
    gate.release()  # its edit is made; before its next step the money is looked at
    done = ended(client, pid)
    assert done["why"] == "Stopped at 6.00 of 5.00 USD, the spend limit."
    one, two = until(lambda: (n := night(client, pid))["jobs"][0]["kept"] and n["jobs"])
    assert (one["state"], one["why"], one["files"]) == ("stopped", done["why"], ["hello.py"])
    assert two["state"] == "next"


def test_one_notification_once_every_task_was_looked_at_and_none_at_im_back(
    make_client, wait_run, project_dir, monkeypatch
):
    shown = []
    monkeypatch.setattr(app.web, "has_desktop", lambda: True)
    monkeypatch.setattr(app.web, "desktop", lambda title, said: shown.append(said))
    client, _model, pid, cid, run_id = evening(
        make_client, project_dir, [text("one done"), text("two done")], notify_desktop=True
    )
    wait_run(client, cid, run_id)
    go_away(client, cid)
    until(lambda: shown)
    (said,) = shown
    assert (
        said.startswith("Every To-do task was looked at. ")
        and summary(said.removeprefix("Every To-do task was looked at. ")) == "2 of 2 To-do done."
    )
    # Away lasts until the user is back: none again at the clock's look, none at I'm back
    client.app.state.triggers.tick(now())
    assert night(client, pid)["status"] == "running"
    ended(client, pid)
    assert len(shown) == 1


def test_what_agents_propose_at_night_waits_for_the_morning(make_client, wait_run, project_dir):
    client, _model, pid, cid, run_id = evening(
        make_client,
        project_dir,
        [
            step(call("add_task", {"title": "rate-limit the form"})),
            text("one done"),
            text("two done"),
        ],
    )
    wait_run(client, cid, run_id)
    go_away(client, cid)
    done = ended(client, pid)
    (proposed,) = done["proposed"]
    assert proposed["title"] == "rate-limit the form" and proposed["conversation_id"] is None


def test_the_offer_is_one_line_and_starts_nothing(make_client, wait_run, project_dir):
    client, model = make_client(
        [
            to_do(),
            step(call("offer_away", {**OFFER, "money": 2})),
            text("Two tasks are on your To-do."),
        ]
    )
    client.headers.update(ORIGIN)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    snap = wait_run(
        client,
        cid,
        client.post(
            f"/api/conversations/{cid}/messages",
            json={"content": "I'm going to sleep: do one and two"},
        ).json()["run"]["id"],
    )
    (offered,) = client.get(f"/api/conversations/{cid}/away").json()
    assert (offered["status"], offered["kept_out"], offered["money"]) == ("planned", ["secret"], 2)
    # (the tasks its Orchestrator put on To-do in that turn: what its Go away line takes)
    assert [job["title"] for job in offered["jobs"]] == ["one", "two"]
    assert [t["name"] for t in snap["tool_calls"]] == ["add_task", "add_task", "offer_away"]
    # nothing started: the tasks proposed from this chat, no other chat, nobody away
    assert {t["status"] for t in tasks(client, pid).values()} == {"proposed"}
    assert night(client, pid) is None and len(model.calls) == 3
    assert len(client.get(f"/api/projects/{pid}/conversations").json()) == 1
    # a newer offer takes its place; Go away puts every offer away
    assert go_away(client, cid).status_code == 200
    assert [c["status"] for c in client.get(f"/api/conversations/{cid}/away").json()] == [
        "dismissed",
        "running",
    ]


def test_no_offer_from_a_turn_nobody_watches(make_client, wait_run, project_dir):
    from tests.test_trigger_scenarios import run_now, trigger

    client, model = make_client(
        [
            step(call("offer_away", OFFER)),
            text("offered"),
            step(call("offer_away", OFFER, "p2")),
            text("tried"),
        ]
    )
    client.headers.update(ORIGIN)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    wait_run(
        client,
        cid,
        client.post(f"/api/conversations/{cid}/messages", json={"content": "sleep"}).json()["run"][
            "id"
        ],
    )
    (planned,) = client.get(f"/api/conversations/{cid}/away").json()
    started = run_now(client, trigger(client, pid, cid)["id"])
    snap = wait_run(client, cid, started)
    (result,) = [t["result"] for t in snap["tool_calls"] if t["run_id"] == started]
    assert "offer_away is the Orchestrator's, at a turn of the user's own" in result
    # nor is that turn's Lead told to call it
    assert told_when_offered(model) == [True, True, False, False]
    assert [c["status"] for c in client.get(f"/api/conversations/{cid}/away").json()] == [
        planned["status"]
    ]


def test_a_night_left_running_by_a_restart_is_over_and_nothing_starts_again(
    make_client, wait_run, project_dir, gate
):
    client, _model, pid, cid, run_id = evening(make_client, project_dir, [gate.step(text("x"))])
    wait_run(client, cid, run_id)
    go_away(client, cid)
    gate.wait_partial()
    factory = client.app.state.session_factory
    recover_interrupted(factory)
    with factory() as session:
        (found,) = session.scalars(select(AwayRun)).all()
        assert (found.status, found.why) == ("ended", away.CLOSED)
    # its summary written; the rule back to the project's minutes (nothing is away)
    assert lines(client, cid) == ["0 of 2 To-do done · 1 could not be done · 1 not started"]
    assert night(client, pid)["jobs"][1]["conversation_id"] is None
    gate.release()


def test_the_report_says_what_each_jobs_reviews_last_said(make_client, wait_run, project_dir):
    from app.db.models import Agent, Run

    client, _model, pid, cid, run_id = evening(
        make_client, project_dir, [text("one done"), text("two done")]
    )
    wait_run(client, cid, run_id)
    go_away(client, cid)
    one = ended(client, pid)["jobs"][0]
    with client.app.state.session_factory() as session:
        job_run = session.scalar(
            select(Run.id).where(Run.conversation_id == one["conversation_id"])
        )
        for name, found in (
            ("Reviewer", [{"what": "x"}]),
            ("Tester", [{"what": "y"}, {"what": "z"}]),
            ("Reviewer", []),
            ("Designer", [{"what": "w", "blocking": False}]),
            ("Docs", [{"what": "v"}, {"what": "u", "blocking": False}]),
        ):
            session.add(
                Agent(
                    run_id=job_run,
                    role_name=name,
                    depth=1,
                    tools=[],
                    status="completed",
                    findings=found,
                )
            )
            session.commit()
    assert night(client, pid)["jobs"][0]["checks"] == [
        "Reviewer: no findings",
        "Tester: 2 findings left",
        # B-192: a suggestion is none left
        "Designer: 1 suggestion",
        "Docs: 1 finding left, 1 suggestion",
    ]


def test_the_job_at_work_says_what_it_does_now(make_client, wait_run, project_dir, gate):
    client, _model, pid, cid, run_id = evening(
        make_client,
        project_dir,
        [
            spawn("Coder", "edit hello"),
            gate.step(text("edited")),
            text("one done"),
            text("two done"),
        ],
    )
    wait_run(client, cid, run_id)
    go_away(client, cid)
    gate.wait_partial()
    one = night(client, pid)["jobs"][0]
    assert (one["state"], one["now"]) == ("working", "Lead · spawn_agent")
    gate.release()
    assert ended(client, pid)["jobs"][0]["now"] is None


def test_a_change_in_a_place_kept_out_that_no_refusal_caught_is_said_in_the_morning(
    make_client, wait_run, project_dir
):
    from app.db.models import Agent, Merge, Run

    client, _model, pid, cid, run_id = evening(
        make_client, project_dir, [text("one done"), text("two done")]
    )
    wait_run(client, cid, run_id)
    go_away(client, cid)
    one = ended(client, pid)["jobs"][0]
    assert night(client, pid)["tried"] == []
    # (a command that wrote there without naming it: its copy holds the file all the same)
    with client.app.state.session_factory() as session:
        job_run = session.scalar(
            select(Run.id).where(Run.conversation_id == one["conversation_id"])
        )
        lead = session.scalar(select(Agent.id).where(Agent.run_id == job_run))
        session.add(
            Merge(
                run_id=job_run,
                agent_id=lead,
                status="interrupted",
                kept_in="x",
                files=[{"path": "secret/pay.py"}, {"path": "hello.py"}],
            )
        )
        session.commit()
    done = night(client, pid)
    assert done["jobs"][0]["kept_out"] == ["secret/pay.py"]
    # (found in the morning, not refused at night: said apart)
    assert done["tried"] == [] and done["slipped"] == [
        {"task_id": one["task_id"], "what": "one: changed secret/pay.py in its copy"}
    ]


def test_a_job_with_a_team_and_its_recipe_works_by_it_and_is_done_at_ready_for_you(
    make_client, wait_run, project_dir
):
    from tests.test_chat_teams_scenarios import teams_of
    from tests.test_claim_scenarios import write
    from tests.test_recipe_run_scenarios import asked, one_step

    plan = {"jobs": [{"title": "build a"}, {"title": "two"}]}
    client, model = make_client(
        {
            "Lead": [
                to_do(plan),
                text("on your To-do"),
                spawn("Coder", "build a"),
                text("one done"),
                text("two done"),
            ],
            "Coder": [step(write("a.py", "a\n")), text("built")],
        }
    )
    client.headers.update(ORIGIN)
    recipe = one_step(client, "Just build", "Coder")
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(
        f"/api/conversations/{cid}",
        json={
            "permission_mode": "full_auto",
            "teams_mode": "manual",
            "teams": [{"team_id": teams_of(client)["Web app"]["id"], "recipe_id": recipe["id"]}],
        },
    )
    client.todo_mode = "full_auto"
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "sleep"}).json()[
        "run"
    ]["id"]
    wait_run(client, cid, run_id)
    go_away(client, cid)
    one = ended(client, pid)["jobs"][0]
    snap = client.get(f"/api/conversations/{one['conversation_id']}").json()
    # its chat works with the team and recipe the user picked in the chat they went away from
    assert snap["conversation"]["teams_mode"] == "manual"
    assert [(t["team_id"], t["recipe_id"]) for t in snap["conversation"]["teams"]] == [
        (teams_of(client)["Web app"]["id"], recipe["id"])
    ]
    # its Ready for you is no card it waits on: the job is done, its work kept for Take in
    assert one["state"] == "done" and asked(snap) is None
    assert one["files"] == ["a.py"] and len(one["kept"]) == 1
    assert not (project_dir / "a.py").exists()


NIGHT_TR = (
    "Uyumaya gidiyorum. Bu gece şunları bitir: (1) calc.average'a docstring ekle, (2) build/ "
    "klasörünü sil. .env'e dokunma."
)


@pytest.mark.parametrize(
    "said",
    [
        NIGHT_TR,
        "UYUMAYA GİDİYORUM, sabaha kadar şunu yap",
        "Ben yokken testleri düzelt",
        "yatıyorum, bu gece bitir şunu",
        "I'm going to bed: fix the login",
        "While I’m away, finish the docs",
        "Run it overnight",
        "Tonight, please do the docs",
    ],
)
def test_a_going_away_phrase_is_a_cue(said):
    from app.agent import AWAY_CUES

    assert AWAY_CUES.search(said)


@pytest.mark.parametrize(
    "said",
    [
        "config dosyası yokken uygulama çöküyor",
        "add time.sleep(1)",
        "worker is going out of memory",
        "şemaya uyumayan satırları atla",
        "deploy tonight's build",
        "Sleep mode bug",
        "Make the colours uyumlu with the logo",
        "eve gidiyorum diye bir log satırı ekle",
    ],
)
def test_work_that_names_sleep_or_tonight_is_no_cue(said):
    # (The review: bare words fired on ordinary work.)
    from app.agent import AWAY_CUES

    assert not AWAY_CUES.search(said)


@pytest.mark.parametrize(
    "said, noted",
    [
        (NIGHT_TR, True),
        ("I'm off to bed - overnight, finish the docs.", True),
        ("Make the colours uyumlu with the logo, and in harmony (uyum).", False),
    ],
)
def test_a_message_that_may_say_the_user_goes_away_reminds_the_lead_to_offer_it(
    make_client, wait_run, project_dir, said, noted
):
    # B-121 (live, haiku): a natural Turkish night message - the Lead did the work at once, no card.
    # (A scripted model shows only what the Lead is told, not that it heeds it.)
    from app.agent import AWAY_NOTE

    client, model = make_client([step(call("offer_away", OFFER)), text("offered")])
    client.headers.update(ORIGIN)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": said}).json()[
        "run"
    ]["id"]
    wait_run(client, cid, run_id)
    # (under the user's own words, which stay the last message: a CLI does what the last one asks)
    last = model.calls[0][-1]
    assert last["role"] == "user" and last["content"] == (
        f"{said}\n\n{AWAY_NOTE}" if noted else said
    )
    offered = next(
        t["function"] for t in model.tool_args[0] if t["function"]["name"] == "offer_away"
    )
    assert "with add_task first, do none of it, then call this" in offered["description"]


def told_when_offered(model) -> list[bool]:
    """K-gece-dil: each step's system prompt holds the going-away rule exactly when offer_away
    goes out with it; returns, step by step, whether it did."""
    from app.agent import AWAY_PROMPT

    told = [AWAY_PROMPT in str(sent[0]["content"]) for sent in model.calls]
    assert told == [
        "offer_away" in {t["function"]["name"] for t in tools or ()} for tools in model.tool_args
    ]
    return told


def test_going_away_in_another_language_puts_the_work_on_to_do_and_offers_it(
    make_client, wait_run, project_dir
):
    # The user (27 Oct): a message in German, in words no cue lists - the Lead's own rule carries it.
    from app.agent import AWAY_CUES

    said = (
        "Ich gehe schlafen, mach heute Nacht bitte: (1) Docstrings in hello.py, (2) lösch build/."
    )
    assert not AWAY_CUES.search(said)
    client, model = make_client(
        [step(*to_do().tool_calls, call("offer_away", {}, "o")), text("on your To-do")]
    )
    client.headers.update(ORIGIN)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": said}).json()[
        "run"
    ]["id"]
    snap = wait_run(client, cid, run_id)
    assert [one["status"] for one in client.get(f"/api/conversations/{cid}/away").json()] == [
        "planned"
    ]
    assert [t["name"] for t in snap["tool_calls"]] == ["add_task", "add_task", "offer_away"]
    assert {t["status"] for t in tasks(client, pid).values()} == {"proposed"}
    assert night(client, pid) is None
    assert model.calls[0][-1]["content"] == said and told_when_offered(model) == [True, True]


@pytest.mark.no_po  # (the fast model's answers are the views, in order)
def test_each_job_is_assessed_on_its_copys_changes_and_the_report_follows_take_in(
    team, wait_run, project_dir
):  # noqa: F811
    # B-123 (live): a copy job's view said it "worked directly in the project folder... no file change is
    # on record"; the job allowed in the morning had no view; after Take in its row said "nothing changed".
    from tests.test_tier_scenarios import tiered

    run = step(call("run_command", {"command": "echo hi"}))
    client, _default, fast = team(
        [
            to_do(),
            text("on your To-do"),
            edit(),
            run,
            edit(id="w2"),
            text("two done"),
            text("one done"),
        ],
        [text("Two looks met."), text("One looks met.")],
    )
    tiered(team, client)
    client.headers.update(ORIGIN)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={"permission_mode": "ask"})
    wait_run(
        client,
        cid,
        client.post(
            f"/api/conversations/{cid}/messages", json={"content": "sleep: do one and two"}
        ).json()["run"]["id"],
    )
    go_away(client, cid, kept_out=PLAN["kept_out"])
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
    make_client, wait_run, project_dir
):
    # B-122 (live): "delete build/" found no build/ in the copy, did nothing, and was counted done.
    client, model, pid, cid, run_id = evening(
        make_client,
        project_dir,
        [
            text(
                "build/ is not in my copy.\n\n**Needs the project itself: build/ is not in the copy**"
            ),
            text("two done"),
        ],
    )
    wait_run(client, cid, run_id)
    go_away(client, cid)
    one, two = ended(client, pid)["jobs"]
    assert (one["state"], one["why"]) == (
        "waits",
        "Needs the project itself: build/ is not in the copy",
    )
    assert two["state"] == "done"
    told = model.calls[2][-1]["content"]
    assert "The copy leaves out" in told and "build/" in told and "node_modules/" in told


def test_what_a_job_needs_of_the_project_is_read_in_time_linear_in_its_answer():
    # (A model's answer, read as its turn ends: "-\n" lines made the first pattern quadratic.)
    import time

    assert (
        away.needs_project("Done.\n\n- **Needs the project itself: build/ is gone** ")
        == "build/ is gone"
    )
    for odd in ("-\n" * 50_000, "*" * 50_000 + "\n", "Needs the project itself: a" + " *" * 25_000):
        began = time.monotonic()
        away.needs_project(odd)
        assert time.monotonic() - began < 0.5


def test_what_a_job_took_in_is_its_nights_not_later_work_in_its_chat(
    make_client, wait_run, project_dir
):
    # (The review: a later turn of the job's chat, in the project, was said "taken in" from the night.)
    from tests.test_claim_scenarios import write

    client, _model, pid, cid, run_id = evening(
        make_client,
        project_dir,
        [
            text("one done"),
            text("two done"),
            spawn("Coder", "write later.py"),
            step(write("later.py", "later\n")),
            text("written"),
            text("later"),
        ],
    )
    wait_run(client, cid, run_id)
    go_away(client, cid)
    one = ended(client, pid)["jobs"][0]
    later = client.post(
        f"/api/conversations/{one['conversation_id']}/messages", json={"content": "write later.py"}
    ).json()["run"]["id"]
    wait_run(client, one["conversation_id"], later)
    assert (project_dir / "later.py").exists()
    assert night(client, pid)["jobs"][0]["taken"] == []


def test_a_job_that_waits_for_a_question_after_a_refused_command_says_so_and_holds_off_no_new_night(
    make_client, wait_run, project_dir
):
    # B-147 (live, R68/R69): an earlier night's job waiting for the user held a new night off for good
    # ("... is being worked on: the jobs start once nothing else of the To-do list is at work"); its
    # command refused, the job asked a question in its chat - in neither the report nor anywhere else.
    from app import backlog

    run = step(call("run_command", {"command": "echo hi"}))
    question = step(
        call("ask_user", {"question": "Fix the old tests too?", "options": ["Yes", "No"]}, "q1")
    )
    client, _model, pid, cid, run_id = evening(
        make_client,
        project_dir,
        [edit(), run, edit(id="w2"), text("two done"), question, text("one done")],
        mode="ask",
    )
    wait_run(client, cid, run_id)
    go_away(client, cid)
    ((ask),) = ended(client, pid)["jobs"][0]["asks"]
    assert client.post(f"/api/commands/{ask['id']}/reject", json={}).status_code == 200
    one = until(
        lambda: (j := night(client, pid)["jobs"][0])["asks"] and j["asks"][0]["kind"] is None and j
    )
    assert (one["state"], one["why"]) == ("waits", "Lead asks you something (ask_user)")
    # Waiting for the user's word, it is not at work: a new Away starts (its tasks, the next ones).
    with client.app.state.runner._factory() as session:
        assert backlog.busy(session, pid) is not None  # (the To-do list's own start: as before)
    three = client.post(f"/api/projects/{pid}/backlog", json={"title": "three"}).json()["id"]
    started = client.post(f"/api/conversations/{cid}/away", json={"task_ids": [three]})
    assert started.status_code == 200, started.text


def test_a_night_job_done_later_changes_its_own_nights_line_not_a_later_nights(
    make_client, wait_run, project_dir
):
    # (The review, M2: the newest morning line was changed - a second night's, started from the same chat.)
    run = step(call("run_command", {"command": "echo hi"}))
    client, _model, pid, cid, run_id = evening(
        make_client,
        project_dir,
        [edit(), run, edit(id="w2"), text("two done"), text("three done"), text("one done")],
        mode="ask",
    )
    wait_run(client, cid, run_id)
    go_away(client, cid)
    ((ask),) = ended(client, pid)["jobs"][0]["asks"]
    three = client.post(f"/api/projects/{pid}/backlog", json={"title": "three"}).json()["id"]
    assert (
        client.post(f"/api/conversations/{cid}/away", json={"task_ids": [three]}).status_code == 200
    )
    ended(client, pid)
    assert lines(client, cid) == ["1 of 2 To-do done · 1 waits", "1 of 1 To-do done"]
    assert (
        client.post(f"/api/commands/{ask['id']}/approve", json={"remember": False}).status_code
        == 200
    )
    until(lambda: lines(client, cid)[0] == "2 of 2 To-do done")
    assert lines(client, cid)[1] == "1 of 1 To-do done"


def test_a_task_away_never_started_is_the_to_do_lists_again(make_client, wait_run, project_dir):
    # (The review: a night stopped before it held the user's task for good - Run the backlog said
    # "no task of the backlog is todo".)
    client, _model = make_client([text("hello"), text("one done")])
    client.headers.update(ORIGIN)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    one = client.post(f"/api/projects/{pid}/backlog", json={"title": "one"}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    wait_run(
        client,
        cid,
        client.post(f"/api/conversations/{cid}/messages", json={"content": "hi"}).json()["run"][
            "id"
        ],
    )
    assert (
        client.post(
            f"/api/conversations/{cid}/away", json={"task_ids": [one], "money": 0}
        ).status_code
        == 200
    )
    done = ended(client, pid)
    assert done["why"] and done["counts"]["not_started"] == 1
    assert [(job["task_id"], job["state"]) for job in done["jobs"]] == [(one, "next")]
    started = client.post(f"/api/projects/{pid}/backlog/do-in-chat", json={"task_ids": [one]})
    assert started.status_code == 200, started.text


# --- ☾ Away: Go away from the chat ------------------------------------------------------------


def test_go_away_takes_the_ticked_tasks_in_the_panels_order_and_leaves_the_rest(
    make_client, wait_run, project_dir
):
    client, _model, pid, cid, run_id = evening(
        make_client, project_dir, [text("two done"), text("one done")]
    )
    wait_run(client, cid, run_id)
    mine = client.post(f"/api/projects/{pid}/backlog", json={"title": "mine"}).json()["id"]
    one, two = proposed_in(client, cid)
    # a chat with no turn: nothing for Away to finish first
    empty = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    refused = client.post(f"/api/conversations/{empty}/away", json={"task_ids": [one]})
    assert refused.status_code == 409 and refused.json()["detail"].startswith(
        "write to the Orchestrator first"
    )
    for wrong in ([one, one], ["nope"]):
        assert (
            client.post(f"/api/conversations/{cid}/away", json={"task_ids": wrong}).status_code
            == 409
        )
    started = client.post(
        f"/api/conversations/{cid}/away", json={"task_ids": [two, one], "order": [two, one, mine]}
    ).json()
    assert [job["title"] for job in started["jobs"]] == ["two", "one"]
    # the panel's order is To-do's now; nothing else starts meanwhile
    assert [t["title"] for t in client.get(f"/api/projects/{pid}/backlog").json()] == [
        "two",
        "one",
        "mine",
    ]
    doing = client.post(f"/api/away/{started['id']}/jobs/{one}/again")
    assert (doing.status_code, doing.json()["detail"]) == (409, away.AWAY_NOW)
    done = ended(client, pid)
    assert [(job["title"], job["state"]) for job in done["jobs"]] == [
        ("two", "done"),
        ("one", "done"),
    ]
    left = tasks(client, pid)["mine"]
    assert (left["status"], left["conversation_id"], left["proposed_in"]) == ("todo", None, None)


def test_the_chat_finishes_its_turn_first_and_a_task_added_meanwhile_does_not_join(
    make_client, wait_run, project_dir, gate
):
    client, _model, pid, cid, run_id = evening(
        make_client,
        project_dir,
        [
            gate.step(step(call("add_task", {"title": "three"}, "t9"))),
            text("chat done"),
            text("one done"),
            text("two done"),
        ],
    )
    wait_run(client, cid, run_id)
    later = client.post(
        f"/api/conversations/{cid}/messages", json={"content": "add three too"}
    ).json()["run"]["id"]
    gate.wait_partial()
    assert go_away(client, cid).status_code == 200
    # the chat's turn is at work: To-do waits for it
    client.app.state.triggers.tick(now())
    assert [job["conversation_id"] for job in night(client, pid)["jobs"]] == [None, None]
    gate.release()
    wait_run(client, cid, later)
    done = ended(client, pid)
    assert [(job["title"], job["state"]) for job in done["jobs"]] == [
        ("one", "done"),
        ("two", "done"),
    ]
    assert tasks(client, pid)["three"]["status"] == "proposed"


def test_a_chat_turn_that_waits_for_your_word_does_not_hold_to_do_back(
    make_client, wait_run, project_dir
):
    client, _model, pid, cid, run_id = evening(
        make_client,
        project_dir,
        [
            step(call("run_command", {"command": "echo hi"}, "k")),
            text("one done"),
            text("two done"),
            text("chat done"),
        ],
        mode="ask",
    )
    wait_run(client, cid, run_id)
    later = client.post(f"/api/conversations/{cid}/messages", json={"content": "say hi"}).json()[
        "run"
    ]["id"]
    (command,) = until(lambda: client.get(f"/api/conversations/{cid}").json()["commands"])
    assert go_away(client, cid).status_code == 200
    until(lambda: all(job["state"] == "done" for job in night(client, pid)["jobs"]))
    assert (
        client.post(f"/api/commands/{command['id']}/approve", json={"remember": False}).status_code
        == 200
    )
    wait_run(client, cid, later)


def test_the_spend_limit_counts_only_what_was_spent_after_go_away_and_cuts_the_chats_turn(
    make_client, wait_run, project_dir, gate
):
    import json

    from app.model_client import StepResult, ToolCallRequest
    from tests.conftest import Gate

    def big(id):
        return StepResult(
            "",
            [ToolCallRequest(id, "read_file", json.dumps({"path": "hello.py"}))],
            1_000_000,
            500_000,
        )

    second = Gate()
    client, _model, pid, cid, run_id = evening(
        make_client, project_dir, [big("r1"), gate.step(big("r2")), second.step(text("never"))]
    )
    client.put(
        "/api/prices", json={"model_id": "fake-model", "input": 3, "output": 15, "currency": "USD"}
    )
    wait_run(client, cid, run_id)
    later = client.post(f"/api/conversations/{cid}/messages", json={"content": "read it"}).json()[
        "run"
    ]["id"]
    gate.wait_partial()  # (its first step spent 10.50 before Go away)
    started = go_away(client, cid, money=5).json()
    assert started["spent"] == 0
    gate.release()
    second.wait_partial()  # (and 10.50 more after it)
    client.app.state.triggers.tick(now())
    done = night(client, pid)
    assert (done["status"], done["why"]) == (
        "ended",
        "Stopped at 10.50 of 5.00 USD, the spend limit.",
    )
    second.release()
    assert wait_run(client, cid, later)["runs"][-1]["status"] == "cancelled"


def test_stop_all_stops_a_job_that_waits_for_your_word_too(make_client, wait_run, project_dir):
    # (The review: Stop all cut only the job at work; one waiting on a card stayed open.)
    run = step(call("run_command", {"command": "echo hi"}))
    client, _model, pid, cid, run_id = evening(
        make_client, project_dir, [run, text("two done")], mode="ask"
    )
    wait_run(client, cid, run_id)
    started = go_away(client, cid).json()
    until(lambda: looked_at(night(client, pid)))
    stopped = client.post(f"/api/away/{started['id']}/stop").json()
    assert stopped["status"] == "ended" and stopped["why"] == "Stopped by you."
    one = until(lambda: (j := night(client, pid)["jobs"][0])["state"] == "stopped" and j)
    assert one["why"] == "Stopped by you."
    until(
        lambda: (
            client.get(f"/api/conversations/{one['conversation_id']}").json()["runs"][-1]["status"]
            == "cancelled"
        )
    )


def test_the_offer_holds_only_the_tasks_its_orchestrator_added_in_that_turn(
    make_client, wait_run, project_dir
):
    # (The review: one click on the line approved what any agent proposed in the chat - a
    # sub-agent that read a hostile page, an earlier turn's.)
    client, _model = make_client(
        {
            "Lead": [
                step(call("add_task", {"title": "earlier"}, "t0")),
                text("noted"),
                spawn("Hive keeper", "note what you found"),
                step(
                    call("add_task", {"title": "mine", "criteria": "it is done"}, "t1"),
                    call("offer_away", OFFER, "o1"),
                ),
                text("offered"),
            ],
            "Hive keeper": [step(call("add_task", {"title": "sneaky"}, "c1")), text("added")],
        }
    )
    client.headers.update(ORIGIN)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(
        f"/api/conversations/{cid}",
        json={"permission_mode": "full_auto", "spawn_approval": "never"},
    )
    for said in ("remember this", "I'm going to sleep"):
        wait_run(
            client,
            cid,
            client.post(f"/api/conversations/{cid}/messages", json={"content": said}).json()["run"][
                "id"
            ],
        )
    assert sorted(tasks(client, pid)) == ["earlier", "mine", "sneaky"]
    (offered,) = client.get(f"/api/conversations/{cid}/away").json()
    assert [(job["title"], job["line"], job["task_id"]) for job in offered["jobs"]] == [
        ("mine", "it is done", tasks(client, pid)["mine"]["id"])
    ]
