"""The project's own tree, read only, for the Files window (slice 42c): a folder one level at a
time, a file's text, and a file a preview's frame asks for. Nothing outside the project, no link
followed, no secret (`is_secret`) and no place KOLONİ never opens is listed or read - by its
name, nor by a short name that leads to it (`ENV~1` for `.env`).

Plain functions: they read files, and run in the server's threads, off its loop.
"""

import itertools
import os
import time
from collections import deque
from pathlib import Path

from app import copies, git, views
from app.project_view import _is_link
from app.views import Refused
from app.workspace import (
    MAX_READ_BYTES,
    Workspace,
    _cased,
    _never_places,
    has_other_names,
    is_kept_code,
    is_secret,
    unified_diff,
)

# shortcut: first 2000 entries of a folder; add a "more" row if a real project needs it.
MOST_LISTED = 2000


def _inside(root: Path) -> list:
    """The places KOLONİ never opens that lie in the project (`_hidden`'s), found once for many
    paths of it."""
    top = _cased(root)
    return [place for place in (_cased(one) for one, _ in _never_places())
            if place != top and place.is_relative_to(top)]


def _hidden(root: Path, path: Path, places: list | None = None) -> bool:
    """A secret, a link, or a place KOLONİ never opens that lies in the project (its own
    record, say). (Places around the project are not asked: the e2e project lies in one.)
    `places`: `_inside(root)`, where the caller asks of many paths of it."""
    rel = path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
    cased = _cased(path)
    return is_secret(rel) or _is_link(path) or any(
        cased.is_relative_to(place) for place in (_inside(root) if places is None else places))


def _where(root: Path, rel: str) -> Path:
    """A path of the project by its relative name, every part looked at from the root down:
    as written (a link is refused before it is followed) and as it really is (a short name
    is its long one then)."""
    if rel in ("", "."):
        return root
    try:
        views._vetted(rel)  # no drive, no way up, no backslash, no device name
    except Refused:
        raise Refused(400, "not a path in the project") from None
    at, places = root, _inside(root)
    for part in rel.split("/"):
        at = at / part
        if _hidden(root, at, places) or _hidden(root, at.resolve(), places):
            raise Refused(404, "not shown")
    return at


def listing(root_path: str, rel: str) -> list[dict]:
    root = Path(root_path).resolve()
    folder = _where(root, rel)
    if not folder.is_dir():
        raise Refused(404, "no such folder")
    out, places = [], _inside(root)
    try:
        with os.scandir(folder) as entries:
            for entry in itertools.islice(entries, MOST_LISTED):
                child = Path(entry.path)
                try:
                    if _hidden(root, child, places):
                        continue
                    if entry.is_dir():
                        out.append({"name": entry.name, "kind": "dir", "size": None})
                    elif entry.is_file():
                        size = entry.stat().st_size
                        out.append({"name": entry.name, "kind": "file", "size": size})
                except OSError:
                    continue  # (one that cannot be looked at is left out, not the folder)
    except OSError:
        raise Refused(404, "it could not be read") from None
    return sorted(out, key=lambda e: (e["kind"] != "dir", e["name"].lower()))


def text_of(root_path: str, rel: str) -> dict:
    """Its text, at most MAX_READ_BYTES; a larger or not-UTF-8 file says so instead."""
    root = Path(root_path).resolve()
    target = _where(root, rel)
    if not rel or not target.is_file():
        raise Refused(404, "no such file")
    if has_other_names(target):  # a hard link: another name of it may be a key anywhere
        raise Refused(404, "not shown")
    try:
        with open(target, "rb") as file:
            size = os.fstat(file.fileno()).st_size
            data = file.read(MAX_READ_BYTES + 1)
    except OSError:
        raise Refused(404, "it could not be read") from None
    return _shown(data, size)


def _shown(data: bytes, size: int) -> dict:
    if len(data) > MAX_READ_BYTES:
        return {"text": None, "size": size, "binary": False, "too_large": True}
    try:
        text = data.decode("utf-8").replace("\r\n", "\n")  # shown, not written
    except UnicodeDecodeError:
        return {"text": None, "size": size, "binary": True, "too_large": False}
    return {"text": text, "size": size, "binary": False, "too_large": False}


def diff_of(root_path: str, rel: str) -> dict:
    """A file's unified diff against the project's git HEAD, whole, for the Workspace's Changes
    tab (K-degisenler): by `text_of`'s rules and its size (MAX_READ_BYTES) - over it, or not
    text, 413 / 415 say so instead. An untracked file is all added. 404 where the project
    shows no git."""
    root = Path(root_path).resolve()
    target = _where(root, rel)
    if not rel or target.is_dir():
        raise Refused(404, "no such file")
    if target.is_file() and has_other_names(target):  # a hard link: another name may be a key
        raise Refused(404, "not shown")
    # (Before git is asked: a diff of a file past the size is never made, let alone read.)
    if target.is_file() and target.stat().st_size > MAX_READ_BYTES:
        raise Refused(413, "too large to show: over 256 KB")
    try:
        said = git.diff(root, rel)
    except git.Refused as refused:
        raise Refused(404, str(refused)) from None
    if said is None:
        read = text_of(root_path, rel)
        if read["binary"]:
            raise Refused(415, "not text: there is no diff to show")
        if read["too_large"]:
            raise Refused(413, "too large to show: over 256 KB")
        return {"diff": unified_diff("", read["text"] or "", rel)[0]}
    return _diff_shown(said)


def _diff_shown(said: str) -> dict:
    if len(said.encode()) > MAX_READ_BYTES:  # (a deleted file: its size is HEAD's)
        raise Refused(413, "too large to show: over 256 KB")
    if "@@" not in said and any(line.startswith("Binary files ") for line in said.splitlines()):
        raise Refused(415, "not text: there is no diff to show")
    return {"diff": said}


# K-dallar: a branch of the project, read from git without switching to it - nothing checked
# out, nothing written - by the project's rules: no secret by any part of its path, no link.
def _in_branch(rel: str) -> str:
    """A path of a branch by its relative name ("" its top), vetted as `_where` vets one."""
    if rel in ("", "."):
        return ""
    try:
        views._vetted(rel)  # no drive, no way up, no backslash, no device name
    except Refused:
        raise Refused(400, "not a path in the project") from None
    if is_secret(rel):
        raise Refused(404, "not shown")
    return rel


def _from_git(read, *args):
    try:
        return read(*args)
    except git.Refused as refused:
        raise Refused(404, str(refused)) from None


def listing_at(root_path: str, ref: str, rel: str) -> list[dict]:
    rel = _in_branch(rel)
    found = _from_git(git.folder_at, Path(root_path), ref, rel)
    if found is None:
        raise Refused(404, "no such folder")
    shown = [one for one in found if not is_secret(f"{rel}/{one['name']}".lstrip("/"))]
    return sorted(shown[:MOST_LISTED], key=lambda e: (e["kind"] != "dir", e["name"].lower()))


def text_at(root_path: str, ref: str, rel: str) -> dict:
    rel = _in_branch(rel)
    data = _from_git(git.file_at, Path(root_path), ref, rel, MAX_READ_BYTES) if rel else None
    if data is None:
        raise Refused(404, "no such file")
    if isinstance(data, int):  # (over the size: not read)
        return {"text": None, "size": data, "binary": False, "too_large": True}
    return _shown(data, len(data))


def changes_at(root_path: str, ref: str) -> list[dict] | None:
    return _from_git(git.changes_at, Path(root_path), ref)


def diff_at(root_path: str, ref: str, rel: str) -> dict:
    rel = _in_branch(rel)
    said = _from_git(git.diff_at, Path(root_path), ref, rel) if rel else None
    if said is None:
        raise Refused(404, "no such change")
    return _diff_shown(said)


def bytes_of(root_path: str, rel: str, most: int) -> bytes:
    """A file of the project as it is, by the same rules - for one attached to a message
    (slice 85b); Refused 413 past `most` bytes."""
    root = Path(root_path).resolve()
    target = _where(root, rel)
    if not rel or not target.is_file() or has_other_names(target):
        raise Refused(404, "no such file")
    try:
        with open(target, "rb") as file:
            data = file.read(most + 1)
    except OSError:
        raise Refused(404, "it could not be read") from None
    if len(data) > most:
        raise Refused(413, f"a file is {most // 2**20} MB at most")
    return data


def raw(root_path: str, rel: str) -> tuple[bytes, str]:
    """A file a preview's frame asks for - a page, or what is beside it - by slice 39's rules
    (`views.read_file`, served with `views.HEADERS`); only of a kind a page is drawn with."""
    root = Path(root_path).resolve()
    kind = views.type_of(_where(root, rel).resolve().name)
    if kind is None:
        raise Refused(404, "not a kind a preview shows")
    return views.read_file(Workspace(root), rel), kind


# What CLI agents load by themselves from the folders they work in (K-yabanci-talimat), and
# Copilot's in `.github/`: below the project's root, another project's. (agy reads .agents/,
# .agent/, _agents/, _agent/ - `model_agy`; Codex its skills from .agents/skills.)
INSTRUCTIONS = frozenset(name.casefold() for name in (
    *copies.MARKS[1:], "CLAUDE.local.md", ".codex", ".gemini", ".agents", ".agent", "_agents",
    "_agent"))
IN_GITHUB = frozenset({"copilot-instructions.md", "skills"})
# shortcut: the first 10 found, 8 folders deep, 5000 folders or 2 s; deeper is not looked in.
MOST_SHOWN, MOST_DEEP, MOST_FOLDERS, MOST_SECONDS = 10, 8, 5000, 2.0


def others_instructions(root_path: str) -> dict:
    """Another project's agent instruction files below the project's root - never the root's
    own, which are the user's: the first MOST_SHOWN paths, how many more, and whether a cap
    stopped the walk first. Names only: no file is read, no link followed."""
    root = Path(root_path).resolve()
    skipped = copies.NOT_COPIED | copies.LINKED
    deadline = time.monotonic() + MOST_SECONDS
    found: list[str] = []
    todo, looked = deque([("", 0)]), 0
    while todo and looked < MOST_FOLDERS and time.monotonic() < deadline:
        rel, depth = todo.popleft()
        looked += 1
        try:
            with os.scandir(root / rel) as entries:
                listed = sorted(entries, key=lambda entry: entry.name)
        except OSError:
            continue
        for entry in listed:
            name, path = entry.name.rstrip(" .").casefold(), f"{rel}{entry.name}"
            folder = entry.is_dir(follow_symlinks=False)
            if name in INSTRUCTIONS:  # (not gone into: one is enough to say)
                if depth:
                    found.append(f"{path}/" if folder else path)
            elif depth > 1 and name in IN_GITHUB and rel.casefold().endswith(".github/"):
                found.append(f"{path}/" if folder else path)
            elif (folder and depth < MOST_DEEP and name not in skipped
                  and not _hidden(root, Path(entry.path)) and not is_kept_code(path.split("/"))):
                todo.append((f"{path}/", depth + 1))
    return {"paths": found[:MOST_SHOWN], "more": max(len(found) - MOST_SHOWN, 0),
            "partial": bool(todo)}
