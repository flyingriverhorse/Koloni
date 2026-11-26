"""Branches of `app/agent/__init__.py` that no other test met, pinned before its long
functions were split (C901 <= 12): each test here ran green on the code before the split
(the last one was written after `_apply`'s split, and run on the code before it too)."""

from app import copies
from app.agent.ctx import Ctx
from tests.test_browser import FAKE
from tests.test_chat_flow import start_in_mode, text
from tests.test_claim_scenarios import ORIGIN
from tests.test_spawn import call, step


def test_a_diagram_that_is_not_there_or_not_text_is_refused_with_why(
    monkeypatch, make_client, wait_run, project_dir
):
    monkeypatch.setenv("KOLONI_BROWSER_FAKE", FAKE)
    (project_dir / "bytes.drawio").write_bytes(b"\xff\xfe\x00not text")
    client, _model = make_client(
        [
            step(call("diagram_image", {"path": "bytes.drawio"}, "d1")),
            step(call("diagram_image", {"path": "gone.drawio"}, "d2")),
            text("done"),
        ]
    )
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    wait_run(client, cid, run_id)
    said = [t["result"] for t in client.get(f"/api/conversations/{cid}").json()["tool_calls"]]
    assert said == [
        "error: bytes.drawio is not UTF-8 text: not a draw.io file",
        "error: gone.drawio: no such file",
    ]
    assert not list(project_dir.glob("*.png"))


def test_apply_shows_again_a_file_that_is_not_as_its_card_showed_it_and_takes_nothing(
    make_client, project_dir, tmp_path
):
    client, _model = make_client([])
    client.headers["Origin"] = ORIGIN
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    (project_dir / "note.txt").write_text("one\n", encoding="utf-8")
    copy = copies.make(project_dir, tmp_path / "copies", "a1")
    (copy.root / "note.txt").write_text("two\n", encoding="utf-8")
    ctx = Ctx("run", cid, str(project_dir), "a1", "Coder", (), 1, name="Coder")
    # (The user's yes was to other bytes than the two files hold now.)
    files = {
        "note.txt": {"path": "note.txt", "state": "ready", "shown": ["not", "these"], "note": None}
    }
    assert client.app.state.runner._apply(ctx, copy, files, True) == set()
    assert (project_dir / "note.txt").read_text(encoding="utf-8") == "one\n"
    (one,) = files.values()
    assert one["state"] == "ready" and tuple(one["shown"]) == copy.sides("note.txt")
