import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import get_session, require_origin, require_own_origin
from app.changes import ChangeConflict, revert_change
from app.db.models import Conversation, FileChange, Project, Run
from app.schemas import FileChangeDiffOut, FileChangeOut
from app.serialize import file_change_out
from app.workspace import WorkspaceError, for_change, unified_diff

router = APIRouter(
    prefix="/api/file-changes", tags=["file changes"], dependencies=[Depends(require_origin)]
)

DECISION_TIMEOUT = 5.0
# The most of a file, before and after together, that is sent whole to be read in the window.
WHOLE_BYTES = 200_000


def _change(session: Session, change_id: str) -> FileChange:
    change = session.get(FileChange, change_id)
    if change is None:
        raise HTTPException(404, "file change not found")
    return change


async def _decide(change_id: str, decision: str, request: Request, session: Session) -> dict:
    change = _change(session, change_id)
    if not request.app.state.runner.decide(change_id, decision):
        raise HTTPException(409, "this change is no longer waiting for a decision")
    # The agent task applies the decision; answer once it has.
    deadline = asyncio.get_running_loop().time() + DECISION_TIMEOUT
    while True:
        await asyncio.sleep(0.01)
        session.refresh(change)
        if change.status != "proposed" or asyncio.get_running_loop().time() > deadline:
            return file_change_out(change)


@router.get("/{change_id}/diff", response_model=FileChangeDiffOut)
def whole_diff(change_id: str, session: Session = Depends(get_session)):
    """The change's diff with all of the file around it, for the Changes window to open what
    it folded - asked for, one change at a time; events and the snapshot carry three lines
    around each change. Too large a file is refused, and its folds stay folded."""
    change = _change(session, change_id)
    before, after = change.before_content or "", change.after_content or ""
    if len(before.encode()) + len(after.encode()) > WHOLE_BYTES:
        raise HTTPException(413, "the file is too large to show whole")
    lines = max(len(before.splitlines()), len(after.splitlines()))
    return {"diff": unified_diff(before, after, change.path, context=lines)[0]}


@router.post("/{change_id}/approve", response_model=FileChangeOut,
             dependencies=[Depends(require_own_origin)])
async def approve(change_id: str, request: Request, session: Session = Depends(get_session)):
    return await _decide(change_id, "approve", request, session)


@router.post("/{change_id}/reject", response_model=FileChangeOut,
             dependencies=[Depends(require_own_origin)])
async def reject(change_id: str, request: Request, session: Session = Depends(get_session)):
    return await _decide(change_id, "reject", request, session)


def held_by_another(request: Request, root: str, change: FileChange) -> str | None:
    """Why the change cannot be reverted now: an agent other than its own is changing the
    file. A revert cannot wait for it, so it is refused until that one is done. The agent
    whose change this is may hold the file itself; that was never in the way."""
    holder = request.app.state.runner.holds(root, change.path)
    if holder is not None and holder[0] != change.agent_id:
        return f"{holder[1]} is changing {change.path} now; revert this change when it has finished"
    return None


async def revert_one(request: Request, session: Session, change: FileChange) -> dict:
    """Revert one applied change, or raise 409 with why not; the one revert there is (the
    Revert button's, and each of an undone turn's)."""
    run = session.get_one(Run, change.run_id)
    conversation = session.get_one(Conversation, run.conversation_id)
    project = session.get_one(Project, conversation.project_id)
    if why := held_by_another(request, project.root_path, change):
        raise HTTPException(409, why)
    try:
        revert_change(session, for_change(project.root_path, change.path), change)
    except (ValueError, ChangeConflict, WorkspaceError) as exc:
        raise HTTPException(409, str(exc)) from None
    # Not the doing of a CLI that is at work in a copy of the project and watched there.
    await request.app.state.runner.seen_in_project(project.root_path, {change.path})
    payload = file_change_out(change)
    request.app.state.bus.emit(conversation.id, run.id, "file_change.updated", payload)
    return payload


@router.post("/{change_id}/revert", response_model=FileChangeOut,
             dependencies=[Depends(require_own_origin)])
async def revert(change_id: str, request: Request, session: Session = Depends(get_session)):
    return await revert_one(request, session, _change(session, change_id))
