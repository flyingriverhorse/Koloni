import asyncio
import subprocess
from pathlib import Path

import pytest

from app.db.models import Project
from app.executors import docker, executor_for
from app.executors.base import StartError
from app.executors.docker import DockerExecutor, DockerStatus, docker_argv, docker_status

pytestmark = pytest.mark.anyio


def test_docker_argv_mounts_the_project_and_sets_the_folder(tmp_path):
    root = tmp_path / "p"
    argv = docker_argv("koloni-k1", "python:3.12", root, root / "src" / "x", False, "pytest -q")
    assert argv[:5] == ["docker", "run", "--rm", "--name", "koloni-k1"]
    assert argv[argv.index("-v") + 1] == f"{root}:/workspace"
    assert argv[argv.index("-w") + 1] == "/workspace/src/x"
    assert argv[argv.index("--network") + 1] == "none"
    assert argv[-4:] == ["python:3.12", "sh", "-c", "pytest -q"]
    assert argv[argv.index("--env") + 1] == "PYTHONDONTWRITEBYTECODE=1"  # (no __pycache__/ left)

    at_root = docker_argv("n", "alpine", root, root, True, "ls")
    assert at_root[at_root.index("-w") + 1] == "/workspace"
    assert at_root[at_root.index("--network") + 1] == "bridge"


def test_docker_argv_runs_as_the_user_where_there_are_uids(tmp_path, monkeypatch):
    # (Linux: else what a command makes in the project is root's)
    monkeypatch.setattr(docker.os, "getuid", lambda: 1000, raising=False)
    monkeypatch.setattr(docker.os, "getgid", lambda: 1001, raising=False)
    argv = docker_argv("n", "python:3.12", tmp_path, tmp_path, False, "ls")
    assert argv[argv.index("--user") + 1] == "1000:1001" and "HOME=/tmp" in argv
    assert argv.index("--user") < argv.index("python:3.12")
    monkeypatch.delattr(docker.os, "getuid")
    assert "--user" not in docker_argv("n", "python:3.12", tmp_path, tmp_path, False, "ls")


def mounts(argv):
    return [argv[at + 1] for at, part in enumerate(argv) if part == "-v"]


def test_docker_argv_for_a_working_copy_mounts_the_copy_and_never_the_project(tmp_path):
    """The container gets the copy, and the linked dependency folders from their real
    places (a junction leads nowhere in it): no other way into the project is mounted."""
    project, copy = tmp_path / "p", tmp_path / "runtime" / "copies" / "a1" / "tree"
    links = {"node_modules": project / "node_modules", "web/.venv": project / "web" / ".venv"}
    argv = docker_argv("n", "alpine", copy, copy / "src", False, "ls", links)
    assert mounts(argv) == [
        f"{copy}:/workspace",
        f"{project / 'node_modules'}:/workspace/node_modules",
        f"{project / 'web' / '.venv'}:/workspace/web/.venv",
    ]
    assert argv[argv.index("-w") + 1] == "/workspace/src"
    assert not [part for part in argv if part.startswith(f"{project}:")]


def test_docker_argv_in_a_linked_folder_works_where_that_is_mounted(tmp_path):
    """The agent's folder is one the copy shares with the project: its real place is
    the project's, and in the container that is under the copy's own name for it."""
    project, copy = tmp_path / "p", tmp_path / "runtime" / "copies" / "a1" / "tree"
    links = {"node_modules": project / "node_modules", "web/.venv": project / "web" / ".venv"}
    inside = docker_argv("n", "alpine", copy, project / "node_modules" / "pkg", False, "ls", links)
    assert inside[inside.index("-w") + 1] == "/workspace/node_modules/pkg"
    at_link = docker_argv("n", "alpine", copy, project / "web" / ".venv", False, "ls", links)
    assert at_link[at_link.index("-w") + 1] == "/workspace/web/.venv"
    # anywhere else is not in the container: a failed start, with a plain reason
    for cwd in (project / "src", tmp_path):
        with pytest.raises(StartError, match="not in the folder"):
            docker_argv("n", "alpine", copy, cwd, False, "ls", links)
    with pytest.raises(StartError):
        docker_argv("n", "alpine", project, tmp_path, False, "ls")


async def test_a_command_of_a_working_copy_is_started_on_the_copy(monkeypatch, tmp_path):
    project, copy = tmp_path / "p", tmp_path / "copies" / "a1" / "tree"
    ran = []

    async def fine(argv, timeout):
        return 0, "27.0"

    async def spawn(*argv, **given):
        ran.append(list(argv))
        return None

    monkeypatch.setattr(docker, "_exec", fine)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    docker.forget_status()
    links = {"venv": project / "venv"}
    await DockerExecutor(project, "alpine", False).start("k1", "ls", copy, copy=copy, links=links)
    assert mounts(ran[0]) == [f"{copy}:/workspace", f"{project / 'venv'}:/workspace/venv"]
    # and one that runs in the project is started as before
    await DockerExecutor(project, "alpine", False).start("k2", "ls", project)
    assert mounts(ran[1]) == [f"{project}:/workspace"]
    docker.forget_status()


def test_executor_for_picks_by_the_commands_recorded_location(tmp_path):
    project = Project(id="p", name="p", root_path=str(tmp_path), exec_location="docker",
                      docker_image="alpine", docker_network=True)
    assert executor_for("host", project, tmp_path).location == "host"
    chosen = executor_for("docker", project, tmp_path)
    assert isinstance(chosen, DockerExecutor) and chosen.location == "docker"
    project.docker_image = None
    with pytest.raises(StartError, match="no Docker image is set"):
        executor_for("docker", project, tmp_path)


async def test_status_when_the_docker_program_is_missing(monkeypatch):
    async def missing(argv, timeout):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(docker, "_exec", missing)
    docker.forget_status()
    status = await docker_status()
    assert status == DockerStatus(False, "the docker command was not found")


async def test_status_when_the_daemon_is_not_running(monkeypatch):
    async def down(argv, timeout):
        return 1, "error during connect: open //./pipe/dockerDesktopLinuxEngine: not found\n"

    monkeypatch.setattr(docker, "_exec", down)
    docker.forget_status()
    status = await docker_status()
    assert status.available is False and "Docker is not running" in status.error


async def test_status_when_docker_does_not_answer(monkeypatch):
    async def hang(argv, timeout):
        raise TimeoutError

    monkeypatch.setattr(docker, "_exec", hang)
    docker.forget_status()
    assert (await docker_status()).error == "Docker did not answer in time"


async def test_start_fails_cleanly_when_docker_is_not_available(monkeypatch, tmp_path):
    started = []

    async def down(argv, timeout):
        started.append(argv)
        return 1, "Cannot connect to the Docker daemon"

    monkeypatch.setattr(docker, "_exec", down)
    docker.forget_status()
    with pytest.raises(StartError, match="Docker is not available"):
        await DockerExecutor(tmp_path, "alpine", False).start("k1", "echo hi", tmp_path)
    assert all(argv[1] != "run" for argv in started)


async def test_missing_image_is_a_start_error_with_the_pull_command(monkeypatch, tmp_path):
    async def no_image(argv, timeout):
        if argv[1] == "version":
            return 0, "27.0.1\n"
        return 1, "Error: No such image: python:3.12"

    monkeypatch.setattr(docker, "_exec", no_image)
    docker.forget_status()
    with pytest.raises(StartError, match="docker pull python:3.12"):
        await DockerExecutor(tmp_path, "python:3.12", False).start("k1", "echo hi", tmp_path)


def test_health_reports_docker_state(client, monkeypatch):
    async def fake_status():
        return DockerStatus(False, "Docker is not running")

    monkeypatch.setattr("app.api.health.docker_status", fake_status)
    body = client.get("/api/health").json()
    assert (body["docker_available"], body["docker_error"]) == (False, "Docker is not running")


# --- against a real Docker daemon: pytest -m live ---------------------------


async def _run(executor: DockerExecutor, command: str, cwd: Path, name: str = "k-live"):
    running = await executor.start(name, command, cwd)

    async def drain():
        return "".join([chunk async for chunk in running])

    return await asyncio.wait_for(asyncio.gather(drain(), running.wait()), 120)


@pytest.mark.live
async def test_live_output_exit_code_and_a_file_written_into_the_project(tmp_path):
    executor = DockerExecutor(tmp_path, "alpine", False)
    output, code = await _run(executor, "echo hi; echo made > made.txt; exit 4", tmp_path)
    assert "hi" in output and code == 4
    assert (tmp_path / "made.txt").read_text().strip() == "made"


@pytest.mark.live
async def test_live_network_is_off_by_default(tmp_path):
    executor = DockerExecutor(tmp_path, "alpine", False)
    _, code = await _run(executor, "wget -q -T 3 -O /dev/null http://example.com", tmp_path)
    assert code != 0


@pytest.mark.live
async def test_live_kill_stops_the_container(tmp_path):
    executor = DockerExecutor(tmp_path, "alpine", False)
    running = await executor.start("k-kill", "sleep 120", tmp_path)
    await asyncio.sleep(3)
    await running.kill()
    await asyncio.wait_for(running.wait(), 20)
    listing = subprocess.run(
        ["docker", "ps", "--filter", "name=koloni-k-kill", "--format", "{{.Names}}"],
        capture_output=True, text=True).stdout
    assert listing.strip() == ""
