import hmac
from collections.abc import Iterator

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session
from starlette.datastructures import Headers, QueryParams

from app import views


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def require_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin not in request.app.state.settings.allowed_origins:
        raise HTTPException(403, "origin not allowed")


def carries_key(scope) -> bool:
    """Whether a request carries the key this start made (slice 94): in `X-KOLONI-Key`, or
    `?key=`."""
    key = scope["app"].state.page_key.encode()
    given = (
        Headers(scope=scope).get("x-koloni-key"), QueryParams(scope["query_string"]).get("key"))
    # (As bytes: a str holding other than ASCII cannot be compared in constant time.)
    return any(value and hmac.compare_digest(value.encode(), key) for value in given)


def keyed_if_read_by_the_app(request: Request, kind: str) -> None:
    """K-belge-ciktilari: a document the app reads itself (`views.KEYED`) - not one a frame
    loads - is served on a keyless door only with the key all the same."""
    if kind in views.KEYED and not carries_key(request.scope):
        raise HTTPException(401, "open KOLONİ from the link in its window")


def require_own_origin(request: Request) -> None:
    """For what only the user may do through the app's own page: the request has to say
    where it is from. A browser does, on everything that changes something; a command an
    agent runs against the app's address does not. (Not a wall - a program on the user's
    machine can say anything - but a request that says nothing is not taken for the user.)"""
    if request.headers.get("origin") not in request.app.state.settings.allowed_origins:
        raise HTTPException(403, "origin not allowed")
