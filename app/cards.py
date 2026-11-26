"""Why each command card was asked (0.1.7), kept on its record (`Command.asked_reason`); and
which line of the user's words names a delete's target (`mentioned`, for "Check what I said
first"). 0.1.10: Usage's Cards - the counts and the rules they suggested - is cut.

Every word here is KOLONİ's: a card's reason is the gate's own family of it (`card_reason`, when
the card opens - never an agent's words)."""

import fnmatch
import re

from app.commands import (
    SEARCHES_FOLDER,
    _words,
    harms,
    names_secret,
)

# The families of why a card was asked, in the order the Usage page says them.
REASONS = {
    "delete": "Deletes or overwrites",
    "send": "Sends off this machine",
    "install": "Installs packages",
    "shell": "Runs a command through a shell",
    "secret": "A secret file",
    "standing": "A file that steers later turns",
    "stop": "Stops programs by name",
    "outside": "Out of its working copy",
    "web": "The web, with web tools off",
    "server": "Starts a server",
    "rule": "No rule covers it",
    "judge": "Full auto's judge found it risky",
    "other": "Another reason",
}
# A reason's sentence (`harms`, `copy_reason`, `installs`, `runs_another`, `web_off_reason`, the
# disposable look's) by how it starts: case matters - "it names" a path out of the copy, "Names"
# a file that steers later turns.
_FAMILIES = (
    (
        "delete",
        r"(?:Deletes|Empties|Throws away|Overwrites or deletes|it deletes|it rebuilds"
        r"|what it deletes changed)\b",
    ),
    ("send", r"It (?:reaches beyond|sends work off)\b"),
    ("install", r"It (?:installs|downloads a package)\b"),
    ("shell", r"It (?:runs another command|hands shells)\b"),
    ("stop", r"Stops programs\b"),
    ("secret", r"(?:Opens a secret file|It searches the whole folder)\b"),
    ("standing", r"(?:Names|Sets this project's git|Applies a patch)\b"),
    ("outside", r"(?:it names|it writes in|Climbs out|Makes a link|Opens a git worktree)\b"),
    ("web", r"web is off\b"),
    ("judge", r"KOLONİ's judge: "),  # (Full auto's judge's card: `risk_judge.CARD`)
)
_FAMILY = [(name, re.compile(pattern)) for name, pattern in _FAMILIES]

# The family of a card a CLI asked for with a reason of its own (Codex: to leave its sandbox) where
# KOLONİ's gate gave none: the CLI's words are on the card, never read for its family (review of
# the card measurement: a reason that started "Deletes" made any command a delete card).
CLI_ASKED = "The CLI asked for it in words of its own"

# What deletes files by their names, and the switches it may have in a suggested rule - none that
# takes a value (`-ErrorAction x`, `-Exclude src`: a value read as a target names what was not
# deleted) nor one that reaches further (`del /s`, `rmdir -p`). shortcut: deletes only; add a
# family (a push to a branch) when its rule's words are as plain.
_DELETERS = {
    "rm": frozenset(
        {
            "-r",
            "-R",
            "-f",
            "-rf",
            "-fr",
            "-Rf",
            "-fR",
            "-d",
            "-v",
            "--recursive",
            "--force",
            "--dir",
            "--verbose",
        }
    ),
    "rmdir": frozenset({"-v", "--verbose"}),
    "rd": frozenset({"/s", "/q"}),
    "del": frozenset({"/q", "/f"}),
    "erase": frozenset({"/q", "/f"}),
    "remove-item": frozenset({"-recurse", "-force"}),
    "ri": frozenset({"-recurse", "-force"}),
}
_CASED = frozenset({"rm", "rmdir"})  # (PowerShell's and cmd's switches are read in any case)
# A target a rule may name, joined with its folder: a relative path every part of which is plain
# characters - never a glob, a variable, `.`, `..`, a dot file, a part that ends in a dot.
_PART = re.compile(r"[A-Za-z0-9_](?:[A-Za-z0-9_.\-]*[A-Za-z0-9_\-])?")
MOST_PATH = 80
MOST_TARGETS = 3


def family(sentence: str) -> str:
    """A reason's sentence as a `REASONS` key; "other" for one none of them starts so."""
    return next((name for name, start in _FAMILY if start.match(sentence)), "other")


def card_reason(
    judged: str,
    instructions: bool,
    why: str,
    *,
    searched: bool = False,
    web_off: bool = False,
    keep_running: bool = False,
) -> str:
    """Why a card was asked, as the gate saw it the moment it opened: the sentence its card shows
    (the harm of `judged` - the command with its folder, `with_cwd` - else the reason KOLONİ gave
    its call, `why` - `ToolCall.why_asked`, never a CLI's own words: `CLI_ASKED` -, else the
    folder search), then web off, a server, else no rule covered it at the chat's level."""
    said = harms(judged, instructions) or why or (SEARCHES_FOLDER if searched else "")
    if said:
        return family(said)
    if names_secret(judged):
        return "secret"
    return "web" if web_off else "server" if keep_running else "rule"


def _targets(command: str, cwd: str | None) -> list[str] | None:
    """What a plain delete names, each joined with its folder; None where its folder is not known,
    a switch is not one of its plain ones (`_DELETERS`), or a target is no plain relative path."""
    words = _words(command)
    # (By its bare name alone: `./rm` is a script of the project's, `C:/x/rm.exe` another program.)
    bare = words[0] if words else ""
    program = bare if bare in _CASED else bare.casefold()
    if cwd is None or program not in _DELETERS:
        return None
    switches = [w for w in words[1:] if w.startswith(("-", "/"))]
    plain = _DELETERS[program]
    if any((w if program in _CASED else w.casefold()) not in plain for w in switches):
        return None
    # (`./build` is `build`: §8's two lines that disagree name it so - "Never delete ./build.")
    named = [w.removeprefix("./") for w in words[1:] if not w.startswith(("-", "/"))]
    if not named or len(named) > MOST_TARGETS:
        return None
    # The path as joined, never resolved, is what must be plain - its folder is on record as the
    # agent's command gave it (review: a cwd "all of src and" wrote "You may delete all of src
    # and/build.", and `x/../src` "You may delete src."). The root is "." - or "", as a CLI's
    # command at the root may be on record.
    joined = [w.rstrip("/") if cwd in ("", ".") else f"{cwd}/{w}".rstrip("/") for w in named]
    if not all(_plain_path(one) for one in joined):
        return None
    return joined


def _plain_path(path: str) -> bool:
    return len(path) <= MOST_PATH and all(_PART.fullmatch(part) for part in path.split("/"))


def mentioned(texts: list[str | None], command: str, cwd: str | None) -> str | None:
    """S: the first line of the user's words - their preferences, the project's rules - that
    names a target of this delete at all, however spelled (`./build`, `.\\build`, `build/`,
    `build`, a path under it: `build/keep.txt`), or a folder it is in ("anything under out"), its
    own name ("any build folder"), a full path ending in it, or a pattern that takes it in
    (`out/*`, `**/build`, `*.db`) - a nested list item and a code block's line too; None: none
    does. Check what I said first sets such lines against each other (`judge.set_against`): no
    list of words tells one that allows a delete from one that forbids it."""
    targets = _targets(command, cwd) or []
    if not targets:
        return None
    names: set[str] = set()
    for one in targets:
        parts = one.split("/")
        names.update("/".join(parts[:n]) for n in range(1, len(parts) + 1))
        names.add(parts[-1])
    named = re.compile(
        # (a path of its own or one under it - never part of a longer name: `src/build`,
        # `build-cache`, `build.old`; a sentence's full stop after it is none - or the end of a
        # full path: `C:/proj/out/build`, `/home/me/proj/build`)
        # (bounded: a long line of "/a;/a;…" is read in time, never each start to its end)
        r"(?<![\w./\\-])(?:\.[/\\]|(?:[A-Za-z]:)?[/\\](?:[^\s/\\]{1,80}[/\\]){0,32})?(?:"
        + "|".join(re.escape(one).replace("/", r"[/\\]") for one in sorted(names, key=len)[::-1])
        + r")(?![\w-]|\.[\w-])",
        re.IGNORECASE,
    )
    lines = (line.strip() for text in texts for line in (text or "").splitlines())
    return next((line for line in lines if named.search(line) or _globbed(line, targets)), None)


def _globbed(line: str, targets: list[str]) -> bool:
    """Whether a word of `line` is a pattern (`*`, `?`) that takes a target in, as a shell's glob
    would from the project's root or any folder (`**/build`); whatever its case."""
    for word in line.split():
        if ("*" in word or "?" in word) and len(word) <= MOST_PATH:
            glob = word.strip(".,;:`'\"()").removeprefix("./").replace("\\", "/").casefold()
            if not glob.strip("*?/"):  # (a list's `*`, "5 * 3", a lone `**`: no pattern)
                continue
            for one in targets:
                path = one.casefold()
                if fnmatch.fnmatchcase(path, glob) or fnmatch.fnmatchcase(
                    path, glob.removeprefix("**/")
                ):
                    return True
    return False
