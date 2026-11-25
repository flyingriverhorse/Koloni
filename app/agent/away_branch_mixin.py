"""☾ Away, a job on its own branch (0.1.9, `app.away_branch`): where the project is a git
repository, a job's turn works on `koloni/<task>` in a worktree (`_away_on_branch`), its CLI told so
(`_git_section`); its end commits what is left there and puts the branch on record, its push waiting
for the user's Run in the morning (`_away_branch_end`); a later turn of the job - its second try,
its going-on turn after the user's decisions - goes on in that worktree (`_as_away_branch`); and
the morning's push itself (`push_away_branch`). Never into the project: that is Take in's.
H1 (`copies.no_push`), H2 (`away_branch.refs`), H3 (the push held to what was checked)."""

import asyncio
import hashlib
import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import away, away_branch, checks_now, copies, git, parked, raw, web
from app.agent.context_mixin import git_prompt
from app.agent.ctx import Ctx
from app.agent.merge import _as_branch, _few, _git_parts, _kept_as, _kept_branch, _secret_forms
from app.agent.story_branch_mixin import branch_there
from app.commands import secret_values, spellings_of
from app.db.away_models import Parked
from app.db.models import Agent, AwayRun, BacklogTask, Merge, Project, Run, now
from app.project_view import standing as standing_files

if TYPE_CHECKING:
    from app.agent import AgentRunner, _LeadTurn

log = logging.getLogger(__name__)

# What of an earlier Orchestrator's record a later turn of the job goes on with (`_as_away_branch`).
CARRIED = ("tree", "parts", "branch", "on_branch", "start", "snapshot", "from_head", "not_taken")
# Under the job's turn where its branch could not be kept as one at its end.
NOT_ON_BRANCH_END = "KOLONİ: the job's work is kept as a copy, not on its branch: {why}."
# The morning's push (H3): why it pushed nothing - the row stays, to try again.
GONE = "{name} is gone: nothing was pushed"
MOVED_SINCE = "{name} moved since the job ended ({old} → {new}): nothing was pushed"
NOT_NOW = "{why}: nothing was pushed"
TAKEN = "its work was taken in or discarded: nothing to push"
UNDER_WAY = "its push or its Take in is under way"
PUSH_SECRET = "{files} on the branch holds a secret KOLONİ knows - take it off the branch first"
# (D1: a branch of that name made on origin between its look and the push - git's own words name
# this machine's folders)
ON_ORIGIN = "origin already has a branch named {name}: nothing was pushed"
# ...and what it asks a second Run for.
PUSH_CONFIG = (
    "git's config changed since the job began - a push runs what it names (an address, a "
    "credential helper, an ssh command): look at it, then Run again"
)
PUSH_KEPT_OUT = "It changed {files}, where you said nothing may change while you were away"
# (git resolves origin's push address in every scope of its config: one added since moves it)
PUSH_ELSEWHERE = (
    "A push to origin goes to {now} now, not to {then} as when the job began: Run anyway pushes "
    "it there"
)
REFS_UNKNOWN = "git did not say what the repository's refs are now: what moved is not known"
# ...and why nothing is pushed where the project moved off the branch its push goes into (L5).
INTO_MOVED = (
    "the project is on {now} now, not on {into} as when the job ended: switch back to {into}, "
    "then Run again - nothing was pushed"
)
# A pull request's body: what an agent wrote (its notes, the files' names) in a code block, so
# that no @mention, closing keyword or link of it is read by GitHub (`_fenced`).
PUSH_BODY = (
    "{task}\n\nMade by KOLONİ's agents ({name}) while you were away, on the branch `{branch}`, "
    "pushed as one commit.\n\n### Changed files\n{files}\n\n### KOLONİ's checks\n{checks}\n\n"
    "### {name}'s notes\n{notes}\n"
)


def _fenced(text: str) -> str:
    """`text` as a code block whose fence is longer than any run of backticks in it."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{text}\n{fence}"


# What of the repository a night's jobs are compared with: taken once, at Go away (`night_base`).
BASE = ("refs", "config", "hooks", "push_to", "push_shown")


def git_state(project: Path) -> dict:
    """What of git runs, or says where a push goes, as it is now (H2, H3): its config in every
    scope (`away_branch.config_digest`), its hooks (`_git_parts`) and the address a push to origin
    goes to (`git.push_address`) - by its digest, and as it is shown (`web.kept_url`: never a
    password - it is kept on records the page reads). Blocking: git is asked, the hooks read."""
    url = git.push_address(project)
    return {
        "config": away_branch.config_digest(project),
        "hooks": _git_parts(standing_files(str(project)), project)["hooks"],
        "push_to": hashlib.sha256(url.encode()).hexdigest() if url else "",
        "push_shown": web.kept_url(url),
    }


def night_base(project: Path) -> dict:
    """M-B: what every job of a night is compared with, taken once as the user goes away - the
    repository's refs and `git_state` - so what an earlier job planted is seen by a later one's
    push too. Blocking."""
    return {"refs": away_branch.refs(project), **git_state(project)}


def _nothing(why: object) -> str:
    """Why nothing was pushed, said once."""
    said = str(why)
    return said if said.rstrip(".").endswith("nothing was pushed") else NOT_NOW.format(why=said)


def _elsewhere(held: dict, state: dict) -> list[str]:
    """The note where a push to origin goes elsewhere now than as the night began (MEDIUM-2)."""
    if state["push_to"] == (held.get("push_to") or ""):
        return []
    then, now = held.get("push_shown") or "none", state["push_shown"] or "none"
    return [PUSH_ELSEWHERE.format(now=now, then=then)]


class AwayBranchMixin:
    async def _away_on_branch(self: "AgentRunner", run_id: str, t: "_LeadTurn", ctx: Ctx) -> None:
        """A job's turn, as it starts, where its Go away found a git repository: on its branch in
        a worktree - its earlier try's, kept (`_as_away_branch`), or a new one (`_working_copy`) -
        H1 set there, and the repository's refs and git's config on its record (H2). Where git
        will not now, the job works in a copy, told why, and its card says so."""
        with self._factory() as session:
            task = away.job_of(session, ctx.cid)
            night = session.get(AwayRun, task.away_run_id) if task and task.away_run_id else None
            job = (
                next((one for one in night.jobs if one.get("task_id") == task.id), None)
                if night and task
                else None
            )
            kept = [
                merge
                for merge in away.kept_copies(session, ctx.cid)
                if self._undecided(merge)
                and "away" in (session.get_one(Agent, merge.agent_id).copy or {})
            ]
        if (
            not t.root
            or task is None
            or night is None
            or job is None
            or job.get("mode") in (None, "copy")
        ):
            return
        if ctx.agent_id not in self._copies and kept:  # (its earlier try's: TRIES)
            self._resume_in[run_id] = kept[-1].id
            self._resume_held(ctx)
        copy, why = self._copies.get(ctx.agent_id), None
        if copy is None:
            mode, why = await asyncio.to_thread(away_branch.mode_of, Path(t.root))
            if mode != "copy":
                self._on_branch[ctx.agent_id] = git.task_branch(task.title, task.id)
                await self._git_start(ctx)
                copy = await self._working_copy(ctx, ctx.agent_id)
                why = self._no_branch.pop(ctx.agent_id, None)
        if copy is None or not copy.branch:
            said = (why or away_branch.NO_GIT_NOW).rstrip(".")
            self._nudge(ctx, away_branch.NOT_ON_BRANCH_NOW.format(why=said))
            with self._factory() as session:
                night = session.get_one(AwayRun, night.id)
                night.jobs = [
                    {**one, "mode": "copy", "mode_why": said}
                    if one.get("task_id") == task.id
                    else one
                    for one in night.jobs
                ]
                session.commit()
            return
        copies.no_push(copy.root)
        with self._factory() as session:
            record = session.get_one(Agent, ctx.agent_id).copy or {}
        was = record.get("away") or {}
        # (M-B: the night's, taken at Go away - what an earlier job planted is seen by this one's
        # push too; a card from before that: as this job first began)
        base = job.get("base") or {key: was[key] for key in BASE if key in was}
        base = base or await asyncio.to_thread(night_base, Path(t.root))
        now_away = {**was, "mode": job["mode"], **base}
        self._set_agent(ctx.cid, ctx.agent_id, copy={**record, "away": now_away})

    def _no_push_if_away(self: "AgentRunner", merge: Merge, copy: copies.Copy) -> None:
        """H1 where a kept copy opened again (a morning's Run line) is a job's branch: whatever
        runs there pushes nothing - after a restart too, which forgot this process's trees."""
        with self._factory() as session:
            if "away" in (session.get_one(Agent, merge.agent_id).copy or {}):
                copies.no_push(copy.root)

    @staticmethod
    def _night_branches(session: Session, night: AwayRun | None, copy: copies.Copy) -> set[str]:
        """L-3: the branches of a night's own jobs (each its own push) - this one's, and those its
        other jobs' records name: what H2 does not count as changed outside a job's branch. A
        `koloni/` branch of another day's is the user's to count."""
        found = {copy.branch or ""}
        for task in away.tasks_of(session, night) if night is not None else []:
            mine = (
                away_branch.record(session, task.conversation_id) if task.conversation_id else None
            )
            found.add(str(((mine[0].copy or {}).get("on_branch") if mine else None) or ""))
        return found - {""}

    def _git_section(self: "AgentRunner", ctx: Ctx, seen: dict, copy: copies.Copy | None) -> str:
        """A CLI's git section (slice 70): in a job on its branch, that branch's (`AWAY_GIT`)."""
        if copy is not None and copy.branch and ctx.run_id in self._away_jobs:
            return away_branch.AWAY_GIT.format(branch=copy.branch)
        return git_prompt(seen["branch"], copy is not None, self._reports_git(ctx))

    def _as_away_branch(
        self: "AgentRunner", session: Session, ctx: Ctx, merge: Merge, copy: copies.Copy
    ) -> copies.Copy:
        """`_resume_held`'s kept copy where it is a job's branch and this turn is the job's (its
        second try, its going-on turn): loaded as the branch it is - its commits go on there -
        with H1 set and its record carried to this Orchestrator. Any other turn (Fix it, a message
        of the user's) has it as a plain copy: it never merges by itself."""
        record = session.get_one(Agent, merge.agent_id).copy or {}
        found = _kept_branch(session, merge.agent_id, copy.root.parent)
        if found is None or "away" not in record:
            return copy
        copies.no_push(copy.root)  # (H1 in any turn there - a Fix it's too, after a restart)
        if not away.job_turn(session, session.get_one(Run, ctx.run_id)):
            return copy
        copy = _as_branch(copy, found)
        copy.secrets = lambda run_id=ctx.run_id: self.given_spellings(run_id)
        carried = {key: record[key] for key in CARRIED if key in record}
        session.get_one(Agent, ctx.agent_id).copy = {
            "state": "own",
            **carried,
            "away": record["away"],
        }
        return copy

    async def _away_branch_end(self: "AgentRunner", ctx: Ctx, status: str) -> None:
        """A job's turn on its branch ends, before its worktree is kept (`_set_aside`): what its
        agents left is committed there (`_commit_line`), a branch holding a secret given this turn
        is dropped (`_secret_branch_gone`), and the branch goes on record for the morning - its
        tip, its commits and files, its checks' verdict, what moved outside it (H2) - with its
        push row where it has an origin and the turn completed. Never raises: what goes wrong is
        logged, and the worktree is kept as a copy is."""
        try:
            await self._away_branch_ends(ctx, status)
        except Exception as exc:
            log.warning("run %s: its branch's end not on record: %r", ctx.run_id, exc)

    async def _away_branch_ends(self: "AgentRunner", ctx: Ctx, status: str) -> None:
        copy = self._copies.get(ctx.agent_id)
        if ctx.run_id not in self._away_jobs or copy is None or not copy.branch:
            return
        with self._factory() as session:
            record = session.get_one(Agent, ctx.agent_id).copy or {}
            task = away.job_of(session, ctx.cid)
        held = record.get("away")
        if copy is None or not copy.branch or copy.start is None or not isinstance(held, dict):
            return
        first = ((task.title if task else "").strip().splitlines() or [copy.branch])[0][:72]
        for one in copy.secrets():  # (a secret given this turn goes into no commit's message)
            first = first.replace(one, "***") if one else first
        try:
            await self._commit_line(ctx, copy, first)
        except git.Refused as exc:  # (its worktree on another branch now: a plain copy)
            copy.branch = None
            self._set_agent(
                ctx.cid, ctx.agent_id, copy={**record, "away": {**held, "why": str(exc)}}
            )
            self._koloni_line(ctx.cid, ctx.run_id, NOT_ON_BRANCH_END.format(why=exc))
            return
        look = await self._branch_look(copy)
        if gone := await self._secret_branch_gone(ctx, copy, look):
            self._koloni_line(ctx.cid, ctx.run_id, gone)
            return
        held |= await self._branch_on_record(ctx, copy, look, held)
        self._set_agent(ctx.cid, ctx.agent_id, copy={**record, "away": held})
        self._push_row(ctx, copy, held, look["into"], status == "completed")

    async def _branch_on_record(
        self: "AgentRunner", ctx: Ctx, copy: copies.Copy, look: dict, held: dict
    ) -> dict:
        """What the morning says of a job's branch (`away_branch.row`), as its turn ends."""
        project, tip = copy.project, look["tip"]
        after = await asyncio.to_thread(away_branch.refs, project)
        state = await asyncio.to_thread(git_state, project)
        proof = self._proofs.get(ctx.run_id)
        start = copy.snapshot_sha or (copy.start or ("", ""))[1]
        with self._factory() as session:
            task = away.job_of(session, ctx.cid)
            night = session.get(AwayRun, task.away_run_id or "") if task else None
            ours = self._night_branches(session, night, copy)
        moved = away_branch.moved(held["refs"], after, ours) if held.get("refs") and after else []
        return {
            "tip": tip,
            "into": look["into"],
            "why": look["note"],
            "commits": await asyncio.to_thread(away_branch.commits, project, start, tip)
            if tip
            else None,
            "files": len(look["files"]),
            "checks": checks_now.verdict(
                proof.rows,
                None,
                review=proof.verdict,
                gone_tests=proof.gone_tests,
                loosened=proof.loosened,
                halted=proof.halted,
            )
            if proof is not None
            else checks_now.NOT_COMPLETE,
            "moved": list(dict.fromkeys([*held.get("moved", []), *moved])),
            "config_moved": state["config"] != held.get("config"),
            "hooks_moved": state["hooks"] != held.get("hooks"),
            # (where a push goes, as the job began: the row names it; Run asks where it moved)
            "origin": held.get("push_shown") or state["push_shown"],
        }

    def _push_row(
        self: "AgentRunner", ctx: Ctx, copy: copies.Copy, held: dict, into: str | None, done: bool
    ) -> None:
        """§10: the job's push waits for the user's Run under Waiting for you - one row a task,
        KOLONİ's own (`ref_id` None), made again with this turn's tip (an earlier yes never holds
        for a later tip). Only where the project has an origin, the turn completed and the branch
        holds work; a turn that did not complete closes a row that waits."""
        with self._factory() as session:
            task = away.job_of(session, ctx.cid)
            if task is None or task.away_run_id is None:
                return
            finish_way = session.get_one(Project, task.project_id).finish_way
            rows = session.scalars(
                select(Parked).where(
                    Parked.task_id == task.id, Parked.kind == "push", Parked.decision.is_(None)
                )
            ).all()
            wanted = done and held.get("mode") == "push" and held.get("tip") and held.get("files")
            what = away_branch.push_line(
                held, copy.branch or "", into, finish_way == "pull_request"
            )
            data = {"branch": copy.branch, "tip": held.get("tip"), "tree": str(copy.root)}
            for row in rows:
                if wanted:
                    row.what, row.data = what, data
                else:
                    row.decision, row.decided_at = "stop", now()
            if wanted and not rows:
                parked.park(session, task, "push", None, what, data)
            session.commit()

    async def _origin_is(self: "AgentRunner", copy: copies.Copy) -> str:
        """`away_branch.origin_name`, off the event loop."""
        return await asyncio.to_thread(away_branch.origin_name, copy.project)

    async def push_away_branch(
        self: "AgentRunner", away_id: str, task_id: str, decision: str, seen: list[str]
    ) -> dict:
        """The user's Run (or Reject) of a job's push, from Waiting for you: H3 - its branch still
        there at the tip on record, nothing of it taken in, no secret KOLONİ knows in what goes
        up, a second Run where git's config changed, the repository moved outside the branch,
        a place kept out was changed or the user's own work may go up (`notes`) - then ONE
        commit by KOLONİ pushed to origin (`git.push_one`), and a pull request where the
        project's `finish_way` says so. Its result ("pushed", "pull_request", "rejected"; or
        "refused" with why, "asks" with notes: nothing pushed) is kept on the branch's record."""
        with self._factory() as session:
            task = session.get(BacklogTask, task_id)
            cid = task.conversation_id if task is not None and task.away_run_id == away_id else None
            found = away_branch.record(session, cid) if cid else None
            if found is None:
                return {"state": "refused", "why": TAKEN}
            agent, held = found
            if decision == "reject":  # (whatever became of its work: the row is decided)
                return self._pushed(agent.id, {"state": "rejected"})
            merge = session.scalar(
                select(Merge).where(Merge.kept_in == (agent.copy or {}).get("tree")).limit(1)
            )
            if merge is None or not self._undecided(merge):
                return {"state": "refused", "why": TAKEN}
            if merge.id in self._deciding:
                return {"state": "refused", "why": UNDER_WAY}
            runtime = self.settings.runtime_root
            name = copies.named(runtime, merge.kept_in or "")
            place = copies.place(runtime, name)
            tree, recorded, part = _kept_as(session, agent.id, place)
            on_branch = _kept_branch(session, agent.id, place)
            project = session.get_one(Project, task.project_id)
            night = session.get(AwayRun, away_id)
            what = {
                "root": project.root_path,
                "way": project.finish_way,
                # (its first line: nothing past it - a trailer - goes into the commit or the PR)
                "title": (task.title.strip().splitlines() or ["?"])[0][:72],
                "name": agent.name or agent.role_name,
                "notes": (agent.report or "").strip(),
            }
            passed = [
                os.environ[key.strip()]
                for key in (project.pass_env or "").split(",")
                if len(os.environ.get(key.strip(), "")) >= raw.MIN_SECRET
            ]
            merge_id = merge.id
        if on_branch is None:
            return {"state": "refused", "why": TAKEN}
        # (S1: and every secret KOLONİ knows - its keys, the page's -, not the environment's alone)
        known = [*spellings_of([*secret_values(os.environ), *passed]), *raw.known()]
        for one in known:  # (no secret KOLONİ knows goes up in a commit's message or a PR's words)
            what["title"], what["notes"] = (
                what[key].replace(one, "***") for key in ("title", "notes")
            )
        self._deciding.add(merge_id)
        try:
            copy = _as_branch(
                copies.kept(Path(what["root"]), runtime, name, tree, recorded, part), on_branch
            )
            copy.secrets = lambda: known
            done = await self._push_held(copy, held, night, what, seen)
        except (OSError, ValueError) as exc:
            done = {"state": "refused", "why": NOT_NOW.format(why=exc)}
        finally:
            self._deciding.discard(merge_id)
        return self._pushed(agent.id, done) if done["state"] not in ("asks",) else done

    async def _push_held(
        self: "AgentRunner",
        copy: copies.Copy,
        held: dict,
        night: AwayRun | None,
        what: dict,
        seen: list[str],
    ) -> dict:
        """`push_away_branch` once its kept worktree is opened as the branch it is."""
        look, name = await self._branch_look(copy), copy.branch or ""
        if look["tip"] is None:
            there = await asyncio.to_thread(branch_there, what["root"], name)
            why = NOT_NOW.format(why=look["note"]) if there else GONE.format(name=name)
            return {"state": "refused", "why": why}
        if look["tip"] != held.get("tip"):
            old, new = (held.get("tip") or "none")[:7], look["tip"][:7]
            return {"state": "refused", "why": MOVED_SINCE.format(name=name, old=old, new=new)}
        if look["into"] != held.get("into"):
            why = INTO_MOVED.format(now=look["into"], into=held.get("into"))
            return {"state": "refused", "why": why}
        state = await asyncio.to_thread(git_state, copy.project)
        if (there := _elsewhere(held, state)) and there[0] not in seen:
            return {"state": "asks", "notes": there}  # (named before origin is asked there)
        try:  # (HIGH-1: origin's branches here are origin's, before what is unpushed is counted)
            await asyncio.to_thread(away_branch.origin_checked, copy.project)
        except git.Refused as exc:
            return {"state": "refused", "why": _nothing(exc)}
        notes = await self._push_notes(copy, look, held, night, state)
        if any(note not in seen for note in notes):
            return {"state": "asks", "notes": notes}
        try:
            sent = await self._sent(copy, look)
            files = [path for path, letter in look["files"].items() if letter != "D"]
            if secret := await asyncio.to_thread(
                git.holding, copy.project, sent, files, _secret_forms(copy)
            ):
                raise git.Refused(PUSH_SECRET.format(files=_few(secret)))
            sha = await asyncio.to_thread(
                git.push_one,
                copy.project,
                sent,
                name,
                look["into"] or "",
                (copy.start or ("", ""))[1],
                f"{what['title']}\n\nKoloni-Agent: {what['name']}",
                self.settings.runtime_root / "no-hooks",
                look["tip"],
                copy.snapshot_sha,
                under=copies.folders(self.settings.runtime_root),
            )
        except git.Refused as exc:
            said = str(exc)
            rejected = said.startswith("git push failed") and "[rejected]" in said
            return {
                "state": "refused",
                "why": ON_ORIGIN.format(name=name) if rejected else _nothing(said),
            }
        if what["way"] != "pull_request":
            return {"state": "pushed", "sha": sha}
        return await self._push_pr(copy, look, held, what, sha)

    async def _push_pr(
        self: "AgentRunner", copy: copies.Copy, look: dict, held: dict, what: dict, sha: str
    ) -> dict:
        """The pull request of a branch just pushed, where the project's way is one."""
        repo, off = await asyncio.to_thread(git.pr_ready, copy.project)
        body = PUSH_BODY.format(
            task=_fenced(what["title"]),
            name=what["name"],
            branch=copy.branch,
            files=_fenced(
                "\n".join(
                    f"{path} ({letter})" for path, letter in list(look["files"].items())[:200]
                )
            ),
            checks=held.get("checks") or checks_now.NOT_COMPLETE,
            notes=_fenced(what["notes"][:4000] or "(none)"),
        )
        try:
            if repo is None:
                raise git.Refused(off or "no repository on GitHub")
            url = await asyncio.to_thread(
                git.open_pr,
                copy.project,
                repo,
                copy.branch or "",
                look["into"] or "",
                what["title"],
                body,
                self.settings.runtime_root / "no-hooks",
            )
        except git.Refused as exc:
            return {"state": "pushed", "sha": sha, "why": f"no pull request was opened: {exc}"}
        return {"state": "pull_request", "sha": sha, "url": url}

    async def _push_notes(
        self: "AgentRunner",
        copy: copies.Copy,
        look: dict,
        held: dict,
        night: AwayRun | None,
        state: dict,
    ) -> list[str]:
        """What a push asks a second Run for (H3): the user's own work that may go up with it
        (`_pr_asks`, first: origin's branches were checked against origin), where a push goes now
        if not where it went as the job began, git's config or hooks changed since then, what
        moved outside its branch from the job's start to now (H2, looked at again now), a place
        kept out it changed. `state`: `git_state`'s, now."""
        now = await asyncio.to_thread(away_branch.refs, copy.project)
        with self._factory() as session:
            ours = self._night_branches(session, night, copy)
        known = held.get("refs") and now
        moved = away_branch.moved(held["refs"], now, ours) if known else [REFS_UNKNOWN]
        kept = [
            path for path in look["files"] if away.kept_out(night, path, root=str(copy.project))
        ]
        return [
            *([asks] if (asks := await self._pr_asks(copy)) else []),
            *_elsewhere(held, state),
            *([PUSH_CONFIG] if state["config"] != held.get("config") else []),
            *([away_branch.HOOKS_MOVED] if state["hooks"] != held.get("hooks") else []),
            *dict.fromkeys([*(held.get("moved") or []), *moved]),
            *([PUSH_KEPT_OUT.format(files=_few(kept))] if kept else []),
        ]

    def _pushed(self: "AgentRunner", agent_id: str, done: dict) -> dict:
        """A push's result on the branch's record (`Agent.copy["away"]["push"]`)."""
        with self._factory() as session:
            agent = session.get_one(Agent, agent_id)
            record = agent.copy or {}
            agent.copy = {
                **record,
                "away": {**record.get("away", {}), "push": {**done, "at": now().isoformat()}},
            }
            session.commit()
        return done
