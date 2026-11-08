"""Codex in native mode: it works in the project with its own tools.

KOLONİ does not run Codex's file and shell tools here. Codex runs as its app-server
(slice 89a) and asks before each command and patch; KOLONİ answers as it answers
Claude Code's prompts (`AgentRunner._approve`). It watches Codex's events and hands
what it sees to the agent runner, which records it, and it gives Codex one MCP server
with KOLONİ's collaboration tools (opening sub-agents, creating roles, asking the user).
"""

import asyncio
import contextlib
import hashlib
import itertools
import json
import logging
import os
import re
import shlex
import shutil
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import replace
from pathlib import Path, PureWindowsPath

from app import mcp_bridge
from app.commands import _CLIMBS, only_looks
from app.ledger import TESTS
from app.model_cli import (
    RESULT_TEXT,
    ClaudeCliClient,
    CliStepClient,
    CodexCliClient,
    Exited,
    _brief,
    _cache_tokens,
    _dict,
    _events,
    _input_tokens,
    classed,
    claude_content,
    codex_model,
    codex_skills_off,
    complaints,
    conversation,
    image_copies,
    levels_of,
    own_error,
)
from app.model_client import ModelUnavailable, OwnStop, count_of
from app.model_session import (
    COPILOT_PREFIX,
    PREFIX,
    SERVER,
    TOOL_WAIT_MS,
    CallTool,
    ClaudeSessionClient,
    CopilotSessionClient,
    QoderSessionClient,
    SessionResult,
    ToolServer,
    _sum,
    bridge_file,
    build_session_prompt,
    copilot_counts,
    why_picked,
)
from app.raw import feed
from app.skills import RUNS_AS_IT_LOADS, front
from app.views import DEVICES
from app.workspace import SCRATCH

log = logging.getLogger(__name__)

# Measured on Windows (6 Oct 2026): Codex's sandbox started its shell in the root of the
# drive when it could not enter the project folder it was given, without saying so.
WHERE = (
    'The project folder is "{root}". Your shell should start there; if it starts anywhere '
    "else, go there first, and keep every path you read or write inside it."
)

NATIVE_RULES = """You are working as an agent inside KOLONİ, a workspace where several agents
work for one user. The input is a JSON document with "instructions" (who you are and how
to work) and "conversation" (everything so far, oldest first). Carry on from the end of
the conversation: do what the last user message asks.

Do the work in this project folder with your own tools (shell, file edits and the rest),
as you normally would. KOLONİ shows the user what you do as you do it.

The "koloni" MCP server gives you what your own tools cannot:
- spawn_agent hands a separate part of the job to another agent and returns its report;
- ask_user asks the user a question and waits for the answer;
- create_role adds a role agents can be opened in.
Use them when the instructions call for it. Where the instructions or the conversation
mention tools such as read_file, edit_file or run_command, use your own equivalents.

When the work is done, say briefly what you did and what you did not verify."""
# B-301: after the rules, for a CLI KOLONİ started read-only for its role ("read_only" withheld).
READ_ONLY_RULES = """KOLONİ started you read-only for this role, whatever is said above: your own
file edits are refused, and so are your own commands unless your role runs commands (then
they run where nothing can be written). Read files with the koloni server's read_file,
list_dir and search, and write a file only with its write_file or edit_file, where your role
has them. A refused command of your own is no reason to stop: read with those tools."""

# Called for everything Codex does with tools of its own: the event's phase
# ("started" or "completed") and the item as Codex reported it.
OnItem = Callable[[str, dict], Awaitable[None]]
# 89d: words to a CLI while its turn runs; whether it took them (not that it read them).
Steer = Callable[[str], Awaitable[bool]]
# Handed the run's steer once its turn is under way, and None when it no longer is.
OnLive = Callable[[Steer | None], None]
STEER_SECONDS = 5.0
# B-197: why KOLONİ declined a request of Codex's, steered into its turn (as `AGENT_STEERED`).
DECLINED_WHY = ("KOLONİ declined that request of yours: {why}\n\n"
                "(KOLONİ's words - not the user's.)")
# K-48: a write its read-only sandbox refused, by what PowerShell says of it - Codex calls the
# command completed, exit code 0 (a non-terminating error), so it is told by its output.
# Matched on its words with their spaces made one (PowerShell wraps its error to the console's
# width); never of a command that only reads or lists (`only_looks`: a refused read says the
# same), nor of a test run (`ledger.TESTS`: its result is its own, counted as one).
# shortcut: this one message, measured with codex 0.164.0 on Windows (`Set-Content`); a command
# that only prints such a line (`python -c` reading a log) is marked too, and other shells'
# words are not known - add them once measured.
WRITE_REFUSED = re.compile(r"Access to the path .{1,500}? is denied")
WRITE_BLOCKED = "blocked: its read-only sandbox refused a write"
# B-357: a command of Codex's own that it was let run and then says nothing of (no output, no
# end) for this long never started; its turn ends.
# shortcut: its output is told by `item/commandExecution/outputDelta`, as its schema names it,
# not measured live - a command quiet for half a minute ends the turn too; measure it.
NEVER_STARTED_SECONDS = 30.0
# B-357: no command or patch of its own is at work longer: KOLONİ's own commands' longest
# (MAX_TIMEOUT) and a minute. One that is ends its turn, failed - none keeps it open for good.
CALL_SECONDS = 660.0
NEVER_STARTED = "never started: nothing came of it {seconds:g} seconds after it was allowed"
RAN_TOO_LONG = "ended by KOLONİ: still at work after {seconds:g} seconds"
TOOL_WAIT_SECONDS = 24 * 60 * 60
# 93-B6: a report that did not keep to its schema is asked for once more, with what was
# wrong - the schema itself is not written out again (it is on its command line).
REPORT_AGAIN = ("Your report did not keep to its schema: {errors}. Hand it in again with "
                "StructuredOutput, corrected; do no other work.")
# shortcut: Claude Code's result subtype for "its own schema retries ran out", as the Agent
# SDK names it, not measured; a report is then its text, as without a schema.
SCHEMA_GAVE_UP = "error_max_structured_output_retries"

# What Codex's app-server asks before it acts (measured on 0.163.0, 24 Oct 2026; the
# schema of 0.164.0 says the same): the two it asks about everything with, at "untrusted".
RUN_ASKED = "item/commandExecution/requestApproval"
PATCH_ASKED = "item/fileChange/requestApproval"
# The no of a request whose answer the schema types; any other is answered with an error.
# shortcut: how Codex takes an error answer (does its turn go on?) is not measured; measure
# item/tool/requestUserInput and item/permissions/requestApproval live and answer as typed.
DECLINED = {
    RUN_ASKED: {"decision": "decline"}, PATCH_ASKED: {"decision": "decline"},
    "mcpServer/elicitation/request": {"action": "decline"},
    "execCommandApproval": {"decision": "denied"}, "applyPatchApproval": {"decision": "denied"},
}
# Its own item types, as `codex exec --json` named them: what `_work` and the agent read.
EXEC_ITEMS = {
    "agentMessage": "agent_message", "commandExecution": "command_execution",
    "fileChange": "file_change", "mcpToolCall": "mcp_tool_call", "webSearch": "web_search",
}


# How Codex runs a command on Windows (measured on 0.164.0, 24 Oct 2026): this line around
# it, the command between single quotes, PowerShell's way (a quote in it written twice) -
# or, one that holds a single quote, between double quotes (seen live, 24 Oct: B-45).
# shortcut: one in double quotes with a backtick escape stays the whole line (a shell: no
# rule covers it, every check sees all of it); read PowerShell's escapes if Codex sends one.
POWERSHELL_LINE = re.compile(
    r'"?[A-Za-z]:\\[^"]*\\(?:powershell|pwsh)\.exe"? -Command '
    r'(?:\'(.*)\'|"((?:[^"`]|"")*)")', re.S | re.I)
# B-307 (seen live, 29 Oct): the same argv joined as a POSIX shell's words instead - the path's
# `\` written `\\`, a `!` or `$` in single quotes (`-g '"'!.git'"'`) - with `-NoProfile` too.
POSIX_JOINED = re.compile(r'"[A-Za-z]:\\\\')
SHELL_EXE = re.compile(r"[A-Za-z]:\\.*\\(?:powershell|pwsh)\.exe", re.S | re.I)


def _unwrapped(command: str) -> str:
    """The command Codex runs, without the PowerShell line it runs it in: what the
    allow list, the deleting and secret rules and the card judge."""
    if POSIX_JOINED.match(command):
        with contextlib.suppress(ValueError):  # (unbalanced quotes: the whole line)
            words = shlex.split(command)
            if (len(words) >= 3 and SHELL_EXE.fullmatch(words[0])
                    and words[-2].lower() == "-command"
                    and all(w.lower() in ("-noprofile", "-nologo", "-noninteractive")
                            for w in words[1:-2])):
                return words[-1]
        return command
    found = POWERSHELL_LINE.fullmatch(command)
    if not found:
        return command
    return found[1].replace("''", "'") if found[1] is not None else found[2].replace('""', '"')


def _files(changes: object) -> list[tuple[str, str, object]]:
    """(path, "add" | "update" | "delete" | "move from <path>", diff) of each file a patch
    of Codex's touches: a file it moves at both of its paths."""
    found = []
    for change in changes if isinstance(changes, list) else []:
        change = _dict(change)
        kind = change.get("kind")
        how = str(_dict(kind).get("type") if isinstance(kind, dict) else kind)
        path = str(change.get("path") or "")
        found.append((path, how, change.get("diff")))
        if isinstance(kind, dict) and kind.get("move_path"):
            found.append((str(kind["move_path"]), f"move from {path}", None))
    return found


# R175 (live): Codex sent its patch as a command, `apply_patch <<'EOF'` with the patch in a
# heredoc, and it came as a command card at Auto-edit. Only the whole command is one: the
# delimiter quoted (nothing in it is expanded), no line of the patch ending the heredoc early,
# nothing before or after it, and every path in the folder it runs in (none whole, none up).
# B-389 (R184, live): Copilot native in PowerShell sent its patch as a single-quoted here-string
# piped to apply_patch (`HERE_STRING_PATCH`), held to the same rules: nothing in it expanded, no
# line of the patch ending it early, nothing before or after it, every path in the folder.
# shortcut: whether its shell runs it is not measured - PowerShell, Codex's shell on Windows, has
# no heredoc: such a run fails, writes nothing, and is on record as a failed patch.
# (Review: no CR anywhere - Git Bash drops each one, so `EO\rF` would end the heredoc there and
# run what follows - and only ASCII blanks: what a shell might read as one is not judged here.)
HEREDOC_PATCH = re.compile(
    r"apply_patch <<(['\"])([A-Za-z_]\w*)\1\n(\*\*\* Begin Patch\n.*\n\*\*\* End Patch)\n\2"
    r"[ \t\n]*", re.S | re.A)
# (`@'`, not `@"`: a double-quoted one expands `$(...)`. It ends at `'@` starting a line.)
# shortcut: only where its shell is said to be PowerShell (Copilot's shellType) - Codex says no
# shell with a command, so one of its here-strings stays a command card; judge it so too where
# `_unwrapped` took off a `powershell -Command`, once Codex is seen sending one.
HERE_STRING_PATCH = re.compile(
    r"@'\n(\*\*\* Begin Patch\n.*\n\*\*\* End Patch)\n'@[ \t]*\|[ \t]*apply_patch[ \t\n]*",
    re.S | re.A)
# A line PowerShell might end the here-string at: it reads U+2018-U+201B as single quotes too;
# (review) any other non-ASCII mark before an @, after blanks or invisible marks, is held so too.
HERE_STRING_END = re.compile(r"[\s\u200b-\u200f\u2028-\u202e\u2060-\u2064\ufeff]*"
                             r"(?:'|[^\x00-\x7f])[@\ufe6b\uff20]")
PATCH_FILE = re.compile(r"\*\*\* (Add|Update|Delete) File: (.+)")
# (Review) A control character a console would act on - Ctrl+C ending the line it is in, Esc -
# never reaches a shell as a patch: CR, NUL and the rest of C0, and DEL.
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
# What `_decide` asks its runner (`call_tool`) of such a command: true where it may be a patch.
PATCH_MAY_RUN = "patch_may_run"


def _odd_path(text: str) -> bool:
    """Whether a patch's path is any but a plain one in the folder it runs in: whole or up; a
    blank only Unicode calls one at an end (the card would name another file than is written);
    a stream (`b.py:x`) or a device (NUL, con.txt); a name Windows cuts (`.git.`, `.git `: its
    last dots and blanks go); a home (`~`). Read as Windows reads it on every system: off
    Windows a backslash is a name's own character, and a name holding one is no plain one there."""
    named = PureWindowsPath(text.strip(" \t"))
    return text.strip() != text.strip(" \t") or bool(named.anchor) or not named.parts or any(
        part == ".." or ":" in part or part.startswith("~") or part[-1] == "."
        or part[-1].isspace() or DEVICES.fullmatch(part) is not None for part in named.parts)


def _heredoc_patch(command: str, cwd: str, powershell: bool = False) -> list[dict] | None:
    """The changes of an `apply_patch` heredoc command, as Codex says a patch's (`_files`
    reads them), its paths taken from `cwd`; None where the command is anything more.
    `powershell`: its shell is PowerShell, and the form is its here-string (`HERE_STRING_PATCH`)
    - in bash that form's quote would end at the patch's first `'`, and the rest run."""
    if powershell:
        # B-389: PowerShell reads CRLF as one line break, as LF, so the lines judged here are
        # those it parses; a CR left, or a break only Python's splitlines knows, is refused.
        command = command.replace("\r\n", "\n")
        found = None if CONTROL.search(command) else HERE_STRING_PATCH.fullmatch(
            command.strip(" \t\n"))
        body = found[1] if found else ""
        lines = body.split("\n")[1:-1]
        if found is None or body.splitlines() != body.split("\n") or any(
                HERE_STRING_END.match(line) for line in lines):
            return None  # (the here-string would end there, and what follows run as commands)
    else:
        found = None if CONTROL.search(command) else HEREDOC_PATCH.fullmatch(
            command.strip(" \t\n"))
        if found is None:
            return None
        lines = found[3].split("\n")[1:-1]
        if found[2] in lines:
            return None  # (the heredoc would end there, and what follows run as commands)
    changes: list[dict] = []
    for line in lines:
        header = PATCH_FILE.fullmatch(line)
        moved = line.startswith("*** Move to: ") and bool(changes) and (
            changes[-1]["kind"]["type"] == "update")
        text = header[2] if header else line[13:] if moved else ""
        named = Path(text.strip(" \t"))
        if (header or moved) and _odd_path(text):
            return None  # (a path out of the folder it runs in stays a command's)
        if header:
            changes.append({"path": str(Path(cwd) / named),
                            "kind": {"type": header[1].lower(), "move_path": None}, "diff": ""})
        elif not changes:
            return None
        elif moved:
            changes[-1]["kind"]["move_path"] = str(Path(cwd) / named)
        elif line.lstrip().startswith("***") or changes[-1]["kind"]["type"] == "delete" or (
                changes[-1]["kind"]["type"] == "add" and not line.startswith("+")):
            return None
        else:  # (a new file's lines without their "+": what it will hold, as Codex says it)
            new = changes[-1]["kind"]["type"] == "add"
            changes[-1]["diff"] += (line[1:] if new else line) + "\n"
    return changes or None


def _patch_questions(changes: object, given: dict) -> list[tuple[str, dict]]:
    """Each file of a patch asked as Claude Code's prompts are: a new one as its Write (its
    diff is what it will hold), any other as its Edit."""
    return [("Write", {"file_path": path, "content": diff, "kind": how, **given})
            if how == "add" and isinstance(diff, str)
            else ("Edit", {"file_path": path, "kind": how, "diff": diff, **given})
            for path, how, diff in _files(changes)]


class _Asked:
    """What a run of Codex's app-server asked KOLONİ: the item ids it asked about; each
    patch's changes, as it last said them, until it asks; each patch's files that were
    asked about (path -> the id each was asked under); the requests already answered
    (item id, approval id); the commands that were patches (`_heredoc_patch`), by item id;
    how many of its requests were declined (`CodexSessionClient._decide`)."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root
        self.items: set[str] = set()
        self.patches: dict[str, object] = {}
        self.paths: dict[str, dict[str, str]] = {}
        self.answered: set[tuple[str, object]] = set()
        self.heredocs: dict[str, list[dict]] = {}
        self.declined = 0


def _note_patch(method: object, params: dict, item: dict, asked: _Asked) -> None:
    # A patch's changes as Codex last said them (`CodexNativeClient._converse`).
    if method == "item/started" and item.get("type") == "fileChange":
        asked.patches[str(item.get("id"))] = item.get("changes")
    if method == "item/fileChange/patchUpdated":
        # What is asked about is the patch as it now stands.
        asked.patches[str(params.get("itemId"))] = params.get("changes")


def _note_reply(request: dict, params: dict, reply: dict, busy: set[str],
                allowed: dict[str, float]) -> None:
    # KOLONİ's answer to a request of Codex's, kept before it is sent
    # (`CodexNativeClient._converse`).
    if _dict(reply.get("result")).get("decision") == "decline":
        busy.discard(str(params.get("itemId")))  # it may never say it is done
    if request.get("method") == RUN_ASKED and _dict(
            reply.get("result")).get("decision") == "accept":
        # (Before it is sent: its end may be read before this call goes on.)
        allowed[str(params.get("itemId"))] = time.monotonic()


def _overdue(busy: set[str], asking: set[str], since: dict[str, float],
             allowed: dict[str, float], at: float) -> tuple[str | None, str | None]:
    # B-357 (`CodexNativeClient._converse`): a command let run that never started, and the
    # first of its own at work for too long.
    at_work = [key for key in busy - asking if not key.startswith("asked ")]
    for key in at_work:
        since.setdefault(key, at)
    late = next((key for key, yes in allowed.items()
                 if at - yes > NEVER_STARTED_SECONDS), None)
    over = late or next((key for key in at_work if at - since[key] > CALL_SECONDS),
                        None)
    return late, over


def _as_exec(method: str, params: dict, asked: _Asked, read_only: bool = False) -> list[dict]:
    """One notification of Codex's app-server as the events `codex exec --json` printed.
    A command or a patch is on record from when it is asked about (`AgentRunner._approve`):
    its start is only that it is at work. One it never asked about is `unasked`; of a
    patch, `parts` are the ids its files were asked about under (`CodexNativeClient._decide`)
    and `unasked` the paths that were not. `read_only`: in its read-only sandbox, a command
    whose write it refused is `blocked` (K-48)."""
    phase = {"item/started": "started", "item/completed": "completed"}.get(method)
    item = _dict(params.get("item"))
    if item.get("type") == "imageView" and phase == "completed":
        # B-347: an image it looked at with its own tool (R128: {"type":"imageView","path":…}),
        # on record as a tool of its own (`AgentRunner._own_look`). shortcut: only its end is
        # read, and its id as any item's - neither was seen; read its start if one comes.
        return [{"type": "item.completed", "item": {
            "type": "mcp_tool_call", "id": str(item.get("id") or ""), "server": "codex",
            "tool": "imageView", "arguments": {"path": item.get("path")}, "status": "completed"}}]
    what = EXEC_ITEMS.get(str(item.get("type")))
    if phase is None or what is None:
        return []  # its reasoning, deltas and the rest: as `codex exec` was read, nothing
    item_id = str(item.get("id") or "")
    # A patch it ran as a command (`_heredoc_patch`): on record as the patch it was asked as.
    heredoc = asked.heredocs.get(item_id) if what == "command_execution" else None
    if heredoc is not None:
        what = "file_change"
    if phase == "started" and what in ("command_execution", "file_change"):
        return [{"type": "busy", "id": item_id, "on": True}]
    # What was declined did not happen; it is on record as KOLONİ's no.
    status = {"inProgress": "in_progress", "declined": "failed"}.get(
        str(item.get("status")), item.get("status"))
    if heredoc is not None and item.get("exitCode") not in (0, None):
        status = "failed"
    told = {**item, "type": what, "id": item_id, "status": status}
    if what == "command_execution":
        told |= {"command": _unwrapped(str(item.get("command") or "")),
                 "aggregated_output": item.get("aggregatedOutput"),
                 "exit_code": item.get("exitCode"), "unasked": item_id not in asked.items}
        command = told["command"]
        if read_only and WRITE_REFUSED.search(" ".join(str(
                item.get("aggregatedOutput") or "").split())) and not (
                only_looks(command) or TESTS.search(command)):
            told["blocked"] = WRITE_BLOCKED
    if what == "file_change":
        files = _files(item.get("changes") if heredoc is None else heredoc)
        ids = asked.paths.get(item_id, {})
        declined = item.get("status") == "declined"  # (then nothing of it was written)
        return [{"type": "busy", "id": item_id, "on": False}, {"type": "item.completed", "item": {
            "type": what, "id": item_id, "status": status, "declined": declined,
            "changes": [{"path": path, "kind": how} for path, how, _diff in files],
            "parts": [ids[path] for path, _how, _diff in files if path in ids],
            "unasked": [] if declined else [
                path for path, _how, _diff in files if path not in ids]}}]
    return [{"type": f"item.{phase}", "item": told}]


def _no_shell(withheld: tuple[str, ...]) -> bool:
    """B-301: whether Codex is started without a shell of its own - read-only, for a role that
    may not run commands."""
    return {"read_only", "run"} <= set(withheld)


NO_SHELL_RAN = ("Codex ran a command of its own though it was started without its shell (its "
                "role may not run commands), so the run is stopped")


def _not_as_asked(thread: dict, root: Path, also: tuple[str, ...],
                  read_only: bool = False) -> str | None:
    """Why the thread Codex started is not the one KOLONİ asked for (the user's own
    config.toml can make more of it), or None. `read_only`: one in its read-only sandbox."""
    reviewer, sandbox = thread.get("approvalsReviewer"), _dict(thread.get("sandbox"))
    if thread.get("approvalPolicy") != "untrusted":
        return (f"its thread would ask {json.dumps(thread.get('approvalPolicy'))}, not "
                "before every command and patch")
    if reviewer != "user":
        return f"its requests would go to {json.dumps(reviewer)}, not to KOLONİ"
    # shortcut: "readOnly" is the app-server's tag as its protocol names it, not seen from the
    # real CLI; measure thread/start's answer with "read-only" (K-cli-surface) before relying on it.
    wanted, said = ("readOnly", "read-only") if read_only else ("workspaceWrite", "workspace-write")
    if sandbox.get("type") != wanted:
        return f"its sandbox would be {json.dumps(sandbox.get('type'))}, not {said}"
    if sandbox.get("networkAccess"):
        return "its sandbox would let its commands use the network"
    given = {Path(one).resolve() for one in (root, *also)}
    wider = [str(one) for one in sandbox.get("writableRoots") or []
             if Path(str(one)).resolve() not in given]
    return f"its sandbox would also make {wider[0]} writable" if wider else None


def _filled(used: object, window: object) -> dict | None:
    """89j: how full its context is, as its own CLI counts it; None where either is no count."""
    used, window = count_of(used), count_of(window)
    if used is None or not window:
        return None
    return {"type": "live", "context": {"used": used, "window": window}}


# shortcut: a plan's first 30 steps, 200 characters each; show more if a longer one is seen.
PLAN_STEPS, PLAN_WORDS = 30, 200
PLAN_STATUSES = ("pending", "inProgress", "completed")


def _plan(steps: object) -> dict:
    """89j: Codex's plan as it sent it (`turn/plan/updated`): each step's words - data, never
    orders - and how far it is."""
    # shortcut: its fields are read off 0.164.0's binary, never seen live (its model did not
    # plan in the measured turn); check them when a turn with a plan is seen.
    told = [_dict(one) for one in steps][:PLAN_STEPS] if isinstance(steps, list) else []
    return {"type": "live", "plan": [{
        "step": str(one.get("step") or "")[:PLAN_WORDS],
        "status": one["status"] if one.get("status") in PLAN_STATUSES else "pending",
    } for one in told]}


def schema_errors(value: object, schema: dict, at: str = "report") -> list[str]:
    """Where `value` does not keep to `schema`, each said in a few words.
    shortcut: only the words a report schema uses (type object / array / string / boolean,
    enum, required; no property beyond those named); widen it for a schema that uses more."""
    if "enum" in schema:
        return [] if value in schema["enum"] else [
            f"{at} is not one of {', '.join(schema['enum'])}"]
    kind = schema.get("type")
    if kind == "string":
        return [] if isinstance(value, str) else [f"{at} is not a string"]
    if kind == "boolean":
        return [] if isinstance(value, bool) else [f"{at} is not true or false"]
    if kind == "array":
        if not isinstance(value, list):
            return [f"{at} is not a list"]
        return [error for number, one in enumerate(value)
                for error in schema_errors(one, schema["items"], f"{at}[{number}]")]
    if not isinstance(value, dict):
        return [f"{at} is not an object"]
    known = schema.get("properties", {})
    return [*(f"{at}.{name} is missing" for name in schema.get("required", ())
              if name not in value),
            *(f"{at}.{name} is not in the schema" for name in value if name not in known),
            *(error for name, one in value.items() if name in known
              for error in schema_errors(one, known[name], f"{at}.{name}"))]


def how_it_ended(label: str, code: int | None, reason: str) -> str:
    """What is said of a CLI that ended without finishing its turn. An exit code nobody
    knows (it could not be waited for) is not called 0."""
    if code is None:
        return (f"{label} ended, exit code not known: {reason}" if reason
                else f"{label} ended without finishing (exit code not known)")
    return (f"{label} exited with code {code}: {reason}" if reason
            else f"{label} ended without finishing (exit code {code})")


class CodexNativeClient(CliStepClient):
    command = "codex"
    label = "Codex"
    native = True
    efforts = levels_of("codex_cli")
    # Whether the CLI asks KOLONİ for leave before a tool of its own acts. Codex does, over
    # its app-server (`_converse`).
    asks = True
    # Whether it looks at files only by running commands (Codex: measured on Windows, 24 Oct
    # 2026): asking first or not, it is of no use to a role that may not run them.
    looks_by_running = True
    # Whether the CLI itself refuses whatever would change something, so that it only
    # reads; and whether this kind of provider can be set to run that way.
    reads = False
    can_read_only = False
    # B-301: whether it can be started read-only for a role not allowed both to write and run
    # (`team.reads_only`) - its own writes refused, KOLONİ's write tools over the bridge - and
    # whether its commands then run in a sandbox that writes nothing (Codex's "read-only").
    starts_read_only = True
    read_only_commands = True
    # Whether it is given KOLONİ's tools to work with other agents and the user.
    collaborates = True
    # Whether a sub-agent run by it is started in a working copy of the project
    # (`app.copies`). Measured for Codex and Claude Code (9 Oct 2026); native agy too, not
    # measured (`app.model_agy`).
    own_copy = True
    rules = NATIVE_RULES
    # B-301: why the run stops where a command of its own comes though it has no shell.
    no_shell_ran = NO_SHELL_RAN

    @property
    def resumes(self) -> bool:
        """27: whether its session is kept for the agent's next turn to go on in (`run_native`);
        else KOLONİ compacts what each turn is sent (`AgentRunner._idle_after`)."""
        return False

    # Its own sign-in's secret variables (codex-rs/login/src/auth/manager.rs, Apache-2.0).
    # shortcut: a model provider of the user's config.toml signs in by a variable it names
    # (env_key), Bedrock by AWS's: those are held back; keep them once one is used.
    logins: frozenset[str] | None = frozenset({
        "OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN"})
    _offered: list[str] = []

    def _translator(self) -> Callable[[dict], list[dict]]:
        """Turns one line of this CLI's stream into the events read below (Codex's own).
        A new one for every run: a CLI whose stream needs memory keeps it there."""
        return lambda event: [event]

    def _native_env(self, workdir: Path) -> dict[str, str]:
        return {}

    def _settings_model(self) -> str | None:
        # Codex's settings say which model Codex uses, not the CLIs built on this class.
        return codex_model(self._env) if self.command == "codex" else None

    async def _startable(self, command: list[str], shim: bool) -> None:
        # Codex's own skills and its line; not the CLIs built on this class. (The folder
        # it will work in is not known yet: a longer path there is said at its start.)
        if self.command == "codex":
            await asyncio.to_thread(
                self._would_start, command, shim,
                lambda folder: self._native_arguments(folder, folder / "b.json"),
            )

    def _hide(self, text: str) -> str:
        """What the CLI said, without anything that must not be repeated (a key).
        Applied to the whole text, before it is cut short for an error message."""
        return text

    async def stream_step(self, model_id, messages, tools, on_delta, on_thinking=None,
                          effort=None):
        raise OwnStop("Codex runs here with its own tools, not step by step")

    def talker(self) -> CliStepClient:
        """The same Codex, one step at a time with its own tools off: how it speaks in
        a discussion, where nobody may change anything."""
        return CodexCliClient(
            self._executable, self._model, self._timeout, self._which, self._launcher,
            self._env, self.server, self._homes, self.home,
        )

    def _native_arguments(
        self, root: Path, bridge_config: Path, withheld: tuple[str, ...] = (),
        linked: tuple[str, ...] = (), also: tuple[str, ...] = (),
    ) -> list[str]:
        # (Not `linked`: a copy's dependency folders, which would be made writable.)
        for path in (sys.executable, mcp_bridge.__file__, str(bridge_config)):
            if "'" in str(path):
                raise OwnStop(
                    f"a path with an apostrophe ({str(path)[:60]}) cannot be given to Codex"
                )
        # Its folder, model and the folders it also works in go in thread/start and
        # turn/start (`_converse`). The user's own MCP servers are off: a tool of theirs is
        # not one Codex asks KOLONİ about (as `limits._AppServer` has them).
        theirs = [name for name in CodexCliClient(env=self._env, server=self.server)
                  ._own_mcp_servers()
                  if name != SERVER]
        return [
            *(one for name in theirs for one in ("-c", f"mcp_servers.{name}.enabled=false")),
            # One more MCP server: KOLONİ's collaboration tools.
            "-c", f"mcp_servers.{SERVER}.command='{sys.executable}'",
            "-c", f"mcp_servers.{SERVER}.args=['{mcp_bridge.__file__}','{bridge_config}']",
            # Whatever the user's own config says about a server of this name.
            "-c", f"mcp_servers.{SERVER}.enabled=true",
            # An answer from the user, or a whole sub-agent, can take a long time.
            "-c", f"mcp_servers.{SERVER}.tool_timeout_sec={TOOL_WAIT_SECONDS}",
            # B-304: none of its own sub-agents, as step by step (`CodexCliClient.DISABLED`): they
            # work past KOLONİ's records, and each would start a bridge of its own, which the
            # tool server turns away. shortcut: the key as `features.apps` below, not measured
            # live; measure it (K-cli-surface).
            "-c", "features.multi_agent=false",
            # The user's own skills are not an agent of KOLONİ's to use - nor its plugins' (B-312:
            # a Debugger read a plugin's SKILL.md), as Claude Code's `--setting-sources` and
            # step by step (`DISABLED`). shortcut: `plugins` among Codex 0.164's feature names,
            # not measured natively; measure it (K-cli-surface).
            *codex_skills_off(self._env), "-c", "features.plugins=false",
            # Slice 61: web_search switched off on the Tools page, its own search is too.
            # shortcut: the config key as Codex documents it, not measured with the real CLI;
            # measure it (K-cli-surface) before relying on it.
            *(("-c", "web_search='disabled'") if "search" in withheld else ()),
            # B-185: and its apps (connectors: `codex_apps__github_fetch` read GitHub with no
            # card) with either of KOLONİ's web tools off.
            # shortcut: the `apps` feature key only seen among Codex 0.164's feature names (its
            # binary's strings), not in --help nor measured live; an unknown key could refuse
            # to start or be ignored - measure it (K-cli-surface) before relying on it.
            *(("-c", "features.apps=false") if {"search", "fetch"} & set(withheld) else ()),
            # B-301: read-only for a role that may not run commands, no shell of its own at all:
            # its read-only sandbox keeps writes, not reads, and its known-safe commands run
            # unasked ("untrusted") - a .env, the home folder. It reads with KOLONİ's tools.
            # shortcut: Codex 0.164 takes both names (`--disable shell_tool` / `unified_exec`
            # measured), but that they take its shell away is not; a command that comes all
            # the same ends the turn (`_converse`). Measure it live (K-cli-surface).
            *(("-c", "features.shell_tool=false", "-c", "features.unified_exec=false")
              if _no_shell(withheld) else ()),
            *self._server_settings(),
            # Before the subcommand: it takes the settings given to `codex` (`limits`).
            "app-server",
        ]

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
        on_live: OnLive | None = None,
        tests_at_stop: bool = False,
        inside: dict[str, dict] | None = None,
        report_schema: dict | None = None,
        on_end: Callable[[Callable[[BaseException], None]], None] | None = None,
        session: dict | None = None,
        level: str | None = None,
        keep: bool = False,
    ) -> SessionResult:
        """`keep`: its session is kept for a later turn (27 / 93-C3: Claude Code signed in for
        KOLONİ alone) - and the result says it; else it is kept nowhere, as before. `session`:
        what the agent's last run of it left (`SessionResult.session`), which it goes on in
        with only what is new where it is started under the same now (`_under`, with the
        permission `level`).
        `on_live`: given the run's `Steer` while its turn runs (Claude Code's and Codex's,
        89d), then None. `on_end`: given what ends its turn, with why (B-357: Stop on a command
        of its own, whose process KOLONİ does not hold). `tests_at_stop`: Claude Code is given
        a Stop hook (89m), answered by `call_tool("stop", <its input>)`.
        `inside`: 89g, roles offered to Claude Code as sub-agents of its own, by the name each
        is offered by (`inside_name`): what `--agents` takes of each.
        `report_schema`: the shape its report is handed back in, for Claude Code (89p,
        `_control`); a CLI that is not told one reports in words.
        `skills`: its role's skills, by name, where KOLONİ keeps each - for a CLI that
        takes them as skills of its own (Claude Code, `claude_plugin`). `skills_told`: what
        its instructions say of them where it does not (`AgentRunner._skills_told`): Claude
        Code's, given as its own, are only named there (B-151).
        `withheld`: what the agent may not do ("write", "run"; "unasked": whatever
        would have to be asked about, in a turn nobody is watching), for a CLI
        that can be told to leave such tools of its own alone. `linked`: where `root`
        is a working copy, the project's folders that are linked into it, by where
        they really are - for a CLI that has to be told it may read there. `ceiling`:
        there too, how far up git may look for a repository (`copies.ceiling`). `also`:
        outside a copy, the folders outside the project it also works in. `pass_env`: the
        secret variables its commands are given all the same (`Project.pass_env`).
        `denied`: what its commands may not open, for a CLI with a sandbox that can be told
        (Copilot's); None: nothing is hidden from them."""
        codex = self.command == "codex"
        # Codex and Copilot ask over a protocol of their own (`_converse`), Claude Code over
        # its control protocol (`_control`). (No approve tool is offered to any: slice 89b.)
        conversing = self.command in ("codex", "copilot")
        self._offered = [tool["function"]["name"] for tool in tools or []]
        # 27 / 93-C3: Claude Code (and Qoder, once its `resumes` is on) goes on in the session its
        # last turn left only where started under all the same now (`_under`): resuming carries
        # the conversation, never the rights - those are this run's own line, hook and
        # settings, as for a new one.
        # shortcut: Codex and Copilot go on in no session, each turn is sent the whole
        # conversation (KOLONİ compacts it: `AgentRunner._idle_after`). Resume was measured on
        # `codex exec resume` and `copilot -p --resume` (cli-surdurme-olcum.md), not on the
        # app-server's `thread/resume` (its threads are `ephemeral`; whether it takes this run's
        # approvalPolicy / sandbox; its token total is the thread's, which would count earlier
        # turns again) nor headless `session.resume` (its COPILOT_HOME, where the session is,
        # goes with each turn's workdir; whether availableTools / requestPermission / sandbox
        # are given anew). Measure those and resume them. Nor does any CLI as a session or step
        # by step (`ClaudeSessionClient`, the default mode).
        under = self._under(model_id, root, withheld, linked, also, level) \
            if keep and isinstance(self, ClaudeNativeClient) and self.resumes else None
        resume = session["id"] if under and session and session.get("under") == under \
            and SESSION_ID.fullmatch(str(session.get("id"))) else None
        acted = False  # (whether anything of a resumed run was said or done: then no new one)
        if resume:
            def noted(act):
                async def then(*args):
                    nonlocal acted
                    acted = True
                    return await act(*args)
                return then

            call_tool, on_text, on_item = noted(call_tool), noted(on_text), noted(on_item)
        server = ToolServer(tools or [], call_tool)
        if on_end:
            on_end(server._end)
        workdir: Path | None = None
        try:
            workdir = Path(tempfile.mkdtemp(prefix="koloni-cli-"))
            await server.start()
            bridge_config = bridge_file(server, workdir)
            command, shim = self._command()
            # (In a thread: Codex's line is built from a walk of the user's skills.)
            arguments = await asyncio.to_thread(
                self._native_arguments, Path(root), bridge_config, withheld, linked, also)
            if under:  # (27: kept, in KOLONİ's own sign-in folder, where its next turn resumes it)
                arguments.remove("--no-session-persistence")
            # (Not with the user's own setup, which goes as it is: their commands are on.)
            if skills and isinstance(self, ClaudeNativeClient) \
                    and "--disable-slash-commands" in arguments \
                    and (given := await self._skills_given(
                        workdir / "plugin", skills, Path(root))) is not None:
                held, left = given
                if held:
                    arguments = [*(one for one in arguments
                                   if one != "--disable-slash-commands"),
                                 "--plugin-dir", str(workdir / "plugin")]
                # B-151: those it has as its own only named, nothing of one it was not given
                # (its text in the instructions would be there to run) - and that said once.
                skills_told = SKILLS_OWN + "".join(
                    f"\n- {PLUGIN}:{name}" for name in held) if held else ""
                for name, why in left.items():
                    await on_item("completed", {"type": "skill_not_given", "name": name,
                                                "why": why})
            # (Qoder over the same protocol, B-306: none of Claude Code's extras below.)
            claude = isinstance(self, ClaudeNativeClient) and self.command == "claude"
            if claude and report_schema:
                # (Compact, and with nothing a .cmd shim's interpreter acts on: `_fits`.)
                arguments += ["--json-schema", json.dumps(report_schema, separators=(",", ":"))]
            if inside and claude:  # (after the schema: `_fits` below measures the whole line)
                agents = ["--agents", json.dumps(inside)]
                try:
                    # Before it, a tool of one is not known to name its role to the hook: it
                    # would be held to its Lead's rights only.
                    if not await self._from(INSIDE_FROM):
                        raise OwnStop(f"{self.label} is older than "
                                      f"{'.'.join(map(str, INSIDE_FROM))}")
                    self._fits([*command, *self._leveled([*arguments, *agents], effort)], shim)
                    arguments = [*arguments, *agents]
                except OwnStop as exc:
                    # shortcut: a line too long for Windows, or one its .cmd cannot take,
                    # offers none of them (they are opened as KOLONİ's agents); pass them in
                    # a file if Claude Code is measured to take one.
                    await on_item("completed", {"type": "inside_not_given",
                                                "names": list(inside), "why": str(exc)})
            # (Codex's level goes in turn/start.)
            argv = [*command, *(arguments if codex else self._leveled(arguments, effort))]
            # (With the secret variables the user passes: `_start` gives it the rest.)
            # (and what KOLONİ plants for the turn: 101's test key, judged at its hook)
            env = {**self._inherited(pass_env), **(planted or {}), **self._native_env(workdir)}
            if ceiling:
                env = {**env, "GIT_CEILING_DIRECTORIES": ceiling}
            temp = Path(root) / SCRATCH
            if codex and temp.is_dir():
                # B-358: its sandbox writes only in the folder it works in, not in %TEMP% - where
                # Python's tempfile went ("No usable temporary directory"). The agents' scratch
                # (made by `AgentRunner` before it looks at the folder) is there, and no look
                # reads it. (A TEMP of the user's own for Codex comes after this: `_start`.)
                # shortcut: that its commands are given these and its sandbox lets them write
                # there is not measured live; measure it (K-cli-surface).
                env = {**env, "TMP": str(temp), "TEMP": str(temp), "TMPDIR": str(temp)}
            instructions = "\n\n".join(
                m["content"] for m in messages if m["role"] == "system") + skills_told
            document = {"instructions": instructions, "conversation": conversation(messages)}
            rules = f"{self.rules}\n\n{READ_ONLY_RULES}" if "read_only" in withheld else self.rules
            prompt = (
                f"{rules}\n\n{WHERE.format(root=root)}\n\n"
                + json.dumps(document, ensure_ascii=False)
            )
            if conversing:
                # Codex's turn takes the prompt, and each picture as it is (slice 85c).
                copies = await asyncio.to_thread(image_copies, messages, workdir) if codex else []
                given = [{"type": "text", "text": prompt, "text_elements": []}, *(
                    {"type": "localImage", "path": copy} for copy in copies)] if codex else prompt
                return await self._converse(
                    argv, shim, given, Path(root), server, on_text, on_item, env, call_tool,
                    also, effort, bridge_config, denied, on_live,
                    read_only="read_only" in withheld, no_shell=_no_shell(withheld))
            if isinstance(self, ClaudeNativeClient):  # over its control protocol (slice 89b)
                def with_session(result: SessionResult) -> SessionResult:
                    kept = under and result.session and SESSION_ID.fullmatch(result.session["id"])
                    return replace(result, session={
                        **result.session, "under": under,
                        **({"home": str(self.home)} if self.home else {})}
                        if kept and result.session else None)

                new = since_its_last_word(messages) if resume else []
                off = self._plugins_off
                if new:
                    # Only what came since its last answer there, with its rules and instructions
                    # as they stand now (they say this run's leave): the rest is in its session.
                    told = f"{rules}\n\n{RESUMED}\n\n{WHERE.format(root=root)}\n\n" + json.dumps(
                        {"instructions": instructions, "conversation": conversation(new)},
                        ensure_ascii=False)
                    acted = False  # (what was said above - a skill not given - is not its doing)
                    try:
                        return with_session(await self._control(
                            [*argv, self.resume_flag, str(resume)], shim,
                            await asyncio.to_thread(claude_content, told, new) if claude
                            else told, Path(root),
                            server, on_text, on_item, env, call_tool, on_live, tests_at_stop,
                            report_schema))
                    except (OwnStop, ModelUnavailable) as exc:
                        # It could not go on in that session (gone, another sign-in): anew, once.
                        # Never where it said or did anything (that would be done twice), was
                        # stopped, or loaded what it was not given (`_control`'s `leaked`) - nor,
                        # where its own words for a session it lacks are measured (`NO_SESSION`),
                        # on any other failure.
                        # shortcut: Claude Code's are not measured; any failure before a word or
                        # a tool is taken for that.
                        if acted or server.ended or self._plugins_off != off or (
                                self.NO_SESSION and not self.NO_SESSION.search(str(exc))):
                            raise
                    # A new tool server for it: the one before may have served its bridge (its
                    # file gone, its key taken).
                    await server.close()
                    server = ToolServer(tools or [], call_tool)
                    if on_end:
                        on_end(server._end)
                    await server.start()
                    bridge_file(server, workdir)
                content = await asyncio.to_thread(claude_content, prompt, messages) \
                    if claude else prompt  # (no picture is sent to Qoder: IMAGE_CLIS)
                return with_session(await self._control(
                    argv, shim, content, Path(root), server, on_text, on_item, env, call_tool,
                    on_live, tests_at_stop, report_schema))
            return await self._work(
                argv, shim, prompt, Path(root), server, on_text, on_item, env
            )
        finally:
            await server.close()
            if workdir:
                shutil.rmtree(workdir, ignore_errors=True)

    async def _work(  # noqa: C901
        self, argv, shim, prompt, root: Path, server: ToolServer, on_text, on_item: OnItem,
        env: dict[str, str] | None = None, *,
        ready: Callable[[], Awaitable[str | None]] | None = None,
        translate: Callable[[dict], list[dict]] | None = None,
    ) -> SessionResult:
        """`ready`: awaited once it has started, before it is given the prompt - a CLI that
        must be seen to hold itself to KOLONİ's rules first (native agy's hook); it may stop
        the run, or give the prompt to send instead (agy whose bridge never came, B-310).
        `translate`: its stream's translator for this run, if not a new one."""
        try:
            process, job = await self._start(argv, shim, root, env)
        except OSError as exc:
            reason = exc.strerror or exc
            raise OwnStop(f"{self.label} could not be started: {reason}") from None
        stdin, stdout, errors = process.stdin, process.stdout, process.stderr
        assert stdin is not None and stdout is not None and errors is not None  # all piped
        stderr = asyncio.ensure_future(complaints(errors, (server.key,)))
        usage: dict | None = None
        reported: str | None = None  # the model it says it is using
        translating = translate or self._translator()
        failure: str | None = None
        limited = None  # what it said of its plan's limit, if it turned this run away
        own_word: tuple | None = None  # what its own word says a failure is (`own_error`)
        heard = time.monotonic()
        busy: set[str] = set()  # ids of its own commands that are still running
        said = False  # whether the last thing it did was say something

        def end_now() -> None:
            if job:
                job.terminate()
            with contextlib.suppress(ProcessLookupError):
                process.kill()

        server.on_end = end_now

        async def talk() -> None:  # noqa: C901
            nonlocal usage, failure, heard, said, reported, limited, own_word, prompt
            if ready:
                prompt = await ready() or prompt
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                stdin.write(prompt.encode("utf-8"))
                await stdin.drain()
            stdin.close()
            async for raw in stdout:
                heard = time.monotonic()
                written = raw.decode("utf-8", errors="replace")
                feed("stdout", written, (server.key,))
                for event in (
                    told
                    for line in _events(written)
                    for told in translating(line)
                ):
                    kind = event.get("type")
                    item = _dict(event.get("item"))
                    if kind == "model":
                        reported = str(event.get("model") or "") or reported
                        continue
                    if kind == "rate_limit_event":
                        limited = self._limit_event(event)
                        continue
                    if kind == "own_error":
                        own_word = event["failure"]
                        continue
                    if kind == "text":
                        # A piece of what it is saying, as it says it.
                        await on_text(str(event.get("text") or ""))
                        continue
                    if kind == "busy":
                        # A tool of its own is at work (or done): that is not silence.
                        (busy.add if event.get("on") else busy.discard)(str(event.get("id")))
                        if event.get("on"):
                            # It has said it wants this tool: leave may now be asked for it.
                            await on_item("announced", {
                                "id": str(event.get("id")), "parent": event.get("parent")})
                        continue
                    if kind in ("error", "turn.failed"):
                        error = _dict(event.get("error")) or event
                        failure = _brief(self._hide(str(error.get("message"))))
                        if event.get("result_text"):
                            limited = limited or RESULT_TEXT
                    elif kind == "turn.completed":
                        usage = _dict(event.get("usage"))
                        return  # it has finished; whatever lingers is ended below
                    elif kind in ("item.started", "item.completed"):
                        said = await self._heard(kind, item, said, busy, on_text, on_item)
                if server.ended:
                    return
            await process.wait()

        talking = asyncio.ensure_future(talk())
        try:
            # The limit is on silence, and neither a tool KOLONİ is running for it nor a
            # command of its own that is still going counts as silence. A CLI that is gone
            # is not at work (`Exited`): said below as it ended.
            gone = Exited(process, job)
            while not talking.done():
                await asyncio.wait({talking}, timeout=min(1.0, self._timeout / 4))
                quiet = time.monotonic() - max(heard, server.last_reply)
                working = server.in_flight > 0 or bool(busy)
                if not talking.done() and await gone():
                    break
                if not talking.done() and not working and quiet > self._timeout:
                    raise ModelUnavailable(
                        f"{self.label} sent nothing for {self._timeout:g} seconds"
                    )
            if talking.done():
                try:
                    talking.result()
                except ValueError:
                    raise ModelUnavailable(
                        f"{self.label} sent a line too long to read") from None
        finally:
            talking.cancel()
            with contextlib.suppress(BaseException):
                await asyncio.shield(asyncio.wait({talking}, timeout=2))
            await self._end(process, job)
            complaint = b""
            with contextlib.suppress(Exception):
                complaint = await asyncio.wait_for(asyncio.shield(stderr), 2)
            stderr.cancel()
        if server.ended:
            raise server.ended
        if usage is None:
            reason = _brief(self._hide(complaint.decode("utf-8", errors="replace")))
            failed = ModelUnavailable(
                f"{self.label} reported an error: {failure}" if failure
                else how_it_ended(self.label, process.returncode, reason)
            )
            failed.failure = classed(limited, own_word)
            raise failed
        sent, made = usage.get("input_tokens"), usage.get("output_tokens")
        return SessionResult(
            sent if isinstance(sent, int) else None, made if isinstance(made, int) else None,
            reported,
            # Codex's own name for what of its input came from the cache. Of what it wrote
            # there it says nothing: that is told for a CLI whose stream is translated.
            count_of(usage.get("cached_input_tokens")),
            count_of(usage.get("cache_creation_input_tokens")),
        )

    async def _heard(
        self, kind: str, item: dict, said: bool, busy: set[str], on_text, on_item: OnItem,
    ) -> bool:
        """One thing it began or ended (exec's "item.started" / "item.completed"): what it
        says goes to `on_text`, what it does to `on_item`. Returns whether the last thing it
        did was to say something."""
        phase = kind.split(".")[1]
        what = item.get("type")
        if what == "agent_message":
            # B-182: not its commentary - notes between its steps, which leaked one to itself
            # live ("Wait mixed languages oops commentary need"): its answer is what it says.
            # shortcut: the phase by Codex 0.164's strings (commentary, partial_answer,
            # final_answer), not seen on a live item; check one before relying on it.
            if phase == "completed" and item.get("text") and item.get("phase") != "commentary":
                # Two messages in a row are two paragraphs.
                await on_text(("\n\n" if said else "") + str(item["text"]))
                return True
            return said
        if what == "mcp_tool_call" and item.get("server") == SERVER:
            return False  # KOLONİ's own tool: recorded where it is run
        if what in ("command_execution", "file_change", "mcp_tool_call", "web_search",
                    "sub_agent"):
            if what == "command_execution" and item.get("id") is not None:
                (busy.add if phase == "started" else busy.discard)(str(item["id"]))
            await on_item(phase, item)
            return False
        return said

    async def _converse(  # noqa: C901
        self, argv, shim, prompt, root: Path, server: ToolServer, on_text, on_item: OnItem,
        env: dict[str, str], call_tool: CallTool, also: tuple[str, ...], effort: str | None,
        bridge_config: Path | None = None, denied: tuple[str, ...] | None = None,
        on_live: OnLive | None = None, read_only: bool = False, no_shell: bool = False,
    ) -> SessionResult:
        """Codex's app-server for one turn, started and ended as `_work` starts and ends
        `codex exec`: a thread that asks before every command and patch ("untrusted"; in its
        "read-only" sandbox with `read_only`, B-301), the
        prompt (its turn's input: `run_native`) as its one turn, each request of its own
        answered by KOLONİ (`_decide`), and
        what it does handed on as `_work` hands on exec's events. A Codex that cannot be
        started asking first - its start or its thread's refused or never answered - is
        stopped, never run unasked instead. (`denied` is Copilot's: Codex's sandbox is not
        told it, K-codex-elevated.)"""
        try:
            process, job = await self._start(argv, shim, root, env)
        except OSError as exc:
            raise OwnStop(f"{self.label} could not be started: {exc.strerror or exc}") from None
        stdin, stdout, errors = process.stdin, process.stdout, process.stderr
        assert stdin is not None and stdout is not None and errors is not None  # all piped
        stderr = asyncio.ensure_future(complaints(errors, (server.key,)))
        loop = asyncio.get_running_loop()
        replies: dict[int, asyncio.Future] = {}  # the ids of KOLONİ's requests -> answers
        asked = _Asked(root)
        thread_id: object = None  # its thread's: its turn's end is told by that
        answering: set[asyncio.Future] = set()
        writing = asyncio.Lock()
        heard = time.monotonic()
        # Its commands and patches at work, and its requests KOLONİ is answering (a card
        # can be open for long): none of that is silence.
        busy: set[str] = set()
        # B-357: when each of those was first seen at work; and each command it was let run,
        # from its yes until it is heard of again.
        since: dict[str, float] = {}
        asking: set[str] = set()  # (the items a card is open for: not at work yet)
        allowed: dict[str, float] = {}
        commands: set[str] = set()  # (its items that are commands)
        said = False
        # B-182: whether it said anything but commentary, and its last commentary - what is
        # shown of a turn that said nothing else (a preamble, then an error or a cut).
        spoke, commentary = False, ""
        usage: dict | None = None
        failure: str | None = None
        unasked: str | None = None  # why it could not be started asking first
        broke: BaseException | None = None  # what answering a request of its own ended in
        started = False  # its turn is under way
        turn_id: object = None  # its turn's, while it runs: what a steer is sent into
        numbers = itertools.count(4)  # (1 to 3: its start and its turn's)

        def end_now() -> None:
            if job:
                job.terminate()
            with contextlib.suppress(ProcessLookupError):
                process.kill()

        server.on_end = end_now

        async def send(message: dict) -> None:
            async with writing:
                stdin.write((json.dumps({"jsonrpc": "2.0", **message}) + "\n").encode())
                await stdin.drain()

        async def ask(number: int, method: str, params: dict) -> tuple[dict, str | None]:
            """What it answered, and why it said no (None: it did not)."""
            replies[number] = loop.create_future()
            await send({"id": number, "method": method, "params": params})
            told = await replies[number]
            if "result" in told:
                return _dict(told["result"]), None
            error = told.get("error")
            return {}, _brief(self._hide(str(_dict(error).get("message") or error)))

        async def steer(text: str) -> bool:
            """89d: `text` into its turn, as measured 25 Oct (`turn/steer`, mid-command); True:
            Codex took it, or sent and not answered within STEER_SECONDS - which may have
            reached its turn, as Claude Code's line still in the pipe is on its way - and not
            yet that it read it. Never into a thread of its own agents', and never an error that
            ends the run."""
            if turn_id is None:
                return False
            # shortcut: one Codex refuses after STEER_SECONDS is called taken (and kept on
            # record); wait longer if a slow answer is seen live.
            try:
                _, no = await asyncio.wait_for(ask(next(numbers), "turn/steer", {
                    "threadId": thread_id, "expectedTurnId": turn_id,
                    "input": [{"type": "text", "text": text, "text_elements": []}]}),
                    STEER_SECONDS)
            except TimeoutError:
                return True
            except Exception:
                return False
            return no is None

        async def answer(request: dict) -> None:
            nonlocal heard, broke
            key = f"asked {request.get('id')}"
            item = str(_dict(request.get("params")).get("itemId"))
            busy.add(key)
            asking.add(item)
            try:
                params = _dict(request.get("params"))
                reply = await self._decide(str(request.get("method")), params, asked,
                                           call_tool, on_item)
                why = reply.pop("why", "")
                if why and params.get("threadId") == thread_id:
                    # B-197: told only "rejected", a Lead put its own refused patch down to a
                    # Coder. Before the no: after it its turn may be over, and this lost.
                    await steer(DECLINED_WHY.format(why=why))
                _note_reply(request, params, reply, busy, allowed)
                with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                    await send({"id": request.get("id"), **reply})
            except Exception as exc:  # a stop of KOLONİ's own, or a bug: its work ends here
                broke = broke or exc
                end_now()
            finally:
                busy.discard(key)
                asking.discard(item)
                since.pop(item, None)  # (its time at work starts once it is answered)
                heard = time.monotonic()

        async def read() -> None:  # noqa: C901
            nonlocal heard, said, usage, failure, turn_id, spoke, commentary, broke
            try:
                async for raw in stdout:
                    heard = time.monotonic()
                    written = raw.decode("utf-8", errors="replace")
                    messages = _events(written)
                    # Whose account it is (account/updated) is kept nowhere.
                    if not [m for m in messages if str(m.get("method")).startswith("account/")]:
                        feed("stdout", written, (server.key,))
                    for message in messages:
                        method, params = message.get("method"), _dict(message.get("params"))
                        item = _dict(params.get("item"))
                        if "id" not in message:  # (its output, its end: it has started)
                            allowed.pop(str(params.get("itemId") or item.get("id")), None)
                        if item.get("type") == "commandExecution":
                            commands.add(str(item.get("id")))
                        if method is None:  # an answer to a request of KOLONİ's
                            number = message.get("id")
                            future = replies.get(number) if isinstance(number, int) else None
                            if future is not None and not future.done():
                                future.set_result(message)
                        elif "id" in message:  # a request of its own
                            task = asyncio.ensure_future(answer(message))
                            answering.add(task)
                            task.add_done_callback(answering.discard)
                        elif method == "account/rateLimits/updated":
                            if self.on_limits:  # (keeping it never breaks the run)
                                with contextlib.suppress(Exception):
                                    self.on_limits(params)
                        elif method == "thread/tokenUsage/updated":
                            told = _dict(params.get("tokenUsage"))
                            usage = _dict(told.get("total"))
                            # 89j: its last request's input (cached included) is what its
                            # context holds; not a thread of its own agents'.
                            filled = _filled(_dict(told.get("last")).get("inputTokens"),
                                             told.get("modelContextWindow"))
                            if filled and params.get("threadId") == thread_id:
                                await on_item("live", filled)
                        elif method == "turn/plan/updated":
                            if params.get("threadId") == thread_id:
                                await on_item("live", _plan(params.get("plan")))
                        elif method == "error" and not params.get("willRetry"):
                            error = _dict(params.get("error"))
                            failure = _brief(self._hide(str(error.get("message"))))
                        elif method == "turn/started" and params.get("threadId") == thread_id:
                            turn_id = _dict(params.get("turn")).get("id") or turn_id
                        elif method == "turn/completed":
                            if params.get("threadId") != thread_id:
                                continue  # (another thread's: one of its own agents', say)
                            turn_id = None  # (nothing more is steered into it)
                            turn = _dict(params.get("turn"))
                            if turn.get("status") == "completed":
                                usage = {} if usage is None else usage
                            else:
                                error = _dict(turn.get("error")).get("message")
                                failure = failure or _brief(self._hide(
                                    str(error or f"its turn ended {turn.get('status')}")))
                                usage = None
                            return  # it has finished; whatever lingers is ended below
                        else:
                            item = _dict(params.get("item"))
                            if (why := self._unwanted(item, no_shell)) is not None:
                                broke = broke or OwnStop(why)  # (B-301: asked or not)
                                end_now()
                                return
                            _note_patch(method, params, item, asked)
                            for event in _as_exec(str(method), params, asked, read_only):
                                if event["type"] == "busy":
                                    (busy.add if event["on"] else busy.discard)(event["id"])
                                else:
                                    one = event["item"]
                                    if one.get("type") == "agent_message" and one.get(
                                            "phase") == "commentary":
                                        commentary = str(one.get("text") or "") or commentary
                                    said = await self._heard(event["type"], one, said, busy,
                                                             on_text, on_item)
                                    spoke = spoke or said
                    if server.ended:
                        return
                await process.wait()
            finally:
                for future in replies.values():  # nothing more will answer them
                    if not future.done():
                        future.set_result({"error": {"message": "it ended"}})

        async def talk() -> None:
            nonlocal unasked, started, failure, thread_id, turn_id
            reading = asyncio.ensure_future(read())
            thread: dict = {}
            try:
                _, no = await ask(1, "initialize", {"clientInfo": {"name": "koloni",
                                                                   "version": "0"}})
                if no is None:
                    await send({"method": "initialized"})
                    thread, no = await ask(2, "thread/start", {
                        "cwd": str(root), "approvalPolicy": "untrusted",
                        # Every request is KOLONİ's to answer: none goes to Codex's own reviewer.
                        "approvalsReviewer": "user",
                        # shortcut: in "read-only" a test's own cache (.pytest_cache) or a build's
                        # output is refused too, and a test command that must write fails; give a
                        # role that runs tests a writable temp folder if that is seen live.
                        "sandbox": "read-only" if read_only else "workspace-write",
                        "ephemeral": True,
                        **({"model": self._model} if self._model else {})})
                    no = no or _not_as_asked(thread, root, also, read_only)
                if no is not None:
                    if not reading.done():  # (one that ended says so below, as exec's did)
                        unasked = no
                    return
                started = True
                thread_id = _dict(thread.get("thread")).get("id")
                asking = {
                    "threadId": thread_id,
                    **({"effort": self.effort_words.get(effort, effort)} if effort else {}),
                    # The folders outside the project it also works in.
                    # shortcut: as --add-dir was, not measured with the real CLI; check
                    # that a command writing there is not refused by its sandbox.
                    **({"sandboxPolicy": {"type": "workspaceWrite",
                                          "writableRoots": list(also)}}
                       if also and not read_only else {})}
                # B-343: the level sent is seen in its raw stream beside what it answers (the
                # prompt left out: it is the turn's own, and long).
                feed("stdin", json.dumps({"method": "turn/start", "params": asking}),
                     (server.key,))
                turn, no = await ask(3, "turn/start", {**asking, "input": prompt})
                if no is not None:
                    failure = failure or no
                    return
                if not reading.done():  # (a turn already over takes nothing more)
                    turn_id = turn_id or _dict(turn.get("turn")).get("id")
                if on_live:
                    on_live(steer)
                await reading
            except (BrokenPipeError, ConnectionResetError):
                return  # it is gone: how it ended is said below, as exec's was
            finally:
                reading.cancel()
                with contextlib.suppress(BaseException):
                    await asyncio.shield(asyncio.wait({reading}, timeout=2))

        talking = asyncio.ensure_future(talk())
        try:
            # The limit is on silence, as for `_work`; not a word before it was asked to
            # start its turn is a Codex that could not be asked first.
            gone = Exited(process, job)
            while not talking.done():
                await asyncio.wait({talking}, timeout=min(1.0, self._timeout / 4))
                at = time.monotonic()
                quiet = at - max(heard, server.last_reply)
                working = server.in_flight > 0 or bool(busy)
                if not talking.done() and await gone():
                    break  # (said as it ended, `_turn_outcome`)
                # (Not a card: the user may take hours over it.)
                # shortcut: nor the wait after the user's yes for the agent's place
                # (`AgentRunner._users_word`) - B-357's 26 minutes were a lock there, fixed;
                # bound that wait too if one is seen to last again.
                late, over = _overdue(busy, asking, since, allowed, at)
                if not talking.done() and over:
                    why = (NEVER_STARTED.format(seconds=NEVER_STARTED_SECONDS) if late
                           else RAN_TOO_LONG.format(seconds=CALL_SECONDS))
                    command = bool(late) or over in commands
                    if command:  # (on record as failed, with why; a patch is closed below)
                        await on_item("completed", {
                            "type": "command_execution", "id": over, "status": "failed",
                            "exit_code": None, "aggregated_output": why,
                            "never_started": bool(late)})
                    raise ModelUnavailable(f"{self.label}'s own "
                                           f"{'command' if command else 'patch'} {why}")
                if not talking.done() and not working and quiet > self._timeout:
                    if not started:
                        unasked = f"it did not answer for {self._timeout:g} seconds"
                        break
                    raise ModelUnavailable(
                        f"{self.label} sent nothing for {self._timeout:g} seconds"
                    )
            if talking.done():
                try:
                    talking.result()
                except ValueError:
                    raise ModelUnavailable(
                        f"{self.label} sent a line too long to read") from None
        finally:
            if on_live:
                on_live(None)
            for task in (talking, *answering):
                task.cancel()
            with contextlib.suppress(BaseException):
                await asyncio.shield(asyncio.wait({talking, *answering}, timeout=2))
            await self._end(process, job)
            complaint = b""
            with contextlib.suppress(Exception):
                complaint = await asyncio.wait_for(asyncio.shield(stderr), 2)
            stderr.cancel()
        if commentary and not spoke:
            await on_text(commentary)
        return await self._turn_outcome(broke, server, unasked, usage, failure, complaint,
                                       process)

    def _unwanted(self, item: dict, no_shell: bool) -> str | None:
        """Why an item it began or ended ends its turn at once (`_converse`), or None: a
        command of its own where it has no shell (B-301)."""
        return self.no_shell_ran if no_shell and item.get("type") == "commandExecution" else None

    async def _turn_outcome(
        self, broke: BaseException | None, server: ToolServer, unasked: str | None,
        usage: dict | None, failure: str | None, complaint: bytes, process,
    ) -> SessionResult:
        # What `_converse`'s turn came to, once it is over.
        if broke is not None:
            raise broke
        if server.ended:
            raise server.ended
        if unasked is not None:
            raise OwnStop(f"{self.label} {await self._version()} could not be asked before it "
                          f"acts ({unasked}); run it as a step instead")
        if usage is None:
            reason = _brief(self._hide(complaint.decode("utf-8", errors="replace")))
            raise ModelUnavailable(
                f"{self.label} reported an error: {failure}" if failure
                else how_it_ended(self.label, process.returncode, reason))
        # (The whole thread's: it is this turn's alone. Of what it wrote to its cache it says
        # nothing that exec said, so nothing is said.)
        return SessionResult(count_of(usage.get("inputTokens")),
                             count_of(usage.get("outputTokens")), None,
                             count_of(usage.get("cachedInputTokens")), None)

    async def _version(self) -> str:
        """Its version, as `--version` says it; that it is not known, if it does not."""
        with contextlib.suppress(Exception):
            _code, said, _errors = await self.run_status(["--version"], 10)
            # ("codex-cli 0.164.0", "GitHub Copilot CLI 1.0.91.", "2.1.310 (Claude Code)": the
            # number is the version.)
            found = re.search(r"\d+(?:\.\d+)+(?:-[\w.]*\w)?", said)
            if found or said.strip():
                return found[0] if found else _brief(said.strip())
        return "(version not known)"

    async def _decide(
        self, method: str, params: dict, asked: _Asked, call_tool: CallTool, on_item: OnItem,
    ) -> dict:
        """KOLONİ's answer to a request of Codex's: what `AgentRunner._approve` says, asked
        as Claude Code's prompts are - a command as its Bash; each file of a patch as its
        Write (a new file, whose diff is what it will hold) or its Edit, and the patch
        accepted only if every file is. A call of one of KOLONİ's own tools is let through:
        those are held to KOLONİ's rules where they run. Anything else is declined, and that
        is on record."""
        item_id = str(params.get("itemId") or "")
        meta = _dict(params.get("_meta"))
        if method == "mcpServer/elicitation/request" and (
                meta.get("codex_approval_kind") == "mcp_tool_call"):
            # (Measured on 0.164.0: every MCP tool call, at "untrusted". Nothing is kept
            # for later: no `persist`. A server's of its own fails, and is on record so.)
            return {"result": {"action": "accept", "content": {}}
                    if params.get("serverName") == SERVER else DECLINED[method]}
        why = (f"KOLONİ declined this request of {self.label}'s: only a command or a patch "
               "it said it was making is answered")
        questions: list[tuple[str, dict]] = []
        given = {key: params[key] for key in ("reason", "cwd") if params.get(key)}
        again = (item_id, params.get("approvalId")) in asked.answered
        command = _unwrapped(str(params.get("command") or ""))
        runs = (not again and method == RUN_ASKED and params.get("kind") in (None, "command")
                and not params.get("networkApprovalContext"))
        # (A patch it runs as a command is asked file by file as the patch it is; its end is
        # that patch's: `_as_exec`.)
        heredoc = _heredoc_patch(command, str(params.get("cwd") or asked.root or "")) if (
            runs) else None
        if heredoc is not None:
            # Review: it still starts a shell - only where every rule of a command that is not
            # the user's word lets it run is it a patch (`AgentRunner._runs_as_patch`).
            _ok, may = await call_tool(PATCH_MAY_RUN, json.dumps({"command": command, **given}))
            heredoc = heredoc if may == "true" else None
        patch = heredoc is not None or method == PATCH_ASKED
        if again:
            why = (f"KOLONİ declined this request of {self.label}'s: it asked again for "
                   "what was answered")
        elif runs and heredoc is None:
            questions = [("Bash", {"command": command, **given})]
        elif heredoc is not None or (method == PATCH_ASKED and not params.get("grantRoot")):
            if heredoc is not None:
                asked.heredocs[item_id] = heredoc
            questions = _patch_questions(
                heredoc if heredoc is not None else asked.patches.pop(item_id, None), given)
        if not item_id or not questions:
            # Input to a terminal, network or a whole folder for good, a patch it never said
            # it was making, a question of its own: none of it is answered yes. (Of one
            # about whose account it is, only its name is kept.)
            whose = method.startswith(("account/", "attestation/"))
            await on_item("completed", {
                "type": "mcp_tool_call", "server": "codex", "tool": method,
                "arguments": {} if whose else params, "status": "declined",
                "error": {"message": why}})
            return ({"result": DECLINED[method]} if method in DECLINED
                    else {"error": {"code": -32601, "message": "KOLONİ declines this request"}})
        asked.items.add(item_id)
        asked.answered.add((item_id, params.get("approvalId")))
        for number, (tool, question) in enumerate(questions):
            # A patch's files by the ids its record names as its `parts` (`_as_exec`).
            # shortcut: commands under one item id told apart by `approvalId` (its zsh
            # bridge's; not on Windows) are each asked, and the record is the last one's.
            use_id = f"{item_id}:{number}" if patch else item_id
            if patch:
                asked.paths.setdefault(item_id, {})[question["file_path"]] = use_id
            await on_item("announced", {"id": use_id})
            _ok, verdict = await call_tool("approve", json.dumps(
                {"tool_name": tool, "input": question, "tool_use_id": use_id}))
            said = _dict(json.loads(verdict))
            if said.get("behavior") != "allow":
                # Its decision has no room for a reason (0.164.0): KOLONİ's own words go into
                # its turn - never what it or anything else wrote (`deny(fixed=True)`).
                return {"result": DECLINED[method],
                        "why": str(said.get("message") or "") if said.get("koloni") else ""}
        return {"result": {"decision": "accept"}}


# What Codex as a session is told (`CodexSessionClient`): as `SESSION_RULES`, but without how
# its MCP tools are named (not measured for Codex) and with its patch tool's refusal.
PATCH_REFUSED = ("Your own apply_patch is refused by KOLONİ: write and edit files only with "
                 "the koloni server's write_file and edit_file.")
CODEX_SESSION_RULES = f"""You are an agent that another program, KOLONİ, runs. The input is a JSON
document with "instructions" (who you are and how to work) and "conversation" (everything so
far, oldest first). Carry on from the end of the conversation: do what the last user message
asks.

Your only tools are the ones of the "koloni" MCP server, which the instructions and the
conversation name. You have no other way to read files, run commands or reach the network,
and that is expected. {PATCH_REFUSED} A tool result that says the user declined something is
their decision, not an error to work around.

The folder you are started in is a temporary one of KOLONİ's, not the project: the project
folder is the one the instructions name.

When the work is done, say briefly what you did and what you did not verify."""


class CodexSessionClient(CodexNativeClient):
    """Codex as one session per agent, with KOLONİ's tools only: its app-server, as natively
    (`_converse`) - one process, one thread and one turn for each `run_session`, as the other
    session CLIs run one process for each of an agent's turns - but in a folder of KOLONİ's,
    its own tools off and KOLONİ's whole tool set over the bridge (`ToolServer`).

    Measured 7 Nov 2026 (codex-cli 0.164.0, gpt-6-luna, a temp folder, one short turn): the
    feature flags below take its shell, image, web, apps, agents and plugins away; its
    apply_patch has no flag (openai/codex #8161) and is asked about first at "untrusted" -
    declined, Codex wrote with KOLONİ's write_file instead, and with no hint it never tried
    it. Every MCP tool call is asked first (`mcpServer/elicitation/request`).
    shortcut: not measured - a long session of many steps, compaction inside its turn, a
    model server of the user's, the read-only sandbox (it is `workspace-write` in KOLONİ's
    empty folder, as measured: Codex writes nothing there). Measure them live.
    shortcut: what its Codex home says still comes in, as step by step and natively: its
    AGENTS.md, developer_instructions, model_instructions_file and notify; and whether
    features.hooks=false keeps a hooks file of the user's from running is not measured."""

    native = False
    session = True
    asks = False
    looks_by_running = False
    no_shell_ran = ("Codex ran a command of its own though its shell was switched off, so the "
                    "session was stopped")
    # Its own tools, off as step by step does (`CodexCliClient.DISABLED`) - but its code-mode
    # host: without it no MCP tool is reached at all (measured: "Code Mode is unavailable
    # because code-mode host is disabled", R181/B-387). Code mode itself reaches no file,
    # command or network (measured: asked to read a file without KOLONİ's tools, it could not).
    # With the host on, these flags are the only switch: also off are the tool-like keys among
    # 0.164's feature names that the user's own config could turn on (js_repl reaches the
    # project through Node).
    # shortcut: those names are read off 0.164's binary, what each adds is not measured; an
    # unknown one would make Codex refuse to start, said at once - drop it then.
    OFF = (*(one for one in CodexCliClient.DISABLED if one != "code_mode_host"),
           "js_repl", "js_repl_tools_only", "request_permissions_tool", "standalone_web_search",
           "web_search_request", "search_tool", "codex_git_commit", "artifact")
    # The items it may begin in a session: its words, thoughts, plan and compaction; a patch
    # (asked about, and declined, before it is applied); an MCP call (another server's is asked
    # about and declined). Any other item - a tool of its own, whatever turned it on - ends the
    # session as soon as it is seen (`_unwanted`): before it acts where Codex begins it first.
    # shortcut: an item it sends only once done (imageView, webSearch) is caught after it acted,
    # and js_repl may send no item at all: for those the flags in `OFF` are the guard.
    # shortcut: by the item types of 0.164's protocol; one code mode sends around an MCP call is
    # not measured - it would end every session: add it here once seen live.
    # shortcut: B-415 (live, 8 Nov, gpt-6-luna): a lead began collabAgentToolCall with
    # multi_agent off - an item, not a request, so nothing to decline: the session still stops
    # (its agents at work end its row, `_lead_ended`); measure which flag turns it off.
    ITEMS = frozenset({"userMessage", "agentMessage", "reasoning", "plan", "contextCompaction",
                       "fileChange", "mcpToolCall"})
    # Requests declined in one turn before it is ended: a model that keeps trying its patch tool
    # counts no step, keeps the silence limit off and spends tokens all the while.
    # shortcut: a guess (the measured turn asked once, then used write_file); tune it live.
    DECLINES_AT_MOST = 3

    def _unwanted(self, item: dict, no_shell: bool) -> str | None:
        kind = item.get("type")
        if kind is None or (isinstance(kind, str) and kind in self.ITEMS):
            return None
        return super()._unwanted(item, no_shell) or (
            f"{self.label} began a tool of its own ({str(kind)[:40]}); the session was stopped")

    # (Said of a line too long for Windows: `_fits`.)
    line_also = (f". As a session its line also switches {len(OFF)} tools of Codex's own off: "
                 "One run per model step or Native has a shorter one")

    async def stream_step(self, model_id, messages, tools, on_delta, on_thinking=None,
                          effort=None):
        raise OwnStop(f"{self.label} runs as a session, not step by step")

    def _native_arguments(
        self, root: Path, bridge_config: Path, withheld: tuple[str, ...] = (),
        linked: tuple[str, ...] = (), also: tuple[str, ...] = (),
    ) -> list[str]:
        # Native's line (the user's MCP servers, skills and plugins off, KOLONİ's server, its web
        # search and apps off), then the rest of its own tools off, before "app-server".
        line = super()._native_arguments(root, bridge_config, ("search", "fetch"))
        return [*line[:-1], *(one for name in self.OFF for one in ("-c", f"features.{name}=false")),
                line[-1]]

    async def _decide(
        self, method: str, params: dict, asked: _Asked, call_tool: CallTool, on_item: OnItem,
    ) -> dict:
        """A call of KOLONİ's own tools is let through (held to KOLONİ's rules where it runs);
        everything else is declined - a patch with why, steered into its turn (`_converse`).
        Never `call_tool`: here that is the agent's, and would put a call on its record."""
        if method == "mcpServer/elicitation/request" and params.get("serverName") == SERVER \
                and _dict(params.get("_meta")).get("codex_approval_kind") == "mcp_tool_call":
            return {"result": {"action": "accept", "content": {}}}
        # shortcut: a decline is in the log and the raw stream, not on the agent's record (a
        # session keeps no record of a CLI's own tools); record it if it is missed there.
        log.info("%s as a session: declined %s", self.label, method)
        asked.declined += 1
        if asked.declined >= self.DECLINES_AT_MOST:
            raise OwnStop(f"{self.label} asked {asked.declined} times for what KOLONİ declines "
                          "(its own patch tool, or another tool of its own), so the session was "
                          "stopped")
        if method == PATCH_ASKED:
            return {"result": DECLINED[method], "why": PATCH_REFUSED}
        return ({"result": DECLINED[method]} if method in DECLINED
                else {"error": {"code": -32601, "message": "KOLONİ declines this request"}})

    async def run_session(
        self, model_id: str, messages: list[dict], tools: list[dict] | None,
        call_tool: CallTool, on_text: Callable[[str], Awaitable[None]],
        on_message: Callable[[object], None] | None = None, effort: str | None = None,
        on_live: Callable[[dict], None] | None = None, queue_wait: float | None = None,
    ) -> SessionResult:
        """As `CliSessionClient.run_session`. Each tool call is a step of its own (it names no
        message: `on_message` is not told); nothing of a queue (`queue_wait`)."""
        server = ToolServer(tools or [], call_tool)
        workdir: Path | None = None

        async def on_item(phase: str, item: dict) -> None:
            # Its context and plan are shown live; a tool of its own that did anything (a
            # patch applied, another server's tool, a web search) ends the session.
            if phase == "live":
                if on_live:
                    on_live(item)
            elif phase == "completed" and item.get("status") not in ("failed", "declined"):
                server._end(OwnStop(f"{self.label} used a tool of its own "
                                    f"({item.get('tool') or item.get('type')}); the session "
                                    "was stopped"))

        try:
            workdir = Path(tempfile.mkdtemp(prefix="koloni-cli-"))
            await server.start()
            bridge_config = bridge_file(server, workdir)
            command, shim = self._command()
            arguments = await asyncio.to_thread(self._native_arguments, workdir, bridge_config)
            copies = await asyncio.to_thread(image_copies, messages, workdir)
            given = [{"type": "text", "text": build_session_prompt(messages, CODEX_SESSION_RULES),
                      "text_elements": []}, *({"type": "localImage", "path": copy}
                                              for copy in copies)]
            return await self._converse(
                [*command, *arguments], shim, given, workdir, server, on_text, on_item, {},
                call_tool, (), effort, bridge_config, no_shell=True)
        finally:
            await server.close()
            if workdir:
                shutil.rmtree(workdir, ignore_errors=True)


CLAUDE_RULES = """You are working as an agent inside KOLONİ, a workspace where several agents
work for one user. The input is a JSON document with "instructions" (who you are and how
to work) and "conversation" (everything so far, oldest first). Carry on from the end of
the conversation: do what the last user message asks.

Do the work in this project folder with your own tools, as you normally would. KOLONİ
shows the user what you do, and the user may be asked before a change or a command: a
refusal is their decision, not an error to work around.

The "koloni" MCP server gives you what your own tools cannot: spawn_agent, message_agent
and discuss reach the other agents of this turn, ask_user asks the user, create_role adds
a role, post_note and read_notes write and read the turn's shared notebook. Notes the
others leave reach you only with the result of one of these tools. Use them when the
instructions call for it.
Where the instructions or the conversation mention tools such as read_file, edit_file or
run_command, use your own equivalents.

When the work is done, say briefly, once, what you did and what you did not verify - in the
language of the last user message of the conversation, even after a sub-agent of your own
has reported back in another."""
# (Live, B-136's run: a Turkish question got its last answer in English, after its own
# background sub-agent's English report.)
# 27 / 93-C3: after the rules, where it goes on in its session of earlier turns (`run_native`).
RESUMED = """You are going on in your own session of earlier turns: this time "conversation"
holds only what came since your last answer in it, oldest first. The instructions are given
again as they stand now; where they differ from before, these stand. What the memory gave you
or recall found in earlier turns is what it held then: a record may have been removed or
corrected since - recall it again before you rely on it."""
# What a session's id may be to go on a command line or name a file (a uuid as Claude Code
# gives it): anything else, a planted `-...` say, is no session.
SESSION_ID = re.compile(r"[0-9A-Za-z][0-9A-Za-z-]{7,63}")


def forget_session(session: dict, runtime_root: Path) -> None:
    """A kept session's transcript gone (27): one that will not be resumed, or whose
    conversation is deleted. Only in a sign-in folder of KOLONİ's: one right inside this
    runtime's `cli-homes` once resolved (`limits.cli_home`; as a provider's folder is deleted).
    shortcut: where Claude Code keeps a session (`projects/<folder>/<id>.jsonl`, and
    `file-history/<id>`) is read off its folder layout, not measured; anything else it keeps
    of one stays. Measure live and add them."""
    home = Path(str(session.get("home"))).resolve()
    number = str(session.get("id"))
    homes = (runtime_root / "cli-homes").resolve()  # (limits.CLI_HOMES: limits imports this)
    if home.parent != homes or not SESSION_ID.fullmatch(number):
        return
    for transcript in home.glob(f"projects/*/{number}.jsonl"):
        transcript.unlink(missing_ok=True)
    shutil.rmtree(home / "file-history" / number, ignore_errors=True)


def since_its_last_word(messages: list[dict]) -> list[dict]:
    """What a session it goes on in has not seen: what came after its last answer (but the
    results of that answer's tool calls, which it was handed then). [] where it has none, or
    nothing came since: then it starts anew."""
    talk = [m for m in messages if m["role"] != "system"]
    last = next((at for at in range(len(talk) - 1, -1, -1) if talk[at]["role"] == "assistant"),
                None)
    if last is None:
        return []
    new = talk[last + 1:]
    while new and new[0]["role"] == "tool":
        new = new[1:]
    return new


# How Claude Code's shell tools begin the result of a command that failed.
# shortcut: from its tool results as known, not measured here (no CLI in tests); measure it
# on the next live run if a failed command still says "no exit code reported".
CLAUDE_EXIT = re.compile(r"(?:Error: )?Exit code (-?\d+)\b")

# Claude Code's own tools, by what they can do. Others are asked about in words.
CLAUDE_WRITES = ("Write", "Edit", "MultiEdit", "NotebookEdit")
# (Monitor runs a command and reads what it prints: its init `tools` on 2.1.310.)
CLAUDE_RUNS = ("Bash", "PowerShell", "Monitor")
# What only reads or ends a command it was let run in the background.
CLAUDE_SHELL_OUTPUT = ("BashOutput", "KillShell", "KillBash")
# What a role without the run tool is not given at all: the shells and what goes with them.
CLAUDE_SHELLS = (*CLAUDE_RUNS, *CLAUDE_SHELL_OUTPUT, "REPL")
# Its tools that reach out of this machine: not given where nobody can be asked about them.
CLAUDE_REACHES = ("WebFetch", "WebSearch")
# The one hook KOLONİ registers with it, by the id its requests name (`_control`).
HOOK = "koloni_pre_tool_use"
# 89m: and where it changes files, one at its end, which KOLONİ answers with the tests' word
# (`AgentRunner._tests_at_stop`); its wait, in seconds, longer than theirs (MAX_TIMEOUT).
# shortcut: the matcher's "timeout" is the Agent SDK's field, not measured live - measure it
# with tests over a minute before relying on it (else the CLI may stop waiting first).
STOP_HOOK = "koloni_stop"
STOP_WAIT = 660
# The tool that starts one of its own sub-agents: Agent (measured on 2026-10-06), Task in
# the init `tools` of 2.1.310.
CLAUDE_AGENTS = ("Agent", "Task")
# Its tools never given: they act later or elsewhere (a worktree, a schedule, a remote
# trigger, a push), ask the user themselves (KOLONİ's ask_user does), or run a workflow of
# its own whose steps are not known (2.1.310's init `tools`); nor those that reach its other
# sessions or designs (2.1.311's: measured 27 Oct 2026).
CLAUDE_NEVER = ("EnterWorktree", "ExitWorktree", "CronCreate", "CronDelete", "ScheduleWakeup",
                "RemoteTrigger", "PushNotification", "AskUserQuestion", "Workflow",
                "DesignSync", "SendMessage", "ListAgents")
# How long it may stay silent before it has taken the hook (`_control`).
START_SECONDS = 30.0
# How long it may stay silent after a turn's end that came before it read a steer (`_control`).
LATE_SECONDS = 30.0
# What of its init line is its own (where its memory, its socket and its session are):
# kept nowhere.
CLAUDE_OWN = frozenset({"memory_paths", "messaging_socket_path", "session_id"})
# Its tools that only look: the only ones a role limited to reading may use.
CLAUDE_READS = frozenset({
    "Read", "Glob", "Grep", "LS", "NotebookRead", "TodoWrite", "TodoRead", "ToolSearch",
})
# B-306: the names KOLONİ knows Claude Code's tools by; a Qoder tool named otherwise is a card.
CLAUDE_KNOWN = frozenset({*CLAUDE_READS, *CLAUDE_RUNS, *CLAUDE_WRITES, *CLAUDE_SHELL_OUTPUT,
                          *CLAUDE_AGENTS, *CLAUDE_REACHES})
# The first version whose setting sources alone keep the user's own plugins and skills out
# (measured on 2.1.311, 27 Oct 2026: 2.1.310 let them in), so KOLONİ's can be given.
SKILLS_FROM = (2, 1, 311)
# The plugin KOLONİ gives its skills in (`claude_plugin`): its skills are named `koloni:<name>`.
# shortcut: a plugin of the user's own named so, with a skill named as one KOLONİ gives,
# would pass `_control`'s look as KOLONİ's; none can load under KOLONİ's setting sources.
PLUGIN = "koloni"
# What the instructions of a Claude Code given its skills as its own say of them (B-151).
SKILLS_OWN = ("\n\nYour skills - ready instructions for kinds of work - are skills of your own "
              "here: load the one a job is for with your Skill tool.")
# 89g: a role offered to Claude Code as one of its own sub-agents (`--agents`) is named so; its
# tools reach KOLONİ's hook with that name as their `agent_type` (measured on 2.1.311, 27 Oct).
INSIDE = "koloni-"
# The version that was measured to do so: an older one is offered no role.
INSIDE_FROM = (2, 1, 311)
# A role's tools (KOLONİ's names) as Claude Code's own: never its Agent, nor KOLONİ's tools.
# shortcut: the names are those of the constants above, not measured in an `--agents` tools
# list (LS and NotebookRead may be gone from 2.1.311); and a role run so gets none of its skills,
# MCP servers or expert's knowledge. Measure and give them once a live run shows the need.
# Copilot's `customAgents`, agy's `--agent` and a Lead on an API model offer no role so (89g).
CLAUDE_OF = {"read_file": ("Read", "NotebookRead"), "list_dir": ("LS", "Glob"),
             "search": ("Grep", "Glob"), "write_file": ("Write",),
             "edit_file": ("Edit", "MultiEdit", "NotebookEdit"), "run_command": CLAUDE_SHELLS,
             "web_search": ("WebSearch",), "http_request": ("WebFetch",)}


def claude_without(withheld: tuple[str, ...]) -> list[str]:
    """Claude Code's own tools a run is started without (`--disallowedTools`)."""
    without: list[str] = list(CLAUDE_NEVER)
    if "write" in withheld:
        without += CLAUDE_WRITES
    if "run" in withheld:
        without += CLAUDE_SHELLS
    if "agents" in withheld:  # (B-385: its model is closed to agents)
        without += CLAUDE_AGENTS
    if "unasked" in withheld:
        # A turn nobody is watching, where nobody could be asked: none of its tools that reach
        # out.
        without += CLAUDE_REACHES
    # Slice 61: KOLONİ's web_search or http_request switched off on the Tools page.
    return without + [tool for tool, what in zip(CLAUDE_REACHES, ("fetch", "search"), strict=True)
                      if what in withheld and tool not in without]


def claude_tools(tools: list[str], withheld: tuple[str, ...] = ()) -> list[str]:
    """89g: a role's tools as Claude Code's own, less what its Lead's run is started without."""
    off = set(claude_without(withheld))
    return list(dict.fromkeys(
        one for tool in tools for one in CLAUDE_OF.get(tool, ()) if one not in off))


def inside_name(role: str) -> str:
    """89g: the name a role is offered to Claude Code by (lower-case letters, digits and -)."""
    return INSIDE + (re.sub(r"[^a-z0-9]+", "-", role.lower()).strip("-") or "role")


def claude_plugin(folder: Path, given: dict[str, str]) -> tuple[list[str], dict[str, str]]:
    """The role's skills, from KOLONİ's store, as one plugin for `--plugin-dir`; the names of
    those it holds, and why each other was left out. Each SKILL.md is written afresh with its
    name and description only (no `allowed-tools`, no `hooks`); a skill with a line that
    would run as it loads is left out, and so is one that cannot be copied - neither is given
    on that run, nor its text in the instructions (`run_native`, B-151).
    shortcut: the user's own document skills (their `anthropic-skills` plugin: docx, pptx,
    pdf, xlsx) are never copied or shipped; the user's chosen plugin could be passed by its
    folder, with their opt-in, as a second --plugin-dir."""
    held, left = [], {}
    for name, kept in given.items():
        target = folder / "skills" / name
        try:
            text = Path(kept, "SKILL.md").read_text(encoding="utf-8")
            if RUNS_AS_IT_LOADS in text:
                left[name] = "it runs a command when it loads"
                continue
            meta, body = front(text)
            shutil.copytree(kept, target, ignore=lambda at, _names, top=Path(kept): (
                ["SKILL.md"] if Path(at) == top else []))
            (target / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: {json.dumps(meta.get('description', ''))}"
                f"\n---\n\n{body}\n", encoding="utf-8")
            held.append(name)
        except OSError as exc:  # (a name Windows takes for a device, say: con, nul)
            log.warning("the skill %s is not given to Claude Code as its own: %s", name, exc)
            left[name] = "it could not be copied"
            shutil.rmtree(target, ignore_errors=True)
    if held:
        (folder / ".claude-plugin").mkdir(parents=True)
        (folder / ".claude-plugin" / "plugin.json").write_text(json.dumps({
            "name": PLUGIN, "description": "The skills KOLONİ gives this agent's role"}),
            encoding="utf-8")
    return held, left


def claude_names(folder: Path) -> set[str]:
    """The names of the skills and commands in a Claude Code folder (`.claude`): their
    folder and file names, never what is in them. Raises OSError."""
    names: set[str] = set()
    if (folder / "skills").is_dir():
        names |= {p.name for p in (folder / "skills").iterdir() if p.is_dir()}
    return names | {p.stem for p in (folder / "commands").rglob("*.md")}


def own_names(env: dict[str, str]) -> set[str]:
    """The names of the user's own Claude Code skills and commands (`~/.claude`'s, or
    CLAUDE_CONFIG_DIR's).
    shortcut: one named as a built-in is taken for the user's (no list of built-ins is
    kept); rename it, or keep the list, if a user is stopped so."""
    home = Path(env.get("CLAUDE_CONFIG_DIR") or os.environ.get("CLAUDE_CONFIG_DIR")
                or Path.home() / ".claude")
    try:
        return claude_names(home)
    except OSError:
        raise OwnStop("your own Claude Code skills and commands could not be listed, so "
                      "KOLONİ cannot tell them from its own") from None


def only_given(tool: str, given_input: dict, skills_given: set[str],
               plugin: str | None) -> bool:
    """A use that only reads what KOLONİ gave this run - one of its skills, as KOLONİ's own
    use_skill reads one, or a file of one by its full path - and so takes no card.
    shortcut: Skill's `skill` field is the Agent SDK's name for it; one named otherwise goes
    to KOLONİ as any other tool (a card), so check it live."""
    if tool == "Skill":
        return given_input.get("skill") in skills_given
    path = given_input.get("file_path")
    if tool != "Read" or not plugin or not isinstance(path, str) or not Path(path).is_absolute():
        return False
    if "\x00" in path:  # (3.13+ resolve() no longer raises on one)
        return False
    return Path(plugin, "skills").resolve() in Path(path).resolve().parents


def _control_line(line: dict, replies: dict[str, asyncio.Future],
                  answering: dict[object, asyncio.Future],
                  answer: Callable[[object, dict], Awaitable[None]]) -> bool:
    # `_control`'s read of a control line of the protocol's; False: the line is none.
    if line.get("type") == "control_response":
        response = _dict(line.get("response"))
        future = replies.get(str(response.get("request_id")))
        if future is not None and not future.done():
            future.set_result(response)
        return True
    if line.get("type") == "control_cancel_request":
        # It no longer waits for that answer: its card is closed, as
        # Stop closes one (`AgentRunner._native_work`), never a yes.
        withdrawn = answering.get(line.get("request_id"))
        if withdrawn is not None:
            withdrawn.cancel()
        return True
    if line.get("type") == "control_request":
        number = line.get("request_id")
        answering[number] = asyncio.ensure_future(
            answer(number, _dict(line.get("request"))))
        return True
    return False


class ClaudeNativeClient(CodexNativeClient):
    """Claude Code working natively: its own tools and sub-agents, in the project folder
    - and asking KOLONİ before one of its tools needs leave. It loads the project's own
    settings only; the user's personal setup (skills, plugins, hooks, MCP servers) only
    where the provider says so (`own_setup`).

    Since slice 89b it runs over its stream-json control protocol (`_control`): one
    PreToolUse hook comes before every tool of its own - reads and harmless commands too
    (measured on 2.1.310, 24 Oct 2026) - and hands it to `can_use_tool`, which KOLONİ answers.
    """

    command = "claude"
    label = "Claude Code"
    asks = True
    looks_by_running = False  # it has a Read of its own
    # Whether a tool it ran unasked counts so though it failed (Qoder, not measured: B-306).
    failed_unasked = False
    # Its own writes are asked as they come (B-190 measured a Spec writer so): left as it is.
    starts_read_only = False
    rules = CLAUDE_RULES
    efforts = levels_of("claude_cli")
    # Its own sign-in's secret variables, as its documentation names them (Settings,
    # environment variables). shortcut: named from that page as known, not read here (no
    # network); Bedrock's, Vertex's and Foundry's sign-ins are held back - keep theirs once
    # one is used.
    logins = frozenset({"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"})

    def __init__(self, *args, own_setup: bool = False, **more):
        super().__init__(*args, **more)
        self._own_setup = own_setup
        # It loaded commands KOLONİ did not give once (`_control`): no skill is given again.
        self._plugins_off = False

    @property
    def resumes(self) -> bool:
        """27 / 93-C3: whether its sessions are kept, to be resumed - only Claude Code signed in
        for KOLONİ alone (K-claude-hesap: `home`), so that they are kept in KOLONİ's folder.
        shortcut: not with the user's own ~/.claude, where every turn's transcript would be
        kept (and listed by their own `claude --resume`); the user decides that. The kept ones
        pile up in `home`: clear them if needed."""
        return self.command == "claude" and self.home is not None

    resume_flag = "--resume"
    # What it says of a session it does not have, where measured: only that falls back to a new
    # one (`run_native`); None: any failure before it said or did anything.
    NO_SESSION: re.Pattern | None = None

    def _under(self, model_id: str, root: str, withheld: tuple[str, ...],
               linked: tuple[str, ...], also: tuple[str, ...], level: str | None) -> str:
        """What a session of it is started under - its sign-in folder, model, setup, folders,
        permission level and what is withheld: another of any of these starts a new session,
        so that none goes on with more leave, elsewhere or as another account than it began."""
        return hashlib.sha256(json.dumps([
            str(self.home), self._model, model_id, self._own_setup, root, sorted(withheld),
            list(linked), list(also), level]).encode()).hexdigest()

    async def _skills_given(self, folder: Path, given: dict[str, str],
                            root: Path) -> tuple[list[str], dict[str, str]] | None:
        """The role's skills as a plugin in `folder` (`claude_plugin`: those it holds, and why
        each other is not given), for a version that keeps the user's own out by its setting
        sources alone (asked each run), in a project with no skills or commands of its own -
        they would load with KOLONİ's, unasked (a cloned repo's, a line of which can run as it
        loads); None: none given so (its instructions hold them whole)."""
        if self._plugins_off:
            return None
        try:
            if await asyncio.to_thread(claude_names, root / ".claude"):
                return None
        except OSError:
            return None
        if not await self._from(SKILLS_FROM):
            return None
        return await asyncio.to_thread(claude_plugin, folder, given)

    async def _from(self, version: tuple[int, int, int]) -> bool:
        """Whether its version (`--version`, asked each time) is this one or later."""
        found = re.match(r"(\d+)\.(\d+)\.(\d+)", await self._version())
        return bool(found) and tuple(map(int, found.groups())) >= version

    def talker(self) -> CliStepClient:
        """The same Claude Code as a session with its own tools off: how it speaks where
        nobody may change anything (a discussion, an answer to another agent)."""
        session = ClaudeSessionClient(
            self._executable, self._model, self._timeout, self._which, self._launcher,
            self._env, self.server, self._homes, self.home,
        )
        session.on_limits = self.on_limits  # it says its plan's limits that way too
        return session

    def _native_env(self, workdir: Path) -> dict[str, str]:
        # An approval, or a whole sub-agent, can take a long time.
        return {"MCP_TOOL_TIMEOUT": TOOL_WAIT_MS}

    def _native_arguments(
        self, root: Path, bridge_config: Path, withheld: tuple[str, ...] = (),
        linked: tuple[str, ...] = (), also: tuple[str, ...] = (),
    ) -> list[str]:
        config = bridge_config.parent / "mcp.json"
        config.write_text(json.dumps({"mcpServers": {SERVER: {
            "command": sys.executable,
            "args": [mcp_bridge.__file__, str(bridge_config)],
        }}}), encoding="utf-8")
        arguments = [
            "-p",
            # Its control protocol (`_control`): KOLONİ's hook before every tool, and its
            # permission prompts on stdin and stdout.
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            # Whatever would prompt is asked of KOLONİ, at every permission level. (Its
            # --help no longer lists "default"; 2.1.310's init says permissionMode "default".)
            "--permission-mode", "default",
            "--permission-prompt-tool", "stdio",
            "--mcp-config", str(config),
            # (Taken off by `run_native` for a run whose session is kept: 27.)
            "--no-session-persistence",
        ]
        # Measured on 9 Oct 2026: in a working copy its own Read refuses to go through
        # a link to a folder of the project's ("outside the allowed working directories").
        # Its Read, Grep and Glob in an --add-dir folder reach the hook too (`_approve`
        # judges the path they name; a link in it is followed as Claude Code sees fit).
        for folder in (*linked, *also):
            arguments += ["--add-dir", folder]
        if not self._own_setup:
            # Measured on 10 Oct 2026: without this it starts with the user's own skills,
            # plugins and their hooks, which KOLONİ neither shows nor approves.
            # On a model server none at all (K-cli-llama): a project's settings `env` or
            # `apiKeyHelper` could send its prompts or a key elsewhere. KOLONİ's own hook,
            # MCP server and settings come by `initialize`, --mcp-config and --settings.
            # shortcut: the project's CLAUDE.md and allow rules are not loaded there either
            # (not measured); measure that with the real CLI before relying on it.
            arguments += ["--setting-sources", "" if self.server else "project,local"]
            # Measured on 2.1.310 (24 Oct 2026): the user's own commands and skills are in
            # its answer to `initialize` whatever the setting sources; this keeps them out -
            # and every skill with them: a project's own too, unprefixed, which nothing else
            # would show. Only a run given KOLONİ's skills goes without it, from 2.1.311
            # (`run_native`, `_skills_given`), and `_control` stops one that loads others.
            arguments.append("--disable-slash-commands")
            # Measured on 2.1.311 (27 Oct 2026): a project's own .claude/settings.json hooks
            # (SessionStart, UserPromptSubmit, ...) run their commands unasked under the
            # setting sources above - a cloned repo's would. This keeps them off; KOLONİ's own
            # hook comes over `initialize` and still holds every tool (measured the same day).
            arguments += ["--settings", json.dumps({"disableAllHooks": True})]
        # A turn nobody is watching, where nobody could be asked: no MCP server but KOLONİ's
        # (`claude_without`: none of its tools that reach out). (Its hook is asked first all the
        # same: measured on 2.1.310, a project's allow rules do not pass it by.)
        if not self._own_setup or "unasked" in withheld:
            arguments.append("--strict-mcp-config")  # only the server of --mcp-config
        arguments += ["--disallowedTools", ",".join(claude_without(withheld))]
        # KOLONİ's own tools need no leave.
        offered = [PREFIX + name for name in self._offered]
        if offered:
            arguments += ["--allowedTools", ",".join(offered)]
        if self._model:
            arguments += ["--model", self._model]
        return arguments  # the prompt comes on stdin

    async def _control(  # noqa: C901
        self, argv, shim, prompt, root: Path, server: ToolServer, on_text, on_item: OnItem,
        env: dict[str, str], call_tool: CallTool, on_live: OnLive | None = None,
        tests_at_stop: bool = False,
        report_schema: dict | None = None,
    ) -> SessionResult:
        """Claude Code over its stream-json control protocol (slice 89b; the names are those
        of Anthropic's Agent SDK), started and ended as `_work` starts and ends it. Before it
        is given the prompt it takes one PreToolUse hook for every tool (and says it applied
        it). The hook lets through the tools KOLONİ offered it (they are held to KOLONİ's
        rules where they run) and
        answers "ask" for every other, so that its one decision is KOLONİ's answer to the
        `can_use_tool` that follows (`AgentRunner._approve`, as `CodexNativeClient._decide`
        asks it): a card waits there, never in the hook, whose own wait is short. A Claude
        Code that does not take the hook is stopped, never run without it; a tool it runs
        all the same is on record as unasked."""
        # Where it was given KOLONİ's skills (`_skills_given`), its commands are on: those
        # skills, and the names of the user's own it must not have loaded (`own_names`).
        plugin = argv[argv.index("--plugin-dir") + 1] if "--plugin-dir" in argv else None
        ours_skills = {f"{PLUGIN}:{p.name}" for p in Path(plugin, "skills").iterdir()} \
            if plugin else set()
        own = await asyncio.to_thread(own_names, self._env) if plugin else set()
        try:
            process, job = await self._start(argv, shim, root, env)
        except OSError as exc:
            raise OwnStop(f"{self.label} could not be started: {exc.strerror or exc}") from None
        stdin, stdout, errors = process.stdin, process.stdout, process.stderr
        assert stdin is not None and stdout is not None and errors is not None  # all piped
        stderr = asyncio.ensure_future(complaints(errors, (server.key,)))
        loop = asyncio.get_running_loop()
        replies: dict[str, asyncio.Future] = {}  # the ids of KOLONİ's requests -> answers
        answering: dict[object, asyncio.Future] = {}  # its requests' ids -> their answering
        writing = asyncio.Lock()
        ours = {PREFIX + name for name in self._offered}  # KOLONİ's tools it was given
        asked: set[str] = set()  # the tool uses KOLONİ was asked about
        roles_of: dict[str, str] = {}  # 89g: tool uses of a role run inside it -> its name
        # Its tools at work, and its requests KOLONİ is answering: none of it is silence.
        busy: set[str] = set()
        translate = self._translator()
        heard = time.monotonic()
        said = False
        usage: dict | None = None
        earlier: dict | None = None  # its turns' usage while a sub-agent of it works on
        reported: str | None = None  # the model it says it is using
        failure: str | None = None
        limited = None  # what it said of its plan's limit, if it turned this run away
        own_word: tuple | None = None  # what its own word says a failure is (`own_error`)
        unhooked: str | None = None  # why it did not take the hook
        leaked: str | None = None  # the user's own plugins' commands it loaded
        broke: BaseException | None = None  # what answering a request of its own ended in
        opened = False  # it took the hook and was given the prompt
        live = False  # its turn runs: a steer is read in it (89d)
        # The words last steered into it, until it takes a turn on them; whether it said
        # anything after they were written (its message ids are in no order: that it has is
        # not that it read them, so a turn's end then is read on past all the same).
        steered: str | None = None
        after = False
        late = False  # a turn has ended since: it may take one more on them
        measured: object = None  # 89j: the message of its own its context was last asked after
        measuring = itertools.count(1)
        measures: set[asyncio.Future] = set()  # (at most one at a time)
        handed: object = None  # what its last result handed back in its schema (89p)
        asked_again = False  # its report was asked for once more (93-B6)
        settled = False  # what it handed back was said
        session_id: str | None = None  # 27: its session, as it says it (kept nowhere else)

        def end_now() -> None:
            if job:
                job.terminate()
            with contextlib.suppress(ProcessLookupError):
                process.kill()

        server.on_end = end_now

        async def send(message: dict) -> None:
            async with writing:
                stdin.write((json.dumps(message) + "\n").encode())
                await stdin.drain()

        async def hand_back(may_ask: bool) -> bool:
            """89p / 93-B6, once its turns are over: what it last handed back in its schema is
            its report, or why not. True: it did not keep to the schema and is asked for it once
            more (`may_ask`), with what was wrong - the schema is on its command line."""
            nonlocal asked_again, settled
            assert report_schema is not None  # (asked only where one was given)
            errors = None if handed is None else schema_errors(handed, report_schema)[:5]
            if errors and may_ask and not asked_again:
                # (89m's Stop hook ends that turn too: MAX_SENT_BACK counts across both turns.)
                asked_again = True
                with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                    await send(prompt_line(REPORT_AGAIN.format(errors="; ".join(errors))))
                await on_item("completed", {"type": "structured_report", "asked_again": errors})
                return True
            settled = True
            await on_item("completed", {"type": "structured_report", **(
                {"report": handed} if handed is not None and not errors
                else {"errors": errors or []})})
            return False

        def prompt_line(content: object) -> dict:
            # shortcut: as the Agent SDK's client sends a prompt; check the session id live.
            return {"type": "user", "message": {"role": "user", "content": content},
                    "parent_tool_use_id": None, "session_id": "default"}

        async def steer(text: str) -> bool:
            """89d: `text` as a user line while its turn runs - measured 25 Oct: read and obeyed
            in the same turn. True: written, which is not yet that it read it. Never an error
            that ends the run."""
            nonlocal steered, after
            if not live:
                return False
            # (Before the write: a result read while it waits for the pipe is read on past.)
            steered, after, written = text, False, False
            try:
                async with asyncio.timeout(STEER_SECONDS):
                    async with writing:
                        stdin.write((json.dumps(prompt_line(text)) + "\n").encode())
                        written = True
                        await stdin.drain()
            except TimeoutError:
                pass  # (written, it waits for room in the pipe: it is on its way)
            except Exception:
                written = False
            if not written:
                steered = None
            return written

        async def answer(number: object, request: dict) -> None:
            nonlocal heard, broke
            key = f"asked {number}"
            busy.add(key)
            try:
                reply = await self._control_reply(request, call_tool, on_item, ours,
                                                  ours_skills, plugin, roles_of, asked,
                                                  report_schema)
                if reply is None:
                    with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                        await send({"type": "control_response", "response": {
                            "subtype": "error", "request_id": number,
                            "error": f"KOLONİ does not answer {request.get('subtype')}"}})
                    return
                with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                    await send({"type": "control_response", "response": {
                        "subtype": "success", "request_id": number, "response": reply}})
            except Exception as exc:  # a stop of KOLONİ's own, or a bug: its work ends here
                broke = broke or exc
                end_now()
            finally:
                busy.discard(key)
                answering.pop(number, None)
                heard = time.monotonic()

        async def read() -> None:  # noqa: C901
            nonlocal heard, said, usage, earlier, failure, reported, limited, own_word, live, \
                steered, after, late, measured, handed, session_id
            try:
                async for raw in stdout:
                    heard = time.monotonic()
                    written = raw.decode("utf-8", errors="replace")
                    lines = _events(written)
                    # What it and KOLONİ say to each other is kept nowhere: its answer to
                    # `initialize` can say whose account it is, a hook where its transcripts are.
                    # Nor where its own memory, socket and session are (its init line).
                    if not [m for m in lines if str(m.get("type")).startswith("control_")]:
                        feed("stdout", "\n".join(json.dumps(
                            {k: v for k, v in m.items() if k not in CLAUDE_OWN},
                            ensure_ascii=False) for m in lines)
                            if any(CLAUDE_OWN & m.keys() for m in lines) else written,
                            (server.key,))
                    for line in lines:
                        if line.get("type") in ("system", "result") \
                                and isinstance(line.get("session_id"), str):
                            session_id = line["session_id"]
                        if _control_line(line, replies, answering, answer):
                            continue
                        if line.get("type") == "assistant" and not measures \
                                and not line.get("parent_tool_use_id") \
                                and _dict(line.get("message")).get("id") != measured:
                            measured = _dict(line.get("message")).get("id")  # once a step
                            task = asyncio.ensure_future(
                                self._measure(send, replies, loop, measuring, on_item))
                            measures.add(task)
                            task.add_done_callback(measures.discard)
                        if line.get("type") == "assistant" and steered is not None \
                                and not line.get("parent_tool_use_id"):
                            if late:
                                steered = None  # it took a turn on them
                            else:
                                after = True
                        for event in translate(line):
                            kind, item = event.get("type"), _dict(event.get("item"))
                            if kind == "model":
                                reported = str(event.get("model") or "") or reported
                            elif kind == "rate_limit_event":
                                limited = self._limit_event(event)
                            elif kind == "own_error":
                                own_word = event["failure"]
                            elif kind == "busy":
                                (busy.add if event.get("on") else busy.discard)(str(event["id"]))
                                if event.get("on"):
                                    await on_item("announced", {
                                        "id": str(event["id"]), "parent": event.get("parent")})
                            elif kind == "error":
                                failure = _brief(self._hide(str(event.get("message"))))
                                if event.get("result_text"):
                                    limited = limited or RESULT_TEXT
                            elif kind == "turn.completed":
                                # Each result's usage is per turn, measured on 2.1.311 (27 Oct).
                                told = _dict(event.get("usage"))
                                told = {key: told.get(key) if earlier is None else
                                        _sum(earlier.get(key), told.get(key)) for key in told}
                                live = False  # (a steer now could start a turn nobody reads)
                                if event.get("more"):
                                    # Its sub-agent works on in the background, and it will
                                    # take another turn on its report (B-136).
                                    earlier = told
                                    continue
                                usage = told
                                if event.get("structured") is not None:  # (89p: the last kept)
                                    handed = event["structured"]
                                if steered is not None and not late:
                                    # shortcut: not measured - a steer it did not read in its
                                    # turn may start one more: read on to its end, or to
                                    # LATE_SECONDS of silence (every steered run's end waits
                                    # so). Read in its turn or dropped stays unknown until its
                                    # own word on a user line (--replay-user-messages) is
                                    # measured live (89d).
                                    earlier, late = told, True
                                    continue
                                if report_schema is not None and await hand_back(True):
                                    # Read on to its answer, or to LATE_SECONDS of silence:
                                    # then what it handed first stands (its usage so far too).
                                    earlier, late, heard = told, True, time.monotonic()
                                    continue
                                return  # it has finished; whatever lingers is ended below
                            elif kind in ("item.started", "item.completed"):
                                said = await self._control_item(kind, item, said, asked,
                                                                asked_again, busy, on_text,
                                                                on_item)
                    if server.ended:
                        return
                await process.wait()
            finally:
                for future in replies.values():  # nothing more will answer them
                    if not future.done():
                        future.set_result({"subtype": "error", "error": "it ended"})

        async def talk() -> None:
            nonlocal unhooked, opened, leaked, live
            reading = asyncio.ensure_future(read())
            try:
                replies["init"] = loop.create_future()
                await send({"type": "control_request", "request_id": "init", "request": {
                    "subtype": "initialize",
                    "hooks": {"PreToolUse": [{"matcher": None, "hookCallbackIds": [HOOK]}],
                              **({"Stop": [{"matcher": None, "hookCallbackIds": [STOP_HOOK],
                                            "timeout": STOP_WAIT}]} if tests_at_stop else {})}}})
                told = await replies["init"]
                if told.get("subtype") != "success" or _dict(
                        told.get("response")).get("hooks_applied") is not True:
                    if not reading.done():  # (one that ended says so below, in its words)
                        unhooked = _brief(self._hide(str(told.get("error") or (
                            "it did not apply KOLONİ's hook"))))
                    return
                listed = _dict(told.get("response")).get("commands")
                names = [one if isinstance(one, str) else str(_dict(one).get("name") or "")
                         for one in (listed if isinstance(listed, list) else ())]
                theirs = sorted({name for name in names
                                 if name in own or ":" in name and name not in ours_skills})
                if theirs and plugin:
                    # A plugin's command or skill (`plugin:name`) KOLONİ did not give, or one
                    # named as the user's own: what KOLONİ neither shows nor approves (none
                    # of the project's: a project with any is given no skills). No run of
                    # this client is given skills again: its commands stay off.
                    self._plugins_off = True
                    leaked = ", ".join(theirs[:5])
                    return
                opened = True
                await send(prompt_line(prompt))
                live = True
                if on_live:
                    on_live(steer)
                await reading
            except (BrokenPipeError, ConnectionResetError):
                return  # it is gone: how it ended is said below
            finally:
                reading.cancel()
                with contextlib.suppress(BaseException):
                    await asyncio.shield(asyncio.wait({reading}, timeout=2))

        talking = asyncio.ensure_future(talk())
        try:
            # The limit is on silence, as for `_work`; not a word before it took the hook is
            # a Claude Code that could not be asked first.
            gone = Exited(process, job)
            while not talking.done():
                await asyncio.wait({talking}, timeout=min(1.0, self._timeout / 4))
                quiet = time.monotonic() - max(heard, server.last_reply)
                working = server.in_flight > 0 or bool(busy)
                if not talking.done() and await gone():
                    break  # (said below as it ended)
                limit = self._timeout if opened else min(self._timeout, START_SECONDS)
                if late and not working and quiet > LATE_SECONDS:
                    break  # no turn came on what was steered (or asked again): it has finished
                if not talking.done() and not working and quiet > limit:
                    if not opened:
                        unhooked = f"it did not answer for {limit:g} seconds"
                        break
                    raise ModelUnavailable(
                        f"{self.label} sent nothing for {self._timeout:g} seconds")
            if talking.done():
                try:
                    talking.result()
                except ValueError:
                    raise ModelUnavailable(
                        f"{self.label} sent a line too long to read") from None
            if report_schema is not None and usage is not None and not settled \
                    and broke is None and not server.ended:
                await hand_back(False)  # (no turn came after its last result: it stands)
        finally:
            if on_live:
                on_live(None)
            if opened and usage is None:
                # A turn not finished (Stop, say) is asked to stop first; ended below if not.
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(asyncio.shield(send({
                        "type": "control_request", "request_id": "stop",
                        "request": {"subtype": "interrupt"}})), 2)
                    stdin.close()
                    await asyncio.wait_for(asyncio.shield(process.wait()), 2)
            left = {talking, *answering.values(), *measures}
            for task in left:
                task.cancel()
            with contextlib.suppress(BaseException):
                await asyncio.shield(asyncio.wait(left, timeout=2))
            await self._end(process, job)
            complaint = b""
            with contextlib.suppress(Exception):
                complaint = await asyncio.wait_for(asyncio.shield(stderr), 2)
            stderr.cancel()
        if broke is not None:
            raise broke
        if server.ended:
            raise server.ended
        reason = _brief(self._hide(complaint.decode("utf-8", errors="replace")))
        if leaked:
            raise OwnStop(f"{self.label} {await self._version()} loaded commands or skills "
                          f"KOLONİ did not give ({leaked}): it was stopped before it acted. Its "
                          "next run has its commands and skills off")
        if not opened:
            why = unhooked or how_it_ended("it", process.returncode, reason)
            raise OwnStop(f"{self.label} {await self._version()} could not be asked before it "
                          f"acts ({why}); run it as a session instead")
        if usage is None:
            failed = ModelUnavailable(
                f"{self.label} reported an error: {failure}" if failure
                else f"{self.label} ended while its sub-agent was still at work in the "
                     "background: that work and its report were cut off" if earlier is not None
                else how_it_ended(self.label, process.returncode, reason))
            failed.failure = classed(limited, own_word)
            raise failed
        if steered is not None and not after:  # (no error: its work is done; it is on record)
            await on_item("completed", {"type": "steer_unread", "text": steered})
        sent, made = usage.get("input_tokens"), usage.get("output_tokens")
        return SessionResult(
            sent if isinstance(sent, int) else None, made if isinstance(made, int) else None,
            reported, count_of(usage.get("cached_input_tokens")),
            count_of(usage.get("cache_creation_input_tokens")),
            {"id": session_id} if session_id else None,
        )

    async def _control_reply(
        self, request: dict, call_tool: CallTool, on_item: OnItem, ours: set[str],
        ours_skills: set[str], plugin: str | None, roles_of: dict[str, str], asked: set[str],
        report_schema: dict | None,
    ) -> dict | None:
        # `_control`'s answer to a control request of its own; None: one it does not answer.
        given = _dict(request.get("input"))
        if request.get("subtype") == "hook_callback" \
                and request.get("callback_id") == STOP_HOOK:
            # Its end (89m): {} lets it finish, {"decision": "block", ...} sends it back.
            _ok, said = await call_tool("stop", json.dumps(given))
            reply = _dict(json.loads(said))
        elif request.get("subtype") == "hook_callback":
            tool = str(given.get("tool_name") or "")
            # 89g: a role run inside it is held to its own tools by `_approve`, which
            # is asked about every one - KOLONİ's too, which would be its Lead's.
            kind = str(given.get("agent_type") or "")
            if kind.startswith(INSIDE):
                roles_of[str(given.get("tool_use_id") or request.get("tool_use_id")
                             or "")] = kind
            # Its StructuredOutput only hands back the report (89p): no card.
            # shortcut: let through by its name, not measured under KOLONİ's hook.
            handing = bool(report_schema) and tool == ClaudeCliClient.OWN_TOOL
            reply = {"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow" if (tool in ours or handing)
                and not kind.startswith(INSIDE) else "ask"}}
        elif request.get("subtype") == "can_use_tool":
            tool = request.get("tool_name")
            # (Measured on 2.1.310: it names the tool use, as its hook did. One that
            # names none is refused by `_approve`.)
            use_id = str(request.get("tool_use_id") or "")
            asked.add(use_id)
            if use_id:  # (only it writes here: no model can make such a request up)
                await on_item("announced", {"id": use_id})
            if use_id not in roles_of and only_given(
                    str(tool), _dict(request.get("input")), ours_skills, plugin):
                reply = {"behavior": "allow", "updatedInput": request.get("input")}
            else:
                _ok, verdict = await call_tool("approve", json.dumps({
                    "tool_name": tool, "input": request.get("input"),
                    "tool_use_id": use_id,
                    **({"agent_type": roles_of[use_id]} if use_id in roles_of else {})}))
                reply = _dict(json.loads(verdict))
                reply.pop("koloni", None)  # (KOLONİ's mark, for Codex: not its answer)
        else:
            return None
        return reply

    async def _measure(self, send: Callable[[dict], Awaitable[None]],
                       replies: dict[str, asyncio.Future], loop: asyncio.AbstractEventLoop,
                       measuring: Iterator[int], on_item: OnItem) -> None:
        """89j: how full its context is, by its own count (`get_context_usage`). "summary"
        answers from its last response's usage, with no token-count call; never awaited
        where its lines are read, and nothing is said where it does not answer."""
        number = f"context_{next(measuring)}"
        replies[number] = loop.create_future()
        try:
            await send({"type": "control_request", "request_id": number, "request": {
                "subtype": "get_context_usage", "detail": "summary"}})
            told = _dict((await asyncio.wait_for(replies[number], 10)).get("response"))
        except Exception:
            return
        finally:
            replies.pop(number, None)
        # (`maxTokens`: what its own `percentage` is of.)
        # shortcut: `detail` and these fields are read off 2.1.x's schema, not sent to a
        # live CLI: one that refuses `detail` shows nothing - measure live. And a step
        # asked about while the last ask is open is skipped, "summary" counting its last
        # finished response: the fill can be a step behind.
        filled =_filled(told.get("totalTokens"), told.get("maxTokens"))
        if filled:
            await on_item("live", filled)

    async def _control_item(self, kind: str, item: dict, said: bool, asked: set[str],
                            asked_again: bool, busy: set[str], on_text,
                            on_item: OnItem) -> bool:
        # `_control`'s read of one of its tool uses, or words; what `_heard` makes of `said`.
        use_id = str(item.get("id") or "")
        if kind == "item.completed" and use_id and use_id not in asked \
                and (self.failed_unasked
                     or item.get("status") != "failed"):
            # It ran this without asking KOLONİ: past its hook. (One
            # that failed, or its own rules refused, did not run.)
            item["unasked"] = [
                change.get("path") for change in item.get("changes") or []
            ] if item.get("type") == "file_change" else True
        if asked_again and item.get("type") == "agent_message":
            return said  # (93-B6: its words on handing it again are not
            # its report - those of its answer before stand)
        return await self._heard(kind, item, said, busy, on_text, on_item)

    def _translator(self) -> Callable[[dict], list[dict]]:
        using: dict[str, dict] = {}  # tool_use id -> the tool_use block, until its result
        # Its own sub-agents, by the id of the Agent tool use that started each: whether
        # KOLONİ has been told it started, whether it has been seen at work, and the last
        # thing it said. And for a tool use made inside one, which one.
        subs: dict[str, dict] = {}
        inside: dict[str, str] = {}
        # Those said to be done: what still comes from one is put down to it all the same.
        ended: set[str] = set()

        def translate(event: dict) -> list[dict]:
            kind = event.get("type")
            if kind == "system" and event.get("subtype") == "init":
                return [{"type": "model", "model": event.get("model")}]
            if kind == "rate_limit_event":
                return [event]  # what it says of its plan's limits: read in `_work`
            if kind == "system" and event.get("subtype") == "task_started":
                return _task_started(event, using, subs, inside)
            if kind == "system" and event.get("subtype") == "task_notification":
                return _task_notified(event, subs, inside, ended)
            if kind == "assistant":
                return _assistant(event, using, subs, inside, ended)
            if kind == "user":
                return _tool_results(event, using, subs, inside, ended)
            if kind == "result":
                return _turn_result(event, subs)
            return []

        return translate


# The parts of `ClaudeNativeClient._translator`: `using`, `subs`, `inside` and `ended` are its
# state, the same objects in each.
def _sub_begin(use_id: str, subs: dict[str, dict], inside: dict[str, str]) -> list[dict]:
    """The sub-agent is at work - told once, at the first sign of it: not when the
    tool is asked for, which is before leave for it is given."""
    sub = subs[use_id]
    if sub["started"]:
        return []
    sub["started"] = True
    return [{"type": "item.started", "item": {
        "type": "sub_agent", "id": use_id, "server": "claude", "tool": sub["tool"],
        "arguments": sub["given"], "parent": inside.get(use_id)}}]


def _sub_end(use_id: str, status: str, said: str, subs: dict[str, dict],
             inside: dict[str, str], ended: set[str]) -> list[dict]:
    """The sub-agent is done. What the CLI gives as its report (or the reason it
    failed) is what is kept; only without one, the last thing it was heard saying."""
    told = _sub_begin(use_id, subs, inside)
    sub = subs.pop(use_id)
    ended.add(use_id)
    return [*told, {"type": "busy", "id": use_id, "on": False},
            {"type": "item.completed", "item": {
        "type": "sub_agent", "id": use_id, "status": status,
        "text": said or sub["words"]}}]


def _sub_within(event: dict, subs: dict[str, dict], inside: dict[str, str],
                ended: set[str]) -> tuple[str | None, list[dict]]:
    """The sub-agent an event comes from, if it is one KOLONİ knows."""
    parent = str(event.get("parent_tool_use_id") or "")
    if parent in ended:
        return parent, []
    if parent not in subs:
        return None, []
    told = _sub_begin(parent, subs, inside)
    # Only what it says or asks for itself shows it at work: the task it was
    # handed may be in the stream before the tool that launched it has returned.
    subs[parent]["worked"] = subs[parent]["worked"] or event.get("type") == "assistant"
    return parent, told


def _result_text(content: object) -> str:
    if isinstance(content, list):
        return "".join(
            str(block.get("text") or "") for block in content if isinstance(block, dict)
        )
    return "" if content is None else str(content)


def _tool_done(use: dict, block: dict, subs: dict[str, dict], inside: dict[str, str],
               ended: set[str]) -> list[dict]:
    """One of its own tools has finished: the item KOLONİ records for it."""
    name, given, use_id = str(use.get("name")), _dict(use.get("input")), str(use["id"])
    failed = bool(block.get("is_error"))
    said = _result_text(block.get("content"))
    off = [{"type": "busy", "id": use_id, "on": False}]
    if use_id in ended:
        return off  # already said to be done; this is only its tool returning
    sub = subs.get(use_id)
    if sub is not None and (sub["started"] or not failed):
        if failed:
            return [*off, *_sub_end(use_id, "failed", said, subs, inside, ended)]
        # In the foreground its tool returns when it is done; in the background
        # the tool only launched it, and it works on. Where the CLI did not say
        # which, one seen at work before its tool returned was in the foreground.
        foreground = sub["worked"] if sub["background"] is None else not sub["background"]
        if foreground:
            return [*off, *_sub_end(use_id, "completed", said, subs, inside, ended)]
        # One the CLI says is in the background is at work, not silent, until it is
        # said to be done (B-136), as one in the foreground is until its tool returns.
        return _sub_begin(use_id, subs, inside) if sub["background"] else [
            *off, *_sub_begin(use_id, subs, inside)]
    subs.pop(use_id, None)  # refused, or it never started: a tool like any other
    item: dict
    if name in CLAUDE_RUNS:
        # A failed one starts "Exit code N" (Bash and PowerShell alike); one that did
        # not fail says none - nothing is made up for it.
        code = CLAUDE_EXIT.match(said) if failed else None
        item = {"type": "command_execution", "id": use_id,
                "command": str(given.get("command") or ""),
                "aggregated_output": said,
                "exit_code": int(code.group(1)) if code else None,
                "status": "failed" if failed else "completed"}
    elif name in CLAUDE_WRITES and not failed:
        path = given.get("file_path") or given.get("notebook_path")
        item = {"type": "file_change", "id": use_id,
                "changes": [{"path": path, "kind": "update"}]}
    else:
        item = {"type": "mcp_tool_call", "id": use_id, "server": "claude", "tool": name,
                "arguments": given, "status": "failed" if failed else "completed",
                "error": {"message": said} if failed else None,
                "result": {"content": [{"type": "text", "text": said}]}}
    item["parent"] = inside.pop(use_id, None)
    return [{"type": "busy", "id": use_id, "on": False},
            {"type": "item.completed", "item": item}]


def _task_started(event: dict, using: dict[str, dict], subs: dict[str, dict],
                  inside: dict[str, str]) -> list[dict]:
    # Leave was given and its sub-agent is at work; it says whether in the
    # background. (Measured 6 Oct 2026: tool_use_id, is_backgrounded.)
    named = str(event.get("tool_use_id") or "")
    if named not in subs:
        return []
    if isinstance(event.get("is_backgrounded"), bool):
        subs[named]["background"] = event["is_backgrounded"]
    if subs[named]["background"] is True and named not in using:
        # Said after its launch returned: at work all the same (B-136).
        return [{"type": "busy", "id": named, "on": True}, *_sub_begin(named, subs, inside)]
    return _sub_begin(named, subs, inside)


def _task_notified(event: dict, subs: dict[str, dict], inside: dict[str, str],
                   ended: set[str]) -> list[dict]:
    # A sub-agent is done: named by the tool use that started it, with its
    # report as "summary". One that names no sub-agent of ours ends none: a
    # notice about something else must not close one still at work.
    named = str(event.get("tool_use_id") or "")
    if named not in subs:
        return []
    # Only what is said to be completed is; an ending KOLONİ does not know
    # is not called a success.
    status = str(event.get("status") or "")
    known = {"completed": "completed", "failed": "failed", "stopped": "failed"}
    return _sub_end(named, known.get(status, "unknown"), str(event.get("summary") or ""),
                    subs, inside, ended)


def _assistant(event: dict, using: dict[str, dict], subs: dict[str, dict],
               inside: dict[str, str], ended: set[str]) -> list[dict]:
    # One of Claude Code's own sub-agents speaking: not this agent's words.
    inner = bool(event.get("parent_tool_use_id"))
    parent, told = _sub_within(event, subs, inside, ended)
    if said_why := own_error(event):
        told.append({"type": "own_error", "failure": said_why})
    for block in _dict(event.get("message")).get("content") or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and block.get("text"):
            if inner:
                if parent in subs:
                    subs[parent]["words"] = str(block["text"])
                continue
            told.append({"type": "item.completed",
                         "item": {"type": "agent_message", "text": block["text"]}})
        elif block.get("type") == "tool_use" and block.get("id"):
            if block.get("name") == ClaudeCliClient.OWN_TOOL and not inner:
                continue  # its report, handed back (89p): read off its result
            if str(block.get("name", "")).startswith(PREFIX):
                # KOLONİ's own tool: recorded where it is run.
                told.append({"type": "item.completed", "item": {
                    "type": "mcp_tool_call", "server": SERVER}})
                continue
            use_id = str(block["id"])
            using[use_id] = block
            if parent:
                inside[use_id] = parent
            if block.get("name") in CLAUDE_AGENTS:
                subs[use_id] = {"given": _dict(block.get("input")), "words": "",
                                "started": False, "worked": False,
                                "background": None, "tool": block["name"]}
            told.append({"type": "busy", "id": use_id, "on": True,
                         "parent": parent})
    return told


def _tool_results(event: dict, using: dict[str, dict], subs: dict[str, dict],
                  inside: dict[str, str], ended: set[str]) -> list[dict]:
    _parent, told = _sub_within(event, subs, inside, ended)
    for block in _dict(event.get("message")).get("content") or []:
        if isinstance(block, dict) and block.get("type") == "tool_result":
            use = using.pop(str(block.get("tool_use_id")), None)
            if use is not None:
                told += _tool_done(use, block, subs, inside, ended)
    return told


def _turn_result(event: dict, subs: dict[str, dict]) -> list[dict]:
    if event.get("is_error") and event.get("subtype") != SCHEMA_GAVE_UP:
        reason = str(event.get("result") or event.get("errors") or "it failed")
        # (The text of its answer, not an error line of its own: `RESULT_TEXT`.)
        return [{"type": "error", "message": reason, "result_text": True}]
    usage = _dict(event.get("usage"))
    sent = _input_tokens(usage)
    # (Nothing sent: zeros from a CLI that does not count are not a count.)
    read, written = _cache_tokens(usage) if sent else (None, None)
    # A sub-agent the CLI said is in the background and not yet done: this
    # result ends only the turn that launched it (measured on 2.1.311, B-136).
    return [{"type": "turn.completed", "usage": {
        "input_tokens": sent or None, "output_tokens": usage.get("output_tokens"),
        "cached_input_tokens": read, "cache_creation_input_tokens": written},
        "more": any(sub["background"] is True for sub in subs.values()),
        "structured": event.get("structured_output")}]


class QoderNativeClient(ClaudeNativeClient):
    """B-306: Qoder working natively, over Claude Code's control protocol (`_control`): its CLI
    takes Claude Code's flags (qodercli 1.1.51's --help, 29 Oct 2026). Not measured: whether
    it takes KOLONİ's hook and asks before its tools. `_control` stops one that does not apply
    the hook before it is given the prompt; `_heard` stops one that runs a tool unasked.
    shortcut: its tools are taken to be Claude Code's by name (Bash, Write, Edit, Read); one
    named otherwise is a tool KOLONİ does not know to `_approve`: a card at every level (Full
    auto too) - measure the names in its init line live."""

    command = "qodercli"
    label = "Qoder"
    efforts = QoderSessionClient.efforts
    effort_flag = QoderSessionClient.effort_flag
    effort_words = QoderSessionClient.effort_words
    # shortcut: its sign-in's variables are not known (it signs in by its own files): none of
    # the secret variables reach its commands; keep its own once one is seen to be needed.
    logins = frozenset()
    failed_unasked = True  # (one that failed may have acted all the same: as native agy's)
    # Measured 5 Nov 2026 (qodercli 1.1.51, cli-surdurme-olcum.md): `-r <id>` goes on in its
    # session; an id it does not have - another folder's too - exits 42 at once, unanswered.
    resume_flag = "-r"
    NO_SESSION = re.compile(
        r"exited with code 42: .*Error resuming session: Invalid session identifier")

    @property
    def resumes(self) -> bool:
        """Off (the user's call, 5 Nov 2026): it goes on in no session, KOLONİ compacts it.
        shortcut: its sessions would be kept in the user's own ~/.qoder/projects (listed by
        their own `qodercli -r`), which `forget_session` cannot clear - and its free models cost
        nothing to send the whole history. Turn this on (the path above is tested so) once
        Qoder is measured to sign in from a home of KOLONİ's own, as Claude Code's `home`."""
        return False

    def talker(self) -> CliStepClient:
        return QoderSessionClient(
            self._executable, self._model, self._timeout, self._which, self._launcher,
            self._env, self.server, self._homes,
        )

    def _native_arguments(
        self, root: Path, bridge_config: Path, withheld: tuple[str, ...] = (),
        linked: tuple[str, ...] = (), also: tuple[str, ...] = (),
    ) -> list[str]:
        # shortcut: a project's own .qoder settings could allow its tools past KOLONİ, and
        # whether `--setting-sources ""` keeps them out is not measured: no native run there.
        # Drop this once measured live.
        if any((root / ".qoder").glob("settings*.json")):
            raise OwnStop("Qoder cannot run natively in this project: it has Qoder settings of "
                          "its own (.qoder), which could let Qoder's tools run without asking "
                          "KOLONİ, and that is not yet measured. Run it as a session instead")
        config = bridge_config.parent / "mcp.json"
        config.write_text(json.dumps({"mcpServers": {SERVER: {
            "command": sys.executable,
            "args": [mcp_bridge.__file__, str(bridge_config)],
        }}}), encoding="utf-8")
        # Its session's line (measured live) with the control protocol's flags.
        # shortcut: --permission-prompt-tool is not in its --help; nor --add-dir, so a working
        # copy's linked folders are not given (its reads there fail), nor Claude Code's
        # --settings and --disable-slash-commands (`--setting-sources ""` keeps the project's
        # hooks and allow rules out, as in its session). An option it does not take ends it
        # before `initialize` is answered: stopped, never run unasked. Measure live.
        arguments = [
            "-p",
            "--input-format", "stream-json",
            "-o", "stream-json",
            "--permission-mode", "default",
            "--permission-prompt-tool", "stdio",
            "--strict-mcp-config",
            "--mcp-config", str(config),
            "--no-session-persistence",
            "--setting-sources", "",
        ]
        for name in claude_without(withheld):
            arguments += ["--disallowed-tools", name]
        for name in self._offered:  # KOLONİ's own tools need no leave
            arguments += ["--allowed-tools", PREFIX + name]
        if self._model:
            arguments += ["-m", self._model]
        return arguments  # the prompt comes on stdin

    async def _heard(
        self, kind: str, item: dict, said: bool, busy: set[str], on_text, on_item: OnItem,
    ) -> bool:
        said = await super()._heard(kind, item, said, busy, on_text, on_item)
        if "unasked" in item:
            # Not measured to ask first: one tool past KOLONİ (it has run: on record above) and
            # nothing more runs, as native agy's (`AgyClient._heard`).
            # (Never the command's own words: they could hold a token.)
            what, paths = item.get("type"), item["unasked"]
            name = ("a command" if what == "command_execution"
                    else "a write to " + ", ".join(map(str, paths))[:120]
                    if isinstance(paths, list) and paths
                    else f"its {str(item.get('tool'))[:60]} tool" if item.get("tool")
                    else "one of its own tools")
            raise OwnStop(f"Qoder ran {name} without KOLONİ being asked, so the run is "
                          "stopped: Qoder natively is not yet measured to ask before its tools; "
                          "run it as a session instead")
        return said


COPILOT_WRITES = ("edit", "create")
COPILOT_RUNS = ("powershell", "bash", "shell")
# Its tool that only says what it is about to do: not one that ran unasked.
# shortcut: by its name as remembered, not measured; add any other that never acts.
COPILOT_QUIET = ("report_intent",)
# The line Copilot ends a shell tool's output with; nothing before it is the exit code.
EXIT_CODE = re.compile(r"<shellId: \d+ completed with exit code (-?\d+)>\s*$")
# ... and a shell id said without it: the command is still at work (B-377: not failed).
STILL_RUNNING_SHELL = re.compile(r"<shellId: \d+(?!\d| completed with exit code)")
# B-377 (live, R173): its sandbox kept a uv-made venv's python.exe from starting the real one
# (under AppData\Roaming\uv), and Copilot gave no exit code: the tests never ran. Blocked, as
# K-48's refused write (`WRITE_REFUSED`), test runs too - here the failure is the test run's.
# shortcut: this one message, measured once on Windows (REA, Copilot as Orchestrator); a
# command that only prints it is blocked too, and other sandboxes' words are not known.
NO_PYTHON = re.compile(r"uv trampoline failed to spawn Python child process")
NO_PYTHON_BLOCKED = ("blocked: Copilot's sandbox could not start Python: run tests with a "
                     "sub-agent or in session mode")
# What Copilot headless speaks (measured on 1.0.91, 24 Oct 2026: `ping` says it).
PROTOCOL = 3
# How long its turn's end waits for `account.getQuota` (89l), in seconds.
QUOTA_SECONDS = 5.0
# The run's first word where its commands cannot be kept from the secret files (slice 105).
NO_SANDBOX = ("Copilot cannot sandbox commands on this machine: secret files are not hidden "
              "from them")
# KOLONİ's answers to a permission request: this once, never for the session or for good.
APPROVE_ONCE = {"kind": "approve-once"}
# (Review) A command that may change what a later one in Copilot's one shell session means: where
# it is (`commands._CLIMBS`: cd, sl, Push-Location...), an environment or path, a function or an
# alias, a module, an activate script, a line dot-sourced, any script run (it may define a
# `function global:`), or anything run as a string.
SHELL_STATE = re.compile(
    _CLIMBS.pattern + r"|(?<![\w-])(?i:function|filter|set-alias|new-alias|sal|nal|"
    r"import-module|ipmo|iex|invoke-expression|activate(?:\.ps1|\.bat)?|source|alias|export)"
    r"(?![\w-])|(?i:env:|function:|alias:|variable:|\]::|\.psm?1\b|using\s+module)"
    r"|(?:^|[\s;&|({])\.[ \t]+\S")


class _ShellPatches(dict):
    """B-389: the commands of a Copilot run that were patches, by tool call id (`_permit`);
    `moved`: a command it was let run may have changed its shell session (`SHELL_STATE`) - from
    then on, every patch it runs as a command is asked as the command it is."""

    moved = False
HEADLESS = ["--headless", "--no-auto-update", "--log-level", "error", "--stdio"]
# Its own tools a session is given (`availableTools`): its shell and what goes with it, and
# its file tools, each asked about as a command, a write or a read. Not grep or glob (a
# search reads a secret's lines with no card for the file), web_fetch or web_search, sql,
# skill, its workflow tools, nor task and its agent tools (sub-agents in sessions of their
# own, whose events are not read here).
# shortcut: the tools Copilot 1.0.91 reports (measured 24 Oct 2026; no write_powershell
# then); check the list again after an update of Copilot's (K-cli-surface).
COPILOT_TOOLS = ["powershell", "read_powershell", "stop_powershell", "list_powershell", "view",
                 "create", "edit"]
COPILOT_READS = ["view"]
MAX_MESSAGE = 2**26


async def _framed(stream: asyncio.StreamReader) -> dict | None:
    """One JSON-RPC message of Copilot's, Content-Length framed; None at its end. A frame
    that is not one raises ValueError, saying what was wrong with it."""
    length: int | None = None
    while True:
        line = await stream.readline()
        if not line:
            return None
        name, colon, value = line.decode("ascii", errors="replace").partition(":")
        if colon and name.strip().lower() == "content-length":
            try:
                length = int(value)
            except ValueError:
                raise ValueError(f"a Content-Length that is not a number ({value.strip()[:20]})"
                                 ) from None
        elif not line.strip() and length is not None:
            break
    if length is None or length <= 0:
        raise ValueError("an empty message")
    if length > MAX_MESSAGE:
        raise ValueError(f"a message of {length} bytes, longer than {MAX_MESSAGE} KOLONİ reads")
    try:
        body = await stream.readexactly(length)
    except asyncio.IncompleteReadError:
        return None
    try:
        return _dict(json.loads(body))
    except ValueError:
        raise ValueError("a message that is not JSON") from None


def _diff_paths(diff: object) -> list[str]:
    """The paths a diff's own headers name ("--- a/x", "+++ b/x"; not /dev/null)."""
    found = []
    for line in str(diff or "").splitlines():
        if line.startswith(("--- ", "+++ ")):
            path = line[4:].split("\t")[0].strip()
            if path != "/dev/null":
                found.append(path[2:] if path[:2] in ("a/", "b/") else path)
    return found


def _all_named(root: Path, named: str, paths: list[str]) -> bool:
    """Whether every path is the file a write names: the same file, or (a diff's header,
    from the folder it works in) one its path ends with."""
    target = Path(root, named).resolve()
    whole = "/" + target.as_posix().casefold()
    return all(Path(root, one).resolve() == target
               or whole.endswith("/" + one.replace("\\", "/").casefold().lstrip("/"))
               for one in paths)


class CopilotNativeClient(CodexNativeClient):
    """GitHub Copilot CLI working natively, on a model server of the user's own: its own
    file and shell tools in the project folder. It runs headless (slice 89c) and asks
    before each command, write and read; KOLONİ answers as it answers Codex's requests
    (`AgentRunner._approve`) and writes down what its events say it did.
    """

    command = "copilot"
    label = "GitHub Copilot CLI"
    asks = True
    looks_by_running = False  # it has a view tool of its own
    own_copy = False  # not measured in a copy: it works in the project
    # Read-only (B-301) it is given only its view tool; its commands have no read-only
    # sandbox here, so a role that runs them is not had read-only.
    read_only_commands = False
    # Its levels, sent as the session's are (`CopilotSessionClient`): `_leveled` puts
    # --reasoning-effort first on the headless server's line (`run_native`).
    # shortcut: native effort sent as the CLI flag, not measured in a native run (whether the
    # headless server holds it for the sessions it makes, or session.create has a field of
    # its own); measure with one cheap call.
    efforts = CopilotSessionClient.efforts
    effort_flag = CopilotSessionClient.effort_flag
    effort_words = CopilotSessionClient.effort_words
    # B-389 (R187, live): it sent its patch as a command (`git apply`), refused, and gave up the
    # change. Its own edit tool is a file card; KOLONİ's write tools it has only read-only.
    rules = NATIVE_RULES + (
        "\n\nTo change a file, use your own file edit tool (KOLONİ's write_file / edit_file where "
        "you have them). A patch command (apply_patch, git apply) is asked about as a command, "
        "and may be refused.")

    def __init__(self, executable=None, model=None, timeout: float = 900.0, *,
                 base_url=None, api_key=None, options=None, context=None, **more):
        super().__init__(executable, model, timeout, **more)
        # The session client knows how Copilot is started and what it is told about
        # the model server; natively only its tools differ.
        self._session = CopilotSessionClient(
            executable, model, timeout, base_url=base_url, api_key=api_key, options=options,
            context=context, **more,
        )
        # Its `auto` takes no level, as the session's (`level_in_name`).
        self.efforts, self.level_named = self._session.efforts, self._session.level_named

    def talker(self) -> CliStepClient:
        return self._session  # in a discussion: KOLONİ's reading tools only

    def _leveled(self, arguments: list[str], effort: str | None) -> list[str]:
        return self._session._leveled(arguments, effort)

    def _command(self) -> tuple[list[str], bool]:
        return self._session._command()

    def _inherited(self, pass_env: str | None = None) -> dict[str, str]:
        return self._session._inherited(pass_env)

    def _hide(self, text: str) -> str:
        return self._session._hide(text)

    def _native_env(self, workdir: Path) -> dict[str, str]:
        # shortcut: Copilot keeps its session state in its home (session.create's
        # workspacePath, `session-state`): here KOLONİ's empty one, removed after the turn,
        # never read; keep it in KOLONİ with a SessionFsProvider (slice 89q).
        return self._session._session_env(workdir)

    def _native_arguments(
        self, root: Path, bridge_config: Path, withheld: tuple[str, ...] = (),
        linked: tuple[str, ...] = (), also: tuple[str, ...] = (),
    ) -> list[str]:
        # Before --headless what holds for the whole server, as the SDK starts it; its
        # folder, model, KOLONİ's MCP server and the folders it also works in go in
        # session.create (`_converse`). No --allow-all-tools: it asks about each one.
        # shortcut: that these flags still hold headless is not measured; check that no
        # builtin MCP server and no custom instructions are loaded.
        secret = [one for one in self._session._account_arguments()
                  if one.startswith("--secret-env-vars=")]
        # shortcut: that a headless server takes --context for the sessions it makes (its
        # model goes in session.create) is not measured, nor whether session.create has a
        # field of its own for it; measure it live before trusting the long tier natively.
        return ["--disable-builtin-mcps", "--no-custom-instructions", *secret,
                *self._session.context_arguments(), *HEADLESS]

    def _translator(self, asked: set[str] | frozenset[str] = frozenset(),  # noqa: C901
                    heredocs: "_ShellPatches | None" = None,
                    ) -> Callable[[dict], list[dict]]:
        """Its events as `-p` printed them, as the events read by `_heard`. `asked`: the
        tool calls it asked KOLONİ about; one of the rest that ran is `unasked`. `heredocs`:
        the commands that were patches, asked file by file (`_permit`), by tool call id; and
        whether a command that ran may have changed its shell's session (`moved`)."""
        using: dict[str, dict] = {}  # tool call id -> what was started
        heredocs = _ShellPatches() if heredocs is None else heredocs

        def translate(event: dict) -> list[dict]:
            kind, data = event.get("type"), _dict(event.get("data"))
            if kind in ("model.call_start", "session.auto_mode_resolved"):
                return self._session._translate(event)  # (the model it picks under auto, and why)
            if kind == "assistant.message":
                text = str(data.get("content") or "")
                return [{"type": "item.completed",
                         "item": {"type": "agent_message", "text": text}}] if text else []
            if kind == "tool.execution_start":
                call_id = str(data.get("toolCallId") or "")
                if data.get("mcpServerName") == SERVER:
                    return [{"type": "item.completed",
                             "item": {"type": "mcp_tool_call", "server": SERVER}}]
                using[call_id] = data
                # A command is on record from when it is asked about (`_approve`), as Codex's.
                return [{"type": "busy", "id": call_id, "on": True}]
            if kind == "tool.execution_complete":
                call_id = str(data.get("toolCallId") or "")
                started = using.pop(call_id, None)
                if started is None:
                    return []
                name, given = str(started.get("toolName")), _dict(started.get("arguments"))
                said = str(_dict(data.get("result")).get("content") or "")
                failed = data.get("success") is False
                if failed and not said:
                    said = str(_dict(data.get("error")).get("message") or "")
                unasked = call_id not in asked and name not in COPILOT_QUIET
                done = [{"type": "busy", "id": call_id, "on": False}]
                patch = heredocs.pop(call_id, None) if name in COPILOT_RUNS else None
                if patch is not None:
                    # B-389: a patch it ran as a command, on record as the patch it was asked
                    # as - each file by the id it was asked under (as Codex's: `_as_exec`).
                    code = EXIT_CODE.search(said)
                    files = _files(patch)
                    return [*done, {"type": "item.completed", "item": {
                        "type": "file_change", "id": call_id, "declined": failed,
                        "status": "failed" if failed or code is None or code[1] != "0"
                        else "completed",
                        "changes": [{"path": path, "kind": how} for path, how, _diff in files],
                        "parts": [f"{call_id}:{n}" for n in range(len(files))],
                        "unasked": []}}]
                if name in COPILOT_RUNS:
                    # (Review: its shell is one session - after a command that may have moved
                    # it or named commands anew, a patch's paths or apply_patch may mean else.
                    # Refused or failed counts too: whether it ran is not sure.)
                    heredocs.moved |= bool(SHELL_STATE.search(str(given.get("command") or "")))
                    code = EXIT_CODE.search(said)
                    # shortcut: REA saw toolTelemetry's sandboxApplied on 1.0.103; the MIT
                    # SDK names a `sandboxed` - either counts, until one is seen live.
                    boxed = data.get("sandboxed") is True or _dict(
                        data.get("toolTelemetry")).get("sandboxApplied") in (True, "true")
                    # B-377: its shell ends what it ran with the code (EXIT_CODE): one it ran
                    # to its end with none did not end as it should, and is no success on
                    # record. One still running - started async, or past its first wait, its
                    # shell id said without "completed" - is not known yet, so not failed.
                    # shortcut: async and "still running" are read off the SDK's `mode` and a
                    # bare `<shellId: N` trailer, not measured; measure them live.
                    running = given.get("mode") == "async" or bool(given.get("detach")) or (
                        code is None and STILL_RUNNING_SHELL.search(said) is not None)
                    return [*done, {"type": "item.completed", "item": {
                        "type": "command_execution", "id": call_id,
                        "command": str(given.get("command") or ""),
                        "aggregated_output": EXIT_CODE.sub("", said),
                        "exit_code": int(code.group(1)) if code else None,
                        "status": "failed" if failed or (code is None and not running)
                        else "completed",
                        "unasked": unasked, "sandboxed": boxed,
                        **({"blocked": NO_PYTHON_BLOCKED} if NO_PYTHON.search(said) else {})}}]
                if name in COPILOT_WRITES and not failed:
                    how = "add" if name == "create" else "update"
                    path = given.get("path")
                    return [*done, {"type": "item.completed", "item": {
                        "type": "file_change", "id": call_id,
                        "changes": [{"path": path, "kind": how}],
                        "unasked": [str(path)] if unasked and path else []}}]
                return [*done, {"type": "item.completed", "item": {
                    "type": "mcp_tool_call", "id": call_id, "server": "copilot", "tool": name,
                    "arguments": given, "status": "failed" if failed else "completed",
                    "error": {"message": said} if failed else None, "unasked": unasked,
                    "result": {"content": [{"type": "text", "text": said}]}}}]
            if kind == "session.error":
                return [{"type": "error", "message": self._hide(
                    str(data.get("message") or "it failed"))}]
            return []

        return translate

    async def _converse(  # noqa: C901
        self, argv, shim, prompt, root: Path, server: ToolServer, on_text, on_item: OnItem,
        env: dict[str, str], call_tool: CallTool, also: tuple[str, ...], effort: str | None,
        bridge_config: Path | None = None, denied: tuple[str, ...] | None = None,
        on_live: OnLive | None = None,  # (never called: its session.send while busy waits, 89d)
        read_only: bool = False,
        no_shell: bool = False,  # (read-only its shell is not among availableTools at all)
    ) -> SessionResult:
        """Copilot headless for one turn, started and ended as Codex's app-server is
        (`CodexNativeClient._converse`): one session that asks before it acts
        (requestPermission), the prompt as its one message, each permission request
        answered by KOLONİ (`_permit`), and its events read as `-p`'s were. One that
        cannot be started asking first - its start, ping or session refused, another
        protocol, or no answer - is stopped, never run with leave for everything instead.
        `denied`: its commands run in its sandbox, kept from these, where this machine
        has one (slice 105)."""
        try:
            process, job = await self._start(argv, shim, root, env)
        except OSError as exc:
            raise OwnStop(f"{self.label} could not be started: {exc.strerror or exc}") from None
        stdin, stdout, errors = process.stdin, process.stdout, process.stderr
        assert stdin is not None and stdout is not None and errors is not None  # all piped
        stderr = asyncio.ensure_future(complaints(errors, (server.key,)))
        loop = asyncio.get_running_loop()
        replies: dict[int, asyncio.Future] = {}  # the ids of KOLONİ's requests -> answers
        permits: set[int] = set()  # the ids of KOLONİ's answers to its permission requests
        numbers = iter(range(1, 10**9))
        asked: set[str] = set()  # the tool calls it asked about
        answered: set[tuple[str, str]] = set()  # (tool call, kind) already answered
        heredocs = _ShellPatches()  # (B-389: its commands that were patches)
        translate = self._translator(asked, heredocs)
        session: str | None = None
        answering: set[asyncio.Future] = set()
        writing = asyncio.Lock()
        heard = time.monotonic()
        busy: set[str] = set()  # its tools at work, and its requests KOLONİ is answering
        said = False
        reported: str | None = None  # the model it says it is using
        picked_why: str | None = None  # why Copilot's auto picked it, where it said so
        usage: dict | None = None  # its last session.usage_checkpoint
        failure: str | None = None
        unasked: str | None = None  # why it could not be started asking first
        broke: BaseException | None = None  # what answering a request of its own ended in
        started = False  # its session is made
        sent = False  # its prompt is on its way: an idle now ends its turn
        idle = False  # its turn ended

        def end_now() -> None:
            if job:
                job.terminate()
            with contextlib.suppress(ProcessLookupError):
                process.kill()

        server.on_end = end_now

        async def send(message: dict) -> None:
            body = json.dumps({"jsonrpc": "2.0", **message}).encode("utf-8")
            async with writing:
                stdin.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
                await stdin.drain()

        async def ask(method: str, params: dict) -> tuple[dict, str | None]:
            """What it answered, and why it said no (None: it did not)."""
            number = next(numbers)
            replies[number] = loop.create_future()
            await send({"id": number, "method": method, "params": params})
            told = await replies[number]
            if "result" in told:
                return _dict(told["result"]), None
            error = told.get("error")
            return {}, _brief(self._hide(str(_dict(error).get("message") or error)))

        async def answer(data: dict) -> None:
            nonlocal heard, broke
            request_id = str(data.get("requestId") or "")
            request = _dict(data.get("permissionRequest"))
            # shortcut: a request that names no tool call is told by its own id, and its
            # record does not join its tool's; check live that toolCallId is always there.
            use_id = str(request.get("toolCallId") or request_id)
            key = f"asked {request_id}"
            busy.add(key)
            try:
                result = await self._permit(request, use_id, root, asked, answered, on_item,
                                            call_tool, heredocs)
                if result["kind"] == "reject":
                    busy.discard(use_id)  # it may never say a rejected tool is done
                # (Its answer is not waited for: one that refuses KOLONİ's ends the run, `read`.)
                number = next(numbers)
                permits.add(number)
                with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                    await send({"id": number,
                                "method": "session.permissions.handlePendingPermissionRequest",
                                "params": {"sessionId": session, "requestId": request_id,
                                           "result": result}})
            except Exception as exc:  # a stop of KOLONİ's own, or a bug: its work ends here
                broke = broke or exc
                end_now()
            finally:
                busy.discard(key)
                heard = time.monotonic()

        async def read() -> None:  # noqa: C901
            nonlocal heard, said, reported, usage, failure, idle, broke, picked_why
            try:
                while (message := await _framed(stdout)) is not None:
                    heard = time.monotonic()
                    method, params = message.get("method"), _dict(message.get("params"))
                    if method is None:  # an answer to a request of KOLONİ's
                        number = message.get("id")
                        future = replies.get(number) if isinstance(number, int) else None
                        if future is not None and not future.done():
                            future.set_result(message)
                        elif "error" in message or (number in permits and _dict(
                                message.get("result")).get("success") is False):
                            # It did not take KOLONİ's answer: what it does next is not known.
                            error = _dict(message.get("error")).get("message") or "success false"
                            failure = failure or _brief(self._hide(
                                f"it did not take KOLONİ's answer: {error}"))
                            end_now()
                        continue
                    if "id" in message:  # a request of its own: declined, never left waiting
                        await on_item("completed", {
                            "type": "mcp_tool_call", "server": "copilot", "tool": str(method),
                            "arguments": {}, "status": "declined", "error": {"message": (
                                f"KOLONİ declined this request of {self.label}'s")}})
                        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                            await send({"id": message["id"], "error": {
                                "code": -32601, "message": "KOLONİ declines this request"}})
                        continue
                    # Only its session's events are kept (never an answer: session.create's
                    # names where its home is).
                    # shortcut: another session's events are dropped, unread; none is
                    # expected while its task and agent tools are left out (COPILOT_TOOLS).
                    # Read them if those tools are ever given.
                    if method != "session.event" or (
                            session and params.get("sessionId") != session):
                        continue
                    event = _dict(params.get("event"))
                    feed("stdout", json.dumps(event, ensure_ascii=False), (server.key,))
                    kind = event.get("type")
                    if kind == "session.usage_checkpoint":
                        # Measured on 1.0.103 `-p` (5 Nov 2026): the session's total so far
                        # (a resumed one counted on), so the last one stands, never summed; a
                        # session here is one turn's.
                        # shortcut: that headless sends it at all, and before session.idle, is
                        # not measured, nor on a model server of the user's own; with none
                        # its tokens stay unknown. Check live on a native Copilot turn.
                        usage = _dict(event.get("data"))
                        continue
                    if kind == "permission.requested":
                        data = _dict(event.get("data"))
                        if data.get("resolvedByHook"):
                            # KOLONİ gives it no hooks: one of its own decided, unasked.
                            broke = broke or OwnStop(
                                f"a hook of Copilot's own answered a permission request of "
                                f"{self.label}'s, not KOLONİ: the run was stopped")
                            end_now()
                            return
                        task = asyncio.ensure_future(answer(data))
                        answering.add(task)
                        task.add_done_callback(answering.discard)
                        continue
                    if kind == "session.idle" and sent:
                        if _dict(event.get("data")).get("aborted"):
                            failure = failure or "its turn was aborted"
                        idle = True
                        return  # it has finished; whatever lingers is ended below
                    for told in translate(event):
                        if told["type"] == "model":
                            picked_why = why_picked(told, reported, picked_why)
                            reported = str(told.get("model") or "") or reported
                        elif told["type"] == "error":
                            failure = _brief(str(told["message"]))
                        elif told["type"] == "busy":
                            (busy.add if told["on"] else busy.discard)(str(told["id"]))
                        else:
                            said = await self._heard(told["type"], told["item"], said, busy,
                                                     on_text, on_item)
                    if server.ended:
                        return
                await process.wait()
            finally:
                for future in replies.values():  # nothing more will answer them
                    if not future.done():
                        future.set_result({"error": {"message": "it ended"}})

        async def said_quota() -> None:
            """89l: what is left of its plan, asked of this Copilot once its turn is over (no
            turn, no other process): QUOTA_SECONDS at most, never the run's failure. Read
            here, `read` having ended at its idle; whose account it is goes unkept.
            shortcut: measured only alone after a ping (1.0.91/1.0.103), not after a turn;
            check live that it answers there, and widen QUOTA_SECONDS if it is slower."""
            number = next(numbers)
            try:
                async with asyncio.timeout(QUOTA_SECONDS):
                    await send({"id": number, "method": "account.getQuota", "params": {}})
                    while (told := await _framed(stdout)) is not None:
                        if told.get("id") == number and "method" not in told:
                            if "result" in told and self.on_limits:
                                self.on_limits({"quotaSnapshots": _dict(
                                    told["result"]).get("quotaSnapshots")})
                            return
            except Exception as exc:  # (TimeoutError among them) keeping it never breaks the run
                log.warning("Copilot's quota was not read: %s", type(exc).__name__)

        async def talk() -> None:
            nonlocal unasked, started, failure, session, sent
            reading = asyncio.ensure_future(read())
            try:
                pong, no = await ask("ping", {})
                if no is None and pong.get("protocolVersion") != PROTOCOL:
                    no = f"it speaks protocol {pong.get('protocolVersion')}, not {PROTOCOL}"
                sandbox: dict = {}
                if no is None and denied is not None:
                    sandbox = await self._sandbox(ask, denied, also, on_item)
                if no is None:
                    made, no = await ask("session.create", {
                        **sandbox,
                        "workingDirectory": str(root),
                        "requestPermission": True,  # every tool of its own is asked about
                        "mcpServers": {SERVER: {
                            "type": "local", "command": sys.executable,
                            "args": [mcp_bridge.__file__, str(bridge_config)], "tools": ["*"]}},
                        **({"model": self._model} if self._model else {}),
                        # Only the tools KOLONİ judges: its own, and KOLONİ's by the names
                        # Copilot gives an MCP server's tools (`CopilotSessionClient`). Read-only
                        # (B-301): of its own only view - no shell, no edit (`_approve` refuses
                        # them too).
                        "availableTools": [*(COPILOT_READS if read_only else COPILOT_TOOLS),
                                           *(COPILOT_PREFIX + name for name in self._offered)],
                        # None of a repository's own hooks (they act unasked), config or
                        # skills. No additionalDirectories: it would give it those folders,
                        # with their hooks; a path outside is asked about (`_approve`).
                        "enableFileHooks": False, "enableConfigDiscovery": False,
                        "enableSkills": False})
                    session = made.get("sessionId") if isinstance(
                        made.get("sessionId"), str) else None
                    no = no or (None if session else "it named no session")
                if no is not None:
                    if not reading.done():  # (one that ended says so below)
                        unasked = no
                    return
                started = sent = True
                _, no = await ask("session.send", {"sessionId": session, "prompt": prompt})
                if no is not None:
                    failure = failure or no
                    return
                await reading
                if idle and self.on_limits and not server.ended:
                    await said_quota()
            except (BrokenPipeError, ConnectionResetError):
                return  # it is gone: how it ended is said below
            finally:
                reading.cancel()
                with contextlib.suppress(BaseException):
                    await asyncio.shield(asyncio.wait({reading}, timeout=2))

        # shortcut: from here on as Codex's `_converse`, line for line; merge the two into
        # one loop when agy (89e) converses the same way.
        talking = asyncio.ensure_future(talk())
        try:
            # The limit is on silence, as for Codex; not a word before its session is made
            # is a Copilot that could not be asked first.
            gone = Exited(process, job)
            while not talking.done():
                await asyncio.wait({talking}, timeout=min(1.0, self._timeout / 4))
                quiet = time.monotonic() - max(heard, server.last_reply)
                working = server.in_flight > 0 or bool(busy)
                if not talking.done() and await gone():
                    break  # (said as it ended, `_session_result`)
                if not talking.done() and not working and quiet > self._timeout:
                    if not started:
                        unasked = f"it did not answer for {self._timeout:g} seconds"
                        break
                    raise ModelUnavailable(
                        f"{self.label} sent nothing for {self._timeout:g} seconds")
            if talking.done():
                try:
                    talking.result()
                except ValueError as exc:  # (`_framed`: what was wrong with the frame)
                    raise ModelUnavailable(
                        f"{self.label} sent what KOLONİ cannot read: {exc}") from None
        finally:
            for task in (talking, *answering):
                task.cancel()
            with contextlib.suppress(BaseException):
                await asyncio.shield(asyncio.wait({talking, *answering}, timeout=2))
            await self._end(process, job)
            complaint = b""
            with contextlib.suppress(Exception):
                complaint = await asyncio.wait_for(asyncio.shield(stderr), 2)
            stderr.cancel()
        return await self._session_result(broke, server, unasked, failure, idle, complaint,
                                          process, reported, usage, picked_why)

    async def _sandbox(self, ask: Callable[[str, dict], Awaitable[tuple[dict, str | None]]],
                       denied: tuple[str, ...], also: tuple[str, ...],
                       on_item: OnItem) -> dict:
        # The sandbox `_converse` asks for its session, where this Copilot has one.
        sandbox: dict = {}
        # Where it cannot (a Copilot older than 1.0.101 has no such method) it
        # runs all the same, and says so: the search card and slice 88 still hold.
        # shortcut: the answer's shape is the MIT SDK's (SandboxHostSupport), not
        # seen here; REA saw denied_paths supported on 1.0.103.
        host, refused = await ask("sandbox.getHostSupport", {})
        able = host.get("capabilities")
        if refused is None and host.get("supported") is True and any(
                one.get("name") == "denied_paths" and one.get("supported") is True
                for one in (able if isinstance(able, list) else [])
                if isinstance(one, dict)):
            sandbox = {"sandboxConfig": {
                "enabled": True, "allowBypass": False,
                # KOLONİ's bridge reaches 127.0.0.1: it is not sandboxed. No
                # network policy: Copilot's default stays (a closed one breaks
                # npm install).
                "sandboxMcpServers": False, "addCurrentWorkingDirectory": True,
                # Measured on 1.0.103 (24 Oct 2026): a write outside the folder
                # or to the home folder is denied unless in readwritePaths, TEMP
                # is writable, the network is as without a sandbox.
                "userPolicy": {"filesystem": {
                    "deniedPaths": list(denied),
                    **({"readwritePaths": list(also)} if also else {})}}}}
        else:
            await on_item("completed", {
                "type": "mcp_tool_call", "server": "copilot", "tool": "sandbox",
                "arguments": {}, "status": "completed",
                "result": {"content": [{"type": "text", "text": NO_SANDBOX}]}})
        return sandbox

    async def _session_result(
        self, broke: BaseException | None, server: ToolServer, unasked: str | None,
        failure: str | None, idle: bool, complaint: bytes, process, reported: str | None,
        usage: dict | None = None, picked_why: str | None = None,
    ) -> SessionResult:
        # What `_converse`'s session came to, once it is over.
        if broke is not None:
            raise broke
        if server.ended:
            raise server.ended
        if unasked is not None:
            # B-176: a model its account does not have is refused as its session is made
            # ('Request session.create failed with message: Model "gpt-5.4-nano" is not
            # available.', seen live, B-179): the model, not the start.
            # shortcut: R166 saw this come ~4 min after the start; KOLONİ stops as session.create
            # answers (no retry, `test_a_model_not_on_the_account_is_named_as_the_cause`), so the
            # wait is taken to be Copilot's own before it answers - not measured. Time
            # session.create's request against its answer live; if it is the CLI, a check of the
            # model before the session (or on the Models page's Check) would say it at once.
            if self._model and re.search(
                    r'(?:^|failed with message: )Model "[^"]+" is not available', unasked):
                raise OwnStop(
                    f"Copilot can't use {self._model} on your account: pick another model")
            raise OwnStop(f"{self.label} {await self._version()} could not be asked before it "
                          f"acts ({unasked}); run it as a session instead")
        if failure or not idle:
            reason = _brief(self._hide(complaint.decode("utf-8", errors="replace")))
            raise ModelUnavailable(
                f"{self.label} reported an error: {failure}" if failure
                else how_it_ended(self.label, process.returncode, reason))
        return replace(copilot_counts(usage), model=reported, picked_why=picked_why)

    async def _permit(  # noqa: C901
        self, request: dict, use_id: str, root: Path, asked: set[str],
        answered: set[tuple[str, str]], on_item: OnItem, call_tool: CallTool,
        heredocs: "_ShellPatches",
    ) -> dict:
        """KOLONİ's answer to a permission request of Copilot's: what `AgentRunner._approve`
        says, asked as Codex's requests are (`CodexNativeClient._decide`) - a command as its
        Bash; a file it writes as its Write (the whole file it will hold, so the card is a
        diff) or, without that, its Edit; a file it reads as its Read (a secret's is a card,
        slice 88). A call of one of KOLONİ's own tools is let through: those are held to
        KOLONİ's rules where they run. Anything else is rejected, and that is on record.
        `heredocs`: where a command is a patch (B-389), its changes, by `use_id`."""
        kind = str(request.get("kind"))
        if kind == "mcp" and request.get("serverName") == SERVER:
            return APPROVE_ONCE
        asked.add(use_id)  # (declined too: it was asked about, it did not run unasked)
        # Asking to go outside its sandbox is a reason: a card at every level, as Codex's.
        given = {"reason": str(request.get("requestSandboxBypassReason")
                               or "to go outside its sandbox")} if request.get(
            "requestSandboxBypass") else {}
        named = str(request.get({"shell": "fullCommandText", "write": "fileName",
                                 "read": "path"}.get(kind, "")) or "")
        why = (f"KOLONİ declined this request of {self.label}'s: only a command, a file it "
               "writes or a file it reads is answered")
        question: tuple[str, dict] | None = None
        questions: list[tuple[str, dict]] = []  # (a patch's: one a file)
        if (use_id, kind) in answered:
            why = (f"KOLONİ declined this request of {self.label}'s: it asked again for what "
                   "was answered")
        elif named and kind == "shell":
            # What it says the command touches, judged as a read or write of each (`_approve`);
            # where it runs, if it says (1.0.91 does not, measured 24 Oct 2026): outside the
            # folder, a card at every level (89a).
            where = request.get("resolvedWorkingDirectory")
            urls = [str(_dict(one).get("url")) for one in request.get("possibleUrls") or []]
            # B-389: a patch it runs as a command (`_heredoc_patch`) is asked file by file as
            # the patch it is, as Codex's (`_decide`) - only where every rule of a command lets
            # it run, and nothing it says of the command (a URL, a redirection) is more. Each
            # form only in the shell it is said to run in; none once a command may have moved
            # its session (`_ShellPatches.moved`).
            shell = request.get("shellType")
            patch = None if urls or request.get("hasWriteFileRedirection") or heredocs.moved or (
                shell not in ("powershell", "bash")) else _heredoc_patch(
                named, str(where or root), shell == "powershell")
            if patch is None:  # (asked as a command: from here on, if it may move its session)
                heredocs.moved |= bool(SHELL_STATE.search(named))
            if patch is not None:
                _ok, may = await call_tool(PATCH_MAY_RUN, json.dumps(
                    {"command": named, **given, **({"cwd": str(where)} if where else {})}))
                patch = patch if may == "true" else None
            if patch is not None:
                heredocs[use_id] = patch
                questions = _patch_questions(patch, given)
            else:
                question = ("Bash", {"command": named, **given,
                                     **({"cwd": str(where)} if where else {}),
                                     "paths": list(request.get("possiblePaths") or []),
                                     "writes": bool(request.get("hasWriteFileRedirection")),
                                     # Its own word that a part is not read-only can only
                                     # make it asked, never let one through unasked.
                                     "not_read_only": any(
                                         _dict(one).get("readOnly") is False
                                         for one in request.get("commands") or []),
                                     "urls": urls})
        elif named and kind == "write":
            # What it will write is its one fileEdit (newFileContents is no sure word: an
            # empty one is not a deletion); a write that names more files, or another one
            # (a move), is not what is asked about, so not answered yes.
            edits = [_dict(edit) for edit in request.get("fileEdits") or []]
            after = _dict(edits[0].get("after")) if len(edits) == 1 else {}
            diff = request.get("diff")
            if edits:
                paths = [str(_dict(side).get("path")) for edit in edits
                         for side in (edit.get("before"), edit.get("after")) if side]
            else:
                paths = [str(request["resolvedPath"])] if request.get("resolvedPath") else []
                paths += _diff_paths(diff)
            if len(edits) > 1 or not _all_named(root, named, paths):
                why = (f"KOLONİ declined this request of {self.label}'s: it would change "
                       "another file than the one it names, or more than one")
            elif isinstance(after.get("content"), str):
                question = ("Write", {"file_path": named, "content": after["content"], **given})
            elif edits:  # (no after: the file goes)
                question = ("Edit", {"file_path": named, "kind": "delete", "diff": diff, **given})
            else:
                # As 1.0.91 asks (measured 24 Oct 2026: no fileEdits): in words, with its
                # diff - newFileContents is not taken as what the file will hold.
                # shortcut: not shown as a change; show it as one if a version sends fileEdits.
                question = ("Edit", {"file_path": named, "diff": diff, **given})
        elif named and kind == "read":
            question = ("Read", {"file_path": named, **given})
        if question is not None:
            questions = [question]
        if not questions:
            await on_item("completed", {
                "type": "mcp_tool_call", "server": "copilot", "tool": f"permission {kind}",
                "arguments": request, "status": "declined", "error": {"message": why}})
            return {"kind": "reject", "feedback": why}
        answered.add((use_id, kind))
        for number, (tool, input_) in enumerate(questions):
            # (A patch's files by the ids its record names as its `parts`: `_translator`.)
            ask_id = f"{use_id}:{number}" if use_id in heredocs else use_id
            await on_item("announced", {"id": ask_id})
            _ok, verdict = await call_tool("approve", json.dumps(
                {"tool_name": tool, "input": input_, "tool_use_id": ask_id}))
            verdict = _dict(json.loads(verdict))
            if verdict.get("behavior") != "allow":
                return {"kind": "reject", "feedback": str(verdict.get("message") or "rejected")}
        return APPROVE_ONCE

