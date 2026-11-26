"""☾ Away, a job on its own branch (0.1.9): where the project is a git repository, a job works on a
branch of its own, `koloni/<task>`, in a worktree of the project's repository, and commits there;
KOLONİ commits what is left at its end and keeps the worktree for the user's Take in - and, where
the project has an `origin`, its push waits for the user's Run in the morning (Waiting for you):
one commit by KOLONİ (`git.push_one`), a pull request where the project's `finish_way` says so.
Nothing goes into the project without the user's Take in (or their own `git merge`).

What is here only reads: which way a job works (`mode_of`), whether a line pushes (`pushes`),
the repository's refs before and after a job (`refs`, `moved`: H2) and the morning's row of it
(`row`). Every word here is KOLONİ's."""

import contextlib
import hashlib
import os
import re
import unicodedata
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import git, raw, secret_set
from app.commands import _TOKENS, _commands_in, _git_sub, _program
from app.db.models import Agent, Run

# The job's first message ends with this where it works on its branch (`backlog.first_message`).
AWAY_BRANCH_JOB = (
    "The user is away (☾ Away): this is a task of their To-do list, worked through while they "
    "are away. It works on a git branch of its own, {branch}, in a worktree of the project's "
    "repository: commit there as you go (git add, git commit). Do not push: KOLONİ pushes this "
    "branch when the user says yes. Nothing of it goes into the project meanwhile - the user "
    "takes it in when back. Only the files git tracks are here; what git ignores (.env, data, "
    "build output) is read in the project. What needs the user's word waits for them, and this "
    "job waits with it while the next one goes on: decide what you can yourself, and end with a "
    "short report. Where the job needs what is not here, change nothing and end your report "
    "with the line `Needs the project itself: <what is not here>`: it then waits for the user."
)
# A CLI's git section in such a job (`git_prompt`'s place).
AWAY_GIT = (
    "Git: you work on the branch {branch}, in a worktree of the project's repository. Commit "
    "there as you go; do not push, switch branches or merge - KOLONİ pushes this branch when the "
    "user says yes."
)
# What an agent's own `git push` there is answered (no card: the morning asks it once).
PUSH_REFUSED = "KOLONİ pushes this branch when the user says yes: go on"
# Where the job could not be put on its branch after all, as it starts.
NOT_ON_BRANCH_NOW = "KOLONİ: this job works in a copy, not on a branch: {why}."
NO_GIT_NOW = "the project is not a git repository now"
# Why a job works in a copy where git is there (`mode_of`).
SUBMODULE = "the project has a git submodule, which a worktree does not fill"
LFS = "the project keeps files in Git LFS, whose filter a worktree is checked out without"
# H2: what moved in the repository outside the job's branch while it worked.
MOVED = "Changed outside its branch: {ref} {old} → {new}"
MOVED_ALL = {
    "tags": "tags",
    "remotes": "remote-tracking branches",
    # (every other ref: replace objects, notes, a namespace of anyone's)
    "other": "other refs (replace objects, notes, ...)",
    "stash-list": "the stash list",
    "git-files": "git's own files (info/attributes, info/exclude, info/grafts, alternates)",
}
CONFIG_MOVED = "git's config changed during the job"
HOOKS_MOVED = "git's hooks changed during the job"
# What of git's folder changes how the repository is read, beside its config and hooks (H2).
GIT_FILES = ("info/attributes", "info/exclude", "info/grafts", "objects/info/alternates")
MOST_MOVED = 10
# The morning's row of a job's push (Waiting for you, `parked.KINDS["push"]`).
PUSH_LINE = (
    "Push {name} to origin ({origin}) — one commit by KOLONİ, {files} files · checks {mark} "
    "at {tip7}"
)
PUSH_PR = " · opens a pull request into {into}"
PUSH_LEFT = " · left out: {files} (a secret KOLONİ knows, or named as one)"  # (HIGH-1, W-1)
PUSH_WHY = "A push leaves this machine: nothing goes up before you say so"
MARKS = {"green": "✓", "red": "✗"}


def mode_of(project: Path) -> tuple[str, str | None]:
    """How a job works on the project, and why not on a branch: "copy" (no git - why None -, a
    folder of a repository, HEAD on no branch, no commit, a merge under way, a submodule, Git
    LFS), "branch" (a repository with no `origin`: a branch, its commits, no push) or "push" (and
    the morning's push to `origin`). Only reads, running no program the repository names."""
    if not any(os.path.lexists(one / ".git") for one in (project, *project.parents)):
        return "copy", None
    try:
        exe, _folder, _on = git._on_a_branch(project)
        if why := _not_for_a_worktree(project, exe):
            return "copy", why
        return ("push" if git._origin(project) else "branch"), None
    except git.Refused as exc:  # (git refused, or did not answer in time)
        return "copy", str(exc)


def _not_for_a_worktree(project: Path, exe: str) -> str | None:
    """Why a worktree of the project would not hold what its tests read: a submodule (`.gitmodules`,
    a gitlink), or files kept in Git LFS (a `filter=lfs` in a `.gitattributes` git tracks)."""
    if os.path.lexists(project / ".gitmodules"):
        return SUBMODULE
    code, out, _said = git._in(
        project,
        exe,
        *git.UNASKED,
        "ls-files",
        "-z",
        "-s",
        seconds=git.SHORT_SECONDS,
        **git.UNASKED_ENV,
    )
    entries = (
        [one for one in out.decode("utf-8", "replace").split("\0") if one] if code == 0 else []
    )
    if any(one.startswith("160000 ") for one in entries):
        return SUBMODULE
    for one in entries:
        path = one.split("\t", 1)[-1]
        if (path == ".lfsconfig" or path.rsplit("/", 1)[-1] == ".gitattributes") and _lfs(
            project / path
        ):
            return LFS
    return None


def _lfs(path: Path) -> bool:
    try:
        return path.name == ".lfsconfig" or b"filter=lfs" in path.read_bytes()[: 1 << 20]
    except OSError:
        return False


def pushes(command: str) -> bool:
    """Whether a line runs `git push` - in any of its parts, and in what a shell or a wrapper is
    handed (`bash -c`, `cmd /c`), as `git -C . push` or git's own `git-push`. A line too deep to
    read is not (its card asks it: `reaches_shared_git`)."""
    return any(
        words and (_program(words[0]) == "git-push" or _git_sub(words)[0] == "push")
        for words in _commands_in(command)
    )


def refs(project: Path) -> dict[str, str] | None:
    """H2: the repository's refs as they are - each branch and the stash by its commit, the
    project's HEAD (the branch it is on, or its commit); the tags, the remote-tracking branches
    and every other ref (replace objects, notes, any namespace) each as one digest; the stash's
    whole list (a drop of an older one); and git's own files that change how the repository is
    read (`GIT_FILES`). None where git does not answer."""
    try:
        exe, folder = git.repository(project)
    except git.Refused:
        return None
    code, out, _said = git._in(
        project,
        exe,
        *git.UNASKED,
        "for-each-ref",
        "--format=%(objectname) %(refname)",
        seconds=git.SHORT_SECONDS,
        **git.UNASKED_ENV,
    )
    if code != 0:
        return None
    found: dict[str, str] = {}
    digests = {kind: hashlib.sha256() for kind in MOVED_ALL}
    for line in out.decode("utf-8", "replace").splitlines():
        sha, _, ref = line.partition(" ")
        kind = ref.split("/")[1] if ref.count("/") >= 2 else ""
        if ref.startswith("refs/heads/") or ref == "refs/stash":
            found[ref] = sha
        else:
            group = kind if kind in ("tags", "remotes") else "other"
            digests[group].update(f"{ref} {sha}\n".encode())
    stashes = git._in(project, exe, "reflog", "show", "--format=%H", "refs/stash")[1]
    digests["stash-list"].update(stashes)
    for name in GIT_FILES:
        with contextlib.suppress(OSError):
            digests["git-files"].update(name.encode() + b"\0" + (folder / name).read_bytes())
    code, out, _said = git._in(project, exe, "symbolic-ref", "-q", "HEAD")
    if code != 0:
        code, out, _said = git._in(project, exe, "rev-parse", "-q", "--verify", "HEAD")
    found["HEAD"] = out.decode("utf-8", "replace").strip() if code == 0 else ""
    return found | {kind: digest.hexdigest() for kind, digest in digests.items()}


def origin_checked(project: Path) -> None:
    """HIGH-1: origin, where a push goes, answers what it holds - at one address git does not
    rewrite (`git._origin_holds`): what is unpushed is then counted against origin itself, never
    a remote-tracking ref of the repository's. Refused where not, or with no such address."""
    url = git.push_address(project)
    if not url:
        raise git.Refused(git.NO_ADDRESS)
    exe, _folder = git.repository(project)
    git._origin_holds(project, exe, url)


# R2: an @ that would mention someone on GitHub (`@octocat`, `@org/team`).
_MENTION = re.compile(r"@(?=[\w-])")


def titled(text: str, secrets: Iterable[str] = ()) -> str:
    """R2: a To-do task's line - which an agent may have written (the Scout) - as a commit's subject
    or a pull request's title says it: no control or format character (a line break, a bidi
    override), each of `secrets` masked, and any secret by its shape alone (`secret_set.parts`: a
    `ghp_…` token, an address's password) - before the joiner could split one - and a zero-width
    joiner after each `@` that would mention someone and before each issue's number a closing
    keyword would close (`Fixes #12`, `Fixes GH-9`, an issue's link: L-3). The rest as written: a
    link's or code's marks there are only text."""
    shown = "".join(ch for ch in text if unicodedata.category(ch) not in ("Cc", "Cf"))
    # (`_TOKENS` has no group: `findall` gives each whole token)
    for one in [*secrets, *secret_set.parts(shown), *_TOKENS.findall(shown)]:
        shown = shown.replace(one, "***") if one else shown
    return _MENTION.sub("@\u200d", _CLOSES.sub("\\1\u200d", shown))


# L-3: a closing keyword before an issue's number (`Fixes #12`, `closes owner/repo#3`, `Fixes GH-9`,
# `fixes https://github.com/o/r/issues/8`), which GitHub acts on from a commit's message or a pull
# request's words - after no letter or digit (`_fixes #10`), its space perhaps gone (a tab dropped).
_CLOSES = re.compile(
    r"(?i)(?<![^\W_])((?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b[\s:]*"
    r"(?:(?:[\w.-]+/[\w.-]+)?#|gh-|https?://\S+?/issues/))(?=\d)"
)
# D2's team pull request: its body (`AgentRunner._pull_request`). What an agent wrote - its task's
# name, the files' names, the check, its notes, the role's name - goes in fenced (`fenced`, L-3): no
# @mention, closing keyword or link of it is read by GitHub.
TEAM_PR_BODY = (
    "{task}\n\nMade by KOLONİ's agents ({name}) on the branch `{branch}`, pushed as one "
    "commit.\n\n### Changed files\n{files}\n\n### Check\n{check}\n\n"
    "### {name}'s notes\n{notes}\n"
)
TEAM_PR_NOTES = 4000


def fenced(text: str, inline: bool = False) -> str:
    """`text` as a code block whose fence is longer than any run of backticks in it - or, `inline`,
    as code on one line (in a sentence, a heading)."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    if inline:
        return f"{'`' * (longest + 1)} {' '.join(text.split())} {'`' * (longest + 1)}"
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{text}\n{fence}"


def team_pr_body(
    task: str, name: str, branch: str, files: dict, check: str, notes: str, secrets: list[str]
) -> str:
    """A team's pull request's body (`TEAM_PR_BODY`): `secrets` masked out of all it says - its
    notes before they are cut -, what an agent wrote fenced."""
    listed = "\n".join(f"{path} ({letter})" for path, letter in list(files.items())[:200])
    task, name, branch, listed, check, notes = (
        raw.hide(one, secrets) for one in (task, name, branch, listed, check, notes)
    )
    return TEAM_PR_BODY.format(
        task=fenced(task),
        name=fenced(name, inline=True),
        branch=branch,
        files=fenced(listed),
        check=fenced(check),
        notes=fenced(notes[:TEAM_PR_NOTES] or "(none)"),
    )


# D2: an address on github.com as git writes one - https, ssh, scp-like (`git@github.com:o/r`).
_GITHUB = re.compile(
    r"(?:(?:https?|ssh|git)://(?:[^/@]+@)?|[^/@:]+@)github\.com(?::\d+)?[:/]", re.I
)


def origin_name(project: Path) -> str:
    """What a note calls origin (D2): "GitHub" where a push goes to github.com, else "origin" - a
    folder on this machine, another host."""
    return "GitHub" if _GITHUB.match(git.push_address(project)) else "origin"


def config_digest(project: Path) -> str | None:
    """What git's config is for the project, in every scope it reads - system, the user's global
    one, the repository's, a worktree's `config.worktree`, and what they include - as one digest
    (`git config --list --show-origin`: a push runs what it names, an address, a credential
    helper, an ssh command). None where git does not answer."""
    try:
        exe, _folder = git.repository(project)
    except git.Refused:
        return None
    code, out, _said = git._in(
        project,
        exe,
        *git.UNASKED,
        "config",
        "--list",
        "--show-origin",
        "-z",
        seconds=git.SHORT_SECONDS,
        **git.UNASKED_ENV,
    )
    return hashlib.sha256(out).hexdigest() if code == 0 else None


def _short(value: str | None) -> str:
    if not value:
        return "none"
    return value.removeprefix("refs/heads/") if value.startswith("refs/") else value[:7]


def moved(before: dict, after: dict, own: str | Iterable[str]) -> list[str]:
    """H2: what changed in the repository between `before` and `after` (`refs`) but the job's own
    branch `own` - or, a night's jobs, each of theirs (made, each pushed as its own) - in KOLONİ's
    lines - at most `MOST_MOVED`, then how many more."""
    ours = {f"refs/heads/{one}" for one in ([own] if isinstance(own, str) else own)}
    lines = []
    for ref in sorted(set(before) | set(after)):
        if ref in ours or before.get(ref) == after.get(ref):
            continue
        if ref in MOVED_ALL:
            lines.append(f"Changed outside its branch: {MOVED_ALL[ref]}")
            continue
        name = ref.removeprefix("refs/heads/").removeprefix("refs/")
        lines.append(
            MOVED.format(ref=name, old=_short(before.get(ref)), new=_short(after.get(ref)))
        )
    more = len(lines) - MOST_MOVED
    return lines[:MOST_MOVED] + ([f"and {more} more"] if more > 0 else [])


def commits(project: Path, start: str, tip: str) -> int | None:
    """How many commits the branch has from `start` (the commit it began at) to `tip`."""
    try:
        exe, _folder = git.repository(project)
    except git.Refused:
        return None
    code, out, _said = git._in(
        project,
        exe,
        *git.UNASKED,
        "rev-list",
        "--count",
        f"{start}..{tip}",
        seconds=git.SHORT_SECONDS,
        **git.UNASKED_ENV,
    )
    return int(out.strip()) if code == 0 and out.strip().isdigit() else None


def push_line(away: dict, name: str, into: str | None, pull_request: bool) -> str:
    """The push row's line, from a job's end record."""
    said = PUSH_LINE.format(
        name=name,
        origin=away.get("origin") or "?",
        files=away.get("files") or 0,
        mark=MARKS.get(away.get("checks") or "", "…"),
        tip7=(away.get("tip") or "")[:7],
    )
    said += PUSH_PR.format(into=into) if pull_request and into else ""
    left = away.get("left_out") or []
    return said + (PUSH_LEFT.format(files=", ".join(left)) if left else "")


def record(session: Session, cid: str) -> tuple[Agent, dict] | None:
    """The newest Orchestrator of a job's chat that worked on its branch, and its record's
    `away` part (`Agent.copy["away"]`); None: none did."""
    for agent in session.scalars(
        select(Agent)
        .join(Run, Run.id == Agent.run_id)
        .where(Run.conversation_id == cid, Agent.depth == 0)
        .order_by(Agent.created_at.desc())
    ):
        if isinstance(away := (agent.copy or {}).get("away"), dict):
            return agent, away
    return None


def row(session: Session, cid: str) -> dict | None:
    """The morning's line of a job's branch (`AwayBranchOut`), once its end is on record."""
    found = record(session, cid)
    if found is None or "tip" not in found[1]:
        return None
    agent, away = found
    return {
        "name": (agent.copy or {}).get("on_branch"),
        "from_head": (agent.copy or {}).get("from_head"),
        **{
            key: away.get(key)
            for key in ("tip", "into", "commits", "files", "checks", "origin", "why")
        },
        "moved": [
            *(away.get("moved") or []),
            *([CONFIG_MOVED] if away.get("config_moved") else []),
            *([HOOKS_MOVED] if away.get("hooks_moved") else []),
        ],
    }
