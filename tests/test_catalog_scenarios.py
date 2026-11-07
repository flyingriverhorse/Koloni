"""Slice 40's acceptance set: a catalogue of the providers' models fills the team guide.
Written before the code.

The app ships a catalogue: for each kind of provider, the models it is known to take, each with
how strong it is among them, what it is for, and where that was read. "Fill from catalogue"
proposes a team guide for a provider - the user's own words kept, nothing of theirs dropped,
never past the list's limit - and saves nothing until the user does. Beside every model is
whether it can be used now, cannot (and why), or is not known; a CLI that is not installed, or
not signed in, says how to install it or sign in. What a CLI's status command says of the
account is never passed on.
"""

import importlib.util
import json
import sys

import pytest

if importlib.util.find_spec("app.catalog") is None:
    pytest.skip("slice 40 is not built yet", allow_module_level=True)  # written before the code

from app import catalog  # noqa: E402
from app.providers import MAX_MODELS, TIERS, check_guide  # noqa: E402

ORIGIN = "http://127.0.0.1:8790"
CATALOGUED = ("claude_cli", "anthropic", "codex_cli", "copilot_cli", "agy_cli", "qoder_cli")


def add(client, kind, **body):
    made = client.post("/api/providers", json={"name": f"P {kind}", "kind": kind, **body},
                       headers={"Origin": ORIGIN})
    assert made.status_code == 201, made.text
    return made.json()


def proposed(client, provider):
    answer = client.post(f"/api/providers/{provider['id']}/fill-from-catalogue",
                         headers={"Origin": ORIGIN})
    assert answer.status_code == 200, answer.text
    return answer.json()


def missing(tmp_path):
    return str(tmp_path / "not-installed" / "cli.exe")


# --- the catalogue itself ----------------------------------------------------------------------


@pytest.mark.parametrize("kind", CATALOGUED)
def test_every_entry_has_a_name_a_tier_and_a_source(kind):
    entries = catalog.models_for(kind)
    assert entries, f"no models catalogued for {kind}"
    names = [entry["name"] for entry in entries]
    assert len(names) == len(set(names)), names
    for entry in entries:
        assert entry["name"].strip() == entry["name"] and entry["name"]
        assert entry["tier"] in (None, *TIERS)
        # (a page read, or the command whose list was measured: `qodercli --list-models`; or
        # the run that measured a CLI's own name: `copilot -p --model auto`)
        assert entry["source"]["url"].startswith("https://") or entry["source"]["url"].endswith(
            (" --list-models", f" --model {entry['name']}")), entry
        assert entry["source"]["read_on"], entry           # the date it was read
        assert entry.get("note") is None or len(entry["note"]) <= 120


def test_a_server_of_ones_own_has_no_catalogue():
    assert catalog.models_for("openai_compat") == []


# --- fill from catalogue -----------------------------------------------------------------------


def test_fill_proposes_the_catalogue_and_saves_nothing(client, tmp_path):
    provider = add(client, "codex_cli", executable=missing(tmp_path))
    offer = proposed(client, provider)
    names = [model["name"] for model in offer["models"]]
    assert names and set(names) <= {e["name"] for e in catalog.models_for("codex_cli")}
    # what is proposed would be accepted as it stands
    check_guide(None, offer["models"])
    # nothing is saved until the user saves it
    again = next(p for p in client.get("/api/providers").json() if p["id"] == provider["id"])
    assert again["models"] == []


def test_fill_keeps_the_users_words_and_the_users_models(client, tmp_path):
    known = catalog.models_for("claude_cli")[0]
    provider = add(client, "claude_cli", executable=missing(tmp_path), models=[
        {"name": known["name"], "note": "mine, for reviews", "tier": "fast"},
        {"name": "my-own-model", "note": "kept", "tier": None},
        {"name": catalog.models_for("claude_cli")[-1]["name"], "note": None, "tier": None},
    ])
    offer = {m["name"]: m for m in proposed(client, provider)["models"]}
    assert offer[known["name"]]["note"] == "mine, for reviews"      # never overwritten
    assert offer[known["name"]]["tier"] == "fast"
    assert offer["my-own-model"]["note"] == "kept"                  # never dropped
    last = catalog.models_for("claude_cli")[-1]
    assert offer[last["name"]]["tier"] == last["tier"]              # a blank one is filled
    assert offer[last["name"]]["note"] == last.get("note")


def test_fill_never_goes_past_the_lists_limit_and_says_so(client, tmp_path, monkeypatch):
    many = [{"name": f"m{i}", "tier": TIERS[i % 3], "note": None,
             "source": {"url": "https://example.com/models", "read_on": "2026-10-16"}}
            for i in range(MAX_MODELS + 5)]
    monkeypatch.setattr(catalog, "models_for", lambda kind, copy=None, provider=None: many)
    provider = add(client, "codex_cli", executable=missing(tmp_path))
    offer = proposed(client, provider)
    assert len(offer["models"]) == MAX_MODELS
    # the strongest are kept first, and the user is told what was left out
    kept = [m["tier"] for m in offer["models"]]
    assert kept == sorted(kept, key=lambda t: {"strongest": 0, "balanced": 1, "fast": 2}[t])
    assert offer["left_out"] == 5


def test_fill_is_the_users_from_the_apps_own_page(client, tmp_path):
    provider = add(client, "codex_cli", executable=missing(tmp_path))
    answer = client.post(f"/api/providers/{provider['id']}/fill-from-catalogue")
    assert answer.status_code == 403


# --- usable, not, or not known -----------------------------------------------------------------


def availability(client, provider):
    answer = client.get(f"/api/providers/{provider['id']}/availability")
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_a_cli_that_is_not_installed_says_how_to_install_it(client, tmp_path):
    provider = add(client, "codex_cli", executable=missing(tmp_path))
    told = availability(client, provider)
    assert told["installed"] is False
    assert told["install"]["command"] and told["install"]["docs"].startswith("https://")
    assert told["models"] and all(m["state"] == "unusable" for m in told["models"])
    assert all("not installed" in m["why"] for m in told["models"])


def test_an_anthropic_provider_without_a_key_cannot_be_used_yet(client):
    provider = add(client, "anthropic")
    told = availability(client, provider)
    assert told["models"] and all(m["state"] == "unusable" for m in told["models"])
    assert all("API key" in m["why"] for m in told["models"])


def test_a_cli_that_lists_nothing_is_not_known_rather_than_usable(client):
    # installed (the command is there), but it does not list its models
    provider = add(client, "codex_cli", executable=sys.executable)
    told = availability(client, provider)
    assert told["installed"] is True
    assert {m["state"] for m in told["models"]} <= {"unknown", "unusable"}
    assert "usable" not in {m["state"] for m in told["models"]}


def test_a_key_never_shows_in_what_is_told(client, monkeypatch):
    from app.api import providers as api

    async def nothing_listed(provider, providers):  # no request leaves the machine in a test
        return [], f"refused with {provider.api_key}", False

    monkeypatch.setattr(api, "_own_list", nothing_listed)
    secret = "sk-ant-test-DO-NOT-LEAK-40"
    provider = add(client, "anthropic", api_key=secret)
    told = client.get(f"/api/providers/{provider['id']}/availability")
    assert secret not in told.text


# --- signed in or not, and nothing of the account --------------------------------------------


@pytest.mark.parametrize("code,said,expected", [
    (0, "Logged in using ChatGPT (acct_9f8e7d6c, someone@example.com)", True),
    (1, "Not logged in", False),
])
def test_the_status_command_tells_only_signed_in_or_not(code, said, expected):
    told = catalog.signed_in_from("codex_cli", code, said)
    assert told is expected
    assert "acct_" not in json.dumps(told) and "@" not in json.dumps(told)


def test_a_status_it_cannot_read_is_not_known():
    assert catalog.signed_in_from("copilot_cli", 0, "something it never said before") is None
