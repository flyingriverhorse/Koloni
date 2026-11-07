"""K-posix review: what an agent could reach on Linux and WSL - KOLONİ's own environment through
/proc, the system's live folders a message names, Windows' homes under /mnt - a hook put back
as runnable as it was, and secrets by a dotted name."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app import raw, workspace
from app.agent import _restore
from app.commands import names_secret
from app.config import REPO_ROOT
from app.project_view import standing
from app.workspace import WorkspaceError, listed_folder, named_folders, never, secret_in_project

LINUX = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux's /proc")
POSIX = pytest.mark.skipif(os.name == "nt", reason="Linux's and macOS's paths")
HOME = Path(os.path.expanduser("~"))

PROBE = """
import os, subprocess
from app.main import not_dumpable
def parent():
    return subprocess.run(["cat", f"/proc/{os.getpid()}/environ"], capture_output=True)
before = parent()
not_dumpable()
after = parent()
own = subprocess.run(["sh", "-c", "cat /proc/self/environ"], capture_output=True)
mark = b"KOLONI_PROBE=sk-probe"
print(mark in before.stdout, after.returncode != 0 and mark not in after.stdout,
      mark in own.stdout)
"""


@LINUX
def test_a_child_cannot_read_kolonis_environment_once_it_is_started():
    done = subprocess.run([sys.executable, "-c", PROBE], cwd=REPO_ROOT, capture_output=True,
                          text=True, env={**os.environ, "KOLONI_PROBE": "sk-probe"}, timeout=60)
    # (read before, refused after - and a child's own environment is still its own)
    assert done.stdout.split() == ["True", "True", "True"], done.stderr


def test_the_pages_key_is_hidden_as_every_secret_kolonis_knows(make_client):
    client, _model = make_client([])
    key = client.app.state.page_key
    raw.read_again()
    assert raw.hidden(f"KOLONI_PAGE_KEY={key}") == f"KOLONI_PAGE_KEY={raw.HIDDEN}"


@POSIX
def test_the_systems_live_folders_are_never_opened_by_a_message():
    for path in ("/dev/null", "/dev/shm", "/run/user/1000", "/var/run/docker.sock", "/boot",
                 "/proc/self/environ", "/sys/kernel"):
        assert never(Path(path)), path
    with pytest.raises(WorkspaceError, match="never opened"):
        listed_folder("/var")  # (it holds /var/run)
    assert named_folders("make test 2>/dev/null; ls /dev/shm /run/user/1000 /var/run /boot") == []


@pytest.fixture
def wsl(tmp_path, monkeypatch):
    drives = tmp_path / "mnt"
    me = drives / "c" / "Users" / "me"
    for folder in (".claude", ".ssh", "AppData/Local", "work"):
        (me / folder).mkdir(parents=True)
    (drives / "d" / "data").mkdir(parents=True)
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    monkeypatch.setattr(workspace, "WSL_DRIVES", drives)
    workspace._places.cache_clear()
    yield drives
    workspace._places.cache_clear()


@POSIX
def test_under_wsl_windows_drives_and_homes_are_refused_as_on_windows(wsl):
    me = wsl / "c" / "Users" / "me"
    for refused in (wsl / "c", wsl / "d", me):
        with pytest.raises(WorkspaceError, match="never opened"):
            listed_folder(str(refused))
    assert never(wsl / "d") == "it is a drive's root"
    for inside in (me / ".ssh" / "id_ed25519", me / "AppData" / "Local" / "x", me / ".codex"):
        assert never(inside), inside
    # what the user keeps there is theirs to name
    assert listed_folder(str(me / "work")) == me / "work"
    assert listed_folder(str(wsl / "d" / "data")) == wsl / "d" / "data"


@POSIX
def test_under_wsl_a_windows_home_is_kept_in_any_case_and_as_a_linux_home_is(wsl):
    for spelled in ("c/users/me", "c/Users/me/appdata", "c/users/me/.ssh", "c/Users/me/.CLAUDE",
                    "c/USERS/me/AppData/Local", "c/Users/ME/.Ollama"):
        with pytest.raises(WorkspaceError, match="never opened"):
            listed_folder(str(wsl / spelled))
        assert spelled == "c/users/me" or never(wsl / spelled), spelled
    for name in (".qoder", ".ollama", ".kaggle", ".docker", ".config/gcloud"):
        assert never(wsl / "c" / "Users" / "me" / name / "x"), name


@pytest.mark.skipif(sys.platform != "linux", reason="WSL is Linux")
def test_wsl_started_by_systemd_is_told_by_its_interop(wsl, monkeypatch):
    monkeypatch.delenv("WSL_DISTRO_NAME")
    monkeypatch.setattr(workspace, "_interop", lambda: True)
    workspace._places.cache_clear()
    assert never(wsl / "d") == "it is a drive's root"
    monkeypatch.setattr(workspace, "_interop", lambda: False)
    workspace._places.cache_clear()
    assert never(wsl / "d") is None


@POSIX
def test_a_hook_put_back_is_as_runnable_as_it_was(tmp_path):
    hook = tmp_path / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True)
    hook.write_bytes(b"#!/bin/sh\nexit 0\n")
    hook.chmod(0o755)
    standing(tmp_path)  # (the look before the agent's command)
    hook.write_bytes(b"#!/bin/sh\necho pwned\n")
    hook.chmod(0o644)
    assert _restore(tmp_path, ".git/hooks/pre-commit", b"#!/bin/sh\nexit 0\n") is None
    assert hook.stat().st_mode & 0o777 == 0o755
    assert _restore(tmp_path, ".git/hooks/pre-commit", b"never seen\n") is None
    assert hook.stat().st_mode & 0o777 == 0o600  # (a version never seen is runnable by nobody)
    # an agent's chmod +x of the same bytes is not how it was
    hook.write_bytes(b"exit 1\n")
    hook.chmod(0o644)
    standing(tmp_path)
    hook.chmod(0o755)
    standing(tmp_path)
    assert _restore(tmp_path, ".git/hooks/pre-commit", b"exit 1\n") is None
    assert hook.stat().st_mode & 0o777 == 0o644


def test_a_credentials_file_is_a_secret_with_its_dot_or_without():
    for command in ("cat ~/.claude/.credentials.json", "cat ~/.config/x/credentials.json"):
        assert names_secret(command), command
    assert secret_in_project(".credentials.json")
    for tool in ("gcloud", "github-copilot", "rclone", "gh"):
        assert never(HOME / ".config" / tool / "x"), tool
