"""models.dev's facts of the services' models (github.com/anomalyco/models.dev, MIT,
"Copyright (c) 2025 models.dev": `models_dev.LICENSE`): the copy the app ships, trimmed to
what KOLONİ reads (`models_dev.json`), or the one the user's "Update catalogue" wrote in the
runtime folder, which is read instead. Same shape as models.dev's `api.json`: service id ->
{"id", "name", "api", "env", "doc", "models": {model id -> {...}}}, with `ABOUT` beside them.
`download` runs on the user's button, and at the app's start for a copy older than a week
while the user keeps it fresh (`refresh`)."""

import asyncio
import json
import logging
import math
import os
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import httpx2

from app.providers import MAX_MODEL_NAME

URL = "https://models.dev/api.json"
SHIPPED = Path(__file__).with_name("models_dev.json")
NAME = "models_dev.json"  # the user's copy, in the runtime folder
# About 6 MB on 21 Oct 2026: room to grow, not to be filled with anything at all.
MAX_BYTES = 32 * 2**20
SECONDS = 60.0
# Where and when a copy was read, beside the services: no service is called that.
ABOUT = "$about"
# The user's "Keep the catalogue fresh" (`Flag`): "0" when turned off; on until then.
FRESH = "catalogue_fresh"
FRESH_FOR = timedelta(days=7)

log = logging.getLogger(__name__)
LICENSE = "MIT, Copyright (c) 2025 models.dev (app/models_dev.LICENSE)"
# KOLONİ's kinds whose models are a models.dev service's; an OpenAI-compatible server's
# is the service at its address (`app.catalog.catalogue_of`).
# shortcut: Copilot's list is every model GitHub offers, not those the user's account has (a
# model it lacks fails the turn, saying so - B-176); mark them once a call that lists the
# account's models (headless, beside `account.getQuota`) is measured live.
SERVICES = {
    "anthropic": "anthropic", "claude_cli": "anthropic", "codex_cli": "openai",
    "copilot_cli": "github-copilot",
}
# What the app ships: the services above and those KOLONİ knew by address before models.dev.
# shortcut: another service at an address of its own is known only after "Update catalogue"
# (which keeps every service with an address); ship more here if users ask for one.
SHIPPED_SERVICES = ("anthropic", "openai", "github-copilot", "deepseek", "alibaba", "alibaba-cn")
MAX_TEXT = 300  # a name, a family, an address: anything longer is not kept
COSTS = ("input", "output", "cache_read", "cache_write")
MODALITIES = ("text", "image", "audio", "video", "pdf")


def _text(value: object, most: int = MAX_TEXT) -> str | None:
    ok = isinstance(value, str) and 0 < len(value) <= most and value.isprintable()
    return value if ok else None


def _https(value: object) -> str | None:
    """An address on the internet; a service at one on this machine or a template is none."""
    url = _text(value)
    try:
        return url if url and urlsplit(url).scheme == "https" and urlsplit(url).hostname else None
    except ValueError:
        return None


def _number(value: object) -> float | int | None:
    ok = isinstance(value, int | float) and not isinstance(value, bool)
    return value if ok and math.isfinite(value) and value >= 0 else None


def _model(told: dict) -> dict:
    """What KOLONİ reads of a model, each field only as models.dev's README gives it."""
    kept: dict = {}
    for field in ("name", "family", "status", "release_date"):
        if _text(told.get(field)):
            kept[field] = told[field]
    for field in ("reasoning", "tool_call", "attachment"):
        if isinstance(told.get(field), bool):
            kept[field] = told[field]
    options = told.get("reasoning_options")
    if isinstance(options, list):
        kept["reasoning_options"] = [
            {"type": "effort", "values": [v for v in one["values"] if _text(v, 20)][:10]}
            if one.get("type") == "effort" and isinstance(one.get("values"), list)
            else {"type": one["type"]}
            for one in options[:10] if isinstance(one, dict) and _text(one.get("type"), 40)
        ]
    for field, parts in (("limit", ("context", "output")), ("cost", COSTS)):
        said = told.get(field)
        if isinstance(said, dict):
            kept[field] = {p: said[p] for p in parts if _number(said.get(p)) is not None}
    # What it reads and writes besides text (slice 85b): only the kinds its README names.
    said = told.get("modalities")
    if isinstance(said, dict):
        kept["modalities"] = {way: [m for m in said[way] if m in MODALITIES]
                              for way in ("input", "output") if isinstance(said.get(way), list)}
    return kept


def clean(told: object, only: tuple[str, ...] | None = None) -> dict:
    """models.dev's list as KOLONİ keeps it: every service KOLONİ names, and every other one
    with an address on the internet (`only`: these services alone); each model with a name
    that could be saved, and only the fields read. Raises ValueError for anything that is
    not models.dev's list."""
    if not isinstance(told, dict):
        raise ValueError("not models.dev's list of services")
    kept: dict = {}
    for service, said in told.items():
        if not (isinstance(said, dict) and isinstance(said.get("models"), dict)
                and _text(service, 100) and service != ABOUT):
            continue
        api = _https(said.get("api"))
        if (service not in only) if only else (service not in SERVICES.values() and not api):
            continue
        env = said.get("env")
        kept[service] = {
            "id": service, "name": _text(said.get("name")) or service, "api": api,
            "env": [e for e in env[:5] if _text(e, 100)] if isinstance(env, list) else [],
            "doc": _https(said.get("doc")),
            "models": {
                name: _model(model) for name, model in said["models"].items()
                if isinstance(model, dict) and name == name.strip() and name.isprintable()
                and 0 < len(name) <= MAX_MODEL_NAME
            },
        }
    if not any(service["models"] for service in kept.values()):
        raise ValueError("models.dev's list has no service with models")
    about = told.get(ABOUT)
    if isinstance(about, dict):
        kept[ABOUT] = {k: about[k] for k in ("url", "read_on", "license") if _text(about.get(k))}
    return kept


def services(copy: dict) -> dict[str, dict]:
    """The services of a copy, without what is said about it."""
    return {name: service for name, service in copy.items() if name != ABOUT}


def read_on(copy: dict) -> str | None:
    return (copy.get(ABOUT) or {}).get("read_on")


# Each copy as read, by when it was last changed - and its size and file: a disk whose clock
# ticks coarsely (Linux) gives a copy written right after another the same time; None: it
# could not be read then.
_read: dict[Path, tuple[tuple[int, int, int], dict | None]] = {}


def load(runtime_root: Path | None) -> dict:
    """The user's copy where "Update catalogue" wrote one, else the shipped one; read again
    only once it changed. A copy that cannot be read is passed over for the shipped one."""
    path = runtime_root / NAME if runtime_root and (runtime_root / NAME).is_file() else SHIPPED
    try:
        status = path.stat()
        stamp = (status.st_mtime_ns, status.st_size, status.st_ino)
    except OSError:  # gone since it was looked for
        if path == SHIPPED:
            raise
        return load(None)
    if _read.get(path, (None,))[0] != stamp:
        try:
            _read[path] = (stamp, clean(json.loads(path.read_bytes())))
        except (OSError, ValueError, RecursionError):
            if path == SHIPPED:
                raise
            _read[path] = (stamp, None)  # not read again until it changes
    told = _read[path][1]
    return told if told is not None else load(None)



_transport: httpx2.AsyncBaseTransport | None = None  # a test's stand-in for models.dev


async def download() -> bytes:
    """models.dev's whole list, as it answers: at most MAX_BYTES, within SECONDS a read."""
    got = bytearray()
    timeout = httpx2.Timeout(SECONDS, connect=10.0)
    async with (
        httpx2.AsyncClient(timeout=timeout, transport=_transport) as http,
        http.stream("GET", URL) as answer,
    ):
        answer.raise_for_status()
        async for chunk in answer.aiter_bytes():
            got += chunk
            if len(got) > MAX_BYTES:
                raise ValueError(f"models.dev sent more than {MAX_BYTES // 2**20} MB")
    return bytes(got)


def update(runtime_root: Path, raw: bytes) -> dict:
    """Keep what models.dev sent as the user's copy, trimmed; what it was, and when. Raises
    ValueError, and writes nothing, for an answer that is not models.dev's list."""
    if len(raw) > MAX_BYTES:
        raise ValueError(f"models.dev sent more than {MAX_BYTES // 2**20} MB")
    try:
        kept = clean(json.loads(raw))
    except RecursionError:
        raise ValueError("not models.dev's list of services") from None
    when = datetime.now(UTC).isoformat(timespec="seconds")
    kept[ABOUT] = {"url": URL, "read_on": when, "license": LICENSE}
    runtime_root.mkdir(parents=True, exist_ok=True)
    # A file of its own for each update: two at once never write into one another's.
    handle, part = tempfile.mkstemp(dir=runtime_root, prefix=NAME, suffix=".part")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(json.dumps(kept, ensure_ascii=False, separators=(",", ":")).encode())
        os.replace(part, runtime_root / NAME)  # whole or not at all
    except BaseException:
        Path(part).unlink(missing_ok=True)
        raise
    return summary(kept)


async def refresh(runtime_root: Path) -> bool:
    """At the app's start, while the user keeps the catalogue fresh (`main`): models.dev's
    list downloaded and kept as `update` keeps it, where the copy read is older than
    FRESH_FOR or says no date. Without the network, or with an answer that is not its list,
    the copy stays as it was and only the log says so. Whether it was updated."""
    copy = await asyncio.to_thread(load, runtime_root)  # (a copy of some MB is read)
    try:
        read = datetime.fromisoformat(read_on(copy) or "")
    except ValueError:
        read = None
    if read and datetime.now(UTC) - (read if read.tzinfo else read.replace(tzinfo=UTC)) < FRESH_FOR:
        return False
    try:
        raw = await asyncio.wait_for(download(), 2 * SECONDS)
        await asyncio.to_thread(update, runtime_root, raw)
    except Exception as exc:
        log.info("the catalogue was not kept fresh: %s", type(exc).__name__)
        return False
    return True


def summary(copy: dict) -> dict:
    """How many services and models a copy holds, and when it was read."""
    found = services(copy).values()
    return {"providers": len(found), "models": sum(len(s["models"]) for s in found),
            "updated_at": read_on(copy)}


if __name__ == "__main__":
    # The shipped copy, from a downloaded api.json: python -m app.models_dev <api.json> <date>
    shipped = clean(json.loads(Path(sys.argv[1]).read_bytes()), SHIPPED_SERVICES)
    shipped = {ABOUT: {"url": URL, "read_on": sys.argv[2], "license": LICENSE}, **shipped}
    SHIPPED.write_bytes((json.dumps(shipped, ensure_ascii=False, indent=0) + "\n").encode())
