"""Branches of `app/agent/__init__.py` that no other test met, pinned before its long
functions were split (C901 <= 12): each test here ran green on the code before the split."""

from tests.test_browser import FAKE
from tests.test_chat_flow import start_in_mode, text
from tests.test_spawn import call, step


def test_a_diagram_that_is_not_there_or_not_text_is_refused_with_why(
        monkeypatch, make_client, wait_run, project_dir):
    monkeypatch.setenv("KOLONI_BROWSER_FAKE", FAKE)
    (project_dir / "bytes.drawio").write_bytes(b"\xff\xfe\x00not text")
    client, _model = make_client([
        step(call("diagram_image", {"path": "bytes.drawio"}, "d1")),
        step(call("diagram_image", {"path": "gone.drawio"}, "d2")),
        text("done")])
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    wait_run(client, cid, run_id)
    said = [t["result"] for t in client.get(f"/api/conversations/{cid}").json()["tool_calls"]]
    assert said == ["error: bytes.drawio is not UTF-8 text: not a draw.io file",
                    "error: gone.drawio: no such file"]
    assert not list(project_dir.glob("*.png"))
