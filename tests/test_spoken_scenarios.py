"""Slice 32a's acceptance set, the backend's part: what the lead says aloud. Written before
the code.

A message can ask for a spoken answer. The turn's lead - and nobody else - is then told to end
its answer with one line of what to say, in the language and the manner the user chose. That
line is taken off the written answer and kept beside it; where it was not asked for, nothing
is taken off anything.
"""

import json

import pytest

from app.schemas import MessageOut

if "spoken" not in MessageOut.model_fields:  # written before the code
    pytest.skip("slice 32a is not built yet", allow_module_level=True)

from tests.test_chat_flow import text  # noqa: E402
from tests.test_spawn import call, step  # noqa: E402

ORIGIN = "http://127.0.0.1:8790"
STYLE = "short and friendly, no filler"
WRITTEN = "The total adds 20% tax once.\n\n```python\ntotal = subtotal * 1.2\n```"


def start(make_client, project_dir, scripts):
    client, model = make_client(scripts)
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "full_auto", "spawn_approval": "never"}).status_code == 200
    return client, model, cid


def say(client, wait_run, cid, content, **spoken):
    body = {"content": content, **({"spoken": spoken} if spoken else {})}
    posted = client.post(f"/api/conversations/{cid}/messages", json=body)
    assert posted.status_code in (200, 201, 202), posted.text
    snap = wait_run(client, cid, posted.json()["run"]["id"])
    assert snap["runs"][-1]["status"] == "completed", snap["runs"][-1]["error"]
    return snap


def test_the_lead_is_asked_for_a_line_to_say_and_it_is_kept_beside_the_written_answer(
    make_client, wait_run, project_dir
):
    client, model, cid = start(make_client, project_dir, {
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "look at the tax"}, "sp")),
                 text(WRITTEN + "\n\nSay: It adds the tax once, twenty percent.")],
        "Coder": [text("The tax is added once.")],
    })
    snap = say(client, wait_run, cid, "how is the total worked out?",
               language="en-US", style=STYLE)
    answer = snap["messages"][-1]
    assert answer["content"] == WRITTEN                         # the line is off the written answer
    assert answer["spoken"] == "It adds the tax once, twenty percent."
    assert snap["messages"][0]["spoken"] is None                # the user's own message has none
    # the lead was told what to end with, in which language and in the user's manner
    told = json.dumps(model.calls_of["Lead"][0])
    assert "Say:" in told and "en-US" in told and STYLE in told
    # and nobody else was
    assert "Say:" not in json.dumps(model.calls_of["Coder"])


def test_where_no_spoken_answer_was_asked_for_nothing_is_taken_off(
    make_client, wait_run, project_dir
):
    whole = "It adds the tax once.\n\nSay: this line is the model's own, and stays."
    client, model, cid = start(make_client, project_dir, {"Lead": [text(whole)]})
    snap = say(client, wait_run, cid, "how is the total worked out?")
    assert snap["messages"][-1]["content"] == whole and snap["messages"][-1]["spoken"] is None
    assert "Say:" not in json.dumps(model.calls_of["Lead"][0])


def test_a_lead_that_wrote_no_line_to_say_leaves_the_place_empty(
    make_client, wait_run, project_dir
):
    client, _model, cid = start(make_client, project_dir, {
        "Lead": [text("Say: this is not the last line.\n\nIt adds the tax once.")]})
    snap = say(client, wait_run, cid, "how is the total worked out?", language="tr-TR")
    answer = snap["messages"][-1]
    # only a last line is the line to say: nothing is made up, nothing is cut out of the middle
    assert answer["spoken"] is None
    assert answer["content"] == "Say: this is not the last line.\n\nIt adds the tax once."


def test_what_may_be_asked_for(make_client, project_dir):
    client, _model, cid = start(make_client, project_dir, {"Lead": [text("x")]})
    send = f"/api/conversations/{cid}/messages"
    for bad in ({"language": "English please"}, {"language": ""}, {},
                {"language": "en-US", "style": "x" * 301},
                {"language": "en-US", "voice": "anything else"}):
        assert client.post(send, json={"content": "hi", "spoken": bad}).status_code == 422, bad
