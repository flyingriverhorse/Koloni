"""What git is given for whatever is started in a working copy's tree (`git_env`), split from
`app.copies` (K-koloni-alan): where it looks for a repository, the hooks it runs (none), and a ☾
Away job's worktree that pushes nothing (H1). `copies` gives each name on as its own.
"""

import contextlib
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from app.workspace import has_other_names

# Beside a copy's tree: an empty folder that git is told holds the hooks (`git_env`).
NO_HOOKS = "no-hooks"


def ceiling(tree: Path) -> str:
    """GIT_CEILING_DIRECTORIES for whatever is started in a copy's tree: git looks for
    a repository no higher than the copies folder - never in one that folder is in."""
    return os.pathsep.join(
        [str(tree.parent.parent), *filter(None, [os.environ.get("GIT_CEILING_DIRECTORIES")])]
    )


def _tree_key(tree: Path) -> str:
    return os.path.normcase(os.path.realpath(tree))


# H1: the trees of ☾ Away jobs on their branch (`no_push`), by `_tree_key` - this process's.
_NO_PUSH: set[str] = set()
# Every push URL starts with "": rewritten to a scheme git has no helper for, it fails; a fetch is
# not rewritten (`pushInsteadOf` is push's alone). Measured with git 2.53 (25 Nov): a push to a
# remote's name, a path and a file:// URL fail; a fetch works.
NO_PUSH = "'url.koloni-no-push://.pushInsteadOf='"


def no_push(tree: Path) -> None:
    """H1: whatever is started in `tree` - a ☾ Away job's worktree - pushes nothing: `git_env`
    adds `NO_PUSH` there. For this process: set again wherever such a tree is opened."""
    _NO_PUSH.add(_tree_key(tree))


def git_env(tree: Path, env: Mapping[str, str]) -> dict[str, str]:
    """What git is given for whatever is started in a copy's tree, `env` being the environment it
    is started with: it looks no higher than the copies folder (`ceiling`), and runs no hook of the
    repository it finds - its hooks folder is an empty one beside the tree (`NO_HOOKS`) -, nor its
    fsmonitor, nor asks for a signature (a key's prompt), after the config `env` gives git already -
    and keeps a branch's reflog, what a pull request's push reads its own commits by
    (`git._made_on`).
    A branch's worktree is the user's own repository: its hooks and settings, and a
    `core.hooksPath` in the tree (husky's), which the agent can write.
    GIT_CONFIG_PARAMETERS, not GIT_CONFIG_COUNT/KEY/VALUE: GIT_CONFIG_KEY_0 is a secret by its
    name (`commands.secret_name`), held back where its count is not - and git stops at a count
    with no key. Not `safe.bareRepository=explicit`, as KOLONİ's own git has it: a project's tests
    that use a bare repository by its folder (`git -C remote.git log`) would fail in a copy
    (measured), and what such a repository's config could run (hooks, fsmonitor) is off here.
    H1, in a ☾ Away job's worktree (`no_push`): no push (`NO_PUSH`), and no prompt for a login.
    shortcut: H1 is no wall - measured with git 2.53, a script of the job's own pushes all the same
    with `git send-pack`, its own `-c url.<x>.pushInsteadOf=...`, a `remote.origin.pushurl` it
    sets first, or this environment replaced (`GIT_CONFIG_PARAMETERS`, `GIT_CONFIG_COUNT`); so
    does a pushurl or a longer pushInsteadOf of the user's. Each such line the agent types itself
    is refused or asked on a card; what a script it runs does is not read. H2 says what moved
    outside the branch in the morning, and the morning's push checks origin itself (H3)."""
    # shortcut: an empty core.hooksPath stops the hooks git finds in a folder, not hooks set in its
    # config (`hook.<name>.command` / `.event`: git 2.53 ran none, probed 21 Nov); turn those off
    # here too once a git that runs them is seen.
    empty = tree.parent / NO_HOOKS
    empty.mkdir(exist_ok=True)
    ours = "'" + f"core.hooksPath={empty}".replace("'", "'\\''") + "'"  # (git's own quoting)
    away = _tree_key(tree) in _NO_PUSH
    return {
        **({"GIT_TERMINAL_PROMPT": "0"} if away else {}),
        "GIT_CEILING_DIRECTORIES": ceiling(tree),
        "GIT_CONFIG_PARAMETERS": " ".join(
            filter(
                None,
                [
                    env.get("GIT_CONFIG_PARAMETERS"),
                    ours,
                    "'core.fsmonitor=false'",
                    "'commit.gpgsign=false'",
                    "'core.logAllRefUpdates=true'",
                    NO_PUSH if away else None,
                ],
            )
        ),
    }


def exclude(project: Path, lines: Sequence[str]) -> None:
    """K-koloni-alan: each of `lines` in the repository's own `info/exclude` - where git reads it
    (`--git-path`: in a linked worktree, the main repository's) - once, its other lines kept, and
    never through a link or over another name of a file elsewhere: git ignores KOLONİ's worktrees
    and copies in `.koloni/` (`copies.EXCLUDED`) with no line in the user's .gitignore. Refused,
    with why, where git does not say where it is or it cannot be written."""
    from app import git  # (here: git's executors import commands, which imports copies)

    exe, _folder = git.repository(project)
    said = git._said_or_refused(project, exe, None, "rev-parse", "--git-path", "info/exclude")
    path = Path(project, said.decode("utf-8", "surrogateescape").strip())
    try:
        # (review: nor where `info/`, or git's folder, is a link or a junction to elsewhere)
        for folder in (path.parent, path.parent.parent):
            real = os.path.join(os.path.realpath(folder.parent), folder.name)
            if os.path.normcase(os.path.realpath(folder)) != os.path.normcase(real):
                raise OSError(f"{folder} is a link, or a junction")
        there = os.path.lexists(path)
        if there and (path.is_symlink() or has_other_names(path)):
            raise OSError("it is a link, or another name of a file elsewhere")
        had = path.read_bytes() if there else b""  # (bytes: what else it holds stays as it is)
        missing = [line.encode() for line in lines if line.encode() not in had.splitlines()]
        if not missing:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        ends = b"" if not had or had.endswith(b"\n") else b"\n"
        temp = path.with_name(f"{path.name}.koloni-tmp")
        temp.unlink(missing_ok=True)  # (never written through one a command left there)
        temp.write_bytes(had + ends + b"".join(line + b"\n" for line in missing))
        os.replace(temp, path)
    except OSError as exc:
        raise git.Refused(f"{path} could not be written: {exc}") from None


def drop_project(project: Path, runtime_root: Path) -> None:
    """K-koloni-alan: a project's record is gone (its delete waited for no work of it to be
    left): this runtime root's worktrees and copies in its `.koloni/` go with it - each as
    `copies.remove` deletes one, its links as links - but a worktree whose note is gone
    (`copies.unread_worktree`) - and git's records of those worktrees; their
    folders too where nothing else is left in them, and it is no longer looked in (`folders`).
    What cannot be deleted stays. The branches stay: they are the repository's."""
    from app import copies, git  # (here: copies imports this; git's executors import commands)

    for area in (copies.WORKTREES, copies.FOLDER):
        held = copies.in_project(project, runtime_root, area)
        if held is None or not held.is_dir():
            continue
        for entry in copies._entries(held):
            with contextlib.suppress(OSError, ValueError):
                if not copies.unread_worktree(Path(entry.path)):
                    copies._remove(Path(entry.path))
                elif not copies._is_link(Path(entry.path)):  # (kept: its links go, as `clear`'s)
                    copies._unlink_links(Path(entry.path))
        for empty in (held, held.parent, held.parent.parent):
            with contextlib.suppress(OSError):
                ignore = (
                    empty / ".gitignore"
                )  # (the area's own, `copies.make`: when it is all left)
                if empty == held.parent and os.listdir(empty) == [ignore.name]:
                    ignore.unlink()
                empty.rmdir()
        if area == copies.WORKTREES:
            with contextlib.suppress(git.Refused, OSError):
                git.forget_worktrees(Path(project), [held], Path(runtime_root) / "no-hooks")
    copies._PROJECTS.get(copies._runtime_key(runtime_root), set()).discard(
        os.path.realpath(project)
    )
