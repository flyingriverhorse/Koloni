"""The places KOLONİ never opens, said with why (slice 75), and the folder picker's listing
(slice 86a). The folders a chat also works in are its own (slice 86b)."""

import os
import stat
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require_own_origin
from app.config import REPO_ROOT
from app.schemas import FolderBrowseIn, FolderBrowseOut, FoldersOut
from app.workspace import OWN_CODE, OWN_RECORD, _cased, _never_places, far_or_device, not_a_project

router = APIRouter(prefix="/api/folders", tags=["folders"])
# The most folders one listing holds.
MAX_LISTED = 500
_HIDDEN = stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM


@router.get("", response_model=FoldersOut)
def folders():
    # (A place by its name and by where it leads: the same one is said once.)
    never = dict(_never_places())
    return FoldersOut(never=[{"path": str(place), "why": why} for place, why in never.items()])


def _in_a_never_place(path: Path) -> str | None:
    """Why nothing in this folder is listed: it is, or is in, a place KOLONİ never opens.
    shortcut: but the one folder KOLONİ's e2e works in (frontend/e2e/paths.mjs) and the folder
    it is in, as `not_a_project` lets the one be opened; take this out with that one's."""
    cased = _cased(path)
    why = next((why for place, why in _never_places() if cased.is_relative_to(_cased(place))),
               None)
    e2e = REPO_ROOT / "runtime" / "e2e" / "project"
    if why in (OWN_RECORD, OWN_CODE) and cased in (_cased(e2e), _cased(e2e.parent)):
        return None
    return why


def _entry(child: Path, attributes: int, link: bool) -> dict:
    """One folder of a listing. A link (or junction) is shown, never followed: it may lead
    to a share, which would be dialled - and is not opened."""
    try:
        blocked = link or bool(not_a_project(child))
    except (OSError, ValueError):
        blocked = True
    return {
        "name": child.name, "path": str(child),
        # (Nothing in one that is not opened is looked at; lexists follows no link.)
        "koloni": not blocked and os.path.lexists(child / ".koloni"),
        "git": not blocked and os.path.lexists(child / ".git"),
        "hidden": child.name.startswith(".") or bool(attributes & _HIDDEN),
        "blocked": blocked,
    }


def _shortcuts() -> list[dict]:
    home = Path.home()
    # shortcut: Desktop and Documents as folders of home; one Windows moved elsewhere (OneDrive)
    # is not found - read the known folders from the shell if that is missed.
    places = [(name, place) for name, place in (
        ("Home", home), ("Desktop", home / "Desktop"), ("Documents", home / "Documents"))
        if place.is_dir()]
    # The drives by their letters only: a network drive or an empty one would stall a look.
    drives = getattr(os, "listdrives", None)  # (Windows only)
    places += [(drive, Path(drive)) for drive in (drives() if drives else ["/"])]
    return [{"name": name, "path": str(place)} for name, place in places]


def _link_on_the_way(path: Path) -> Path | None:
    """The first link (or junction) from the drive's root down to `path`, each part looked at
    without following it; None: there is none."""
    return next((part for part in [*reversed(path.parents), path]
                 if part.is_symlink() or part.is_junction()), None)


@router.post("/browse", response_model=FolderBrowseOut,
             dependencies=[Depends(require_own_origin)])
def browse(body: FolderBrowseIn):
    """The folders in one folder, for the user to pick one from the app's own page (the
    browser does not give a folder's path): names only, never a file's, and at most
    MAX_LISTED. Nothing is listed in a place KOLONİ never opens."""
    raw = body.path or str(Path.home())
    # (A share or a device, in any spelling, before anything of it is looked at on disk.)
    if far_or_device(raw) or not Path(raw).is_absolute():
        raise HTTPException(422, f"{raw[:200]} is not a full path of this machine's")
    try:
        named = Path(os.path.abspath(raw))
        if link := _link_on_the_way(named):
            raise HTTPException(422, f"{str(link)[:200]} is a link: open where it leads")
        folder = named.resolve()  # (no link on the way: its long names, as they are)
        if far_or_device(str(folder)) or not folder.is_dir():
            raise HTTPException(422, f"{raw[:200]} is not an existing folder")
    except (OSError, ValueError) as exc:  # a NUL in it, or too long a path
        raise HTTPException(422, f"{raw[:200]} cannot be opened: {exc}") from None
    if why := _in_a_never_place(named) or _in_a_never_place(folder):
        raise HTTPException(422, f"{raw[:200]} is never opened: {why}")
    found = []
    try:
        with os.scandir(folder) as listing:
            for entry in listing:
                try:  # (one that cannot be looked at is left out; no link is followed)
                    attributes = getattr(
                        entry.stat(follow_symlinks=False), "st_file_attributes", 0)
                    link = entry.is_symlink() or entry.is_junction()
                    # A link is a folder's where it says so itself (Windows); else left out.
                    if (not attributes & stat.FILE_ATTRIBUTE_DIRECTORY if link
                            else not entry.is_dir(follow_symlinks=False)):
                        continue
                    found.append((entry.name, attributes, link))
                except OSError:
                    continue
    except OSError as exc:
        raise HTTPException(422, f"{raw[:200]} cannot be read: {exc.strerror or exc}") from None
    found.sort(key=lambda one: one[0].casefold())
    parts = [*reversed(folder.parents), folder]
    return {
        "path": str(folder),
        "parts": [{"name": part.name or part.anchor, "path": str(part)} for part in parts],
        "shortcuts": _shortcuts(),
        "entries": [_entry(folder / name, attributes, link)
                    for name, attributes, link in found[:MAX_LISTED]],
        "more": len(found) > MAX_LISTED,
    }
