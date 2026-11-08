"""Slice 85b §2-§3: what the Lead and the roles are told of the files the user attached, what
their models are sent as it is, a refusal sent again without it and learned, a file read and
handed on by its name, and the save into the project asked as a write is. Slice 85c: how
Claude Code and Codex are given a picture, and a file's record of whose model was shown it."""

import base64
import contextlib
import json
import os
import sys
import tempfile
import time
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import httpx2
import pytest

from app.attachments import MAX_BYTES
from app.db.models import Attachment, FileChange, Provider
from app.model_anthropic import to_anthropic
from app.model_cli import ClaudeCliClient, CodexCliClient
from app.model_client import (
    ModelUnavailable,
    OpenAICompatClient,
    StepResult,
    ToolCallRequest,
    with_files,
)
from app.model_native import ClaudeNativeClient, CodexNativeClient
from app.model_session import ClaudeSessionClient, QoderSessionClient
from tests.test_attachments import EXE, MP4, PNG, attach
from tests.test_chat_flow import text
from tests.test_usage_scenarios import began

HERE = Path(__file__).parent
FAKE_STEP, FAKE_SESSION, FAKE_CLAUDE, FAKE_CODEX = (
    [sys.executable, str(HERE / name)] for name in (
        "fake_cli.py", "fake_session_cli.py", "fake_claude_native_cli.py",
        "fake_codex_app_server.py"))
KEPT_AS = "5e1f0c9a7b2d"  # a file in KOLONİ's store: by its id, with no extension


def step(name, args, id="c1"):
    return StepResult("", [ToolCallRequest(id, name, json.dumps(args))], 5, 3)


def seeing(client, cid, inputs=("image",)):
    """The chat's Lead on a model marked to take `inputs`, on an OpenAI-compatible server."""
    made = client.post("/api/providers", json={
        "name": "Seer", "kind": "openai_compat", "base_url": "http://localhost:9/v1",
        "default_model": "eye", "models": [{"name": "eye", "inputs": list(inputs)}]}).json()
    assert client.patch(f"/api/conversations/{cid}", json={
        "provider_id": made["id"], "model_id": "eye"}).status_code == 200
    return made["id"]


def send(client, cid, content, *ids, **more):
    told = client.post(f"/api/conversations/{cid}/messages",
                       json={"content": content, "attachments": list(ids), **more})
    assert told.status_code == 201, told.text
    return told.json()["run"]["id"]


def told_of_files(messages):
    return next(m for m in messages if m["role"] == "user"
                and "Files the user attached" in m["content"])


def cards(snap):
    """What each file's card says became of it, for each agent's model (`shown_to`)."""
    return {one["id"]: list(one["shown_to"].values()) for one in snap["attachments"]
            if one["shown_to"]}


def tried(client, provider_id):
    with client.app.state.session_factory() as session:
        return session.get_one(Provider, provider_id).tried_inputs


def test_the_lead_is_told_of_each_file_and_its_model_sees_the_image(
        make_client, wait_run, project_dir):
    client, model, _pid, cid = began(make_client, project_dir, [text("seen")])
    provider = seeing(client, cid)
    shot = attach(client, cid, "shot.png", PNG).json()
    code = attach(client, cid, "cart.ts", b"const x = 1\n").json()
    tool = attach(client, cid, "tool.exe", EXE).json()
    wait_run(client, cid, send(client, cid, "see https://stripe.com/docs", shot["id"],
                               code["id"], tool["id"]))
    said = told_of_files(model.calls[0])
    assert said["content"].startswith("see https://stripe.com/docs\n\n")
    assert '"cart.ts" (text, 12 B): 1 line. Read it with read_attachment.' in said["content"]
    assert '"tool.exe" (a program or script' in said["content"]
    assert "It is shown to you with the message." in said["content"]
    assert "Links in the message are not read" in said["content"]
    assert "End your reply with one line for each file" in said["content"]
    assert [one["kind"] for one in said["files"]] == ["image"]
    # nothing of the program reaches the model: its bytes were never kept
    assert all(Path(one["path"]).read_bytes() == PNG for one in said["files"])
    assert tried(client, provider) == {"eye": {"image": True}}  # taken: learned


def test_a_model_nobody_described_is_tried_one_marked_not_to_see_is_told_to_say_so(
        make_client, wait_run, project_dir):
    client, model, _pid, cid = began(make_client, project_dir, [text("tried"), text("cannot")])
    shot = attach(client, cid, "shot.png", PNG).json()
    wait_run(client, cid, send(client, cid, "", shot["id"]))
    assert [f["kind"] for f in told_of_files(model.calls[0])["files"]] == ["image"]
    seeing(client, cid, inputs=())  # (marked by hand: it takes none)
    again = attach(client, cid, "again.png", PNG).json()
    wait_run(client, cid, send(client, cid, "", again["id"]))
    said = told_of_files(model.calls[1])
    assert "your model is not known to see images: say so" in said["content"]
    assert "files" not in said


def test_a_size_refusal_goes_again_as_words_and_is_learned_as_nothing(
        make_client, wait_run, project_dir, monkeypatch):
    client, model, _pid, cid = began(make_client, project_dir, [
        ModelUnavailable("model server returned 400: image exceeds 5 MB maximum"), text("ok")])
    provider = seeing(client, cid)
    from app import attachments
    monkeypatch.setattr(attachments, "MAX_SENT", 20)
    shot = attach(client, cid, "shot.png", PNG[:12]).json()
    big = attach(client, cid, "big.png", PNG).json()  # (over the cap: never sent as it is)
    snap = wait_run(client, cid, send(client, cid, "look", shot["id"], big["id"]))
    first = told_of_files(model.calls[0])
    assert len(first["files"]) == 1 and "too big to be shown to a model" in first["content"]
    again = told_of_files(model.calls[1])
    assert "files" not in again and "refused as too large" in again["content"]
    # Its card says so, not "shown" (slice 85c).
    assert cards(snap) == {shot["id"]: ["not shown to eye on Seer: the request was too large"],
                           big["id"]: ["not shown to eye on Seer: over 20 B"]}
    assert tried(client, provider) is None  # no word of what the model takes
    client.delete(f"/api/providers/{provider}/tried-inputs?model=eye")  # (nothing to forget)


def test_what_was_tried_is_taken_away_by_the_user(make_client, project_dir):
    client, _model, _pid, cid = began(make_client, project_dir, [])
    provider = seeing(client, cid)
    with client.app.state.session_factory() as session:
        session.get_one(Provider, provider).tried_inputs = {"eye": {"image": False}}
        session.commit()
    url = f"/api/providers/{provider}/model-facts?model=eye"
    assert {"kind": "image", "takes": False, "source": "tried"} in client.get(url).json()["inputs"]
    gone = client.delete(f"/api/providers/{provider}/tried-inputs?model=eye")
    assert gone.status_code == 204 and tried(client, provider) is None
    assert {"kind": "image", "takes": True, "source": "you"} in client.get(url).json()["inputs"]
    no_origin = client.delete(f"/api/providers/{provider}/tried-inputs?model=eye",
                              headers={"Origin": "http://evil.test"})
    assert no_origin.status_code == 403


def test_a_refused_image_is_sent_again_as_words_said_and_never_sent_again(
        make_client, wait_run, project_dir):
    client, model, _pid, cid = began(make_client, project_dir, [
        ModelUnavailable("model server returned 500: image input is not supported"),
        text("I could not look at it"), text("again")])
    provider = seeing(client, cid)
    shot = attach(client, cid, "shot.png", PNG).json()
    run = wait_run(client, cid, send(client, cid, "look", shot["id"]))
    assert next(r for r in run["runs"] if r["id"])["status"] == "completed"
    first, again = told_of_files(model.calls[0]), told_of_files(model.calls[1])
    assert "files" in first and "files" not in again
    assert "the model refused it; it was sent again as its name and summary" in again["content"]
    assert tried(client, provider) == {"eye": {"image": False}}
    assert cards(run) == {shot["id"]: ["not shown to eye on Seer: refused"]}
    wait_run(client, cid, send(client, cid, "and now"))
    later = told_of_files(model.calls[2])
    assert "files" not in later and "not known to see images" in later["content"]


def test_a_refused_video_goes_again_as_its_frames(make_client, wait_run, project_dir):
    client, model, _pid, cid = began(make_client, project_dir, [
        ModelUnavailable("model server returned 400: video input is not supported"),
        text("frames seen")])
    provider = seeing(client, cid, ("image", "video"))
    video = attach(client, cid, "repro.mp4", b"\x00\x00\x00\x18ftypmp42").json()
    attach(client, cid, "repro.mp4 frame 1", PNG, frame_of=video["id"])
    snap = wait_run(client, cid, send(client, cid, "the bug", video["id"]))
    assert [f["kind"] for f in told_of_files(model.calls[0])["files"]] == ["video"]
    again = told_of_files(model.calls[1])
    assert [f["kind"] for f in again["files"]] == ["image"] and "as its frames" in again["content"]
    assert tried(client, provider) == {"eye": {"video": False, "image": True}}
    assert cards(snap) == {video["id"]: ["1 frames shown to eye on Seer: the video was refused"]}


def test_a_video_larger_than_a_file_reaches_even_a_model_that_watches_video_as_its_frames(
        make_client, wait_run, project_dir):
    client, model, _pid, cid = began(make_client, project_dir, [text("frames seen")])
    seeing(client, cid, ("image", "video"))
    video = attach(client, cid, "long.mp4", MP4, size=MAX_BYTES + 1).json()
    attach(client, cid, "long.mp4 frame 1.jpg", PNG, frame_of=video["id"])
    wait_run(client, cid, send(client, cid, "the bug", video["id"]))
    said = told_of_files(model.calls[0])
    assert [f["kind"] for f in said["files"]] == ["image"]
    assert "frames only: larger than 25 MB, the video is not kept" in said["content"]


def test_files_are_read_by_name_handed_on_and_the_receiver_reads_them(
        make_client, wait_run, project_dir):
    client, model, _pid, cid = began(make_client, project_dir, {
        "Lead": [step("read_attachment", {"name": "cart.ts"}),
                 step("spawn_agent", {"role": "Coder", "task": "fix it",
                                      "attachments": ["nope.ts"]}, "c2"),
                 step("spawn_agent", {"role": "Coder", "task": "fix it",
                                      "attachments": ["cart.ts"]}, "c3"),
                 text("cart.ts: the handler → Coder")],
        "Coder": [step("read_attachment", {"name": "cart.ts", "start": 2}, "k1"), text("done")]})
    code = attach(client, cid, "cart.ts", b"const x = 1\nconst y = 2\n").json()
    snap = wait_run(client, cid, send(client, cid, "fix the cart", code["id"]))
    calls = {c["provider_call_id"]: c for c in snap["tool_calls"]}
    assert "const x = 1" in calls["c1"]["result"]
    assert 'no attached file is named "nope.ts"' in calls["c2"]["result"]
    coder = next(a for a in snap["agents"] if a["depth"] == 1)
    assert snap["attachments"][0]["given_to"] == [coder["id"]]
    handed = told_of_files(model.calls_of["Coder"][0])
    assert "that were handed to you" in handed["content"] and '"cart.ts"' in handed["content"]
    assert "(lines 2-2 of 2)\nconst y = 2" in next(
        c for c in snap["tool_calls"] if c["agent_id"] == coder["id"])["result"]


def test_a_second_secret_file_kept_with_its_text_before_the_fix_is_not_read(
        make_client, wait_run, project_dir):
    client, model, _pid, cid = began(make_client, project_dir, [
        step("read_attachment", {"name": ".env (2)"}), text("ok")])
    old = attach(client, cid, "x.txt", b"API_KEY=abcdef1234567890\n").json()
    with client.app.state.session_factory() as session:  # (as a ".env (2)" was once kept)
        session.get_one(Attachment, old["id"]).name = ".env (2)"
        session.commit()
    snap = wait_run(client, cid, send(client, cid, "read it", old["id"]))
    assert "Read it with read_attachment" not in told_of_files(model.calls[0])["content"]
    (call,) = snap["tool_calls"]
    assert "secret file" in call["result"] and "abcdef1234567890" not in call["result"]


def test_saving_into_the_project_is_koloni_s_own_change_unasked_at_ask_and_undone_as_any(
        make_client, wait_run, project_dir):
    client, model, _pid, cid = began(make_client, project_dir, [text("seen")])
    assert client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "ask"}).status_code == 200
    saved, day = project_dir / "docs" / "attachments", date.today().isoformat()
    saved.mkdir(parents=True)
    (saved / f"{day}-shot.png").write_bytes(b"older")
    files = [attach(client, cid, name, data).json()["id"] for name, data in (
        ("shot.png", PNG), ("cart.ts", b"const x = 1\r\n"), ("tool.exe", EXE),
        (".env", b"KEY=abcdefgh1234\n"), ("a.txt:hidden", b"a stream's name\n"))]
    run_id = send(client, cid, "keep these", *files, save_to_project=True)
    snap = wait_run(client, cid, run_id)
    # The tick was the user's word: no card even at Ask, each an ordinary change on record.
    assert [(c["path"], c["status"], c["attachment_id"]) for c in snap["file_changes"]] == [
        (f"docs/attachments/{day}-shot (2).png", "applied", files[0]),
        (f"docs/attachments/{day}-cart.ts", "applied", files[1])]
    assert (saved / f"{day}-shot (2).png").read_bytes() == PNG
    # as it was, byte for byte
    assert (saved / f"{day}-cart.ts").read_bytes() == b"const x = 1\r\n"
    assert (saved / f"{day}-shot.png").read_bytes() == b"older"
    # Never a program, a secret's name, or a name Windows would open as a file's stream.
    assert sorted(p.name for p in saved.iterdir()) == [
        f"{day}-cart.ts", f"{day}-shot (2).png", f"{day}-shot.png"]
    assert not any(one["keep_in_project"] for one in snap["attachments"])
    assert "save_attachments" not in json.dumps(model.tool_args)
    # Undo this turn takes them away again.
    undone = client.post(f"/api/runs/{run_id}/undo")
    assert undone.status_code == 200, undone.text
    assert sorted(p.name for p in saved.iterdir()) == [f"{day}-shot.png"]


def test_saving_where_later_turns_obey_is_still_asked_at_every_level(
        make_client, wait_run, project_dir):
    client, _model, _pid, cid = began(make_client, project_dir, [text("seen")])
    assert client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "full_auto"}).status_code == 200
    # docs/attachments/ leads into .claude/: what lands there, later turns obey.
    (project_dir / ".claude").mkdir()
    (project_dir / "docs").mkdir()
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(project_dir / ".claude"),
                               str(project_dir / "docs" / "attachments"))
    else:
        os.symlink(project_dir / ".claude", project_dir / "docs" / "attachments",
                   target_is_directory=True)
    shot = attach(client, cid, "shot.png", PNG).json()
    run_id = send(client, cid, "keep", shot["id"], save_to_project=True)
    waiting = []
    for _ in range(200):
        snap = client.get(f"/api/conversations/{cid}").json()
        waiting = [c for c in snap["file_changes"] if c["status"] == "proposed"]
        if waiting:
            break
        time.sleep(0.02)
    assert [c["path"] for c in waiting] == [f"docs/attachments/{date.today().isoformat()}-shot.png"]
    # K-belge-ciktilari: while it waits, its preview is the picture, not the line its text is.
    (view,) = client.get(f"/api/conversations/{cid}/views").json()
    assert client.get(view["url"]).content == PNG
    # ...found again by its id in KOLONİ's store: a record that names another file is not read.
    (project_dir / "elsewhere.png").write_bytes(b"not the attachment")
    with client.app.state.session_factory() as session:
        row = session.get_one(FileChange, waiting[0]["id"])
        kept, row.after_from = row.after_from, str(project_dir / "elsewhere.png")
        session.commit()
    assert client.get(view["url"]).status_code == 404
    with client.app.state.session_factory() as session:
        session.get_one(FileChange, waiting[0]["id"]).after_from = kept
        session.commit()
    assert client.post(f"/api/file-changes/{waiting[0]['id']}/reject").status_code == 200
    wait_run(client, cid, run_id)
    assert list((project_dir / ".claude").iterdir()) == []


def test_saving_at_auto_edit_asks_nothing_and_writes_over_nothing(
        make_client, wait_run, project_dir):
    client, _model, _pid, cid = began(make_client, project_dir, [text("seen")])
    assert client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "auto_edit"}).status_code == 200
    shot = attach(client, cid, "shot.png", PNG).json()
    snap = wait_run(client, cid, send(client, cid, "keep", shot["id"], save_to_project=True))
    day = date.today().isoformat()
    assert [(c["path"], c["status"], c["attachment_id"]) for c in snap["file_changes"]] == [
        (f"docs/attachments/{day}-shot.png", "applied", shot["id"])]
    assert (project_dir / "docs" / "attachments" / f"{day}-shot.png").read_bytes() == PNG
    # Unticked, the next one stays KOLONİ's alone.
    other = attach(client, cid, "other.png", PNG).json()
    snap = wait_run(client, cid, send(client, cid, "just look", other["id"]))
    assert len(snap["file_changes"]) == 1
    assert sorted(p.name for p in (project_dir / "docs" / "attachments").iterdir()) == [
        f"{day}-shot.png"]


def test_a_cli_lead_is_shown_the_picture_and_its_card_says_whose_model_saw_it(
        settings_env, project_dir, wait_run, tmp_path):
    """Slice 85c: a Claude Code Lead's model is sent the picture (given its CLI's way: below),
    and its prompt names no file of KOLONİ's store. A CLI with no way to take one (Qoder) is
    told so, never "your model is not known to see". Each card says what became of it."""
    from app.config import load_settings
    from app.main import create_app
    from app.model_cli import build_step_prompt
    from tests.fakes import ScriptedModel
    from tests.keyed import TestClient

    cli = ScriptedModel([text("seen")])
    qoder = QoderSessionClient(launcher=FAKE_SESSION, **plan(tmp_path, [{"say": "cannot"}]))
    app = create_app(load_settings(settings_env), model=ScriptedModel([]),
                     clients={"Claude": cli, "Qoder": qoder})
    with TestClient(app, base_url="http://127.0.0.1:8790") as client:
        client.headers["Origin"] = "http://127.0.0.1:8790"
        made = client.post("/api/providers", json={
            "name": "Claude", "kind": "claude_cli", "mode": "step",
            "models": [{"name": "sonnet", "inputs": ["image"]}]}).json()
        other = client.post("/api/providers", json={
            "name": "Qoder", "kind": "qoder_cli", "models": [{"name": "q", "inputs": ["image"]}]})
        pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
        cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
        client.patch(f"/api/conversations/{cid}", json={
            "provider_id": made["id"], "model_id": "sonnet"})
        shot = attach(client, cid, "shot.png", PNG).json()
        first = wait_run(client, cid, send(client, cid, "look", shot["id"]))
        client.patch(f"/api/conversations/{cid}", json={
            "provider_id": other.json()["id"], "model_id": "q"})
        again = attach(client, cid, "again.png", PNG).json()
        later = wait_run(client, cid, send(client, cid, "and this", again["id"]))
    said = told_of_files(cli.calls[0])
    assert [one["kind"] for one in said["files"]] == ["image"]
    assert "It is shown to you with the message." in said["content"]
    prompt = build_step_prompt(cli.calls[0], cli.tool_args[0])
    assert "Files the user attached" in prompt and '"files": [' not in prompt
    assert shot["id"] not in prompt and "base64," not in prompt
    lead = next(a["id"] for a in first["agents"] if a["depth"] == 0)
    cards = {one["id"]: one["shown_to"] for one in later["attachments"]}
    assert cards[shot["id"]] == {lead: "shown to sonnet on Claude"}
    told = record(tmp_path)["stdin"]
    assert "Qoder has no way KOLONİ can give it images" in told and again["id"] not in told
    other_lead = next(a["id"] for a in later["agents"] if a["depth"] == 0 and a["id"] != lead)
    assert cards[again["id"]] == {
        other_lead: "not shown to q on Qoder: Qoder is given no images by KOLONİ"}


def plan(tmp_path, script=(), **more) -> dict:
    """A stand-in CLI's plan: what it records goes to record.json (`record`)."""
    written = tmp_path / "plan.json"
    written.write_text(json.dumps({"record": str(tmp_path / "record.json"),
                                   "script": list(script), **more}), encoding="utf-8")
    return {"timeout": 30.0, "env": {"FAKE_CLI_PLAN": str(written)}}


def record(tmp_path) -> dict:
    return json.loads((tmp_path / "record.json").read_text(encoding="utf-8"))


def with_picture(tmp_path) -> list[dict]:
    """A turn whose message carries a picture its model is sent as it is (`files`)."""
    (tmp_path / KEPT_AS).write_bytes(PNG)
    return [{"role": "system", "content": "You are KOLONİ's agent."},
            {"role": "user", "content": "look", "files": [{
                "name": "shot.png", "kind": "image", "mime": "image/png",
                "path": str(tmp_path / KEPT_AS), "frames": []}]}]


async def nothing(*_):
    return None


async def answered(_name, _arguments):
    return True, "ok"


def kept_out(prompt: str) -> None:
    """A prompt that names no file of KOLONİ's store: the picture is given apart from it."""
    assert "look" in prompt and KEPT_AS not in prompt and '"files": [' not in prompt


@pytest.mark.anyio
async def test_claude_code_is_given_a_picture_as_an_image_block_in_each_mode(tmp_path):
    messages = with_picture(tmp_path)
    block = {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                         "data": base64.b64encode(PNG).decode("ascii")}}
    named = [{"type": "text", "text": "shot.png:"}, block]  # (so that pictures are told apart)
    await ClaudeCliClient(launcher=FAKE_STEP, **plan(
        tmp_path, answer={"text": "ok", "tool_calls": []})).stream_step("m", messages, None, nothing)
    step = record(tmp_path)
    await ClaudeSessionClient(launcher=FAKE_SESSION, **plan(tmp_path, [{"say": "ok"}])).run_session(
        "m", messages, [], answered, nothing)
    session = record(tmp_path)
    for seen in (step, session):
        assert seen["argv"][-2:] == ["--input-format", "stream-json"]
        given = json.loads(seen["stdin"])
        assert given["type"] == "user" and given["message"]["content"][1:] == named
        kept_out(given["message"]["content"][0]["text"])
    await ClaudeNativeClient(launcher=FAKE_CLAUDE, **plan(tmp_path, [{"say": "ok"}])).run_native(
        "m", messages, [], str(tmp_path), answered, nothing, nothing)
    native = record(tmp_path)
    assert native["images"] == named
    kept_out(native["stdin"])


@pytest.mark.anyio
async def test_codex_is_given_a_copy_of_a_picture_by_its_path_in_each_mode(tmp_path):
    messages = with_picture(tmp_path)
    await CodexCliClient(launcher=FAKE_STEP, **plan(
        tmp_path, answer={"text": "ok", "tool_calls": []})).stream_step("m", messages, None, nothing)
    step = record(tmp_path)
    # Right after `exec`: --image takes several values, so a flag must follow it.
    assert step["argv"][:2] == ["exec", "--image"] and step["argv"][3].startswith("--")
    assert Path(step["argv"][2]).name == "1.png" and step["images"] == [PNG.hex()]
    assert list(step["files"]) == ["answer.schema.json"]  # (the copy is in a folder of its own)
    assert not Path(step["argv"][2]).parent.exists()  # and gone with the run's folder
    kept_out(step["stdin"])
    await CodexNativeClient(launcher=FAKE_CODEX, **plan(tmp_path, [{"say": "ok"}])).run_native(
        "m", messages, [], str(tmp_path), answered, nothing, nothing)
    native = record(tmp_path)
    assert [part["type"] for part in native["input"]] == ["text", "localImage"]
    assert Path(native["input"][1]["path"]).name == "1.png" and native["images"] == [PNG.hex()]
    kept_out(native["stdin"])


@pytest.mark.anyio
async def test_a_cli_with_no_way_to_take_a_picture_is_given_none_nor_its_path(tmp_path):
    await QoderSessionClient(launcher=FAKE_SESSION, **plan(tmp_path, [{"say": "ok"}])).run_session(
        "m", with_picture(tmp_path), [], answered, nothing)
    seen = record(tmp_path)
    assert "--input-format" not in seen["argv"]
    kept_out(seen["stdin"])


def test_the_api_clients_send_images_as_parts_and_nothing_else_changes(tmp_path):
    image = tmp_path / "a"
    image.write_bytes(PNG)
    plain = {"role": "user", "content": "hi"}
    files = {"role": "user", "content": "look", "files": [
        {"kind": "image", "mime": "image/png", "path": str(image), "frames": []},
        {"kind": "image", "mime": "image/png", "path": str(tmp_path / "gone"), "frames": []}]}
    sent = with_files([plain, files])
    assert sent[0] is plain and "files" not in sent[1]
    assert sent[1]["content"][0] == {"type": "text", "text": "look"}
    assert sent[1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,iVBOR")
    assert len(sent[1]["content"]) == 2  # one gone from the store is left out
    _system, blocks = to_anthropic([files])
    assert blocks[0]["content"][1]["source"]["media_type"] == "image/png"


@pytest.mark.parametrize(("status", "said", "took"), [
    (200, '{"choices": [{"message": {"content": "ok"}}]}', True),
    (500, "image input is not supported - you may need to provide the mmproj", False),
    (500, "out of memory", None),  # not a word of images: not known
])
@pytest.mark.anyio
async def test_the_check_sends_one_pixel_and_reads_a_refusal(status, said, took):
    seen = []

    def served(request):
        seen.append(json.loads(request.content))
        return httpx2.Response(status, text=said)

    client = OpenAICompatClient("http://model/v1", transport=httpx2.MockTransport(served))
    assert await client.takes_image("eye") is took
    assert seen[0]["messages"][0]["content"][1]["image_url"]["url"].startswith(
        "data:image/png;base64,")


@contextlib.contextmanager
def chat_on(settings_env, project_dir, clients, **provider):
    """A chat whose Lead runs on this provider, its client one of `clients`: (client, chat)."""
    from app.config import load_settings
    from app.main import create_app
    from tests.fakes import ScriptedModel
    from tests.keyed import TestClient

    app = create_app(load_settings(settings_env), model=ScriptedModel([]), clients=clients)
    with TestClient(app, base_url="http://127.0.0.1:8790") as client:
        client.headers["Origin"] = "http://127.0.0.1:8790"
        made = client.post("/api/providers", json=provider).json()
        pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
        cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
        client.patch(f"/api/conversations/{cid}", json={
            "provider_id": made["id"], "model_id": provider["models"][0]["name"]})
        yield client, cid


SONNET = {"name": "Claude", "kind": "claude_cli", "models": [{"name": "sonnet", "inputs": ["image"]}]}


def test_a_picture_whose_cli_never_started_is_not_said_shown(
        settings_env, project_dir, wait_run, tmp_path):
    gone = ClaudeSessionClient(launcher=[str(tmp_path / "no-claude.exe")], timeout=10)
    with chat_on(settings_env, project_dir, {"Claude": gone}, mode="session", **SONNET) as (
            client, cid):
        shot = attach(client, cid, "shot.png", PNG).json()
        snap = wait_run(client, cid, send(client, cid, "look", shot["id"]))
    assert cards(snap) == {shot["id"]: ["not shown to sonnet on Claude: its model was not reached"]}


def test_claude_code_is_sent_no_picture_whose_base64_would_pass_anthropic_s_limit(
        settings_env, project_dir, wait_run, monkeypatch):
    """It has no retry without its pictures in a session or natively: one that would be
    refused for its size is not sent at all."""
    from app import attachments
    from tests.fakes import ScriptedModel

    monkeypatch.setattr(attachments, "MAX_SENT", 40)  # PNG is 32 B: under it, its base64 not
    cli = ScriptedModel([text("seen")])
    with chat_on(settings_env, project_dir, {"Claude": cli}, mode="step", **SONNET) as (
            client, cid):
        shot = attach(client, cid, "shot.png", PNG).json()
        snap = wait_run(client, cid, send(client, cid, "look", shot["id"]))
    said = told_of_files(cli.calls[0])
    assert "files" not in said and "It is over 30 B, too big to be shown" in said["content"]
    assert cards(snap) == {shot["id"]: ["not shown to sonnet on Claude: over 30 B"]}


def test_codex_step_is_given_no_picture_where_its_temporary_folder_has_a_comma(
        settings_env, project_dir, wait_run, tmp_path, monkeypatch):
    from tests.fakes import ScriptedModel

    comma = tmp_path / "a,b"
    comma.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(comma))
    cli = ScriptedModel([text("seen")])
    with chat_on(settings_env, project_dir, {"Codex": cli}, name="Codex", kind="codex_cli",
                 mode="step", models=[{"name": "gpt", "inputs": ["image"]}]) as (client, cid):
        shot = attach(client, cid, "shot.png", PNG).json()
        snap = wait_run(client, cid, send(client, cid, "look", shot["id"]))
    said = told_of_files(cli.calls[0])
    assert "files" not in said and "--image cannot take a path with a comma" in said["content"]
    assert cards(snap)[shot["id"]][0].startswith("not shown to gpt on Codex: Codex, whose --image")


def test_a_card_is_written_and_said_again_only_when_it_changed(
        make_client, project_dir, monkeypatch):
    client, _model, _pid, cid = began(make_client, project_dir, [])
    shot = attach(client, cid, "shot.png", PNG).json()
    runner, said = client.app.state.runner, []
    monkeypatch.setattr(runner.bus, "emit", lambda _cid, _run, kind, payload: said.append(
        payload["shown_to"]))
    ctx = SimpleNamespace(cid=cid, run_id=None, agent_id="a1")
    for words in ("shown to x", "shown to x", "not shown to x: refused"):
        runner._shown(ctx, {shot["id"]: words})
    assert said == [{"a1": "shown to x"}, {"a1": "not shown to x: refused"}]
