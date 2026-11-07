"""Slice 59c beside its acceptance set: how a service is found by host, a tier by price, the
levels models.dev gives, what is kept of what it sends, a llama-server's level in the request,
and a price that is the catalogue's."""

import asyncio
import json

import httpx2
import pytest

from app import catalog, models_dev
from app.model_client import OpenAICompatClient
from tests.test_chat_flow import text
from tests.test_reasoning_level_scenarios import leveled  # noqa: F401 - the fixture

ORIGIN = {"Origin": "http://127.0.0.1:8790"}


def service(api="https://api.acme.test", **models):
    return {"acme": {"id": "acme", "name": "Acme", "api": api, "env": ["ACME_KEY"],
                     "doc": "https://docs.acme.test", "models": models}}


def priced(output, **more):
    return {"cost": {"input": 1, "output": output}, "tool_call": True, **more}


@pytest.mark.parametrize(("address", "found"), [
    ("https://api.acme.test/v1", "acme"),
    ("https://API.ACME.TEST", "acme"),  # a host is a host whatever its case
    ("https://eu.api.acme.test/v1", None),  # another host: models.dev names only its own
    ("https://api.openai.com/v1", "openai"),  # catalog.json's, where models.dev has no address
    ("https://ws9.eu-central-1.maas.aliyuncs.com/compatible-mode/v1", "alibaba"),
    ("https://maas.aliyuncs.com.example.net/v1", None),
    ("http://localhost:8080/v1", None),
    ("http://[::1/v1", None),
])
def test_a_service_is_found_by_the_host_of_its_address(address, found):
    copy = service(m=priced(1))
    assert catalog.catalogue_of("openai_compat", address, copy) == found


def test_a_tier_by_price_ranks_among_the_services_models_in_use_and_one_price_is_one_tier():
    copy = service(top=priced(9), also_top=priced(9), mid=priced(5), low=priced(1),
                   gone=priced(100, status="deprecated"), free=priced(0))
    tier = {name: catalog.facts("openai_compat", "https://api.acme.test", name, copy)[0]["tier"]
            for name in ("top", "also_top", "mid", "low", "free")}
    # gone is not counted: else "top" would be second of five, not first of four
    assert tier == {"top": "strongest", "also_top": "strongest", "mid": "balanced",
                    "low": "fast", "free": None}


def test_a_family_rule_comes_before_the_price():
    copy = {"anthropic": {**service()["acme"], "id": "anthropic", "api": None, "models": {
        "claude-haiku-9": priced(90, family="claude-haiku"), "x": priced(1)}}}
    told, said = catalog.facts("anthropic", None, "claude-haiku-9", copy)
    assert (told["tier"], said["tier"]) == ("fast", "catalog")


@pytest.mark.parametrize(("entry", "levels"), [
    ({"reasoning": True, "reasoning_options": [
        {"type": "effort", "values": ["none", "minimal", "low", "high", "max"]}]},
     ["low", "high", "max"]),  # only those KOLONİ sends
    ({"reasoning": True, "reasoning_options": [{"type": "toggle"}]}, []),
    ({"reasoning": True, "reasoning_options": []}, []),
    ({"reasoning": False}, []),
    ({"reasoning": True}, None),  # not said
])
def test_the_levels_are_models_devs_effort_values_and_none_where_it_says_none(entry, levels):
    copy = service(m={**priced(1), **entry})
    assert catalog.facts("openai_compat", "https://api.acme.test", "m", copy)[0]["efforts"] == levels


def test_a_cli_has_its_own_levels_and_no_price():
    told, said = catalog.facts("codex_cli", None, "gpt-6-astra")
    assert told["efforts"] == ["low", "medium", "high", "xhigh", "max"]
    assert said["efforts"] == "catalog" and told["price"] is None and told["context_window"]
    assert catalog.facts("qoder_cli", None, "Qwen3.8-Flash")[0]["efforts"][0] == "off"


def test_qoders_listed_models_have_their_tiers():
    # (Its old levels - performance, auto, efficient - are no model names of qodercli 1.1.51.)
    tiers = {name: catalog.facts("qoder_cli", None, name)[0]["tier"]
             for name in catalog._CATALOGUE["cli"]["qoder_cli"]["models"]}
    assert tiers == {"Qwen3.8-Flash": "fast", "DeepSeek-v4-Pro": "strongest", "Qwen-3.8-Max": "strongest",
                     "DeepSeek-v4-Flash": "fast", "Qwen-3.7-Max": "strongest", "GLM-5.2": "strongest",
                     "Qwen-3.6-Flash": "fast"}


def test_what_is_kept_of_models_dev_is_what_is_read_in_the_shape_it_should_have():
    told = {
        "acme": {"id": "acme", "name": "Acme", "api": "https://api.acme.test", "npm": "x",
                 "env": ["ACME_KEY", 7], "doc": "javascript:alert(1)", "models": {
                     "ok": {"name": "Ok", "cost": {"input": 1, "output": True, "cache_read": -1},
                            "limit": {"context": 1000, "output": "lots"}, "extra": "dropped",
                            "reasoning_options": [{"type": "effort", "values": ["low", 3]},
                                                  "junk"]},
                     "bad\nname": {"name": "Bad"},
                     "x" * 201: {"name": "Too long"},
                 }},
        "local": {"api": "http://127.0.0.1:1234/v1", "models": {"m": {}}},
        "templated": {"api": "${GATEWAY}/v1", "models": {"m": {}}},
        "anthropic": {"name": "Anthropic", "models": {"claude": {}}},  # a kind's: no address
        "broken": "not a service",
    }
    kept = models_dev.clean(told)
    assert set(kept) == {"acme", "anthropic"}
    acme = kept["acme"]
    assert acme["env"] == ["ACME_KEY"] and acme["doc"] is None and "npm" not in acme
    assert list(acme["models"]) == ["ok"]
    assert acme["models"]["ok"] == {
        "name": "Ok", "cost": {"input": 1}, "limit": {"context": 1000},
        "reasoning_options": [{"type": "effort", "values": ["low"]}]}
    for not_it in ([], {"acme": {"models": {}}}, {}):
        with pytest.raises(ValueError):
            models_dev.clean(not_it)


def test_an_answer_too_big_or_not_json_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(models_dev, "MAX_BYTES", 100)
    for raw in (b" " * 101, b"{" * 50 + b"}" * 50, b"\xff\xfe"):
        with pytest.raises(ValueError):
            models_dev.update(tmp_path, raw)
    assert list(tmp_path.iterdir()) == []


def test_a_users_copy_that_cannot_be_read_gives_way_to_the_shipped_one(tmp_path):
    (tmp_path / models_dev.NAME).write_text("{not json", encoding="utf-8")
    assert "anthropic" in models_dev.load(tmp_path)


async def _step(client: OpenAICompatClient, effort: str | None) -> None:
    async def quiet(_text):
        pass

    await client.stream_step("qwen", [{"role": "user", "content": "x"}], None, quiet,
                             **({"effort": effort} if effort else {}))


@pytest.mark.anyio
@pytest.mark.parametrize(("effort", "sent"), [
    ("off", {"chat_template_kwargs": {"enable_thinking": False}}),
    ("high", {"reasoning_effort": "high"}),
    (None, {}),
])
async def test_a_level_goes_to_a_llama_server_as_its_template_takes_it(effort, sent):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx2.Response(200, text="data: [DONE]\n\n")

    await _step(OpenAICompatClient("http://127.0.0.1:8080/v1",
                                   transport=httpx2.MockTransport(handler)), effort)
    told = {key: bodies[0][key] for key in ("chat_template_kwargs", "reasoning_effort")
            if key in bodies[0]}
    assert told == sent


LEVEL_KEYS = ("chat_template_kwargs", "reasoning_effort", "enable_thinking", "thinking_budget")


@pytest.mark.anyio
@pytest.mark.parametrize(("model", "effort", "sent"), [
    # measured on Alibaba's service (27 Oct 2026): Qwen ignores reasoning_effort, takes a budget
    ("qwen3.8-flash", "low", {"enable_thinking": True, "thinking_budget": 1024}),
    ("qwen3.8-flash", "xhigh", {"enable_thinking": True, "thinking_budget": 32768}),
    ("qwen3.8-flash", "max", {"enable_thinking": True}),  # its own most
    ("qwen3.8-flash", "off", {"chat_template_kwargs": {"enable_thinking": False}}),
    # and DeepSeek on the same service takes reasoning_effort, ignoring a budget
    ("deepseek-v4-flash-0731", "high", {"reasoning_effort": "high"}),
])
async def test_a_hosted_qwen_is_given_a_budget_and_another_model_its_level(model, effort, sent):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx2.Response(200, text="data: [DONE]\n\n")

    async def quiet(_text):
        pass

    client = OpenAICompatClient("https://token-plan.ap-southeast-1.maas.aliyuncs.com/v1",
                                transport=httpx2.MockTransport(handler))
    await client.stream_step(model, [{"role": "user", "content": "x"}], None, quiet,
                             effort=effort)
    assert {key: bodies[0][key] for key in LEVEL_KEYS if key in bodies[0]} == sent


@pytest.mark.anyio
# (a model that does not think refuses the switch itself)
@pytest.mark.parametrize("field", ["thinking_budget", "enable_thinking"])
async def test_a_qwen_service_that_refuses_the_budget_is_asked_again_without_it(field):
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if "thinking_budget" in body:
            return httpx2.Response(400, json={"error": {
                "message": f"<400> InternalError.Algo.InvalidParameter: {field}"}})
        return httpx2.Response(200, text='data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
                                         "data: [DONE]\n\n")

    async def quiet(_text):
        pass

    client = OpenAICompatClient("https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                                transport=httpx2.MockTransport(handler))
    said = [{"role": "user", "content": "x"}]
    first = await client.stream_step("qwen3.8-max", said, None, quiet, effort="low")
    assert first.content == "ok" and first.effort_refused and client.refused_effort
    assert ["thinking_budget" in body for body in bodies] == [True, False]


@pytest.mark.anyio
async def test_a_template_without_the_switch_has_no_off():
    def handler(request):
        return httpx2.Response(200, json={
            "chat_template_caps": {"supports_reasoning_effort": True}, "chat_template": "{{x}}"})

    client = OpenAICompatClient("http://model/v1", transport=httpx2.MockTransport(handler))
    await client.found_window()
    assert client.efforts == ("low", "medium", "high")


def test_qoder_says_off_its_own_way():
    from app.model_session import QoderSessionClient

    assert QoderSessionClient()._leveled(["-p"], "off") == ["--reasoning-effort", "none", "-p"]


def test_a_model_without_the_users_price_costs_the_catalogues_and_says_so(
    make_client, wait_run, project_dir
):
    from sqlalchemy import select

    from app.db.models import Agent
    from tests.test_chat_flow import text
    from tests.test_usage_scenarios import began, turn, usage

    client, _model, pid, cid = began(make_client, project_dir, [text("a", 1, 1)])
    run = turn(client, wait_run, cid)
    made = client.post("/api/providers", json={
        "name": "Claude API", "kind": "anthropic", "api_key": "sk-test"}).json()
    with client.app.state.session_factory() as session:
        lead = session.scalars(select(Agent)).one()
        session.add(Agent(run_id=run["id"], role_name="Other", tools=[],
                          provider_name="Claude API", model_id="claude-sonnet-4-5",
                          input_tokens_total=1_000_000, output_tokens=1_000_000,
                          started_at=lead.started_at))
        session.commit()
    cost = lambda: next(row["cost"] for row in usage(client, project_id=pid)["by_model"]  # noqa: E731
                        if row["model_id"] == "claude-sonnet-4-5")
    # models.dev: $3 in and $15 out a million, with the day its (shipped) copy was read
    from app import models_dev
    shipped_on = models_dev.read_on(models_dev.load(None))
    assert cost() == {"amount": 18.0, "currency": "USD", "price_from": "models.dev",
                      "price_read_on": shipped_on}
    # a month's budget counts it, in USD: with only the catalogue's prices it goes over
    assert client.patch(f"/api/projects/{pid}", json={"monthly_budget": 10}).status_code == 200
    budget = lambda: client.get(f"/api/projects/{pid}/budget").json()  # noqa: E731
    assert (budget()["spent"], budget()["currency"], budget()["over"]) == (18.0, "USD", True)
    # the Prices list offers it at the catalogue's price, for the user to write over
    offered = client.get("/api/prices/catalogue").json()
    assert {"model_id": "claude-sonnet-4-5", "provider_name": "Claude API", "input": 3,
            "output": 15, "cache_read": 0.3, "cache_write": 3.75, "currency": "USD",
            "read_on": shipped_on} in offered
    # the user's own price comes first: in the cost, the spend and what is known of the model
    client.put("/api/prices", json={
        "model_id": "claude-sonnet-4-5", "input": 1, "output": 2, "currency": "USD"})
    assert cost() == {"amount": 3.0, "currency": "USD"}
    assert (budget()["spent"], budget()["over"]) == (3.0, False)
    client.put("/api/prices", json={
        "model_id": "claude-sonnet-4-5", "input": 1, "output": 2, "currency": "TL"})
    told = client.get(f"/api/providers/{made['id']}/model-facts",
                      params={"model": "claude-sonnet-4-5"}).json()
    assert told["price"]["currency"] == "TL" and told["sources"]["price"] == "you"
    assert "sk-test" not in json.dumps(told)
    assert client.get(f"/api/providers/{made['id']}/model-facts", params={"model": "x"},
                      headers={"Origin": "https://elsewhere.example"}).status_code == 403


def test_of_two_services_on_one_host_the_one_at_the_servers_address_is_found():
    copy = {**service(api="https://api.z.test/plan/v4", m=priced(1)),
            "payg": {**service()["acme"], "id": "payg", "api": "https://api.z.test/v4"}}
    assert catalog.catalogue_of("openai_compat", "https://api.z.test/v4", copy) == "payg"
    assert catalog.catalogue_of("openai_compat", "https://api.z.test/plan/v4/", copy) == "acme"
    assert catalog.catalogue_of("openai_compat", "https://api.z.test/other", copy) == "acme"
    assert catalog.catalogue_of("openai_compat", "https://API.z.test/V4/", copy) == "payg"
    # a path is compared part by part: /v4beta is not under /v4
    assert catalog.catalogue_of("openai_compat", "https://api.z.test/v4beta", copy) == "acme"


def test_a_budget_in_another_currency_still_holds_and_the_users_copy_is_what_prices(
    make_client, wait_run, project_dir, settings_env
):
    from pathlib import Path

    from sqlalchemy import select

    from app.db.models import Agent
    from tests.test_chat_flow import text
    from tests.test_usage_scenarios import began, turn, usage

    client, _model, pid, cid = began(make_client, project_dir, [text("a", 1_000_000, 0)])
    run = turn(client, wait_run, cid)
    root = Path(settings_env["KOLONI_RUNTIME_ROOT"])
    (root / models_dev.NAME).write_text(json.dumps(service(m=priced(2))), encoding="utf-8")
    client.post("/api/providers", json={
        "name": "Acme", "kind": "openai_compat", "base_url": "https://api.acme.test/v1"})
    with client.app.state.session_factory() as session:
        lead = session.scalars(select(Agent)).one()
        session.add(Agent(run_id=run["id"], role_name="Other", tools=[], provider_name="Acme",
                          model_id="m", input_tokens_total=1_000_000, output_tokens=1_000_000,
                          started_at=lead.started_at))
        session.commit()
    rows = {row["model_id"]: row["cost"] for row in usage(client, project_id=pid)["by_model"]}
    # the user's updated copy, not the shipped one: $1 in, $2 out a million
    assert rows["m"] == {"amount": 3.0, "currency": "USD", "price_from": "models.dev",
                         "price_read_on": None}  # (that copy says no date)
    client.put("/api/prices", json={
        "model_id": "fake-model", "input": 1, "output": 1, "currency": "TL"})
    spend = client.get(f"/api/projects/{pid}/budget").json()
    # a month priced in TL is summed in TL; the model at the catalogue's USD price is unpriced
    assert (spend["currency"], spend["spent"], spend["unpriced_runs"]) == ("TL", 1.0, 1)


def test_a_server_is_asked_its_props_once_whatever_name_is_typed_and_never_its_chat(
    client, monkeypatch
):
    asked = []

    async def found_window(self):
        asked.append(self)
        self.props_efforts, self.reached = ("off", "low"), True
        return 8192

    async def never(*args, **kwargs):
        raise AssertionError("a lookup starts no generation")

    monkeypatch.setattr(OpenAICompatClient, "found_window", found_window)
    monkeypatch.setattr(OpenAICompatClient, "info", never)
    monkeypatch.setattr(OpenAICompatClient, "stream_step", never)
    # A server on the LAN as well as on this machine: its `/props` is a free GET.
    lan = client.post("/api/providers", headers=ORIGIN, json={
        "name": "L", "kind": "openai_compat", "base_url": "http://192.168.1.20:8080/v1"}).json()
    for name in ("q", "qw", "qwen"):
        told = client.get(f"/api/providers/{lan['id']}/model-facts", params={"model": name}).json()
    assert len(set(map(id, asked))) == 1  # one client: the one its runs use
    assert (told["efforts"], told["context_window"], told["failed"]) == (["off", "low"], 8192, False)
    assert told["sources"] == {"efforts": "server", "context_window": "server"}


@pytest.mark.anyio
async def test_a_server_that_does_not_answer_is_a_failed_lookup_and_one_that_says_no_is_not():
    def refused(request):
        raise httpx2.ConnectError("refused")

    down = OpenAICompatClient("http://model/v1", transport=httpx2.MockTransport(refused))
    await down.found_window()
    unauthorised = OpenAICompatClient(
        "http://model/v1", transport=httpx2.MockTransport(lambda r: httpx2.Response(401)))
    await unauthorised.found_window()
    assert (down.reached, unauthorised.reached) == (False, True)


def test_anthropic_is_asked_through_one_client_and_a_model_it_does_not_know_is_unknown(
    client, monkeypatch
):
    from app.model_anthropic import AnthropicClient
    from app.model_client import ModelInfo, ModelUnavailable

    asked = []

    async def look_up(self, model_id, seconds):
        asked.append(model_id)
        if model_id == "claude-gone":
            response = httpx2.Response(404, request=httpx2.Request("GET", "https://x"))
            try:
                response.raise_for_status()
            except httpx2.HTTPStatusError as exc:
                raise ModelUnavailable("model server returned 404") from exc
        return ModelInfo(model_id, True, efforts=("low",), context_window=1000), None

    monkeypatch.setattr(AnthropicClient, "_look_up", look_up)
    made = client.post("/api/providers", headers=ORIGIN, json={
        "name": "A", "kind": "anthropic", "api_key": "sk-test"}).json()
    facts = lambda name: client.get(f"/api/providers/{made['id']}/model-facts",  # noqa: E731
                                    params={"model": name}).json()
    built = len(client.app.state.providers._cache)
    assert facts("")["efforts"] is None and asked == []  # no name and no default: nobody asked
    gone = facts("claude-gone")
    assert (gone["efforts"], gone["failed"]) == (None, False)
    new = facts("claude-new-9")
    assert (new["efforts"], new["sources"]["efforts"]) == (["low"], "anthropic")
    assert len(client.app.state.providers._cache) <= built + 1  # not one client per name


def test_a_download_past_its_size_is_cut_off_and_nothing_is_written(client, settings_env, monkeypatch):
    from pathlib import Path

    chunks = []

    async def body():
        for _ in range(10):
            chunks.append(1)
            yield b"x" * 64

    monkeypatch.setattr(models_dev, "MAX_BYTES", 100)
    monkeypatch.setattr(models_dev, "_transport", httpx2.MockTransport(
        lambda request: httpx2.Response(200, content=body())))
    assert client.post("/api/catalog/update").status_code == 403  # not the app's own page
    assert chunks == []
    failed = client.post("/api/catalog/update", headers=ORIGIN)
    assert failed.status_code == 502 and "more than" in failed.json()["detail"]
    assert len(chunks) == 2  # cut off as it streams, not read to its end
    assert not (Path(settings_env["KOLONI_RUNTIME_ROOT"]) / models_dev.NAME).exists()


@pytest.mark.anyio
async def test_a_service_that_refuses_the_level_is_asked_again_without_it_and_never_sent_one_again():
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if "reasoning_effort" in body:
            return httpx2.Response(400, json={"error": {
                "message": "Unrecognized request argument supplied: reasoning_effort"}})
        return httpx2.Response(200, text='data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
                                         "data: [DONE]\n\n")

    async def quiet(_text):
        pass

    client = OpenAICompatClient("https://api.acme.test/v1", efforts=("low", "high"),
                                transport=httpx2.MockTransport(handler))
    said = [{"role": "user", "content": "x"}]
    first = await client.stream_step("m", said, None, quiet, effort="high")
    assert first.content == "ok" and first.effort_refused
    assert client.efforts is None and client.refused_effort
    again = await client.stream_step("m", said, None, quiet, effort="high")
    assert not again.effort_refused
    assert ["reasoning_effort" in body for body in bodies] == [True, False, False]


def test_an_agent_whose_service_refused_its_level_says_so_on_its_record(
    leveled, wait_run, project_dir, monkeypatch  # noqa: F811
):
    from dataclasses import replace

    from tests.test_reasoning_level_scenarios import ran, set_role

    client, model = leveled({"Lead": [text("one")]})
    plain = type(model).stream_step

    async def stream_step(self, *args, effort=None, **more):
        result = await plain(self, *args, effort=effort, **more)
        return replace(result, effort_refused=True) if effort else result  # the service: no

    monkeypatch.setattr(type(model), "stream_step", stream_step)
    set_role(client, "Lead", effort="high")
    lead = client.get(f"/api/conversations/{ran(client, wait_run, project_dir)}").json()[
        "agents"][0]
    assert lead["effort"] is None
    assert lead["effort_note"].endswith(
        "refused reasoning level high: this step was asked again without one, and none is "
        "sent to it until the provider is changed.")


def test_catalog_jsons_hosts_come_before_models_devs():
    copy = {**service(api="https://api.openai.com/v1", m=priced(1))}  # models.dev says "acme"
    assert catalog.catalogue_of("openai_compat", "https://api.openai.com/v1", copy) == "openai"


def test_a_users_copy_that_cannot_be_read_is_not_read_again_until_it_changes(tmp_path, monkeypatch):
    broken = tmp_path / models_dev.NAME
    broken.write_text("{not json", encoding="utf-8")
    reads = []
    real = models_dev.json.loads
    monkeypatch.setattr(models_dev.json, "loads", lambda raw: reads.append(1) or real(raw))
    models_dev.load(tmp_path)
    count = len(reads)
    models_dev.load(tmp_path)
    assert len(reads) == count  # its failure is kept by its stamp


ALIBABA = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"


def test_a_model_its_service_does_not_know_has_the_facts_of_another_that_has_it_said_so():
    # The shipped copy (slice 81a-2): Alibaba's plan serves models its service does not list.
    # The vendor's own service, of two that have it: all it says, said to be its.
    told, said = catalog.facts("openai_compat", ALIBABA, "deepseek-v4-pro")
    assert told["context_window"] and told["efforts"] and told["price"]
    assert {said[f] for f in ("context_window", "max_output", "price", "efforts")} == {
        "models.dev (deepseek)"}
    assert told["price"]["output"] == models_dev.load(None)["deepseek"]["models"][
        "deepseek-v4-pro"]["cost"]["output"]
    # Another reseller's: shown, but not the window or levels that are run with.
    told, said = catalog.facts("openai_compat", ALIBABA, "glm-5.3")
    assert told["max_output"] and said["price"] == "models.dev (alibaba-cn)"
    assert (told["context_window"], told["efforts"]) == (None, None)
    # Another service retiring it says nothing of this one's.
    assert told["deprecated"] is None and "deprecated" not in said
    # Its own service's word, where it has one; nobody's, where none has it.
    assert catalog.facts("openai_compat", ALIBABA, "qwen3-max")[1]["price"] == "models.dev"
    assert catalog.facts("openai_compat", ALIBABA, "nobody-has-it") == (
        dict.fromkeys(catalog.FACTS), {})


def test_a_users_copy_is_looked_through_the_same_way_and_only_a_server_borrows():
    other = {**service()["acme"], "models": {
        "glm-9": priced(4, limit={"context": 9}), "kimi-9": priced(2, limit={"context": 7})}}
    copy = {**service(own=priced(1)), "glm": {**other, "id": "glm"}}
    told, said = catalog.facts("openai_compat", "https://api.acme.test", "glm-9", copy)
    assert (told["context_window"], told["price"]["output"]) == (9, 4)
    assert said["context_window"] == said["price"] == "models.dev (glm)"
    # (Ranked by price among the provider's own service's, and said to be the other's.)
    assert (told["tier"], said["tier"]) == ("strongest", "models.dev (glm)")
    # Not the vendor's own service: no window.
    told = catalog.facts("openai_compat", "https://api.acme.test", "kimi-9", copy)[0]
    assert (told["context_window"], told["price"]["output"]) == (None, 2)
    for kind in ("codex_cli", "anthropic"):
        assert catalog.facts(kind, None, "deepseek-v4-pro")[0]["context_window"] is None


def test_of_two_other_services_that_have_a_model_the_one_at_the_providers_domain_is_taken():
    # Neither is the vendor's own: the one whose address shares the provider's domain is the
    # more like it (Alibaba's plan and Alibaba China's service), not the first by id.
    copy = {**service(own=priced(1)),
            "aaa": {**service()["acme"], "id": "aaa", "api": "https://api.aaa.test",
                    "models": {"glm-9": priced(5)}},
            "zed": {**service()["acme"], "id": "zed", "api": "https://cn.acme.test/v1",
                    "models": {"glm-9": priced(3)}}}
    told, said = catalog.facts("openai_compat", "https://api.acme.test/v1", "glm-9", copy)
    assert (told["price"]["output"], said["price"]) == (3, "models.dev (zed)")
    # The vendor's own still comes first.
    copy["glm"] = {**copy["aaa"], "id": "glm", "models": {"glm-9": priced(7)}}
    assert catalog.facts("openai_compat", "https://api.acme.test/v1", "glm-9", copy)[1][
        "price"] == "models.dev (glm)"


def test_another_services_price_is_shown_and_never_counted(make_client, wait_run, project_dir):
    from sqlalchemy import select

    from app.db.models import Agent
    from tests.test_usage_scenarios import began, turn, usage

    client, _model, pid, cid = began(make_client, project_dir, [text("a", 1, 1)])
    run = turn(client, wait_run, cid)
    made = client.post("/api/providers", json={
        "name": "Token Plan", "kind": "openai_compat", "base_url": ALIBABA}).json()
    with client.app.state.session_factory() as session:
        lead = session.scalars(select(Agent)).one()
        session.add(Agent(run_id=run["id"], role_name="Other", tools=[],
                          provider_name="Token Plan", model_id="deepseek-v4-pro",
                          input_tokens_total=1_000_000, output_tokens=1_000_000,
                          started_at=lead.started_at))
        session.commit()
    # Shown, its service named...
    told = client.get(f"/api/providers/{made['id']}/model-facts",
                      params={"model": "deepseek-v4-pro"}).json()
    assert told["price"]["output"] and told["sources"]["price"] == "models.dev (deepseek)"
    # ...but a plan's credits are not DeepSeek's prices: unpriced, and the budget holds.
    row = next(row for row in usage(client, project_id=pid)["by_model"]
               if row["model_id"] == "deepseek-v4-pro")
    assert row["cost"] is None
    assert client.patch(f"/api/projects/{pid}", json={"monthly_budget": 1}).status_code == 200
    budget = client.get(f"/api/projects/{pid}/budget").json()
    assert (budget["spent"], budget["over"], budget["unpriced_runs"]) == (0, False, 1)
    assert "deepseek-v4-pro" not in {p["model_id"] for p in client.get("/api/prices/catalogue").json()}


@pytest.mark.anyio
async def test_a_catalogue_a_week_old_is_downloaded_again_a_fresh_one_is_not(tmp_path, monkeypatch):
    """Keeping the catalogue fresh (`models_dev.refresh`): one download for a copy older than
    a week, none for a newer one; without the network the copy stays as it was."""
    calls = []

    async def download():
        calls.append(1)
        return json.dumps(service(m={})).encode()

    monkeypatch.setattr(models_dev, "download", download)
    old = {**service(m={}), models_dev.ABOUT: {"read_on": "2026-01-01"}}
    (tmp_path / models_dev.NAME).write_text(json.dumps(old), encoding="utf-8")
    assert await models_dev.refresh(tmp_path) and calls == [1]
    assert models_dev.read_on(models_dev.load(tmp_path)) > "2026-01-01"  # (kept as an update)
    assert not await models_dev.refresh(tmp_path) and calls == [1]  # fresh now

    async def unreachable():
        raise httpx2.ConnectError("no network")

    monkeypatch.setattr(models_dev, "download", unreachable)
    (tmp_path / models_dev.NAME).write_text(json.dumps(old), encoding="utf-8")
    assert not await models_dev.refresh(tmp_path)
    assert models_dev.read_on(models_dev.load(tmp_path)) == "2026-01-01"


def test_keeping_the_catalogue_fresh_is_the_users_and_looked_at_on_each_start(
        settings_env, monkeypatch):
    from app.config import load_settings
    from app.main import create_app
    from tests.keyed import TestClient

    started = []

    def refresh(root):  # (looked at here: what it does is the test above)
        started.append(root)
        return asyncio.sleep(0)

    monkeypatch.setattr(models_dev, "refresh", refresh)

    def start(**env):
        app = create_app(load_settings({**settings_env, **env}))
        return TestClient(app, base_url="http://127.0.0.1:8790")

    with start(KOLONI_CATALOGUE_REFRESH="1") as client:
        assert client.get("/api/catalog").json()["keep_fresh"] is True  # on until turned off
        assert len(started) == 1
        assert client.put("/api/catalog/fresh", json={"keep_fresh": False}).status_code == 403
        off = client.put("/api/catalog/fresh", json={"keep_fresh": False}, headers=ORIGIN)
        assert off.status_code == 200 and off.json()["keep_fresh"] is False
    with start(KOLONI_CATALOGUE_REFRESH="1") as client:
        assert len(started) == 1  # the user turned it off
        client.put("/api/catalog/fresh", json={"keep_fresh": True}, headers=ORIGIN)
    with start():  # (tests: KOLONI_CATALOGUE_REFRESH=0)
        assert len(started) == 1


# K-60d-kalan: the user's own catalogue (catalog.local.json) over models.dev's tier and levels,
# under the model's own row; the levels it gives are the ones sent.
def test_the_users_catalogue_says_a_tier_and_levels_over_models_devs(tmp_path, monkeypatch):
    copy = service(m={**priced(9), "reasoning": True, "reasoning_options": [
        {"type": "effort", "values": ["low", "medium", "high"]}]}, cheap=priced(1))
    told, said = catalog.facts("openai_compat", "https://api.acme.test", "m", copy, "Acme")
    assert (told["tier"], said["tier"], said["efforts"]) == ("strongest", "models.dev", "models.dev")
    local = tmp_path / "catalog.local.json"
    monkeypatch.setattr(catalog, "LOCAL", local)
    local.write_text(json.dumps({
        "models": {"acme": [{"name": "m", "tier": "balanced", "efforts": ["max", "low"]}]},
        "providers": {"Acme": [{"name": "m", "tier": "fast"}], "Mine": [
            {"name": "q", "tier": "balanced", "efforts": ["high"]}]}}))
    told, said = catalog.facts("openai_compat", "https://api.acme.test", "m", copy, "Acme")
    # the provider's name over its catalogue's; levels in the order KOLONİ has them
    assert (told["tier"], told["efforts"]) == ("fast", ["low", "max"])
    assert (said["tier"], said["efforts"]) == ("you", "you")
    # a server on this machine has no catalogue: its rows are found by the provider's name
    told, said = catalog.facts("openai_compat", "http://localhost:8080/v1", "q", copy, "Mine")
    assert (told["tier"], told["efforts"], said) == ("balanced", ["high"],
                                                     {"tier": "you", "efforts": "you"})
    # a CLI sends catalog.json's levels, whatever the file says: only its tier is taken
    local.write_text(json.dumps({"models": {"codex_cli": [
        {"name": "gpt-6-astra", "tier": "fast", "efforts": ["max"]}]}}))
    told, said = catalog.facts("codex_cli", None, "gpt-6-astra", None, "Codex")
    assert (told["tier"], said["tier"], said["efforts"]) == ("fast", "you", "catalog")
    assert catalog.facts("codex_cli", None, "gpt-6-astra")[1]["tier"] == "catalog"  # unnamed
    local.write_text(json.dumps({"models": {"acme": [{"name": "m", "efforts": ["most"]}]}}))
    told, why = catalog.local()
    assert told == {} and "efforts a list of off" in (why or "")


@pytest.mark.anyio
async def test_the_users_levels_are_sent_over_what_a_llama_server_says_the_catalogues_are_not():
    def handler(request):
        return httpx2.Response(200, json={
            "chat_template_caps": {"supports_reasoning_effort": True}, "chat_template": "{{x}}"})

    mine, catalogued = (OpenAICompatClient("http://model/v1", efforts=("high",), efforts_yours=yours,
                                           transport=httpx2.MockTransport(handler))
                        for yours in (True, False))
    await mine.found_window()
    await catalogued.found_window()
    assert mine.efforts == ("high",) and catalogued.efforts == ("low", "medium", "high")


def test_the_page_says_the_users_catalogue_and_the_models_own_row_over_it(
    client, tmp_path, monkeypatch
):
    import os

    from app.api import providers as api

    asked = []  # (the clients themselves: a dropped one's id may be given again)

    async def found_window(self):
        if self not in asked:
            asked.append(self)
        self.props_efforts, self.reached = ("off", "low"), True
        return 8192

    def edit(said):  # (a later time, whatever the clock's grain)
        local.write_text(json.dumps(said))
        os.utime(local, ns=(len(asked) * 10**9, len(asked) * 10**9))

    monkeypatch.setattr(OpenAICompatClient, "found_window", found_window)
    local = tmp_path / "catalog.local.json"
    monkeypatch.setattr(catalog, "LOCAL", local)
    edit({"providers": {"L": [{"name": "q", "tier": "fast", "efforts": ["high"]}]}})
    made = client.post("/api/providers", headers=ORIGIN, json={
        "name": "L", "kind": "openai_compat", "base_url": "http://192.168.1.20:8080/v1",
        "models": [{"name": "row", "tier": "strongest"}]}).json()
    facts = f"/api/providers/{made['id']}/model-facts"
    told = client.get(facts, params={"model": "q"}).json()
    assert (told["tier"], told["efforts"], told["context_window"]) == ("fast", ["high"], 8192)
    assert told["sources"] == {"tier": "you", "efforts": "you", "context_window": "server"}
    edit({"providers": {"L": [{"name": "row", "tier": "fast"}, {"name": "q", "tier": "fast"}]}})
    told = client.get(facts, params={"model": "row"}).json()
    assert (told["tier"], told["sources"]["tier"]) == ("strongest", "you")
    assert len(asked) == 2  # an edit of the file makes a new client: its levels are the file's
    # a tier alone leaves the levels to the server
    told = client.get(facts, params={"model": "q"}).json()
    assert (told["efforts"], told["sources"]["efforts"]) == (["off", "low"], "server")
    # a service's catalogue levels give way to what its server says, as its client sends them
    monkeypatch.setattr(api, "_copy", lambda request: service(m={
        **priced(1), "reasoning": True, "limit": {"context": 1000},
        "reasoning_options": [{"type": "effort", "values": ["low", "high"]}]}))
    hosted = client.post("/api/providers", headers=ORIGIN, json={
        "name": "H", "kind": "openai_compat", "base_url": "https://api.acme.test/v1"}).json()
    told = client.get(f"/api/providers/{hosted['id']}/model-facts", params={"model": "m"}).json()
    assert (told["efforts"], told["context_window"]) == (["off", "low"], 1000)
    assert (told["sources"]["efforts"], told["sources"]["context_window"]) == ("server", "models.dev")


def test_the_example_catalogue_is_read(monkeypatch):
    monkeypatch.setattr(catalog, "LOCAL", catalog.REPO_ROOT / "catalog.local.example.json")
    told, why = catalog.local()
    assert why is None and told["providers"]["My service"][0]["efforts"] == ["low", "high"]


OPENAI = "https://api.openai.com/v1"


@pytest.mark.parametrize(("model", "first", "off"), [
    ("gpt-5.5", "off", "none"),  # models.dev's "none" is KOLONİ's off, and goes as that
    ("gpt-6-astra", "low", "low"),  # no none: off goes as its lowest
    ("gpt-6.2-nova", "off", "none"),  # not in the catalogue: the docs' table, by its name
    ("gpt-6.1-sol-mini", "low", "low"),
    ("someone-elses", None, None),  # neither knows it: off goes as before
])
def test_openais_off_is_its_none_only_where_the_model_takes_it(model, first, off):
    levels = catalog.facts("openai_compat", OPENAI, model)[0]["efforts"]
    assert (levels or [None])[0] == first
    assert catalog.off_as("openai_compat", OPENAI, model) == off
    # a llama-server's off is its template's switch, whatever the model is named
    assert catalog.off_as("openai_compat", "http://127.0.0.1:8080/v1", model) is None


@pytest.mark.anyio
async def test_off_goes_to_openai_as_none():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx2.Response(200, text="data: [DONE]\n\n")

    await _step(OpenAICompatClient(OPENAI, off_as="none", transport=httpx2.MockTransport(
        handler)), "off")
    assert bodies[0]["reasoning_effort"] == "none" and "chat_template_kwargs" not in bodies[0]


@pytest.mark.anyio
async def test_a_level_the_model_does_not_take_is_asked_again_with_the_highest_it_takes():
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body.get("reasoning_effort"))
        if body.get("reasoning_effort") == "xhigh":  # as OpenAI answers for GPT-5.5's max
            return httpx2.Response(400, json={"error": {
                "message": "Unsupported value: 'reasoning_effort' does not support 'xhigh' with "
                           "this model. Supported values are: 'none', 'low', 'medium', and "
                           "'high'.", "type": "invalid_request_error",
                "param": "reasoning_effort", "code": "unsupported_value"}})
        return httpx2.Response(200, text='data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
                                         "data: [DONE]\n\n")

    async def quiet(_text):
        pass

    client = OpenAICompatClient(OPENAI, efforts=("low", "high", "xhigh"),
                                transport=httpx2.MockTransport(handler))
    said = [{"role": "user", "content": "x"}]
    first = await client.stream_step("gpt-5.5", said, None, quiet, effort="xhigh")
    assert first.content == "ok" and first.effort_instead == ("xhigh", "high")
    assert not first.effort_refused and not client.refused_effort
    again = await client.stream_step("gpt-5.5", said, None, quiet, effort="xhigh")
    assert again.effort_instead is None
    assert bodies == ["xhigh", "high", "high"]  # asked once more, then sent high from the start


def test_an_agent_whose_model_took_another_level_says_so_on_its_record(
    leveled, wait_run, project_dir, monkeypatch  # noqa: F811
):
    from dataclasses import replace

    from tests.test_reasoning_level_scenarios import ran, set_role

    client, model = leveled({"Lead": [text("one")]})
    plain = type(model).stream_step

    async def stream_step(self, *args, effort=None, **more):
        result = await plain(self, *args, effort=effort, **more)
        return replace(result, effort_instead=(effort, "medium")) if effort else result

    monkeypatch.setattr(type(model), "stream_step", stream_step)
    set_role(client, "Lead", effort="high")
    lead = client.get(f"/api/conversations/{ran(client, wait_run, project_dir)}").json()[
        "agents"][0]
    assert lead["effort"] == "medium"
    assert lead["effort_note"].endswith("does not take high; sent medium")
