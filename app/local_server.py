"""The model server on this machine (slice 64): llama.cpp's llama-server, started and stopped
only from the user's Models page - never when KOLONİ opens, never by an agent - and Start
keeps the form's program and arguments first. It runs as its own program with the user's
arguments as a list, never through a shell, in its own folder (where its `models\\...` paths
are), and ends with KOLONİ."""

import asyncio
import contextlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import httpx2

from app.commands import OutputMask, secret_values
from app.executors.host import ProcessCommand, _job_for, command_env
from app.model_client import count_of

# As the form first shows it and as it runs until changed: the user picks the model.
DEFAULT_ARGS = ["--port", "8080", "--jinja"]
CONFIG = "local-server.json"
# Of what it printed, the end is kept: it writes a line for every request it answers.
MAX_OUTPUT = 64_000
ASK_SECONDS = 2.0
SMI_SECONDS = 5.0


class Busy(Exception):
    pass


class NotStarted(Exception):
    pass


def _last(args: list[str], flag: str) -> str | None:
    """A flag's value as llama-server reads it: the last, as `--flag value` or `--flag=value`."""
    found = None
    for at, arg in enumerate(args):
        if arg == flag and at + 1 < len(args):
            found = args[at + 1]
        elif arg.startswith(f"{flag}="):
            found = arg[len(flag) + 1:]
    return found


def port_of(args: list[str]) -> int:
    """The port it serves on: its `--port`, else 8080.
    shortcut: asked on 127.0.0.1 whatever `--host` says, and a port given by `LLAMA_ARG_PORT`
    is not read; read them if one is ever used."""
    port = _last(args, "--port") or ""
    return int(port) if port.isdigit() else 8080


def key_of(args: list[str]) -> str | None:
    """The key it asks for, sent with the status's questions and hidden in what it prints.
    shortcut: `--api-key-file` and `LLAMA_API_KEY` are not read; its model is then unknown."""
    return _last(args, "--api-key")


# What cmd.exe reads in an argument as its own (`&` starts a second command): a .cmd or .bat
# runs in it, a .exe gets its arguments as they are.
CMD_SPECIAL = set('&|<>^%!"')


def _number(text: str) -> int | None:
    text = text.strip()
    return int(text) if text.isdigit() else None


def gpu_of(cards: str | None, apps: str | None, pid: int | None) -> dict | None:
    """The graphics card's memory used and in all (MiB), its load (%) and the server's share
    of the memory, from nvidia-smi's CSV; None where nothing was read, a number None where
    it was not said (`[N/A]`: Windows' own drivers say no process's memory).
    shortcut: the first card only; add them up if a machine with two is met."""
    lines = (cards or "").strip().splitlines()
    if not lines:
        return None
    used, total, load = ([*lines[0].split(","), "", "", ""][:3])
    share = None
    for line in (apps or "").splitlines():
        fields = line.split(",")
        if len(fields) == 2 and fields[0].strip() == str(pid):
            share = _number(fields[1])
    return {"memory_used": _number(used), "memory_total": _number(total), "load": _number(load),
            "share": share}


class LocalServer:
    """One llama-server at a time, and what it printed, masked as a command's output is."""

    def __init__(self, runtime_root: Path, executable: Path, nvidia_smi: str):
        self._file = runtime_root / CONFIG
        self._default = executable
        self._smi = nvidia_smi
        self._lock = asyncio.Lock()
        self._command: ProcessCommand | None = None
        self._reader: asyncio.Task | None = None
        self._pid: int | None = None
        self.output = ""
        self.exit_code: int | None = None

    def config(self) -> dict:
        """The program and its arguments as the user last set them, else the ready command."""
        try:
            told = json.loads(self._file.read_text("utf-8"))
            return {"executable": str(told["executable"]), "args": [str(a) for a in told["args"]]}
        except (OSError, ValueError, KeyError, TypeError):
            return {"executable": str(self._default), "args": list(DEFAULT_ARGS)}

    def save(self, executable: str, args: list[str]) -> None:
        # Whole or not at all: a half-written file would start the ready command instead.
        self._file.parent.mkdir(parents=True, exist_ok=True)
        part = self._file.with_suffix(".part")
        part.write_text(json.dumps({"executable": executable, "args": args}), "utf-8")
        os.replace(part, self._file)

    @property
    def running(self) -> bool:
        return self._command is not None

    async def start(self) -> None:
        async with self._lock:
            await self._start()

    async def _start(self) -> None:
        if self._command is not None:
            raise Busy
        told = self.config()
        exe, args = Path(told["executable"]), told["args"]
        if not (exe.is_absolute() and exe.is_file()):
            raise NotStarted(f"{exe} is not a program on this machine; set Program to the full "
                             "path of llama-server (in a llama.cpp build's bin folder)")
        if exe.suffix.lower() in (".cmd", ".bat") and any(CMD_SPECIAL & set(a) for a in args):
            raise NotStarted(f"{exe.name} runs in cmd.exe, which would read one of "
                             f"{''.join(sorted(CMD_SPECIAL))} in an argument as its own; "
                             "take it out or start a .exe")
        # As a command's (slice 103). shortcut: a secret variable such as HF_TOKEN is withheld,
        # so a gated `-hf` download fails; pass one through if that is asked for.
        try:
            process = await asyncio.create_subprocess_exec(
                str(exe), *args, cwd=exe.parent, env=command_env(),
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                start_new_session=sys.platform != "win32",
            )
        except (OSError, ValueError) as exc:  # ValueError: a NUL in an argument
            raise NotStarted(f"{exe} could not be started: "
                             f"{getattr(exc, 'strerror', None) or exc}") from None
        self._command = command = ProcessCommand(process, _job_for(process))
        self._pid, self.output, self.exit_code = process.pid, "", None
        self._reader = asyncio.create_task(self._read(command, key_of(args)), name="local-server")

    async def _read(self, command: ProcessCommand, key: str | None) -> None:
        # Always read: a full pipe would stop the server.
        mask = OutputMask([*secret_values(os.environ), *([key] if key else [])])
        async for chunk in command:
            self._add(mask.feed(chunk))
        self._add(mask.flush())
        code = await command.wait()
        if self._command is command:  # it ended by itself, not by Stop
            self._command, self.exit_code = None, code
            await command.close()

    def _add(self, text: str) -> None:
        self.output = (self.output + text)[-MAX_OUTPUT:]

    async def stop(self) -> None:
        """End it and everything it started; nothing when it is not running."""
        async with self._lock:
            await self._stop()

    async def _stop(self) -> None:
        command, self._command = self._command, None
        if command is None:
            return
        await command.kill()
        if self._reader is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._reader, 10)

    async def restart(self) -> None:
        # One hold: no other Start comes between.
        async with self._lock:
            await self._stop()
            await self._start()

    async def status(self) -> dict:
        told = self.config()
        exe = Path(told["executable"])
        folder = exe.parent / "models"
        models = sorted(str(Path("models") / p.name) for p in folder.glob("*.gguf")) \
            if exe.is_absolute() and folder.is_dir() else []
        model = n_ctx = gpu = None
        # Only its own: a server started by hand is not this one, and no Stop here ends it.
        if self.running:
            args = told["args"]
            (model, n_ctx), gpu = await asyncio.gather(
                self._served(port_of(args), key_of(args)), self._gpu())
        state = "running" if self.running else "exited" if self.exit_code is not None \
            else "stopped"
        return {**told, "models": models, "state": state, "exit_code": self.exit_code,
                "model": model, "n_ctx": n_ctx, "gpu": gpu, "output": self.output}

    async def _served(self, port: int, key: str | None) -> tuple[str | None, int | None]:
        """The model it serves and its window, as it says them; None while it loads."""
        base = f"http://127.0.0.1:{port}"
        model = n_ctx = None
        unsaid = (httpx2.HTTPError, ValueError, LookupError, TypeError, AttributeError)
        headers = {"Authorization": f"Bearer {key}"} if key else None
        async with httpx2.AsyncClient(timeout=ASK_SECONDS, headers=headers) as http:
            with contextlib.suppress(*unsaid):
                model = str((await http.get(f"{base}/v1/models")).json()["data"][0]["id"])
            with contextlib.suppress(*unsaid):
                said = (await http.get(f"{base}/props")).json()["default_generation_settings"]
                n_ctx = count_of(said.get("n_ctx"))
        return model, n_ctx

    async def _gpu(self) -> dict | None:
        cards = await self._ask_smi("--query-gpu=memory.used,memory.total,utilization.gpu")
        apps = await self._ask_smi("--query-compute-apps=pid,used_memory") if cards else None
        return gpu_of(cards, apps, self._pid)

    async def _ask_smi(self, query: str) -> str | None:
        """What nvidia-smi says, or None: not installed, failed or too slow."""
        program = shutil.which(self._smi)
        if program is None:
            return None
        try:
            smi = await asyncio.create_subprocess_exec(
                program, query, "--format=csv,noheader,nounits",
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError:
            return None
        try:
            out, _ = await asyncio.wait_for(smi.communicate(), SMI_SECONDS)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                smi.kill()
            return None
        return out.decode(errors="replace") if smi.returncode == 0 else None
