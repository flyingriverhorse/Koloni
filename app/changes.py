"""Applying and reverting recorded file changes, never over content that moved on."""

import hashlib
from pathlib import Path, PurePath

from sqlalchemy import literal_column, select
from sqlalchemy.orm import Session

from app import attachments
from app.db.models import FileChange, Run, now
from app.workspace import (
    CliHome,
    Workspace,
    WorkspaceError,
    in_scratch,
    sha256_text,
    unified_diff,
)

# What a deletion stores where other changes store the digest of the new content.
DELETED_SHA = "deleted"


class ChangeConflict(Exception):
    """The file on disk is no longer what the change expects."""


# A file in a CLI's own folder: nothing grants it outside the one call the user said yes to.
# shortcut: so its change is not undone from here; give the revert a card if users want it.
NOT_HERE = "in a CLI's own folder"


def _current_sha(ws: Workspace, path: str, change: FileChange | None = None) -> str | None:
    """Digest of the file as it is now; an unreadable file matches nothing. For a file the
    user attached (`after_from`, slice 85b), of its bytes, as its change's are."""
    try:
        if change is not None and change.after_from:
            target = ws.resolve(path)
            return hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
        return sha256_text(ws.read_text_or_none(path))
    except CliHome:
        return NOT_HERE
    except (WorkspaceError, OSError):
        return "unreadable"


def apply_change(session: Session, ws: Workspace, change: FileChange,
                 runtime_root: Path | None = None) -> str:
    """Write the change if the file still has the content it was planned against.
    `runtime_root`: where KOLONİ keeps attached files - an attached file's change is written
    from there, found again by its id, never from where its record says (`attachments.path_of`).

    Returns the change's new status: "applied" or "conflict". If the disk refuses the
    write, the change is recorded as "failed" and the WorkspaceError is raised.
    """
    error: WorkspaceError | None = None
    if _current_sha(ws, change.path, change) != change.before_sha:
        change.status = "conflict"
    else:
        try:
            if change.kind == "delete":
                ws.delete(change.path)
            elif change.after_from:
                # (A new file, never one written over: one made meanwhile is a failure.)
                cid = session.get_one(Run, change.run_id).conversation_id
                kept = runtime_root and attachments.path_of(
                    runtime_root, cid, PurePath(change.after_from).name)
                try:
                    data = kept.read_bytes() if kept else None
                except OSError:
                    data = None
                if data is None:
                    raise WorkspaceError("the attached file is no longer kept")
                ws.write_new(change.path, data)
            else:
                ws.write_text(change.path, change.after_content)
            change.status = "applied"
        except WorkspaceError as exc:
            change.status, error = "failed", exc
    change.decided_at = now()
    session.commit()
    if error:
        raise error
    return change.status


def changed_since(change: FileChange, current: str | None) -> str | None:
    """Why the change cannot be reverted over a file whose digest is `current`; None if it can."""
    # A deletion is reverted only while the file is still gone.
    expected = None if change.kind == "delete" else change.after_sha
    if current == NOT_HERE:
        return (f"{change.path} can't be undone here: it is a CLI's settings for this whole "
                "computer, opened only on a card; change it back by hand")
    return None if current == expected else (
        f"{change.path} has changed since this edit; revert it by hand")


def would_revert(changes: list[FileChange], ws_for) -> list[str | None]:
    """For changes to be reverted in this order: why each would not be (None: it would), as
    if each one before it had been. Nothing is written. `ws_for(path)`: where a path is."""
    files: dict[str, str | None] = {}
    whys = []
    for change in changes:
        if change.path not in files:
            files[change.path] = _current_sha(ws_for(change.path), change.path, change)
        why = changed_since(change, files[change.path])
        if why is None:  # what `revert_change` would leave
            files[change.path] = sha256_text(
                None if change.kind == "create" else change.before_content or "")
        whys.append(why)
    return whys


def revert_change(session: Session, ws: Workspace, change: FileChange) -> None:
    """Put back what an applied change replaced, unless the file was edited since."""
    if change.status != "applied":
        raise ValueError("only an applied change can be reverted")
    if why := changed_since(change, _current_sha(ws, change.path, change)):
        raise ChangeConflict(why)
    if change.kind == "create":
        ws.delete(change.path)
    else:
        ws.write_text(change.path, change.before_content or "")
    change.status = "reverted"
    change.decided_at = now()
    session.commit()


def in_copy(session: Session, agent_ids: list[str]) -> list[dict]:
    """What these agents' working copy holds that the project does not, as its record has
    it (slice 70): each file once, from what it held when the copy took it to what its
    last change made it - {path, kind, diff, additions, deletions}, in path order. A file
    changed back to what it was is not one.
    shortcut: from the record, not the copy's files - a CLI's own writes are on it from its
    next look; read the copy itself (`copies.Copy.changes`) if that is seen to lag."""
    first: dict[str, FileChange] = {}
    last: dict[str, FileChange] = {}
    for row in session.scalars(
        select(FileChange).where(FileChange.agent_id.in_(agent_ids),
                                 FileChange.status == "in_copy")
        .order_by(FileChange.created_at, literal_column("file_changes.rowid"))
    ):
        if in_scratch(row.path):
            continue  # (as a Take in leaves it out: `copies._scan`)
        first.setdefault(row.path, row)
        last[row.path] = row
    files = []
    for path in sorted(first):
        before = first[path].before_content
        after = None if last[path].kind == "delete" else last[path].after_content
        if before == after:
            continue
        diff, additions, deletions = unified_diff(before, after or "", path)
        kind = "delete" if after is None else "create" if before is None else "modify"
        files.append({"path": path, "kind": kind, "diff": diff,
                      "additions": additions, "deletions": deletions})
    return files
