"""Slice 84c's edges: what the acceptance set (tests/test_findings_scenarios.py) leaves open."""

import pytest

from app.agent import (
    MAX_FINDINGS,
    MAX_WHAT,
    _carried,
    _checked,
    _failing_before,
    _findings,
    _hand_on,
    _handed_findings,
)
from tests.test_agent_talk import message
from tests.test_chat_flow import text
from tests.test_discussion import discuss
from tests.test_findings_scenarios import REPORT, agent, run
from tests.test_spawn import begin, call, role_id, spawn, step

ORIGIN = {"Origin": "http://127.0.0.1:8790"}
ROLES = ["Coder", "UI designer"]


# --- the reader --------------------------------------------------------------------


def test_a_report_s_findings_are_read_within_bounds():
    report = "Many.\n\n**Findings:**\n" + "\n".join(f"- {'x' * 900} {n} | kind: CODE" for n in range(60))
    found = _findings(report, [])
    assert len(found) == MAX_FINDINGS
    assert found[0] == {"what": "x" * MAX_WHAT, "kind": "code", "role": None, "blocking": True}
    # a line however long is cut before it is read
    assert _findings("## Findings\n- " + "x|" * 100_000, []) is None


def test_the_section_ends_at_the_next_heading_or_fence():
    found = _findings("## Findings\n- a | kind: code | role: coder\n\n## Summary\nAll good. | kind: ui",
                      ROLES)
    assert found == [{"what": "a", "kind": "code", "role": "Coder", "blocking": True}]
    fenced = "## Findings\n- a | kind: ui\n```\n- b | kind: code\n```"
    assert [f["what"] for f in _findings(fenced, ROLES)] == ["a"]


def test_a_findings_heading_inside_a_fenced_block_opens_nothing():
    assert _findings("Like this:\n```md\n## Findings\n- x | kind: code\n```\nDone.", ROLES) is None
    assert _findings("~~~\nFindings: none\n~~~", ROLES) is None


def test_a_line_on_the_heading_itself_is_read_like_the_rest():
    assert _findings("Findings: greet is wrong | kind: code | role: Coder", ROLES) == [
        {"what": "greet is wrong", "kind": "code", "role": "Coder", "blocking": True}]


@pytest.mark.parametrize("report", [
    "## Findings\n- No issues found.", "Findings: None.", "**Findings:** no problems",
    "## Findings\n\nNo findings!", "Findings:\n1. none found",
])
def test_nothing_found_said_in_other_words_is_an_empty_list(report):
    assert _findings(report, ROLES) == []


def test_what_a_review_checked_is_no_finding_and_is_read_apart():
    # G1.5: the `Checked:` line a recipe's review gives, after its findings too.
    assert _findings("Findings: none\n- Checked: ran pytest, 3 passed", ROLES) == []
    assert _checked("Fine.\n**Checked:** read greet.py\n\nFindings: none")
    assert not _checked("Fine.\nChecked:\n\nFindings: none") and not _checked("Findings: none")
    # (Nothing checked is no check, nor one inside a fenced block it quotes.)
    assert not _checked("Checked: nothing.\nFindings: none")
    assert not _checked("Like this:\n```\nChecked: read a.py\n```\nFindings: none")


def test_what_was_already_failing_before_is_no_finding():
    # B-117 (live): the Tester wrote two old broken tests as findings and the loop stuck on them.
    report = ("## Findings\n- greet says Helo | kind: code | role: Coder\n"
              "- Already failing before: test_calc, test_cart | kind: test | role: Coder")
    assert [f["what"] for f in _findings(report, ROLES)] == ["greet says Helo"]
    assert _findings("Already failing before: test_calc\n\nFindings: none", ROLES) == []
    # (inside the section, before a real finding - with its bullet or not - it loses none of them)
    for line in ("- Already failing before: x | kind: test | role: Coder", "Already failing before: x"):
        found = _findings(f"## Findings\n{line}\n- real bug | kind: code | role: Coder", ROLES)
        assert [f["what"] for f in found] == ["real bug"]
    assert _findings("## Findings\n- Already failing before: x", ROLES) == []


def test_a_finding_marked_as_failing_before_in_its_own_line_is_no_finding():
    # B-387 (live): "do_HEAD bypasses authentication", marked as not caused by the change,
    # opened another build round.
    report = ("## Findings\n1. Already failing before: old test | kind: test | role: Coder\n"
              "- greet is slow (already failing before) | kind: code | role: Coder\n"
              "- **Pre-existing:** x is slow | kind: code | role: Coder\n"
              "- y (pre-existing) | kind: ui | role: Coder | blocking")
    assert _findings(report, ROLES) == []
    assert _failing_before(report) == [
        "old test | kind: test | role: Coder", "greet is slow (already failing before)",
        "**Pre-existing:** x is slow", "y (pre-existing)"]


@pytest.mark.parametrize("line", [
    # (security stays blocking, marked or not - review of B-387)
    "do_HEAD skips auth (already failing before) | kind: security | role: Coder",
    "Pre-existing: a key in the log | kind: security | role: Coder",
    # (a failure of its own besides the mark)
    "test_greet fails (pre-existing) | kind: test | role: Coder",
    # (no mark: the words are only about something that was there before)
    "Pre-existing tests now fail after this change | kind: test | role: Coder | blocking",
    "**Pre-existing** callers of greet() now crash | kind: bug | role: Coder",
    "Cache breaks (preexisting entries are not invalidated) | kind: bug | role: Coder",
    "test_x fails | kind: test | role: Coder | pre-existing? no, new | blocking",
    "this breaks the pre-existing tests | kind: test | role: Coder",
    "test_greet fails (it was not already failing before) | kind: test | role: Coder",
])
def test_what_stays_a_blocking_finding_though_it_names_what_was_before(line):
    (found,) = _findings(f"## Findings\n- {line}", ROLES)
    assert found["blocking"] and not _failing_before(f"## Findings\n- {line}")


def test_at_a_recipes_step_a_finding_for_no_role_of_it_goes_to_its_first_role_only():
    # B-117's review: handed to every role of the step, each fixed it.
    found = [{"what": "own", "kind": "code", "role": "Reviewer"}, {"what": "stray", "kind": "test", "role": "Tester"}]
    step = ["coder", "reviewer"]
    assert "stray" in _carried(found, "Coder", step) and "own" not in _carried(found, "Coder", step)
    assert "stray" not in _carried(found, "Reviewer", step) and "own" in _carried(found, "Reviewer", step)


def test_a_finding_is_blocking_unless_marked_a_suggestion_and_a_failing_test_always_is():
    # B-192 (live): every small note was a finding and the loop went round twice.
    report = ("## Findings\n- greet says Helo | kind: code | role: Coder | blocking\n"
              "- name it greeting | kind: code | role: Coder | **suggestion**\n"
              "- old style | kind: code | role: Coder\n"
              "- test_greet fails | kind: test | role: Coder | suggestion")
    found = _findings(report, ROLES)
    assert [(f["what"], f["role"], f["blocking"]) for f in found] == [
        ("greet says Helo", "Coder", True), ("name it greeting", "Coder", False),
        ("old style", "Coder", True), ("test_greet fails", "Coder", True)]
    # Handed on are the blocking ones only; the Lead is told the suggestion is the user's.
    assert "name it greeting" not in _carried(found, "Coder") and "greet says Helo" in _carried(found, "Coder")
    assert _hand_on(found) == ("\n\nFindings to hand on: Coder (3)"
                               "\n\nSuggestions for the user, not to hand on: 1")
    assert _hand_on([f for f in found if not f["blocking"]]) == (
        "\n\nSuggestions for the user, not to hand on: 1")


@pytest.mark.parametrize(("line", "blocking"), [
    # (the coordinator's: security is always blocking; `blocking` anywhere wins; a suggestion
    # is read from the last field only)
    ("- a key in the log | kind: security | role: Coder | suggestion", True),
    ("- rename x | kind: code | role: Coder | blocking | suggestion", True),
    ("- rename x | kind: code | suggestion | role: Coder", True),
    ("- rename x | kind: code | role: Coder | suggestion", False),
    # what a failure is said in, whatever it is marked
    *((f"- {said} | kind: test | role: Coder | suggestion", True) for said in (
        "an Error on import", "pytest exited 2", "exit code 1 from npm test", "parse() raises",
        "a Traceback in train.py", "testler başarısız", "etl.py hata veriyor", "test_x FAILED")),
])
def test_what_makes_a_finding_blocking(line, blocking):
    (found,) = _findings(f"## Findings\n{line}", ROLES)
    assert found["blocking"] is blocking


def test_a_section_with_no_line_in_the_format_is_not_said():
    assert _findings("## Findings\nThe greeting is wrong.\n- and slow", ROLES) is None
    # (a line not in the format is no finding beside those that are)
    assert [f["what"] for f in _findings("## Findings\nTwo:\n- a | role: Coder", ROLES)] == ["a"]


# --- who reads and who is told --------------------------------------------------------


def test_a_report_of_a_role_not_of_the_check_kind_has_no_findings(make_client, wait_run, project_dir):
    _, _, snap = run(make_client, wait_run, project_dir,
                     [spawn("Researcher", "Look at hello.py"), text("done")],
                     Researcher=[text("Found it.\n\nFindings:\n- greet() is wrong | kind: code | role: Coder")])
    assert agent(snap, "Researcher")["findings"] is None


def test_a_check_role_answering_a_message_is_not_told_the_findings_section(make_client, wait_run, project_dir):
    _, model, _ = run(make_client, wait_run, project_dir,
                      [spawn("Reviewer", "Review hello.py"), message("reviewer", "And the tests?"), text("done")],
                      Reviewer=[text("Findings: none"), text("There are none.")])
    told = model.calls_of["Reviewer"]
    assert "| kind:" in told[0][0]["content"] and "| kind:" not in told[1][0]["content"]


def test_a_check_role_speaking_in_a_discussion_is_not_told_the_findings_section(
        make_client, wait_run, project_dir):
    _, model, _ = run(make_client, wait_run, project_dir,
                      [discuss("Is hello.py fine?", ["reviewer"], rounds=1), text("Fine."), text("done")],
                      Reviewer=[text("Looks fine.")])
    assert model.calls_of["Reviewer"]
    assert all("| kind:" not in sent[0]["content"] for sent in model.calls_of["Reviewer"])


def test_a_role_closed_in_this_conversation_is_no_role_named_and_is_not_offered(
        make_client, wait_run, project_dir):
    client, model = make_client({"Lead": [spawn("Reviewer", "Review hello.py"), text("done")],
                                 "Reviewer": [text(REPORT)]})
    off = client.patch(f"/api/roles/{role_id(client, 'UI designer')}", json={"enabled": False},
                       headers=ORIGIN)
    assert off.status_code == 200, off.text
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    assert [f["role"] for f in agent(snap, "Reviewer")["findings"]] == ["Coder", None, None]
    assert "Findings to hand on: Coder (1), no role named (2)" in model.calls_of["Lead"][1][-1]["content"]
    offered = model.calls_of["Reviewer"][0][0]["content"].split("should take it: ")[1].split(". With")[0]
    assert "Coder" in offered and "UI designer" not in offered


# --- B-364: a finding that names an agent, not a role ---------------------------------


def test_a_finding_naming_an_agent_goes_to_that_agent_s_role():
    def role(said, agents=None):
        (found,) = _findings(f"## Findings\n- x | kind: code | role: {said}", ROLES, agents)
        return found["role"]

    assert role("Fixer", {"fixer": "Coder"}) == "Coder"  # (an agent of the turn, by its name)
    assert role("Coder 3") == "Coder"  # (numbered as agents are)
    assert role("Wizard 2") is role("Coder2") is None
    given = {"report": "", "findings": [{"what": "x", "kind": "code", "role": "coder 2",
                                         "blocking": True}]}
    assert _handed_findings(given, ROLES, {"coder 2": "Coder"})[0][0]["role"] == "Coder"


def test_a_reviewer_s_finding_for_coder_2_goes_to_the_coder_2_agent(make_client, wait_run, project_dir):
    # B-364 (live): "3 suggestions → no role ×2, Coder" - two named `role: Coder 2`.
    found = "Fixed?\n\n## Findings\n- greet() prints \"Helo\" | kind: code | role: Coder 2\n"
    _, model, snap = run(make_client, wait_run, project_dir,
                         [spawn("Coder", "Write hello.py", "s1"), spawn("Coder", "Fix hello.py", "s2"),
                          spawn("Reviewer", "Review hello.py", "s3"), text("done")],
                         Coder=[text("written")], **{"Coder 2": [text("fixed")]},
                         Reviewer=[text(found)])
    assert [a["name"] for a in snap["agents"][1:]] == ["Coder", "Coder 2", "Reviewer"]
    assert [f["role"] for f in agent(snap, "Reviewer")["findings"]] == ["Coder"]
    assert "Findings to hand on: Coder (1)" in model.calls_of["Lead"][3][-1]["content"]


def test_findings_from_an_agent_of_an_earlier_turn_is_refused(make_client, wait_run, project_dir):
    client, model = make_client({
        "Lead": [spawn("Reviewer", "Review hello.py"), text("done"),
                 step(call("spawn_agent", {"role": "Coder", "task": "Fix it",
                                           "findings_from": "Reviewer"}, "s2")),
                 text("not handed")],
        "Reviewer": [text(REPORT)], "Coder": [text("fixed")]})
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    wait_run(client, cid, run_id)
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "fix it"},
                         headers=ORIGIN).json()
    snap = wait_run(client, cid, posted["run"]["id"])
    refused = model.calls_of["Lead"][3][-1]
    assert refused["role"] == "tool" and "no agent of this turn is named Reviewer" in refused["content"]
    assert "Coder" not in [a["role_name"] for a in snap["agents"]]
