"""Full auto's judge (0.1.9), its gate: at Full auto, before a command the list does not stop runs,
a small model is asked once whether it is risky (`app.risk_judge`) - `RiskJudgeMixin`."""

import asyncio
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import func, literal_column, select
from sqlalchemy.exc import IntegrityError

from app import away, ledger, project_map, proof, proof_style, raw, risk_judge
from app.agent.cards import _answer
from app.agent.ctx import Ctx
from app.command_runner import _planted
from app.commands import (
    _INTERPRETER,
    _SHELLS,
    _program,
    _words,
    names_secret,
    only_reads,
    standing_asked,
    with_cwd,
)
from app.db.models import (
    Command,
    Conversation,
    FileChange,
    JudgeAllowed,
    Project,
    Provider,
    Run,
    project_of,
)
from app.providers import ask_once
from app.roles import LEAD, find_role
from app.team import judge_chosen, judge_pick, would_run

if TYPE_CHECKING:
    from app.agent import AgentRunner

log = logging.getLogger("app.agent")
CARD = risk_judge.CARD
# Said once in the chat where the judge cannot be asked for the rest of a turn - none of these is
# the agent's doing (a command that slows it, or one it cannot read, is a card).
ASIDE = "Full auto's judge is off for this turn: {why}."
NO_MODEL = "no model to ask - choose a Judge model in Settings, or give a model the Fast tier"
NO_ROOM = "{provider} has no room for it now"
OVER_LIMIT = "the turn is past its token limit"
# Its card where it was asked and gave no answer to go by: never a run.
LATE = "it did not answer in time"
UNREAD = "its answer could not be read"
FAILED = "it could not be asked"
NOT_LOOKED = "it could not look at this command"

# An option word of an interpreter's or a shell's after which the line holds its code itself
# (`python -c`, `-m`, `node -e`, `bash -c`, PowerShell's `-Command` / `-EncodedCommand` cut short
# as it takes them): no file of its own runs. ...and PowerShell's `-File`, which names the file.
_INLINE = re.compile(r"-(?:c|m.*|e|p|r|-eval|-print)|(?i:-co\w*|-en\w*|-ec)")
_FILE = re.compile(r"(?i)-f(?:i(?:le?)?)?")
# Their options that take a value: the word after one is no script.
_VALUED = frozenset(
    {"-X", "-W", "--require", "--import", "--loader", *("-executionpolicy", "-ep", "-ex")}
    | {"-windowstyle", "-version", "-workingdirectory", "-wd", "-configurationname"}
)


def _script(words: list[str]) -> str:
    """The file a line runs by its name: the script an interpreter or a shell is handed - its
    first word that is no option, or the value of PowerShell's `-File` -, "" where the line holds
    its code (`_INLINE`); else the program itself."""
    program = _program(words[0])
    if not (_INTERPRETER.fullmatch(program) or program in _SHELLS):
        return words[0]
    rest = iter(words[1:])
    for word in rest:
        if _INLINE.fullmatch(word):
            return ""
        if program in ("powershell", "pwsh") and _FILE.fullmatch(word):
            return next(rest, "")
        if word.startswith("-") or program == "cmd" and word.startswith("/"):
            if word in _VALUED or word.lower() in _VALUED:
                next(rest, None)
            continue
        return word
    return ""


def planted_program(factory, cid: str, root: Path, command: str, cwd: str) -> Path | None:
    """The file `command` (run in `cwd` of `root`: the project, or a copy of it) runs by its name
    (`_script`: `node x.js`, `python -u x.py`, `./x.sh`, `bash x.sh`, `powershell -File x.ps1`,
    `x.cmd`) where an agent wrote it - its write on record, of any turn of the project's, as it
    still stands (`proof_style.still_written`): its full path. None: no such file, one out of
    `root`, or the user's own (none on record, or changed since). Blocking: off the event loop.
    shortcut: by the line's first file alone - one it imports, or a tool an agent changed but
    did not write, is not seen (the judge's known limits)."""
    words = [word.strip("'\"") for word in _words(command)]
    words = words[1:] if words[:1] in (["&"], ["."]) else words  # (PowerShell's call)
    name = _script(words) if words else ""
    if not name:
        return None
    home = root.resolve()
    try:
        path = (root / cwd / name).resolve()
        if not path.is_relative_to(home) or not path.is_file():
            return None
    except (OSError, ValueError):
        return None
    rel = path.relative_to(home).as_posix()
    with factory() as session:
        found = session.execute(
            select(FileChange.path, FileChange.after_sha)
            .join(Run, Run.id == FileChange.run_id)
            .join(Conversation, Conversation.id == Run.conversation_id)
            .where(
                Conversation.project_id
                == select(Conversation.project_id).where(Conversation.id == cid).scalar_subquery(),
                FileChange.status.in_((*ledger.KEPT, proof.MERGED)),
                func.lower(FileChange.path) == rel.lower(),
            )
            .order_by(FileChange.created_at, literal_column("file_changes.rowid"))
        ).all()
    newest = dict(found)  # (the last write of each spelling)
    return path if proof_style.still_written(root, newest.items()) else None


def _program_read(path: Path, root: Path) -> tuple[tuple[str, str, int], str]:
    """What the judge is shown of a program an agent wrote: its path from `root`, the text of its
    first PROGRAM_BYTES and the bytes left - and the digest of all of it, which its key holds (a
    change past what is shown is a change too)."""
    with path.open("rb") as file:
        head = file.read(risk_judge.PROGRAM_BYTES)
        file.seek(0)
        digest = hashlib.file_digest(file, "sha256").hexdigest()
    left = max(0, path.stat().st_size - len(head))
    rel = path.relative_to(root.resolve()).as_posix()
    return (rel, head.decode("utf-8", "replace"), left), digest


class RiskJudgeMixin:
    async def _risk_judged(
        self: "AgentRunner",
        ctx: Ctx,
        command: str,
        cwd: str | None,
        root: Path,
        found: tuple[str, dict | None],
        *,
        exempt: bool,
    ) -> tuple[str, dict | None]:
        """Full auto's judge: why `command` (run in `cwd` of `root`, the project or the copy it
        works in) waits for the user on a card though KOLONİ found no reason of its own - asked
        only where none was found, nor any by the check of the user's words (`found`, their
        reason and record: given back as they are). ("", record) - it runs, its record "fine";
        ("", None) - not judged; (`CARD`, record "risky") - its card.
        Not judged: not a watched Full auto turn nor a job's at Full auto (a trigger's never), a
        line the user lets run or KOLONİ asks of anyway (`exempt`: a skill's script they allowed,
        a disposable delete, a reason in a working copy, a role that runs no command),
        the project's switch off (read at each command), one that only reads, their own test
        command, one asked at every level anyway (a secret, a file that steers later turns), an
        ordinary line (`risk_judge.ordinary`, what it runs not an agent's: `_planted`, W7), one
        they said Run to on its card this turn - or not to ask about again here (`JudgeAllowed`),
        or the judge stood aside for the turn. A card unasked: `risk_judge.risky_unasked`.
        Whatever goes wrong in it but a Stop is its card, never a run."""
        if exempt or found != ("", None):
            return found
        try:
            if not (self._full_auto(ctx) or self._away_full_auto(ctx)):
                return "", None
            return await self._risk_judging(ctx, command, cwd, root)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("run %s: Full auto's judge failed", ctx.run_id, exc_info=True)
            return CARD.format(why=NOT_LOOKED), None

    def _risk_line(
        self: "AgentRunner", ctx: Ctx, command: str, cwd: str, root: Path
    ) -> tuple[bool, tuple[str, str, int] | None, str]:
        """Whether a line is ordinary (`risk_judge.ordinary`, nothing it runs an agent's), and the
        program an agent wrote that it runs: as shown, and its digest ("": none). Blocking."""
        npm = [_program(word) for word in _words(command.strip())[:1]] == ["npm"]  # (npm.cmd)
        plain = (
            risk_judge.ordinary(command, npm_run=True)
            and _planted(self._factory, ctx.cid, root, command, cwd) is None
            # W7: what `npm test` and `npm run x` run is package.json's - an agent's, where one of
            # its writes of one (or of a lock, a runner's setting) still stands: as npx's reads
            and not (npm and _planted(self._factory, ctx.cid, root, "npx -", cwd))
        )
        path = None if plain else planted_program(self._factory, ctx.cid, root, command, cwd)
        if path is None:
            return plain, None, ""
        shown, digest = _program_read(path, root)
        return plain, shown, digest

    async def _risk_judging(
        self: "AgentRunner", ctx: Ctx, command: str, cwd: str | None, root: Path
    ) -> tuple[str, dict | None]:
        """`_risk_judged`'s work, which may raise."""
        line = with_cwd(command, cwd)
        with self._factory() as session:
            project = project_of(session, session.get_one(Conversation, ctx.cid))
            if (
                project is None
                or not project.full_auto_judge
                or only_reads(command)
                or project_map.own_test(project.test_commands, command, cwd)
                or names_secret(line)
                or standing_asked(line, False)
            ):
                return "", None
            project_id = project.id
        plain, program, digest = await asyncio.to_thread(
            self._risk_line, ctx, command, cwd or ".", root
        )
        if plain:
            return "", None
        key = (command.strip(), cwd or "", digest)
        if self._risk_cache.get(ctx.run_id, {}).get(key) == "approved" or self._risk_allowed(
            project_id, key
        ):
            return "", None
        record = {"kind": "risk", "verdict": "risky", "why": "", "model": "", "program": digest}
        if why := risk_judge.risky_unasked(command, program[1] if program else None):
            return CARD.format(why=why), {**record, "why": why}
        if ctx.run_id in self._risk_aside:
            return "", None
        return await self._risk_asked(ctx, command, cwd, program, key, record)

    def _risk_allowed(self: "AgentRunner", project_id: str, key: tuple[str, str, str]) -> bool:
        """Whether the user said on a judge's card not to ask about this line again here."""
        command, cwd, digest = key
        with self._factory() as session:
            found = session.scalar(
                select(JudgeAllowed.id).where(
                    JudgeAllowed.project_id == project_id,
                    JudgeAllowed.command == command,
                    JudgeAllowed.cwd == cwd,
                    JudgeAllowed.program_sha == digest,
                )
            )
        return found is not None

    def _risk_aside_why(self: "AgentRunner", session, ctx: Ctx, picked, project) -> str:
        """Why the judge cannot be asked now, none of it the agent's doing: no model to ask, the
        turn past its token limit, no room on the model's provider; "" for none."""
        limit = project.turn_token_limit
        if picked is None:
            return NO_MODEL
        if limit and self._turn_spent(session, ctx.run_id)[0] > limit:
            return OVER_LIMIT
        provider = session.get_one(Provider, picked[0].provider_id)
        return (
            ""
            if self._has_room(session, provider, project)
            else NO_ROOM.format(provider=provider.name)
        )

    async def _risk_asked(
        self: "AgentRunner",
        ctx: Ctx,
        command: str,
        cwd: str | None,
        program: tuple[str, str, int] | None,
        key: tuple[str, str, str],
        record: dict,
    ) -> tuple[str, dict | None]:
        """The judge asked (`_risk_asks`) - once a turn for the line and the user's words as they
        are -, what it reads masked (`raw.hidden`); or, where it cannot be asked
        (`_risk_aside_why`), it stands aside for the turn, said once in the chat (`ASIDE`), and the
        line runs as Full auto runs it."""
        with self._factory() as session:
            conversation = session.get_one(Conversation, ctx.cid)
            project = session.get_one(Project, conversation.project_id)
            # (A job's: the chat the user went away from - never its task's own words.)
            night = away.night_of(session, ctx.cid) if ctx.run_id in self._away_jobs else None
            said = self._users_words(
                session, night.conversation_id if night else ctx.cid, project.rules
            )
            full = (*key, hashlib.sha256(json.dumps(said, sort_keys=True).encode()).hexdigest())
            cache = self._risk_cache.setdefault(ctx.run_id, {})
            if isinstance(found := cache.get(full), dict):
                return ("" if found["verdict"] == "fine" else CARD.format(why=found["why"])), found
            would = would_run(session, find_role(session, LEAD), conversation)
            picked = judge_pick(session, would, self.providers, judge_chosen(session))
            if aside := self._risk_aside_why(session, ctx, picked, project):
                self._risk_aside[ctx.run_id] = aside
                self._koloni_line(ctx.cid, ctx.run_id, ASIDE.format(why=aside))
                return "", None
            assert picked is not None  # (`_risk_aside_why` says NO_MODEL for none)
            asking, mode = self._on(session, ctx, *picked)
            earlier = session.scalars(
                select(Command.command)
                .where(Command.run_id == ctx.run_id, Command.agent_id == ctx.agent_id)
                .order_by(Command.created_at.desc(), literal_column("commands.rowid").desc())
                .limit(risk_judge.EARLIER)
            ).all()
        asked = risk_judge.prompt(
            said,
            {
                "command": raw.hidden(command),
                "where": raw.hidden(cwd) if cwd else "not known",
                "by": "Orchestrator" if not ctx.depth else raw.hidden(f"sub-agent {ctx.role}"),
            },
            [raw.hidden(one) for one in reversed(earlier)],
            (raw.hidden(program[0]), raw.hidden(program[1]), program[2]) if program else None,
        )
        record = {**record, "model": f"{asking.provider} · {asking.model_name}"}
        got, failed = await self._risk_asks(ctx, asking, mode, asked)
        if got is None:
            return CARD.format(why=failed), {**record, "why": failed}
        cache[full] = record = {**record, **got, "why": raw.hidden(got["why"])}
        return ("" if got["verdict"] == "fine" else CARD.format(why=record["why"])), record

    async def _risk_asks(
        self: "AgentRunner", ctx: Ctx, asking: Ctx, mode: str | None, asked: str
    ) -> tuple[dict | None, str]:
        """The judge's one request, in the turn's usage (`_own_request`): its word
        (`risk_judge.verdict`), or None and why - it timed out (`API_SECONDS`, a CLI's
        `CLI_SECONDS`), failed or said nothing that can be read. Stop goes on as Stop."""
        try:
            try:
                limit = risk_judge.API_SECONDS if mode is None else risk_judge.CLI_SECONDS
                async with asyncio.timeout(limit):
                    said, answer = await ask_once(
                        asking.model, asking.model_name or "", [{"role": "user", "content": asked}]
                    )
            except BaseException:
                self._own_request(ctx, asking, mode, None)  # sent, and not heard out
                raise
            self._own_request(ctx, asking, mode, answer)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return None, LATE
        except Exception:
            log.warning("run %s: Full auto's judge was not answered", ctx.run_id, exc_info=True)
            return None, FAILED
        got = risk_judge.verdict(_answer(said))
        return got, "" if got else UNREAD

    def _risk_approved(self: "AgentRunner", command_id: str, remember: bool) -> None:
        """The user's Run on a card of Full auto's judge: its line - the command, its folder and
        the digest of the program it ran as the judge saw it - is not asked again this turn, and
        with `remember` (its card's "Don't ask about this line again here") nor in this project
        again. Nothing for another card."""
        with self._factory() as session:
            row = session.get(Command, command_id)
            record = row.judged if row is not None else None
            if row is None or not isinstance(record, dict) or record.get("kind") != "risk":
                return
            key = (row.command.strip(), row.cwd or "", record.get("program") or "")
            self._risk_cache.setdefault(row.run_id, {})[key] = "approved"
            project_id = session.scalar(
                select(Conversation.project_id)
                .join(Run, Run.conversation_id == Conversation.id)
                .where(Run.id == row.run_id)
            )
            if not remember or project_id is None:
                return
            command, cwd, digest = key
            session.add(
                JudgeAllowed(project_id=project_id, command=command, cwd=cwd, program_sha=digest)
            )
            try:
                session.commit()
            except IntegrityError:  # (said before)
                session.rollback()
