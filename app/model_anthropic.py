"""Anthropic's Messages API as a model provider."""

import asyncio
import contextlib
import hashlib
import json
import re
import uuid

import httpx2

from app.model_cli import _cache_tokens, _input_tokens
from app.model_client import (
    EFFORTS,
    ModelInfo,
    ModelUnavailable,
    OwnStop,
    StepResult,
    ToolCallRequest,
    Transient,
    _describe,
    count_of,
    files_of,
    unavailable,
)

API_VERSION = "2023-06-01"
# The most a step may write: the model's own limit (Models API), at most this. Thinking
# takes from it too; the request streams, so a long step is no timeout. Where the API does
# not say the model's own (a gateway at a base URL of the user's), the old 8192: unknown
# is as before, never a guess that the server may refuse.
MAX_TOKENS = 64_000
UNKNOWN_MAX_TOKENS = 8192
# Listing the models: how many pages are asked for at most, and how long one may take.
MAX_MODEL_PAGES = 5
MODELS_SECONDS = 10.0
CUT = "[cut off at the output limit]"
# A web search through the API's own search tool (`app.web.api_search`): the tool as it
# is now, and the one a model from before it knows.
SEARCH_TOOLS = ("web_search_20260209", "web_search_20250305")
SEARCH_TOKENS = 2048
SEARCH_USES = 2
SEARCH_RESULTS = 8
SEARCH_SECONDS = 120.0
SEARCH_ASK = "Search the web for this query and do nothing else: "
# On a block: the request up to and with it is kept in the API's cache (five minutes) and
# read from there by a request that begins the same. A request takes four at most.
CACHE_MARK = {"cache_control": {"type": "ephemeral"}}
REFUSED_KEY = (
    "Anthropic refused this key ({status}). It may be a Claude subscription token, which the "
    "API does not take; use the Claude Code provider for a subscription."
)
# How a model is asked to think (K-dusunme-blok), by the first start of its id it has: "on",
# it thinks unasked (asked, its summary is shown); "adaptive", only asked, as hard as its
# level says; "summarised", the same, and its summary is shown unasked (Opus 4.6, Sonnet
# 4.6: `display` is not sent); "budget", a number of tokens - the only way on these.
# shortcut: any other id (a gateway's own name, a model newer than this) is asked nothing,
# as before; add its start here when its way is known.
THINKS = {
    "claude-opus-5": "on", "claude-opus-4-8": "adaptive", "claude-opus-4-7": "adaptive",
    "claude-opus-4-6": "summarised", "claude-sonnet-5-5": "on", "claude-sonnet-5": "adaptive",
    "claude-sonnet-4-6": "summarised", "claude-haiku-5": "on", "claude-fable-5": "on",
    "claude-haiku-4-5": "budget", "claude-sonnet-4-5": "budget", "claude-opus-4-5": "budget",
}
MIN_BUDGET = 1024  # the least the API takes
THOUGHT = ("thinking", "redacted_thinking")
# On an answer sent back as it was (`StepResult.blocks`), until `_replayed` takes it off: the
# digest of what was sent before it when it was written.
AFTER = "_after"


def _said(exc: httpx2.HTTPError, key: str | None) -> str:
    """What a failed request says; a key refused is said so, with what the server said of it
    (a key of another workspace, ...)."""
    status = exc.response.status_code if isinstance(exc, httpx2.HTTPStatusError) else None
    if status not in (401, 403):
        return _describe(exc)
    told = _describe(exc).partition(": ")[2]
    # A gateway may echo back what it was sent: neither the key nor anything like one is shown.
    # shortcut: a part of a key that is not sk-ant-... is not caught; mask by length if one is seen.
    told = re.sub(r"sk-ant-\S*", "[key]", told.replace(key, "[key]") if key else told)
    return REFUSED_KEY.format(status=status) + (f" It said: {told}" if told else "")


def _word(value: object) -> str:
    """A reason the API gives (an error code, a refusal's category) as it is passed on:
    one plain word, or nothing."""
    return value if isinstance(value, str) and re.fullmatch(r"[\w-]{1,60}", value) else ""


def _names_the_tool(response: httpx2.Response) -> bool:
    """Whether a refusal is about the search tool that was asked for: its error message
    names it. Any other refusal - and one that cannot be read - is not asked again: a
    second request is paid for like the first. Measured on 11 Oct 2026 with
    claude-haiku-4-5: "... does not support programmatic tool calling. The following
    tools have `allowed_callers` that require it: web_search ..." - the tool's name is
    in it, its type is not, so the name is what is looked for."""
    try:
        message = response.json()["error"]["message"]
    except (ValueError, LookupError, TypeError):
        return False
    return isinstance(message, str) and "web_search" in message


def _whole(arguments: str) -> bool:
    """Whether a tool call's arguments came to their end: a JSON object."""
    try:
        return isinstance(json.loads(arguments), dict)
    except ValueError:
        return False


def _object(arguments: str) -> dict:
    """A tool call's arguments as the API's `input`: the object, or {} for any other."""
    try:
        told = json.loads(arguments or "{}")
    except ValueError:
        return {}
    return told if isinstance(told, dict) else {}


def _replayed(system: str, tools: list[dict] | None, history: list[dict], strips: bool) -> str:
    """The history as it is sent: each answer kept as the API gave it, but - on a model that
    checks it (`strips`) - without its thinking where anything sent before it is no longer
    what it was written after (a step's own notes not sent again, older results trimmed, a
    summary): such thinking is refused, never edited. What it was written after is a digest
    of the system text, the tools and the messages (not the cache marks, placed after this).
    Returns that digest for this step."""
    sent = hashlib.sha256(json.dumps([system, tools], sort_keys=True).encode())
    for message in history:
        after = message.pop(AFTER, None)
        if strips and after is not None and after != sent.hexdigest():
            message["content"] = [b for b in message["content"] if b.get("type") not in THOUGHT]
        sent.update(json.dumps(message, sort_keys=True).encode())
    return sent.hexdigest()


def search_results(told: object) -> list[dict]:  # noqa: C901
    """The results of a search the API made, out of its answer: what its
    `web_search_tool_result` blocks list - never what the model wrote, which could be
    of its own making. A summary is the passage the model cited from that page, where
    it cited one. ModelUnavailable says why there are none."""
    content = told.get("content") if isinstance(told, dict) else None
    blocks = [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []
    cited: dict[str, str] = {}
    for block in blocks:
        marks = block.get("citations") if block.get("type") == "text" else None
        for mark in marks if isinstance(marks, list) else []:
            if isinstance(mark, dict) and isinstance(mark.get("cited_text"), str):
                cited.setdefault(str(mark.get("url")), mark["cited_text"])
    results: dict[str, dict] = {}
    searched, failed = False, None
    for block in blocks:
        if block.get("type") != "web_search_tool_result":
            continue
        # A list of results - or, with HTTP 200 all the same, one object that says why not.
        given = block.get("content")
        if isinstance(given, dict):
            failed = _word(given.get("error_code"))
        searched = searched or isinstance(given, list)
        for one in given if isinstance(given, list) else []:
            url = one.get("url") if isinstance(one, dict) else None
            if isinstance(url, str):
                results.setdefault(
                    url, {"title": one.get("title"), "url": url, "snippet": cited.get(url, "")}
                )
    if results:
        return list(results.values())[:SEARCH_RESULTS]
    stop = told.get("stop_reason") if isinstance(told, dict) else None
    details = told.get("stop_details") if isinstance(told, dict) else None
    category = _word(details.get("category")) if isinstance(details, dict) else ""
    if failed is not None:
        raise ModelUnavailable("the search failed" + (f": {failed}" if failed else ""))
    if stop == "refusal":
        raise ModelUnavailable(
            "the model declined to search" + (f" ({category})" if category else ""))
    if stop in ("pause_turn", "max_tokens"):
        raise ModelUnavailable(f"the search did not finish ({stop})")
    raise ModelUnavailable("the search found nothing" if searched else "the model made no search")


def to_anthropic(messages: list[dict]) -> tuple[str, list[dict]]:
    """Rewrite chat-completions history as a system text and content-block messages."""
    system: list[str] = []
    out: list[dict] = []
    for message in messages:
        role = message["role"]
        if role == "system":
            system.append(message["content"])
        elif role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": message["tool_call_id"],
                "content": message["content"],
            }
            # Results of one assistant message answer together, in one user message.
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
        elif role == "assistant" and message.get("blocks") and [
                b.get("id") for b in message["blocks"]["content"] if b.get("type") == "tool_use"
        ] == [call["id"] for call in message.get("tool_calls") or ()]:
            # As the API gave it, its thinking first (`StepResult.blocks`): never rebuilt -
            # unless KOLONİ filed calls of its own under it since (a lead beside, a team's
            # request), which it does not hold: rebuilt below then, without its thinking.
            kept = message["blocks"]
            out.append({"role": "assistant", "content": list(kept["content"]),
                        AFTER: kept["after"]})
        elif role == "assistant":
            blocks: list[dict] = []
            if message.get("content"):
                blocks.append({"type": "text", "text": message["content"]})
            for call in message.get("tool_calls") or []:
                blocks.append({
                    "type": "tool_use",
                    "id": call["id"],
                    "name": call["function"]["name"],
                    "input": _object(call["function"]["arguments"]),
                })
            if blocks:  # the API refuses an empty message
                out.append({"role": "assistant", "content": blocks})
        elif "files" in message:
            # The files sent as they are (slice 85b): images as base64 blocks after the text.
            # (The API takes no video: KOLONİ never says one of its models does.)
            out.append({"role": "user", "content": [{"type": "text", "text": message["content"]}, *(
                {"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}}
                for kind, mime, data in files_of(message) if kind == "image")]})
        else:
            out.append({"role": "user", "content": message["content"]})
    return "\n\n".join(system), out


def _told(model_id: str, response: httpx2.Response) -> tuple[ModelInfo, int | None]:
    """What the Models API says of a model: the levels it takes, the most it reads, and
    the most it may write. What it does not say, or not in that shape, stays unknown."""
    try:
        told = response.json()
    except ValueError:
        told = None
    told = told if isinstance(told, dict) else {}
    capabilities = told.get("capabilities")
    effort = capabilities.get("effort") if isinstance(capabilities, dict) else None
    takes = tuple(
        level for level in EFFORTS
        if isinstance(effort, dict) and effort.get("supported") is True
        and isinstance(effort.get(level), dict) and effort[level].get("supported") is True
    )
    info = ModelInfo(
        model_id, True, efforts=takes or None,
        context_window=count_of(told.get("max_input_tokens")),
    )
    return info, count_of(told.get("max_tokens"))


class AnthropicClient:
    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        model_id: str | None,
        transport: httpx2.AsyncBaseTransport | None = None,
        stall_seconds: float = 120.0,
        first_token_seconds: float = 900.0,
        workspace_id: str | None = None,
    ):
        self._base = base_url.rstrip("/")
        self._key = api_key
        # The workspace the key belongs to, where the user named one: it goes with
        # every request, as the key does.
        self._workspace = workspace_id or None
        self._model_id = model_id
        self._transport = transport
        self._stall_seconds = stall_seconds
        self._first_token_seconds = first_token_seconds
        # What the Models API said of each model asked about, and the most it may write.
        self._known: dict[str, tuple[ModelInfo, int | None]] = {}
        # Told the headers of each answer to a step, which say its rate limits (slice 73).
        self.on_limits = None

    def _headers(self) -> dict[str, str]:
        """What every request to the API carries."""
        headers = {"x-api-key": self._key or "", "anthropic-version": API_VERSION}
        if self._workspace:
            headers["anthropic-workspace-id"] = self._workspace
        return headers

    def _client(self, timeout: float | None) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            headers=self._headers(),
            transport=self._transport,
            timeout=httpx2.Timeout(timeout, connect=5.0),
        )

    async def models(self) -> list[str]:
        """The ids of the models this key can use, as the API lists them: page after
        page while it says there are more, a few pages at most. No tokens are spent."""
        if not self._key:
            raise OwnStop("this provider needs an API key")
        listed: list[str] = []
        after: str | None = None
        try:
            async with self._client(MODELS_SECONDS) as http:
                for _ in range(MAX_MODEL_PAGES):
                    response = await http.get(
                        f"{self._base}/v1/models", params={"after_id": after} if after else None
                    )
                    response.raise_for_status()
                    told = response.json()
                    data = told.get("data") if isinstance(told, dict) else None
                    if not isinstance(data, list):
                        raise ModelUnavailable(
                            "the model server did not answer with a list of models")
                    ids = [str(m["id"]) for m in data if isinstance(m, dict) and m.get("id")]
                    listed += ids
                    last = told.get("last_id")
                    after = last if isinstance(last, str) and last else (ids[-1] if ids else None)
                    if told.get("has_more") is not True or not ids:
                        break
        except httpx2.HTTPError as exc:
            raise ModelUnavailable(_said(exc, self._key)) from exc
        except ValueError:
            raise ModelUnavailable(
                "the model server did not answer with a list of models") from None
        return list(dict.fromkeys(listed))

    async def info(self) -> ModelInfo:
        """Confirm the key and the model exist; no tokens are spent."""
        if not self._key:
            raise OwnStop("this provider needs an API key")
        if not self._model_id:
            raise OwnStop("choose a model for this provider")
        return (await self._look_up(self._model_id, 30.0))[0]

    async def _look_up(self, model_id: str, seconds: float) -> tuple[ModelInfo, int | None]:
        """What the Models API says of a model (`_told`), asked once and kept. A failed
        asking is not kept: `info()` takes a kept answer for "the model exists"."""
        if model_id not in self._known:
            try:
                async with self._client(seconds) as http:
                    response = await http.get(f"{self._base}/v1/models/{model_id}")
                    response.raise_for_status()
            except httpx2.HTTPError as exc:
                raise ModelUnavailable(_said(exc, self._key)) from exc
            self._known[model_id] = _told(model_id, response)
        return self._known[model_id]

    # Its `info()` spends nothing and is remembered: a page may ask it (`/api/roles/models`).
    free_info = True

    async def search(self, query: str, spent=None) -> list[dict]:
        """Have the API search the web with its own search tool, on this provider's
        model: one request, a couple of searches at most. Returns what the search
        found (`search_results`); ModelUnavailable says why there is nothing. `spent`
        is told the tokens the answer reports (sent, written) - also for an answer
        that found nothing: it was paid for all the same."""
        if not self._key:
            raise OwnStop("this provider needs an API key")
        if not self._model_id:
            raise OwnStop("choose a model for this provider")
        payload = {
            "model": self._model_id,
            "max_tokens": SEARCH_TOKENS,
            "tools": [{"type": SEARCH_TOOLS[0], "name": "web_search", "max_uses": SEARCH_USES}],
            "messages": [{"role": "user", "content": SEARCH_ASK + query}],
        }
        try:
            async with self._client(SEARCH_SECONDS) as http:
                response = await http.post(f"{self._base}/v1/messages", json=payload)
                if response.status_code == 400 and _names_the_tool(response):
                    # A model from before the tool refuses it: asked once more, with
                    # the one it knows.
                    payload["tools"][0]["type"] = SEARCH_TOOLS[1]
                    response = await http.post(f"{self._base}/v1/messages", json=payload)
                response.raise_for_status()
                told = response.json()
        except httpx2.HTTPError as exc:
            raise ModelUnavailable(_said(exc, self._key)) from exc
        except ValueError:
            raise ModelUnavailable("the model server sent an unreadable answer") from None
        usage = told.get("usage") if isinstance(told, dict) else None
        if spent is not None and isinstance(usage, dict):
            made = usage.get("output_tokens")
            spent(_input_tokens(usage), made if isinstance(made, int) else None)
        return search_results(told)

    # The API says what a step sent when its answer begins: a step cut before its end
    # can still be counted (`so_far`).
    reports_early = True
    # A step can mark what the next one sends again, to be read from the API's cache.
    caches = True
    # Its answers go back as they came (`StepResult.blocks`): the history carries them.
    replays_blocks = True

    async def stream_step(  # noqa: C901
        self, model_id, messages, tools, on_delta, on_thinking=None, so_far=None,
        cache: bool = False, effort: str | None = None, max_tokens: int | None = None,
        think: bool = True,
    ) -> StepResult:
        """`max_tokens`: the most it may write (a summary of KOLONİ's own), under the
        model's own most; a step cut there says so (`cut`).
        `so_far` is told the tokens reported up to now (sent, written, and of what was
        sent: read again from the cache, written to it), each time the stream reports
        any: what is on hand if the step never comes to its end. `cache`: this step is
        one of several that send the same beginning, so that is marked for the cache -
        the system text (the tools come before it) and the end of what is sent now and
        will be sent again: not a `Transient` message at the end, which the next step does
        not send - a mark there would be written to the cache at every step and never read.
        `effort`: the model's level (`output_config`); None: its own default.
        Where its caller hears its thinking (`on_thinking`: an agent's step, not KOLONİ's own
        one-off asking), a model of THINKS is asked to think - adaptive, its summary shown
        (the newest send none unasked), or with a budget - and the answer comes back whole
        (`StepResult.blocks`), its thinking signed, to be sent back as it came. `think`
        False: asked so only where its model thinks unasked (THINKS "on") - none of it would
        be sent back (a room's member, told how its room stands at each step and never again).
        shortcut: the UI shows that it is thinking, not the summary's words; show them if
        asked for."""
        system, history = to_anthropic(messages)
        shape = [
            {
                "name": tool["function"]["name"],
                "description": tool["function"]["description"],
                "input_schema": tool["function"]["parameters"],
            }
            for tool in tools or ()
        ] or None
        family = next((way for start, way in THINKS.items() if model_id.startswith(start)), None)
        # (Haiku 4.5 and older check nothing, and in a tool loop want the thinking kept.)
        # shortcut: KOLONİ's history is not sent the same from step to step (a step's own notes,
        # trimmed results, summaries), so thinking from before such a change is left out;
        # make those append-only if too much is lost. (Not the API's own `drop_block`, a beta
        # - `thinking-binding-controls-2026-08-01` - a gateway may not take.)
        after = _replayed(system, shape, history, strips=family != "budget")
        kept = len(messages)
        while kept and isinstance(messages[kept - 1], Transient):
            kept -= 1
        # What the messages before them become (a transient one is never joined to another).
        at = len(to_anthropic(messages[:kept])[1]) - 1 if kept < len(messages) else len(history) - 1
        if cache and at >= 0 and history[at]["content"]:
            # Copies: a block is never marked in place, where a later step would find it.
            last = history[at]
            blocks = last["content"]
            if isinstance(blocks, str):
                blocks = [{"type": "text", "text": blocks}]
            if blocks[-1].get("type") not in THOUGHT:  # (thinking takes no mark)
                history[at] = {**last, "content": [*blocks[:-1], {**blocks[-1], **CACHE_MARK}]}
        # The most it may write, asked of the Models API where not known yet (a step that
        # comes before any `info()`, a model other than the provider's own).
        # shortcut: a failed asking is asked again at every step (a fast 404 where a
        # gateway has no Models API); upgrade to remembering it if one is slow to say so.
        own = None
        with contextlib.suppress(ModelUnavailable):
            own = (await self._look_up(model_id, MODELS_SECONDS))[1]
        most = min(own, MAX_TOKENS) if own else UNKNOWN_MAX_TOKENS
        payload: dict = {
            "model": model_id,
            "max_tokens": min(most, max_tokens) if max_tokens else most,
            "messages": history,
            "stream": True,
        }
        if effort:
            payload["output_config"] = {"effort": effort}
        thinks = family if on_thinking and (think or family == "on") else None
        if thinks in ("on", "adaptive", "summarised"):
            payload["thinking"] = {"type": "adaptive", **(
                {} if thinks == "summarised" else {"display": "summarized"})}
        elif thinks == "budget" and payload["max_tokens"] // 2 >= MIN_BUDGET:
            # shortcut: half of what the step may write, whatever its level; set it by the
            # level if a budget is seen to be too much or too little. An answer of its open
            # tool loop kept without its thinking (from before this, or cut) is refused here.
            payload["thinking"] = {"type": "enabled", "budget_tokens": payload["max_tokens"] // 2}
        if system:
            payload["system"] = (
                [{"type": "text", "text": system, **CACHE_MARK}] if cache else system
            )
        if shape:
            payload["tools"] = shape
        content: list[str] = []
        # Every block as it comes, by its index: what is sent back (`StepResult.blocks`).
        raw: dict[int, dict] = {}
        calls: dict[int, dict] = {}
        input_tokens: int | None = None
        output_tokens: int | None = None
        cached: tuple[int | None, int | None] = (None, None)  # read again, written
        # Why the model stopped, and the block it was writing when it did.
        stop: object = None
        details: object = None
        last: int | None = None
        try:
            async with (
                self._client(None) as http,
                http.stream("POST", f"{self._base}/v1/messages", json=payload) as response,
            ):
                if self.on_limits:  # (a 429's too; keeping them never breaks the step)
                    with contextlib.suppress(Exception):
                        self.on_limits(response.headers)
                if response.status_code >= 400:
                    await response.aread()
                    response.raise_for_status()
                lines = response.aiter_lines().__aiter__()
                answering = False
                while True:
                    limit = self._stall_seconds if answering else self._first_token_seconds
                    try:
                        line = await asyncio.wait_for(anext(lines), limit)
                    except StopAsyncIteration:
                        break
                    except TimeoutError:
                        raise ModelUnavailable(
                            f"model server sent nothing for {limit:g} seconds"
                        ) from None
                    answering = True
                    if not line.startswith("data:"):
                        continue
                    event = json.loads(line[5:].strip())
                    kind = event.get("type")
                    if kind == "error":
                        error = event.get("error") or {}
                        failed = ModelUnavailable(
                            f"model server reported an error: {error.get('message')}")
                        # (Overloaded, said in the stream: as short as a 529 - `brief`.)
                        failed.retry_in = 1.0 if error.get("type") == "overloaded_error" else None
                        raise failed
                    if kind == "message_start":
                        usage = (event.get("message") or {}).get("usage")
                        input_tokens, cached = _input_tokens(usage), _cache_tokens(usage)
                        if so_far:
                            so_far(input_tokens, output_tokens, *cached)
                    elif kind == "message_delta":
                        made = (event.get("usage") or {}).get("output_tokens")
                        output_tokens = made if isinstance(made, int) else output_tokens
                        if so_far:
                            so_far(input_tokens, output_tokens, *cached)
                        delta = event.get("delta") or {}
                        stop = delta.get("stop_reason") or stop
                        details = delta.get("stop_details") or details
                    elif kind == "content_block_start":
                        last = event.get("index", 0)
                        block = event.get("content_block") or {}
                        raw[last] = dict(block)  # (redacted thinking comes whole)
                        if block.get("type") == "tool_use":
                            calls[event.get("index", 0)] = {
                                "id": block.get("id") or "", "name": block.get("name") or "",
                                "arguments": "",
                            }
                    elif kind == "content_block_delta":
                        delta = event.get("delta") or {}
                        # (A delta of no block that began is kept nowhere.)
                        into = raw.get(event.get("index", 0), {})
                        if delta.get("type") == "text_delta" and delta.get("text"):
                            content.append(delta["text"])
                            into["text"] = into.get("text", "") + delta["text"]
                            await on_delta(delta["text"])
                        elif delta.get("type") == "thinking_delta":
                            into["thinking"] = into.get("thinking", "") + (
                                delta.get("thinking") or "")
                            if on_thinking:
                                await on_thinking(delta.get("thinking") or "")
                        elif delta.get("type") == "signature_delta":
                            into["signature"] = into.get("signature", "") + (
                                delta.get("signature") or "")
                        elif delta.get("type") == "input_json_delta":
                            slot = calls.get(event.get("index", 0))
                            if slot is not None:
                                slot["arguments"] += delta.get("partial_json") or ""
        except httpx2.HTTPError as exc:
            raise unavailable(_said(exc, self._key), exc) from exc
        except ValueError as exc:
            raise ModelUnavailable(f"model server sent an unreadable stream: {exc}") from exc
        if stop == "refusal":
            # Not an empty answer: the turn fails, and says what happened.
            category = _word(details.get("category")) if isinstance(details, dict) else ""
            raise ModelUnavailable(
                "the model declined to answer" + (f" ({category})" if category else ""))
        cut = None
        if stop == "max_tokens":
            # The output limit came in the middle of something. In a tool call (its
            # arguments are no whole JSON object): that call is not run. Otherwise in
            # the text, which is kept and says so.
            if last in calls and not _whole(calls[last]["arguments"]):
                cut = last
            else:
                mark = ("\n\n" if content else "") + CUT
                content.append(mark)
                await on_delta(mark)
        made = [
            ToolCallRequest(
                c["id"] or f"call_{uuid.uuid4().hex[:8]}", c["name"], c["arguments"] or "{}",
                i == cut)
            for i, c in sorted(calls.items())
        ]
        for i, call in zip(sorted(calls), made, strict=True):
            # Its arguments as the API holds them, under the id its result is sent with.
            raw[i] = {**raw[i], "id": call.id, "input": _object(call.arguments)}
        # (A thinking block cut before its signature cannot be sent back: the last one only.
        # Nor a text block that began and said nothing: the API takes no empty text, and
        # reads none in what an answer was written after, so leaving it out is no edit.)
        answer = [b for _, b in sorted(raw.items())
                  if (b.get("type") != "thinking" or b.get("signature"))
                  and (b.get("type") != "text" or b.get("text"))]
        return StepResult(
            content="".join(content),
            tool_calls=made,
            blocks={"after": after, "content": answer} if any(
                b.get("type") in THOUGHT for b in answer) else None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read=cached[0],
            cache_write=cached[1],
            cut=stop == "max_tokens",
        )
