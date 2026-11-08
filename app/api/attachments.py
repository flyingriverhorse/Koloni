"""Files added to a chat message (slice 85b): sent one at a time as the request's body -
never as JSON, and never more than `attachments.MAX_BYTES` read - kept as the
conversation's, and served only with the page key, as every other `/api` address is."""

import asyncio
from pathlib import Path, PurePath
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import attachments, git, injection, project_files, web
from app.api.deps import get_session, require_origin, require_own_origin
from app.db.models import Attachment, Conversation, project_of
from app.schemas import AttachmentOut, AttachmentTextOut
from app.serialize import attachment_out
from app.views import HEADERS, Refused

router = APIRouter(prefix="/api", tags=["attachments"])


def _attachment(session: Session, attachment_id: str) -> Attachment:
    found = session.get(Attachment, attachment_id)
    if found is None:
        raise HTTPException(404, "attachment not found")
    return found


@router.post(
    "/conversations/{conversation_id}/attachments", response_model=AttachmentOut,
    status_code=201, dependencies=[Depends(require_origin)],  # as a message is sent
)
async def add_attachment(
    conversation_id: str, request: Request,
    name: str = Query(max_length=1000), frame_of: str | None = Query(None, max_length=32),
    size: int | None = Query(None, gt=attachments.MAX_BYTES, lt=2**63),
    session: Session = Depends(get_session),
):
    """One file for the conversation's next message, or a frame the page took of a video
    of it: kept, and said what it is - by its bytes, not its name. With `size`: a video
    larger than a file may be, by its first bytes - it goes as its frames alone."""
    shown = _room_for(session, conversation_id, name, frame_of)
    most = attachments.MAX_HEAD if size else attachments.MAX_BYTES
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > most:
            raise HTTPException(413, f"a video larger than {attachments.MAX_BYTES // 2**20} MB "
                                f"is sent as its first {most // 2**10} KB" if size else
                                f"a file is {most // 2**20} MB at most")
    return await _keep(session, request, conversation_id, shown, frame_of, bytes(data), size)


@router.post(
    "/conversations/{conversation_id}/attachments/project", response_model=AttachmentOut,
    status_code=201, dependencies=[Depends(require_own_origin)],
)
async def add_project_file(
    conversation_id: str, request: Request, path: str = Query(max_length=4000),
    session: Session = Depends(get_session),
):
    """"A file of the project…": one of the chat's project, by the Files window's rules -
    never a secret, a link or a place KOLONİ never opens."""
    shown = _room_for(session, conversation_id, path, None)
    project = project_of(session, session.get_one(Conversation, conversation_id))
    if project is None:
        raise HTTPException(404, "this chat has no project folder")
    try:
        data = await asyncio.to_thread(
            project_files.bytes_of, project.root_path, path, attachments.MAX_BYTES)
    except Refused as refused:
        raise HTTPException(refused.status, str(refused)) from None
    return await _keep(session, request, conversation_id, shown, None, data)


@router.post(
    "/conversations/{conversation_id}/attachments/github-issue", status_code=201,
    dependencies=[Depends(require_own_origin)],
)
async def add_github_issue(
    conversation_id: str, request: Request, ref: str = Query(max_length=300),
    session: Session = Depends(get_session),
):
    """Item 57, "From a GitHub issue…": an issue - its number in the project's repository or its
    address - read with the user's own gh, kept as a file of the next message. Anyone can write
    an issue: its text is framed as data (`web.framed`, as a fetched page is), and noted where it
    reads like orders; its name holds its number alone, never its title."""
    conversation = session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(404, "conversation not found")
    project = project_of(session, conversation)
    if project is None:
        raise HTTPException(404, "this chat has no project folder")
    try:
        ref = git.issue_ref(ref)
        # (Room for it first: GitHub is not asked for a file the message cannot take.)
        shown = _room_for(session, conversation_id, f"github-issue-{ref.rsplit('/')[-1]}.md", None)
        found = await asyncio.to_thread(git.issue, Path(project.root_path), ref)
    except git.Refused as refused:
        raise HTTPException(422, str(refused)) from None
    text = found["text"]
    # shortcut: what reads like orders is noted for the agent only - the user is not warned
    # (`injection.warn` needs a turn); warn at the turn's start if a planted issue is seen.
    marked = (f"{injection.NOTE}\n" if injection.scan(text, "web") else "") + web.framed(
        text, attachments.ISSUE)
    added = await _keep(session, request, conversation_id, shown, None, marked.encode("utf-8"))
    return {"attachment": added, "number": found["number"], "url": found["url"]}


def _room_for(session: Session, conversation_id: str, name: str, frame_of: str | None) -> str:
    """The name a file is kept by, once the next message has room for it."""
    if session.get(Conversation, conversation_id) is None:
        raise HTTPException(404, "conversation not found")
    try:
        shown = attachments.clean_name(name)
    except attachments.Refused as exc:
        raise HTTPException(422, str(exc)) from None

    def unsent(*where) -> int:
        return session.scalar(select(func.count()).select_from(Attachment).where(
            Attachment.conversation_id == conversation_id, Attachment.message_id.is_(None),
            *where)) or 0

    if frame_of is not None:
        video = session.get(Attachment, frame_of)
        if video is None or video.conversation_id != conversation_id or video.kind != "video":
            raise HTTPException(422, "a frame is of a video added to this conversation")
        if video.message_id is not None:  # (it would never reach its message)
            raise HTTPException(409, "its video was sent already")
        if unsent(Attachment.frame_of == frame_of) >= attachments.MAX_FRAMES:
            raise HTTPException(422, f"a video has {attachments.MAX_FRAMES} frames at most")
    elif unsent(Attachment.frame_of.is_(None)) >= attachments.MAX_FILES:
        raise HTTPException(422, f"a message has {attachments.MAX_FILES} files at most")
    else:
        # One name, one file of the chat: agents name them ("a.png", then "a (2).png").
        taken = set(session.scalars(select(Attachment.name).where(
            Attachment.conversation_id == conversation_id, Attachment.frame_of.is_(None))))
        stem, suffix, number = PurePath(shown).stem, PurePath(shown).suffix, 2
        while shown in taken:
            shown, number = f"{stem} ({number}){suffix}", number + 1
    return shown


async def _keep(session: Session, request: Request, conversation_id: str, shown: str,
                frame_of: str | None, data: bytes, size: int | None = None) -> dict:
    """`size`: of a video larger than a file may be, of which `data` is the first bytes."""
    if not data:
        raise HTTPException(422, "the file is empty")
    # (A PDF's pages are read off the app's loop.)
    kind, mime, summary, text = await asyncio.to_thread(attachments.read, data, shown)
    if frame_of is not None and kind != "image":
        raise HTTPException(422, "a frame is an image")
    if size is not None and kind != "video":
        raise HTTPException(422, f"a file is {attachments.MAX_BYTES // 2**20} MB at most; "
                            "only a larger video is taken, as its frames")
    added = Attachment(conversation_id=conversation_id, frame_of=frame_of, name=shown,
                       kind=kind, mime=mime, size=size or len(data),
                       summary=attachments.FRAMES_ONLY if size else summary)
    session.add(added)
    session.flush()
    # A program's bytes are not kept at all: only its name and size; nor a larger video's.
    attachments.keep(request.app.state.settings.runtime_root, conversation_id, added.id,
                     None if kind == "executable" or size else data, text)
    session.commit()
    payload = attachment_out(added)
    request.app.state.bus.emit(conversation_id, None, "attachment.created", payload)
    return payload


@router.delete("/attachments/{attachment_id}", status_code=204,
               dependencies=[Depends(require_origin)])
async def remove_attachment(attachment_id: str, request: Request,
                            session: Session = Depends(get_session)):
    """The ×: a file taken off the next message, with the frames of it. One sent stays
    with its message.
    shortcut: one added and never sent nor taken off (the page closed) stays until its chat
    is deleted - the composer shows it again; sweep old unsent ones if they pile up."""
    found = _attachment(session, attachment_id)
    if found.message_id is not None:
        raise HTTPException(409, "it was sent with a message: it stays with it")
    gone = [found, *session.scalars(select(Attachment).where(Attachment.frame_of == found.id))]
    cid = found.conversation_id
    for one in reversed(gone):  # (the frames first: they point at it)
        session.delete(one)
        session.flush()
    session.commit()
    for one in gone:
        attachments.forget(request.app.state.settings.runtime_root, cid, one.id)
        request.app.state.bus.emit(cid, None, "attachment.deleted", {"id": one.id})
    return Response(status_code=204)


@router.get("/attachments/{attachment_id}/file")
def attachment_file(attachment_id: str, request: Request, session: Session = Depends(get_session)):
    """The file as it was added. Only an image, a video or a PDF is shown as what it is;
    anything else is a download - nothing of it runs in the app's page."""
    found = _attachment(session, attachment_id)
    path = attachments.path_of(
        request.app.state.settings.runtime_root, found.conversation_id, found.id)
    if path is None:
        raise HTTPException(404, "only its name and size are kept")
    shown = found.kind in attachments.SHOWN
    way = "inline" if shown else "attachment"
    return Response(
        path.read_bytes(), media_type=found.mime if shown else "application/octet-stream",
        headers={**HEADERS,
                 "Content-Disposition": f"{way}; filename*=UTF-8''{quote(found.name)}"})


@router.get("/attachments/{attachment_id}/text", response_model=AttachmentTextOut)
def attachment_text(attachment_id: str, request: Request,
                    session: Session = Depends(get_session)):
    """What a model is given of it: the text taken out, its secrets masked."""
    found = _attachment(session, attachment_id)
    return {"text": attachments.text_of(
        request.app.state.settings.runtime_root, found.conversation_id, found.id)}
