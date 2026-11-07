"""Runs one `run_command` tool call: record it, get it decided, execute it, record the end."""

import asyncio
import contextlib
import os
import re
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app import project_map
from app.commands import (
    MAX_STORED_OUTPUT,
    OutputMask,
    applies_patch,
    danger,
    for_model,
    held_back,
    is_allowed,
    names_secret,
    reads_here,
    recallable,
    rules_here,
    search_reason,
    secret_values,
    standing_asked,
    with_cwd,
)
from app.db.models import Agent, AllowedCommand, Command, Conversation, Project, Run, ToolCall, now
from app.executors.base import Executor, StartError
from app.serialize import allowed_command_out, command_event, command_out
from app.tools import ToolError, plan_command
from app.workspace import Workspace

FLUSH_SECONDS = 0.5
# How long output may keep arriving after the process itself has exited.
DRAIN_GRACE_SECONDS = 2.0
# How long killing a command may take before we stop waiting for it.
KILL_SECONDS = 20.0
TRUNCATED_NOTE = "\n[output truncated: more than 1 MiB]"
# B-321: a refusal ends that one action, not the task - told "do not try another way" and
# "stop and ask", Codex gave up the whole task over one part of one command.
CARRY_ON = ("Carry on with the rest of the task without it, and say in your report what you "
            "could not do.")
REJECTED = (
    "rejected: the user declined to run this command. This is their decision, not a tool "
    "error: do not run it again, or anything that does the same. " + CARRY_ON
)
# B-389 (R187, live): a patch sent as a command, refused, and the agent gave up its change. Not
# the change was refused - the command: it is made with the file tools, as a card of its own.
FILE_TOOLS = ("If the change is still needed, make it with edit_file / write_file (or your own "
              "file edit tool, where you work with your own tools); the user sees it as a file "
              "change. ")
PATCH_REJECTED = (
    "rejected: the user declined to run this patch as a command. Do not run it again, or "
    "anything else that applies a patch, as a command. " + FILE_TOOLS + CARRY_ON
)
# B-393 (R188, live): refused a patch, Copilot's Coder wrote the file with PowerShell instead.
WRITE_REJECTED = (
    "rejected: the user declined to run this command, which writes a file. Do not run it "
    "again, or anything else that writes a file, as a command. " + FILE_TOOLS + CARRY_ON
)
# apply_patch as the program a part of the command runs (`'@ | apply_patch`, a line of its own),
# not a word it names (`grep apply_patch`).
APPLY_PATCH = re.compile(r"(?:^|[|;&])\s*apply_patch\b", re.M)
# A file written by PowerShell or .NET, or by a redirection - not one into nothing (`>$null`,
# `2>&1`) nor an arrow or comparison (`=>`, `->`, `>=`).
# shortcut: blind to quotes - `-m "a > b"` gets this wording too; only the wording, never the card.
WRITES_FILE = re.compile(
    r"(?i)\[\s*(?:system\s*\.\s*)?io\s*\.\s*file\s*\]\s*::\s*(?:write|append)all"
    r"|\b(?:set-content|add-content|out-file)\b"
    r"|(?<![=<>-])>>?(?![>&=])\s*(?!\$null\b|nul\b|/dev/null\b)[^\s|;&]")
# ...and `New-Item … -Value`, looked for part by part: as one pattern, a long line of `new-item`
# with no `-value` took seconds.
NEW_ITEM, WITH_VALUE = re.compile(r"(?i)\bnew-item\b"), re.compile(r"(?i)\s-value\b")


def _writes_file(command: str) -> bool:
    return bool(WRITES_FILE.search(command)) or any(
        NEW_ITEM.search(part) and WITH_VALUE.search(part) for part in re.split(r"[|;&\n]", command))


def rejected(command: str) -> str:
    """What an agent is told of a command the user declined (`PATCH_REJECTED` for a patch,
    `WRITE_REJECTED` for one that writes a file)."""
    if applies_patch(command) or APPLY_PATCH.search(command):
        return PATCH_REJECTED
    # (One that also deletes or the like was refused for that, not for its write.)
    return WRITE_REJECTED if _writes_file(command) and not danger(command) else REJECTED

HELD_BACK = ("(secret variables held back from this command: {names} - the user can pass one "
             "in Settings › This project › Commands and secrets)")
# A command that keeps running (a dev server, slice 42b): the tool answers once it printed
# its address, or its output went quiet for SERVE_QUIET after it began, or SERVE_AT_MOST is up.
SERVE_QUIET = 1.0
SERVE_AT_MOST = 10.0
MAX_SERVING = 3
# How a command ended: its status, exit code, output, and why it failed to start if it did.
Ended = tuple[str, int | None, str, str | None]
# A terminal's colours, and its links (OSC 8: an address round an address).
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
# An address on this machine with its port, as a server prints it - up to the space after it,
# so that one cut between two chunks of output is not taken half.
_LOOPBACK = re.compile(
    r"http://(?:localhost|127\.0\.0\.1|\[::1\]):(\d{1,5})(?:/[^\s'\"<>]*)?(?=[\s'\"<>])"
)


def preview_url(output: str, closed: set[int]) -> str | None:
    """The first address on this machine in a command's output whose port is none of
    `closed` (KOLONİ's own, a model server's), colours aside."""
    for found in _LOOPBACK.finditer(_ANSI.sub("", output)):
        if 0 < int(found[1]) < 65536 and int(found[1]) not in closed:
            return found[0]
    return None


def port_of(url: str | None) -> int | None:
    try:
        parts = urlsplit(url or "")
        return parts.port or {"http": 80, "https": 443}.get(parts.scheme)
    except ValueError:  # not a port at all
        return None


class CommandRunner:
    def __init__(
        self,
        session_factory,
        bus,
        executors: Callable[[str, Project], Executor],
        update_run: Callable[..., None],
    ):
        self._factory = session_factory
        self.bus = bus
        self._executors = executors
        self._update_run = update_run
        # command id -> future resolved with "once", "always" or "reject"
        self._decisions: dict[str, asyncio.Future[str]] = {}
        # command id -> (conversation id, output so far) while the command runs
        self._live: dict[str, tuple[str, str]] = {}
        # command id -> what hides the secrets in its output, while it runs (slice 90)
        self._masks: dict[str, OutputMask] = {}
        # The kills under way, each with the folder its command ran in. One that failed
        # stays: its process may still be alive.
        self._ending: dict[asyncio.Future, Path] = {}
        # How the user's decision is waited for, for an agent (by its id): whoever owns
        # the agents' places puts its own here, so that one that waits holds none. Its
        # last argument is called with the decision as soon as it is there, and with
        # whether the agent has to wait for a place before it can go on.
        self.users_word: Callable[
            [str, asyncio.Future[str], Callable[[str, bool], None]], Awaitable[str]
        ] | None = None
        # The ports a served address may not have: KOLONİ's own, the model servers'.
        self.closed_ports: Callable[[], set[int]] = set
        # A turn's secrets the user gave on a card (slice 91), by run id: name -> value.
        self.secrets: Callable[[str], dict[str, str]] = lambda _run_id: {}
        # command id -> (conversation id, its task) while a command that keeps running runs
        self._serving: dict[str, tuple[str, asyncio.Task]] = {}
        self._closing = False

    def decide(self, command_id: str, decision: str) -> bool:
        """Deliver the user's decision to the waiting run; False if nothing waits."""
        future = self._decisions.get(command_id)
        if future is None or future.done():
            return False
        future.set_result(decision)
        return True

    def live_outputs(self, conversation_id: str) -> dict[str, str]:
        return {k: text for k, (cid, text) in self._live.items() if cid == conversation_id}

    async def run(
        self, run_id: str, cid: str, agent_id: str, ws: Workspace, call_id: str, args: dict,
        ask: bool = True, where: Callable[[], Awaitable[Workspace]] | None = None,
        always: bool = False, web_off: bool = False, once: set[str] | None = None,
    ) -> tuple[str, str]:
        """Returns the tool call's final status and the result text for the model.
        `ask` is False where the command has its leave already and nobody can be asked
        (an unattended turn, by its trigger): it runs, whatever the conversation says.
        `ws` is where it runs: the project folder, or the agent's working copy.
        `where`: asked once the command may run, for where it then runs - an agent's
        working copy is made by its first command, and not for one that is refused.
        `always`: asked about at every level, as `ask_for`'s (`copy_reason`). `web_off`: that
        is because web is off (`web_off_reason`): no rule is offered. `once`: commands the
        user said yes to on a card, exactly as written, that the level alone does not ask again
        (K-evrim's measure, for its run) - what asks at every level still does; a yes on this
        one's card is added to it."""
        planned = plan_command(ws, args)
        searched = await asyncio.to_thread(
            search_reason, planned.command, ws.root, planned.cwd_rel)
        reads = await asyncio.to_thread(
            reads_here, planned.command, ws.root, planned.cwd_rel == ".")
        with self._factory() as session:
            conversation = session.get_one(Conversation, cid)
            project = session.get_one(Project, conversation.project_id)
            if planned.keep_running:
                self._may_serve(session, cid, project, ws, ask, where,
                                lead=session.get_one(Agent, agent_id).depth == 0)
            prefixes = [rule.prefix for rule in session.scalars(rules_here(conversation))]
            # (Its id is said beside a cut output only where recall_output would give it.)
            asked = session.get(ToolCall, call_id)
            recall = call_id if asked is not None and recallable(
                asked.name, asked.outside_folder, None, planned.command) else None
            # One the user is not asked about runs on a yes given before - a rule, the
            # level, its trigger's leave: "approved" from the first, so that while its
            # start is waited for it is not shown as waiting for the user, and a turn
            # that ends before it starts does not leave it "rejected". A server is asked
            # for every time but in Full auto: no rule covers one. One that names a secret
            # file is asked for at every level (slice 90), and so is one that searches the
            # whole folder while it holds one, or names `.koloni` (86c) or another file that
            # steers later turns (`names_standing`, B-79), or has a reason in a working copy
            # (`copy_reason`, which its card shows from its call's record). One that only reads
            # is not (K-ask-okuma), nor the user's own test command run in its part's folder
            # (`project_map.own_test`).
            own = project_map.own_test(project.test_commands, planned.command, planned.cwd_rel)
            # (K-fullauto-sorma: at Full auto an instruction file alone is not asked.)
            # (Judged with its cwd, `with_cwd`: `cwd=.koloni/tmp` and `.. ` reach out of it.)
            judged = with_cwd(planned.command, planned.cwd_rel)
            asks = ask and (always or names_secret(judged) or bool(standing_asked(
                judged, conversation.permission_mode != "full_auto"))
                or bool(searched) or (
                conversation.permission_mode != "full_auto"
                and (planned.keep_running or not (is_allowed(planned.command, prefixes)
                                                  or reads or own
                                                  or planned.command in (once or ())))))
            # The place is fixed now: changing the project setting while this command
            # waits for a decision must not move it somewhere the user did not see.
            command = Command(
                run_id=run_id,
                agent_id=agent_id,
                tool_call_id=call_id,
                command=planned.command,
                cwd=planned.cwd_rel,
                location=project.exec_location,
                image=project.docker_image if project.exec_location == "docker" else None,
                timeout_seconds=planned.timeout,
                status="proposed" if asks else "approved",
                keep_running=planned.keep_running,
                web_off=web_off,
            )
            session.add(command)
            session.commit()
            command_id, location = command.id, command.location
            payload = command_out(command, held=bool(searched))
            rule = payload["suggested_prefix"]
        self.bus.emit(cid, run_id, "command.created", payload)

        if asks:
            # (`rule` is empty when this command cannot be remembered.)
            decision = await self._wait_for_decision(run_id, cid, agent_id, command_id, rule)
            if decision == "reject":
                self._set(cid, command_id, status="rejected", ended_at=now())
                return "denied", rejected(planned.command)
            if once is not None:
                once.add(planned.command)

        try:
            if where is not None:
                ws = await where()
                planned = plan_command(ws, args)
        except ToolError as exc:  # its folder is not in the copy (one that is left out)
            self._set(
                cid, command_id, status="failed_to_start", output=f"error: {exc}", ended_at=now()
            )
            return "failed", f"error: {exc}"
        try:
            in_copy = ws.root != Path(project.root_path).resolve()
            # shortcut: a command that keeps running (42b) keeps what it was given after the
            # turn; stop such a one at the turn's end if a secret is ever given to a server.
            given = self.secrets(run_id)
            running = await self._executors(location, project).start(
                command_id, planned.command, planned.cwd_path,
                copy=ws.root if in_copy else None, links=ws.links if in_copy else None,
                secrets=given,
            )
        except StartError as exc:
            # The reason stays on the record, so the user sees it and not only the model.
            self._set(
                cid, command_id, status="failed_to_start", output=f"error: {exc}", ended_at=now()
            )
            return "failed", f"error: {exc}"

        self._set(cid, command_id, status="running", started_at=now())
        self._live[command_id] = (cid, "")
        # (The command gets this machine's environment, `KOLONI_*` and the secret variables
        # the user did not pass aside: what of it is a secret is hidden in what it prints. In
        # Docker it gets none; hiding is harmless.)
        self._masks[command_id] = OutputMask([*secret_values(os.environ), *given.values()])
        # Which were held back (slice 103), by name: the model is told, and that the user can
        # pass one. (Not one the user gave this turn on a card: it has that.)
        held = [name for name in held_back(os.environ, project.pass_env)
                if name.upper() not in given] if location == "host" else []
        note = f"\n{HELD_BACK.format(names=', '.join(held))}" if held else ""
        started = time.monotonic()
        if not planned.keep_running:
            ended = await self._through(cid, command_id, running, ws.root, planned.timeout)
            status, said = self._told(
                *ended, planned.timeout, time.monotonic() - started, recall)
            return status, said + note
        heard = {"url": None, "at": None, "scanned": 0, "closed": self.closed_ports()}
        life = asyncio.ensure_future(
            self._through(cid, command_id, running, ws.root, None, heard))
        self._serving[command_id] = (cid, life)
        life.add_done_callback(lambda _: self._serving.pop(command_id, None))
        status, said = await self._first_words(cid, command_id, life, heard, started)
        return status, said + note

    async def _through(
        self, cid: str, command_id: str, running, root: Path, timeout: int | None,
        heard: dict | None = None,
    ) -> Ended:
        """Watch a started command to its end and record it: how it ended, its exit code,
        its output, and why it failed to start if it did. Raises CancelledError, once that is
        recorded, where it was stopped. `heard`: what a server said of its address."""
        state = {"truncated": False}
        drain = asyncio.ensure_future(self._drain(cid, command_id, running, state, heard))
        code: int | None = None
        cancelled = False
        try:
            code = await asyncio.wait_for(running.wait(), timeout)
            status = "exited"
            # The process is done. Whatever it left running may still hold the output
            # open, so the rest of the output gets a moment, not forever.
            with contextlib.suppress(TimeoutError, Exception):
                await asyncio.wait_for(asyncio.shield(drain), DRAIN_GRACE_SECONDS)
        except TimeoutError:
            status = "timed_out"
        except asyncio.CancelledError:
            # Stop; or, of a server, KOLONİ closing ("stopped when KOLONİ closed").
            status, cancelled = "interrupted" if heard and self._closing else "killed", True
        except Exception:
            status = "killed"
        # From here to the record below nothing may be skipped, whatever arrives:
        # a second Stop must not leave the command "running".
        cancelled = await self._end(running, status != "exited", root) or cancelled
        drain.cancel()
        # What was held back - half a line, with no end after it - comes out hidden now.
        mask = self._masks.pop(command_id, None)
        if mask is not None and (rest := mask.flush()) and not state["truncated"]:
            self._add_output(cid, command_id, rest, state)
        output = self._live.get(command_id, (cid, ""))[1]
        failure = None
        if status == "exited" and code is not None:
            failure = running.start_failure(code, output)
        if failure:
            status = "failed_to_start"
        self._finish(cid, command_id, status, code, state["truncated"])
        if cancelled:
            raise asyncio.CancelledError
        return status, code, output, failure

    @staticmethod
    def _told(
        status: str, code: int | None, output: str, failure: str | None, timeout: int | None,
        seconds: float, call_id: str | None = None,
    ) -> tuple[str, str]:
        """How a command ended, for the model: the tool call's status and its result - where
        that is cut, with the id that gives the whole of it (K-gecmis-zengin).
        shortcut: not a server's (`_first_words`): it goes on printing; pass its id there if
        an agent is seen to need a server's whole output."""
        shown = for_model(output, call_id)
        if failure:
            return "failed", f"error: {failure}\n{shown}"
        if status == "timed_out":
            return "failed", f"error: timed out after {timeout} seconds and was stopped\n{shown}"
        if status != "exited":
            return "failed", f"error: the command was stopped\n{shown}"
        # A non-zero exit code is a result for the model to read, not a tool failure.
        return "succeeded", f"exit code {code} ({seconds:.1f}s)\n{shown}"

    def _may_serve(
        self, session, cid: str, project: Project, ws: Workspace, ask: bool, where,
        lead: bool = False,
    ) -> None:
        """Why a command may not keep running here, as a ToolError: said before anything of
        it is on record. `lead`: the agent is the turn's Lead, in a copy only in a recipe's
        turn (or a side's, a night job's) - there is nobody above it to start it."""
        if project.exec_location == "docker":
            raise ToolError(
                "keep_running is only on this machine for now, and this project runs its "
                "commands in Docker: run it without keep_running, or ask the user to start it")
        # shortcut: never in a working copy (it goes with its agent's work, and a server in it
        # would too); upgrade when a sub-agent has to serve what it made.
        if (where is not None or ws.root != Path(project.root_path).resolve()) and lead:
            raise ToolError(
                "keep_running does not run in the copy you work in: start it once the work is "
                "taken into the project (the user's Take in), or run the server and its test in "
                "one command without keep_running")
        if where is not None or ws.root != Path(project.root_path).resolve():
            raise ToolError(
                "keep_running runs in the project folder itself, not in a working copy: "
                "say what to start, and the Orchestrator starts it")
        if not ask:
            raise ToolError("keep_running is not for a turn nobody watches")
        serving = session.scalar(
            select(func.count()).select_from(Command).join(Run, Run.id == Command.run_id).where(
                Run.conversation_id == cid, Command.keep_running,
                Command.status.in_(("proposed", "approved", "running")),
            )
        )
        if serving >= MAX_SERVING:
            raise ToolError(
                f"at most three commands keep running in a conversation, and {serving} do: "
                "nothing was started. The user can stop one under Preview")

    async def _first_words(
        self, cid: str, command_id: str, life: asyncio.Future[Ended], heard: dict,
        started: float,
    ) -> tuple[str, str]:
        """The answer for a command that keeps running: once it said its address, its output
        went quiet or SERVE_AT_MOST is up - or, where it ended first, as any command's."""
        while not life.done() and heard["url"] is None and (
            (heard["at"] is None or time.monotonic() - heard["at"] < SERVE_QUIET)
            and time.monotonic() - started < SERVE_AT_MOST
        ):
            await asyncio.sleep(0.05)
        if not life.done() and heard["url"] is None and heard["at"] is not None:
            # (one printed last, with nothing after it, is whole once its output went quiet -
            # and still held back, with the half line it is on)
            mask = self._masks.get(command_id)
            output = self._live.get(command_id, (cid, ""))[1] + (mask.peek() if mask else "")
            self._look_for_address(cid, command_id, output + "\n", heard)
        if life.done():
            if life.cancelled():
                return "failed", "error: the command was stopped"
            return self._told(*life.result(), None, time.monotonic() - started)
        last = "\n".join(self._live.get(command_id, (cid, ""))[1].splitlines()[-20:])
        where = (f"serving {heard['url']}" if heard["url"]
                 else "no address on this machine in its output yet")
        return "succeeded", (
            f"keeps running as command {command_id}, {where}. The user sees its page under "
            f"Preview and can stop it there. Its last lines:\n{for_model(last)}"
        )

    def stop(self, command_id: str) -> bool:
        """Stop a command that keeps running, with what it started; False if none does."""
        serving = self._serving.get(command_id)
        if serving is None:
            return False
        serving[1].cancel()
        return True

    def stop_all(self, cid: str) -> None:
        """Stop every command of a conversation that keeps running, and turn down one still
        asked about."""
        for command_id, (at, _life) in list(self._serving.items()):
            if at == cid:
                self.stop(command_id)
        with self._factory() as session:
            asked = session.scalars(
                select(Command.id).join(Run, Run.id == Command.run_id).where(
                    Run.conversation_id == cid, Command.keep_running,
                    Command.status == "proposed")
            ).all()
        for command_id in asked:
            self.decide(command_id, "reject")

    async def shutdown(self) -> None:
        """KOLONİ closes: every command that keeps running is stopped, and recorded so."""
        self._closing = True
        lives = [life for _cid, life in self._serving.values()]
        for life in lives:
            life.cancel()
        await asyncio.gather(*lives, return_exceptions=True)

    async def ask_for(
        self, run_id: str, cid: str, agent_id: str, call_id: str, command: str,
        ask: bool = True, always: bool = False, held: bool = False, reads: bool = False,
        web_off: bool = False, cwd: str | None = None,
    ) -> tuple[bool, str]:
        """A command a CLI is about to run with a tool of its own: put it on record,
        get it decided the way KOLONİ's own commands are, and say whether it may run.
        KOLONİ does not run it; the record is completed when the CLI reports the end.
        `always`: asked about at every level, whatever was allowed before - as one that
        names a secret file always is. `held`: as `command_out`'s; `web_off`: as `run`'s.
        `reads`: it only reads (`reads_here`), so below Full auto it is not asked. `cwd`:
        where the CLI says it runs, on the record as KOLONİ's own commands' is ("." for
        the root), so that the card is judged the same when it is read again. What it
        prints comes from the CLI, hidden there (`AgentRunner._observe_command`) for the
        screen and the record - the CLI's own model has read it already."""
        with self._factory() as session:
            conversation = session.get_one(Conversation, cid)
            row = Command(
                run_id=run_id, agent_id=agent_id, tool_call_id=call_id, command=command,
                cwd=cwd, location="host", timeout_seconds=0, origin="cli", web_off=web_off,
            )
            session.add(row)
            session.commit()
            command_id, payload = row.id, command_out(row, held=held)
            mode = conversation.permission_mode
            prefixes = [rule.prefix for rule in session.scalars(rules_here(conversation))]
            tests = session.scalar(select(Project.test_commands).where(
                Project.id == conversation.project_id))
        self.bus.emit(cid, run_id, "command.created", payload)
        # (as `run`'s: the user's own test command in its part's folder is not asked)
        own = project_map.own_test(tests, command, cwd)
        if ask and (always or names_secret(command)
                    or standing_asked(command, mode != "full_auto")
                    or (mode != "full_auto"
                        and not (is_allowed(command, prefixes) or reads or own))):
            decision = await self._wait_for_decision(
                run_id, cid, agent_id, command_id, payload["suggested_prefix"])
            if decision == "reject":
                self._set(cid, command_id, status="rejected", ended_at=now())
                return False, command_id
        self._set(cid, command_id, status="running", started_at=now())
        return True, command_id

    def ending(self, root: Path) -> list[asyncio.Future]:
        """The kills of commands that ran in a folder which are not over, or failed:
        while there is one, a process may still be at work in that folder."""
        return [kill for kill, at in self._ending.items() if at == root]

    async def _end(self, running, kill: bool, root: Path) -> bool:
        """Kill (if asked) and release a command; returns whether Stop arrived meanwhile.

        Bounded and shielded: a kill that hangs, fails or is interrupted never keeps
        the caller from recording how the command ended. `root`: where it ran.
        """

        async def end() -> None:
            if kill:
                await running.kill()
            await running.close()

        task = asyncio.ensure_future(asyncio.wait_for(end(), KILL_SECONDS))
        if kill:
            self._ending[task] = root
            task.add_done_callback(
                lambda done: None if done.cancelled() or done.exception()
                else self._ending.pop(done, None)
            )
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            return True  # the kill carries on in the background
        except Exception:
            pass  # could not kill it; the record still says what we know
        return False

    def close_open(self, run_id: str, cid: str, agent_id: str | None = None) -> None:
        """Settle whatever a run (or one of its agents) leaves behind: a command nobody
        decided on is rejected, one the user said yes to that never started - its agent
        never got its place, or its start never came back - is interrupted ("rejected"
        is the user's own no), and one still marked running (its task was cut short) is
        killed."""
        with self._factory() as session:
            query = select(Command).where(
                Command.run_id == run_id,
                Command.status.in_(("proposed", "approved", "running")),
            )
            if agent_id is not None:
                query = query.where(Command.agent_id == agent_id)
            # (A command that keeps running outlives its turn: it is stopped by itself.)
            leftover = [c for c in session.scalars(query) if c.id not in self._serving]
            for command in leftover:
                if command.status == "running":
                    command.output = self._live.pop(command.id, (cid, command.output))[1]
                    command.status = "killed"
                else:
                    command.status = (
                        "interrupted" if command.status == "approved" else "rejected")
                command.ended_at = now()
            session.commit()
            payloads = [command_event(command) for command in leftover]
        for payload in payloads:
            self.bus.emit(cid, run_id, "command.updated", payload)

    # --- steps -----------------------------------------------------------------

    async def _wait_for_decision(
        self, run_id: str, cid: str, agent_id: str, command_id: str, rule: str
    ) -> str:
        """`rule`: what "Always run" puts on the conversation's allow list for it."""
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._decisions[command_id] = future
        self._update_run(run_id, cid, status="waiting_approval")

        def heard(word: str, waits: bool) -> None:
            # "Always run" is the user's word about later commands: it is kept the
            # moment it is said, whether or not this command ever gets to run.
            if word == "always":
                self._add_rule(cid, rule)
            # A yes is on record the moment it is given - "approved", not the user's to
            # decide a second time - whether or not anything is waited for before the
            # command runs: a place for its agent, or its start (a container, a working
            # copy). And where its agent has to stand in line, a no is too: it needs no
            # place.
            if word != "reject":
                self._set(cid, command_id, status="approved")
            elif waits:
                self._set(cid, command_id, status="rejected", ended_at=now())

        try:
            if self.users_word:
                decision = await self.users_word(agent_id, future, heard)
            else:
                decision = await future
                heard(decision, False)
        finally:
            self._decisions.pop(command_id, None)
            # Also when the wait is cut short: the turn no longer waits on this one.
            self._update_run(run_id, cid, status="running")
        return decision

    def _add_rule(self, cid: str, prefix: str) -> None:
        if not prefix:
            return
        with self._factory() as session:
            project_id = session.get_one(Conversation, cid).project_id
            session.add(AllowedCommand(conversation_id=cid, project_id=project_id, prefix=prefix))
            try:
                session.commit()
            except IntegrityError:  # the rule is already there
                session.rollback()
        self.emit_rules(cid)

    def emit_rules(self, cid: str) -> None:
        with self._factory() as session:
            rules = session.scalars(rules_here(session.get_one(Conversation, cid))
                                    .order_by(AllowedCommand.created_at)).all()
            payload = {"rules": [allowed_command_out(rule) for rule in rules]}
        self.bus.emit(cid, None, "allowed_commands.updated", payload)

    async def _drain(
        self, cid: str, command_id: str, running, state: dict, heard: dict | None = None
    ) -> None:
        """Read the output to the end; keep and publish at most MAX_STORED_OUTPUT of it. Of
        a command that keeps running (`heard`), take the first address it serves on."""
        last_flush = time.monotonic()
        mask = self._masks[command_id]
        async for chunk in running:
            if state["truncated"]:
                continue  # keep reading so the process is never blocked on a full pipe
            if heard is not None:
                heard["at"] = time.monotonic()
            chunk = mask.feed(chunk)
            if not chunk:
                continue  # half a line: it waits for the rest (a secret may be cut in two)
            output = self._add_output(cid, command_id, chunk, state)
            if heard is not None and heard["url"] is None:
                self._look_for_address(cid, command_id, output, heard)
            if time.monotonic() - last_flush >= FLUSH_SECONDS:
                last_flush = time.monotonic()
                self._save_output(command_id, output)

    def _add_output(self, cid: str, command_id: str, chunk: str, state: dict) -> str:
        """Keep and publish a piece of a command's output, at most MAX_STORED_OUTPUT of it
        in all; returns the output so far."""
        current = self._live[command_id][1]
        room = MAX_STORED_OUTPUT - len(current)
        if len(chunk) > room:
            chunk = chunk[:room] + TRUNCATED_NOTE
            state["truncated"] = True
        self._live[command_id] = (cid, current + chunk)
        self.bus.emit_transient(cid, "command.output", {"command_id": command_id, "text": chunk})
        return current + chunk

    def _look_for_address(self, cid: str, command_id: str, output: str, heard: dict) -> None:
        # (From a little before where the last look ended: an address cut by a chunk is whole.)
        # shortcut: the address is only what the output says - a server that prints none stays
        # "starting"; find the loopback port its process tree listens on if one is seen (B-351).
        url = preview_url(output[max(0, heard["scanned"] - 512):], heard["closed"])
        heard["scanned"] = len(output)
        if url:
            heard["url"] = url
            self._set(cid, command_id, preview_url=url)

    def _save_output(self, command_id: str, output: str) -> None:
        with self._factory() as session:
            session.get_one(Command, command_id).output = output
            session.commit()

    def _finish(
        self, cid: str, command_id: str, status: str, code: int | None, truncated: bool
    ) -> str:
        output = self._live.pop(command_id, (cid, ""))[1]
        self._set(
            cid,
            command_id,
            status=status,
            exit_code=code if status == "exited" else None,
            output=output,
            output_truncated=truncated,
            ended_at=now(),
        )
        return output

    def _set(self, cid: str, command_id: str, **fields) -> None:
        with self._factory() as session:
            command = session.get_one(Command, command_id)
            for key, value in fields.items():
                setattr(command, key, value)
            session.commit()
            run_id, payload = command.run_id, command_event(command)
        self.bus.emit(cid, run_id, "command.updated", payload)
