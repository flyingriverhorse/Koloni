"""The user's own slash commands (slice 53): saved, changed and removed only from the app's
own page - a command an agent runs could otherwise put words in the user's mouth."""

import re
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_session, require_origin, require_own_origin
from app.db.models import OwnCommand, Project, Role, new_id
from app.roles import find_agent_role
from app.schemas import OwnCommandIn, OwnCommandOut, OwnCommandPatch

router = APIRouter(
    prefix="/api/own-commands", tags=["own commands"], dependencies=[Depends(require_origin)])
OWN = [Depends(require_own_origin)]

# The box's own commands (slice 46, 49's `/plan`, 54's `/compare`): a saved one would
# never be reached.
RESERVED = frozenset({"new", "room", "stop", "model", "mode", "plan", "compare"})
NAME = re.compile(r"[^\s/]{1,40}")


def fold(name: str) -> str:
    """Exactly as the box's menu looks a name up (frontend `fold`): lower case, NFD, every
    mark (category M) dropped, ı as i. Not casefold(): the page keeps ß, and drops U+FE0F."""
    plain = unicodedata.normalize("NFD", name.lower())
    return "".join(
        c for c in plain if not unicodedata.category(c).startswith("M")).replace("ı", "i")


def out(command: OwnCommand) -> dict:
    return {key: getattr(command, key)
            for key in ("id", "name", "description", "template", "role", "project_id")}


def _command(session: Session, command_id: str) -> OwnCommand:
    command = session.get(OwnCommand, command_id)
    if command is None:
        raise HTTPException(404, "command not found")
    return command


def _check(session: Session, command: OwnCommand) -> None:
    """The name, project and role of a command about to be saved; refused as the contract says."""
    if not NAME.fullmatch(command.name) or not command.name.isprintable():
        raise HTTPException(422, "a command's name is 1 to 40 characters, no space and no /")
    if not fold(command.name):
        raise HTTPException(422, "a command's name has to have a letter or sign to type")
    if fold(command.name) in RESERVED:
        raise HTTPException(422, f"/{command.name} is the message box's own command")
    if not command.template.strip():
        raise HTTPException(422, "a command's text is empty")
    if command.project_id is not None and session.get(Project, command.project_id) is None:
        raise HTTPException(422, "unknown project")
    if command.role is not None:
        # (One an agent may be opened in: not the Observer, nor a team's lead, slice 63a.)
        role = find_agent_role(session, command.role)
        if role is None:
            raise HTTPException(422, f"there is no role named {command.role}")
        command.role = role.name
    # The box makes "/coder " the role's chip: a command of that name would never be offered.
    # (Not the Lead's: it has no chip.)
    if any(role.name != "Lead" and fold(role.name) == fold(command.name)
           for role in session.scalars(select(Role))):
        raise HTTPException(409, f"/{command.name} is a role's name: the role's chip is meant")
    # Seen together: a global one with every other, a project's with its project's.
    seen = select(OwnCommand).where(OwnCommand.id != command.id)
    if command.project_id is not None:
        seen = seen.where(or_(
            OwnCommand.project_id.is_(None), OwnCommand.project_id == command.project_id))
    # (Compared here, not in SQL: SQLite's lower() knows only ASCII.)
    if any(fold(other.name) == fold(command.name) for other in session.scalars(seen)):
        raise HTTPException(409, f"there is already a command named /{command.name} there")


@router.get("", response_model=list[OwnCommandOut])
def list_commands(project_id: str | None = None, session: Session = Depends(get_session)):
    """The project's commands and the ones for every project."""
    commands = session.scalars(
        select(OwnCommand)
        .where(or_(OwnCommand.project_id.is_(None), OwnCommand.project_id == project_id))
        .order_by(OwnCommand.created_at))
    return [out(command) for command in commands]


@router.post("", response_model=OwnCommandOut, status_code=201, dependencies=OWN)
def create_command(body: OwnCommandIn, session: Session = Depends(get_session)):
    # An id before the check, which leaves the command itself out.
    command = OwnCommand(id=new_id(), **body.model_dump())
    _check(session, command)
    session.add(command)
    session.commit()
    return out(command)


@router.patch("/{command_id}", response_model=OwnCommandOut, dependencies=OWN)
def patch_command(command_id: str, body: OwnCommandPatch, session: Session = Depends(get_session)):
    command = _command(session, command_id)
    for key in body.model_fields_set:
        value = getattr(body, key)
        # name, description and template sent as null: left as they are.
        if value is not None or key in ("role", "project_id"):
            setattr(command, key, value)
    with session.no_autoflush:
        _check(session, command)
    session.commit()
    return out(command)


@router.delete("/{command_id}", status_code=204, dependencies=OWN)
def delete_command(command_id: str, session: Session = Depends(get_session)):
    session.delete(_command(session, command_id))
    session.commit()
    return Response(status_code=204)
