"""Full auto's judge (0.1.9), its gate: at Full auto, before a command the list does not stop runs,
a small model is asked once whether it is risky (`app.risk_judge`) - `RiskJudgeMixin`."""

import asyncio
import hashlib
import json
import logging
import re
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, NamedTuple

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
from app.workspace import in_scratch

if TYPE_CHECKING:
    from app.agent import AgentRunner

log = logging.getLogger("app.agent")
CARD = risk_judge.CARD
# Said once in the chat where the judge cannot be asked for the rest of a turn: no model to ask -
# nothing an agent can bring about (one that slows the judge, spends its turn's tokens or its
# provider's room, or writes what it cannot read, gets a card).
ASIDE = "Full auto's judge is off for this turn: {why}."
NO_MODEL = "no model to ask - choose a Judge model in Settings, or give a model the Fast tier"
# Its card where it may not be asked now, or was asked and gave no answer to go by: never a run.
NO_ROOM = "it could not be asked: {name} has no room for it now"
OVER_LIMIT = "it could not be asked: the turn is past its token limit"
CHANGED = "the program it runs changed while it was looked at"
LATE = "it did not answer in time"
UNREAD = "its answer could not be read"
FAILED = "it could not be asked"
NOT_LOOKED = "it could not look at this command"
NO_REASON = "it gave no reason"  # (a "risky" with no sentence)

# An option word of an interpreter's after which the line holds its code itself (`python -c`,
# `node -e`, `-p`, `-r`): no file of its own runs (`python -m x` is read as its module's file). A
# shell's are fewer: `bash -c`, PowerShell's `-Command` / `-EncodedCommand` cut short as it takes
# them - `bash -e x.sh` runs x.sh. ...and PowerShell's `-File`, which names the file.
_INLINE = re.compile(r"-(?:c|e|p|r|-eval|-print)")
_SHELL_INLINE = re.compile(r"-c|(?i:-co\w*|-en\w*|-ec)")
_FILE = re.compile(r"(?i)-f(?:i(?:le?)?)?")
_PYTHON = re.compile(r"python[\d.]*w?|pyw?")
# Their options that take a value: the word after one is no script.
_VALUED = frozenset(
    {"-X", "-W", "--require", "--import", "--loader", *("-executionpolicy", "-ep", "-ex")}
    | {"-windowstyle", "-version", "-workingdirectory", "-wd", "-configurationname"}
)
# What a name with no ending may be, as its runner looks: Node's, a Python's folder, and a
# program by its path on Windows (PowerShell's `.\x` runs x.ps1, cmd's x.cmd).
_NODE_ENDINGS = ("", ".js", ".mjs", ".cjs", "/index.js")
_PYTHON_ENDINGS = ("", "/__main__.py")
_RUN_ENDINGS = ("", ".ps1", ".cmd", ".bat")


def _endings(name: str, endings: tuple[str, ...]) -> list[str]:
    """`name` and, where it has no ending of its own, `name` with each of `endings`."""
    if PurePosixPath(name.replace("\\", "/")).suffix:
        return [name]
    return [name + one for one in endings]


def _script(words: list[str]) -> list[str]:
    """The files a line may run by their name, in the order its runner looks: the script an
    interpreter or a shell is handed - its first word that is no option, or the value of
    PowerShell's `-File` -, `python -m x`'s module (x.py, x/__main__.py), Node's name with no
    ending; none where the line holds its code (`_INLINE`, a shell's `_SHELL_INLINE`); else the
    program itself, where named by its path (a bare name runs from PATH alone under KOLONİ: W1)."""
    program = _program(words[0])
    interpreter = bool(_INTERPRETER.fullmatch(program))
    if not (interpreter or program in _SHELLS):
        return _endings(words[0], _RUN_ENDINGS) if re.search(r"[\\/]", words[0]) else []
    python, node = bool(_PYTHON.fullmatch(program)), program.startswith(("node", "bun", "deno"))
    rest = iter(words[1:])
    for word in rest:
        if python and word.startswith("-m"):
            module = (word[2:] or next(rest, "")).replace(".", "/")
            return [f"{module}.py", f"{module}/__main__.py"] if module else []
        if (_INLINE if interpreter else _SHELL_INLINE).fullmatch(word):
            return []
        if program in ("powershell", "pwsh") and _FILE.fullmatch(word):
            return [next(rest, "")]
        if word.startswith("-") or program == "cmd" and word.startswith("/"):
            if word in _VALUED or word.lower() in _VALUED:
                next(rest, None)
            continue
        return _endings(word, _NODE_ENDINGS if node else _PYTHON_ENDINGS if python else ("",))
    return []


def _named_file(root: Path, command: str, cwd: str) -> Path | None:
    """The file `command` (run in `cwd` of `root`: the project, or a copy of it) runs by its name
    (`_script`: `node x.js`, `node x`, `python -u x.py`, `python -m x`, `./x.sh`, `bash x.sh`,
    `powershell -File x.ps1`, `.\\x`), its full path - the first that is a file in `root`; None:
    none such (a name not found, or out of `root`: no digest, and nothing kept for the line)."""
    words = [word.strip("'\"") for word in _words(command)]
    words = words[1:] if words[:1] in (["&"], ["."]) else words  # (PowerShell's call)
    home = root.resolve()
    for name in _script(words) if words else []:
        try:
            path = (root / cwd / name).resolve()
            if name and path.is_relative_to(home) and path.is_file():
                return path
        except (OSError, ValueError):
            continue
    return None


def _agents(factory, cid: str, root: Path, path: Path) -> bool:
    """Whether `path` (in `root`) is as an agent wrote it - its write on record, of any turn of
    the project's, still stands (`proof_style.still_written`) - or in the agents' scratch, theirs
    whoever wrote it there (`workspace.in_scratch`)."""
    rel = path.relative_to(root.resolve()).as_posix()
    if in_scratch(rel):
        return True
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
    return bool(proof_style.still_written(root, newest.items()))


def planted_program(factory, cid: str, root: Path, command: str, cwd: str) -> Path | None:
    """The file `command` runs by its name (`_named_file`) where an agent wrote it (`_agents`):
    its full path. None: no such file, one out of `root`, or the user's own (none on record, or
    changed since). Blocking: off the event loop.
    shortcut: by the line's first file alone - one it imports, or a tool an agent changed but
    did not write, is not seen (the judge's known limits)."""
    path = _named_file(root, command, cwd)
    return path if path is not None and _agents(factory, cid, root, path) else None


def _digest(path: Path) -> str:
    """The digest of all of a file ("" where it cannot be read: gone, say)."""
    try:
        with path.open("rb") as file:
            return hashlib.file_digest(file, "sha256").hexdigest()
    except OSError:
        return ""


def _program_read(path: Path, root: Path) -> tuple[tuple[str, str, int], str]:
    """A program a line runs: its path from `root`, the text of its first PROGRAM_BYTES and the
    bytes left - and the digest of all of it, which the line's key holds (a change past what is
    shown is a change too, and so is one no write on record made).
    shortcut: the whole file hashed at each judged command; cap it if a big one slows a turn."""
    with path.open("rb") as file:
        head = file.read(risk_judge.PROGRAM_BYTES)
    left = max(0, path.stat().st_size - len(head))
    rel = path.relative_to(root.resolve()).as_posix()
    return (rel, head.decode("utf-8", "replace"), left), _digest(path)


class _Seen(NamedTuple):
    """What of a line besides it the judge goes by: the file it runs by its name (`_named_file`;
    None: none found, or its folder no fact), that program as shown where an agent wrote it, its
    digest ("": none), and what the same agent ran before it in the turn."""

    path: Path | None
    program: tuple[str, str, int] | None
    digest: str
    earlier: list[str]


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
        known: bool = True,
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
        command (but where an agent wrote the program it runs), one asked at every level anyway
        (a secret, a file that steers later turns), an ordinary line (`risk_judge.ordinary`, what
        it runs not an agent's: `_planted`, W7), one they said Run to on its card this turn - or
        not to ask about again here (`JudgeAllowed`) -, or where it stood aside for the turn (no
        model to ask). A card unasked: `risk_judge.risky_unasked`.
        `known`: False where `cwd` is no fact (a CLI's folder not known, or its model's word):
        then no program is read. Nothing is kept for such a line - neither its verdict, nor a Run
        on its card -, nor for one whose program file was not found to hash (`_named_file`):
        what it runs may change unseen, the same words in another folder be another line.
        Whatever goes wrong in it but a Stop is its card, never a run."""
        if exempt or found != ("", None):
            return found
        try:
            if not (self._full_auto(ctx) or self._away_full_auto(ctx)):
                return "", None
            return await self._risk_judging(ctx, command, cwd, root, known)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("run %s: Full auto's judge failed", ctx.run_id, exc_info=True)
            return CARD.format(why=NOT_LOOKED), None

    def _risk_line(
        self: "AgentRunner", ctx: Ctx, command: str, cwd: str, root: Path, known: bool
    ) -> tuple[bool, Path | None, tuple[str, str, int] | None, str]:
        """Whether a line is ordinary (`risk_judge.ordinary`, nothing it runs an agent's); the
        file it runs by its name (`_named_file`, where `known`); that program as the judge is
        shown it where an agent wrote it (`_agents`), and its digest whoever wrote it ("": no
        file found). Blocking."""
        npm = [_program(word) for word in _words(command.strip())[:1]] == ["npm"]  # (npm.cmd)
        plain = (
            risk_judge.ordinary(command, npm_run=True)
            and _planted(self._factory, ctx.cid, root, command, cwd) is None
            # W7: what `npm test` and `npm run x` run is package.json's - an agent's, where one of
            # its writes of one (or of a lock, a runner's setting) still stands: as npx's reads
            and not (npm and _planted(self._factory, ctx.cid, root, "npx -", cwd))
        )
        path = None if plain or not known else _named_file(root, command, cwd)
        if path is None:
            return plain, None, None, ""
        shown, digest = _program_read(path, root)
        return plain, path, shown if _agents(self._factory, ctx.cid, root, path) else None, digest

    async def _risk_judging(
        self: "AgentRunner", ctx: Ctx, command: str, cwd: str | None, root: Path, known: bool
    ) -> tuple[str, dict | None]:
        """`_risk_judged`'s work, which may raise."""
        line = with_cwd(command, cwd)
        with self._factory() as session:
            project = project_of(session, session.get_one(Conversation, ctx.cid))
            if (
                project is None
                or not project.full_auto_judge
                or only_reads(command)
                or names_secret(line)
                or standing_asked(line, False)
            ):
                return "", None
            project_id = project.id
            own = project_map.own_test(project.test_commands, command, cwd)
            earlier = self._risk_earlier(session, ctx)
        plain, path, program, digest = await asyncio.to_thread(
            self._risk_line, ctx, command, cwd or ".", root, known
        )
        # (the user's own test command is theirs - but not where it runs a program an agent wrote)
        if plain or own and program is None:
            return "", None
        key = (command.strip(), cwd or "", digest, str(root)) if known and digest else None
        if key and (
            self._risk_cache.get(ctx.run_id, {}).get(key) == "approved"
            or self._risk_allowed(project_id, key)
        ):
            return "", None
        # ("program", "root": the line's key, for `_risk_approved` - "program" None: none; no
        # fields of `schemas.Judged`)
        record: dict = {"kind": "risk", "verdict": "risky", "why": "", "model": ""}
        record |= {"program": key and digest, "root": str(root)}
        if why := risk_judge.risky_unasked(command, program[1] if program else None, earlier):
            return CARD.format(why=why), {**record, "why": why}
        if ctx.run_id in self._risk_aside:
            return "", None
        seen = _Seen(path, program, digest, earlier)
        return await self._risk_asked(ctx, command, cwd, seen, key, record)

    @staticmethod
    def _risk_earlier(session, ctx: Ctx) -> list[str]:
        """What the same agent ran before in the turn - one that started: not one refused, turned
        down or never run -, at most `EARLIER`, oldest first, each masked (`raw.hidden`)."""
        ran = session.scalars(
            select(Command.command)
            .where(
                Command.run_id == ctx.run_id,
                Command.agent_id == ctx.agent_id,
                Command.started_at.is_not(None),
            )
            .order_by(Command.created_at.desc(), literal_column("commands.rowid").desc())
            .limit(risk_judge.EARLIER)
        ).all()
        return [raw.hidden(one) for one in reversed(ran)]

    def _risk_allowed(self: "AgentRunner", project_id: str, key: tuple[str, ...]) -> bool:
        """Whether the user said on a judge's card not to ask about this line again here: its
        command, folder and program digest (in any copy of the project)."""
        command, cwd, digest = key[:3]
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

    def _risk_no_room(self: "AgentRunner", session, ctx: Ctx, picked, project) -> str:
        """Why the judge's model may not be asked now: the turn past its token limit, no room on
        its provider - an agent may bring either about (its own request spends), so its card;
        "" for none."""
        limit = project.turn_token_limit
        if limit and self._turn_spent(session, ctx.run_id)[0] > limit:
            return OVER_LIMIT
        provider = session.get_one(Provider, picked[0].provider_id)
        return (
            "" if self._has_room(session, provider, project) else NO_ROOM.format(name=provider.name)
        )

    async def _risk_asked(
        self: "AgentRunner",
        ctx: Ctx,
        command: str,
        cwd: str | None,
        seen: _Seen,
        key: tuple[str, ...] | None,
        record: dict,
    ) -> tuple[str, dict | None]:
        """The judge asked (`_risk_asks`) - once a turn for a line with a key and the user's words
        as they are -, what it reads masked (`raw.hidden`); a "fine" whose program changed while
        it was asked is a card. Where no model can be asked it stands aside for the turn, said
        once in the chat (`ASIDE`), and the line runs as Full auto runs it; where one may not be
        asked now (`_risk_no_room`), its card."""
        with self._factory() as session:
            conversation = session.get_one(Conversation, ctx.cid)
            project = session.get_one(Project, conversation.project_id)
            # (A job's: the chat the user went away from - never its task's own words.)
            night = away.night_of(session, ctx.cid) if ctx.run_id in self._away_jobs else None
            said = self._users_words(
                session, night.conversation_id if night else ctx.cid, project.rules
            )
            digest = hashlib.sha256(json.dumps(said, sort_keys=True).encode()).hexdigest()
            full = (*key, digest) if key else None
            cache = self._risk_cache.setdefault(ctx.run_id, {})
            if full and isinstance(found := cache.get(full), dict):
                why = found["why"] or NO_REASON
                return ("" if found["verdict"] == "fine" else CARD.format(why=why)), found
            would = would_run(session, find_role(session, LEAD), conversation)
            picked = judge_pick(session, would, self.providers, judge_chosen(session))
            if picked is None:
                self._risk_aside[ctx.run_id] = NO_MODEL
                self._koloni_line(ctx.cid, ctx.run_id, ASIDE.format(why=NO_MODEL))
                return "", None
            if why := self._risk_no_room(session, ctx, picked, project):
                return CARD.format(why=why), {**record, "why": why}
            asking, mode = self._on(session, ctx, *picked)
        program = seen.program
        asked = risk_judge.prompt(
            said,
            {
                "command": raw.hidden(command),
                "where": raw.hidden(cwd) if cwd else "not known",
                "by": "Orchestrator" if not ctx.depth else raw.hidden(f"sub-agent {ctx.role}"),
            },
            seen.earlier,
            (raw.hidden(program[0]), raw.hidden(program[1]), program[2]) if program else None,
        )
        record = {**record, "model": f"{asking.provider} · {asking.model_name}"}
        got, failed = await self._risk_asks(ctx, asking, mode, asked)
        if got is None:
            return CARD.format(why=failed), {**record, "why": failed}
        record = {**record, **got, "why": raw.hidden(got["why"])}
        if seen.path and await asyncio.to_thread(_digest, seen.path) != seen.digest:
            return CARD.format(why=CHANGED), {**record, "verdict": "risky", "why": CHANGED}
        if full:
            cache[full] = record
        why = record["why"] or NO_REASON
        return ("" if got["verdict"] == "fine" else CARD.format(why=why)), record

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
        """The user's Run on a card of Full auto's judge: its line - the command, its folder, the
        digest of the program it ran as the judge saw it and where it ran (a copy, say) - is not
        asked again this turn, and with `remember` (its card's "Don't ask about this line again
        here") nor in this project again, in any copy. Nothing for another card, nor for one
        with no key (`_risk_judged`'s `known`, or no program file found)."""
        with self._factory() as session:
            row = session.get(Command, command_id)
            record = row.judged if row is not None else None
            if (
                row is None
                or not isinstance(record, dict)
                or record.get("kind") != "risk"
                or not record.get("program")
            ):
                return
            key = (row.command.strip(), row.cwd or "", record["program"], record.get("root", ""))
            self._risk_cache.setdefault(row.run_id, {})[key] = "approved"
            project_id = session.scalar(
                select(Conversation.project_id)
                .join(Run, Run.conversation_id == Conversation.id)
                .where(Run.id == row.run_id)
            )
            if not remember or project_id is None:
                return
            command, cwd, digest = key[:3]
            session.add(
                JudgeAllowed(project_id=project_id, command=command, cwd=cwd, program_sha=digest)
            )
            try:
                session.commit()
            except IntegrityError:  # (said before)
                session.rollback()
