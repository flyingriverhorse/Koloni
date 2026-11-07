"""Card and permission helpers: what an agent on a model may do where (`needs_full_auto`,
`outside_a_copy`, `sandbox_denied`, `_changes_nothing`), which folders a card covers
(`folders_of`, `within`), and the words of a few cards (`_cant_card`, `lead_pick`).
"""
import contextlib
import fnmatch
import json
import re
import tempfile
from collections.abc import Collection, Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from app import copies
from app.agent.ctx import Ctx
from app.agent.words import GO_ON_AT, RECONNECT, RUN_THERE
from app.claims import place
from app.commands import holds_a_key, secret_files
from app.db.models import Agent, Conversation, Message, Project, Provider
from app.model_client import ToolCallRequest
from app.model_native import ClaudeNativeClient
from app.roles import can_change_things, shown_name
from app.team import only_in_project, reads_only
from app.tools import MAX_LINE_CHARS
from app.workspace import Workspace, WorkspaceError, never

# What a CLI that asks first did without asking (Codex: its own allow rules, its known-safe
# commands; Copilot's own tools; Claude Code: a tool past its hook): its turn goes on, and
# the record says so (`_unasked_note`). (Native agy's run is stopped there: `AgyClient._heard`.)
UNASKED_BY_CLI = "ran without KOLONİ being asked ({who}'s own rules)"
NATIVE_NEEDS_FULL_AUTO = (
    "{provider} works here with its own tools and cannot ask before it writes or runs "
    "something. Set the permission level to Full auto to use it, or switch the provider "
    "to one step at a time on the Models page."
)
# The same for a CLI that has no "one step at a time", but can be set to read only.
NATIVE_OR_READS = (
    "{provider} works here with its own tools and cannot ask before it writes or runs "
    "something. Set the permission level to Full auto to use it, or switch the provider "
    "to reads only on the Models page."
)
LEAD_WHY_CHARS, LEAD_ANSWER_CHARS = 300, 300


def _answer(said: str) -> str:
    """What a model answered to a request of KOLONİ's own, without what a local reasoning
    model thinks first: that comes in its answer, and is not the answer."""
    return re.sub(r"^\s*<think>.*?</think>", "", said, flags=re.IGNORECASE | re.DOTALL)


def lead_pick(said: str, options: list[str]) -> tuple[str, str] | None:
    """The Lead's answer for the user and its reason, from its JSON line (`LEAD_ASKED`): one of
    `options` as written there, or - with none - one short line; None for anything else, or
    with no reason: the question waits for the user."""
    try:
        got = json.loads(said[said.find("{"):said.rfind("}") + 1])
    except ValueError:
        return None
    answer, why = (got.get("answer"), got.get("why")) if isinstance(got, dict) else (None, None)
    if not isinstance(answer, str) or not isinstance(why, str) or not why.strip():
        return None
    answer, why = answer.strip(), " ".join(why.split())[:LEAD_WHY_CHARS]
    if options:
        answer = next((one for one in options if one.casefold() == answer.casefold()), "")
    elif len(answer) > LEAD_ANSWER_CHARS or "\n" in answer:
        return None
    return (answer, why) if answer else None


def folders_of(project: Project | None, conversation: Conversation, access: str) -> list[str]:
    """The folders outside the project a conversation's agents may use with this access
    ("write": read and write, "read": read only): its own - its folder's are copied in as
    it starts (slice 86b). None ([]) for a plain chat: no folder is open to it (86a). Never
    the project or a folder in it, whatever a list kept (B-66: from a working copy it would
    be offered to write in)."""
    if project is None:
        return []
    root, kept = Path(project.root_path), "also_in" if access == "write" else "read_in"
    return [folder for folder in getattr(conversation, kept) if not within(Path(folder), root)]


def _then(said: str, moved: str | None) -> str:
    """An agent's reason, then why its tier's model is not the first: two sentences (B-76:
    they were joined with ".;")."""
    if not (said and moved):
        return said or moved or ""
    return f"{said.rstrip(' .;')}. {moved[:1].upper()}{moved[1:]}"


def within(path: Path, folder: Path) -> bool:
    return path == folder or path.is_relative_to(folder)


def _handed(folder: str, write: list[str], read: list[str]) -> bool:
    """Whether a CLI with tools of its own is given this folder to write in (`_add_dirs`):
    not one that holds a place KOLONİ never opens, or a folder to read in only."""
    return not never(Path(folder)) and not any(
        within(Path(r), Path(folder)) and r not in write for r in read)


def _shows_a_key(ws: Workspace, path: str) -> bool:
    """Whether read_file would show a key (`holds_a_key`) in a line of this file, as it cuts
    its lines."""
    try:
        return any(holds_a_key(line) for line, _length in ws.lines(path, MAX_LINE_CHARS))
    except WorkspaceError:
        return False  # (not text: read_file says so itself)


def _shared(copy: copies.Copy, target: Path) -> bool:
    """Whether a path a CLI names in its working copy leads into one of the folders the
    copy shares with the project (installed dependencies): read there, never written."""
    with contextlib.suppress(OSError, ValueError):
        real = target.resolve()
        return any(real == folder or real.is_relative_to(folder) for folder in copy.links.values())
    return False


def _glob_could_take(glob: object, rel: str) -> bool:
    """Whether a search held to `glob` (Claude Code's Grep takes ripgrep's) could open the
    file at `rel`, by its name or its path: any file, without a glob or with one KOLONİ does
    not read here (braces, `**`, a `!` that leaves files out)."""
    if not isinstance(glob, str) or not glob or re.search(r"[{!]|\*\*", glob):
        return True
    return fnmatch.fnmatch(rel.rsplit("/", 1)[-1], glob) or fnmatch.fnmatch(rel, glob)


def _places(root: str, paths: list[str]) -> list[str]:
    """Paths of a project as they are compared (`claims.place`); what is no path inside
    it is left out."""
    return [found[0][1] for path in paths if (found := place(root, path))]


def _on(provider: Provider, model: str | None) -> str:
    """A provider and its model as a card says them: "Local · big-model", or its name alone."""
    return shown_name(provider.name) + (f" · {model}" if model else "")


def _cant_card(team: str, step: str, child: Ctx, cant: tuple[str, str | None, datetime | None],
               offer: tuple[str, Provider, str | None] | None) -> tuple[str, list[str]]:
    """The card of a step whose agent could not run on its provider (B-88, G3): run it where
    there is room; go on with the same agent at its limit's reset - not for a window of a day
    or more, nor at a time not known - or once signed in again; try it again where nothing
    says when; skip it; stop. The chosen model is never switched without the user's word."""
    why, kind, resets = cant
    role, provider = shown_name(child.role), shown_name(child.provider or "its provider")
    text, options = f"{team}: {role} can't run on {provider} ({why}).", []
    if offer:
        text += f" Run {step} on {_on(offer[1], offer[2])}?"
        options.append(RUN_THERE)
    if resets and kind != "long":
        at = f"{resets.astimezone():%H:%M}"
        text += f" {GO_ON_AT}{at}: the same agent goes on from what it has done so far."
        options.append(GO_ON_AT + at)
    if kind == "sign_in":
        text += f" Sign in to {provider} first, then {RECONNECT}."
        options.append(RECONNECT)
    elif kind != "long" and not resets:
        options.append("Try again")
    return text, [*options, "Skip", "Stop"]


def needs_full_auto(model: object, level: str) -> str | None:
    """Why a CLI with tools of its own cannot work at this permission level ({provider}
    to be filled in), or None: one that neither asks first nor only reads needs Full auto."""
    if not getattr(model, "native", False) or getattr(model, "asks", False) or getattr(
            model, "reads", False) or level == "full_auto":
        return None
    return NATIVE_OR_READS if getattr(model, "can_read_only", False) else NATIVE_NEEDS_FULL_AUTO


def outside_a_copy(model: object) -> bool:
    """Whether an agent on this model could change the project while it works in a copy: a
    CLI with tools of its own that is not started in one, or whose commands' writes are not
    kept to it - one that only reads changes nothing. No side of a comparison runs on it."""
    return bool(getattr(model, "native", False)) and not getattr(model, "reads", False) and (
        only_in_project(model) or not _sandboxed(model))


def _links_in_copy(model: object) -> bool:
    """Whether an agent on this model may work in a copy with the project's dependency
    folders linked in: not one that writes there unasked and unwatched (native agy)."""
    return getattr(model, "links_in_copy", True)


def _in_its_chat(ctx: Ctx, model: Any) -> Any:
    """The client an agent of `ctx`'s chat runs on: in a plain chat (slice 86a) a CLI that
    works with tools of its own is its talker - with them off, in an empty folder of its own,
    as it speaks in a discussion. One that still has them then (agy) stays as it is."""
    talker = getattr(model, "talker", None) if ctx.root is None else None
    return talker() if talker and getattr(model, "native", False) else model


def _unasked_note(ctx: Ctx) -> str:
    """What the record says of a tool a CLI that asks first ran without asking."""
    return UNASKED_BY_CLI.format(who=getattr(ctx.model, "label", "the CLI"))


def _unasked(model: object) -> bool:
    """Whether an agent on this model works with tools of its own that neither ask KOLONİ
    first nor only read: what `team.cannot_pick` holds to Full auto and to the tools."""
    return bool(getattr(model, "native", False)) and not (
        getattr(model, "asks", False) or getattr(model, "reads", False)
    )


def _hands_back(ctx: Ctx) -> bool:
    """89p: whether an agent told the findings hands its report back in REPORT_SCHEMA.
    shortcut: Claude Code's only - agy's flag was measured with --output-format json, not the
    stream-json it runs on here, and Codex's turn/start outputSchema (in 0.164's strings) not at
    all; give theirs once measured."""
    return isinstance(ctx.model, ClaudeNativeClient) and ctx.model.command == "claude"


def _needs_its_tools(model: object, tools: Collection[str]) -> bool:
    """Whether an agent on this model must be allowed to write files and run commands: a
    CLI at work with tools of its own that neither asks first nor only reads, or one that
    asks but looks at files only by running commands (`looks_by_running`) - unless it is
    started read-only for these tools (B-301: Codex reads with KOLONİ's tools then)."""
    return _unasked(model) or (
        getattr(model, "looks_by_running", False) and not reads_only(model, tools))


def sandbox_denied(where: Path, project: Path, records: Path, homes: Path,
                   logins: Path) -> tuple[str, ...]:
    """What Copilot's sandbox keeps its commands from (slice 105): the secret files where it
    works and, from a copy, the project's own too (a command there can name the project's
    path) - and KOLONİ's own records, and the providers' own sign-in folders (`logins`,
    K-claude-hesap). shortcut: the secrets in the user's home (~/.ssh, ~/.aws)
    are not denied on purpose: git push over ssh needs ~/.ssh. Blocking.
    B-304: and the keys to the other runs' tool servers - the CLI runs' bridge files (its own
    is written after this) and agy's doors in `homes` (`model_agy.DOOR`). shortcut: those
    there as it starts, by their path - its sandbox takes no wildcard (measured on 1.0.103),
    nor can the whole temp folder be denied; one made later is not (a bridge file is gone once
    its bridge is in: `ToolServer`); one gone before its session.create is still named
    (whether the sandbox minds a path that is gone is not measured): measure both live."""
    tops = dict.fromkeys((where, project))
    keys = [*Path(tempfile.gettempdir()).glob("koloni-cli-*/bridge.json"),
            *homes.glob("agy-*/.gemini/config/koloni-door.json")]
    return (*(str(top / rel) for top in tops for rel in secret_files(top)), str(records),
            str(logins), *map(str, keys))


def _role_asked(request: ToolCallRequest) -> str:
    """The role a spawn_agent call asks for, casefolded; "" where it names none readable."""
    try:
        role = json.loads(request.arguments).get("role")
    except (ValueError, AttributeError):
        return ""
    return " ".join(role.split()).casefold() if isinstance(role, str) else ""


def _at_a_step_limit(error: str | None) -> bool:
    """Whether an agent's error is a step limit's: the app's, its role's (ROLE_STEPS), or
    the end of a budget it was given (GIVEN_LIMIT)."""
    return error == "step_limit" or bool(
        error and error.startswith("stopped at its role's limit of") and "step" in error
        or error and error.startswith("stopped after the "))


def _steps_of_chain(session, agent_id: str | None) -> int:
    """B-327: the model steps an agent and the earlier ones it goes on from (`continues_id`)
    took, as their records have them - one assistant message a step, a CLI session's
    messages too. What its role's limit counts across turns (`_role_before`).
    shortcut: a step cut short (a 429, a Stop) leaves a message too, and so does a turn an
    agent took to answer another (`message_agent` "answer"), and both are counted here,
    where `_steps_used` within a turn counted neither - a message says nothing of the turn
    it was written in; keep each agent's count on its record if that is ever felt."""
    steps, seen = 0, set()
    while agent_id and agent_id not in seen:
        seen.add(agent_id)
        steps += session.scalar(select(func.count(Message.id)).where(
            Message.agent_id == agent_id, Message.role == "assistant",
            Message.discussion_id.is_(None))) or 0
        agent_id = session.scalar(select(Agent.continues_id).where(Agent.id == agent_id))
    return steps


def _goes_on(ctx: Ctx) -> bool:
    """Whether an agent's loop is one it may be told to go on in, from the steps it took
    (B-83: `_loop`) - its own work, not an answer's or a discussion's beside it."""
    return not (ctx.answering or ctx.discussion)


def _changes_nothing(ctx: Ctx) -> bool:
    """R102: a CLI with tools of its own whose commands no folder holds (native agy) that
    changes nothing - it asks KOLONİ before each tool, in a role that changes nothing: it works
    beside others of its kind in one place (`_native_place`), and what is found changed there
    is not its doing. Not agy reading only: what the user's own agy settings let through is
    written (`test_reading_only_what_the_users_own_agy_settings_let_through_is_on_record_as_done`).
    shortcut: a change seen beside it is then on no record (a hand change, a CLI's command
    that wrote past its copy), nor is its own write by a tool its hook missed (the run stops:
    `model_agy`'s "unhooked"); put such a one down as `IN_THE_PROJECT` if one is missed."""
    return not _sandboxed(ctx.model) and getattr(ctx.model, "asks", False) and (
        not can_change_things(ctx.tools))


def _sandboxed(model: object) -> bool:
    """Whether a CLI with tools of its own keeps its commands' writes to the folder it
    works in (Codex: `--sandbox workspace-write`). One that does not (native agy) can
    change the project from its copy without naming a path."""
    return getattr(model, "sandboxed", True)


def _who(ctx: Ctx) -> str:
    """The model an agent runs on, as a file's card names it."""
    return " on ".join(filter(None, [ctx.model_name, ctx.provider])) or "its model"


def _asked_about(approval: str, mode: str, tools: Iterable[str]) -> bool:
    """Whether opening an agent with these tools is asked about at this approval setting and
    permission level - before any pick of a model (`_propose`; B-386's take-up too)."""
    return approval == "always" or (
        approval == "auto" and mode == "ask" and can_change_things(tools))
