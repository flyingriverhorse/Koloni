import asyncio
import contextlib
import copy
import ctypes
import hmac
import io
import logging
import logging.config
import mimetypes
import os
import re
import secrets
import shutil
import sys
import time
import tomllib
import webbrowser
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from html import escape
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import backup as backups
from app import earlier, mcp_client, models_dev, raw, web
from app.agent import (
    AgentRunner,
    recover_copies,
    recover_interrupted,
    running_docker_commands,
)
from app.api import (
    agents,
    attachments,
    away,
    backlog,
    backup,
    board,
    builtin_tools,
    categories,
    commands,
    compares,
    conversations,
    day,
    discussions,
    events,
    file_changes,
    folders,
    health,
    hold,
    knowledge_page,
    local_server,
    mcp_servers,
    memory,
    merges,
    own_commands,
    projects,
    providers,
    questions,
    recipes,
    record,
    roles,
    rooms,
    runs,
    skills,
    teams,
    tiers,
    triggers,
    undo,
    usage,
    views,
    voice,
    web_requests,
)
from app.api.deps import carries_key, require_own_origin
from app.away import send as send_night
from app.config import Settings, load_settings
from app.db.models import Flag, McpServer, Project, Provider, now
from app.db.session import make_engine, make_session_factory, tidy_db, upgrade_db
from app.events import EventBus
from app.executors.docker import kill_containers
from app.local_server import LocalServer
from app.model_agy import sweep_homes
from app.model_client import ModelClient
from app.providers import Providers, search_apis, search_clients, seed_providers
from app.roles import seed_builtin_roles
from app.triggers import Triggers
from app.views import VIEWER_HEADERS


class NoWebhookKeys(logging.Filter):
    """A webhook's key is part of its address, and the server writes the address of every
    request into its access log: there, and in anything else the server logs, the key is
    replaced by "[key]" before the line is written anywhere. So is the page's key, where an
    address carries it (`?key=`, slice 94)."""

    _address = re.compile(r"(/api/hooks/|[?&]key=)[^/?#&\s\"']+", re.IGNORECASE)

    def _without(self, value: object) -> object:
        return self._address.sub(r"\1[key]", value) if isinstance(value, str) else value

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._without(record.msg)
        if isinstance(record.args, dict):
            record.args = {name: self._without(value) for name, value in record.args.items()}
        elif isinstance(record.args, tuple):
            record.args = tuple(self._without(value) for value in record.args)
        return True


class NoRawStreamReads(logging.Filter):
    """An open raw stream view asks for its agent's new lines every second. Those
    requests, when they were answered, are left out of the access log: one line a second
    for every open view would bury the rest. One that failed is logged like any other."""

    _address = re.compile(r"/api/agents/[^/?#]+/raw(\?|$)")

    def filter(self, record: logging.LogRecord) -> bool:
        # (client, method, address, HTTP version, status): what the server logs of a request.
        told = record.args
        return not (
            isinstance(told, tuple) and len(told) == 5 and told[1] == "GET" and told[4] == 200
            and isinstance(told[2], str) and self._address.match(told[2])
        )


class NoFrame:
    """No answer may be shown in another page's frame: a page of another origin could
    otherwise lay the app under its own and have the user click in it. Said in both of
    the ways browsers read, on every answer the app gives - but one whose own policy says
    who may frame it: a view's file (`app.views`), framed by the app alone."""

    HEADERS = (
        (b"content-security-policy", b"frame-ancestors 'none'"),
        (b"x-frame-options", b"DENY"),
    )

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def framed(message):
            if message["type"] == "http.response.start" and not any(
                name.lower() == b"content-security-policy" and b"frame-ancestors" in value.lower()
                for name, value in message.get("headers", ())
            ):
                message = {**message, "headers": [*message.get("headers", ()), *self.HEADERS]}
            await send(message)

        await self.app(scope, receive, framed if scope["type"] == "http" else send)


class PageKey:
    """Every request to the API carries the key this start made (slice 94): in the
    `X-KOLONI-Key` header, or `?key=` where a header cannot go (an event stream, an
    image's source; a download is fetched with the header, its address kept in the
    browser's list of downloads). One without it is answered before anything else is looked at: an
    agent's command can say any origin, but it does not know the key. What has a door of
    its own needs none: health, a webhook, the status line, and what a frame loads."""

    OWN_DOORS = re.compile(
        r"GET /api/health|POST /api/hooks/[^/]+|POST /api/limits/claude-session|POST /api/open"
        r"|GET /api/conversations/[^/]+/views/[^/]+/.*|GET /api/projects/[^/]+/raw/.*"
    )
    REFUSED = "open KOLONİ from the link in its window"

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if (
            scope["type"] == "http"
            and (path == "/api" or path.startswith("/api/"))
            and not self.OWN_DOORS.fullmatch(f"{scope['method']} {path}")
            and not self._carries(scope)
        ):
            await JSONResponse({"detail": self.REFUSED}, 401)(scope, receive, send)
            return
        await self.app(scope, receive, send)

    @staticmethod
    def _carries(scope) -> bool:
        return carries_key(scope)


SERVER_LOGS = ("uvicorn", "uvicorn.access", "uvicorn.error")
# How long the code the opened browser carries may be exchanged for the key (`open_code`).
OPEN_SECONDS = 120


def hide_webhook_keys() -> None:
    """Put the filter on the server's loggers, once. A filter on a logger sees only what
    is logged to that very logger, so each of them gets it. (And the access log gets the
    one that spares it the raw stream views' asking.)"""
    for name in SERVER_LOGS:
        logger = logging.getLogger(name)
        kinds = (NoWebhookKeys, NoRawStreamReads) if name.endswith("access") else (NoWebhookKeys,)
        for kind in kinds:
            if not any(isinstance(known, kind) for known in logger.filters):
                logger.addFilter(kind())


def opens_browser() -> bool:
    """A start from a terminal opens the page; a start without one (tests, e2e, REA's copy)
    or with `KOLONI_OPEN_BROWSER=0` does not."""
    return (sys.stdout is not None and sys.stdout.isatty()
            and os.environ.get("KOLONI_OPEN_BROWSER") != "0")


def open_code(state) -> str:
    """A code for the browser this start opens, good once and for `OPEN_SECONDS`: a browser
    it starts keeps the address on its command line, where an agent's command can read it -
    so the address carries this, which the page exchanges for the key (`POST /api/open`)."""
    code = secrets.token_urlsafe(32)
    state.open_code = (code, time.monotonic() + OPEN_SECONDS)
    return code


opening = APIRouter(prefix="/api", tags=["open"])


class OpenIn(BaseModel):
    code: str = Field(max_length=100)


class OpenOut(BaseModel):
    key: str


@opening.post("/open", response_model=OpenOut, dependencies=[Depends(require_own_origin)])
async def open_page(body: OpenIn, request: Request):
    """The page key, for the code the opened browser's address carries (`open_code`): once,
    in time, from the app's own page. Anything else is told as a request without the key is."""
    state = request.app.state
    code, until = getattr(state, "open_code", None) or ("", 0.0)
    # (As bytes: a str holding other than ASCII cannot be compared in constant time.)
    if not code or time.monotonic() > until or not hmac.compare_digest(
            body.code.encode(), code.encode()):
        raise HTTPException(401, PageKey.REFUSED)
    state.open_code = None
    return {"key": state.page_key}


def show_link(port: int, key: str, opening: Callable[[], str] | None = None) -> Callable[[], None]:
    """In the window, in place of uvicorn's "running on" line: the link that opens the page
    with its key - after "#", which a browser never sends. Printed, never logged: a log is
    kept, and read by more than the user. With `opening`, the page is opened once in a new
    tab of the default browser too, now that the server listens - with a one-time code of
    `opening`'s, never the key. Gives back what takes it away again."""
    # (uvicorn says "running on" at INFO: at a quieter level there is no line to replace.)
    logger = logging.getLogger("uvicorn.error")

    def instead(record: logging.LogRecord) -> bool:
        if not str(record.msg).startswith("Uvicorn running on"):
            return True
        print(f"KOLONİ is open at http://127.0.0.1:{port}/#key={key}", flush=True)
        if opening is not None:
            with contextlib.suppress(Exception):  # no browser: the printed link is enough
                webbrowser.open_new_tab(f"http://127.0.0.1:{port}/#open={opening()}")
        return False

    logger.addFilter(instead)
    return lambda: logger.removeFilter(instead)


def known_secrets(factory, settings: Settings) -> list[str | None]:
    """Every secret KOLONİ knows, to be kept out of what an agent's CLI wrote (`app.raw`):
    the providers' keys, the projects' notification addresses, the values of the MCP
    servers' variables and the keys in their arguments, the key of the model server it was
    started with, Gemini's voice key and Claude Code's status line key. (A webhook's key is
    kept nowhere: only its hash.)"""
    with factory() as session:
        servers = session.scalars(select(McpServer)).all()
        return [
            settings.model_api_key,
            *session.scalars(select(Provider.api_key)),
            *session.scalars(select(Project.notify_url)),
            *(value for server in servers for value in server.env.values()),
            *(key for server in servers for key in mcp_client.keys_in(server.command)),
            *session.scalars(select(Flag.value).where(
                Flag.name.in_((voice.KEY, providers.SESSION_KEY)))),
        ]


def create_app(
    settings: Settings,
    model: ModelClient | None = None,
    executors=None,
    clients: dict[str, ModelClient] | None = None,
    which=shutil.which,
) -> FastAPI:
    """Build the app. `model` stands in for every provider and `clients` for the
    providers they name (tests); `which` finds installed CLIs on the first start."""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # A container outlives the server that started it: stop the ones whose
        # commands the previous process left running.
        if stale_containers:
            await kill_containers(stale_containers)
        # Again here: by now the server has set its logging up, whatever it did to it.
        hide_webhook_keys()
        triggers = app.state.triggers
        triggers.attach(asyncio.get_running_loop())
        for note in closed_nights:
            send_night(note)
        # MCP servers' start folders a KOLONİ that did not end well left (97): off the loop,
        # and before any server of this one's starts.
        await asyncio.to_thread(mcp_client.sweep, settings.mcp_home)

        clock = None
        if settings.trigger_clock:
            # What came due while the app was off is looked at once, as missed; from
            # here on the clock is looked at every few seconds.
            with contextlib.suppress(Exception):
                # (What is on disk read off the loop: git and large folders take their time.)
                await triggers.look(now(), starting=True)
            clock = asyncio.create_task(triggers.run_forever(), name="triggers")
        # The turns that are over and not in the index of what was said: indexed beside
        # everything else, so that neither the start nor a request waits for them.
        indexing = asyncio.create_task(earlier.index_what_is_there(factory), name="earlier")
        # A catalogue a week old is downloaded again, beside everything else, unless the
        # user said not to.
        with factory() as session:
            fresh = session.get(Flag, models_dev.FRESH)
        refreshing = asyncio.create_task(
            models_dev.refresh(settings.runtime_root), name="catalogue",
        ) if settings.catalogue_refresh and (fresh is None or fresh.value != "0") else None
        yield
        indexing.cancel()
        await asyncio.gather(indexing, return_exceptions=True)
        if refreshing is not None:
            refreshing.cancel()
            await asyncio.gather(refreshing, return_exceptions=True)
        if clock is not None:
            clock.cancel()
            await asyncio.gather(clock, return_exceptions=True)
        await app.state.runner.shutdown()
        # The model server the user started here ends with KOLONİ: none is left on the card.
        await app.state.local_server.stop()
        triggers.attach(None)

    hide_webhook_keys()
    # A restore the user staged replaces the data before anything opens it (K-disa-aktar).
    backups.apply_staged(settings.runtime_root, lambda: upgrade_db(settings.db_path))
    upgrade_db(settings.db_path)
    tidy_db(settings.db_path)  # (after the migration's backup, before anything else opens it)
    factory = make_session_factory(make_engine(settings.db_path))
    # What a session reads the user's copy of the catalogue from (`app.api.usage`'s prices),
    # and how each provider last looked (`app.providers.looked_down`), one for every session.
    factory.configure(info={"runtime_root": settings.runtime_root, "looked_down": {}})
    stale_containers = running_docker_commands(factory)
    # (A night a restart ended says so in its chat; its one notification goes once the loop runs.)
    closed_nights: list = []
    recover_interrupted(factory, closed_nights)
    # No turn outlives the process: a working copy that is still there is deleted -
    # unless it holds changes that never reached the project.
    recover_copies(factory, settings.runtime_root)
    sweep_homes(settings.runtime_root / "agy-home")  # (as `providers` names it for agy)
    with factory() as session:
        seed_builtin_roles(session)
        seed_providers(session, settings, which)
    # No docs or schema served: they are outside /api, where no key is asked.
    app = FastAPI(
        title="KOLONİ", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.page_key = settings.page_key or secrets.token_urlsafe(32)
    # Innermost of the three: its refusal has NoFrame's headers; a wrong host is told so first.
    app.add_middleware(PageKey)
    # Loopback names only: a page on another origin cannot reach the API by pointing
    # its own host name at 127.0.0.1 (DNS rebinding).
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    # Added after it, so around it: the answer to a host that is not allowed has them too.
    app.add_middleware(NoFrame)

    @app.exception_handler(RequestValidationError)
    async def _invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Say what was wrong, never what was sent: a request body can hold an API key.
        problems = [
            {"loc": list(error.get("loc", ())), "msg": error.get("msg"), "type": error.get("type")}
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": problems})

    @app.exception_handler(Exception)
    async def _failed(request: Request, exc: Exception) -> PlainTextResponse:
        # The server's own answer to an error nobody caught goes out around every
        # middleware: this one, Starlette's very text, carries NoFrame's headers itself.
        return PlainTextResponse("Internal Server Error", 500, headers=dict(
            (name.decode(), value.decode()) for name, value in NoFrame.HEADERS))
    app.state.settings = settings
    app.state.session_factory = factory
    app.state.providers = Providers(
        settings, override=model, named=clients, session_factory=factory)
    # The CLIs a web search can fall back on: the user's own providers, read when asked.
    web.searchers = lambda: search_clients(factory)
    # ...and the Anthropic providers with a key, for the last way a search is tried.
    web.apis = lambda: search_apis(factory)
    # (and those given on a card this turn, slice 91 - and the page's own key, which drives
    # the whole API)
    raw.use(lambda: [*known_secrets(factory, settings), *app.state.runner.given_spellings(),
                     app.state.page_key])
    app.state.bus = EventBus(factory)
    app.state.runner = AgentRunner(
        settings, factory, app.state.bus, app.state.providers, executors
    )
    app.state.triggers = Triggers(factory, app.state.bus, app.state.runner, day.day_note)
    app.state.local_server = LocalServer(
        settings.runtime_root, settings.local_server, settings.nvidia_smi)
    # The unattended turns the previous process left open are told to their triggers.
    app.state.triggers.settle()
    for module in (
        health, projects, providers, roles, mcp_servers, skills, conversations, runs, file_changes,
        merges, commands, web_requests, agents, questions, discussions, rooms, memory, triggers,
        usage, record, folders, board, backlog, away, day, views, events, undo, voice, own_commands,
        tiers, compares, teams, recipes, local_server, categories, attachments, builtin_tools,
        hold, backup, knowledge_page,
    ):
        app.include_router(module.router)
    app.include_router(providers.catalogue_router)
    app.include_router(providers.session_router)
    app.include_router(opening)
    # Python reads these from Windows' registry, which some installers set to text/plain:
    # the page's modules were refused and it stayed blank (`views.TYPES` says the same).
    for end, kind in ((".js", "text/javascript"), (".mjs", "text/javascript"),
                      (".css", "text/css"), (".svg", "image/svg+xml"),
                      (".json", "application/json"), (".wasm", "application/wasm")):
        mimetypes.add_type(kind, end)
    _serve_guide(app, settings.guide_site)
    _serve_frontend(app, settings.frontend_dist)
    return app


GUIDE_NOT_BUILT = """<!doctype html><meta charset="utf-8"><title>KOLONİ guide</title>
<h1>The guide is not built yet</h1>
<p>Build it once in KOLONİ's folder, then reload this page:</p>
<pre>uv pip install -r pyproject.toml --extra docs
.venv/Scripts/zensical build   (macOS and Linux: .venv/bin/zensical build)</pre>
<p>Once Zensical is installed, scripts/update.ps1 and scripts/update.sh rebuild it on each
update.</p>
"""


# On the page key's origin: the theme's scripts may load more (mermaid, a lightbox, pyodide) from
# a CDN - none is let in. 'unsafe-inline' for the theme's own inline scripts; frame-ancestors in
# it keeps NoFrame from adding a second policy.
GUIDE_HEADERS = (
    (b"content-security-policy", b"; ".join([
        b"script-src 'self' 'unsafe-inline'", b"worker-src 'self'", b"connect-src 'self'",
        b"style-src 'self' 'unsafe-inline'", b"font-src 'self'", b"img-src 'self' data:",
        b"media-src 'self'", b"object-src 'none'", b"base-uri 'none'", b"frame-ancestors 'none'",
    ])),
    (b"x-content-type-options", b"nosniff"),
)


def _serve_guide(app: FastAPI, site: Path) -> None:
    """The user guide `zensical build` made, at /guide/, without the page key: like the page, it
    is public, read-only and no API. Looked for at each request, so a build needs no restart."""
    files = StaticFiles(directory=site, html=True, check_dir=False)
    online = None
    with contextlib.suppress(OSError, tomllib.TOMLDecodeError, KeyError):
        # (zensical.toml's site_dir is runtime/site: the file is two folders up.)
        online = tomllib.loads((site.parents[1] / "zensical.toml").read_text("utf-8"))[
            "project"].get("site_url")
    not_built = GUIDE_NOT_BUILT + (
        f'<p>Or read it online: <a href="{escape(online)}">{escape(online)}</a></p>'
        if online else "")

    async def guide(scope, receive, send):
        started = False

        async def guarded(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                message = {**message, "headers": [*message.get("headers", ()), *GUIDE_HEADERS]}
            await send(message)

        # A drive or a backslash is refused as text, before the file system is touched (a UNC
        # path would be dialled out to).
        if "\\" in scope["path"] or ":" in scope["path"]:
            answer = PlainTextResponse("Not Found", 404)
        elif not (site / "index.html").is_file():
            answer = HTMLResponse(not_built, 404)
        else:
            try:
                await files(scope, receive, guarded)
                return
            except (OSError, StarletteHTTPException) as error:
                # A name Windows will not look up (? * < | " or too long): not found, not a 500.
                # (Answered here, not by the app's handler: with the headers above.)
                if started:
                    raise
                status = getattr(error, "status_code", 404)
                answer = PlainTextResponse("Not Found" if status == 404 else "Refused", status)
        await answer(scope, receive, guarded)

    app.add_api_route("/guide", lambda: RedirectResponse("/guide/"), include_in_schema=False)
    # shortcut: Zensical's 404.html links its styles and pages under site_url's /manual/, which
    # the app does not serve, so a missing page here shows unstyled; rewrite its links if common.
    app.mount("/guide", guide)


def _serve_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built single-page app, if there is a build, from the same origin."""
    index = dist / "index.html"
    if not index.is_file():
        return
    root = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str):
        if path.startswith("api/") or path == "api":
            raise HTTPException(404, "not found")
        found = asset_path(root, path)
        # K-drawio: the diagram viewer's page is framed by the app, under a policy of its own - and
        # K-belge-ciktilari's document viewer (`frontend/public/office/`) the same.
        return FileResponse(found or index, headers=VIEWER_HEADERS
                            if found and path.lower().startswith(("drawio/", "office/")) else None)


def asset_path(root: Path, requested: str) -> Path | None:
    """The built file a URL path names, or None.

    The path is vetted as text before the file system is touched: on Windows a
    UNC or drive path would otherwise be opened (and a UNC path dialled out to) - and a part
    ending in a dot or a space is opened without it, so `office./viewer.html` would be the
    viewer's page served without its policy (K-belge-ciktilari review).
    """
    parts = requested.split("/")
    if not requested or any(
        not part or part in (".", "..") or "\\" in part or ":" in part
        or part != part.rstrip(". ") for part in parts
    ):
        return None
    candidate = root.joinpath(*parts)
    return candidate if candidate.is_file() else None


def not_dumpable() -> None:
    """On Linux, this process's /proc/<pid>/environ, fd and cwd closed to every other process
    of the user's - its children, an agent's commands, too (PR_SET_DUMPABLE 0): the kernel
    keeps the environment KOLONİ started with, KOLONI_PAGE_KEY with it though `load_settings`
    took it out, and `cat /proc/$PPID/environ` would print it. Called before any child is
    started; where it fails, the log says so and KOLONİ starts all the same.
    shortcut: a CLI given a provider's key in its own environment (`model_cli`) can still be
    read through its own /proc/<pid>/environ by the commands it runs; and macOS has no such
    call (`ps -E` shows a process's environment to its user) - hold those when it is met."""
    if not sys.platform.startswith("linux"):
        return
    try:
        if ctypes.CDLL(None, use_errno=True).prctl(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE, 0
            raise OSError(ctypes.get_errno(), "prctl(PR_SET_DUMPABLE) failed")
    except (OSError, AttributeError) as exc:
        logging.getLogger(__name__).warning(
            "KOLONİ's environment stays readable to its children (/proc): %s", exc)


# KOLONİ's own log beside the window's (0.1.0-hijyen), at most this many bytes × files.
LOG_BYTES = 10 * 1024 * 1024
LOG_FILES = 5


def log_config(runtime_root: Path) -> dict:
    """uvicorn's logging, and a file that rotates by size, `runtime/logs/koloni.log`, under
    the server's loggers (which reach no other) and every other's. Its keys are hidden as in
    the window: the filters sit on the loggers, before any handler."""
    import uvicorn.config

    (runtime_root / "logs").mkdir(parents=True, exist_ok=True)
    config = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
    config["formatters"]["file"] = {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}
    config["handlers"]["file"] = {
        "class": "logging.handlers.RotatingFileHandler", "formatter": "file", "encoding": "utf-8",
        "filename": str(runtime_root / "logs" / "koloni.log"),
        "maxBytes": LOG_BYTES, "backupCount": LOG_FILES,
    }
    for name in ("uvicorn", "uvicorn.access"):
        config["loggers"][name]["handlers"].append("file")
    # Everything else at WARNING, as before (an httpx line at INFO would carry its address);
    # KOLONİ's own at INFO.
    config["root"] = {"handlers": ["default", "file"], "level": "WARNING"}
    config["loggers"]["app"] = {"level": "INFO"}
    return config


# The addresses that are this machine only; anything else (0.0.0.0, ::) is the network's.
LOOPBACK = ("127.0.0.1", "::1", "localhost")


def bind_allowed(host: str, environ: Mapping[str, str] = os.environ) -> bool:
    """Whether KOLONİ may listen on `host`: this machine only, unless it runs in its image
    (KOLONI_IN_CONTAINER, set by the Dockerfile), whose port is published as 127.0.0.1:N:N."""
    return host in LOOPBACK or environ.get("KOLONI_IN_CONTAINER") == "1"


def run() -> None:
    import uvicorn

    not_dumpable()  # (first: before any child is started)
    settings = load_settings()
    if not bind_allowed(settings.host):
        sys.exit(f"KOLONİ serves your keys and files with no TLS: bind to this machine "
                 f"(KOLONI_HOST={settings.host} is not), or run the image.")
    # Before the app is made: what its start says (`tidy_db`) is in the log too.
    logging.config.dictConfig(log_config(settings.runtime_root))
    app = create_app(settings)
    # A pipe's encoding (cp1252 on Windows) has no "İ": the link is printed all the same.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(errors="replace")
    show_link(settings.port, app.state.page_key,
              (lambda: open_code(app.state)) if opens_browser() else None)
    uvicorn.run(app, host=settings.host, port=settings.port, log_config=None)  # (set up above)


if __name__ == "__main__":
    run()
