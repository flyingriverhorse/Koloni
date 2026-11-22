"""Kanıtlı bitiş S5a, what needs no model: each kind of work's checks on files written to a folder -
documents, diagrams, data, slides (`app.proof_kinds`). Only what is sure and fixable fails; what a
tool may read otherwise is a note; what the file had before the turn is a note."""

import base64
import io
import json
import struct
import time
import tracemalloc
import zipfile
import zlib
from urllib.parse import quote

from app import proof_kinds
from app.proof_kinds import check_data, check_diagrams, check_docs, check_slides


def put(root, rel, content):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8", newline="")
    return rel


def said(rows):
    return [(one["state"], one["text"]) for one in rows]


def test_md_links_and_anchors(tmp_path):
    put(tmp_path, "docs/guide.md", "# Guide\n\n## Install it\n")
    put(tmp_path, "img/logo.png", b"png")
    rel = put(tmp_path, "README.md", (
        "# Readme\n\n## Start here\n\n[guide](docs/guide.md) and [install](docs/guide.md#install-it)"
        " and ![logo](img/logo.png) and [up](#start-here) and [web](https://example.com) and "
        "[mail](mailto:a@b.c) and [site root](/about)\n\n```\n[in a fence](nowhere.md)\n```\n"))
    rows = check_docs(tmp_path, [rel])
    assert ("passed", "README.md: 4 links, all found") in said(rows), said(rows)
    put(tmp_path, "README.md", "# Readme\n\n[gone](docs/old.md) [bad anchor](docs/guide.md#nope)\n")
    rows = said(check_docs(tmp_path, [rel]))
    assert ("failed", "README.md: link to docs/old.md not found") in rows
    assert ("note", "README.md: anchor #nope not found in docs/guide.md") in rows
    assert not [one for one in rows if one[0] == "passed"]


def test_heading_skips_and_two_h1_are_notes(tmp_path):
    rel = put(tmp_path, "a.md", "# One\n\n### Three\n\n# Again\n")
    rows = said(check_docs(tmp_path, [rel]))
    assert ("note", "a.md: heading level skips from 1 to 3") in rows
    assert ("note", "a.md: 2 top-level (#) headings, not one") in rows
    assert not [one for one in rows if one[0] == "failed"]


def test_sections_asked_are_a_note_not_a_failure(tmp_path):
    rel = put(tmp_path, "report.md", "# Report\n\n## Results\n\n## Next steps\n")
    asked = "Write a report with:\n- results\n- next steps\n- a cost table\n1. Make it short and do not add anything else at all please\n"
    rows = said(check_docs(tmp_path, [rel], asked))
    assert ("note", "Sections you listed and no heading names: - a cost table") in rows
    assert ("note", "Spelling: not checked") in rows
    assert not [one for one in rows if one[0] == "failed"]


def test_docx_that_does_not_open(tmp_path):
    good = io.BytesIO()
    with zipfile.ZipFile(good, "w") as made:
        made.writestr("word/document.xml", "<w:document xmlns:w='w'><w:body/></w:document>")
    put(tmp_path, "ok.docx", good.getvalue())
    put(tmp_path, "bad.docx", b"not a zip")
    rows = said(check_docs(tmp_path, ["ok.docx", "bad.docx"]))
    assert ("passed", "ok.docx: opens") in rows
    assert ("failed", "bad.docx: does not open as a Word document") in rows


MODEL = ("<mxGraphModel><root><mxCell id='0'/><mxCell id='1' parent='0'/>"
         "<mxCell id='a' value='A' vertex='1' parent='1'><mxGeometry x='0' y='0' width='80' height='40'/></mxCell>"
         "<mxCell id='b' value='B' vertex='1' parent='1'><mxGeometry x='200' y='0' width='80' height='40'/></mxCell>"
         "<mxCell id='e' edge='1' source='a' target='b' parent='1'/></root></mxGraphModel>")


def packed(xml: str) -> str:
    squeeze = zlib.compressobj(wbits=-15)
    return base64.b64encode(squeeze.compress(quote(xml).encode()) + squeeze.flush()).decode()


def test_drawio_plain_and_compressed(tmp_path):
    put(tmp_path, "plain.drawio", f"<mxfile><diagram id='p'>{MODEL}</diagram></mxfile>")
    put(tmp_path, "packed.drawio", f"<mxfile><diagram id='p'>{packed(MODEL)}</diagram></mxfile>")
    rows = said(check_diagrams(tmp_path, ["plain.drawio", "packed.drawio"]))
    assert ("passed", "plain.drawio: 1 edges, 2 shapes, all connected") in rows
    assert ("passed", "packed.drawio: 1 edges, 2 shapes, all connected") in rows
    put(tmp_path, "broken.drawio", "<mxfile><diagram>")
    assert said(check_diagrams(tmp_path, ["broken.drawio"]))[0][0] == "failed"


def test_drawio_dangling_edge_overlap_and_lonely_shape(tmp_path):
    model = MODEL.replace("target='b'", "target='gone'").replace(
        "</root>", "<mxCell id='c' value='C' vertex='1' parent='1'><mxGeometry x='0' y='0' "
                   "width='80' height='40'/></mxCell><mxCell id='d' value='D' vertex='1' parent='1'>"
                   "<mxGeometry x='500' y='0' width='80' height='40'/></mxCell></root>")
    rel = put(tmp_path, "d.drawio", f"<mxfile><diagram>{model}</diagram></mxfile>")
    rows = said(check_diagrams(tmp_path, [rel]))
    assert ("failed", "d.drawio: edge e points at nothing") in rows
    assert ("note", "d.drawio: 2 labelled shapes lie on each other") in rows  # (A and C)
    assert ("note", "d.drawio: 3 shapes are not connected") in rows  # (B, C, D)


def test_svg_and_mermaid(tmp_path):
    put(tmp_path, "a.svg", "<svg xmlns='http://www.w3.org/2000/svg'><rect/></svg>")
    put(tmp_path, "b.svg", "<svg><rect></svg>")
    put(tmp_path, "c.mmd", "%% a note\nflowchart TD\n  A --> B\n")
    put(tmp_path, "d.mmd", "A --> B\n")
    put(tmp_path, "e.puml", "@startuml\nA -> B\n@enduml\n")
    rows = said(check_diagrams(tmp_path, ["a.svg", "b.svg", "c.mmd", "d.mmd", "e.puml"]))
    assert ("passed", "a.svg: parses") in rows and rows[1][0] == "failed"
    assert ("passed", "c.mmd: a flowchart diagram") in rows
    assert ("note", "c.mmd: drawn: not checked (Mermaid draws in the app only)") in rows
    assert ("note", "d.mmd: the first line names no Mermaid diagram type KOLONİ knows") in rows
    assert ("passed", "e.puml: @startuml … @enduml") in rows


def test_an_xml_with_a_dtd_is_not_read(tmp_path):
    bomb = ("<?xml version='1.0'?><!DOCTYPE lolz [<!ENTITY lol 'lol'>"
            "<!ENTITY lol2 '&lol;&lol;&lol;'>]><svg>&lol2;</svg>")
    rel = put(tmp_path, "bomb.svg", bomb)
    assert said(check_diagrams(tmp_path, [rel])) == [
        ("note", "bomb.svg: not checked: it declares a DTD or entities, which KOLONİ does not read")]


def test_csv_ragged_rows(tmp_path):
    put(tmp_path, "ok.csv", "﻿a,b,c\r\n1,2,3\r\n4,5,6\r\n")  # (a BOM and CRLF)
    put(tmp_path, "bad.tsv", "a\tb\n1\t2\n3\n4\t5\t6\n7\n")
    rows = said(check_data(tmp_path, ["ok.csv", "bad.tsv"]))
    assert ("passed", "ok.csv: 2 rows × 3 columns") in rows
    assert ("failed", "bad.tsv: rows 3, 5 have 1 fields, not 2") in rows
    assert ("failed", "bad.tsv: rows 4 have 3 fields, not 2") in rows


def notebook(cells):
    return json.dumps({"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5})


def test_notebook_out_of_order_and_error_cell(tmp_path):
    put(tmp_path, "ok.ipynb", notebook([
        {"cell_type": "code", "execution_count": 1, "outputs": [], "source": ""},
        {"cell_type": "markdown", "source": "# x"},
        {"cell_type": "code", "execution_count": 2, "outputs": [], "source": ""}]))
    put(tmp_path, "bad.ipynb", notebook([
        {"cell_type": "code", "execution_count": 3, "outputs": [], "source": ""},
        {"cell_type": "code", "execution_count": 1, "source": "",
         "outputs": [{"output_type": "error", "ename": "ZeroDivisionError"}]}]))
    rows = said(check_data(tmp_path, ["ok.ipynb", "bad.ipynb", "c.parquet"]))
    assert ("passed", "ok.ipynb: 2 code cells, run in order") in rows
    assert ("note", "ok.ipynb: not re-run: KOLONİ does not run notebooks") in rows
    assert ("failed", "bad.ipynb: cell 2 ends in an error") in rows
    assert ("note", "bad.ipynb: cells did not run in order from 1 (3, 1)") in rows
    assert ("note", "c.parquet: not checked: 'c.parquet' does not exist") in rows or any(
        text.startswith("c.parquet: not checked") for _state, text in rows)  # (not there: said)
    put(tmp_path, "d.parquet", b"PAR1")
    assert said(check_data(tmp_path, ["d.parquet"])) == [
        ("note", "d.parquet: not checked: only CSV and notebooks are read")]


def pptx(*slides, notes=0):
    made = io.BytesIO()
    with zipfile.ZipFile(made, "w") as deck:
        for at, body in enumerate(slides, 1):
            deck.writestr(f"ppt/slides/slide{at}.xml", f"<p:sld xmlns:p='p' xmlns:a='a'>{body}</p:sld>")
        for at in range(1, notes + 1):
            deck.writestr(f"ppt/notesSlides/notesSlide{at}.xml", "<p:notes/>")
    return made.getvalue()


def test_pptx_empty_slide_and_notes(tmp_path):
    put(tmp_path, "ok.pptx", pptx("<a:t>Title</a:t>", "<p:pic>x</p:pic>", notes=1))
    put(tmp_path, "bad.pptx", pptx("<a:t>Title</a:t>", "<a:t>  </a:t>"))
    rows = said(check_slides(tmp_path, ["ok.pptx", "bad.pptx", "c.key"]))
    assert ("passed", "ok.pptx: 2 slides, 1 with notes") in rows
    assert ("failed", "bad.pptx: slide 2 is empty") in rows
    assert ("note", "ok.pptx: overflow and contrast: not checked (no slide renderer here)") in rows


def test_a_path_outside_the_root_is_never_read(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    put(tmp_path, "secret.md", "[x](nowhere.md)\n")
    rel = put(root, "a.md", "[out](../secret.md) [far](../../x.md)\n")
    assert said(check_docs(root, ["../secret.md"]))[0] == (
        "note", "../secret.md: not read - it is outside the project")
    rows = said(check_docs(root, [rel]))
    assert ("note", "a.md: link to ../secret.md leads outside the project") in rows
    assert not [one for one in rows if one[0] == "failed"]


def test_a_problem_the_file_had_before_the_turn_is_a_note(tmp_path):
    rel = put(tmp_path, "README.md", "# R\n\n[old](gone.md) [new](also-gone.md)\n")
    rows = said(check_docs(tmp_path, [rel], before={rel: "# R\n\n[old](gone.md)\n"}))
    assert ("note", "README.md: link to gone.md not found - so before this turn") in rows
    assert ("failed", "README.md: link to also-gone.md not found") in rows


def test_a_long_line_is_read_in_linear_time(tmp_path):
    rel = put(tmp_path, "long.md", "[" * 100_000 + "\n" + "#" + " " * 100_000 + "x" + " #" * 50_000)
    started = time.monotonic()
    check_docs(tmp_path, [rel], "- x\n" + "-" * 100_000)
    assert time.monotonic() - started < 5


def test_a_zip_member_too_big_is_not_read(tmp_path, monkeypatch):
    monkeypatch.setattr(proof_kinds, "MOST_BYTES", 100)
    rel = put(tmp_path, "big.pptx", pptx("<a:t>" + "x" * 500 + "</a:t>"))
    rows = said(check_slides(tmp_path, [rel]))
    assert rows[0][0] == "note" and "not checked" in rows[0][1], rows


def test_valid_files_a_reader_may_take_otherwise_are_not_failed(tmp_path):
    # (Review: each of these spent a fix round on valid work.)
    put(tmp_path, "chart.pptx", pptx("<p:graphicFrame>chart</p:graphicFrame>",
                                     "<p:sp><p:spPr><a:prstGeom prst='rect'/></p:spPr></p:sp>"))
    put(tmp_path, "front.mmd", "---\ntitle: Flow\n---\nflowchart LR\n  A --> B\n")
    put(tmp_path, "new.mmd", "quadrantChart\n  title Reach\n")
    put(tmp_path, "odd.mmd", "someNewChart\n")
    put(tmp_path, "mind.puml", "@startmindmap\n* root\n@endmindmap\n")
    put(tmp_path, "docs/guide.md", "# Guide\n")
    put(tmp_path, "docs/api/index.md", "# API\n")
    put(tmp_path, "site.md", "# Site\n\n[g](docs/guide) [a](docs/api/) and `[code](nowhere.md)`\n")
    put(tmp_path, "wide.csv", "a,b\n" + "x" * 200_000 + ",1\n")
    rows = said(check_slides(tmp_path, ["chart.pptx"]) + check_diagrams(
        tmp_path, ["front.mmd", "new.mmd", "odd.mmd", "mind.puml"]) + check_docs(
        tmp_path, ["site.md"]) + check_data(tmp_path, ["wide.csv"]))
    assert not [one for one in rows if one[0] == "failed"], rows
    assert ("passed", "chart.pptx: 2 slides, 0 with notes") in rows
    assert ("passed", "front.mmd: a flowchart diagram") in rows
    assert ("passed", "new.mmd: a quadrantChart diagram") in rows
    assert ("note", "odd.mmd: the first line names no Mermaid diagram type KOLONİ knows") in rows
    assert ("passed", "mind.puml: @startmindmap … @endmindmap") in rows
    assert ("passed", "site.md: 2 links, all found") in rows
    assert ("note", "wide.csv: not checked: a field is over the CSV reader's limit") in rows


def test_a_zip_member_that_breaks_its_reader_is_said_not_checked(tmp_path):
    deck = bytearray(pptx("<a:t>" + "word " * 200 + "</a:t>"))
    at = deck.find(b"word")  # (stored: no compression - corrupt the member's own deflate instead)
    made = io.BytesIO()
    with zipfile.ZipFile(made, "w", compression=zipfile.ZIP_DEFLATED) as broken:
        broken.writestr("ppt/slides/slide1.xml", "<p:sld><a:t>" + "word " * 200 + "</a:t></p:sld>")
    data = bytearray(made.getvalue())
    start = data.find(b"ppt/slides/slide1.xml") + len("ppt/slides/slide1.xml")
    data[start + 5:start + 25] = b"\xff" * 20  # (inside the compressed stream)
    rel = put(tmp_path, "broken.pptx", bytes(data))
    rows = said(check_slides(tmp_path, [rel]))
    # (One line for the file - however its reader breaks - never the whole check broken.)
    assert at >= 0 and len(rows) == 1 and rows[0] in (
        ("failed", "broken.pptx: does not open as a PowerPoint file"),) or rows[0][1].startswith(
        "broken.pptx: not checked"), rows


def test_a_file_gives_at_most_a_dozen_lines(tmp_path):
    rel = put(tmp_path, "many.md", "".join(f"[x{i}](gone{i}.md)\n" for i in range(30)))
    rows = said(check_docs(tmp_path, [rel]))
    mine = [one for one in rows if one[1].startswith("many.md")]
    assert len(mine) == proof_kinds.MOST_ROWS_A_FILE + 1
    assert mine[-1] == ("note", "many.md: +18 more lines")


def test_a_reader_that_breaks_any_way_is_one_line_not_a_broken_check(tmp_path, monkeypatch):
    def broke(_data, _rel):
        raise RuntimeError("zipfile: a member of an unknown compression")
    monkeypatch.setattr(proof_kinds, "_pptx", broke)
    rel = put(tmp_path, "a.pptx", pptx("<a:t>x</a:t>"))
    assert said(check_slides(tmp_path, [rel])) == [
        ("note", "a.pptx: not checked: zipfile: a member of an unknown compression")]


# --- review of S5a: what a hostile file inflates to is read no further than the caps -----------

def peak_of(work):
    """What `work` returns, and the most Python heap it held at once."""
    was = tracemalloc.is_tracing()
    tracemalloc.start()
    tracemalloc.reset_peak()
    try:
        before = tracemalloc.get_traced_memory()[0]
        out = work()
        return out, tracemalloc.get_traced_memory()[1] - before
    finally:
        if not was:
            tracemalloc.stop()


def lying_docx(inflated: int, says: int) -> bytes:
    """A .docx whose one member inflates to `inflated` bytes and whose zip says it holds `says`."""
    squeeze = zlib.compressobj(9, zlib.DEFLATED, -15)
    raw = squeeze.compress(b"<a>" + b"A" * inflated + b"</a>") + squeeze.flush()
    name = b"word/document.xml"
    local = struct.pack("<4s5H3L2H", b"PK\x03\x04", 20, 0, 8, 0, 0, 0, len(raw), says,
                        len(name), 0) + name + raw
    central = struct.pack("<4s6H3L5H2L", b"PK\x01\x02", 20, 20, 0, 8, 0, 0, 0, len(raw), says,
                          len(name), 0, 0, 0, 0, 0, 0) + name
    end = struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, 1, 1, len(central), len(local), 0)
    return local + central + end


def test_a_zip_member_is_read_no_further_than_the_cap_whatever_size_it_says(tmp_path,
                                                                             monkeypatch):
    # (The probe: a 298 KB .docx saying 100 bytes inflated to 300 MB at once - 602 MB of heap.
    # A file is read no further than MOST_BYTES + 1 - Python makes room for that much first.)
    monkeypatch.setattr(proof_kinds, "MOST_INFLATED", 64 * 2**10)
    monkeypatch.setattr(proof_kinds, "MOST_BYTES", 256 * 2**10)
    put(tmp_path, "lies.docx", lying_docx(4 * 2**20, 100))
    put(tmp_path, "big.docx", lying_docx(4 * 2**20, 4 * 2**20 + 7))
    rows, peak = peak_of(lambda: said(check_docs(tmp_path, ["lies.docx", "big.docx"])))
    assert peak < 2**20, peak  # (not the 4 MB it inflates to)
    assert rows[0] == ("failed", "lies.docx: does not open as a Word document"), rows
    assert rows[1][0] == "note" and rows[1][1].startswith("big.docx: not checked: it is over"), rows


def test_a_decks_slides_are_capped_together_and_by_number(tmp_path, monkeypatch):
    monkeypatch.setattr(proof_kinds, "MOST_INFLATED", 64 * 2**10)
    rel = put(tmp_path, "many.pptx", pptx(*["<a:t>" + "x" * 10_000 + "</a:t>"] * 10))
    ((state, text),) = said(check_slides(tmp_path, [rel]))
    assert state == "note" and text.endswith("MB inflated"), text
    monkeypatch.setattr(proof_kinds, "MOST_MEMBERS", 3)
    rel = put(tmp_path, "four.pptx", pptx(*["<a:t>x</a:t>"] * 4))
    assert said(check_slides(tmp_path, [rel])) == [
        ("note", "four.pptx: not checked: it has over 3 slides")]


def drawio_pages(n: int, size: int) -> str:
    page = f"<mxGraphModel><root><mxCell id='0' value='{'A' * size}'/></root></mxGraphModel>"
    return "<mxfile>" + "".join(f"<diagram id='p{i}'>{packed(page)}</diagram>"
                                for i in range(n)) + "</mxfile>"


def test_a_drawio_files_pages_are_capped_together(tmp_path, monkeypatch):
    # (The probe: 30 pages just under 8 MB each, all kept until the end - 264 MB.)
    monkeypatch.setattr(proof_kinds, "MOST_INFLATED", 64 * 2**10)
    rel = put(tmp_path, "d.drawio", drawio_pages(30, 40_000))
    ((state, text),) = said(check_diagrams(tmp_path, [rel]))
    assert state == "note" and text.startswith("d.drawio: not checked: its pages are over"), text


def test_a_drawio_files_pages_are_checked_one_at_a_time(tmp_path, monkeypatch):
    # (20 pages of 200 KB: kept all at once they held 4 MB; one at a time, a page or two.)
    monkeypatch.setattr(proof_kinds, "MOST_BYTES", 256 * 2**10)  # (the file: a few KB)
    rel = put(tmp_path, "d.drawio", drawio_pages(20, 200_000))
    rows, peak = peak_of(lambda: said(check_diagrams(tmp_path, [rel])))
    assert rows == [("passed", "d.drawio: 0 edges, 0 shapes")], rows
    assert peak < 2.5 * 2**20, peak


def test_a_dtd_is_refused_whatever_the_encoding(tmp_path):
    # (The probe: in UTF-16 the byte search for "<!DOCTYPE" found nothing.)
    laughs = ('<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE svg [<!ENTITY a "' + "x" * 100
              + '"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]><svg>&b;</svg>')
    outside = ('<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE svg [<!ENTITY x SYSTEM '
               '"file:///C:/Windows/win.ini">]><svg>&x;</svg>')
    put(tmp_path, "laughs.svg", laughs.encode("utf-16"))
    put(tmp_path, "outside.svg", outside.encode("utf-16"))
    put(tmp_path, "fine.svg", '<?xml version="1.0" encoding="UTF-16"?><svg><rect/></svg>'.encode(
        "utf-16"))
    refused = "not checked: it declares a DTD or entities, which KOLONİ does not read"
    assert said(check_diagrams(tmp_path, ["laughs.svg", "outside.svg", "fine.svg"])) == [
        ("note", f"laughs.svg: {refused}"), ("note", f"outside.svg: {refused}"),
        ("passed", "fine.svg: parses")]
