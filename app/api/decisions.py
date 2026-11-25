"""The decision log (karar defteri) of a project, for Today's Decisions: read only - there is no
way here, nor any tool of an agent's, to add, change or delete one of its rows."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import decisions
from app.api.deps import get_session
from app.db.models import Project
from app.schemas_decisions import DecisionLog

router = APIRouter(prefix="/api/projects", tags=["decisions"])


# (Not async: it reads the database for as long as a long night takes - in a worker thread, not on
# the event loop.)
@router.get("/{project_id}/decisions", response_model=DecisionLog)
def read(
    project_id: str,
    since: datetime | None = None,
    until: datetime | None = None,
    unseen: bool = False,
    session: Session = Depends(get_session),
):
    """What was decided for the user in the project from `since` until `until` (each where
    given), newest first, and how many commands the judge found fine meanwhile. `unseen`: only
    those that wait for your OK, of any age."""
    if session.get(Project, project_id) is None:
        raise HTTPException(404, "project not found")
    try:
        since, until = (None if at is None else decisions.utc(at) for at in (since, until))
    except OverflowError:
        raise HTTPException(422, "since and until must be times UTC can hold") from None
    return decisions.of(session, project_id, since, until, unseen)
