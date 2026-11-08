"""Slice 85b §0b: what a model takes besides text - kept from models.dev, marked by the user,
learned by sending one - and said to the Lead in words."""

import json
from types import SimpleNamespace

import pytest

from app import catalog, models_dev, team
from app.providers import check_guide

ORIGIN = {"Origin": "http://127.0.0.1:8790"}


def copy(**models):
    return {"acme": {"id": "acme", "name": "Acme", "api": "https://api.acme.test", "env": [],
                     "doc": None, "models": models}}


def provider(**more):
    return SimpleNamespace(**{"kind": "openai_compat", "base_url": "https://api.acme.test/v1",
                              "name": "Acme", "models": None, "tried_inputs": None, **more})


def test_models_dev_modalities_are_kept_only_as_its_readme_names_them():
    kept = models_dev.clean(copy(m={"modalities": {
        "input": ["text", "image", "smell", 3], "output": ["text"], "other": ["x"]}}))
    assert kept["acme"]["models"]["m"]["modalities"] == {"input": ["text", "image"],
                                                         "output": ["text"]}


def test_who_said_it_the_later_over_the_earlier_and_unknown_stays_unknown(tmp_path, monkeypatch):
    dev = copy(m={"modalities": {"input": ["text", "image"]}}, plain={})
    assert catalog.inputs(provider(), "plain", dev) == {}  # nobody said: nothing is guessed
    said = catalog.inputs(provider(), "m", dev)
    assert said["image"] == (True, "models.dev") and said["video"] == (False, "models.dev")
    local = tmp_path / "catalog.local.json"
    local.write_text(json.dumps({"providers": {"Acme": [{"name": "m", "inputs": ["video"]}]}}))
    monkeypatch.setattr(catalog, "LOCAL", local)
    marked = catalog.inputs(provider(), "m", dev)
    assert marked["image"] == (False, "you") and marked["video"] == (True, "you")
    row = provider(models=[{"name": "m", "inputs": ["image", "video"]}])
    assert catalog.inputs(row, "m", dev)["image"] == (True, "you")
    tried = provider(models=row.models, tried_inputs={"m": {"image": False}})
    assert catalog.inputs(tried, "m", dev)["image"] == (False, "tried")
    assert catalog.inputs(tried, "m", dev)["video"] == (True, "you")


def test_a_local_model_is_marked_by_hand_and_a_bad_mark_is_refused(tmp_path, monkeypatch):
    local = tmp_path / "catalog.local.json"
    local.write_text(json.dumps({"providers": {"Mine": [{"name": "q", "inputs": ["image"]}]}}))
    monkeypatch.setattr(catalog, "LOCAL", local)
    own = provider(base_url="http://localhost:8080/v1", name="Mine")
    assert catalog.inputs(own, "q") == {"image": (True, "you"), "video": (False, "you"),
                                        "audio": (False, "you"), "pdf": (False, "you")}
    local.write_text(json.dumps({"providers": {"Mine": [{"name": "q", "inputs": ["smell"]}]}}))
    told, why = catalog.local()
    assert told == {} and "inputs a list of image" in (why or "")
    with pytest.raises(ValueError, match="inputs are some of"):
        check_guide(None, [{"name": "q", "inputs": ["smell"]}])
    assert check_guide(None, [{"name": "q", "inputs": ["image", "image"]}])[1][0]["inputs"] == [
        "image"]


def test_the_leads_guide_says_it_in_words_and_only_of_what_koloni_can_send():
    assert catalog.inputs_words({"image": (True, "tried"), "video": (True, "you"),
                                 "pdf": (False, "you")}) == "sees images and video"
    assert catalog.inputs_words({"image": (False, "tried")}) is None
    rows = [{"name": "m", "inputs": ["image", "video"]}]
    http = SimpleNamespace(id="p", name="Acme", kind="openai_compat", base_url=None,
                           for_agents=True, models=rows, only_listed=False, note=None,
                           default_model="m", tried_inputs=None, mode=None, options=None, enabled=True)
    line = team.describe(team.guide([http]))
    assert '"m" (sees images and video)' in line
    # A CLI's model sees what its CLI is given: Claude Code and Codex images, never a video.
    cli = SimpleNamespace(**{**vars(http), "kind": "claude_cli", "mode": "step"})
    assert '"m" (sees images)' in team.describe(team.guide([cli]))
    copilot = SimpleNamespace(**{**vars(http), "kind": "copilot_cli", "mode": "session"})
    assert "sees" not in team.describe(team.guide([copilot]))


def test_a_fill_from_a_catalogue_with_modalities_keeps_every_chat_model():
    """Kept modalities make `catalog._chats` live: only a model that writes no text (it
    draws pictures) is left out of a fill; one that also takes pictures, one with no word of
    its modalities, and one the user saved stay."""
    dev = copy(chat={"tool_call": True, "modalities": {"input": ["text", "image"],
                                                       "output": ["text"]}},
               painter={"tool_call": True, "modalities": {"input": ["text"], "output": ["image"]}},
               plain={"tool_call": True})
    offered, _left = catalog.fill("acme", [], [], dev)
    assert sorted(row["name"] for row in offered) == ["chat", "plain"]
    kept, _left = catalog.fill("acme", [{"name": "painter"}], [], dev)
    assert sorted(row["name"] for row in kept) == ["chat", "painter", "plain"]


def test_the_models_page_is_told_each_kind_and_who_said_it(client):
    made = client.post("/api/providers", headers=ORIGIN, json={
        "name": "Mine", "kind": "openai_compat", "base_url": "http://localhost:8080/v1",
        "default_model": "q", "models": [{"name": "q", "inputs": ["image"]}]}).json()
    facts = client.get(f"/api/providers/{made['id']}/model-facts?model=q", headers=ORIGIN).json()
    assert {"kind": "image", "takes": True, "source": "you"} in facts["inputs"]
    # A row sent again without its marks keeps them; [] takes them away.
    url = f"/api/providers/{made['id']}"
    kept = client.patch(url, headers=ORIGIN, json={"models": [{"name": "q", "note": "x"}]})
    assert kept.json()["models"][0]["inputs"] == ["image"]
    gone = client.patch(url, headers=ORIGIN, json={"models": [{"name": "q", "inputs": []}]})
    assert gone.json()["models"][0]["inputs"] == []
