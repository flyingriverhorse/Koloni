import hashlib
import os
import time
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app import copies, web
from app.api.deps import get_session
from app.config import REPO_ROOT
from app.executors.docker import docker_status
from app.executors.host import shell_name, store_pwsh_note
from app.model_client import ModelUnavailable, safe_url
from app.providers import NotListed, allowed, list_providers
from app.schemas import HealthOut, StorageOut

router = APIRouter(prefix="/api", tags=["health"])
# How long one folder is counted before it is said as unknown: copies can be large.
COUNT_SECONDS = 5.0


def api_hash() -> str | None:
    """The API the page is typed against (`generated.ts`, which `check:api` keeps equal
    to this code's): a page built from another hashes it otherwise. None without it."""
    try:
        text = (REPO_ROOT / "frontend" / "src" / "api" / "generated.ts").read_bytes()
    except OSError:
        return None
    # (Line ends as git may write them on Windows: the same API either way.)
    return hashlib.sha256(text.replace(b"\r\n", b"\n")).hexdigest()[:12]


# Read once, as this server starts: code pulled since is not what it runs.
API_HASH = api_hash()


@router.get("/health", response_model=HealthOut)
async def health(
    request: Request, provider_id: str | None = None, session: Session = Depends(get_session)
):
    """Whether a provider can be reached - the one given (the open conversation's), else
    the default - and whether Docker can."""
    docker = await docker_status()
    providers = list_providers(session)
    provider = next(
        (p for p in providers if p.id == provider_id), providers[0] if providers else None)
    report = {
        # (shown on the page: no password or key that the address may carry)
        "model_base_url": safe_url((provider.base_url if provider else None) or ""),
        "provider_id": provider.id if provider else None,
        "provider_name": provider.name if provider else None,
        "docker_available": docker.available,
        "docker_error": docker.error,
        "desktop_available": web.has_desktop(),
        "api_hash": API_HASH,
        "shell": shell_name(),
        "shell_note": store_pwsh_note(),
    }
    try:
        if provider is None:
            raise ModelUnavailable("no model provider is set up")
        allowed(provider, provider.default_model)
        client = request.app.state.providers.client(provider, provider.default_model)
        info = await client.info()
    except NotListed as exc:
        # Nothing was asked of it: it is not known to be out of reach.
        return HealthOut(
            model_reachable=False, model_id=None, tools_supported=None, error=str(exc),
            not_listed=True, **report,
        )
    except ModelUnavailable as exc:
        return HealthOut(
            model_reachable=False, model_id=None, tools_supported=None, error=str(exc),
            not_listed=False, **report,
        )
    return HealthOut(
        model_reachable=True,
        model_id=info.model_id,
        tools_supported=info.tools_supported,
        error=None,
        not_listed=False,
        **report,
    )


def _megabytes(paths: list[Path]) -> float | None:
    """The MB of these files and folders, following no link (a copy's .venv is a junction to
    the project's); None when the count takes over COUNT_SECONDS."""
    until, total = time.monotonic() + COUNT_SECONDS, 0
    todo = [path for path in paths if not copies._is_link(path)]
    while todo:
        if time.monotonic() > until:
            return None
        path = todo.pop()
        try:
            if path.is_file():
                total += path.stat().st_size
                continue
            with os.scandir(path) as found:
                for entry in found:
                    if entry.is_dir(follow_symlinks=False) and not entry.is_junction():
                        todo.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
        except OSError:
            continue  # not there, or gone while counted
    return round(total / 2**20, 1)


@router.get("/storage", response_model=StorageOut)
def storage(request: Request):
    """What KOLONİ's data takes, counted when asked (0.1.0-hijyen)."""
    settings = request.app.state.settings
    db = settings.db_path
    return StorageOut(
        db_mb=_megabytes([db, db.with_name(db.name + "-wal")]),
        backups_mb=_megabytes([db.parent / "backups"]),
        copies_mb=_megabytes(copies.folders(settings.runtime_root)),
        logs_mb=_megabytes([settings.runtime_root / "logs"]),
    )
