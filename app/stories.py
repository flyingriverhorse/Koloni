"""To-do's goals and stories (0.1.8, To-do in a chat): a goal holds stories, a story holds tasks
and bugs. A story's state comes from its tasks; it is done only by the user's word.

(Never imports `app.backlog`, which imports this.)"""

from collections.abc import Sequence

from sqlalchemy import case, func, literal_column, select
from sqlalchemy.orm import Session

from app import topics
from app.db.models import Agent, BacklogTask, Goal, Run, Story, Topic, now

PRIORITIES = ("high", "normal", "low")
# A story's notebook: each note at most NOTE_MOST characters, at most NOTEBOOK_MOST of them (the
# newest kept).
NOTE_MOST, NOTEBOOK_MOST = 200, 20
# What a story is: none of its tasks started; one at work or queued in a chat; one stuck; all of
# them done or waiting at "done?" for the user's word (the user is asked); closed by the user.
STORY_STATES = ("todo", "running", "stuck", "done?", "done")


def story_state(story: Story, tasks: Sequence[BacklogTask]) -> str:
    """Its state from its tasks, proposals left out: closed, at work, all done or at "done?" (the
    user's word waits), stuck, or to do."""
    if story.closed_at is not None:
        return "done"
    tasks = [task for task in tasks if task.status != "proposed"]
    if not tasks:
        return "todo"
    if any(task.status == "doing" or task.place for task in tasks):
        return "running"
    if all(task.status in ("done", "review") for task in tasks):
        return "done?"
    if any(task.status == "blocked" for task in tasks):
        return "stuck"
    return "todo"


def goal_progress(states: Sequence[str]) -> tuple[int, int]:
    """How many of a goal's stories are done (closed by the user), of how many."""
    return sum(state == "done" for state in states), len(states)


def tasks_of(session: Session, story_id: str) -> list[BacklogTask]:
    """A story's tasks as the To-do list orders them: by priority, then by their place."""
    rank = case({p: i for i, p in enumerate(PRIORITIES)}, value=BacklogTask.priority)
    return list(
        session.scalars(
            select(BacklogTask)
            .where(BacklogTask.story_id == story_id)
            .order_by(rank, BacklogTask.position)
        )
    )


def _next_position(session: Session, model: type[Goal] | type[Story], project_id: str) -> int:
    last = session.scalar(select(func.max(model.position)).where(model.project_id == project_id))
    return 0 if last is None else last + 1


def add_goal(session: Session, project_id: str, title: str, created_by: str) -> Goal:
    goal = Goal(
        project_id=project_id,
        title=title,
        position=_next_position(session, Goal, project_id),
        created_by=created_by,
    )
    session.add(goal)
    session.flush()
    return goal


def add_story(
    session: Session, project_id: str, title: str, goal_id: str | None, created_by: str
) -> Story:
    story = Story(
        project_id=project_id,
        goal_id=goal_id,
        title=title,
        position=_next_position(session, Story, project_id),
        notes=[],
        created_by=created_by,
    )
    session.add(story)
    session.flush()
    return story


def of_project(session: Session, model: type[Goal] | type[Story], project_id: str, id: str) -> bool:
    """Whether `id` is a goal (or a story) of this project: a link never crosses projects."""
    found = session.get(model, id)
    return found is not None and found.project_id == project_id


def shown(story: Story, tasks: Sequence[BacklogTask]) -> bool:
    """Whether To-do shows it: not one an agent opened that holds only its proposals yet."""
    return story.created_by != "agent" or any(task.status != "proposed" for task in tasks)


def renumber(session: Session, model: type[Goal] | type[Story], project_id: str, moved=None, to=0):
    """The project's goals (or stories) numbered 0, 1, ... in their order - `moved` put before
    the one that has the place `to` now (after them all if none has)."""
    others = [
        one
        for one in session.scalars(
            select(model).where(model.project_id == project_id).order_by(model.position)
        )
        if one is not moved
    ]
    if moved is not None:
        at = next((i for i, one in enumerate(others) if one.position >= to), len(others))
        others.insert(at, moved)
    for i, one in enumerate(others):
        one.position = i


STORY_FIELDS = ("id", "goal_id", "title", "position", "notes", "created_by", "closed_at")


def story_row(story: Story, tasks: Sequence[BacklogTask]) -> dict:
    """A story as `StoryOut`: with its state from these tasks of it."""
    return {
        **{key: getattr(story, key) for key in STORY_FIELDS},
        "state": story_state(story, tasks),
    }


def goal_row(goal: Goal, states: Sequence[str]) -> dict:
    """A goal as `GoalOut`: with the count of its shown stories (`states`) and of those done."""
    done, all_ = goal_progress(states)
    return {
        **{key: getattr(goal, key) for key in ("id", "title", "position", "created_by")},
        "stories_done": done,
        "stories_all": all_,
    }


def tree(session: Session, project_id: str) -> dict:
    """The project's goals and stories in their order, as `TodoTreeOut`: its shown stories
    (`shown`), and the goals of the user's or over a shown story."""
    by_story: dict[str, list[BacklogTask]] = {}
    for task in session.scalars(
        select(BacklogTask).where(
            BacklogTask.project_id == project_id, BacklogTask.story_id.is_not(None)
        )
    ):
        by_story.setdefault(task.story_id or "", []).append(task)
    stories = [
        story_row(story, by_story.get(story.id, []))
        for story in session.scalars(
            select(Story).where(Story.project_id == project_id).order_by(Story.position)
        )
        if shown(story, by_story.get(story.id, []))
    ]
    goals = [
        goal_row(goal, states)
        for goal in session.scalars(
            select(Goal).where(Goal.project_id == project_id).order_by(Goal.position)
        )
        # (nor a goal an agent opened over such stories alone)
        if (states := [one["state"] for one in stories if one["goal_id"] == goal.id])
        or goal.created_by != "agent"
    ]
    return {"goals": goals, "stories": stories}


def told(session: Session, project_id: str) -> dict[str, dict]:
    """By story id, what a task's row says of its story (`BacklogTaskOut`): its title and goal's,
    and who opened each - "agent" for one an agent's proposal would make, the user's not yet."""
    goals = {
        goal.id: goal for goal in session.scalars(select(Goal).where(Goal.project_id == project_id))
    }
    out: dict[str, dict] = {}
    for story in session.scalars(select(Story).where(Story.project_id == project_id)):
        goal = goals.get(story.goal_id or "")
        out[story.id] = {
            "story_title": story.title,
            "story_by": story.created_by,
            "goal_title": goal.title if goal else None,
            "goal_by": goal.created_by if goal else None,
        }
    return out


def goal_states(session: Session, goal: Goal) -> list[str]:
    """The states of a goal's shown stories."""
    return [
        story_state(story, tasks)
        for story in session.scalars(select(Story).where(Story.goal_id == goal.id))
        if shown(story, tasks := tasks_of(session, story.id))
    ]


def story_named(session: Session, project_id: str, title: str) -> Story | None:
    """The project's open story of this title, whatever its case; None if it has none."""
    folded = title.strip().casefold()
    return next(
        (
            story
            for story in session.scalars(
                select(Story)
                .where(Story.project_id == project_id, Story.closed_at.is_(None))
                .order_by(Story.position)
            )
            if story.title.casefold() == folded
        ),
        None,
    )


def goal_named(session: Session, project_id: str, title: str) -> Goal | None:
    """The project's goal of this title, whatever its case; None if it has none."""
    folded = title.strip().casefold()
    return next(
        (
            goal
            for goal in session.scalars(select(Goal).where(Goal.project_id == project_id))
            if goal.title.casefold() == folded
        ),
        None,
    )


def adopt(session: Session, story_id: str | None) -> None:
    """A proposal's story added by the user's word: it, and its goal where an agent opened it,
    are the user's from then on - kept though its tasks go, as one the user made."""
    story = session.get(Story, story_id) if story_id else None
    if story is None:
        return
    story.created_by = "user"
    goal = session.get(Goal, story.goal_id) if story.goal_id else None
    if goal is not None:
        goal.created_by = "user"


def drop_if_empty(session: Session, story: Story) -> None:
    """A story an agent opened goes once none of its tasks is left (its proposals turned down),
    and its goal, where an agent's, once no story is left under it. The user's stay."""
    if story.created_by != "agent" or session.scalar(
        select(BacklogTask.id).where(BacklogTask.story_id == story.id).limit(1)
    ):
        return
    goal = session.get(Goal, story.goal_id) if story.goal_id else None
    session.delete(story)
    session.flush()
    renumber(session, Story, story.project_id)
    if (
        goal is not None
        and goal.created_by == "agent"
        and session.scalar(select(Story.id).where(Story.goal_id == goal.id).limit(1)) is None
    ):
        session.delete(goal)
        session.flush()
        renumber(session, Goal, goal.project_id)


def add_notes(story: Story, texts: Sequence[str], by: str, kind: str = "decision") -> None:
    """Notes put in a story's notebook, each cut to NOTE_MOST, the newest NOTEBOOK_MOST kept.
    shortcut: not masked nor read for orders yet (the plan's Task 10 does); only the Hive
    keeper's draft, added by the user's word, writes here until then."""
    at = now().isoformat()
    added = [{"kind": kind, "text": text[:NOTE_MOST], "by": by, "at": at} for text in texts]
    story.notes = [*(story.notes or []), *added][-NOTEBOOK_MOST:]  # (replaced whole)


def _story_runs(story_id: str):
    return (
        select(Run.id)
        .join(BacklogTask, BacklogTask.id == Run.task_id)
        .where(BacklogTask.story_id == story_id)
    )


def branch_lead(session: Session, story_id: str) -> str | None:
    """The Orchestrator of the story's latest turn that left its work on a git branch (its
    record's `on_branch`, or `left_on` where it could not open it again): the one the story's
    next turn goes on from (`AgentRunner._branch_again`). None: the story has no branch yet."""
    for agent_id, copy in session.execute(
        select(Agent.id, Agent.copy)
        .where(Agent.run_id.in_(_story_runs(story_id)), Agent.depth == 0)
        .order_by(Agent.created_at.desc(), literal_column("agents.rowid").desc())
    ):
        if (copy or {}).get("on_branch") or (copy or {}).get("left_on"):
            return agent_id
    return None


def last_task(session: Session, story_id: str) -> BacklogTask | None:
    """The story's task whose turn ran last."""
    return session.scalar(
        select(BacklogTask)
        .join(Run, Run.task_id == BacklogTask.id)
        .where(BacklogTask.story_id == story_id)
        .order_by(Run.created_at.desc(), literal_column("runs.rowid").desc())
        .limit(1)
    )


def _last_topic(session: Session, cid: str, *where) -> Topic | None:
    """The topic of the chat's newest turn that matches `where`."""
    return session.scalar(
        select(Topic)
        .join(Run, Run.topic_id == Topic.id)
        .where(Run.conversation_id == cid, Topic.conversation_id == cid, *where)
        .order_by(Run.created_at.desc(), literal_column("runs.rowid").desc())
        .limit(1)
    )


def topic_for(session: Session, cid: str, task: BacklogTask) -> tuple[Topic, bool]:
    """The topic a To-do task's turn goes on in, in this chat, and whether it was made now
    (added, not committed): the task's own where it had a turn here (its fix round, a task
    put back and queued again); else its story's newest topic here - a story's tasks go on
    in one session (`topics.previous_lead`) - unless the story's task that last ran there ended
    badly (stuck: the next does not carry its wrong guess on, the spec's rule 6), when the story
    gets a topic anew; else, for a story with none here or a task of no story, a new one. A story
    deleted since counts as none."""
    own = _last_topic(session, cid, Run.task_id == task.id)
    if own is not None:
        return own, False
    story = session.get(Story, task.story_id) if task.story_id else None
    if story is not None:
        found = session.scalar(
            select(Topic)
            .where(Topic.conversation_id == cid, Topic.story_id == story.id)
            .order_by(Topic.created_at.desc(), literal_column("topics.rowid").desc())
            .limit(1)
        )
        last = (
            session.scalar(
                select(BacklogTask)
                .join(Run, Run.task_id == BacklogTask.id)
                .where(Run.topic_id == found.id)
                .order_by(Run.created_at.desc(), literal_column("runs.rowid").desc())
                .limit(1)
            )
            if found is not None
            else None
        )
        if found is not None and (last is None or last.status != "blocked"):
            return found, False
    topic = Topic(
        conversation_id=cid,
        title=topics.title_of(story.title if story else task.title) or "Untitled",
        story_id=story.id if story else None,
    )
    session.add(topic)
    session.flush()
    return topic, True
