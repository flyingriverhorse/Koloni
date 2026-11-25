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


@router.get("/{project_id}/decisions", response_model=DecisionLog)
async def read(
    project_id: str,
    since: datetime | None = None,
    until: datetime | None = None,
    session: Session = Depends(get_session),
):
    """What was decided for the user in the project from `since` until `until` (each where
    given), newest first, and how many commands the judge found fine meanwhile."""
    if session.get(Project, project_id) is None:
        raise HTTPException(404, "project not found")
    return decisions.of(session, project_id, since, until)
