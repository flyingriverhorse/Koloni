"""The project's memory, for the user: read it, write a fact, decide on what agents put
forward, and set the standing rules. Every change here is the user's own - so every route
that changes something takes only a request that says it comes from the app's own page
(`require_own_origin`). Reading is open."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app import earlier, koloni
from app import memory as kept
from app.agent import announce_memory
from app.api.deps import get_session, require_own_origin
from app.db.models import Memory, Project
from app.schemas import (
    MemoryApproveIn,
    MemoryIn,
    MemoryOut,
    MemoryPatch,
    MemorySearchOut,
    PreferencesIn,
    PreferencesOut,
    ProjectMemoryOut,
    RulesIn,
    RulesOut,
)

router = APIRouter(prefix="/api", tags=["memory"])


def _project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    return project


def _record(session: Session, memory_id: str) -> tuple[Memory, Project]:
    record = session.get(Memory, memory_id)
    if record is None:
        raise HTTPException(404, "memory record not found")
    return record, session.get_one(Project, record.project_id)


def _done(request: Request, session: Session, project: Project, change) -> dict:
    """Make a change, tell the project's conversations, and return the record."""
    try:
        record = change()
    except kept.Refused as exc:
        raise HTTPException(exc.status, str(exc)) from None
    announce_memory(request.app.state.session_factory, request.app.state.bus, project.id)
    return kept.out(session, project.root_path, record)


@router.get("/projects/{project_id}/memory", response_model=ProjectMemoryOut)
async def read_memory(project_id: str, session: Session = Depends(get_session)):
    return kept.overview(session, _project(session, project_id))


@router.get("/projects/{project_id}/memory/search", response_model=MemorySearchOut)
def search_memory(project_id: str, q: str = "", session: Session = Depends(get_session)):
    """What an agent's `recall` would find for these words: the same searches, so the
    user sees what an agent would be shown. Words that say nothing find nothing. (Not
    async: a search by meaning asks a server, 22c.)"""
    project = _project(session, project_id)
    query = kept.one_line(q)[:kept.MAX_QUERY]
    also = kept.also(session, project, query)
    return {
        "memory": [{**kept.out(session, project.root_path, record,
                               also.linked.get(record.project_id)),
                    "by_meaning": record.id in also.by_meaning}
                   for record in kept.matching(session, project, query, also=also)],
        "turns": earlier.found(session, project.id, query, also),
        "meaning_off": also.off,
    }


@router.get("/projects/{project_id}/memory/export", response_class=Response, responses={
    200: {"content": {"text/markdown": {}}, "description": "The core, as MEMORY.md"}})
def export_memory(project_id: str, session: Session = Depends(get_session)):
    """The core as a Markdown file to read or keep. A copy: it is never read back."""
    return Response(
        kept.exported(session, _project(session, project_id)),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="MEMORY.md"'},
    )


@router.post(
    "/projects/{project_id}/memory", response_model=MemoryOut, status_code=201,
    dependencies=[Depends(require_own_origin)],
)
async def write_fact(
    project_id: str, body: MemoryIn, request: Request, session: Session = Depends(get_session)
):
    """The user writes a fact into the core, in the place of the one on the same subject.
    It may rest on lines of a project file, which are read here and now."""
    project = _project(session, project_id)

    def write():
        source = kept.user_source(project.root_path, body.file, body.start_line, body.end_line)
        return kept.keep_fact(session, project.id, body.text, body.about, source)

    return _done(request, session, project, write)


@router.put(
    "/projects/{project_id}/rules", response_model=RulesOut,
    dependencies=[Depends(require_own_origin)],
)
async def set_rules(
    project_id: str, body: RulesIn, request: Request, session: Session = Depends(get_session)
):
    """The user's standing rules for agents working in this project."""
    project = _project(session, project_id)
    try:
        # Into the folder's .koloni/rules.md too (slice 86c), where what is in effect changes.
        if (tidy := kept.check_rules(body.rules)) != kept.rules_in_effect(project):
            koloni.save_rules(project.root_path, tidy)
        kept.change_rules(project, body.rules)
    except (kept.Refused, koloni.Refused) as exc:
        raise HTTPException(exc.status, str(exc)) from None
    session.commit()
    announce_memory(request.app.state.session_factory, request.app.state.bus, project.id)
    return {"rules": kept.rules_in_effect(project)}


@router.get("/preferences", response_model=PreferencesOut)
async def read_preferences(session: Session = Depends(get_session)):
    """The user's own preferences (22b): one text, given to every agent in every project."""
    return {"text": kept.preferences(session)}


@router.put(
    "/preferences", response_model=PreferencesOut, dependencies=[Depends(require_own_origin)],
)
async def set_preferences(body: PreferencesIn, session: Session = Depends(get_session)):
    """Set them; an empty text clears them. shortcut: no project's page is told (they are
    nobody's project's), the page reads the memory again itself after the save."""
    try:
        text = kept.change_preferences(session, body.text)
    except kept.Refused as exc:
        raise HTTPException(exc.status, str(exc)) from None
    session.commit()
    return {"text": text}


@router.post(
    "/memory/{memory_id}/add-to-preferences", response_model=MemoryOut,
    dependencies=[Depends(require_own_origin)],
)
async def add_to_preferences(
    memory_id: str, request: Request, session: Session = Depends(get_session)
):
    """Add a line the summariser suggested to the preferences; "not now" is `reject`."""
    record, project = _record(session, memory_id)
    return _done(request, session, project, lambda: kept.add_preference(session, record))


@router.post(
    "/memory/{memory_id}/approve", response_model=MemoryOut,
    dependencies=[Depends(require_own_origin)],
)
async def approve(
    memory_id: str, request: Request, body: MemoryApproveIn | None = None,
    session: Session = Depends(get_session),
):
    """Let a waiting note into the core, as it is or with its words corrected."""
    record, project = _record(session, memory_id)
    text = body.text if body else None
    return _done(request, session, project,
                 lambda: kept.approve(session, project.root_path, record, text))


@router.post(
    "/memory/{memory_id}/reject", response_model=MemoryOut,
    dependencies=[Depends(require_own_origin)],
)
async def reject(memory_id: str, request: Request, session: Session = Depends(get_session)):
    """Say no to a waiting note, or take a record out of effect. It stays on record."""
    record, project = _record(session, memory_id)
    return _done(request, session, project, lambda: kept.reject(session, record))


@router.post(
    "/memory/{memory_id}/restore", response_model=MemoryOut,
    dependencies=[Depends(require_own_origin)],
)
async def restore(memory_id: str, request: Request, session: Session = Depends(get_session)):
    """Take back a record that was rejected or superseded."""
    record, project = _record(session, memory_id)
    return _done(request, session, project, lambda: kept.restore(session, record))


@router.post(
    "/memory/{memory_id}/confirm", response_model=MemoryOut,
    dependencies=[Depends(require_own_origin)],
)
async def confirm(memory_id: str, request: Request, session: Session = Depends(get_session)):
    """Say of a block that moved: these are the same lines. The record is pinned to
    where they stand now. Anything but a source that moved is a 409."""
    record, project = _record(session, memory_id)
    return _done(request, session, project,
                 lambda: kept.confirm(session, project.root_path, record))


@router.patch(
    "/memory/{memory_id}", response_model=MemoryOut,
    dependencies=[Depends(require_own_origin)],
)
async def correct(
    memory_id: str, body: MemoryPatch, request: Request,
    session: Session = Depends(get_session),
):
    """Correct a fact of the core: a new record in its place, the old one superseded."""
    record, project = _record(session, memory_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("text") is None:
        changes.pop("text", None)
    return _done(request, session, project,
                 lambda: kept.correct(session, project.root_path, record, changes))
