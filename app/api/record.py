"""The track record of the agents that ran (`app.record`): measured, by role and model."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import record as kept
from app.api.deps import get_session
from app.db.models import now
from app.schemas import RecordOut

router = APIRouter(prefix="/api", tags=["record"])


@router.get("/record", response_model=RecordOut)
def record(since: datetime | None = None, session: Session = Depends(get_session)):
    """The agents that ended from `since` on (the last 30 days without it), all projects."""
    try:
        since = since or now() - timedelta(days=kept.DAYS)
        return {"rows": kept.rows(session, since),
                "skills": kept.rows(session, since, by_skill=True)}
    except OverflowError:  # the first or last year there is, in a zone that leaves it
        raise HTTPException(422, "since is out of range") from None
