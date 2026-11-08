"""Slice 60d beyond its acceptance set: the proposal keeps a tick the user gave and "Only these
models", a save is all or nothing and leaves alone what it does not change, the catalogue the page
names is the one read, the dots' reading starts nothing, and the Lead is told which notes are the
catalogue's."""

import pytest

from app import models_dev
from app.api import providers as api
from app.db.models import Provider
from app.team import describe, guide

ORIGIN = {"Origin": "http://127.0.0.1:8790"}


@pytest.fixture
def quiet(monkeypatch):
    async def nothing_listed(provider, providers):
        return [], None, False

    monkeypatch.setattr(api, "_own_list", nothing_listed)
    # Whether a CLI's command is on this machine: as the test says, not as this machine has it.
    monkeypatch.setattr(api.catalog, "installed", lambda kind, executable: executable != "gone")

    # And whether it is signed in: no CLI is started; "out" is one signed out.
    async def signed_in(kind, executable, home=None):
        return False if executable == "out" else None

    monkeypatch.setattr(api.catalog, "signed_in", signed_in)


def add(client, **body):
    made = client.post("/api/providers", headers=ORIGIN, json=body)
    assert made.status_code == 201, made.text
    return made.json()


def proposed(client):
    told = client.post("/api/providers/fill-all", headers=ORIGIN)
    assert told.status_code == 200, told.text
    return {p["name"]: p for p in told.json()["providers"]}


def save(client, providers):
    return client.post("/api/providers/fill-all/save", headers=ORIGIN,
                       json={"providers": providers})


def test_a_tick_the_user_gave_is_kept_and_a_save_is_all_or_nothing(client, quiet):
    add(client, name="Paid", kind="anthropic", api_key="sk-test", for_agents=True)
    add(client, name="Claude Code", kind="claude_cli")
    told = list(proposed(client).values())
    assert next(p for p in told if p["name"] == "Paid")["for_agents"] is True
    before = client.get("/api/providers").json()
    # One bad provider last in the lot: nothing of those before it is saved either.
    gone = {"id": "no-such", "for_agents": True, "models": []}
    assert save(client, [*told, gone]).status_code == 404
    twice = [*told[:-1], {**told[-1], "models": [{"name": "a"}, {"name": "a"}]}]
    assert save(client, twice).status_code == 422
    assert save(client, [*told, told[0]]).status_code == 422  # a provider twice
    assert client.get("/api/providers").json() == before


def test_a_cli_not_on_this_machine_comes_unticked(client, quiet):
    add(client, name="Codex", kind="codex_cli", executable="gone")
    add(client, name="Claude Code", kind="claude_cli")
    told = proposed(client)
    assert (told["Codex"]["for_agents"], told["Claude Code"]["for_agents"]) == (False, True)
    assert told["Codex"]["catalogued"] and not told["Local"]["catalogued"]


def test_a_cli_signed_out_comes_unticked_and_one_not_known_ticked(client, quiet):
    # Paid by the plan only once signed in: one that says it is not is no agent's to choose.
    add(client, name="Codex", kind="codex_cli", executable="out")
    add(client, name="Qoder", kind="qoder_cli")  # (it says nothing of its sign-in)
    told = proposed(client)
    assert (told["Codex"]["for_agents"], told["Qoder"]["for_agents"]) == (False, True)


def test_a_cli_already_ticked_is_not_asked_whether_it_is_signed_in(client, quiet, monkeypatch):
    async def never(kind, executable):
        raise AssertionError("asked the CLI")

    add(client, name="Claude Code", kind="claude_cli", for_agents=True)
    monkeypatch.setattr(api.catalog, "signed_in", never)
    assert proposed(client)["Claude Code"]["for_agents"] is True


def test_only_these_models_stays_only_these(client, quiet):
    add(client, name="Claude Code", kind="claude_cli", only_listed=True, default_model="haiku",
        models=[{"name": "haiku", "note": "mine"}, {"name": "opus"}])
    rows = proposed(client)["Claude Code"]["models"]
    assert [(m["name"], m["tier"], m["note"]) for m in rows] == [
        ("haiku", "fast", "mine"),
        ("opus", "strongest", "Among its strongest: for the hardest and longest work"),
    ]


def test_a_provider_left_as_it_was_is_not_touched(client, quiet):
    add(client, name="Claude Code", kind="claude_cli")
    before = {p["name"]: p for p in client.get("/api/providers").json()}
    assert save(client, list(proposed(client).values())).status_code == 200
    after = {p["name"]: p for p in client.get("/api/providers").json()}
    assert after["Local"]["updated_at"] == before["Local"]["updated_at"]  # no catalogue: as it was
    assert after["Claude Code"]["updated_at"] != before["Claude Code"]["updated_at"]


def test_a_tiers_order_is_kept_by_a_save_that_changes_nothing(client, quiet):
    a = add(client, name="A", kind="claude_cli", models=[{"name": "x", "tier": "fast"}])
    b = add(client, name="B", kind="claude_cli", models=[{"name": "y", "tier": "fast"}])
    turned = [{"provider_id": b["id"], "model": "y"}, {"provider_id": a["id"], "model": "x"}]
    assert client.put("/api/tiers", headers=ORIGIN, json={
        "strongest": [], "balanced": [], "fast": turned}).status_code == 200
    before = {p["name"]: p for p in client.get("/api/providers").json()}
    same = [{"id": p["id"], "for_agents": p["for_agents"], "models": p["models"]}
            for p in before.values()]
    assert save(client, same).status_code == 200
    after = {p["name"]: p for p in client.get("/api/providers").json()}
    assert after["A"]["updated_at"] == before["A"]["updated_at"]
    assert [m["model"] for m in client.get("/api/tiers").json()["fast"]] == ["y", "x"]


def test_the_free_reading_starts_nothing(client, monkeypatch):
    claude = add(client, name="Claude Code", kind="claude_cli", executable="gone-for-the-test")

    async def never(*args):
        raise AssertionError("asked the CLI")

    monkeypatch.setattr(api.catalog, "signed_in", never)
    told = client.get(f"/api/providers/{claude['id']}/availability?free=true", headers=ORIGIN)
    assert told.status_code == 200, told.text
    assert (told.json()["installed"], told.json()["models"]) == (False, [])


def test_the_users_own_catalogue_is_read_after_koloni_s_and_a_broken_one_is_said(
        client, quiet, monkeypatch, tmp_path):
    import json

    from app import catalog

    own = tmp_path / "catalog.local.json"
    monkeypatch.setattr(catalog, "LOCAL", own)
    own.write_text(json.dumps({
        # By the provider's name in KOLONİ first, then by its catalogue's.
        "providers": {"Local": [{"name": "qwen-own", "tier": "balanced"}]},
        "models": {"claude_cli": [{"name": "opus", "tier": "balanced", "note": "mine"}]},
    }), encoding="utf-8")
    add(client, name="Claude Code", kind="claude_cli")
    told = proposed(client)
    # A server with no catalogue has one now: the user's.
    assert told["Local"]["catalogued"]
    assert [(m["name"], m["tier"]) for m in told["Local"]["models"]] == [("qwen-own", "balanced")]
    opus = next(m for m in told["Claude Code"]["models"] if m["name"] == "opus")
    assert (opus["tier"], opus["note"]) == ("balanced", "mine")  # the user's wins
    assert client.get("/api/catalog").json()["local"] is None
    # A broken one is not read, and the page is told why; nothing else stops.
    own.write_text('{"providers": [', encoding="utf-8")
    told = proposed(client)
    assert not told["Local"]["catalogued"]
    assert "catalog.local.json" in client.get("/api/catalog").json()["local"]
    own.write_text(json.dumps({"models": {"claude_cli": [{"name": "opus", "tier": "best"}]}}),
                   encoding="utf-8")
    assert "tier" in client.get("/api/catalog").json()["local"]
    own.write_text(json.dumps({"models": {"claude_cli": [{"name": "opus", "note": "x" * 121}]}}),
                   encoding="utf-8")
    assert "characters" in client.get("/api/catalog").json()["local"]
    # One that cannot be read is named, never by where it is.
    monkeypatch.setattr(catalog, "LOCAL", tmp_path)
    said = client.get("/api/catalog").json()["local"]
    assert said.startswith("catalog.local.json is not read") and str(tmp_path) not in said


def test_the_catalogue_named_is_the_copy_read(client, monkeypatch):
    shipped = client.get("/api/catalog").json()
    assert shipped["updated_at"] == models_dev.read_on(models_dev.load(None))
    assert shipped["providers"] >= 1 and shipped["models"] >= 1

    async def download():  # the shipped list again, as if from models.dev
        return models_dev.SHIPPED.read_bytes()

    monkeypatch.setattr(models_dev, "download", download)
    done = client.post("/api/catalog/update", headers=ORIGIN).json()
    assert client.get("/api/catalog").json() == done
    assert done["updated_at"] != shipped["updated_at"] and done["models"] == shipped["models"]


def row(**fields):
    return Provider(**{"id": "p", "name": "Claude Code", "kind": "claude_cli",
                       "for_agents": True, "only_listed": False, **fields})


FAST = "Fast and cheap: for simple, high-volume work"


def test_the_lead_is_told_the_catalogues_note_where_the_user_wrote_none():
    strongest = "Among its strongest: for the hardest and longest work"
    said = describe(guide([row(models=[
        {"name": "opus", "note": None, "tier": "strongest"},     # none of the user's
        {"name": "sonnet", "note": "mine", "tier": "balanced"},  # the user's wins
        {"name": "haiku", "note": FAST, "tier": "fast"},         # copied by a fill
        {"name": "fable", "note": FAST, "tier": "balanced"},     # copied, then re-tiered
        {"name": "not-catalogued", "note": None, "tier": None},
    ])]))
    head, line = said.splitlines()
    assert head.endswith("the notes are the user's, unless marked as the catalogue's):")
    # (the shipped catalogue says these take images, and Claude Code is given them: 85c)
    assert (f'"opus" (strongest tier; sees images; the catalogue\'s note (2026-10-16): "{strongest}")'
            in line)
    assert '"sonnet" (balanced tier; sees images; "mine")' in line
    assert f'"haiku" (fast tier; sees images; the catalogue\'s note (2026-10-16): "{FAST}")' in line
    # A re-tiered row is told the note of the tier it has now, never an old tier's.
    assert ('"fable" (balanced tier; sees images; the catalogue\'s note (2026-10-16): "Strength and speed '
            'balanced: for everyday work")') in line
    assert '"not-catalogued",' in line or '"not-catalogued".' in line
