"""K-ortak-klasor: the teams' shared folder, `.koloni/shared/` in the project. Every agent reads
all of it; `decisions/` is KOLONİ's (a room's decision, K-not-oda), `contracts/` a team lead's
(or a `request_work` contract), and each team's own folder (its name made a slug) only its own
agents'. Outside the working copies (`copies._scan` leaves it out, Take in never touches it), out
of git by its own `.gitignore`, and each file starts with a header saying who wrote it.

Plain functions: they read and write files. Who may write where is the caller's to say (`may`).
"""

import os
import re
import unicodedata
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from app import copies, koloni, project_files
from app.views import Refused
from app.workspace import NOT_WRITTEN_UNATTENDED, _name

FOLDER = "shared"  # in `.koloni/`
PLACE = copies.SHARED
DECISIONS, CONTRACTS = "decisions", "contracts"
# A file's own name: one plain name, no folder of its own and no dot first.
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")
MAX_CHARS = 20_000
MOST_LISTED = 200


def _plain(words: str) -> str:
    """Words as a plain name: "Ünite / İstanbul" is `unite-istanbul` (letters without marks)."""
    bare = "".join(c for c in unicodedata.normalize("NFKD", words.replace("ı", "i"))
                   if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", bare.casefold()).strip("-")[:60].strip("-")


def slug(team: tuple[str, str]) -> str:
    """A team's folder, by its (id, name): "Backend / API" is `backend-api/`; a name with no Latin
    letter in it, a short form of its id; never one of KOLONİ's own folders."""
    made = _plain(team[1]) or f"team-{team[0][:6].casefold()}"
    return f"team-{made}" if made in (DECISIONS, CONTRACTS) else made


def name_of(what: str) -> str:
    """A file name made of a line of words: "GET /api/items" is `get-api-items.md`."""
    return f"{_plain(what) or 'note'}.md"


def header(by: str, turn: int | None, at: datetime, **more: str | None) -> str:
    """Who wrote it (team · role, or KOLONİ), in which turn and when; `for`, `answers` if given."""
    when = f"{at:%d %b %H:%M} UTC"
    lines = [f"by: {' · '.join(str(p) for p in (by, turn and f'turn {turn}', when) if p)}"]
    # (Each on one line: an agent's `answers` with a line break would write a `for:` of its own.)
    lines += [f"{key}: {' '.join(value.split())}" for key, value in more.items() if value]
    return "---\n" + "\n".join(lines) + "\n---\n"


def body_of(text: str) -> str:
    """A file's words without its header."""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            return text[end + 5:]
    return text


def written_by(text: str) -> str | None:
    """The team (or KOLONİ) its header names first."""
    found = re.match(r"---\nby: ([^\n·]+)", text)
    return found[1].strip() if found else None


def written_for(text: str) -> str | None:
    """The team its header says it is for (a request_work contract's asked team), whole: a
    team named "A, B" is one team, never two."""
    top = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    found = re.search(r"^for: (.+)$", top[1], re.MULTILINE) if top else None
    return found[1].strip() if found else None


def checked(path: str) -> tuple[str, str]:
    """A path in the shared folder as an agent writes it - "contracts/items-api.md" - as its
    folder and name; ValueError with why for any other."""
    parts = path.strip().replace("\\", "/").removeprefix(f"{PLACE}/").split("/")
    if len(parts) != 2 or not NAME.fullmatch(parts[1]) or not re.fullmatch(r"[a-z0-9-]+",
                                                                            parts[0]):
        raise ValueError(f"{path!r} is not a file of the shared folder: write it as "
                         "<folder>/<name>, a folder and a plain file name")
    # M1: nothing that steers later agents (AGENTS.md, CLAUDE.md...) - taken in, it would be the
    # project's without a card.
    if steers := next((NOT_WRITTEN_UNATTENDED[_name(p)] for p in parts
                       if _name(p) in NOT_WRITTEN_UNATTENDED), None):
        raise ValueError(f"{parts[1]} is not a name for the shared folder: it is {steers}")
    return parts[0], parts[1]


def may(folder: str, team: tuple[str, str] | None, lead: bool,
        others: Iterable[tuple[str, str]] = ()) -> str | None:
    """Why this writer may not write in `folder` (None: it may). `team`: the writer's team, (id,
    name) (None: an agent of no team); `lead`: it is a team's lead; `others`: the chat's other
    teams - one whose folder would be the same ("Web app", "web-app") makes it nobody's."""
    if folder == DECISIONS:
        return "decisions/ is KOLONİ's own: it writes there what a room between teams decided"
    if team is None:
        return "only an agent of a team writes in the shared folder"
    if folder == CONTRACTS:
        # B-378 (live): the Docs writer was refused, and its coordinator - looking for a role to
        # hand it to - never wrote it: the same finding three rounds.
        return None if lead else (
            "contracts/ is written by a team's coordinator (or with request_work's contract): "
            "put it in your team's folder, or tell your coordinator what to change - it writes "
            "the contract itself with write_shared, at any step of its recipe")
    if folder != slug(team):
        return f"{folder}/ is not your team's folder: your team writes in {slug(team)}/"
    same = [other[1] for other in others if other[0] != team[0] and slug(other) == folder]
    return f"{folder}/ would be {same[0]}'s folder too: the user renames one of the two" if (
        same) else None


def write(root: str, folder: str, name: str, text: str, top: str, own: str | None = None,
          unique: bool = False) -> str:
    """Write a file of the shared folder with its header `top`, and the folder's `.gitignore` the
    first time; returns its path in the folder. `own`: who writes it (a team, KOLONİ) - a file
    another one wrote is not written over, but a contract that is for it (B-378: the asked
    team keeps the contract it works to). `unique`: a file of that name gets a number instead.
    Refused (422) says why it was not written."""
    if len(text) > MAX_CHARS:
        raise Refused(422, f"at most {MAX_CHARS} characters")
    base = Path(root) / koloni.FOLDER / FOLDER
    if not (base / ".gitignore").exists():
        koloni.write(root, f"{FOLDER}/.gitignore", "# KOLONİ's shared folder: out of git; "
                     "take a file in from the canvas to keep it\n*")
    stem, dot, ext = name.rpartition(".") if "." in name else (name, "", "")
    for n in range(1, 100):
        rel = f"{folder}/{name if n == 1 else f'{stem}-{n}{dot}{ext}'}"
        there = read(root, rel) if (base / rel).is_file() else None
        # shortcut: written over by the team it was for, it is that team's alone (its header
        # names no `for` then); keep the asker on it too if a contract is seen to bounce.
        if there is None or not unique and (own is None or written_by(there) == own or (
                folder == CONTRACTS and own == written_for(there))):
            break
        if not unique:
            raise Refused(422, f"{rel} was written by {written_by(there) or 'someone else'}: "
                               "write yours under another name")
    else:
        raise Refused(422, f"{folder}/ has 99 files named {name} already: nothing was written")
    koloni.write(root, f"{FOLDER}/{rel}", top + text.strip())
    return rel


def read(root: str, rel: str) -> str:
    """A file of the shared folder, as the Files window reads one."""
    found = project_files.text_of(root, f"{PLACE}/{rel}")
    if found["text"] is None:
        raise Refused(422, f"{rel} is not text, or too large to read")
    return found["text"]


def listing(root: str) -> list[dict]:
    """Every file of the shared folder, folder by folder: its path in it and when it was last
    written. No link is followed."""
    base = Path(root) / koloni.FOLDER / FOLDER
    found: list[dict] = []
    # (Never through a link or a junction, as the Files window goes.)
    if not base.is_dir() or project_files._is_link(base) or project_files._is_link(base.parent):
        return found
    for folder in sorted(os.scandir(base), key=lambda e: e.name):
        if not folder.is_dir(follow_symlinks=False) or project_files._is_link(Path(folder.path)):
            continue
        for entry in sorted(os.scandir(folder.path), key=lambda e: e.name):
            if entry.is_file(follow_symlinks=False) and len(found) < MOST_LISTED and not (
                    project_files._is_link(Path(entry.path))):
                at = datetime.fromtimestamp(entry.stat().st_mtime).astimezone()
                found.append({"path": f"{folder.name}/{entry.name}", "at": at})
    return found


def take(root: str, rel: str) -> str:
    """Copy a file of the shared folder into the project at the same path (`contracts/x.md`),
    without its header; never over a file that is there. Returns the path it was written to."""
    folder, name = checked(rel)
    text = body_of(read(root, f"{folder}/{name}"))
    target = project_files._where(Path(root).resolve(), f"{folder}/{name}")
    if target.exists():
        raise Refused(409, f"{folder}/{name} is in the project already: nothing was written")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as file:  # (never over one made now)
        file.write(text)
    return f"{folder}/{name}"
