"""KOLONİ's own tools switched on or off on the Tools page (slice 61): one switched off is
offered to no agent, whatever its role lists. Switching is taken only from the app's own page."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.api.deps import get_session, require_own_origin
from app.db.models import Flag
from app.roles import OFF, SWITCHABLE, tools_off
from app.schemas import BuiltinToolIn, BuiltinToolOut

router = APIRouter(prefix="/api/builtin-tools", tags=["builtin tools"])


@router.get("", response_model=list[BuiltinToolOut])
def builtin_tools(session: Session = Depends(get_session)):
    off = tools_off(session)
    return [{"name": name, "on": name not in off} for name in SWITCHABLE]


@router.put("/{name}", response_model=list[BuiltinToolOut],
            dependencies=[Depends(require_own_origin)])
def switch_tool(name: str, body: BuiltinToolIn, session: Session = Depends(get_session)):
    if name not in SWITCHABLE:
        raise HTTPException(404, f"{name} is not one of the tools switched here")
    if body.on:
        session.execute(delete(Flag).where(Flag.name == OFF + name))
    else:
        # (merge: a second click before the first is answered finds the row, and keeps it)
        session.merge(Flag(name=OFF + name, value="1"))
    session.commit()
    return builtin_tools(session)
