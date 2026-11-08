"""What was said in a project's earlier turns: what goes into the index, what a search
finds there, and how it is shown (slice 22a; the acceptance set is test_recall_scenarios)."""

import asyncio
import sqlite3
from datetime import UTC, datetime

import pytest
from alembic import command as alembic

from app import earlier
from app import memory as kept
from app.db.models import (
    Agent,
    BacklogTask,
    BoardPost,
    Command,
    Conversation,
    Discussion,
    DiscussionMember,
    DiscussionPost,
    Merge,
    Message,
    Project,
    Run,
    ToolCall,
)
from app.db.session import make_engine, make_session_factory, upgrade_db
from tests.test_chat_flow import text
from tests.test_migration_0002 import _config
from tests.test_recall_scenarios import ORIGIN, project, recalled, turn
from tests.test_spawn import call, step

AT = datetime(2026, 10, 13, 10, 0, tzinfo=UTC)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "said.db"
    upgrade_db(path)
    engine = make_engine(path)
    yield make_session_factory(engine)
    engine.dispose()


def a_turn(session, said, answer="ok", rid="r", cid="c", pid="p", status="completed",
           started=AT, ended=AT, role="user"):
    """A turn on record, as rows: its message, its lead and the lead's answer."""
    if session.get(Project, pid) is None:
        session.add(Project(id=pid, name=pid, root_path=f"C:/{pid}"))
    if session.get(Conversation, cid) is None:
        session.add(Conversation(id=cid, project_id=pid, title=f"About {cid}"))
    session.add(Run(id=rid, conversation_id=cid, status=status, started_at=started, ended_at=ended))
    session.flush()
    lead = Agent(id=f"lead-{rid}", run_id=rid, role_name="Lead", name="Lead", tools=[], depth=0,
                 status=status)
    session.add(lead)
    session.flush()
    session.add(Message(conversation_id=cid, run_id=rid, role=role, content=said, created_at=AT))
    if answer:
        session.add(Message(id=f"answer-{rid}", conversation_id=cid, run_id=rid, agent_id=lead.id,
                            role="assistant", content=answer, created_at=AT))
    session.commit()
    return lead


def indexed(session, rid="r"):
    earlier.index_run(session, rid)
    session.commit()
    return [(row.agent, row.said) for row in session.execute(
        earlier.text("SELECT agent, said FROM said_in_turns WHERE run_id = :run"), {"run": rid})]


def find(session, query, pid="p"):
    return [said.excerpt for said in earlier.found(session, pid, query)]


# --- what goes in, and what does not ----------------------------------------------------------


def test_only_what_somebody_said_goes_in(db):
    with db() as session:
        lead = a_turn(session, "USER-WORD please look", answer="LEAD-ANSWER it is done")
        # what the lead said along the way is not its answer
        session.add(Message(id="interim", conversation_id="c", run_id="r", agent_id=lead.id,
                            role="assistant", content="LEAD-INTERIM let me look",
                            created_at=datetime(2026, 10, 13, 9, 0, tzinfo=UTC)))
        coder = Agent(id="coder", run_id="r", role_name="Coder", name="Coder 2", tools=[],
                      depth=1, status="completed", report="CODER-REPORT I looked", ended_at=AT)
        quiet = Agent(id="quiet", run_id="r", role_name="Coder", name="Coder 3", tools=[],
                      depth=1, status="failed", report=None)
        session.add_all([coder, quiet])
        session.flush()
        # what tools returned, in every shape it is kept in
        for seq, (name, result) in enumerate([
            ("read_file", "TOOL-RESULT a file said this"),
            ("web_search", "WEB-RESULT a page said this"),
            ("http_request", "HTTP-RESULT a server said this"),
            ("recall", "RECALL-RESULT memory said this"),
        ]):
            session.add(ToolCall(id=f"t{seq}", run_id="r", agent_id=lead.id, message_id="interim",
                                 seq=seq, provider_call_id=f"p{seq}", name=name,
                                 arguments='{"ARGUMENT-WORD": 1}', status="succeeded",
                                 result=result))
        session.flush()
        session.add(Command(run_id="r", agent_id=lead.id, tool_call_id="t0", command="COMMAND-LINE",
                            location="host", output="COMMAND-PRINTED this", timeout_seconds=5))
        # a message from one agent to another, a note on the notebook, a word from memory
        session.add(Message(conversation_id="c", run_id="r", agent_id=coder.id, role="agent",
                            from_agent_id=lead.id, content="AGENT-MESSAGE to the coder"))
        session.add(Message(conversation_id="c", run_id="r", agent_id=lead.id, role="memory",
                            content="MEMORY-WORD no longer stands"))
        session.add(BoardPost(run_id="r", conversation_id="c", agent_id=coder.id,
                              content="BOARD-NOTE on the notebook", seq=1))
        session.commit()
        assert indexed(session) == [
            (None, "USER-WORD please look"), ("Lead", "LEAD-ANSWER it is done"),
            ("Coder 2", "CODER-REPORT I looked"),
        ]
        for word in ("INTERIM", "TOOL", "WEB", "HTTP", "RECALL", "ARGUMENT", "COMMAND",
                     "AGENT-MESSAGE", "MEMORY-WORD", "BOARD"):
            assert find(session, word) == [], word


def test_what_was_said_in_a_discussion_does_not_go_in(db):
    with db() as session:
        lead = a_turn(session, "talk it over", answer="We agreed on the plan.")
        guest = Agent(id="guest", run_id="r", role_name="Reviewer", name="Reviewer", tools=[],
                      depth=1, status="completed", report="GUEST-LAST-WORD I agree", ended_at=AT)
        coder = Agent(id="coder", run_id="r", role_name="Coder", name="Coder", tools=[],
                      depth=1, status="completed", report="CODER-REPORT built it", ended_at=AT)
        session.add_all([guest, coder])
        session.add(Discussion(id="d", run_id="r", agent_id=lead.id, tool_call_id="t",
                               topic="TOPIC-WORD", max_rounds=2))
        session.flush()
        # opened for the discussion: what it said there last is on its record as its report
        session.add(DiscussionMember(discussion_id="d", agent_id="guest", position=1,
                                     opened_here=True))
        # in the discussion too, but opened for a job: its report is its own
        session.add(DiscussionMember(discussion_id="d", agent_id="coder", position=2))
        session.add(DiscussionPost(discussion_id="d", agent_id="guest", round=1,
                                   content="POST-WORD here is my view"))
        session.add(Message(conversation_id="c", run_id="r", agent_id=lead.id, role="assistant",
                            discussion_id="d", content="SPOKEN-WORD in the discussion",
                            created_at=datetime(2026, 10, 14, tzinfo=UTC)))
        session.commit()
        assert indexed(session) == [
            (None, "talk it over"), ("Lead", "We agreed on the plan."),
            ("Coder", "CODER-REPORT built it"),
        ]


def test_a_triggers_message_is_not_the_users_word(db):
    with db() as session:
        a_turn(session, "TRIGGER-MESSAGE every morning", answer="LEAD-FOUND nothing new",
               role="trigger")
        assert indexed(session) == [("Lead", "LEAD-FOUND nothing new")]


def test_a_long_message_is_kept_only_so_far(db):
    with db() as session:
        a_turn(session, "start " + "x " * earlier.MAX_SAID + "NEVER-INDEXED", answer="")
        ((who, said),) = indexed(session)
        assert who is None and len(said) == earlier.MAX_SAID
        assert find(session, "NEVER-INDEXED") == []


# --- the turns that were there already ---------------------------------------------------------


def test_the_turns_that_are_over_and_not_in_the_index_are_the_missing_ones(db):
    with db() as session:
        a_turn(session, "INDEXED already", rid="done")
        earlier.index_run(session, "done")
        a_turn(session, "OLDER turn", rid="older", started=datetime(2026, 10, 1, tzinfo=UTC))
        a_turn(session, "INTERRUPTED turn", rid="cut", status="interrupted", answer="")
        a_turn(session, "RUNNING turn", rid="running", status="running", ended=None)
        a_turn(session, "NEVER started", rid="never", status="cancelled", started=None)
        # nothing was said in it that goes in: it is looked at once, and found by nobody
        a_turn(session, "a trigger's", rid="silent", role="trigger", answer="")
        assert set(earlier.missing(session)) == {"older", "cut", "silent"}
    asyncio.run(earlier.index_what_is_there(db))
    asyncio.run(earlier.index_what_is_there(db))  # a second time: nothing is there twice
    with db() as session:
        assert find(session, "older") == ["OLDER turn"]
        assert find(session, "interrupted") == ["INTERRUPTED turn"]
        assert find(session, "running") == [] and find(session, "never started") == []
        assert sorted(find(session, "turn")) == ["INTERRUPTED turn", "OLDER turn"]
        assert earlier.missing(session) == []
        assert session.execute(earlier.text(
            "SELECT count(*) FROM said_in_turns WHERE run_id = 'silent'")).scalar_one() == 1


def test_one_turn_that_cannot_be_indexed_does_not_stop_the_others(db, monkeypatch):
    with db() as session:
        for n in range(3):
            a_turn(session, f"BATCHED word{n}", rid=f"r{n}", answer="")
    real = earlier.index_run

    def index_run(session, run_id):
        real(session, run_id)
        if run_id == "r1":
            raise RuntimeError("a turn that cannot be read")

    monkeypatch.setattr(earlier, "index_run", index_run)
    asyncio.run(earlier.index_what_is_there(db))
    with db() as session:
        assert sorted(find(session, "batched")) == ["BATCHED word0", "BATCHED word2"]
        assert earlier.missing(session) == ["r1"]  # left for the next start, as it was


def test_many_turns_are_indexed_a_batch_at_a_time(db, monkeypatch):
    monkeypatch.setattr(earlier, "BATCH", 2)
    with db() as session:
        for n in range(5):
            a_turn(session, f"BATCHED word{n}", rid=f"r{n}", answer="")
    between = []
    real = asyncio.sleep

    async def sleep(seconds):
        with db() as session:  # what is indexed so far is found meanwhile
            between.append(len(find(session, "batched")))
        await real(seconds)

    monkeypatch.setattr(earlier.asyncio, "sleep", sleep)
    asyncio.run(earlier.index_what_is_there(db))
    assert between == [2, 4, 5]  # others go on between two batches


def test_the_index_is_brought_up_to_date_when_the_app_starts(make_client, wait_run, project_dir):
    client, _model = make_client({"Lead": [text("The BEFORE-THE-SLICE answer.")]})
    client.headers["Origin"] = ORIGIN
    pid = project(client, project_dir)
    turn(client, wait_run, pid, "something said before there was an index")
    factory = client.app.state.session_factory
    with factory() as session:  # as a database from before the slice is: turns, no index
        session.execute(earlier.text("DELETE FROM said_in_turns"))
        session.commit()
    assert client.get(f"/api/projects/{pid}/memory/search", params={"q": "index"}).json()[
        "turns"] == []
    again, _model = make_client([])
    found = again.get(f"/api/projects/{pid}/memory/search", params={"q": "before-the-slice"})
    assert [(said["who"], said["excerpt"]) for said in found.json()["turns"]] == [
        ("Lead", "The BEFORE-THE-SLICE answer.")]


# --- a backlog task the user closed (G8.1) ---------------------------------------------------


def a_task(session, title, detail=None, status="done", tid="t", cid="c", pid="p"):
    if session.get(Project, pid) is None:
        session.add(Project(id=pid, name=pid, root_path=f"C:/{pid}"))
    if cid and session.get(Conversation, cid) is None:
        session.add(Conversation(id=cid, project_id=pid, title=f"About {cid}"))
    session.flush()
    task = BacklogTask(id=tid, project_id=pid, title=title, detail=detail, status=status,
                       position=0, conversation_id=cid, created_by="user")
    session.add(task)
    session.flush()
    return task


def test_a_task_the_user_closed_is_found_by_its_title_and_its_detail(db):
    with db() as session:
        done = a_task(session, "Fix the LEDGER-TITLE", detail="it closed at DETAIL-MIDNIGHT")
        earlier.index_task(session, done, AT)
        earlier.index_task(session, a_task(session, "an OPEN-TITLE", status="todo", tid="o"), AT)
        session.commit()
        line = ('- "Fix the LEDGER-TITLE — it closed at DETAIL-MIDNIGHT" (a backlog task '
                'closed by the user, "You", in the conversation "About c" on 2026-10-13)')
        assert earlier.told(session, "p", "ledger-title") == f"{earlier.HEAD}\n{line}"
        assert earlier.told(session, "p", "detail-midnight") == f"{earlier.HEAD}\n{line}"
        assert earlier.told(session, "p", "open-title") == earlier.NOTHING
        # edited while done: indexed once more, as of the moment it was closed
        done.detail = "EDITED-DETAIL"
        earlier.index_task(session, done, datetime(2026, 10, 20, tzinfo=UTC))
        assert find(session, "detail-midnight") == []
        assert find(session, "edited-detail") == ["Fix the LEDGER-TITLE — EDITED-DETAIL"]
        assert earlier.found(session, "p", "edited-detail")[0].at == AT
        # opened again: it is no finished work; closed again: of this moment
        done.status = "todo"
        earlier.index_task(session, done, AT)
        assert find(session, "ledger-title") == []
        done.status = "done"
        earlier.index_task(session, done, datetime(2026, 10, 20, tzinfo=UTC))
        (again,) = earlier.found(session, "p", "ledger-title")
        assert again.at == datetime(2026, 10, 20, tzinfo=UTC) and again.kind == "task"
        assert session.execute(earlier.text(
            "SELECT count(*) FROM said_in_turns WHERE run_id = 'task:t'")).scalar_one() == 1


def test_a_task_closed_before_there_was_an_index_is_indexed_when_the_app_starts(db):
    with db() as session:
        a_task(session, "OLD-TASK of no chat", cid=None)
        a_task(session, "an OPEN-TASK", status="todo", tid="o")
        indexed_ = a_task(session, "INDEXED-TASK", tid="i")
        earlier.index_task(session, indexed_, AT)
        session.commit()
        assert earlier.missing_tasks(session) == ["t"]
    asyncio.run(earlier.index_what_is_there(db))
    asyncio.run(earlier.index_what_is_there(db))  # a second time: nothing is there twice
    with db() as session:
        assert earlier.missing_tasks(session) == []
        assert find(session, "open-task") == []
        # when it was closed is not on record, and not made up
        assert earlier.told(session, "p", "old-task") == earlier.HEAD + (
            '\n- "OLD-TASK of no chat" (a backlog task closed by the user, "You", on a day not '
            "on record)")


def test_a_task_is_in_the_index_while_it_is_done_and_the_user_sees_it_on_the_memory_page(
    client, project_dir
):
    client.headers["Origin"] = ORIGIN
    pid = project(client, project_dir)
    task = client.post(f"/api/projects/{pid}/backlog", json={
        "title": "Fix the CLOSED-TITLE", "detail": "the CLOSED-DETAIL"}).json()["id"]
    sought = f"/api/projects/{pid}/memory/search"
    assert client.get(sought, params={"q": "closed-detail"}).json()["turns"] == []
    client.patch(f"/api/backlog/{task}", json={"status": "done"})
    (said,) = client.get(sought, params={"q": "closed-detail"}).json()["turns"]
    assert (said["who"], said["excerpt"], said["run_id"], said["conversation_id"]) == (
        "You", "Fix the CLOSED-TITLE — the CLOSED-DETAIL", f"task:{task}", None)
    # B-329: the page tells a task and a trigger's turn apart by these, not by the id
    assert (said["kind"], said["trigger"]) == ("task", False)
    assert said["at"] is not None
    client.patch(f"/api/backlog/{task}", json={"status": "todo"})
    assert client.get(sought, params={"q": "closed-detail"}).json()["turns"] == []
    client.patch(f"/api/backlog/{task}", json={"status": "done"})
    assert len(client.get(sought, params={"q": "closed-title"}).json()["turns"]) == 1
    client.delete(f"/api/backlog/{task}")
    assert client.get(sought, params={"q": "closed-title"}).json()["turns"] == []


# --- what a search finds ----------------------------------------------------------------------


def test_a_triggers_turn_stands_below_the_users_of_the_same_rank(db):
    with db() as session:
        # the same words, so the index ranks them alike: the trigger's turn is listed last
        a_turn(session, "", answer="The NIGHTLY-WORD build is green.", rid="unwatched",
               role="trigger")
        session.get(Run, "unwatched").unattended = True
        a_turn(session, "", answer="The NIGHTLY-WORD build is green.", rid="watched")
        session.commit()
        indexed(session, "unwatched")
        indexed(session, "watched")
        assert [(said.run_id, said.trigger) for said in earlier.found(session, "p", "nightly-word")
                ] == [("watched", False), ("unwatched", True)]
        _head, first, second = earlier.told(session, "p", "nightly-word").splitlines()
        assert first.endswith('"About c" on 2026-10-13)')
        assert second.endswith('"About c" on 2026-10-13, in a trigger\'s turn)')


def test_a_report_of_work_that_did_not_work_stands_above_an_ordinary_one(db):
    with db() as session:
        # (The turned-down one's words match a little worse: first by its record, not its rank.)
        for rid, report in (("plain", "The SLOWLOADER fix is in."),
                            ("down", "The SLOWLOADER fix is out now.")):
            a_turn(session, "", answer="", rid=rid)
            session.add(Agent(id=f"coder-{rid}", run_id=rid, role_name="Coder", name="Coder",
                              tools=[], depth=1, status="completed", report=report))
        session.add(Merge(run_id="down", agent_id="coder-down", status="rejected", files=[]))
        session.commit()
        indexed(session, "plain")
        indexed(session, "down")
        assert [(said.run_id, said.tried) for said in earlier.found(session, "p", "slowloader")
                ] == [("down", True), ("plain", False)]
        _head, first, _second = earlier.told(session, "p", "slowloader").splitlines()
        assert first.endswith(f"; {earlier.TRIED})")


def test_a_path_with_its_line_is_not_cut_in_two(db):
    filler = "lorem ipsum dolor sit amet " * 200
    with db() as session:
        # the path stands where the excerpt's end would fall: 450 characters past the word
        tail = "x " * 208 + "see app/tools/ledger.py:4242 there"
        a_turn(session, f"{filler}the CUT-MARK stands here {tail} {filler}", answer="")
        session.commit()
        indexed(session)
        (excerpt,) = find(session, "cut-mark")
        assert "app/tools/ledger.py:4242" in excerpt and excerpt.endswith(":4242 …")


def test_how_many_of_the_words_a_question_has_decide_what_speaks_to_it(db):
    with db() as session:
        a_turn(session, "The deploy password rotation happens every Tuesday.", answer="")
        indexed(session)
        for query, finds in [
            ("rotation", True),                                   # one word: it
            ("password rotation", True),                          # two: both
            ("password unicorn", False),
            ("what did the user say about password rotation", True),   # longer: two, and half
            ("zebra unicorn password", False),                    # one of three is not enough
            ("pass rot", True),                                   # a word begins with it
            ("assword", False),                                   # not: is somewhere in it
            ("the and of", False),                                # words that say nothing
            ("", False),
        ]:
            assert bool(find(session, query)) is finds, query


def test_a_file_ending_alone_finds_nothing(db):
    with db() as session:
        a_turn(session, "The cart is in cart.py and the parser in lexer.py.", answer="")
        indexed(session)
        assert find(session, "py") == [] and find(session, "payment.py") == []
        assert len(find(session, "lexer.py")) == 1


def test_a_report_that_names_a_file_by_its_path_is_found_by_the_files_name(db):
    """A handoff report says "core/etl.py"; the next agent asks for "etl.py" (93-C5). The
    index's tokenizer splits on "/" and "." as `_words` does."""
    with db() as session:
        a_turn(session, "Left: the logger call in core/etl.py still prints.", answer="")
        indexed(session)
        assert len(find(session, "etl.py")) == 1 and len(find(session, "core/etl.py")) == 1
        assert find(session, "etl") == find(session, "etl.py")


def test_an_excerpt_stands_around_a_word_asked_for_not_around_a_file_ending(db):
    filler = "lorem ipsum dolor sit amet " * 60
    with db() as session:
        a_turn(session, f"setup.py comes first. {filler} The LEXER-MARK is here. {filler}",
               answer="")
        indexed(session)
        (excerpt,) = find(session, "lexer-mark.py")
        assert "The LEXER-MARK is here." in excerpt and "setup.py" not in excerpt


def test_a_word_that_says_nothing_says_nothing_however_it_is_spelled(db):
    with db() as session:
        a_turn(session, "Sepet icin indirim uygulanir.", answer="")
        indexed(session)
        # "için" without its marks is still a word that says nothing: one word is left
        assert len(find(session, "icin indirim")) == 1
        assert len(find(session, "için indirim")) == 1
        assert find(session, "icin") == []


@pytest.mark.parametrize("said, asked", [
    ("Sunucuyu ÇALIŞTIR ve ışığı aç.", "calistir isigi"),
    ("calistir isigi", "ÇALIŞTIR IŞIĞI"),
    ("İstanbul ofisi kapandı", "istanbul KAPANDI"),
    ("istanbul ofisi kapandi", "İSTANBUL kapandı"),
    ("Öğrenci sayısı üç yüz oldu", "ogrenci sayisi uc yuz"),
    ("the tool_calls rows carry parent_call_id", "TOOL_CALLS parent_call"),
    ("Straße und Café", "strasse cafe"),
    ("cafe\u0301 nai\u0308ve", "caf\u00e9 na\u00efve"),             # a letter in two parts
])
def test_capitals_and_marks_on_letters_do_not_hide_a_word(db, said, asked):
    with db() as session:
        a_turn(session, said, answer="")
        indexed(session)
        assert len(find(session, asked)) == 1


HALF = chr(0xD83D)  # half a character: no text can carry it
ODD = [
    '"', '""', '"unbalanced', "*", "-", "-rotation", ":", "(", ")", "((", "NEAR", "NEAR(a b, 2)",
    "AND", "OR", "NOT", "password AND", "password OR OR rotation", "words:password", "^password",
    "password*", "{password}", "a+b", chr(92), "'", "';DROP TABLE said_in_turns;--", "%", "_",
    chr(0), HALF, "🙂 password", chr(0x200B), " ", "\n\n", "password " * 2000, "x" * 100_000,
    "ı", "İ", "ǆ", "½", "㎏",
]


def test_no_query_is_read_as_the_indexs_own_syntax(db):
    with db() as session:
        a_turn(session, "The deploy password rotation happens every Tuesday.", answer="")
        indexed(session)
        for query in ODD:  # none of them raises, and none finds what it does not name
            if earlier.found(session, "p", query):
                assert "password" in query or "rotation" in query, query
            assert earlier.told(session, "p", query)
        assert find(session, "password " * 2000) == [
            "The deploy password rotation happens every Tuesday."]
        assert session.execute(earlier.text("SELECT count(*) FROM said_in_turns")).scalar_one() == 1


def test_the_search_of_the_memory_page_takes_any_words(make_client, wait_run, project_dir):
    client, _model = make_client({"Lead": [text("ok")]})
    client.headers["Origin"] = ORIGIN
    pid = project(client, project_dir)
    turn(client, wait_run, pid, "The deploy password rotation happens every Tuesday.")
    for query in ODD:
        if query == HALF or len(query) > 50_000:
            continue  # (nor an address that long)
        got = client.get(f"/api/projects/{pid}/memory/search", params={"q": query})
        assert got.status_code == 200, query
        assert got.json()["memory"] == [], query
        if got.json()["turns"]:
            assert "password" in query or "rotation" in query, query
    assert client.get(f"/api/projects/{pid}/memory/search").json() == {
        "memory": [], "turns": [], "meaning_off": None}
    assert client.get("/api/projects/nobody/memory/search", params={"q": "x"}).status_code == 404


def test_at_most_five_are_found_the_best_first(db):
    with db() as session:
        for n in range(8):
            a_turn(session, f"the ledger was mentioned in passing, time {n}, among many other "
                            "words that say nothing about it at all", rid=f"r{n}", answer="")
        a_turn(session, "ledger balance: the ledger balance is kept by the ledger", rid="best",
               answer="")
        for rid in [*(f"r{n}" for n in range(8)), "best"]:
            earlier.index_run(session, rid)
        session.commit()
        found = earlier.found(session, "p", "ledger balance")
        assert [said.run_id for said in found] == ["best"]
        found = earlier.found(session, "p", "ledger")
        assert len(found) == earlier.MAX_FOUND == 5 and found[0].run_id == "best"


def test_another_projects_turns_are_never_found(db):
    with db() as session:
        a_turn(session, "the SHARED-WORD here", answer="", rid="mine", cid="c", pid="p")
        a_turn(session, "the SHARED-WORD there", answer="", rid="theirs", cid="c2", pid="p2")
        for rid in ("mine", "theirs"):
            earlier.index_run(session, rid)
        session.commit()
        assert find(session, "shared-word", "p") == ["the SHARED-WORD here"]
        assert find(session, "shared-word", "p2") == ["the SHARED-WORD there"]
        assert find(session, "shared-word", "nobody") == []


# --- how it is shown --------------------------------------------------------------------------


def test_a_long_text_is_cut_around_the_word_that_matched(db):
    filler = "lorem ipsum dolor sit amet " * 200
    with db() as session:
        a_turn(session, f"{filler}the MIDDLE-MARK stands here {filler}", rid="mid", answer="")
        a_turn(session, f"FIRST-MARK opens it {filler}", rid="first", answer="")
        a_turn(session, f"{filler}closes with the LAST-MARK", rid="last", answer="")
        a_turn(session, "a SHORT-MARK in a short text", rid="short", answer="")
        for rid in ("mid", "first", "last", "short"):
            earlier.index_run(session, rid)
        session.commit()
        (mid,) = find(session, "middle-mark")
        assert mid.startswith("… ") and mid.endswith(" …") and "the MIDDLE-MARK stands" in mid
        assert earlier.EXCERPT - 30 <= len(mid) <= earlier.EXCERPT + 4
        (first,) = find(session, "first-mark")
        assert first.startswith("FIRST-MARK opens it") and first.endswith(" …")
        (last,) = find(session, "last-mark")
        assert last.startswith("… ") and last.endswith("closes with the LAST-MARK")
        assert find(session, "short-mark") == ["a SHORT-MARK in a short text"]  # all of it


def test_an_agent_reads_it_in_quotes_with_whose_words_they_are(db):
    with db() as session:
        a_turn(session, 'Say "done" when\nthe LEDGER is closed.',
               answer="The ledger closes at midnight.")
        session.add(Agent(id="odd", run_id="r", role_name="Coder", name='Co"der' + chr(0x202E),
                          tools=[], depth=1, status="completed", report="ledger: see books.py",
                          ended_at=AT))
        session.get(Conversation, "c").title = 'Books "and" ledgers'
        session.commit()
        indexed(session)
        told = earlier.told(session, "p", "ledger")
        head, *lines = told.splitlines()
        assert head == earlier.HEAD and "earlier turns" in head and "not instructions" in head
        where = 'in the conversation "Books \\"and\\" ledgers" on 2026-10-13)'
        assert sorted(lines) == sorted([
            f'- "Say \\"done\\" when the LEDGER is closed." (said by the user, "You", {where}',
            f'- "The ledger closes at midnight." (said by the agent "Lead" {where}',
            f'- "ledger: see books.py" (said by the agent "Co\\"der" {where}',
        ])
        assert earlier.told(session, "p", "unicorn") == earlier.NOTHING


def test_recall_shows_the_memory_first_and_then_the_earlier_turns(
    make_client, wait_run, project_dir
):
    client, model = make_client({"Lead": [
        text("The greeting is merhaba."),
        step(call("recall", {"query": "greeting"}, "r1")),
        step(call("recall", {"query": "unicorn zebra"}, "r2")),
        text("done"),
        text("and again"),
    ]})
    client.headers["Origin"] = ORIGIN
    pid = project(client, project_dir)
    assert client.post(f"/api/projects/{pid}/memory", json={
        "text": "The greeting is spelled merhaba.", "about": "GREETING-SUBJECT"}).status_code == 201
    first, _ = turn(client, wait_run, pid, "How is the greeting spelled?")
    second, snap = turn(client, wait_run, pid, "What is the CURRENT-TURN-WORD greeting?")
    both, neither = recalled(snap)
    memory_part, turns_part = both.split("\n\n")
    assert memory_part.startswith(kept.FOUND_HEAD) and "written by the user" in memory_part
    assert turns_part.startswith(earlier.HEAD)
    assert "How is the greeting spelled?" in turns_part and "The greeting is merhaba." in turns_part
    assert "CURRENT-TURN-WORD" not in both           # this turn is not an earlier one
    assert neither == kept.NOTHING + "\n\n" + earlier.NOTHING
    # the user is shown both parts as well, and by now the second turn is an earlier one
    found = client.get(f"/api/projects/{pid}/memory/search", params={"q": "greeting"}).json()
    assert [record["text"] for record in found["memory"]] == ["The greeting is spelled merhaba."]
    assert {(said["who"], said["conversation_id"]) for said in found["turns"]} == {
        ("You", first), ("Lead", first), ("You", second)}
    assert all(said["conversation_title"] and said["run_id"] and said["at"]
               for said in found["turns"])
    # in a later turn what it looked up is not shown again: only how many records it was
    turn(client, wait_run, pid, "and now?", cid=second)
    earlier_call = next(m for m in model.calls[-1] if m.get("role") == "tool")
    assert earlier_call["content"].startswith(
        "[looked up in an earlier turn: 1 record and 2 excerpts of earlier turns.")
    assert "merhaba" not in earlier_call["content"]


def test_a_later_turn_is_told_how_many_excerpts_there_were_too():
    line = '- "x" (said by the user, "You", in the conversation "c" on 2026-10-13)'
    only_said = kept.NOTHING + "\n\n" + "\n".join([earlier.HEAD, line, line])
    assert kept.looked_up_earlier(only_said).startswith(
        "[looked up in an earlier turn: 0 records and 2 excerpts of earlier turns.")
    one = kept.NOTHING + "\n\n" + "\n".join([earlier.HEAD, line])
    assert "0 records and 1 excerpt of earlier turns." in kept.looked_up_earlier(one)
    assert kept.looked_up_earlier(kept.NOTHING + "\n\n" + earlier.NOTHING).startswith(
        "[looked up in an earlier turn: 0 records.")


# --- the migration ----------------------------------------------------------------------------


def test_migration_0040_and_back(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    alembic.upgrade(cfg, "0039")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO projects (id, name, root_path, created_at) "
                     "VALUES ('p', 'p', 'C:/p', '2026-10-13 10:00:00')")
        conn.execute("INSERT INTO memories (id, project_id, tier, text, origin, observed_at, "
                     "status, created_at) VALUES ('m', 'p', 'note', 'a note', 'agent', "
                     "'2026-10-13 10:00:00', 'active', '2026-10-13 10:00:00')")
    alembic.upgrade(cfg, "0040")
    with sqlite3.connect(db) as conn:
        # nothing is made up for what was there: nothing noted by itself, nobody's signature
        assert conn.execute("SELECT auto_notes, last_auto FROM projects").fetchall() == [(0, None)]
        assert conn.execute("SELECT noted_by FROM memories").fetchall() == [(None,)]
        # the index is there, empty, and a word of it is found by how it begins
        assert conn.execute("SELECT count(*) FROM said_in_turns").fetchone() == (0,)
        conn.execute("INSERT INTO said_in_turns (words, said, project_id) "
                     "VALUES ('tool_calls here', 'Tool_Calls here', 'p')")
        assert conn.execute("SELECT said FROM said_in_turns WHERE said_in_turns MATCH "
                            "'\"tool_c\"*'").fetchall() == [("Tool_Calls here",)]
        conn.execute("UPDATE projects SET auto_notes = 1, last_auto = '{\"noted\": 1}'")
    alembic.downgrade(cfg, "0039")
    with sqlite3.connect(db) as conn:
        names = [row[0] for row in conn.execute("SELECT name FROM sqlite_master")]
        assert not [name for name in names if name.startswith("said_in_turns")]
        columns = [row[1] for row in conn.execute("PRAGMA table_info(projects)")]
        assert "auto_notes" not in columns and "last_auto" not in columns
        assert "noted_by" not in [row[1] for row in conn.execute("PRAGMA table_info(memories)")]
        assert conn.execute("SELECT id, text FROM memories").fetchall() == [("m", "a note")]
        # the one record in effect on a subject is still held to
        assert "uq_memories_active_subject" in names
    alembic.upgrade(cfg, "head")  # and up again
