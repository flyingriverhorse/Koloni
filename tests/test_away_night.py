"""The night on Ready for you (karar defteri, Part B; §3.4): each job of a night that ended, in its
report, with when its turns of the night began and ended, the decisions in its chat that night and
what KOLONİ's checks did not do - from the records alone: a time no record holds is None, and so is
what was not checked where no Checked note says."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event

from app import away_night, decisions, injection, proof, raw
from app.agent.kinds_mixin import NOT_REACHED
from app.agent.proof_mixin import AWAY_GUESS
from app.agent.try_mixin import NO_DEV, NOT_TRIED
from app.db.away_models import Parked
from app.db.models import Agent, AwayRun, BacklogTask, Merge, Message, Question, Run
from tests.test_decisions import chat
from tests.test_team import SECRET

T0 = datetime(2026, 11, 24, 2, 0, tzinfo=UTC)


def at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def same_time(said: str | None, when: datetime | None) -> bool:
    return (said is None) == (when is None) and (
        said is None or datetime.fromisoformat(said).astimezone(UTC) == when
    )


def turn(session, cid, created, ended=None, started=True):
    run = Run(
        conversation_id=cid,
        status="completed" if ended else "running",
        created_at=at(created),
        started_at=at(created) if started else None,
        ended_at=None if ended is None else at(ended),
    )
    session.add(run)
    session.flush()
    return run


def answered(session, run, minute, question="Which database?"):
    lead = Agent(run_id=run.id, role_name="Lead", name="Lead", tools=[], status="completed")
    session.add(lead)
    session.flush()
    one = Question(
        run_id=run.id,
        agent_id=lead.id,
        question=question,
        options=["SQLite", "Postgres"],
        status="answered",
        answer="SQLite",
        created_at=at(minute),
        answered_at=at(minute),
        lead_why="the tests make one",
    )
    session.add(one)
    return one


def checked(session, cid, run, rows):
    session.add(
        Message(
            conversation_id=cid,
            run_id=run.id,
            role="checked",
            content="",
            blocks={"rows": rows},
        )
    )


def row(kind, state, text, guessed=False):
    return proof.row(kind, state, text, guessed=guessed)


# A Checked note's rows as KOLONİ writes them (`proof.row`, its own sentences): what was not done...
GUESSED = proof.NOT_RUN.format(why=AWAY_GUESS)
UNCHECKED = [
    row("tests", "not_run", GUESSED, guessed=True),
    row("tests", "not_run", proof.NO_COMMAND),
    row("kinds", "not_run", NOT_REACHED.format(kinds="ui")),
    row("try", "note", NOT_TRIED.format(why=NO_DEV)),
    row("tests", "note", proof.TESTS_OFF),
    row("not_checked", "note", proof.NOT_CHECKED),
]
# ...and what was, or says what was found: no row of Not checked.
CHECKED = [
    row("review", "passed", "Reviewer: no findings"),
    row("tests", "passed", "Tests passed: pytest - 3 passed"),
    row("tests", "note", proof.NO_TESTS_ROW),
    row("try", "passed", "Tried live: the page opened"),
]


def night(client, tmp_path, status="ended"):
    """A night of three jobs - one done, one whose turn is still open, one never started - and the
    evening's chat it was gone from: (pid, the ids by name)."""
    pid, evening = chat(client, tmp_path / "a")
    one = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    two = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    with client.app.state.session_factory() as session:
        card = AwayRun(
            project_id=pid,
            conversation_id=evening,
            run_id="r",
            status=status,
            started_at=at(0),
            ended_at=at(240) if status == "ended" else None,
        )
        session.add(card)
        session.flush()

        def task(title, cid, state, position):
            made = BacklogTask(
                project_id=pid,
                title=title,
                status="doing",
                position=position,
                created_by="user",
                conversation_id=cid,
                away_run_id=card.id,
                away_state=state,
            )
            session.add(made)
            session.flush()
            return made

        done = task("Fix the login", one, "done", 0)
        open_ = task("Docs pass", two, None, 1)
        never = task("Clean fixtures", None, None, 2)
        card.jobs = [
            {"title": t.title, "task_id": t.id, "was_todo": True} for t in (done, open_, never)
        ]
        turn(session, one, -60, -30)  # (before the night: not its)
        first = turn(session, one, 10, 60)
        second = turn(session, one, 70, 90)
        turn(session, one, 300, 310)  # (a turn of its chat in the morning: not the night's)
        asked = answered(session, first, 30)
        # (the evening's chat: a decision of the night on no job)
        gone_from = turn(session, evening, 5, 6)
        elsewhere = answered(session, gone_from, 6, "Which branch?")
        checked(
            session,
            one,
            first,
            [row("tests", "not_run", "Tests not run: an older note", guessed=True)],
        )
        checked(
            session,
            one,
            second,
            [*CHECKED[:2], *UNCHECKED, *CHECKED[2:]],
        )
        session.add(
            Parked(
                away_run_id=card.id,
                task_id=done.id,
                seq=1,
                kind="push",
                what="Push koloni/fix-login",
                data={},
                decision="run",
                result="Pushed koloni/fix-login to origin as abc1234",
            )
        )
        turn(session, two, 100)  # (still open: no end)
        session.commit()
        return pid, {
            "first": first.id,
            "asked": asked.id,
            "elsewhere": elsewhere.id,
            "one": one,
            "two": two,
        }


def jobs(client, pid):
    got = client.get(f"/api/projects/{pid}/away")
    assert got.status_code == 200, got.text
    return {job["title"]: job for job in got.json()["jobs"]}


def test_each_job_says_when_its_night_began_and_ended_from_its_turns_alone(client, tmp_path):
    pid, _ids = night(client, tmp_path)
    found = jobs(client, pid)
    done, still, never = found["Fix the login"], found["Docs pass"], found["Clean fixtures"]
    # The first turn of the night's start, the last's end - not the night's own times, nor turns
    # before or after it.
    assert same_time(done["started_at"], at(10)) and same_time(done["ended_at"], at(90))
    # A turn still open: its start, and no end.
    assert same_time(still["started_at"], at(100)) and still["ended_at"] is None
    # Never started: nothing - but the job is still there.
    assert (never["started_at"], never["ended_at"], never["decisions"]) == (None, None, [])
    assert never["not_checked"] is None


def test_the_nights_decisions_go_on_their_jobs_lane_by_its_chat(client, tmp_path):
    pid, ids = night(client, tmp_path)
    found = jobs(client, pid)
    assert [one["id"] for one in found["Fix the login"]["decisions"]] == [f"answer:{ids['asked']}"]
    # (the evening chat's: on no job's lane)
    lanes = [one["id"] for job in found.values() for one in job["decisions"]]
    assert f"answer:{ids['elsewhere']}" not in lanes
    (decision,) = found["Fix the login"]["decisions"]
    assert (decision["who"], decision["seen"], decision["quote"]) == (
        "orchestrator",
        False,
        "Which database?",
    )
    # (what undoes it is not asked here: the strip shows none - Ready's log says it)
    assert (decision["undo"], decision["undo_reason"]) == ("none", None)


def test_not_checked_is_read_from_the_last_checked_note_by_kind_and_state(client, tmp_path):
    pid, _ids = night(client, tmp_path)
    found = jobs(client, pid)
    assert found["Fix the login"]["not_checked"] == [
        *(one["text"] for one in UNCHECKED),
        away_night.GITHUB,  # (its push went: GitHub's checks were not waited for)
    ]
    assert GUESSED == "Tests not run: a guessed command, you were away"
    # No Checked note of the night: not known, never "nothing".
    assert found["Docs pass"]["not_checked"] is None


def test_a_night_still_at_work_draws_nothing_yet(client, tmp_path):
    pid, _ids = night(client, tmp_path, status="running")
    for job in jobs(client, pid).values():
        assert (job["started_at"], job["ended_at"], job["decisions"], job["not_checked"]) == (
            None,
            None,
            [],
            None,
        )


def test_a_checked_note_with_nothing_skipped_is_an_empty_list(client, tmp_path):
    pid, ids = night(client, tmp_path)
    with client.app.state.session_factory() as session:
        two = ids["two"]
        open_turn = session.query(Run).filter(Run.conversation_id == two).one()
        open_turn.ended_at, open_turn.status = at(120), "completed"
        checked(session, two, open_turn, [row("tests", "passed", "Tests passed: pytest")])
        session.commit()
    still = jobs(client, pid)["Docs pass"]
    assert still["not_checked"] == [] and same_time(still["ended_at"], at(120))


def nights_of_answers(client, root, answers, nights=3):
    """A chat whose job worked `nights` nights, each with `answers` cards the Orchestrator answered
    for the user, its agent finished, and a kept copy whose files hold diffs: (pid, cid)."""
    root.mkdir(parents=True, exist_ok=True)
    pid, evening = chat(client, root / "a")
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    files = [
        {"path": f"f{i}.py", "kind": "modified", "state": "refused", "diff": "+x" * 50}
        for i in range(20)
    ]
    with client.app.state.session_factory() as session:
        for n in range(nights):
            base = n * 1440
            card = AwayRun(
                project_id=pid,
                conversation_id=cid if n else evening,
                run_id="r",
                status="ended",
                started_at=at(base),
                ended_at=at(base + 600),
            )
            session.add(card)
            session.flush()
            task = BacklogTask(
                project_id=pid,
                title=f"job {n}",
                status="doing",
                position=n,
                created_by="user",
                conversation_id=cid,
                away_run_id=card.id,
                away_state="done",
            )
            session.add(task)
            session.flush()
            card.jobs = [{"title": task.title, "task_id": task.id, "was_todo": True}]
            run = turn(session, cid, base + 10, base + 500)
            for q in range(answers):
                answered(session, run, base + 20 + q, f"q{q}?")
            lead = session.query(Agent).filter(Agent.run_id == run.id).first()
            session.add(
                Merge(
                    run_id=run.id,
                    agent_id=lead.id,
                    status="interrupted",
                    files=files,
                    kept_in=f"C:/kept/{n}",
                )
            )
        session.commit()
    return pid, cid


def test_a_report_asks_nothing_of_what_undoes_its_decisions(client, tmp_path, monkeypatch):
    # (The review's M1: every night of a chat is reported after each decision of the morning; its
    # answers' Change and redo read each chat's work - 9.7 s for 30 nights of 10 answers.)
    asked = []
    real = decisions.work
    monkeypatch.setattr(decisions, "work", lambda *one: asked.append(one) or real(*one))
    engine = client.app.state.session_factory.kw["bind"]

    def queries(url: str) -> int:
        count = [0]

        def one(*_args, **_kw):
            count[0] += 1

        event.listen(engine, "before_cursor_execute", one)
        try:
            got = client.get(url)
        finally:
            event.remove(engine, "before_cursor_execute", one)
        assert got.status_code == 200, got.text
        return count[0]

    few, cid_few = nights_of_answers(client, tmp_path / "few", answers=1)
    many, cid_many = nights_of_answers(client, tmp_path / "many", answers=10)
    for cid in (cid_few, cid_many):
        assert all(
            len(job["decisions"])
            for one in client.get(f"/api/conversations/{cid}/away").json()
            for job in one["jobs"]
        )
    assert asked == []
    # No query an answer more: ten answers a night read as one does.
    assert queries(f"/api/conversations/{cid_many}/away") == queries(
        f"/api/conversations/{cid_few}/away"
    )
    assert queries(f"/api/projects/{many}/away") == queries(f"/api/projects/{few}/away")
    # (Ready's log still asks it: its rows' Change and redo.)
    client.get(f"/api/projects/{many}/decisions", params={"unseen": "true"})
    assert asked


def test_a_parked_line_is_shown_and_copied_masked(client, tmp_path, monkeypatch):
    # (The review's M2: the night's Copy as Markdown copies what the page shows of a parked line.)
    monkeypatch.setattr(raw, "_known", lambda fresh=False: raw.spellings([SECRET]))
    pid, _ids = night(client, tmp_path)
    away_id = client.get(f"/api/projects/{pid}/away").json()["id"]
    line = (
        'curl -H "Authorization: Bearer ghp_abcdefghijklmnopqrstuvwxyz0123456789" '
        f"https://user:hunter2@example.com/x --data {SECRET}"
    )
    with client.app.state.session_factory() as session:
        task_id = session.query(Parked).filter(Parked.away_run_id == away_id).one().task_id
        session.add(
            Parked(away_run_id=away_id, task_id=task_id, seq=2, kind="command", what=line, data={})
        )
        session.commit()
    rows = client.get(f"/api/away/{away_id}/waiting").json()
    (command,) = [one for one in rows if one["kind"] == "command"]
    assert command["what"] == line  # (whole: what runs, as recorded)
    shown = command["what_shown"]
    for secret in ("ghp_abcdefghijklmnopqrstuvwxyz0123456789", "hunter2", SECRET):
        assert secret not in shown, shown
    assert shown.startswith('curl -H "Authorization: ') and raw.HIDDEN in shown
    (push,) = [one for one in rows if one["kind"] == "push"]
    assert push["opens_pr"] is False  # (the project's way is no pull request)


@pytest.mark.parametrize(
    "unseen",
    [
        "\N{ZERO WIDTH SPACE}",
        "\N{SOFT HYPHEN}",
        "\N{LEFT-TO-RIGHT ISOLATE}",
        "\N{HANGUL FILLER}",
    ],
)
def test_a_secret_split_by_what_nobody_sees_is_masked_and_warned(
    client, tmp_path, monkeypatch, unseen
):
    # (A secret KOLONİ knows, split by a character nobody sees, is one again before the mask - on
    # the page and in the night's Markdown; what runs keeps the line as recorded, and the row warns.)
    monkeypatch.setattr(raw, "_known", lambda fresh=False: raw.spellings([SECRET]))
    pid, _ids = night(client, tmp_path)
    away_id = client.get(f"/api/projects/{pid}/away").json()["id"]
    line = f"deploy --key {SECRET[:6]}{unseen}{SECRET[6:]} --now"
    with client.app.state.session_factory() as session:
        task_id = session.query(Parked).filter(Parked.away_run_id == away_id).one().task_id
        session.add(
            Parked(away_run_id=away_id, task_id=task_id, seq=2, kind="command", what=line, data={})
        )
        session.commit()
    (command,) = [
        one for one in client.get(f"/api/away/{away_id}/waiting").json() if one["kind"] == "command"
    ]
    assert command["what"] == line
    assert command["what_shown"] == f"deploy --key {raw.HIDDEN} --now", ascii(command["what_shown"])
    assert command["warn"] == injection.NOTE
    # (a line with nothing unseen in it: no warning of that)
    assert decisions.shown("npm  test\n--watch") == ("npm  test\n--watch", False)  # (not folded)
