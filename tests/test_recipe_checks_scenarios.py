"""Batch-16 (G1, `tasarim/specs/2026-10-25-referans-ikinci-tur.md`): a recipe's step is not skipped.

- G1.2: a loop's rounds over with findings left, the work does not go on to the next step: it is
  the user's at Ready for you, saying so. Who did the work does not pass its check.
- G1.5: a review passes only saying what it checked.
- An "all at once" group's roles are opened together; one more of a role is not its missing one.
- REA's B-100, B-101, B-102 (read-only part) for teams side by side.
"""

import pytest

from app import memory as kept
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import OWN, no_recipe, teams_of
from tests.test_claim_scenarios import write
from tests.test_parallel import until
from tests.test_recipe_run_scenarios import (
    FOUND,
    NONE,
    READY,
    answer,
    asked,
    by_call,
    made,
    manual,
    row,
    strip,
)
from tests.test_recipes_scenarios import graph
from tests.test_recipes_scenarios import step as part
from tests.test_spawn import begin, call, spawn, step
from tests.test_take_in_scenarios import needs_git, repository


def build_review_ship(client):
    return made(client, "Build review ship", graph(
        [part("build", "Build it", {"role": "Coder"}),
         part("review", "Code review", {"role": "Reviewer"}, done_when="no_findings"),
         part("ship", "Ship it", {"role": "Tester"})],
        [("start", "build"), ("build", "review"), ("review", "ship"), ("ship", "end")],
        loops=[{"from": "review", "to": "build", "rounds": 1}]))


def test_in_the_recipes_copy_a_task_names_no_project_path_and_a_review_is_handed_the_diff(
        make_client, wait_run, project_dir):
    # B-129 (live): a task naming the project's path, agents in the copy asked "Path mismatch: which
    # is the real project?"; reviewers said "no baseline": git does not work in the copy.
    import os
    client, _model = make_client({
        "Lead": [spawn("Coder", f"Fix {project_dir}{os.sep}greet.py in {project_dir}", "c1"),
                 spawn("Reviewer", "review greet.py", "r1"), spawn("Tester", "test it", "t1"), text("over to you")],
        "Coder": [step(write("greet.py", "print('Hi')\n")), text("built")],
        "Reviewer": [text(NONE)], "Tester": [text(NONE)]})
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], build_review_ship(client)))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    tasks = {a["name"]: a["task"] for a in snap["agents"]}
    assert tasks["Coder"] == "Fix greet.py in ./"
    assert "What the work changed, against the project (git does not work in the copy" in tasks["Reviewer"]
    assert "+print('Hi')" in tasks["Reviewer"] and "greet.py" in tasks["Reviewer"]
    # B-144 (live): old broken tests were findings again; what the diff does not change failed before.
    assert tasks["Reviewer"].endswith("was failing before the work: say it under `Already failing before`, "
                                      "not as a finding.")
    told = next(t["result"] for t in snap["tool_calls"] if t["name"] == "write_file")
    assert str(project_dir) not in told and "The copy is your working folder" in told
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)


def test_findings_left_after_the_last_round_go_to_the_user_not_to_the_next_step(make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [spawn("Coder", "build", "c1"), spawn("Reviewer", "review", "r1"),
                 step(call("spawn_agent", {"role": "Coder", "task": "fix", "findings_from": "Reviewer"}, "c2")),
                 spawn("Reviewer", "review", "r2"), text("over to you")],
        "Coder": [step(write("greet.py", "print('Helo')\n")), text("built")],
        "Coder 2": [text("still Helo")],
        "Reviewer": [text(FOUND)], "Reviewer 2": [text(FOUND)],
    })
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], build_review_ship(client)))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    assert "findings are left after 1 round of Code review" in asked(snap)["question"]
    assert row(snap)["status"] == "ready"
    # (R116: the review that sent it back ran again - its round too; ship and end, past the loop, none)
    assert strip(row(snap)) == [("build", "done", 1), ("review", "now", 1), ("ship", "next", 0), ("end", "next", 0)]
    answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id)
    assert (project_dir / "greet.py").exists() and row(snap)["status"] == "in"
    assert "Tester" not in [a["role_name"] for a in snap["agents"]]


def test_a_review_with_suggestions_only_goes_on_after_one_round(make_client, wait_run, project_dir):
    # R180 (live): every small note opened a review round; a suggestion sends no work back to Build.
    client, _model = make_client({
        "Lead": [spawn("Coder", "build", "c1"), spawn("Reviewer", "review", "r1"),
                 spawn("Tester", "ship", "t1"), text("over to you")],
        "Coder": [step(write("greet.py", "print('Hello')\n")), text("built")],
        "Reviewer": [text("Fine.\n\nChecked: read greet.py\n\n## Findings\n"
                          "- say who is greeted | kind: code | role: Coder | suggestion\n")],
        "Tester": [text("shipped")],
    })
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], build_review_ship(client)))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    assert strip(row(snap))[:3] == [("build", "done", 0), ("review", "done", 0), ("ship", "done", 0)]
    assert [a["role_name"] for a in snap["agents"] if a["depth"] == 1] == ["Coder", "Reviewer", "Tester"]
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)


def test_a_lead_that_ends_when_findings_send_the_recipe_back_leaves_findings_not_a_rule_broken(
        make_client, wait_run, project_dir):
    # B-116 (live): the Lead ended back at Build; the steps that ran showed "skipped", the row
    # "stopped: rule broken: Build it and All at once were not done".
    client, _model = make_client({
        "Lead": [spawn("Coder", "build", "c1"), spawn("Reviewer", "review", "r1"), text("over to you"),
                 text("over to you")],
        "Coder": [step(write("greet.py", "print('Helo')\n")), text("built")],
        "Reviewer": [text(FOUND)],
    })
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], build_review_ship(client)))
    snap = wait_run(client, cid, run_id)
    assert (row(snap)["status"], row(snap)["why"]) == ("stopped", "findings are left after 1 round of Code review")
    assert row(snap)["ended_ready"] is True
    assert "skipped" not in [state for _id, state, _round in strip(row(snap))]


def test_findings_sent_back_go_to_the_steps_role_whatever_role_they_name(make_client, wait_run, project_dir):
    # B-117 (live): the Tester's findings named the Debugger; back at Build, which takes only the
    # Coder, the Lead was refused the Debugger and stopped.
    client, model = make_client({
        "Lead": [spawn("Coder", "build", "c1"), spawn("Reviewer", "review", "r1"),
                 step(call("spawn_agent", {"role": "Coder", "task": "fix", "findings_from": "Reviewer"}, "c2")),
                 spawn("Reviewer", "review", "r2"), spawn("Tester", "ship", "t1"), text("over to you")],
        "Coder": [step(write("greet.py", "print('Helo')\n")), text("built")],
        "Coder 2": [step(write("greet.py", "print('Hello')\n", id="w2")), text("- greet says Helo | fixed: Hello")],
        "Reviewer": [text("Found two.\n\n## Findings\n- greet says Helo | kind: code | role: Coder\n"
                          "- no test for greet | kind: test | role: Tester\n")],
        "Reviewer 2": [text(NONE)], "Tester": [text("shipped")],
    })
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], build_review_ship(client)))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    reviewed = by_call(snap)[1][1]
    assert "back to Build it, round 1 of 1. Hand them to Coder with findings_from" in reviewed
    assert "Findings to hand on" not in reviewed
    # (the step's Coder takes the one for the Tester too, which no role of the step could)
    fixer = {a["name"]: a["task"] for a in snap["agents"]}["Coder 2"]
    assert "greet says Helo" in fixer and "no test for greet" in fixer
    # what a review is told: only findings about the work it checks
    review = next(m for m in model.calls if "Your name here is Reviewer" in m[0]["content"])
    assert "Already failing before: <what>" in review[0]["content"]
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)


def test_who_did_the_work_does_not_pass_its_check(make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [spawn("Coder", "build", "c1"), spawn("Coder", "check your own work", "c2"),
                 spawn("Reviewer", "check it", "r1"), text("done")],
        "Coder": [step(write("greet.py", "print('Hello')\n")), text("built")],
        "Reviewer": [text(NONE)],
    })
    checked = made(client, "Build and check", graph(
        [part("build", "Build it", {"role": "Coder"}),
         part("check", "Check it", {"lead": True}, done_when="no_findings")],
        [("start", "build"), ("build", "check"), ("check", "end")]))
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], checked))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    refused = by_call(snap)[1]
    assert refused[0] == "failed" and "not Coder: who did the work does not pass its check" in refused[1]
    assert "the Coder role is not one of its roles now" in refused[1]
    # B-191 (live): refused, the Lead asked the user which role - the step's is named, and opened now.
    assert "is at its Check it step, for Accessibility reviewer, Copywriter, Debugger, Refactorer" in refused[1]
    assert "open the step's role named there now, with spawn_agent; do not ask the user which" in refused[1]
    # ...as the step it goes on to is told by its roles.
    assert "Next: Check it - open Accessibility reviewer or Copywriter or Debugger" in by_call(snap)[0][1]
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)


def reviews_at_once(client):
    return made(client, "Reviews at once", graph(
        [part("code", "Code review", {"role": "Reviewer"}, group="g", done_when="no_findings"),
         part("tests", "Test it", {"role": "Tester"}, group="g", done_when="no_findings")],
        [("start", "g"), ("g", "end")], groups=[{"id": "g", "name": "All at once"}]))


def test_one_more_of_a_role_is_not_the_groups_missing_role(make_client, wait_run, project_dir):
    # Live (PLAN-84B-05): one "Reviewer 3" too many - it took the place of a review not opened.
    client, _model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Reviewer", "task": "review"}, "r1"),
                      call("spawn_agent", {"role": "Reviewer", "task": "review again"}, "r2"),
                      call("spawn_agent", {"role": "Tester", "task": "test"}, "t1")), text("done")],
        "Reviewer": [text(NONE)], "Reviewer 2": [text(NONE)], "Tester": [text(NONE)],
    })
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], reviews_at_once(client)))
    snap = wait_run(client, cid, run_id)  # (K-r144: reviews change no file - no Take in card)
    calls = by_call(snap)
    assert calls[1][0] == "failed" and "has its Reviewer" in calls[1][1]
    # B-184: and which one, with what to do in place of opening it again (one reply's agents open together)
    assert "Reviewer is already at work on it: do not open it again - wait for its report" in calls[1][1]
    assert [a["role_name"] for a in snap["agents"] if a["depth"]] == ["Reviewer", "Tester"]


def test_an_all_at_once_groups_other_roles_are_opened_with_the_first(make_client, wait_run, project_dir, gate):
    # Live (PLAN-84B-05, B-87): the group's reviews were opened one by one, each waiting for the last.
    client, _model = make_client({
        "Lead": [spawn("Reviewer", "review greet.py", "r1"), text("done")],
        "Reviewer": [gate.step(text(NONE))], "Tester": [text(NONE)],
    })
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], reviews_at_once(client)))
    gate.wait_partial()
    # The Tester works and ends while the Reviewer still works: at the same time.
    snap = until(client, cid, lambda s: any(a["role_name"] == "Tester" and a["status"] == "completed"
                                            for a in s["agents"]))
    tester = next(a for a in snap["agents"] if a["role_name"] == "Tester")
    assert "for the All at once step of the Reviews at once recipe" in tester["task"]
    assert "review greet.py" in tester["task"]
    gate.release()
    first = by_call(wait_run(client, cid, run_id))[0][1]
    assert "KOLONİ opened Tester at the same time, beside it, for the All at once step" in first


def test_a_review_that_names_no_check_is_no_pass(make_client, wait_run, project_dir):
    # G1.5: "Findings: none" with nothing checked counts as findings left.
    client, model = make_client({
        "Lead": [spawn("Reviewer", "review", "r1"), text("done")],
        "Reviewer": [text("Looks fine.\n\nFindings: none")],
    })
    review = made(client, "Just review", graph(
        [part("review", "Code review", {"role": "Reviewer"}, done_when="no_findings")],
        [("start", "review"), ("review", "end")]))
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], review))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    assert "Checked: <the files you read" in model.calls_of["Reviewer"][0][0]["content"]
    answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id)
    said = by_call(snap)[0][1]
    assert "Reviewer said it found nothing but not what it checked" in said
    assert "Findings are left: the user sees them." in said
    # (On record as a finding left: Ready for you lists it so.)
    (reviewer,) = [a for a in snap["agents"] if a["role_name"] == "Reviewer"]
    assert [f["what"] for f in reviewer["findings"]] == ["it said nothing was found, but not what it checked"]


def test_beside_teams_leads_the_lead_opens_no_room_by_the_roles_the_message_names(make_client, wait_run, project_dir):
    # B-100 (live): named in the message, Coder and Tester were opened in a room by the Lead itself;
    # Backend / API's lead never ran, and its team had no row at Ready for you.
    from tests.test_recipe_run_scenarios import one_step
    from tests.test_room_open_scenarios import open_room
    client, _model = make_client({"Lead": [open_room(members=("Coder", "Tester")), text("done"), text("done"),
                                           text("done")]})
    teams = teams_of(client)
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never", teams_mode="manual",
                        content="Web app builds it; Docs, with the Coder and the Tester in a room, writes it",
                        teams=[{"team_id": teams["Web app"]["id"], "recipe_id": one_step(client, "Just build", "Coder")["id"]},
                               {"team_id": teams["Docs"]["id"], "recipe_id": one_step(client, "Just write", "Docs writer")["id"]}])
    snap = wait_run(client, cid, run_id)
    ((status, said),) = [(t["status"], t["result"]) for t in snap["tool_calls"] if t["name"] == "open_room"]
    assert status == "failed" and "Coder is in Web app, which its coordinator runs: hand it to Web app lead" in said
    assert not [a for a in snap["agents"] if a["depth"]]


def test_a_lead_refused_a_tier_by_its_rule_does_not_start_its_teams_recipe(make_client, wait_run, project_dir, monkeypatch):
    from tests.test_recipe_ends_scenarios import as_picked
    as_picked(monkeypatch)  # (B-161: as the Lead's own pick - in Manual no team has to work)
    # A team's lead runs on the chat's model (0083): refused a tier given with a why, it never ran -
    # its team is shown not started, not "rule broken" for steps nobody could open.
    from tests.test_recipe_ends_scenarios import SCRIPTS, rows_of
    lead = call("spawn_agent", {"role": "Web app lead", "task": "the page", "tier": "fast", "why": "a small page"}, "l1")
    client, _model = make_client({"Lead": [step(lead), text("done"), text("done"), text("done")], **SCRIPTS})
    cid, run_id = manual(client, project_dir, *rows_of(client, False))
    snap = wait_run(client, cid, run_id)
    refused = by_call(snap)[0]
    assert refused[0] == "failed" and "runs on the conversation's model" in refused[1]
    assert [row(snap, 0)["status"], row(snap, 1)["status"]] == ["waiting", "waiting"]


def test_a_team_with_no_recipe_beside_one_has_its_row_and_its_own_kept_copy(make_client, wait_run, project_dir):
    # B-101 (live): Backend / API, with no recipe beside Web app's, had no row at Ready for you, and its
    # kept copy no Take in / Discard there.
    from tests.test_recipe_ends_scenarios import SCRIPTS
    from tests.test_recipe_run_scenarios import one_step
    client, _model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Web app lead", "task": "the page"}, "l1"),
                      call("spawn_agent", {"role": "Docs lead", "task": "the words"}, "l2")), text("done")],
        **SCRIPTS})
    teams = no_recipe(client, "Docs")  # (0103 gives Docs its own: this one is to have none)
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never", teams_mode="manual",
                        teams=[{"team_id": teams["Docs"]["id"], "recipe_id": None},
                               {"team_id": teams["Web app"]["id"], "recipe_id": one_step(client, "Just build", "Coder")["id"]}])
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    assert "Docs (no recipe): done - its work is a kept copy of its own" in asked(snap)["question"]
    docs = row(snap, 0)
    # B-107: the turn keeps the rows in the chat's order, though Docs' was saved after Web app's.
    turn = next(r for r in snap["runs"] if r["id"] == run_id)
    assert [t["team_id"] for t in turn["teams"]] == [teams["Docs"]["id"], teams["Web app"]["id"]]
    ids = {a["role_name"]: a["id"] for a in snap["agents"]}
    assert (docs["status"], docs["recipe"], docs["agents"]) == ("done", "", [ids["Docs lead"], ids["Docs writer"]])
    (kept,) = [m for m in snap["merges"] if m["status"] == "kept"]
    assert kept["agent_id"] == ids["Docs lead"] and kept["kept_in"]
    answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id)
    assert (project_dir / "a.py").exists() and not (project_dir / "b.md").exists()
    assert row(snap, 0)["status"] == "done"
    # B-158 (live): Applied from its own card, Docs' row is in the project too, as Web app's is.
    from tests.test_chat_teams_scenarios import OWN
    taken = client.post(f"/api/merges/{kept['id']}/approve", json={"choices": {}}, headers=OWN)
    assert taken.status_code == 200, taken.text
    assert (project_dir / "b.md").exists()
    assert [row(client.get(f"/api/conversations/{cid}").json(), at)["status"] for at in (0, 1)] == ["in", "in"]


def test_a_reports_commit_line_is_its_first_that_is_no_heading_without_its_marks():
    from app.agent import report_line
    assert report_line("## Summary\n\n> **Done** - wrote **b.md**\nmore") == "Done - wrote b.md"
    assert report_line("- Fixed the cart\n") == "Fixed the cart"
    assert report_line("# Only a heading") == report_line(None) == ""


@needs_git
def test_a_lead_opened_beside_has_its_commit_named_by_its_team_and_report(make_client, wait_run, project_dir, monkeypatch):
    # B-160 (live): Docs' kept copy, Apply then Commit: "Docs lead: KOLONİ opened you at the same time as Web app lead…".
    from tests.test_chat_teams_scenarios import OWN
    from tests.test_recipe_ends_scenarios import SCRIPTS, as_picked
    as_picked(monkeypatch)  # (Docs' lead opened by KOLONİ beside the Web app's)
    repository(project_dir)
    client, _model = make_client({"Lead": [spawn("Web app lead", "the page", "l1"), text("done")], **SCRIPTS})
    cid, run_id = two_rows(client, project_dir, content="Add the page and its words\n\nmore below")
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    assert client.patch(f"/api/projects/{snap['conversation']['project_id']}", json={"git_commit": True},
                        headers=OWN).status_code == 200
    docs = next(a for a in snap["agents"] if a["role_name"] == "Docs lead")
    assert docs["task"].startswith("KOLONİ opened you at the same time as Web app lead")
    answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id)
    (kept,) = [m for m in snap["merges"] if m["status"] == "kept" and m["kept_in"]]
    taken = client.post(f"/api/merges/{kept['id']}/approve", json={"choices": {}}, headers=OWN)
    assert taken.status_code == 200, taken.text
    snap = until(client, cid, lambda s: next(m for m in s["merges"] if m["id"] == kept["id"])["commit"])
    # B-187: by its team and what it did - not the user's message, the same for every team.
    assert next(m for m in snap["merges"] if m["id"] == kept["id"])["commit"]["message"] == "Docs: docs done"


@pytest.mark.parametrize("content, lead, opened", [
    ("Docs: write the words for the page", [spawn("Docs lead", "the words", "l2"), text("done")], ["Docs lead"]),
    ("Web app and Docs: the page and its words", [step(call("spawn_agent", {"role": "Web app lead", "task": "the page"}, "l1"),
                       call("spawn_agent", {"role": "Docs lead", "task": "the words"}, "l1d")), text("done")],
     ["Web app lead", "Docs lead"]),
    # B-161 (live): "Web app'e iş yok" opened the Web app, named in the message, and it ran its recipe.
    ("Web app'e iş yok; Docs: write the words for the page", [spawn("Docs lead", "the words", "l2"), text("done")],
     ["Docs lead"]),
    ("what does a recipe do?", [text("It runs a team's steps in order.")], []),
])
def test_in_manual_the_lead_opens_only_the_teams_the_message_needs(make_client, wait_run, project_dir, content, lead, opened):
    # B-153 (live; the user: "Lead picks the relevant teams"): a message meant for Docs alone opened both teams, and the
    # Web app ran its whole recipe for nothing. Manual's teams are the ones the Lead may use: the Lead's choice stands.
    from tests.test_recipe_ends_scenarios import SCRIPTS
    client, model = make_client({"Lead": lead, **SCRIPTS})
    cid, run_id = two_rows(client, project_dir, content=content)
    snap = until(client, cid, lambda s: (asked(s) and READY in asked(s)["question"]) or next(
        r for r in s["runs"] if r["id"] == run_id)["status"] in ("completed", "failed"), timeout=10)
    if asked(snap):
        answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id)
    assert sorted(a["role_name"] for a in snap["agents"] if a["depth"] == 1) == sorted(opened)
    # (Nor is the Lead told a team it left "has to work on this message".)
    assert not any("has to work on this message" in str(m) for calls in model.calls_of["Lead"] for m in calls)


def test_a_team_with_no_recipe_that_only_wrote_to_the_shared_folder_has_nothing_to_take_in(
        make_client, wait_run, project_dir):
    # B-153 (live): Docs, which had only written to the shared folder, was said to have "a kept copy of its own".
    from tests.test_recipe_ends_scenarios import SCRIPTS
    client, _model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Web app lead", "task": "the page"}, "l1"),
                       call("spawn_agent", {"role": "Docs lead", "task": "the words"}, "l1d")), text("done")], **SCRIPTS,
        "Docs lead": [step(call("write_shared", {"path": "docs/words.md", "text": "the words"}, "s1")), text("docs done")]})
    cid, run_id = two_rows(client, project_dir)
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    said = asked(snap)["question"]
    assert "Docs (no recipe): done - it wrote to the shared folder · nothing to take in" in said and "kept copy" not in said
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)


def test_a_team_with_no_recipe_whose_change_was_a_commands_has_its_kept_copy(make_client, wait_run, project_dir):
    # (The review of B-153: a command's change is in no FileChange - its copy is kept all the same.)
    from tests.test_recipe_ends_scenarios import SCRIPTS
    from tests.test_recipe_run_scenarios import one_step
    made = "python -c \"open('c.md','w').write('by a command')\""
    client, _model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Web app lead", "task": "the page"}, "l1"),
                      call("spawn_agent", {"role": "Quality lead", "task": "test it"}, "l1q")), text("done")], **SCRIPTS,
        "Tester": [step(call("run_command", {"command": made}, "r1")), text("Fine.\n\nFindings: none")]})
    teams = no_recipe(client, "Quality")  # (0098 gives Quality "Quality check": this one is to have none)
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never", teams_mode="manual",
                        teams=[{"team_id": teams["Web app"]["id"], "recipe_id": one_step(client, "Just build", "Coder")["id"]},
                               {"team_id": teams["Quality"]["id"], "recipe_id": None}])
    snap = approved_ready(client, cid)
    assert not [f for f in snap["file_changes"] if f["path"] == "c.md"]
    assert "Quality (no recipe): done - its work is a kept copy of its own" in asked(snap)["question"]
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)


def test_a_row_stopped_at_ready_for_you_is_told_apart_from_one_that_ended_early(make_client, wait_run, project_dir):
    # (What is said after the turn of the teams that ended before their end leaves this one out.)
    from tests.test_chat_teams_scenarios import OWN
    from tests.test_recipe_run_scenarios import one_step
    client, _model = make_client({"Lead": [spawn("Coder", "build"), text("never")],
                                  "Coder": [step(write("a.py", "a\n")), text("built")]})
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], one_step(client, "Just build", "Coder")))
    until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    client.post(f"/api/runs/{run_id}/cancel", headers=OWN)
    snap = wait_run(client, cid, run_id)
    assert (row(snap)["status"], row(snap)["why"], row(snap)["ended_ready"]) == ("stopped", "Stopped", True)


def test_a_team_that_finished_answers_from_the_copy_its_work_was_kept_in(make_client, wait_run, project_dir, gate):
    # B-102 (live): Backend / API's lead said "count is not in the project yet" - its team's work was
    # done, kept in its copy; a read-only answer read the project.
    from tests.test_agent_talk import message
    from tests.test_recipe_ends_scenarios import SCRIPTS
    from tests.test_recipe_run_scenarios import one_step
    client, _model = make_client({
        **SCRIPTS,
        "Lead": [step(call("spawn_agent", {"role": "Web app lead", "task": "the page"}, "l1"),
                      call("spawn_agent", {"role": "Docs lead", "task": "the words"}, "l2")), text("done")],
        "Web app lead": [gate.step(message("Docs lead", "Is b.md written?")), spawn("Coder", "build a.py", "c"),
                         text("web done")],
        "Docs lead": [spawn("Docs writer", "write b.md", "d"), text("docs done"),
                      step(call("read_file", {"path": "b.md"}, "rd")), text("yes, b.md is there")],
    })
    teams = no_recipe(client, "Docs")
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never", teams_mode="manual",
                        teams=[{"team_id": teams["Web app"]["id"], "recipe_id": one_step(client, "Just build", "Coder")["id"]},
                               {"team_id": teams["Docs"]["id"], "recipe_id": None}])
    until(client, cid, lambda s: any(m["status"] == "kept" for m in s["merges"]))
    gate.release()
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    read = next(t for t in snap["tool_calls"] if t["name"] == "read_file")
    assert read["status"] == "succeeded" and "b" in read["result"] and not (project_dir / "b.md").exists()
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)


def test_asked_for_changes_after_findings_were_left_a_clean_end_does_not_say_they_are(make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [spawn("Coder", "build", "c1"), spawn("Reviewer", "review", "r1"),
                 step(call("spawn_agent", {"role": "Coder", "task": "fix", "findings_from": "Reviewer"}, "c2")),
                 spawn("Reviewer", "review", "r2"), spawn("Coder", "say Hello", "c3"), spawn("Reviewer", "review", "r3"),
                 spawn("Tester", "ship it", "t1"), text("over to you")],
        "Coder": [step(write("greet.py", "print('Helo')\n")), text("built")],
        "Coder 2": [text("still Helo")],
        "Coder 3": [step(write("greet.py", "print('Hello')\n", id="w2")), text("fixed")],
        "Reviewer": [text(FOUND)], "Reviewer 2": [text(FOUND)], "Reviewer 3": [text(NONE)], "Tester": [text("shipped")],
    })
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], build_review_ship(client)))
    first = asked(until(client, cid, lambda s: asked(s) and READY in asked(s)["question"]))
    answer(client, first, "Ask for changes: say Hello")
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"] and asked(s)["id"] != first["id"])
    assert "findings are left" not in asked(snap)["question"] and row(snap)["why"] is None
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)


def test_a_team_with_no_recipe_beside_one_stops_alone(make_client, wait_run, project_dir, gate):
    # (Its frame has Stop, as a recipe's team's has.)
    from tests.test_chat_teams_scenarios import OWN
    from tests.test_recipe_ends_scenarios import SCRIPTS
    from tests.test_recipe_run_scenarios import one_step
    client, _model = make_client({
        **SCRIPTS,
        "Lead": [step(call("spawn_agent", {"role": "Web app lead", "task": "the page"}, "l1"),
                      call("spawn_agent", {"role": "Docs lead", "task": "the words"}, "l2")), text("done")],
        "Docs writer": [gate.step(step(write("b.md", "b\n", id="w2"))), text("never said")],
    })
    teams = no_recipe(client, "Docs")
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never", teams_mode="manual",
                        teams=[{"team_id": teams["Web app"]["id"], "recipe_id": one_step(client, "Just build", "Coder")["id"]},
                               {"team_id": teams["Docs"]["id"], "recipe_id": None}])
    gate.wait_partial()
    stopped = client.post(f"/api/conversations/{cid}/teams/{teams['Docs']['id']}/stop", headers=OWN)
    assert stopped.status_code == 200, stopped.text
    gate.release()
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    assert (row(snap, 1)["status"], row(snap, 1)["why"]) == ("stopped", "Stopped by you")
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)


def test_a_review_by_the_role_that_did_the_work_before_it_is_marked_as_it_is_saved(make_client):
    # (Who did the work does not pass its check.) Only a step before it on the way did the work; a
    # room's review passes as a whole.
    from tests.test_chat_teams_scenarios import OWN

    def saved(name, steps, arrows):
        return client.post("/api/recipes", headers=OWN, json={"name": name, "graph": graph(steps, arrows)})

    client, _model = make_client({})
    build = part("build", "Build it", {"role": "Coder"})
    own = saved("Own", [build, part("review", "Code review", {"role": "Coder"}, done_when="no_findings")],
                [("start", "build"), ("build", "review"), ("review", "end")])
    assert own.status_code == 422 and own.json()["detail"] == [{
        "loc": ["body", "graph"], "msg": "Code review: Coder would check its own work (Build it)", "type": "recipe",
        "at": "review"}]
    later = saved("Later", [part("review", "Code review", {"role": "Reviewer"}, done_when="no_findings"),
                   part("notes", "Write notes", {"role": "Reviewer"})],
                  [("start", "review"), ("review", "notes"), ("notes", "end")])
    room = saved("Room", [build, part("meet", "Look at it", {"room": ["Coder", "Reviewer"]}, done_when="no_findings")],
                 [("start", "build"), ("build", "meet"), ("meet", "end")])
    assert (later.status_code, room.status_code) == (201, 201), (later.text, room.text)


# --- the rules as recipe_run holds them (batch-16's review) ---------------------------------------


def run_of(drawn, picks=("Coder", "Reviewer")):
    from app import recipe_run
    from app.schemas import RecipeGraph, WhoRole, WhoRoom

    def who(one):
        if isinstance(one.who, WhoRole):
            return [(one.who.role,)]
        return [(role,) for role in one.who.room] if isinstance(one.who, WhoRoom) else [picks]

    return recipe_run.begin(RecipeGraph.model_validate(drawn), "r", "x", who)


def done(state, role, found=False):
    from app import recipe_run
    entry = recipe_run.opened(state, f"a{len(state['agents'])}", role)
    entry["ok"], entry["found"] = True, found


def test_who_did_a_part_after_the_review_is_no_writer_of_it_and_ask_for_changes_does_not_stall():
    # Seeded-Feature-like: Approve (the Lead picks) by a Reviewer, then Ask for changes back to Build -
    # the reviews could never fill their Code review again (the whole run's writers were kept off).
    from app import recipe_run
    state = run_of(graph(
        [part("build", "Build it", {"role": "Coder"}),
         part("code", "Code review", {"lead": True}, group="g", done_when="no_findings"),
         part("approve", "Approve it", {"lead": True})],
        [("start", "build"), ("build", "g"), ("g", "approve"), ("approve", "end")],
        groups=[{"id": "g", "name": "Reviews"}]))
    done(state, "Coder")
    recipe_run.advance(state)
    assert recipe_run.open_to(state) == ["Reviewer"]  # (the Coder built it)
    done(state, "Reviewer")
    recipe_run.advance(state)
    done(state, "Reviewer")
    recipe_run.advance(state)
    assert state["status"] == "ready"
    recipe_run.back_to(state)
    done(state, "Coder")
    recipe_run.advance(state)
    assert recipe_run.open_to(state) == ["Reviewer"]


def test_findings_left_name_the_loop_that_sent_the_run_back():
    # (The review: with two loops back to one step, the first drawn was named, not the one that went back.)
    from app import recipe_run
    state = run_of(graph(
        [part("build", "Build it", {"role": "Coder"}),
         part("code", "Code review", {"role": "Reviewer"}, done_when="no_findings"),
         part("test", "Test it", {"role": "Tester"}, done_when="no_findings")],
        [("start", "build"), ("build", "code"), ("code", "test"), ("test", "end")],
        loops=[{"from": "code", "to": "build", "rounds": 2}, {"from": "test", "to": "build", "rounds": 2}]))
    for role, found in (("Coder", False), ("Reviewer", True), ("Coder", False), ("Reviewer", False), ("Tester", True)):
        done(state, role, found=found)
        recipe_run.advance(state)
    assert recipe_run.found_left(state) == "findings are left after 1 round of Test it"


def test_a_room_that_reviews_opens_with_the_one_who_built_it():
    from app import recipe_run
    state = run_of(graph(
        [part("build", "Build it", {"role": "Coder"}),
         part("meet", "Look at it", {"room": ["Coder", "Reviewer"]}, done_when="no_findings")],
        [("start", "build"), ("build", "meet"), ("meet", "end")]))
    done(state, "Coder")
    recipe_run.advance(state)
    assert recipe_run.open_to(state) == ["Coder", "Reviewer"]


def test_a_review_with_no_loop_that_leaves_findings_stops_before_the_next_step():
    # As the seeded Bugfix's Test it: no loop of its own, Review it after it.
    from app import recipe_run
    state = run_of(graph(
        [part("test", "Test it", {"role": "Tester"}, done_when="no_findings"),
         part("review", "Review it", {"role": "Reviewer"})],
        [("start", "test"), ("test", "review"), ("review", "end")]))
    done(state, "Tester", found=True)
    said = recipe_run.advance(state)
    assert (state["status"], state["at"], state["why"]) == ("ready", "test", "findings are left after Test it")
    assert "The recipe stops here" in said


def test_ask_for_changes_gives_the_loop_its_rounds_again():
    from app import recipe_run
    state = run_of(graph(
        [part("build", "Build it", {"role": "Coder"}),
         part("review", "Code review", {"role": "Reviewer"}, done_when="no_findings"),
         part("ship", "Ship it", {"role": "Tester"})],
        [("start", "build"), ("build", "review"), ("review", "ship"), ("ship", "end")],
        loops=[{"from": "review", "to": "build", "rounds": 1}]))
    for _ in range(2):
        done(state, "Coder")
        recipe_run.advance(state)
        done(state, "Reviewer", found=True)
        recipe_run.advance(state)
    assert state["status"] == "ready"
    recipe_run.back_to(state)
    done(state, "Coder")
    recipe_run.advance(state)
    done(state, "Reviewer", found=True)
    assert "back to Build it, round 1 of 1" in recipe_run.advance(state)


# --- teams side by side (batch-16's review) -------------------------------------------------------


def two_rows(client, project_dir, content="please check my greeting", recipe=None, **more):
    from tests.test_recipe_run_scenarios import one_step
    teams = no_recipe(client, "Docs")
    return begin(client, project_dir, mode="auto_edit", teams_mode="manual", content=content,
                 teams=[{"team_id": teams["Web app"]["id"], "recipe_id": (recipe or one_step(client, "Just build", "Coder"))["id"]},
                        {"team_id": teams["Docs"]["id"], "recipe_id": None}], **{"spawn_approval": "never", **more})


def approved_ready(client, cid):
    """Ready for you, the user approving each command asked on the way (Auto-edit asks them;
    at Full auto the card itself is gone, K-fullauto-sorma 2)."""
    def seen(snap):
        for command in snap["commands"]:
            if command["status"] == "proposed":
                client.post(f"/api/commands/{command['id']}/approve", json={}, headers=OWN)
        return asked(snap) and READY in asked(snap)["question"]
    return until(client, cid, seen, timeout=10)


def test_a_lead_refused_for_its_tier_is_opened_beside_the_next_lead(make_client, wait_run, project_dir, monkeypatch):
    from tests.test_recipe_ends_scenarios import as_picked
    as_picked(monkeypatch)  # (B-161: as the Lead's own pick - in Manual no team has to work)
    # B-118 (live): Docs' lead was refused ("Leave tier out"); Web app's, opened again, ran alone.
    from tests.test_recipe_ends_scenarios import SCRIPTS
    client, _model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Docs lead", "task": "the words", "tier": "fast",
                                           "why": "a small job"}, "l1")),
                 spawn("Web app lead", "the page", "l2"), text("done")],
        **SCRIPTS})
    cid, run_id = two_rows(client, project_dir)
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    assert by_call(snap)[0][0] == "failed" and "Leave tier out" in by_call(snap)[0][1]
    assert {"Web app lead", "Docs lead"} <= {a["role_name"] for a in snap["agents"]}
    assert "Docs (no recipe): done" in asked(snap)["question"]
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)


def test_a_no_recipe_teams_lead_that_ended_without_its_work_is_not_done_and_is_opened_again(
        make_client, wait_run, project_dir, monkeypatch):
    from tests.test_recipe_ends_scenarios import as_picked
    as_picked(monkeypatch)  # (B-161: as the Lead's own pick - in Manual no team has to work)
    # B-124 (live): Docs' lead, opened beside Web app's, opened nobody ("I have no write tool"); Ready
    # for you said "Docs (no recipe): done" and the Lead's re-open was refused ("KOLONİ opened it
    # beside another team's lead"). README was never written.
    from tests.test_recipe_ends_scenarios import SCRIPTS
    client, model = make_client({
        "Lead": [spawn("Web app lead", "the page", "l1"), text("done"), spawn("Docs lead", "write it", "l2"),
                 text("done")],
        **SCRIPTS, "Docs lead": [text("I have no write tool")],
        "Docs lead 2": [spawn("Docs writer", "write b.md", "d"), text("docs done")]})
    cid, run_id = two_rows(client, project_dir)
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    first, again = by_call(snap)[:2]
    assert READY not in first[1]  # (Docs' work was not done: no card yet)
    assert again[0] == "succeeded" and "not opened again" not in again[1]
    told = [m["content"] for m in model.calls_of["Lead"][2] if m["role"] == "user"]
    assert any("the Docs team has to work on this message and did not: open Docs lead" in m for m in told)
    # Told who does its team's work.
    assert "open them with spawn_agent (Docs writer, " in model.calls_of["Docs lead"][0][1]["content"]
    assert "Docs (no recipe): done" in asked(snap)["question"]
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)


def test_a_no_recipe_teams_lead_that_did_nothing_is_said_so_on_its_row(make_client, wait_run, project_dir, monkeypatch):
    from tests.test_recipe_ends_scenarios import as_picked
    as_picked(monkeypatch)  # (B-161: as the Lead's own pick - in Manual no team has to work)
    # B-124: the Lead not opening it again, its row is not "done".
    from tests.test_recipe_ends_scenarios import SCRIPTS
    client, _model = make_client({
        "Lead": [spawn("Web app lead", "the page", "l1"), text("done"), text("done"), text("done")],
        **SCRIPTS, "Docs lead": [text("I have no write tool")]})
    cid, run_id = two_rows(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert (row(snap, 1)["status"], row(snap, 1)["why"]) == ("stopped", "Docs lead ended without its work")
    # (Ready for you waited for Docs: Web app's work is kept for the user's Take in, not lost.)
    assert not [q for q in snap["questions"] if READY in q["question"]]
    assert [m for m in snap["merges"] if m["status"] == "kept" and m["kept_in"]]
    assert not (project_dir / "a.py").exists()


def test_a_team_with_no_recipe_whose_lead_never_opens_leaves_the_work_kept_for_take_in(
        make_client, wait_run, project_dir, monkeypatch):
    from tests.test_recipe_ends_scenarios import as_picked
    as_picked(monkeypatch)  # (B-161: as the Lead's own pick - in Manual no team has to work)
    # (As B-84's: a picked team that never runs holds Ready for you; the turn's work is kept for the user.
    # One whose lead the user declined does not: that no is theirs - `test_a_no_recipe_teams_lead_...`.)
    from app.agent import AgentRunner
    from tests.test_recipe_ends_scenarios import SCRIPTS
    monkeypatch.setattr(AgentRunner, "_leads_beside", lambda self, ctx, call_id, args: [])
    client, _model = make_client({"Lead": [spawn("Web app lead", "the page", "l1"), text("done"), text("done"),
                                           text("done")], **SCRIPTS})
    cid, run_id = two_rows(client, project_dir)
    snap = wait_run(client, cid, run_id)
    assert not [q for q in snap["questions"] if READY in q["question"]]
    assert (row(snap)["status"], row(snap)["why"]) == ("stopped", "the turn ended before Take in")
    assert [m for m in snap["merges"] if m["status"] == "kept" and m["kept_in"]]
    assert not (project_dir / "a.py").exists()


def test_ready_for_you_waits_for_a_team_with_no_recipe_that_never_ran(make_client, wait_run, project_dir, monkeypatch):
    from tests.test_recipe_ends_scenarios import as_picked
    as_picked(monkeypatch)  # (B-161: as the Lead's own pick - in Manual no team has to work)
    # B-118 (live): Ready for you said "Every team is at its end" while Docs had not run; its card held
    # the Lead's call, and Docs opened only after the user's Take in.
    from app.agent import AgentRunner
    from tests.test_recipe_ends_scenarios import SCRIPTS
    monkeypatch.setattr(AgentRunner, "_leads_beside", lambda self, ctx, call_id, args: [])
    client, model = make_client({
        "Lead": [spawn("Web app lead", "the page", "l1"), text("done"), spawn("Docs lead", "the words", "l2"),
                 text("done")],
        **SCRIPTS})
    cid, run_id = two_rows(client, project_dir)
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    assert "Docs (no recipe): done" in asked(snap)["question"]
    # Web app's call came back with no card; told Docs has to work, the Lead opened it
    assert "Ready for you" not in by_call(snap)[0][1]
    told = [m["content"] for m in model.calls_of["Lead"][2] if m["role"] == "user"]
    assert any("the Docs team has to work on this message and did not: open Docs lead" in m for m in told)
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)


def test_a_role_the_user_names_is_handed_to_its_teams_lead(make_client, wait_run, project_dir):
    # The user (25 Oct, B-100): in a chat of teams side by side, a role named goes to its team's lead.
    client, _model = make_client({"Lead": [spawn("Coder", "fix the greeting", "c1"), text("done"), text("done"), text("done")]})
    cid, run_id = two_rows(client, project_dir, content="have the Coder fix the greeting")
    ((status, said), *_rest) = by_call(wait_run(client, cid, run_id))
    assert status == "failed" and "Coder is in Web app, which its coordinator runs: hand it to Web app lead" in said
    assert "“Coder is in Web app: I handed it to its coordinator”" in said


def test_in_a_later_turn_of_teams_the_lead_picked_a_role_the_user_names_is_opened(make_client, wait_run, project_dir):
    # (Review: B-100 shut a named role out of every later turn of a chat the Lead had picked teams for.)
    from tests.test_chat_teams_scenarios import OWN
    from tests.test_recipe_ends_scenarios import rows_of
    client, _model = make_client({"Lead": [spawn("Debugger", "look at it", "d1"), text("looked")],
                                  "Debugger": [text("found it")]})
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", headers=OWN, json={
        "permission_mode": "full_auto", "spawn_approval": "never", "teams_mode": "lead"})
    with client.app.state.session_factory() as session:  # (as the Lead's pick_teams left them)
        from app.db.models import Conversation, ConversationTeam
        session.get_one(Conversation, cid).teams = [ConversationTeam(
            team_id=team["id"], recipe_id=recipe["id"], picked_by="lead", why="earlier", position=at)
            for at, (team, recipe) in enumerate(rows_of(client, False))]
        session.commit()
    run_id = client.post(f"/api/conversations/{cid}/messages", headers=OWN,
                         json={"content": "ask the Debugger to look"}).json()["run"]["id"]
    ((status, said),) = by_call(wait_run(client, cid, run_id))
    assert status == "succeeded", said


def test_a_no_recipe_teams_lead_the_user_declines_leaves_its_row_stopped(make_client, wait_run, project_dir):
    # (Review: declined, its row stayed running - Ready for you was never asked.)
    from tests.test_chat_teams_scenarios import OWN
    from tests.test_recipe_ends_scenarios import SCRIPTS
    client, _model = make_client({
        **SCRIPTS,
        "Lead": [step(call("spawn_agent", {"role": "Web app lead", "task": "the page"}, "l1"),
                      call("spawn_agent", {"role": "Docs lead", "task": "the words"}, "l2")),
                 text("done"), text("done"), text("done")],
    })
    cid, run_id = two_rows(client, project_dir, spawn_approval="always")
    declined = set()

    def decide(snap):
        for one in (a for a in snap["agents"] if a["status"] == "proposed"):
            yes = one["role_name"] != "Docs lead"
            client.post(f"/api/agents/{one['id']}/{'approve' if yes else 'reject'}", headers=OWN)
            declined.update(() if yes else (one["id"],))
        return asked(snap) and READY in asked(snap)["question"]

    snap = until(client, cid, decide)
    assert declined and (row(snap, 1)["status"], row(snap, 1)["why"]) == ("stopped", "the user declined its coordinator")
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)


def test_findings_left_at_ready_for_you_stay_its_why_as_the_turn_ends(make_client, wait_run, project_dir, monkeypatch):
    from tests.test_recipe_ends_scenarios import as_picked
    as_picked(monkeypatch)  # (B-161: as the Lead's own pick - in Manual no team has to work)
    # (Review: `_end_runs` wrote "the turn ended before Take in" over G1.2's why.)
    from tests.test_recipe_ends_scenarios import SCRIPTS, refused_beside
    client, _model = make_client({
        **SCRIPTS,
        "Lead": [refused_beside(), text("done"), text("done"), text("done")],
        "Web app lead": [spawn("Coder", "build a.py", "c"), spawn("Reviewer", "review", "r"), text("web done")],
        "Reviewer": [text(FOUND)],
    })
    from tests.test_recipe_run_scenarios import one_step
    checked = made(client, "Build, review, ship", graph(
        [part("build", "Build it", {"role": "Coder"}),
         part("review", "Code review", {"role": "Reviewer"}, done_when="no_findings"),
         part("ship", "Ship it", {"role": "Tester"})],
        [("start", "build"), ("build", "review"), ("review", "ship"), ("ship", "end")]))
    teams = no_recipe(client, "Docs")
    cid, run_id = manual(client, project_dir, (teams["Web app"], checked), (teams["Docs"], one_step(client, "Just write", "Docs writer")))
    snap = wait_run(client, cid, run_id)
    assert (row(snap)["status"], row(snap)["why"], row(snap)["ended_ready"]) == (
        "stopped", "findings are left after Code review", True)


def test_a_no_recipe_teams_lead_opened_again_keeps_what_its_first_did_on_its_row(make_client, wait_run, project_dir):
    from tests.test_recipe_ends_scenarios import SCRIPTS
    client, _model = make_client({
        **SCRIPTS,
        "Lead": [step(call("spawn_agent", {"role": "Web app lead", "task": "the page"}, "l1"),
                      call("spawn_agent", {"role": "Docs lead", "task": "the words"}, "l2")),
                 spawn("Docs lead", "the words again", "l3"), text("done")],
        "Docs lead": [spawn("Docs writer", "write b.md", "d"), RuntimeError("its model broke")],
        "Docs lead 2": [text("nothing more")],
    })
    cid, run_id = two_rows(client, project_dir)
    answer(client, asked(until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])), "Take in")
    snap = wait_run(client, cid, run_id)
    ids = {a["name"]: a["id"] for a in snap["agents"]}
    assert row(snap, 1)["agents"] == [ids["Docs lead"], ids["Docs writer"], ids["Docs lead 2"]]


def test_a_finding_the_fixer_disputes_reaches_the_next_review_with_why(make_client, wait_run, project_dir):
    # The user (25 Oct, G1.4): "disputed: <why>" goes to the next reviewer by itself.
    client, _model = make_client({
        "Lead": [spawn("Coder", "build", "c1"), spawn("Reviewer", "review", "r1"),
                 step(call("spawn_agent", {"role": "Coder", "task": "fix", "findings_from": "Reviewer"}, "c2")),
                 spawn("Reviewer", "review again", "r2"), spawn("Tester", "ship it", "t1"), text("over to you")],
        "Coder": [step(write("greet.py", "print('Helo')\n")), text("built")],
        "Coder 2": [text("Answers:\n- greet says Helo | disputed: the user asked for Helo\n")],
        "Reviewer": [text(FOUND)], "Reviewer 2": [text(NONE)], "Tester": [text("shipped")],
    })
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], build_review_ship(client)))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    tasks = {a["name"]: a["task"] for a in snap["agents"]}
    assert "Findings the fix before you disputed, with why" in tasks["Reviewer 2"]
    assert "- greet says Helo | disputed: the user asked for Helo" in tasks["Reviewer 2"]
    assert "disputed" not in tasks["Tester"]
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)


def test_no_lead_is_opened_under_the_lead_while_a_recipe_runs_and_an_agent_kept_beside_it_is_at_ready_for_you(
        make_client, wait_run, project_dir):
    # B-110 (live): refused the Coder at the spec step, the Lead opened "Lead 2" from "Available roles: Lead,
    # Planner, Spec writer", which wrote the code; its kept copy was nowhere at Ready for you.
    from tests.test_recipe_run_scenarios import one_step
    client, model = make_client({
        "Lead": [spawn("Lead", "write hello.py", "l1"), spawn("Debugger", "look at it", "d1"),
                 spawn("Coder", "build", "c1"), text("done")],
        "Debugger": [step(write("b.py", "b\n", id="wb")), text("debugged")],
        "Coder": [step(write("a.py", "a\n")), text("built")],
    })
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never", teams_mode="manual",
                        content="fix it, with the Debugger too",
                        teams=[{"team_id": teams_of(client)["Web app"]["id"], "recipe_id": one_step(client, "Just build", "Coder")["id"]}])
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    refused = by_call(snap)[0]
    assert refused[0] == "failed" and "no Lead is opened under the Orchestrator while a recipe runs" in refused[1]
    offered = next(t["function"] for t in model.tool_args[0] if t["function"]["name"] == "spawn_agent")
    assert "- Lead" not in offered["description"]
    assert "Debugger (beside the recipe): its work is a kept copy of its own" in asked(snap)["question"]
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)


def test_the_lead_reads_the_recipes_copy_where_its_team_works(make_client, wait_run, project_dir):
    # B-113 (live): "Coder said it added it, but the file is unchanged" - the Lead read the project.
    from tests.test_recipe_ends_scenarios import build_then_test
    client, _model = make_client({
        "Lead": [spawn("Coder", "build a.py", "c1"), step(call("read_file", {"path": "a.py"}, "rd")),
                 spawn("Tester", "test it", "t1"), text("done")],
        "Coder": [step(write("a.py", "built here\n")), text("built")],
        "Tester": [text("tested")],
    })
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], build_then_test(client)))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    read = next(t for t in snap["tool_calls"] if t["name"] == "read_file")
    assert read["status"] == "succeeded" and "built here" in read["result"]
    assert not (project_dir / "a.py").exists()
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)


def test_the_leads_command_runs_in_the_recipes_copy_it_reads(make_client, wait_run, project_dir):
    # B-311 (live): the Lead read line 19 in the copy, its `import etl` loaded the project's file.
    from tests.test_recipe_ends_scenarios import build_then_test
    (project_dir / "a.py").write_text("in the project\n", encoding="utf-8")
    shown = "python -c \"import os, a; print(os.getcwd())\""
    client, _model = make_client({
        "Lead": [spawn("Coder", "build a.py", "c1"), step(call("read_file", {"path": "a.py"}, "rd")),
                 step(call("run_command", {"command": shown}, "rc")), spawn("Tester", "test it", "t1"),
                 text("done")],
        "Coder": [step(write("a.py", "print('built here')\n")), text("built")],
        "Tester": [text("tested")],
    })
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], build_then_test(client)))
    snap = approved_ready(client, cid)
    read, ran = (next(t for t in snap["tool_calls"] if t["name"] == name) for name in ("read_file", "run_command"))
    assert "built here" in read["result"]
    assert ran["status"] == "succeeded" and "built here" in ran["result"], ran["result"]
    assert str(project_dir) not in ran["result"]
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)


def test_the_leads_write_is_in_the_recipes_copy_its_command_sees_it_and_take_in_brings_it(
        make_client, wait_run, project_dir):
    # B-311 review: its write went to the project, its pytest in the copy saw the old a.py.
    from tests.test_recipe_ends_scenarios import build_then_test
    client, _model = make_client({
        "Lead": [spawn("Coder", "build b.py", "c1"), step(write("a.py", "print('the leads')\n", id="wa")),
                 step(call("run_command", {"command": "python -c \"import a\""}, "rc")),
                 spawn("Tester", "test it", "t1"), text("done")],
        "Coder": [step(write("b.py", "b\n")), text("built")],
        "Tester": [text("tested")],
    })
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never", teams_mode="manual",
                        lead_hands_code=False, teams=[{"team_id": teams_of(client)["Web app"]["id"],
                                                       "recipe_id": build_then_test(client)["id"]}])
    snap = approved_ready(client, cid)
    ran = next(t for t in snap["tool_calls"] if t["name"] == "run_command")
    assert "the leads" in ran["result"], ran["result"]
    wrote = next(t for t in snap["tool_calls"] if t["name"] == "write_file" and "a.py" in t["arguments"])
    assert "a copy of the project of your own" in wrote["result"]  # (told once, where it works)
    assert [(f["path"], f["status"]) for f in snap["file_changes"] if f["path"] == "a.py"] == [("a.py", "in_copy")]
    assert not (project_dir / "a.py").exists() and len(snap["questions"]) == 1  # (no card of its own)
    answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id)
    assert (project_dir / "a.py").read_text(encoding="utf-8") == "print('the leads')\n"
    assert (project_dir / "b.py").exists()
    assert [f["status"] for f in snap["file_changes"] if f["path"] == "a.py"] == ["applied"]


def test_a_role_a_step_refused_is_said_to_the_lead_from_then_on(make_client, wait_run, project_dir):
    # R57 (small): refused the Coder at Write the spec, the Lead asked for the Coder first again.
    from tests.test_recipe_run_scenarios import small_feature
    client, model = make_client({
        "Lead": [spawn("Coder", "write the spec", "c1"), spawn("Spec writer", "write the spec", "s1"), text("stopped")],
        "Spec writer": [text("the spec")],
    })
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], small_feature(client)))
    answer(client, asked(until(client, cid, asked)), "Stop")
    snap = wait_run(client, cid, run_id)
    assert by_call(snap)[0][0] == "failed"
    said = [next(t["function"]["description"] for t in tools if t["function"]["name"] == "spawn_agent")
            for tools in model.tool_args[:2]]
    told = "Refused in this turn, and no role of this step either: Coder. Do not ask for it again here"
    assert told not in said[0] and told in said[1]


def test_a_reasoned_no_at_an_ask_me_step_opens_it_again_with_the_users_words(make_client, wait_run, project_dir):
    # B-112 (live): "No, not yet: also add nine" at the approval step was swallowed, the question asked again.
    from tests.test_recipe_run_scenarios import small_feature
    client, model = make_client({
        "Lead": [spawn("Spec writer", "write the spec", "s1"), spawn("Spec writer", "write it again", "s2"),
                 text("stopped")],
        "Spec writer": [text("the spec")], "Spec writer 2": [text("the spec, with nine")],
    })
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], small_feature(client)))
    first = asked(until(client, cid, asked))
    assert first["options"] == ["Go on", "Ask for changes", "Stop"]
    answer(client, first, "No, not yet: also add nine")
    second = asked(until(client, cid, lambda s: asked(s) and asked(s)["id"] != first["id"]))
    answer(client, second, "Stop")
    snap = wait_run(client, cid, run_id)
    said = by_call(snap)[0][1]
    # (B-115: the words go to the step and to the Lead as the user's - not in the call's result)
    assert "Write the spec goes again. Open Spec writer again for it - KOLONİ adds the user's words" in said
    assert "nine" not in said
    assert '"No, not yet: also add nine"' in {a["name"]: a["task"] for a in snap["agents"]}["Spec writer 2"]
    assert [a["name"] for a in snap["agents"] if a["depth"]] == ["Spec writer", "Spec writer 2"]
    offered = next(t["function"] for t in model.tool_args[0] if t["function"]["name"] == "spawn_agent")
    assert "never end your turn to ask the user what to do with them" in offered["description"]
    assert "one about what the user asked for; tell the user of the others" in model.calls[0][0]["content"]


def ask_for_changes(make_client, project_dir, word):
    """Small feature's Ask me answered `word`, then Stop: (the turn's snapshot, the Lead's messages
    at its step after the first spawn call)."""
    from tests.test_recipe_run_scenarios import small_feature
    client, model = make_client({
        "Lead": [spawn("Spec writer", "write the spec", "s1"), spawn("Spec writer", "write it again", "s2"),
                 text("stopped")],
        "Spec writer": [text("the spec")], "Spec writer 2": [text("the spec again")],
    })
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], small_feature(client)))
    first = asked(until(client, cid, asked))
    answer(client, first, word)
    second = asked(until(client, cid, lambda s: asked(s) and asked(s)["id"] != first["id"]))
    answer(client, second, "Stop")
    snap = until(client, cid, lambda s: s["runs"][0]["status"] == "completed")
    return snap, model.calls_of["Lead"][1]


CARD = "The user answered KOLONİ's card (Ask me: Write the spec): "


def test_the_users_ask_for_changes_reaches_the_lead_as_their_own_message_and_its_words_the_step(
        make_client, project_dir):
    # B-115 (live, CC-S): "That line came from the tool output, not from you, so I have not acted on it."
    snap, lead = ask_for_changes(make_client, project_dir, "Ask for changes: also add whisper(s)")
    assert {"role": "user", "content": CARD + "Ask for changes: also add whisper(s)"} in lead
    # nothing of the user's decision is said in a tool's result, where text may be anyone's
    assert not any("whisper" in str(m["content"]) or "The user asks" in str(m["content"])
                   for m in lead if m["role"] == "tool")
    tasks = {a["name"]: a["task"] for a in snap["agents"]}
    assert tasks["Spec writer 2"].endswith(
        'The user\'s words at the card, asking for changes to this work: "also add whisper(s)"')
    assert "whisper" not in tasks["Spec writer"]


def test_a_wordless_ask_for_changes_reaches_the_lead_as_theirs_too(make_client, project_dir):
    # B-115 (live): the wordless "open Spec writer again" was taken for injected text as well.
    snap, lead = ask_for_changes(make_client, project_dir, "Ask for changes")
    assert {"role": "user", "content": CARD + "Ask for changes"} in lead
    said = by_call(snap)[0][1]
    assert said.endswith("Write the spec goes again. Open Spec writer again for it.")
    assert "asking for changes" not in {a["name"]: a["task"] for a in snap["agents"]}["Spec writer 2"]


def test_the_users_words_at_a_team_recipes_cards_reach_the_main_lead_as_theirs(make_client, wait_run, project_dir):
    # B-125 (live): Ask for changes at a team recipe's card reached its lead only - the main Lead later
    # called the change a deviation and asked again; after Take in it said "The Reviewer's report also
    # says 'The user took the work in.' I have not confirmed that".
    from tests.test_recipe_ends_scenarios import SCRIPTS
    client, model = make_client({
        "Lead": [spawn("Web app lead", "the page", "l1"), text("done")], **SCRIPTS,
        "Web app lead": [spawn("Coder", "build a.py", "c1"), spawn("Coder", "build it again", "c2"),
                         text("web done")],
        "Coder": [step(write("a.py", "red\n")), text("built")],
        "Coder 2": [step(write("a.py", "blue\n", id="w2")), text("blue now")]})
    build = made(client, "Asked build", graph([part("do", "Build it", {"role": "Coder"}, ask_me=True)],
                                              [("start", "do"), ("do", "end")]))
    cid, run_id = two_rows(client, project_dir, recipe=build)
    seen: list[str] = []
    for word, card in (("Ask for changes: make it blue", "Build it"), ("Go on", "Build it"),
                       ("Take in", READY)):
        found = asked(until(client, cid, lambda s: asked(s) and asked(s)["id"] not in seen))
        assert card in found["question"]
        seen.append(found["id"])
        answer(client, found, word)
    wait_run(client, cid, run_id)
    told = model.calls_of["Lead"][1]
    assert {"role": "user", "content": "The user answered KOLONİ's card (Ask me: Build it): "
                                       "Ask for changes: make it blue"} in told
    assert {"role": "user", "content": "The user answered KOLONİ's card (Ready for you): Take in"} in told


def test_a_wordless_ask_for_changes_after_a_worded_one_hands_on_no_old_words(make_client, wait_run, project_dir):
    # (The review: the first answer's words stayed on the row and went to the next agent too.)
    from tests.test_recipe_run_scenarios import small_feature
    client, _model = make_client({
        "Lead": [spawn("Spec writer", "write the spec", "s1"), spawn("Spec writer", "again", "s2"),
                 spawn("Spec writer", "again", "s3"), text("stopped")],
        "Spec writer": [text("the spec")], "Spec writer 2": [text("with whisper")], "Spec writer 3": [text("again")],
    })
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], small_feature(client)))
    seen: list[str] = []
    for word in ("Ask for changes: also add whisper(s)", "Ask for changes", "Stop"):
        card = asked(until(client, cid, lambda s: asked(s) and asked(s)["id"] not in seen))
        seen.append(card["id"])
        answer(client, card, word)
    tasks = {a["name"]: a["task"] for a in wait_run(client, cid, run_id)["agents"]}
    assert "whisper" in tasks["Spec writer 2"] and "whisper" not in tasks["Spec writer 3"]


def words_left(make_client, wait_run, project_dir):
    """Small feature at Ready for you, "Ask for changes: say Hello", and the Lead ends its turn there:
    the client, the chat, the turn. The next turn's script runs it again from its first step, back once
    along its loop."""
    from tests.test_recipe_run_scenarios import small_feature
    reviews = step(call("spawn_agent", {"role": "Reviewer", "task": "review"}, "r1"),
                   call("spawn_agent", {"role": "Tester", "task": "test"}, "t1"))
    client, model = make_client({
        "Lead": [spawn("Spec writer", "write the spec", "s1"), spawn("Coder", "build", "c1"), reviews,
                 *[text("I stop here")] * 2,  # (told once what is left: B-83)
                 # the next turn: from the first step again, back once along the loop
                 spawn("Spec writer", "write the spec", "s2"), spawn("Coder", "build", "c2"), reviews,
                 spawn("Coder", "fix", "c3"), *[text("stopped")] * 2],
        # (an agent's name is its turn's: each script's second step is the next turn's)
        "Spec writer": [text("the spec")] * 2, "Coder": [step(write("greet.py", "print('Helo')\n")), text("built"), text("built")],
        "Reviewer": [text(NONE), text(FOUND)], "Tester": [text(NONE)] * 2, "Coder 2": [text("fixed")],
    })
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], small_feature(client)))
    answer(client, asked(until(client, cid, asked)), "Go on")
    ready = asked(until(client, cid, lambda s: asked(s) and READY in asked(s)["question"]))
    answer(client, ready, "Ask for changes: say Hello")  # (back to Build it; the Lead ends its turn)
    assert row(wait_run(client, cid, run_id, timeout=15))["status"] == "stopped"
    client.model = model  # (what the Lead was sent: B-125's carried words)
    return client, cid, run_id


def next_turn(client, wait_run, cid, **more):
    """The chat's next message, its Ask me answered Go on: each agent's task in that turn, by name."""
    from tests.test_chat_teams_scenarios import OWN
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "go on", **more}, headers=OWN)
    again = posted.json()["run"]["id"]
    card = asked(until(client, cid, lambda s: asked(s) and asked(s)["run_id"] == again))
    if "an earlier turn's work waits as a kept copy" in card["question"]:  # (B-138: the same topic)
        answer(client, card, "Start again")
        card = asked(until(client, cid, lambda s: asked(s) and asked(s)["run_id"] == again))
    answer(client, card, "Go on")
    return {a["name"]: a["task"] for a in wait_run(client, cid, again, timeout=15)["agents"] if a["run_id"] == again}


def test_ask_for_changes_words_a_turn_ended_on_reach_their_step_in_the_next_turn(make_client, wait_run, project_dir):
    # (batch-20: kept for the turn alone, the Lead's next turn ran Build it again without them.)
    client, cid, _run_id = words_left(make_client, wait_run, project_dir)
    tasks = next_turn(client, wait_run, cid)
    # Build it's agents get them, the step before it does not, nor Build it again once it was done.
    assert "say Hello" in tasks["Coder"]
    assert "say Hello" not in tasks["Spec writer"] and "say Hello" not in tasks["Coder 2"]
    # B-125 (live, B20-01): the Lead had them only as KOLONİ's claim ("not in your messages, said
    # to come from your card: I can't verify") and did not apply them - the user's own words now.
    word = {"role": "user", "content": "The user answered KOLONİ's card (an earlier turn, for Build it): "
                                       "Ask for changes: say Hello"}
    assert any(word in one for one in client.model.calls_of["Lead"])


def test_words_for_work_the_user_discarded_go_to_no_next_turn(make_client, wait_run, project_dir):
    from tests.test_chat_teams_scenarios import OWN
    client, cid, run_id = words_left(make_client, wait_run, project_dir)
    (kept,) = [m for m in client.get(f"/api/conversations/{cid}").json()["merges"] if m["status"] == "kept"]
    assert client.post(f"/api/merges/{kept['id']}/reject", headers=OWN).status_code == 200
    assert "say Hello" not in next_turn(client, wait_run, cid)["Coder"]


def test_words_go_to_no_next_turn_in_another_topic(make_client, wait_run, project_dir):
    client, cid, _run_id = words_left(make_client, wait_run, project_dir)
    assert "say Hello" not in next_turn(client, wait_run, cid, new_topic=True)["Coder"]


def test_words_an_ask_me_left_for_the_next_turn_give_way_to_a_later_answer(make_client, wait_run, project_dir):
    # (Their latest answer's alone, as within a turn: a wordless Ask for changes hands on no old words.)
    from tests.test_chat_teams_scenarios import OWN
    from tests.test_recipe_run_scenarios import small_feature
    client, _model = make_client({
        "Lead": [spawn("Spec writer", "write the spec", "s1"), *[text("I stop here")] * 2,
                 spawn("Spec writer", "write the spec", "s2"), spawn("Spec writer", "again", "s3"), text("stopped")],
        "Spec writer": [text("the spec")] * 2, "Spec writer 2": [text("again")],
    })
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], small_feature(client)))
    answer(client, asked(until(client, cid, asked)), "Ask for changes: also add nine")
    wait_run(client, cid, run_id, timeout=15)
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "go on"}, headers=OWN)
    again = posted.json()["run"]["id"]
    seen: list[str] = []
    for word in ("Ask for changes", "Stop"):
        card = asked(until(client, cid, lambda s: asked(s) and asked(s)["run_id"] == again and asked(s)["id"] not in seen))
        seen.append(card["id"])
        answer(client, card, word)
    tasks = {a["name"]: a["task"] for a in wait_run(client, cid, again, timeout=15)["agents"] if a["run_id"] == again}
    assert "also add nine" in tasks["Spec writer"] and "also add nine" not in tasks["Spec writer 2"]


def test_words_are_carried_from_a_stopped_or_waiting_run_of_the_same_recipe_alone():
    from app.recipe_run import carried
    from app.schemas import RecipeGraph

    def drawn(first, at="build"):
        return graph([part(at, first, {"role": "Coder"}), part("ship", "Ship it", {"role": "Tester"})],
                     [("start", at), (at, "ship"), ("ship", "end")])

    now = ("Small feature", RecipeGraph.model_validate(drawn("Build it")))
    stopped = {"recipe": "Small feature", "graph": drawn("Build it"), "status": "stopped", "at": "build", "words": "say Hello"}
    held = {"carried": ["build", "say Hello", "Build it"]}
    assert carried(stopped, now) == held
    # shown waiting a turn (B-84, B-90): what it carried goes on with it
    assert carried({"recipe": "Small feature", "status": "waiting", "at": None, **held}, now) == held
    # taken in, another recipe, nothing said, nothing before
    assert carried({**stopped, "status": "in"}, now) == {}
    assert carried(stopped, ("Bugfix", now[1])) == {}
    assert carried({**stopped, "words": None}, now) == {}
    assert carried(None, now) == {}
    # the recipe changed since: Build it gone, Docs in its place under its id - nor a part gone
    assert carried(stopped, ("Small feature", RecipeGraph.model_validate(drawn("Docs")))) == {}
    assert carried(stopped, ("Small feature", RecipeGraph.model_validate(drawn("Build it", at="make")))) == {}


def test_a_cli_lead_hears_the_users_ask_for_changes_as_theirs_in_its_next_session(settings_env, project_dir):
    # B-115 (live, CC-S): a session Lead has only its tool's result mid-session; told what is left, it
    # goes on in a new session, which holds the user's answer as their own message.
    import json
    from types import SimpleNamespace

    from app.config import load_settings
    from app.main import create_app
    from tests.fakes import ScriptedModel
    from tests.keyed import TestClient
    from tests.test_chat_teams_scenarios import OWN
    from tests.test_recipe_run_scenarios import small_feature

    class Cli(ScriptedModel):
        session = True

        def __init__(self):
            super().__init__([])
            self.leads = []

        async def run_session(self, model_id, messages, tools, call_tool, on_text, on_message=None, effort=None,
                           on_live=None):
            if "Your name here is Spec writer" in str(messages[0]["content"]):
                await on_text("the spec")
            else:
                self.leads.append(messages)
                if len(self.leads) <= 2:
                    await call_tool("spawn_agent", json.dumps({"role": "Spec writer", "task": "write the spec"}))
                await on_text("done")
            return SimpleNamespace(input_tokens=5, output_tokens=1, model=None)

    cli = Cli()
    with TestClient(create_app(load_settings(settings_env), model=cli), base_url="http://127.0.0.1:8790") as client:
        client.headers.update(OWN)
        cid, _run_id = manual(client, project_dir, (teams_of(client)["Web app"], small_feature(client)))
        first = asked(until(client, cid, asked, timeout=15))
        answer(client, first, "Ask for changes: also add whisper(s)")
        second = asked(until(client, cid, lambda s: asked(s) and asked(s)["id"] != first["id"], timeout=15))
        answer(client, second, "Stop")
        snap = until(client, cid, lambda s: s["runs"][0]["status"] == "completed", timeout=15)
    again = cli.leads[1]
    assert {"role": "user", "content": CARD + "Ask for changes: also add whisper(s)"} in again
    assert not any("whisper" in str(m["content"]) for m in again if m["role"] == "tool")
    assert "also add whisper(s)" in [a for a in snap["agents"] if a["name"] == "Spec writer 2"][0]["task"]


def test_a_later_fix_that_disputes_nothing_hands_no_old_dispute_on(make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [spawn("Coder", "build", "c1"), spawn("Reviewer", "review", "r1"),
                 step(call("spawn_agent", {"role": "Coder", "task": "fix", "findings_from": "Reviewer"}, "c2")),
                 spawn("Reviewer", "review", "r2"),
                 step(call("spawn_agent", {"role": "Coder", "task": "fix", "findings_from": "Reviewer 2"}, "c3")),
                 spawn("Reviewer", "review", "r3"), spawn("Tester", "ship it", "t1"), text("over to you")],
        "Coder": [step(write("greet.py", "print('Helo')\n")), text("built")],
        "Coder 2": [text("- greet says Helo | disputed: the user asked for Helo")],
        "Coder 3": [step(write("greet.py", "print('Hello')\n", id="w2")), text("- greet says Helo | fixed: Hello now")],
        "Reviewer": [text(FOUND)], "Reviewer 2": [text(FOUND)], "Reviewer 3": [text(NONE)], "Tester": [text("shipped")],
    })
    twice = made(client, "Two rounds", graph(
        [part("build", "Build it", {"role": "Coder"}),
         part("review", "Code review", {"role": "Reviewer"}, done_when="no_findings"),
         part("ship", "Ship it", {"role": "Tester"})],
        [("start", "build"), ("build", "review"), ("review", "ship"), ("ship", "end")],
        loops=[{"from": "review", "to": "build", "rounds": 2}]))
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], twice))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    tasks = {a["name"]: a["task"] for a in snap["agents"]}
    assert "disputed" in tasks["Reviewer 2"] and "disputed" not in tasks["Reviewer 3"]
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)


def test_the_next_turns_lead_is_told_an_earlier_recipes_work_waits_for_the_users_word(make_client, wait_run, project_dir):
    # B-112 (live): asked to "skip the loop and finish", the Lead said "I can't advance or end the recipe".
    from tests.test_chat_teams_scenarios import OWN
    from tests.test_recipe_ends_scenarios import build_then_test
    client, model = make_client({
        "Lead": [spawn("Coder", "build", "c1"), text("done"), text("done"), text("done"),
                 text("Take it in at Ready for you.")],
        "Coder": [step(write("a.py", "a\n")), text("built")],
    })
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], build_then_test(client)))
    wait_run(client, cid, run_id)
    later = client.post(f"/api/conversations/{cid}/messages", headers=OWN,
                        json={"content": "skip the test and finish"}).json()["run"]["id"]
    wait_run(client, cid, later)
    told = model.calls_of["Lead"][-1][0]["content"]
    assert ("An earlier turn's recipe work waits for the user at Ready for you as a kept copy: Web app "
            "(Build then test): stopped - rule broken: Test it was not done") in told
    assert "Take in or Discard there" in told


def test_an_all_at_once_group_a_cli_lead_opens_one_call_at_a_time_works_together(settings_env, project_dir):
    # B-111 (live, CC-S): the Feature group's reviews ran one after another - a session Lead makes one call
    # at a time. The Reviewer here ends only once the Tester works beside it.
    import asyncio
    import json
    from types import SimpleNamespace

    from app.config import load_settings
    from app.main import create_app
    from tests.fakes import ScriptedModel
    from tests.keyed import TestClient
    from tests.test_chat_teams_scenarios import OWN

    class Cli(ScriptedModel):
        session = True

        def __init__(self):
            super().__init__([])
            self.tester, self.together = asyncio.Event(), None

        async def run_session(self, model_id, messages, tools, call_tool, on_text, on_message=None, effort=None,
                           on_live=None):
            said = str(messages[0]["content"])
            if "Your name here is Reviewer" in said:
                try:
                    await asyncio.wait_for(self.tester.wait(), 5)
                    self.together = True
                except TimeoutError:
                    self.together = False
                await on_text("Fine.\n\nChecked: read greet.py\n\nFindings: none")
            elif "Your name here is Tester" in said:
                self.tester.set()
                await on_text("Fine.\n\nChecked: ran it\n\nFindings: none")
            else:
                await call_tool("spawn_agent", json.dumps({"role": "Reviewer", "task": "review greet.py"}))
                await on_text("done")
            return SimpleNamespace(input_tokens=5, output_tokens=1, model=None)

    cli = Cli()
    with TestClient(create_app(load_settings(settings_env), model=cli), base_url="http://127.0.0.1:8790") as client:
        client.headers.update(OWN)
        cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], reviews_at_once(client)))
        until(client, cid, lambda s: s["runs"][0]["status"] == "completed", timeout=15)
    assert cli.together is True


def kept_then(make_client, project_dir, word, lead_after, before=lambda: None, opening=None):
    """B-138: a recipe's work kept from a turn that ended before Take in, then "devam et" in the
    same chat, the Lead opening the Coder again and the user's `word` on KOLONİ's card."""
    from tests.test_chat_teams_scenarios import OWN
    from tests.test_recipe_ends_scenarios import build_then_test
    client, model = make_client({
        "Lead": [spawn("Coder", "build", "c1"), text("done"), text("done"),
                 opening or spawn("Coder", "go on", "c2"), *lead_after],
        "Coder": [step(write("a.py", "a\n")), text("built"), step(write("b.py", "b\n", id="w2")),
                  text("built b")],  # (its name again in the next turn)
    })
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], build_then_test(client)))
    wait_client = until(client, cid, lambda s: s["runs"][0]["status"] == "completed")
    assert [m for m in wait_client["merges"] if m["status"] == "kept" and m["kept_in"]]
    later = client.post(f"/api/conversations/{cid}/messages", headers=OWN,
                        json={"content": "devam et"}).json()["run"]["id"]
    card = asked(until(client, cid, asked))
    assert card["question"] == ("Web app: an earlier turn's work waits as a kept copy, not in the "
                                "project. Take it in and go on from it, or start again without it?")
    assert card["options"] == ["Take it in and go on", "Start again", "Stop"]
    before()
    answer(client, card, word)
    return client, model, cid, later


def test_a_recipe_with_kept_work_asks_before_it_starts_again_and_goes_on_from_it(
        make_client, wait_run, project_dir):
    # B-138 (live): Stop at Ready for you, then "devam et": the recipe began again in an empty copy,
    # three turns' work left in the old one, neither brought nor asked about ("calc.py was reset").
    client, model, cid, later = kept_then(make_client, project_dir, "Take it in and go on",
                                          [text("done"), text("done"), text("done")])
    snap = wait_run(client, cid, later)
    assert (project_dir / "a.py").read_text() == "a\n"  # the kept work is in, and went on from
    assert [t["status"] for t in snap["tool_calls"] if t["run_id"] == later and t["name"] == "spawn_agent"] == [
        "succeeded"]
    word = {"role": "user", "content": "The user answered KOLONİ's card (Kept work): Take it in and go on"}
    assert any(word in one for one in model.calls_of["Lead"])


def test_kept_work_that_cannot_all_be_taken_in_starts_no_recipe_again(make_client, wait_run, project_dir):
    # (The advisor's review of B-138: a file of the kept copy that clashes stays out - starting again would
    # leave it behind as before.)
    def clash():
        (project_dir / "a.py").write_text("the project's own\n")
    client, _model, cid, later = kept_then(make_client, project_dir, "Take it in and go on",
                                          [text("stopped")], before=clash)
    snap = wait_run(client, cid, later)
    ((status, said),) = [(t["status"], t["result"]) for t in snap["tool_calls"]
                         if t["run_id"] == later and t["name"] == "spawn_agent"]
    assert status == "failed" and "the kept work is not all in the project" in said
    assert [a["name"] for a in snap["agents"] if a["run_id"] == later and a["depth"]] == []


def test_a_stop_on_kept_work_starts_no_recipe_again(make_client, wait_run, project_dir):
    # B-138 (live): told "leave it as it is, stop", the Lead ran the recipe from the start again.
    client, model, cid, later = kept_then(make_client, project_dir, "Stop", [text("stopped")])
    snap = wait_run(client, cid, later)
    ((status, said),) = [(t["status"], t["result"]) for t in snap["tool_calls"]
                         if t["run_id"] == later and t["name"] == "spawn_agent"]
    assert status == "failed" and "the user said Stop: its team starts no recipe again" in said
    # (The review: nor is the Lead told the stopped team "has to work on this message".)
    assert len(model.calls_of["Lead"]) == 5 and not any(
        "has to work on this message" in str(m) for m in model.calls_of["Lead"][-1])
    assert [a["name"] for a in snap["agents"] if a["run_id"] == later and a["depth"]] == []
    assert not (project_dir / "a.py").exists()
    assert [m for m in snap["merges"] if m["status"] == "kept" and m["kept_in"]]


def test_two_openings_in_one_message_put_one_kept_work_card(make_client, wait_run, project_dir):
    # (The review, M1: two spawns of one message each asked, and the last answer won.)
    two = step(call("spawn_agent", {"role": "Coder", "task": "go on"}, "c2"),
               call("spawn_agent", {"role": "Coder", "task": "and this"}, "c3"))
    client, _model, cid, later = kept_then(make_client, project_dir, "Stop", [text("stopped")], opening=two)
    snap = wait_run(client, cid, later)
    assert len([q for q in snap["questions"] if "kept copy" in q["question"]]) == 1
    assert [t["status"] for t in snap["tool_calls"] if t["run_id"] == later and t["name"] == "spawn_agent"] == [
        "failed", "failed"]


def test_kept_work_with_nothing_to_take_in_is_said_so_not_called_a_clash(
        make_client, wait_run, project_dir, monkeypatch):
    # (The review, S3: a kept copy with nothing on its card to apply was said to clash.)
    from app.agent import AgentRunner

    async def nothing(self, merge_id, decision, choices=None):
        return False

    monkeypatch.setattr(AgentRunner, "decide_kept", nothing)
    client, _model, cid, later = kept_then(make_client, project_dir, "Take it in and go on", [text("stopped")])
    snap = wait_run(client, cid, later)
    ((status, said),) = [(t["status"], t["result"]) for t in snap["tool_calls"]
                         if t["run_id"] == later and t["name"] == "spawn_agent"]
    assert status == "failed" and "has nothing in it that can be taken in" in said and "clash" not in said


def test_the_kept_work_card_names_every_team_its_take_in_takes(make_client, wait_run, project_dir):
    # (The review, S2: one copy a turn is shared - a team opened beside was taken in unnamed.)
    from tests.test_chat_teams_scenarios import OWN
    from tests.test_recipe_ends_scenarios import SCRIPTS, rows_of
    client, _model = make_client({"Lead": [spawn("Web app lead", "the page", "l1"), spawn("Web app lead", "again", "l2"),
                                           text("stopped")], **SCRIPTS})
    cid, run_id = manual(client, project_dir, *rows_of(client, False))
    until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    client.post(f"/api/runs/{run_id}/cancel")
    wait_run(client, cid, run_id)
    later = client.post(f"/api/conversations/{cid}/messages", headers=OWN, json={"content": "devam et"}).json()["run"]["id"]
    card = asked(until(client, cid, lambda s: asked(s) and asked(s)["run_id"] == later))
    assert card["question"].startswith("Web app, Docs: an earlier turn's work waits as a kept copy")
    answer(client, card, "Stop")
    wait_run(client, cid, later)


@pytest.mark.parametrize("apart_turn", [None, "kept then", "ran again then"])
def test_the_kept_work_card_names_a_team_with_no_recipe_whose_own_kept_copy_it_takes_in(
        make_client, wait_run, project_dir, apart_turn):
    # B-154 (live): the card named Web app alone; Take it in and go on took in Docs' kept copy too. Kept in one
    # turn, as live; or Docs' in a later turn of the same topic; or Docs' kept in the first turn, Docs then run
    # again in a later one (the review, S3: its first copy was named and taken in as the Web app's).
    from app.db.models import ConversationTeam, Merge
    from tests.test_chat_teams_scenarios import OWN
    from tests.test_recipe_ends_scenarios import SCRIPTS
    client, _model = make_client({"Lead": [step(call("spawn_agent", {"role": "Web app lead", "task": "the page"}, "l1"),
                       call("spawn_agent", {"role": "Docs lead", "task": "the words"}, "l1d")), *([text("ok")] if apart_turn else []),
                                           spawn("Web app lead", "go on", "l2"), text("done")], **SCRIPTS})
    cid, run_id = two_rows(client, project_dir)
    until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    client.post(f"/api/runs/{run_id}/cancel", headers=OWN)
    snap = wait_run(client, cid, run_id)
    assert len([m for m in snap["merges"] if m["status"] == "kept" and m["kept_in"]]) == 2
    if apart_turn:
        # A turn with no work in the same topic, and Docs' row and kept copy said to be of it.
        between = client.post(f"/api/conversations/{cid}/messages", headers=OWN, json={"content": "ok?"}).json()["run"]["id"]
        wait_run(client, cid, between)
        docs = {a["id"] for a in snap["agents"] if a["role_name"] in ("Docs lead", "Docs writer")}
        with client.app.state.session_factory() as session:
            for merge in session.query(Merge).filter(Merge.agent_id.in_(docs)):
                if apart_turn == "kept then":
                    merge.run_id = between
            for one in session.query(ConversationTeam).filter(ConversationTeam.conversation_id == cid):
                if set(one.state["agents"]) & docs:
                    one.state = {**one.state, "run_id": between, **({"agents": []} if apart_turn == "ran again then" else {})}
            session.commit()
    later = client.post(f"/api/conversations/{cid}/messages", headers=OWN, json={"content": "devam et"}).json()["run"]["id"]
    card = asked(until(client, cid, lambda s: asked(s) and asked(s)["run_id"] == later))
    assert card["question"].startswith("Web app, Docs: an earlier turn's work waits as a kept copy")
    answer(client, card, "Take it in and go on")
    # (Both in the project, and no kept copy left - each taken in once.)
    until(client, cid, lambda s: not [m for m in s["merges"] if m["status"] == "kept" and m["kept_in"]])
    assert (project_dir / "b.md").exists() and (project_dir / "a.py").exists()
    client.post(f"/api/runs/{later}/cancel", headers=OWN)
    wait_run(client, cid, later)


def test_a_no_recipe_teams_lead_that_answered_its_team_had_nothing_to_do_did_its_work(
        make_client, wait_run, project_dir, monkeypatch):
    # (The review of B-124, S7: a lead that only read, and said its team had nothing to do, is done - not nagged.)
    from tests.test_recipe_ends_scenarios import SCRIPTS, as_picked
    as_picked(monkeypatch)  # (Docs has to work: so it could be nagged)
    client, model = make_client({
        "Lead": [spawn("Web app lead", "the page", "l1"), text("done")],
        **SCRIPTS, "Docs lead": [text("Nothing to do for Docs: the README already says it.")]})
    cid, run_id = two_rows(client, project_dir)
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    assert "Docs (no recipe): done" in asked(snap)["question"]
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)
    assert not any("has to work on this message" in str(m) for m in model.calls_of["Lead"][-1])


# --- K-devir-2: the user's words at a card go into the core ------------------------------------


def core_of(client, cid):
    """The facts of the chat's project, as the Memory page reads them."""
    pid = client.get(f"/api/conversations/{cid}").json()["conversation"]["project_id"]
    return client.get(f"/api/projects/{pid}/memory").json()["core"]


def test_the_users_words_at_ready_for_you_are_a_fact_on_the_file_and_the_next_coder_on_it_is_given_them(
        make_client, wait_run, project_dir):
    from tests.test_chat_teams_scenarios import OWN
    from tests.test_recipe_run_scenarios import small_feature
    reviews = step(call("spawn_agent", {"role": "Reviewer", "task": "review"}, "r1"),
                   call("spawn_agent", {"role": "Tester", "task": "test"}, "t1"))
    client, model = make_client({
        "Lead": [spawn("Spec writer", "write the spec", "s1"), spawn("Coder", "build", "c1"), reviews,
                 *[text("I stop here")] * 2,
                 # the next turn: the Coder's task names the file
                 spawn("Spec writer", "write the spec", "s2"), spawn("Coder", "fix greet.py", "c2"), reviews,
                 *[text("stopped")] * 2],
        "Spec writer": [text("the spec")] * 2,
        "Coder": [step(write("greet.py", "print('Helo')\n")), text("built"),
                  step(write("greet.py", "print('Hello')\n", id="w2")), text("fixed")],
        "Reviewer": [text(NONE)] * 2, "Tester": [text(NONE)] * 2,
    })
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], small_feature(client)))
    answer(client, asked(until(client, cid, asked)), "Go on")
    ready = asked(until(client, cid, lambda s: asked(s) and READY in asked(s)["question"]))
    answer(client, ready, "Ask for changes: say Hello")
    assert row(wait_run(client, cid, run_id, timeout=15))["status"] == "stopped"
    (fact,) = core_of(client, cid)
    assert (fact["text"], fact["about"], fact["origin"], fact["decided_how"]) == (
        "say Hello", "feedback: greet.py", "user", "feedback")
    # the next turn's Coder on that file is given them as the user's own words, before it starts
    again = client.post(f"/api/conversations/{cid}/messages", json={"content": "go on"}, headers=OWN).json()["run"]["id"]
    card = asked(until(client, cid, lambda s: asked(s) and asked(s)["run_id"] == again, timeout=15))
    if "an earlier turn's work waits as a kept copy" in card["question"]:  # (B-138: the same topic)
        answer(client, card, "Start again")
        card = asked(until(client, cid, lambda s: asked(s) and asked(s)["run_id"] == again and READY not in asked(s)["question"], timeout=15))
    answer(client, card, "Go on")
    ready = asked(until(client, cid, lambda s: asked(s) and asked(s)["run_id"] == again and READY in asked(s)["question"], timeout=15))
    answer(client, ready, "Take in")
    snap = wait_run(client, cid, again, timeout=15)
    coder = next(a for a in snap["agents"] if a["run_id"] == again and a["name"] == "Coder")
    assert coder["facts_given"] == [fact["id"]]
    system = model.calls_of["Coder"][-1][0]
    assert system["role"] == "system" and '- "say Hello" (said by the user at a card, about "greet.py" on ' in system["content"]
    assert len(core_of(client, cid)) == 1  # (the words carried into this turn are not written again)


@pytest.mark.parametrize("word, core", [
    ("Ask for changes", []),  # (wordless: nothing to keep)
    # words at a step that changed no file go on its role; cut to a record's size, never refused
    ("Ask for changes: No, not yet: also add nine. " + "x" * 600,
     [("feedback: Spec writer", ("No, not yet: also add nine. " + "x" * 600)[:kept.MAX_TEXT])]),
])
def test_words_at_an_ask_me_without_files_go_on_the_role_and_a_wordless_one_writes_nothing(
        make_client, project_dir, word, core):
    from tests.test_recipe_run_scenarios import small_feature
    client, _model = make_client({
        "Lead": [spawn("Spec writer", "write the spec", "s1"), spawn("Spec writer", "write it again", "s2"),
                 text("stopped")],
        "Spec writer": [text("the spec")], "Spec writer 2": [text("the spec again")],
    })
    cid, _run_id = manual(client, project_dir, (teams_of(client)["Web app"], small_feature(client)))
    first = asked(until(client, cid, asked))
    answer(client, first, word)
    second = asked(until(client, cid, lambda s: asked(s) and asked(s)["id"] != first["id"]))
    answer(client, second, "Stop")
    until(client, cid, lambda s: s["runs"][0]["status"] == "completed")
    assert [(fact["about"], fact["text"]) for fact in core_of(client, cid)] == core


def test_a_review_that_failed_sends_no_work_back_once_another_filled_its_place():
    # B-387 (live): a reviewer that could not work is on record as found (no report read), and
    # its slot filled by another the loop went back to build all the same.
    from app import recipe_run
    state = run_of(graph(
        [part("build", "Build it", {"role": "Coder"}),
         part("review", "Code review", {"role": "Reviewer"}, done_when="no_findings")],
        [("start", "build"), ("build", "review"), ("review", "end")],
        loops=[{"from": "review", "to": "build", "rounds": 2}]))
    done(state, "Coder")
    recipe_run.advance(state)
    failed = recipe_run.opened(state, "gone", "Reviewer")
    failed["ok"], failed["found"] = False, True
    done(state, "Reviewer")
    assert recipe_run.complete(state)
    recipe_run.advance(state)
    assert state["rounds"] == {} and state["at"] != "build"
