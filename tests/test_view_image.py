"""28e: view_image - an image of the project, shown to a model that takes images as a
screenshot is (slice 51), its size said to one that does not; never a secret, a file outside
the project, or one that is not an image by its bytes."""

import base64
import json
import struct
from pathlib import Path

from app.agent import COLLABORATION_TOOLS
from app.attachments import image_size
from app.model_client import ModelUnavailable
from app.tools import READ_TOOLS
from tests.test_agy_agent import agy_app  # noqa: F401  (a fixture)
from tests.test_agy_agent import start as agy_start
from tests.test_attachment_agents import seeing
from tests.test_chat_flow import text
from tests.test_copilot_agent import copilot_native  # noqa: F401  (a fixture)
from tests.test_copilot_agent import start as copilot_start
from tests.test_native_agent import native_app  # noqa: F401  (a fixture)
from tests.test_native_agent import start as native_start
from tests.test_session_agent import session_app, start  # noqa: F401  (a fixture)
from tests.test_spawn import call, step
from tests.test_usage_scenarios import began

PNG = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 2, 3) + bytes(5)


def _calls(client, cid):
    return {t["provider_call_id"]: t for t in
            client.get(f"/api/conversations/{cid}").json()["tool_calls"]}


def _turn(client, wait_run, cid):
    client.patch(f"/api/conversations/{cid}", json={"permission_mode": "ask"})
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "look"}).json()[
        "run"]["id"]
    run = wait_run(client, cid, run_id, timeout=15)
    # No card at any level: an image is looked at as a file is read, unasked.
    assert next(r for r in run["runs"] if r["id"] == run_id)["status"] == "completed"


def test_an_image_reaches_an_image_model_and_the_user_and_what_is_not_one_is_refused(
        make_client, wait_run, project_dir, tmp_path):
    (project_dir / "art").mkdir()
    (project_dir / "art" / "logo.png").write_bytes(PNG)
    (project_dir / ".env").write_bytes(PNG)
    (project_dir / "fake.png").write_text("not a picture\n", encoding="utf-8")
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "out.png").write_bytes(PNG)
    client, model, _pid, cid = began(make_client, project_dir, [
        step(call("view_image", {"path": "art/logo.png"}, "v1")),
        step(call("view_image", {"path": ".env"}, "v2"),
             call("view_image", {"path": "../other/out.png"}, "v3"),
             call("view_image", {"path": "fake.png"}, "v4"),
             call("view_image", {"path": "a\u0000.png"}, "v5")),
        text("seen")])
    seeing(client, cid)
    _turn(client, wait_run, cid)
    made = _calls(client, cid)
    shown = made["v1"]
    assert shown["status"] == "succeeded", shown["result"]
    copy = f".koloni/tmp/images/{shown['agent_id'][:8]}-{shown['id'][:8]}/logo.png"
    assert shown["result"] == (f"art/logo.png, 2×3, {len(PNG)} B: it is shown to you with your "
                               f"next step (the user sees it under the step: {copy})")
    assert (project_dir / copy).read_bytes() == PNG
    # The model: at its next step, the copy as a picture after the call's result.
    pictures = [m for m in model.calls[1] if m.get("files")]
    assert [p["files"][0]["path"] for p in pictures] == [str(project_dir / copy)]
    assert pictures[0]["content"] == "The image:" and pictures[0]["files"][0]["mime"] == "image/png"
    # The user: under the call's own id, served by the view beside the chat.
    (line,) = client.get(f"/api/conversations/{cid}/views").json()
    assert (line["id"], line["path"]) == (shown["id"], copy)
    assert client.get(f"/api/conversations/{cid}/views/{shown['id']}/{copy.split('/')[-1]}"
                      ).content == PNG
    assert [made[one]["status"] for one in ("v2", "v3", "v4", "v5")] == ["failed"] * 4
    assert "is a secret file" in made["v2"]["result"]
    assert made["v3"]["result"] == "error: '../other/out.png' is outside the project folder"
    assert made["v4"]["result"] == ("error: 'fake.png' is not an image by its bytes: PNG, JPEG, "
                                    "GIF or WebP")
    assert made["v5"]["result"] == "error: a path can't hold a NUL character"


def test_a_model_that_takes_no_images_is_told_its_size(make_client, wait_run, project_dir):
    (project_dir / "logo.png").write_bytes(PNG)
    client, model, _pid, cid = began(make_client, project_dir, [
        step(call("view_image", {"path": "logo.png"}, "v1")), text("ok")])
    seeing(client, cid, inputs=())
    _turn(client, wait_run, cid)
    shown = _calls(client, cid)["v1"]
    copy = f".koloni/tmp/images/{shown['agent_id'][:8]}-{shown['id'][:8]}/logo.png"
    assert shown["result"] == (f"eye on Seer does not take images; its size is 2×3, {len(PNG)} B "
                               f"(the user sees it under the step: {copy})")
    assert not any(m.get("files") for m in model.calls[1])


def test_an_image_the_model_refuses_is_sent_again_as_words(make_client, wait_run, project_dir):
    (project_dir / "logo.png").write_bytes(PNG)
    client, model, _pid, cid = began(make_client, project_dir, [
        step(call("view_image", {"path": "logo.png"}, "v1")),
        ModelUnavailable("model server returned 500: image input is not supported"),
        text("I could not look at it")])
    seeing(client, cid)
    _turn(client, wait_run, cid)
    first, again = model.calls[1], model.calls[2]
    assert any(m.get("files") for m in first) and not any(m.get("files") for m in again)
    assert any("the model refused it" in (m.get("content") or "") for m in again)


def test_only_the_last_two_images_of_a_turn_go_as_pictures(make_client, wait_run, project_dir):
    for name in ("a", "b", "c"):
        (project_dir / f"{name}.png").write_bytes(PNG)
    client, model, _pid, cid = began(make_client, project_dir, [
        *(step(call("view_image", {"path": f"{name}.png"}, f"v{name}")) for name in "abc"),
        text("three")])
    seeing(client, cid)
    _turn(client, wait_run, cid)
    last = model.calls[3]
    assert len([m for m in last if m.get("files")]) == 2
    assert [m["content"] for m in last if "An earlier image" in (m.get("content") or "")] == [
        "(An earlier image, not shown again: view it again if you need to.)"]


def test_a_cli_with_its_own_tools_is_not_bridged_view_image():
    assert "view_image" not in READ_TOOLS and "view_image" not in COLLABORATION_TOOLS


def test_sizes_from_the_headers():
    assert image_size(PNG) == (2, 3)
    assert image_size(b"GIF89a" + struct.pack("<HH", 5, 7)) == (5, 7)
    jpeg = (b"\xff\xd8\xff\xe0" + struct.pack(">H", 4) + b"JF" + b"\xff\xc4\x00\x02"
            + b"\xff\xc0" + struct.pack(">HBHH", 11, 8, 30, 40) + bytes(5))
    assert image_size(jpeg) == (40, 30)
    riff = b"RIFF" + bytes(4) + b"WEBP"
    assert image_size(riff + b"VP8X" + bytes(8) + (99).to_bytes(3, "little")
                      + (49).to_bytes(3, "little")) == (100, 50)
    lossless = (9 | 19 << 14).to_bytes(4, "little")
    assert image_size(riff + b"VP8L" + bytes(4) + b"\x2f" + lossless) == (10, 20)
    assert image_size(riff + b"VP8 " + bytes(4) + bytes(6) + struct.pack("<HH", 64, 32)) == (64, 32)
    assert image_size(b"\xff\xd8\xff\xd9") is None


def test_a_cli_session_is_handed_the_image_in_the_tool_result(
        session_app, wait_run, project_dir):  # noqa: F811
    # B-344: a session keeps its own loop, so a "next step" of KOLONİ's never comes.
    (project_dir / "logo.png").write_bytes(PNG)
    client, provider, _ = session_app([{"call": "view_image", "args": {"path": "logo.png"}},
                                       {"say": "Two by three."}])
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    (shown,) = snap["tool_calls"]
    assert ": it is shown to you with this result (the user sees it under the step: " in (
        shown["result"])
    text_block, image = session_app.record()["results"][0]["content"]
    assert text_block["text"] == shown["result"]
    assert image == {"type": "image", "mimeType": "image/png",
                     "data": base64.b64encode(PNG).decode()}


def test_one_over_claude_codes_cap_goes_to_a_session_as_words_only(
        session_app, wait_run, project_dir):  # noqa: F811
    (project_dir / "big.png").write_bytes(PNG + bytes(4 * 2**20))
    client, provider, _ = session_app([{"call": "view_image", "args": {"path": "big.png"}}])
    cid, run_id = start(client, project_dir, provider)
    (shown,) = wait_run(client, cid, run_id)["tool_calls"]
    assert ": over 3.8 MB, too big to be shown to " in shown["result"]
    assert len(session_app.record()["results"][0]["content"]) == 1


def test_the_copy_keeps_the_images_own_name_with_its_types_ending(
        make_client, wait_run, project_dir):
    # B-346: the step and the Workspace tab say the image's name, not a copy's.
    (project_dir / "rea shapes (1).jpeg").write_bytes(PNG)
    client, _model, _pid, cid = began(make_client, project_dir, [
        step(call("view_image", {"path": "rea shapes (1).jpeg"}, "v1")), text("ok")])
    seeing(client, cid)
    _turn(client, wait_run, cid)
    shown = _calls(client, cid)["v1"]
    copy = f".koloni/tmp/images/{shown['agent_id'][:8]}-{shown['id'][:8]}/rea shapes (1).png"
    assert shown["result"].endswith(f"(the user sees it under the step: {copy})")
    assert client.get(f"/api/conversations/{cid}/views/{shown['id']}/rea shapes (1).png"
                      ).content == PNG


def test_one_the_view_would_not_serve_says_it_is_not_under_the_step(
        make_client, wait_run, project_dir):
    # R128: over 5 MB no copy is made, and the result says so.
    (project_dir / "big.png").write_bytes(PNG + bytes(6 * 2**20))
    client, _model, _pid, cid = began(make_client, project_dir, [
        step(call("view_image", {"path": "big.png"}, "v1")), text("ok")])
    seeing(client, cid)
    _turn(client, wait_run, cid)
    shown = _calls(client, cid)["v1"]
    assert shown["result"].endswith(
        "too big to be shown to eye on Seer as it is (too big to show under the step: over 5 MB)")
    assert not (project_dir / ".koloni" / "tmp" / "images").exists()


def test_codexs_own_look_at_an_image_is_a_step_with_the_image_under_it(
        native_app, wait_run, project_dir, tmp_path):  # noqa: F811
    # B-347: Codex looks with its imageView (R128), never KOLONİ's view_image: it is on record
    # as its own tool, and the user sees what it saw - but no secret, nor a file outside.
    (project_dir / "logo.png").write_bytes(PNG)
    (project_dir / ".env").mkdir()
    (project_dir / ".env" / "key.png").write_bytes(PNG)
    (tmp_path / "out.png").write_bytes(PNG)
    client, provider, _ = native_app([
        {"image": str(project_dir / "logo.png")}, {"image": str(project_dir / ".env" / "key.png")},
        {"image": str(tmp_path / "out.png")}, {"say": "A picture."}])
    cid, run_id = native_start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    looked, secret, own_secret, outside, own_outside = snap["tool_calls"]
    assert (looked["name"], looked["status"], looked["origin"]) == (
        "codex__imageView", "succeeded", "cli")
    copy = f".koloni/tmp/images/{looked['agent_id'][:8]}-{looked['id'][:8]}/logo.png"
    assert looked["result"] == f"(the user sees it under the step: {copy})"
    assert (project_dir / copy).read_bytes() == PNG
    assert [line["path"] for line in client.get(f"/api/conversations/{cid}/views").json()] == [copy]
    # what KOLONİ could not stop: a red note, nothing copied
    assert [one["name"] for one in (secret, outside)] == ["codex__imageView"] * 2
    assert [(one["name"], one["status"]) for one in (own_secret, own_outside)] == [
        ("image_look", "failed")] * 2
    assert "a secret file (keys, passwords): KOLONİ cannot stop" in own_secret["result"]
    assert "outside the project folder: KOLONİ cannot stop" in own_outside["result"]


def test_copilots_own_view_of_an_image_is_shown_under_its_step(
        copilot_native, wait_run, project_dir):  # noqa: F811
    (project_dir / "logo.png").write_bytes(PNG)
    client, provider = copilot_native([{"read": "logo.png", "result": "Viewed image"},
                                       {"read": "hello.py"}, {"say": "ok"}])
    cid, run_id = copilot_start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    image, text_file = [t for t in snap["tool_calls"] if t["name"] == "copilot__view"]
    copy = f".koloni/tmp/images/{image['agent_id'][:8]}-{image['id'][:8]}/logo.png"
    assert image["result"].endswith(f"Viewed image (the user sees it under the step: {copy})")
    assert "under the step" not in (text_file["result"] or "")


def test_agys_own_read_of_an_image_reading_only_is_shown_and_says_nothing_of_taking_images(
        agy_app, wait_run, project_dir):  # noqa: F811
    # B-345: agy reading only is handed none of KOLONİ's tools; its own reader showed its model.
    (project_dir / "logo.png").write_bytes(PNG)
    client, provider, _ = agy_app([
        {"tool": "view_file", "parameters": {"AbsolutePath": str(project_dir / "logo.png")},
         "output": "Showing binary file of type image/png"}, {"say": "A picture."}])
    cid, run_id = agy_start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    (read,) = snap["tool_calls"]
    copy = f".koloni/tmp/images/{read['agent_id'][:8]}-{read['id'][:8]}/logo.png"
    assert "take images" not in json.dumps(snap)
    assert read["result"] == ("Showing binary file of type image/png (the user sees it under "
                              f"the step: {copy})")


def test_a_secret_image_copilot_asked_to_view_is_not_copied_and_not_flagged(
        copilot_native, wait_run, project_dir):  # noqa: F811
    # Copilot asked KOLONİ first: the red note is only for what KOLONİ was never asked about.
    (project_dir / ".env").mkdir()
    (project_dir / ".env" / "key.png").write_bytes(PNG)
    client, provider = copilot_native([{"read": ".env/key.png", "result": "Viewed image"},
                                       {"say": "ok"}])
    cid, run_id = copilot_start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert [a["kind"] for a in copilot_native.record()["answers"]] == ["read"]
    assert [(t["name"], t["result"]) for t in snap["tool_calls"]] == [
        ("copilot__view", "Viewed image")]
    assert client.get(f"/api/conversations/{cid}/views").json() == []


def test_a_copy_that_cannot_be_written_leaves_the_call_done_and_says_so(
        make_client, wait_run, project_dir, monkeypatch):
    # Review of K-r127: an image whose copy cannot be written is still looked at, not failed.
    (project_dir / "logo.png").write_bytes(PNG)
    (project_dir / ("a" * 150 + ".png")).write_bytes(PNG)
    real = Path.write_bytes

    def refused(self, data):
        if self.name == "logo.png" and ".koloni" in self.parts:
            raise OSError(28, "No space left on device")
        return real(self, data)

    monkeypatch.setattr(Path, "write_bytes", refused)
    client, model, _pid, cid = began(make_client, project_dir, [
        step(call("view_image", {"path": "logo.png"}, "v1"),
             call("view_image", {"path": "a" * 150 + ".png"}, "v2")), text("ok")])
    seeing(client, cid)
    _turn(client, wait_run, cid)
    made = _calls(client, cid)
    assert made["v1"]["status"] == "succeeded"
    assert made["v1"]["result"] == (
        f"logo.png, 2×3, {len(PNG)} B: not shown to you (not shown under the step: its copy "
        "could not be written: No space left on device)")
    # a long name is cut short of a file system's limit (255)
    long = made["v2"]
    copy = f".koloni/tmp/images/{long['agent_id'][:8]}-{long['id'][:8]}/{'a' * 100}.png"
    assert long["result"].endswith(f"(the user sees it under the step: {copy})")
    assert [m["files"][0]["path"] for m in model.calls[1] if m.get("files")] == [
        str(project_dir / copy)]


def test_a_name_the_view_would_refuse_is_copied_as_image(make_client, wait_run, project_dir):
    # A device's name, or one that reads as a secret's once its signs are gone.
    for name in ("con.png", "nul .png", "api@key.png"):
        (project_dir / name).write_bytes(PNG)
    client, _model, _pid, cid = began(make_client, project_dir, [
        step(*(call("view_image", {"path": name}, f"v{n}")
               for n, name in enumerate(("con.png", "nul .png", "api@key.png")))), text("ok")])
    seeing(client, cid)
    _turn(client, wait_run, cid)
    for shown in (_calls(client, cid)[f"v{n}"] for n in range(3)):
        copy = f".koloni/tmp/images/{shown['agent_id'][:8]}-{shown['id'][:8]}/image.png"
        assert shown["result"].endswith(f"(the user sees it under the step: {copy})")
        assert client.get(f"/api/conversations/{cid}/views/{shown['id']}/image.png"
                          ).content == PNG
