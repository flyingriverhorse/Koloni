"""0.1.0-guncelleme: scripts/update.ps1 and update.sh, run in a throwaway repository of their
own - never this checkout: nothing is pulled or installed here."""

import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from app.config import REPO_ROOT


def _bash() -> str | None:
    if os.name != "nt":
        return shutil.which("bash")
    # Git's own bash: the `bash` on PATH may be WSL's.
    git = shutil.which("git")
    found = [up / "bin" / "bash.exe" for up in Path(git).resolve().parents] if git else []
    return next((str(one) for one in found if one.is_file()), None)


SHELLS = [
    pytest.param(["-NoProfile", "-File", "scripts/update.ps1"], "-DryRun", id="ps1"),
    pytest.param(["scripts/update.sh"], "--dry-run", id="sh"),
]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c",
                    "commit.gpgsign=false", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository holding the two scripts, committed: its tree is clean."""
    root = tmp_path / "koloni"
    (root / "scripts").mkdir(parents=True)
    for name in ("update.ps1", "update.sh"):
        shutil.copy(REPO_ROOT / "scripts" / name, root / "scripts" / name)
    (root / "README.md").write_text("mine\n", encoding="utf-8")
    (root / ".gitignore").write_text("runtime/\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _run(repo: Path, args: list[str], tmp_path: Path, port: int | None = None, *extra: str):
    shell = (shutil.which("pwsh") or shutil.which("powershell")) if args[0] == "-NoProfile" \
        else _bash()
    if shell is None:
        pytest.skip("no such shell here")
    # Never the user's KOLONİ (8790) nor runtime: a port nothing answers on, an empty runtime.
    # (No GIT_DIR or the like a hook set: git would act on that repository, not this one.)
    env = {**{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
           "KOLONI_PORT": str(port or _free_port()),
           "KOLONI_RUNTIME_ROOT": str(tmp_path / "runtime")}
    done = subprocess.run([shell, *args, *extra], cwd=repo, env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=60)
    return done.returncode, done.stdout + done.stderr


def _head(repo: Path) -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True,
                          text=True, check=True).stdout


@pytest.mark.parametrize(("args", "dry"), SHELLS)
def test_the_dry_run_lists_every_step_and_runs_none(repo, tmp_path, args, dry):
    (repo / "README.md").write_text("changed\n", encoding="utf-8")  # (not even refused)
    head = _head(repo)
    code, said = _run(repo, args, tmp_path, None, dry)
    assert code == 0, said
    steps = ["refuse if tracked files have changes", "answers on 127.0.0.1",  # (İ: as the pipe's code page has it)
             "back up the database to", "git pull --ff-only",
             "uv pip sync requirements-dev.lock", "uv pip install --no-deps -e .",
             "npm --prefix frontend ci", "npm --prefix frontend run build",
             "uv pip install -r pyproject.toml --extra docs", "zensical build", "a failure only warns"]
    at = [said.find(step) for step in steps]
    assert -1 not in at and at == sorted(at), said
    assert "Updated to" not in said
    assert _head(repo) == head and not (tmp_path / "runtime").exists()


@pytest.mark.parametrize(("args", "dry"), SHELLS)
def test_changed_tracked_files_are_refused_untracked_ones_are_not(repo, tmp_path, args, dry):
    (repo / "notes.txt").write_text("untracked\n", encoding="utf-8")
    code, said = _run(repo, args, tmp_path)
    # Past the check: no database to back up, and no upstream to pull from - that step stops it.
    assert code == 1 and "git pull --ff-only failed - stopped" in said, said
    assert "uv pip sync" not in said
    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    code, said = _run(repo, args, tmp_path)
    assert code == 1 and "uncommitted changes" in said and "README.md" in said, said
    assert "git pull" not in said


@pytest.mark.parametrize(("args", "dry"), SHELLS)
def test_it_refuses_while_something_answers_on_kolonis_port(repo, tmp_path, args, dry):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        code, said = _run(repo, args, tmp_path, port)
    assert code == 1 and f"something answers on 127.0.0.1:{port}" in said, said
    assert "git pull" not in said and not (tmp_path / "runtime").exists()


def _link(target: Path, at: Path) -> None:
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(at))
    else:
        os.symlink(target, at)


@pytest.mark.parametrize(("args", "dry"), SHELLS)
def test_a_linked_working_copy_is_refused_before_any_step(repo, tmp_path, args, dry):
    elsewhere = tmp_path / "main-venv"
    elsewhere.mkdir()
    (elsewhere / "keep.txt").write_text("main's", encoding="utf-8")
    for at in (repo / ".venv", repo / "frontend" / "node_modules"):
        at.parent.mkdir(exist_ok=True)
        _link(elsewhere, at)
        code, said = _run(repo, args, tmp_path)
        assert code == 1 and "this is a linked working copy" in said, said
        assert "==" not in said
        os.rmdir(at) if os.name == "nt" else os.unlink(at)  # (the link itself)
    assert (elsewhere / "keep.txt").read_text(encoding="utf-8") == "main's"
    worktree = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", str(worktree))
    code, said = _run(worktree, args, tmp_path, None, dry)  # (even a dry run)
    assert code == 1 and "this is a linked working copy" in said, said


@pytest.mark.parametrize(("args", "dry"), SHELLS)
def test_a_guide_that_cannot_be_rebuilt_only_warns_and_the_update_ends_as_usual(
        repo, tmp_path, args, dry, monkeypatch):
    """Every step a stand-in that passes, but the docs extra's install fails (no network, say)."""
    if args[0] == "-NoProfile" and sys.platform != "win32":
        pytest.skip("its stand-ins are .cmd files, which pwsh runs only on Windows")
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(repo), str(work))  # (an upstream: the pull passes)
    tools = tmp_path / "tools"
    tools.mkdir()
    if args[0] == "-NoProfile":
        (work / ".venv" / "Scripts").mkdir(parents=True)
        (work / ".venv" / "Scripts" / "zensical.exe").write_bytes(b"")  # (installed: looked at)
        (tools / "uv.cmd").write_text(
            '@echo %* | findstr /c:"--extra" >nul && exit /b 1\n@exit /b 0\n', encoding="utf-8")
        (tools / "npm.cmd").write_text("@exit /b 0\n", encoding="utf-8")
    else:
        (work / ".venv" / "bin").mkdir(parents=True)
        for path, body in ((work / ".venv" / "bin" / "zensical", "exit 0"),
                           (tools / "uv", 'case "$*" in *--extra*) exit 1;; esac'),
                           (tools / "npm", "exit 0")):
            path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8", newline="\n")
            path.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tools}{os.pathsep}{os.environ['PATH']}")
    code, said = _run(work, args, tmp_path)
    assert code == 0, said
    assert "the guide was not rebuilt" in said and "Updated to" in said, said


@pytest.mark.parametrize(("args", "dry"), SHELLS)
def test_a_folder_that_is_no_git_checkout_is_said_so_and_stops(tmp_path, args, dry):
    # B-340 (live): a copy made with git archive printed "fatal: not a git repository" and went on.
    copy = tmp_path / "copy"
    (copy / "scripts").mkdir(parents=True)
    for name in ("update.ps1", "update.sh"):
        shutil.copy(REPO_ROOT / "scripts" / name, copy / "scripts" / name)
    code, said = _run(copy, args, tmp_path, None, dry)
    assert code == 1 and "this folder is not a git checkout" in said, said
    assert "fatal" not in said and "==" not in said
