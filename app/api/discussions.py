from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import get_session, require_origin, require_own_origin
from app.db.models import Discussion
from app.schemas import DiscussionOut, DiscussionPostIn, DiscussionPostOut
from app.serialize import discussion_out

router = APIRouter(prefix="/api", tags=["discussions"], dependencies=[Depends(require_origin)])

OVER = "this discussion is over"


@router.post(
    "/discussions/{discussion_id}/posts", response_model=DiscussionPostOut, status_code=201,
    dependencies=[Depends(require_own_origin)],
)
async def say(
    discussion_id: str, body: DiscussionPostIn, request: Request,
    session: Session = Depends(get_session),
):
    """The user speaks in the shared place; whoever speaks next reads it."""
    if session.get(Discussion, discussion_id) is None:
        raise HTTPException(404, "discussion not found")
    text = body.content.strip()
    if not text:
        raise HTTPException(422, "there is nothing to say")
    post = request.app.state.runner.say_in_discussion(discussion_id, text)
    if post is None:
        raise HTTPException(409, OVER)
    return post


@router.post("/discussions/{discussion_id}/end", response_model=DiscussionOut)
async def end(discussion_id: str, request: Request, session: Session = Depends(get_session)):
    """End the discussion now; the agent that opened it gets what was said so far."""
    discussion = session.get(Discussion, discussion_id)
    if discussion is None:
        raise HTTPException(404, "discussion not found")
    if not request.app.state.runner.end_discussion(discussion_id):
        raise HTTPException(409, OVER)
    return discussion_out(session, discussion)
