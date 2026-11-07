"""The skills KOLONİ keeps (slice 45): reading a folder of the user's and keeping a copy of
it, or giving its scripts leave, is the user's to do from the app's own page."""

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import literal_column, select
from sqlalchemy.orm import Session

from app import skill_upload, skills
from app.api.deps import get_session, require_own_origin
from app.db.models import Role, Skill
from app.schemas import SkillIn, SkillOut, SkillPatch, SkillPreview

router = APIRouter(prefix="/api/skills", tags=["skills"])
# shortcut: no skill written by hand and no "take it again" from its source (design 2); add
# them when they are wanted.
OWN = [Depends(require_own_origin)]


def _remove_folder(request: Request, folder: str) -> None:
    """A kept skill's copy, removed - only where the store keeps one."""
    store = (request.app.state.settings.runtime_root / "skills").resolve()
    if Path(folder).resolve().is_relative_to(store) and Path(folder).resolve() != store:
        shutil.rmtree(folder, ignore_errors=True)


def _found(body: SkillIn) -> skills.Found:
    try:
        if [body.folder, body.github, body.upload].count(None) != 2:
            raise skills.SkillError("name one: a folder, a GitHub address or an upload")
        if body.upload is None:
            return skills.take(body.folder, body.github)
        return skill_upload.listing(body.upload)
    except skills.SkillError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("", response_model=list[SkillOut])
def list_skills(session: Session = Depends(get_session)):
    return session.scalars(
        select(Skill).order_by(Skill.created_at, literal_column("skills.rowid"))).all()


# (Sync routes: FastAPI runs them in its threads, so a folder read or a download never
# holds up the app's loop.)
@router.post("/preview", response_model=SkillPreview, dependencies=OWN)
def preview_skill(body: SkillIn):
    """What would be kept - its text, files, size, licence, scripts and what is not copied -
    before the user says yes. Nothing is kept; from GitHub nothing more is downloaded."""
    return _found(body).shown()


@router.post("", response_model=SkillOut, status_code=201, dependencies=OWN)
def add_skill(body: SkillIn, request: Request, session: Session = Depends(get_session)):
    found = _found(body)
    if body.sha256 is not None and body.sha256 != found.digest:
        raise HTTPException(409, "it has changed since it was read: read it again")
    try:
        taken = skills.named(session, found.name)
        if taken is not None and not body.replace:
            raise skills.SkillError(f"there is already a skill named {found.name}")
        old = taken.folder if taken is not None else None
        # (One it replaces that was switched off stays off.)
        enabled = taken is None or taken.enabled
        if taken is not None:
            # A role names its skills exactly: one that had "tidy" has the "Tidy" put in.
            for role in session.scalars(select(Role)):
                if taken.name in role.skills:
                    role.skills = [found.name if name == taken.name else name
                                   for name in role.skills]
            # (One commit with the new one: a failed add leaves the old one as it was.)
            session.delete(taken)
            session.flush()
        added = skills.add(session, request.app.state.settings.runtime_root,
                           skills.whole(found), body.scripts_run_unasked, enabled)
    except skills.SkillError as exc:
        raise HTTPException(409, str(exc)) from None
    if old is not None:
        _remove_folder(request, old)
    return added


@router.delete("/{skill_id}", status_code=204, dependencies=OWN)
def delete_skill(skill_id: str, request: Request, session: Session = Depends(get_session)):
    skill = session.get(Skill, skill_id)
    if skill is None:
        raise HTTPException(404, "skill not found")
    # No role is left naming a skill that is gone - or one added later under its name.
    gone = skill.name.lower()
    for role in session.scalars(select(Role)):
        if any(name.lower() == gone for name in role.skills):
            role.skills = [name for name in role.skills if name.lower() != gone]
    folder = skill.folder
    session.delete(skill)
    session.commit()
    _remove_folder(request, folder)
    return Response(status_code=204)


@router.patch("/{skill_id}", response_model=SkillOut, dependencies=OWN)
def patch_skill(skill_id: str, body: SkillPatch, session: Session = Depends(get_session)):
    skill = session.get(Skill, skill_id)
    if skill is None:
        raise HTTPException(404, "skill not found")
    if body.scripts_run_unasked is not None:
        skill.scripts_run_unasked = body.scripts_run_unasked
    if body.enabled is not None:
        skill.enabled = body.enabled
    session.commit()
    return skill
