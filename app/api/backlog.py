"""A project's backlog, for the user (slice 52): read it, write and order its tasks, decide
on what agents proposed, and start the next task. Every change here is the user's own, from
the app's own page (`require_own_origin`): an agent's command against the app's address
neither writes a task nor approves its own proposal. Reading is open."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app import backlog, earlier
from app.agent import announce
from app.api.deps import get_session, require_own_origin
from app.api.providers import _model
from app.api.recipes import ask_writer, asker
from app.api.usage import over_budget, over_month
from app.db.models import BacklogTask, Project, Provider, now
from app.providers import works_with_own_tools
from app.schemas import (
    BacklogAutoIn,
    BacklogAutoOut,
    BacklogChoiceIn,
    BacklogDecideIn,
    BacklogDraftIn,
    BacklogDraftOut,
    BacklogNextOut,
    BacklogTaskIn,
    BacklogTaskOut,
    BacklogTaskPatch,
)
from app.serialize import tell_chats

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


def _told(request: Request, session: Session, project_id: str) -> None:
    """After the user's change, committed: where the backlog works itself, the next task
    may start now (`backlog.chain`, which never raises); whoever is watching is told the
    backlog changed - once, after that."""
    backlog.chain(session, project_id, request.app.state.bus, request.app.state.runner.start)
    announce(request.app.state.session_factory, request.app.state.bus, project_id,
             "backlog.changed")


def _drafter(session: Session, request: Request,
             project: Project) -> tuple[Provider, str | None] | str:
    """Whom "Write it with the Product owner" asks: the first fast model the Lead may pick, as
    the Assistant product owner's view is written (`AgentRunner._assess`), else the Lead's -
    or why nobody is asked now. What the page shows and what the request does are this one
    answer."""
    if over := over_month(session, project):
        return f"This project is {over}."
    return asker(session, request.app.state.providers, "fast")


def _auto(session: Session, project: Project, request: Request) -> dict:
    can = _drafter(session, request, project)
    return {"on": project.backlog_auto, "halt": project.backlog_halt,
            "permission_mode": project.backlog_mode, "provider_id": project.backlog_provider_id,
            "model_id": project.backlog_model_id,
            "lead_work": project.backlog_lead_work or project.lead_work,
            "cannot_run": backlog.cannot_run(session, project),
            "drafter": {"why": can} if isinstance(can, str) else {
                "why": None, "provider_id": can[0].id, "model_id": can[1]}}


@router.get("/projects/{project_id}/backlog/auto", response_model=BacklogAutoOut)
async def read_auto(project_id: str, request: Request, session: Session = Depends(get_session)):
    return _auto(session, _project(session, project_id), request)


@router.post("/projects/{project_id}/backlog/draft", response_model=BacklogDraftOut,
             dependencies=OWN)  # a request the user pays for: their click
async def draft_tasks(project_id: str, body: BacklogDraftIn, request: Request,
                      session: Session = Depends(get_session)):
    """The user's rough note written as tasks by a model asked once, with no tools, as the
    Product owner breaks a goal (`backlog.DRAFT`): nothing is saved - the page shows them, and
    each is added by the user's word. What it spends is on Usage as KOLONİ itself, in this
    project."""
    project = _project(session, project_id)
    can = _drafter(session, request, project)
    if isinstance(can, str):
        raise HTTPException(409, can)
    provider, model = can
    said, model_id = await ask_writer(request, provider, model, [
        {"role": "system", "content": backlog.DRAFT},
        {"role": "user", "content": backlog.draft_question(body.text)},
    ], project_id=project.id)
    try:
        tasks = backlog.drafted(said)
    except ValueError as exc:
        raise HTTPException(502, f"the model's answer is not a list of tasks: {exc}") from None
    return BacklogDraftOut(tasks=tasks, by=f"{provider.name} ({model_id})")


@router.put("/projects/{project_id}/backlog/choice", response_model=BacklogAutoOut,
            dependencies=OWN)
async def set_choice(project_id: str, body: BacklogChoiceIn, request: Request,
                     session: Session = Depends(get_session)):
    """The level and the model the chats the backlog opens from now start with (B-350): the
    user's, from the app's own page, as raising a chat's level is. Their turns hold to a
    night's rules at any level (`AgentRunner._backlog_turns`), so a provider that cannot work
    under them - one with tools of its own, or with no model to run - is refused here rather
    than failing every task. (The default one is said on the page and checked as a run
    starts, `backlog.cannot_run`: the level is still to be set with none chosen.)"""
    project = _project(session, project_id)
    provider = session.get(Provider, body.provider_id) if body.provider_id else None
    if body.provider_id is not None and provider is None:
        raise HTTPException(422, "unknown provider")
    # (Another provider's model name means nothing without its provider.)
    model = _model(body.model_id) if provider else None
    if provider is not None and works_with_own_tools(provider):
        why = backlog.OWN_TOOLS.format(name=provider.name, fix="choose another provider")
        raise HTTPException(422, why)
    if provider is not None and provider.kind == "anthropic" and not (
            model or provider.default_model):
        raise HTTPException(422, f"{provider.name} has no default model: name one")
    project.backlog_mode = body.permission_mode
    project.backlog_provider_id, project.backlog_model_id = body.provider_id, model
    project.backlog_lead_work = body.lead_work
    session.commit()
    announce(request.app.state.session_factory, request.app.state.bus, project_id,
             "backlog.changed")
    if "lead_work" in body.model_fields_set:  # (its To-do chats follow it: `lead_work_of`)
        tell_chats(session, request.app.state.bus, project_id)
    return _auto(session, project, request)


@router.put("/projects/{project_id}/backlog/auto", response_model=BacklogAutoOut,
            dependencies=OWN)
async def set_auto(project_id: str, body: BacklogAutoIn, request: Request,
                   session: Session = Depends(get_session)):
    """The user's switch, Run the backlog by itself: todo tasks start by themselves as there
    is room (`backlog.chain`), now too. Why the run paused or stopped is cleared either way:
    it is the user's word now. Off stops the run: what Run the backlog queued is not started."""
    project = _project(session, project_id)
    if body.on and (why := backlog.cannot_run(session, project)):
        raise HTTPException(422, why)
    project.backlog_auto, project.backlog_halt = body.on, None
    if not body.on:
        for task in backlog.ordered(session, project_id):
            backlog.set_flow(task, queued=None)
    session.commit()
    _told(request, session, project_id)
    session.refresh(project)
    return _auto(session, project, request)


@router.get("/projects/{project_id}/backlog", response_model=list[BacklogTaskOut])
async def read_backlog(project_id: str, session: Session = Depends(get_session)):
    tasks = backlog.ordered(session, _project(session, project_id).id)
    left, waits = backlog.not_in(session, tasks), backlog.waiting(session, tasks)
    return [BacklogTaskOut.model_validate(task).model_copy(
        update={"not_in": task.id in left, "waiting": task.id in waits}) for task in tasks]


@router.post("/projects/{project_id}/backlog", response_model=BacklogTaskOut, status_code=201,
             dependencies=OWN)
async def add_task(project_id: str, body: BacklogTaskIn, request: Request,
                   session: Session = Depends(get_session)):
    fields = body.model_dump()
    fields["title"] = fields["title"].strip()
    if not fields["title"]:
        raise HTTPException(422, "a task needs a title")
    task = backlog.add(session, _project(session, project_id).id, fields, "user")
    session.commit()
    _told(request, session, project_id)
    return task


@router.patch("/backlog/{task_id}", response_model=BacklogTaskOut, dependencies=OWN)
async def change_task(task_id: str, body: BacklogTaskPatch, request: Request,
                      session: Session = Depends(get_session)):
    task = _task(session, task_id)
    changes = body.model_dump(exclude_unset=True)
    # Only detail and criteria can be emptied; the rest left as null is left as it is.
    changes = {k: v for k, v in changes.items() if v is not None or k in ("detail", "criteria")}
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
    # A done task is found by `recall` as the user's words of its closing (app.earlier).
    earlier.index_task(session, task, now())
    session.commit()
    _told(request, session, task.project_id)
    return task


@router.delete("/backlog/{task_id}", status_code=204, dependencies=OWN)
async def delete_task(task_id: str, request: Request, session: Session = Depends(get_session)):
    task = _task(session, task_id)
    earlier.unindex_task(session, task.id)
    if task.status in ("proposed", "todo"):  # (never worked on: a proposal turned down)
        backlog.turned_down(session, task)
    session.delete(task)
    session.flush()
    backlog.renumber(session, task.project_id)
    session.commit()
    _told(request, session, task.project_id)
    return Response(status_code=204)


@router.post("/backlog/{task_id}/decide", response_model=BacklogTaskOut | None, dependencies=OWN)
async def decide(task_id: str, body: BacklogDecideIn, request: Request,
                 session: Session = Depends(get_session)):
    """The user's word on a task an agent proposed, or on a change it proposed: the task as
    it is now, or null when a proposed task was turned down (it is gone)."""
    task = _task(session, task_id)
    project_id = task.project_id
    try:
        kept = backlog.decide(session, task, body.decision == "approve")
    except backlog.Refused as exc:
        raise HTTPException(409, str(exc)) from None
    if kept is not None:  # (an approved change may have closed it)
        earlier.index_task(session, kept, now())
    session.commit()
    _told(request, session, project_id)
    return kept


@router.post("/backlog/{task_id}/seen", response_model=BacklogTaskOut, dependencies=OWN)
async def seen(task_id: str, request: Request, session: Session = Depends(get_session)):
    """The user's OK of the Lead's word on a proposal of the Assistant PO's at Full auto: it
    leaves "Decided for you"."""
    task = _task(session, task_id)
    if not (task.po or {}).get("lead"):
        raise HTTPException(409, "the Orchestrator decided nothing on this task")
    task.po = {**(task.po or {}), "seen": True}  # (replaced whole: `BacklogTask.po`)
    session.commit()
    _told(request, session, task.project_id)
    return task


@router.post("/projects/{project_id}/backlog/next", response_model=BacklogNextOut,
             dependencies=OWN)
async def run_the_backlog(project_id: str, request: Request,
                          session: Session = Depends(get_session)):
    """Run the backlog (K-symphony): every todo task is queued, and they start as there is
    room - MAX_PARALLEL at once, each once the tasks it waits for are done (`backlog.chain`) -
    each in a new conversation (`backlog.start`). Not while everything is held or the
    project works while the user is away, nor over the month's budget, as a message is not.
    A pause or a stop of the run is cleared: it is the user's word now.
    shortcut: no trigger runs the backlog every morning (the spec's 18a idea); the switch
    on the page runs it by itself instead. Add a trigger kind that calls this when asked."""
    project = _project(session, project_id)
    if backlog.held(session):
        raise HTTPException(409, "everything is held (Stop everything): Resume first")
    if backlog.away(session, project.id):
        raise HTTPException(409, "the project works while you're away")
    if why := backlog.cannot_run(session, project):
        raise HTTPException(422, why)
    todo = [task for task in backlog.ordered(session, project.id)
            if task.status == "todo" and task.away_run_id is None]
    # (One the Lead added at Full auto starts by the user's OK only: `backlog.unseen`.)
    ready = [task for task in todo if not backlog.unseen(task)]
    if not ready and todo:
        raise HTTPException(409, f"{len(todo)} tasks wait for your OK on the To-do page")
    if not ready:
        raise HTTPException(409, "no task of the backlog is todo")
    todo = ready
    if over := over_budget(session, project):
        raise HTTPException(409, f"this project is {over}")
    project.backlog_halt = None
    for task in todo:
        backlog.set_flow(task, queued=True)
    session.commit()
    _told(request, session, project_id)
    started = next((task for task in todo if task.status == "doing"), None)
    return {"task_id": started and started.id,
            "conversation_id": started and started.conversation_id}
