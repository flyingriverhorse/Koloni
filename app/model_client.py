import asyncio
import base64
import contextlib
import json
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

import httpx2

from app.config import is_local


@dataclass(frozen=True)
class ToolCallRequest:
    id: str
    name: str
    arguments: str  # raw JSON text exactly as the model produced it
    # The model's output limit came while it was writing this call: it is not run.
    cut: bool = False


@dataclass(frozen=True)
class StepResult:
    content: str
    tool_calls: list[ToolCallRequest]
    input_tokens: int | None
    output_tokens: int | None
    # The model that answered, where the provider says so with the answer.
    model: str | None = None
    # Of `input_tokens`: what the provider says it read again from its cache, and what it
    # wrote to it. None where it did not say - never a zero for that.
    cache_read: int | None = None
    cache_write: int | None = None
    # Its output limit ended it ("length"): what it wrote is not all it would have.
    cut: bool = False
    # The provider refused the level it was asked with: the step was asked again without.
    effort_refused: bool = False
    # The model did not take the level asked, and said which it takes: (asked, what the step
    # was asked again with - None: no level).
    effort_instead: tuple[str, str | None] | None = None
    # The answer as a provider that wants it sent back as it was gave it (Anthropic's content
    # blocks with their thinking, and what they were written after); None for any other.
    blocks: dict | None = None
    # B-387: in this step the CLI's model tried a tool of the CLI's own, which is off there.
    own_tools_refused: bool = False


class Transient(dict):
    """A message sent with this step only, at the end of what is sent (how a room stands
    now, word that a call has returned): the next step does not send it again. To every
    client it is a message like any other; one that keeps a cache marks what is before it."""


# How a server refuses a file sent as it is (slice 85b): llama-server without its mmproj
# ("image input is not supported"), servers that take only text content.
# shortcut: from what servers are known to say, not measured against each; widen it when a
# refusal is seen to fail the step instead.
REFUSES_FILES = re.compile(
    r"image|vision|multi-?modal|mmproj|video|content.{0,40}\b(string|str|text)\b", re.IGNORECASE)
# ...or refuses the request for its size, which files make bigger: sent again without them,
# but no word of the model's taking none ("image exceeds 5 MB maximum" is no such word).
TOO_BIG = re.compile(
    r"too (large|big|long)|exceed|maximum|payload|\b413\b|entity|dimension|resolution|pixels"
    r"|\bsize\b", re.IGNORECASE)
# A PNG of one pixel: what the Check sends a model said to take images.
PIXEL = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
         "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def files_of(message: dict) -> list[tuple[str, str, str]]:
    """The files a user message carries as they are (slice 85b, `files`: what KOLONİ chose
    to send this model), each (kind, media type, base64) - read only now, as it goes out.
    One gone from KOLONİ's store since is left out."""
    sent = []
    for one in message.get("files") or ():
        try:
            sent.append((one["kind"], one["mime"],
                         base64.b64encode(Path(one["path"]).read_bytes()).decode("ascii")))
        except OSError:
            continue
    return sent


def with_files(messages: list[dict]) -> list[dict]:
    """Messages as an OpenAI-compatible server takes them: a message's files as image_url
    (or video_url) parts after its text.
    shortcut: video_url is vLLM's part, not measured against any server; a refusal of it
    sends the video's frames instead (`agent._without`)."""
    out = []
    for message in messages:
        if "files" not in message:
            out.append(message)
            continue
        parts: list[dict] = [{"type": "text", "text": message["content"]}]
        for kind, mime, data in files_of(message):
            way = "video_url" if kind == "video" else "image_url"
            parts.append({"type": way, way: {"url": f"data:{mime};base64,{data}"}})
        out.append(type(message)({k: v for k, v in message.items() if k != "files"},
                                 content=parts))
    return out


def count_of(value: object) -> int | None:
    """A number of tokens as a provider reported it; None for anything else."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


# How hard a model may be asked to think, lowest first (Anthropic's order); "off": not at
# all, offered only where a model is known to turn its thinking off.
EFFORTS = ("off", "low", "medium", "high", "xhigh", "max")


@dataclass(frozen=True)
class ModelInfo:
    model_id: str
    tools_supported: bool
    # "settings": the name was read from the CLI's own settings, not reported by it.
    model_from: str | None = None
    # The reasoning levels it takes (of EFFORTS), and how many tokens it reads at most,
    # as its provider says them; None: not said - unknown, and no level is sent.
    efforts: tuple[str, ...] | None = None
    context_window: int | None = None


class ModelUnavailable(Exception):
    """The model server could not be reached or answered with an error."""

    # Why, where the provider said it in a form of its own and not in the words above:
    # the class of the failure and when its limit resets (`app.limits.classify`).
    failure: tuple[str, datetime | None] | None = None
    # A short failure of the provider's side (`brief`): the seconds to wait before its step
    # is asked once more, with the same model (93-B3). None: not one to ask again.
    retry_in: float | None = None
    # A CLI session's model, as it said it before it failed, and why Copilot's auto picked it
    # (`SessionResult`): on record also when the turn fails (B-410). None: not said.
    model: str | None = None
    picked_why: str | None = None


# The statuses of a short failure of the server's (a timeout, overloaded, a gateway's).
SHORT_STATUS = frozenset({408, 500, 502, 503, 504, 529})
# A 429 is asked again only where it says to wait this long at most; a longer one is a limit.
SHORT_WAIT = 10.0
# A plan key's quota used up, as Alibaba's Token Plan says it in its 429 (its documented
# words and code, not measured here); its plain throttle is a 429 without them. With
# OpenAI's own code for the same: `app.limits` reads these too.
USED_UP = re.compile(r"insufficient_quota|token-plan quota has been exhausted")


def brief(exc: httpx2.HTTPError) -> float | None:
    """How long to wait before asking once more after a short failure - a dropped or timed
    out connection, a SHORT_STATUS, a 429 whose Retry-After is SHORT_WAIT seconds at most
    and that names no quota used up (USED_UP); None for any other (a 401, a quota, a
    request refused for what it is).
    shortcut: Retry-After read as seconds only, not as a date; read the date if one is seen."""
    if isinstance(exc, httpx2.HTTPStatusError):
        status = exc.response.status_code
        if status == 429:
            if USED_UP.search(exc.response.text.lower()):
                return None
            said = exc.response.headers.get("retry-after", "").strip()
            wait = float(said) if said.isascii() and said.isdigit() else None
            return wait if wait is not None and wait <= SHORT_WAIT else None
        return 1.0 if status in SHORT_STATUS else None
    return 1.0 if isinstance(exc, httpx2.TransportError) else None


def unavailable(text: str, exc: httpx2.HTTPError) -> ModelUnavailable:
    """A step's failure in words, with how soon it may be asked again (`brief`)."""
    failed = ModelUnavailable(text)
    failed.retry_in = brief(exc)
    return failed


class OwnStop(ModelUnavailable):
    """Not what the provider's side said: a rule of KOLONİ's own stopped it, or it cannot
    be started as this machine and this provider are set up. No class of failure and no
    advice about other providers is made of it (`app.limits.classify` is for the rest)."""


Delta = Callable[[str], Awaitable[None]]


class ModelClient(Protocol):
    async def info(self) -> ModelInfo: ...

    async def stream_step(
        self,
        model_id: str,
        messages: list[dict],
        tools: list[dict] | None,
        on_delta: Delta,
        on_thinking: Delta | None = None,
    ) -> StepResult: ...


_PROBE_TOOL = {
    "type": "function",
    "function": {
        "name": "ping",
        "description": "Reply by calling this tool.",
        "parameters": {"type": "object", "properties": {}},
    },
}


# How long llama-server's `/props` may take to say its window.
WINDOW_SECONDS = 5.0
# A llama-server (`server_of` its address) -> how many requests it serves at once, as its `/props`
# said (`found_window`): what its provider lets work at once unless the user says (`most_at_once`).
# shortcut: a server restarted with another `-np` keeps its old number until a client of it reads
# its `/props` again (`Providers.forget`: Find again, a provider saved); ask at every agent's
# start if seen.
SLOTS: dict[str, int] = {}
THIS_HOST = ("localhost", "127.0.0.1", "::1")


def server_of(address: str | None) -> str:
    """A model server, however its address is written: scheme, host and port, the host in lower
    case and this machine's names as one."""
    try:
        parts = urlsplit((address or "").strip())
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return (address or "").strip().casefold()
    host = (parts.hostname or "").casefold()
    return f"{parts.scheme.casefold()}://{'127.0.0.1' if host in THIS_HOST else host}:{port}"


class OpenAICompatClient:
    """Talks to an OpenAI-compatible /v1 endpoint such as llama.cpp's server."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        model_id: str | None = None,
        transport: httpx2.AsyncBaseTransport | None = None,
        stall_seconds: float = 120.0,
        first_token_seconds: float = 900.0,
        efforts: tuple[str, ...] | None = None,
        catalogued_window: int | None = None,
        efforts_yours: bool = False,
        off_as: str | None = None,
    ):
        self._base = base_url.rstrip("/")
        # What KOLONİ's off is sent as (`catalog.off_as`: OpenAI's "none", or "low" to a model
        # that does not take it); None: as a llama-server's template takes it.
        self._off_as = off_as
        self._model_id = model_id
        # The levels its model takes: the user's (catalog.local.json, `efforts_yours`), else
        # what a llama-server says in `/props` (`found_window`), else the catalogue's
        # (`Providers`); None: not said, and none is sent.
        self.efforts = efforts
        self._efforts_yours = efforts_yours
        # Its model's window as the catalogue says it (models.dev `limit.context`), for a
        # hosted service, which has no `/props`: what a llama-server says there comes first.
        self.catalogued_window = catalogued_window
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._transport = transport
        self._tools_cache: dict[str, bool] = {}
        self._window: int | None = None
        self._window_said = False
        # Whether its server answered `/props` at all, with anything (a 401 too), and the
        # levels it said there (the whole server's, whatever model a client is for).
        self.reached = False
        self.props_efforts: tuple[str, ...] | None = None
        # Its service refused `reasoning_effort` once: none is sent again by this client.
        self.refused_effort = False
        # A level its model said it does not take, and the one sent for it from then on.
        self.effort_instead: dict[str, str | None] = {}
        # Told the headers of each answer to a step, which may say its rate limits (slice 73).
        self.on_limits = None
        # How long a stream may stay silent before the run is failed.
        self._stall_seconds = stall_seconds
        # A local model may ingest a long prompt for minutes before its first token.
        self._first_token_seconds = first_token_seconds

    def _client(self, timeout: float | None) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            headers=self._headers,
            transport=self._transport,
            timeout=httpx2.Timeout(timeout, connect=5.0),
        )

    async def models(self) -> list[str]:
        """The names of the models the server lists."""
        try:
            async with self._client(15.0) as http:
                r = await http.get(f"{self._base}/models")
                r.raise_for_status()
                told = r.json()
        # Unreachable only where nothing answered: a status (no /models here) is said as one.
        except httpx2.HTTPError as exc:
            raise ModelUnavailable(_describe(exc)) from None
        except ValueError:
            told = None
        listed = told.get("data") if isinstance(told, dict) else None
        if not isinstance(listed, list):
            raise ModelUnavailable("the model server did not answer with a list of models")
        return [str(m["id"]) for m in listed if isinstance(m, dict) and m.get("id")]

    async def found_window(self) -> int | None:
        """How many tokens the server reads at most, as llama-server says it (`/props`
        beside `/v1`: `n_ctx`); None where it does not say - another server, or none that
        answers - never a guess. Kept once a server said it, or said it has no `/props`
        (404); one that did not answer, or not yet (a 503 while it loads), is asked again
        next time. Never fails. Its levels are read there too (`_props_levels`).
        shortcut: a server restarted with another `-c` is not asked again until the
        provider is saved, Find again is pressed on the Models page (a new client) or
        KOLONİ restarts; upgrade by asking at every agent's start if that is seen."""
        if not self._window_said:
            try:
                async with self._client(WINDOW_SECONDS) as http:
                    r = await http.get(self._base.removesuffix("/v1") + "/props")
            except httpx2.HTTPError:
                return None
            self.reached = True
            if not r.is_success and r.status_code != 404:
                return None
            try:
                told = r.json() if r.is_success else {}
            except ValueError:
                told = {}
            told = told if isinstance(told, dict) else {}
            said = told.get("default_generation_settings")
            self._window = (count_of(said.get("n_ctx")) or None) if isinstance(said, dict) else None
            if isinstance(said, dict):  # a llama-server: the requests it serves at once, 1 unsaid
                SLOTS[server_of(self._base)] = max(count_of(told.get("total_slots")) or 1, 1)
            self.props_efforts = _props_levels(told)
            if not self._efforts_yours:  # (the user's word comes first, as the page says it)
                self.efforts = self.props_efforts or self.efforts
            self._window_said = True
        return self._window

    async def info(self) -> ModelInfo:
        window = await self.found_window()
        try:
            async with self._client(120.0) as http:
                model_id = self._model_id
                if model_id is None:
                    r = await http.get(f"{self._base}/models")
                    r.raise_for_status()
                    data = r.json().get("data") or []
                    if not data:
                        raise ModelUnavailable("model server lists no models")
                    model_id = data[0]["id"]
                if model_id not in self._tools_cache:
                    # A model only gets tools if it answers a trivial request with a
                    # structured tool call; prose that mentions the tool does not count.
                    r = await http.post(
                        f"{self._base}/chat/completions",
                        json={
                            "model": model_id,
                            "stream": False,
                            "max_tokens": 256,
                            "messages": [{"role": "user", "content": "Call the ping tool."}],
                            "tools": [_PROBE_TOOL],
                        },
                    )
                    r.raise_for_status()
                    message = r.json()["choices"][0]["message"]
                    self._tools_cache[model_id] = bool(message.get("tool_calls"))
                return ModelInfo(model_id, self._tools_cache[model_id], efforts=self.efforts,
                                 context_window=window or self.catalogued_window)
        except httpx2.HTTPError as exc:
            raise ModelUnavailable(_describe(exc)) from exc
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ModelUnavailable(f"model server sent an unreadable response: {exc}") from exc

    async def takes_image(self, model_id: str) -> bool | None:
        """Whether the model takes an image (slice 85b, the Check): one of a single pixel,
        and one word asked back. A refusal that names it is a no; anything else, unknown."""
        try:
            async with self._client(60.0) as http:
                r = await http.post(f"{self._base}/chat/completions", json={
                    "model": model_id, "stream": False, "max_tokens": 8,
                    "messages": [{"role": "user", "content": [
                        {"type": "text", "text": "Reply with the single word: ok"},
                        {"type": "image_url", "image_url": {"url": PIXEL}}]}]})
        except httpx2.HTTPError:
            return None
        if r.is_success:
            return True
        return False if REFUSES_FILES.search(r.text) and not TOO_BIG.search(r.text) else None

    async def stream_step(  # noqa: C901
        self, model_id, messages, tools, on_delta, on_thinking=None,
        max_tokens: int | None = None, effort: str | None = None, asked_again: bool = False,
    ) -> StepResult:
        """`max_tokens`: the most it may write (a summary of KOLONİ's own); None: the
        server's own. `effort`: a level of `efforts`. A model that says which levels it
        takes instead is asked again once with the highest of them not above it, sent that
        from then on (`effort_instead`); a service that refuses the level otherwise
        (whatever its catalogue said) is asked again once without it, and never sent one
        again by this client (`refused_effort`)."""
        effort = None if self.refused_effort else self.effort_instead.get(effort, effort)
        payload: dict = {
            "model": model_id,
            "messages": with_files(messages),
            "stream": True,
            "stream_options": {"include_usage": True},
            **_leveled(effort, model_id, self._base, self._off_as),
        }
        if tools:
            payload["tools"] = tools
        if max_tokens:
            payload["max_tokens"] = max_tokens
        content: list[str] = []
        calls: dict[int, dict] = {}
        usage: dict = {}
        cut = False
        try:
            async with (
                self._client(None) as http,
                http.stream("POST", f"{self._base}/chat/completions", json=payload) as r,
            ):
                if self.on_limits:  # (a 429's too; keeping them never breaks the step)
                    with contextlib.suppress(Exception):
                        self.on_limits(r.headers)
                if r.status_code >= 400:
                    await r.aread()
                    r.raise_for_status()
                lines = r.aiter_lines().__aiter__()
                answering = False
                while True:
                    limit = self._stall_seconds if answering else self._first_token_seconds
                    try:
                        line = await asyncio.wait_for(anext(lines), limit)
                    except StopAsyncIteration:
                        break
                    except TimeoutError:
                        reason = (
                            f"sent nothing for {limit:g} seconds"
                            if answering
                            else f"did not start answering within {limit:g} seconds"
                        )
                        raise ModelUnavailable(f"model server {reason}") from None
                    answering = True
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    if chunk.get("error"):
                        # Servers report mid-stream failures (context overflow, a crashed
                        # slot) as a data chunk rather than an HTTP status.
                        error = chunk["error"]
                        message = error.get("message") if isinstance(error, dict) else error
                        raise ModelUnavailable(f"model server reported an error: {message}")
                    usage = chunk.get("usage") or usage
                    for choice in chunk.get("choices") or []:
                        cut = cut or choice.get("finish_reason") == "length"
                        delta = choice.get("delta") or {}
                        if delta.get("reasoning_content") and on_thinking:
                            await on_thinking(delta["reasoning_content"])
                        if delta.get("content"):
                            content.append(delta["content"])
                            await on_delta(delta["content"])
                        for tc in delta.get("tool_calls") or []:
                            slot = calls.setdefault(
                                tc.get("index", 0), {"id": "", "name": "", "arguments": ""}
                            )
                            fn = tc.get("function") or {}
                            slot["id"] = tc.get("id") or slot["id"]
                            slot["name"] = fn.get("name") or slot["name"]
                            slot["arguments"] += fn.get("arguments") or ""
        except httpx2.HTTPError as exc:
            takes = None if asked_again else _levels_taken(exc)
            if effort and takes is not None:
                below = [level for level in takes if EFFORTS.index(level) <= EFFORTS.index(effort)]
                sent = self.effort_instead[effort] = below[-1] if below else None
                again = await self.stream_step(model_id, messages, tools, on_delta, on_thinking,
                                               max_tokens, sent, asked_again=True)
                return replace(again, effort_instead=(effort, sent))
            if effort and effort != "off" and _refuses_effort(exc):
                self.efforts, self.refused_effort = None, True
                again = await self.stream_step(
                    model_id, messages, tools, on_delta, on_thinking, max_tokens)
                return replace(again, effort_refused=True)
            raise unavailable(_describe(exc), exc) from exc
        except ValueError as exc:
            raise ModelUnavailable(f"model server sent an unreadable stream: {exc}") from exc
        # A server that keeps a cache by itself says what of the prompt it read from it.
        details = usage.get("prompt_tokens_details")
        cached = details.get("cached_tokens") if isinstance(details, dict) else None
        return StepResult(
            content="".join(content),
            tool_calls=[
                # (An id of its own where the server gave none: never one an earlier step had.)
                ToolCallRequest(
                    c["id"] or f"call_{uuid.uuid4().hex[:8]}", c["name"], c["arguments"] or "{}")
                for _i, c in sorted(calls.items())
            ],
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            cache_read=count_of(cached),
            cut=cut,
        )


def _props_levels(props: dict) -> tuple[str, ...] | None:
    """The levels a llama-server's chat template takes, as `/props` says them (measured on
    b10686, 20 Oct 2026): low, medium and high where it takes `reasoning_effort`, and off
    where the template reads `enable_thinking`; None where it says neither."""
    caps = props.get("chat_template_caps")
    template = props.get("chat_template")
    takes = ("low", "medium", "high") if isinstance(caps, dict) and caps.get(
        "supports_reasoning_effort") is True else ()
    off = ("off",) if isinstance(template, str) and "enable_thinking" in template else ()
    return (*off, *takes) or None


# How a service says it does not take the field: OpenAI "Unrecognized request argument
# supplied: reasoning_effort", "Unsupported parameter: 'reasoning_effort'", and the like
# (a Qwen service's word for its budget, or for thinking at all, too).
_NO_EFFORT = re.compile(r"reasoning[ _.]effort|thinking[ _.]budget|enable[ _.]thinking",
                        re.IGNORECASE)

# The most a hosted Qwen may think at each level, in tokens: x4 a step from a short think;
# max is its own most. A budget its service refuses (a 400 naming it) goes as a level does.
QWEN_BUDGETS = {"low": 1024, "medium": 4096, "high": 16384, "xhigh": 32768, "max": None}


def _refuses_effort(exc: httpx2.HTTPError) -> bool:
    """A request refused for its level (a 400 whose words name the field)."""
    return (isinstance(exc, httpx2.HTTPStatusError) and exc.response.status_code == 400
            and bool(_NO_EFFORT.search(exc.response.text)))


def _levels_taken(exc: httpx2.HTTPError) -> tuple[str, ...] | None:
    """The levels a model says it takes where it refused the one asked (OpenAI's 400 with
    `"code": "unsupported_value"` on the field, "... Supported values are: 'low', 'medium',
    and 'high'."), of KOLONİ's, "none" as off; None for any other answer."""
    if not isinstance(exc, httpx2.HTTPStatusError) or exc.response.status_code != 400:
        return None
    try:
        error = exc.response.json().get("error")
    except (ValueError, AttributeError):
        return None
    if not isinstance(error, dict) or error.get("code") != "unsupported_value" or not (
            _NO_EFFORT.search(str(error.get("param")))):
        return None
    told = re.split(r"supported values are:", str(error.get("message")), flags=re.IGNORECASE)
    if len(told) < 2:
        return None
    said = set(re.findall(r"'(\w+)'", told[1]))
    return tuple(level for level in EFFORTS if level in said or level == "off" and "none" in said)


def _leveled(effort: str | None, model_id: str = "", base_url: str = "",
             off_as: str | None = None) -> dict:
    """What a level adds to the request: off is the chat template's switch, and then no
    level goes - or `off_as` where it is given (OpenAI's "none"); another is
    `reasoning_effort` at the top, as llama-server, OpenAI and DeepSeek read it. A hosted
    Qwen takes that and ignores it (measured on Alibaba's, 27 Oct 2026): its level is a
    budget of thinking."""
    if effort == "off":
        return {"reasoning_effort": off_as} if off_as else {
            "chat_template_kwargs": {"enable_thinking": False}}
    # shortcut: measured on Alibaba's only - a Qwen on another service that reads
    # reasoning_effort (OpenRouter, say) loses its level, and a llama-server on another
    # machine counts as hosted; narrow this to Alibaba's hosts (or tell a llama-server by
    # its `/props`, `reached`) once either is seen.
    if effort and "qwen" in model_id.lower() and not is_local(base_url):
        budget = QWEN_BUDGETS.get(effort)
        return {"enable_thinking": True, **({"thinking_budget": budget} if budget else {})}
    return {"reasoning_effort": effort} if effort else {}


# How a request that nothing answered (refused, timed out) is said: not an answer of a server's.
UNREACHABLE = "model server unreachable"


def _describe(exc: httpx2.HTTPError) -> str:
    if isinstance(exc, httpx2.HTTPStatusError):
        try:
            error = exc.response.json().get("error")
            detail = error.get("message") if isinstance(error, dict) else error
        except (ValueError, AttributeError):
            detail = None
        text = detail or exc.response.text[:300]
        return f"model server returned {exc.response.status_code}: {text}"
    return redact_urls(f"{UNREACHABLE}: {exc or type(exc).__name__}")


def safe_url(url: str) -> str:
    """A URL as it may be shown: without its user name and password, its query and its fragment,
    any of which can hold a secret (`https://user:key@host/v1?key=...`)."""
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        port = parts.port
    except ValueError:
        return ""
    if not parts.scheme or not host:
        # Not a URL that can be taken apart: nothing of it is shown that could be a secret.
        return url.split("@")[-1].split("?")[0].split("#")[0]
    netloc = f"[{host}]" if ":" in host else host
    return urlunsplit((parts.scheme, f"{netloc}:{port}" if port else netloc, parts.path, "", ""))


_URL = re.compile(r"[a-z][a-z0-9+.-]*://[^\s'\"<>]+", re.I)


def redact_urls(text: str) -> str:
    """An error's words with every URL in them made safe to show (httpx names the URL it
    asked, password and all)."""
    return _URL.sub(lambda m: safe_url(m.group(0)), text)
