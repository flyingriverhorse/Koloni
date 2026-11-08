"""Export everything, and restore from a file (K-disa-aktar; `app.backup`). Only the user,
through the app's own page: both are own-origin and behind the page key, and no agent's
tool reaches either."""

import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from starlette.background import BackgroundTask

from app import backup
from app.agent import TERMINAL
from app.api.deps import require_own_origin
from app.db.models import Run
from app.schemas import RestoreOut, StagedOut

router = APIRouter(prefix="/api/backup", tags=["backup"])
# (Not on reading what is staged: a page's own GET says no origin.)
OWN = [Depends(require_own_origin)]


@router.post("/export", response_class=FileResponse, dependencies=OWN, responses={
    200: {"content": {"application/zip": {}}, "description": "Everything, as one .zip"}})
def export(request: Request, secrets: bool = False):
    """The .zip, built in a folder of its own and sent from there; the folder goes after.
    A POST: a form sends its origin, which a download link does not."""
    settings = request.app.state.settings
    tmp = Path(tempfile.mkdtemp(prefix="koloni-export-"))
    out = tmp / "koloni-export.zip"
    try:
        backup.export(settings.runtime_root, settings.db_path, out, secrets)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    # shortcut: only a KOLONİ killed while it sends leaves the folder (with the secrets,
    # where asked for) in the temp folder, until the OS clears it; sweep old ones at the
    # start if that is ever seen.
    return FileResponse(out, media_type="application/zip", filename=f"koloni-{stamp}.zip",
                        background=BackgroundTask(shutil.rmtree, tmp, ignore_errors=True))


@router.post("/restore", response_model=RestoreOut, dependencies=OWN)
async def restore(request: Request):
    """A .zip as the request's body (as an attachment is sent): checked and staged; it
    replaces the data at the next start. Never while a turn runs."""
    settings = request.app.state.settings
    with request.app.state.session_factory() as session:
        if session.scalar(select(func.count()).select_from(Run).where(Run.status.not_in(TERMINAL))):
            raise HTTPException(409, "a turn is running: stop it, or wait for it to end, first")
    if backup.held_copies(settings.runtime_root):
        raise HTTPException(409, backup.HELD_COPIES)
    handle, name = tempfile.mkstemp(prefix="koloni-restore-", suffix=".zip")
    upload = Path(name)
    try:
        # (Written off the event loop: a GB-sized upload's writes held every chat meanwhile.)
        out = await run_in_threadpool(lambda: os.fdopen(handle, "wb"))
        try:
            got = 0
            async for chunk in request.stream():
                got += len(chunk)
                if got > backup.MAX_UPLOAD:
                    raise HTTPException(413, f"a file is {backup.MAX_UPLOAD // 2**30} GB at most")
                await run_in_threadpool(out.write, chunk)
        finally:
            await run_in_threadpool(out.close)
        try:
            manifest = await run_in_threadpool(backup.stage, settings.runtime_root, upload)
        except backup.Refused as exc:
            raise HTTPException(422, f"not restored: {exc}") from None
    finally:
        upload.unlink(missing_ok=True)
    return backup.summary(manifest)


@router.get("/staged", response_model=StagedOut)
def staged(request: Request):
    """The restore that waits for the next start, if one does; and the newest one a start
    could not apply, where it is kept."""
    root = request.app.state.settings.runtime_root
    failed = backup.last_failed(root)
    return {"staged": backup.staged_summary(root), "failed": str(failed) if failed else None}


@router.delete("/staged", status_code=204, dependencies=OWN)
def cancel(request: Request) -> Response:
    """The staged restore given up: the next start keeps the data as it is."""
    shutil.rmtree(request.app.state.settings.runtime_root / backup.STAGED, ignore_errors=True)
    return Response(status_code=204)
