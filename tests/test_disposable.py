"""Disposable deletes (coordination §4): a delete KOLONİ can check by itself - a plain line's build
or cache folder, a clean worktree, a merged branch - may go without a card where the user allowed
it in the project. First what a line could delete: anything else on the line, any form not read
here, is no such delete."""

import pytest

from app.commands import disposable_targets


@pytest.mark.parametrize(("line", "targets"), [
    ("rm -rf build", [("folder", "build", True)]),
    ("Remove-Item -Recurse -Force dist", [("folder", "dist", True)]),
    ("rm -r build dist", [("folder", "build", False), ("folder", "dist", False)]),
    ("rm -R frontend/dist", [("folder", "frontend/dist", False)]),
    ("Remove-Item -LiteralPath .pytest_cache -Recurse", [("folder", ".pytest_cache", False)]),
    ("git worktree remove ../wt/x", [("worktree", "../wt/x", False)]),
    ("git worktree remove /tmp/wt/x", [("worktree", "/tmp/wt/x", False)]),
    ("git branch -d old", [("branch", "old", False)]),
    ("git branch -D a b", [("branch", "a", True), ("branch", "b", True)]),
    ("git branch -d feature/v1.2", [("branch", "feature/v1.2", False)]),
])
def test_a_plain_line_names_what_it_would_delete(line, targets):
    assert disposable_targets(line) == targets


@pytest.mark.parametrize("line", [
    # (the plan's)
    "rm -rf build && x", "rm -rf ../build", "rm -rf /tmp/build", "rm -rf src", "rm -rf build/*",
    "rm -rf .git/build", "rm -rf node_modules/x/build", "rmdir /s /q build", "cmd /c rd /s build",
    "git worktree remove -f x", "git -C x branch -d y", "git branch -d",
    "git push origin --delete x",
    # A folder: recursive, by a bare deleter, flags it knows, each path one of the names, plainly
    # below where it runs - no dot-part above it, no linked folder, no name Windows reads as
    # another (`node_modules.`), no trailing slash (`build/` is where a link leads).
    "rm -f build", "rm build", "rm -rf", "rm -rf -- build", "rm -rf build/", "rm -rf ./build",
    "rm -rf a//build", "rm -rf Build", "rm -rf build.", "rm -rf NODE_MODULES/build",
    "rm -rf node_modules./build", "rm -rf .venv/build", "rm -rf venv/dist", "rm -rf build src",
    "rm.exe -rf build", "/bin/rm -rf build", "Remove-Item -Rec build", "rm -rfv build",
    "rm -rf --no-preserve-root build", "unlink build", "rmdir build", "rd build",
    # Nothing a shell reads past a plain word: a quote, a backslash, a drive, a comment, a
    # splat, a variable, a tab or another space.
    "rm -rf 'build'", "rm -rf a\\build", "rm -rf C:build", "Remove-Item -Recurse -Path:build",
    "rm -rf build #x", "Remove-Item -Recurse @p", "rm -rf $x/build", "rm\t-rf build",
    "rm -rf\u00a0build", "rm -rf build\u000bx", "rm -rf ~/build", "rm -rf build; ls",
    "rm  -rf build", " rm -rf build", "Remove-Item –Recurse build",
    # A worktree: exactly `git worktree remove <path>`.
    "git worktree remove --force x", "git worktree remove x y", "git worktree remove",
    "git worktree remove ../wt/.x", "git worktree remove .git/worktrees/x",
    "git worktree remove node_modules/x", "git worktree remove C:/wt/x",
    "git worktree remove ..\\wt\\x", "git worktree remove -- x", "git worktree prune",
    "git worktree remove ../wt/x/", "git worktree remove wt./x",
    # A branch: exactly `git branch -d|-D <name>...`, none KOLONİ's own.
    "git branch -d koloni/x", "git branch -D Koloni/x", "git branch -d -f x",
    "git branch --delete x", "git branch -dr x", "git branch -d -r origin/x",
    "git branch -d .x", "git branch -d a/.b", "git branch -d x.", "git branch -d x -D y",
    "git branch x", "git branch -m a b", "GIT branch -d x", "git.exe branch -d x",
    "git branch -d @{-1}", "git branch -d x:y", "git branch -d -- x",
])
def test_anything_else_is_no_disposable_delete(line):
    assert disposable_targets(line) is None
