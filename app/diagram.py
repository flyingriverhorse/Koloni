"""K-drawio: a draw.io diagram of the project as a picture beside it - `diagram.png` or
`diagram.svg` from `diagram.drawio`. Drawn by the draw.io viewer (Apache-2.0, vendored in
`frontend/public/drawio/` with KOLONİ's `koloni.js`): in the Workspace's frame (the user's "Save
as PNG / SVG", written by `write_picture`), or by an agent's `diagram_image` in the headless
browser of slice 51 (`draw`), on about:blank - its scripts evaluated into it, nothing loaded."""

import base64
import json
from pathlib import Path, PurePosixPath

from app import browser, project_files
from app.views import DIAGRAMS, Refused
from app.workspace import (
    Workspace,
    WorkspaceError,
    secret_in_project,
    stands_over_later_turns,
    write_bytes,
)

VIEWER = Path(__file__).resolve().parent.parent / "frontend" / "public" / "drawio"
# What `draw` evaluates, in this order: KOLONİ's file keeps the viewer from every address first.
SCRIPTS = ("koloni.js", "viewer-static.min.js")
FORMATS = ("png", "svg")
NOT_A_DIAGRAM = "{path} is not a draw.io file (.drawio, .drawio.xml or .dio)"
NO_BROWSER = ("this machine has no Chrome or Edge to draw it; the user can Save as PNG in the "
              "Workspace")
PNG = b"\x89PNG\r\n\x1a\n"
# The largest picture written: a PNG of a big diagram at twice its size.
MAX_PICTURE = 20 * 1024 * 1024


def is_diagram(path: str) -> bool:
    return path.lower().endswith(DIAGRAMS)


def picture_of(rel: str, format: str) -> str:
    """Where a diagram's picture goes: beside it, by its name - docs/flow.drawio.xml is
    docs/flow.png."""
    path = PurePosixPath(rel)
    name = next(path.name[: -len(end)] for end in DIAGRAMS if path.name.lower().endswith(end))
    return str(path.with_name(f"{name}.{format}"))


def write_picture(ws: Workspace, rel: str, format: str, data: bytes) -> str:
    """Writes the picture of the diagram `rel` (a project path) beside it, over an earlier one;
    its project path. WorkspaceError says why not: not a picture of that kind, too large, or a
    name that is a secret's or that later turns obey (.claude/, .git/...)."""
    if format not in FORMATS:
        raise WorkspaceError('the format is "png" or "svg"')
    if not is_diagram(rel):
        raise WorkspaceError(NOT_A_DIAGRAM.format(path=rel))
    if len(data) > MAX_PICTURE:
        raise WorkspaceError("the picture is larger than 20 MB: it is not written")
    if not (data.startswith(PNG) if format == "png"
            else data.lstrip().startswith((b"<?xml", b"<svg")) and b"<svg" in data[:4096]):
        raise WorkspaceError(f"that is not a {format.upper()} picture")
    out = picture_of(rel, format)
    if secret_in_project(out) or stands_over_later_turns(ws, out):
        raise WorkspaceError(f"{out} is not written here: later turns or the user's keys are "
                             "kept under that name")
    # Its name looked at part by part, as written: a link there (docs/flow.png -> ../.env, or a
    # junction for docs/) would have the picture written over what it leads to.
    try:
        named = project_files._where(Path(ws.root).resolve(), out)
    except Refused:
        named = None
    target = ws.resolve(out)
    if named is None or not ws.is_own(target) or named.resolve() != target:
        raise WorkspaceError(f"{out} is not written: a link, a secret or a place KOLONİ never "
                             "opens is on its way")
    try:
        write_bytes(target, data)
    except OSError as exc:
        raise WorkspaceError(f"could not write {out}: {exc.strerror or exc}") from None
    return out


async def draw(command: list[str], folder: Path, name: str, xml: str, format: str) -> bytes:
    """The diagram as a picture, drawn by the viewer in a headless browser of its own (its
    profile `folder/profile-<name>`, gone after) that loads nothing at all and resolves no
    name, loopback's neither (`Browser.start` with no project). BrowserError says why not."""
    # shortcut: a profile left by a KOLONİ killed mid-drawing stays in `folder` (`browser.sweep`
    # keeps to the agents' own); sweep it at start if such leftovers are seen to pile up.
    one = browser.Browser(folder, name)
    try:
        await one.start(command, None, set())
        for script in SCRIPTS:
            # (`void 0`: the script's last value is not sent back - it may be a function.)
            await one._eval(browser._tag("script", script)
                            + (VIEWER / script).read_text(encoding="utf-8") + "\n;void 0")
        made = await one._eval(browser._tag("drawio", format)
                               + f"koloniDraw({json.dumps(xml)}, {json.dumps(format)})", wait=True)
    finally:
        await one.close()
    if not isinstance(made, str):
        raise browser.BrowserError("the viewer drew nothing")
    if format == "svg":
        return made.encode("utf-8")
    head, _, body = made.partition(",")
    if head != "data:image/png;base64":
        raise browser.BrowserError("the viewer gave no PNG")
    return base64.b64decode(body)
