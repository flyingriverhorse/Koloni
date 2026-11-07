"""89p and 93-B6: a check role's report on Claude Code comes back in its schema
(`--json-schema` -> the result's `structured_output`), read from its fields, not its words;
an answer that does not keep to the schema is asked for once more, with what was wrong."""

import asyncio
import json
import subprocess

import pytest

from app import model_native
from app.agent import MAX_WHAT, REPORT_SCHEMA, _handed_findings
from app.model_cli import CMD_ACTS_ON, MAX_SHIM_LINE
from app.model_native import ClaudeNativeClient, schema_errors
from tests.test_agent_talk import message
from tests.test_agent_writes import wait_status
from tests.test_attachment_agents import FAKE_CLAUDE, plan, record
from tests.test_chat_flow import text
from tests.test_claude_native import ORIGIN, claude_app, start  # noqa: F401  (a fixture)
from tests.test_codex_app_server_scenarios import answered
from tests.test_spawn import role_id, spawn

WORDS = {"say": "Reviewed hello.py; one problem."}
FOUND = {"what": "greet() | prints Helo", "kind": "code", "role": "Coder", "blocking": True}
GOOD = {"report": "Reviewed hello.py.", "checked": "hello.py, ran it", "findings": [FOUND]}
BAD = {"report": "Reviewed.", "findings": [{**FOUND, "kind": "perf"}]}


def run_as(claude_app, wait_run, project_dir, structured, role="Reviewer", **more):  # noqa: F811
    client, provider, _ = claude_app(
        [WORDS], default_steps=[spawn(role, "Review hello.py"), text("ok")],
        structured=structured, **more)
    client.patch(f"/api/roles/{role_id(client, role)}", json={"provider_id": provider["id"]})
    cid, run_id = start(client, project_dir, None, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    agent = next(a for a in snap["agents"] if a["role_name"] == role)
    notes = [(t["status"], t["result"]) for t in snap["tool_calls"] if t["name"] == "report_schema"]
    return agent, notes, claude_app.record()


def test_a_check_role_hands_its_report_back_in_the_schema_and_its_fields_are_read(
    claude_app, wait_run, project_dir  # noqa: F811
):
    reviewer, notes, seen = run_as(claude_app, wait_run, project_dir, [GOOD])
    argv = seen["argv"]
    assert json.loads(argv[argv.index("--json-schema") + 1]) == REPORT_SCHEMA
    assert seen["handed"] == ["allow"]  # its StructuredOutput is no card
    # told to put its findings in the schema, not in its words
    assert "Hand your report in with StructuredOutput" in seen["stdin"]
    assert "`## Findings`" not in seen["stdin"]
    assert reviewer["findings"] == [FOUND]  # (a "|" in it is only a character)
    assert reviewer["report"] == "Reviewed hello.py."  # its words, no findings written in
    assert notes == [("succeeded", "its report came back in its schema: its findings are read "
                                   "from it")]
    assert "steered" not in seen


def test_findings_in_its_words_with_none_in_findings_are_read_fail_closed(
    claude_app, wait_run, project_dir  # noqa: F811
):
    # (Review, Critical: KOLONİ wrote "Findings: none" after them, and the review passed.)
    said = {"report": "One problem.\n\n## Findings\n- the key is logged | kind: security | "
                      "role: Coder | suggestion", "findings": []}
    reviewer, _notes, _seen = run_as(claude_app, wait_run, project_dir, [said])
    assert reviewer["findings"] == [{"what": "the key is logged", "kind": "security",
                                     "role": "Coder", "blocking": True}]


def test_an_answer_off_the_schema_is_asked_for_once_more_with_its_errors_not_the_schema(
    claude_app, wait_run, project_dir  # noqa: F811
):
    reviewer, notes, seen = run_as(claude_app, wait_run, project_dir, [BAD, GOOD],
                                   again_say="Here it is again.")
    (again,) = seen["steered"]
    said = again["message"]["content"]
    assert "report.findings[0].kind is not one of code" in said
    assert '"properties"' not in said and "additionalProperties" not in said
    assert reviewer["findings"] == [FOUND] and reviewer["report"] == "Reviewed hello.py."
    assert [status for status, _ in notes] == ["failed", "succeeded"]
    assert "asked once more" in notes[0][1]


def test_it_is_asked_once_only_and_then_its_first_words_are_its_report(
    claude_app, wait_run, project_dir  # noqa: F811
):
    reviewer, notes, seen = run_as(claude_app, wait_run, project_dir, [BAD, BAD, GOOD],
                                   again_say="Sorry, here it is.")
    assert len(seen["steered"]) == 1
    assert reviewer["report"] == WORDS["say"] and reviewer["findings"] is None
    assert [status for status, _ in notes] == ["failed", "failed"]
    assert "its words are its report" in notes[1][1]


def test_a_retry_never_answered_leaves_its_first_answer_and_the_review_finished(
    claude_app, wait_run, project_dir, monkeypatch  # noqa: F811
):
    monkeypatch.setattr(model_native, "LATE_SECONDS", 0.5)
    reviewer, notes, seen = run_as(claude_app, wait_run, project_dir, [BAD], linger=True)
    assert len(seen["steered"]) == 1
    assert reviewer["status"] == "completed" and reviewer["report"] == WORDS["say"]
    assert [status for status, _ in notes] == ["failed", "failed"]


@pytest.mark.parametrize("handed", [None, "gave_up"])
def test_with_no_structured_answer_its_words_are_its_report_and_it_is_not_asked_again(
    claude_app, wait_run, project_dir, handed  # noqa: F811
):
    reviewer, notes, seen = run_as(claude_app, wait_run, project_dir, [handed])
    assert "steered" not in seen
    assert reviewer["report"] == WORDS["say"]
    assert notes == [("failed", "no report in its schema (none came back): its words are its "
                                "report")]


@pytest.mark.parametrize(("role", "schema"), [("Reviewer", True), ("Coder", False)])
def test_only_a_check_role_is_given_the_schema(
    claude_app, wait_run, project_dir, role, schema  # noqa: F811
):
    _agent, notes, seen = run_as(claude_app, wait_run, project_dir, [None], role=role)
    assert ("--json-schema" in seen["argv"]) is schema and bool(notes) is schema


def test_a_check_role_answering_a_message_is_given_no_schema(
    claude_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = claude_app([WORDS], default_steps=[
        spawn("Reviewer", "Review hello.py"), message("Reviewer", "and main.py?"), text("ok")])
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={"provider_id": provider["id"]})
    cid, run_id = start(client, project_dir, None, "full_auto")
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    assert "--json-schema" not in claude_app.record()["argv"]  # (its last run: the reply)


def test_the_lead_is_given_no_schema_and_its_structured_output_is_asked_about(
    claude_app, wait_run, project_dir  # noqa: F811
):
    client, provider, _ = claude_app([
        {"tool": "StructuredOutput", "input": {"x": 1}}, {"say": "done"}])
    cid, run_id = start(client, project_dir, provider, "ask")
    question = wait_status(client, cid, "waiting_approval")["questions"][0]
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "Deny"},
                headers={"Origin": ORIGIN})
    wait_run(client, cid, run_id)
    seen = claude_app.record()
    assert "--json-schema" not in seen["argv"]
    assert [one["hookSpecificOutput"]["permissionDecision"] for one in seen["hooks"]] == ["ask"]


@pytest.mark.anyio
async def test_a_report_handed_back_before_a_steered_turn_is_kept(tmp_path):
    # (Review: it was dropped once the steer's late turn handed none.)
    client = ClaudeNativeClient(launcher=FAKE_CLAUDE, **plan(
        tmp_path, [{"say": "working"}, {"await_steer": 5}, {"say": "done"}],
        structured=[GOOD], second_turn_on_steer=True))
    doors, items = [], []

    async def on_text(_text):
        pass

    async def on_item(_phase, item):
        items.append(item)

    async def steer():
        while not doors:
            await asyncio.sleep(0.05)
        return await doors[0]("use blue")

    trying = asyncio.ensure_future(steer())
    await client.run_native(
        "m", [{"role": "system", "content": "s"}, {"role": "user", "content": "go"}], [],
        str(tmp_path), answered, on_text, on_item,
        on_live=lambda door: door and doors.append(door), report_schema=REPORT_SCHEMA)
    assert await trying is True and record(tmp_path)["handed"] == ["allow"]
    assert [one for one in items if one.get("type") == "structured_report"] == [
        {"type": "structured_report", "report": GOOD}]


def test_handed_findings_keep_b_192s_rules_and_cut_what_is_long():
    roles = ["Coder"]
    found, checked, before = _handed_findings({"report": "", "findings": [
        {"what": "token in the log", "kind": "security", "role": "coder", "blocking": False},
        {"what": "test_x fails", "kind": "code", "role": "Coder", "blocking": False},
        {"what": "a nicer name", "kind": "code", "role": "Wizard", "blocking": False},
        {"what": "x" * 5000, "kind": "docs", "role": "Coder", "blocking": True},
    ], "checked": "nothing", "failing_before": ["old\ntest", " "]}, roles)
    assert [f["blocking"] for f in found] == [True, True, False, True]
    assert found[0]["role"] == "Coder" and found[2]["role"] is None
    assert found[3]["what"] == "x" * MAX_WHAT
    assert checked is False and before == ["old test"]
    assert _handed_findings({"report": "fine", "findings": []}, roles) == ([], False, [])


def test_the_schema_fits_a_cmd_shims_line():
    line = json.dumps(REPORT_SCHEMA, separators=(",", ":"))
    assert not CMD_ACTS_ON.search(line)
    assert len(subprocess.list2cmdline(["--json-schema", line])) < MAX_SHIM_LINE // 10


def test_schema_errors_say_where():
    assert schema_errors(GOOD, REPORT_SCHEMA) == []
    assert schema_errors({"report": 3, "extra": 1}, REPORT_SCHEMA) == [
        "report.findings is missing", "report.extra is not in the schema",
        "report.report is not a string"]
    assert schema_errors({**GOOD, "findings": [{**FOUND, "blocking": "yes"}]}, REPORT_SCHEMA) == [
        "report.findings[0].blocking is not true or false"]
    assert schema_errors("x", REPORT_SCHEMA) == ["report is not an object"]
