"""The agent's own browser (slice 51, `app.browser`): the browser_* tools, which sites it may
open and what a page may do unwatched, its screenshots, and view_image's copies of pictures
(and a CLI's own look at one) - `BrowserMixin`.
"""

import os
import re
import time
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from sqlalchemy import select

from app import attachments, browser, koloni, project_files, views
from app.agent.cards import _who
from app.agent.ctx import Ctx, _NobodyToAsk, _Transcript, _Watch
from app.agent.words import (
    IMAGE_EXT,
    IMAGE_HERE,
    IMAGE_MIME,
    IMAGE_SHOWN,
    NETWORK_OFF,
    WEB_REJECTED,
)
from app.commands import web_rules_here
from app.db.models import AllowedWeb, BacklogTask, Conversation, ShownFile, WebRequest
from app.tools import ToolError
from app.workspace import Workspace, WorkspaceError, is_secret

if TYPE_CHECKING:
    from app.agent import AgentRunner

# 28e: view_image - the largest image it reads.
IMAGE_MOST = 10 * 2**20

UNDER_STEP = " (the user sees it under the step: "  # (+ its copy's path and ")": `_picture`)

# B-345: the arguments of a CLI's own image look that name the file (`_own_look`).
LOOK_PATHS = ("path", "file_path", "AbsolutePath")

SITE_UNWATCHED = (
    "{host} is not opened: nobody is watching this turn (a trigger's, a job while the user is "
    "away or a backlog task's), and sites out on the internet are opened only while the user "
    "watches. "
    "That is the user's standing decision, not a tool error: do not try it another way. Go on "
    "with this machine's previews, and say in your report what you would have opened."
)

KEY_HELD = (
    "not pressed: on a site, a key goes into a password field (or a field KOLONİ cannot see, "
    "in a frame) only through browser_type, which asks the user"
)

PAGE_UNWATCHED = (
    "not done: to {what} waits for the user's yes, and nobody is watching this turn. That is "
    "the user's standing decision, not a tool error: do not try it another way. Go on with "
    "what you may do, and say in your report what you would have done."
)


def _number(args: dict, key: str) -> float | None:
    """A number argument of a browser tool; None when it is not given (or not a number)."""
    value = args.get(key)
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


class BrowserMixin:
    # --- the agent's own browser (slice 51, `app.browser`) -----------------------------

    async def _browser(self: "AgentRunner", ctx: Ctx, ws: Workspace, call_id: str, name: str,  # noqa: C901
                       args: dict) -> str:
        """A browser tool: on the agent's own headless browser, started at its first. Only
        this machine's previews are opened (`browser.allowed`) - nor is anything a page loads
        by itself that is not (`Browser._judge`); what was refused ends the result. Nobody is
        asked: it cannot reach out. K-tarayici-disari: a site out on the internet is opened
        too where the user allows it (`_site`), in a browser started for sites alone
        (`Browser.away`) - a preview and a site never share one: opening the other kind
        starts the browser anew, empty."""
        command = browser.find_browser()
        if command is None:
            raise ToolError(browser.NONE)
        try:
            site = browser.site_of(args.get("url")) if name == "browser_open" else None
        except browser.BrowserError as exc:
            raise ToolError(str(exc)) from None
        held = site is not None and await self._site(ctx, call_id, args["url"].strip(), site)
        if site is not None:
            try:  # (as `_web`: what the name stands for is looked up after the yes, not before)
                await browser.looked_up(args["url"].strip())
            except browser.BrowserError as exc:
                raise ToolError(str(exc)) from None
        one = self._browsers.get(ctx.agent_id)
        if one is not None and (one.gone or name == "browser_open" and one.away != bool(site)):
            # Ended where its fence no longer held (`Browser._die`): a new one only on an open.
            if name != "browser_open":
                raise ToolError(browser.ENDED + one.refused())
            self._browsers.pop(ctx.agent_id, None)
            await one.close()
            one = None
        try:
            if one is None:
                koloni.scratch(ctx.folder)  # (the scratch is made here, not as the agent opens)
                folder = self._scratch_folder(ctx)
                browser.sweep(folder, keep=set(self._browsers))
                one = browser.Browser(folder, ctx.agent_id)
                # (In the list while it starts: another agent's sweep keeps its profile then.)
                self._browsers[ctx.agent_id] = one
                try:
                    await one.start(command, ws, self._closed_ports(), away=site is not None)
                except BaseException:
                    self._browsers.pop(ctx.agent_id, None)
                    await one.close()
                    raise
            # (A provider added since: its port is closed from this call on.)
            one.closed = self._closed_ports() | {one.port or 0}
            if one.away:
                # A yes held for this browser (`_site`) lets its pages go on within the site.
                # A site on the list taken off it is out from this call; one marked Ask first
                # too, but for the one this call was just asked about.
                # shortcut: such a yes holds till the browser ends (the agent's work, or an
                # open of a preview); end it with the turn if that is seen to matter.
                rules = self._page_rules(ctx.cid)
                if held:
                    one.once.add(site)
                one.once -= {host for host, ask in rules.items() if ask and host != site}
                one.sites = frozenset(one.once) | {host for host, ask in rules.items() if not ask}
            if name == "browser_open" and site is not None:
                url = args["url"].strip()
                browser.outside(url, one.sites, one.closed, main=True)
                said = "opened " + await one.open(url)
            elif name == "browser_open":
                said = "opened " + await one.open(browser.allowed(args.get("url"), ws, one.closed))
            elif name == "browser_console":
                said = one.console()
            elif name == "browser_read":
                said = await one.read()
            elif name == "browser_screenshot":
                said = await self._shot(ctx, one, call_id, args.get("marks") is True)
            elif name == "browser_click":
                at, named = await one.point(args.get("selector"), args.get("text"),
                                            _number(args, "x"), _number(args, "y"),
                                            _number(args, "mark"))
                if one.away:
                    await self._page_stop(ctx, call_id, one, "click", await one.what(at=at))
                said = await one.click_at(at, named)
            elif name == "browser_type":
                if not isinstance(args.get("text"), str):
                    raise ToolError("missing required argument: text")
                said = await one.type(
                    args.get("selector"), args["text"],
                    (lambda found: self._page_stop(ctx, call_id, one, "type", found))
                    if one.away else None)
            elif name == "browser_key":
                if not isinstance(args.get("key"), str):
                    raise ToolError("missing required argument: key")
                key = args["key"]
                if one.away and (len(key) == 1 or key == "Enter"):
                    found = await one.what()
                    # (Else a password goes in a key at a time, past its card.)
                    if len(key) == 1 and browser.keys_held(found):
                        raise ToolError(KEY_HELD)
                    if key in ("Enter", " "):
                        await self._page_stop(ctx, call_id, one, "press", found)
                said = await one.key(args["key"])
            else:
                dy = _number(args, "dy")
                if dy is None:
                    raise ToolError("missing required argument: dy")
                said = await one.scroll(dy)
            return said + one.refused()
        except browser.BrowserError as exc:
            raise ToolError(str(exc) + (one.refused() if one else "")) from None

    async def _site(self: "AgentRunner", ctx: Ctx, call_id: str, url: str, host: str) -> bool:
        """K-tarayici-disari: whether the agent opens `host`, a site out on the internet
        (`browser.site_of`), as a web request is (the user's call, 3 Nov: "at Full auto it does
        not ask, but it depends on the site"): unasked where the project allows it, at any
        level; at Full auto unasked too, and not put on the list; a site marked Ask first on
        the web card at every level, Full auto too; any other below Full auto on the card.
        True: it is held for this browser alone (`Browser.once`) - This time, any yes for a
        marked site, or Full auto's. Never in a turn nobody watches - a trigger's, a night's
        job, a backlog task's: refused there, not asked."""
        with self._factory() as session:
            project = self._project(session, ctx.cid)
        # (As `_web`: the user took the network from this project - no tool is a way round.)
        if project is not None and project.exec_location == "docker" and not (
                project.docker_network):
            raise ToolError(NETWORK_OFF)
        if self._site_unwatched(ctx):
            raise _NobodyToAsk(SITE_UNWATCHED.format(host=host))
        marked = self._page_rules(ctx.cid).get(host)
        if marked is False:
            return False
        if marked is None and self._full_auto(ctx):
            return True
        asked = WebRequest(kind="page", method="GET", target=url, host=host)
        decision = await self._ask_web(ctx, call_id, asked)
        if decision == "reject":
            raise _NobodyToAsk(WEB_REJECTED.format(what="site"))
        # (Allow this site wrote the rule, which holds as it stands; a marked site's yes is
        # for this browser alone, whichever button.)
        return decision == "once" or marked is True

    async def _page_stop(self: "AgentRunner", ctx: Ctx, call_id: str, one: "browser.Browser",
                         action: str, found: object) -> None:
        """K-tarayici-disari A2: on a site's page, an action that sends a form, types into a
        password field or clicks words like Sign in or Pay (`browser.stop`) waits for the
        user's yes on the web card - at every level, Full auto too; refused where nobody
        watches, and on a no. A yes lets the form it sends go (`Browser.posting`)."""
        stopped = browser.stop(found, action)
        if stopped is None:
            return
        kind, said, host = stopped
        if self._site_unwatched(ctx):
            raise _NobodyToAsk(PAGE_UNWATCHED.format(what=said))
        asked = WebRequest(kind=kind, target=said, host=host or None)
        if await self._ask_web(ctx, call_id, asked) == "reject":
            raise _NobodyToAsk(WEB_REJECTED.format(what="action on the page"))
        if kind in ("form", "sign"):
            one.posting = time.monotonic() + browser.LOAD_WAIT

    def _site_unwatched(self: "AgentRunner", ctx: Ctx) -> bool:
        """Whether nobody watches this turn as far as sites go: a trigger's, a night's job's,
        or a backlog task's chat (K-tarayici-disari).
        shortcut: a backlog task's chat is told by its task, so a turn the user starts there
        by hand counts too; mark the turns the backlog starts if that is missed."""
        if not self._watched(ctx.run_id) or ctx.run_id in self._away_jobs:
            return True
        with self._factory() as session:
            return session.scalar(select(BacklogTask.id).where(
                BacklogTask.conversation_id == ctx.cid).limit(1)) is not None

    def _page_rules(self: "AgentRunner", cid: str) -> dict[str, bool]:
        """The sites the project's agents open (K-tarayici-disari), each with its Ask first
        mark, as they stand right now: a site held twice (the chat's and the project's) is
        asked about if either says so."""
        marks: dict[str, bool] = {}
        with self._factory() as session:
            for rule in session.scalars(web_rules_here(session.get_one(Conversation, cid))
                                        .where(AllowedWeb.kind == "page")):
                marks[rule.host] = marks.get(rule.host, False) or rule.ask_first
        return marks

    def _scratch_folder(self: "AgentRunner", ctx: Ctx, sub: str = "browser",
                        what: str = "the browser is not started there") -> Path:
        """`.koloni/tmp/<sub>` of the project, looked at from the root down: a link (a
        junction at .koloni/tmp) would put the profile and the screenshots outside it."""
        root = Path(ctx.folder).resolve()
        try:
            folder = project_files._where(root, f"{koloni.SCRATCH}/{sub}")
        except views.Refused:
            raise ToolError(f"the project's .koloni/tmp is a link: {what}") from None
        if not folder.resolve().is_relative_to(root):
            raise ToolError(f"the project's .koloni/tmp leads outside it: {what}")
        return folder

    def _view_image(self: "AgentRunner", ctx: Ctx, ws: Workspace, call_id: str, args: dict) -> str:
        """28e: an image of the project (or of the agent's copy), read as the view beside the
        chat reads a file (`views.read_file`: never outside, nor a secret, nor a hard link) and
        taken for one by its bytes, never its name. A copy of it under the scratch is shown
        to the model at its next step where it takes images (`_history`, as a screenshot is)
        and to the user under the step. Nobody is asked: it only reads, as read_file does."""
        path = args.get("path")
        if not isinstance(path, str):
            raise ToolError("missing required argument: path")
        try:
            rel = ws.rel(ws.resolve(path))
        except WorkspaceError as exc:
            raise ToolError(str(exc)) from None
        except (OSError, ValueError):  # (a name no file system takes: a NUL in it)
            raise ToolError(f"{path!r} is not a path of a file") from None
        # shortcut: a git-ignored image the agent's git copy left out is "no such file" here,
        # where read_file reaches it in the project (`_reads_left_out`); open it the same way
        # if agents in copies are seen to need one.
        if is_secret(rel) or not os.path.isabs(path) and is_secret(path):
            raise ToolError(f"{path!r} is a secret file (keys, passwords): it is never looked at")
        try:
            data = views.read_file(ws, rel, IMAGE_MOST)
        except views.Refused as exc:
            raise ToolError(f"{path!r} is over {IMAGE_MOST // 2**20} MB" if exc.status == 413
                            else f"{path!r}: {exc}") from None
        kind, mime = attachments.kind_of(data, rel)
        if kind != "image":
            raise ToolError(f"{path!r} is not an image by its bytes: PNG, JPEG, GIF or WebP")
        size = attachments.image_size(data)
        said = f"{size[0]}×{size[1]}" if size else "?×?"
        said += f", {attachments.size_text(len(data))}"
        in_result = bool(getattr(ctx.model, "session", False))  # (B-344: `IMAGE_HERE`)
        with self._factory() as session:
            takes, _without, most = self._takes(session, ctx, in_result)
        copy = self._image_copy(ctx, call_id, rel, data, mime)
        if "image" not in takes:
            return f"{_who(ctx)} does not take images; its size is {said}{copy}"
        if len(data) > most:  # (never more than the view serves: `_history` sends the copy)
            return (f"{rel}, {said}: over {attachments.size_text(most)}, too big to be shown "
                    f"to {_who(ctx)} as it is{copy}")
        if in_result:
            self._in_result[call_id] = (mime, data)
            return f"{rel}, {said}: {IMAGE_HERE}{copy}"
        if not copy.startswith(UNDER_STEP):  # (`_history` sends the copy: there is none)
            return f"{rel}, {said}: not shown to you{copy}"
        return f"{rel}, {said}: {IMAGE_SHOWN}{copy}"

    def _image_copy(self: "AgentRunner", ctx: Ctx, call_id: str, rel: str, data: bytes,
                    mime: str) -> str:
        """A copy of an image an agent looked at, under the scratch, put before the user under
        its call's step (`app.views` serves it under the call's id). What its result says of
        that, at its end: the copy (`UNDER_STEP`), or why there is none - too big for the view
        (R128), or not written. B-346: in a folder of the call's own, by the image's own
        name - what the step and the Workspace tab say - with its type's ending."""
        if len(data) > views.MAX_BYTES:
            return f" (too big to show under the step: over {views.MAX_BYTES // 2**20} MB)"
        # (Short of a file system's 255; a name the view would refuse - a device's, or one
        # that reads as a secret's once its signs are gone - is none of the image's own.)
        stem = re.sub(r"[^\w .()+-]", "_", PurePosixPath(rel).stem)[:100].strip(" .") or "image"
        name = f"{stem}.{IMAGE_EXT[mime]}"
        if views.DEVICES.fullmatch(name) or is_secret(name):
            name = f"image.{IMAGE_EXT[mime]}"
        folder = f"{ctx.agent_id[:8]}-{call_id[:8]}"
        # shortcut: the copies under .koloni/tmp/images are never swept (the browser's
        # screenshots are, after 7 days: `browser.sweep`); sweep them too if a project's
        # scratch is seen to grow.
        try:
            koloni.scratch(ctx.folder)
            target = self._scratch_folder(ctx, "images", "the image is not copied there") / folder
            target.mkdir(parents=True, exist_ok=True)
            (target / name).write_bytes(data)
        except OSError as exc:
            return (" (not shown under the step: its copy could not be written: "
                    f"{exc.strerror or exc})")
        copy = f"{koloni.SCRATCH}/images/{folder}/{name}"
        with self._factory() as session:
            session.add(ShownFile(id=call_id, conversation_id=ctx.cid, agent_id=ctx.agent_id,
                                  path=copy))
            session.commit()
        self.bus.emit(ctx.cid, ctx.run_id, "view.shown", {
            "id": call_id, "path": copy, "agent_id": ctx.agent_id, "note": None})
        return f"{UNDER_STEP}{copy})"

    def _own_look(self: "AgentRunner", ctx: Ctx, transcript: "_Transcript", watch: "_Watch",
                  call_id: str,
                  name: str, args: dict, said: str, under: str | None, unasked: bool) -> None:
        """B-347: a native CLI looked at an image with a tool of its own (`IMAGE_LOOKS`): its
        model saw it, so the user is shown it under that call as under a view_image's - an
        image by its name, then its bytes. A secret, or a file outside the project, is not
        copied; one KOLONİ was not asked about (`unasked`) gets a note in red, as KOLONİ could
        not stop it. Its model is told nothing."""
        path = next((given for key in LOOK_PATHS if isinstance(given := args.get(key), str)
                     and given), None)
        if path is None or os.path.splitext(path)[1].lower().lstrip(".") not in {
                *IMAGE_MIME, "jpeg"}:
            return
        ws = watch.copy.workspace() if watch.copy else Workspace(ctx.folder)
        try:
            rel = ws.rel(ws.resolve(path))
        except (WorkspaceError, OSError, ValueError):
            rel = None
        if rel is None or is_secret(rel):
            if not unasked:  # (it asked, and was let: an added folder, a card's yes)
                return
            # shortcut: an image KOLONİ handed it itself outside the project (an attachment's
            # copy) would be named here too; none is measured to be looked at with these tools.
            what = "outside the project folder" if rel is None else (
                "a secret file (keys, passwords)")
            self._note(ctx, transcript, "image_look", {"path": path}, "failed",
                       f"{name} showed its model {path!r}, {what}: KOLONİ cannot stop a CLI's "
                       "own tool; it is not copied for the user", parent=under)
            return
        try:
            data = views.read_file(ws, rel, IMAGE_MOST)
            kind, mime = attachments.kind_of(data, rel)
            copy = self._image_copy(ctx, call_id, rel, data, mime) if kind == "image" else ""
        except (views.Refused, ToolError, OSError):
            return  # (gone, too big, a hard link, or the scratch a link: nothing shown)
        if copy != "":
            self._set_call(ctx.cid, call_id, result=(said + copy).lstrip())

    async def _shot(self: "AgentRunner", ctx: Ctx, one: "browser.Browser", call_id: str,
                    marks: bool = False) -> str:
        """A screenshot: saved under the scratch for the user, put in the view beside the
        chat under the call's own id (`app.views` serves it there), and shown to the model
        at its next step where it takes images (`_history`) - a CLI session's in this result
        (B-344, as `_view_image`'s). With `marks` (K-gorsel-motor), numbered, and the list of
        the numbers first in the result."""
        data, listed = await one.screenshot(marks)
        name = f"{ctx.agent_id[:8]}-{call_id[:8]}.png"
        rel = f"{koloni.SCRATCH}/browser/shots/{name}"
        target = one.profile.parent / "shots" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        in_result = bool(getattr(ctx.model, "session", False))
        with self._factory() as session:
            takes, _without, most = self._takes(session, ctx, in_result)
            session.add(ShownFile(id=call_id, conversation_id=ctx.cid, agent_id=ctx.agent_id,
                                  path=rel))
            session.commit()
        self.bus.emit(ctx.cid, ctx.run_id, "view.shown", {
            "id": call_id, "path": rel, "agent_id": ctx.agent_id, "note": None})
        said = ((f"marks (for browser_click's mark): {listed}\n" if marks else "")
                + f"screenshot saved: {rel} (the user sees it beside the chat); ")
        if "image" not in takes:
            return said + ("your model is not known to see images, so it is not shown to you: "
                           "browser_read gives the page's text and outline")
        if not in_result:
            return said + IMAGE_SHOWN
        if len(data) > most:
            return said + (f"over {attachments.size_text(most)}, too big to be shown to you: "
                           "browser_read gives the page's text and outline")
        self._in_result[call_id] = ("image/png", data)
        return said + IMAGE_HERE
