"""A project's backlog, for the user (slice 52): read it, write and order its tasks, decide
on what agents proposed, and give tasks to a chat's queue (0.1.8). Every change here is the
user's own, from
the app's own page (`require_own_origin`): an agent's command against the app's address
neither writes a task nor approves its own proposal. Reading is open."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app import backlog, earlier, stories, topics
from app.agent import announce
from app.api.deps import get_session, require_own_origin
from app.api.recipes import Asked, ask_in_turn, askers, chat_of
from app.api.usage import over_budget, over_month
from app.db.models import BacklogTask, Conversation, Project, Story, new_chat, now
from app.schemas import (
    BacklogDoIn,
    BacklogDoOut,
    BacklogDrafter,
    BacklogDraftIn,
    BacklogDraftOut,
    BacklogTaskIn,
    BacklogTaskOut,
    BacklogTaskPatch,
    TodoTreeAdded,
    TodoTreeIn,
)
from app.schemas_decisions import TaskDecideIn
from app.serialize import conversation_out

router = APIRouter(prefix="/api", tags=["backlog"])
OWN = [Depends(require_own_origin)]


def _project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    return project


def _task(session: Session, task_id: str) -> BacklogTask:
    task = session.get(BacklogTask, task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    return task


OTHER_STORY = "a task's story is one of its project"


def _in_story(session: Session, project_id: str, story_id: str | None) -> None:
    """A task's story is one of its project's (None: of no story); else 422."""
    if story_id is not None and not stories.of_project(session, Story, project_id, story_id):
        raise HTTPException(422, OTHER_STORY)


def _told(request: Request, session: Session, project_id: str) -> None:
    """After the user's change, committed: a chat's queue may go on now (`backlog.go_on`, which
    never raises - a task it waited for is done); whoever is watching is told the backlog
    changed - once, after that."""
    state = request.app.state
    backlog.go_on(session, project_id, state.bus, state.runner.start)
    announce(
        request.app.state.session_factory, request.app.state.bus, project_id, "backlog.changed"
    )


def _drafter(
    session: Session, request: Request, project: Project, conversation_id: str | None = None
) -> list[Asked] | str:
    """Whom "Write it with the Hive keeper" asks, in turn: each fast model the Lead may pick,
    as the Scout's view is written (`AgentRunner._assess`), then the Lead's
    (`askers`, as "Or write it" asks) - or why nobody is asked now. The page shows the first,
    the one the request asks first."""
    if over := over_month(session, project):
        return f"This project is {over}."
    return askers(
        session,
        request.app.state.providers,
        "fast",
        chat_of(session, conversation_id, project.id),
        project.id,
    )


@router.get("/projects/{project_id}/backlog/drafter", response_model=BacklogDrafter)
async def read_drafter(
    project_id: str,
    request: Request,
    conversation_id: str | None = None,
    session: Session = Depends(get_session),
):
    """Who "Write it with the Hive keeper" asks first - its provider and model (None: its
    default) - or why nobody is asked now."""
    found = _drafter(session, request, _project(session, project_id), conversation_id)
    if isinstance(found, str):
        return {"why": found}
    provider, model_id = found[0][:2]
    return {"why": None, "provider_id": provider.id, "model_id": model_id}


@router.delete("/backlog/{task_id}/queue", status_code=204, dependencies=OWN)
async def unqueue(task_id: str, request: Request, session: Session = Depends(get_session)):
    """Out of its chat's queue, back on To-do (the queue's Remove); 409 where it waits in none."""
    task = _task(session, task_id)
    if task.place is None:
        raise HTTPException(409, "this task waits in no chat's queue")
    backlog.unqueue(session, task)
    session.commit()
    _told(request, session, task.project_id)
    return Response(status_code=204)


@router.post("/backlog/{task_id}/fix", response_model=BacklogTaskOut, dependencies=OWN)
async def fix_it(task_id: str, request: Request, session: Session = Depends(get_session)):
    """Fix it, on a stuck task's card: one more fix round in its chat, in its topic, on why it
    is stuck - a turn the user pays for, by their click (`backlog.fix_again`). 409 with why
    where it is not stuck in a chat."""
    task = _task(session, task_id)
    try:
        backlog.fix_again(session, task)
    except backlog.Refused as exc:
        raise HTTPException(409, str(exc)) from None
    session.commit()
    _told(request, session, task.project_id)
    session.refresh(task)
    return task


@router.post(
    "/projects/{project_id}/backlog/draft", response_model=BacklogDraftOut, dependencies=OWN
)  # a request the user pays for: their click
async def draft_tasks(
    project_id: str, body: BacklogDraftIn, request: Request, session: Session = Depends(get_session)
):
    """The user's rough note written as tasks by a model asked once, with no tools, as the
    Hive keeper breaks a goal (`backlog.DRAFT`): nothing is saved - the page shows them, and
    each is added by the user's word. What it spends is on Usage as KOLONİ itself, in this
    project."""
    project = _project(session, project_id)
    can = _drafter(session, request, project, body.conversation_id)
    if isinstance(can, str):
        raise HTTPException(409, can)
    provider, said, model_id = await ask_in_turn(
        request,
        session,
        can,
        [
            {"role": "system", "content": backlog.DRAFT},
            {"role": "user", "content": backlog.draft_question(body.text)},
        ],
        project_id=project.id,
    )
    try:
        drawn = backlog.drafted(said)
    except ValueError as exc:
        raise HTTPException(502, f"the model's answer is not a list of tasks: {exc}") from None
    return BacklogDraftOut.model_validate({**drawn, "by": f"{provider.name} ({model_id})"})


@router.post(
    "/projects/{project_id}/backlog/tree",
    response_model=TodoTreeAdded,
    status_code=201,
    dependencies=OWN,
)
async def add_tree(
    project_id: str, body: TodoTreeIn, request: Request, session: Session = Depends(get_session)
):
    """The Hive keeper's draft - a goal, its stories and their tasks, as the user changed it -
    added at once by the user's word: the tasks todo, each the user's (`backlog.add_tree`)."""
    project = _project(session, project_id)
    try:
        added = backlog.add_tree(session, project.id, body.model_dump(), "user")
    except backlog.Refused as exc:
        raise HTTPException(422, str(exc)) from None
    session.commit()
    _told(request, session, project_id)
    return added


@router.post(
    "/projects/{project_id}/backlog/do-in-chat", response_model=BacklogDoOut, dependencies=OWN
)  # (turns the user pays for start from here: their click on the app's own page)
async def do_in_chat(
    project_id: str, body: BacklogDoIn, request: Request, session: Session = Depends(get_session)
):
    """Do in chat: the ticked tasks wait in a chat's queue - this one, or a new chat of the
    project named by the first of them - and run there one by one, each story in a topic of its
    own (`backlog.queue_in_chat`, `backlog.go_on`). Checked here as they stand now, not as the
    page saw them: all of them or none (422 with why); an unknown chat is 404. Not over the
    month's budget (409), as a message is not."""
    project = _project(session, project_id)
    ids = list(dict.fromkeys(body.task_ids))
    tasks = [session.get(BacklogTask, task_id) for task_id in ids]
    if any(task is None for task in tasks):
        raise HTTPException(422, "a task you ticked is not on the To-do list any more")
    found = [task for task in tasks if task is not None]
    if over := over_budget(session, project):
        raise HTTPException(409, f"this project is {over}")
    if body.conversation_id is not None:
        chat = session.get(Conversation, body.conversation_id)
        if chat is None:
            raise HTTPException(404, "conversation not found")
        if chat.project_id != project.id:
            raise HTTPException(422, "the chat is not one of this folder")
    else:
        chat = new_chat(session, project)
        session.flush()
    try:
        backlog.queue_in_chat(session, chat, found)
    except backlog.Refused as exc:
        session.rollback()
        raise HTTPException(422, str(exc)) from None
    queued = backlog.chat_queue(session, chat.id)
    if body.conversation_id is None:
        first = queued[0]
        story = stories.story_of(session, first.story_id, project.id)
        # (Named by it whole, as a To-do chat was: K-backlog-sohbet.)
        chat.title = topics.one_line(story.title if story else first.title) or chat.title
    session.commit()
    request.app.state.bus.emit(chat.id, None, "conversation.updated", conversation_out(chat))
    _told(request, session, project_id)
    return {"conversation_id": chat.id, "queued": [task.id for task in queued if task.id in ids]}


@router.get("/projects/{project_id}/backlog", response_model=list[BacklogTaskOut])
async def read_backlog(project_id: str, session: Session = Depends(get_session)):
    tasks = backlog.ordered(session, _project(session, project_id).id)
    left, waits = backlog.not_in(session, tasks), backlog.waiting(session, tasks)
    told = stories.told(session, project_id)
    return [
        BacklogTaskOut.model_validate(task).model_copy(
            update={
                "not_in": task.id in left,
                "waiting": task.id in waits,
                **told.get(task.story_id or "", {}),
            }
        )
        for task in tasks
    ]


@router.post(
    "/projects/{project_id}/backlog",
    response_model=BacklogTaskOut,
    status_code=201,
    dependencies=OWN,
)
async def add_task(
    project_id: str, body: BacklogTaskIn, request: Request, session: Session = Depends(get_session)
):
    fields = body.model_dump()
    fields["title"] = fields["title"].strip()
    if not fields["title"]:
        raise HTTPException(422, "a task needs a title")
    project = _project(session, project_id)
    _in_story(session, project.id, fields["story_id"])
    task = backlog.add(session, project.id, fields, "user")
    session.commit()
    _told(request, session, project_id)
    return task


@router.patch("/backlog/{task_id}", response_model=BacklogTaskOut, dependencies=OWN)
async def change_task(
    task_id: str, body: BacklogTaskPatch, request: Request, session: Session = Depends(get_session)
):
    task = _task(session, task_id)
    changes = body.model_dump(exclude_unset=True)
    # Only detail, criteria and its story can be emptied; the rest left as null is left as it is.
    changes = {
        k: v for k, v in changes.items() if v is not None or k in ("detail", "criteria", "story_id")
    }
    left = task.story_id
    if "story_id" in changes:
        _in_story(session, task.project_id, changes["story_id"])
    if "title" in changes:
        changes["title"] = changes["title"].strip()
        if not changes["title"]:
            raise HTTPException(422, "a task needs a title")
    position = changes.pop("position", None)
    if (after := changes.pop("after", None)) is not None:
        try:
            backlog.wait_for(session, task, after)
        except backlog.Refused as exc:
            raise HTTPException(422, str(exc)) from None
    if changes.get("status", task.status) != task.status:
        backlog.set_flow(task, stuck=None)  # (the user's word on it now)
    for field, value in changes.items():
        setattr(task, field, value)
    if position is not None:
        backlog.renumber(session, task.project_id, task, position)
    if left != task.story_id:  # (an agent's story it was the last proposal of, now empty, goes)
        session.flush()
        backlog.tidy_story(session, left, task.project_id)
    # A done task is found by `recall` as the user's words of its closing (app.earlier).
    earlier.index_task(session, task, now())
    session.commit()
    _told(request, session, task.project_id)
    return task


@router.delete("/backlog/{task_id}", status_code=204, dependencies=OWN)
async def delete_task(task_id: str, request: Request, session: Session = Depends(get_session)):
    task = _task(session, task_id)
    earlier.unindex_task(session, task.id)
    proposal = task.status == "proposed"
    if task.status in ("proposed", "todo"):  # (never worked on: a proposal turned down)
        backlog.turned_down(session, task)
    session.delete(task)
    session.flush()
    backlog.renumber(session, task.project_id)
    if proposal:  # (the story an agent opened for it goes with its last proposal)
        backlog.tidy_story(session, task.story_id, task.project_id)
    session.commit()
    _told(request, session, task.project_id)
    return Response(status_code=204)


@router.post("/backlog/{task_id}/decide", response_model=BacklogTaskOut | None, dependencies=OWN)
async def decide(
    task_id: str, body: TaskDecideIn, request: Request, session: Session = Depends(get_session)
):
    """The user's word on a task an agent proposed, or on a change it proposed: the task as
    it is now, or null when a proposed task was turned down (it is gone). With `expect`, the
    decision log's Change: only on the Orchestrator's word as its row showed it (409 else)."""
    task = _task(session, task_id)
    project_id = task.project_id
    try:
        kept = backlog.decide(session, task, body.decision == "approve", body.expect)
    except backlog.Refused as exc:
        raise HTTPException(409, str(exc)) from None
    if kept is not None:  # (an approved change may have closed it)
        earlier.index_task(session, kept, now())
    session.commit()
    _told(request, session, project_id)
    return kept


@router.post("/backlog/{task_id}/seen", response_model=BacklogTaskOut, dependencies=OWN)
async def seen(task_id: str, request: Request, session: Session = Depends(get_session)):
    """The user's OK of the Lead's word on a proposal of the Scout's at Full auto: it
    leaves "Decided for you"."""
    task = _task(session, task_id)
    if not (task.po or {}).get("lead"):
        raise HTTPException(409, "the Orchestrator decided nothing on this task")
    task.po = {**(task.po or {}), "seen": True}  # (replaced whole: `BacklogTask.po`)
    session.commit()
    _told(request, session, task.project_id)
    return task
