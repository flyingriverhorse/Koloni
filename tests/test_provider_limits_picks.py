"""Slice 81c, the picks the acceptance set leaves to the implementer: a provider past its limit is
passed over for the next model of its tier, and a subscription past its step-down share gives a
pick one tier lower - each said in `chosen_why` - while the user's own rule is never stepped down.
A plan reading is written as `app.limits` keeps one: no CLI is run."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import LimitReading, Provider
from app.limits import account, plan_used
from app.model_client import ModelUnavailable, OwnStop
from app.providers import looked_down
from tests.fakes import ScriptedModel
from tests.test_agent_writes import wait_status
from tests.test_agents_teams_scenarios import WHY, patch_role, spawn
from tests.test_chat_flow import text
from tests.test_spawn import begin, reported, step
from tests.test_team import NativeStub, pick, team  # noqa: F401  (a fixture)
from tests.test_tier_order_scenarios import both_strongest, picked
from tests.test_tier_scenarios import ORIGIN, role_tier, tiered
from tests.test_triggers import leave, place, run_now, trigger


def reading(client, provider_id, used, resets_in=timedelta(days=2), read=timedelta(0),
            windows=None):
    """What a plan last said `read` ago, kept as `Limits._keep` keeps it: its session 67%
    used, its week `used` (or `windows`, as (name, minutes, used))."""
    resets = resets_in and (datetime.now(UTC) + resets_in).isoformat()
    windows = [{"name": name, "minutes": minutes, "used_percent": percent, "resets_at": resets,
                "stale": False}
               for name, minutes, percent in windows or ((None, 300, 67), (None, 10080, used))]
    with client.app.state.session_factory() as session:
        provider = session.get_one(Provider, provider_id)
        session.merge(LimitReading(
            account=json.dumps(account(provider)), read_at=datetime.now(UTC) - read,
            reading={"source": None, "plan": None, "windows": windows, "credits": None}))
        session.commit()


def test_a_plan_past_its_share_gives_a_pick_one_tier_lower(team, wait_run, project_dir):  # noqa: F811
    client, _default, _fast = team([step(spawn("Coder", "strongest", WHY)), text("done")],
                                   [text("fixed")])
    local, _fast_id = tiered(team, client)  # strongest: Local big-model; balanced: Fast deep
    assert client.patch(f"/api/providers/{local['id']}", json={"step_down_at": 80}).status_code == 200
    reading(client, local["id"], 84)
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    coder = wait_run(client, cid, run_id)["agents"][1]
    assert ("Fast", "deep") in team.asked and ("Local", "big-model") not in team.asked[1:]
    assert coder["tier"] == "balanced"
    assert coder["chosen_why"] == (
        f"{WHY}. Local's weekly plan 84% used: balanced instead of strongest")


def test_the_users_own_rule_and_a_ranges_end_are_never_stepped_down(team):  # noqa: F811
    client, _default, _fast = team([], [])
    _local, fast = tiered(team, client)  # balanced: Fast deep; fast: Fast quick
    assert client.patch(f"/api/providers/{fast}", json={"step_down_at": 80}).status_code == 200
    assert picked(client, "Coder") == ("Fast", "deep", "tier")  # nothing read of its plan yet
    reading(client, fast, 90)
    assert picked(client, "Coder") == ("Fast", "quick", "tier")  # balanced, one lower
    role_tier(client, "Reviewer", "balanced")  # "Always balanced"
    assert picked(client, "Reviewer") == ("Fast", "deep", "tier")
    assert patch_role(client, "Coder", tier_min="balanced").status_code == 200
    assert picked(client, "Coder") == ("Fast", "deep", "tier")
    # under the share, or a window that has reset since it was read: as it was
    reading(client, fast, 79)
    assert picked(client, "Tester") == ("Fast", "deep", "tier")
    reading(client, fast, 90, resets_in=timedelta(days=-1))
    assert picked(client, "Tester") == ("Fast", "deep", "tier")


@pytest.mark.no_po
def test_a_provider_past_its_limit_is_passed_over_for_the_next_of_its_tier(
    team, wait_run, project_dir,  # noqa: F811
):
    client, _default, _fast = team(
        [text("a", 1_000_000, 500_000), step(spawn("Reviewer")), text("done")], [text("looked")])
    local, _fast_id = both_strongest(team, client)  # strongest: Local big-model, then Fast deep
    role_tier(client, "Reviewer", "strongest")
    cid, run_id = begin(client, project_dir)
    wait_run(client, cid, run_id)
    client.put("/api/prices", json={"model_id": "big-model", "input": 3, "output": 15,
                                    "currency": "USD"})
    assert picked(client, "Reviewer") == ("Local", "big-model", "tier")
    assert client.patch(f"/api/providers/{local}", json={"day_limit": 5}).status_code == 200
    assert picked(client, "Reviewer") == ("Fast", "deep", "tier")
    # the Lead itself runs on Local: the turn waits for the user's word, then the pick moves on
    went = client.post(f"/api/conversations/{cid}/messages", headers={"Origin": ORIGIN},
                       json={"content": "check it", "over_budget": True})
    assert went.status_code == 201, went.text
    # Fast is an API key paid per token, Local is not: the move is the user's to say (R173).
    kid = next(a for a in wait_status(client, cid, "waiting_approval")["agents"]
               if a["status"] == "proposed")
    assert client.post(f"/api/agents/{kid['id']}/approve").status_code == 200
    agents = wait_run(client, cid, went.json()["run"]["id"])["agents"]
    reviewer = next(agent for agent in agents if agent["role_name"] == "Reviewer")
    assert reviewer["provider_name"] == "Fast" and team.asked[-1] == ("Fast", "deep")
    assert reviewer["chosen_why"] == (  # (the paid words first: MAX_WHY never cuts them)
        "Fast is paid per token, Local is not: the user says whether it is used. Over Local's "
        "limit of 5.00 USD a day (10.50 spent today): the next strongest model")


def test_an_old_reading_or_a_models_own_week_never_steps_a_plan_down(team):  # noqa: F811
    client, _default, _fast = team([], [])
    _local, fast = tiered(team, client)  # balanced: Fast deep; fast: Fast quick
    assert client.patch(f"/api/providers/{fast}", json={"step_down_at": 80}).status_code == 200
    # read longer ago than its window lasts, with no reset time to make it stale
    reading(client, fast, 90, resets_in=None, read=timedelta(days=8))
    assert picked(client, "Coder") == ("Fast", "deep", "tier")
    reading(client, fast, 90, resets_in=None, read=timedelta(days=6))
    assert picked(client, "Coder") == ("Fast", "quick", "tier")
    # a window of one model's week holds back that model, not every pick on the plan
    reading(client, fast, 0, windows=[("seven_day_opus", None, 95)])
    assert picked(client, "Coder") == ("Fast", "deep", "tier")
    # a window of a name not known: a day at most, said as the plan's
    reading(client, fast, 0, windows=[(None, None, 95)], resets_in=None, read=timedelta(hours=2))
    with client.app.state.session_factory() as session:
        assert plan_used(session, session.get_one(Provider, fast)) == "Fast's plan 95% used"
    reading(client, fast, 0, windows=[(None, None, 95)], resets_in=None, read=timedelta(days=2))
    assert picked(client, "Coder") == ("Fast", "deep", "tier")


# --- K-altajan-saglayici: a provider that fails before its first word ---------------------------


def fails_first(team):  # noqa: F811
    """A Lead on Local that opens a Reviewer; Local's next step (the Reviewer's first) fails."""
    return team([step(spawn("Reviewer")),
                 ModelUnavailable("model server returned 503: busy"), text("done")],
                [text("looked")])


MOVED = ("Reviewer moved from Local to Fast, the next strongest model: model server returned "
         "503: busy.")


@pytest.mark.no_po
def test_a_provider_that_fails_before_its_first_word_gives_the_sub_agent_to_the_tiers_next(
    team, wait_run, project_dir,  # noqa: F811
):
    client, default, fast = fails_first(team)
    both_strongest(team, client)  # strongest: Local big-model, then Fast deep
    role_tier(client, "Reviewer", "strongest")
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    reviewer = wait_run(client, cid, run_id)["agents"][1]
    assert (reviewer["provider_name"], reviewer["model_id"], reviewer["status"],
            reviewer["report"]) == ("Fast", "fast-model", "completed", "looked")
    assert (reviewer["chosen"], reviewer["chosen_why"]) == (False, MOVED)
    assert len(fast.calls) == 1 and "Reviewer sub-agent" in fast.calls[0][0]["content"]
    told = default.calls[-1][-1]["content"]
    assert told.startswith("Reviewer finished.\n\nlooked") and reported(told).endswith(MOVED)


# --- B-396 (live): Copilot's card had a model its CLI refused; every balanced role failed on it -

REFUSED = ('GitHub Copilot CLI exited with code 1: Error: Model "sol" from --model flag is not '
           'available.')
SOL = {"name": "sol", "tier": "strongest"}


def copilot(client, models, name="Copilot", mode="session", stub=None):
    """A Copilot on the GitHub account, its client a stand-in: by default one that refuses sol."""
    made = client.post("/api/providers", headers={"Origin": ORIGIN}, json={
        "name": name, "kind": "copilot_cli", "mode": mode, "for_agents": True, "models": models})
    assert made.status_code == 201, made.text
    client.app.state.providers.named[name] = stub or ScriptedModel([ModelUnavailable(REFUSED)])
    return made.json()["id"]


def model_row(client, provider_id, name):
    provider = next(p for p in client.get("/api/providers").json() if p["id"] == provider_id)
    return next(m for m in provider["models"] if m["name"] == name)


def test_a_model_the_cli_refuses_is_switched_off_with_why_and_the_next_is_taken(
    team, wait_run, project_dir,  # noqa: F811
):
    client, _default, _fast = team([step(spawn("Reviewer")), text("done")], [text("looked")])
    _local, fast = both_strongest(team, client)
    sol_on = copilot(client, [SOL, {"name": "luna", "tier": "fast"}])
    assert patch_role(client, "Reviewer", models=[
        {"provider_id": sol_on, "model_id": "sol"}, {"provider_id": fast, "model_id": "deep"},
    ]).status_code == 200
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    reviewer = wait_run(client, cid, run_id)["agents"][1]
    assert (reviewer["provider_name"], reviewer["status"]) == ("Fast", "completed")
    row = model_row(client, sol_on, "sol")
    assert (row["enabled"], row["off_why"]) == (
        False, "Copilot refused it: not available on your account")
    assert picked(client, "Reviewer")[:2] == ("Fast", "deep")  # not tried again
    # a save of the list keeps why while it stays off; the user's On takes it away
    luna = {"name": "luna", "tier": "fast"}
    client.patch(f"/api/providers/{sol_on}", json={"models": [SOL, luna]})
    assert model_row(client, sol_on, "sol")["off_why"] is not None
    client.patch(f"/api/providers/{sol_on}", json={"models": [{**SOL, "enabled": True}, luna]})
    row = model_row(client, sol_on, "sol")
    assert (row["enabled"], row["off_why"]) == (None, None)
    assert picked(client, "Reviewer")[:2] == ("Copilot", "sol")


def test_the_move_after_a_refusal_never_lands_on_a_pick_held_to_full_auto(
    team, wait_run, project_dir,  # noqa: F811
):
    client, _default, _fast = team([step(spawn("Coder")), text("done")], [text("fixed")])
    _local, fast = both_strongest(team, client)
    held = NativeStub()  # (Copilot at work with its own tools: Full auto only)
    native = copilot(client, [{"name": "x", "tier": "strongest"}], name="Copilot app",
                     mode="native", stub=held)
    sol_on = copilot(client, [SOL])
    assert patch_role(client, "Coder", models=[
        {"provider_id": native, "model_id": "x"}, {"provider_id": sol_on, "model_id": "sol"},
        {"provider_id": fast, "model_id": "deep"}]).status_code == 200
    cid, run_id = begin(client, project_dir, spawn_approval="never")  # (Ask, not Full auto)
    coder = wait_run(client, cid, run_id)["agents"][1]
    assert (coder["provider_name"], coder["status"], held.started) == ("Fast", "completed", 0)
    # (the one model of its list: said so)
    assert model_row(client, sol_on, "sol")["off_why"] == (
        "Copilot refused it: not available on your account - it was this provider's only "
        "model, so no tier uses it now")


LIVE = "Copilot can't use gpt-6.1-sol on your account: pick another model"


class Refusing(NativeStub):
    """Copilot at work with its own tools that refuses its model at session.create, as
    `CopilotNativeClient` says it (an OwnStop) - `said` before it where a step's words wrap it."""

    def __init__(self, said=""):
        super().__init__(asks=True)
        self.said = said

    async def run_native(self, *args, **more):
        self.started += 1
        raise OwnStop(self.said + LIVE)


@pytest.mark.parametrize("before", ["", "GitHub Copilot CLI reported an error: "])
def test_a_native_copilot_sub_agent_refused_its_model_switches_it_off_and_moves_on(
    team, wait_run, project_dir, before,  # noqa: F811
):
    """B-396 (R194, live): a Coder on native Copilot's gpt-6.1-sol, its tier's first, failed
    with the words above, but the model stayed on and the tier did not move on."""
    client, _default, _fast = team([step(spawn("Coder")), text("done")], [text("fixed")])
    client.headers["Origin"] = ORIGIN
    fast = team.providers["Fast"]["id"]
    assert client.patch(f"/api/providers/{fast}", json={"models": [
        {"name": "deep", "tier": "strongest"}]}).status_code == 200
    refusing = Refusing(before)
    native = copilot(client, [{"name": "gpt-6.1-sol", "tier": "strongest"}, {"name": "luna"}],
                     mode="native", stub=refusing)
    assert client.put("/api/tiers", json={"strongest": [
        {"provider_id": native, "model": "gpt-6.1-sol"}, {"provider_id": fast, "model": "deep"}],
        "balanced": [], "fast": []}).status_code == 200
    role_tier(client, "Coder", "strongest")
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    coder = wait_run(client, cid, run_id)["agents"][1]
    assert refusing.started == 1
    assert (coder["provider_name"], coder["status"]) == ("Fast", "completed")
    assert coder["chosen_why"] == (
        f"Coder moved from Copilot to Fast, the next strongest model: {before}{LIVE}.")
    row = model_row(client, native, "gpt-6.1-sol")
    assert (row["enabled"], row["off_why"]) == (
        False, "Copilot refused it: not available on your account")


def test_a_move_after_a_refusal_onto_a_paid_provider_is_the_users_to_say(
    team, wait_run, project_dir,  # noqa: F811
):
    client, _default, _fast = team([step(spawn("Reviewer")), text("done")], [text("looked")])
    client.headers["Origin"] = ORIGIN
    fast = team.providers["Fast"]["id"]
    assert client.patch(f"/api/providers/{fast}", json={"models": [
        {"name": "deep", "tier": "strongest"}]}).status_code == 200
    sol_on = copilot(client, [SOL])
    assert client.put("/api/tiers", json={"strongest": [
        {"provider_id": sol_on, "model": "sol"}, {"provider_id": fast, "model": "deep"}],
        "balanced": [], "fast": []}).status_code == 200
    role_tier(client, "Reviewer", "strongest")
    cid, run_id = begin(client, project_dir)
    kid = next(a for a in wait_status(client, cid, "waiting_approval")["agents"]
               if a["status"] == "proposed")
    assert kid["provider_name"] == "Fast"  # (the card: not moved onto a paid one unasked)
    runner = client.app.state.runner
    assert runner._paid_asked[kid["id"]] == ((run_id, fast), False)  # (asked as the paid move)
    assert client.post(f"/api/agents/{kid['id']}/approve").status_code == 200
    reviewer = wait_run(client, cid, run_id)["agents"][1]
    assert (reviewer["provider_name"], reviewer["status"]) == ("Fast", "completed")


def test_with_nobody_after_it_on_the_ladder_or_a_provider_of_its_own_it_fails_as_before(
    team, wait_run, project_dir,  # noqa: F811
):
    client, default, _fast = fails_first(team)
    tiered(team, client)  # strongest: Local big-model alone
    role_tier(client, "Reviewer", "strongest")
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    reviewer = wait_run(client, cid, run_id)["agents"][1]
    assert (reviewer["provider_name"], reviewer["status"], reviewer["chosen_why"]) == (
        "Local", "failed", None)
    told = default.calls[-1][-1]["content"]
    assert told.startswith("Reviewer failed: model server returned 503: busy") and (
        "moved" not in told) and "Why it failed: other." in told
    # The user's own rule - the role's provider - is never moved, a next of the tier or not.
    client, default, _fast = fails_first(team)
    local_id, _fast_id = both_strongest(team, client)
    assert patch_role(client, "Reviewer", provider_id=local_id,
                      model_id="big-model").status_code == 200
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    reviewer = wait_run(client, cid, run_id)["agents"][1]
    assert (reviewer["provider_name"], reviewer["status"]) == ("Local", "failed")
    assert "moved" not in default.calls[-1][-1]["content"]


def test_a_move_may_cost_money_and_is_asked_about_on_the_cards_as_a_pick_is(
    team, wait_run, project_dir,  # noqa: F811
):
    client, default, _fast = fails_first(team)
    both_strongest(team, client)
    role_tier(client, "Reviewer", "strongest")
    # Full auto with "auto": the opening itself asks nothing; the move does.
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="auto")
    kid = wait_status(client, cid, "waiting_approval")["agents"][1]
    assert (kid["status"], kid["provider_name"], kid["model_id"], kid["chosen_why"]) == (
        "proposed", "Fast", "deep", MOVED)  # (the card: the model asked for; run, its own name)
    assert client.post(f"/api/agents/{kid['id']}/approve").status_code == 200
    reviewer = wait_run(client, cid, run_id)["agents"][1]
    assert (reviewer["provider_name"], reviewer["status"]) == ("Fast", "completed")
    # A no leaves it as it failed, on the provider it failed on.
    client, default, _fast = fails_first(team)
    both_strongest(team, client)
    role_tier(client, "Reviewer", "strongest")
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="auto")
    kid = wait_status(client, cid, "waiting_approval")["agents"][1]
    assert client.post(f"/api/agents/{kid['id']}/reject").status_code == 200
    reviewer = wait_run(client, cid, run_id)["agents"][1]
    assert (reviewer["provider_name"], reviewer["model_id"], reviewer["status"],
            reviewer["chosen_why"]) == ("Local", "big-model", "failed", None)
    assert "Reviewer failed: model server returned 503: busy" in default.calls[-1][-1]["content"]


def gold_too(team, client):  # noqa: F811
    """Paid Api · gold is strongest too, third after Local and Fast, and answers once."""
    paid = team.providers["Paid Api"]["id"]
    assert client.patch(f"/api/providers/{paid}", json={
        "for_agents": True, "models": [{"name": "gold", "tier": "strongest"}]}).status_code == 200
    team.stubs["Paid Api"].steps.append(text("looked by gold"))


def test_a_next_that_was_not_answering_when_last_looked_at_is_passed_over_for_the_one_after(
    team, wait_run, project_dir,  # noqa: F811
):
    client, _default, fast = fails_first(team)
    _local, fast_id = both_strongest(team, client)
    gold_too(team, client)
    role_tier(client, "Reviewer", "strongest")
    with client.app.state.session_factory() as session:
        looked_down(session)[fast_id] = ("not answering", None)
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    reviewer = wait_run(client, cid, run_id)["agents"][1]
    assert (reviewer["provider_name"], reviewer["status"], reviewer["report"]) == (
        "Paid Api", "completed", "looked by gold")
    assert reviewer["chosen_why"].startswith("Reviewer moved from Local to Paid Api, the next")
    assert fast.calls == []


def test_an_openers_pick_and_a_turn_nobody_watches_are_not_moved(
    team, wait_run, project_dir,  # noqa: F811
):
    # The opener's pick, with a reason of its own: Fast fails, and Paid Api after it is not taken.
    client, default, _fast = team(
        [step(pick("Reviewer", "Fast", "deep", why=WHY)), text("done")],
        [ModelUnavailable("model server returned 503: busy")])
    both_strongest(team, client)
    gold_too(team, client)
    role_tier(client, "Reviewer", "strongest")
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    reviewer = wait_run(client, cid, run_id)["agents"][1]
    assert (reviewer["provider_name"], reviewer["status"], reviewer["chosen"]) == (
        "Fast", "failed", True)
    assert "moved" not in default.calls[-1][-1]["content"]
    # A trigger's turn: nobody is there to be asked, and no model is picked.
    client, default, _fast = fails_first(team)
    both_strongest(team, client)
    role_tier(client, "Reviewer", "strongest")
    pid, cid = place(client, project_dir, permission_mode="full_auto")
    run_id = run_now(client, trigger(client, pid, cid, permissions=leave(agents=2))["id"])
    reviewer = wait_run(client, cid, run_id)["agents"][1]
    assert (reviewer["provider_name"], reviewer["status"]) == ("Local", "failed")
    assert "moved" not in default.calls[-1][-1]["content"]


@pytest.mark.no_po
def test_the_move_passes_over_what_another_account_rule_holds_back(
    team, wait_run, project_dir, monkeypatch,  # noqa: F811
):
    # K-claude-hesap: the ladder asks `another_account` of each next model, with why the failed
    # one failed (its rule - same CLI, a limit - is `test_limits`'s); one it holds back is passed.
    import app.agent

    asked = []

    def another(failed, other, failure):
        asked.append((failed.name, other.name, failure))
        return other.name == "Fast"

    monkeypatch.setattr(app.agent.spawn_mixin, "another_account", another)
    client, _default, fast = fails_first(team)
    both_strongest(team, client)
    gold_too(team, client)
    role_tier(client, "Reviewer", "strongest")
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    reviewer = wait_run(client, cid, run_id)["agents"][1]
    assert (reviewer["provider_name"], reviewer["status"]) == ("Paid Api", "completed")
    assert ("Local", "Fast", "other") in asked and fast.calls == []
