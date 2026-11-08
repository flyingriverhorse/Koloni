"""Slice 39 beside its acceptance set (`test_view_scenarios`): the migration, what one line
of the view list says when a file was both written and shown, and what the review of the
slice found: a picture shown from a working copy, the list read without hashing anew, names
Windows would not open as asked, an answering turn, and the frame's own headers."""

import os
import sqlite3

import pytest
from alembic import command
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

from app import views
from app.main import NoFrame
from app.workspace import sha256_text
from tests.conftest import Gate
from tests.keyed import TestClient
from tests.test_agent_writes import wait_status, write
from tests.test_chat_flow import start, start_in_mode, text
from tests.test_claim_scenarios import setup
from tests.test_migration_0002 import _config
from tests.test_parallel import until
from tests.test_spawn import call, spawn, step

OLD = bytes.fromhex(  # a 1x1 picture: the one the project had
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)
NEW = OLD + b"made in the copy"  # (a picture viewer reads no further than its end)
MADE = f"python -c \"open('chart.png','wb').write(bytes.fromhex('{NEW.hex()}'))\""


def test_the_shown_files_table_is_added_and_taken_away_again(tmp_path):
    db = tmp_path / "old.db"
    cfg = _config(db)
    command.upgrade(cfg, "0042")
    command.upgrade(cfg, "head")
    with sqlite3.connect(db) as conn:
        names = {row[1] for row in conn.execute("PRAGMA table_info(shown_files)")}
        assert names == {"id", "conversation_id", "agent_id", "path", "note", "copy_owner",
                         "created_at"}
        assert conn.execute("SELECT count(*) FROM shown_files").fetchone() == (0,)
    command.downgrade(cfg, "0042")
    with sqlite3.connect(db) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert "shown_files" not in tables


def test_a_change_whose_file_is_not_there_now_is_said_to_be_gone(make_client, wait_run, project_dir):
    """B-55: the Workspace tree said "added, Applied" of files deleted by hand. The server
    says it from the disk, not from a listing (which leaves secret names out)."""
    client, _model = make_client([
        write("first.txt", "1", "w1"), write(".env.example", "KEY=", "w2"), text("ok")])
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    wait_run(client, cid, run_id)
    (project_dir / "first.txt").unlink()
    snap = client.get(f"/api/conversations/{cid}").json()
    assert {(c["path"], c["status"], c["gone"]) for c in snap["file_changes"]} == {
        ("first.txt", "applied", True), (".env.example", "applied", False)}


def test_a_page_written_and_then_shown_is_one_line_with_the_note(make_client, wait_run, project_dir):
    client, _model = make_client([
        write("page.html", "<p>one</p>"),
        step(call("show", {"path": "page.html", "note": "  the  page\n"}, "v1")),
        text("ok")])
    cid, run_id = start_in_mode(client, project_dir, "auto_edit")
    wait_run(client, cid, run_id)
    (line,) = client.get(f"/api/conversations/{cid}/views").json()
    assert (line["status"], line["note"], line["kind"]) == ("applied", "the page", "html")
    assert client.get(line["url"]).text == "<p>one</p>"


def test_a_view_file_carries_only_its_own_policy_and_other_answers_keep_theirs(
    make_client, wait_run, project_dir
):
    (project_dir / "a.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    client, _model = make_client([step(call("show", {"path": "a.svg"}, "v1")), text("ok")])
    cid, run_id = start_in_mode(client, project_dir, "ask")
    wait_run(client, cid, run_id)
    (line,) = client.get(f"/api/conversations/{cid}/views").json()
    page = client.get(line["url"])
    assert page.headers["content-type"] == "image/svg+xml"
    assert len(page.headers.get_list("content-security-policy")) == 1
    assert "frame-ancestors 'none'" not in page.headers["content-security-policy"]
    # where it was framed from is not told to wherever it goes
    assert page.headers["referrer-policy"] == "no-referrer"
    missing = client.get(line["url"].rsplit("/", 1)[0] + "/nothing.css")
    assert missing.status_code == 404
    assert missing.headers["content-security-policy"] == "frame-ancestors 'none'"


def test_an_answer_with_a_policy_that_says_nothing_of_frames_is_still_framed_by_nobody():
    app = FastAPI()

    @app.get("/own")
    def own():
        return PlainTextResponse("x", headers={"Content-Security-Policy": "default-src 'none'"})

    app.add_middleware(NoFrame)
    said = TestClient(app).get("/own").headers
    assert "frame-ancestors 'none'" in " ".join(said.get_list("content-security-policy"))
    assert said["x-frame-options"] == "DENY"


# --- a picture made and shown in a working copy --------------------------------------------------


def copy_that_shows(make_client, project_dir, gate, note=None):
    """A lead whose Coder, in a copy of its own, makes chart.png with a command and shows it;
    the project has an older chart.png. The Coder's last step waits for `gate`."""
    (project_dir / "chart.png").write_bytes(OLD)
    return setup(make_client, project_dir, {
        "Lead": [spawn("Coder"), text("done")],
        "Coder": [step(call("run_command", {"command": MADE}, "c")),
                  step(call("show", {"path": "chart.png", **({"note": note} if note else {})},
                            "v")),
                  gate.step(text("Coder done"))],
    })


def test_a_picture_a_sub_agent_makes_and_shows_in_its_copy_is_served_from_there_then_from_the_project(
    make_client, wait_run, project_dir
):
    gate = Gate()
    client, _model, cid, run_id = copy_that_shows(make_client, project_dir, gate, "the new chart")
    gate.wait_partial()                                          # shown; the copy is still there
    (line,) = client.get(f"/api/conversations/{cid}/views").json()
    assert line["note"] == "the new chart"
    assert client.get(line["url"]).content == NEW                 # the copy's, not the project's
    assert (project_dir / "chart.png").read_bytes() == OLD
    gate.release()
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed"
    assert [m["status"] for m in snap["merges"]] == ["applied"]
    # taken in, the copy is gone: what is served is the project's, which is now the same
    assert (project_dir / "chart.png").read_bytes() == NEW
    (line,) = client.get(f"/api/conversations/{cid}/views").json()
    assert client.get(line["url"]).content == NEW


def test_a_picture_shown_from_a_copy_that_was_stopped_is_the_projects_again(
    make_client, wait_run, project_dir
):
    gate = Gate()
    client, _model, cid, run_id = copy_that_shows(make_client, project_dir, gate)
    gate.wait_partial()
    (line,) = client.get(f"/api/conversations/{cid}/views").json()
    assert client.get(line["url"]).content == NEW
    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 202
    gate.release()
    until(client, cid, lambda s: s["runs"][0]["status"] not in ("running", "waiting_approval"))
    assert (project_dir / "chart.png").read_bytes() == OLD
    assert client.get(line["url"]).content == OLD                 # the copy is gone, unmerged


# --- the list, read every 2 s ----------------------------------------------------------------


def test_the_list_hashes_a_file_once_until_it_changes_and_one_file_is_served_without_the_rest(
    make_client, wait_run, project_dir, monkeypatch
):
    for name in ("a.png", "b.png"):
        (project_dir / name).write_bytes(OLD)
    client, _model = make_client([
        step(call("show", {"path": "a.png"}, "v1"), call("show", {"path": "b.png"}, "v2")),
        text("ok")])
    cid, run_id = start(client, project_dir)
    wait_run(client, cid, run_id)
    read = []
    real = views.read_file
    monkeypatch.setattr(views, "read_file", lambda ws, rel: read.append(rel) or real(ws, rel))
    first = client.get(f"/api/conversations/{cid}/views").json()
    read.clear()
    assert client.get(f"/api/conversations/{cid}/views").json() == first   # nothing read again
    assert read == []
    (project_dir / "a.png").write_bytes(NEW)
    os.utime(project_dir / "a.png", ns=(1, 1))     # (a stamp of its own, whatever the clock)
    again = {v["path"]: v["sha"] for v in client.get(f"/api/conversations/{cid}/views").json()}
    assert read == ["a.png"]
    assert again["a.png"] != {v["path"]: v["sha"] for v in first}["a.png"]
    read.clear()
    b = next(line for line in first if line["path"] == "b.png")
    assert client.get(b["url"]).content == OLD
    assert read == ["b.png"]                                      # the one asked for, alone


# --- names Windows would not open as asked ---------------------------------------------------


@pytest.mark.parametrize("asked", ["a%00.css", "CON", "nul.css", "com1.txt", "LPT9", "style.css.",
                                   "style.css%20", "x%01y.css"])
def test_a_name_windows_would_open_otherwise_is_refused_not_failed(
    make_client, wait_run, project_dir, asked
):
    (project_dir / "page.html").write_text("<p>hi</p>")
    (project_dir / "style.css").write_text("p{}")
    client, _model = make_client([step(call("show", {"path": "page.html"}, "v")), text("ok")])
    cid, run_id = start(client, project_dir)
    wait_run(client, cid, run_id)
    (line,) = client.get(f"/api/conversations/{cid}/views").json()
    answer = client.get(line["url"].rsplit("/", 1)[0] + "/" + asked)
    assert answer.status_code == 400, (asked, answer.status_code)


@pytest.mark.skipif(os.name != "nt", reason="names are told apart by case elsewhere")
def test_a_waiting_change_is_what_a_page_gets_beside_it_by_any_case_of_its_name(
    make_client, project_dir
):
    client, _model = make_client([
        step(call("write_file", {"path": "page.html", "content": "<link href=Style.CSS>"}, "w1")),
        step(call("write_file", {"path": "style.css", "content": "p{color:red}"}, "w2")),
        text("ok")])
    cid, _run_id = start(client, project_dir)
    (page,) = wait_status(client, cid, "waiting_approval")["file_changes"]
    client.post(f"/api/file-changes/{page['id']}/approve")
    until(client, cid, lambda s: [c["status"] for c in s["file_changes"]] == ["applied", "proposed"])
    line = next(v for v in client.get(f"/api/conversations/{cid}/views").json()
                if v["path"] == "page.html")
    beside = client.get(line["url"].rsplit("/", 1)[0] + "/Style.CSS")
    assert beside.status_code == 200 and beside.text == "p{color:red}"


def test_a_page_asked_for_under_the_address_of_its_kept_text_gets_that_and_not_a_newer_change(
    make_client, project_dir
):
    """K-e2e-titrek: the frame loaded the list's address of the kept page after a second
    change had come, and got the second's text; turned down, the list gave the same address
    again and the frame kept showing what nobody kept."""
    client, _model = make_client([
        write("page.html", "<p>one</p>", "w1"), write("page.html", "<p>two</p>", "w2"),
        text("ok")])
    cid, _run_id = start(client, project_dir)
    (first,) = wait_status(client, cid, "waiting_approval")["file_changes"]
    client.post(f"/api/file-changes/{first['id']}/approve")
    until(client, cid, lambda s: [c["status"] for c in s["file_changes"]] == ["applied", "proposed"])
    (line,) = client.get(f"/api/conversations/{cid}/views").json()
    assert (line["status"], line["sha"]) == ("proposed", sha256_text("<p>two</p>"))
    assert client.get(f"{line['url']}?v={sha256_text('<p>one</p>')}-applied").text == "<p>one</p>"
    assert client.get(f"{line['url']}?v={line['sha']}-proposed").text == "<p>two</p>"
    assert client.get(line["url"]).text == "<p>two</p>"


# --- an answering turn ------------------------------------------------------------------------


def test_an_agent_answering_a_message_cannot_show_either(make_client, wait_run, project_dir):
    (project_dir / "chart.png").write_bytes(OLD)
    client, _model = make_client({
        "Lead": [spawn("Reviewer"), step(call("show", {"path": "chart.png"}, "v")),
                 text("It is the chart."), text("done")],
        "Reviewer": [step(call("message_agent", {"to": "Lead", "message": "what is it?"}, "m")),
                     text("ok")],
    })
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id)
    (shown,) = [t for t in snap["tool_calls"] if t["name"] == "show"]
    assert shown["status"] == "failed" and "not available while answering" in shown["result"]
    assert client.get(f"/api/conversations/{cid}/views").json() == []


def test_a_pdf_is_shown_and_served_for_the_browsers_viewer_by_both_ways(
    make_client, wait_run, project_dir
):
    """K-belge-ciktilari: a pdf is drawn by the browser's own viewer, which no sandbox lets in -
    so it goes without one, and is kept from the app by its exact type, nosniff and its frame."""
    pdf = b"%PDF-1.4\n%%EOF\n"
    (project_dir / "report.pdf").write_bytes(pdf)
    client, _model = make_client([step(call("show", {"path": "report.pdf"}, "v1")), text("ok")])
    cid, run_id = start_in_mode(client, project_dir, "ask")
    wait_run(client, cid, run_id)
    (line,) = client.get(f"/api/conversations/{cid}/views").json()
    assert line["kind"] == "pdf"
    pid = client.get(f"/api/conversations/{cid}").json()["conversation"]["project_id"]
    for answer in (client.get(line["url"]), client.get(f"/api/projects/{pid}/raw/report.pdf")):
        assert answer.content == pdf
        assert answer.headers["content-type"] == "application/pdf"
        assert answer.headers["content-security-policy"] == (
            "script-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'")
        assert answer.headers["x-content-type-options"] == "nosniff"
        assert answer.headers["x-frame-options"] == "SAMEORIGIN"
        assert answer.headers["cross-origin-resource-policy"] == "same-origin"
    # (A page is still sandboxed, by the same ways.)
    assert views.headers_of("text/html; charset=utf-8") is views.HEADERS


def test_a_document_is_shown_and_served_as_its_own_type_under_a_views_policy(
    make_client, wait_run, project_dir
):
    """K-belge-ciktilari: a docx, an xlsx or a pptx is read by the app and drawn in a frame of no
    origin (`frontend/public/office/`): served as what it is, sandboxed as any view."""
    (project_dir / "plan.docx").write_bytes(b"PK\x03\x04 a docx")
    client, _model = make_client([step(call("show", {"path": "plan.docx"}, "v1")), text("ok")])
    cid, run_id = start_in_mode(client, project_dir, "ask")
    wait_run(client, cid, run_id)
    (line,) = client.get(f"/api/conversations/{cid}/views").json()
    assert line["kind"] == "docx"
    answer = client.get(line["url"])
    assert answer.content == b"PK\x03\x04 a docx"
    assert answer.headers["content-type"] == views.TYPES[".docx"]
    assert answer.headers["content-security-policy"] == views.POLICY
    assert answer.headers["cross-origin-resource-policy"] == "same-origin"
    assert [views.kind_of(f"a.{end}") for end in ("XLSX", "pptx")] == ["xlsx", "pptx"]
    # The app reads it itself, with its key: on these keyless doors, none is served without.
    pid = client.get(f"/api/conversations/{cid}").json()["conversation"]["project_id"]
    for url in (line["url"], f"/api/projects/{pid}/raw/plan.docx"):
        assert client.get(url, headers={"X-KOLONI-Key": ""}).status_code == 401
        assert client.get(url).status_code == 200
