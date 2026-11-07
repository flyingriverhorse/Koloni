"""Slice 85b: files added to a chat message - what each is by its bytes, the limits held by
the server, the text taken out of a PDF and a Word file, a program kept by name alone, a
secret masked, and all of it gone with its conversation."""

import io
import time
import zipfile

import pytest

from app import attachments
from tests.test_usage_scenarios import began

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
EXE = b"MZ\x90\x00" + b"\x00" * 60


def pdf(*pages: str) -> bytes:
    """A PDF of these pages, each with its words in Helvetica ("" for a page with none)."""
    kids = " ".join(f"{4 + 2 * at} 0 R" for at in range(len(pages)))
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode(),
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    for at, words in enumerate(pages):
        stream = f"BT /F1 12 Tf 72 720 Td ({words}) Tj ET".encode() if words else b""
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources "
                       f"<< /Font << /F1 3 0 R >> >> /Contents {5 + 2 * at} 0 R >>".encode())
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1, xref)
    return bytes(out)


def docx(xml: str) -> bytes:
    made = io.BytesIO()
    with zipfile.ZipFile(made, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", xml)
    return made.getvalue()


def attach(client, cid, name, data, **more):
    return client.post(f"/api/conversations/{cid}/attachments", params={"name": name, **more},
                       content=data)


@pytest.fixture
def chat(make_client, project_dir):
    client, _model, _pid, cid = began(make_client, project_dir, [])
    return client, cid


@pytest.mark.parametrize(("data", "name", "kind"), [
    (PNG, "shot.png", "image"),
    (EXE, "cat.png", "executable"),  # a .png that is really a program
    (b"MZ is how it starts", "notes.txt", "executable"),
    (b"#!/bin/sh\necho hi\n", "run", "executable"),
    (b"echo hi\n", "go.bat", "executable"),  # named as one runs: kept as one
    (b"\xff\xd8\xff\xe0", "photo.bin", "image"),
    (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "a", "image"),
    (b"%PDF-1.4\n", "spec", "pdf"),
    (b"\x00\x00\x00\x18ftypmp42", "repro.mp4", "video"),
    (b"\x00\x00\x00\x18ftypheic", "IMG_1.HEIC", "file"),  # a photo no model or page shows
    (b"\x00\x00\x00\x18ftypavif", "a.avif", "file"),
    (b"\x1a\x45\xdf\xa3", "clip", "video"),
    (b"const x = 1\n", "cart.ts", "text"),
    (b"\x00\x01\x02", "blob.txt", "file"),
    (b"PK\x03\x04\x00 not a zip", "notes.docx", "file"),
])
def test_what_a_file_is_comes_from_its_bytes(data, name, kind):
    assert attachments.kind_of(data, name)[0] == kind


def test_a_program_is_kept_by_name_and_size_alone(chat, tmp_path):
    client, cid = chat
    told = attach(client, cid, "cat.png", EXE).json()
    assert (told["kind"], told["size"]) == ("executable", len(EXE))
    assert "only its name and size" in told["summary"]
    assert client.get(f"/api/attachments/{told['id']}/file").status_code == 404
    assert client.get(f"/api/attachments/{told['id']}/text").json() == {"text": None}
    kept = tmp_path / "runtime" / "attachments" / cid
    assert not any(kept.iterdir())


def test_the_server_holds_the_limits(chat, monkeypatch):
    client, cid = chat
    monkeypatch.setattr(attachments, "MAX_BYTES", 10)
    big = attach(client, cid, "a.txt", b"x" * 11)
    assert big.status_code == 413 and "MB at most" in big.json()["detail"]
    assert attach(client, cid, "empty.txt", b"").status_code == 422
    monkeypatch.setattr(attachments, "MAX_BYTES", 2**20)
    monkeypatch.setattr(attachments, "MAX_FILES", 2)
    for name in ("a.txt", "b.txt"):
        assert attach(client, cid, name, b"hi").status_code == 201
    third = attach(client, cid, "c.txt", b"hi")
    assert third.status_code == 422 and "2 files at most" in third.json()["detail"]


def test_a_name_is_a_name_never_a_path(chat, tmp_path):
    client, cid = chat
    told = attach(client, cid, "..\\..\\evil.txt", b"hi").json()
    assert told["name"] == "evil.txt"
    assert (tmp_path / "runtime" / "attachments" / cid / told["id"]).read_bytes() == b"hi"
    assert attach(client, cid, "../..", b"hi").status_code == 422
    # Two of one name: each has its own, as agents name them.
    assert [attach(client, cid, "a.png", PNG).json()["name"] for _ in range(3)] == [
        "a.png", "a (2).png", "a (3).png"]


def test_a_pdfs_text_is_taken_out_page_by_page(chat):
    client, cid = chat
    told = attach(client, cid, "spec.pdf", pdf("Hello PDF", "")).json()
    assert told["kind"] == "pdf" and told["summary"] == (
        "2 pages, text taken out; no text on page 2")
    text = client.get(f"/api/attachments/{told['id']}/text").json()["text"]
    assert "Hello PDF" in text and "no text on page 2" in text
    broken = attach(client, cid, "broken.pdf", b"%PDF-1.4\nnothing more").json()
    assert broken["kind"] == "pdf" and "could not be read" in broken["summary"]


def test_a_word_files_text_is_read_without_an_xml_parser_and_a_bomb_is_refused(
        chat, monkeypatch):
    client, cid = chat
    body = ('<w:document><w:body><w:p><w:r><w:t xml:space="preserve">Most buyers </w:t></w:r>'
            "<w:r><w:t>are on phones &amp; tablets</w:t></w:r></w:p><w:p/><w:p><w:r><w:t>"
            "Second</w:t></w:r></w:p></w:body></w:document>")
    told = attach(client, cid, "notes.docx", docx(body)).json()
    assert told["kind"] == "docx" and told["summary"] == "Word, 8 words, text taken out"
    assert client.get(f"/api/attachments/{told['id']}/text").json()["text"] == (
        "Most buyers are on phones & tablets\nSecond")
    entities = attach(client, cid, "lol.docx", docx('<!DOCTYPE x [<!ENTITY a "a">]><w:t>&a;</w:t>'))
    assert "declares its own entities" in entities.json()["summary"]
    monkeypatch.setattr(attachments, "MAX_DOCUMENT", 10)
    bomb = attach(client, cid, "bomb.docx", docx(body)).json()
    assert "bigger than KOLONİ reads" in bomb["summary"]


def test_a_hostile_word_file_is_read_in_well_under_a_second():
    # (A few KB unpack to these: before, 25 s holding the whole app.)
    for body in ("<w:t " * 400_000, "<w:p><w:t a='" + "x" * 2_000_000):
        began = time.perf_counter()
        attachments.read(docx(body), "evil.docx")
        assert time.perf_counter() - began < 1.0


def test_a_zip_of_too_many_entries_is_no_word_file():
    made = io.BytesIO()
    with zipfile.ZipFile(made, "w") as archive:
        for at in range(attachments.MAX_ENTRIES + 1):
            archive.writestr(f"{at}", "")
        archive.writestr("word/document.xml", "<w:t>hi</w:t>")
    assert attachments.kind_of(made.getvalue(), "a.docx")[0] == "file"


def many_streams(count: int) -> bytes:
    """A PDF of one page whose content is `count` streams: each decoded on its own."""
    refs = " ".join(f"{5 + at} 0 R" for at in range(count))
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << "
               f"/F1 3 0 R >> >> /Contents [{refs}] >>".encode()]
    stream = b"BT /F1 12 Tf 72 720 Td (word) Tj ET"
    objects += [b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"] * count
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1, xref)
    return bytes(out)


def test_a_hostile_pdf_is_read_apart_and_stops_saying_so():
    began = time.perf_counter()
    text, summary = attachments._pdf_text(many_streams(3000))
    assert time.perf_counter() - began < attachments.PDF_SECONDS and "word" in text
    limits = {**attachments.PDF_LIMITS, "chars": 10}
    text, summary = attachments._pdf_text(pdf(*["Hello PDF"] * 5), limits)
    assert summary == "5 pages, text taken out; the rest of this PDF was not read: too large"
    assert text.count("--- page") == 2
    limits = {**attachments.PDF_LIMITS, "seconds": -1}
    text, summary = attachments._pdf_text(pdf(*["Hello PDF"] * 3), limits)
    assert text.count("--- page") == 1 and summary.endswith("not read: too large")


def test_a_secret_is_never_given_and_one_of_a_secrets_shape_is_masked(chat):
    client, cid = chat
    env = attach(client, cid, ".env", b"API_KEY=abcdef1234567890\n").json()
    assert "secret file" in env["summary"]
    assert client.get(f"/api/attachments/{env['id']}/text").json() == {"text": None}
    said = attach(client, cid, "log.txt", b"Authorization: Bearer abcdefghijklmnop1234\n").json()
    text = client.get(f"/api/attachments/{said['id']}/text").json()["text"]
    assert "abcdefghijklmnop1234" not in text and "Bearer ***" in text


def test_only_an_image_a_video_or_a_pdf_is_shown_as_what_it_is(chat):
    client, cid = chat
    image = client.get(f"/api/attachments/{attach(client, cid, 'a.png', PNG).json()['id']}/file")
    assert image.headers["content-type"] == "image/png" and image.content == PNG
    assert image.headers["content-disposition"].startswith("inline")
    page = attach(client, cid, "x.html", b"<script>alert(1)</script>").json()
    served = client.get(f"/api/attachments/{page['id']}/file")
    assert served.headers["content-type"] == "application/octet-stream"
    assert served.headers["content-disposition"].startswith("attachment")
    assert served.headers["x-content-type-options"] == "nosniff"


def test_a_file_of_the_project_is_attached_by_its_path_but_never_a_secret(chat, project_dir):
    client, cid = chat
    (project_dir / ".env").write_text("KEY=1\n")
    url = f"/api/conversations/{cid}/attachments/project"
    told = client.post(url, params={"path": "hello.py"})
    assert told.status_code == 201, told.text
    assert (told.json()["name"], told.json()["kind"]) == ("hello.py", "text")
    assert client.post(url, params={"path": ".env"}).status_code == 404
    assert client.post(url, params={"path": "../outside.txt"}).status_code in (400, 404)


def test_a_frame_is_an_image_of_a_video_and_eight_at_most(chat, monkeypatch):
    client, cid = chat
    video = attach(client, cid, "repro.mp4", b"\x00\x00\x00\x18ftypmp42").json()
    note = attach(client, cid, "n.txt", b"hi").json()
    assert attach(client, cid, "f.png", PNG, frame_of=note["id"]).status_code == 422
    assert attach(client, cid, "f.txt", b"hi", frame_of=video["id"]).status_code == 422
    monkeypatch.setattr(attachments, "MAX_FRAMES", 1)
    assert attach(client, cid, "f1.png", PNG, frame_of=video["id"]).status_code == 201
    assert attach(client, cid, "f2.png", PNG, frame_of=video["id"]).status_code == 422


MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 100


def test_a_video_larger_than_a_file_goes_as_its_frames_alone(chat, tmp_path):
    """Slice 85c: the page sends its first bytes and its size; none of it is kept."""
    client, cid = chat
    large = attachments.MAX_BYTES + 1
    video = attach(client, cid, "long.mp4", MP4, size=large).json()
    assert (video["kind"], video["size"]) == ("video", large)
    assert video["summary"] == "frames only: larger than 25 MB, the video is not kept"
    assert not (tmp_path / "runtime" / "attachments" / cid / video["id"]).exists()
    assert client.get(f"/api/attachments/{video['id']}/file").status_code == 404
    frame = attach(client, cid, "long.mp4 frame 1.jpg", PNG, frame_of=video["id"])
    assert frame.status_code == 201 and frame.json()["frame_of"] == video["id"]
    # Only a video, by its first bytes alone, and only one larger than a file may be.
    text = attach(client, cid, "big.txt", b"hello", size=large)
    assert text.status_code == 422 and "only a larger video" in text.json()["detail"]
    whole = attach(client, cid, "long.mp4", MP4 + b"\x00" * attachments.MAX_HEAD, size=large)
    assert whole.status_code == 413 and "first 64 KB" in whole.json()["detail"]
    assert attach(client, cid, "small.mp4", MP4, size=attachments.MAX_BYTES).status_code == 422


def test_sent_with_a_message_it_stays_and_goes_with_its_conversation(chat, tmp_path, wait_run):
    client, cid = chat
    first = attach(client, cid, "a.txt", b"hi").json()
    gone = attach(client, cid, "b.txt", b"bye").json()
    assert client.delete(f"/api/attachments/{gone['id']}").status_code == 204
    assert not (tmp_path / "runtime" / "attachments" / cid / gone["id"]).exists()
    other = client.post("/api/conversations", json={}).json()["id"]
    elsewhere = attach(client, other, "c.txt", b"x").json()
    wrong = client.post(f"/api/conversations/{cid}/messages",
                        json={"content": "look", "attachments": [elsewhere["id"]]})
    assert wrong.status_code == 422
    sent = client.post(f"/api/conversations/{cid}/messages",
                       json={"content": "", "attachments": [first["id"]]})
    assert sent.status_code == 201, sent.text
    snap = client.get(f"/api/conversations/{cid}").json()
    assert [a["message_id"] for a in snap["attachments"]] == [sent.json()["message"]["id"]]
    assert client.delete(f"/api/attachments/{first['id']}").status_code == 409
    again = client.post(f"/api/conversations/{cid}/messages",
                        json={"content": "x", "attachments": [first["id"]]})
    assert again.status_code == 422  # sent once already
    wait_run(client, cid, sent.json()["run"]["id"])
    assert client.patch(f"/api/conversations/{cid}", json={"archived": True}).status_code == 200
    deleted = client.post("/api/conversations/delete", json={"ids": [cid]}).json()
    assert deleted["deleted"] == [cid], deleted
    assert not (tmp_path / "runtime" / "attachments" / cid).exists()
    assert (tmp_path / "runtime" / "attachments" / other).is_dir()  # another's stays


def test_a_text_with_crlf_lines_is_read_with_as_many_lines_as_it_has(tmp_path):
    """B-105: an 11-line CRLF file was read back as 22 lines on Windows."""
    data = "".join(f"line {n}\r\n" for n in range(1, 12)).encode()
    _kind, _mime, summary, text = attachments.read(data, "cart.py")
    attachments.keep(tmp_path, "c", "a", data, text)
    kept = attachments.text_of(tmp_path, "c", "a")
    assert summary == "11 lines" and kept is not None and len(kept.splitlines()) == 11
    assert attachments.page(kept).startswith("(lines 1-11 of 11)\nline 1\nline 2\n")


def test_a_kept_file_is_found_by_its_id_in_its_own_folder_alone(tmp_path):
    """K-belge-ciktilari review: `D:x` joined to a folder is drive D's, and `..` is the folder
    above - neither is an attachment's id."""
    kept = attachments.folder(tmp_path, "c")
    kept.mkdir(parents=True)
    (kept / "a1").write_bytes(b"hi")
    (tmp_path / "attachments" / "x").write_bytes(b"another chat's")
    assert attachments.path_of(tmp_path, "c", "a1") == kept / "a1"
    for name in ("D:a1", "C:a1", "..", ".", "", "../x"):
        assert attachments.path_of(tmp_path, "c", name) is None, name
