import asyncio
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

import app.main
from app.config import Settings, load_settings
from app.db.session import upgrade_db
from app.main import create_app
from app.model_client import ModelUnavailable
from tests.fakes import ScriptedModel
from tests.keyed import TestClient

TERMINAL = {"completed", "failed", "cancelled", "interrupted"}

# How much longer the shared waits below last on a CI runner (GitHub sets CI): a ceiling for
# something that does happen, never what a test asserts. Run 42408875343 on windows-latest took
# 60 s for one fresh migration (2 s here) and its 5 s waits ran out with every sub-agent done;
# a slow Linux runner took 63 s for a 60 s wait. A passing test waits no longer for it.
WAIT_SCALE = (10.0 if sys.platform == "win32" else 4.0) if os.environ.get("CI") else 1.0


def scaled(seconds: float) -> float:
    """A wait of `seconds` here, on this runner: at most 3 minutes unless it was already longer,
    so a real failure still fails as itself, not as a part cancelled at its time limit."""
    return min(seconds * WAIT_SCALE, max(seconds, 180.0))

# Every app a test makes would migrate a new database from nothing (about a second, 57
# migrations); one migrated once per run is copied instead. A database that is already
# there (a test of an older one) is still upgraded for real.
_migrated: list[Path] = []


def _upgrade_or_copy(db_path: Path) -> None:
    if db_path.exists():
        upgrade_db(db_path)
        return
    if not _migrated:
        once = Path(tempfile.mkdtemp(prefix="koloni-migrated-")) / "koloni.db"
        upgrade_db(once)
        _migrated.append(once)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_migrated[0], db_path)


app.main.upgrade_db = _upgrade_or_copy


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def no_name_lookup_for_a_test_server(monkeypatch):
    """A test's own HTTPServer asks DNS for 127.0.0.1's name when it binds (`getfqdn`): on a
    macOS runner some 35 s each. Its name is never used, so it is not asked."""
    monkeypatch.setattr("http.server.socket.getfqdn", lambda name="": name or "localhost")


@pytest.fixture(autouse=True)
def codex_settings_of_the_test(request, tmp_path, monkeypatch):
    """Codex's own settings are read from a folder of the test's, never this machine's -
    and so are the skills in the user's home (`~/.agents/skills`): home is the test's.

    Not in a live test: there the real Codex runs, and it needs its real home (with this
    in place it would not start at all - every live Codex test failed so, 7 Oct 2026)."""
    if request.node.get_closest_marker("live"):
        return
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)  # (Claude Code's home: `own_names`)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))


@pytest.fixture(autouse=True)
def no_secret_variable_of_this_machine(request, monkeypatch):
    """This machine's secret variables (a CLI's own session token, say) are not a test's: a
    command's result names those held back from it (slice 103). A test that needs one sets
    it. Not in a live test: the real CLIs sign in by theirs."""
    from app.commands import held_back

    if request.node.get_closest_marker("live"):
        return
    for name in held_back(os.environ):
        monkeypatch.delenv(name)


@pytest.fixture(autouse=True)
def user_data_of_the_test(tmp_path, monkeypatch):
    """Where working copies go when the runtime root is inside a repository: a folder of
    the test's, never this machine's per-user data folder."""
    from app import copies

    monkeypatch.setattr(copies, "_user_data", lambda: tmp_path / "user-data")


@pytest.fixture(autouse=True)
def no_search_is_waited_for(monkeypatch):
    """A built-in search that was told to wait in one test is not left alone in the next:
    that wait is kept for the whole process (`app.web`)."""
    from app import web

    monkeypatch.setattr(web, "_ddg_waits_until", 0.0)


# Slice 48 has the Lead hand code to sub-agents in a new conversation. In these modules the
# Lead's own writes are incidental to what is tested, and come through helpers that cannot
# take the setting without changing what the tests read: there a new conversation starts
# with it off, as all did before. (No event: it is set as the conversation is made.)
LEAD_WRITES = {
    # through helpers of earlier acceptance sets, which are not edited
    "test_memory_scenarios",  # memory: a fact backed by what the Lead wrote
    "test_places",  # places under a project's limit, through test_board_scenarios' helpers
    "test_outside_folders_fixes",  # writes outside the project
    "test_board_scenarios",  # the board shows who holds which file
    "test_hardening_scenarios",  # a change that waited, applied through a link
    "test_observer_scenarios",  # what the observer counts as a sign
    "test_outside_folders_scenarios",  # tools in a folder of the project's list
    "test_folders_scenarios",  # a write in a folder to read in only, through slice 41's helpers
    "test_max_agents",  # places: a waiting change holds none
    # through test_chat_flow.start, whose one more PATCH would be one more event in replays
    "test_agent_writes",  # the write tools themselves
    "test_review_fixes",  # a write the disk refuses
    "test_views",  # a page written, then shown
    "test_view_scenarios",  # pages an agent writes, listed beside the chat
    "test_agent_tools",  # tool results in the history
    # what every agent is sent, compared with what it was sent before the memory was built
    "test_memory",
    # Codex's own writes as its Lead, from before a Lead that hands code on was refused them
    "test_codex_app_server_scenarios",
    "test_away_scenarios",  # a job's Lead writing in its own copy (slice 106)
    "test_away_rules_scenarios",  # the same, held to what a night allows (slice 106)
}


@pytest.fixture(autouse=True)
def lead_writes_before_slice_48(request):
    if request.module.__name__.rpartition(".")[2] not in LEAD_WRITES:
        yield
        return
    from sqlalchemy import event

    from app.db.models import Conversation, Project

    # (at construction: a column's default is cached in its compiled insert; a chat's is its
    # folder's since tek-ev, a plain chat's its own)
    def off(_target, _args, kwargs):
        kwargs["lead_work"] = "itself"

    for made in (Conversation, Project):
        event.listen(made, "init", off)
    yield
    for made in (Conversation, Project):
        event.remove(made, "init", off)


# The Assistant PO asks the fast tier after a turn that did something, on by default (6 Nov). A
# test marked `no_po` counts the model calls or the clients made for something else, where the
# PO's own request - made where it may be - is one more: there a new project starts with it off.
@pytest.fixture(autouse=True)
def no_po_where_calls_are_counted(request):
    if request.node.get_closest_marker("no_po") is None:
        yield
        return
    from sqlalchemy import event

    from app.db.models import Project

    def off(_target, _args, kwargs):
        kwargs.setdefault("suggest_tasks", False)

    event.listen(Project, "init", off)
    yield
    event.remove(Project, "init", off)


@pytest.fixture(autouse=True)
def no_catalogue_of_the_users(monkeypatch, tmp_path):
    """A catalog.local.json the user keeps in the checkout is not a test's."""
    from app import catalog

    monkeypatch.setattr(catalog, "LOCAL", tmp_path / "no-catalog.local.json")


@pytest.fixture(autouse=True)
def google_is_never_reached(monkeypatch):
    """What `app.speech` asks of Google is answered by a stand-in that takes any key and has
    no sound; a test that needs another answer puts in its own."""
    import httpx2

    from app import speech

    answer = httpx2.MockTransport(lambda request: httpx2.Response(200, json={"models": []}))
    monkeypatch.setattr(speech, "_transport", answer)


@pytest.fixture(autouse=True)
def models_dev_is_never_reached(monkeypatch):
    """A catalogue downloaded in a test - an app started without KOLONI_CATALOGUE_REFRESH=0
    keeps it fresh - is refused here, never fetched; a test that needs an answer puts in its
    own."""
    import httpx2

    from app import models_dev

    def refused(request):
        raise httpx2.ConnectError("a test reached models.dev without standing it in")

    monkeypatch.setattr(models_dev, "_transport", httpx2.MockTransport(refused))


@pytest.fixture(autouse=True)
def registries_and_osv_are_never_reached(monkeypatch):
    """npm, PyPI and osv.dev (slice 92) are refused here, never asked, and osv.dev's answers
    are not kept from one test to the next; a test that needs an answer puts in its own."""
    from app import package_look

    def refused(url, limit, body=None):
        raise AssertionError(f"a test reached {url} without standing it in")

    monkeypatch.setattr(package_look, "fetch", refused)
    monkeypatch.setattr(package_look, "_checked", {})


@pytest.fixture(autouse=True)
def claude_is_never_run_to_read_its_limits(monkeypatch):
    """Read now's short Claude Code turn would start the real claude: a test that wants it
    stands it in. Not a ModelUnavailable, which a Read now would take for a failed reading."""
    import app.limits

    async def refused(executable, timeout, home=None):
        raise AssertionError("a test reached app.limits.claude_turn without standing it in")

    monkeypatch.setattr(app.limits, "claude_turn", refused)

    # Nor the real agy or Copilot, which a look at their limits reads in the background, nor
    # Copilot asked whether it is signed in (a provider's check): not known, as unstarted.
    async def unread(*args):
        raise ModelUnavailable("a test reached agy's or Copilot's quota without standing it in")

    monkeypatch.setattr(app.limits, "agy_quota", unread)
    monkeypatch.setattr(app.limits, "copilot_quota", unread)
    monkeypatch.setattr(app.limits, "copilot_signed_in", unread)

    # Nor the real qodercli, asked for its models by a provider's model list: only a
    # stand-in started through a launcher is.
    from app.model_session import QoderSessionClient

    listed = QoderSessionClient.models

    async def stood_in(self):
        if not self._launcher and self._which(self._executable or self.command):
            raise ModelUnavailable("a test reached the real qodercli without standing it in")
        return await listed(self)

    monkeypatch.setattr(QoderSessionClient, "models", stood_in)


@pytest.fixture
def settings_env(tmp_path: Path) -> dict[str, str]:
    return {
        "KOLONI_RUNTIME_ROOT": str(tmp_path / "runtime"),
        "KOLONI_MCP_HOME": str(tmp_path / "mcp-home"),  # never the user's own (97)
        "KOLONI_MODEL_BASE_URL": "http://127.0.0.1:9/v1",
        "KOLONI_DETECT_CLI": "0",  # what is installed on this machine is not the test's business
        "KOLONI_TRIGGER_CLOCK": "0",  # a test hands the scheduler its time: tick(now)
        "KOLONI_CATALOGUE_REFRESH": "0",  # no download at the start
        # Never this machine's llama-server or graphics card (slice 64): a test gives its own.
        "KOLONI_LOCAL_SERVER": str(tmp_path / "no-llama-server.exe"),
        "KOLONI_NVIDIA_SMI": str(tmp_path / "no-nvidia-smi"),
    }


@pytest.fixture
def settings(settings_env) -> Settings:
    return load_settings(settings_env)


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "hello.py").write_bytes(b"print('hi')\n")
    return root


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app, base_url="http://127.0.0.1:8790") as c:
        yield c


@pytest.fixture
def make_client(settings_env):
    """Build an app around a ScriptedModel; returns (client, model)."""
    opened: list[TestClient] = []

    def make(steps, tools_supported: bool = True, executor=None):
        model = ScriptedModel(steps, tools_supported=tools_supported)
        app = create_app(
            load_settings(settings_env),
            model=model,
            executors=executor.factory if executor else None,
        )
        client = TestClient(app, base_url="http://127.0.0.1:8790")
        client.__enter__()
        opened.append(client)
        return client, model

    yield make
    for client in opened:
        client.__exit__(None, None, None)


@pytest.fixture
def wait_run():
    # A ceiling, not a pace: it waits for a state, so 20 s costs time only to a test already
    # failing - and a CLI started as a process of its own (1-2 s alone) went past 5 s under load.
    def wait(client, conversation_id: str, run_id: str, timeout: float = 20.0) -> dict:
        timeout = scaled(timeout)
        deadline = time.monotonic() + timeout
        while True:
            snap = client.get(f"/api/conversations/{conversation_id}").json()
            run = next(r for r in snap["runs"] if r["id"] == run_id)
            if run["status"] in TERMINAL:
                return snap
            if time.monotonic() > deadline:
                raise AssertionError(f"run still {run['status']} after {timeout}s")
            time.sleep(0.02)

    return wait


class Gate:
    """Holds a scripted model step open until the test releases it."""

    def __init__(self):
        self._released = threading.Event()
        self._partial_seen = threading.Event()

    def step(self, result, partial: str | None = None):
        async def held(on_delta):
            if partial is not None:
                await on_delta(partial)
            self._partial_seen.set()
            while not self._released.is_set():
                await asyncio.sleep(0.01)
            await on_delta(result.content)  # a real client only returns text it streamed
            return result

        return held

    def wait_partial(self) -> None:
        assert self._partial_seen.wait(scaled(5)), "the model step never started"

    def release(self) -> None:
        self._released.set()

    @property
    def released(self) -> bool:
        return self._released.is_set()


@pytest.fixture
def gate():
    g = Gate()
    yield g
    g.release()
