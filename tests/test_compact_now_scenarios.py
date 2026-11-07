"""Slice 77a's acceptance set: the rest of compaction, first half. Written before the code.

Design: `tasarim/plans/kalan-isler.md` row 77; `tasarim/specs/2026-10-20-dilim-59-dusunme-ve-baglam-design.md`
§3, §3a, §3d; the Compact button of slice 27 §4.

Contract:
- `GET /api/compaction` -> {"compact_at": 75}: the % of its window past which an agent KOLONİ
  compacts has the older part of what it is sent summarised (one setting for the whole app).
  `PUT /api/compaction` (the app's own page only) with {"compact_at": 50..95} saves it and
  answers like GET; anything else is 422.
- Anthropic's API is compacted by KOLONİ like any model that is not a CLI: its window is what
  the Models API says (`max_input_tokens`); the summary is asked with a `max_tokens` of its own.
- `POST /api/agents/{id}/compact` (the app's own page only): a lead whose turn is over has its
  older part summarised now, as after a turn, whatever its size; answers with the agent.
  409 for a CLI that keeps what it is sent itself (`compacts_itself`), an agent at work (it compacts itself at its
  steps), a sub-agent, and one a later agent goes on from.
- (The conversation header's context line is the page's: `RunStatus.test.tsx`.)
"""

import asyncio
import json
import threading

import httpx2
import pytest

from app.api.agents import router
from tests.keyed import TestClient

if not any(getattr(route, "path", "") == "/api/compaction" for route in router.routes):
    pytest.skip("slice 77a is not built yet", allow_module_level=True)  # written before the code

from app.agent import COMPACT_FLAG  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.db.models import Agent, Flag  # noqa: E402
from app.main import create_app  # noqa: E402
from app.model_anthropic import AnthropicClient  # noqa: E402
from app.model_client import ModelUnavailable  # noqa: E402
from tests.conftest import Gate  # noqa: E402
from tests.test_chat_flow import text  # noqa: E402
from tests.test_context_scenarios import (  # noqa: E402,F401
    ORIGIN,
    SUMMARISED,
    WORK,
    ran,
    sent,
    windowed,
)
from tests.test_context_state import FULL_AT_THE_END, lead_of  # noqa: E402
from tests.test_model_anthropic import events  # noqa: E402
from tests.test_spawn import begin, call, spawn, step  # noqa: E402

# --- the threshold ------------------------------------------------------------------------


def test_the_threshold_is_75_until_the_user_sets_another(windowed):  # noqa: F811
    client, _model = windowed([])
    assert client.get("/api/compaction").json() == {"compact_at": 75}
    assert client.put("/api/compaction", json={"compact_at": 90}).json() == {"compact_at": 90}
    assert client.get("/api/compaction").json() == {"compact_at": 90}


def test_below_the_users_threshold_nothing_is_summarised(windowed, wait_run, project_dir):  # noqa: F811
    client, model = windowed([*WORK, text("done")])  # its second step fills 80%
    assert client.put("/api/compaction", json={"compact_at": 90}).status_code == 200
    ran(client, wait_run, project_dir)
    assert len(model.calls) == 3 and SUMMARISED not in sent(model.calls[2])


def test_past_the_users_threshold_the_older_part_is_summarised(windowed, wait_run, project_dir):  # noqa: F811
    client, model = windowed([step(call("read_file", {"path": "hello.py"}, "r1"), i=100),
                              step(call("list_dir", {}, "l1"), i=600),
                              text("SUMMARY: hello.py prints hi"), text("done")])
    assert client.put("/api/compaction", json={"compact_at": 50}).status_code == 200
    ran(client, wait_run, project_dir)
    assert len(model.calls) == 4 and "SUMMARY: hello.py prints hi" in sent(model.calls[3])


@pytest.mark.parametrize("body", [
    {"compact_at": 49}, {"compact_at": 96}, {"compact_at": 75.5}, {"compact_at": "75"}, {},
    {"compact_at": 80, "more": 1},
])
def test_a_threshold_outside_50_to_95_is_refused(windowed, body):  # noqa: F811
    client, _model = windowed([])
    assert client.put("/api/compaction", json=body).status_code == 422
    assert client.get("/api/compaction").json() == {"compact_at": 75}


def test_the_threshold_is_set_only_from_the_apps_own_page(windowed):  # noqa: F811
    client, _model = windowed([])
    del client.headers["Origin"]
    assert client.put("/api/compaction", json={"compact_at": 90}).status_code == 403
    assert client.get("/api/compaction").json() == {"compact_at": 75}


def test_a_threshold_row_out_of_shape_is_held_to_50_95_or_counts_for_nothing(windowed):  # noqa: F811
    client, _model = windowed([])
    for value, read in (("abc", 75), ("200", 95), ("10", 50)):
        with client.app.state.runner._factory() as session:
            session.merge(Flag(name=COMPACT_FLAG, value=value))
            session.commit()
        assert client.get("/api/compaction").json() == {"compact_at": read}


# --- Anthropic's API ----------------------------------------------------------------------


def answered(sent_tokens, content="", tool=None, stop=None):
    """One streamed answer of the Messages API: text, or one tool call."""
    blocks = [{"type": "content_block_start", "index": 0, "content_block": {"type": "text"}},
              {"type": "content_block_delta", "index": 0,
               "delta": {"type": "text_delta", "text": content}}] if content else []
    if tool:
        name, arguments, call_id = tool
        blocks += [
            {"type": "content_block_start", "index": 1,
             "content_block": {"type": "tool_use", "id": call_id, "name": name}},
            {"type": "content_block_delta", "index": 1,
             "delta": {"type": "input_json_delta", "partial_json": json.dumps(arguments)}},
        ]
    return events(
        {"type": "message_start", "message": {"usage": {"input_tokens": sent_tokens,
                                                         "output_tokens": 1}}},
        *blocks,
        {"type": "message_delta",
         "delta": {"stop_reason": stop or ("tool_use" if tool else "end_turn")},
         "usage": {"output_tokens": 5}},
        {"type": "message_stop"},
    )


def on_anthropic(settings_env, wait_run, project_dir, answers):
    """A turn on Anthropic's API (a window of 1000) answered with `answers` in turn (a stream,
    or a whole response): its snapshot, and every request body it sent."""
    bodies: list[dict] = []

    def api(request):
        if request.method == "GET":  # the Models API: its window and the most it writes
            return httpx2.Response(200, json={"id": "claude-test", "max_input_tokens": 1000,
                                              "max_tokens": 4096})
        bodies.append(json.loads(request.content))
        answer = answers[len(bodies) - 1]
        return answer if isinstance(answer, httpx2.Response) else httpx2.Response(
            200, content=answer)

    model = AnthropicClient("https://api.test", "sk-ant-test", "claude-test",
                            transport=httpx2.MockTransport(api))
    with TestClient(create_app(load_settings(settings_env), model=model),
                    base_url=ORIGIN) as client:
        client.headers["Origin"] = ORIGIN
        return ran(client, wait_run, project_dir)[1], bodies


READ = answered(100, tool=("read_file", {"path": "hello.py"}, "toolu_1"))


def test_an_anthropic_summary_cut_at_its_max_tokens_is_not_taken(
    settings_env, wait_run, project_dir
):
    snap, bodies = on_anthropic(settings_env, wait_run, project_dir, [
        READ, answered(800, tool=("list_dir", {}, "toolu_2")),
        answered(50, "SUMMARY: hello.py pri", stop="max_tokens"), answered(300, "done")])
    assert snap["runs"][0]["status"] == "completed" and len(bodies) == 4
    after = json.dumps(bodies[3])
    assert "SUMMARY: hello.py pri" not in after and "print('hi')" not in after  # left out
    (lead,) = snap["agents"]
    assert lead["summarised"] == 0 and "it was cut at its length limit" in lead["summary_note"]


def test_anthropics_prompt_is_too_long_is_summarised_and_asked_once_more(
    settings_env, wait_run, project_dir
):
    too_long = httpx2.Response(400, json={"type": "error", "error": {
        "type": "invalid_request_error",
        "message": "prompt is too long: 1200 tokens > 1000 maximum"}})
    # (What it read is larger than its summary: asked again only with less.)
    (project_dir / "big.txt").write_text("big " * 1000)
    snap, bodies = on_anthropic(settings_env, wait_run, project_dir, [
        answered(100, tool=("read_file", {"path": "big.txt"}, "toolu_1")),
        answered(200, tool=("list_dir", {}, "toolu_2")), too_long,
        answered(50, "SUMMARY: hello.py prints hi"), answered(300, "done")])
    assert snap["runs"][0]["status"] == "completed" and len(bodies) == 5
    again = json.dumps(bodies[4])
    assert "SUMMARY: hello.py prints hi" in again and "big big" not in again


def test_anthropics_api_is_compacted_by_koloni_against_its_models_window(
    settings_env, wait_run, project_dir
):
    snap, bodies = on_anthropic(settings_env, wait_run, project_dir, [
        READ, answered(800, tool=("list_dir", {}, "toolu_2")),  # 80% of its window
        answered(50, "SUMMARY: hello.py prints hi"), answered(300, "done")])
    assert snap["runs"][0]["status"] == "completed" and len(bodies) == 4
    summariser, after = json.dumps(bodies[2]), json.dumps(bodies[3])
    assert "print('hi')" in summariser and "tools" not in bodies[2]
    assert bodies[2]["max_tokens"] == 250  # a quarter of its window
    assert SUMMARISED in after and "SUMMARY: hello.py prints hi" in after
    assert "print('hi')" not in after and "look at hello please" in after
    (lead,) = snap["agents"]
    assert lead["context_window"] == 1000 and lead["summarised"] == 2


# --- Compact now --------------------------------------------------------------------------

# A short turn: 20% of its window, nothing summarised by itself.
SHORT = [step(call("read_file", {"path": "hello.py"}, "r1"), i=100), text("It prints hi.", i=200)]


def test_compact_now_summarises_a_lead_whose_turn_is_over_and_the_next_turn_goes_on_from_it(
    windowed, wait_run, project_dir  # noqa: F811
):
    client, model = windowed([*SHORT, text("SUMMARY: hello.py prints hi"), text("done again")])
    cid, _snap = ran(client, wait_run, project_dir)
    first = lead_of(client, cid)
    assert len(model.calls) == 2 and first["summarised"] == 0
    compacted = client.post(f"/api/agents/{first['id']}/compact")
    assert compacted.status_code == 200, compacted.text
    lead = compacted.json()
    assert lead["summarised"] == 2 and lead["summary"] == "SUMMARY: hello.py prints hi"
    assert lead["status"] == "completed" and "print('hi')" in sent(model.calls[2])
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "and now?"})
    snap = wait_run(client, cid, posted.json()["run"]["id"])
    later = sent(model.calls[3])
    assert len(model.calls) == 4 and "SUMMARY: hello.py prints hi" in later
    assert "print('hi')" not in later and "look at hello please" in later
    assert snap["agents"][-1]["summarised"] == 2


def test_compact_now_with_nothing_older_summarises_nothing(windowed, wait_run, project_dir):  # noqa: F811
    client, model = windowed([text("hi")])
    cid, _snap = ran(client, wait_run, project_dir)
    lead = client.post(f"/api/agents/{lead_of(client, cid)['id']}/compact")
    assert lead.status_code == 200 and lead.json()["summarised"] == 0 and len(model.calls) == 1


def test_compact_now_whose_model_cannot_be_asked_says_so(windowed, wait_run, project_dir):  # noqa: F811
    client, model = windowed([*SHORT])
    cid, _snap = ran(client, wait_run, project_dir)

    async def down():
        raise ModelUnavailable("model server unreachable: down")

    model.info = down
    refused = client.post(f"/api/agents/{lead_of(client, cid)['id']}/compact")
    assert refused.status_code == 409 and "not compacted: model server unreachable: down" in refused.text
    assert lead_of(client, cid)["summarised"] == 0


def test_compact_now_while_its_turn_is_still_being_closed_is_refused(
    windowed, wait_run, project_dir  # noqa: F811
):
    client, model = windowed([*SHORT, text("SUMMARY: never asked")])
    held, done = threading.Event(), threading.Event()

    async def noting(_ctx):  # what the turn found, noted after it is over: held here
        held.set()
        while not done.is_set():
            await asyncio.sleep(0.01)

    client.app.state.runner._note_what_it_found = noting
    cid, run_id = begin(client, project_dir, mode="full_auto", content="look at hello please")
    assert held.wait(5)
    lead = lead_of(client, cid)
    assert lead["status"] == "completed"
    refused = client.post(f"/api/agents/{lead['id']}/compact")
    assert refused.status_code == 409 and "still being closed" in refused.text
    done.set()
    wait_run(client, cid, run_id)
    assert len(model.calls) == 2


def test_while_compact_now_works_another_and_a_correction_are_refused(
    windowed, wait_run, project_dir  # noqa: F811
):
    gate = Gate()
    client, _model = windowed([*SHORT, gate.step(text("SUMMARY: hello.py prints hi"))])
    cid, _snap = ran(client, wait_run, project_dir)
    url = f"/api/agents/{lead_of(client, cid)['id']}"
    answered_with = {}
    first = threading.Thread(target=lambda: answered_with.update(it=client.post(f"{url}/compact")))
    first.start()
    try:
        gate.wait_partial()
        again = client.post(f"{url}/compact")
        assert again.status_code == 409 and "being summarised already" in again.text
        corrected = client.patch(f"{url}/summary", json={"summary": "my words", "summarised": 0})
        assert corrected.status_code == 409 and "being summarised" in corrected.text
    finally:
        gate.release()
        first.join(5)
    lead = answered_with["it"].json()
    assert lead["summarised"] == 2 and lead["summary"] == "SUMMARY: hello.py prints hi"


def test_a_correction_while_a_step_is_summarised_is_refused(windowed, wait_run, project_dir):  # noqa: F811
    """77: the summary being made at a step would be written over the user's words."""
    gate = Gate()
    client, _model = windowed([*WORK, gate.step(text("SUMMARY: hello.py prints hi")),
                               text("done")])
    cid, run_id = begin(client, project_dir, mode="full_auto", content="look at hello please")
    try:
        gate.wait_partial()
        url = f"/api/agents/{lead_of(client, cid)['id']}/summary"
        corrected = client.patch(url, json={"summary": "my words", "summarised": 0})
        assert corrected.status_code == 409 and "being summarised" in corrected.text
    finally:
        gate.release()
    snap = wait_run(client, cid, run_id)
    assert snap["agents"][0]["summary"] == "SUMMARY: hello.py prints hi"


def test_compact_now_on_a_lead_that_goes_on_from_a_summary_summarises_the_summary_too(
    windowed, wait_run, project_dir  # noqa: F811
):
    client, model = windowed([
        *SHORT, text("SUMMARY: one"),
        step(call("read_file", {"path": "hello.py"}, "r2"), i=100), text("Still hi.", i=200),
        text("SUMMARY: two"), text("done")])
    cid, _snap = ran(client, wait_run, project_dir)
    assert client.post(f"/api/agents/{lead_of(client, cid)['id']}/compact").json()["summary"] == (
        "SUMMARY: one")
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "and again?"})
    snap = wait_run(client, cid, posted.json()["run"]["id"])
    second = snap["agents"][-1]
    assert (second["summary"], second["summarised"]) == ("SUMMARY: one", 2)  # gone on from it
    after = client.post(f"/api/agents/{second['id']}/compact").json()
    assert after["summary"] == "SUMMARY: two" and after["summarised"] > 2
    assert "The summary so far:\nSUMMARY: one" in sent(model.calls[5])
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "and now?"})
    wait_run(client, cid, posted.json()["run"]["id"])
    last = sent(model.calls[6])
    assert "SUMMARY: two" in last and "SUMMARY: one" not in last and "print('hi')" not in last
    assert "Still hi." in last  # the last exchange it went on from


def test_a_working_state_edited_before_a_compaction_is_refused_after_it(
    windowed, wait_run, project_dir  # noqa: F811
):
    client, _model = windowed([
        *SHORT, text("SUMMARY: one"),
        step(call("read_file", {"path": "hello.py"}, "r2"), i=100), text("Still hi.", i=200),
        text("SUMMARY: two")])
    cid, _snap = ran(client, wait_run, project_dir)
    assert client.post(f"/api/agents/{lead_of(client, cid)['id']}/compact").status_code == 200
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "and again?"})
    second = wait_run(client, cid, posted.json()["run"]["id"])["agents"][-1]
    began = second["summarised"]  # the user opens its working state to edit
    after = client.post(f"/api/agents/{second['id']}/compact").json()
    assert after["summarised"] > began
    url = f"/api/agents/{second['id']}/summary"
    stale = client.patch(url, json={"summary": "my words", "summarised": began})
    assert stale.status_code == 409 and "summarised again since you began" in stale.text
    assert client.get(f"/api/conversations/{cid}").json()["agents"][-1]["summary"] == "SUMMARY: two"
    fresh = client.patch(url, json={"summary": "my words", "summarised": after["summarised"]})
    assert fresh.status_code == 200 and fresh.json()["summary"] == "my words"


def test_a_continuing_leads_first_step_is_compacted_at_the_threshold_set_since(
    windowed, wait_run, project_dir  # noqa: F811
):
    client, model = windowed([*FULL_AT_THE_END, text("SUMMARY: hello.py prints hi"),
                              text("done again")])
    assert client.put("/api/compaction", json={"compact_at": 90}).status_code == 200
    cid, _snap = ran(client, wait_run, project_dir)  # its last step sent 80%: not after it
    assert len(model.calls) == 2 and lead_of(client, cid)["summarised"] == 0
    assert client.put("/api/compaction", json={"compact_at": 75}).status_code == 200
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "and now?"})
    snap = wait_run(client, cid, posted.json()["run"]["id"])
    assert len(model.calls) == 4 and "print('hi')" in sent(model.calls[2])  # its first step
    assert "SUMMARY: hello.py prints hi" in sent(model.calls[3])
    assert snap["agents"][-1]["summarised"] == 2


@pytest.mark.parametrize("mode, kept", [("step", None), ("native", {"id": "s-0001", "under": "u"})])
def test_compact_now_is_refused_for_a_cli_that_keeps_what_it_is_sent(  # noqa: F811
    windowed, wait_run, project_dir, mode, kept  # noqa: F811
):
    # (Step by step, as before; or one whose next turn goes on in its session. A native or
    # session CLI that starts anew is KOLONİ's to compact: test_cli_compaction.)
    client, model = windowed([*SHORT])
    cid, _snap = ran(client, wait_run, project_dir)
    lead_id = lead_of(client, cid)["id"]
    with client.app.state.runner._factory() as session:
        lead = session.get_one(Agent, lead_id)
        lead.provider_mode, lead.cli_session = mode, kept
        session.commit()
    assert lead_of(client, cid)["compacts_itself"] is True
    refused = client.post(f"/api/agents/{lead_id}/compact")
    assert refused.status_code == 409 and (
        "each step is sent a trimmed history; not compacted" if mode == "step"
        else "keeps what it is sent itself") in refused.text
    assert len(model.calls) == 2


def test_compact_now_is_refused_for_an_agent_at_work_and_a_sub_agent(
    windowed, wait_run, project_dir  # noqa: F811
):
    gate = Gate()
    client, model = windowed({
        "Lead": [spawn("Coder", "look at hello.py"), gate.step(text("all done"))],
        "Coder": [text("It prints hi.")],
    })
    cid, run_id = begin(client, project_dir, mode="full_auto")
    gate.wait_partial()
    snap = client.get(f"/api/conversations/{cid}").json()
    lead = next(a for a in snap["agents"] if a["depth"] == 0)
    coder = next(a for a in snap["agents"] if a["depth"] == 1)
    at_work = client.post(f"/api/agents/{lead['id']}/compact")
    assert at_work.status_code == 409 and "at work" in at_work.text
    assert client.post(f"/api/agents/{coder['id']}/compact").status_code == 409
    gate.release()
    wait_run(client, cid, run_id)


def test_compact_now_is_refused_where_a_later_agent_goes_on(windowed, wait_run, project_dir):  # noqa: F811
    client, _model = windowed([text("hi"), text("hi again")])
    cid, _snap = ran(client, wait_run, project_dir)
    first = lead_of(client, cid)["id"]
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "and now?"})
    wait_run(client, cid, posted.json()["run"]["id"])
    refused = client.post(f"/api/agents/{first}/compact")
    assert refused.status_code == 409 and "goes on from this one" in refused.text


def test_compact_now_only_from_the_apps_own_page(windowed, wait_run, project_dir):  # noqa: F811
    client, model = windowed([*SHORT])
    cid, _snap = ran(client, wait_run, project_dir)
    lead_id = lead_of(client, cid)["id"]
    del client.headers["Origin"]
    assert client.post(f"/api/agents/{lead_id}/compact").status_code == 403
    assert len(model.calls) == 2
