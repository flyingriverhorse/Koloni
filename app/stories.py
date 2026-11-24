"""To-do's goals and stories (0.1.8, To-do in a chat): a goal holds stories, a story holds tasks
and bugs. A story's state comes from its tasks; it is done only by the user's word.

(Never imports `app.backlog`, which imports this.)"""

from collections.abc import Sequence

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db.models import BacklogTask, Goal, Story

PRIORITIES = ("high", "normal", "low")
# What a story is: none of its tasks started; one at work or queued in a chat; one stuck; all of
# them done (the user is asked); closed by the user.
STORY_STATES = ("todo", "running", "stuck", "done?", "done")


def story_state(story: Story, tasks: Sequence[BacklogTask]) -> str:
    """Its state from its tasks, proposals left out: closed, at work, all done, stuck, or to do."""
    if story.closed_at is not None:
        return "done"
    tasks = [task for task in tasks if task.status != "proposed"]
    if not tasks:
        return "todo"
    if any(task.status == "doing" or task.place for task in tasks):
        return "running"
    if all(task.status == "done" for task in tasks):
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
    """The project's goals and stories in their order, as `TodoTreeOut`: its shown stories."""
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
        goal_row(goal, [one["state"] for one in stories if one["goal_id"] == goal.id])
        for goal in session.scalars(
            select(Goal).where(Goal.project_id == project_id).order_by(Goal.position)
        )
    ]
    return {"goals": goals, "stories": stories}


def goal_states(session: Session, goal: Goal) -> list[str]:
    """The states of a goal's shown stories."""
    return [
        story_state(story, tasks)
        for story in session.scalars(select(Story).where(Story.goal_id == goal.id))
        if shown(story, tasks := tasks_of(session, story.id))
    ]
