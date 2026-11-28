"""The Judge model (0.1.9): whom KOLONİ's judges ask - Full auto's, and the check of the user's
words. The user's choice in Settings, for every project; none chosen, the Fast tier's first
model that answers with no tools (`team.judge_pick`)."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app import advisor, judge
from app.api.deps import get_session, require_origin, require_own_origin
from app.db.models import Provider, UserPreferences
from app.model_client import OwnStop
from app.providers import mode_of
from app.roles import LEAD, find_role
from app.team import Entry, judge_choices, judge_chosen, judge_pick, would_run

router = APIRouter(prefix="/api/judge", tags=["judge"], dependencies=[Depends(require_origin)])


class JudgeModel(BaseModel):
    provider_id: str
    provider_name: str
    model_id: str
    # Whether it is a CLI: its one-shot start makes each judged command wait for it.
    cli: bool
    # §8: whether it runs as its measurement of Check what I said first passed (`judge.measured`) -
    # the judge's box for the user's words works on it; never for `now` asked in the chosen one's
    # place (the gate's `fallback`).
    measured: bool


class JudgeChoice(JudgeModel):
    tier: str


class JudgeOut(BaseModel):
    # The user's choice; null: none (the Fast tier's first).
    provider_id: str | None
    model_id: str | None
    # Whom the judges ask now: the choice where it may be asked, else the Fast tier's first;
    # null: nobody (Full auto's judge stands aside, and says so in the chat).
    now: JudgeModel | None
    # What may be chosen: of every tier, the models that answer with no tools now.
    choices: list[JudgeChoice]


class JudgeIn(BaseModel):
    provider_id: str | None = Field(default=None, max_length=32)
    model_id: str | None = Field(default=None, max_length=200)


def _model(session: Session, one: Entry, name: str, fallback: bool = False) -> dict:
    provider = session.get_one(Provider, one.provider_id)
    return {
        "provider_id": one.provider_id,
        "provider_name": one.name,
        "model_id": name,
        "cli": mode_of(provider) is not None,
        "measured": judge.measured(provider, name) and not fallback,
    }


def _judge(session: Session, request: Request) -> dict:
    providers = request.app.state.providers
    chosen = judge_chosen(session)
    try:
        would = would_run(session, find_role(session, LEAD), None)
    except OwnStop:  # (no provider at all: nobody to choose)
        would = None
    now = judge_pick(session, would, providers, chosen) if would else None
    return {
        "provider_id": chosen[0] if chosen else None,
        "model_id": chosen[1] if chosen else None,
        "now": _model(session, *now, chosen is not None and (now[0].provider_id, now[1]) != chosen)
        if now
        else None,
        "choices": [
            {**_model(session, one, name), "tier": tier}
            for one, name, tier in (judge_choices(session, would, providers) if would else [])
        ],
    }


@router.get("", response_model=JudgeOut)
def get_judge(request: Request, session: Session = Depends(get_session)):
    return _judge(session, request)


@router.put("", response_model=JudgeOut, dependencies=[Depends(require_own_origin)])
def put_judge(body: JudgeIn, request: Request, session: Session = Depends(get_session)):
    """The user's Judge model: one of `choices` now, or none (both null: the Fast tier's first)."""
    chosen = (body.provider_id, body.model_id) if body.provider_id or body.model_id else None
    listed = {(one["provider_id"], one["model_id"]) for one in _judge(session, request)["choices"]}
    if chosen is not None and chosen not in listed:
        raise HTTPException(422, "the Judge model is one of the models listed, or none")
    # (The one row of the user's preferences, made where none is: no words of theirs in it.)
    session.execute(insert(UserPreferences).values(id=1).on_conflict_do_nothing())
    row = session.get_one(UserPreferences, 1)
    row.judge_provider_id, row.judge_model_id = chosen or (None, None)
    session.commit()
    return _judge(session, request)


# --- ask_advisor (0.1.11): the Advisor model, beside the Judge model ---------------------------

advisor_router = APIRouter(
    prefix="/api/advisor", tags=["judge"], dependencies=[Depends(require_origin)]
)


class AdvisorOut(BaseModel):
    # The user's choice; null: none - another provider's than the Orchestrator's (`advisor.pick`).
    provider_id: str | None
    model_id: str | None
    # What may be chosen: of every tier, the models that answer with no tools now.
    choices: list[JudgeChoice]


def _advisor(session: Session, request: Request) -> dict:
    chosen = advisor.chosen(session)
    return {
        "provider_id": chosen[0] if chosen else None,
        "model_id": chosen[1] if chosen else None,
        "choices": _judge(session, request)["choices"],
    }


@advisor_router.get("", response_model=AdvisorOut)
def get_advisor(request: Request, session: Session = Depends(get_session)):
    return _advisor(session, request)


@advisor_router.put("", response_model=AdvisorOut, dependencies=[Depends(require_own_origin)])
def put_advisor(body: JudgeIn, request: Request, session: Session = Depends(get_session)):
    """The user's Advisor model: one of `choices` now, or none (both null: another provider's)."""
    chosen = (body.provider_id, body.model_id) if body.provider_id or body.model_id else None
    listed = {(one["provider_id"], one["model_id"]) for one in _judge(session, request)["choices"]}
    if chosen is not None and chosen not in listed:
        raise HTTPException(422, "the Advisor model is one of the models listed, or none")
    advisor.choose(session, chosen)
    session.commit()
    return _advisor(session, request)
