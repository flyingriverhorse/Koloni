"""0.1.8 (the user, 24 Nov: "story per branch + worktree"): a To-do task's turn on a git branch -
its story's, kept from one task to the next and merged at Close the story, or a task of no
story's own - and Close the story's turn, which runs no model: KOLONİ checks the story's branch
and merges it, or opens a pull request (`AgentRunner._merge_branch`)."""

import asyncio
import contextlib
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import backlog, copies, git, stories
from app.agent.ctx import Ctx, announce
from app.agent.merge import _secret_forms
from app.db.models import Agent, BacklogTask, Run, Story, now
from app.team import only_in_project

if TYPE_CHECKING:
    from app.agent import AgentRunner, _LeadTurn

BRANCH_KEPT = (
    "{name}'s changes are committed on branch {branch}, not merged into the project's: {why}. "
    "The user can merge it with git. Do not go on as if they were in the project."
)
BRANCH_SECRET_GONE = (
    "{name}'s changes were not merged, and its branch {branch} was deleted"
    "{earlier}: it held a secret given this turn, which no branch keeps. Do not "
    "go on as if they were in the project."
)
EARLIER_TURNS_TOO = ", with the work of its earlier turns on it"
# A story's tasks go on on its branch, one after another; it goes in at Close the story.
STORY_BRANCH = "it is its story's branch: it goes in when the user closes the story"
# ...where KOLONİ's check of it, at Close the story, did not pass - or the branch holds a secret:
# the branch waits, the story's last task is stuck with why (Fix it).
STORY_RED = "the check {command} did not pass on the story's branch"
STORY_SECRET = "the story's branch holds a secret KOLONİ knows, in {files}: take it off the branch"
# ...or the user turned its merge down: the branch stays, the story open.
STORY_TURNED_DOWN = "you turned its merge down: the story stays open"
# Close the story where its branch cannot be opened now.
CLOSE_NOT_NOW = "the story's branch {branch} could not be opened: {why}. Nothing of it went in"
NOT_ON_A_BRANCH = "the project is not on a branch with a commit now (HEAD detached, or no git)"
# Under a story task's turn: where its work is (`_say_landed`).
STORY_LANDED = (
    "Not in the project yet: the work is on the story's branch {branch}, and goes in when you "
    "close the story."
)


def branch_there(root: str, branch: str) -> bool:
    """Whether the project's git still has the branch (`refs/heads/<branch>`). Where git cannot
    be asked, it counts as there: nothing is taken for gone on a guess."""
    try:
        exe, _folder = git.repository(Path(root))
        return (
            git._in(Path(root), exe, "rev-parse", "--verify", "-q", f"refs/heads/{branch}")[0] == 0
        )
    except (git.Refused, OSError):
        return True


class StoryBranchMixin:
    def _branch_of(
        self: "AgentRunner", session: Session, run: Run
    ) -> tuple[str | None, tuple[str, str] | None]:
        """The story a To-do task's turn (or Close the story's) works for, and the git branch it
        works on (`_turn_on_branch`), named by its story's title and id - the task's where it is
        of no story, or its story is gone or another project's. None: no task's - nor a night's
        job, whose copy is its own."""
        story_id = self._closes_story.get(run.id)
        task = session.get(BacklogTask, run.task_id) if run.task_id and not story_id else None
        if task is not None and task.away_run_id is not None:
            return None, None
        story = (
            session.get(Story, story_id)
            if story_id
            else stories.story_of(session, task.story_id, task.project_id)
            if task
            else None
        )
        if story is not None:
            return story.id, (story.title, story.id)
        return None, (task.title, task.id) if task is not None else None

    async def _turn_on_branch(self: "AgentRunner", run_id: str, t: "_LeadTurn", ctx: Ctx) -> None:
        """K-dal-takim, 0.1.8: a To-do task's whole turn - the Lead too - works on a git branch: its
        story's, kept from one task to the next (`_branch_again` from the story's last
        Orchestrator on it) and merged when the user closes the story; a task of no story's own,
        merged at its end as a team's branch is (`_merge_branch`). Not where git cannot hold one
        (no git, HEAD on no branch, no commit), nor where the Orchestrator is a CLI working in the
        project itself: the task works in the project, its agents held to their claims.
        shortcut: the user's own message in a story's topic works in the project, not on its
        branch; take it onto the branch if users expect the story's work there."""
        closing = run_id in self._closes_story
        if not (t.on_branch and t.root) or t.planning or t.run_compare or t.job:
            return
        if not closing and only_in_project(t.model, t.lead_tools):
            return
        seen = await asyncio.to_thread(git.where, Path(t.root))
        if not (seen and seen["branch"] and seen["head"]):
            return
        self._on_branch[ctx.agent_id] = git.task_branch(*t.on_branch)
        self._branch_runs[run_id] = ctx.agent_id
        if t.story_id is not None:
            self._story_runs[run_id] = t.story_id
        # (Its story's last turn on the branch - a task of no story's own last, kept where it did
        # not finish: its fix round, a run again after a Stop, goes on there.)
        with self._factory() as session:
            earlier = stories.branch_lead(
                session, t.story_id, None if t.story_id else t.on_branch[1]
            )
        if earlier is not None:
            self._branch_again(ctx, earlier)
        if ctx.agent_id in self._left_on:
            # Its worktree at once, not at its first change: what it reads is the branch's work.
            await self._git_start(ctx)
            await self._working_copy(ctx, ctx.agent_id)

    def _landed_on_branch(self: "AgentRunner", session: Session, run_id: str) -> str | None:
        """Where a story task's turn left its work (`_say_landed`): on the story's branch, for
        Close the story - None for any other turn, or one that left nothing on the branch."""
        if run_id not in self._story_runs or run_id in self._closes_story:
            return None
        held = session.scalar(
            select(Agent.copy).where(Agent.run_id == run_id, Agent.depth == 0).limit(1)
        )
        branch = (held or {}).get("on_branch")
        return STORY_LANDED.format(branch=branch) if branch else None

    def close_story(self: "AgentRunner", run_id: str, story_id: str) -> None:
        """Close the story (`app.api.stories`): this turn, on the story's branch, runs no model -
        its branch goes in by KOLONİ's check (`_close_story`)."""
        self._closes_story[run_id] = story_id
        self.start(run_id)

    async def _close_story(self: "AgentRunner", ctx: Ctx) -> tuple[str, str | None]:
        """Close the story's turn, in place of a model's: the story's branch opened in a worktree
        (`_working_copy`, at the commit its last task left), for `_merge_branch` to check - with
        every secret KOLONİ knows looked for in it, not only this turn's - and merge, or open a
        pull request (`finish_way`), at the turn's end. Where it cannot be opened: the story is
        done only where git says the branch is gone (deleted by hand); else the turn fails with
        why, the story open and its branch as it was."""
        story_id = self._closes_story[ctx.run_id]
        with self._factory() as session:
            lead = stories.branch_lead(session, story_id)
            held = (session.get_one(Agent, lead).copy or {}) if lead else {}
        branch = held.get("on_branch") or held.get("left_on") or ""
        copy = None
        if ctx.run_id in self._branch_runs:
            await self._git_start(ctx)
            copy = await self._working_copy(ctx, ctx.agent_id)
        if copy is not None and copy.branch:
            # (and every secret KOLONİ checks, at its merge: `Copy.every_secret`, MEDIUM-2)
            copy.secrets = lambda run_id=ctx.run_id: self.given_spellings(run_id)
            return "completed", None
        why = self._no_branch.get(ctx.agent_id) or NOT_ON_A_BRANCH
        self._drop_copy(ctx.agent_id)  # (a plain copy in its place is nothing to take in)
        self._branch_runs.pop(ctx.run_id, None)
        if branch and ctx.root and not await asyncio.to_thread(branch_there, ctx.root, branch):
            self._went_in.add(ctx.run_id)  # (gone from git: nothing of it waits)
            return "completed", None
        return "failed", CLOSE_NOT_NOW.format(branch=branch or "?", why=why.rstrip("."))

    def _story_closed(self: "AgentRunner", run_id: str) -> None:
        """After Close the story's turn: its branch went in - the story is done - or it was held
        (its check did not pass, it holds a secret): the story's last task is stuck with why (Fix
        it goes on on the branch). Otherwise (turned down, stopped, not opened) it stays open."""
        story_id = self._closes_story.get(run_id)
        if story_id is None:
            return
        with self._factory() as session:
            story = session.get(Story, story_id)
            if story is None:
                return
            if run_id in self._went_in:
                # (No later turn goes on on that branch: it went in.)
                if (lead := stories.branch_lead(session, story_id)) is not None:
                    agent = session.get_one(Agent, lead)
                    agent.copy = {**(agent.copy or {}), stories.BRANCH_GONE: True}  # (whole)
                story.closed_at = now()
            elif (red := self._closed_red.get(run_id)) and (
                last := stories.last_task(session, story_id)
            ) is not None:
                last.status = "blocked"
                backlog.set_flow(last, stuck=red, fix=None)
            session.commit()
            project_id = story.project_id
        announce(self._factory, self.bus, project_id, "backlog.changed")

    async def _branch_kept(
        self: "AgentRunner", ctx: Ctx, copy: copies.Copy, look: dict, why: str
    ) -> str:
        """`_merge_branch`'s work left committed on its branch, unmerged - told to go on, the agent
        goes on there (`_branch_again`), and so does its story's next turn: the commit it stopped
        on goes on its record. What its opener is told. (A branch holding a secret given in its
        turn goes - but not at Close the story, whose every earlier task's work is on it: held.)"""
        with self._factory() as session:
            record = session.get_one(Agent, ctx.agent_id).copy or {}
        closing = ctx.run_id in self._closes_story
        if not closing and (gone := await self._secret_branch_gone(ctx, copy, look)):
            return gone
        # (The commit it stopped on: a go-on opens this branch only while it holds it.)
        self._set_agent(
            ctx.cid, ctx.agent_id, copy={**record, "tip": look["tip"] or record.get("tip")}
        )
        return BRANCH_KEPT.format(name=ctx.name, branch=copy.branch or "", why=why)

    def _drop_branch(self: "AgentRunner", copy: copies.Copy, force: bool = False) -> None:
        """K-dal-takim: a branch copy's folder is deleted - git's record of its worktree goes,
        and its branch where its work is merged, or `force` (turned down: `git.drop_branch`).
        shortcut: on the event loop, as the folder's delete is; a thread if that is felt."""
        if copy.branch:
            with contextlib.suppress(git.Refused):
                git.drop_branch(
                    copy.project,
                    copy.root,
                    copy.branch,
                    self.settings.runtime_root / "no-hooks",
                    force,
                    keep=copy.branch in self._keep_branches,
                )
            self._keep_branches.discard(copy.branch)

    def _shown_name(self: "AgentRunner", ctx: Ctx) -> str:
        """N11: an agent as the screen calls it (the Orchestrator, not "Lead"), for a branch's
        commit subject; the commit's `Koloni-Agent:` trailer keeps its recorded name."""
        with self._factory() as session:
            return self._title(session, ctx.cid, ctx.name)

    def _kept_branch_gone(
        self: "AgentRunner",
        ctx: Ctx,
        project: Path,
        held: Path,
        on_branch: dict | None,
        decision: str,
    ) -> None:
        """W-1: a kept branch copy's folder is gone (`_decide_kept`) - git's record of its worktree
        goes, and its branch (`git.drop_branch`, unlocked first): forced where the user turned it
        down, or took all of it in and no go-on is on record to open it again (`tip`); else only
        where git finds it merged. Where git will not, the branch stays, as unmerged work does.
        N12: a job's branch that went is on its record, for its morning row (`away_branch.row`)."""
        if on_branch is None:
            return
        try:
            git.drop_branch(
                project,
                held / copies.TREE,
                on_branch["branch"],
                self.settings.runtime_root / "no-hooks",
                force=decision == "reject" or not on_branch["tip"],
            )
        except git.Refused:
            return
        with self._factory() as session:
            record = session.get_one(Agent, ctx.agent_id).copy or {}
        if isinstance(away := record.get("away"), dict):
            self._set_agent(ctx.cid, ctx.agent_id, copy={**record, "away": {**away, "gone": True}})

    async def _secret_branch_gone(
        self: "AgentRunner", ctx: Ctx, copy: copies.Copy, look: dict | None = None
    ) -> str:
        """K-dal-takim: a branch that would sit unmerged with a secret given this turn on it is
        not kept - dropped whole, its worktree and the branch (`-D`). What its opener is told;
        "" where it holds none. `look`: `git.branch_look`'s, made already.
        shortcut: a branch opened again (`_branch_again`: a tip on its record) goes whole, with
        the work of its earlier turns, and is said so; take this turn's commits off alone if
        that loss is felt (its reflog holds the secret still)."""
        look = look or await self._branch_look(copy)
        if not look["tip"] or not await asyncio.to_thread(
            git.holding,
            copy.project,
            look["tip"],
            [path for path, letter in look["files"].items() if letter != "D"],
            _secret_forms(copy, every=False),  # (HIGH-1: one KOLONİ knows stops it, never drops it)
        ):
            return ""
        with self._factory() as session:
            record = session.get_one(Agent, ctx.agent_id).copy or {}
        self._drop_copy(ctx.agent_id, "rejected")
        return BRANCH_SECRET_GONE.format(
            name=ctx.name,
            branch=copy.branch,
            earlier=(EARLIER_TURNS_TOO if record.get("tip") else ""),
        )

    async def _said_gone(self: "AgentRunner", ctx: Ctx, copy: copies.Copy) -> None:
        """Stop - or the app closing - while a branch's way in is under way (its card, its
        check, a resolve): `_secret_branch_gone`, said in the chat; else the branch stays."""
        with contextlib.suppress(Exception):
            if said := await self._secret_branch_gone(ctx, copy):
                self._koloni_line(ctx.cid, ctx.run_id, said)

    async def _branch_look(self: "AgentRunner", copy: copies.Copy) -> dict:
        """`git.branch_look` of a branch copy, with its name - and where git did not say,
        nothing to merge yet and why (`note`). W-1: measured from the snapshot it began from."""
        try:
            found = await asyncio.to_thread(
                git.branch_look, copy.project, copy.branch or "", copy.start, copy.snapshot_sha
            )
        except git.Refused as exc:
            return {
                "name": copy.branch,
                "into": None,
                "files": {},
                "conflicts": [],
                "dirty": [],
                "special": [],
                "drift": None,
                "half": None,
                "tip": None,
                "share": None,
                "yours": [],
                "since": None,
                "over": [],
                "note": str(exc),
            }
        return {"name": copy.branch, **found, "note": None}
