"""Whom KOLONİ's judges ask (`team.judge_pick`): the user's Judge model where it may be asked now -
of any tier, answering with no tools -, else the Fast tier's first; and K-yargıç's request to a
CLI waits as long as Full auto's judge's does."""

import asyncio
from dataclasses import replace

import pytest

from app import risk_judge
from app.agent.tiers_mixin import TiersMixin
from app.roles import LEAD, find_role
from app.team import judge_choices, judge_pick, would_run
from tests.keyed import OWN
from tests.test_agent_commands import cmd
from tests.test_chat_flow import text
from tests.test_judge_scenarios import RULE, begin, carded, judging, verdict_line  # noqa: F401
from tests.test_team import ADDRESS, SECRET


def provider(client, name, models):
    made = client.post(
        "/api/providers",
        headers=OWN,
        json={
            "name": name,
            "kind": "openai_compat",
            "base_url": ADDRESS,
            "api_key": SECRET,
            "for_agents": True,
            "default_model": models[0]["name"],
            "models": models,
        },
    )
    assert made.status_code == 201, made.text
    return made.json()


@pytest.fixture
def two(client):
    """A Fast provider (quick, fast) and a Big one (deep, balanced; plain, no tier)."""
    provider(client, "Fast", [{"name": "quick", "tier": "fast"}])
    big = provider(client, "Big", [{"name": "deep", "tier": "balanced"}, {"name": "plain"}])
    return client, big


def pick(client, chosen, **changed):
    with client.app.state.session_factory() as session:
        would = replace(would_run(session, find_role(session, LEAD), None), **changed)
        found = judge_pick(session, would, client.app.state.providers, chosen)
        return found and (found[0].name, found[1])


def test_the_fast_tiers_first_unless_the_user_chose(two):
    client, big = two
    assert pick(client, None) == ("Fast", "quick")
    assert pick(client, (big["id"], "deep")) == ("Big", "deep")
    # (one of no tier, or of no provider, is no choice: the Fast tier's first)
    assert pick(client, (big["id"], "plain")) == ("Fast", "quick")
    assert pick(client, ("gone", "deep")) == ("Fast", "quick")
    with client.app.state.session_factory() as session:
        would = would_run(session, find_role(session, LEAD), None)
        assert [
            (one.name, name, tier)
            for one, name, tier in judge_choices(session, would, client.app.state.providers)
        ] == [("Fast", "quick", "fast"), ("Big", "deep", "balanced")]


def test_a_chosen_model_its_provider_down_closed_or_gone_is_the_fast_tiers_first(two):
    # Review Focus 5
    client, big = two
    chosen = (big["id"], "deep")
    assert pick(client, chosen, down={"Big": "not answering"}) == ("Fast", "quick")
    closed = client.patch(f"/api/providers/{big['id']}", json={"for_agents": False}, headers=OWN)
    assert closed.status_code == 200, closed.text
    assert pick(client, chosen) == ("Fast", "quick")
    assert client.delete(f"/api/providers/{big['id']}", headers=OWN).status_code == 204
    assert pick(client, chosen) == ("Fast", "quick")


def test_nobody_to_ask_with_no_tier(client):
    assert pick(client, None) is None


@pytest.mark.no_po
@pytest.mark.parametrize("cli", [False, True])
def test_the_check_of_the_users_words_waits_longer_for_a_cli(
    judging, wait_run, project_dir, monkeypatch, cli
):
    seen, timeout = [], asyncio.timeout

    def spy(seconds):
        seen.append(seconds)
        return timeout(seconds)

    on = TiersMixin._on

    def as_cli(self, session, ctx, entry, model):
        asking, mode = on(self, session, ctx, entry, model)
        return asking, ("native" if cli and entry.name == "Fast" else mode)

    monkeypatch.setattr(TiersMixin, "_on", as_cli)
    monkeypatch.setattr(asyncio, "timeout", spy)
    client, *_ = judging(
        [cmd("rm -rf build"), text("left it")], [verdict_line("ask", why="No line.")], []
    )
    _, cid, run_id = begin(client, project_dir, "tidy up", rules=RULE)
    carded(client, cid, run_id, wait_run)
    assert (risk_judge.CLI_SECONDS if cli else 30.0) in seen
