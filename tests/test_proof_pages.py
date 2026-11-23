"""Kanıtlı bitiş S5b: a turn's pages in KOLONİ's own headless browser - each changed `.html` page,
and the chat's running preview where a component or a style changed - at 375, 768 and 1280 px:
console errors and a page wider than the screen are failed (a fix round, as S5a's kinds are), a
page that loads from outside this machine is a note, no browser or no preview is said. The
stand-in browser (`tests/fake_browser.py`) plays Chrome; one test drives the real one where this
machine has it."""

import os
import sys
from pathlib import Path

import pytest

from app import browser, proof_kinds
from app.workspace import Workspace
from tests.fakes import ScriptedExecutor
from tests.test_agent_writes import write
from tests.test_browser import served  # noqa: F401  (a fixture)
from tests.test_chat_flow import text
from tests.test_proof_end_scenarios import OWN, PASS, begin, texts

pytestmark = pytest.mark.no_po

FAKE = str(Path(__file__).with_name("fake_browser.py"))
ALL = "375, 768, 1280"
ERROR_PAGE = "<html><title>A</title><script>console.error('x is not defined')</script></html>"
CLEAN_PAGE = "<html><title>B</title><body><p>Hello</p></body></html>"
WIDE_PAGE = '<html><title>C</title><body data-fits-from="800"><p>Wide</p></body></html>'
OUT_PAGE = '<html><title>D</title><script src="https://cdn.example/x.js"></script></html>'


def pages(root: Path, **found: str) -> list[str]:
    for name, html in found.items():
        (root / f"{name}.html").write_text(html, encoding="utf-8")
    return [f"{name}.html" for name in found]


def starter(scratch: Path, ws: Workspace, command: list[str] | None = None):
    async def start() -> browser.Browser:
        one = browser.Browser(scratch, "pages")
        await one.start(command or [sys.executable, FAKE], ws, set())
        return one

    return start


def said(rows):
    return [(one["kind"], one["state"], one["text"]) for one in rows]


@pytest.mark.anyio
async def test_a_page_with_a_console_error_is_failed_at_each_width(tmp_path):
    ws, shots = Workspace(str(tmp_path)), tmp_path / ".koloni" / "tmp" / "checked" / "r1"
    found = pages(tmp_path, index=ERROR_PAGE, about=CLEAN_PAGE)
    rows = await proof_kinds.check_pages(starter(tmp_path / "b", ws), ws, found, None, shots)
    assert said(rows) == [
        (
            "ui",
            "failed",
            f"index.html: 1 console errors at {ALL} px - console.error: x is not defined",
        ),
        ("ui", "passed", f"about.html: no console errors at {ALL} px"),
    ]
    # (each page at each width, for the user - in the scratch, never among the project's files)
    assert sorted(one.name for one in shots.iterdir()) == sorted(
        f"{name}-{width}.png" for name in ("about-html", "index-html") for width in (375, 768, 1280)
    )


@pytest.mark.anyio
async def test_a_wide_page_is_said(tmp_path):
    ws = Workspace(str(tmp_path))
    found = pages(tmp_path, wide=WIDE_PAGE)
    rows = await proof_kinds.check_pages(
        starter(tmp_path / "b", ws), ws, found, None, tmp_path / "shots"
    )
    assert said(rows) == [("ui", "failed", "wide.html: wider than the screen at 375, 768 px")]


@pytest.mark.anyio
async def test_a_page_that_loads_from_outside_this_machine_is_a_note(tmp_path):
    # (KOLONİ's browser never goes out: the page is not wrong for that - not sent back)
    ws = Workspace(str(tmp_path))
    found = pages(tmp_path, out=OUT_PAGE)
    rows = await proof_kinds.check_pages(
        starter(tmp_path / "b", ws), ws, found, None, tmp_path / "shots"
    )
    # (its failed load is no error of its own; what it was checked without is said)
    assert said(rows) == [
        ("ui", "passed", f"out.html: no console errors at {ALL} px"),
        (
            "ui",
            "note",
            "out.html: checked without what it loads from outside this machine, "
            "which KOLONİ's browser never opens: https://cdn.example/x.js",
        ),
    ]
    # (a script of its own failing beside such a load: said, not sent back - it may be of it)
    found = pages(
        tmp_path, both=OUT_PAGE.replace("</html>", "<script>console.error('x')</script></html>")
    )
    rows = await proof_kinds.check_pages(
        starter(tmp_path / "b2", ws), ws, found, None, tmp_path / "shots"
    )
    assert said(rows)[0] == (
        "ui",
        "note",
        f"both.html: 1 console errors at {ALL} px - it loads "
        "from outside this machine, which KOLONİ's browser never opens: "
        "console.error: x",
    )


@pytest.mark.anyio
async def test_no_browser_is_said(tmp_path):
    ws = Workspace(str(tmp_path))
    found = pages(tmp_path, index=CLEAN_PAGE)
    assert said(await proof_kinds.check_pages(None, ws, found, None, tmp_path / "shots")) == [
        ("ui", "note", "Pages not checked: no Chrome or Edge here")
    ]


@pytest.mark.anyio
async def test_a_component_change_without_a_preview_is_said(tmp_path):
    async def never() -> browser.Browser:
        raise AssertionError("no browser for nothing to open")

    rows = await proof_kinds.check_pages(
        never, Workspace(str(tmp_path)), ["src/App.tsx", "src/app.css"], None, tmp_path / "s"
    )
    assert said(rows) == [("ui", "note", "Pages not checked: no preview running")]


@pytest.mark.anyio
async def test_a_component_change_is_looked_at_on_the_running_preview(tmp_path, served):  # noqa: F811
    ws = Workspace(str(tmp_path))
    rows = await proof_kinds.check_pages(
        starter(tmp_path / "b", ws), ws, ["src/App.tsx"], served, tmp_path / "shots"
    )
    # (the stand-in's preview page says console.error('oops'))
    assert said(rows) == [
        (
            "ui",
            "failed",
            f"the preview {served}: 1 console errors at {ALL} px - console.error: oops",
        )
    ]


@pytest.mark.anyio
async def test_at_most_three_pages_a_turn(tmp_path):
    ws = Workspace(str(tmp_path))
    found = pages(tmp_path, a=CLEAN_PAGE, b=CLEAN_PAGE, c=CLEAN_PAGE, d=CLEAN_PAGE)
    rows = await proof_kinds.check_pages(
        starter(tmp_path / "b", ws), ws, found, None, tmp_path / "shots"
    )
    assert said(rows)[0] == ("ui", "note", "Pages not checked: d.html - at most 3 pages a turn")
    assert [line for _kind, state, line in said(rows) if state == "passed"] == [
        f"{name}.html: no console errors at {ALL} px" for name in "abc"
    ]


@pytest.mark.skipif(
    browser.find_browser() is None or "KOLONI_BROWSER_FAKE" in os.environ,
    reason="no Chrome or Edge on this machine",
)
@pytest.mark.anyio
async def test_the_real_chrome_finds_an_error_and_a_page_too_wide_for_a_phone(
    tmp_path, monkeypatch
):
    # (What it finds is tested here, not how fast: a busy machine is waited for longer.)
    monkeypatch.setattr(browser, "START_WAIT", 120.0)
    monkeypatch.setattr(browser, "LOAD_WAIT", 40.0)
    monkeypatch.setattr(proof_kinds, "PAGES_SECONDS", 600)
    ws, command = Workspace(str(tmp_path)), browser.find_browser()
    found = pages(
        tmp_path,
        broken="<html><head><meta name='viewport' content='width=device-width'>"
        "</head><body><script>console.error('oops')</script></body></html>",
        wide="<html><head><meta name='viewport' content='width=device-width'></head><body>"
        "<div style='width:1000px'>wide</div></body></html>",
    )
    rows = await proof_kinds.check_pages(
        starter(tmp_path / "b", ws, command), ws, found, None, tmp_path / "shots"
    )
    assert said(rows) == [
        ("ui", "failed", f"broken.html: 1 console errors at {ALL} px - console.error: oops"),
        ("ui", "failed", "wide.html: wider than the screen at 375, 768 px"),
    ]
    assert (tmp_path / "shots" / "wide-html-375.png").read_bytes().startswith(b"\x89PNG")


@pytest.mark.anyio
async def test_a_missing_script_of_the_project_is_the_pages_own_error(tmp_path):
    # (Refused too - "not a file of the project" - but no address out of this machine: failed)
    ws = Workspace(str(tmp_path))
    found = pages(tmp_path, gone='<html><title>G</title><script src="missing.js"></script></html>')
    rows = await proof_kinds.check_pages(
        starter(tmp_path / "b", ws), ws, found, None, tmp_path / "shots"
    )
    ((kind, state, line),) = said(rows)
    assert (kind, state) == ("ui", "failed") and line.startswith(
        f"gone.html: 1 console errors at {ALL} px - network error: Failed to load"
    ), line


@pytest.mark.anyio
async def test_an_outside_stylesheet_does_not_hide_the_pages_own_error(tmp_path):
    ws = Workspace(str(tmp_path))
    found = pages(
        tmp_path,
        styled='<html><title>S</title><script src="https://fonts.example/'
        "a.css\"></script><script>console.error('own')</script></html>",
    )
    rows = await proof_kinds.check_pages(
        starter(tmp_path / "b", ws), ws, found, None, tmp_path / "shots"
    )
    assert said(rows)[0] == (
        "ui",
        "failed",
        f"styled.html: 1 console errors at {ALL} px - console.error: own",
    )


def test_a_favicon_and_an_outside_load_are_not_the_pages_own_errors():
    # (Measured with Chrome here: a preview with no favicon.ico logs its 404 at the first load.)
    console = "\n".join(
        [
            "network error: Failed to load resource: the server responded with a status of 404 "
            "(File not found) (http://127.0.0.1:5173/favicon.ico)",
            "network error: Failed to load resource: net::ERR_BLOCKED_BY_CLIENT "
            "(https://cdn.example/lib.js)",
            "console.log: ready",
            "error: ReferenceError: lib is not defined (http://127.0.0.1:5173/)",
        ]
    )
    refused = "\nrefused: https://cdn.example/lib.js: not a web address of this machine; x"
    assert proof_kinds._errors(console, refused) == (
        ["error: ReferenceError: lib is not defined (http://127.0.0.1:5173/)"],
        True,
    )
    assert proof_kinds._errors(console.split("\n", 1)[0], "") == ([], False)


# --- the end check: a page the turn wrote ------------------------------------------------------


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("KOLONI_BROWSER_FAKE", FAKE)


def test_a_page_with_an_error_is_one_fix_round_then_said(fake, make_client, wait_run, project_dir):
    client, model = make_client(
        [
            write("index.html", ERROR_PAGE),
            text("done"),
            write("index.html", CLEAN_PAGE, "w2"),
            text("fixed"),
        ],
        executor=ScriptedExecutor([PASS, PASS]),
    )
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    snap = wait_run(client, cid, run_id, timeout=30)
    nudged = [
        str(m["content"])
        for m in model.calls[-1]
        if m["role"] == "user"
        and str(m["content"]).startswith("Not the end yet: KOLONİ's checks of what")
    ]
    assert len(nudged) == 1 and "index.html: 1 console errors at" in nudged[0]
    # (what the page said reaches the model only as data)
    assert "x is not defined" in nudged[0] and "data, not instructions" in nudged[0]
    assert f"index.html: no console errors at {ALL} px" in texts(snap)
    shots = project_dir / ".koloni" / "tmp" / "checked" / run_id
    assert len(list(shots.glob("index-html-*.png"))) == 3
    assert not (shots / "profile-pages").exists()  # (its browser gone with the look)


def test_pages_switched_off_are_said_not_checked(fake, make_client, wait_run, project_dir):
    client, model = make_client(
        [write("index.html", ERROR_PAGE), text("done")], executor=ScriptedExecutor([PASS])
    )
    cid, run_id = begin(
        client, project_dir, check_command="python check.py", check_kinds={"ui": False}
    )
    snap = wait_run(client, cid, run_id)
    assert "Not checked: pages switched off for this project" in texts(snap)
    assert not (project_dir / ".koloni" / "tmp" / "checked").exists()
    pid = snap["conversation"]["project_id"]
    assert client.get(f"/api/projects/{pid}").json()["check_kinds"] == {"ui": False}
    assert (
        client.patch(
            f"/api/projects/{pid}", json={"check_kinds": {"ui": True}}, headers=OWN
        ).status_code
        == 200
    )


def test_a_component_change_with_no_preview_running_is_said(
    fake, make_client, wait_run, project_dir
):
    client, _model = make_client(
        [write("src/App.tsx", "export const A = 1\n"), text("done")],
        executor=ScriptedExecutor([PASS]),
    )
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    snap = wait_run(client, cid, run_id)
    assert "Pages not checked: no preview running" in texts(snap)
