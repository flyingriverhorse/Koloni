"""Slice 59a beside its acceptance set: what the level of a step is on record, a role's level
against its most as it is kept, a lowered level said, and what the Models API is read for."""

import asyncio
import json
import time
from typing import get_args

import httpx2
import pytest

from app.api import roles as roles_api
from app.model_client import EFFORTS, ModelUnavailable
from app.schemas import Effort
from tests.test_chat_flow import text
from tests.test_model_anthropic import client_for
from tests.test_reasoning_level_scenarios import (
    ENDED,
    LEVELS,
    MODEL,
    leveled,  # noqa: F401 - the fixture
    ran,
    set_role,
)
from tests.test_spawn import call, role_id, spawn, step
from tests.test_topic_scenarios import FIRST, GO_ON, OLD_TASK, OLD_WORDS, SECOND, setup, turn


def test_the_level_sent_is_on_the_agents_record_and_none_where_none_went(
    leveled, wait_run, project_dir  # noqa: F811
):
    client, _model = leveled({"Lead": [spawn("Coder"), text("done")], "Coder": [text("ok")]},
                             efforts=("low", "medium"))
    set_role(client, "Coder", effort="off")  # not one the model takes, nor below it: nothing goes
    set_role(client, "Lead", effort="high")  # not one the model takes: the nearest lower one
    cid = ran(client, wait_run, project_dir)
    lead, coder = client.get(f"/api/conversations/{cid}").json()["agents"]
    assert (lead["effort"], coder["effort"]) == ("medium", None)
    assert lead["effort_note"].startswith("high → medium: the nearest lower level ")
    assert coder["effort_note"].startswith("off → none: ")


def test_a_lowered_level_is_said_with_the_sub_agents_report(
    leveled, wait_run, project_dir  # noqa: F811
):
    client, _model = leveled({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "t", "effort": "max"})),
                 text("done")],
        "Coder": [text("fixed")],
    })
    set_role(client, "Coder", max_effort="medium")
    cid = ran(client, wait_run, project_dir)
    snap = client.get(f"/api/conversations/{cid}").json()
    spawned = next(t for t in snap["tool_calls"] if t["name"] == "spawn_agent")
    assert spawned["result"].endswith(
        "effort max was lowered to medium: the most the Coder role may be given.")


def test_a_level_above_the_kept_most_is_refused_and_a_reset_clears_both(
    leveled  # noqa: F811
):
    client, _model = leveled({"Lead": []})
    coder = f"/api/roles/{role_id(client, 'Coder')}"
    set_role(client, "Coder", max_effort="medium")
    assert client.patch(coder, json={"effort": "high"}).status_code == 422  # the most kept
    assert client.patch(coder, json={"effort": "low"}).status_code == 200
    assert client.patch(coder, json={"max_effort": "low"}).status_code == 200  # equal is fine
    reset = client.post(f"{coder}/reset").json()
    assert (reset["effort"], reset["max_effort"]) == (None, None)


def test_who_uses_what_says_the_levels_only_when_asked_and_never_spends_to_know_them(
    leveled  # noqa: F811
):
    client, model = leveled({"Lead": []})
    assert {row["efforts"] for row in client.get("/api/roles/models").json()} == {None}
    # a client that carries its levels, as a CLI does, is not asked: they are its own
    rows = client.get("/api/roles/models?levels=1").json()
    assert {tuple(row["efforts"]) for row in rows} == {LEVELS}
    model.efforts = None  # one whose asking costs, and says none: none is sent
    assert {tuple(row["efforts"]) for row in
            client.get("/api/roles/models?levels=1").json()} == {()}
    type(model).free_info = True
    model.efforts = ("low", "high")
    try:
        rows = client.get("/api/roles/models?levels=1").json()
        unasked = client.get("/api/roles/models").json()
    finally:
        del type(model).free_info
    assert {tuple(row["efforts"]) for row in rows} == {("low", "high")}
    assert {row["efforts"] for row in unasked} == {None}  # the chat's table does not ask


@pytest.mark.parametrize("fails", [ModelUnavailable("down"), "stalls"])
def test_a_failed_asking_of_the_levels_is_said_fast_and_not_asked_again_for_a_while(
    leveled, monkeypatch, fails  # noqa: F811
):
    client, model = leveled({"Lead": []})
    monkeypatch.setattr(roles_api, "LEVELS_SECONDS", 0.2)
    asked = []

    async def info():
        asked.append(1)
        if fails == "stalls":
            await asyncio.Event().wait()
        raise fails

    monkeypatch.setattr(type(model), "free_info", True, raising=False)
    monkeypatch.setattr(model, "info", info)
    started = time.monotonic()
    rows = client.get("/api/roles/models?levels=1")
    assert rows.status_code == 200 and {row["efforts"] for row in rows.json()} == {None}
    assert time.monotonic() - started < 2
    client.get("/api/roles/models?levels=1")
    assert len(asked) == 1  # one client for every role, asked once and then remembered


@pytest.mark.anyio
async def test_anthropic_asks_once_and_writes_at_most_its_own_limit_or_ours():
    asked, sent = [], []

    def handler(request):
        if request.method == "GET":
            asked.append(request.url.path)
            return httpx2.Response(200, content=json.dumps({**MODEL, "max_tokens": 20_000}))
        sent.append(json.loads(request.content))
        return httpx2.Response(200, content=ENDED)

    async def on_delta(_text):
        pass

    client = client_for(handler)
    await client.info()
    await client.info()
    await client.stream_step("claude-sonnet-5-5", [{"role": "user", "content": "x"}], None,
                             on_delta)
    assert len(asked) == 1 and sent[0]["max_tokens"] == 20_000


@pytest.mark.anyio
async def test_anthropic_levels_are_none_where_the_api_says_effort_is_not_taken():
    told = {**MODEL, "capabilities": {"effort": {**MODEL["capabilities"]["effort"],
                                                 "supported": False}}}
    info = await client_for(lambda _r: httpx2.Response(200, content=json.dumps(told))).info()
    assert info.efforts is None
    unread = await client_for(lambda _r: httpx2.Response(200, content=b"not json")).info()
    assert (unread.efforts, unread.context_window) == (None, None)


@pytest.mark.anyio
@pytest.mark.parametrize(("models", "most"), [
    (httpx2.Response(200, content=json.dumps({**MODEL, "max_tokens": 128_000})), 64_000),
    (httpx2.Response(200, content=json.dumps({"id": "claude-sonnet-5-5"})), 8192),  # not said
    (httpx2.Response(404), 8192),  # a gateway with no Models API: as before
])
async def test_a_step_asked_before_any_info_writes_its_models_limit_or_the_old_one(models, most):
    sent = []

    def handler(request):
        if request.method == "GET":
            return models
        sent.append(json.loads(request.content))
        return httpx2.Response(200, content=ENDED)

    async def on_delta(_text):
        pass

    # a step on a model other than the provider's own, with no info() before it (ask_once)
    client = client_for(handler, model="claude-haiku-5-5")
    await client.stream_step("claude-sonnet-5-5", [{"role": "user", "content": "x"}], None,
                             on_delta)
    assert sent[0]["max_tokens"] == most


@pytest.mark.parametrize(("role_levels", "asked", "given", "said"), [
    # with no most, never above the role's own level: a higher one is the user's to give
    ({"effort": "medium"}, "max", "medium",
     "effort max was lowered to medium: the most the Coder role may be given without the "
     "user's say."),
    ({"effort": "medium"}, "low", "low", None),  # lower is fine
    # Auto (no level of its own): the opener picks, up to high where the user gave no most
    ({}, "high", "high", None),
    ({}, "max", "high", "effort max was lowered to high: the most the Coder role may be given "
     "without the user's say."),
    ({"max_effort": "xhigh"}, "xhigh", "xhigh", None),
    ({"effort": "low", "max_effort": "xhigh"}, "xhigh", "xhigh", None),  # a most the user gave
])
def test_with_no_most_a_task_gets_no_more_than_its_roles_own_level(
    leveled, wait_run, project_dir, role_levels, asked, given, said  # noqa: F811
):
    client, model = leveled({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "t", "effort": asked})),
                 text("done")],
        "Coder": [text("fixed")],
    })
    if role_levels:
        set_role(client, "Coder", **role_levels)
    cid = ran(client, wait_run, project_dir)
    assert model.levels["Coder"] == [given]
    result = next(t for t in client.get(f"/api/conversations/{cid}").json()["tool_calls"]
                  if t["name"] == "spawn_agent")["result"]
    assert result.endswith(said) if said else "effort" not in result


@pytest.mark.parametrize(("effort", "max_effort", "asked", "given"), [
    (None, None, None, None),  # nothing asked: none here (B-402: `_spawn_one` gives AUTO_START)
    (None, None, "medium", "medium"),
    (None, None, "max", "high"),  # Auto's most with none given
    (None, "max", "max", "max"),  # Auto with a most
    (None, None, "off", None),  # Auto never picks Off
    (None, "low", "off", None),
    (None, "off", "low", "off"),  # Auto with a most of Off: the user chose no thinking
    (None, "off", "off", "off"),
    ("medium", "high", "high", "high"),  # a start and a most
    ("medium", "high", "max", "high"),
    ("medium", None, "high", "medium"),  # a start, no most: never above it
    ("medium", None, "off", "off"),  # the user set a start: lower, to Off, is fine
])
def test_auto_thinking_caps(effort, max_effort, asked, given):
    from types import SimpleNamespace

    from app.agent.spawn_mixin import capped_effort

    role = SimpleNamespace(effort=effort, max_effort=max_effort)
    assert capped_effort(asked, role) == given  # type: ignore[arg-type]


@pytest.mark.parametrize(("asked", "takes", "sent"), [
    ("max", ("off", "low", "medium", "high", "xhigh"), "xhigh"),  # Qoder
    ("low", ("medium", "high"), None),  # none at or below it
    ("medium", (), None),  # Copilot: no levels known
    ("medium", None, None),
    ("high", ("off", "low"), "low"),  # never down to Off
    ("off", ("off", "low"), "off"),  # only an Off asked is Off
    ("off", ("low",), None),
    ("medium", ("low", "medium"), "medium"),
    (None, ("low",), None),
])
def test_a_model_without_the_level_is_sent_the_nearest_lower_one(asked, takes, sent):
    from types import SimpleNamespace

    from app.agent.ctx import sent_effort

    assert sent_effort(SimpleNamespace(effort=asked),  # type: ignore[arg-type]
                       SimpleNamespace(efforts=takes)) == sent  # type: ignore[arg-type]


def test_an_auto_off_is_not_sent_and_the_openers_pick_is_on_the_record_with_why(
    leveled, wait_run, project_dir  # noqa: F811
):
    client, model = leveled({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "t", "effort": "off"}),
                      call("spawn_agent", {"role": "Coder", "task": "u", "effort": "medium",
                                           "why": "a normal code change"}, "c2")),
                 text("done")],
        "Coder": [text("fixed"), text("fixed")],
    }, efforts=("off", *LEVELS))
    cid = ran(client, wait_run, project_dir)
    snap = client.get(f"/api/conversations/{cid}").json()
    coders = [level for name, levels in model.levels.items() if name.startswith("Coder")
              for level in levels]
    assert sorted(map(str, coders)) == ["None", "medium"]
    results = [t["result"] for t in snap["tool_calls"] if t["name"] == "spawn_agent"]
    assert any(r.endswith("effort off: only the user sets Off for the Coder role; none was "
                          "sent, so its model's own level ran.") for r in results)
    notes = {a["effort_note"] for a in snap["agents"] if a["depth"] > 0}
    assert notes == {None, "Thinking Medium, picked by the Orchestrator: “a normal code change”."}


def test_a_model_that_takes_no_levels_is_said_once_and_no_lowering_with_it(
    leveled, wait_run, project_dir  # noqa: F811
):
    client, model = leveled({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "t", "effort": "max"})),
                 text("done")],
        "Coder": [text("fixed")],
    }, efforts=None)
    set_role(client, "Coder", max_effort="medium")
    cid = ran(client, wait_run, project_dir)
    result = next(t for t in client.get(f"/api/conversations/{cid}").json()["tool_calls"]
                  if t["name"] == "spawn_agent")["result"]
    assert result.endswith("\n\neffort max: its model takes no levels: none is sent.")
    assert "lowered" not in result and model.levels["Coder"] == [None]


def test_a_level_not_in_the_list_is_refused_to_the_lead(
    leveled, wait_run, project_dir  # noqa: F811
):
    client, model = leveled({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "t", "effort": "turbo"})),
                 text("done")],
    })
    cid = ran(client, wait_run, project_dir)
    spawned = next(t for t in client.get(f"/api/conversations/{cid}").json()["tool_calls"]
                   if t["name"] == "spawn_agent")
    assert spawned["status"] == "failed" and "effort is one of: off, low, medium" in spawned["result"]
    assert "Coder" not in model.levels


def test_an_agent_gone_on_with_in_a_later_turn_keeps_its_level(
    leveled, wait_run, project_dir  # noqa: F811
):
    client, model, _pid, cid = setup(leveled, project_dir, {
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": OLD_TASK, "effort": "low"},
                           "s1")), text("made"), GO_ON, text("done")],
        "Coder": [text(OLD_WORDS), text("again")],
    })
    set_role(client, "Coder", effort="high")
    turn(client, wait_run, cid, FIRST)
    turn(client, wait_run, cid, SECOND)
    assert model.levels["Coder"] == ["low", "low"]  # not the role's own, high


def test_the_leads_level_is_set_only_from_the_apps_own_page(leveled, project_dir):  # noqa: F811
    client, _model = leveled({"Lead": []})
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    del client.headers["Origin"]
    assert client.patch(f"/api/conversations/{cid}", json={"lead_effort": "max"}).status_code == 403
    assert client.get(f"/api/conversations/{cid}").json()["conversation"]["lead_effort"] is None


def test_the_api_levels_are_the_ones_the_code_knows():
    assert get_args(Effort) == EFFORTS


def test_the_openers_pick_stays_on_the_record_beside_the_level_really_sent(
    leveled, wait_run, project_dir  # noqa: F811
):
    # e1e1c4b6: a lower level sent (or a refused one) is said after the pick, never over it.
    client, _model = leveled({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "t", "effort": "high",
                                           "why": "a hard bug"})), text("done")],
        "Coder": [text("fixed")],
    }, efforts=("low", "medium"))
    cid = ran(client, wait_run, project_dir)
    (coder,) = [a for a in client.get(f"/api/conversations/{cid}").json()["agents"]
                if a["depth"] > 0]
    assert coder["effort"] == "medium"
    assert coder["effort_note"].startswith(
        "Thinking High, picked by the Orchestrator: “a hard bug”. high → medium: the nearest "
        "lower level ")


@pytest.mark.parametrize(("role_levels", "efforts", "sent", "note"), [
    ({}, ("off", *LEVELS), "medium",
     "Thinking Medium, KOLONİ's default for Auto (the opener gave no level)."),
    ({"max_effort": "low"}, ("off", *LEVELS), "low",  # (under the role's most)
     "Thinking Low, KOLONİ's default for Auto (the opener gave no level)."),
    ({"max_effort": "off"}, ("off", *LEVELS), "off", "Thinking Off (the role's most)."),
    ({}, None, None,  # (a model that takes no levels: nothing is sent, and said so)
     "KOLONİ's default for Auto, Medium: its model takes no levels: none is sent."),
    ({"effort": "high"}, ("off", *LEVELS), "high", None),  # a start level: as before
])
def test_auto_with_no_level_from_the_opener_gets_medium_and_says_so(
    leveled, wait_run, project_dir, role_levels, efforts, sent, note  # noqa: F811
):
    """B-402 (live): Copilot and Codex openers gave no effort, and an Auto role's sub-agent ran
    with no level and nothing on its record."""
    client, model = leveled({"Lead": [spawn("Coder"), text("done")], "Coder": [text("fixed")]},
                            efforts=efforts)
    if role_levels:
        set_role(client, "Coder", **role_levels)
    cid = ran(client, wait_run, project_dir)
    assert model.levels["Coder"] == [sent]
    (coder,) = [a for a in client.get(f"/api/conversations/{cid}").json()["agents"]
                if a["depth"] > 0]
    assert (coder["effort"], coder["effort_note"]) == (sent, note)


@pytest.mark.parametrize("role_levels,copilot", [({}, False), ({"effort": "high"}, False),
                                                 ({}, True)])
def test_a_model_whose_name_fixes_its_level_is_sent_none_and_its_record_says_why(
    leveled, wait_run, project_dir, role_levels, copilot  # noqa: F811
):
    """B-404 (live): agy refused gemini-3.8-flash-low with --effort medium (Auto's default): a
    model whose name says its level is sent none - Auto's or the role's - and the record says
    why. (As `AgyClient` has it for such a name: no levels, and `level_named`.) Copilot's auto
    too, in its own words: Copilot picks its model and level (measured 7 Nov 2026)."""
    client, model = leveled({"Lead": [spawn("Coder"), text("done")], "Coder": [text("fixed")]},
                            efforts=())
    model.level_named = True
    if copilot:
        model.command = "copilot"
    if role_levels:
        set_role(client, "Coder", **role_levels)
    cid = ran(client, wait_run, project_dir)
    assert model.levels["Coder"] == [None]
    (coder,) = [a for a in client.get(f"/api/conversations/{cid}").json()["agents"]
                if a["depth"] > 0]
    asked = role_levels.get("effort", "medium")
    assert (coder["effort"], coder["effort_note"]) == (None, (
        f"{asked} → none: Copilot's auto picks the model and its level; none is sent." if copilot
        else f"{asked} → none: {model.model_id} has its level in its name, and takes no other."))
    # ...and who uses what says so, for the role's card (asked for its levels only)
    assert {row["level_named"] for row in client.get("/api/roles/models?levels=1").json()} == {True}
    assert {row["level_named"] for row in client.get("/api/roles/models").json()} == {False}
