"""Roles' categories (slice 63b): labels the Agents page finds roles by - a name, a colour and
a place. Changed only from the app's own page; one goes only while no role is in it. They change
no team's stages."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_session, require_own_origin
from app.db.models import Category, Role
from app.roles import LEADS, STAGES
from app.schemas import CategoryIn, CategoryOrder, CategoryOut, CategoryPatch

# The four built-in categories are today's kinds of work (`STAGES`' keys).
# shortcut: Data, ML and Ops (migration 0103) go as the user's do, once empty - a built-in role of
# theirs reset then lands in the first category (`landing_kind`); keep them too if that is met.
BUILT_IN = dict(STAGES)
MOST = 200

router = APIRouter(prefix="/api/categories", tags=["categories"])


def _all(session: Session) -> list[Category]:
    return list(session.scalars(select(Category).order_by(Category.position)))


def _category(session: Session, key: str) -> Category:
    category = session.get(Category, key)
    if category is None:
        raise HTTPException(404, "category not found")
    return category


def _free(session: Session, name: str, category: Category | None = None) -> None:
    # (casefold in Python: SQLite's lower() knows only ASCII.)
    other = next((one for one in _all(session) if one.name.casefold() == name.casefold()), None)
    if other is not None and other is not category:
        raise HTTPException(409, f"there is already a category named {other.name}")


@router.get("", response_model=list[CategoryOut])
def categories(session: Session = Depends(get_session)):
    return _all(session)


@router.post("", response_model=list[CategoryOut], status_code=201)
def add_category(body: CategoryIn, request: Request, session: Session = Depends(get_session)):
    require_own_origin(request)
    _free(session, body.name)
    # (As many as an order names at most: `CategoryOrder`.)
    if (session.scalar(select(func.count()).select_from(Category)) or 0) >= MOST:
        raise HTTPException(409, f"there are {MOST} categories already: delete an empty one first")
    last = session.scalar(select(func.max(Category.position)))
    session.add(Category(name=body.name, colour=body.colour,
                         position=0 if last is None else last + 1))
    session.commit()
    return _all(session)


@router.patch("/{key}", response_model=list[CategoryOut])
def change_category(key: str, body: CategoryPatch, request: Request,
                    session: Session = Depends(get_session)):
    require_own_origin(request)
    category = _category(session, key)
    if body.name is not None:
        _free(session, body.name, category)
        category.name = body.name
    if body.colour is not None:
        category.colour = body.colour
    session.commit()
    return _all(session)


@router.put("", response_model=list[CategoryOut])
def order_categories(body: CategoryOrder, request: Request,
                     session: Session = Depends(get_session)):
    require_own_origin(request)
    every = _all(session)
    if sorted(body.order) != sorted(one.key for one in every):
        raise HTTPException(422, "the order names every category, each once")
    for category in every:
        category.position = body.order.index(category.key)
    session.commit()
    return _all(session)


@router.delete("/{key}", status_code=204)
def delete_category(key: str, request: Request, session: Session = Depends(get_session)):
    """Only an empty one of the user's goes: no role is ever left without a category."""
    require_own_origin(request)
    category = _category(session, key)
    # The four built-in ones stay: "check" says who reports findings (app.agent), and the
    # built-in roles land in theirs (`landing_kind`).
    if key in BUILT_IN:
        raise HTTPException(409, f"{category.name} is one of KOLONİ's four categories: it can be "
                                 "renamed and recoloured, not deleted")
    # (A team's lead is in none, whatever its kind reads.)
    # shortcut: a role moved in between this count and the delete is left in no category (the
    # library shows it under its key); count again in one statement if that is ever seen.
    held = session.scalar(select(func.count()).select_from(Role).where(
        Role.kind == key, Role.id.not_in(LEADS)))
    if held:
        raise HTTPException(409, f"{category.name} holds {held} role{'s' if held != 1 else ''}: "
                                 "move them to another category first")
    session.delete(category)
    session.commit()
    return Response(status_code=204)
