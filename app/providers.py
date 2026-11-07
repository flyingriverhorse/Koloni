"""Model providers: where an agent's model steps are sent."""

import json
import shutil
from collections.abc import Callable
from functools import partial
from time import monotonic
from typing import Literal

from sqlalchemy import func, literal_column, select
from sqlalchemy.orm import Session

from app.config import Settings, is_local
from app.db.models import Conversation, OwnRequest, Provider, Role
from app.limits import Limits, account, cli_home
from app.model_agy import AgyClient, AgySearch
from app.model_anthropic import AnthropicClient
from app.model_cli import (
    SEARCH_SECONDS,
    ClaudeCliClient,
    ClaudeSearch,
    CliStepClient,
    CodexCliClient,
    CodexSearch,
)
from app.model_client import (
    SLOTS,
    ModelClient,
    ModelInfo,
    OpenAICompatClient,
    OwnStop,
    server_of,
)
from app.model_native import (
    ClaudeNativeClient,
    CodexNativeClient,
    CodexSessionClient,
    CopilotNativeClient,
    QoderNativeClient,
)
from app.model_session import ClaudeSessionClient, CopilotSessionClient, QoderSessionClient
from app.roles import shown_name

HTTP_KINDS = ("openai_compat", "anthropic")
CLI_KINDS = ("claude_cli", "qoder_cli", "codex_cli", "copilot_cli", "agy_cli")
# The CLIs KOLONİ gives images (and a video's frames) as they are, by their own image input
# (slice 85c): Claude Code's image blocks, Codex's --image and localImage. The others have
# none KOLONİ can use: their agents are told of a picture, never shown it. No CLI is sent a
# video as it is.
IMAGE_CLIS = ("claude_cli", "codex_cli")
# The CLIs that can run on a model server of the user's, by its address on the provider
# (K-cli-llama, measured 27 Oct 2026); Copilot has one of its own way (`check_options`).
SERVER_CLIS = ("claude_cli", "codex_cli")
# Agents at work at once on a provider the user set no number for (`Providers.most_at_once`).
CLI_AT_ONCE, SERVICE_AT_ONCE = 3, 8
# How each CLI can be run, the first being its default. A session needs the CLI's own
# tools to be really off while KOLONİ's reach it over MCP: Codex's patch tool cannot be
# switched off, so KOLONİ declines each patch it asks about (`CodexSessionClient`).
# Native is a CLI with its own tools in the project, asking KOLONİ before they act.
# Reads is agy with its own tools and no leave to change anything: the CLI itself
# refuses a write or a command, so nothing has to be asked.
MODES = {
    "claude_cli": ("session", "step", "native"),
    "qoder_cli": ("session", "native"),  # (native: B-306, not yet measured)
    "codex_cli": ("session", "step", "native"),
    "copilot_cli": ("session", "native"),
    "agy_cli": ("reads", "native"),
}
# What each kind may be told about its model server, with the value when nothing is said.
COPILOT_TYPES = ("openai", "anthropic")
MAX_TOKENS = 2_000_000
# The short names the Claude Code CLI documents for --model.
CLAUDE_MODELS = ("sonnet", "opus", "haiku", "fable")
KINDS = (*HTTP_KINDS, *CLI_KINDS)
ANTHROPIC_URL = "https://api.anthropic.com"
# What the CLI is called when the provider does not name a path.
CLI_COMMANDS = {
    "claude_cli": "claude", "qoder_cli": "qodercli", "codex_cli": "codex",
    "copilot_cli": "copilot", "agy_cli": "agy",
}
# agy goes by its command's name: what the product is called was not measured.
CLI_NAMES = {
    "claude_cli": "Claude Code", "qoder_cli": "Qoder", "codex_cli": "Codex",
    "copilot_cli": "GitHub Copilot CLI", "agy_cli": "agy",
}


def mode_of(provider: Provider) -> str | None:
    """How a provider runs: its mode, or its kind's default where the row names a way
    that kind cannot run in. None for a kind that is not a CLI."""
    modes = MODES.get(provider.kind)
    if modes is None:
        return None
    return provider.mode if provider.mode in modes else modes[0]


def per_token(provider: Provider) -> bool:
    """Whether its requests are paid for one by one: an API key that is not a CLI, not on this
    machine, not a plan (as the knowledge Try it box says it, B-372)."""
    return provider.kind not in CLI_KINDS and not is_local(provider.base_url) and not provider.plan


# K-native-not: which of KOLONİ's rules nobody watches for a CLI at work with its own tools,
# said on its agent's node and window - only where its code skips the check. Empty where
# every tool of its own is asked about (`AgentRunner._approve`): Claude Code's and native
# agy's hooks, each of Copilot's requests.
NOT_WATCHED: dict[tuple[str, str], tuple[str, ...]] = {
    ("claude_cli", "native"): (),
    # shortcut: as `QoderNativeClient` says, whether it asks before its tools is not measured
    # (`_heard` stops it only once one ran unasked); drop this line once measured live.
    ("qoder_cli", "native"): (
        "not yet measured to ask before each tool; a tool that ran unasked stops the turn "
        "after it ran",
    ),
    ("copilot_cli", "native"): (),
    ("agy_cli", "native"): (),
    ("codex_cli", "native"): (
        # At "untrusted" (`CodexNativeClient._converse`) its known-safe commands run unasked:
        # a .env, the home folder (B-301's note in `_native_arguments`).
        # shortcut: said also for a role that may not run commands (`_no_shell`), where it reads
        # with KOLONİ's tools - the safe side; leave it out there if that misleads.
        "reading secret files (.env, keys): its read-only commands run without asking",
        "reading files outside the project, the same way",
        # Its own web search asks nothing at any level (`AgentRunner._approve`'s canary
        # shortcut), where KOLONİ's search is asked below Full auto.
        "its own web searches are not asked about (nor checked for the planted key)",
    ),
    # Reading only it has no hook (`AgyClient.run_native`: `hooked` is None, and `withheld`'s
    # search and fetch are not read); it cannot run a command, so the canary key never reaches
    # it. Its search_web, address reads and browser run unasked (measured: `AgySearch`).
    ("agy_cli", "reads"): (
        "reading secret files (.env, keys): its reading tools run without asking",
        "reading files outside the project, the same way",
        "searching the web and opening addresses: its own tools run unasked, even with web "
        "tools switched off",
    ),
}
# Said too where the agent's project runs its commands in Docker: a CLI's own commands run
# on this machine (`CommandRunner.ask_for`'s location "host") - for every way above that runs
# commands, which agy reading only does not.
ON_HOST = ("its commands run on this machine, not in the project's Docker (its network "
           "setting and hidden secrets do not apply)")
RUNS_NO_COMMANDS = frozenset({("agy_cli", "reads")})


def not_watched(kind: str, docker: bool) -> dict[str, list[str]] | None:
    """`NOT_WATCHED` of a kind, by mode; `docker`: for a project whose commands run in Docker.
    None for a kind that never works with its own tools."""
    told = {mode: [*rules, *([ON_HOST] if docker and (kind, mode) not in RUNS_NO_COMMANDS
                             else [])]
            for (one, mode), rules in NOT_WATCHED.items() if one == kind}
    return told or None
# The ways of running in which a CLI works with tools of its own, not KOLONİ's. KOLONİ
# sees of such a CLI's tools only what it asks about (`AgentRunner._cannot_be_held`):
# with nobody watching it cannot be held to what a trigger allows, so no trigger's turn
# is started on it.
OWN_TOOLS = frozenset(NOT_WATCHED)


def works_with_own_tools(provider: Provider) -> bool:
    return (provider.kind, mode_of(provider)) in OWN_TOOLS


def check_options(kind: str, options: dict | None, has_server: bool) -> dict | None:  # noqa: C901
    """A provider's own settings, complete and checked; ValueError says what is wrong.

    Copilot has some: how its own model server is spoken to. Anthropic has one: the
    workspace its key belongs to. Claude Code has two, the first only its native way reads:
    whether it starts with the user's own setup; and, as Codex, whose sign-in it runs on
    (`sign_in`: the user's own, or "koloni" - a folder of its own, `limits.cli_home`).
    """
    if kind in ("claude_cli", "codex_cli"):
        told = dict(options or {})
        unknown = set(told) - ({"own_setup", "sign_in"} if kind == "claude_cli" else {"sign_in"})
        if unknown:
            raise ValueError(f"unknown setting: {sorted(unknown)[0]}")
        own = told.get("own_setup")
        if own is not None and not isinstance(own, bool):
            raise ValueError("own_setup is true or false")
        if own and has_server:
            # Its own settings can name another address or key (`env`, `apiKeyHelper`).
            raise ValueError("Use my own Claude Code setup cannot go with a model server of "
                             "your own: your settings could send its work elsewhere")
        sign_in = told.get("sign_in") or "own"
        if sign_in not in ("own", "koloni"):
            raise ValueError("sign_in is own or koloni")
        if sign_in == "koloni" and has_server:
            raise ValueError("a sign-in of its own is for your plan: on a model server of your "
                             "own nothing is signed in to")
        if sign_in == "koloni" and own:
            # Its folder holds none of your setup, and the setup's switch would let it start
            # with hooks and commands on.
            raise ValueError("Use my own Claude Code setup cannot go with a sign-in of its own")
        kept = {"own_setup": True} if own else {}
        return {**kept, "sign_in": "koloni"} if sign_in == "koloni" else kept or None
    if kind == "anthropic":
        told = dict(options or {})
        unknown = set(told) - {"workspace_id"}
        if unknown:
            raise ValueError(f"unknown setting: {sorted(unknown)[0]}")
        workspace = workspace_id(told.get("workspace_id"))
        return {"workspace_id": workspace} if workspace else None
    if kind != "copilot_cli":
        if options:
            raise ValueError("this kind of provider has no settings of its own")
        return None
    told = dict(options or {})
    unknown = set(told) - {"provider_type", "max_prompt_tokens", "max_output_tokens", "offline"}
    if unknown:
        raise ValueError(f"unknown setting: {sorted(unknown)[0]}")
    provider_type = told.get("provider_type") or "openai"
    if provider_type not in COPILOT_TYPES:
        raise ValueError(f"the model server's type is one of: {', '.join(COPILOT_TYPES)}")
    limits = {}
    for name in ("max_prompt_tokens", "max_output_tokens"):
        value = told.get(name)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_TOKENS
        ):
            raise ValueError(f"{name} is a whole number from 1 to {MAX_TOKENS}")
        limits[name] = value
    offline = told.get("offline")
    if offline is not None and not isinstance(offline, bool):
        raise ValueError("offline is true or false")
    # With a model server of your own there is nothing to ask GitHub for: never going
    # there is how it runs unless that was switched off.
    # Without one, it runs on the user's GitHub account and has to go there.
    return {
        "provider_type": provider_type, **limits,
        "offline": has_server and offline is not False,
    }


MAX_WORKSPACE = 100


def workspace_id(value: object) -> str | None:
    """An Anthropic workspace's id as it will go into a request header: printable
    ASCII without spaces, not longer than an id is. Empty is None."""
    if value is None:
        return None
    text = value.strip() if isinstance(value, str) else None
    if text is None or len(text) > MAX_WORKSPACE or not (
        text.isascii() and text.isprintable() and " " not in text
    ):
        raise ValueError(
            f"the workspace id is at most {MAX_WORKSPACE} characters, without spaces, "
            "line breaks or non-ASCII characters; copy it again from the Anthropic console"
        )
    return text or None


MAX_NOTE = 300
MAX_MODELS = 30
# The Models page's name of `only_listed`, as the messages that point to it say it.
ONLY = "Never run a model that is not on this list"
MAX_MODEL_NAME = 200
MAX_MODEL_NOTE = 120
# How strong the user says a model is, weakest first. A model with no tier is in no
# automatic choice: it is only ever named.
TIERS = ("fast", "balanced", "strongest")
# What a model may take besides text, as models.dev names them (slice 85b).
INPUTS = ("image", "video", "audio", "pdf")
# Copilot's context window tiers, as its --help names them (CLI 1.0.103, K-copilot-baglam).
CONTEXTS = ("default", "long_context")


def _line(value: object, limit: int, what: str, even: bool = True) -> str | None:
    """Text an agent will be shown as data: one printable line, no longer than `limit`.
    A line break or a control character is refused, not tidied away; empty is None."""
    text = value.strip() if isinstance(value, str) else ""
    if not text.isprintable():
        raise ValueError(f"{what} cannot contain line breaks or control characters")
    if even:
        text = " ".join(text.split())  # only plain spaces are left to even out
    if len(text) > limit:
        raise ValueError(f"{what} has at most {limit} characters")
    return text or None


def check_guide(note: str | None, models: list[dict] | None, tiered: bool = False
                ) -> tuple[str | None, list[dict]]:
    """What the user tells agents about a provider, tidied and checked: the note and the
    models that can be chosen on it. `tiered`: a Copilot provider on the user's GitHub
    account, the only one whose models take a context tier. ValueError says what is wrong."""
    if len(models or []) > MAX_MODELS:
        raise ValueError(f"a provider's list has at most {MAX_MODELS} models")
    listed: list[dict] = []
    for model in models or []:
        # A name is kept as typed: it has to be the name the provider knows.
        name = _line(model.get("name"), MAX_MODEL_NAME, "a model name", even=False)
        if name is None:
            raise ValueError("a model in the list needs a name")
        if any(name == other["name"] for other in listed):
            raise ValueError(f"the model {name} is in the list twice")
        tier = model.get("tier")
        if tier not in (None, *TIERS):
            raise ValueError(f"a model's tier is one of: {', '.join(TIERS)}")
        # Whether agents may pick it (slice 81a); the user still may, by hand.
        agents = model.get("agents", True)
        if not isinstance(agents, bool):
            raise ValueError("a model's agents is true or false")
        # Switched off: nobody uses it (`allowed`). Kept only when off: on is what none says.
        enabled = model.get("enabled")
        if enabled is not None and not isinstance(enabled, bool):
            raise ValueError("a model's enabled is true or false")
        # What the user marked it to take besides text (slice 85b); None: not marked.
        takes = model.get("inputs")
        if takes is not None and not (isinstance(takes, list) and set(takes) <= set(INPUTS)):
            raise ValueError(f"a model's inputs are some of: {', '.join(INPUTS)}")
        # K-copilot-baglam: GitHub's tier; on a model server of the user's own it means nothing.
        context = model.get("context")
        if context not in (None, *CONTEXTS):
            raise ValueError(f"a model's context is one of: {', '.join(CONTEXTS)}")
        if context and not tiered:
            raise ValueError("a context tier is only for Copilot on your GitHub account")
        listed.append({
            "name": name, "note": _line(model.get("note"), MAX_MODEL_NOTE, "a model's note"),
            "tier": tier, "agents": agents, **({"enabled": False} if enabled is False else {}),
            **({"inputs": list(dict.fromkeys(takes))} if takes is not None else {}),
            # (Only the long one is kept: the default is what passing nothing gives.)
            **({"context": context} if context == "long_context" else {}),
        })
    return _line(note, MAX_NOTE, "the note"), listed


class NotListed(OwnStop):
    """The provider runs only with the models listed for it, and this is not one. What it
    says is for the user; `to_agent` is for an agent, which can do nothing about a setting
    of the user's and is told of no model it could not choose."""

    def __init__(self, to_user: str, to_agent: str):
        super().__init__(to_user)
        self.to_agent = to_agent


class ClosedToAgents(NotListed):
    """B-385: no agent of a role is opened on a model closed to agents
    (`app.team.CLOSED_TO_AGENTS`); what it says is the user's too (`AgentRunner._closed_said`)."""


class SwitchedOff(ClosedToAgents):
    """The user switched the provider, or this model of it, off on the Models page: nobody uses
    it - no chat, no agent, no Observer, no learning - until it is switched on again. A stronger
    "closed to agents": the Lead and the chat are held to it too."""


def is_on(provider: Provider, model: str | None) -> bool:
    """Whether the user left this provider, and this model of it, switched on. (One not
    saved yet says nothing of it: on.) With no model at all - a CLI's own default would run,
    which KOLONİ does not know - it is off where every model of its list is."""
    rows = provider.models or []
    if model is None and rows and not any(m.get("enabled", True) for m in rows):
        return False
    return provider.enabled is not False and not any(
        m["name"] == model and not m.get("enabled", True) for m in rows)


def allowed(provider: Provider, model: str | None) -> None:
    """Raise NotListed unless this provider may run with this model. One switched off
    (`is_on`) never runs, nor does its default model where that is off. With "Only these
    models" on it never runs with a model outside its list, nor with none at all. An
    Anthropic provider never runs with none: the API has no default model.
    shortcut: a CLI with no model named and no default runs its own, which KOLONİ does not
    know: it is held back only where its whole list is off (`is_on`), not where that own
    default is one model switched off; name its default if that is ever missed."""
    model_or_default = model or provider.default_model
    if not is_on(provider, model_or_default):
        whole = provider.enabled is False
        what = provider.name if whole else f"Every model of {provider.name}" if (
            model_or_default is None) else f"{provider.name}'s {model_or_default}"
        shown = shown_name(provider.name) + ("" if whole else " (every model)" if (
            model_or_default is None) else " " + json.dumps(model_or_default, ensure_ascii=False))
        raise SwitchedOff(
            f"{what} is switched off. Turn it on on the Models page, or pick another model.",
            f"{shown} is switched off by the user (Models page): choose another model.",
        )
    if provider.kind == "anthropic" and not model:
        raise NotListed(
            f"{provider.name} has no model to run with: none is chosen for it here, and it has "
            "no default model. Set its Default model on the Models page, or choose a model in "
            "the conversation's model picker - or, for a role set to run on it, the role's "
            "model on the Agents page.",
            f"{shown_name(provider.name)} does not run without a model named for it: name one "
            "of its models, or choose another provider.",
        )
    if not provider.only_listed:
        return
    names = [listed["name"] for listed in provider.models or []]
    if model and model in names:
        return
    # A name from before names were checked is shown as agents are shown it elsewhere.
    shown = shown_name(provider.name)
    to_agent = (
        f"{shown} does not run with the model "
        f"{json.dumps(model, ensure_ascii=False)} here" if model
        else f"{shown} does not run here without a model chosen for it"
    )
    # It names the setting, so that the user reading this knows where to look.
    to_agent += f': the user limited it to listed models ("{ONLY}", Models page)'
    if provider.for_agents:
        # In the team guide, where these are the models an agent may name: as data.
        chosen = ", ".join(json.dumps(m["name"], ensure_ascii=False)
                           for m in provider.models or [] if m.get("agents", True))
        to_agent += f". The models that can be chosen on it: {chosen}."
    else:
        to_agent += ". Only the user can change that."
    raise NotListed(
        f"{provider.name} runs only with the models listed for it ({', '.join(names)}), and "
        + (f"{model} is not one of them" if model else "no model is chosen for it")
        + f'. Choose one of those, or switch "{ONLY}" off on the Models page.',
        to_agent,
    )


class Refused:
    """Stands where a client would be for a model the provider may not run: nothing is
    built and nothing is started, and whoever asks is told why."""

    def __init__(self, why: NotListed):
        self._why = (str(why), why.to_agent)

    async def info(self) -> ModelInfo:
        raise NotListed(*self._why)

    async def stream_step(self, model_id, messages, tools, on_delta, on_thinking=None):
        raise NotListed(*self._why)


async def ask_once(client, model_id: str, messages: list[dict], **more):
    """One answer from a model with no tools, whatever kind of client it is: what it
    said, and the result that carries what it spent and the model that answered. A CLI
    at work with its own tools speaks with them off (`talker`), and a session is run
    with none of KOLONİ's tools. `more` goes with a step (`max_tokens`), not a session."""
    said: list[str] = []

    async def on_text(text: str) -> None:
        said.append(text)

    async def no_tool(name: str, arguments: str) -> tuple[bool, str]:
        return False, "error: no tools in this request"

    # (A CLI's step takes no `max_tokens`: agy's, Codex's, one run step by step.)
    if getattr(client, "native", False):
        client, more = client.talker(), {}
    if getattr(client, "compacts_itself", False):
        more = {}
    if getattr(client, "session", False):
        result = await client.run_session(model_id, messages, [], no_tool, on_text)
        return "".join(said).strip(), result
    step = await client.stream_step(model_id, messages, None, on_text, **more)
    return (step.content or "".join(said)).strip(), step


def own_request(session: Session, provider_name: str | None, mode: str | None,
                model_id: str | None, answer, run_id: str | None = None,
                agent_id: str | None = None, project_id: str | None = None) -> None:
    """A request KOLONİ made of a model itself goes on record (`OwnRequest`, not committed),
    under the provider and model it went to. `answer`: what came back, with what it spent;
    None where it was sent and not heard out (Stop, a failure): what it spent is not known.
    With no run it is Usage's "KOLONİ itself"."""
    session.add(OwnRequest(
        run_id=run_id, agent_id=agent_id, project_id=project_id, provider_name=provider_name,
        provider_mode=mode, model_id=(answer.model if answer else None) or model_id,
        input_tokens=answer.input_tokens if answer else None,
        output_tokens=answer.output_tokens if answer else None,
        # (A result that has no word of a cache: not known.)
        cache_read_tokens=getattr(answer, "cache_read", None),
        cache_write_tokens=getattr(answer, "cache_write", None),
        cut_short=answer is None,
    ))


async def ask_own(factory, asked: tuple[str, str | None], client, model_id: str,
                  messages: list[dict], project_id: str | None = None, **more):
    """`ask_once` for a request KOLONİ makes of a model with no turn (the day's words, a
    recipe's draft, a role's guide, a Check that runs a CLI): on record as it ends, well or
    not (`own_request`), for Usage's "KOLONİ itself" (K-56). `asked`: the provider's name and
    how it runs (`mode_of`), read while its row is at hand."""
    name, mode = asked
    answer = None
    try:
        said, answer = await ask_once(client, model_id, messages, **more)
        return said, answer
    finally:
        with factory() as session:
            own_request(session, name, mode, model_id, answer, project_id=project_id)
            session.commit()


# How long a server whose list did not answer is passed over: one started later is tried again.
LIST_DOWN_SECONDS = 120.0


def looked_down(session: Session) -> dict[str, tuple[str, float | None]]:
    """Provider id -> how it looked when KOLONİ last read it ("not answering"), where that
    stands in its way, and until when (`time.monotonic`; None: until it is seen again). The
    app's sessions share one (app.main), for as long as it runs; any other session has one
    of its own.
    shortcut: in memory only (gone on a restart), and cleared only by a reading, a Check or
    its time - not by a turn that works there; keep it with the limits' readings, or clear it
    on a turn, if a stale one is seen holding a tier back."""
    return session.info.setdefault("looked_down", {})


def down_now(session: Session) -> dict[str, str]:
    """Of `looked_down`, the providers a tier passes over now (`app.team.Would.pick`)."""
    at = monotonic()
    return {pid: why for pid, (why, until) in looked_down(session).items()
            if until is None or until > at}


def list_providers(session: Session) -> list[Provider]:
    """Providers in the user's order; the first one is the default."""
    return list(
        session.scalars(
            select(Provider).order_by(
                Provider.position, Provider.created_at, literal_column("providers.rowid")
            )
        )
    )


def search_clients(session_factory) -> list:
    """The CLIs a web search can be handed to, in the user's order: each Codex, Claude
    Code and agy provider, on its own default model (agy reading only, however it is set
    to run). (Copilot: not yet.)"""
    kinds = {"codex_cli": CodexSearch, "claude_cli": ClaudeSearch, "agy_cli": AgySearch}
    with session_factory() as session:
        return [
            kinds[provider.kind](provider.executable, provider.default_model, SEARCH_SECONDS)
            # (Not one on a model server of the user's: it has no search of its own.)
            for provider in list_providers(session)
            if provider.kind in kinds and not provider.base_url
            and is_on(provider, provider.default_model)
        ]


def search_apis(session_factory) -> list:
    """The Anthropic providers a web search can go through, in the user's order: each
    one that has a key, on its own default model - where it may run with that model."""
    found = []
    with session_factory() as session:
        for provider in list_providers(session):
            if provider.kind != "anthropic" or not provider.api_key:
                continue
            try:
                allowed(provider, provider.default_model)
            except NotListed:
                continue
            found.append(AnthropicClient(
                provider.base_url or ANTHROPIC_URL, provider.api_key, provider.default_model,
                workspace_id=(provider.options or {}).get("workspace_id"),
            ))
    return found


def find_provider(session: Session, name: str) -> Provider | None:
    return session.scalar(select(Provider).where(func.lower(Provider.name) == name.lower()))


def seed_providers(
    session: Session, settings: Settings, which: Callable[[str], str | None] = shutil.which
) -> None:
    """On the very first start, offer what is at hand: the local server from the
    environment, and the CLIs that are installed (all but Copilot). After that the
    list is the user's and is left alone."""
    if session.scalar(select(func.count()).select_from(Provider)):
        return
    session.add(Provider(
        name="Local",
        kind="openai_compat",
        base_url=settings.model_base_url,
        api_key=settings.model_api_key,
        default_model=settings.model_id,
        position=0,
        # A model server on this machine is the one thing agents may choose unasked.
        for_agents=is_local(settings.model_base_url),
    ))
    if settings.detect_cli:
        # Copilot is not offered by itself: the user adds it on the Models page.
        seeded = [kind for kind in CLI_KINDS if kind != "copilot_cli"]
        for position, kind in enumerate(seeded, 1):
            if which(CLI_COMMANDS[kind]):
                session.add(Provider(
                    name=CLI_NAMES[kind], kind=kind, position=position, mode=MODES[kind][0],
                    # Google's Antigravity terms (section 6) forbid using it through another app.
                    enabled=kind != "agy_cli",
                ))
    session.commit()


Source = Literal["role", "tier", "conversation", "default"]


def resolved(
    session: Session, role: Role | None, conversation: Conversation | None
) -> tuple[Provider, str | None, Source]:
    """The provider and model for an agent, and where that comes from: its role's choice
    ("role"), else the conversation's ("conversation"), else the first provider
    ("default"). A choice whose provider is gone counts as no choice. With no
    conversation: what a new one would give. (Between the role's own model and the
    conversation's comes the role's tier, which is read off the team guide:
    `app.team.would_run`, which is what everything that opens an agent asks.)"""
    choices: list[tuple[Source, str | None, str | None]] = [
        ("role", role.provider_id, role.model_id) if role else ("role", None, None),
        ("conversation", conversation.provider_id, conversation.model_id)
        if conversation else ("conversation", None, None),
    ]
    for source, provider_id, model_id in choices:
        provider = session.get(Provider, provider_id) if provider_id else None
        if provider:
            if not model_id and conversation and conversation.provider_id == provider.id:
                # A role on the provider the conversation is on, with no model of its own:
                # the model picked there, before the provider's default.
                model_id = conversation.model_id
            return provider, model_id or provider.default_model or stand_in(provider), source
    providers = list_providers(session)
    if not providers:
        raise OwnStop("no model provider is set up")
    return providers[0], providers[0].default_model or stand_in(providers[0]), "default"


def stand_in(provider: Provider) -> str | None:
    """B-193: the model KOLONİ names for a CLI given none and with no default - else it runs
    its own default, which may be its dearest (Claude Code's was). Of what its list lets
    agents use: the first of the tier nearest balanced, as `team.tier_for` picks a tier, else
    the list's first. None for an HTTP provider, and a CLI with no such list: the chat says
    the CLI's own default runs (frontend/src/models/ModelPicker.tsx `runsOn`, the same rule).
    shortcut: in the list's order, not the tier's order the user set (app.api.tiers)."""
    if provider.kind not in CLI_KINDS:
        return None
    mine = [m for m in provider.models or [] if m.get("agents", True) and m.get("enabled", True)]
    tiered = [m for m in mine if m.get("tier") in TIERS]
    middle = TIERS.index("balanced")
    # (Fast before strongest where no balanced one is: the cheaper.)
    nearest = min(tiered, key=lambda m: (abs(TIERS.index(m["tier"]) - middle),
                                         TIERS.index(m["tier"])), default=None)
    return (nearest or (mine[0] if mine else {})).get("name")


def most_at_once(provider: Provider) -> int:
    """K-paralel-saglayici: the most agents at work on a provider at once, in the whole app -
    the user's number, else by its kind: a CLI 3 (each spends the user's subscription), a
    llama-server its slots as its `/props` said them (1 unsaid), any other service 8.
    shortcut: a server on this machine counts as a service until a client of it has read its
    `/props` (its first agent's start, before its first step) - and `-np` in the local server's
    arguments is not read; read them, or `/props` at Save, if a burst before that is seen."""
    if provider.max_running:
        return provider.max_running
    if provider.kind in CLI_KINDS:
        return CLI_AT_ONCE
    return SLOTS.get(server_of(provider.base_url), SERVICE_AT_ONCE)


class Providers:
    """Builds the client for a provider. Tests can stand in for all providers
    (`override`) or for one by name (`named`)."""

    def __init__(
        self,
        settings: Settings,
        override: ModelClient | None = None,
        named: dict[str, ModelClient] | None = None,
        session_factory: Callable[[], Session] | None = None,
    ):
        self.settings = settings
        self.override = override
        self.named = dict(named or {})
        self._cache: dict[tuple, ModelClient] = {}
        # What each provider last said of its plan; with a database, kept across restarts.
        self.limits = Limits(session_factory, settings.runtime_root / "agy-home",
                             settings.runtime_root)

    def client(self, provider: Provider, model_id: str | None) -> ModelClient:
        # The one place every path to a model goes through: lead, sub-agent, a
        # discussion's new member, the Models page's test.
        try:
            allowed(provider, model_id)
        except NotListed as exc:
            return Refused(exc)
        if provider.name in self.named:
            return self.named[provider.name]
        if self.override is not None:
            return self.override
        # A client is kept while the provider's settings stay the same, so what it has
        # learned about a model (does it take tools?) is not asked again every turn; and,
        # for a service whose levels and window are its catalogue's (`_build`), while the
        # catalogue read and the user's catalog.local.json stay the same: an update of either
        # reaches it at its next step, as on the Models page.
        from app import catalog, models_dev

        stamp, read = provider.updated_at, None
        if provider.kind == "openai_compat":
            stamp = (stamp, catalog.local_stamp())
            read = models_dev.read_on(models_dev.load(self.settings.runtime_root))
        key = (provider.id, stamp, model_id, read)
        if key not in self._cache:
            for stale in [k for k in self._cache
                          if k[0] == provider.id and (k[1], k[3]) != (key[1], key[3])]:
                del self._cache[stale]
            self._cache[key] = self._build(provider, model_id)
        return self._cache[key]

    def forget(self, provider_id: str | None = None) -> None:
        """Drop the kept clients of model servers and Anthropic's API (of one provider, or
        all): what they learned (a window, its tools) is asked again - the server on this
        machine was started anew, or the user pressed Find again. A CLI's is left alone."""
        for key, client in list(self._cache.items()):
            if isinstance(client, OpenAICompatClient | AnthropicClient) and (
                    provider_id is None or key[0] == provider_id):
                del self._cache[key]

    def lister(self, provider: Provider) -> ModelClient:
        """The client to ask which models a provider has. Listing runs no model, so
        "Only these models" does not stand in its way."""
        if provider.name in self.named:
            return self.named[provider.name]
        if self.override is not None:
            return self.override
        return self._build(provider, None)

    def _build(self, provider: Provider, model_id: str | None) -> ModelClient:
        settings = self.settings
        if provider.kind == "openai_compat":
            from app import catalog, models_dev  # (the catalogue reads this module's names)

            # A service's model takes the levels its catalogue (or the user's, catalog.local.json)
            # says: they are what is sent; and its window is the catalogue's, which its agents
            # are compacted against (slice 59d); an update of either builds it anew (`client`).
            copy = models_dev.load(settings.runtime_root)
            told, said = catalog.facts(provider.kind, provider.base_url, model_id or "", copy,
                                       provider.name)
            built_api = OpenAICompatClient(
                provider.base_url or "",
                provider.api_key,
                model_id,
                stall_seconds=settings.model_stall_seconds,
                first_token_seconds=settings.model_first_token_seconds,
                efforts=None if told["efforts"] is None else tuple(told["efforts"]),
                catalogued_window=told["context_window"],
                efforts_yours=said.get("efforts") == "you",
                off_as=catalog.off_as(provider.kind, provider.base_url, model_id or "", copy),
            )
            # Each answer's headers may say its rate limits (slice 73): the last are kept.
            built_api.on_limits = partial(self.limits.api_said, account(provider))
            return built_api
        if provider.kind == "anthropic":
            anthropic = AnthropicClient(
                provider.base_url or ANTHROPIC_URL,
                provider.api_key,
                model_id,
                stall_seconds=settings.model_stall_seconds,
                first_token_seconds=settings.model_first_token_seconds,
                workspace_id=(provider.options or {}).get("workspace_id"),
            )
            anthropic.on_limits = partial(self.limits.api_said, account(provider))
            return anthropic
        # A mode this kind cannot safely run in is never used, whatever the row says.
        mode = mode_of(provider)
        if mode is None:
            raise OwnStop(f"unknown kind of provider: {provider.kind}")
        if provider.kind == "agy_cli":
            return AgyClient(
                provider.executable, model_id, timeout=settings.model_first_token_seconds,
                reads=mode != "native", homes=settings.runtime_root / "agy-home",
            )
        if provider.kind == "copilot_cli":
            build = CopilotNativeClient if provider.mode == "native" else CopilotSessionClient
            # K-copilot-baglam: the tier comes only from the model's row, checked when it was
            # saved (`check_guide`), and only on GitHub's account.
            # shortcut: KOLONİ's own window for a Copilot model (compaction, usage) stays the
            # catalogue's one number whatever the tier; models.dev has no tiers, so that number
            # may be the long tier's and the default one smaller. Measure both windows live.
            row = next((m for m in provider.models or [] if m["name"] == model_id), {})
            copilot = build(
                provider.executable, model_id, timeout=settings.model_first_token_seconds,
                base_url=provider.base_url, api_key=provider.api_key,
                options=provider.options or {},
                context=None if provider.base_url else row.get("context"),
            )
            if build is CopilotNativeClient and not provider.base_url:
                # 89l: on GitHub's plan its headless client says what is left of it.
                copilot.on_limits = partial(self.limits.copilot_said, account(provider))
            return copilot
        home = cli_home(settings.runtime_root, provider)  # (Claude Code's and Codex's only)
        if (provider.kind, mode) == ("claude_cli", "native"):
            built: CliStepClient = ClaudeNativeClient(
                provider.executable, model_id, timeout=settings.model_first_token_seconds,
                own_setup=bool((provider.options or {}).get("own_setup")),
                server=provider.base_url, homes=settings.runtime_root / "server-homes", home=home,
            )
        else:
            cli = {
                ("claude_cli", "session"): ClaudeSessionClient,
                ("claude_cli", "step"): ClaudeCliClient,
                ("qoder_cli", "session"): QoderSessionClient,
                ("qoder_cli", "native"): QoderNativeClient,
                ("codex_cli", "step"): CodexCliClient,
                ("codex_cli", "session"): CodexSessionClient,
                ("codex_cli", "native"): CodexNativeClient,
            }[provider.kind, mode]
            # A CLI has no stream of tokens to watch, so one limit covers the whole run.
            built = cli(provider.executable, model_id, timeout=settings.model_first_token_seconds,
                        server=provider.base_url, homes=settings.runtime_root / "server-homes",
                        home=home)
        # (On the user's own model server nothing it says is of the user's plan.)
        if provider.kind == "claude_cli" and not provider.base_url:
            # Claude Code says what is left of its plan in every run: the last is kept.
            built.on_limits = partial(self.limits.said, account(provider))
        elif provider.kind == "codex_cli" and mode != "step" and not provider.base_url:
            # So does Codex's app-server (slice 89a; a session too), in the words its read is
            # answered in.
            built.on_limits = partial(self.limits.codex_said, account(provider))
        return built
