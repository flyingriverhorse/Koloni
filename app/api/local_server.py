"""The model server on this machine (slice 64). What starts, stops or sets it is only the
user's, from the app's own page (`require_own_origin`): an agent's command against the app's
address can neither start a program nor choose one."""

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import require_origin, require_own_origin
from app.local_server import Busy, LocalServer, NotStarted
from app.schemas import LocalServerIn, LocalServerOut

router = APIRouter(prefix="/api/local-server", tags=["local-server"])
OWN = [Depends(require_own_origin)]


def _server(request: Request) -> LocalServer:
    return request.app.state.local_server


@router.get("", response_model=LocalServerOut, dependencies=[Depends(require_origin)])
async def local_server(request: Request):
    return await _server(request).status()


@router.put("", response_model=LocalServerOut, dependencies=OWN)
async def set_local_server(body: LocalServerIn, request: Request):
    """Kept for the next Start; one that runs goes on as it was started."""
    server = _server(request)
    server.save(body.executable, body.args)
    return await server.status()


async def _run(request: Request, action: str) -> dict:
    server = _server(request)
    try:
        await getattr(server, action)()
    except Busy:
        raise HTTPException(409, "the server is already running; Restart starts it anew") from None
    except NotStarted as exc:
        raise HTTPException(422, str(exc)) from None
    if action != "stop":
        # Another model or window may be served now: what the clients learned is asked again.
        request.app.state.providers.forget()
    return await server.status()


@router.post("/start", response_model=LocalServerOut, dependencies=OWN)
async def start(request: Request):
    return await _run(request, "start")


@router.post("/stop", response_model=LocalServerOut, dependencies=OWN)
async def stop(request: Request):
    return await _run(request, "stop")


@router.post("/restart", response_model=LocalServerOut, dependencies=OWN)
async def restart(request: Request):
    return await _run(request, "restart")
