"""Slice 59b's own checks beside its acceptance set: how a summarised history is rebuilt."""

import httpx2
import pytest

from app import ledger
from app.agent import (
    ANSWER_PREFIX,
    SUMMARY_STUCK,
    THEIRS,
    TRIMMED,
    _compacted,
    _in_words,
    _summarised,
    _Summary,
)
from app.config import load_settings
from app.main import create_app
from app.model_client import ModelUnavailable, OpenAICompatClient, StepResult
from tests.fakes import sse_body
from tests.keyed import TestClient
from tests.test_chat_flow import text
from tests.test_context_scenarios import (  # noqa: F401
    ORIGIN,
    SUMMARISED,
    WORK,
    Windowed,
    ran,
    sent,
    windowed,
)
from tests.test_parallel import until
from tests.test_spawn import call, role_id, spawn, step


def said(role, content, *calls):
    message = {"role": role, "content": content}
    if calls:
        message["tool_calls"] = [{"id": c, "type": "function", "function": {
            "name": "read_file", "arguments": "{}"}} for c in calls]
    return message


HISTORY = [
    said("system", "rules"),
    said("user", "first ask"),
    said("assistant", "", "a1"),
    {"role": "tool", "tool_call_id": "a1", "content": "old output"},
    said("user", "second ask"),
    said("assistant", "", "a2"),
    {"role": "tool", "tool_call_id": "a2", "content": ANSWER_PREFIX + "yes, go on"},
    # The last exchange: two calls made together.
    said("assistant", "both", "b1", "b2"),
    {"role": "tool", "tool_call_id": "b1", "content": "one"},
    {"role": "tool", "tool_call_id": "b2", "content": "two"},
]


def test_the_users_words_stay_in_order_and_the_last_exchange_whole():
    out = _compacted(HISTORY, 7, "S")
    assert out[0] == HISTORY[0] and out[-3:] == HISTORY[-3:]
    # Their messages, and their answer as a message of theirs (its call is not sent).
    assert [m["content"] for m in out[1:4]] == [
        "first ask", "second ask", ANSWER_PREFIX + "yes, go on"]
    assert all(m["role"] == "user" for m in out[1:5]) and "S" in out[4]["content"]
    assert "old output" not in str(out)
    # Found again as the third answer, wherever a note handed over late puts it.
    later = [*HISTORY[:4], said("user", "a note handed over late"), *HISTORY[4:]]
    assert _summarised(later, _Summary(2, "S"))[1:5] == [out[1], later[4], *out[2:4]]


def test_without_a_summary_the_older_tool_outputs_are_left_out_but_the_users_answers():
    out = _summarised(HISTORY, _Summary(failed=True))
    assert out[3]["content"] == TRIMMED and out[6] == HISTORY[6] and out[-3:] == HISTORY[-3:]
    assert HISTORY[3]["content"] == "old output"  # what is built from the record is not changed


def test_a_failed_summary_does_not_fail_the_turn(windowed, wait_run, project_dir):  # noqa: F811
    client, model = windowed([
        *WORK, ModelUnavailable("model server unreachable"),
        step(call("read_file", {"path": "hello.py"}, "r2"), i=900), text("done"),
    ])
    _cid, snap = ran(client, wait_run, project_dir)
    assert snap["runs"][0]["status"] == "completed"
    assert len(model.calls) == 5  # asked once: the step after the next is not summarised
    after = model.calls[3]
    assert SUMMARISED not in sent(after) and TRIMMED in sent(after)
    assert "look at hello please" in sent(after) and after[-1]["role"] == "tool"
    (lead,) = snap["agents"]
    assert lead["summarised"] == 0 and "could not be summarised" in lead["summary_note"]


def test_the_agents_page_is_told_the_window_a_server_says_without_a_cost(windowed):  # noqa: F811
    client, model = windowed([])

    async def found_window():
        return 80128

    model.found_window = found_window  # as llama-server's `/props` says it
    rows = client.get("/api/roles/models?levels=1").json()
    assert rows and all(row["context_window"] == 80128 for row in rows)
    assert all(row["context_window"] is None for row in client.get("/api/roles/models").json())
    assert model.calls == []  # nothing was asked of the model itself


def test_the_summariser_reads_the_users_words_in_their_place_and_spends_the_agents_tokens(
    windowed, wait_run, project_dir  # noqa: F811
):
    client, model = windowed([*WORK, text("SUMMARY: hello.py prints hi"), text("done")])
    _cid, snap = ran(client, wait_run, project_dir)
    asked = sent(model.calls[2])
    assert f"user {THEIRS}: look at hello please" in asked
    assert asked.index("look at hello please") < asked.index("print('hi')")
    # An answer of theirs is read as theirs too.
    answer = {"role": "tool", "content": ANSWER_PREFIX + "yes"}
    assert _in_words(answer) == f"user {THEIRS}: {ANSWER_PREFIX}yes"
    (lead,) = snap["agents"]
    assert lead["output_tokens"] == 2 + 2 + 3 + 3  # the summary's are the agent's
    assert lead["input_tokens"] == 5  # its size is its last step's, not the summary's


class Told(httpx2.MockTransport):
    """Answers `/props` with the next of `answers`: a status, or an exception raised."""

    def __init__(self, answers):
        self.answers = list(answers)
        super().__init__(self.answer)

    def answer(self, request):
        said = self.answers.pop(0)
        if isinstance(said, Exception):
            raise said
        if said == 200:
            return httpx2.Response(200, json={"default_generation_settings": {"n_ctx": 80128}})
        return httpx2.Response(said)


@pytest.mark.anyio
async def test_a_window_is_kept_only_once_said():
    loading = OpenAICompatClient("http://model/v1", transport=Told([
        httpx2.ConnectError("down"), 503, 200]))
    assert await loading.found_window() is None  # not answering: asked again
    assert await loading.found_window() is None  # still loading: asked again
    assert await loading.found_window() == 80128
    assert await loading.found_window() == 80128  # kept: not asked again
    other = OpenAICompatClient("http://model/v1", transport=Told([404]))
    assert await other.found_window() is None
    assert await other.found_window() is None  # no `/props` at all: kept, not asked again


class Capped(Windowed):
    """A windowed model that keeps what each request asked for besides its messages."""

    def __init__(self, steps, window):
        super().__init__(steps, window)
        self.more = []

    async def stream_step(self, model_id, messages, tools, on_delta, on_thinking=None, **more):
        self.more.append(more)
        return await super().stream_step(model_id, messages, tools, on_delta, on_thinking)


def test_what_the_summariser_reads_fits_half_the_window_and_a_cut_summary_is_none(
    settings_env, wait_run, project_dir
):
    (project_dir / "big.txt").write_text("".join(f"line {n:04} of a long file\n" for n in range(600)))
    model = Capped([
        step(call("read_file", {"path": "big.txt"}, "r1"), i=10),
        step(call("read_file", {"path": "hello.py"}, "r2"), i=10),
        step(call("list_dir", {}, "l1"), i=900),
        StepResult("SUMMARY: half of it", [], 5, 3, cut=True),
        text("done"),
    ], window=1000)
    with TestClient(create_app(load_settings(settings_env), model=model), base_url=ORIGIN) as client:
        _cid, snap = ran(client, wait_run, project_dir)
    asked = sent(model.calls[3])
    assert TRIMMED in asked and "line 0599" not in asked and len(asked) < 1000 * 3
    assert model.more[3] == {"max_tokens": 250}  # a quarter of the window
    (lead,) = snap["agents"]
    assert snap["runs"][0]["status"] == "completed" and lead["summarised"] == 0
    assert "cut at its length limit" in lead["summary_note"]


def test_a_step_refused_for_its_size_is_summarised_and_asked_once_more(
    windowed, wait_run, project_dir  # noqa: F811
):
    refused = ModelUnavailable(
        "model server returned 400: the request exceeds the available context size, "
        "try increasing it")
    # (Asked again only with less: the summary has to stand for more than it says.)
    (project_dir / "hello.py").write_text("print('hi')\n" + "# a line of a long file\n" * 40)
    client, model = windowed([
        step(call("read_file", {"path": "hello.py"}, "r1"), i=100),
        step(call("list_dir", {}, "l1"), i=100),
        refused, text("SUMMARY: read hello.py"), text("done"),
    ])
    _cid, snap = ran(client, wait_run, project_dir)
    assert snap["runs"][0]["status"] == "completed" and len(model.calls) == 5
    assert SUMMARISED in sent(model.calls[4]) and "print('hi')" not in sent(model.calls[4])
    assert snap["agents"][0]["summarised"] == 2


def test_a_later_turns_lead_is_summarised_before_its_first_step(
    windowed, wait_run, project_dir  # noqa: F811
):
    client, model = windowed([
        step(call("read_file", {"path": "hello.py"}, "r1"), i=100), text("It prints hi.", i=800),
        text("SUMMARY: hello.py prints hi"), text("done again"),
    ])
    cid, _snap = ran(client, wait_run, project_dir)
    # (Summarised after its turn, while the user reads: slice 59d's `_compact_idle`.)
    until(client, cid, lambda snap: snap["agents"][0]["summarised"] == 2)
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "and now?"})
    snap = wait_run(client, cid, posted.json()["run"]["id"])
    assert len(model.calls) == 4 and "print('hi')" in sent(model.calls[2])
    first = model.calls[3]  # the new lead's first step
    assert SUMMARISED in sent(first) and "print('hi')" not in sent(first)
    assert "look at hello please" in sent(first)
    assert first[-3]["content"] == "It prints hi." and first[-1]["content"] == "and now?"
    # (K-gecmis-zengin: KOLONİ's record of the turn, after its answer - past the summarised part.)
    assert first[-2]["content"] == f'{ledger.HEAD}\n- files read: "hello.py"'
    assert snap["agents"][-1]["summarised"] == 2


def test_a_second_summary_folds_in_the_first(windowed, wait_run, project_dir):  # noqa: F811
    (project_dir / "big.txt").write_text("".join(f"line {n:04} of a long file\n" for n in range(600)))
    client, model = windowed([
        step(call("read_file", {"path": "hello.py"}, "r1"), i=100),
        step(call("list_dir", {}, "l1"), i=800),
        text("SUMMARY ONE"),
        step(call("read_file", {"path": "big.txt"}, "r2"), i=500),
        step(call("list_dir", {}, "l2"), i=800),
        text("SUMMARY TWO"),
        text("done"),
    ])
    _cid, snap = ran(client, wait_run, project_dir)
    assert len(model.calls) == 7
    assert "The summary so far:\nSUMMARY ONE" in sent(model.calls[5])
    last = sent(model.calls[6])
    assert "SUMMARY TWO" in last and "SUMMARY ONE" not in last and "line 0001" not in last
    assert last.count("earlier conversation, summarised") == 1 and "look at hello please" in last
    (lead,) = snap["agents"]
    assert lead["summarised"] == 2 + 4 and lead["summary"] == "SUMMARY TWO"


def test_a_summary_that_cannot_bring_the_size_down_is_not_tried_again(
    windowed, wait_run, project_dir  # noqa: F811
):
    client, model = windowed([
        *WORK, text("SUMMARY: hello.py prints hi"),
        step(call("read_file", {"path": "hello.py"}, "r2"), i=900),
        step(call("list_dir", {}, "l2"), i=900),
        text("done"),
    ])
    _cid, snap = ran(client, wait_run, project_dir)
    assert len(model.calls) == 6  # one summary only
    (lead,) = snap["agents"]
    assert lead["summary_note"] == SUMMARY_STUCK and lead["summarised"] == 2


def test_a_sub_agent_is_summarised_as_any_agent(windowed, wait_run, project_dir):  # noqa: F811
    # The summary request is no agent's: the scripted model takes it from the Lead's steps.
    client, model = windowed({
        "Lead": [spawn("Coder", "look at hello.py"), text("SUMMARY: coder read hello.py"),
                 text("all done")],
        "Coder": [*WORK, text("It prints hi.")],
    })
    _cid, snap = ran(client, wait_run, project_dir)
    coder = next(a for a in snap["agents"] if a["role_name"] == "Coder")
    assert coder["summarised"] == 2 and coder["context_window"] == 1000
    assert SUMMARISED in sent(model.calls_of["Coder"][-1])
    assert next(a for a in snap["agents"] if a["depth"] == 0)["summarised"] == 0


def test_a_cli_that_says_no_window_is_measured_against_none(
    windowed, wait_run, project_dir  # noqa: F811
):
    client, model = windowed([*WORK, text("done")], window=None)
    model.compacts_itself = True
    lead = f"/api/roles/{role_id(client, 'Lead')}"
    assert client.patch(lead, json={"context_window": 1000}).status_code == 200
    _cid, snap = ran(client, wait_run, project_dir)
    assert snap["agents"][0]["context_window"] is None and len(model.calls) == 3


@pytest.mark.anyio
async def test_a_call_with_no_id_is_given_one_no_other_has_and_a_cut_step_says_so():
    def handler(request):
        if request.url.path == "/props":
            return httpx2.Response(404)
        made = {"index": 0, "function": {"name": "list_dir", "arguments": "{}"}}
        return httpx2.Response(200, content=sse_body(
            {"choices": [{"delta": {"tool_calls": [made]}, "finish_reason": "length"}]}))

    client = OpenAICompatClient("http://model/v1", transport=httpx2.MockTransport(handler))

    async def nothing(_text):
        pass

    steps = [await client.stream_step("m", [], None, nothing) for _ in range(2)]
    ids = [step.tool_calls[0].id for step in steps]
    assert ids[0] != ids[1] and all(i.startswith("call_") for i in ids)
    assert all(step.cut for step in steps)  # its output limit ended it
