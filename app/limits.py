"""What is left of a CLI's plan, why an agent's model failed, and who else has room.

Codex says what is left without a model call (`codex app-server`, measured 11 Oct 2026):
`app_server` is the one place it is asked, and a native run of it says it too
(`Limits.codex_said`). Claude Code says it in every run of its own (a
`rate_limit_event`): the last one is kept. It is read afresh in one short turn of its own
(`claude_turn`) only when the user asks, and the status line of the user's own Claude Code
sessions sends it as it changes (`of_session`). agy (`agy -p /quota`) and Copilot
(`account.getQuota`) say it without a model turn too (measured 24 Oct 2026): they are read
in the background as they are looked at, at most once in `AUTO_EVERY` (`Limits.refresh`).
No other CLI says it: theirs is unknown, never a made-up number. These are the limits of
the account the provider's CLI is signed in to - the user's own, or the provider's own
sign-in folder for KOLONİ (`cli_home`, K-claude-hesap); that account's id is dropped where
it is read. An API says its rate limits in the headers of every answer (Anthropic's
`anthropic-ratelimit-*`, an OpenAI-compatible service's `x-ratelimit-*`, slice 73): the last
are kept in memory (`Limits.api_said`). DeepSeek says its balance when asked
(`deepseek_balance`, Check now only).
"""

import asyncio
import contextlib
import json
import logging
import math
import re
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import httpx2
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import Agent, LimitReading, Provider
from app.model_agy import AgyClient
from app.model_cli import (
    ClaudeCliClient,
    CodexCliClient,
    _brief,
    _dict,
    codex_skills_off,
    when,
)
from app.model_client import USED_UP, ModelUnavailable, OwnStop, _describe
from app.model_native import CopilotNativeClient, _framed
from app.raw import of

if TYPE_CHECKING:
    from app.team import Entry

log = logging.getLogger(__name__)
SECONDS = 15.0  # `codex app-server`, from before it is started to its answer
MAX_BYTES = 2**20  # of all it says in that time, its notifications included
NOT_READ = "not read yet"
# How long each of Claude Code's windows is. Only what was measured: a window of another
# name is shown by that name, without a length.
# (seven_day: seen with the real CLI on 11 Oct 2026, resetting when the weekly limit does.)
CLAUDE_MINUTES = {"five_hour": 300, "seven_day": 10080}
# Claude Code's windows that are not its plan's (seen 25 Oct 2026, B-61: the extra usage
# beyond the plan, with no length): not shown, and nothing is stepped down by them.
NOT_THE_PLANS = {"seven_day_overage_included"}
FROM_RUNS = "its last run"
SHORT_RUN = "a short run to read it"
FROM_SESSION = "your Claude Code session"
CLAUDE_SECONDS = 60.0  # Claude Code's one short turn, from its start to its end
# The status line's numbers: a reset after 2100 is no reset time anyone was told.
LATEST_RESET = 4_102_444_800
# Two resets of a window this close are one window, said by two of Claude Code's ways; a
# window's next one resets hours later.
# shortcut: 10 minutes is not measured; measure rate_limit_event's resetsAt against the
# status line's resets_at of one window and narrow it to that.
SAME_WINDOW = 600
DOES_NOT_SAY = "this CLI does not say what is left of its plan"
NO_PLAN = "a model server does not say what is left of a plan"
NOT_RUN = "not run yet: Claude Code says its limits in its runs, and none has said them yet"
NOT_ANSWERED = "not run yet: the API says its rate limits in each answer"
FROM_ANSWER = "its last answer"
# DeepSeek's API, the one service whose key is asked its balance (`deepseek_balance`): only a
# provider whose base URL is on its host is (`is_deepseek`), and the key goes only there.
DEEPSEEK = "https://api.deepseek.com"
FAILURES = ("rate_limited", "credits_exhausted", "signed_out", "cli_crashed", "empty_output",
            "other")
# The CLIs that say what is left of their plan without a model turn, read as they are looked
# at (`Limits.refresh`): no more often than this, in seconds, read well or not.
QUIET = ("agy_cli", "copilot_cli")
AUTO_EVERY = 600
NAMES = {"codex_cli": "Codex", "claude_cli": "Claude Code", "agy_cli": "agy",
         "copilot_cli": "Copilot"}
# K-claude-hesap: the kinds a provider may give a sign-in folder of its own, and where those are
# in the runtime (`cli_home`).
SIGN_IN_KINDS = ("claude_cli", "codex_cli")
CLI_HOMES = "cli-homes"
# A provider's id as KOLONİ makes one (`db.models.new_id`): only such a name is a folder there -
# a row restored from a backup could hold "..".
PROVIDER_ID = re.compile(r"[0-9a-f]{32}")
PREMIUM = "premium requests"  # Copilot's one window (`of_copilot`)
AGY_MINUTES = {"weekly": 10080}  # the one window agy 1.4.7 was seen to name


class _AppServer(CodexCliClient):
    def _arguments(self, workdir: Path) -> list[str]:
        # The user's own MCP servers and skills are off, as for a model step. Before the
        # subcommand: `app-server` takes the settings given to `codex` itself (the real
        # CLI answered when started this way, 11 Oct 2026).
        arguments: list[str] = []
        for name in self._own_mcp_servers():
            arguments += ["-c", f"mcp_servers.{name}.enabled=false"]
        return [*arguments, *codex_skills_off(self._env), "app-server"]


async def app_server(  # noqa: C901
    executable: str | None, timeout: float = SECONDS, launcher: list[str] | None = None,
    home: Path | None = None,
) -> dict:
    """What `codex app-server` answers to `account/rateLimits/read`: no model is called.
    Started and ended the way a Codex model step is. TimeoutError when all of it - its
    line being built and its start included - takes longer than `timeout`; then, as on
    every other path, it is ended before this returns (`_end`: a few seconds at most).
    ModelUnavailable when it cannot be started or says no."""
    client = _AppServer(executable, launcher=launcher, home=home)
    workdir = Path(tempfile.mkdtemp(prefix="koloni-limits-"))
    starting: asyncio.Future | None = None
    complaints: asyncio.Future | None = None
    try:
        async with asyncio.timeout(timeout):
            command, shim = client._command()
            arguments = await asyncio.to_thread(client._arguments, workdir)
            # Not given up half-way: a Codex that was started is one that is ended below.
            async def start() -> tuple:
                return await client._start([*command, *arguments], shim, workdir)

            starting = asyncio.ensure_future(start())
            try:
                process, _job = await asyncio.shield(starting)
            except OSError as exc:
                raise OwnStop(f"Codex could not be started: {exc.strerror or exc}") from None
            stdin, stdout, errors = process.stdin, process.stdout, process.stderr
            assert stdin is not None and stdout is not None and errors is not None  # piped
            read = 0

            async def unheard() -> None:
                # Read, so that it cannot fill up; none of it is kept.
                while await errors.read(2**16):
                    pass

            complaints = asyncio.ensure_future(unheard())

            async def ask(message: dict) -> None:
                stdin.write((json.dumps({"jsonrpc": "2.0", **message}) + "\n").encode())
                await stdin.drain()

            async def answer(to: int) -> object:
                nonlocal read
                # Its notifications (`account/updated`, …) come in between: passed over,
                # however many - the time and what they add up to are the bound.
                while raw := await stdout.readline():
                    read += len(raw)
                    if read > MAX_BYTES:
                        raise ModelUnavailable(
                            "Codex said too much without saying what is left of its plan")
                    try:
                        told = json.loads(raw)
                    except ValueError:
                        continue
                    # A request of its own can carry the same id: an answer names no method.
                    if isinstance(told, dict) and told.get("id") == to and "method" not in told:
                        if "result" not in told:
                            raise ModelUnavailable(
                                "Codex would not say what is left of its plan")
                        return told["result"]
                raise ModelUnavailable("Codex ended without saying what is left of its plan")

            await ask({"id": 1, "method": "initialize",
                       "params": {"clientInfo": {"name": "koloni", "version": "0"}}})
            await answer(1)
            await ask({"method": "initialized"})
            await ask({"id": 2, "method": "account/rateLimits/read"})
            told = await answer(2)
    except (BrokenPipeError, ConnectionResetError, ValueError):
        raise ModelUnavailable("Codex ended without saying what is left of its plan") from None
    finally:
        # On every path: Codex and anything it started end here.
        if starting is not None:
            with contextlib.suppress(Exception):
                await client._end(*await starting)
        if complaints is not None:
            complaints.cancel()
            with contextlib.suppress(BaseException):
                await asyncio.wait({complaints}, timeout=2)
        shutil.rmtree(workdir, ignore_errors=True)
    # Whose account it is is nobody's business here: gone before anything is kept.
    return {k: v for k, v in told.items() if k != "accountId"} if isinstance(told, dict) else {}


class _OneTurn(ClaudeCliClient):
    def _arguments(self, workdir: Path) -> list[str]:
        # A model step's line (none of its own tools, nor the user's MCP servers, skills,
        # plugins or settings; no session kept) without its answer format, and a one-line
        # system prompt in place of Claude Code's long one: as little as a turn can cost.
        return [
            "-p", "--tools", "", "--strict-mcp-config", "--no-session-persistence",
            "--setting-sources", "", "--output-format", "stream-json", "--verbose",
            "--system-prompt", "Answer with one word.", "--model", self._model or "haiku",
        ]


async def claude_turn(
    executable: str | None, timeout: float = CLAUDE_SECONDS, launcher: list[str] | None = None,
    home: Path | None = None,
) -> dict:
    """The `rate_limit_info` of the last `rate_limit_event` of one short Claude Code turn:
    its cheapest model (`haiku`), no tools, a one-word answer. Started and ended the way a
    model step is. ModelUnavailable when it cannot be started, does not end within
    `timeout` or names no limit."""
    client = _OneTurn(executable, "haiku", timeout=timeout, launcher=launcher, home=home)
    said: list[dict] = []
    client.on_limits = said.append
    workdir = Path(tempfile.mkdtemp(prefix="koloni-limits-"))
    try:
        command, shim = client._command()
        # Nobody's work: nothing of it is in an agent's raw stream.
        with of(None):
            code, stdout, stderr = await client._run(
                [*command, *client._arguments(workdir)], shim, "Say ok.", workdir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    client._limits(stdout)
    if not said:
        why = f": {_brief(stderr)}" if _brief(stderr) else ""
        raise ModelUnavailable(
            f"Claude Code ended without saying its limits (exit code {code}){why}")
    return said[-1]


async def agy_quota(
    executable: str | None, homes: Path | None, timeout: float = SECONDS,
    launcher: list[str] | None = None,
) -> dict:
    """What `agy -p /quota --output-format json` answers: no model turn (`num_turns: 0`,
    measured on 1.4.7). Run as native agy is, in a home of KOLONİ's under `homes` (the
    system's temp folder if None; its sign-in comes from the Windows vault) and with none of
    the user's Gemini or Antigravity variables; the home goes after. Only its `command` is
    handed on. TimeoutError past `timeout`; ModelUnavailable when it fails or answers what
    cannot be read."""
    homes = homes or Path(tempfile.gettempdir())
    homes.mkdir(parents=True, exist_ok=True)
    home = Path(tempfile.mkdtemp(prefix="agy-", dir=homes))  # (as `sweep_homes` clears them)
    client = AgyClient(executable, reads=False, launcher=launcher,
                       env={"USERPROFILE": str(home), "HOME": str(home)})
    try:
        try:
            # A list, never a shell's line: Git Bash's once made a path of "/quota".
            code, printed, complaint = await client.run_status(
                ["-p", "/quota", "--output-format", "json"], timeout)
        except OSError as exc:
            raise OwnStop(f"agy could not be started: {exc.strerror or exc}") from None
    finally:
        shutil.rmtree(home, ignore_errors=True)
    if code:
        why = _brief(complaint)
        raise ModelUnavailable(f"agy exited with code {code}" + (f": {why}" if why else ""))
    # One JSON document, written whole or as its last line after anything else it prints.
    for part in (printed, *reversed(printed.splitlines())):
        with contextlib.suppress(ValueError):
            told = json.loads(part)
            if isinstance(told, dict) and "command" in told:
                return {"command": told["command"]}
    raise ModelUnavailable("agy's answer could not be read")


async def copilot_quota(
    executable: str | None, token: str | None, timeout: float = SECONDS,
    launcher: list[str] | None = None,
) -> dict:
    """What Copilot headless answers to `account.getQuota` (measured on 1.0.91): only its
    `quotaSnapshots` are handed on."""
    told = await _copilot_asked(executable, token, "account.getQuota",
                                "what is left of its plan", timeout, launcher)
    # Whose account it is is nobody's business here: only what is left of it is kept.
    return {"quotaSnapshots": _dict(told).get("quotaSnapshots")}


def is_deepseek(provider: Provider) -> bool:
    """Whether a provider is DeepSeek's API: an OpenAI-compatible one on its host."""
    ours, theirs = urlsplit(DEEPSEEK), urlsplit(provider.base_url or "")
    return provider.kind == "openai_compat" and (theirs.scheme, theirs.netloc) == (
        ours.scheme, ours.netloc)


async def deepseek_balance(key: str | None, timeout: float = SECONDS) -> object:
    """What DeepSeek's `GET /user/balance` answers, the key sent as its Bearer header only.
    ModelUnavailable says why not, never with the answer's own words."""
    if not key:
        raise OwnStop("this provider needs an API key")
    try:
        async with httpx2.AsyncClient(timeout=httpx2.Timeout(timeout, connect=5.0)) as http:
            response = await http.get(f"{DEEPSEEK}/user/balance",
                                      headers={"Authorization": f"Bearer {key}"})
            response.raise_for_status()
            return response.json()
    except httpx2.HTTPStatusError as exc:
        raise ModelUnavailable(
            f"DeepSeek's balance answered {exc.response.status_code}") from None
    except httpx2.HTTPError as exc:
        raise ModelUnavailable(_describe(exc)) from None
    except ValueError:
        raise ModelUnavailable("DeepSeek's balance could not be read") from None


async def copilot_signed_in(
    executable: str | None, token: str | None, timeout: float = SECONDS,
    launcher: list[str] | None = None,
) -> dict:
    """What Copilot headless answers to `auth.getStatus` (measured on 1.0.103): whether it
    is signed in and how. Its statusMessage names the account: it is never kept."""
    told = _dict(await _copilot_asked(executable, token, "auth.getStatus",
                                      "whether it is signed in", timeout, launcher))
    signed_in, how = told.get("isAuthenticated"), told.get("authType")
    return {"isAuthenticated": signed_in if isinstance(signed_in, bool) else None,
            "authType": how if isinstance(how, str) else None}


async def _copilot_asked(
    executable: str | None, token: str | None, method: str, saying: str, timeout: float,
    launcher: list[str] | None,
) -> object:
    """What Copilot headless answers to `method` after its `ping`: no session, no turn.
    Started as native Copilot is: KOLONİ's empty COPILOT_HOME, the provider's GitHub token
    or else the user's own gh login, nothing of the user's own Copilot set-up. TimeoutError
    past `timeout`; ModelUnavailable when it cannot be started, says no or ends first."""
    client = CopilotNativeClient(executable, api_key=token, launcher=launcher)
    workdir = Path(tempfile.mkdtemp(prefix="koloni-limits-"))
    starting: asyncio.Future | None = None
    complaints: asyncio.Future | None = None
    try:
        async with asyncio.timeout(timeout):
            command, shim = client._command()
            env = client._native_env(workdir)
            argv = [*command, *client._native_arguments(workdir, workdir)]

            # Not given up half-way: a Copilot that was started is one that is ended below.
            async def start() -> tuple:
                return await client._start(argv, shim, workdir, env)

            starting = asyncio.ensure_future(start())
            try:
                process, _job = await asyncio.shield(starting)
            except OSError as exc:
                raise OwnStop(f"Copilot could not be started: {exc.strerror or exc}") from None
            stdin, stdout, errors = process.stdin, process.stdout, process.stderr
            assert stdin is not None and stdout is not None and errors is not None  # piped

            async def unheard() -> None:
                while await errors.read(2**16):  # read, so that it cannot fill up; not kept
                    pass

            complaints = asyncio.ensure_future(unheard())

            async def ask(number: int, method: str) -> object:
                body = json.dumps({"jsonrpc": "2.0", "id": number, "method": method,
                                   "params": {}}).encode("utf-8")
                stdin.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
                await stdin.drain()
                # A request or notification of its own comes in between: it names a method.
                while (told := await _framed(stdout)) is not None:
                    if told.get("id") == number and "method" not in told:
                        if "result" not in told:
                            error = told.get("error")
                            why = _brief(client._hide(str(_dict(error).get("message") or error)))
                            raise ModelUnavailable(
                                f"Copilot would not say {saying}: {why}")
                        return told["result"]
                raise ModelUnavailable(f"Copilot ended without saying {saying}")

            await ask(1, "ping")
            told = await ask(2, method)
    except (BrokenPipeError, ConnectionResetError, ValueError):
        raise ModelUnavailable(f"Copilot ended without saying {saying}") from None
    finally:
        if starting is not None:
            with contextlib.suppress(Exception):
                await client._end(*await starting)
        if complaints is not None:
            complaints.cancel()
            with contextlib.suppress(BaseException):
                await asyncio.wait({complaints}, timeout=2)
        shutil.rmtree(workdir, ignore_errors=True)
    return told


def _number(value: object) -> int | float | None:
    # (A JSON line can hold NaN: that is no number to show, nor to reckon with.)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return value if math.isfinite(value) else None


def _window(name: str | None, minutes: object, used: object, resets: object) -> dict | None:
    if _number(used) is None and when(resets) is None:
        return None  # it says nothing of this window
    return {"name": name, "minutes": minutes if isinstance(minutes, int) else None,
            "used_percent": _number(used), "resets_at": when(resets), "stale": False}


def of_codex(told: object, read_at: datetime) -> dict:
    """What Codex answered, as it is shown; unknown for an answer that cannot be read."""
    limits = told.get("rateLimits") if isinstance(told, dict) else None
    if not isinstance(limits, dict):
        return {"unknown": "Codex's answer could not be read"}
    windows = [
        window for window in (
            _window(None, part.get("windowDurationMins"), part.get("usedPercent"),
                    part.get("resetsAt"))
            for part in (limits.get("primary"), limits.get("secondary"))
            if isinstance(part, dict)
        ) if window
    ]
    credits, plan = limits.get("credits"), limits.get("planType")
    if isinstance(credits, dict):
        balance, has, free = (credits.get(k) for k in ("balance", "hasCredits", "unlimited"))
        credits = {
            "balance": balance if isinstance(balance, str) else None,
            "has_credits": has if isinstance(has, bool) else None,
            "unlimited": free if isinstance(free, bool) else None,
        }
    else:
        credits = None
    plan = plan if isinstance(plan, str) else None
    if not windows and not credits and not plan:
        return {"unknown": "Codex's answer says nothing of its plan"}
    # `reached`: which limit Codex says is reached, if any. For `room` only - not shown.
    return {"read_at": read_at, "source": None, "plan": plan, "windows": windows,
            "credits": credits, "reached": limits.get("rateLimitReachedType") is not None}


def _iso(value: object) -> float | None:
    """A moment a CLI gave as an ISO 8601 string, in seconds since 1970 (as `when` takes it)."""
    try:
        return datetime.fromisoformat(value).timestamp() if isinstance(value, str) else None
    except ValueError:
        return None


def of_agy(told: object, read_at: datetime) -> dict:
    """What agy's /quota answered, as it is shown: a window for each of its groups (its
    models), what is used being what is not left."""
    groups = _dict(_dict(_dict(told).get("command")).get("data")).get("groups")
    windows = []
    for group in groups if isinstance(groups, list) else []:
        group = _dict(group)
        buckets = group.get("buckets")
        # shortcut: a group of more than one bucket shows each by the group's name; name them
        # apart once agy is seen to give one more than its weekly bucket.
        for bucket in map(_dict, buckets if isinstance(buckets, list) else []):
            left = _number(bucket.get("remaining_fraction"))
            window = _window(
                str(group.get("name") or bucket.get("id") or "agy"),
                AGY_MINUTES.get(str(bucket.get("window"))),
                None if left is None else round(100 * (1 - left), 2),
                _iso(bucket.get("reset_time")))
            if window:
                windows.append(window)
    if not windows:
        return {"unknown": "agy's answer says nothing of its plan"}
    return {"read_at": read_at, "source": None, "plan": None, "windows": windows,
            "credits": None}


def of_copilot(told: object, read_at: datetime) -> dict:
    """What Copilot's getQuota answered, as it is shown: its premium requests, what is used
    being what is not left. An unlimited entitlement is no window."""
    # shortcut: chat and completions were measured unlimited and are not read; show them as
    # windows of their own once a plan with a limit on them is seen.
    premium = _dict(_dict(_dict(told).get("quotaSnapshots")).get("premium_interactions"))
    left = _number(premium.get("remainingPercentage"))
    resets = _iso(premium.get("resetDate"))
    # 1.0.103 gave the moment of the call itself as its resetDate (24 Oct 2026): a reset
    # within a few minutes of the reading, or before it, is not known.
    if resets is not None and resets <= read_at.timestamp() + 300:
        resets = None
    window = None if premium.get("isUnlimitedEntitlement") is True else _window(
        PREMIUM, None, None if left is None else round(100 - left, 2), resets)
    if not window:
        return {"unknown": "Copilot's answer says nothing of a limited plan"}
    return {"read_at": read_at, "source": None, "plan": None, "windows": [window],
            "credits": None}


def of_deepseek(told: object, read_at: datetime) -> dict:
    """DeepSeek's balance as it is shown: each currency's total, and whether it says there is
    any. shortcut: its shape is from its API documentation, not seen from a real key here."""
    told = _dict(told)
    infos = told.get("balance_infos")
    parts = [f"{info['total_balance']} {info['currency']}"
             for info in map(_dict, infos if isinstance(infos, list) else [])
             if isinstance(info.get("total_balance"), str)
             and isinstance(info.get("currency"), str)]
    has = told.get("is_available")
    if not parts and not isinstance(has, bool):
        return {"unknown": "DeepSeek's answer says nothing of its balance"}
    return {"read_at": read_at, "source": None, "credits": {
        "balance": ", ".join(parts) or None, "has_credits": has if isinstance(has, bool) else None,
        "unlimited": None}}


def _count(value: str | None) -> int | None:
    # (ASCII digits only: `isdigit` takes "²" and other scripts' digits too, which int() refuses.)
    value = (value or "").strip()
    return int(value) if value.isascii() and value.isdigit() else None


_DURATION = re.compile(r"(\d+(?:\.\d+)?)(ms|s|m|h)")
_UNIT = {"ms": 0.001, "s": 1, "m": 60, "h": 3600}


def _after(duration: str | None, read_at: datetime) -> datetime | None:
    """When an OpenAI-style reset ("6m0s", "1s", "20ms") comes, from when it was said."""
    parts = _DURATION.findall(duration or "")
    if not parts or "".join(n + u for n, u in parts) != (duration or "").strip():
        return None
    try:
        return read_at + timedelta(seconds=sum(float(n) * _UNIT[u] for n, u in parts))
    except OverflowError:  # (a duration past any date)
        return None


def _rfc3339(value: str | None) -> datetime | None:
    try:
        moment = datetime.fromisoformat(value) if value else None
    except ValueError:
        return None
    return moment if moment is None or moment.tzinfo else moment.replace(tzinfo=UTC)


def of_headers(headers, read_at: datetime) -> list[dict]:
    """The rate limits an API's answer says in its headers, a window for each: Anthropic's
    `anthropic-ratelimit-{requests,tokens,input-tokens,output-tokens}-{limit,remaining,reset}`
    (a minute's, its reset an RFC 3339 time), an OpenAI-compatible service's
    `x-ratelimit-{limit,remaining,reset}-{requests,tokens}` (its reset a duration, its window's
    length not said). No share of a plan is said: `used_percent` stays None. [] for none."""
    windows = []
    for part in ("requests", "tokens", "input-tokens", "output-tokens"):
        anthropic = f"anthropic-ratelimit-{part}-"
        if any(headers.get(anthropic + one) for one in ("limit", "remaining")):
            limit, left = (_count(headers.get(anthropic + one)) for one in ("limit", "remaining"))
            resets, minutes = _rfc3339(headers.get(anthropic + "reset")), 1
        else:
            limit, left = (_count(headers.get(f"x-ratelimit-{one}-{part}"))
                           for one in ("limit", "remaining"))
            resets, minutes = _after(headers.get(f"x-ratelimit-reset-{part}"), read_at), None
        if limit is not None or left is not None:
            windows.append({"name": part.replace("-", " "), "minutes": minutes,
                            "used_percent": None, "resets_at": resets, "stale": False,
                            "limit": limit, "remaining": left})
    return windows


def of_claude(info: dict, read_at: datetime) -> dict:
    """Claude Code's `rate_limit_info`, as it is shown: a window for each it names."""
    def percent(share: object) -> int | float | None:
        share = _number(share)
        if share is None:
            return None
        # A window is full only when Claude Code says so: 0.996 is not shown as 100.
        return round(share * 100) if share >= 1 else min(round(share * 100), 99)

    named = info.get("unifiedWindows")
    windows = [
        window for name, part in (named.items() if isinstance(named, dict) else ())
        if isinstance(part, dict) and (window := _window(
            str(name), CLAUDE_MINUTES.get(name), percent(part.get("utilization")),
            part.get("resetsAt")))
    ]
    kind = info.get("rateLimitType")
    if not windows and isinstance(kind, str):
        one = _window(kind, CLAUDE_MINUTES.get(kind), percent(info.get("utilization")),
                      info.get("resetsAt"))
        windows = [one] if one else []
    if not windows:
        return {"unknown": "Claude Code's last run named no limit"}
    return {"read_at": read_at, "source": FROM_RUNS, "plan": None, "windows": windows,
            "credits": None}


def of_session(told: object, read_at: datetime) -> dict:
    """The `rate_limits` of Claude Code's status line input, as `of_claude` shows its own
    word: {"five_hour" | "seven_day": {"used_percentage": 0-100, "resets_at": epoch
    seconds}}, one window or both. ValueError for anything else: it came from outside."""
    if not isinstance(told, dict) or not told or set(told) - set(CLAUDE_MINUTES):
        raise ValueError("not the status line's rate_limits")
    named = {}
    for name, part in told.items():
        if not isinstance(part, dict) or set(part) != {"used_percentage", "resets_at"}:
            raise ValueError("not the status line's rate_limits")
        used, resets = _number(part["used_percentage"]), _number(part["resets_at"])
        if not (used is not None and 0 <= used <= 100 and resets is not None
                and 0 <= resets <= LATEST_RESET):
            raise ValueError("a number of the status line's rate_limits is out of range")
        named[name] = {"utilization": used / 100, "resetsAt": resets}
    return {**of_claude({"unifiedWindows": named}, read_at), "source": FROM_SESSION}


def _as_of(reading: dict, now: datetime) -> dict:
    """A reading as it stands now: a window that has reset since is stale, and what was
    used of it then is not what is used of it now - not shown, never a zero. Nor is a
    limit Codex said was reached still taken for reached once a window has reset."""
    windows = [
        {**w, "stale": True, "used_percent": None}
        if w["resets_at"] is not None and w["resets_at"] <= now else w
        for w in reading.get("windows") or [] if w["name"] not in NOT_THE_PLANS
    ]
    if reading.get("reached") and any(w["stale"] for w in windows):
        reading = {**reading, "reached": False}
    return {**reading, "windows": windows}


# The words KOLONİ's own clients put before what the provider's side said (`_describe`,
# the CLI clients' "reported an error" / "exited with code"): only what comes straight
# after them is the provider's own line. Anything further in can be a model's words.
_LEAD = re.compile(
    r"model server returned (?P<status>\d{3})\b:? ?"
    r"|[\w .-]+? reported an error: "
    r"|[\w .-]+? exited with code -?\d+: "
)
# ("exceeded your current quota": OpenAI's documented wording, not measured here.)
_CREDITS = re.compile(r"(?:your )?credit balance is too low|you exceeded your current quota")
# (Codex's and Claude Code's own wording of a limit: not measured here.)
# (Qoder's "You've reached your credit usage limit": seen in a live run, 25 Oct, B-88.)
_LIMIT = re.compile(
    r"you(?:'ve|’ve| have) (?:hit|reached) your (?:[\w-]+ ){0,2}limit"
    r"|(?:[\w-]+ )?limit reached|(?:rate|usage) limit"
)
# Not signed in, or a key refused: a model server's 401, or a CLI's own words.
# shortcut: the CLIs' words are not measured here (Claude Code's "Invalid API key · Please run
# /login" is as it is commonly reported); add each one's as it is seen.
_SIGNED_OUT = re.compile(
    r"invalid api key|not (?:logged|signed) in|please (?:run /?login|log ?in|sign in)"
    r"|authentication (?:failed|required)"
)
# A plan key's quota used up (`model_client.USED_UP`).
# shortcut: `_describe` keeps only `error.message` where there is one, so its code beside
# other words is not seen; keep the code too if Alibaba's measured 429 words differ.
_USED_UP = USED_UP
_CRASHED = re.compile(
    r"[\w .-]+? (?:exited with code -?\d|ended without finishing|ended, exit code not known)")
_EMPTY = re.compile(r"[\w .-]+? ended without an answer")


def classify(exc: ModelUnavailable) -> tuple[str, datetime | None]:
    """Why a model's step or a CLI's run failed, from what the provider's side said: its
    own event where there was one (`exc.failure`), else the status a model server
    answered with, else the words its own error line begins with. Words further in -
    a model's, a refusal's - make nothing of it. Not sure: `other`."""
    if exc.failure:
        return exc.failure
    said = str(exc).lower()
    lead = _LEAD.match(said)
    own = said[lead.end():] if lead else ""
    # Before the limit: an API out of credit can answer 429 too.
    if _CREDITS.match(own):
        return "credits_exhausted", None
    if (lead and lead["status"] == "429") or _LIMIT.match(own):
        return "rate_limited", None
    if (lead and lead["status"] == "401") or _SIGNED_OUT.match(own):
        return "signed_out", None
    if _CRASHED.match(said):
        return "cli_crashed", None
    if _EMPTY.fullmatch(said):
        return "empty_output", None
    return "other", None


# G3.1: a limit of a day or longer is not waited for. Its words, where no reading says its
# length: as the providers' documents and live runs word them, not measured here.
# (Not a bare "usage limit": Codex says it of its 5-hour window too.)
_LONG = re.compile(r"\b(?:daily|weekly|monthly)\b|credit (?:usage )?limit|quota")
LONG_MINUTES = 1440


def window(failure: str | None, error: str | None, resets: datetime | None, reading: dict
           ) -> str | None:
    """Which window a provider's failure is in (G3.1), never kept: "sign_in" for one not
    signed in; out of credits "long"; for a limit "long" (a day or more) or "short" - by its
    reset, a day or more away; by the provider's last reading (`Limits.last`), a window that
    resets when the failure does or is full; else by the provider's own words (`classify`'s).
    None: another failure, or not known."""
    if failure == "signed_out":
        return "sign_in"
    if failure == "credits_exhausted":
        return "long"
    if failure != "rate_limited":
        return None
    if resets is not None and resets.tzinfo is None:
        resets = resets.replace(tzinfo=UTC)  # (as the database gives it back: UTC)
    if resets and resets - datetime.now(UTC) >= timedelta(minutes=LONG_MINUTES):
        return "long"
    lengths = [w["minutes"] for w in reading.get("windows") or [] if w["minutes"] and (
        (w["used_percent"] or 0) >= 100 or resets and w["resets_at"]
        and abs((w["resets_at"] - resets).total_seconds()) < SAME_WINDOW)]
    if lengths:
        return "long" if max(lengths) >= LONG_MINUTES else "short"
    said = (error or "").lower()
    lead = _LEAD.match(said)
    own = said[lead.end():] if lead else ""
    if _USED_UP.search(said) or _LONG.search(own):
        return "long"
    return "short" if (lead and lead["status"] == "429") or _LIMIT.match(own) else None


def at_limit(reading: dict) -> bool:
    """Whether a reading (`Limits.last`) has its limit reached now, as far as anyone knows."""
    return bool(reading.get("reached")) or any(
        (w["used_percent"] or 0) >= 100 for w in reading.get("windows") or [])


def _loaded(row: LimitReading | None) -> dict:
    """A reading as the database keeps it, its times read back; {} for none."""
    return {} if row is None else {**row.reading, "read_at": row.read_at, "windows": [
        {**w, "resets_at": w["resets_at"] and datetime.fromisoformat(w["resets_at"]),
         **({"read_at": datetime.fromisoformat(w["read_at"])} if w.get("read_at") else {})}
        for w in row.reading["windows"]
    ]}


# The words of a window's length in "Claude Code's weekly plan 84% used".
PLAN_WORDS = {10080: "weekly", 300: "5-hour"}


def plan_used(session: Session, provider: Provider) -> str | None:
    """Where a subscription's picks go a tier lower (81c): what its narrowest window - the one
    with the least left - says, at or past the provider's `step_down_at`, as "Claude Code's
    weekly plan 84% used"; None below it, with none set, or with nothing known now. Read from
    the database, where every reading is kept (`Limits._keep`), as it stands now."""
    if provider.step_down_at is None:
        return None
    now = datetime.now(UTC)
    reading = _as_of(_loaded(session.get(LimitReading, json.dumps(account(provider)))), now)
    read_at = reading.get("read_at")
    if read_at is not None and read_at.tzinfo is None:
        read_at = read_at.replace(tzinfo=UTC)  # (as the database gives it back: UTC)
    known = [
        w for w in reading.get("windows") or [] if w["used_percent"] is not None
        # Only the whole account's: a model's own week (Claude Code's `seven_day_opus`, ...)
        # holds back that model, not every pick on the plan. Copilot's premium requests are
        # the whole account's too (B-314: its step-down share was never reached).
        and (w["name"] is None or w["name"] in CLAUDE_MINUTES or w["name"] == PREMIUM)
        # One read longer ago than the window lasts (a day where that is not known) says
        # nothing of now, reset time or none: a step down does not go on for ever on it.
        and read_at is not None and now - read_at < timedelta(minutes=w["minutes"] or 1440)
    ]
    if not known:
        return None
    narrowest = max(known, key=lambda w: w["used_percent"])
    if narrowest["used_percent"] < provider.step_down_at:
        return None
    words = PLAN_WORDS.get(narrowest["minutes"])
    plan = f"{provider.name}'s {words} plan" if words else f"{provider.name}'s plan"
    return f"{plan} {narrowest['used_percent']:g}% used"


def cli_home(runtime_root: Path, provider: Provider) -> Path | None:
    """K-claude-hesap: the sign-in folder of a Claude Code or Codex provider signed in for
    KOLONİ alone (its `sign_in` setting): under the runtime, kept across restarts, never in a
    project. None: it uses the user's own (~/.claude, ~/.codex).
    shortcut: measured (3 Nov 2026) only that `claude auth status` goes by the folder; that a
    login made with it lands there on Windows (not in a store both share) and that Codex's does
    in its CODEX_HOME is not - check both at the user's first login."""
    if provider.kind not in SIGN_IN_KINDS or provider.base_url or (
            provider.options or {}).get("sign_in") != "koloni" or not PROVIDER_ID.fullmatch(
            provider.id or ""):
        return None
    return runtime_root / CLI_HOMES / provider.id


def account(provider: Provider) -> tuple:
    """Whose plan a provider's is. Two providers of one CLI started by the same command
    are signed in to one account: what one says of its plan is the other's too, and
    neither has room when the other is at its limit. Anything else is its own - a CLI on a
    model server of the user's too: its room is not the plan's (K-cli-llama) - and one with
    a sign-in folder of its own (`cli_home`)."""
    if not provider.kind.endswith("_cli") or _on_server(provider) or (
            provider.options or {}).get("sign_in") == "koloni":
        return (provider.id,)
    # shortcut: the command is compared as it is written (none given is not "claude"
    # spelled out, nor its full path); resolve it first if such doubles are seen in use.
    # shortcut: Copilot signs in by each provider's own token or the user's gh login, so two
    # Copilots of two GitHub accounts share one reading here; key them apart (never by the
    # token) if seen.
    return provider.kind, provider.executable or None


# The failures that are an account's plan or credit used up (`classify`).
ACCOUNT_LIMITS = frozenset({"rate_limited", "credits_exhausted"})


def another_account(failed: Provider, other: Provider, failure: str | None) -> bool:
    """K-claude-hesap: whether `other` is never turned to for `failed`'s failure - another
    account of the same CLI (two Claude Code providers, each signed in its own folder) when
    the failure is its plan's limit: work is not moved from one account of a vendor to the
    next to get past a limit (the user's rule, 3 Nov 2026; the vendors' terms). Another kind,
    or the user's own model server, is fine."""
    return (failure in ACCOUNT_LIMITS and other.kind == failed.kind
            and other.kind.endswith("_cli") and not _on_server(other))


def _on_server(provider: Provider) -> bool:
    """A CLI on a model server of the user's own (Copilot; Claude Code and Codex, K-cli-llama):
    it is on no plan."""
    return provider.kind.endswith("_cli") and bool(provider.base_url)


class Limits:
    """What each account last said of its plan (`account`). A reading is kept in memory
    and in the database (`LimitReading`) with when it was read: after a restart the last
    one is shown, as of then, until it is read again ("Read now"), Claude Code runs again
    or the user's own Claude Code session says it. Why a reading failed is kept in memory
    only; an account never read says why it is not known. Without a `session_factory` (a
    test's): in memory only. `homes`: where agy is given its homes (`agy_quota`);
    `runtime_root`: where the providers' own sign-in folders are (`cli_home`)."""

    def __init__(
        self, session_factory: Callable[[], Session] | None = None, homes: Path | None = None,
        runtime_root: Path | None = None,
    ) -> None:
        self._factory = session_factory
        self._homes = homes
        self._root = runtime_root or Path(tempfile.gettempdir())
        self._kept: dict[tuple, dict] = {}  # account -> its last reading, or its unknown
        self._reading: dict[tuple, asyncio.Future] = {}  # account -> its CLI being asked now
        self._tried: dict[tuple, float] = {}  # account -> when it was last asked (monotonic)
        # A session's post is taken in a worker thread, a run's on the event loop: one at a
        # time, or one would write over a window the other took.
        self._taking = threading.Lock()

    def _known(self, of: tuple) -> dict:
        """An account's last reading, or its unknown; {} for none. What is not in memory
        is looked for in the database once, and what was found - or that nothing was - is
        kept in memory."""
        if of not in self._kept and self._factory is not None:
            with self._factory() as session:
                loaded = _loaded(session.get(LimitReading, json.dumps(of)))
            # (Read in a worker thread: a reading kept meanwhile by a run is fresher.)
            self._kept.setdefault(of, loaded)
        return self._kept.get(of, {})

    def _keep(self, of: tuple, reading: dict) -> None:
        self._kept[of] = reading
        # Only a reading as it was read: an unknown, or one with a failure beside it, is not.
        if self._factory is None or "read_at" not in reading or "failed" in reading:
            return
        shown = {k: v for k, v in reading.items() if k != "read_at"}
        try:
            with self._factory() as session:
                session.merge(LimitReading(
                    account=json.dumps(of), read_at=reading["read_at"],
                    reading=json.loads(json.dumps(shown, default=datetime.isoformat))))
                session.commit()
        except SQLAlchemyError as exc:
            # In memory it is kept all the same: only a restart forgets it.
            log.warning("the last limits reading of a %s could not be saved: %s",
                        of[0], type(exc).__name__)

    def _take(self, of: tuple, told: dict) -> None:
        """What Claude Code said of its windows - in a run here, a short run to read it or
        the user's own session - taken into the account's last reading window by window: the
        newest word on a window wins, less used too (Anthropic reset a week's use early on
        23 Oct 2026 and kept its reset time: 93% became 5%), a later window always, an
        earlier one never. The reading's time and source are those of what was taken; where
        nothing changed, nothing is written - but for a short run to read it.
        shortcut: a session idle since its last answer may say that answer's use again and
        take a higher one back for a while; tell its refreshes apart if that is seen."""
        with self._taking:
            self._take_now(of, told)

    def _take_now(self, of: tuple, told: dict) -> None:
        kept = self._known(of)
        if "read_at" not in kept:
            self._keep(of, told)
            return
        if "unknown" in told:
            return  # what names no limit does not unsay the last
        windows = {w["name"]: w for w in kept["windows"]}
        taken, said = False, set()
        for window in told["windows"]:
            was = windows.get(window["name"])
            if was is not None and was["resets_at"] and window["resets_at"]:
                apart = (window["resets_at"] - was["resets_at"]).total_seconds()
                if apart <= -SAME_WINDOW:
                    continue  # an earlier window: over
                said.add(window["name"])
                used, had = window["used_percent"], was["used_percent"]
                if abs(apart) < SAME_WINDOW and (used is None or used == had):
                    continue  # the same window, nothing new said of it
            said.add(window["name"])
            windows[window["name"]] = window
            taken = True
        # The user's Read now is read now, though it says nothing new (B-74: the card kept
        # "read 6 min ago, in its last run here" after it). A window it did not name keeps
        # when it was read (its own `read_at`): it is not read now.
        if taken or told.get("source") == SHORT_RUN:
            self._keep(of, {**{k: v for k, v in kept.items() if k != "failed"},
                            "read_at": told["read_at"], "source": told["source"],
                            "windows": [
                                {k: v for k, v in w.items() if k != "read_at"}
                                if name in said else {**w, "read_at": w.get("read_at")
                                                      or kept["read_at"]}
                                for name, w in windows.items()]})
        elif "failed" in kept:
            # Read afresh after all: the failure beside it is over (what is saved is as it was).
            self._kept[of] = {k: v for k, v in kept.items() if k != "failed"}

    def said(self, of: tuple, info: dict) -> None:
        """Claude Code named its limits in a run (`CliStepClient.on_limits`)."""
        self._take(of, of_claude(info, datetime.now(UTC)))

    def codex_said(self, of: tuple, told: dict) -> None:
        """Codex said its limits in a native run (`account/rateLimits/updated`, which holds
        what `app_server` reads): kept as a reading of it is. Only its plan's own limit."""
        # shortcut: a limit of another id (one model's, say) is passed over, not shown;
        # show it beside the plan's once such a notification is seen.
        limits = told.get("rateLimits")
        if isinstance(limits, dict) and limits.get("limitId") not in (None, "codex"):
            return
        reading = of_codex(told, datetime.now(UTC))
        if "unknown" not in reading:
            with self._taking:
                self._keep(of, reading)

    def copilot_said(self, of: tuple, told: dict) -> None:
        """Copilot said what is left of its plan in a native run (`account.getQuota` asked of
        its own headless client, 89l): kept as `copilot_quota`'s reading is, and its
        background read (`refresh`) is not due again until AUTO_EVERY from now."""
        reading = of_copilot(told, datetime.now(UTC))
        if "unknown" not in reading:
            with self._taking:
                self._keep(of, reading)
            self._tried[of] = time.monotonic()

    def api_said(self, of: tuple, headers) -> None:
        """An API's answer began, its headers saying its rate limits (`of_headers`): they are
        its account's last windows, beside what else is known of it (DeepSeek's balance).
        shortcut: in memory only - a minute's window says nothing after a restart, and a write
        at every step is not worth it; keep them if a longer window is seen here."""
        now = datetime.now(UTC)
        windows = of_headers(headers, now)
        if not windows:
            return
        with self._taking:
            kept = {k: v for k, v in self._known(of).items() if k not in ("unknown", "failed")}
            self._kept[of] = {"plan": None, "credits": None, **kept, "read_at": now,
                              "source": FROM_ANSWER, "windows": windows}

    def from_session(self, reading: dict) -> None:
        """What the status line of the user's own Claude Code session said (`of_session`):
        that session is the default command's, signed in as the user is there - not a
        provider with a sign-in folder of its own (`account`)."""
        self._take(("claude_cli", None), reading)

    def forget(self, session: Session, of: tuple) -> None:
        """An account no provider is on any more: what was read of it goes, in `session`."""
        with self._taking:
            self._kept.pop(of, None)
            row = session.get(LimitReading, json.dumps(of))
            if row is not None:
                session.delete(row)

    def last(self, provider: Provider) -> dict:
        """What is known of a provider's plan without asking anyone, as it stands now."""
        if _on_server(provider):
            # (Before what is kept: a Copilot on GitHub's plan can share its account.)
            return {"unknown": NO_PLAN}
        kept = self._known(account(provider))
        if kept:
            return _as_of(kept, datetime.now(UTC))
        if provider.kind == "claude_cli":
            return {"unknown": NOT_RUN}
        if provider.kind in ("codex_cli", *QUIET) or is_deepseek(provider):
            return {"unknown": NOT_READ}
        if provider.kind == "anthropic":
            return {"unknown": NOT_ANSWERED}
        return {"unknown": DOES_NOT_SAY if provider.kind.endswith("_cli") else NO_PLAN}

    async def read(self, provider: Provider) -> dict:
        """The same, read afresh: where the user asks ("Read now") - Codex over its
        app-server, Claude Code in one short turn (`claude_turn`), agy and Copilot with no
        turn (`agy_quota`, `copilot_quota`); DeepSeek's balance (`deepseek_balance`). One at a
        time for an account: whoever asks meanwhile waits for that one."""
        if (provider.kind not in NAMES or _on_server(provider)) and not is_deepseek(provider):
            return self.last(provider)
        # (Shielded: one asker going away does not take the reading from the others.)
        await asyncio.shield(self._asking(provider))
        return self.last(provider)

    def refresh(self, provider: Provider) -> None:
        """agy's or Copilot's plan read in the background as it is looked at (the plan meter,
        every few seconds): when it was last asked - read well or not, or else last read
        before a restart - more than AUTO_EVERY ago. Never waited for: what was read
        before is shown meanwhile. Not one switched off: nobody uses it."""
        if provider.kind not in QUIET or _on_server(provider) or provider.enabled is False:
            return
        of = account(provider)
        tried = self._tried.get(of)
        if tried is not None:
            ago = time.monotonic() - tried
        else:
            read_at = self._known(of).get("read_at")
            if read_at is not None and read_at.tzinfo is None:
                read_at = read_at.replace(tzinfo=UTC)  # (as the database gives it back: UTC)
            ago = (datetime.now(UTC) - read_at).total_seconds() if read_at else math.inf
        if ago >= AUTO_EVERY:
            self._asking(provider)

    def _asking(self, provider: Provider) -> asyncio.Future:
        """The account's CLI being asked: the one asked already, or one asked now."""
        of = account(provider)
        reading = self._reading.get(of)
        if reading is None:
            # Plain values: the provider's row is its request's, which ends before this does.
            reading = self._reading[of] = asyncio.ensure_future(self._ask(
                of, provider.kind, provider.executable, provider.api_key,
                cli_home(self._root, provider)))
        return reading

    async def _ask(
        self, of: tuple, kind: str, executable: str | None, token: str | None = None,
        home: Path | None = None,
    ) -> None:
        self._tried[of] = time.monotonic()
        had = self._known(of).get("read_at")  # (what was read before it is asked)
        claude = kind == "claude_cli"
        try:
            try:
                if kind == "codex_cli":
                    told = of_codex(await app_server(executable, SECONDS, home=home),
                                    datetime.now(UTC))
                elif kind == "agy_cli":
                    told = of_agy(await agy_quota(executable, self._homes, SECONDS),
                                  datetime.now(UTC))
                elif kind == "copilot_cli":
                    told = of_copilot(await copilot_quota(executable, token, SECONDS),
                                      datetime.now(UTC))
                elif kind == "openai_compat":  # (DeepSeek's only: `read`)
                    told = of_deepseek(await deepseek_balance(token, SECONDS), datetime.now(UTC))
                else:
                    told = of_claude(await claude_turn(executable, CLAUDE_SECONDS, home=home),
                                     datetime.now(UTC))
                    if "unknown" not in told:
                        told["source"] = SHORT_RUN
            except TimeoutError:
                seconds = CLAUDE_SECONDS if claude else SECONDS
                told = {"unknown": f"{NAMES.get(kind, 'DeepSeek')} did not answer within "
                                   f"{seconds:g} seconds"}
            except ModelUnavailable as exc:
                told = {"unknown": str(exc)}
            with self._taking:
                kept = self._known(of)
                if "unknown" in told and "read_at" in kept:
                    # The last good reading stays, with its time; why this one failed is
                    # said beside it - unless it was kept after this one was asked (a
                    # native run's): that one is fresher than the failure.
                    if kept["read_at"] == had:
                        self._keep(of, {**kept, "failed": told["unknown"]})
                elif kind == "openai_compat" and "unknown" not in told:
                    # The balance, read now and kept as such: the windows its last answer said
                    # (`api_said`) were not read now, and are not kept with it.
                    self._keep(of, {"plan": None, **{
                        k: v for k, v in kept.items() if k not in ("unknown", "failed")},
                        **told, "windows": []})
                elif not claude:
                    self._keep(of, told)
                else:
                    self._take_now(of, told)
        finally:
            del self._reading[of]

    def why(
        self, provider: Provider | None, exc: ModelUnavailable
    ) -> tuple[str, datetime | None]:
        """`classify`, and for a limit whose reset the failure did not name: that of a
        window the provider's last reading has as full. A plan key's quota used up is kept
        as its reading, with when it was seen: no API says what is left of such a plan."""
        failure, resets = classify(exc)
        if failure == "rate_limited" and resets is None and provider is not None:
            full = [w["resets_at"] for w in self.last(provider).get("windows") or []
                    if (w["used_percent"] or 0) >= 100 and w["resets_at"]]
            resets = max(full) if full else None
            # shortcut: kept until the next one is seen, a turn that runs again does not
            # unsay it; clear it on a turn that ends well if a stale "used up" misleads.
            if provider.plan and _USED_UP.search(str(exc).lower()):
                with self._taking:
                    self._keep(account(provider), {"read_at": datetime.now(UTC),
                                                   "windows": [], "used_up": True})
        return failure, resets

    def room(self, session: Session, providers: list[Provider], failed: str | None,
             failure: str | None = None) -> str:
        """Advice for whoever opened an agent that failed: which other providers of the
        team guide have room now, each with why. Nothing is asked for it - what was last
        read is used, with when - and nothing is switched."""
        found = [f"{json.dumps(entry.name, ensure_ascii=False)} ({why})"
                 for entry, why in self.with_room(session, providers, failed, failure)]
        if not found:
            return "No other provider is known to have room now."
        return (
            f"These providers have room now: {'; '.join(found)}. This is advice only: "
            "nothing was switched. To go on with one of them, open a new agent on it."
        )

    def with_room(self, session: Session, providers: list[Provider], failed: str | None,
                  failure: str | None = None) -> list[tuple["Entry", str]]:
        """The team guide's entries (`app.team.Entry`) that have room now, in its order,
        each with why: not the provider that failed nor another on its account - nor, where
        it failed at its limit (`failure`), another account of its CLI (`another_account`)."""
        from app.team import guide  # here: app.team needs app.providers, which needs this

        by_id = {provider.id: provider for provider in providers}
        same = account(by_id[failed]) if failed in by_id else None
        found = []
        for entry in guide(providers):
            provider = by_id[entry.provider_id]
            # Not the one that failed, nor another on its account (its limit is that
            # one's too), nor one an agent could name no model for.
            if account(provider) == same or (entry.must_name and not entry.selectable()) or (
                    failed in by_id and another_account(by_id[failed], provider, failure)):
                continue
            why = has_room(session, provider, self.last(provider))
            if why is not None:
                found.append((entry, why))
        return found


def has_room(session: Session, provider: Provider, reading: dict,
             never_ran_is_room: bool = False) -> str | None:
    """Why a provider has room now, from its last reading (`Limits.last`): what of its plan is
    used; or, where nothing of it is known (most API keys: their credit is not read), that its
    last run ended well. None where it is known to have none - its plan at its limit or used
    up, its credits out - or nothing is known and its last run did not end well (a credit or
    rate-limit failure among others), or it has not run - unless `never_ran_is_room` (B-166,
    the Lead's yes to a sub-agent: what has neither run out nor gone over a limit may be used;
    `Limits.with_room`'s advice names only one known to have room)."""
    if at_limit(reading) or reading.get("used_up") or (
            reading.get("credits") or {}).get("has_credits") is False:
        return None
    known = [w for w in reading.get("windows") or [] if w["used_percent"] is not None]
    if known:
        used = ", ".join(
            f"{w['used_percent']:g}% of its "
            + (f"{w['minutes']}-minute" if w["minutes"] else w["name"] or "one")
            + " window used" for w in known
        )
        return f"{used}; read {reading['read_at']:%Y-%m-%d %H:%M} UTC"
    # (Of the runs that ended by themselves: the user's Stop, or a restart, says nothing of it.)
    last = session.scalars(
        select(Agent.status)
        .where(Agent.provider_name == provider.name, Agent.ended_at.is_not(None),
               Agent.status.in_(("completed", "failed")))
        .order_by(Agent.ended_at.desc()).limit(1)
    ).first()
    if last is None and never_ran_is_room:
        return "its limit is not known; it has not run yet"
    return "its limit is not known; its last run ended well" if last == "completed" else None
