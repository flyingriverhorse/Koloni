"""The host executor against real processes."""

import asyncio
import os
import subprocess
import sys
import time

import pytest

from app.executors import host
from app.executors.base import StartError
from app.executors.host import HostExecutor

pytestmark = pytest.mark.anyio


_counter = iter(range(1000))


_real_pwsh = host._pwsh


@pytest.fixture(autouse=True, params=["powershell.exe", "pwsh"] if sys.platform == "win32" else ["sh"])
def shell(request, monkeypatch):
    """Every test under each shell KOLONİ may pick (K-pwsh): 5.1 always, 7 where it is
    installed (not the Store's)."""
    pwsh = _real_pwsh()
    if request.param == "pwsh" and not pwsh:
        pytest.skip("PowerShell 7 is not installed (or only from the Store)")
    monkeypatch.setattr(host, "_pwsh", lambda: pwsh if request.param == "pwsh" else None)
    return request.param


STORE = r"C:\Users\u\AppData\Local\Microsoft\WindowsApps\pwsh.exe"
MSI = r"C:\Program Files\PowerShell\7\pwsh.exe"


@pytest.mark.parametrize(("found", "used"), [
    ((), None), ((STORE,), None), ((MSI,), MSI), ((STORE, MSI), MSI)])
def test_only_an_installed_pwsh_is_used_and_the_stores_alone_is_explained(monkeypatch, found,
                                                                           used):
    monkeypatch.setattr(host, "_pwsh_found", lambda: found)
    monkeypatch.setattr(host, "_pwsh", _real_pwsh)
    assert host._pwsh() == used
    assert (host.store_pwsh_note() == host.STORE_PWSH_NOTE) == (found == (STORE,))
    assert host.store_pwsh_note() is None or "winget install" in host.store_pwsh_note()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows installs")
def test_an_install_is_found_before_the_store_alias_on_path(monkeypatch, tmp_path):
    # the alias folder first on PATH, as a process started before the install has it
    (tmp_path / "PowerShell" / "7").mkdir(parents=True)
    (tmp_path / "PowerShell" / "7" / "pwsh.exe").write_bytes(b"")
    (tmp_path / "WindowsApps").mkdir()
    (tmp_path / "WindowsApps" / "pwsh.exe").write_bytes(b"")
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path / "WindowsApps"))
    monkeypatch.setattr(host, "_pwsh_found", host._pwsh_found.__wrapped__)
    assert [p.lower() for p in host._pwsh_found()] == [
        str(tmp_path / "PowerShell" / "7" / "pwsh.exe").lower(),
        str(tmp_path / "WindowsApps" / "pwsh.exe").lower()]  # (`which` names it pwsh.EXE)


def test_the_shell_found_is_named_and_handed_the_same_script(shell):
    argv = host.shell_argv("echo hi")
    if sys.platform != "win32":
        assert argv == ["/bin/sh", "-c", "echo hi"] and host.shell_name() == "sh"
        assert host.shell_writes() == ""
        return
    assert argv[0] == (_real_pwsh() if shell == "pwsh" else "powershell.exe")
    assert argv[1:] == ["-NoProfile", "-NonInteractive", "-Command",
                        f"{host._PS_PROLOGUE}echo hi{host._PS_EPILOGUE}"]
    assert host.shell_name() == ("PowerShell 7" if shell == "pwsh" else "Windows PowerShell")
    # the agent is warned of the BOM only where one is written
    assert ("BOM" in host.shell_writes()) == (shell == "powershell.exe")


def py(code: str, folder) -> str:
    """A shell command that runs Python code from a script file in `folder`.

    A file avoids quoting the code for the shell: Windows PowerShell drops inner
    double quotes when it passes arguments to a program.
    """
    script = folder / f"_script{next(_counter)}.py"
    script.write_text(code, encoding="utf-8")
    call = "& " if sys.platform == "win32" else ""
    return f"{call}'{sys.executable}' '{script}'"


async def run(command: str, cwd, timeout: float = 20):
    running = await HostExecutor().start("cmd1", command, cwd)

    async def drain():
        return "".join([chunk async for chunk in running])

    output, code = await asyncio.wait_for(asyncio.gather(drain(), running.wait()), timeout)
    return output, code


def alive(pid: int) -> bool:
    if sys.platform == "win32":
        listing = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True
        ).stdout
        return str(pid) in listing
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


async def test_output_and_exit_code(tmp_path):
    output, code = await run(
        py("import sys; print('out'); sys.stderr.write('err'); sys.exit(3)", tmp_path), tmp_path)
    assert "out" in output and "err" in output
    assert code == 3


async def test_runs_in_the_given_folder(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    output, _ = await run(py("import os; print(os.getcwd())", tmp_path), sub)
    assert os.path.normcase(output.strip()) == os.path.normcase(str(sub))


async def test_kolonis_own_settings_are_not_a_commands_to_see(tmp_path, monkeypatch):
    monkeypatch.setenv("KOLONI_MODEL_API_KEY", "sk-koloni-secret")
    monkeypatch.setenv("NOT_KOLONIS", "the-users-own")
    output, _ = await run(py(
        "import os; print(sorted(k for k in os.environ if k.upper().startswith('KOLONI_')), "
        "os.environ['NOT_KOLONIS'], os.environ['PYTHONUTF8'], os.environ['PYTHONDONTWRITEBYTECODE'])",
        tmp_path), tmp_path)
    # (Live: agents' Python left __pycache__/ in the project after Take in.)
    assert output.strip() == "[] the-users-own 1 1"


@pytest.mark.parametrize(("users", "seen"), [
    ("cp1254", "utf-8"), ("utf-8:surrogateescape", "utf-8:surrogateescape")])
async def test_python_prints_utf8_keeping_only_a_users_utf8_setting(tmp_path, monkeypatch,
                                                                     users, seen):
    monkeypatch.setenv("PYTHONIOENCODING", users)
    output, _ = await run(py("import os; print(os.environ['PYTHONIOENCODING'])", tmp_path),
                          tmp_path)
    assert output.strip() == seen


@pytest.mark.parametrize(("users", "seen"), [(None, "1"), ("0", "0")])
async def test_python_prints_unbuffered_unless_the_user_said_otherwise(tmp_path, monkeypatch,
                                                                       users, seen):
    # B-351: a server's address, printed without flush, must reach the pipe at once.
    if users is None:
        monkeypatch.delenv("PYTHONUNBUFFERED", raising=False)
    else:
        monkeypatch.setenv("PYTHONUNBUFFERED", users)
    output, _ = await run(py("import os; print(os.environ['PYTHONUNBUFFERED'])", tmp_path),
                          tmp_path)
    assert output.strip() == seen


async def test_stdin_is_closed(tmp_path):
    output, code = await run(py("import sys; print(repr(sys.stdin.read()))", tmp_path), tmp_path)
    assert output.strip() == "''" and code == 0


async def test_kill_takes_the_whole_process_tree(tmp_path):
    child = "import time; time.sleep(60)"
    parent = (
        "import subprocess, sys, time; "
        f"p = subprocess.Popen([sys.executable, '-c', '{child}']); "
        "print(p.pid, flush=True); time.sleep(60)"
    )
    running = await HostExecutor().start("cmd1", py(parent, tmp_path), tmp_path)
    first = await asyncio.wait_for(anext(aiter(running)), 15)
    child_pid = int(first.split()[0])
    assert alive(child_pid)

    await running.kill()
    await asyncio.wait_for(running.wait(), 10)
    deadline = time.monotonic() + 5
    while alive(child_pid) and time.monotonic() < deadline:
        await asyncio.sleep(0.1)
    assert not alive(child_pid)
    await running.kill()  # a second kill is harmless


async def test_a_flood_of_output_is_drained_not_blocked(tmp_path):
    output, code = await run(py("import sys; sys.stdout.write('x' * 5_000_000)", tmp_path), tmp_path, 30)
    assert code == 0 and len(output) >= 5_000_000


async def test_undecodable_bytes_do_not_break_the_stream(tmp_path):
    output, code = await run(
        py("import sys; sys.stdout.buffer.write(bytes([255, 254]) + b'ok')", tmp_path), tmp_path)
    assert "ok" in output and code == 0


async def test_a_multibyte_character_split_across_reads_is_kept(tmp_path):
    # 4095 ASCII bytes put the two-byte "ş" across the 4096-byte read boundary.
    code_text = (
        "import sys; sys.stdout.buffer.write(b\"a\" * 4095 + \"\\u015f\".encode() + b\"z\")"
    )
    output, _ = await run(py(code_text, tmp_path), tmp_path)
    assert output == "a" * 4095 + "ş" + "z"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell 5.1's own defaults")
async def test_powershell_reads_and_rewrites_a_utf8_file_without_garbling_it(tmp_path, shell):
    # B-324: Get-Content read a file without a BOM in the ANSI code page ("KÃ¼Ã§Ã¼k")
    (tmp_path / "r.md").write_bytes("Küçük bir ev fiyatı\n".encode())
    output, code = await run("Get-Content r.md", tmp_path)
    assert code == 0 and output.strip() == "Küçük bir ev fiyatı"
    # read right and written back: no letter is lost on the way (UTF-8 writes a BOM in 5.1)
    _, code = await run("(Get-Content r.md) -replace 'ev','oda' | Set-Content r.md", tmp_path)
    assert code == 0
    written = (tmp_path / "r.md").read_bytes()
    assert written.decode("utf-8-sig").strip() == "Küçük bir oda fiyatı"
    # K-pwsh: PowerShell 7 writes none (measured), which is what the agent is told
    assert written.startswith(b"\xef\xbb\xbf") == (shell == "powershell.exe")


async def test_a_missing_folder_is_a_start_error(tmp_path):
    with pytest.raises(StartError, match="is not a folder"):
        await HostExecutor().start("cmd1", "echo hi", tmp_path / "nope")


async def test_a_shell_builtin_reports_success_and_failure(tmp_path):
    _, ok = await run("echo hi", tmp_path)
    assert ok == 0
    missing = "Get-Item ./no-such-file" if sys.platform == "win32" else "ls ./no-such-file"
    output, failed = await run(missing, tmp_path)
    assert failed != 0 and "no-such-file" in output
    assert "\x1b" not in output  # PowerShell 7 would colour the error (K-pwsh)


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell's object output")
async def test_objects_left_on_the_pipeline_are_printed_as_text(tmp_path):
    # K-ps-nesne (R116): `gci | select name` printed nothing - the table formatter held the
    # rows until the script's end, and the epilogue's `exit` came first
    (tmp_path / "alpha.txt").write_text("a")
    (tmp_path / "beta.txt").write_text("b")
    output, code = await run("gci | select name", tmp_path)
    assert code == 0 and "alpha.txt" in output and "beta.txt" in output
    # the listing still comes out when a later program fails, and its exit code is kept
    output, code = await run("gci | select name; cmd /c exit 3", tmp_path)
    assert code == 3 and "alpha.txt" in output
    # a command that ends in a top-level `return` leaves the block early and still exits 0
    output, code = await run("echo hi; return", tmp_path)
    assert code == 0 and output.strip() == "hi"
