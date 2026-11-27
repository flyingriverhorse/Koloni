"""B-336: the one delete with no card at Full auto - of files in the agents' scratch,
`.koloni/tmp/`; split from `app.commands` (K-koloni-alan). Judged where the card is decided
(`AgentRunner._night_asks`); `commands.danger` stays as strict as ever.
"""

import os
import re

from app.commands import _CLIMBS, _IN_SCRATCH, _as_read, _holds_link, names_secret

# B-336: the one card-free delete - a deleter alone on its line, by its bare name; plain forcing
# and recursion (`_RECURSES`: a folder of the scratch, no link anywhere below it) its only
# flags; its paths each spelt plainly under `.koloni/tmp/` (no part starting with ".", no
# wildcard); and nothing in the line that joins, wraps, quotes, expands or redirects (`_NOT_PLAIN`:
# `|;&`, a newline, `<>`, a comma or `=` list, any quote - smart ones too -, `^`, a backtick,
# brackets, `$ % ~`, `* ?`).
_SCRATCH_DELETERS = frozenset({"remove-item", "ri", "rm", "del", "erase", "unlink"})
_RECURSES = frozenset({"-r", "-rf", "-fr", "-recurse"})  # (`-R`, `-Rf`: by `casefold`)
_SCRATCH_FLAGS = _RECURSES | {"-f", "--force", "-force", "-fo", "-q", "-path", "-literalpath"}
_NOT_PLAIN = re.compile(r"[|;&\n\r<>,=`^'\"()\[\]{}$%~*?‘-„]")
# Live (Codex 0.164.0): `Remove-Item -LiteralPath '.koloni/tmp/cs' -Recurse -Force` asked. A
# word that is one plain scratch path in one pair of plain quotes is that path, to sh and to
# PowerShell: read without them. Any other quote - around a flag, a space, two pieces glued,
# a pair left open - is still no plain line.
_QUOTED_SCRATCH = re.compile(r"(?<!\S)(['\"])(" + _IN_SCRATCH.pattern + r")\1(?!\S)", re.IGNORECASE)


def scratch_delete_only(command: str, root: str | None) -> bool:
    """B-336: whether a line is one delete of files in `.koloni/tmp/`, the agents' scratch of
    `root` (the folder it runs in), and nothing else - no card at Full auto, as writing there has
    none. Judged where the card is decided (`AgentRunner._night_asks`): `danger` stays as strict
    as ever, so no rule is offered for such a delete nor covers one. As narrow as it can be
    (`_SCRATCH_DELETERS`, `_SCRATCH_FLAGS`, `_IN_SCRATCH`, `_NOT_PLAIN`), not climbing out
    (`_CLIMBS`, the line read as the shell reads it), and each path, links resolved, inside the
    project's own scratch - which is no link itself. A recursive one (`_RECURSES`) of a folder
    that holds no link (`_holds_link`: Windows PowerShell's `Remove-Item -Recurse` deletes
    through a junction). Not `rmdir /s /q`: `/s` is a path to sh and pwsh. Nor a delete after a
    `cd` into the scratch (run_command's `cwd` there): a `cd` that fails leaves it in the project.
    shortcut: only the links there when it is asked are checked; one made after that by a script
    (python's `_winapi.CreateJunction`: a `mklink` line is a card, a script that makes a link is
    not) is not seen, and Windows PowerShell 5.1's `Remove-Item -Recurse` follows it. Not given
    to Copilot's new shell for that (`_approve_command`); check again as it runs if it is.
    K-koloni-alan, after its review: the scratch alone - KOLONİ's worktrees and copies in
    `.koloni/` are each another agent's work, and a delete there is asked as any."""
    command = _QUOTED_SCRATCH.sub(r"\2", command)
    if root is None or _NOT_PLAIN.search(command) or _CLIMBS.search(_as_read(command)):
        return False
    words = command.split()
    if not words or words[0].casefold() not in _SCRATCH_DELETERS:
        return False
    flags = [word for word in words[1:] if word.startswith("-")]
    paths = [word for word in words[1:] if not word.startswith("-")]
    if (
        not paths
        or any(flag.casefold() not in _SCRATCH_FLAGS for flag in flags)
        or not all(_IN_SCRATCH.fullmatch(path) for path in paths)
    ):
        return False
    where = os.path.normcase(os.path.join(os.path.realpath(root), ".koloni", "tmp"))
    scratch = os.path.normcase(os.path.realpath(where))
    if scratch != where:  # (the scratch, or .koloni, a link itself: where it leads is not it)
        return False
    real = [os.path.realpath(os.path.join(root, path)) for path in paths]
    recursive = any(flag.casefold() in _RECURSES for flag in flags)
    # (What KOLONİ itself keeps there - the browser's profile, the user's screenshots, the
    # images shown - is not an agent's to empty unasked: `_KOLONIS_OWN`.)
    # (`browser.`: Windows opens a name without its last dots.)
    own = recursive and any(
        re.split(r"[/\\]", path.removeprefix("./"))[2].rstrip(".").casefold() in _KOLONIS_OWN
        for path in paths
    )
    return all(os.path.normcase(path).startswith(scratch + os.sep) for path in real) and not (
        own or names_secret(command) or recursive and _holds_link(real)
    )


_KOLONIS_OWN = frozenset({"browser", "images"})  # (`AgentRunner._scratch_folder`'s)
