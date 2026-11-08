"""The agy CLI as a provider: it works in the project with its own tools.

Built on what was measured from the real CLI (version 1.2.14, 7 Oct 2026):

- it is started with --input-format stream-json --output-format stream-json -p= and reads
  its prompt from stdin as one JSON line; when stdin closes, the turn ends;
- it prints one JSON event per line: `init` (the model it runs on), `step_update` (text
  deltas of an answer, and its own tools as they start and end) and `result`. Each event's
  fields are in an object of the event's own name, and every step has a `step_index`
  (two streams of the real CLI are kept in tests/agy_streams);
- started without a flag it uses its reading tools, and a tool that needs leave (a
  command, a write) is refused by the CLI itself, since nobody can be asked: the step ends
  as an error that says "permission check failed ... user denied permission", and the
  result names it in `denied_actions`. The user's own agy settings can give leave for more;
- --dangerously-skip-permissions is the one way to let it do everything (run against the
  real CLI on 11 Oct 2026: tests/agy_streams/native_writes_and_runs.jsonl).

Natively (slice 89e, measured on 1.3.3, 24 Oct 2026) it runs with that flag in a home of
KOLONİ's (USERPROFILE and HOME; its sign-in is in the Windows vault and still works), whose
`.gemini/config/hooks.json` holds one PreToolUse hook: KOLONİ's `agy_hook`, which hands each
tool call to KOLONİ before it runs and tells agy KOLONİ's answer (`AgentRunner._approve`).
With the flag the hook still sees every tool and its "deny" is obeyed; without it, headless
agy refuses every command whatever the hook says. A hook that fails or times out blocks the
tool; a hooks.json that is not JSON is passed over without a word - so agy is not given its
task before its log says it loaded the hook.

An MCP server it is given only through its home's settings (B-310). What was measured is R103
(1.4.9, an empty home of its own): `agy mcp add` wrote `.gemini/config/mcp_config.json` (that
file was not kept, so the shape written here is not measured), headless agy started the server
it named, and called its tool only with `mcp(<server>/<tool>)` allowed in
`.gemini/antigravity-cli/settings.json`. So in both ways of running it works in a home of
KOLONİ's that names KOLONİ's bridge there and allows each of KOLONİ's tools it is offered, one
by one; it is given its task only once that bridge is in (or runs the old way, without
KOLONİ's tools). Reading only, it can also be asked to search the web (`AgySearch`).
"""

import asyncio
import contextlib
import ctypes
import json
import os
import re
import shlex
import shutil
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable, Collection
from pathlib import Path
from typing import Any

from app import agy_hook, mcp_bridge
from app.model_cli import _brief, _dict, _events, _Searches, conversation, level_in_name, levels_of
from app.model_client import ModelUnavailable, OwnStop, StepResult
from app.model_native import READ_ONLY_RULES, WHERE, CodexNativeClient, OnItem
from app.model_session import SERVER, CallTool, SessionResult, ToolServer, bridge_file
from app.roles import BACKLOG
from app.workspace import far_or_device

# The one tool its hook calls on its door (`agy_hook`): never one an agent is offered.
DOOR_TOOL = {"type": "function", "function": {
    "name": "approve", "description": "KOLONİ's answer to agy's hook, before its tool acts.",
    "parameters": {"type": "object", "properties": {}}}}

AGY_RULES = """You are working as an agent inside KOLONİ, a workspace where several agents
work for one user. The input is a JSON document with "instructions" (who you are and how
to work) and "conversation" (everything so far, oldest first). Carry on from the end of
the conversation: do what the last user message asks.

Work in this project folder with your own tools. KOLONİ shows the user what you do. Where
the instructions or the conversation mention tools such as read_file, edit_file or
run_command, use your own equivalents. {reach}

{how}

When the work is done, say briefly what you did and what you did not verify."""
REACH_NONE = (
    "You have nothing here to reach the user or another agent with: where the instructions "
    "speak of asking someone or handing work on, do that part yourself, or say plainly that "
    "you could not.")
REACH_KOLONI = (
    'The "koloni" MCP server gives you KOLONİ\'s own tools, which yours cannot do: {tools}. Use '
    "them where the instructions call for it (spawn_agent, where you have it, hands a part of "
    "the job to another agent and returns its report). They are yours already: call them by "
    "these names, with no need to look for them first.")
# B-317: reading only, it listed that folder with a command, refused there, and ended mute.
DEFINED_IN = (" Should you want one's definition, it is <name>.json in {folder}: read it with "
              "your own file tool, never with a command.")
HOW_READS = (
    "You are here to read: no command can run in this run and no file can be changed, so a "
    "step that would do either is refused. Look with your own tools that read files, list "
    "folders and search, and carry on with the rest of the task. Say what you found, and what "
    "would have to be changed or run."
)
HOW_NATIVE = (
    "You may change files and run commands here. KOLONİ is asked before each of your tools "
    "runs, and the user may be asked: a refusal is their decision, not an error to work "
    "around another way."
)

SKIP_PERMISSIONS = "--dangerously-skip-permissions"
# Its own tools, by what they do (as listed in the design; the others only look). 1.3.3's
# hook named its write `write_file` (measured).
AGY_RUNS = ("run_command",)
# Input to a command at work: judged as a command of its own (its "Input").
AGY_INPUT = "send_command_input"
AGY_WRITES = (
    "write_file", "write_to_file", "replace_file_content", "multi_replace_file_content",
    "sed_file", "notebook_edit", "edit_notebook",
)
# Its steps that change nothing and run nothing - a running command's output read, the end
# of its turn: let through, and not stopped at if its hook was not called for them.
AGY_INERT = ("command_status", "finish", "task_boundary")
# Its tools that run code or start agents of its own (its step types, as its binary names
# them): refused until each is measured.
AGY_NOT_YET = (
    "invoke_subagent", "browser_subagent", "define_subagent", "schedule", "run_workflow",
    "notebook_execution", "execute_notebook", "run_extension_code", "execute_browser_javascript",
    "agency_tool_call", "shell_exec", "rpc_action", "compile", "compile_applet",
    "blaze_build_targets", "blaze_test_targets", "install_applet_dependencies",
    "install_applet_package", "deploy_firebase", "set_up_firebase", "set_up_cloud_sql",
    "cloud_sql_execute_sql", "cloud_sql_update_schema", "restart_dev_server", "git_commit",
)
UNKNOWN_YET = "KOLONİ does not know what this agy tool does yet"
# Why a tool KOLONİ does not know is a card in words at every level (`AgentRunner._approve`).
UNKNOWN = "KOLONİ does not know this tool of agy's: it is asked about every time"
CANNOT_TELL = "KOLONİ cannot tell what this tool would do, so it does not run"
# Where its tools name the file they work on, as measured: write_to_file's "TargetFile"
# (natively, a full path) and view_file's "AbsolutePath"; 1.3.3's hook was told "Path". For a
# tool that was not measured, a parameter named like those, in any case; never what a
# parameter holds (a file's content can be a path).
AGY_PATHS = ("file", "path", "filename", "directory")
WORDS = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z0-9]+")  # the words a parameter's name is made of
# What its tools that only look are asked about as (Claude Code's of the same kind): 1.3.3's
# read_file as measured, the others by the names agy's own documents and stream give them.
AGY_LOOKS = {
    **dict.fromkeys(("read_file", "view_file", "view_file_outline", "view_code_item",
                     "view_content_chunk", "read_notebook"), "Read"),
    **dict.fromkeys(("grep_search", "find", "find_by_name", "code_search"), "Grep"),
    **dict.fromkeys(("list_dir", "list_directory"), "LS"),
}
# Its writes that are given the whole of what the file will hold (measured: "Content").
AGY_WHOLE_WRITES = ("write_file", "write_to_file")
# KOLONİ's door for its hook, next to hooks.json: {"port", "key"} (`agy_hook`); and the
# .cmd file there that agy runs as its hook.
DOOR = "koloni-door.json"
WRAPPER = "koloni-hook.cmd"
# B-310: the first version KOLONİ's tools were measured to reach over MCP (`cli_surface`).
BRIDGE_FROM = (1, 4, 9)
# How its hook and its stream may name a tool of KOLONİ's server: one of these, then the tool.
# shortcut: neither is measured (R103 called one reading only, with no hook and no stream kept):
# the hook's name of an MCP call, and its stream's step, are guessed - Gemini CLI's
# mcp__<server>__<tool> and its permission rule's <server>/<tool>. A name not among them is a
# card in words, and a step on record twice; measure it on a native run.
KOLONIS_AS = (f"mcp__{SERVER}__", f"{SERVER}/")
# B-318 (1.4.x, seen live): its one tool for a tool of any MCP server, and its listings of one.
WRAPS = "call_mcp_tool"
LISTINGS = ("list_resources", "list_tools")
# shortcut: how the wrapper and the listings name the server and the tool is not measured (the
# hook's args and the stream's parameters were not kept): a key that reads as one of these in
# any case and however joined (ServerName, server_name), as agy names its other parameters.
# Only those keys, each once: any other (a second way of naming a server) leaves the call as it
# came - a card in words. Measure it live.
KEYS = {
    **dict.fromkeys(("server", "servername", "mcpserver", "mcpservername"), "server"),
    **dict.fromkeys(("tool", "toolname", "name", "mcptool", "mcptoolname"), "tool"),
    **dict.fromkeys(("arguments", "args"), "arguments"),
}
# What KOLONİ says where agy ended its turn with no word after a step was refused (B-317).
NO_ANSWER = "KOLONİ: agy ended its turn without an answer, after it was refused {steps}."
BY_AGY = "refused by agy"  # (its own words are not repeated: they hold the command line)
# How long its bridge is waited for before it is given its task (as its hook is: `loaded`).
# shortcut: that agy starts its MCP servers before it reads its prompt is R103's reading of
# one headless run, not measured on a turn; if it starts them only once it has its task, every
# run waits this long and runs the old way - measure it first.
BRIDGE_SECONDS = 10.0
BRIDGE_NOT_STARTED = "agy did not start KOLONİ's bridge: running the old way"
NOT_OFFERED = "it is not one of KOLONİ's tools given to this agent"
# What no tool of agy's own can do: an agent offered one whose role does not run commands (a
# Product owner, not a Lead: it does the work itself) is not run the old way. Nor, started
# read-only for its role (B-301), one that writes only with KOLONİ's.
NEEDS_KOLONI = frozenset(BACKLOG)
WRITES_KOLONI = frozenset({"write_file", "edit_file"})
# A step named as KOLONİ's own that KOLONİ's server never ran: another server of that name.
NOT_KOLONIS = ("agy reported a call of KOLONİ's {tool} that KOLONİ's server never ran (another "
               'server named "koloni"?), so the run is stopped')
# shortcut: the longest timeout agy honours is unmeasured, and a card left open longer
# leaves the tool blocked while its card stays open; measure it, and end the card with it.
HOOK_SECONDS = 1800
# What its log says when it has read its hooks (measured: "loaded 1 named hooks from 1
# hooks.json file(s)"), and how long it is waited for before it is given its task. Its own
# documents say a project's .agents/hooks.json is merged in too: anything but KOLONİ's one
# hook from its one file would run commands KOLONİ was never asked about.
LOADED = re.compile(r"loaded (\d+) named hooks from (\d+) hooks\.json")
LOADED_SECONDS = 20.0
# What can go between quotes in a .cmd file: plain ASCII, but a quote and the % it expands.
QUOTABLE = re.compile(r"[ !#$&-~]+")
# A step that could have changed something and ended in an error nobody can read as a
# refusal: KOLONİ does not know whether it ran, and says so.
UNSURE = "ended in an error; not known whether it ran"
# The step said nothing of a refusal itself; the result did.
NAMED_DENIED = "its result names a command among the actions it denied"
# Listing its models uses no model; it is not waited on for long.
MODELS_SECONDS = 20.0
MODEL_ID = re.compile(r"[A-Za-z0-9._-]+")
# What it is told when it is only tried out: the folder it runs in is nobody's project.
TRY_OUT_RULES = (
    'The input is a JSON document with "instructions" and "conversation". Answer the last '
    "user message."
)


def said_refused(reason: str) -> bool:
    """Whether a step's error is the CLI saying it refused the step, in the words that
    were measured: 'permission check failed for command "...": user denied permission to
    run command'. The word "permission" alone says nothing: a command that ran can print
    it."""
    words = reason.strip().lower()
    return words.startswith("permission check failed") or "user denied permission" in words


def listed_models(printed: str) -> list[str]:
    """The model ids in what `agy models` prints: one `id<TAB>display name` on a line,
    the id made of letters, digits, ".", "-" and "_". Any other line (it says "Fetching
    available models..." first; a warning may have a tab in it) is passed over."""
    names: list[str] = []
    for line in printed.splitlines():
        name, tab, shown = line.partition("\t")
        if tab and MODEL_ID.fullmatch(name) and shown.strip() and name not in names:
            names.append(name)
    return names


def kolonis(name: str, offered: Collection[str]) -> bool:
    """Whether agy names one of KOLONİ's tools it was offered this run (`KOLONIS_AS`): run by
    KOLONİ and held to KOLONİ's rules there, so neither asked about nor on record as agy's own.
    Never a bare name: agy's own write_file is named so. By name only: each such step is
    counted against the calls KOLONİ's server ran (`NOT_KOLONIS`)."""
    return any(name.startswith(lead) and name[len(lead):] in offered for lead in KOLONIS_AS)


def _parts(args: dict) -> dict[str, object] | None:
    """What a wrapper or a listing was given, by `KEYS`' kinds; None where a key is none of
    them or a kind comes twice."""
    parts: dict[str, object] = {}
    for key, value in args.items():
        kind = KEYS.get(re.sub(r"[^a-z]", "", key.lower()))
        if kind is None or kind in parts:
            return None
        parts[kind] = value
    return parts


def unwrapped(tool: str, args: dict) -> str:
    """B-318: a tool of KOLONİ's server called through agy's own wrapper (`WRAPS`), under the
    name it has when called directly - so it is judged the same way (`kolonis`). Any other call
    of the wrapper (another server, no clear name, a key more) is left as it came."""
    parts = _parts(args) if tool == WRAPS else None
    if parts and parts.get("server") == SERVER and isinstance(inner := parts.get("tool"), str) \
            and inner:
        return KOLONIS_AS[0] + inner
    return tool


def own_definition(raw: str, home: Path, offered: Collection[str]) -> bool:
    """B-318: whether agy reads its own definition of a KOLONİ tool offered this run, which
    1.4.x reads before it calls the tool: <tool>.json in .gemini/antigravity-cli/mcp/koloni of
    this run's home, by where the path really leads (a link out of that folder is none). agy
    writes it from what KOLONİ's server lists - a tool's name, description and parameters; the
    bridge's key is only in config/bridge.json, which stays refused.
    shortcut: the file's own layout was not measured; if agy copies the server's command in,
    that names bridge.json's path, never the key."""
    if not Path(raw).is_absolute() or far_or_device(raw):
        return False  # (never resolved: a share would be dialled, a relative path is KOLONİ's)
    try:
        real = Path(raw).resolve(strict=True)
        folder = home.resolve(strict=True) / ".gemini" / "antigravity-cli" / "mcp" / SERVER
    except (OSError, ValueError):
        return False
    # (One more link to the file is a hard link from elsewhere - bridge.json, say.)
    return (os.path.normcase(real.parent) == os.path.normcase(folder)
            and real.suffix == ".json" and real.stem in offered and real.is_file()
            and os.stat(real).st_nlink == 1)


def _user_line(prompt: str) -> str:
    """A prompt as agy reads it on stdin: one JSON line, in plain ASCII - no code page
    between here and there can change it."""
    return json.dumps({"event": "user", "message": {"role": "user", "content": prompt}}) + "\n"


def _text(value: object) -> str:
    """What a tool gave back, as text."""
    if value is None:
        return ""
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _named(args: dict, *words: str) -> list[str]:
    """What `args` holds under a name whose last word is one of `words`, in any case and
    however the words are joined (TargetFile, target_file, TARGET_FILE) - "Profile" is no
    file."""
    return list(dict.fromkeys(
        value for key, value in args.items()
        if (said := WORDS.findall(key)) and said[-1].lower() in words
        and isinstance(value, str) and value))


def asked_as(tool: str, args: dict) -> list[tuple[str, dict]] | str:
    """How KOLONİ asks about one tool call agy's hook was told of: as about Claude Code's
    own tool of the same kind (`AgentRunner._approve`), one question for each file it names.
    A tool KOLONİ does not know that names files - a move, a delete - is a change of each of
    them; one that names none, or a look whose path is not found, is a card in words at every
    level. [] for a step that changes nothing; the reason it is refused where KOLONİ cannot
    tell what it would do (a command without its line, a change or a read that names no
    file) or does not know it yet (it runs code or starts agents: `AGY_NOT_YET`)."""
    paths = _named(args, *AGY_PATHS)
    if tool in AGY_INERT or (tool in LISTINGS and _parts(args) == {"server": SERVER}):
        return []  # (KOLONİ's server lists only what it offers: B-318)
    if tool == WRAPS or tool in LISTINGS:
        # Another server's: KOLONİ cannot tell what it would do, whatever path it names.
        return [(tool, {**args, "reason": UNKNOWN})]
    if tool in AGY_NOT_YET:
        return UNKNOWN_YET
    if tool in (*AGY_RUNS, AGY_INPUT):
        line = args.get("Input" if tool == AGY_INPUT else "CommandLine")
        cwd = _named(args, "cwd")[:1]
        # (Its run_command's BypassSandbox, REA R18: a reason, so a card at every level.)
        out = {"reason": "it asks to run outside its sandbox"} if args.get(
            "BypassSandbox") in (True, "true") else {}
        return [("Bash", {"command": line, **({"cwd": cwd[0]} if cwd else {}), **out})] \
            if isinstance(line, str) and line else CANNOT_TELL
    content = args.get("Content", args.get("CodeContent"))
    if tool in AGY_LOOKS and AGY_LOOKS[tool] == "Read":
        return [("Read", {"file_path": path}) for path in paths] or CANNOT_TELL
    if tool in AGY_LOOKS and paths:
        # (A search of a folder with a secret its glob could take is a card: `_approve`, 89b.)
        held = next((value for key, value in args.items() if key.lower() == "includes"), None)
        return [(AGY_LOOKS[tool], {"path": path, **({"glob": held} if held else {})})
                for path in paths]
    if tool in AGY_WHOLE_WRITES and isinstance(content, str):
        return [("Write", {"file_path": path, "content": content}) for path in paths] \
            or CANNOT_TELL
    if tool in AGY_WRITES or (paths and tool not in AGY_LOOKS):
        return [("Edit", {**args, "file_path": path}) for path in paths] or CANNOT_TELL
    return [(tool, {**args, "reason": UNKNOWN})]


def _quotable(path: str) -> str:
    """`path` as a .cmd file can hold it between quotes: as it is, or by its 8.3 name."""
    if QUOTABLE.fullmatch(path) or sys.platform != "win32":
        return path  # (only Windows writes a .cmd file to quote it in)
    buffer = ctypes.create_unicode_buffer(32768)
    if ctypes.windll.kernel32.GetShortPathNameW(path, buffer, len(buffer)) and (
            QUOTABLE.fullmatch(buffer.value)):
        return buffer.value
    raise OwnStop(f"agy cannot be given KOLONİ's hook: the path {path!r} has a sign a .cmd "
                  "file cannot hold, and no short name without it")


def _hook_line(folder: Path) -> str:
    """The command agy's hook runs. agy runs it through `cmd /c` in the folder of hooks.json
    (its own documents), where a quoted path broke (measured): so it is a .cmd file there,
    named from that folder, that starts KOLONİ's hook script with KOLONİ's python - each by
    a name a .cmd file can hold - given the door's file beside it. No path of the home is on
    it. (`.\\`: with NoDefaultCurrentDirectoryInExePath set, `cmd` finds no bare name there.)"""
    if sys.platform != "win32":
        return shlex.join([sys.executable, "-I", agy_hook.__file__, DOOR])
    python, script = (_quotable(path) for path in (sys.executable, agy_hook.__file__))
    (folder / WRAPPER).write_text(  # (text mode: each line ends in CRLF)
        f'@"{python}" -I "{script}" {DOOR}\n@exit /b %errorlevel%\n', encoding="ascii")
    return f".\\{WRAPPER}"


class _Hooked:
    """What its hook asked KOLONİ in one run: each step's id -> whether it was let through;
    whether a call came that could not be read; each refusal, "tool: why" (B-317); each step
    it let through as a tool of KOLONİ's, by the name KOLONİ judged (B-318)."""

    def __init__(self) -> None:
        self.steps: dict[str, bool] = {}
        self.unread = False
        self.refused: list[str] = []
        self.kolonis: dict[str, str] = {}


class _Bridged:
    """KOLONİ's tools in one run (B-310): those it was offered; those it has now (none once it
    runs the old way); how many calls KOLONİ's server ran, and how many agy said it made."""

    def __init__(self, offered: frozenset[str]) -> None:
        self.offered = offered
        self.own = set(offered)
        self.served = 0
        self.reported = 0


def sweep_homes(homes: Path) -> None:
    """The homes an earlier process left behind (`AgyClient.run_native`): at the start no
    run is live, and none of them is of any use."""
    for home in homes.glob("agy-*"):
        shutil.rmtree(home, ignore_errors=True)


def _log_of(home: Path) -> str:
    """What agy has written to its log in `home` so far."""
    with contextlib.suppress(OSError):
        return (home / ".gemini" / "antigravity-cli" / "cli.log").read_text(
            encoding="utf-8", errors="replace")
    return ""


class AgyClient(CodexNativeClient):
    """agy at work in the project folder. `reads`: started without the flag, so that it
    only reads - at any permission level, for any role, since the CLI itself refuses the
    rest. Otherwise with the flag, in a home of KOLONİ's under `homes` (the system's temp
    folder if None), asking KOLONİ before each tool through its hook."""

    command = "agy"
    label = "agy"
    asks = False
    looks_by_running = False  # it has a read_file of its own
    read_only_commands = False  # (reading it runs none)
    efforts = levels_of("agy_cli")
    # Nothing keeps what its commands write to the folder it works in (`agent._sandboxed`).
    sandboxed = False
    # KOLONİ's tools over its bridge, in its home (B-310; not on an agy older than BRIDGE_FROM:
    # `cli_surface.checked`), and this kind has a way of running that only reads.
    collaborates = True
    can_read_only = True
    def __init__(self, executable=None, model=None, timeout: float = 900.0, *,
                 reads: bool = True, homes: Path | None = None, **more):
        super().__init__(executable, model, timeout, **more)
        self.reads = reads
        # B-404: a model whose name fixes its level (gemini-3.8-flash-low) takes none.
        self.level_named = level_in_name("agy_cli", model)
        if self.level_named:
            self.efforts = ()
        # No secret variable, reading too (B-310: it has KOLONİ's tools and a server named in
        # its home; its sign-in: `_inherited`).
        self.logins = frozenset()
        self.asks = not reads  # natively, through its hook
        self.homes = homes
        # Natively a sub-agent is started in a working copy, as Codex is (seen with the real
        # CLI on 11 Oct 2026). Reading changes nothing: no copy.
        self.own_copy = not reads
        # B-301: reading it is read-only for any role whose commands it need not run: it writes
        # with KOLONİ's write tools over its bridge (B-310). Natively it writes, asked by its
        # hook, in its own copy: left as it is.
        self.starts_read_only = reads
        # Nothing asks before it writes, and nothing is told of a write through a link:
        # the project's dependency folders are not linked into its copy.
        self.links_in_copy = reads

    def _inherited(self, pass_env: str | None = None) -> dict[str, str]:
        # Nothing of the user's own Gemini or Antigravity set-up reaches it (reading too, since
        # B-310), as for Copilot: such a variable can name other settings than its home's (other
        # MCP servers, other rules), or another account.
        # shortcut: none is kept for its sign-in (`logins`), which was measured to come from
        # the Windows vault (natively; reading, not yet on 1.4.9); keep one here (a
        # GEMINI_API_KEY) if a sign-in is ever seen to need it.
        told = super()._inherited(pass_env)
        return {name: value for name, value in told.items()
                if not name.upper().startswith(("GEMINI_", "ANTIGRAVITY_"))}

    def _new_home(self) -> Path:
        """A home of KOLONİ's for one run, under `homes` (`sweep_homes`)."""
        homes = self.homes or Path(tempfile.gettempdir())
        homes.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix="agy-", dir=homes))

    def talker(self) -> "AgyClient":
        """The same agy, reading only: how it speaks where nobody may change anything."""
        if self.reads:
            return self
        return AgyClient(
            self._executable, self._model, self._timeout, reads=True, homes=self.homes,
            which=self._which, launcher=self._launcher, env=self._env,
        )

    def _agy_arguments(self) -> list[str]:
        arguments = ["--model", self._model] if self._model else []
        arguments += ["--input-format", "stream-json", "--output-format", "stream-json"]
        if not self.reads:
            arguments.append(SKIP_PERMISSIONS)
        # -p takes its value in the same argument (measured: written apart, it takes the
        # next flag for the prompt). It is left empty: the prompt comes on stdin.
        return [*arguments, "-p="]

    def _input(self, messages: list[dict], root: str | None,
               own: frozenset[str] = frozenset(), read_only: bool = False,
               home: Path | None = None) -> str:
        """What is written to its stdin: the whole prompt as one JSON line. `root`: the
        project folder it works in; None when it is only tried out, in a folder that is
        no project - and is not said to be one. `own`: KOLONİ's tools it has;
        `read_only`: started read-only for its role (B-301), it writes with them; `home`:
        this run's own, where agy keeps their definitions."""
        instructions = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        document = {"instructions": instructions, "conversation": conversation(messages)}
        if root is None:
            told = TRY_OUT_RULES
        else:
            reach = REACH_KOLONI.format(tools=", ".join(sorted(own))) + (DEFINED_IN.format(
                folder=home / ".gemini" / "antigravity-cli" / "mcp" / SERVER) if home else ""
            ) if own else REACH_NONE
            rules = AGY_RULES.format(reach=reach,
                                     how=HOW_READS if self.reads else HOW_NATIVE)
            if read_only:
                rules += f"\n\n{READ_ONLY_RULES}"
            told = f"{rules}\n\n{WHERE.format(root=root)}"
        return _user_line(f"{told}\n\n" + json.dumps(document, ensure_ascii=False))

    async def run_native(  # noqa: C901
        self,
        model_id: str,
        messages: list[dict],
        tools: list[dict] | None,
        root: str,
        call_tool: CallTool,
        on_text: Callable[[str], Awaitable[None]],
        on_item: OnItem,
        withheld: tuple[str, ...] = (),
        linked: tuple[str, ...] = (),
        ceiling: str | None = None,
        also: tuple[str, ...] = (),
        effort: str | None = None,
        pass_env: str | None = None,
        denied: tuple[str, ...] | None = None,
        planted: dict[str, str] | None = None,
        skills: dict[str, str] | None = None,
        skills_told: str = "",
        on_live: object = None,  # (agy has no door into its turn: never called, 89d)
        tests_at_stop: bool = False,  # (nor a hook at its end: Claude Code's, 89m)
        # shortcut: 89g's roles as its own sub-agents (`--agent`) are Claude Code's only; offer
        # them to agy once measured.
        inside: dict[str, dict] | None = None,
        report_schema: dict | None = None,  # (never given to agy: `_hands_back`, 89p)
        # shortcut: Stop on one of agy's own commands does not end its turn (B-357 was Codex's);
        # end its bridge then too if one is seen to hang.
        on_end: object = None,
        # shortcut (27): agy goes on in no session of its own - its resuming is not measured;
        # every turn is sent the whole conversation. Resume it once measured, as Claude Code.
        session: dict | None = None,
        level: str | None = None,
        keep: bool = False,
    ) -> SessionResult:
        # shortcut: agy is not given `also` - no folder option of its is known (not tried
        # against the real CLI); it starts in the project alone. Give them once one is.
        # Nor `denied`: its sandbox cannot write to the project (K-agy-bypass). Nor
        # `skills` as its own (nor `skills_told`): they are in its instructions.
        # In a working copy, git there looks no higher than the copies' folder; the secret
        # variables the user passes (`pass_env`) go in too.
        env = {**self._inherited(pass_env), **(planted or {}),
               **({"GIT_CEILING_DIRECTORIES": ceiling} if ceiling else {})}
        # (An older agy, `cli_surface.checked`, is handed none: not even a Lead's pick_teams.)
        tools = tools if self.collaborates else []
        bridged = _Bridged(frozenset(tool["function"]["name"] for tool in tools or []))
        read_only = "read_only" in withheld
        hooked = None if self.reads else _Hooked()

        def answer(decision: str, reason: str = "") -> tuple[bool, str]:
            return True, json.dumps({"decision": decision, "reason": reason})

        async def asked(name: str, arguments: str) -> tuple[bool, str]:
            """One call of its hook: KOLONİ's answer, as the hook tells it to agy."""
            with contextlib.suppress(ValueError):
                told = _dict(json.loads(arguments))
                call, step = _dict(told.get("toolCall")), told.get("stepIdx")
                args = _dict(call.get("args"))
                tool = unwrapped(str(call.get("name") or ""), args)
                if tool and isinstance(step, int) and not isinstance(step, bool):
                    assert hooked is not None  # (its hook is natively only)
                    step_id = f"agy_{step}"
                    hooked.steps[step_id] = False  # (let through only once all is allowed)
                    hooked.kolonis.pop(step_id, None)  # (asked again: as it is asked now)
                    # KOLONİ's own tool: asked about where KOLONİ runs it, not here.
                    # One named so that it has not now (not offered, or it runs the old way):
                    # refused, whichever server would answer it.
                    questions = [] if kolonis(tool, bridged.own) else NOT_OFFERED if any(
                        tool.startswith(lead) for lead in KOLONIS_AS) else asked_as(tool, args)
                    if questions == [] and kolonis(tool, bridged.own):
                        hooked.kolonis[step_id] = tool  # (its stream is not read for this)
                    if isinstance(questions, str):
                        hooked.refused.append(f"{tool}: {questions}")
                        await on_item("completed", {
                            "type": "mcp_tool_call", "server": "agy", "tool": tool,
                            "arguments": args, "status": "declined",
                            "error": {"message": questions}})
                        return answer("deny", questions)
                    # B-318: its own definition of a tool of KOLONİ's, read before it calls it.
                    questions = [(kind, given) for kind, given in questions if not (
                        kind == "Read" and own_definition(given["file_path"], home,
                                                          bridged.offered))]
                    for number, (kind, given) in enumerate(questions):
                        # A tool asked about as several (each file it names): each its own id.
                        use_id = step_id + (f":{number}" if number else "")
                        await on_item("announced", {"id": use_id})
                        _ok, verdict = await call_tool("approve", json.dumps(
                            {"tool_name": kind, "input": given, "tool_use_id": use_id}))
                        said = _dict(json.loads(verdict))
                        if said.get("behavior") != "allow":
                            why = str(said.get("message") or "KOLONİ said no")
                            hooked.refused.append(f"{tool}: {why}")
                            return answer("deny", why)
                    hooked.steps[step_id] = True
                    return answer("allow")
            if hooked is not None:
                hooked.unread = True
            return answer("deny", "KOLONİ could not read this tool call")

        # shortcut: a command at Full auto runs with this home as its own, so it could rewrite
        # hooks.json (if agy reads it again mid-turn: unmeasured) or read koloni-door.json and
        # call the door with its key, to have steps of its own let through. Only an agent set on
        # getting past KOLONİ would; agy's file tools cannot (KOLONİ's runtime is never opened).
        # Keep the home out of commands' reach if that is ever wanted.
        # shortcut: in a working copy agy also reads the .agents/ (.agent/, _agents/, _agent/)
        # of every folder from the copy up to its root, and a write there in its copy is asked
        # only when the copy is taken in; the one-hook check above holds what it loads at its
        # start. Measure what it loads mid-turn and from above the copy.
        home = self._new_home()

        async def loaded() -> None:
            """agy is given its task only once its log says it loaded KOLONİ's hook: one
            that is not JSON it passes over without a word (measured)."""
            waited = min(LOADED_SECONDS, self._timeout / 2)
            deadline = time.monotonic() + waited
            while not (counts := LOADED.findall(await asyncio.to_thread(_log_of, home))):
                if time.monotonic() > deadline:
                    raise OwnStop(f"agy did not say within {waited:g} seconds that it loaded "
                                  "KOLONİ's hook, and is not run without it")
                await asyncio.sleep(0.1)
            if any(count == "0" for count, _files in counts):
                raise OwnStop("agy loaded no hook (its log says none), so nothing could "
                              "ask KOLONİ before its tools: it is not run without it")
            if set(counts) != {("1", "1")}:
                raise OwnStop("agy loaded hooks besides KOLONİ's (a project's .agents/"
                              "hooks.json, say), which would run without KOLONİ being asked: "
                              "it is not run so")

        # Its hook's door: the one tool it calls is KOLONİ's approve; while it waits for an
        # answer (a card, for as long as the user thinks) agy is not silent.
        # (Its own: since slice 89b no agent is offered approve.)
        door = None if self.reads else ToolServer([DOOR_TOOL], asked, alone=False)

        async def counted(name: str, arguments: str) -> tuple[bool, str]:
            """KOLONİ's tools over its bridge (B-310), counted as the door's calls: `_work`
            watches one server for silence, and a sub-agent's work is none."""
            bridged.served += 1  # (before it runs: agy says it made it only once it has run)
            if door is None:
                return await call_tool(name, arguments)
            door.in_flight += 1
            try:
                return await call_tool(name, arguments)
            finally:
                door.in_flight -= 1
                door.last_reply = time.monotonic()

        # B-304: its key serves one connection. shortcut: agy was seen to start it once, at its
        # start (R103, reading); one that starts it again (a reconnect, a sub-agent of its own)
        # ends the run, said why (`SECOND_BRIDGE`) - measure it on a long native run.
        bridge = ToolServer(tools or [], counted)
        if door is not None:
            bridge.on_end = lambda: door._end(bridge.ended or OwnStop("its bridge ended"))

        async def ready() -> str | None:
            """Its hook loaded (natively), then its bridge in: given its task only then, so
            that a home it did not take, or a server in place of KOLONİ's, is not what it works
            with (B-310). One whose bridge never comes runs the old way: the prompt for that."""
            if door is not None:
                await loaded()
            deadline = time.monotonic() + min(BRIDGE_SECONDS, self._timeout / 2)
            while bridged.own and not bridge._taken and not bridge.ended:
                if time.monotonic() > deadline and ("run" in withheld or read_only) and (
                        needs := sorted(bridged.offered & (
                            NEEDS_KOLONI | (WRITES_KOLONI if read_only else frozenset())))):
                    # (B-315: a Product owner without them searched the files for 17 minutes.)
                    raise OwnStop(f"{BRIDGE_NOT_STARTED.split(':')[0]}, and this agent's work "
                                  f"needs KOLONİ's own tools ({', '.join(needs)}): it is not "
                                  "run on agy without them")
                if time.monotonic() > deadline:
                    bridged.own.clear()
                    await bridge.close()  # (a late one serves nothing)
                    await on_item("completed", {"type": "bridge_not_started",
                                                "why": BRIDGE_NOT_STARTED})
                    return self._input(messages, root, frozenset())
                await asyncio.sleep(0.05)
            return None

        try:
            await bridge.start()
            config = home / ".gemini" / "config"
            config.mkdir(parents=True)
            if bridged.offered:
                # shortcut: the shape is Antigravity's documented mcpServers (as Claude Code's
                # mcp.json), not the file `agy mcp add` wrote in R103, which was not kept; a
                # wrong one is a run the old way (`ready`) - measure it live.
                (config / "mcp_config.json").write_text(json.dumps({"mcpServers": {SERVER: {
                    "command": sys.executable,
                    "args": [mcp_bridge.__file__, str(bridge_file(bridge, config))]}}}),
                    encoding="utf-8")
                # One rule for each tool it is offered, never a wildcard: reading only, these
                # are all that a headless agy is let call (measured, R103).
                own = home / ".gemini" / "antigravity-cli"
                own.mkdir(parents=True)
                (own / "settings.json").write_text(json.dumps({"permissions": {"allow": [
                    f"mcp({SERVER}/{name})" for name in sorted(bridged.offered)]}}),
                    encoding="utf-8")
            if door is not None:
                await door.start()
                # Port and key in a file only its hook is pointed at, not on a command line.
                (config / DOOR).write_text(json.dumps({"port": door.port, "key": door.key}),
                                           encoding="utf-8")
                hook = {"type": "command", "command": _hook_line(config),
                        "timeout": HOOK_SECONDS}
                (config / "hooks.json").write_text(json.dumps(
                    {"koloni": {"PreToolUse": [{"matcher": "*", "hooks": [hook]}]}}),
                    encoding="utf-8")
            return await self._turn(
                messages, Path(root), root, call_tool, on_text, on_item,
                {**env, "USERPROFILE": str(home), "HOME": str(home)}, effort,
                server=door or bridge, ready=ready, hooked=hooked, bridged=bridged,
                read_only=read_only, home=home,
            )
        finally:
            await bridge.close()
            if door is not None:
                await door.close()
            shutil.rmtree(home, ignore_errors=True)

    async def _heard(
        self, kind: str, item: dict, said: bool, busy: set[str], on_text, on_item: OnItem,
    ) -> bool:
        said = await super()._heard(kind, item, said, busy, on_text, on_item)
        if item.get("unhooked"):
            # Its hook did not ask KOLONİ about this tool: the gate is gone, nothing more runs.
            name = item["unhooked"]
            how = "ended in an error" if item.get("status") == "failed" else "ran"
            why = ("a call of its hook could not be read (no tool or step number), so KOLONİ "
                   "cannot tell which step it was" if item.get("unread")
                   else "its hook did not reach KOLONİ for it")
            raise OwnStop(f"agy's {name} ran though KOLONİ refused it, so the run is stopped"
                          if item.get("refused") else
                          f"agy's {name} {how} without KOLONİ being asked ({why}), so the run "
                          "is stopped")
        return said

    async def _turn(
        self, messages: list[dict], workdir: Path, root: str | None, call_tool: CallTool,
        on_text: Callable[[str], Awaitable[None]], on_item: OnItem,
        env: dict[str, str] | None = None, effort: str | None = None, *,
        server: ToolServer | None = None,
        ready: Callable[[], Awaitable[str | None]] | None = None,
        hooked: "_Hooked | None" = None, bridged: _Bridged | None = None,
        read_only: bool = False, home: Path | None = None,
    ) -> SessionResult:
        """One run of the CLI in `workdir`. `root`: the project it is told it works in -
        None where the folder is no project (a try-out). Natively: its hook's door
        (`server`), and the steps its hook asked about (`hooked`). What it waits for before it
        is given its task (`ready`, which may give another prompt). `bridged`: KOLONİ's tools
        over its bridge (reading only, the bridge's server is `server`); `read_only` and
        `home`: as `_input`."""
        # A try-out's is never started: there is no tool to call.
        server = server or ToolServer([], call_tool)
        command, shim = self._command()
        # Its steps that have started and are not settled, by their id.
        unsettled: dict[str, dict] = {}

        async def seen(phase: str, item: dict) -> None:
            if phase == "started":
                unsettled[str(item.get("id"))] = item
                return
            unsettled.pop(str(item.get("id")), None)
            if not item.get("settled"):  # (a step KOLONİ's server put on record: `used`)
                await on_item(phase, item)

        try:
            return await self._work(
                [*command, *self._leveled(self._agy_arguments(), effort)], shim,
                self._input(messages, root, bridged.offered if bridged else frozenset(),
                            read_only, home),
                workdir, server, on_text, seen, env,
                ready=ready, translate=self._translator(hooked, bridged),
            )
        finally:
            # However the turn ended - its result, a crash, the limit on silence, Stop - a
            # step that started and was never said to end is not known to have finished.
            for item in list(unsettled.values()):
                for left in item.get("pending") or [{**item, "status": "interrupted"}]:
                    with contextlib.suppress(Exception):
                        await on_item("completed", left)

    async def stream_step(self, model_id, messages, tools, on_delta, on_thinking=None,
                          effort=None):
        """One answer with no project to work in: how the provider is tried out. It runs
        in an empty folder and reading only, whatever way the provider is set to run, and
        is not told that the folder is a project - in a home of KOLONİ's, as its runs are, so
        that a try-out signs in as they do (B-310)."""
        said: list[str] = []

        async def on_text(text: str) -> None:
            said.append(text)
            await on_delta(text)

        async def no_tool(name: str, arguments: str) -> tuple[bool, str]:
            return False, "error: it has no tools of KOLONİ's"

        async def unseen(phase: str, item: dict) -> None:
            return None

        workdir, talker = Path(tempfile.mkdtemp(prefix="koloni-cli-")), self.talker()
        home = talker._new_home()
        try:
            result = await talker._turn(
                messages, workdir, None, no_tool, on_text, unseen,
                {**talker._inherited(), "USERPROFILE": str(home), "HOME": str(home)},
                effort=effort,
            )
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
            shutil.rmtree(home, ignore_errors=True)
        return StepResult(
            "".join(said), [], result.input_tokens, result.output_tokens, result.model,
            result.cache_read, result.cache_write,
        )

    async def models(self) -> list[str]:
        """The ids `agy models` lists. No model is used for it."""
        command, shim = self._command()
        workdir = Path(tempfile.mkdtemp(prefix="koloni-cli-"))
        try:
            try:
                process, job = await self._start([*command, "models"], shim, workdir)
            except OSError as exc:
                reason = self._hide(str(exc.strerror or exc))
                raise OwnStop(f"{self.label} could not be started: {reason}") from None
            try:
                printed, complaint = await asyncio.wait_for(process.communicate(), MODELS_SECONDS)
            except TimeoutError:
                raise ModelUnavailable(
                    f"{self.label} did not list its models within {MODELS_SECONDS:g} seconds"
                ) from None
            finally:
                await self._end(process, job)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        if process.returncode:
            reason = _brief(self._hide(complaint.decode("utf-8", errors="replace")))
            raise ModelUnavailable(
                f"{self.label} exited with code {process.returncode}"
                + (f": {reason}" if reason else "")
            )
        return listed_models(printed.decode("utf-8", errors="replace"))

    def _translator(self, hooked: "_Hooked | None" = None,  # noqa: C901
                    bridged: _Bridged | None = None) -> Callable[[dict], list[dict]]:
        """`hooked`: natively, what its hook asked KOLONİ about - a step that ends without
        being among it was not asked about (`_heard`). `bridged`: KOLONİ's tools in this run,
        whose steps are on record where KOLONİ runs them (`kolonis`)."""
        # Its tool steps that have started and not ended: the id each is told under, by
        # the step's `step_index` - or, for a step that has none, by the tool's name.
        at_work: dict[object, str] = {}
        ended_steps: set[int] = set()  # said to be done: said again, it is not done twice
        unnumbered = 0
        # Commands that ended in an error nobody can read as a refusal, while it runs
        # reading only: the result says whether a command was denied. Each with the
        # record it is if one was, and what it is if not.
        waiting: list[tuple[dict, list[dict]]] = []
        said_done: list[tuple[dict, list[dict]]] = []  # the same, said to be done (B-317)
        refusals = 0  # commands whose own error said they were refused
        turned_down: list[str] = []  # each step it said it refused, "tool: by whom" (B-317)
        writing = False  # the answer being written has said a word
        held = ""  # the space an answer began with, until its first word comes
        answered = False  # the last thing it did was finish an answer
        tail = 0  # how many line ends what it said last ends with
        spoke = False  # it has said a word in this turn

        def said(step: dict) -> list[dict]:
            nonlocal writing, held, answered, tail, spoke
            told = []
            delta = step.get("text_delta")
            if isinstance(delta, str) and delta:
                if not writing and not delta.strip():
                    # Space is not speech: an answer may be nothing more than the "\n"
                    # its last step carries (measured), and then it said nothing.
                    held += delta
                else:
                    if not writing:
                        # Two answers in a row are two paragraphs: one empty line.
                        delta = ("\n" * max(0, 2 - tail) if answered else "") + held + delta
                        held = ""
                    told.append({"type": "text", "text": delta})
                    ending = len(delta) - len(delta.rstrip("\n"))
                    tail = ending if ending < len(delta) else tail + ending
                    writing = spoke = True
            if step.get("state") in ("DONE", "ERROR"):
                answered, writing, held = answered or writing, False, ""
            return told

        def used(step: dict) -> list[dict]:  # noqa: C901
            nonlocal unnumbered, refusals, writing, held, answered, tail
            name, state = str(step.get("tool_name") or ""), step.get("state")
            if state not in ("ACTIVE", "DONE", "ERROR"):
                return []
            index = step.get("step_index")
            numbered = isinstance(index, int) and not isinstance(index, bool)
            if numbered and index in ended_steps:
                return []  # said again after it ended: one step is one record
            error = _dict(step.get("tool_info")).get("error")
            words_ = _text(_dict(error).get("message") or error)
            refused = state == "ERROR" and said_refused(words_)
            if refused and hooked is None:  # (natively only KOLONİ refuses: `_Hooked.refused`)
                turned_down.append(f"{name}: {BY_AGY}")
            own_name = _own_name(step, name, index, numbered, hooked)
            if bridged is not None and not refused and kolonis(own_name, bridged.offered):
                bridged_told = _bridged_step(own_name, name, state, index, numbered, bridged,
                                             ended_steps, at_work)
                if bridged_told is not None:
                    return bridged_told
            # Two tools of one name can be at work at once: the step's number tells them
            # apart. Only a step without one is paired by the tool's name.
            key: object = index if numbered else name
            writing, held, answered, tail = False, "", False, 0
            info = _dict(step.get("tool_info"))
            given = _dict(info.get("parameters"))
            step_id = at_work.get(key)

            def call(**how) -> dict:
                return {"type": "mcp_tool_call", "id": step_id, "server": "agy", "tool": name,
                        "arguments": given, **how}

            if state == "ACTIVE" and step_id is not None:
                return []  # said again while it works
            if step_id is None:
                if numbered:
                    step_id = f"agy_{index}"
                else:
                    unnumbered += 1
                    step_id = f"agy_n{unnumbered}"
            if state == "ACTIVE":
                at_work[key] = step_id
                # Nothing here holds the limit on silence off: a step that starts and is
                # never heard of again must not keep the turn waiting for ever.
                return [{"type": "item.started", "item": call()}]
            at_work.pop(key, None)
            if numbered:
                ended_steps.add(index)
            error = info.get("error")
            reason = _text(_dict(error).get("message") or (None if isinstance(error, dict)
                                                          else error))
            failed = state == "ERROR"
            output = _text(info.get("output"))
            runs, writes = name in AGY_RUNS, name in AGY_WRITES

            def closed(status: str, why: str = "") -> dict:
                return call(status=status, error={"message": why} if failed else None,
                            result={"content": [{"type": "text", "text": output}]})

            # What a step changed is read off the folder it works in; the paths it names go
            # with it, so that one outside that folder - the project itself, from a copy -
            # is on record too. (What a step that failed names is only looked for.)
            named = _named(given, *AGY_PATHS)
            let = hooked.steps.get(str(step_id)) if hooked is not None else None
            if failed and let is False:
                return []  # refused by KOLONİ before it ran: on record as KOLONİ's no
            look: dict = {"type": "file_change", "id": step_id,
                    "changes": [{"path": path} for path in dict.fromkeys(named)]}
            unsure = [closed("failed", f"{UNSURE}: {reason}" if reason else UNSURE),
                      {**look, "status": "failed"}]
            items: list[dict]
            if runs and (not failed or not self.reads):
                # A command that ran - also one that failed, when it had leave for
                # everything: there, no error is read as a refusal. Measured: the command
                # line is "CommandLine". Without one, "command"; without either, its
                # parameters as they came rather than a guess.
                line = next((given[named] for named in ("CommandLine", "command")
                             if isinstance(given.get(named), str) and given[named]), None)
                items = [{"type": "command_execution", "id": step_id,
                          "command": _text(given) if line is None else line,
                          "aggregated_output": output or reason, "exit_code": None,
                          "status": "failed" if failed else "completed"}]
                if self.reads and not failed:
                    # B-317 (R110): agy 1.4.x put a command it refused reading only down as
                    # done. Refused if its output begins with the measured words (what a
                    # command prints can hold them further on), or its result names it among
                    # the actions it denied; else it ran.
                    # shortcut: R110's stream was not kept, so this shape is a guess; capture
                    # one and keep it in tests/agy_streams.
                    denied = {**closed("denied"), "error": {"message": output or NAMED_DENIED}}
                    if not output.strip().lower().startswith(
                            ("permission check failed", "user denied permission")):
                        said_done.append((denied, items))
                        return [{"type": "item.started", "item": call(pending=items)}]
                    refusals += 1
                    turned_down.append(f"{name}: {BY_AGY}")
                    items = [denied]
            elif not failed:
                # A write leaves its own record - with what it was given, so a path
                # outside the project is named - and then the project is looked at. Natively
                # it is its change alone: one asked about is the card's (`AgentRunner._observe`).
                items = ([look] if hooked is not None else [closed("completed"), look]) \
                    if writes else [closed("completed")]
            elif not (runs or writes):
                items = [closed("failed", reason)]  # a tool that only looks, and failed
            elif not self.reads:
                items = unsure  # a write with leave for everything: never a refusal
            elif said_refused(reason):
                # Measured: without the flag, a tool that needs leave ends as an error
                # that says the permission check failed. Nothing was run or changed.
                refusals += 1 if runs else 0
                items = [closed("denied", reason)]
            elif writes:
                # How the result names a refused write was not measured: nothing more
                # will be learned about this one.
                items = unsure
            else:
                # The result may still name a command among what was denied. Until it
                # comes, the step is open - with what to put down if it never does.
                waiting.append((closed("denied", reason or NAMED_DENIED), unsure))
                return [{"type": "item.started", "item": call(pending=unsure)}]
            _unhooked(items, name, let, failed, named, hooked)
            return [{"type": "item.completed", "item": item} for item in items]

        def translate(event: dict) -> list[dict]:
            # Measured: an event's fields are in an object of the event's own name.
            kind = event.get("event")
            if kind == "init":
                model = _dict(event.get("init")).get("model")
                return [{"type": "model", "model": model}] if isinstance(model, str) and model \
                    else []
            if kind == "step_update":
                step = _dict(event.get("step_update"))
                what = step.get("step_type")
                if what == "agent_response":
                    return said(step)
                if what == "tool":
                    return used(step)
                return []
            if kind == "result":
                result = _dict(event.get("result"))
                told = _settled(result, refusals, waiting, said_done, turned_down)
                return _ended(result, told, spoke, turned_down, hooked)
            return []

        return translate


# The parts of `AgyClient._translator` that rebind none of its variables: what they change of
# its state (`ended_steps`, `at_work`, `waiting`, `said_done`, `turned_down`, `bridged`) is the
# same object it holds. (`said` and `used` rebind its counts and flags: they stay inside it.)
def _own_name(step: dict, name: str, index: object, numbered: bool,
              hooked: _Hooked | None) -> str:
    """The name a tool step is KOLONİ's tool by, if it is one."""
    if hooked is not None:
        # Natively a wrapper is KOLONİ's tool only as its hook judged it at that step
        # (B-318), never by what its stream says it was given; any other name is itself.
        return name if name != WRAPS else hooked.kolonis.get(
            f"agy_{index}", "") if numbered else ""
    # (shortcut: reading only there is no hook; that its stream gives the wrapper
    # the parameters it was given is not measured - if not, it is on record as
    # agy's own call and not counted.)
    return unwrapped(name, _dict(_dict(step.get("tool_info")).get("parameters")))


def _bridged_step(own_name: str, name: str, state: object, index: Any, numbered: bool,
                  bridged: _Bridged, ended_steps: set[int],
                  at_work: dict[object, str]) -> list[dict] | None:
    """A step of KOLONİ's tool over the bridge: what is told of it, or None if it is told as
    agy's own (one KOLONİ no longer has)."""
    if state != "ACTIVE":
        # Each one it says it made is one KOLONİ's server ran - or another server
        # of that name did it, past KOLONİ (its rules allow it by that name).
        if numbered:
            ended_steps.add(index)
        bridged.reported += 1
        if bridged.reported > bridged.served:
            raise OwnStop(NOT_KOLONIS.format(tool=own_name))
    if kolonis(own_name, bridged.own):
        # KOLONİ's own: on record where it runs, as Codex's `_heard` has it. One
        # agy refused never reached KOLONİ (its rule not taken, say): on record.
        # A wrapper whose start was told before its hook judged it is settled with
        # no record of its own (`_turn`).
        told = None if state == "ACTIVE" else at_work.pop(
            index if numbered else name, None)
        return [{"type": "item.completed", "item": {
            "type": "mcp_tool_call", "id": told, "server": "agy",
            "settled": True}}] if told else []
    return None


def _unhooked(items: list[dict], name: str, let: bool | None, failed: bool, named: list[str],
              hooked: _Hooked | None) -> None:
    """Natively, a step its hook did not ask KOLONİ about: so marked on its items."""
    if hooked is not None and not let and name not in AGY_INERT:
        for item in items:
            item.update(unhooked=name or "a tool", refused=let is False,
                        unread=hooked.unread)
            if not failed and item["type"] == "command_execution":
                item["unasked"] = True
            if not failed and item["type"] == "file_change":
                item["unasked"] = named


def _settled(result: dict, refusals: int, waiting: list[tuple[dict, list[dict]]],
             said_done: list[tuple[dict, list[dict]]], turned_down: list[str]) -> list[dict]:
    """The commands that waited for the result: refused if it names enough
    commands among `denied_actions` to cover them all, else not known to have
    done nothing."""
    denied = result.get("denied_actions")
    named = sum(
        1 for action in (denied if isinstance(denied, list) else [])
        if _dict(action).get("action") == "command"
    )
    left, items = named - refusals, []
    # Those that ended in an error first, as before B-317; those said to be done get
    # what is left.
    for held in (waiting, said_done):
        refused = left >= len(held)
        left -= len(held) if refused else 0
        items += [item for denied_item, other in held
                  for item in ([denied_item] if refused else other)]
        turned_down.extend(f"{item['tool']}: {BY_AGY}"
                           for item, _other in (held if refused else []))
        held.clear()
    return [{"type": "item.completed", "item": item} for item in items]


def _ended(result: dict, told: list[dict], spoke: bool, turned_down: list[str],
           hooked: _Hooked | None) -> list[dict]:
    """The turn's end: `told`, what `_settled` made of the commands that waited for it."""
    status = result.get("status")
    if status != "SUCCESS":
        error = result.get("error")
        reason = _text(_dict(error).get("message") or (None if isinstance(error, dict)
                                                      else error))
        if status != "ERROR":
            # An ending KOLONİ does not know is not called a success.
            reason = reason or f"it ended with the status {_text(status) or 'unknown'}"
        return [*told, {"type": "error", "message": reason or "it failed"}]
    response = result.get("response")
    if not spoke and isinstance(response, str) and response.strip():
        # No word came in deltas: the answer is the one the result carries.
        told.append({"type": "item.completed",
                     "item": {"type": "agent_message", "text": response}})
    elif not spoke and (refused := [*turned_down, *(hooked.refused if hooked else [])]):
        # One that is empty after a refusal is not left silent (B-317): KOLONİ says, in
        # its own name, which tool was refused and by whom - with its own reason where
        # it refused, never agy's words (they hold the command line, a token in it).
        steps = "; ".join(
            "`" + one.strip().splitlines()[0][:300].rstrip(":").replace("`", "'") + "`"
            for one in refused[-3:])
        told.append({"type": "item.completed", "item": {
            "type": "agent_message", "text": NO_ANSWER.format(steps=steps)}})
    usage = _dict(result.get("usage"))
    # Measured: its usage has `cache_read_tokens` - passed on where it says so.
    cached = ({"cached_input_tokens": usage["cache_read_tokens"]}
              if "cache_read_tokens" in usage else {})
    return [*told, {"type": "turn.completed", "usage": {
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"), **cached}}]


def _not_searching(event: dict) -> bool:
    """Whether an event of a search's stream shows anything but the search: every step but
    those measured to be no tool (`user_input`, `agent_response` - unless they carry a tool)
    and a `search_web` tool step, and any event but init, step_update and result."""
    kind = event.get("event")
    if kind != "step_update":
        return kind not in ("init", "result")
    step = _dict(event.get("step_update"))
    if "tool_name" not in step and "tool_info" not in step:
        return step.get("step_type") not in ("user_input", "agent_response")
    names = {step.get("tool_name"), _dict(step.get("tool_info")).get("name")} - {None}
    return step.get("step_type") != "tool" or names != {"search_web"}


class AgySearch(_Searches, AgyClient):
    """agy asked to search the web (slice 20b). Measured on 11 Oct 2026: reading only, it
    ran its `search_web` tool without being asked - but that tool's output is not in its
    stream, so what it found is only in its answer; and reading only, its other reading
    tools (files, addresses, a browser) can run unasked too. So its answer counts only
    where the stream shows a search that was done and nothing else at all, and the run is
    stopped at the first thing that is not a search (`_not_searching`). Used only where
    the project lets agy search (`search_agy`)."""

    held_to_search = False  # `app.web.cli_search`: asked only where the project says so

    def __init__(self, executable=None, model=None, timeout: float = 900.0, **more):
        super().__init__(executable, model, timeout, reads=True, **more)  # never the flag

    def _arguments(self, workdir: Path) -> list[str]:
        return self._agy_arguments()

    def _stdin(self, prompt: str) -> str:
        return _user_line(prompt)

    def _complete(self, stdout: str) -> bool:
        # Stopped at once at anything that is not a search: it cannot be held to its search
        # tool, and what another tool does (read a file, open a page) is not waited out.
        return any(map(_not_searching, _events(stdout)))

    def _searched(self, stdout: str) -> bool:
        events = _events(stdout)
        return not any(map(_not_searching, events)) and any(
            _dict(event.get("step_update")).get("state") == "DONE"
            and _dict(event.get("step_update")).get("step_type") == "tool" for event in events
        )

    def _read(self, stdout: str) -> tuple[object, int | None, int | None]:
        result = next((_dict(event.get("result")) for event in reversed(_events(stdout))
                       if event.get("event") == "result"), {})
        return (result.get("response") if result.get("status") == "SUCCESS" else None), None, None
