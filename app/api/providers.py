import asyncio
import hmac
import json
import re
import secrets
import shlex
import shutil
import sys
from datetime import UTC, datetime
from ipaddress import ip_address, ip_network
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit

import httpx2
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import catalog, limits, models_dev
from app.api.deps import get_session, require_origin, require_own_origin
from app.config import REPO_ROOT, THIS_MACHINE
from app.db.models import Agent, Conversation, Flag, OwnRequest, Price, Project, Provider, Role, now
from app.limits import CLI_HOMES, PROVIDER_ID, account, cli_home, of_session
from app.model_cli import HOMES
from app.model_client import UNREACHABLE, ModelUnavailable, OpenAICompatClient, OwnStop
from app.providers import (
    ANTHROPIC_URL,
    CLAUDE_MODELS,
    CLI_COMMANDS,
    CLI_NAMES,
    HTTP_KINDS,
    KINDS,
    LIST_DOWN_SECONDS,
    MAX_MODEL_NAME,
    MODES,
    ONLY,
    SERVER_CLIS,
    ask_own,
    check_guide,
    check_options,
    find_provider,
    list_providers,
    looked_down,
    mode_of,
)
from app.roles import plain_name
from app.schemas import (
    AvailabilityOut,
    CatalogueFillIn,
    CatalogueFillOut,
    CatalogueFreshIn,
    CatalogueUpdateOut,
    ClaudeSessionSetupOut,
    FillAllIn,
    FillAllOut,
    FillAllProvider,
    LimitsOut,
    ModelFactsOut,
    ProviderIn,
    ProviderModelsOut,
    ProviderOut,
    ProviderPatch,
    ProviderTestOut,
    SuggestIn,
    SuggestOut,
)

router = APIRouter(prefix="/api/providers", tags=["providers"])
catalogue_router = APIRouter(prefix="/api/catalog", tags=["providers"])
session_router = APIRouter(prefix="/api/limits", tags=["providers"])

MAX_NAME = 60
# A provider's limits (slice 81c): set from its window's Limits tab only.
LIMITS = ("plan", "step_down_at", "day_limit", "month_limit")


def _provider(session: Session, provider_id: str) -> Provider:
    provider = session.get(Provider, provider_id)
    if provider is None:
        raise HTTPException(404, "provider not found")
    return provider


def _name(session: Session, name: str, own_id: str | None = None) -> str:
    try:
        name = plain_name(name, "a provider name")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if not name:
        raise HTTPException(422, "name is empty")
    if len(name) > MAX_NAME:
        raise HTTPException(422, f"a provider name has at most {MAX_NAME} characters")
    other = find_provider(session, name)
    if other and other.id != own_id:
        raise HTTPException(409, f"there is already a provider named {other.name}")
    return name


def _text(value: str | None) -> str | None:
    """A trimmed setting; empty means not set."""
    return (value or "").strip() or None


def _model(value: str | None) -> str | None:
    """A model name: any printable text, on one line."""
    name = _text(value)
    if name and not name.isprintable():
        raise HTTPException(422, "a model name cannot contain line breaks or control characters")
    return name


def _key(value: str | None) -> str | None:
    """An API key as it will go into a request header. The refusal never repeats it."""
    key = _text(value)
    if key and not (key.isascii() and key.isprintable() and " " not in key):
        raise HTTPException(
            422,
            "the key has characters a key cannot contain (spaces, line breaks or "
            "non-ASCII characters); paste it again",
        )
    return key


# Kinds that speak to a model server at an address, with a key: the HTTP ones, and
# Copilot when it is given a model server of your own.
SERVED = (*HTTP_KINDS, "copilot_cli")


# This machine and the local network, and nothing else (no 0.0.0.0, no 169.254.x: a cloud's
# metadata address, no reserved range).
NEARBY = [ip_network(net) for net in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "::1/128", "fc00::/7", "fe80::/10")]


def _nearby(url: str) -> bool:
    """Whether an address is a plain one (no user, query or quote: it goes into Codex's TOML
    and onto a command line) of this machine or of one on its local network, ending in the
    server's /v1 (Codex speaks to it there; Claude Code beside it).
    shortcut: a LAN machine by its IP only, as a name could resolve anywhere; resolve names
    if one is asked for."""
    if not re.fullmatch(r"https?://[\w.:\[\]-]+(/[\w.~/-]*)?/v1", url, re.ASCII):
        return False
    try:
        parts = urlsplit(url)
        parts.port  # noqa: B018 - a port that is no number, or out of range, is refused
        host = parts.hostname or ""
        return host == "localhost" or any(ip_address(host) in net for net in NEARBY)
    except ValueError:
        return False


# CLIs a model server can be set for, where their work and a key then go: set only from
# the app's own page, never by a command an agent runs against the app's address.
ROUTED = (*SERVER_CLIS, "copilot_cli")


def _address(kind: str, base_url: str | None) -> str | None:
    if kind not in (*SERVED, *SERVER_CLIS):
        return None
    url = (_text(base_url) or (ANTHROPIC_URL if kind == "anthropic" else "")).rstrip("/")
    if not url and kind in ("copilot_cli", *SERVER_CLIS):
        return None  # on the user's own sign-in (Copilot: a token, or else their gh login)
    if not url:
        raise HTTPException(422, "this kind of provider needs an address")
    if not url.startswith(("http://", "https://")):
        raise HTTPException(422, "the address must start with http:// or https://")
    # (Not Copilot's: a model server of its own may be remote; who may point it is the
    # page's alone - `ROUTED`.)
    if kind in SERVER_CLIS and not _nearby(url):
        raise HTTPException(422, "the model server has to be on this machine or your local "
                                 "network, by its IP address, and end in /v1 "
                                 "(http://127.0.0.1:8080/v1)")
    return url


NOT_SIGNED_IN = (
    "Copilot is not signed in: run `gh auth login` (or sign in in Copilot itself) and try again."
)


async def _copilot_signed_in(provider: Provider) -> bool | None:
    """Whether Copilot on a GitHub account is signed in (`auth.getStatus`, no session, no
    turn); None on a model server of one's own, or when it could not be asked."""
    if provider.base_url:
        return None
    try:
        told = await limits.copilot_signed_in(
            provider.executable, provider.api_key, limits.SECONDS)
    except (ModelUnavailable, TimeoutError):
        return None
    return told["isAuthenticated"]


def _login(kind: str, executable: str | None, home: Path) -> dict:
    """The CLI's own sign-in command (catalog.json's) for the user's PowerShell and for
    cmd.exe (for sh off Windows), with the provider's sign-in folder set first: its login lands
    there, and KOLONİ never sees it."""
    def quoted(text: str) -> str:
        # PowerShell takes the curly single quotes for one too (U+2018-U+201B).
        return "'" + re.sub(r"(['\u2018-\u201b])", r"\1\1", text) + "'"

    told = catalog.sign_in(kind)
    assert told is not None  # (catalog.json has Claude Code's and Codex's)
    first, rest = told["command"].split(" ", 1)
    variable = HOMES[CLI_COMMANDS[kind]]
    if sys.platform != "win32":
        command = f"{shlex.quote(executable) if executable else first} {rest}"
        return {"command": f"{variable}={shlex.quote(str(home))} {command}", "docs": told["docs"]}
    command = f"& {quoted(executable)} {rest}" if executable else f"{first} {rest}"
    login = {"command": f"$env:{variable}={quoted(str(home))}; {command}", "docs": told["docs"]}
    # cmd.exe cannot quote a '"', expands a '%' even in quotes, and runs each pasted line: no
    # cmd form for such a path.
    if not re.search(r'["%\r\n]', f"{executable or ''}{home}"):
        command = f'"{executable}" {rest}' if executable else f"{first} {rest}"
        login["cmd"] = f'set "{variable}={home}"\n{command}'
    return login


def _options(kind: str, options: dict | None, base_url: str | None) -> dict | None:
    try:
        return check_options(kind, options, bool(base_url))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


def _guide(provider: Provider, note: str | None, models: list | None) -> None:
    """Set what agents are told about a provider; a 422 says what is wrong with it."""
    told = [model if isinstance(model, dict) else model.model_dump(exclude_unset=True)
            for model in models or []]
    try:
        provider.note, listed = check_guide(
            note, told, tiered=provider.kind == "copilot_cli" and not provider.base_url)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    # A model keeps its place in its tier's order (app.api.tiers) while it keeps its tier;
    # one given another tier has none there, so it comes last in it. A row that does not say
    # whether agents may use it keeps what it was; a new one says what its provider does.
    was = {m["name"]: m for m in provider.models or []}
    unsaid = {str(row.get("name", "")).strip() for row in told if "agents" not in row}
    unmarked = {str(row.get("name", "")).strip() for row in told if row.get("inputs") is None}
    untiered = {str(row.get("name", "")).strip() for row in told if "context" not in row}
    unswitched = {str(row.get("name", "")).strip() for row in told if "enabled" not in row}
    for m in listed:
        old = was.get(m["name"], {})
        if m["tier"] and old.get("tier") == m["tier"] and "order" in old:
            m["order"] = old["order"]
        if m["name"] in unsaid:
            m["agents"] = old.get("agents", provider.for_agents)
        # (A row that says nothing of its inputs keeps those it had; [] takes them off.)
        if m["name"] in unmarked and old.get("inputs") is not None:
            m["inputs"] = old["inputs"]
        # (Nor of its context tier: a catalogue's fill does not know it.)
        if m["name"] in untiered and "context" in old:
            m["context"] = old["context"]
        # (Nor of being switched off: a fill, or a page from before, does not turn it on.)
        if m["name"] in unswitched and "enabled" in old:
            m["enabled"] = old["enabled"]
        # (B-396: why KOLONİ switched it off stands while it is off; switched on, it goes.)
        if m.get("enabled") is False and old.get("off_why"):
            m["off_why"] = old["off_why"]
    provider.models = listed or None


def _agents_follow(provider: Provider, body: ProviderIn | ProviderPatch) -> None:
    """Whether agents may choose the provider follows its models (slice 81a), when the models
    sent say it of themselves: on while one of them is agents', off when none is - unless the
    request said it itself (fill-all does). A request that does not speak of it leaves it.
    shortcut: a provider with no list keeps the flag it had (its default model is all an agent
    could pick there); give the default model a flag of its own if that is ever asked."""
    said = any("agents" in m.model_fields_set for m in body.models or [])
    if said and "for_agents" not in body.model_fields_set and provider.models:
        provider.for_agents = any(m["agents"] for m in provider.models)


def _listed(provider: Provider) -> None:
    """"Only these models" means something only while there is a list."""
    if provider.only_listed and not provider.models:
        raise HTTPException(
            422, f'"{ONLY}" needs at least one model in the list'
        )


async def served_models(base_url: str, key: str | None) -> list[str]:
    """The model names a server at this address lists."""
    return await OpenAICompatClient(base_url, key).models()


def _mode(kind: str, mode: str | None, server: str | None = None) -> str | None:
    """How a CLI provider is run; only the ways that kind can safely run are accepted."""
    allowed = MODES.get(kind)
    if allowed is None:
        return None
    if not mode:
        # shortcut: Codex as a session on a model server of the user's is not measured
        # (`CodexSessionClient`), so there it starts as a step; drop this once it is.
        return "step" if kind == "codex_cli" and server else allowed[0]
    if mode not in allowed:
        name = CLI_NAMES[kind]
        if kind == "agy_cli":
            raise HTTPException(
                422,
                "agy cannot run with KOLONİ's tools: it can be given a tool server only by "
                "a change to your own agy settings. It runs with its own tools, reading "
                "only or natively",
            )
        raise HTTPException(422, f"{name} cannot run in {mode!r} mode")
    return mode


def apply_choice(session: Session, target: Conversation | Role, body) -> None:
    """Set or clear a conversation's or role's model choice from a patch body.

    Only fields the request actually sent are touched; a null provider clears both.
    """
    sent = body.model_fields_set
    if "provider_id" in sent:
        if body.provider_id is None:
            target.provider_id, target.model_id = None, None
        else:
            if session.get(Provider, body.provider_id) is None:
                raise HTTPException(422, "unknown provider")
            target.provider_id = body.provider_id
            if "model_id" not in sent:
                target.model_id = None  # another provider's model name means nothing here
    if "model_id" in sent and target.provider_id is not None:
        target.model_id = _model(body.model_id)


@router.get("", response_model=list[ProviderOut])
def get_providers(session: Session = Depends(get_session)):
    return list_providers(session)


@router.get("/{provider_id}/limits", response_model=LimitsOut)
async def get_limits(
    provider_id: str, request: Request, session: Session = Depends(get_session)
):
    """What is known of what is left of the provider's plan: what was last read, by Codex,
    Claude Code, the user's own Claude Code session, agy or Copilot. Only agy and Copilot,
    which say it without a model turn, are asked for it - in the background, at most once
    in ten minutes (`Limits.refresh`); this answers at once."""
    provider = _provider(session, provider_id)
    limits = request.app.state.providers.limits
    limits.refresh(provider)
    return limits.last(provider)


@router.post(
    "/{provider_id}/limits/check", response_model=LimitsOut,
    dependencies=[Depends(require_own_origin)],
)
async def check_limits(
    provider_id: str, request: Request, session: Session = Depends(get_session)
):
    """The same, read afresh: Codex is asked (no model is called), Claude Code runs one
    short turn. The user's, from the app's own page: a command an agent runs cannot have
    it started. Not one switched off: Claude Code's would be a model turn."""
    provider = _provider(session, provider_id)
    if provider.enabled is False:
        raise HTTPException(409, f"{provider.name} is switched off")
    return await request.app.state.providers.limits.read(provider)


SESSION_BYTES = 4096
STATUS_LINE = REPO_ROOT / "scripts" / "koloni_statusline.py"
# The key the status line command carries (`Flag`, as Gemini's voice key is: it is shown
# again each time the setup is), and the header it comes back in.
SESSION_KEY = "claude_session_key"
KEY_HEADER = "x-koloni-key"


def session_key(factory, make: bool = False) -> str | None:
    """The status line's key; made the first time the setup is asked for (`make`)."""
    with factory() as session:
        flag = session.get(Flag, SESSION_KEY)
        if flag is None and make:
            try:
                session.add(Flag(name=SESSION_KEY, value=secrets.token_hex(32)))
                session.commit()
            except IntegrityError:  # made meanwhile by another asker: that one is the key
                session.rollback()
            flag = session.get(Flag, SESSION_KEY)
        return flag.value if flag else None


@session_router.post("/claude-session", status_code=204)
async def claude_session(request: Request) -> Response:
    """What is left of Claude Code's plan, as the status line of the user's own Claude
    Code session said it (`scripts/koloni_statusline.py` sends it, with the key of its
    setup). Only from a program on this machine: a web page always says where it is from
    (Origin), and is refused."""
    client = request.client.host if request.client else None
    if request.headers.get("origin") or client not in THIS_MACHINE:
        raise HTTPException(403, "only a program on this machine sends this")
    key = await asyncio.to_thread(session_key, request.app.state.session_factory)
    given = request.headers.get(KEY_HEADER, "").encode("latin-1")
    if key is None or not hmac.compare_digest(given, key.encode("latin-1")):
        raise HTTPException(403, "not the key of KOLONİ's status line setup")
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise HTTPException(422, "the status line's rate_limits are sent as JSON")
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > SESSION_BYTES:
            raise HTTPException(422, f"at most {SESSION_BYTES} bytes")
    try:
        reading = of_session(json.loads(body), datetime.now(UTC))
    except (ValueError, RecursionError):
        raise HTTPException(422, "not the status line's rate_limits") from None
    # (In a worker thread: it can write the database.)
    await asyncio.to_thread(request.app.state.providers.limits.from_session, reading)
    return Response(status_code=204)


@session_router.post(
    "/claude-session/setup", response_model=ClaudeSessionSetupOut,
    dependencies=[Depends(require_own_origin)],  # it carries the key, made the first time
)
def claude_session_setup(request: Request):
    """The status line command the user adds to their Claude Code settings themselves:
    KOLONİ's script, run by KOLONİ's own Python, sending to KOLONİ's own address with
    KOLONİ's key."""
    port = request.app.state.settings.port
    key = session_key(request.app.state.session_factory, make=True)
    python, script = Path(sys.executable).as_posix(), STATUS_LINE.as_posix()
    return {"command": f'"{python}" "{script}" --koloni http://127.0.0.1:{port} --key {key}',
            "script": str(STATUS_LINE)}


@router.post(
    "", response_model=ProviderOut, status_code=201, dependencies=[Depends(require_origin)]
)
def create_provider(
    body: ProviderIn, request: Request, session: Session = Depends(get_session)
):
    if body.kind not in KINDS:
        raise HTTPException(422, f"unknown kind: {body.kind}")
    if body.max_running is not None or body.kind in ROUTED and body.base_url:
        require_own_origin(request)  # as when it is changed: the user's, from the app's page
    address = _address(body.kind, body.base_url)
    provider = Provider(
        name=_name(session, body.name),
        kind=body.kind,
        base_url=address,
        api_key=_key(body.api_key) if body.kind in SERVED else None,
        default_model=_model(body.default_model),
        executable=_text(body.executable) if body.kind not in HTTP_KINDS else None,
        mode=_mode(body.kind, body.mode, address),
        options=_options(body.kind, body.options, address),
        position=len(list_providers(session)),
        for_agents=body.for_agents,
        only_listed=body.only_listed,
        max_running=body.max_running,
    )
    _guide(provider, body.note, body.models)
    _agents_follow(provider, body)
    _listed(provider)
    session.add(provider)
    session.commit()
    return provider


# On the event loop, as everything that reaches the runner is.
@router.patch("/{provider_id}", response_model=ProviderOut, dependencies=[Depends(require_origin)])
async def patch_provider(  # noqa: C901
    provider_id: str, body: ProviderPatch, request: Request,
    session: Session = Depends(get_session),
):
    provider = _provider(session, provider_id)
    sent = body.model_fields_set
    # (Where a CLI sends its work, too: not an agent's to point elsewhere.)
    if sent & {"max_running", "models", "for_agents", "enabled", *LIMITS} or (
            "base_url" in sent and provider.kind in ROUTED) or (
            # Copilot's token goes to its model server (COPILOT_PROVIDER_API_KEY): both are
            # the page's to set.
            "api_key" in sent and provider.kind == "copilot_cli"):
        # As a project's limit: the user's to say from the app's own page, not a
        # command's that an agent runs against the app's address - nor what agents may pick.
        require_own_origin(request)
    if "max_running" in sent:
        provider.max_running = body.max_running
    for limit in sent & set(LIMITS) - ({"plan"} if body.plan is None else set()):
        setattr(provider, limit, getattr(body, limit))
    if body.name is not None:
        name = _name(session, body.name, provider.id)
        if name != provider.name:
            # The record goes by the name: its rows follow, or a renamed provider's would drop
            # out of its usage, its day's limit (`over_limit`) and its room (`has_room`).
            for table in (Agent, OwnRequest):
                session.execute(update(table).where(table.provider_name == provider.name)
                                .values(provider_name=name))
        provider.name = name
    if "base_url" in sent:
        provider.base_url = _address(provider.kind, body.base_url)
        if provider.base_url and provider.models:
            # A context tier is GitHub's (K-copilot-baglam): on a model server of the user's
            # own it means nothing, and a stale one would refuse every later save of the list.
            provider.models = [{k: v for k, v in m.items() if k != "context"}
                               for m in provider.models]
    if "api_key" in sent and provider.kind in SERVED:
        provider.api_key = _key(body.api_key)  # an empty key removes it
    if "options" in sent or "base_url" in sent:
        told = body.options if "options" in sent else provider.options
        if (provider.kind == "copilot_cli" and told is not None and "offline" not in told
                and provider.options):
            # Not said this time: it stays as it was set.
            told = {**told, "offline": provider.options.get("offline")}
        provider.options = _options(provider.kind, told, provider.base_url)
    if "default_model" in sent:
        provider.default_model = _model(body.default_model)
    if "executable" in sent and provider.kind not in HTTP_KINDS:
        provider.executable = _text(body.executable)
    if "mode" in sent and body.mode is not None:
        provider.mode = _mode(provider.kind, body.mode)
    if body.for_agents is not None:
        provider.for_agents = body.for_agents
    if "note" in sent or "models" in sent:
        _guide(
            provider,
            body.note if "note" in sent else provider.note,
            body.models if "models" in sent else provider.models,
        )
    _agents_follow(provider, body)
    if body.only_listed is not None:
        provider.only_listed = body.only_listed
    if body.enabled is not None:
        provider.enabled = body.enabled
    _listed(provider)
    provider.updated_at = now()
    session.commit()
    if "max_running" in sent:
        request.app.state.runner.let_in()  # there may be room now for agents that wait
    return provider


@router.delete("/{provider_id}", status_code=204, dependencies=[Depends(require_own_origin)])
def delete_provider(provider_id: str, request: Request, session: Session = Depends(get_session)):
    provider = _provider(session, provider_id)
    providers = list_providers(session)
    if len(providers) == 1:
        raise HTTPException(409, "the last provider cannot be deleted")
    # What was read of its plan goes with the last provider on that account.
    if not any(p.id != provider.id and account(p) == account(provider) for p in providers):
        request.app.state.providers.limits.forget(session, account(provider))
    # Whatever pointed at it goes back to "no choice" and falls through to the next level.
    for table in (Conversation, Role):
        session.execute(
            update(table)
            .where(table.provider_id == provider.id)
            .values(provider_id=None, model_id=None)
        )
    session.execute(update(Project).where(Project.backlog_provider_id == provider.id).values(
        backlog_provider_id=None, backlog_model_id=None))
    # And it is no longer one that may be picked for a role (a list of one becomes none).
    for role in session.scalars(select(Role)):
        picks = role.pick_from or []
        if provider.id in picks:
            role.pick_from = [kept for kept in picks if kept != provider.id]
    session.delete(provider)
    session.commit()
    # Its own sign-in folder's login goes with it (K-claude-hesap) - one switched back to the
    # user's own sign-in since too; only a folder that really is one of `cli-homes`.
    homes = (request.app.state.settings.runtime_root / CLI_HOMES).resolve()
    folder = (homes / provider.id).resolve()
    if PROVIDER_ID.fullmatch(provider.id) and folder.parent == homes:
        shutil.rmtree(folder, ignore_errors=True)
    return Response(status_code=204)


@router.post(
    "/{provider_id}/default", response_model=ProviderOut,
    dependencies=[Depends(require_own_origin)],
)
def make_default(provider_id: str, session: Session = Depends(get_session)):
    """Move a provider to the front: the first one is what a conversation uses by default."""
    provider = _provider(session, provider_id)
    others = [p for p in list_providers(session) if p.id != provider.id]
    for position, row in enumerate([provider, *others]):
        row.position = position
    session.commit()
    return provider


@router.get("/{provider_id}/models", response_model=ProviderModelsOut)
async def provider_models(
    provider_id: str, request: Request, session: Session = Depends(get_session)
):
    """Model names worth offering for this provider: the user's own list first, then the
    catalogue's (none being retired), then what the provider lists itself. Nothing is made
    up: where there is no list at all, the answer is empty and says what to type instead."""
    provider = _provider(session, provider_id)
    own = [model["name"] for model in provider.models or []]
    copy = _copy(request)
    known = [row["name"] for row in catalog.models_for(
        catalog.catalogue_of(provider.kind, provider.base_url, copy), copy, provider.name)]
    listed, note, advice = await _own_list(provider, request.app.state.providers)
    # (Not one the user switched off: nobody may pick it.)
    off = {m["name"] for m in provider.models or [] if m.get("enabled") is False}
    return ProviderModelsOut(
        models=[name for name in dict.fromkeys([*own, *known, *listed]) if name not in off],
        # "Type the name" is for a provider with nothing to choose from (a CLI's catalogue
        # is something; Anthropic's note also says what a key would list).
        note=None if advice and (own or known and provider.kind in CLI_NAMES) else note,
    )


@router.post(
    "/fill-from-catalogue", response_model=CatalogueFillOut,
    dependencies=[Depends(require_own_origin)],
)
def fill_new_from_catalogue(body: CatalogueFillIn, request: Request):
    """The same for a provider not added yet: the catalogue only, as nothing is there to
    list from yet (its own list comes once it is added). Nothing is saved."""
    if body.kind not in KINDS:
        raise HTTPException(422, f"unknown kind: {body.kind}")
    copy = _copy(request)
    models, left_out = catalog.fill(
        catalog.catalogue_of(body.kind, _address(body.kind, body.base_url), copy),
        [model.model_dump() for model in body.models], [], copy)
    return CatalogueFillOut(models=models, left_out=left_out)


@router.post(
    "/{provider_id}/fill-from-catalogue", response_model=CatalogueFillOut,
    dependencies=[Depends(require_own_origin)],
)
async def fill_from_catalogue(
    provider_id: str, request: Request, session: Session = Depends(get_session)
):
    """A team guide proposed from the catalogue and the provider's own list; nothing is
    saved: the user looks it over and saves it. The user's, from the app's own page."""
    models, left_out = await _fill(_provider(session, provider_id), request)
    return CatalogueFillOut(models=models, left_out=left_out)


async def _fill(provider: Provider, request: Request) -> tuple[list[dict], int]:
    listed, _ = await _listed_by(provider, request.app.state.providers)
    copy = _copy(request)
    return catalog.fill(
        catalog.catalogue_of(provider.kind, provider.base_url, copy), provider.models or [],
        listed or [], copy, provider.name)


# Paid by the plan, not the token: ticked for agents when the tiers are filled (design §3b),
# where its command is on this machine (looked for on PATH) and it does not say it is signed
# out (its own status command, which calls no model; one with none is taken as signed in).
SUBSCRIPTIONS = ("claude_cli", "codex_cli", "agy_cli", "qoder_cli")


@router.post(
    "/fill-all", response_model=FillAllOut, dependencies=[Depends(require_own_origin)])
async def fill_all(request: Request, session: Session = Depends(get_session)):
    """Every provider's team guide proposed from the catalogue at once; nothing is saved.
    A provider with no catalogue (a server of one's own) keeps its rows and tick as they
    are, and its server is not asked: its tiers are the user's to give. One that runs only
    its listed models keeps those rows, their blanks filled: nothing is added to it."""
    copy = _copy(request)

    async def proposed(p: Provider) -> list[dict] | None:
        key = catalog.catalogue_of(p.kind, p.base_url, copy)
        if not catalog.models_for(key, copy, p.name):
            return None
        if p.only_listed:
            return catalog.fill(key, p.models or [], [], copy, p.name)[0][:len(p.models or [])]
        return (await _fill(p, request))[0]

    async def on_plan(p: Provider) -> bool:  # (asked only where it can change the tick)
        return (not p.for_agents and p.kind in SUBSCRIPTIONS
                and bool(catalog.models_for(catalog.catalogue_of(p.kind, p.base_url, copy), copy,
                                            p.name))
                and catalog.installed(p.kind, p.executable)
                and await catalog.signed_in(p.kind, p.executable, cli_home(
                    request.app.state.settings.runtime_root, p)) is not False)

    providers = list_providers(session)
    found, ready = await asyncio.gather(asyncio.gather(*(proposed(p) for p in providers)),
                                        asyncio.gather(*(on_plan(p) for p in providers)))
    return FillAllOut(providers=[FillAllProvider(
        id=p.id, name=p.name, kind=p.kind, catalogued=models is not None,
        for_agents=p.for_agents or (models is not None and plan),
        models=p.models or [] if models is None else models,
    ) for p, models, plan in zip(providers, found, ready, strict=True)], notes=catalog.NOTES)


@router.post(
    "/fill-all/save", response_model=list[ProviderOut],
    dependencies=[Depends(require_own_origin)])
def save_fill_all(body: FillAllIn, session: Session = Depends(get_session)):
    """The proposal as the user left it, saved in one go: all of it, or (a 422 or 404 says
    why) none of it. A provider it leaves as it was is not touched (its form stays open)."""
    for told in body.providers:
        provider = _provider(session, told.id)
        # (Whether a model is switched off is not the fill's to say: `_guide` keeps it.)
        models = [model.model_dump(exclude={"enabled", "off_why"}) for model in told.models]
        if told.for_agents and models and not any(m["agents"] for m in models):
            # Ticked with every model switched off: the tick would do nothing, so they are on.
            models = [{**m, "agents": True} for m in models]
        # (Without a model's place in its tier's order, which is not set here.)
        kept = [{**{key: m.get(key) for key in ("name", "note", "tier")},
                 "agents": m.get("agents", True), "inputs": m.get("inputs"),
                 "context": m.get("context")}
                for m in provider.models or []]
        if told.for_agents == provider.for_agents and models == kept:
            continue
        provider.for_agents = told.for_agents
        _guide(provider, provider.note, models)
        _listed(provider)
        provider.updated_at = now()
    session.commit()
    return list_providers(session)


@router.get(
    "/{provider_id}/availability", response_model=AvailabilityOut,
    dependencies=[Depends(require_origin)],
)
async def availability(  # noqa: C901
    provider_id: str, request: Request, free: bool = False,
    session: Session = Depends(get_session),
):
    """Whether each model of the guide, the catalogue and the provider's own list can be used
    now. No model is run: a CLI is looked for and asked only its own sign-in status, the
    provider only its list. With `free`, only what costs nothing: whether a CLI's command is
    on this machine - nothing is started and nobody is asked."""
    provider = _provider(session, provider_id)
    down = looked_down(session)
    if free:
        installed = catalog.installed(provider.kind, provider.executable) if (
            provider.kind in CLI_NAMES) else None
        if installed is False:
            down[provider.id] = ("not installed", None)
        elif installed and down.get(provider.id, ("",))[0] == "not installed":
            del down[provider.id]  # (whether it is signed in is not read here)
        return {"installed": installed, "models": []}
    kind = provider.kind
    copy = _copy(request)
    names = dict.fromkeys([m["name"] for m in provider.models or []]
                          + [e["name"] for e in catalog.models_for(
                              catalog.catalogue_of(kind, provider.base_url, copy), copy,
                              provider.name)])
    told: dict = {"installed": None}
    why = None  # why none of them can be used
    if kind in CLI_NAMES:
        told["installed"] = catalog.installed(kind, provider.executable)
        if not told["installed"]:
            told["install"], why = catalog.install(kind), "not installed"
        else:
            # (On a model server of the user's its sign-in is not used: not asked.)
            home = cli_home(request.app.state.settings.runtime_root, provider)
            if provider.base_url:
                told["signed_in"] = None
            elif kind == "copilot_cli":
                told["signed_in"] = await _copilot_signed_in(provider)
            else:
                told["signed_in"], told["plan"] = await catalog.status(
                    kind, provider.executable, home)
            if home is not None:
                # K-claude-hesap: its own folder's login, in the user's own terminal.
                told["login"] = _login(kind, provider.executable, home)
            if told["signed_in"] is False:
                told["sign_in"] = told.get("login") or catalog.sign_in(kind)
                why = "not signed in"
    elif kind == "anthropic" and not provider.api_key:
        why = "needs an API key"
    listed, failed = (None, None) if why else await _listed_by(
        provider, request.app.state.providers)
    # As the page says it. A list nothing answered for: its server is not answering - for a
    # while, as one started later answers; a status or an answer that is no list says
    # nothing of its chat, which may work without /models.
    if why:
        down[provider.id] = ({"needs an API key": "without an API key"}.get(why, why), None)
    elif failed and failed.startswith(UNREACHABLE):
        down[provider.id] = ("not answering", monotonic() + LIST_DOWN_SECONDS)
    else:
        down.pop(provider.id, None)
    unknown = failed or "the provider does not list its models; it is checked when first used"
    # What it listed is marked too: a fill can put any of it in the guide.
    names = dict.fromkeys([*names, *(listed or [])])
    told["models"] = [
        {"name": name, "state": "unusable", "why": why} if why
        else {"name": name, "state": "unknown", "why": unknown} if listed is None
        else {"name": name, "state": "usable", "why": None} if name in listed
        else {"name": name, "state": "unusable", "why": "not offered by the provider now"}
        for name in names
    ]
    for row in told["models"]:
        row["retired"] = catalog.facts(kind, provider.base_url, row["name"], copy)[0][
            "deprecated"] is True
    return told


async def _listed_by(provider: Provider, providers) -> tuple[list[str] | None, str | None]:
    """The models the provider itself listed just now - None where no list was read (Claude
    Code's names are the CLI's documented aliases, not a list it gave) - and why it could
    not be read, the key already taken out of that."""
    if provider.kind == "claude_cli" and not provider.base_url:
        return None, None
    listed, note, advice = await _own_list(provider, providers)
    if note and provider.api_key:  # whatever the provider's error said, never the key
        note = note.replace(provider.api_key, "[key]")
    return listed or None, None if advice else note  # an empty list is no list read


async def _own_list(provider: Provider, providers) -> tuple[list[str], str | None, bool]:  # noqa: C901
    """What the provider itself lists, a note, and whether that note is only advice on
    what to type (rather than why a list could not be had)."""
    if provider.kind == "claude_cli" and not provider.base_url:
        return list(CLAUDE_MODELS), None, False
    if provider.kind == "agy_cli":
        # The CLI lists its models itself (`agy models`), and uses no model to do it.
        try:
            lister = getattr(providers.lister(provider), "models", None)
            listed = await lister() if lister else []
            # It ran and named none (none KOLONİ could read as one): said, not left blank.
            return listed, None if listed else (
                "agy listed no models. Type the name you would give its --model option, "
                "or leave it empty for its own choice."
            ), False
        except ModelUnavailable as exc:
            return [], str(exc), False
    if provider.kind == "anthropic":
        if not provider.api_key:
            # Nobody is asked without a key: there is nothing it could list.
            return [], (
                "Set an API key to see the models it can use, or type the model's name "
                "as Anthropic knows it."
            ), True
        try:
            lister = getattr(providers.lister(provider), "models", None)
            return (await lister() if lister else []), None, False
        except ModelUnavailable as exc:
            return [], str(exc).replace(provider.api_key, "[key]"), False
    if provider.kind in ("openai_compat", "copilot_cli", *SERVER_CLIS) and provider.base_url:
        try:
            return await served_models(provider.base_url, provider.api_key), None, False
        except ModelUnavailable as exc:
            reason = str(exc)
            if provider.api_key:
                reason = reason.replace(provider.api_key, "[key]")
            return [], reason, False
    if provider.kind == "qoder_cli":
        # Its own list (`qodercli --list-models`, no model used). Not installed, failed or
        # too slow: silently the catalogue's names, as before (R99), with the advice below.
        # shortcut: asked on each look, uncached, as agy's is; cache it if it proves slow.
        try:
            lister = getattr(providers.lister(provider), "models", None)
            listed = await lister() if lister else []
        except Exception:  # (whatever it was, nothing of it is shown or logged)
            listed = []
        if listed:
            return listed, None, False
    if provider.kind == "copilot_cli":
        return [], (
            "On a GitHub account the models are GitHub's: type the name you would give "
            "Copilot's --model option, or leave it empty for its own choice."
        ), True
    if provider.kind in CLI_NAMES:
        return [], (
            f"{CLI_NAMES[provider.kind]} does not list its models: type the name you "
            "would give its --model option, or leave it empty for its own default."
        ), True
    return [], "Type the model's name as the provider knows it.", True


@router.post(
    "/{provider_id}/test", response_model=ProviderTestOut, dependencies=[Depends(require_origin)]
)
async def test_provider(
    provider_id: str, request: Request, run: bool = False,
    session: Session = Depends(get_session),
):
    """Ask the provider what it is: reachable or not, which model, tools or no tools.

    For a CLI that only says whether the command is there. With `run`, the CLI is
    really run once on a one-word question - which spends the user's plan, so it is
    never done unasked - and the answer says which model replied.
    """
    provider = _provider(session, provider_id)
    reply: str | None = None
    try:
        client = request.app.state.providers.client(provider, provider.default_model)
        info = await client.info()
        model_id, model_from = info.model_id, info.model_from
        if run and provider.kind in CLI_NAMES:
            # Run once on a one-word question: what it answered and the model it named.
            # (On Usage as "KOLONİ itself": K-56.)
            reply, answer = await ask_own(
                request.app.state.session_factory, (provider.name, mode_of(provider)), client,
                info.model_id, TRY_OUT)
            if answer.model:
                model_id, model_from = answer.model, None  # the CLI said it itself
        elif provider.kind == "copilot_cli" and await _copilot_signed_in(provider) is False:
            raise ModelUnavailable(NOT_SIGNED_IN)
        # Said to take images and never tried (slice 85b): one of a pixel, once, where the
        # Check already asks the model. (Anthropic's Check spends nothing: not there.)
        name = catalog.model_key(provider, None)  # (as a run on its default keeps it)
        said = catalog.inputs(provider, name, _copy(request)).get("image")
        if said and said[0] and said[1] != "tried" and hasattr(client, "takes_image"):
            took = await client.takes_image(info.model_id)
            if took is not None:
                provider.tried_inputs = {**(provider.tried_inputs or {}), name: {
                    **(provider.tried_inputs or {}).get(name, {}), "image": took}}
                session.commit()
    except ModelUnavailable as exc:
        reason = str(exc)
        if provider.api_key:
            reason = reason.replace(provider.api_key, "[key]")
        looked_down(session)[provider.id] = ("not answering", None)
        return ProviderTestOut(ok=False, model_id=None, tools_supported=None, error=reason)
    looked_down(session).pop(provider.id, None)
    return ProviderTestOut(
        ok=True, model_id=model_id, tools_supported=info.tools_supported, error=None,
        reply=reply, model_from=model_from,
    )


TRY_OUT = [
    {"role": "system", "content": "This is a connection check. Use no tools."},
    {"role": "user", "content": "Reply with the single word: ok"},
]


def _copy(request: Request) -> dict:
    """models.dev as this app reads it: the user's updated copy, else the shipped one."""
    return models_dev.load(request.app.state.settings.runtime_root)


# How long the facts wait for what a provider says itself: a server on this machine may
# be loading its model, and is asked again next time if it does not answer in time.
FACTS_SECONDS = 15.0


@router.get(
    "/{provider_id}/model-facts", response_model=ModelFactsOut,
    dependencies=[Depends(require_origin)],  # it may ask the provider: not for another site
)
async def model_facts(  # noqa: C901
    provider_id: str, request: Request,
    model: str = Query("", max_length=MAX_MODEL_NAME), session: Session = Depends(get_session),
):
    """What is known of a model on this provider - the one being picked, saved or not -
    each fact with where it came from: the user's own (a tier in the team guide, a price),
    then the catalogue, then what the provider says where asking spends nothing (an
    OpenAI-compatible server's `/props`, Anthropic's Models API for a model the catalogue
    does not know).
    What none of them says is null; `failed` where one that was asked did not answer."""
    provider = _provider(session, provider_id)
    name = _model(model) or ""
    copy = _copy(request)
    told, said = catalog.facts(provider.kind, provider.base_url, name, copy, provider.name)
    told["price"] = told["price"] and {**told["price"], "currency": "USD"}
    mine = next((row for row in provider.models or [] if row["name"] == name), None)
    # The user's where it is not the catalogue's: a fill saves the catalogue's as it is.
    if mine and mine.get("tier") and mine["tier"] != told["tier"]:
        told["tier"], said["tier"] = mine["tier"], "you"
    price = session.get(Price, name) if name else None
    if price is not None:
        told["price"], said["price"] = {
            "input": price.input, "output": price.output, "cache_read": price.cache_read,
            "cache_write": price.cache_write, "currency": price.currency}, "you"
    # Asked of the client its runs use (its default model's): never one more per name typed.
    try:
        client = request.app.state.providers.client(provider, provider.default_model)
    except OwnStop:  # a provider that cannot be run as it is set up: nothing to ask
        client = None
    failed = False
    found = getattr(client, "found_window", None)
    if provider.kind == "openai_compat" and found and (
            said.get("efforts") != "you" or told["context_window"] is None):
        # Its `/props` (llama-server's window and levels: the whole server's, on this machine
        # or the LAN) is a free GET; never its chat, which would start a generation.
        try:
            window = await asyncio.wait_for(found(), FACTS_SECONDS)
        except TimeoutError:
            window, failed = None, True
        else:
            failed = not getattr(client, "reached", True)
        # (Its levels as the server said them: not a catalogue's for another model. Over the
        # catalogue's, as its client sends them; never over the user's, catalog.local.json.)
        for fact, value in (("efforts", getattr(client, "props_efforts", None)),
                            ("context_window", window)):
            if ((fact == "efforts" and value and said.get(fact) != "you")
                    or (value is not None and told[fact] is None)):
                told[fact], said[fact] = list(value) if fact == "efforts" else value, "server"
    look_up = getattr(client, "_look_up", None)
    if provider.kind == "anthropic" and look_up is None:
        # No model its runs could use (`allowed`): a name being picked is looked up all the same.
        look_up = getattr(request.app.state.providers.lister(provider), "_look_up", None)
    if (provider.kind == "anthropic" and provider.api_key and look_up and "efforts" not in said
            and (name or provider.default_model)):
        # Anthropic's Models API costs nothing; what it said of a model is kept by the client.
        try:
            info = (await asyncio.wait_for(
                look_up(name or provider.default_model, FACTS_SECONDS), FACTS_SECONDS))[0]
        except ModelUnavailable as exc:
            cause = exc.__cause__
            # A model it does not know is unknown, not a failed lookup.
            failed = not (isinstance(cause, httpx2.HTTPStatusError)
                          and cause.response.status_code == 404)
        except TimeoutError:
            failed = True
        else:
            for fact, value in (("efforts", list(info.efforts or ())),
                                ("context_window", info.context_window)):
                if value is not None and told[fact] is None:
                    told[fact], said[fact] = value, "anthropic"
    takes = catalog.inputs(provider, catalog.model_key(provider, name), copy)
    return ModelFactsOut(**told, sources=said, catalogue_date=models_dev.read_on(copy),
                         failed=failed, inputs=[
                             {"kind": kind, "takes": yes, "source": source}
                             for kind, (yes, source) in takes.items()])


@router.post("/{provider_id}/find-again", status_code=204,
             dependencies=[Depends(require_own_origin)])
def find_again(provider_id: str, request: Request, session: Session = Depends(get_session)):
    """The user's Find again on the Models page: what this provider's server or Anthropic's
    Models API said of its models (a window, levels) is asked again at the next look - a
    llama-server restarted with another `-c`, say. Nothing is asked here; an agent at work
    keeps what its client found."""
    _provider(session, provider_id)
    request.app.state.providers.forget(provider_id)
    return Response(status_code=204)


@router.delete("/{provider_id}/tried-inputs", status_code=204,
               dependencies=[Depends(require_own_origin)])
def forget_tried(provider_id: str, model: str = Query("", max_length=MAX_MODEL_NAME),
                 session: Session = Depends(get_session)):
    """What KOLONİ learned sending a model files (slice 85b), taken away by the user: what
    models.dev or their own mark says counts again, and the next file is tried once more."""
    provider = _provider(session, provider_id)
    name = catalog.model_key(provider, _model(model))
    provider.tried_inputs = {k: v for k, v in (provider.tried_inputs or {}).items()
                             if k != name} or None
    session.commit()
    return Response(status_code=204)


@router.post("/suggest", response_model=SuggestOut, dependencies=[Depends(require_own_origin)])
def suggest(body: SuggestIn, request: Request):
    """For a provider not added yet, from its kind and the address typed so far: the
    catalogue's model names, and a service's address and key name where models.dev has
    them. Nothing is asked of any provider and nothing is saved."""
    if body.kind not in KINDS:
        raise HTTPException(422, f"unknown kind: {body.kind}")
    return catalog.suggest(body.kind, _text(body.base_url), _copy(request))


@catalogue_router.get("", response_model=CatalogueUpdateOut)
def catalogue(request: Request, session: Session = Depends(get_session)):
    """Which copy of models.dev the app reads: the user's updated one, else the shipped one;
    and why the user's own catalogue is not read, where it is not."""
    return {**models_dev.summary(_copy(request)), **_told(session)}


def _told(session: Session) -> dict:
    """What is said beside a copy's counts: why catalog.local.json is not read, and whether
    the user keeps the catalogue fresh."""
    fresh = session.get(Flag, models_dev.FRESH)
    return {"local": catalog.local()[1], "keep_fresh": fresh is None or fresh.value != "0"}


@catalogue_router.put(
    "/fresh", response_model=CatalogueUpdateOut, dependencies=[Depends(require_own_origin)])
def keep_catalogue_fresh(body: CatalogueFreshIn, request: Request,
                         session: Session = Depends(get_session)):
    """"Keep the catalogue fresh": the user's, from the app's own page; read at the start."""
    session.merge(Flag(name=models_dev.FRESH, value="1" if body.keep_fresh else "0"))
    session.commit()
    return catalogue(request, session)


@catalogue_router.post(
    "/update", response_model=CatalogueUpdateOut, dependencies=[Depends(require_own_origin)])
async def update_catalogue(request: Request, session: Session = Depends(get_session)):
    """Download models.dev's list, check it is that, trim it and keep it as the catalogue
    this app reads. Only ever the user's, from the app's own page; an answer that is not
    models.dev's list changes nothing."""
    try:
        raw = await asyncio.wait_for(models_dev.download(), 2 * models_dev.SECONDS)
        kept = await asyncio.to_thread(
            models_dev.update, request.app.state.settings.runtime_root, raw)
        return {**kept, **_told(session)}
    except TimeoutError:
        raise HTTPException(504, "models.dev did not answer in time; nothing was changed") from None
    except Exception as exc:  # unreachable, refused, or not its list: the copy stays as it was
        raise HTTPException(502, f"models.dev's list could not be used ({type(exc).__name__}: "
                            f"{str(exc)[:200]}); nothing was changed") from None
