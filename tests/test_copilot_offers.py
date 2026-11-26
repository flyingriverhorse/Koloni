"""KOLONİ's Copilot shows only what the user's Copilot account offers (the user, 24 Nov 2026):
`models.list` asked beside `account.getQuota` in one headless start, no model turn - kept on the
provider, its rows switched by it, its fills and lists held to it; its chat requests and its
premium ones shown apart, and its auto not held back by premium at 0."""

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.limits
from app.agent.tiers_mixin import TiersMixin
from app.api.providers import ADD_FIRST, NONE_LISTED
from app.copilot_offers import (
    LISTED_REFUSED,
    NO_PREMIUM,
    NOT_LISTED,
    offered,
    offered_names,
    offers_of,
    premium_none,
    switched,
)
from app.db.models import Provider
from app.limits import CHAT, PREMIUM, Limits, account, at_limit, copilot_quota, of_copilot
from app.model_client import ModelUnavailable
from app.model_session import CopilotSessionClient
from app.providers import list_providers

ORIGIN = {"Origin": "http://127.0.0.1:8790"}
FAKE_COPILOT = [sys.executable, str(Path(__file__).with_name("fake_copilot_headless.py"))]
NOT_ON_PLAN = "This tier is not available for the user's Copilot plan."
READ_AT = datetime(2026, 11, 24, 17, 13, 30, tzinfo=UTC)


def counter(entitlement: int, used: int, left: float) -> dict:
    return {
        "isUnlimitedEntitlement": False,
        "entitlementRequests": entitlement,
        "usedRequests": used,
        "remainingPercentage": left,
        "resetDate": "2026-11-24T17:13:33.598Z",
        "hasQuota": left > 0,
    }


# As Copilot 1.0.114 answered on the user's account (24 Nov 2026, an empty home, no model call).
MEASURED_QUOTA = {
    "quotaSnapshots": {
        "chat": counter(200, 0, 100),
        "completions": counter(2000, 0, 100),
        "premium_interactions": counter(0, 0, 0),
    }
}
MEASURED_AUTO = {
    "defaultTier": "balance",
    "tiers": [
        {
            "id": "balance",
            "displayName": "Standard",
            "type": "auto",
            "fusionTier": "standard",
            "status": {"enabled": True, "pickerVisible": True},
        },
        {
            "id": "hydrafusion",
            "displayName": "High",
            "type": "fusion",
            "fusionTier": "high",
            "status": {"enabled": False, "reason": "user_not_eligible", "message": NOT_ON_PLAN},
        },
        {
            "id": "hydrafusion-max",
            "displayName": "Max",
            "type": "fusion",
            "fusionTier": "max",
            "status": {"enabled": False, "reason": "user_not_eligible", "message": NOT_ON_PLAN},
        },
        {
            "id": "fast",
            "displayName": "Fast",
            "type": "auto",
            "status": {"enabled": True, "pickerVisible": False},
        },
    ],
    "providerId": "copilot",
}
MEASURED_LIST = {"models": [], "auto": MEASURED_AUTO, "imageModels": []}
OFFERS = offers_of(MEASURED_LIST)


# --- what the account offers, as KOLONİ keeps it ------------------------------------------------


def test_the_measured_list_offers_auto_at_standard_and_fast_and_nothing_by_name():
    assert OFFERS is not None and OFFERS["models"] == []
    assert [(t["id"], t["name"], t["type"], t["enabled"]) for t in OFFERS["tiers"]] == [
        ("balance", "Standard", "auto", True),
        ("hydrafusion", "High", "fusion", False),
        ("hydrafusion-max", "Max", "fusion", False),
        ("fast", "Fast", "auto", True),  # (on, though not in Copilot's own picker)
    ]
    assert OFFERS["tiers"][1]["why"] == NOT_ON_PLAN and OFFERS["tiers"][0]["why"] is None
    assert [t["fusion"] for t in OFFERS["tiers"]] == ["standard", "high", "max", None]
    assert (offered("auto", OFFERS), offered("fusion", OFFERS)) == (True, False)
    assert offered("gpt-6-luna", OFFERS) is False
    assert offered_names(OFFERS) == ["auto"]
    assert premium_none(MEASURED_QUOTA)


def test_what_it_lists_is_kept_bounded_and_nothing_is_made_of_what_it_did_not_say():
    assert offers_of(None) is None and offers_of({"auto": MEASURED_AUTO}) is None
    told = offers_of(
        {
            "models": [
                {"id": "gpt-6-luna"},
                {"id": "gpt-6-luna"},  # (once)
                {"id": "x" * 301},  # too long to be a name
                "not a model",
            ],
            "auto": {
                "tiers": [
                    {"id": "--model=evil", "type": "auto", "status": {"enabled": True}},
                    {"id": "later", "type": "something new", "status": {"enabled": True}},
                    {"id": "fast", "type": "auto", "displayName": "a\nb", "status": {}},
                ]
            },
        }
    )
    assert told == {
        "models": ["gpt-6-luna"],
        "tiers": [
            {
                "id": "fast",
                "name": "fast",
                "type": "auto",
                "fusion": None,
                "enabled": False,
                "why": None,
            }
        ],
    }
    # An answer with no tiers says nothing of auto or fusion: neither is switched for it.
    assert offered("auto", {"models": [], "tiers": []}) is None


def test_a_row_the_account_does_not_offer_is_off_with_why_and_back_on_once_it_does():
    rows = [
        {"name": "gpt-6-luna", "tier": "balanced"},
        {"name": "auto", "routing": "fast"},
        {"name": "fusion", "routing": "high"},
        {"name": "mine-off", "enabled": False},  # the user's: no why of KOLONİ's
    ]
    now = switched(rows, OFFERS, no_premium=True)
    assert now == [
        {"name": "gpt-6-luna", "tier": "balanced", "enabled": False, "off_why": NO_PREMIUM},
        {"name": "auto", "routing": "fast"},
        {
            "name": "fusion",
            "routing": "high",
            "enabled": False,
            "off_why": f"Copilot says: {NOT_ON_PLAN}",
        },
        {"name": "mine-off", "enabled": False},
    ]
    assert switched(rows, OFFERS, no_premium=False)[0]["off_why"] == NOT_LISTED
    later = {**OFFERS, "models": ["gpt-6-luna", "mine-off"]}
    again = switched(now, later, no_premium=False, before=OFFERS)
    assert again[0] == {"name": "gpt-6-luna", "tier": "balanced"}
    assert again[3] == {"name": "mine-off", "enabled": False}  # still the user's to switch on
    # Only once it is listed anew: one Copilot refused while it was listed stays off, and so does
    # one switched off before the account was ever asked.
    refused = [{"name": "gpt-6-luna", "enabled": False, "off_why": "Copilot refused it"}]
    assert switched(refused, later, no_premium=False, before=later) == refused
    assert switched(refused, later, no_premium=False) == refused


# --- its quota: chat and premium apart -----------------------------------------------------------


def test_chat_requests_and_premium_are_two_windows_and_premium_at_0_is_none_not_full():
    shown = of_copilot(MEASURED_QUOTA, READ_AT)
    assert shown["windows"] == [
        {
            "name": CHAT,
            "minutes": None,
            "used_percent": 0,
            "resets_at": None,  # (its resetDate is the moment it was asked)
            "stale": False,
            "limit": 200,
            "remaining": 200,
        },
        {
            "name": PREMIUM,
            "minutes": None,
            "used_percent": None,
            "resets_at": None,
            "stale": False,
            "limit": 0,
            "remaining": 0,
        },
    ]
    assert not at_limit(shown) and not at_limit(shown, "gpt-6-luna")


def test_premium_used_up_holds_back_a_named_model_but_not_auto_while_chat_requests_are_left():
    told = json.loads(json.dumps(MEASURED_QUOTA))
    told["quotaSnapshots"]["premium_interactions"] = counter(300, 300, 0)
    shown = of_copilot(told, READ_AT)
    assert at_limit(shown) and at_limit(shown, "gpt-6-luna")
    assert not at_limit(shown, "auto")
    told["quotaSnapshots"]["chat"] = counter(200, 200, 0)
    assert at_limit(of_copilot(told, READ_AT), "auto")


# --- asked of Copilot itself: one start, both answers -------------------------------------------


def plan(tmp_path, monkeypatch, **more) -> Path:
    record = tmp_path / "record.json"
    given = tmp_path / "plan.json"
    given.write_text(json.dumps({"record": str(record), "script": [], **more}), encoding="utf-8")
    monkeypatch.setenv("FAKE_CLI_PLAN", str(given))
    return record


@pytest.mark.anyio
async def test_one_headless_start_says_the_quota_and_what_the_account_offers(tmp_path, monkeypatch):
    record = plan(tmp_path, monkeypatch, quota=MEASURED_QUOTA, models=[], auto=MEASURED_AUTO)
    told = await copilot_quota(None, "gho_provider", 20, launcher=FAKE_COPILOT)
    assert told["quotaSnapshots"] == MEASURED_QUOTA["quotaSnapshots"]
    assert offers_of(told["listed"]) == OFFERS
    seen = json.loads(record.read_text("utf-8"))
    assert seen["models_asked"] and "create" not in seen and "prompt" not in seen


@pytest.mark.anyio
@pytest.mark.parametrize("refusal", [{"models_error": "no"}, {"models_hang": True}])
async def test_a_list_it_will_not_give_leaves_the_quota_read(tmp_path, monkeypatch, refusal):
    plan(tmp_path, monkeypatch, quota=MEASURED_QUOTA, **refusal)
    monkeypatch.setattr(app.limits, "ALSO_SECONDS", 1.0)  # (one that never answers)
    told = await copilot_quota(None, None, 20, launcher=FAKE_COPILOT)
    assert told["listed"] is None and told["quotaSnapshots"]["chat"]["entitlementRequests"] == 200


# --- kept on the provider, as the Models page and the model panel open --------------------------


def stand_in(monkeypatch, answers: list) -> list:
    """Copilot's reader, answering from `answers` in turn; each call is noted."""
    asked = []

    async def answer(*args):
        asked.append(args)
        told = answers.pop(0)
        if isinstance(told, BaseException):
            raise told
        return told

    monkeypatch.setattr(app.limits, "copilot_quota", answer)
    return asked


def measured(**listed) -> dict:
    return {**MEASURED_QUOTA, "listed": {**MEASURED_LIST, **listed}}


def offers_of_api(client, provider_id: str) -> dict:
    """The provider after the plan meter's look (GET /limits: its account asked where that is due,
    in the background) and the reading it started, if any, is over."""
    assert client.get(f"/api/providers/{provider_id}/limits").status_code == 200
    limits = client.app.state.providers.limits

    async def read() -> None:
        if (reading := limits._reading.get(account(Provider(kind="copilot_cli")))) is not None:
            await reading

    client.portal.call(read)
    return next(one for one in client.get("/api/providers").json() if one["id"] == provider_id)


def test_the_account_is_asked_at_most_once_in_ten_minutes_and_its_rows_follow_it(
    client, monkeypatch
):
    later = {**MEASURED_QUOTA, "quotaSnapshots": {"chat": counter(200, 3, 98.5)}}
    asked = stand_in(
        monkeypatch,
        [
            measured(),
            {**later, "listed": {"models": [{"id": "gpt-6-luna"}], "auto": MEASURED_AUTO}},
        ],
    )
    rows = [
        {"name": "gpt-6-luna", "tier": "balanced"},
        {"name": "auto", "tier": "fast", "routing": "fast"},
        {"name": "fusion", "routing": "high"},
    ]
    made = client.post(
        "/api/providers",
        headers=ORIGIN,
        json={"name": "Copilot", "kind": "copilot_cli", "models": rows},
    ).json()
    assert made["offers"] is None  # not asked yet
    shown = offers_of_api(client, made["id"])
    assert shown["offers"] == OFFERS and len(asked) == 1
    assert [(m["name"], m.get("enabled"), m.get("off_why")) for m in shown["models"]] == [
        ("gpt-6-luna", False, NO_PREMIUM),
        ("auto", None, None),
        ("fusion", False, f"Copilot says: {NOT_ON_PLAN}"),
    ]
    assert shown["models"][1]["routing"] == "fast"
    # Opened again at once: nothing is asked; the plan meter has both counters.
    assert offers_of_api(client, made["id"])["offers"] == OFFERS and len(asked) == 1
    limits = client.get(f"/api/providers/{made['id']}/limits").json()
    assert [(w["name"], w["limit"], w["remaining"]) for w in limits["windows"]] == [
        (CHAT, 200, 200),
        (PREMIUM, 0, 0),
    ]
    # Ten minutes on, it lists gpt-6-luna again: its row is on again, and the provider is marked
    # changed (a window open on it shows its rows anew).
    limits = client.app.state.providers.limits
    of = account(Provider(kind="copilot_cli"))
    limits._tried[of] -= app.limits.AUTO_EVERY + 1
    limits._listed[of] -= app.limits.AUTO_EVERY + 1
    again = offers_of_api(client, made["id"])
    assert len(asked) == 2 and again["offers"]["models"] == ["gpt-6-luna"]
    assert again["models"][0] == {**shown["models"][0], "enabled": None, "off_why": None}
    assert again["updated_at"] >= shown["updated_at"]  # (Windows' clock: ~15 ms a tick)


def test_a_model_refused_while_it_is_listed_stays_off_after_the_read_it_starts(client, monkeypatch):
    listed = measured(models=[{"id": "gpt-6-luna"}])
    asked = stand_in(monkeypatch, [listed, listed])
    made = client.post(
        "/api/providers",
        headers=ORIGIN,
        json={"name": "Copilot", "kind": "copilot_cli", "models": [{"name": "gpt-6-luna"}]},
    ).json()
    assert offers_of_api(client, made["id"])["models"][0]["enabled"] is None
    limits = client.app.state.providers.limits
    of = account(Provider(kind="copilot_cli"))
    ctx = SimpleNamespace(provider_id=made["id"], model_name="gpt-6-luna")
    refusal = ModelUnavailable("Copilot can't use gpt-6-luna on your account: pick another model")
    assert client.portal.call(client.app.state.runner._refused, ctx, refusal)

    async def read() -> None:  # (the reading it started, unless it is over already)
        if (reading := limits._reading.get(of)) is not None:
            await reading

    client.portal.call(read)  # (asked again at once, though it was asked just now)
    assert len(asked) == 2
    (row,) = offers_of_api(client, made["id"])["models"]
    assert row["enabled"] is False and row["off_why"].startswith("Copilot refused it")
    assert LISTED_REFUSED in row["off_why"]  # (its list is not its word on it: it stays off)


def reads(rows: list[dict], *answers: dict | None) -> list[dict]:
    """`rows` after each of `answers` in turn, as `Limits._offered` switches them."""
    before = None
    for answer in answers:
        if answer is None:  # (a read that failed: nothing kept, nothing switched)
            continue
        rows, before = switched(rows, answer, False, before), answer
    return rows


def read(models: list[str], auto_on: bool | None = None) -> dict:
    tiers = {"tiers": [{"id": "balance", "type": "auto", "status": {"enabled": auto_on}}]}
    told = offers_of(
        {"models": [{"id": m} for m in models], **({} if auto_on is None else {"auto": tiers})}
    )
    assert told is not None
    return told


def test_auto_switched_off_comes_back_on_after_an_answer_that_said_nothing_of_its_tiers():
    # (The review's sequence: auto off, then a list with no "auto" in it, then auto on.)
    rows = reads([{"name": "auto"}], read([], auto_on=False))
    assert rows[0]["enabled"] is False
    assert reads(rows, read([], auto_on=False), read([]), read([], auto_on=True)) == [
        {"name": "auto"}
    ]


def test_a_model_refused_while_listed_stays_off_through_a_flap_one_the_list_switched_does_not():
    refused = {"name": "x", "enabled": False, "off_why": "Copilot refused it" + LISTED_REFUSED}
    unlisted = {"name": "y", "enabled": False, "off_why": NOT_LISTED}
    rows = reads([refused, unlisted], read(["x"]), read([]), read(["x", "y"]))
    assert rows == [refused, {"name": "y"}]


def test_room_elsewhere_is_judged_for_the_model_an_agent_there_would_run(client):
    # Premium used up, chat requests left: auto has room, a named model has not (`at_limit`).
    told = json.loads(json.dumps(MEASURED_QUOTA))
    told["quotaSnapshots"]["premium_interactions"] = counter(300, 300, 0)
    made = client.post(
        "/api/providers",
        headers=ORIGIN,
        json={
            "name": "Copilot",
            "kind": "copilot_cli",
            "for_agents": True,
            "models": [
                {"name": "auto", "tier": "fast"},
                {"name": "gpt-6-luna", "tier": "strongest"},
            ],
        },
    ).json()
    limits = client.app.state.providers.limits
    limits._keep(account(Provider(kind="copilot_cli")), of_copilot(told, datetime.now(UTC)))

    def room() -> list[str]:
        with client.app.state.session_factory() as session:
            found = limits.with_room(session, list_providers(session), None)
        return [entry.name for entry, _why in found]

    # (With no default an agent there runs Copilot's own: not known to be auto, so held back.)
    assert "Copilot" not in room()
    url = f"/api/providers/{made['id']}"
    assert client.patch(url, headers=ORIGIN, json={"default_model": "auto"}).status_code == 200
    assert "Copilot" in room()
    assert (
        client.patch(url, headers=ORIGIN, json={"default_model": "gpt-6-luna"}).status_code == 200
    )
    assert "Copilot" not in room()


def test_a_page_from_before_does_not_make_koloni_s_off_the_user_s(client, monkeypatch):
    stand_in(monkeypatch, [measured(models=[{"id": "gpt-6-luna"}])])
    made = client.post(
        "/api/providers",
        headers=ORIGIN,
        json={
            "name": "Copilot",
            "kind": "copilot_cli",
            "models": [{"name": "gpt-6-luna"}, {"name": "gpt-x", "enabled": False}],
        },
    ).json()
    assert offers_of_api(client, made["id"])["models"][0]["enabled"] is None
    # A page that saw gpt-6-luna switched off by KOLONİ (its why beside it) saves its rows.
    stale = [
        {"name": "gpt-6-luna", "enabled": False, "off_why": NOT_LISTED},
        {"name": "gpt-x", "enabled": False},
    ]
    saved = client.patch(f"/api/providers/{made['id']}", headers=ORIGIN, json={"models": stale})
    assert [m["enabled"] for m in saved.json()["models"]] == [None, False]
    # Switched off by you, with no why of KOLONİ's: off.
    mine = [{"name": "gpt-6-luna", "enabled": False}, {"name": "gpt-x", "enabled": False}]
    saved = client.patch(f"/api/providers/{made['id']}", headers=ORIGIN, json={"models": mine})
    assert [m["enabled"] for m in saved.json()["models"]] == [False, False]


@pytest.mark.anyio
async def test_native_turns_telling_the_quota_do_not_keep_the_list_from_being_read(monkeypatch):
    asked = stand_in(monkeypatch, [measured(), measured()])
    limits = Limits()
    provider = Provider(id="g", name="Copilot", kind="copilot_cli")
    await limits.refresh(provider)
    provider.offers = OFFERS
    of = account(provider)
    limits._listed[of] -= app.limits.AUTO_EVERY + 60  # (its list read 11 minutes ago)
    limits._tried[of] -= app.limits.AUTO_EVERY + 60
    limits.copilot_said(of, MEASURED_QUOTA)  # a native turn's quota, just now
    reading = limits.refresh(provider)
    assert reading is not None
    await reading
    assert len(asked) == 2


def test_a_copilot_on_a_server_of_ones_own_is_never_asked(client, monkeypatch):
    asked = stand_in(monkeypatch, [])
    made = client.post(
        "/api/providers",
        headers=ORIGIN,
        json={
            "name": "Copilot local",
            "kind": "copilot_cli",
            "base_url": "http://localhost:8080/v1",
            "default_model": "qwen-local",
        },
    )
    assert made.status_code == 201, made.text
    assert offers_of_api(client, made.json()["id"])["offers"] is None and asked == []


def test_opening_the_model_panel_or_the_models_page_asks_no_account(client, monkeypatch):
    # F417: what the panel and the page read as they open is what the account offered when last
    # asked - no Copilot is started, and no row is switched by a look. (The plan meter's GET
    # /limits asks it, at most once in 10 minutes: the top bar's, not theirs.)
    asked = stand_in(monkeypatch, [])
    signed = []

    async def signed_in(*args):
        signed.append(args)
        return True

    monkeypatch.setattr(app.limits, "copilot_signed_in", signed_in)
    rows = [{"name": "gpt-6-luna"}, {"name": "auto", "routing": "fast"}]
    made = client.post(
        "/api/providers",
        headers=ORIGIN,
        json={"name": "Copilot", "kind": "copilot_cli", "models": rows},
    ).json()
    pid = made["id"]
    for path in (
        "/api/providers",
        f"/api/providers/{pid}/models",
        f"/api/providers/{pid}/model-facts?model=auto",
        f"/api/providers/{pid}/availability?free=true",
    ):
        assert client.get(path, headers=ORIGIN).status_code == 200, path
    # (Its old door, which asked the account as they opened, is gone.)
    assert client.post(f"/api/providers/{pid}/offers", headers=ORIGIN).status_code in (404, 405)
    listed = next(one for one in client.get("/api/providers").json() if one["id"] == pid)
    assert (asked, signed, listed["models"], listed["offers"]) == ([], [], made["models"], None)


def test_a_fill_and_a_models_list_offer_only_what_the_account_offers(client, monkeypatch):
    stand_in(monkeypatch, [measured()])
    made = client.post(
        "/api/providers", headers=ORIGIN, json={"name": "Copilot", "kind": "copilot_cli"}
    ).json()
    fill = client.post(f"/api/providers/{made['id']}/fill-from-catalogue", headers=ORIGIN).json()
    assert [m["name"] for m in fill["models"]] == ["auto"] and fill["note"] == NONE_LISTED
    listed = client.get(f"/api/providers/{made['id']}/models", headers=ORIGIN).json()
    assert listed == {"models": ["auto"], "note": NONE_LISTED}
    # Not added yet: its account is not known, and GitHub's whole catalogue is not proposed.
    new = client.post(
        "/api/providers/fill-from-catalogue",
        headers=ORIGIN,
        json={"kind": "copilot_cli", "models": [{"name": "auto"}]},
    ).json()
    assert [m["name"] for m in new["models"]] == ["auto"] and new["note"] == ADD_FIRST


@pytest.mark.parametrize("answer", [measured(), ModelUnavailable("Copilot is away")])
def test_fill_tiers_holds_copilot_to_its_account_or_leaves_it_as_it_is(client, monkeypatch, answer):
    stand_in(monkeypatch, [answer])
    rows = [{"name": "gpt-6-luna", "tier": "strongest"}]
    client.post(
        "/api/providers",
        headers=ORIGIN,
        json={"name": "Copilot", "kind": "copilot_cli", "models": rows},
    )
    filled = client.post("/api/providers/fill-all", headers=ORIGIN).json()
    (copilot,) = [p for p in filled["providers"] if p["name"] == "Copilot"]
    names = [m["name"] for m in copilot["models"]]
    if isinstance(answer, dict):  # (its own row kept, as a fill keeps it; auto is what it offers)
        assert copilot["catalogued"] and names == ["gpt-6-luna", "auto"]
    else:  # its account did not say: no GitHub catalogue in its stead
        assert not copilot["catalogued"] and names == ["gpt-6-luna"]


def test_an_account_that_offers_nothing_at_all_is_filled_with_nothing(client, monkeypatch):
    nothing = {**MEASURED_AUTO, "tiers": [{**MEASURED_AUTO["tiers"][1]}]}  # fusion, off
    stand_in(monkeypatch, [measured(auto=nothing)])
    made = client.post(
        "/api/providers", headers=ORIGIN, json={"name": "Copilot", "kind": "copilot_cli"}
    ).json()
    fill = client.post(f"/api/providers/{made['id']}/fill-from-catalogue", headers=ORIGIN).json()
    assert fill["models"] == [] and fill["note"] == NONE_LISTED


# --- after a refusal, it is asked again at once -------------------------------------------------


@pytest.mark.anyio
async def test_a_refused_model_or_routing_has_the_account_asked_again_at_once(monkeypatch):
    asked = stand_in(monkeypatch, [measured(), measured(), measured()])
    limits = Limits()
    provider = Provider(id="g", name="Copilot", kind="copilot_cli", models=[{"name": "gpt-x"}])

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, _kind, _id):
            return provider

        def commit(self):
            pass

    runner = SimpleNamespace(_factory=Session, providers=SimpleNamespace(limits=limits))
    await limits.refresh(provider)
    assert len(asked) == 1  # read just now: a look is not due
    assert limits.refresh(provider) is None
    ctx = SimpleNamespace(provider_id="g", model_name="gpt-x")
    model = ModelUnavailable("Copilot can't use gpt-x on your account: pick another model")
    assert TiersMixin._refused(runner, ctx, model)
    await limits._reading[account(provider)]
    tier = ModelUnavailable(
        f"Copilot refused auto at Fast ({NOT_ON_PLAN.rstrip('.')}): pick another routing"
    )
    assert not TiersMixin._refused(runner, ctx, tier)  # (the row is the routing's: it stays on)
    await limits._reading[account(provider)]
    assert len(asked) == 3


def test_the_account_s_own_fast_reaches_the_session_flag():
    client = CopilotSessionClient(None, "auto", routing="fast")
    assert client._account_arguments()[-2:] == ["--auto-tier", "fast"]
    assert client.capi() == {"capi": {"autoTier": "fast"}}


def test_a_reading_a_day_old_is_read_again_and_one_without_offers_at_once(monkeypatch):
    limits = Limits()
    provider = Provider(id="g", name="Copilot", kind="copilot_cli", offers=None)
    limits._keep(account(provider), of_copilot(MEASURED_QUOTA, datetime.now(UTC)))
    started = []
    monkeypatch.setattr(limits, "_asking", lambda p: started.append(p) or "reading")
    assert limits.refresh(provider) == "reading"  # its list was never kept
    provider.offers = OFFERS
    assert limits.refresh(provider) is None and len(started) == 1
    limits._keep(
        account(provider), of_copilot(MEASURED_QUOTA, datetime.now(UTC) - timedelta(days=1))
    )
    assert limits.refresh(provider) == "reading"
