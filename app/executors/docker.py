"""Runs commands in a fresh container with the project folder mounted at /workspace."""

import asyncio
import contextlib
import os
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from app.commands import secret_files
from app.executors.base import StartError
from app.executors.host import ProcessCommand

CONTAINER_PREFIX = "koloni-"
STATUS_TTL_SECONDS = 10.0


@dataclass(frozen=True)
class DockerStatus:
    available: bool
    error: str | None


async def _exec(argv: list[str], timeout: float) -> tuple[int, str]:
    """Run a short docker CLI call; returns (exit code, combined output)."""
    process = await asyncio.create_subprocess_exec(
        *argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError:
        process.kill()
        raise
    return process.returncode or 0, output.decode("utf-8", errors="replace")


_cached: tuple[float, DockerStatus] | None = None


def forget_status() -> None:
    global _cached
    _cached = None


async def docker_status() -> DockerStatus:
    """Whether a Docker daemon answers; cached briefly because the UI polls it."""
    global _cached
    if _cached and time.monotonic() - _cached[0] < STATUS_TTL_SECONDS:
        return _cached[1]
    try:
        code, output = await _exec(["docker", "version", "--format", "{{.Server.Version}}"], 5.0)
    except FileNotFoundError:
        status = DockerStatus(False, "the docker command was not found")
    except TimeoutError:
        status = DockerStatus(False, "Docker did not answer in time")
    except OSError as exc:
        status = DockerStatus(False, f"could not run docker: {exc.strerror or exc}")
    else:
        if code == 0:
            status = DockerStatus(True, None)
        else:
            lines = output.strip().splitlines()
            detail = lines[-1] if lines else "no answer"
            status = DockerStatus(False, f"Docker is not running ({detail[:200]})")
    _cached = (time.monotonic(), status)
    return status


def container_name(command_id: str) -> str:
    return f"{CONTAINER_PREFIX}{command_id}"


def docker_argv(
    name: str, image: str, root: Path, cwd: Path, network: bool, command: str,
    links: dict[str, Path] | None = None, hidden: tuple[Path, ...] = (),
    empty: Path | None = None, named: tuple[str, ...] = (),
) -> list[str]:
    """`root`: what the container gets as its /workspace - the project folder, or an
    agent's working copy instead of it. `links`: the copy's linked dependency folders,
    each mounted from where it really is (a junction leads nowhere in the container);
    nothing else of the project is mounted then. `cwd` in one of those is where that is
    mounted; StartError for a folder that is not in the container at all. `hidden`: the
    secret files and folders in those, each with `empty`'s empty one of its kind mounted
    over it, read-only (slice 104). `named`: the variables it gets from the client's own
    environment, by name only (slice 91)."""
    places = {"": root, **{f"/{at}": target for at, target in (links or {}).items()}}

    def inside(path: Path) -> str | None:
        return next((
            f"/workspace{at}/{path.relative_to(top).as_posix()}".removesuffix("/.")
            for at, top in places.items() if path == top or path.is_relative_to(top)
        ), None)

    workdir = inside(cwd)
    if workdir is None:
        raise StartError(f"{cwd} is not in the folder the container gets")
    shared = [
        part for at, target in (links or {}).items()
        for part in ("-v", f"{target}:/workspace/{at}")
    ]
    # shortcut: one mount for each, uncounted - a folder of hundreds of keys and certificates
    # may pass Windows' longest command line - and the project's own CA bundle (*.pem) is
    # emptied too; cover a folder by one mount, or pass a named file, if either is met.
    covered = [
        part for path in hidden if empty is not None and (at := inside(path))
        for part in ("-v", f"{empty / ('folder' if path.is_dir() else 'file')}:{at}:ro")
    ]
    # Linux and macOS: what a command makes is the user's, not root's - with a home it can write,
    # as the image has none for that uid. (Windows: Docker Desktop maps the owner itself.)
    # shortcut: a command that needs root in the container (apt-get install) now fails, and under
    # rootless Docker (container root is the user there) its files go to a subuid instead; give
    # the project an "as root" switch if a user asks for one, or asks Docker which it is.
    user = (["--user", f"{os.getuid()}:{os.getgid()}", "--env", "HOME=/tmp"]
            if hasattr(os, "getuid") else [])
    return [
        "docker", "run", "--rm", "--name", name,
        "-v", f"{root}:/workspace", *shared, *covered,
        "-w", workdir, "--env", "PYTHONDONTWRITEBYTECODE=1",  # (no __pycache__/ left in it)
        *user,
        *(part for name in named for part in ("-e", name)),
        "--network", "bridge" if network else "none",
        image, "sh", "-c", command,
    ]


class DockerCommand(ProcessCommand):
    """A `docker run` client process; killing it means killing the container."""

    def __init__(self, process: asyncio.subprocess.Process, name: str):
        super().__init__(process)
        self._name = name

    async def _kill_tree(self) -> None:
        # Ending the client alone would leave the container running: stop the container.
        try:
            code, _ = await _exec(["docker", "kill", self._name], 15.0)
        except (OSError, TimeoutError):
            code = 1
        if code != 0:
            # Not running yet, or the kill did not take: make sure it cannot go on.
            with contextlib.suppress(OSError, TimeoutError):
                await _exec(["docker", "rm", "-f", self._name], 15.0)
        if self._process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self._process.kill()

    async def close(self) -> None:
        """`--rm` removes a finished container; only a client still running needs ending."""
        if self._process.returncode is None:
            await self.kill()

    def start_failure(self, code: int, output: str) -> str | None:
        # docker run exits 125 when Docker itself failed (mount refused, daemon error),
        # as opposed to the command running and failing.
        if code != 125:
            return None
        lines = [line for line in output.strip().splitlines() if line.strip()]
        detail = lines[-1].strip() if lines else "no reason given"
        return f"Docker could not start the container: {detail}"


class DockerExecutor:
    location = "docker"

    def __init__(self, root: Path, image: str, network: bool, empty: Path | None = None):
        """`empty`: where the empty file and folder put over its secrets are; None: the
        project lets its commands see them (`Project.hide_secrets`)."""
        self._root, self._image, self._network, self._empty = root, image, network, empty

    async def start(
        self, command_id: str, command: str, cwd: Path, copy: Path | None = None,
        links: dict[str, Path] | None = None, secrets: Mapping[str, str] | None = None,
    ) -> DockerCommand:
        # Nothing here falls back to the host: if Docker cannot run it, nothing runs.
        status = await docker_status()
        if not status.available:
            raise StartError(f"Docker is not available: {status.error}")
        try:
            code, _ = await _exec(["docker", "image", "inspect", self._image], 15.0)
        except (OSError, TimeoutError) as exc:
            raise StartError(f"Docker is not available: {exc}") from None
        if code != 0:
            # "No such image" and "the daemon just went away" both land here: ask again
            # rather than trust a status cached a few seconds ago.
            forget_status()
            status = await docker_status()
            if not status.available:
                raise StartError(f"Docker is not available: {status.error}")
            raise StartError(
                f"the image {self._image} is not on this machine; run: docker pull {self._image}"
            )
        name = container_name(command_id)
        # For an agent that works in a copy the container gets the copy, not the project.
        top = copy or self._root
        hidden: tuple[Path, ...] = ()
        if self._empty is not None:
            (self._empty / "folder").mkdir(parents=True, exist_ok=True)
            (self._empty / "file").touch()
            # (A linked folder - node_modules, .venv, venv - holds what was installed: no
            # secret of the project's, `secret_in_project`.)
            hidden = tuple(top / rel for rel in await asyncio.to_thread(secret_files, top))
        argv = docker_argv(
            name, self._image, top, cwd, self._network, command, links if copy else None,
            hidden, self._empty, tuple(secrets or ()),
        )
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                # (`-e NAME` takes the value from here: never on the command line.)
                env={**os.environ, **secrets} if secrets else None,
            )
        except OSError as exc:
            raise StartError(f"could not start docker: {exc.strerror or exc}") from None
        return DockerCommand(process, name)


async def kill_containers(command_ids: list[str]) -> None:
    """Stop containers left running by commands a previous process did not finish."""
    for command_id in command_ids:
        try:
            await _exec(["docker", "kill", container_name(command_id)], 15.0)
        except (OSError, TimeoutError):
            return
