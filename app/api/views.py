"""The conversation's views (slice 39, `app.views`): the list, and the files a view's frame is
served. Plain functions: they read files, and run in the server's threads, off its loop."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app import views
from app.api.deps import get_session, keyed_if_read_by_the_app, require_origin
from app.db.models import Conversation, Project
from app.schemas import ViewOut

router = APIRouter(prefix="/api/conversations", tags=["views"])


def _root(session: Session, conversation_id: str) -> str:
    conversation = session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(404, "conversation not found")
    if conversation.project_id is None:  # (a plain chat has no file to show)
        raise HTTPException(404, "this chat has no folder")
    return session.get_one(Project, conversation.project_id).root_path


@router.get(
    "/{conversation_id}/views", response_model=list[ViewOut],
    dependencies=[Depends(require_origin)],
)
def list_views(conversation_id: str, request: Request, session: Session = Depends(get_session)):
    return views.list_views(session, conversation_id, _root(session, conversation_id),
                            request.app.state.runner.copy_workspace)


# No origin is asked for: the frame's own requests come from an origin of their own ("null").
@router.get("/{conversation_id}/views/{view_id}/{name:path}", include_in_schema=False)
def view_file(
    conversation_id: str, view_id: str, name: str, request: Request,
    session: Session = Depends(get_session),
):
    try:
        data, kind = views.serve(
            session, conversation_id, _root(session, conversation_id),
            request.app.state.settings.runtime_root, request.app.state.runner.copy_workspace,
            view_id, name, request.query_params.get("v"))
    except views.Refused as refused:
        raise HTTPException(refused.status, str(refused)) from None
    keyed_if_read_by_the_app(request, kind)
    return Response(data, media_type=kind, headers=views.headers_of(kind))
