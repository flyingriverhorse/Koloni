"""Slice 40 beyond its acceptance set: the fill's merge, and a CLI asked only its status."""

import json
import sys
import time
from pathlib import Path

import pytest

from app import catalog

ORIGIN = {"Origin": "http://127.0.0.1:8790"}


def test_fill_keeps_the_users_rows_fills_their_blanks_and_adds_the_rest_strongest_first():
    saved = [{"name": "my-own", "note": "mine", "tier": None},
             {"name": "gpt-6-luna", "note": None, "tier": None}]
    proposed, left_out = catalog.fill(
        "codex_cli", saved, ["gpt-6-astra", "served-extra", "bad\nname", " padded"])
    names = [row["name"] for row in proposed]
    assert names[:2] == ["my-own", "gpt-6-luna"] and left_out == 0
    assert proposed[1]["tier"] == "fast" and proposed[1]["note"]       # its blanks filled
    assert proposed[0] == {"name": "my-own", "note": "mine", "tier": None}
    added = [row["tier"] for row in proposed[2:]]
    assert added == sorted(added, key=lambda t: {"strongest": 0, "balanced": 1, "fast": 2,
                                                 None: 3}[t])
    # a name the server lists is offered once, blank; one that could not be saved is not
    assert names.count("gpt-6-astra") == 1 and "served-extra" in names
    assert "bad\nname" not in names and " padded" not in names


CODEX_HELP = "Commands:\n  exec    Run Codex non-interactively\n  login   Manage login\n"


def _status_cli(tmp_path, code: int, said: str, helped: str = CODEX_HELP,
                hang: bool = False) -> str:
    """A stand-in Codex that notes how and where it was started, answers --help with
    `helped`, and says `said` on stderr as Codex's status does - with a misleading line on
    stdout, which is not where Codex says it. With `hang` its status never answers."""
    record = tmp_path / "argv.jsonl"
    script = tmp_path / "status_cli.py"
    script.write_text(
        "import json, os, sys, time\n"
        f"open({str(record)!r}, 'a').write(json.dumps([sys.argv[1:], os.getcwd()]) + '\\n')\n"
        "if sys.argv[1:] == ['--help']:\n"
        f"    print({helped!r})\n"
        "    sys.exit(0)\n"
        "print('Not logged in')\n"
        f"if {hang!r}:\n"
        "    time.sleep(60)\n"
        f"sys.stderr.write({said!r})\n"
        f"sys.exit({code})\n", encoding="utf-8")
    if sys.platform == "win32":
        shim = tmp_path / "codex.cmd"
        shim.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        shim = tmp_path / "codex"
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n')
        shim.chmod(0o755)
    return str(shim)


def _started(tmp_path) -> list:
    """How the stand-in was started each time, and in which folder."""
    record = tmp_path / "argv.jsonl"
    return [json.loads(line) for line in record.read_text().splitlines()] if record.exists() else []


def test_a_signed_in_cli_is_asked_only_its_status_and_nothing_of_the_account_is_told(
    client, tmp_path
):
    cli = _status_cli(tmp_path, 0, "Logged in using ChatGPT (acct_9f8e, someone@example.com)")
    made = client.post("/api/providers", headers=ORIGIN,
                       json={"name": "Codex", "kind": "codex_cli", "executable": cli}).json()
    told = client.get(f"/api/providers/{made['id']}/availability")
    # read from stderr, where Codex says it: stdout's "Not logged in" is not taken
    assert told.json()["installed"] is True and told.json()["signed_in"] is True
    assert {m["state"] for m in told.json()["models"]} == {"unknown"}  # Codex lists none
    assert "acct_" not in told.text and "@" not in told.text
    client.post(f"/api/providers/{made['id']}/fill-from-catalogue", headers=ORIGIN)
    # its free help first, then the status: no prompt, no model
    assert [argv for argv, _ in _started(tmp_path)] == [["--help"], ["login", "status"]]


def test_a_cli_that_is_not_signed_in_says_how_to_sign_in(client, tmp_path):
    cli = _status_cli(tmp_path, 1, "Not logged in\n")
    made = client.post("/api/providers", headers=ORIGIN,
                       json={"name": "Codex", "kind": "codex_cli", "executable": cli}).json()
    told = client.get(f"/api/providers/{made['id']}/availability").json()
    assert told["signed_in"] is False and told["sign_in"]["command"] == "codex login"
    assert told["sign_in"]["docs"].startswith("https://")
    assert all(m["state"] == "unusable" and m["why"] == "not signed in" for m in told["models"])


@pytest.mark.anyio
async def test_a_cli_whose_help_has_no_status_command_is_not_asked_it(tmp_path):
    # an older CLI could take "login status" for a prompt and spend a model call on it
    cli = _status_cli(tmp_path, 0, "Logged in using ChatGPT", helped="Usage: codex [PROMPT]")
    assert await catalog.signed_in("codex_cli", cli) is None
    assert [argv for argv, _ in _started(tmp_path)] == [["--help"]]


@pytest.mark.anyio
async def test_a_status_command_that_hangs_is_not_known_and_leaves_no_folder(
    tmp_path, monkeypatch
):
    # The limit is the --help's too, and each call is a Python started through a .cmd: under
    # load that alone took over half a second, and a call cut before its first line leaves
    # no record of its folder. shortcut: 3 s is a guess at a busy machine's start.
    monkeypatch.setattr(catalog, "STATUS_SECONDS", 3.0)
    cli = _status_cli(tmp_path, 0, "Logged in using ChatGPT", hang=True)
    started = time.monotonic()
    assert await catalog.signed_in("codex_cli", cli) is None
    assert time.monotonic() - started < 15  # the help, three seconds, and the ending of it
    folders = [folder for _, folder in _started(tmp_path)]
    assert len(folders) == 2 and not any(Path(folder).exists() for folder in folders)


def test_claude_codes_status_is_read_from_its_json_and_its_exit_code():
    assert catalog.signed_in_from("claude_cli", 0, '{"loggedIn": true, "email": "a@b.c"}') is True
    assert catalog.signed_in_from("claude_cli", 0, '{"loggedIn": false}') is None
    assert catalog.signed_in_from("claude_cli", 1, '{"loggedIn": false}') is False
    assert catalog.signed_in_from("claude_cli", 0, "Usage: claude [options]") is None
    assert catalog.signed_in_from("codex_cli", 2, "can't open file 'login'") is None


def test_what_is_told_is_for_the_apps_own_page_and_commands_not_another_site(client):
    made = client.post("/api/providers", headers=ORIGIN,
                       json={"name": "Codex", "kind": "codex_cli",
                             "executable": "no-such-codex"}).json()
    answer = client.get(f"/api/providers/{made['id']}/availability",
                        headers={"Origin": "https://elsewhere.example"})
    assert answer.status_code == 403


def test_copilot_on_a_model_server_of_ones_own_is_offered_that_servers_models_not_githubs(
    client, monkeypatch
):
    from app.api import providers as api

    async def served(base_url, key):
        return ["my-local-model"]

    monkeypatch.setattr(api, "served_models", served)
    made = client.post("/api/providers", headers=ORIGIN, json={
        "name": "Copilot", "kind": "copilot_cli", "base_url": "http://127.0.0.1:8080/v1"}).json()
    offer = client.post(f"/api/providers/{made['id']}/fill-from-catalogue", headers=ORIGIN).json()
    assert [m["name"] for m in offer["models"]] == ["my-local-model"]


def test_copilot_offers_its_own_auto_beside_models_devs_models_with_no_level():
    rows = {row["name"]: row for row in catalog.models_for("copilot_cli")}
    assert "auto" in rows and "gpt-6-luna" in rows  # (models.dev's github-copilot: still there)
    assert rows["auto"]["tier"] == "fast" and "no thinking level" in rows["auto"]["note"]
    told, said = catalog.facts("copilot_cli", None, "auto")
    assert told["efforts"] == [] and told["tier"] == "fast" and said["tier"] == "catalog"
    assert said["efforts"] == "Copilot picks it (auto)"  # (its own words, not B-404's)
    assert catalog.facts("copilot_cli", None, "gpt-6-luna")[0]["efforts"]  # (others: Off–Max)
    assert "auto" in [row["name"] for row in catalog.fill("copilot_cli", [], [])[0]]
    # Not on a model server of one's own: that has its own models.
    assert catalog.catalogue_of("copilot_cli", "http://127.0.0.1:8080/v1") is None


@pytest.mark.parametrize("address,first", [
    ("https://api.openai.com/v1", "gpt-6-astra"),
    ("https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "qwen3.8-max"),
    # (the newest strongest: glm is strongest by Alibaba's rules since slice 81a)
    ("https://dashscope.aliyuncs.com/compatible-mode/v1", "glm-5.3"),
    ("https://ws1.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1", "qwen3.8-max"),
    ("http://127.0.0.1:8080/v1", None),
    ("https://api.openai.com.example.net/v1", None),
])
def test_an_openai_compatible_server_gets_the_catalogue_of_the_service_at_its_address(
    client, monkeypatch, address, first
):
    from app.api import providers as api

    async def nothing_listed(provider, providers):  # no request leaves the machine
        return [], None, False

    monkeypatch.setattr(api, "_own_list", nothing_listed)
    made = client.post("/api/providers", headers=ORIGIN, json={
        "name": "Server", "kind": "openai_compat", "base_url": address}).json()
    offer = client.post(f"/api/providers/{made['id']}/fill-from-catalogue", headers=ORIGIN).json()
    assert [m["name"] for m in offer["models"]][:1] == ([first] if first else [])


@pytest.mark.parametrize("key", ["openai", "alibaba"])
def test_the_services_catalogues_have_a_name_a_tier_and_a_source_too(key):
    entries = catalog.models_for(key)
    assert entries and all(e["source"]["url"].startswith("https://") for e in entries)


# Slice 40b: a provider not added yet is proposed its catalogue's models; nothing is listed
# from a server, nothing is saved.
@pytest.mark.parametrize("kind,address,first", [
    ("codex_cli", None, "gpt-6-astra"),
    ("claude_cli", None, "fable"),
    ("openai_compat", "https://api.openai.com/v1", "gpt-6-astra"),
    ("openai_compat", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "qwen3.8-max"),
    ("openai_compat", "http://127.0.0.1:8080/v1", None),
    ("openai_compat", "http://[not-an-address/v1", None),
    ("copilot_cli", "http://127.0.0.1:8080/v1", None),
])
def test_a_provider_not_added_yet_is_proposed_its_catalogue_and_nothing_is_saved(
    client, monkeypatch, kind, address, first
):
    from app.api import providers as api

    async def never(*args):
        raise AssertionError("nothing is listed for a provider not added yet")

    monkeypatch.setattr(api, "_own_list", never)
    monkeypatch.setattr(api, "served_models", never)
    before = client.get("/api/providers").json()
    answer = client.post("/api/providers/fill-from-catalogue", headers=ORIGIN, json={
        "kind": kind, "base_url": address, "models": [{"name": "mine", "note": "kept"}]})
    assert answer.status_code == 200
    names = [m["name"] for m in answer.json()["models"]]
    assert names[0] == "mine" and names[1:2] == ([first] if first else [])
    assert client.get("/api/providers").json() == before


def test_a_proposal_for_a_provider_not_added_yet_is_the_apps_own_page_and_a_known_kind(client):
    told = {"kind": "codex_cli", "models": []}
    assert client.post("/api/providers/fill-from-catalogue", json=told).status_code == 403
    assert client.post("/api/providers/fill-from-catalogue", headers=ORIGIN,
                       json={"kind": "no_such_kind"}).status_code == 422


# What Alibaba's Token Plan lists (its page, 23 Oct 2026): text models, and models that cannot chat.
TOKEN_PLAN_TEXT = [
    "auto", "qwen3.8-max", "qwen3.8-flash", "qwen3.7-plus", "qwen3.7-max", "qwen3.6-flash",
    "deepseek-v4.1-flash-1017", "deepseek-v4.1-flash", "deepseek-v4-pro-0813", "deepseek-v4-pro",
    "deepseek-v4-flash-0731", "glm-5.3", "glm-5.2",
]
TOKEN_PLAN_OTHER = [
    "qwen-audio-3.0-asr-flash", "qwen-audio-3.0-realtime-plus", "qwen-audio-3.0-tts-plus",
    "qwen-image-3.0-pro", "wan2.7-image", "wan2.7-image-pro", "wan3.0-video",
    "happyhorse-1.1-r2v", "happyhorse-1.1-t2v", "happyhorse-1.1-i2v",
]


def test_a_provider_that_lists_its_models_is_offered_only_those_that_chat_with_rule_tiers():
    proposed, left_out = catalog.fill("alibaba", [], TOKEN_PLAN_TEXT + TOKEN_PLAN_OTHER)
    tiers = {row["name"]: row["tier"] for row in proposed}
    # only what the plan lists: not the catalogue's kimi-k3, which it does not offer
    assert set(tiers) <= set(TOKEN_PLAN_TEXT)
    assert "kimi-k3" in [m["name"] for m in catalog.models_for("alibaba")]
    # names the catalogue does not know get the service's rules, with the tier's note
    assert {name: tiers[name] for name in (
        "glm-5.3", "deepseek-v4-pro", "deepseek-v4.1-flash", "qwen3.8-max")} == {
        "glm-5.3": "strongest", "deepseek-v4-pro": "strongest",
        "deepseek-v4.1-flash": "fast", "qwen3.8-max": "strongest"}
    assert next(row for row in proposed if row["name"] == "glm-5.3")["note"] == catalog.NOTES["strongest"]
    # nothing that cannot chat, and each of those counted as left out
    assert left_out >= len(TOKEN_PLAN_OTHER)
    # the user's own row stays, whatever it is
    mine = catalog.fill("alibaba", [{"name": "wan2.7-image"}], TOKEN_PLAN_OTHER)[0]
    assert [row["name"] for row in mine] == ["wan2.7-image"]


@pytest.mark.parametrize("name", [
    "qwen-audio-3.0-asr-flash", "qwen-image-3.0-pro", "text-embedding-3-large", "gte-rerank-v2",
    "whisper-1", "gpt-4o-transcribe", "omni-moderation-latest", "dall-e-3",
])
def test_no_rule_gives_a_model_that_cannot_chat_a_tier(name):
    rules = {**catalog._rules("alibaba"), "large": "strongest", "latest": "fast", "e": "fast"}
    assert catalog._tier(rules, name, {}, [])[0] is None
    assert catalog._tier(rules, "qwen3.8-flash", {}, [])[0] == "fast"  # a chat model still has its rule
