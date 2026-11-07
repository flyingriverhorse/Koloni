"""A CLI asking leave for a tool of its own: the card that asks the user, or the rule, trigger
or Lead that answers instead (`_approve`, moved whole), and a question asked in words
(`_ask_leave`) - `ApprovalsMixin`.
"""

import asyncio
import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from app import copies, mcp_client
from app.agent.cards import _glob_could_take, _shared
from app.agent.ctx import Ctx, _NobodyToAsk, _Transcript, _Watch
from app.agent.merge import _planned_edit
from app.agent.words import (
    ANSWER_PREFIX,
    CANARY_REFUSED,
    CANARY_STOPPED,
    CHANGE_REJECTED,
    HANDS_CODE_REFUSED,
    NOT_IN_A_COPY,
    NOT_IN_THE_PART,
    SHARED_WITH_PROJECT,
)
from app.command_runner import CARRY_ON, rejected
from app.commands import copy_reason, reads_here, search_reason, sends_canary, web_off_reason
from app.db.models import Conversation, FileChange, now
from app.model_native import (
    CLAUDE_KNOWN,
    CLAUDE_READS,
    CLAUDE_RUNS,
    CLAUDE_SHELL_OUTPUT,
    CLAUDE_WRITES,
    INSIDE,
)
from app.model_session import PREFIX
from app.serialize import file_change_out
from app.team import quoted, reads_only
from app.tools import WRITE_TOOLS, ToolError
from app.workspace import (
    HARD_LINK,
    Workspace,
    WorkspaceError,
    has_other_names,
    home_of,
    not_written_as_named,
    opened,
    secret_in_project,
    secret_named,
    sha256_text,
    stands_over_later_turns,
)

if TYPE_CHECKING:
    from app.agent import AgentRunner

# B-301: what a CLI started read-only for its role is told when it tries its own (and before:
# `model_native.READ_ONLY_RULES`).
READ_ONLY_READS = ("read files with the koloni server's read_file, list_dir and search "
                   "instead")
READ_ONLY_WRITE = (
    "{who} was started read-only for the {role} role: its own {tool} is refused. Write the "
    "file with the koloni server's write_file or edit_file instead, not in any other way."
)
# What a CLI's own tool is refused with (`AgentRunner._approve`), and KOLONİ's edit a user
# declined: each a no to that action, not to the task (B-321).
NO_COMMANDS = "do not run it another way. " + CARRY_ON
NO_CHANGES = "the {role} role may not change files: do not change them another way. " + CARRY_ON
ONLY_READS = ("the {role} role may only read here, and KOLONİ cannot tell what {tool} would "
              "change: do not use it, or anything else, to do the same. " + CARRY_ON)

LEAVE_REJECTED = ("rejected: the user declined this. It is their decision on this step, not on "
                  "the task: do not do it another way. " + CARRY_ON)

# As `READ_AGAIN` (after a wait), for a CLI that asks leave for its own write tool: what it
# has read KOLONİ does not see, so it is told when the file changed while its request waited.
READ_AGAIN_ASKED = (
    "{name} has finished with {path}, and the file changed while this change waited "
    "for it: read it again, then make your change"
)

WAITED = "waited for {name} to finish with {path}"

OUTSIDE_THE_COPY = (
    "{path} is outside your working copy ({root}): you work on the copy of the project "
    "there, and on nothing else - name the file by its path in the copy"
)

KOLONI_IN_SEARCH = (
    "this search would read {place}, KOLONİ's own code or record, which is never opened: "
    "search a narrower folder that leaves it out"
)

CARD_CHARS = 20_000  # of a question asked in words (`_ask_leave`): longer, it is refused


def _searched(tool: str, given: dict) -> str:
    """The folder a CLI's own Grep or Glob looks in: its path, or the folder it works in -
    and a Glob's pattern from there (a pattern is a path too; braces pick names as
    wildcards do)."""
    start = given.get("path") if isinstance(given.get("path"), str) and given["path"] else None
    if tool != "Glob" or not isinstance(given.get("pattern"), str):
        return start or "."
    base = re.split(r"[*?\[{]", given["pattern"])[0] or "."
    return base if start is None or Path(base).is_absolute() or base.startswith("~") else str(
        Path(start) / base)


class ApprovalsMixin:
    # --- a CLI asking leave for a tool of its own -----------------------------

    async def _runs_as_patch(
        self: "AgentRunner", ctx: Ctx, watch: "_Watch", arguments: str
    ) -> bool:
        """R175 (review): whether a patch Codex (or Copilot, B-389) runs as a command
        (`model_native._heredoc_patch`) is asked about as that patch, file by file. Its shell
        still starts, so only where every rule of a command that is not the user's word lets it
        run, as `_approve` judges one: its
        role runs commands, 101's key is not in it, a turn nobody watches allows this very
        command, and nothing makes it a card at every level (Codex's own reason, a folder out of
        the one it works in, the search, web, copy, branch and night reasons). Else it is asked
        about as the command it is."""
        try:
            given = json.loads(arguments or "{}")
        except ValueError:
            return False
        command = given.get("command") if isinstance(given, dict) else None
        if not isinstance(command, str) or "run_command" not in ctx.tools or given.get("reason"):
            return False
        if (canary := self._canaries.get(ctx.run_id)) and sends_canary(
                json.dumps(given), canary, True):
            return False
        root, copy, cwd = watch.view.root.resolve(), watch.copy, given.get("cwd")
        folder = root / cwd if isinstance(cwd, str) and cwd else root  # (a whole path stays one)
        try:
            where = folder.resolve().relative_to(root).as_posix()
        except (ValueError, OSError):
            return False
        if self._nobody_to_ask(ctx, "command", f"run {quoted(command)}", command=command,
                               cwd=where or ".") not in (None, ""):
            return False
        searched = await asyncio.to_thread(search_reason, command, root, str(folder))
        return not (web_off_reason(command, self._off()) or searched or copy is not None and (
            copy_reason(command, bool(copy.links), ctx.folder, self.settings.runtime_root))
            or self._branch_asks(ctx, command, copy is not None)
            or self._night_asks(ctx, command, cwd))

    async def _approve(  # noqa: C901
        self: "AgentRunner", ctx: Ctx, transcript: "_Transcript", watch: "_Watch", arguments: str
    ) -> dict:
        """Answer a permission prompt of a CLI working with its own tools: the role's
        limits first, then the conversation's permission level, the user where it says so.
        In a turn nobody is watching the level counts for nothing and nobody is asked:
        after the role's limits it is the trigger's own leave (`_nobody_to_ask`), as for
        KOLONİ's own tools - a change inside the project, a command it names word for
        word, a tool that only looks; everything else is refused.

        What is allowed goes back exactly as it came: what was approved is what runs.
        """
        # K-yazma-denetimi: a standing file one of its commands wrote unnamed is put back
        # before anything more is let run (a hook, before `git commit`) - and nothing is
        # answered while a card of its turn asks whether to keep one.
        await self._standing_look(ctx, transcript, watch)
        await self._keeps_answered(ctx)
        try:
            asked = json.loads(arguments or "{}")
        except ValueError:
            asked = None
        asked = asked if isinstance(asked, dict) else {}
        tool, given = asked.get("tool_name"), asked.get("input")
        if not isinstance(tool, str) or not tool or not isinstance(given, dict):
            return {"behavior": "deny", "message": "KOLONİ could not read this request"}
        use_id = str(asked.get("tool_use_id") or "")
        under = watch.under(use_id)  # asked from inside one of the CLI's own sub-agents
        allow = {"behavior": "allow", "updatedInput": given}
        who = getattr(ctx.model, "label", "Claude Code")  # (Codex asks here too: slice 89a)

        def deny(why: str, fixed: bool = False) -> dict:
            if use_id:
                watch.denied.add(use_id)
            # `fixed`: KOLONİ's own words, with nothing the CLI sent but a path - what a CLI
            # whose answer has no room for a reason is told in its turn (Codex, B-197).
            return {"behavior": "deny", "message": why, **({"koloni": True} if fixed else {})}

        # 89g: a role run inside the CLI has its role's tools only - none of KOLONİ's, which
        # would be its Lead's; one not offered by KOLONİ (a project's own) has none.
        kind = asked.get("agent_type")
        if isinstance(kind, str) and kind.startswith(INSIDE) and (
                tool not in watch.roles.get(kind, ("", []))[1]):
            role = watch.roles.get(kind, (kind, []))[0]
            why = f"{role} (inside {who}) may not use {tool}: its role does not give it that tool"
            self._note(ctx, transcript, re.sub(r"[^A-Za-z0-9_-]", "_", f"claude__{tool}")[:64],
                       given, "denied", why, parent=under)
            return deny(why)
        if tool.startswith(PREFIX):
            # KOLONİ's own tools: leave for them is not this tool's to give or withhold.
            # (One it was not offered fails where they run: its tool server has none such.)
            return allow
        # Leave is given for a tool use the CLI itself has announced, and for nothing
        # else: not for a request the model makes up by calling this tool directly.
        # (The announcement comes down another channel and may be a moment behind.)
        for _ in range(30 if use_id else 0):
            if use_id in watch.announced:
                break
            await asyncio.sleep(0.05)
        if use_id not in watch.announced:
            return {"behavior": "deny", "message": "KOLONİ knows of no such tool use"}
        # 101, as for KOLONİ's own tools: what it runs, fetches or hands an MCP server.
        # shortcut: only what reaches this hook - not a CLI's own web search with none (Codex's,
        # agy's), nor `env | curl -d @-` (it names nothing), nor the key encoded, or written to
        # a file and sent from there.
        if (canary := self._canaries.get(ctx.run_id)) and tool not in CLAUDE_WRITES and (
                sends_canary(json.dumps(given), canary, tool in CLAUDE_RUNS)):
            self._note(ctx, transcript, "run_command" if tool in CLAUDE_RUNS else re.sub(
                r"[^A-Za-z0-9_-]", "_", f"claude__{tool}")[:64], given, "denied", CANARY_REFUSED,
                parent=under)
            self._over_budget(ctx.run_id, CANARY_STOPPED)
            return deny(CANARY_REFUSED, fixed=True)

        with self._factory() as session:
            level = session.get_one(Conversation, ctx.cid).permission_mode
        # Where the CLI works: the project, or the working copy it was started in.
        root, copy = watch.view.root.resolve(), watch.copy
        ours = Workspace(root)

        def inside(named: str) -> tuple[Path, str | None]:
            """A path the CLI names, and what it is called in the folder it works in -
            None for one that leads out of it. "~" is the home folder, as the CLI reads
            it: never a folder of the project's; nor KOLONİ's own code or record in the
            project (`Workspace.koloni_s`): judged as outside, it is never opened."""
            named = home_of(named)
            target = Path(named) if Path(named).is_absolute() else root / named
            if "\x00" in named:  # (3.13+ resolve() no longer raises on one)
                return target, None
            try:
                real = target.resolve()
                if ours.koloni_s(real):
                    return target, None
                return target, real.relative_to(root).as_posix()
            except (ValueError, OSError):
                return target, None

        # A place the user kept out while away (slice 106): refused whatever else allows it.
        runs = tool in CLAUDE_RUNS and isinstance(given.get("command"), str)
        named = str(given.get("file_path") or given.get("notebook_path") or "")
        relative = inside(named)[1] if tool in CLAUDE_WRITES and named else None
        # (and where it says the command runs: Codex's cwd)
        at = given.get("cwd") if runs and isinstance(given.get("cwd"), str) else None
        if (runs or relative) and (kept := self._keeps_out(
                ctx, path=relative, command=given["command"] if runs else None,
                cwd=inside(at)[1] if at else None,
                what=f"run {given['command']}" if runs else f"change {named}") or (
                at and inside(at)[1] and self._keeps_out(
                    ctx, path=inside(at)[1], what=f"run {given['command']} in {at}"))):
            self._note(ctx, transcript, "run_command" if runs else "edit_file",
                       {"command": given["command"]} if runs else {"path": named},
                       "denied", kept, parent=under)
            return deny(kept)

        if tool in CLAUDE_RUNS:
            return await self._approve_command(
                ctx, transcript, watch, tool=tool, given=given, use_id=use_id, under=under,
                allow=allow, deny=deny, level=level, root=root, copy=copy, inside=inside)
        if tool in CLAUDE_SHELL_OUTPUT and "run_command" in ctx.tools:
            return allow  # (what a command it was let run says, or its end: no new action)

        if tool in CLAUDE_WRITES:
            return await self._approve_write(
                ctx, transcript, watch, tool=tool, given=given, use_id=use_id, under=under,
                allow=allow, deny=deny, who=who, level=level, root=root, copy=copy,
                inside=inside)
        if (refused := await self._approve_read(
                ctx, transcript, watch, tool=tool, given=given, under=under, deny=deny,
                root=root, copy=copy, inside=inside)) is not None:
            return refused
        # Full auto is the conversation's level: in a turn nobody is watching it gives
        # nothing, and a tool KOLONİ cannot tell from a write or a command is one no
        # trigger allows. Why it asks (native agy: a tool KOLONİ does not know) makes it a
        # card at every level - a read too (Copilot's, to go outside its sandbox). So does
        # one of a Lead that hands code on (slice 48): it may write, and that Lead may not.
        # B-306: and none of a Qoder tool named as none of Claude Code's - an unknown name may
        # be a shell, a write or the network past every check. shortcut: allow by name once
        # Qoder's tool list is measured (K-fullauto-sorma 2 review).
        if not given.get("reason") and (
                tool in CLAUDE_READS or level == "full_auto" and self._watched(ctx.run_id)
                and ctx.run_id not in self._away_jobs  # (nor at night: the job waits for it)
                and not self._hands_code(ctx)
                and (tool in CLAUDE_KNOWN or getattr(ctx.model, "command", "") != "qodercli")):
            return allow  # recorded when it reports it done
        shown = json.dumps(given, ensure_ascii=False)
        return await self._ask_leave(
            ctx, transcript, watch, use_id, tool, given, allow, deny,
            f"{who} wants to use its own tool {tool}: {shown}",
            f"let {who} use its own tool {quoted(tool)}",
        )

    async def _approve_command(
        self: "AgentRunner", ctx: Ctx, transcript: "_Transcript", watch: "_Watch", *,
        tool: str, given: dict, use_id: str, under: str | None, allow: dict,
        deny: Callable[..., dict], level: str, root: Path, copy: copies.Copy | None,
        inside: Callable[[str], tuple[Path, str | None]],
    ) -> dict:
        """`_approve`'s answer to a command of the CLI's own (`CLAUDE_RUNS`)."""
        if not isinstance(given.get("command"), str) or not given["command"]:
            # (Its Monitor can watch other things than a command: those are not judged.)
            return deny(f"KOLONİ judges {tool} by the command it runs, and this one names none",
                        fixed=True)
        command = given["command"]
        # Why it asks (Codex: to leave its sandbox, say) and where it says the command
        # runs are shown with it; either makes it a card at every level, and nothing a
        # trigger allows. (Out of a working copy is out of the folder it works in.)
        reason, cwd = given.get("reason"), given.get("cwd")
        # What it says the command touches (Copilot: possiblePaths, slice 89c): each path
        # judged as a read or a write of it would be, and a hit is its reason.
        # shortcut: a path in a folder the project also works in is a card too, where a
        # read or write there may not be; judge it by `_native_outside` if that is wanted.
        for one in [p for p in given.get("paths") or [] if isinstance(p, str) and p]:
            relative = inside(one)[1]
            reason = reason or (
                f"it names {one}, outside the folder it works in" if relative is None
                else f"it names {relative}, a secret file" if secret_named(one, relative)
                else f"it may write {relative}, which tells later turns what they may do"
                if given.get("writes") and stands_over_later_turns(Workspace(root), relative)
                else None)
        # (Its paths are read from where it says it runs: a part's folder, say.)
        searched = await asyncio.to_thread(search_reason, command, root, str(
            inside(cwd)[0]) if isinstance(cwd, str) and cwd else ".")
        # Web off first: Codex's own reason for wanting the network says nothing of it. An
        # address the CLI says it may reach (Copilot's possibleUrls) counts as in the line.
        urls = [one for one in given.get("urls") or [] if isinstance(one, str)]
        web_off = web_off_reason(" ".join([command, *urls]), self._off())
        reason = web_off or reason or searched or (
            copy_reason(command, bool(copy.links), ctx.folder, self.settings.runtime_root)
            if copy is not None else "") or self._branch_asks(
            ctx, command, copy is not None) or self._night_asks(ctx, command, cwd)
        if not reason and given.get("urls") and level != "full_auto":
            reason = f"it may reach {given['urls'][0]}"  # (as KOLONİ's web tools are asked)
        where = inside(cwd)[1] if isinstance(cwd, str) and cwd else "."
        noted = {"command": command, **({"reason": reason} if reason else {}),
                 **({"cwd": cwd} if cwd else {})}
        if "run_command" not in ctx.tools:
            self._note(ctx, transcript, "run_command", noted, "denied",
                       f"the {ctx.role} role may not run commands", parent=under)
            # B-301: one started read-only reads with KOLONİ's tools - Codex looks at files
            # only by running commands, and is not to stop at this no.
            return deny(f"the {ctx.role} role may not run commands; " + (
                READ_ONLY_READS if reads_only(ctx.model, ctx.tools)
                else NO_COMMANDS), fixed=True)
        refused = self._nobody_to_ask(
            ctx, "command", f"run {quoted(command)}", command=command,
            cwd="." if where in ("", ".") else where or str(cwd))
        if refused == "" and reason:
            refused = self._nobody_to_ask(ctx, "words", f"run {quoted(command)}: {reason}")
        if refused:
            # Not put on record as a command at all: it is not one that waits.
            self._note(ctx, transcript, "run_command", noted, "denied", refused, parent=under)
            return deny(refused)
        call_id = self._note(ctx, transcript, "run_command", noted, None, None, parent=under)
        if reason:  # (on its card)
            self._set_call(ctx.cid, call_id, why_asked=reason)
        # One that names a folder to read in only by its full path is asked about, as
        # KOLONİ's own commands are.
        allowed, command_id = await self.commands.ask_for(
            ctx.run_id, ctx.cid, ctx.agent_id, call_id, command, ask=refused is None,
            always=self._read_named(ctx, command) is not None or bool(reason)
            or where is None, held=bool(searched), web_off=bool(web_off),
            reads=not given.get("not_read_only") and await asyncio.to_thread(
                reads_here, command, root, where in ("", ".")),
            # (One out of the folder it works in: as the CLI gave it. None where it gave
            # none: KOLONİ does not know where its shell stood, and judges at the root.)
            # shortcut: Claude Code gives no cwd (Codex, Copilot and agy do): its command is
            # judged at the root, also after a `cd` an earlier Bash call kept; read its cwd
            # from the hook input if it carries one.
            cwd=(where if where is not None else cwd)
            if isinstance(cwd, str) and cwd else None,
        )
        if not allowed:
            self._set_call(ctx.cid, call_id, status="denied", result=rejected(command),
                           ended_at=now())
            return deny(rejected(command), fixed=True)
        watch.commands[use_id] = (call_id, command_id)
        # What it names was on its card (asked at every level): what it writes under that
        # name stands at the look after it, that one (`_command_names`).
        # shortcut: Copilot's possiblePaths are not named so - a write there is a card to
        # keep; name them too if that is asked twice.
        if copy is None:
            watch.approved.add(use_id)
        return allow

    async def _approve_write(  # noqa: C901
        self: "AgentRunner", ctx: Ctx, transcript: "_Transcript", watch: "_Watch", *,
        tool: str, given: dict, use_id: str, under: str | None, allow: dict,
        deny: Callable[..., dict], who: str, level: str, root: Path,
        copy: copies.Copy | None, inside: Callable[[str], tuple[Path, str | None]],
    ) -> dict:
        """`_approve`'s answer to a write of the CLI's own (`CLAUDE_WRITES`)."""
        named = str(given.get("file_path") or given.get("notebook_path") or "")
        if (no := self._write_by_role(ctx, transcript, watch, tool=tool, under=under,
                                      deny=deny, who=who, named=named)) is not None:
            return no
        target, relative = inside(named)
        if copy is not None:
            # In a working copy only what will be taken into the project is written:
            # nothing outside the copy (the project itself least of all), nothing in
            # a folder it shares with the project or leaves out - as for KOLONİ's
            # own write tools. Refused, not asked about: the user is asked once, for
            # what is in the copy, when its work is over.
            # (By the folders' names as Windows reads them: `dist./x` is in `dist`.)
            parts = (relative or "").split("/")
            left_out = copies.under(parts, copies.NOT_COPIED)
            why = (
                NOT_IN_A_COPY.format(path=relative, name=left_out) if left_out
                else SHARED_WITH_PROJECT.format(path=relative or named)
                if _shared(copy, target) or copies.under(parts, copies.LINKED)
                else OUTSIDE_THE_COPY.format(path=named, root=root) if relative is None
                else NOT_IN_THE_PART.format(path=relative, part=copy.part,
                                            project=copy.project)
                if not copy.holds(relative) else None
            )
            if why:
                self._note(ctx, transcript, "edit_file", {"path": relative or named},
                           "denied", why, parent=under)
                return deny(why, fixed=True)
        outside = relative is None
        if outside:
            # (Not in a working copy: refused above.) In a folder the project also
            # works in, or one the user allows, it is a file like the project's: on
            # record by its full path, and asked about as the level says.
            why = await self._native_outside(ctx, transcript, under, "edit_file", named,
                                             target)
            if why:
                return deny(why)
            relative = str(target.resolve())
        odd = not_written_as_named(named)  # (a device, a stream: as for KOLONİ's own tools)
        if odd or has_other_names(target.resolve()):
            # As for KOLONİ's own write tools: refused at every level, nobody asked.
            why = f"{relative!r} is not written: {odd or HARD_LINK}"
            self._note(ctx, transcript, "edit_file", {"path": relative}, "failed",
                       f"error: {why}", parent=under)
            return deny(why)
        # As for KOLONİ's own write tools, at any depth and as Windows opens the name
        # (outside the project: wherever in that folder's path).
        standing = stands_over_later_turns(Workspace(root), relative)

        def stands(verdict: dict) -> dict:
            # (A yes to a write of a standing file of the project names it: it stands.)
            if verdict is allow and standing and copy is None and not outside:
                watch.named.add(relative.casefold())
            return verdict

        if standing in (".claude", ".mcp.json", ".claude.json"):
            # What it is allowed to do next time is decided there: never without asking.
            whose = "its own" if who == "Claude Code" else "Claude Code's"
            return stands(await self._ask_leave(
                ctx, transcript, watch, use_id, tool, given, allow, deny,
                f"{who} wants to change {whose} settings ({relative}), which decide "
                f"what it may do without asking: {json.dumps(given, ensure_ascii=False)}",
                f"let {who} change {whose} settings ({quoted(relative)})",
            ))
        # Why it asks (Codex: for more than its sandbox gives, say): shown with it, and
        # it makes the change one to ask about at every level, and one no trigger allows.
        reason = given.get("reason")
        refused = self._nobody_to_ask(ctx, "write", "change files")
        if refused == "" and standing:
            refused = self._nobody_to_ask(
                ctx, "standing file",
                f"change {quoted(relative)}: such a file tells later turns what they may "
                "do, or runs by itself, which no trigger allows",
            )
        if refused == "" and reason:
            refused = self._nobody_to_ask(ctx, "words", f"change {quoted(relative)}: {reason}")
        if refused:
            self._note(ctx, transcript, "edit_file", {"path": relative}, "denied", refused,
                       parent=under)
            return deny(refused)
        # The file is this agent's from here on, as for KOLONİ's own write tools:
        # held by another agent, the request waits - and is refused afterwards if the
        # file is no longer what it was when the CLI asked.
        if (no := await self._write_claim(
                ctx, transcript, watch, under=under, deny=deny, target=target,
                relative=relative)) is not None:
            return no
        asks = (level == "ask" or self._standing_asks(ctx.run_id, standing, level)
                or bool(reason)) and refused is None and (copy is None or bool(reason))
        if not asks and not outside:
            # Written by the CLI; recorded when it reports it done. In a working copy
            # at every level: the user is asked once, when the copy is taken in.
            # (`stands`: an instruction file let through at Full auto stands at the look.)
            return stands(allow)
        planned = await asyncio.to_thread(_planned_edit, target, tool, given)
        if planned is None and not asks:
            # shortcut: a change outside the project that cannot be worked out from
            # the request (a notebook, an edit that does not match) is made with no
            # record of its own - no look covers that folder; look there if needed.
            return allow
        if planned is None:
            shown = json.dumps(
                {k: v for k, v in given.items() if k != "file_path"}, ensure_ascii=False
            )
            # shortcut: Codex's patch to a file that is there is asked here, in words
            # with its whole diff; apply the diff to show it as a change if that is wanted.
            return stands(await self._ask_leave(
                ctx, transcript, watch, use_id, tool, given, allow, deny,
                f"{who} wants to use its {tool} tool on {relative} (KOLONİ cannot "
                f"show this one as a diff): {shown}",
                f"use {who}'s {tool} tool on {quoted(relative)}",
            ))
        before, after = planned
        call_id = self._note(ctx, transcript, "edit_file" if before is not None
                             else "write_file",
                             {"path": relative, **({"reason": reason} if reason else {})},
                             None, None, parent=under)
        with self._factory() as session:
            change = FileChange(
                run_id=ctx.run_id, agent_id=ctx.agent_id, tool_call_id=call_id,
                path=relative, kind="create" if before is None else "modify",
                before_content=before, after_content=after,
                before_sha=sha256_text(before), after_sha=sha256_text(after),
                origin="cli",
            )
            session.add(change)
            session.commit()
            change_id, payload = change.id, file_change_out(change)
        self.bus.emit(ctx.cid, ctx.run_id, "file_change.created", payload)
        decision = "approve"  # (outside the project, at a level that does not ask)
        if asks:
            future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
            self._decisions[change_id] = future
            self._update_run(ctx.run_id, ctx.cid, status="waiting_approval")
            try:
                decision = await self._users_word(
                    ctx, future, self._change_heard(ctx, change_id))
            finally:
                self._decisions.pop(change_id, None)
                self._update_run(ctx.run_id, ctx.cid, status="running")
        if decision == "reject":
            self._mark_change(ctx, change_id, "rejected")
            why = CHANGE_REJECTED.format(path=relative)
            self._set_call(ctx.cid, call_id, status="denied", result=why, ended_at=now())
            return deny(why, fixed=True)
        # The yes is on record now, also where no place was waited for: the CLI
        # makes the change itself, and may be a while about it - or never do.
        self._mark_change(ctx, change_id, "approved")
        watch.asked[use_id] = (call_id, change_id)
        return stands(allow)

    def _write_by_role(
        self: "AgentRunner", ctx: Ctx, transcript: "_Transcript", watch: "_Watch", *,
        tool: str, under: str | None, deny: Callable[..., dict], who: str, named: str,
    ) -> dict | None:
        """`_approve_write`'s refusals by the role and the Lead's rule; None: none."""
        if not any(name in ctx.tools for name in WRITE_TOOLS):
            self._note(ctx, transcript, "edit_file", {"path": named}, "denied",
                       f"the {ctx.role} role may not change files", parent=under)
            return deny(NO_CHANGES.format(role=ctx.role), fixed=True)
        if reads_only(ctx.model, ctx.tools):
            # B-301: started read-only, it writes with KOLONİ's write tools, not its own.
            why = READ_ONLY_WRITE.format(who=who, role=ctx.role, tool=tool)
            self._note(ctx, transcript, "edit_file", {"path": named}, "denied", why,
                       parent=under)
            return deny(why, fixed=True)
        # A Lead that hands code on (slice 48), as for KOLONİ's own write tools.
        if self._own_writes_refused(ctx, watch):
            why = HANDS_CODE_REFUSED.format(tool=f"{tool} to {named}")
            self._note(ctx, transcript, "edit_file", {"path": named}, "denied", why,
                       parent=under)
            return deny(why, fixed=True)
        return None

    async def _write_claim(
        self: "AgentRunner", ctx: Ctx, transcript: "_Transcript", watch: "_Watch", *,
        under: str | None, deny: Callable[..., dict], target: Path, relative: str,
    ) -> dict | None:
        """`_approve_write`'s claim on the file: the refusal where it cannot be had, or was
        changed while this request waited for it; None: claimed."""
        asked_at = await asyncio.to_thread(copies.digest, target, follow=True)
        waiting: list[str] = []
        try:
            waited = await self._claim(
                ctx, relative, hold=watch.hold,
                began=lambda: waiting.append(self._note(
                    ctx, transcript, "edit_file", {"path": relative}, None, None,
                    parent=under)),
            )
        except ToolError as exc:
            # Waiting would never end: said at once, or when the file went on to
            # an agent that waits for this one.
            if waiting:
                self._set_call(ctx.cid, waiting[0], status="failed",
                               result=f"error: {exc}", ended_at=now())
            else:
                self._note(ctx, transcript, "edit_file", {"path": relative}, "failed",
                           f"error: {exc}", parent=under)
            return deny(str(exc))
        if waited:
            changed = await asyncio.to_thread(copies.digest, target, follow=True) != asked_at
            why = READ_AGAIN_ASKED.format(name=waited, path=relative)
            self._set_call(
                ctx.cid, waiting[0], ended_at=now(),
                status="failed" if changed else "succeeded",
                result=f"conflict: {why}" if changed
                else WAITED.format(name=waited, path=relative),
            )
            if changed:
                return deny(why)
        return None

    async def _approve_read(  # noqa: C901
        self: "AgentRunner", ctx: Ctx, transcript: "_Transcript", watch: "_Watch", *,
        tool: str, given: dict, under: str | None, deny: Callable[..., dict], root: Path,
        copy: copies.Copy | None, inside: Callable[[str], tuple[Path, str | None]],
    ) -> dict | None:
        """`_approve`'s refusals of any other tool, a read's above all: None where none
        refuses it, and `_approve` goes on."""
        if tool not in CLAUDE_READS and not (
            "run_command" in ctx.tools and any(name in ctx.tools for name in WRITE_TOOLS)
        ):
            # A tool KOLONİ does not know - an MCP server of the user's, a sub-agent - may
            # write or run anything. A role that may not do both gets none of them.
            self._note(ctx, transcript, re.sub(r"[^A-Za-z0-9_-]", "_", f"claude__{tool}")[:64],
                       given, "denied", f"the {ctx.role} role may only use tools that read",
                       parent=under)
            return deny(ONLY_READS.format(role=ctx.role, tool=tool))
        if copy is not None and tool in CLAUDE_READS:
            # It asks about a read only where it leaves its own folders. Out of a working
            # copy that is the project itself, or anywhere: read in the copy, or in what
            # the copy shares with the project.
            named = next((given[key] for key in ("file_path", "path", "notebook_path")
                          if isinstance(given.get(key), str) and given[key]), None)
            why = None
            # (A Glob's pattern is a path too: `../../**` or a full one looks outside.)
            glob_at = _searched(tool, given) if tool == "Glob" else None
            if named and inside(named)[1] is None and not _shared(copy, inside(named)[0]):
                why = OUTSIDE_THE_COPY.format(path=named, root=root)
            elif glob_at and inside(glob_at)[1] is None and not _shared(copy, inside(glob_at)[0]):
                why = OUTSIDE_THE_COPY.format(path=given.get("pattern"), root=root)
            elif named and copy.part and (in_copy := inside(named)[1]) is not None and not (
                    os.path.lexists(inside(named)[0])) and not copy.holds(in_copy):
                # K-buyuk-proje: another part, by its path in a copy of one part - why it is
                # not there, rather than "not found".
                why = NOT_IN_THE_PART.format(path=in_copy, part=copy.part, project=copy.project)
            if why:
                self._note(ctx, transcript, re.sub(r"[^A-Za-z0-9_-]", "_", f"claude__{tool}")[:64],
                           given, "denied", why, parent=under)
                return deny(why)
        if copy is None and tool in CLAUDE_READS:
            # A look outside the project, as for KOLONİ's own tools: in a folder it also
            # works in, or one the user allows - never one KOLONİ never opens.
            named = [given[key] for key in ("file_path", "path", "notebook_path")
                     if isinstance(given.get(key), str) and given[key]]
            if tool == "Glob" and isinstance(given.get("pattern"), str):
                named.append(_searched(tool, given))
            looks = {"Grep": "search", "Glob": "search", "LS": "list_dir"}

            def opens(one: str) -> bool:
                try:
                    opened(str(inside(one)[0]))
                    return True
                except (WorkspaceError, OSError):
                    return False

            # What KOLONİ never opens is refused before the user is asked about the rest.
            for one in sorted(named, key=opens):
                if inside(one)[1] is None:
                    why = await self._native_outside(
                        ctx, transcript, under, looks.get(tool, "read_file"), one,
                        inside(one)[0])
                    if why:
                        return deny(why)
        if tool in ("Grep", "Glob"):
            # KOLONİ's own checkout or record in the project (a folder that holds it, the
            # Desktop: `not_a_project` refuses one in it) is never opened by name; a search
            # of a folder that holds it would read it all - its .env, its logs. Refused at
            # every level, with the place to leave out.
            # (Qoder's come as Grep and Glob, agy's searches as Grep; Copilot is given none.)
            # shortcut: a glob that keeps the search off it is refused all the same; Codex's
            # own reads have no hook - refuse its searches too if it is ever given one.
            try:
                held = Workspace(root).koloni_under(inside(_searched(tool, given))[0].resolve())
            except (OSError, ValueError):
                held = None
            if held is not None:
                why = KOLONI_IN_SEARCH.format(place=held)
                self._note(ctx, transcript, "search", given, "denied", why, parent=under)
                return deny(why)
        return await self._secret_reads(ctx, transcript, watch, tool=tool, given=given,
                                         under=under, deny=deny, inside=inside)

    async def _secret_reads(
        self: "AgentRunner", ctx: Ctx, transcript: "_Transcript", watch: "_Watch", *,
        tool: str, given: dict, under: str | None, deny: Callable[..., dict],
        inside: Callable[[str], tuple[Path, str | None]],
    ) -> dict | None:
        """`_approve_read`'s secret files, each on the user's word: the refusal of the
        first not allowed; None: all were."""
        if tool in CLAUDE_READS and tool not in ("Glob", "LS"):  # (those two only list names)
            # A secret in the folder it works in, as for KOLONİ's own read_file: read only
            # on the user's word, each time - each one it would open. Every read reaches here
            # through its hook (89b): its Read by its path; its Grep by its path, and over a
            # folder (its own, or the whole one) by each secret file there its `glob` could
            # take, as the project's last look listed them (`ProjectView`).
            # shortcut: a secret in a folder that look leaves out (dist, build) is not seen.
            # (A search over KOLONİ's own checkout or record in the project was refused:
            # `_approve_read`.)
            secrets = [one for one in (given.get(key) for key in
                                       ("file_path", "path", "notebook_path"))
                       if isinstance(one, str) and one and inside(one)[1] is not None
                       and secret_named(one, str(inside(one)[1]))]
            searched, start = inside(str(given.get("path") or ".")) if tool == "Grep" else (
                None, None)
            if searched is not None and start is not None and searched.is_dir():
                async with watch.looking:
                    listed = watch.view.paths()
                secrets += [rel for rel in sorted(listed) if secret_in_project(rel)
                            and (start == "." or rel.startswith(f"{start}/"))
                            and _glob_could_take(given.get("glob"), rel)]
            for one in secrets:
                call_id = self._note(ctx, transcript, "read_file", {"path": one}, None, None,
                                     parent=under)
                try:
                    await self._ask_outside(ctx, call_id, one, None)
                except _NobodyToAsk as exc:
                    self._set_call(ctx.cid, call_id, status="denied", result=str(exc),
                                   ended_at=now())
                    return deny(str(exc))
                self._set_call(ctx.cid, call_id, status="succeeded", ended_at=now(),
                               result=f"allowed: {one}, a secret file, this once")
        return None

    async def _ask_leave(
        self: "AgentRunner", ctx: Ctx, transcript: "_Transcript", watch: "_Watch", use_id: str,
        tool: str,
        given: dict, allow: dict, deny, question: str, wanted: str,
    ) -> dict:
        """Ask the user in words about a tool KOLONİ cannot show as a diff or a command.
        `wanted` says the same for a turn nobody is watching, where it is refused before
        any question is put on record: no trigger allows what would be asked in words.
        The question is shown whole; one too long for a card is refused, never cut short:
        what is after the cut would be allowed unseen."""
        cli = getattr(ctx.model, "command", "claude")
        name = re.sub(r"[^A-Za-z0-9_-]", "_", f"{cli}__{tool}")[:64]
        refused = self._nobody_to_ask(ctx, "words", wanted)
        if refused is None and len(question) > CARD_CHARS:
            refused = (f"too long to show on a card whole ({len(question)} characters): make "
                       "it in smaller parts")
        if refused is not None:
            self._note(ctx, transcript, name, given, "denied", refused,
                       parent=watch.under(use_id))
            return deny(refused)
        call_id = self._note(ctx, transcript, name, given, None, None,
                             parent=watch.under(use_id))
        # Headed as KOLONİ's own: what does not show in it (the CLI's words: a path, the
        # tool's inputs) is written out, as where a call of an MCP server's tool is asked about.
        _status, answer = await self._ask_user(ctx, call_id, {
            "question": mcp_client.visible(question), "options": ["Allow", "Deny"]}, leave=True)
        if answer.removeprefix(ANSWER_PREFIX).strip().casefold() == "allow":
            watch.asked_other[use_id] = call_id
            return allow
        why = LEAVE_REJECTED
        self._set_call(ctx.cid, call_id, status="denied", result=why, ended_at=now())
        return deny(why, fixed=True)
