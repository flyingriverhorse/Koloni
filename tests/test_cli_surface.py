"""K-cli-surface: a CLI version KOLONİ's protocol use was not measured with is asked its
protocol's first request once; one that does not answer runs the older way, and the Models
page says so. Only the stand-ins run here."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app import cli_surface
from app.model_agy import AgyClient
from app.model_cli import CodexCliClient
from app.model_native import ClaudeNativeClient, CodexNativeClient
from app.model_session import ClaudeSessionClient
from tests.test_attachment_agents import FAKE_CLAUDE, FAKE_CODEX, plan
from tests.test_copilot_agent import copilot_native, start  # noqa: F401  (a fixture)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def nothing_kept(monkeypatch):
    monkeypatch.setattr(cli_surface, "_answered", {})
    monkeypatch.setattr(cli_surface, "_said", {})


def started(tmp_path) -> list[str]:
    return [json.loads(line)[-1] for line in
            (tmp_path / "starts.jsonl").read_text("utf-8").splitlines()]


@pytest.mark.anyio
async def test_a_measured_version_is_asked_nothing_and_agy_only_its_version(tmp_path):
    codex = CodexNativeClient(launcher=FAKE_CODEX, **plan(
        tmp_path, starts=str(tmp_path / "starts.jsonl")))  # 0.164.0-fake: its numbers count
    assert await cli_surface.checked(codex) is codex
    assert started(tmp_path) == ["--version"]
    # (agy has no protocol to ask; B-310: one whose version is not known keeps KOLONİ's tools)
    agy = AgyClient(launcher=["no-such-agy"])
    assert await cli_surface.checked(agy) is agy and agy.collaborates
    assert cli_surface.note("codex_cli", None) is None
    assert cli_surface.note("agy_cli", None) is None


@pytest.mark.anyio
async def test_codex_not_measured_that_answers_runs_as_it_is_and_is_asked_once(tmp_path):
    codex = CodexNativeClient(launcher=FAKE_CODEX, **plan(
        tmp_path, version="0.170.0", starts=str(tmp_path / "starts.jsonl")))
    assert await cli_surface.checked(codex) is codex
    assert await cli_surface.checked(codex) is codex
    # its run's own line, once; then only its version
    assert started(tmp_path) == ["--version", "app-server", "--version"]
    assert cli_surface.note("codex_cli", None) == "Codex 0.170.0 not measured with KOLONİ"


@pytest.mark.anyio
async def test_codex_not_measured_that_refuses_initialize_runs_as_a_step(tmp_path):
    codex = CodexNativeClient(launcher=FAKE_CODEX, **plan(
        tmp_path, version="0.170.0", handshake="initialize"))
    older = await cli_surface.checked(codex)
    assert type(older) is CodexCliClient  # its own tools off: KOLONİ's run
    assert type(await cli_surface.checked(codex)) is CodexCliClient  # (kept: asked once)
    assert cli_surface.note("codex_cli", None) == (
        "Codex 0.170.0 not measured; running the old way")


@pytest.mark.anyio
@pytest.mark.parametrize("answer, native", [({}, True), ({"initialize": "error"}, False),
                                            ({"hooks_applied": False}, False)])
async def test_claude_code_not_measured_is_asked_initialize_with_its_hook(
    tmp_path, answer, native
):
    claude = ClaudeNativeClient(launcher=FAKE_CLAUDE, **plan(tmp_path, version="2.9.0", **answer))
    chosen = await cli_surface.checked(claude)
    assert (chosen is claude) if native else type(chosen) is ClaudeSessionClient
    seen = json.loads((tmp_path / "record.json").read_text("utf-8"))
    assert seen["init"]["request"]["hooks"]["PreToolUse"][0]["hookCallbackIds"]
    assert seen["stdin"] == ""  # never given a prompt: no turn
    assert "--disable-slash-commands" in seen["argv"]  # with its run's own line


@pytest.mark.parametrize("handshake, headless, said", [
    (None, True, "GitHub Copilot CLI 1.0.200 not measured with KOLONİ"),
    ("ping", False, "GitHub Copilot CLI 1.0.200 not measured; running the old way")])
def test_copilot_not_measured_runs_natively_if_it_answers_else_as_a_session_and_its_card_says(
    copilot_native, wait_run, project_dir, handshake, headless, said  # noqa: F811
):
    client, provider = copilot_native([{"say": "done"}], version="1.0.200",
                                      **({"handshake": handshake} if handshake else {}))
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    # natively, or its session with KOLONİ's tools
    assert ("--headless" in copilot_native.record()["argv"]) is headless
    (shown,) = [one for one in client.get("/api/providers").json() if one["id"] == provider["id"]]
    assert shown["version_note"] == said


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell")
def test_the_script_names_what_an_installed_cli_no_longer_has(tmp_path):
    surface = json.loads((ROOT / "app" / "cli_surface.json").read_text("utf-8"))
    schema = tmp_path / "schema"
    schema.mkdir()
    (schema / "a.json").write_text(json.dumps(surface["codex"]["names"][1:]), encoding="utf-8")
    claude = tmp_path / "claude-pkg"
    claude.mkdir()
    (claude / "cli.js").write_bytes(" ".join(surface["claude"]["names"]).encode())
    copilot = tmp_path / "copilot.exe"
    copilot.write_bytes(b"\x00".join(n.encode() for n in surface["copilot"]["names"][:-1]))
    agy = tmp_path / "agy.exe"
    agy.write_bytes(" ".join(surface["agy"]["names"]).encode())
    told = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(ROOT / "scripts" / "cli-surface.ps1"), "-CodexSchema", str(schema),
         "-Claude", str(claude), "-Copilot", str(copilot), "-Agy", str(agy)],
        capture_output=True, text=True, timeout=120)
    said = told.stdout
    assert told.returncode == 1, said + told.stderr
    assert f"codex: missing {surface['codex']['names'][0]}" in said
    assert f"copilot: missing {surface['copilot']['names'][-1]}" in said
    assert "claude: all" in said and "agy: all" in said
