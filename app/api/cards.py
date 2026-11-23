"""Cards measured (0.1.7): the command cards of a period on the Usage page, and the rules they
suggest - read only: a suggested rule is saved by the Memory page's routes alone
(`app.api.memory.add_suggested_rule`), as every change of the user's rules is."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import cards
from app import memory as kept
from app.api.deps import get_session
from app.db.models import Project
from app.schemas import CardsOut

router = APIRouter(prefix="/api", tags=["cards"])


@router.get("/cards", response_model=CardsOut)
def read_cards(
    project_id: str | None = None,
    since: datetime | None = None,
    session: Session = Depends(get_session),
):
    """The cards asked since `since` (all without it), in one project's chats or in all; for one
    project, the rules its approvals suggest too."""
    project = session.get(Project, project_id) if project_id else None
    if project_id and project is None:
        raise HTTPException(404, "project not found")
    try:  # (kept in UTC with no zone: one that names another is brought there)
        when = since.astimezone(UTC).replace(tzinfo=None) if since and since.tzinfo else since
    except OverflowError:
        raise HTTPException(422, "since is out of range") from None
    found = cards.stats(session, project_id, when)
    if project is not None:
        found["suggestions"] = cards.suggestions(
            session, project, kept.rules_in_effect(project) or ""
        )
    return found
