"""K-cli-surface: a CLI version KOLONİ's protocol use was not measured with is asked its
protocol's first request once; one that does not answer runs the older way, and the Models
page says so. Only the stand-ins run here."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import app.model_native
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


COPILOT = "GitHub Copilot CLI"


@pytest.mark.parametrize("version, protocol, said", [
    ("1.0.105", 3, None),
    ("1.0.200", 3, f"{COPILOT} 1.0.200 not measured; running the old way"),
    ("1.0.200", 5, f"{COPILOT} 1.0.200 is newer than KOLONİ knows; running the old way"),
    ("1.0.200", 2, f"{COPILOT} 1.0.200 speaks a protocol KOLONİ does not know; running the old way"),
    ("1.0.114", 4, f"{COPILOT} 1.0.114 not measured with KOLONİ")])
def test_copilot_runs_natively_or_the_old_way_by_its_protocol_and_its_card_says(
    copilot_native, wait_run, project_dir, version, protocol, said  # noqa: F811
):
    # The version is the one KOLONİ runs, its own `status.get` as KOLONİ starts it - not what a
    # plain `--version` says (20 Nov 2026: 1.0.107, the package Copilot updated itself to in the
    # user's home; KOLONİ's empty COPILOT_HOME runs the program's own, 1.0.105). Its protocol
    # with it: a measured protocol-3 version runs natively, any other the old way.
    client, provider = copilot_native([{"say": "done"}], version=version, protocol=protocol,
                                      updated="1.0.103")
    cid, run_id = start(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    # natively (protocol 4: through KOLONİ's hook), or its session with KOLONİ's tools
    assert ("--headless" in copilot_native.record()["argv"]) is (
        said is None or said.endswith("with KOLONİ"))
    (shown,) = [one for one in client.get("/api/providers").json() if one["id"] == provider["id"]]
    assert shown["version_note"] == said


def test_copilots_version_and_protocol_are_read_in_one_start_with_no_auto_update(
    copilot_native, wait_run, project_dir, tmp_path  # noqa: F811
):
    starts = tmp_path / "starts.jsonl"
    client, provider = copilot_native([{"say": "done"}], version="1.0.105",
                                      starts=str(starts))
    cid, run_id = start(client, project_dir, provider)
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    # its status, then its run: both headless as a run starts it, never a plain --version (it
    # would name the package Copilot updated itself to) and never one that updates itself
    began = [json.loads(line) for line in starts.read_text("utf-8").splitlines()]
    assert len(began) == 2, began
    assert all("--headless" in argv and "--no-auto-update" in argv for argv in began)


@pytest.mark.parametrize("told", [{"status_error": True}, {"status_hang": True}])
def test_a_copilot_that_does_not_say_its_status_runs_the_old_way_and_its_card_says(
    copilot_native, wait_run, project_dir, monkeypatch, told  # noqa: F811
):
    monkeypatch.setattr(app.model_native, "VERSION_SECONDS", 1.0)  # (one that never says)
    client, provider = copilot_native([{"say": "done"}], **told)
    cid, run_id = start(client, project_dir, provider)
    run = wait_run(client, cid, run_id)["runs"][0]
    assert run["status"] == "completed", run["error"]
    assert "--headless" not in copilot_native.record()["argv"]  # its session, KOLONİ's tools
    (shown,) = [one for one in client.get("/api/providers").json() if one["id"] == provider["id"]]
    assert shown["version_note"] == f"{COPILOT} did not say its version; running the old way"


@pytest.mark.parametrize("version, status", [("1.0.200", "failed"), ("1.0.105", "completed")])
def test_its_run_itself_asks_a_protocol_3_copilot_its_version_before_it_works_natively(
    copilot_native, wait_run, project_dir, monkeypatch, version, status  # noqa: F811
):
    # (Its program replaced between the check and the run: the run asks again, and works
    # natively only on a measured version.)
    async def unchecked(client):
        return client

    monkeypatch.setattr(cli_surface, "checked", unchecked)
    client, provider = copilot_native([{"say": "done"}], version=version)
    cid, run_id = start(client, project_dir, provider)
    run = wait_run(client, cid, run_id)["runs"][0]
    assert run["status"] == status, run["error"]
    if status == "failed":
        assert "could not be asked before it acts" in run["error"]
        assert "1.0.200 is not measured with KOLONİ" in run["error"]
        assert "create" not in copilot_native.record()  # no session made


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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell and a .cmd stand-in")
def test_the_script_asks_the_copilot_koloni_runs_and_searches_the_package_it_runs(tmp_path):
    # (No real CLI is run: each one is a stand-in, Copilot a .cmd that says 1.0.114.)
    surface = json.loads((ROOT / "app" / "cli_surface.json").read_text("utf-8"))
    names = surface["copilot"]["names"]
    seen = tmp_path / "seen.txt"
    copilot = tmp_path / "copilot.cmd"
    copilot.write_text(f'@echo off\r\necho %*^|%COPILOT_HOME%> "{seen}"\r\n'
                       f'dir /b "%COPILOT_HOME%" >> "{seen}" 2>nul\r\n'
                       "echo GitHub Copilot CLI 1.0.114.\r\n", encoding="ascii")
    package = tmp_path / "local" / "copilot" / "pkg" / "win32-x64" / "1.0.114"
    (package / "prebuilds" / "win32-x64").mkdir(parents=True)
    (package / "prebuilds" / "win32-x64" / "runtime.node").write_bytes(
        b"\x00".join(n.encode() for n in names[:-1]))
    (package / "copilot-sdk").mkdir()
    (package / "copilot-sdk" / "index.js").write_text("// the SDK", encoding="utf-8")
    schema = tmp_path / "schema"
    schema.mkdir()
    (schema / "a.json").write_text(json.dumps(surface["codex"]["names"]), encoding="utf-8")
    claude = tmp_path / "claude-pkg"
    claude.mkdir()
    (claude / "cli.js").write_bytes(" ".join(surface["claude"]["names"]).encode())
    agy = tmp_path / "agy.exe"
    agy.write_bytes(" ".join(surface["agy"]["names"]).encode())
    told = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(ROOT / "scripts" / "cli-surface.ps1"), "-CodexSchema", str(schema),
         "-Claude", str(claude), "-CopilotExe", str(copilot), "-Agy", str(agy)],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, "LOCALAPPDATA": str(tmp_path / "local")})
    said = told.stdout
    assert told.returncode == 1, said + told.stderr
    assert "copilot: version GitHub Copilot CLI 1.0.114. (NOT measured" in said
    assert f"copilot: searching {package} (the package it runs)" in said
    assert f"copilot: missing {names[-1]}" in said and "codex: all" in said
    # asked as KOLONİ starts it: no update of its own, in an empty home of KOLONİ's, gone after
    asked, home = seen.read_text("ascii").splitlines()[0].split("|")
    assert asked.split() == ["--no-auto-update", "--version"]
    assert home.strip() and "koloni-copilot-home-" in home
    assert len(seen.read_text("ascii").splitlines()) == 1  # (nothing in it)
    assert not Path(home.strip()).exists()
