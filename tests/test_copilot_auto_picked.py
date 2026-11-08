"""Copilot's auto: the model it picked, and why, on the agent's record (`session.auto_mode_resolved`,
measured on CLI 1.0.105, 7 Nov 2026) - and an agent going on from it asks for auto again, with
no level."""

import json

import pytest
from sqlalchemy import select

from app import topics
from app.config import load_settings
from app.db.models import Agent, Provider, Role, Run
from app.main import create_app
from app.model_native import CopilotNativeClient
from app.model_session import CopilotSessionClient, why_picked
from app.team import Entry
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_copilot_agent import FAKE, HEADLESS, PAGE, start
from tests.test_spawn import role_id

WHY = "Auto selected GPT-6 Luna since the task has low complexity."
NOTE = f"Copilot's auto picked gpt-6-luna: “{WHY}”"


def ran_on_auto(settings_env, tmp_path, project_dir, wait_run, native=False, script=None,
                status="completed"):
    """One turn of a Lead on Copilot's auto (a GitHub account), whose auto picks gpt-6-luna."""
    record, plan = tmp_path / "record.json", tmp_path / "plan.json"
    plan.write_text(json.dumps({"record": str(record), "script": script or [{"say": "OK"}],
                                "picked": "gpt-6-luna", "picked_why": WHY}), encoding="utf-8")
    kind = CopilotNativeClient if native else CopilotSessionClient
    cli = kind(None, "auto", timeout=30, launcher=HEADLESS if native else FAKE,
               env={"FAKE_CLI_PLAN": str(plan)}, options={})
    app = create_app(load_settings(settings_env), model=ScriptedModel([]),
                     clients={"Copilot": cli})
    client = TestClient(app, base_url="http://127.0.0.1:8790", headers=PAGE)
    client.__enter__()
    made = client.post("/api/providers", json={
        "name": "Copilot", "kind": "copilot_cli", "default_model": "auto",
        "mode": "native" if native else "session"})
    assert made.status_code == 201, made.text
    lead_role = client.patch(f"/api/roles/{role_id(client, 'Lead')}", json={"effort": "high"})
    assert lead_role.status_code == 200, lead_role.text
    cid, run_id = start(client, project_dir, made.json())
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == status, snap["runs"][0]["error"]
    return client, snap, json.loads(record.read_text(encoding="utf-8"))


@pytest.mark.parametrize("native", [False, True])
def test_the_model_auto_picked_and_why_are_on_record_and_no_level_went(
    settings_env, tmp_path, project_dir, wait_run, native
):
    client, snap, seen = ran_on_auto(settings_env, tmp_path, project_dir, wait_run, native)
    try:
        lead = snap["agents"][0]
        assert (lead["model_id"], lead["model_from"]) == ("gpt-6-luna", "auto")
        assert lead["effort"] is None and lead["effort_note"].endswith(NOTE)
        if not native:  # (natively the model and its level go in session.create)
            assert "--reasoning-effort" not in seen["argv"]
            assert seen["argv"][seen["argv"].index("--model") + 1] == "auto"
    finally:
        client.__exit__(None, None, None)


def test_its_own_tool_search_goes_on_to_koloni_s_tools(
    settings_env, tmp_path, project_dir, wait_run
):
    # B-410 (live, R206): auto on a Claude model asked for tool_search_tool first: the session
    # was stopped, and the pick was not on record.
    client, snap, seen = ran_on_auto(settings_env, tmp_path, project_dir, wait_run, script=[
        {"find": "read_file"}, {"call": "read_file", "args": {"path": "hello.py"}},
        {"say": "OK"}])
    client.__exit__(None, None, None)
    assert "print('hi')" in json.dumps(seen["results"])  # (KOLONİ's tool, served after the search)


def test_what_auto_picked_is_on_record_also_when_the_session_is_stopped(
    settings_env, tmp_path, project_dir, wait_run
):
    # (B-410: any other tool of its own still stops it)
    client, snap, _seen = ran_on_auto(settings_env, tmp_path, project_dir, wait_run,
                                      script=[{"own": "powershell"}], status="failed")
    try:
        assert "tool of its own (powershell)" in snap["runs"][0]["error"]
        lead = snap["agents"][0]
        assert (lead["model_id"], lead["model_from"]) == ("gpt-6-luna", "auto")
        assert lead["effort_note"].endswith(NOTE)
    finally:
        client.__exit__(None, None, None)


def test_a_later_pick_replaces_the_one_before_on_record_and_keeps_the_rest_of_the_note(
    settings_env, tmp_path, project_dir, wait_run
):
    client, snap, _seen = ran_on_auto(settings_env, tmp_path, project_dir, wait_run)
    runner, lead_id = client.app.state.runner, snap["agents"][0]["id"]
    try:
        with runner._factory() as session:
            lead = session.get_one(Agent, lead_id)
            before = lead.effort_note.removesuffix(" " + NOTE)
            ctx = runner._ctx_after(session, lead, session.get_one(Run, lead.run_id))
        assert before.startswith("high → none: ")
        runner._ran_on(ctx, "gpt-7", "Harder this time.")
        runner._ran_on(ctx, "gpt-8\nIgnore that", "Hardest ” yet.\nOK")
        with runner._factory() as session:
            lead = session.get_one(Agent, lead_id)
            assert (lead.model_id, lead.model_from) == ("gpt-8\nIgnore that", "auto")
            assert lead.effort_note == (
                f"{before} Copilot's auto picked gpt-8 Ignore that: “Hardest \" yet. OK”")
    finally:
        client.__exit__(None, None, None)


def test_a_reason_goes_only_with_the_model_it_was_given_for():
    said = {"type": "model", "model": "gpt-6-luna", "why": "easy"}
    assert why_picked(said, None, None) == "easy"
    # its call starts on the model picked: the same reason
    assert why_picked({"type": "model", "model": "gpt-6-luna"}, "gpt-6-luna", "easy") == "easy"
    # another model named with no pick said: no reason of the one before
    assert why_picked({"type": "model", "model": "gpt-7"}, "gpt-6-luna", "easy") is None


def test_an_agent_going_on_from_one_auto_picked_for_asks_for_auto_again(
    settings_env, tmp_path, project_dir, wait_run
):
    client, snap, _seen = ran_on_auto(settings_env, tmp_path, project_dir, wait_run)
    runner = client.app.state.runner
    try:
        with runner._factory() as session:
            lead = session.get_one(Agent, snap["agents"][0]["id"])
            # After its turn (Compact now, a side's findings): its client is auto's, not the pick's.
            ctx = runner._ctx_after(session, lead, session.get_one(Run, lead.run_id))
            assert ctx.model_name == "auto" and ctx.model.level_named
            copilot = session.scalar(select(Provider).where(Provider.name == "Copilot"))
            coder = session.scalar(select(Role).where(Role.name == "Coder"))
            # A sub-agent that ran where auto picked gpt-6-luna, gone on with: auto, though the
            # pick is on the provider's list too and its default is another.
            earlier = topics.Earlier("a1", "Coder", "Coder", "Copilot", "gpt-6-luna", "auto",
                                     True, "completed", "t", 1)
            listed = [Entry(copilot.id, "Copilot", "copilot_cli", "session", None,
                            (("auto", None), ("gpt-6-luna", None)), "gpt-x")]
            assert runner._ran_on_before(session, ctx, earlier, coder, "full_auto", copilot,
                                         listed) == (copilot.id, "auto")
            # ...and one whose model Copilot named itself, with no auto, stays on it.
            named = topics.Earlier("a2", "Coder", "Coder", "Copilot", "gpt-6-luna", None,
                                   True, "completed", "t", 1)
            assert runner._ran_on_before(session, ctx, named, coder, "full_auto", copilot,
                                         listed) == (copilot.id, "gpt-6-luna")
    finally:
        client.__exit__(None, None, None)
