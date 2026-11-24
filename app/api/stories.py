"""To-do's goals and stories (0.1.8, To-do in a chat), for the user: read them, add, change and
delete them. Every change here is the user's own, from the app's own page
(`require_own_origin`): an agent's command against the app's address writes none. Reading is
open. A link never crosses projects; deleting a goal or a story keeps what was under it."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import update
from sqlalchemy.orm import Session

from app import stories
from app.agent import announce
from app.api.deps import get_session, require_own_origin
from app.db.models import BacklogTask, Goal, Project, Story, now
from app.schemas import GoalIn, GoalOut, GoalPatch, StoryIn, StoryOut, StoryPatch, TodoTreeOut

router = APIRouter(prefix="/api", tags=["backlog"])
OWN = [Depends(require_own_origin)]
OTHER_GOAL = "a story's goal is one of its project"


def _project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    return project


def _goal(session: Session, goal_id: str) -> Goal:
    goal = session.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(404, "goal not found")
    return goal


def _story(session: Session, story_id: str) -> Story:
    story = session.get(Story, story_id)
    if story is None:
        raise HTTPException(404, "story not found")
    return story


def _told(request: Request, project_id: str) -> None:
    announce(
        request.app.state.session_factory, request.app.state.bus, project_id, "backlog.changed"
    )


def _title(title: str) -> str:
    if not (title := title.strip()):
        raise HTTPException(422, "a title is needed")
    return title


def _story_out(session: Session, story: Story) -> dict:
    return stories.story_row(story, stories.tasks_of(session, story.id))


@router.get("/projects/{project_id}/stories", response_model=TodoTreeOut)
async def read_tree(project_id: str, session: Session = Depends(get_session)):
    return stories.tree(session, _project(session, project_id).id)


@router.post(
    "/projects/{project_id}/goals", response_model=GoalOut, status_code=201, dependencies=OWN
)
async def add_goal(
    project_id: str, body: GoalIn, request: Request, session: Session = Depends(get_session)
):
    goal = stories.add_goal(session, _project(session, project_id).id, _title(body.title), "user")
    session.commit()
    _told(request, project_id)
    return stories.goal_row(goal, [])


@router.patch("/goals/{goal_id}", response_model=GoalOut, dependencies=OWN)
async def change_goal(
    goal_id: str, body: GoalPatch, request: Request, session: Session = Depends(get_session)
):
    goal = _goal(session, goal_id)
    if body.title is not None:
        goal.title = _title(body.title)
    if body.position is not None:
        stories.renumber(session, Goal, goal.project_id, goal, body.position)
    session.commit()
    _told(request, goal.project_id)
    return stories.goal_row(goal, stories.goal_states(session, goal))


@router.delete("/goals/{goal_id}", status_code=204, dependencies=OWN)
async def delete_goal(goal_id: str, request: Request, session: Session = Depends(get_session)):
    goal = _goal(session, goal_id)
    session.execute(update(Story).where(Story.goal_id == goal.id).values(goal_id=None))
    session.delete(goal)
    session.flush()
    stories.renumber(session, Goal, goal.project_id)
    session.commit()
    _told(request, goal.project_id)
    return Response(status_code=204)


@router.post(
    "/projects/{project_id}/stories", response_model=StoryOut, status_code=201, dependencies=OWN
)
async def add_story(
    project_id: str, body: StoryIn, request: Request, session: Session = Depends(get_session)
):
    project = _project(session, project_id)
    if body.goal_id is not None and not stories.of_project(session, Goal, project.id, body.goal_id):
        raise HTTPException(422, OTHER_GOAL)
    story = stories.add_story(session, project.id, _title(body.title), body.goal_id, "user")
    session.commit()
    _told(request, project_id)
    return _story_out(session, story)


@router.patch("/stories/{story_id}", response_model=StoryOut, dependencies=OWN)
async def change_story(
    story_id: str, body: StoryPatch, request: Request, session: Session = Depends(get_session)
):
    story = _story(session, story_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("title") is not None:
        story.title = _title(changes["title"])
    if "goal_id" in changes:  # (null takes it out of its goal)
        goal_id = changes["goal_id"]
        if goal_id is not None and not stories.of_project(session, Goal, story.project_id, goal_id):
            raise HTTPException(422, OTHER_GOAL)
        story.goal_id = goal_id
    if changes.get("closed") is not None:
        story.closed_at = now() if changes["closed"] else None
    if changes.get("position") is not None:
        stories.renumber(session, Story, story.project_id, story, changes["position"])
    session.commit()
    _told(request, story.project_id)
    return _story_out(session, story)


@router.delete("/stories/{story_id}", status_code=204, dependencies=OWN)
async def delete_story(story_id: str, request: Request, session: Session = Depends(get_session)):
    story = _story(session, story_id)
    session.execute(
        update(BacklogTask).where(BacklogTask.story_id == story.id).values(story_id=None)
    )
    session.delete(story)
    session.flush()
    stories.renumber(session, Story, story.project_id)
    session.commit()
    _told(request, story.project_id)
    return Response(status_code=204)
