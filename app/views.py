"""What an agent wrote, or put before the user with `show`, to be seen beside the chat (slice
39): the conversation's views, and the files a view's frame is served.

A page an agent writes is untrusted: it is served under a policy of its own (`POLICY`) that
lets its script run in an origin of its own and reach nothing - neither the app nor the
outside. What it names beside itself is served from the folder it lies in, and nothing
outside the project by any name. (The app runs a page's script only once the user asks for
it: the frame is sandboxed without scripts until then.)

Everything here reads files and is called off the event loop (`app.api.views`).
"""

import hashlib
import os
import posixpath
import stat
from collections.abc import Callable
from pathlib import Path, PurePath, PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import attachments
from app.db.models import FileChange, Run, ShownFile
from app.project_view import UNREAD_FOLDERS, _is_link
from app.workspace import DEVICES, Workspace, WorkspaceError, has_other_names, is_secret

MAX_BYTES = 5 * 1024 * 1024
# A 3D model (slice 58), and the buffers a glTF names beside it, may be larger than a page.
MAX_MODEL_BYTES = 50 * 1024 * 1024
MODEL_FILES = (".stl", ".obj", ".gltf", ".glb", ".3mf", ".bin")
MAX_NOTE_CHARS = 200
KINDS = {
    ".html": "html", ".htm": "html", ".svg": "svg", ".md": "md",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image", ".webp": "image",
    ".stl": "model", ".obj": "model", ".gltf": "model", ".glb": "model", ".3mf": "model",
    ".pdf": "pdf",
    # K-belge-ciktilari: drawn by the renderer of each, in a frame of no origin (`OFFICE`).
    ".docx": "docx", ".xlsx": "xlsx", ".pptx": "pptx",
}
# R161: the kinds that read as something an agent made, as the canvas's output card counts them
# (`frontend/src/canvas/outputs.ts`): not a note (.md), written all the time.
MADE = frozenset({"html", "svg", "image", "model", "pdf", "docx", "xlsx", "pptx", "drawio"})
# R161: the most of them found after one command, and kept for one agent (`_record_made`); and
# the most entries a look after a command walks (as many as a copy holds: `copies.MAX_FILES`).
MOST_MADE = 200
MOST_WALKED = 20_000
# K-drawio: a draw.io diagram, drawn in a frame of the vendored viewer (`app.diagram`); by the
# end of its name, one of them two suffixes long.
DIAGRAMS = (".drawio.xml", ".drawio", ".dio")
# What a file is served as - said here, not guessed: Windows' registry can name .js and .css
# otherwise.
TYPES = {
    ".html": "text/html; charset=utf-8", ".htm": "text/html; charset=utf-8",
    ".svg": "image/svg+xml", ".md": "text/markdown; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8", ".json": "application/json",
    ".txt": "text/plain; charset=utf-8", ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
    ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf", ".otf": "font/otf",
    ".stl": "model/stl", ".obj": "model/obj", ".gltf": "model/gltf+json",
    ".glb": "model/gltf-binary", ".3mf": "model/3mf", ".mtl": "text/plain; charset=utf-8",
    ".bin": "application/octet-stream", ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
_OWN = "'self' 'unsafe-inline' 'unsafe-eval' data: blob:"
# Its own sandbox even opened alone; nothing reached by script, form or frame; what it draws
# with comes from itself or from beside it; framed by the app alone.
POLICY = "; ".join([
    "sandbox allow-scripts", "default-src 'none'", f"script-src {_OWN}", f"style-src {_OWN}",
    f"img-src {_OWN}", f"font-src {_OWN}", "connect-src 'none'", "form-action 'none'",
    "frame-src 'none'", "base-uri 'none'", "frame-ancestors 'self'",
])
HEADERS = {
    "Content-Security-Policy": POLICY,
    "X-Frame-Options": "SAMEORIGIN",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
    # Wherever it goes, it does not say where it was.
    "Referrer-Policy": "no-referrer",
}
# K-drawio: the draw.io viewer's own page (`frontend/public/drawio/`), framed by the app. Sandboxed
# as a view is, but stricter: its scripts are its own files alone - no inline script, no eval -
# and it reaches nothing; what a diagram names elsewhere (a picture, a font) is not loaded.
VIEWER_HEADERS = {
    **{name: value for name, value in HEADERS.items() if name != "Cache-Control"},
    "Content-Security-Policy": "; ".join([
        "sandbox allow-scripts", "default-src 'none'", "script-src 'self'",
        "style-src 'self' 'unsafe-inline'", "img-src 'self' data: blob:", "font-src 'self' data:",
        "connect-src 'none'", "form-action 'none'", "frame-src 'none'", "base-uri 'none'",
        "frame-ancestors 'self'",
    ]),
}
# K-belge-ciktilari: a pdf, drawn by the browser's own viewer - which a sandbox keeps out (Chrome
# draws no pdf in a sandboxed frame), as `default-src` / `object-src` may its embed. Its type,
# `application/pdf` with nosniff, is only ever the viewer's; the Workspace loads one only on the
# user's click. No script, form or base of the page's own.
# shortcut: the frame is KOLONİ's own origin, where the page key is - a flaw in the browser's pdf
# viewer (PDFium, pdf.js) would run there. Upgrade: serve pdfs from a loopback origin of their own,
# or draw them with pdf.js in a frame of no origin. And the policy is not seen in a real browser
# here (headless has no pdf viewer): REA's live check decides whether Chrome still draws under it.
PDF_HEADERS = {
    **{name: value for name, value in HEADERS.items() if name != "Content-Security-Policy"},
    "Content-Security-Policy": "script-src 'none'; form-action 'none'; base-uri 'none'; "
                               "frame-ancestors 'self'",
}


# K-belge-ciktilari: the documents the app reads itself and posts into the document viewer: on a
# keyless door, served only with the page's key (`api.deps.keyed_if_read_by_the_app`).
KEYED = frozenset(TYPES[end] for end in (".docx", ".xlsx", ".pptx"))
# (A document's or a pdf's answer is the app's own page's to read, no other site's.)
SAME_ORIGIN = {"Cross-Origin-Resource-Policy": "same-origin"}


def headers_of(kind: str) -> dict[str, str]:
    """The headers a file of this type is served with: a pdf's own, the rest a view's."""
    if kind == "application/pdf":
        return {**PDF_HEADERS, **SAME_ORIGIN}
    return {**HEADERS, **SAME_ORIGIN} if kind in KEYED else HEADERS


# A change whose text is, or will be, the file's: the rest are gone or never were.
LIVE = ("proposed", "approved", "in_copy", "applied")
NOT_ON_DISK_YET = ("proposed", "approved", "in_copy")

# A copy's files, by the agent whose line it is (`AgentRunner.copy_workspace`).
CopyOf = Callable[[str], Workspace | None]


class Refused(Exception):
    """A file is not served; `status` is the HTTP answer."""

    def __init__(self, status: int, why: str):
        super().__init__(why)
        self.status = status


def kind_of(path: str) -> str | None:
    if path.lower().endswith(DIAGRAMS):
        return "drawio"
    return KINDS.get(PurePosixPath(path).suffix.lower())


def made_here(rel: str) -> bool:
    """Whether a file a command left is one of an agent's outputs (R161): of a made kind, and
    not KOLONİ's own in `.koloni/`."""
    return kind_of(rel) in MADE and not rel.casefold().startswith(".koloni/")


def made_since(root: Path, since_ns: int) -> list[str]:
    """The files of a made kind (`made_here`) under `root` written at `since_ns` or later, by
    their path from it - as `ProjectView.changes` walks: not through a link, nor into others'
    code or build output (`UNREAD_FOLDERS`), nor into `.koloni/`.
    shortcut: by when each was written - one a command copies keeping its time (`cp -p`,
    `shutil.copy2`) is not found; compare digests if that is seen. And at most `MOST_WALKED`
    entries walked and `MOST_MADE` found: past them a project's outputs are not looked for."""
    found: list[str] = []
    walked = 0
    for folder, folders, files in os.walk(root):
        here = Path(folder)
        top = here == root
        folders[:] = [name for name in folders if name.casefold() not in UNREAD_FOLDERS
                      and not (top and name.casefold() == ".koloni") and not _is_link(here / name)]
        walked += len(folders) + len(files)
        if walked > MOST_WALKED:
            break
        for name in files:
            path = here / name
            if kind_of(name) not in MADE or _is_link(path):
                continue
            try:
                if path.stat().st_mtime_ns >= since_ns:
                    found.append(path.relative_to(root).as_posix())
            except OSError:
                continue
            if len(found) >= MOST_MADE:
                return found
    return found


def type_of(path: str) -> str | None:
    """What a file is served as, by its name (`TYPES`): a diagram as text - the app reads it,
    nothing draws it as what it says it is - and no other .xml at all."""
    if path.lower().endswith(DIAGRAMS):
        return "text/plain; charset=utf-8"
    return TYPES.get(PurePosixPath(path).suffix.lower())


def max_bytes(path: str) -> int:
    """The largest a file is served: a model's larger than a page's."""
    return MAX_MODEL_BYTES if PurePosixPath(path).suffix.lower() in MODEL_FILES else MAX_BYTES


def _key(path: str) -> str:
    """A path as the file system tells it from another: on Windows, in any case."""
    return path.casefold() if os.name == "nt" else path


def _changes(session: Session, cid: str) -> list:
    """The conversation's changes, oldest first, without their text: (id, path, agent_id,
    status, kind, after_sha, created_at)."""
    return list(session.execute(
        select(FileChange.id, FileChange.path, FileChange.agent_id, FileChange.status,
               FileChange.kind, FileChange.after_sha, FileChange.created_at)
        .join(Run, Run.id == FileChange.run_id).where(Run.conversation_id == cid)
        .order_by(FileChange.created_at, FileChange.id)
    ).all())


def _live(changes: list) -> dict:
    """Each path's newest change whose text is, or will be, the file's, by `_key`."""
    return {_key(change.path): change for change in changes if change.status in LIVE}


def _lines(session: Session, cid: str) -> list[dict]:
    """The conversation's views as on record - one for each path - without reading a file."""
    changes = _changes(session, cid)
    live = _live(changes)
    shown = session.scalars(
        select(ShownFile).where(ShownFile.conversation_id == cid)
        .order_by(ShownFile.created_at, ShownFile.id)
    ).all()
    records = [
        (c.created_at, c.id, c.path, c.agent_id, None) for c in changes
        if _key(c.path) in live and kind_of(c.path)
    ] + [(s.created_at, s.id, s.path, s.agent_id, s) for s in shown]
    lines: dict[str, dict] = {}
    for at, record_id, path, agent_id, show in sorted(records, key=lambda r: r[0]):
        line = lines.setdefault(_key(path), {
            "id": record_id, "path": path, "note": None, "copy_owner": None})
        line.update(agent_id=agent_id, at=at)
        if show is not None:
            line["copy_owner"] = show.copy_owner
            if show.note is not None:
                line["note"] = show.note
    out = []
    for key, line in lines.items():
        change = live.get(key)
        if kind_of(line["path"]) is None or (change is not None and change.kind == "delete"):
            continue
        out.append({**line, "kind": kind_of(line["path"]), "change": change})
    return out


def _where(root: str, copy_of: CopyOf, line: dict) -> Workspace:
    """Where a view's file lies on disk: in the working copy it was shown from while that
    copy is there, in the project otherwise."""
    copy = copy_of(line["copy_owner"]) if line["copy_owner"] else None
    return copy if copy is not None else Workspace(root)


# The digest of each file on disk read so far, by where it is: kept while its stamp - when it
# was last written, and its size - stays the same. The list is read every 2 s.
_digests: dict[str, tuple[tuple[int, int], str]] = {}


def _on_disk(ws: Workspace, rel: str) -> tuple[str | None, bool]:
    """The digest of a file on disk, and whether it is too large to be served."""
    try:
        target = ws.resolve(rel)
        status = target.stat()
    except (WorkspaceError, OSError, ValueError):
        return None, False
    if not stat.S_ISREG(status.st_mode):
        return None, False
    if status.st_size > max_bytes(target.name):
        return None, True
    stamp = (status.st_mtime_ns, status.st_size)
    known = _digests.get(str(target))
    if known is not None and known[0] == stamp:
        return known[1], False
    try:
        digest = hashlib.sha256(read_file(ws, rel)).hexdigest()
    except Refused:
        return None, False
    if len(_digests) > 4096:
        _digests.clear()  # (a bound, not a policy: each is read again when next asked for)
    _digests[str(target)] = (stamp, digest)
    return digest, False


def list_views(session: Session, cid: str, root: str, copy_of: CopyOf) -> list[dict]:
    """The conversation's views, newest first: one line for each path."""
    out = []
    for line in _lines(session, cid):
        change = line.pop("change")
        if change is not None and change.status in NOT_ON_DISK_YET:
            sha, too_large = change.after_sha, False
        else:
            sha, too_large = _on_disk(_where(root, copy_of, line), line["path"])
        out.append({
            **line, "status": change.status if change else "shown", "sha": sha,
            "too_large": too_large, "url": f"/api/conversations/{cid}/views/{line['id']}/"
            + PurePosixPath(line["path"]).name,
        })
    return sorted(out, key=lambda line: line["at"], reverse=True)


def _vetted(name: str) -> str:
    """A name asked for beside a page, as text, before the file system is touched: no
    drive, no UNC path, no way up, no backslash (`app.main.asset_path`) - and nothing
    Windows would open as something else: no control character, no device's name, no
    part that ends in a dot or a space (Windows drops those)."""
    parts = name.split("/")
    if not name or any(
        not part or part in (".", "..") or "\\" in part or ":" in part
        or any(ord(c) < 32 for c in part) or part.endswith((".", " "))
        or DEVICES.fullmatch(part)
        for part in parts
    ):
        raise Refused(400, "not a name of a file beside the page")
    return name


def read_file(ws: Workspace, rel: str, limit: int | None = None) -> bytes:
    """A file of the project (or of a copy) as it is now: never one outside it, by a link
    or by another name of the same file (a hard link), nor one larger than `max_bytes` - nor a
    secret (`is_secret`), by its name or by a short name that leads to it (`ENV~1`). `limit`:
    another largest than `max_bytes` (28e: an image an agent looks at)."""
    try:
        target = ws.resolve(rel)
    except (WorkspaceError, ValueError):
        raise Refused(404, "not in the project") from None
    if is_secret(rel) or is_secret(ws.rel(target)) or has_other_names(target):
        raise Refused(404, "not in the project")
    # (by the name it has, as its type is: `project_files.raw`)
    limit = limit or max_bytes(target.name)
    try:
        # shortcut: resolved, then opened by its name - a link put in its place between the
        # two is followed. Accepted: whoever can put one there can read the file anyway;
        # upgrade to opening each part without following links if that stops being so.
        with open(target, "rb") as file:
            status = os.fstat(file.fileno())
            # Counted on the open file too: a link made after the look above is caught here.
            if not stat.S_ISREG(status.st_mode) or status.st_nlink > 1:
                raise Refused(404, "not a file of the project")
            if status.st_size > limit:
                raise Refused(413, "too large to show")
            return file.read(limit + 1)
    except OSError:
        raise Refused(404, "no such file") from None


def serve(
    session: Session, cid: str, root: str, runtime_root: Path, copy_of: CopyOf, view_id: str,
    name: str, version: str | None = None,
) -> tuple[bytes, str]:
    """A file a view's frame asks for - the page itself, or one beside it - and its type.
    That one file is read, and no other. `version`: the `?v=<sha>-<status>` the list put on
    the page's address (`srcOf`)."""
    line = next((line for line in _lines(session, cid) if line["id"] == view_id), None)
    if line is None:
        raise Refused(404, "no such view in this conversation")
    rel = posixpath.join(posixpath.dirname(line["path"]), _vetted(name))
    change = _live(_changes(session, cid)).get(_key(rel))
    if change is not None and change.kind == "delete":
        raise Refused(404, "no such file")
    # A change come after the list was read is not served under the address of the text before
    # it: turned down, the next list gives that same address and the frame would keep its text.
    if change is not None and change.status in NOT_ON_DISK_YET and (
            version is None or version.startswith(f"{change.after_sha}-")):
        row = session.get_one(FileChange, change.id)
        if row.after_from:
            # An attached file saved into the project (85b): its text is a line saying what it is,
            # its bytes KOLONİ's own copy - found again by its id in KOLONİ's store, never where
            # the record says (a record restored from elsewhere could name any file).
            kept = attachments.path_of(runtime_root, cid, PurePath(row.after_from).name)
            if kept is None:
                raise Refused(404, "no such file")
            try:
                with open(kept, "rb") as file:
                    data = file.read(max_bytes(rel) + 1)
            except OSError:
                raise Refused(404, "no such file") from None
            if len(data) > max_bytes(rel):
                raise Refused(413, "too large to show")
        else:
            data = row.after_content.encode("utf-8")
    else:
        data = read_file(_where(root, copy_of, line), rel)
    kind = type_of(rel) or "application/octet-stream"
    return data, kind


def check_shown(ws: Workspace, path: str) -> str:
    """The project path of a file an agent asks to show; WorkspaceError says why not."""
    target = ws.resolve(path)  # never outside the project, by any name or link
    if kind_of(target.name) is None:
        raise WorkspaceError(
            f"{path!r} is not a kind that can be shown: a page (.html, .htm), a drawing "
            "(.svg), a note (.md), a picture (.png, .jpg, .gif, .webp), a 3D model (.stl, .obj, "
            ".gltf, .glb, .3mf), a draw.io diagram (.drawio, .drawio.xml, .dio) or a document "
            "(.pdf, .docx, .xlsx, .pptx)")
    if not target.is_file():
        raise WorkspaceError(f"{path!r} does not exist")
    if has_other_names(target):
        raise WorkspaceError(f"{path!r} is a hard link: it may be a file outside the project")
    if is_secret(ws.rel(target)) or not os.path.isabs(path) and is_secret(path):
        # The view never serves a secret, by any part of its path (`read_file`): a page
        # beside it could send it on, and shown it would not be there.
        raise WorkspaceError(f"{path!r} is a secret file (keys, passwords): it is never shown")
    return ws.rel(target)
