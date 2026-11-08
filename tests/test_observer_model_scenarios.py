"""Slice 33b's acceptance set: an observer model looks over a sub-agent's report. Written before
the code.

Off by default. Switched on for the project (from the app's own page: it spends), the built-in
Observer role is asked once, without tools, when a sub-agent hands in its report: it sees the
task, the report and the calls that were made, and says in at most three sentences what of the
report the record shows and what it does not. The Lead gets the report as before, with the
observer's words quoted beside it as an opinion, not a fact; the sub-agent's state does not
change and nothing is stopped. With no observer model, or one that fails, nothing is made up:
there is no observation, and why is said.

Contract: `ProjectPatch.observe_reports` / `ProjectOut.observe_reports` (bool, default false);
`AgentOut.observation` (str | None) and `AgentOut.observation_note` (str | None: why none).
"""

import pytest

from app.schemas import AgentOut

if "observation" not in AgentOut.model_fields:
    pytest.skip("slice 33b is not built yet", allow_module_level=True)  # written before the code

from app.model_client import ModelUnavailable  # noqa: E402
from tests.test_chat_flow import text  # noqa: E402
from tests.test_spawn import call, reported, spawn, step  # noqa: E402

ORIGIN = "http://127.0.0.1:8790"
TASK = "Make the tests pass"
REPORT = "Done. The tests pass now."
SAID = "The report says the tests pass; no test run is on record."
OPINION = "an observer's opinion, not a fact"


def project(client, project_dir, **settings):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    if settings:
        changed = client.patch(f"/api/projects/{pid}", json=settings, headers={"Origin": ORIGIN})
        assert changed.status_code == 200, changed.text
    return pid


def turn(client, pid, content="fix it"):
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(
        f"/api/conversations/{cid}",
        json={"permission_mode": "full_auto"},
        headers={"Origin": ORIGIN},
    )
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": content}).json()[
        "run"
    ]["id"]
    return cid, run_id


def child_of(snap):
    return next(a for a in snap["agents"] if a["depth"] == 1)


def test_it_is_off_unless_the_project_asks_for_it(make_client, wait_run, project_dir):
    client, model = make_client(
        [
            spawn("Reviewer", TASK),
            step(call("read_file", {"path": "hello.py"}), content="Looking."),
            text(REPORT),
            text("Good."),
        ]
    )
    pid = project(client, project_dir)
    assert client.get(f"/api/projects/{pid}").json()["observe_reports"] is False
    cid, run_id = turn(client, pid)
    snap = wait_run(client, cid, run_id)
    assert len(model.calls) == 4  # the Lead twice, the Reviewer twice: no one else asked
    kid = child_of(snap)
    assert (kid["observation"], kid["observation_note"]) == (None, None)
    assert reported(model.calls[3][-1]["content"]) == f"Reviewer finished.\n\n{REPORT}"


def test_switched_on_the_observer_is_asked_once_without_tools_and_its_words_go_beside_the_report(
    make_client, wait_run, project_dir
):
    client, model = make_client(
        [
            spawn("Reviewer", TASK),
            step(call("read_file", {"path": "hello.py"}), content="Looking."),
            text(REPORT),
            text(SAID),  # the observer
            text("Good."),
        ]
    )
    pid = project(client, project_dir, observe_reports=True)
    cid, run_id = turn(client, pid)
    snap = wait_run(client, cid, run_id)

    asked = model.calls[3]
    assert not model.tool_args[3]  # no tools: one question
    seen = " ".join(str(m["content"]) for m in asked)
    assert TASK in seen and REPORT in seen and "read_file" in seen
    assert "three sentences" in seen

    kid = child_of(snap)
    assert kid["status"] == "completed" and kid["report"] == REPORT  # nothing of it changed
    assert kid["observation"] == SAID and kid["observation_note"] is None
    back = model.calls[4][-1]["content"]
    assert back.startswith(f"Reviewer finished.\n\n{REPORT}")
    assert SAID in back and OPINION in back
    assert len(model.calls) == 5  # asked once


def test_no_more_than_three_sentences_are_kept(make_client, wait_run, project_dir):
    long = "One. Two. Three. Four. Five."
    client, _model = make_client([spawn("Reviewer", TASK), text(REPORT), text(long), text("ok")])
    pid = project(client, project_dir, observe_reports=True)
    cid, run_id = turn(client, pid)
    kid = child_of(wait_run(client, cid, run_id))
    assert kid["observation"] == "One. Two. Three."


def test_an_observer_that_fails_makes_nothing_up_and_says_why(make_client, wait_run, project_dir):
    client, model = make_client(
        [
            spawn("Reviewer", TASK),
            text(REPORT),
            ModelUnavailable("model server unreachable: refused"),  # the observer
            text("Good."),
        ]
    )
    pid = project(client, project_dir, observe_reports=True)
    cid, run_id = turn(client, pid)
    snap = wait_run(client, cid, run_id)
    kid = child_of(snap)
    assert kid["status"] == "completed" and kid["observation"] is None
    assert "unreachable" in (kid["observation_note"] or "")
    assert reported(model.calls[3][-1]["content"]) == f"Reviewer finished.\n\n{REPORT}"  # as ever
    assert snap["runs"][0]["status"] == "completed"


def test_the_observer_is_a_built_in_role_of_its_own_tier(make_client):
    client, _model = make_client([])
    observer = next(r for r in client.get("/api/roles").json() if r["name"] == "Observer")
    # Slice 81b: no fixed tier any more; with none it is asked on a balanced model, as before.
    assert observer["builtin"] is True and observer["tier"] is None
    rows = {row["role"]: row for row in client.get("/api/roles/models").json()}
    assert rows["Observer"]["tier"] == "balanced"


def test_switching_it_on_is_asked_from_the_apps_own_page(make_client, project_dir):
    client, _model = make_client([])
    pid = project(client, project_dir)
    assert client.patch(f"/api/projects/{pid}", json={"observe_reports": True}).status_code == 403
    assert client.get(f"/api/projects/{pid}").json()["observe_reports"] is False
