"""What the user's Copilot account offers, as Copilot itself lists it (`models.list`, asked beside
`account.getQuota` with no model turn: `limits.copilot_quota`), and what KOLONİ makes of it.

Measured on 1.0.114 (24 Nov 2026, the user's account, an empty home): `{"models": [], "auto":
{"defaultTier": "balance", "tiers": [{"id": "balance", "displayName": "Standard", "type": "auto",
"fusionTier": "standard", "status": {"enabled": true, "pickerVisible": true}}, {"id":
"hydrafusion", "displayName": "High", "type": "fusion", "fusionTier": "high", "status": {"enabled":
false, "reason": "user_not_eligible", "message": "This tier is not available for the user's
Copilot plan."}}, ..., {"id": "fast", "displayName": "Fast", "type": "auto", "status": {"enabled":
true, "pickerVisible": false}}]}}`, with chat requests left and premium at 0. On 23 Nov the same
account listed ~14 models: the list follows the plan, and is read again (`Limits.refresh`).

A row of a Copilot provider that its account does not offer is switched off, with why, as a
model Copilot refused is (`AgentRunner._refused`); one KOLONİ switched off is switched back on
once the account lists it again - only then, and never one Copilot refused while its account
listed it (`LISTED_REFUSED`): the list is not its word on that model. One the user switched off
stays off.
"""

import re

from app.model_cli import _dict

# Copilot's own names for its routed models (`model_session.ROUTINGS`).
AUTO, FUSION = "auto", "fusion"
MOST_MODELS = 200
MOST_TIERS = 20
MAX_TEXT = 300
# A tier's id goes into a command line (`--auto-tier`): only such a word is kept.
TIER_ID = re.compile(r"[a-z][a-z0-9_-]{0,39}")
NOT_LISTED = "not on your Copilot plan now: Copilot's own list does not offer it"
NO_PREMIUM = (
    "your Copilot plan has no premium requests now: its named models are off until Copilot "
    "lists them again"
)
# Said after why Copilot refused a model its account listed then (`AgentRunner._refused`): such a
# row is the user's to switch on again, whatever the list says later.
LISTED_REFUSED = ", though your Copilot account listed it: switch it on to try it again"


def _text(value: object, most: int = MAX_TEXT) -> str | None:
    ok = isinstance(value, str) and 0 < len(value) <= most and value.isprintable()
    return value if ok else None


def _tier(told: object) -> dict | None:
    told = _dict(told)
    status = _dict(told.get("status"))
    kind, tier, fusion = told.get("type"), told.get("id"), told.get("fusionTier")
    if kind not in (AUTO, FUSION) or not (isinstance(tier, str) and TIER_ID.fullmatch(tier)):
        return None
    on = status.get("enabled") is True
    return {
        "id": tier,
        "name": _text(told.get("displayName"), 60) or tier,
        "type": kind,
        # The routing its Fusion takes for it (`FusionTier`): standard, high, max.
        "fusion": fusion if isinstance(fusion, str) and TIER_ID.fullmatch(fusion) else None,
        "enabled": on,
        # The account's own words for why not (its "message"), else its reason's code.
        "why": None if on else _text(status.get("message")) or _text(status.get("reason"), 60),
    }


def offers_of(listed: object) -> dict | None:
    """models.list's answer as KOLONİ keeps it: the ids of the models it lists, and Auto's
    tiers with whether each is on and why not - each string one printable line, the counts
    bounded. None: no list in it (not asked, refused, or not read in time).
    shortcut: of a model only its `id` is read, taken to be the name `--model` takes - the shape
    of a listed model is from 23 Nov's listing, not from an answer kept here (premium at 0 lists
    none now); check both against the next account that lists models."""
    listed = _dict(listed)
    models = listed.get("models")
    if not isinstance(models, list):
        return None
    ids = [_text(_dict(m).get("id")) for m in models[:MOST_MODELS]]
    tiers = _dict(listed.get("auto")).get("tiers")
    kept = [_tier(t) for t in (tiers if isinstance(tiers, list) else [])[:MOST_TIERS]]
    return {
        "models": list(dict.fromkeys(i for i in ids if i)),
        "tiers": [t for t in kept if t is not None],
    }


def offered(name: str, offers: dict) -> bool | None:
    """Whether the account offers a row's model: auto while one of its auto tiers is on, fusion
    while one of its fusion tiers is (Standard is an auto tier's: `balance` says it), any other
    by its list. None: not known (an answer with no tiers says nothing of auto or fusion)."""
    if name in (AUTO, FUSION):
        if not offers["tiers"]:
            return None
        return any(t["enabled"] for t in offers["tiers"] if t["type"] == name)
    return name in offers["models"]


def offered_names(offers: dict) -> list[str]:
    """The models the account offers now, by the names a row takes: its list, then auto and
    fusion where they are offered."""
    return [*offers["models"], *(name for name in (AUTO, FUSION) if offered(name, offers))]


def premium_none(told: object) -> bool:
    """Whether getQuota said no premium request is left (0 of 0 on 24 Nov 2026)."""
    premium = _dict(_dict(_dict(told).get("quotaSnapshots")).get("premium_interactions"))
    return premium.get("isUnlimitedEntitlement") is not True and (
        premium.get("hasQuota") is False or premium.get("remainingPercentage") == 0
    )


def why_not(name: str, offers: dict, no_premium: bool) -> str:
    """Why the account does not offer a row's model, in a line: auto's or fusion's in its own
    words where it says them."""
    if name in (AUTO, FUSION):
        said = next((t["why"] for t in offers["tiers"] if t["type"] == name and t["why"]), None)
        return f"Copilot says: {said}" if said else NOT_LISTED
    return NO_PREMIUM if no_premium else NOT_LISTED


def switched(
    rows: list[dict], offers: dict, no_premium: bool, before: dict | None = None
) -> list[dict]:
    """A Copilot provider's rows as its account offers them now: one it does not offer is
    switched off with why (`off_why`); one KOLONİ switched off (it has an `off_why`) is switched
    back on where the account offers it now and was not known to when last asked (`before`: an
    answer with no tiers says nothing of auto or fusion) - but never one Copilot refused while
    it was listed (`LISTED_REFUSED`), or it would fail the next agent again. One the user
    switched off has none: it stays off."""
    out = []
    for row in rows:
        on = offered(row["name"], offers)
        again = on and before is not None and offered(row["name"], before) is not True
        why = row.get("off_why") or ""
        if again and row.get("enabled") is False and why and LISTED_REFUSED not in why:
            row = {k: v for k, v in row.items() if k not in ("enabled", "off_why")}
        elif on is False and row.get("enabled") is not False:
            row = {**row, "enabled": False, "off_why": why_not(row["name"], offers, no_premium)}
        out.append(row)
    return out
