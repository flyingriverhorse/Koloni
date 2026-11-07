"""Slice 64: the model server on this machine, started and stopped from the Models page only.
llama-server stands in as tests/fake_llama_server.py, nvidia-smi as a script of the test's."""

import socket
import sys
import time
from pathlib import Path

import httpx
import pytest

from app.config import load_settings
from app.local_server import DEFAULT_ARGS, gpu_of, key_of, port_of
from app.main import create_app
from tests.keyed import TestClient

OWN = {"Origin": "http://127.0.0.1:8790"}
FAKE = Path(__file__).parent / "fake_llama_server.py"
READY = "--port 8080 --jinja"  # (no one's own model, nor their machine's settings)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def script(path: Path, body: str) -> Path:
    """A program the test writes: a .cmd on Windows, a shell script elsewhere."""
    if sys.platform == "win32":
        path = path.with_suffix(".cmd")
        path.write_text(f"@echo off\r\n{body}\r\n")
    else:
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(0o755)
    return path


def fake_server(folder: Path) -> Path:
    """A llama-server folder: the program, and a `models` folder with two models in it."""
    (folder / "models").mkdir(parents=True)
    for name in ("a.gguf", "b.gguf", "notes.txt"):
        (folder / "models" / name).write_bytes(b"")
    args = '%*' if sys.platform == "win32" else '"$@"'
    return script(folder / "llama-server", f'"{sys.executable}" "{FAKE}" {args}')


def until(client: TestClient, done, seconds: float = 20.0) -> dict:
    end = time.monotonic() + seconds
    while True:
        told = client.get("/api/local-server").json()
        if done(told) or time.monotonic() > end:
            return told
        time.sleep(0.2)


def answers(port: int) -> bool:
    try:
        return httpx.get(f"http://127.0.0.1:{port}/props", timeout=1).is_success
    except httpx.HTTPError:
        return False


@pytest.fixture
def server_app(tmp_path, settings_env):
    """The app with a fake llama-server and a fake nvidia-smi."""
    # The card's numbers; of its programs, one that is not the server. (cmd cuts `%1` at `=`.)
    smi = script(tmp_path / "nvidia-smi", (
        'if "%1"=="--query-gpu" '
        "(echo 18000, 24576, 35) else (echo 1, [N/A])" if sys.platform == "win32"
        else 'case "$1" in --query-gpu*) echo "18000, 24576, 35";; *) echo "1, [N/A]";; esac'))
    exe = fake_server(tmp_path / "Release")
    settings = load_settings({**settings_env, "KOLONI_LOCAL_SERVER": str(exe),
                              "KOLONI_NVIDIA_SMI": str(smi)})
    return create_app(settings), exe


def test_the_form_starts_from_the_ready_command_and_nothing_runs_by_itself(client):
    told = client.get("/api/local-server").json()
    assert told["args"] == DEFAULT_ARGS == READY.split()
    assert told["state"] == "stopped" and told["model"] is None and told["gpu"] is None
    assert told["output"] == ""


def test_only_the_apps_own_page_starts_stops_or_changes_it(client):
    config = {"executable": sys.executable, "args": ["-c", "print(1)"]}
    for origin in ({}, {"Origin": "http://evil.example"}):
        assert client.put("/api/local-server", json=config, headers=origin).status_code == 403
        for action in ("start", "stop", "restart"):
            assert client.post(f"/api/local-server/{action}", headers=origin).status_code == 403
    assert client.get("/api/local-server").json()["args"] == DEFAULT_ARGS


def test_cmd_takes_no_argument_it_would_read_as_a_command_of_its_own(client, tmp_path):
    # cmd.exe runs `&` in an argument as a second command; a model named `a&x.gguf` is one.
    ran = tmp_path / "ran.txt"
    for suffix in (".cmd", ".BAT"):
        exe = tmp_path / f"llama-server{suffix}"
        exe.write_text(f"@echo off\r\necho ran> \"{ran}\"\r\n")
        for arg in ("0.3&echo:INJECTED", r"models\a&x.gguf", "a|b", "<x", "^", "%PATH%", "!x!",
                    'a"b'):
            client.put("/api/local-server", headers=OWN,
                       json={"executable": str(exe), "args": ["--temp", arg]})
            r = client.post("/api/local-server/start", headers=OWN)
            assert r.status_code == 422 and "cmd.exe" in r.json()["detail"], arg
    assert not ran.exists()


def test_an_argument_with_a_nul_in_it_is_refused_not_a_failure(client):
    client.put("/api/local-server", headers=OWN,
               json={"executable": sys.executable, "args": ["-c", "print(1)\x00"]})
    r = client.post("/api/local-server/start", headers=OWN)
    assert r.status_code == 422 and "could not be started" in r.json()["detail"]
    assert client.get("/api/local-server").json()["state"] == "stopped"


def test_the_port_and_key_are_read_as_llama_server_reads_them():
    assert port_of(["--port", "9000", "--port=9001"]) == 9001
    assert port_of(["--port=9002", "--port", "9003"]) == 9003
    assert port_of(["--port", "x"]) == 8080 and port_of(["--port"]) == 8080
    assert key_of(["--api-key", "k1", "--api-key=k2"]) == "k2" and key_of([]) is None


def test_a_server_with_a_key_is_asked_with_it_and_the_key_is_not_shown(server_app):
    app, exe = server_app
    port = free_port()
    key = "local-key-0123456789abcdef"
    with TestClient(app, base_url="http://127.0.0.1:8790") as client:
        client.put("/api/local-server", headers=OWN, json={
            "executable": str(exe), "args": [f"--port={port}", "-c", "512", "--api-key", key]})
        client.post("/api/local-server/start", headers=OWN)
        told = until(client, lambda t: t["n_ctx"] is not None and "key:" in t["output"])
        assert (told["model"], told["n_ctx"]) == ("none.gguf", 512)
        assert key not in told["output"]
        client.post("/api/local-server/stop", headers=OWN)


def test_a_program_that_is_not_there_is_not_started(client, tmp_path):
    for exe in (str(tmp_path / "none.exe"), "llama-server.exe"):
        r = client.put("/api/local-server", json={"executable": exe, "args": []}, headers=OWN)
        assert r.status_code == 200
        r = client.post("/api/local-server/start", headers=OWN)
        assert r.status_code == 422 and "not a program" in r.json()["detail"]


def test_start_shows_the_model_window_output_and_gpu_then_stop_ends_it(server_app):
    app, exe = server_app
    port = free_port()
    args = ["-m", r"models\a.gguf", "--port", str(port), "-c", "4096", "--jinja"]
    with TestClient(app, base_url="http://127.0.0.1:8790") as client:
        r = client.put("/api/local-server", json={"executable": str(exe), "args": args},
                       headers=OWN)
        assert r.json()["models"] == [str(Path("models") / "a.gguf"), str(Path("models") / "b.gguf")]
        assert client.post("/api/local-server/start", headers=OWN).json()["state"] == "running"
        assert client.post("/api/local-server/start", headers=OWN).status_code == 409
        told = until(client, lambda t: t["n_ctx"] is not None and "listening" in t["output"])
        assert (told["state"], told["model"], told["n_ctx"]) == ("running", "a.gguf", 4096)
        # Masked as a command's output is: the key it printed is not shown.
        assert "sk-fake" not in told["output"] and "***" in told["output"]
        assert told["gpu"] == {"memory_used": 18000, "memory_total": 24576, "load": 35,
                               "share": None}
        assert answers(port)
        told = client.post("/api/local-server/stop", headers=OWN).json()
        assert told["state"] == "stopped" and told["gpu"] is None
        assert not answers(port)


def test_restart_runs_what_is_saved_now(server_app):
    app, exe = server_app
    port = free_port()
    with TestClient(app, base_url="http://127.0.0.1:8790") as client:
        for n_ctx, action in ((1000, "start"), (2000, "restart")):
            client.put("/api/local-server", headers=OWN, json={
                "executable": str(exe), "args": ["--port", str(port), "-c", str(n_ctx)]})
            assert client.post(f"/api/local-server/{action}", headers=OWN).status_code == 200
            assert until(client, lambda t, n=n_ctx: t["n_ctx"] == n)["n_ctx"] == n_ctx
        client.post("/api/local-server/stop", headers=OWN)


def test_a_server_that_ends_by_itself_says_its_exit_code(server_app, tmp_path):
    app, _ = server_app
    ends = script(tmp_path / "ends", "echo bad argument\r\nexit /b 3" if sys.platform == "win32"
                  else "echo bad argument\nexit 3")
    with TestClient(app, base_url="http://127.0.0.1:8790") as client:
        client.put("/api/local-server", headers=OWN, json={"executable": str(ends), "args": []})
        client.post("/api/local-server/start", headers=OWN)
        told = until(client, lambda t: t["state"] == "exited")
        assert told["exit_code"] == 3 and "bad argument" in told["output"]


def test_koloni_shutting_down_stops_it(server_app):
    app, exe = server_app
    port = free_port()
    with TestClient(app, base_url="http://127.0.0.1:8790") as client:
        client.put("/api/local-server", headers=OWN, json={
            "executable": str(exe), "args": ["--port", str(port)]})
        client.post("/api/local-server/start", headers=OWN)
        until(client, lambda t: t["model"] is not None)
        assert answers(port)
    assert not answers(port)


def test_gpu_numbers_are_read_from_nvidia_smi_or_left_unknown():
    assert gpu_of("18000, 24576, 35\n1, 2, 3\n", "77, 17000\n4, 10\n", 77) == {
        "memory_used": 18000, "memory_total": 24576, "load": 35, "share": 17000}
    # Windows' own drivers do not say a process's memory.
    assert gpu_of("[N/A], 24576, [N/A]", "77, [N/A]", 77) == {
        "memory_used": None, "memory_total": 24576, "load": None, "share": None}
    assert gpu_of(None, None, 77) is None
    assert gpu_of("", "", 77) is None
