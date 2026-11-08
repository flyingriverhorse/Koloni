"""A conversation's title, beyond slice 67's acceptance set (`test_conversation_title_scenarios`):
lines that say nothing, a long word after a short head, a mark on a letter, what a cut does not
end on, the joiners inside a word - and a room's goal and a trigger's name going through it."""

import pytest

from app.topics import one_line, title_from
from tests.test_chat_flow import text
from tests.test_room_scenarios import start
from tests.test_triggers import run_now, setup, trigger

ZWSP, BOM, LRM, ZWJ, ZWNJ = "​", "﻿", "‎", "‍", "‌"
LINK = "https://example.com/" + "a" * 60


@pytest.mark.parametrize("said,title", [
    # the first line that says anything, whatever comes before it
    ("\n\n  \nfix the login", "fix the login"),
    ("fix the login\r\nthe button does nothing", "fix the login"),
    # pasted code (slice 85a): its fence's line says nothing, the code does
    ("```python\ndef greet():\n```", "def greet():"),
    ("``` python\ndef greet():\n```", "def greet():"),
    ("```{.py}\ndef greet():\n```", "def greet():"),
    ("~~~ js\nlet a = 1\n~~~", "let a = 1"),
    ("```x``` is inline\nnext", "```x``` is inline"),
    (f"{ZWSP}{BOM}{LRM}{ZWJ}\nfix the login", "fix the login"),
    (f"{ZWSP}{BOM}{LRM}{ZWJ}", ""),
    # next to nothing before one long word: cut inside it
    (f"fix {LINK}", f"fix {LINK}"[:59] + "…"),
    # what a cut does not end on, before its "…"
    ("a" * 40 + " b, (" + "c" * 30, "a" * 40 + " b…"),
    ("a" * 40 + " b — " + "c" * 30, "a" * 40 + " b…"),
])
def test_a_title_from_a_message(said, title):
    assert title_from(said) == title


@pytest.mark.parametrize("said,title", [
    # B-57's commit message: at a word, not on the quote that opens the next
    ('Coder: In the file lines.txt in the project folder, change line 2 from "two" to "TWO"',
     "Coder: In the file lines.txt in the project folder, change line 2 from…"),
    # nor on a word that opens a quote, or a bracket, and does not close it
    ('Coder: in the file hello.py set the greeting that it prints to "Hello there, all"',
     "Coder: in the file hello.py set the greeting that it prints to…"),
    ('Coder: in hello.py, keep the greeting and add a farewell line (print("bye"))',
     "Coder: in hello.py, keep the greeting and add a farewell line…"),
    ('Coder: in the file hello.py set the greeting that it prints to "Hello" now and then',
     'Coder: in the file hello.py set the greeting that it prints to "Hello"…'),
    # a quote opened words back: cut before it, where half the line is still left
    ('Coder: in the greeting file of the site set the text to "Hello there all my good friends"',
     "Coder: in the greeting file of the site set the text to…"),
    # (where it is not, the quote stays open: next to nothing would be left)
    ('Set it to "Hello there all my good friends and neighbours who came by today and stayed"',
     'Set it to "Hello there all my good friends and neighbours who came by…'),
    # an apostrophe opens nothing
    ("Coder: don't change the greeting of hello.py, only the farewell line at its very end",
     "Coder: don't change the greeting of hello.py, only the farewell line at…"),
])
def test_a_line_cut_to_a_commits_length_closes_what_it_opened(said, title):
    assert title_from(said, 72) == title


def test_a_hard_cut_never_parts_a_letter_from_its_mark():
    said = "e" * 58 + "é" + "x" * 10  # the 60th character is the accent on the 59th
    title = title_from(said)
    assert title == "e" * 58 + "…"
    assert len(title) <= 60


def test_the_joiners_inside_a_word_stay_and_those_around_it_go():
    family = f"\U0001f468{ZWJ}\U0001f469{ZWJ}\U0001f467"
    assert one_line(f"our {family} trip") == f"our {family} trip"
    assert one_line(f"می{ZWNJ}خوام") == f"می{ZWNJ}خوام"
    assert one_line(f"{ZWJ} a {ZWNJ}") == "a"


def test_a_message_of_nothing_printable_keeps_the_conversations_name(client, project_dir):
    origin = {"Origin": "http://127.0.0.1:8790"}
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}, headers=origin).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations", headers=origin).json()["id"]
    sent = client.post(f"/api/conversations/{cid}/messages", headers=origin, json={"content": f"{ZWSP}{BOM}"})
    assert sent.status_code < 300, sent.text
    assert client.get(f"/api/conversations/{cid}").json()["conversation"]["title"] == "New conversation"


def test_a_rooms_goal_names_its_conversation_cut_at_a_words_end(make_client, wait_run, project_dir):
    goal = "make the calculator page together (HTML+CSS+JS in one file, no libraries)"
    client, _model, cid, run_id, _room = start(
        make_client, project_dir, {"Coder": [text("Done.")], "Reviewer": [text("Done.")]}, goal=goal)
    assert client.get(f"/api/conversations/{cid}").json()["conversation"]["title"] == (
        "make the calculator page together…")  # (not inside the bracket it opened)
    wait_run(client, cid, run_id)


def test_a_triggers_name_names_its_conversation_whole(make_client, wait_run, project_dir):
    name = "Look the whole project over every hour and say what changed since"  # 65 characters
    client, _model, pid, cid = setup(make_client, project_dir, {"Lead": [text("Looked.")]})
    made = trigger(client, pid, cid, name=name)
    wait_run(client, cid, run_now(client, made["id"]))
    assert client.get(f"/api/conversations/{cid}").json()["conversation"]["title"] == name
