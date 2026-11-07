"""`.koloni/` in a folder (slice 86c): the folder's rules (`memory.RULES_FILE`) and settings,
kept in git with it. KOLONİ's own page writes it, when the user saves one of them - never on
opening a folder, never for an agent (`NOT_WRITTEN_UNATTENDED`) - but for the agents' scratch
(K-koloni-klasor): once `.koloni/tmp/` is there (an agent's write or command made it, or KOLONİ
needs it), `scratch` writes `.koloni/.gitignore` so git ignores it. What it holds is read as the
Files window reads a file: no link followed, no other name of a file elsewhere.
shortcut: `ProjectOut.koloni` reads two files per project each time projects are listed - slow
on a network drive; keep what was read by the files' times if that is met.

Plain functions: they read and write files.
"""

import contextlib
import json
import os
import time
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from app import memory, project_files
from app.schemas import KoloniAsks
from app.team import quoted
from app.views import Refused
from app.workspace import SCRATCH, has_other_names

FOLDER = ".koloni"
SETTINGS_FILE = f"{FOLDER}/settings.json"
# K-koloni-klasor: the agents' scratch in the folder - temp files, profiles, logs, downloads -
# read and written with no card (`workspace.standing_names`, `commands._path_parts`), not
# copied or taken in (`copies._scan`), ignored by git (`scratch`), and in no list of what a
# turn changed (`workspace.in_scratch`): `workspace.SCRATCH`.
# What KOLONİ itself last wrote in a folder's `.koloni/` (None: removed) and when (monotonic),
# by (the folder as it resolves, the path in it): no agent's doing, so not put back by a look
# whose snapshot is older (K-yazma-denetimi, `_put_back`).
WROTE: dict[tuple[str, str], tuple[bytes | None, float]] = {}
# What settings.json holds. Secrets, the user's own addresses and this machine's folders stay
# in KOLONİ's record alone.
SETTINGS = ("exec_location", "docker_image", "docker_network", "search_order")
INSTRUCTIONS = ("AGENTS.md", "CLAUDE.md")
_CHECKED = TypeAdapter(KoloniAsks)


def _text(root: str, rel: str) -> tuple[str | None, str | None]:
    """A file's text (None when it is not there or not read), and why it is not read."""
    try:
        read = project_files.text_of(root, rel)
    except Refused as refused:
        return None, None if str(refused) == "no such file" else str(refused)
    if read["text"] is not None:
        return read["text"], None
    return None, (f"it is larger than {project_files.MAX_READ_BYTES // 1024} KiB"
                  if read["too_large"] else "it is not text")


def _kept(root: str) -> tuple[dict | None, str | None]:
    """settings.json as it is written, every key of it (None when it is not there or not
    read), and why it is not read."""
    text, why = _text(root, SETTINGS_FILE)
    if text is None:
        return None, why
    try:
        # (PowerShell 5.1 starts the UTF-8 it writes with a byte order mark)
        found = json.loads(text.removeprefix("﻿"))
    except (ValueError, RecursionError) as exc:  # (`[[[…`: deeper than json.loads goes)
        return None, f"it is not valid JSON ({str(exc)[:200]})"
    return (found, None) if isinstance(found, dict) else (None, "it is not a JSON object")


def settings(root: str) -> tuple[dict | None, str | None]:
    """settings.json's values of SETTINGS, checked as `KoloniAsks` (None when it is not there
    or not read), and why it is not read."""
    found, why = _kept(root)
    if found is not None:
        try:
            found = dict(_CHECKED.validate_python(
                {k: found[k] for k in SETTINGS if k in found}, strict=True))  # ("yes": no bool)
        except ValidationError as exc:
            found, why = None, "; ".join(f"{e['loc'][0]}: {e['msg']}" for e in exc.errors())
    return found, why and f"{SETTINGS_FILE} is not read - {why}"


def state(project) -> dict:
    """What the folder's `.koloni/` holds, as Settings shows it: whether its files are
    read, its rules, why one is not read, and what settings.json asks for that is not what is
    saved - used only once the user says so (`asks`)."""
    values, why = settings(project.root_path)
    rules = memory.rules_file(project.root_path)[0]
    return {
        "settings_kept": values is not None,
        "rules_kept": rules is not None,
        "rules": rules or None,
        "broken": [line for line in (why and memory.UNREAD.format(why=why, what="settings"),
                                     memory.rules_unread(project.root_path)) if line],
        "asks": {k: v for k, v in (values or {}).items() if getattr(project, k) != v},
    }


def write(root: str, name: str, text: str | None) -> None:
    """Write (None: remove) a file of the folder's `.koloni/` - never through a link, never
    over another name of a file elsewhere. Refused (422) says why it was not."""
    rel = f"{FOLDER}/{name}"
    try:
        target = project_files._where(Path(root).resolve(), rel)
        if target.exists() and has_other_names(target):
            raise Refused(422, "it is another name of a file elsewhere")
        WROTE[(str(Path(root).resolve()), rel)] = (
            None if text is None else f"{text}\n".encode(), time.monotonic())
        if text is None:
            target.unlink(missing_ok=True)
            # (An empty .koloni/, or an empty .koloni/recipes/ in it, is not left behind.)
            for folder in target.parents[:name.count("/") + 1]:
                with contextlib.suppress(OSError):
                    folder.rmdir()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            # Whole or not at all: a half-written file would be broken for git and for the page.
            temp = target.with_name(f"{target.name}.koloni-tmp")
            temp.write_bytes(f"{text}\n".encode())  # (\n, not this machine's line end: git's)
            os.replace(temp, target)
    except (Refused, OSError) as exc:
        raise Refused(422, f"{rel} could not be written: {exc}") from None


def save_settings(root: str, changed: dict) -> None:
    """Put the settings the user changed into settings.json, keeping what else it says. One
    that is not read is left as it is (a hand's edit, a merge's conflict): the page says so,
    and what is saved in KOLONİ changes all the same."""
    if settings(root)[1] is None:
        write(root, "settings.json", json.dumps({**(_kept(root)[0] or {}), **changed},
                                                indent=2, ensure_ascii=False))


def save_rules(root: str, rules: str | None) -> None:
    """The same for rules.md: an empty one is taken away."""
    if memory.rules_file(root)[1] is None:
        write(root, "rules.md", rules)


# What `.koloni/.gitignore` holds for the scratch: the scratch, and the file itself - so that
# neither shows in `git status` (`?? .koloni/`) where the user keeps no other `.koloni` file.
# (Not `.git/info/exclude`: KOLONİ would write into the user's `.git`, which in a linked
# worktree is a file pointing elsewhere.)
IGNORED = ("tmp/", ".gitignore")


def scratch(root: str, made: bool = False) -> None:
    """Make the agents' scratch, `.koloni/tmp/` (`SCRATCH`), where KOLONİ needs it - or, `made`,
    only where an agent made it already (a look after its command or write) - and have git
    ignore it by `.koloni/.gitignore` (`IGNORED`, each line added once, the file's other lines
    kept). Never on opening a folder: an untouched project gets no `.koloni/`. A folder that
    cannot take it (a link, read-only) is left as it is: the scratch is a convenience."""
    with contextlib.suppress(Refused, OSError):
        place = project_files._where(Path(root).resolve(), SCRATCH)
        if made and not place.is_dir():
            return
        place.mkdir(parents=True, exist_ok=True)
        text, why = _text(root, f"{FOLDER}/.gitignore")
        lines = (text or "").splitlines()
        if why is None and (missing := [line for line in IGNORED if line not in lines]):
            write(root, ".gitignore", "\n".join([*lines, *missing]))


def instructions(root: str, part: str = "") -> str:
    """The folder's own instructions for agents - its AGENTS.md, else its CLAUDE.md - as the
    lead is given them: as one quoted string, which no heading in it can step out of; "" when
    it has neither. `part`: those of a part of it ("core/", K-buyuk-proje) instead.
    shortcut: at most MAX_RULES (1500) characters, as the user's rules; raise it when real
    AGENTS.md files are cut.
    shortcut: a command writes AGENTS.md or CLAUDE.md unasked at Full auto when it does not name
    it (`NOT_WRITTEN_UNATTENDED`'s shortcut) - and the next lead reads what it wrote."""
    for name in INSTRUCTIONS:
        text = (_text(root, part + name)[0] or "").strip()
        if text:
            cut = f" - only its first {memory.MAX_RULES} characters" if (
                len(text) > memory.MAX_RULES) else ""
            whose = f"The folder {quoted(part)}'s" if part else "This folder's"
            return (f"{whose} {name}, its instructions for agents working in it, the "
                    f"file's text as one quoted string{cut}:\n{quoted(text[:memory.MAX_RULES])}")
    return ""
