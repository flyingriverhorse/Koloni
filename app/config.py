import hashlib
import os
import shutil
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent
# llama.cpp's llama-server: the one on PATH, else only its name - the Models page asks for
# its full path - until another is set there (or by KOLONI_LOCAL_SERVER).
LOCAL_SERVER = Path(shutil.which("llama-server") or "llama-server")


@dataclass(frozen=True)
class Settings:
    port: int
    runtime_root: Path
    # Where the MCP servers this KOLONİ starts stand (97): `mcp_base`'s folder for its
    # runtime; tests give one of their own (KOLONI_MCP_HOME). No default: never ".".
    mcp_home: Path
    db_path: Path
    model_base_url: str
    model_id: str | None
    model_api_key: str | None
    allowed_origins: tuple[str, ...]
    context_char_budget: int
    max_steps: int
    model_stall_seconds: float
    model_first_token_seconds: float
    frontend_dist: Path
    # The address it listens on: this machine only. The Docker image alone says 0.0.0.0
    # (KOLONI_HOST), its port published as 127.0.0.1:N:N - the container's own address.
    host: str = "127.0.0.1"
    # Offer the CLIs found on PATH (all but Copilot) as providers on the first start.
    detect_cli: bool = True
    # Look at the clock by itself, every few seconds, and start the triggers that are
    # due. Off in tests, which hand the scheduler the time themselves.
    trigger_clock: bool = True
    # At the start, download the catalogue again where it is older than a week, unless the
    # user turned that off (`models_dev.refresh`). Off in tests: they reach no network.
    catalogue_refresh: bool = True
    # How long a search pattern may run before it is given up (app.workspace).
    search_seconds: float = 20.0
    # The page's key for this start (slice 94), given only by tests; None makes a new one.
    page_key: str | None = field(default=None, repr=False)
    # The model server the Models page starts, and what reads the graphics card (slice 64);
    # tests give stand-ins.
    local_server: Path = LOCAL_SERVER
    nvidia_smi: str = "nvidia-smi"
    # The built user guide, served at /guide/: where zensical.toml's site_dir puts it, in the
    # checkout - not under KOLONI_RUNTIME_ROOT, which `zensical build` does not read.
    guide_site: Path = REPO_ROOT / "runtime" / "site"


THIS_MACHINE = ("localhost", "127.0.0.1", "::1")


def is_local(base_url: str | None) -> bool:
    """Whether an address names this machine: a model server here costs nothing to use."""
    try:
        return urlsplit(base_url or "").hostname in THIS_MACHINE
    except ValueError:
        return False


def mcp_base() -> Path:
    """KOLONİ's folder for the MCP servers it starts (97), in the user's own cache: no
    folder above it can be a project - AppData/Local holds the browsers' profiles, so it,
    and the folders above it, are never opened (`workspace._kept_out`) - and it is one
    of KOLONİ's own places itself, which no file tool writes in. npm, npx and uv look for
    their settings and packages in the folders above where they start.
    shortcut: off Windows, ~/.cache or ~/Library/Caches holds no place KOLONİ never opens,
    so it could be listed as a project; make it such a place if KOLONİ is run there."""
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/AppData/Local")
        return Path(local) / "KOLONI" / "mcp"
    if sys.platform == "darwin":
        return Path(os.path.expanduser("~/Library/Caches")) / "KOLONI" / "mcp"
    cache = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return Path(cache) / "KOLONI" / "mcp"


def load_settings(env: Mapping[str, str] | None = None, repo_root: Path | None = None) -> Settings:
    env = os.environ if env is None else env
    root = repo_root or REPO_ROOT
    runtime = Path(env.get("KOLONI_RUNTIME_ROOT") or root / "runtime")
    port = int(env.get("KOLONI_PORT") or 8790)
    page_key = env.get("KOLONI_PAGE_KEY") or None
    if env is os.environ:
        # Read once and taken out: no agent's process inherits it.
        os.environ.pop("KOLONI_PAGE_KEY", None)
    return Settings(
        port=port,
        runtime_root=runtime,
        db_path=runtime / "data" / "koloni.db",
        model_base_url=(env.get("KOLONI_MODEL_BASE_URL") or "http://127.0.0.1:8080/v1").rstrip("/"),
        model_id=env.get("KOLONI_MODEL_ID") or None,
        model_api_key=env.get("KOLONI_MODEL_API_KEY") or None,
        allowed_origins=(
            f"http://127.0.0.1:{port}",
            f"http://localhost:{port}",
            # Vite's dev page (scripts/dev.ps1) only then: an agent's Vite page is on 5173 too.
            *(("http://127.0.0.1:5173", "http://localhost:5173")
              if env.get("KOLONI_DEV") == "1" else ()),
        ),
        context_char_budget=int(env.get("KOLONI_CONTEXT_CHARS") or 240_000),
        max_steps=25,
        model_stall_seconds=float(env.get("KOLONI_MODEL_STALL_SECONDS") or 120),
        model_first_token_seconds=float(env.get("KOLONI_MODEL_FIRST_TOKEN_SECONDS") or 900),
        frontend_dist=root / "frontend" / "dist",
        guide_site=root / "runtime" / "site",
        host=env.get("KOLONI_HOST") or "127.0.0.1",
        detect_cli=(env.get("KOLONI_DETECT_CLI") or "1") != "0",
        trigger_clock=(env.get("KOLONI_TRIGGER_CLOCK") or "1") != "0",
        catalogue_refresh=(env.get("KOLONI_CATALOGUE_REFRESH") or "1") != "0",
        search_seconds=_seconds(env.get("KOLONI_SEARCH_SECONDS"), 20.0),
        page_key=page_key,
        local_server=Path(env.get("KOLONI_LOCAL_SERVER") or LOCAL_SERVER),
        nvidia_smi=env.get("KOLONI_NVIDIA_SMI") or "nvidia-smi",
        # One folder for each runtime: the e2e's KOLONİ never clears the user's servers' folders.
        mcp_home=Path(env.get("KOLONI_MCP_HOME") or mcp_base() / hashlib.sha256(
            str(runtime.resolve()).encode()).hexdigest()[:12]),
    )


def _seconds(value: str | None, default: float) -> float:
    """A number of seconds a setting gives - or `default` where it gives none that is a
    positive, finite number: a wrong value does not keep the app from starting."""
    try:
        number = float(value or "")
    except ValueError:
        return default
    return number if 0 < number < float("inf") else default
