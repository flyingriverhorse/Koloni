"""Slice 84c's acceptance set: findings go to the right role. Written before the code.

Design: `tasarim/specs/2026-10-23-dilim-63-84-takimlar-tarifler-design.md` §4 ("Bulgular doğru role")
and §6 (84c). The user (23 Oct): "not only the Coder: it must give them to the roles that need
them; this is important".

Contract:
- A sub-agent of a role whose kind of work is "check" (Reviewer, Tester, Security reviewer, ...) is
  told, in its system prompt, to end its report with a Findings section: one line per finding,
  `- <what> | kind: <kind> | role: <role>`, or `Findings: none`. Its kinds: code, ui, security,
  docs, test, data. A role of another kind (the Coder: "build") is not told this.
- A check-kind sub-agent's report that has the section is read into the agent's `findings`: a list of
  {"what", "kind", "role"}. A kind not in the list is "other"; a role is the name of an existing
  role matched without case (its own spelling), else null - never a made-up one. "none" is [].
  A report with no section: `findings` is null (not said), not [].
- The Lead's tool result for that spawn says, after the report, which roles the findings are for:
  "Findings to hand on: Coder (1), UI designer (1)" (a finding with no role: "no role named (n)").
  None when there are none.
- `spawn_agent` takes `findings_from`: the name of an agent of this turn whose findings the new agent
  carries. The new agent's task (what it sees first) is the Lead's task and, under it, those
  findings - the ones for its role, or all of them when none is - word for word. A channel row of
  kind "findings" goes from the agent they came from to the new one (the canvas draws it). An agent
  that is not of this turn, or has no findings: refused, saying why; nothing is opened.
- The Lead is told to hand each finding to the role it names.
"""

import pytest

from app.db.models import Agent

if not hasattr(Agent, "findings"):  # written before the code: skipped until it exists
    pytest.skip("slice 84c is not built yet", allow_module_level=True)

from tests.test_chat_flow import text  # noqa: E402
from tests.test_spawn import begin, call, spawn, step  # noqa: E402

REPORT = """Two problems.

## Findings
- greet() prints "Helo" | kind: code | role: Coder
- the button text is too light to read | kind: ui | role: ui designer
- a slow loop in main | kind: perf | role: Wizard
"""


def run(make_client, wait_run, project_dir, lead, **subs):
    client, model = make_client({"Lead": lead, **subs})
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    return client, model, wait_run(client, cid, run_id)


def agent(snap, role):
    return next(a for a in snap["agents"] if a["role_name"] == role)


def test_a_check_role_is_told_the_findings_section_and_a_build_role_is_not(make_client, wait_run, project_dir):
    _, model, _ = run(make_client, wait_run, project_dir,
                      [spawn("Reviewer", "Review hello.py"),
                       step(call("spawn_agent", {"role": "Coder", "task": "Tidy hello.py"}, "s2")),
                       text("done")],
                      Reviewer=[text("Findings: none")], Coder=[text("tidied")])
    told = model.calls_of["Reviewer"][0][0]["content"]
    assert "Findings" in told and "| kind:" in told and "| role:" in told
    assert "| kind:" not in model.calls_of["Coder"][0][0]["content"]


def test_a_report_s_findings_are_read_each_with_its_kind_and_an_existing_role(make_client, wait_run, project_dir):
    _, _, snap = run(make_client, wait_run, project_dir,
                     [spawn("Reviewer", "Review hello.py"), text("done")],
                     Reviewer=[text(REPORT)])
    assert agent(snap, "Reviewer")["findings"] == [
        {"what": 'greet() prints "Helo"', "kind": "code", "role": "Coder", "blocking": True},
        {"what": "the button text is too light to read", "kind": "ui", "role": "UI designer", "blocking": True},
        {"what": "a slow loop in main", "kind": "other", "role": None, "blocking": True},
    ]


@pytest.mark.parametrize(("report", "found"), [
    ("Looks fine.\n\nFindings: none", []),
    ("Looks fine.", None),
])
def test_none_is_an_empty_list_and_no_section_is_not_said(make_client, wait_run, project_dir, report, found):
    _, _, snap = run(make_client, wait_run, project_dir,
                     [spawn("Reviewer", "Review hello.py"), text("done")],
                     Reviewer=[text(report)])
    assert agent(snap, "Reviewer")["findings"] == found


def test_the_lead_is_told_which_roles_the_findings_are_for(make_client, wait_run, project_dir):
    _, model, _ = run(make_client, wait_run, project_dir,
                      [spawn("Reviewer", "Review hello.py"), text("done")],
                      Reviewer=[text(REPORT)])
    lead = model.calls_of["Lead"]
    assert "each blocking finding" in lead[0][0]["content"]  # its instructions
    back = lead[1][-1]
    assert back["role"] == "tool" and back["content"].startswith("Reviewer finished.")
    assert "Findings to hand on: Coder (1), UI designer (1), no role named (1)" in back["content"]


def test_a_report_with_no_findings_adds_nothing_to_the_lead_s_result(make_client, wait_run, project_dir):
    _, model, _ = run(make_client, wait_run, project_dir,
                      [spawn("Reviewer", "Review hello.py"), text("done")],
                      Reviewer=[text("Looks fine.\n\nFindings: none")])
    assert "Findings to hand on" not in model.calls_of["Lead"][1][-1]["content"]


def test_findings_from_gives_the_new_agent_its_role_s_findings_word_for_word(make_client, wait_run, project_dir):
    _, model, snap = run(make_client, wait_run, project_dir,
                         [spawn("Reviewer", "Review hello.py"),
                          step(call("spawn_agent", {"role": "Coder", "task": "Fix what the review found",
                                                    "findings_from": "Reviewer"}, "s2")),
                          text("done")],
                         Reviewer=[text(REPORT)], Coder=[text("fixed")])
    first = model.calls_of["Coder"][0][1]["content"]
    assert first.startswith("Fix what the review found")
    assert 'greet() prints "Helo"' in first
    assert "too light to read" not in first  # the UI designer's, not the Coder's
    # G1.4: each is answered one of two ways.
    assert "`- <what> | fixed: <how>` or `- <what> | disputed: <why it is not to be fixed>`" in first
    reviewer, coder = agent(snap, "Reviewer"), agent(snap, "Coder")
    given = [m for m in snap["channel_messages"] if m["kind"] == "findings"]
    assert [(m["from_agent_id"], m["to_agent_id"]) for m in given] == [(reviewer["id"], coder["id"])]
    assert 'greet() prints "Helo"' in given[0]["content"]


def test_findings_for_no_agent_of_its_role_are_all_given(make_client, wait_run, project_dir):
    _, model, _ = run(make_client, wait_run, project_dir,
                      [spawn("Reviewer", "Review hello.py"),
                       step(call("spawn_agent", {"role": "Debugger", "task": "Look into these",
                                                 "findings_from": "Reviewer"}, "s2")),
                       text("done")],
                      Reviewer=[text(REPORT)], Debugger=[text("looked")])
    first = model.calls_of["Debugger"][0][1]["content"]
    assert 'greet() prints "Helo"' in first and "too light to read" in first and "slow loop" in first


@pytest.mark.parametrize(("source", "why"), [
    ("Nobody", "Nobody"),          # not an agent of this turn
    ("Reviewer", "no findings"),   # one with none
])
def test_findings_from_an_unknown_agent_or_one_with_none_is_refused(make_client, wait_run, project_dir, source, why):
    _, model, snap = run(make_client, wait_run, project_dir,
                         [spawn("Reviewer", "Review hello.py"),
                          step(call("spawn_agent", {"role": "Coder", "task": "Fix it",
                                                    "findings_from": source}, "s2")),
                          text("done")],
                         Reviewer=[text("Looks fine.\n\nFindings: none")], Coder=[text("fixed")])
    refused = model.calls_of["Lead"][2][-1]
    assert refused["role"] == "tool" and why in refused["content"]
    assert [a["role_name"] for a in snap["agents"]] == ["Lead", "Reviewer"]
    assert not [m for m in snap["channel_messages"] if m["kind"] == "findings"]
