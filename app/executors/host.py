"""Runs commands on this machine, in the project folder, as the app's own user."""

import asyncio
import codecs
import contextlib
import functools
import os
import shutil
import signal
import subprocess
import sys
from collections.abc import AsyncIterator, Mapping
from pathlib import Path

from app import copies
from app.commands import held_back
from app.executors.base import StartError
from app.executors.winjob import Job, resume

CHUNK = 4096
# denetim-010 #5: on Windows a process is started suspended and runs only once it is in its
# job (`_job_for`): one put there after it started could start children first, outside it,
# and they outlived Stop. (CREATE_SUSPENDED; Popen refuses creationflags off Windows.)
SUSPENDED: dict = {"creationflags": 0x4} if sys.platform == "win32" else {}

# Windows PowerShell writes program and cmdlet output in the OEM code page unless told
# otherwise, which turns "ş" into "s" or "?". Ask for UTF-8 before anything runs.
# B-324: 5.1 also reads a file without a BOM in the ANSI code page ("KÃ¼Ã§Ã¼k"), so files are
# read as UTF-8 - and written so too: read right but written in ANSI, "ş" comes back as "s"
# (measured). The cost: Set-Content and Out-File (and `>`) start a file with a UTF-8 BOM (5.1
# has no UTF-8 without one; before, Set-Content wrote ANSI and `>` UTF-16LE); Add-Content to a
# file that is there adds none. A file in an ANSI code page (cp1252, cp1254) reads with U+FFFD
# for its non-ASCII letters, and read, changed and written back it loses them (EF BF BD in
# the file) - where the old round trip kept its bytes by chance.
# K-pwsh: PowerShell 7 (`pwsh`) is preferred where it is. Measured (7.6.9): its console is
# still ibm437 without the first line ("ş" printed as "s"), and with 'UTF8' its Set-Content,
# Out-File, `>` and Add-Content all write without a BOM - the same prologue serves both.
_PS_PROLOGUE = (
    # 7 colours its errors with ANSI escapes even into a pipe (measured); 5.1 has no $PSStyle.
    "if ($PSStyle) { $PSStyle.OutputRendering = 'PlainText' }; "
    "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
    "$OutputEncoding = [Console]::OutputEncoding; "
    "$PSDefaultParameterValues = @{'Get-Content:Encoding' = 'UTF8'; "
    "'Set-Content:Encoding' = 'UTF8'; 'Add-Content:Encoding' = 'UTF8'; "
    "'Out-File:Encoding' = 'UTF8'}\n"
    # K-ps-nesne (R116): `gci | select name` printed only "\n". The whole -Command script is
    # one pipeline into one Out-Default, whose table formatter holds objects with no
    # predefined view until that pipeline ends - and the epilogue's `exit` ends it before
    # then (measured 5.1 and 7.6.9: nothing even after a Start-Sleep; `gci` alone, with a
    # view, streamed). So the command is a pipeline of its own, dot-sourced to keep its scope
    # and `$?`: its table is written out before `exit` comes.
    # `$true` first: a command ending in a top-level `return` leaves the block before `$?` is
    # taken, and exits 0 as it did.
    # shortcut: an unbalanced `}` in the command is reported at the epilogue's line, not the
    # command's; objects left on the pipeline before an in-command `exit` or `throw` are still
    # lost (as before); Write-Host text comes before a later table. Upgrade if an agent is
    # seen misled by any of these.
    "$koloniOk = $true; . {\n"
)
# What the agent is told of it with where its commands run (`AgentRunner`'s shell_note),
# in 5.1 alone (`shell_writes`).
SHELL_WRITES = (" In this shell Set-Content, Out-File and > write UTF-8 with a BOM: write JSON, "
                "TOML and scripts with write_file instead." if sys.platform == "win32" else "")
# PowerShell itself exits 0 or 1 whatever happened inside. Report the last statement:
# success is 0; a failed program passes its own exit code on; a failed cmdlet is 1.
_PS_EPILOGUE = (
    "\n$koloniOk = $? } | Out-Default; "
    "if ($koloniOk) { exit 0 } "
    "elseif ($LASTEXITCODE) { exit $LASTEXITCODE } "
    "else { exit 1 }"
)


@functools.cache
def _pwsh_found() -> tuple[str, ...]:
    """Every pwsh in sight, once per process: an install under Program Files first, then
    each on PATH - `which` gives only the first, and the Store alias may stand before an
    install (or this process may have started before it was installed)."""
    if sys.platform != "win32":
        return ()
    installed = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "PowerShell"
    on_path = (shutil.which("pwsh", path=entry)
               for entry in os.environ.get("PATH", "").split(os.pathsep) if entry)
    return tuple(dict.fromkeys(
        str(p) for p in (*sorted(installed.glob("7*/pwsh.exe")), *filter(None, on_path))))


def _pwsh() -> str | None:
    """PowerShell 7 to run commands with; None where there is none, or only the Store's -
    then Windows PowerShell 5.1 runs them as before.
    shortcut: the Store package (under WindowsApps) is not used - measured 29 Oct, pwsh
    7.6.9: a command's children are not in KOLONİ's job (IsProcessInJob 0) and outlive its
    kill; upgrade when a Store pwsh is measured to keep them in it."""
    return next((p for p in _pwsh_found() if "\\windowsapps\\" not in p.lower()), None)


STORE_PWSH_NOTE = (
    "PowerShell 7 from the Store cannot be used (its commands' child processes escape KOLONİ's "
    "kill): install it with winget install --id Microsoft.PowerShell -e --source winget; until "
    "then commands run in Windows PowerShell 5.1 (Set-Content writes a UTF-8 BOM)")


def store_pwsh_note() -> str | None:
    """Why a pwsh that is there is not the shell, for the Commands settings; None otherwise."""
    return STORE_PWSH_NOTE if _pwsh_found() and not _pwsh() else None


def shell_argv(command: str) -> list[str]:
    if sys.platform == "win32":
        script = f"{_PS_PROLOGUE}{command}{_PS_EPILOGUE}"
        return [_pwsh() or "powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script]
    return ["/bin/sh", "-c", command]


def shell_name() -> str:
    if sys.platform != "win32":
        return "sh"
    return "PowerShell 7" if _pwsh() else "Windows PowerShell"


def shell_writes() -> str:
    """The BOM warning, for the shell that writes one."""
    return "" if _pwsh() else SHELL_WRITES


def copy_python_path(copy: Path, already: str | None) -> str:
    """PYTHONPATH for a command run in a working copy: the copy's own code first. The
    `.venv` it uses is the project's, linked - and a package installed there to be
    edited in place (`pip install -e .`) names the project's folder, not the copy's."""
    first = [str(copy), *([str(copy / "src")] if (copy / "src").is_dir() else [])]
    return os.pathsep.join([*first, *([already] if already else [])])


class ProcessCommand:
    """A running child process whose merged output is read as text."""

    def __init__(self, process: asyncio.subprocess.Process, job: Job | None = None):
        self._process = process
        self._job = job
        self._killed = False

    async def __aiter__(self) -> AsyncIterator[str]:
        assert self._process.stdout is not None
        # Incremental: a multi-byte character may be split across two reads.
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        while chunk := await self._process.stdout.read(CHUNK):
            if text := decoder.decode(chunk):
                yield text
        if tail := decoder.decode(b"", final=True):
            yield tail

    async def wait(self) -> int:
        return await self._process.wait()

    async def kill(self) -> None:
        """End the process and everything it started, even if the shell already exited."""
        if self._killed:
            return
        self._killed = True
        await self._kill_tree()

    async def close(self) -> None:
        """Called once the command is over: nothing it started is left running."""
        await self.kill()

    def start_failure(self, code: int, output: str) -> str | None:
        return None

    async def _kill_tree(self) -> None:
        pid = self._process.pid
        if self._job is not None:
            self._job.terminate()
        elif sys.platform == "win32":
            # No job (Windows refused one): /T reaches the children while the shell lives.
            killer = await asyncio.create_subprocess_exec(
                "taskkill", "/F", "/T", "/PID", str(pid),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            await killer.wait()
        else:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(pid, signal.SIGKILL)


def command_env(passed: str | None = None) -> dict[str, str]:
    """This machine's environment as a program KOLONİ starts gets it: KOLONİ's own settings (a
    model server's key among them) are not its to see, nor a secret variable the user did not
    pass (slice 103) - what it prints is kept."""
    held = set(held_back(os.environ, passed))
    return {k: v for k, v in os.environ.items()
            if not k.upper().startswith("KOLONI_") and k not in held}


class HostExecutor:
    location = "host"

    def __init__(self, pass_env: str | None = None):
        self._pass_env = pass_env  # the secret variables it is given all the same

    async def start(
        self, command_id: str, command: str, cwd: Path, copy: Path | None = None,
        links: dict[str, Path] | None = None, secrets: Mapping[str, str] | None = None,
    ) -> ProcessCommand:
        if not cwd.is_dir():
            raise StartError(f"{cwd} is not a folder")
        # Python programs would otherwise print in the ANSI code page - and leave __pycache__/
        # in the project (live). (What the user gave on a card goes in over what was held back.)
        env = {**command_env(self._pass_env), **(secrets or {}), "PYTHONUTF8": "1",
               "PYTHONDONTWRITEBYTECODE": "1"}
        # Its output is read as UTF-8: the user's own setting is kept only where it is UTF-8 too
        # (utf-8:surrogateescape, say).
        if not env.get("PYTHONIOENCODING", "").lower().startswith(("utf-8", "utf8")):
            env["PYTHONIOENCODING"] = "utf-8"
        # Python buffers what it prints to a pipe: a server's "Serving on ..." never came
        # and its preview waited for an address (B-351). A user's own setting is kept.
        env.setdefault("PYTHONUNBUFFERED", "1")
        if copy is not None:
            env["PYTHONPATH"] = copy_python_path(copy, env.get("PYTHONPATH"))
            # git in a copy never answers with a repository the copies folder is in.
            env["GIT_CEILING_DIRECTORIES"] = copies.ceiling(copy)
        try:
            process = await asyncio.create_subprocess_exec(
                *shell_argv(command),
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                # Its own process group, so the whole tree can be signalled at once.
                # shortcut: on POSIX nothing ends that group if KOLONİ itself is killed (-9,
                # OOM; Windows has its kill-on-close job): a keep_running server lives on
                # (denetim-010 #13). PR_SET_PDEATHSIG reaches only the shell, and needs
                # preexec_fn; a sweep at the next start needs each command's pgid and start
                # time kept (a pgid alone may be the user's own by then). Do the sweep if
                # ghost servers are seen on Linux or macOS.
                start_new_session=sys.platform != "win32",
                **SUSPENDED,
            )
        except OSError as exc:
            raise StartError(f"could not start the shell: {exc.strerror or exc}") from None
        return ProcessCommand(process, _job_for(process))


def _job_for(process: asyncio.subprocess.Process) -> Job | None:
    """Its job, None where there is none; one started SUSPENDED runs from here on, inside it -
    so whoever starts one so calls this at once, with no await between."""
    if sys.platform != "win32":
        return None
    try:
        # asyncio keeps the Popen object, and with it the Windows process handle.
        popen = getattr(process, "_transport").get_extra_info("subprocess")  # noqa: B009
        handle = int(popen._handle)
    except Exception:
        with contextlib.suppress(Exception):
            process.kill()  # (started suspended, nothing here could let it run)
        return None
    try:
        return Job.for_process(handle)
    except Exception:
        return None
    finally:
        if not resume(handle):
            with contextlib.suppress(OSError):
                popen.kill()  # never left suspended: it is seen to end instead
