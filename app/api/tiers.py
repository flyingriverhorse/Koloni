"""The order in which each tier's models are tried (slice 81a): the user's, set on the Models
page. The tier itself is set on the provider; each tiered model keeps its place as `order`
in its provider's list (app.api.providers._guide)."""

from math import inf

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_session, require_own_origin
from app.db.models import Provider
from app.providers import TIERS, list_providers
from app.schemas import TiersIn, TiersOut

router = APIRouter(prefix="/api/tiers", tags=["providers"])


def tiers(providers: list[Provider]) -> dict[str, list[dict]]:
    """Each tier's models in the user's order; those never ordered after them, in the
    providers' order and then each list's (as `app.team.Would.first`)."""
    found: dict[str, list[tuple[float, dict]]] = {tier: [] for tier in TIERS}
    for provider in providers:
        for m in provider.models or []:
            if m.get("tier"):
                found[m["tier"]].append((m.get("order", inf), {
                    "provider_id": provider.id, "provider_name": provider.name, "model": m["name"],
                    # As the team guide has it (app.team.guide): passed over when off, or when
                    # it, or its provider, is switched off.
                    "agents": provider.for_agents and provider.enabled is not False
                    and m.get("agents", True) and m.get("enabled", True),
                }))
    return {tier: [one for _at, one in sorted(rows, key=lambda row: row[0])]
            for tier, rows in found.items()}


@router.get("", response_model=TiersOut)
def get_tiers(session: Session = Depends(get_session)):
    return tiers(list_providers(session))


@router.put("", response_model=TiersOut, dependencies=[Depends(require_own_origin)])
def put_tiers(body: TiersIn, session: Session = Depends(get_session)):
    """The user's order of each tier: exactly the models that have it, each once."""
    providers = list_providers(session)
    now = tiers(providers)
    order: dict[tuple[str, str], int] = {}
    for tier in TIERS:
        told = [(one.provider_id, one.model) for one in getattr(body, tier)]
        if sorted(told) != sorted((one["provider_id"], one["model"]) for one in now[tier]):
            raise HTTPException(
                422, f"the {tier} list has to be exactly the models whose tier is {tier}, "
                "each once")
        order.update((key, at) for at, key in enumerate(told))
    for provider in providers:
        # A new list, so the JSON column is seen to change.
        provider.models = [
            {**m, "order": order[(provider.id, m["name"])]} if m.get("tier") else m
            for m in provider.models or []
        ] or None
    session.commit()
    return tiers(providers)
