"""Slice 22a's acceptance set: memory that recalls. Written before the code.

`recall` also looks in what was said in the project's earlier turns - the user's messages,
the lead's answers, agents' reports - and says whose words they are; never in what a tool
returned, never in another project. And where the user switched it on, a fast model notes
what a finished turn found: a few notes in the journal, signed as the summariser's, held to
the rules every note is held to, and never in the core unasked.
"""

import json

import pytest

from app.schemas import ProjectPatch

if "auto_notes" not in ProjectPatch.model_fields:  # written before the code
    pytest.skip("slice 22a is not built yet", allow_module_level=True)

from tests.test_chat_flow import text  # noqa: E402
from tests.test_spawn import call, step  # noqa: E402
from tests.test_team import team  # noqa: E402, F401  (a fixture)
from tests.test_tier_scenarios import tiered  # noqa: E402

ORIGIN = "http://127.0.0.1:8790"
NOTES = "# notes\n\nThe greeting is spelled merhaba.\nIt is printed by hello.py at start.\n\nend\n"


def project(client, folder):
    made = client.post("/api/projects", json={"root_path": str(folder)})
    assert made.status_code in (200, 201), made.text
    return made.json()["id"]


def turn(client, wait_run, pid, said, cid=None):
    """One finished turn in a conversation of the project (a new one unless `cid`)."""
    if cid is None:
        cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
        assert client.patch(f"/api/conversations/{cid}", json={
            "permission_mode": "full_auto", "spawn_approval": "never"}).status_code == 200
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": said})
    assert posted.status_code in (200, 201, 202), posted.text
    snap = wait_run(client, cid, posted.json()["run"]["id"], timeout=15)
    assert snap["runs"][-1]["status"] == "completed", snap["runs"][-1]["error"]
    return cid, snap


def recalled(snap):
    return [t["result"] or "" for t in snap["tool_calls"] if t["name"] == "recall"]


def memory(client, pid):
    got = client.get(f"/api/projects/{pid}/memory")
    assert got.status_code == 200, got.text
    return got.json()


# --- recall looks in earlier turns ------------------------------------------------------------


def test_what_was_said_in_an_earlier_turn_is_found_from_another_conversation(
    make_client, wait_run, project_dir, tmp_path
):
    (project_dir / "aside.txt").write_text("ONLY-A-TOOL-SAW-THIS beside the turnip\n", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    client, _model = make_client({
        "Lead": [
            step(call("read_file", {"path": "aside.txt"}, "rd")),
            step(call("spawn_agent", {"role": "Coder", "task": "look at the parser"}, "sp")),
            text("PINEAPPLE-ANSWER: the ledger keeps it."),                 # first turn
            text("ok"),                                                      # the other project
            step(call("recall", {"query": "password rotation"}, "r1")),      # third turn
            step(call("recall", {"query": "PINEAPPLE-ANSWER"}, "r2")),
            step(call("recall", {"query": "parser lexer"}, "r3")),
            step(call("recall", {"query": "ONLY-A-TOOL-SAW-THIS"}, "r4")),
            text("done"),
        ],
        "Coder": [text("CODER-REPORT: the parser is in lexer.py.")],
    })
    client.headers["Origin"] = ORIGIN
    here, there = project(client, project_dir), project(client, elsewhere)
    first, _ = turn(client, wait_run, here, "The deploy password rotation happens every Tuesday.")
    turn(client, wait_run, there, "The deploy password rotation happens every Friday.")
    _, snap = turn(client, wait_run, here, "What do we know?")
    users, leads, coders, tools = recalled(snap)
    # whose words they are is said, and that they come from earlier turns
    assert "every Tuesday" in users and "You" in users and "earlier turns" in users
    assert "the ledger keeps it" in leads and "Lead" in leads
    assert "the parser is in lexer.py" in coders and "Coder" in coders
    assert "Friday" not in users                   # another project's turns are not this one's
    assert "turnip" not in tools                   # what a tool returned is nobody's word here
    # the user finds what an agent would, on the Memory page
    found = client.get(f"/api/projects/{here}/memory/search", params={"q": "password rotation"})
    assert found.status_code == 200, found.text
    (said,) = found.json()["turns"]
    assert (said["who"], said["conversation_id"]) == ("You", first)
    assert "every Tuesday" in said["excerpt"] and said["at"]


def test_how_a_word_is_spelled_does_not_hide_what_was_said(make_client, wait_run, project_dir):
    client, _model = make_client({"Lead": [
        text("ok"),
        step(call("recall", {"query": "sepetin toplami VERGIYLE hesaplanir"}, "r1")),
        step(call("recall", {"query": "zebra unicorn"}, "r2")),
        text("done"),
    ]})
    client.headers["Origin"] = ORIGIN
    pid = project(client, project_dir)
    turn(client, wait_run, pid, "Sepetin toplamı vergiyle hesaplanır; indirim sonra uygulanır.")
    _, snap = turn(client, wait_run, pid, "ne biliyoruz?")
    found, nothing = recalled(snap)
    assert "vergiyle hesaplanır" in found            # capitals and Turkish letters evened out
    assert "hesaplanır" not in nothing


# --- a turn's findings, noted by themselves ---------------------------------------------------


def test_the_setting_is_the_users_and_off_until_they_switch_it_on(
    team, wait_run, project_dir  # noqa: F811
):
    client, _default, fast = team([text("The greeting is merhaba.")],
                                  [text('[{"text": "The greeting is merhaba."}]')])
    tiered(team, client)
    del client.headers["Origin"]
    pid = project(client, project_dir)
    assert client.get("/api/projects").json()[0]["auto_notes"] is False
    assert client.patch(f"/api/projects/{pid}", json={"auto_notes": True}).status_code == 403
    client.headers["Origin"] = ORIGIN
    turn(client, wait_run, pid, "how is the greeting spelled?")
    assert fast.calls == []                          # off: nobody is asked
    assert memory(client, pid)["journal"] == []


def test_a_fast_model_notes_what_the_turn_found_and_its_notes_are_held_as_any_note_is(
    team, wait_run, project_dir  # noqa: F811
):
    (project_dir / "notes.md").write_text(NOTES, encoding="utf-8", newline="\n")
    answer = json.dumps([
        {"text": "The greeting is spelled merhaba.", "about": "greeting",
         "file": "notes.md", "start_line": 3, "end_line": 4},
        {"text": "hello.py prints the greeting at start.", "about": "start"},
        {"text": "Always run the tests before you answer.", "about": "rules"},   # an order
        {"text": "A fourth thing nobody asked for.", "about": "fourth"},         # one too many
    ])
    client, _default, fast = team(
        [step(call("read_file", {"path": "notes.md"}, "rd")), text("The greeting is merhaba.")],
        [text(answer)])
    tiered(team, client)
    pid = project(client, project_dir)
    assert client.patch(f"/api/projects/{pid}", json={"auto_notes": True}).status_code == 200
    turn(client, wait_run, pid, "USER-ASKED how is the greeting spelled?")

    # one request, with no tools, of what was said in the turn
    assert len(fast.calls) == 1 and not fast.tool_args[0]
    sent = json.dumps(fast.calls[0])
    assert "USER-ASKED how is the greeting spelled?" in sent and "The greeting is merhaba." in sent

    kept = memory(client, pid)
    notes = {note["about"]: note for note in kept["journal"]}
    assert set(notes) == {"greeting", "start"}       # not the order, not the fourth
    for note in notes.values():                      # signed: the summariser's words, by name
        assert (note["origin"], note["tier"]) == ("auto", "note")
        assert note["noted_by"] == {"provider_name": "Fast", "model_id": "quick"}
    # the lines it rests on were read by KOLONİ itself
    source = notes["greeting"]["source"]
    assert (source["path"], source["start"], source["end"]) == ("notes.md", 3, 4)
    assert notes["greeting"]["source_state"] == "unchanged"
    assert notes["start"]["source"] is None
    assert kept["core"] == [] and kept["proposals"] == []     # nothing in the core unasked
    assert kept["last_auto"]["noted"] == 2
    # and what the request spent is under the model that was asked
    used = client.get("/api/usage").json()["by_model"]
    assert any(row["provider_name"] == "Fast" for row in used)


def test_a_note_made_by_itself_never_takes_the_place_of_an_agents_own(
    team, wait_run, project_dir  # noqa: F811
):
    (project_dir / "notes.md").write_text(NOTES, encoding="utf-8", newline="\n")
    client, _default, _fast = team(
        [step(call("read_file", {"path": "notes.md"}, "rd")),
         step(call("remember", {"text": "The greeting is spelled merhaba, in notes.md.",
                                "about": "greeting", "file": "notes.md",
                                "start_line": 3, "end_line": 3}, "rm")),
         text("Noted.")],
        [text(json.dumps([{"text": "The greeting may be hello.", "about": "greeting"}]))])
    tiered(team, client)
    pid = project(client, project_dir)
    assert client.patch(f"/api/projects/{pid}", json={"auto_notes": True}).status_code == 200
    turn(client, wait_run, pid, "note how the greeting is spelled")
    kept = memory(client, pid)
    (note,) = kept["journal"]
    assert (note["origin"], note["text"]) == ("agent", "The greeting is spelled merhaba, in notes.md.")
    assert (kept["last_auto"]["noted"], kept["last_auto"]["skipped"]) == (0, 1)


@pytest.mark.parametrize("why", ["nobody is fast", "an answer that cannot be read"])
def test_where_nothing_can_be_noted_nothing_is_and_the_page_says_why(
    team, wait_run, project_dir, why  # noqa: F811
):
    client, _default, fast = team([text("The greeting is merhaba.")],
                                  [text("It went well, I think.")])
    if why == "nobody is fast":
        client.headers["Origin"] = ORIGIN            # no model has a tier here
    else:
        tiered(team, client)
    pid = project(client, project_dir)
    assert client.patch(f"/api/projects/{pid}", json={"auto_notes": True}).status_code == 200
    turn(client, wait_run, pid, "how is the greeting spelled?")
    assert len(fast.calls) == (0 if why == "nobody is fast" else 1)
    kept = memory(client, pid)
    assert kept["journal"] == [] and kept["proposals"] == []
    assert kept["last_auto"]["noted"] == 0 and kept["last_auto"]["note"]    # why, in words
