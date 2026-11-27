"""A push of your feature branch to the judge (0.1.11, the user's 27 Nov: "main push edilmesin,
açılan branch'in origin'ine push etme olabilir"): in a turn the user watches at Full auto, a plain
`git push` of the checked-out branch to its own `origin` goes to Full auto's judge in place of the
list's card - K3's way (`RiskJudgeMixin._push_takes`), as Claude Code's auto mode. Never main,
master or origin's default branch, a force, a tag, another name or another remote. `shape` reads
the line, `at_start` keeps what a push goes by as the turn begins (`LeadToolsMixin._git_start`) and
`refused` looks at the repository as the command is decided: what it does not know as plain is the
list's card (fails closed)."""

import os
import re
from pathlib import Path

from app import git
from app.away_branch import config_digest
from app.read_edges import chained
from app.risk_judge import _PLAIN

# Pushed only on a card, whatever origin's default is - casefolded: on a disk that folds case
# `Main` is main.
PROTECTED = frozenset({"main", "master"})
# The most commits a push may send that are looked at for a secret: past it, its card.
# shortcut: each commit's files are read one by one (`git.held_since`); read them in one batch if
# longer pushes are met often.
MOST_COMMITS = 50
# git's `push.default`s that send the branch to its own name (with `branch.<b>.merge` its own):
# `matching` sends main too.
_DEFAULTS = frozenset({"simple", "current", "upstream", "tracking"})
_FALSE = frozenset({"false", "no", "off", "0"})
# Settings that are a refused option's other spelling (`--mirror`, `--follow-tags`, `-o`,
# `--receive-pack`, `--recurse-submodules`) or a push's map to another name: none, or false.
_NEVER = ("remote.origin.push", "push.pushoption", "remote.origin.receivepack")
_OFF = ("remote.origin.mirror", "push.followtags")
# The hooks a push runs on this machine (a name with an ending too: `pre-push.exe` on Windows).
_PUSH_HOOKS = ("pre-push", "reference-transaction")
# An address git reaches over a network: a scheme's (not file://), or scp's `host:path`.
_REMOTE = re.compile(r"(?i)(?!file:)(?:[a-z][a-z0-9+.-]*://|[^/\\:]{2,}:)")


def shape(line: str) -> str | None:
    """The branch a plain push to `origin` names, word for word: "" for none (`git push`, `git push
    origin`: git's own pick), its name (`git push origin x`, `git push -u origin x`, `git push
    --set-upstream origin x`) or "HEAD" (`git push origin HEAD`); None for any other line - not
    plain (`risk_judge._PLAIN`: no quote, `:`, `+`, `$`...), chained, git by a path, any other
    option (`-f`, `--tags`, `-o`, `--repo`...), remote or refspec, main or master by name."""
    if not _PLAIN.fullmatch(line) or chained(line):
        return None
    words = line.split()
    if words[:2] != ["git", "push"]:
        return None
    rest = words[2:]
    if rest in ([], ["origin"]):
        return ""
    upstream = rest[0] in ("-u", "--set-upstream")
    rest = rest[1:] if upstream else rest
    if len(rest) != 2 or rest[0] != "origin" or rest[1].casefold() in PROTECTED:
        return None
    if rest[1] == "HEAD":
        return None if upstream else "HEAD"
    return None if rest[1].startswith("-") else rest[1]


def at_start(root: Path) -> dict | None:
    """What a push goes by, as a turn begins: where a push to origin goes (`git.push_address`: its
    pushurl and git's rewrites applied; "" for none), git's config in every scope as one digest
    (`away_branch.config_digest`: a `remote set-url`, a hooksPath, an ssh command, a credential
    helper; None: not read) and origin's default branch (`_default`). None where the project is
    no repository's top folder. Blocking.
    shortcut: a push that changes git's config (`git push -u`, a branch made to track one) makes
    the turn's next push a card; leave the branch's own upstream out of the digest if that is
    met often."""
    try:
        exe, _folder = git.repository(root)
    except git.Refused:
        return None
    return {
        "url": git.push_address(root),
        "config": config_digest(root),
        "default": _default(root, exe),
    }


def refused(root: Path, word: str, start: dict | None, needles: list[bytes]) -> str:
    """Why a plain push (`shape`'s `word`) run at the project's top `root` stays the list's card;
    "" for none: its branch (`_branch`), git's config (`_redirects`), what changed since the turn
    began (`start`, `at_start`'s - none: a card), a hook a push runs (`_hooked`), origin a folder
    in the project (its own hooks would run here), and a secret in what it sends
    (`_sends_secret`). Blocking: git, and origin asked, with git's own time limits.
    shortcut: a bare push (and `origin HEAD`) pushes the branch checked out as it runs - looked
    at here, before the judge and again after its fine; a switch by the user's own hand in
    between is not seen (another turn's is asked: `_branch_asks`). Name the branch on the line
    the agent is told to use if that is ever met."""
    if not start or not start["url"] or start["config"] is None:
        return "what a push goes by was not read as the turn began"
    try:
        exe, _folder = git.repository(root)
        branch = _branch(root, exe, start["default"])
        if not branch or word not in ("", "HEAD", branch):
            return "it pushes main, master, origin's default branch, no branch or another one"
        if why := _redirects(_config(root, exe), branch):
            return why
        url = git.push_address(root)
        if (url, config_digest(root)) != (start["url"], start["config"]):
            return "origin's address or git's config changed in this turn"
        if _hooked(root, exe):
            return "a pre-push or reference-transaction hook would run with it"
        if not _REMOTE.match(url) and (url.lower().startswith("file:") or _inside(root, url)):
            return "origin is a folder in the project, or given by a file: address"
        return _sends_secret(root, exe, url, branch, start["default"], needles)
    except git.Refused as exc:
        return str(exc) or "git did not answer"


def _branch(root: Path, exe: str, default: str) -> str:
    """The branch checked out; "" where HEAD is on none, or on main, master or origin's default -
    as it is now and as it was when the turn began (`default`): `refs/remotes/origin/HEAD` is a
    file anything may write."""
    branch = _ref(root, exe, "HEAD", "refs/heads/")
    held = {*PROTECTED, default.casefold(), _default(root, exe).casefold()}
    return "" if branch.casefold() in held else branch


def _ref(root: Path, exe: str, name: str, prefix: str) -> str:
    """Where the symbolic ref `name` points, `prefix` off; "" for nowhere, or not under it."""
    code, out, _said = git._in(
        root,
        exe,
        *git.UNASKED,
        "symbolic-ref",
        "-q",
        name,
        seconds=git.SHORT_SECONDS,
        **git.UNASKED_ENV,
    )
    found = out.decode("utf-8", "replace").strip() if code == 0 else ""
    return found.removeprefix(prefix) if found.startswith(prefix) else ""


def _default(root: Path, exe: str) -> str:
    """origin's default branch as this repository last heard it (`refs/remotes/origin/HEAD`); ""
    for none known."""
    return _ref(root, exe, "refs/remotes/origin/HEAD", "refs/remotes/origin/")


def _hooked(root: Path, exe: str) -> bool:
    """Whether a push would run a hook on this machine: a file of the folder git runs hooks from
    (`.git/hooks`, or the one `core.hooksPath` names, wherever it is: `rev-parse --git-path`)
    named `pre-push` or `reference-transaction`, with an ending or none, but git's samples. Any,
    the user's own too: an unchanged hook can run what an agent wrote (husky's stubs run
    `.husky/<name>`, Git LFS's pre-push uploads what `.lfsconfig` names). Refused where the
    folder cannot be read."""
    code, out, _said = git._in(
        root,
        exe,
        *git.UNASKED,
        "rev-parse",
        "--git-path",
        "hooks",
        seconds=git.SHORT_SECONDS,
        **git.UNASKED_ENV,
    )
    if code != 0:
        raise git.Refused("git did not say where its hooks are")
    folder = root / out.decode("utf-8", "replace").strip()
    try:
        names = os.listdir(folder) if folder.is_dir() else []
    except OSError as exc:
        raise git.Refused(f"git's hooks could not be read: {exc.strerror or exc}") from None
    return any(
        name.casefold().startswith(_PUSH_HOOKS) and not name.casefold().endswith(".sample")
        for name in names
    )


def _config(root: Path, exe: str) -> dict[str, list[str]]:
    """git's config as git reads it, in every scope (`config --list`): each key's values - a key
    with no value is true. Refused where git does not say it."""
    code, out, _said = git._in(
        root,
        exe,
        *git.UNASKED,
        "config",
        "-z",
        "--list",
        seconds=git.SHORT_SECONDS,
        **git.UNASKED_ENV,
    )
    if code != 0:
        raise git.Refused("git's config could not be read")
    found: dict[str, list[str]] = {}
    for entry in out.decode("utf-8", "replace").split("\0"):
        key, newline, value = entry.partition("\n")
        if key:
            found.setdefault(key, []).append(value if newline else "true")
    return found


def _redirects(said: dict[str, list[str]], branch: str) -> str:
    """What in git's config sends a plain push of `branch` elsewhere or sends more, in a sentence;
    "" for none: its upstream another branch, a remote other than origin for it, a `push.default`
    that sends more (`matching`), a push map, a mirror, tags, push options, a receive-pack, its
    submodules, or a hook the config sets (`hook.*`)."""
    at = f"branch.{branch}."
    if set(said.get(at + "merge", [])) - {f"refs/heads/{branch}"}:
        return "git's config gives the branch another upstream"
    remotes = [*said.get(at + "remote", []), *said.get(at + "pushremote", [])]
    if set(remotes + said.get("remote.pushdefault", [])) - {"origin"}:
        return "git's config pushes the branch to another remote"
    if {one.lower() for one in said.get("push.default", [])} - _DEFAULTS:
        return "git's push.default sends more than the branch"
    if any(said.get(key) for key in _NEVER) or any(
        one.lower() not in _FALSE for key in _OFF for one in said.get(key, [])
    ):
        return "git's config sends more with a push, or elsewhere"
    if {one.lower() for one in said.get("push.recursesubmodules", [])} - {*_FALSE, "check"}:
        return "git's config pushes submodules too"
    if any(key.startswith("hook.") for key in said):
        return "git's config sets hooks of its own"
    return ""


def _inside(root: Path, path: str) -> bool:
    """Whether `path` (from `root`, or whole) is `root` or in it, as it really is."""
    top = os.path.normcase(os.path.realpath(root))
    here = os.path.normcase(os.path.realpath(root / path))
    return here == top or here.startswith(top.rstrip(os.sep) + os.sep)


def _sends_secret(
    root: Path, exe: str, url: str, branch: str, default: str, needles: list[bytes]
) -> str:
    """Why the commits a push of `branch` sends are its card, "" for none: counted from a commit
    origin itself says it holds (`git._origin_holds`: never a remote-tracking ref of the
    repository's, which anything may write) - origin's own branch of that name, else its main,
    master or default -, none such, more than MOST_COMMITS, or one of them holding a secret
    (`needles`) in its message or a file it writes (`git.held_since`, as a branch's commits are
    looked at before KOLONİ keeps one). Refused where origin does not answer."""
    listed, here = git._origin_holds(root, exe, url)
    base = next(
        (listed[one] for one in (branch, *sorted(PROTECTED), default) if listed.get(one) in here),
        None,
    )
    if base is None:
        return "origin holds none of the branch, main, master or its default branch here"
    tip = f"refs/heads/{branch}"
    code, out, _said = git._in(
        root,
        exe,
        *git.UNASKED,
        "rev-list",
        "--count",
        f"^{base}",
        tip,
        seconds=git.SHORT_SECONDS,
        **git.UNASKED_ENV,
    )
    if code != 0 or not out.strip().isdigit() or int(out) > MOST_COMMITS:
        return f"it sends more than {MOST_COMMITS} commits, or they could not be counted"
    if git.held_since(root, base, tip, needles):
        return "a commit it sends holds a secret"
    return ""
