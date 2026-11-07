"""Slice 54's acceptance set: the same request to two models, side by side. Written before the code.

The user sends one message to two models at once. Each works in a working copy of its own (slice
19b), so nothing either writes reaches the project. The two answers are shown side by side - the
answer, the files changed, time and tokens. The user picks one: its changes are taken into the
project, the other's copy is thrown away. Only from the app's own page.

Contract:
- `POST /api/conversations/{cid}/compare {content, sides: [{provider_id, model_id?}, {…}]}` → 201
  `{compare_id, run_ids: [a, b]}`; exactly two sides, both providers known (else 422).
- `GET /api/compares/{id}` → `{status (running|ready|chosen|discarded), chosen_run_id,
  sides: [{run_id, provider_id, model_id, status, answer, changed_files: [path], input_tokens,
  output_tokens, cost, seconds}]}`; `cost` null with no price.
- `POST /api/compares/{id}/choose {run_id}` → the chosen side's changes are in the project, the
  other's copy is gone; 409 before both sides end or once chosen. `POST /api/compares/{id}/discard`
  throws both away.
"""

import time

import pytest

from app.config import load_settings
from app.main import create_app
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_agent_writes import write
from tests.test_chat_flow import text

ORIGIN = {"Origin": "http://127.0.0.1:8790"}


@pytest.fixture
def two(settings_env):
    opened = []

    def make(a_steps, b_steps):
        alpha, beta = ScriptedModel(a_steps, model_id="alpha-1"), ScriptedModel(b_steps, model_id="beta-1")
        app = create_app(load_settings(settings_env), model=ScriptedModel([]),
                         clients={"Alpha": alpha, "Beta": beta})
        client = TestClient(app, base_url="http://127.0.0.1:8790")
        client.__enter__()
        opened.append(client)
        client.headers.update(ORIGIN)
        if "/api/compares/{compare_id}" not in client.app.openapi()["paths"]:
            pytest.skip("slice 54 is not built yet")  # written before the code
        made = [client.post("/api/providers", json={
            "name": name, "kind": "openai_compat", "base_url": "http://127.0.0.1:9/v1",
            "model_id": model_id}).json() for name, model_id in (("Alpha", "alpha-1"), ("Beta", "beta-1"))]
        return client, made

    yield make
    for client in opened:
        client.__exit__(None, None, None)


def compared(client, project_dir, providers, content="make greeting.txt"):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={"permission_mode": "full_auto"})
    sides = [{"provider_id": p["id"]} for p in providers]
    started = client.post(f"/api/conversations/{cid}/compare", json={"content": content, "sides": sides})
    assert started.status_code == 201, started.text
    return cid, started.json()


def ready(client, compare_id, timeout=10.0):
    deadline = time.monotonic() + timeout
    while True:
        seen = client.get(f"/api/compares/{compare_id}").json()
        if seen["status"] != "running":
            return seen
        assert time.monotonic() < deadline, seen
        time.sleep(0.05)


def test_two_models_work_apart_and_only_the_chosen_ones_work_reaches_the_project(two, project_dir):
    client, providers = two([write("greeting.txt", "hello from alpha\n"), text("Alpha made it.", 10, 4)],
                            [write("greeting.txt", "hello from beta\n"), text("Beta made it.", 20, 8)])
    _cid, started = compared(client, project_dir, providers)
    seen = ready(client, started["compare_id"])
    assert seen["status"] == "ready"
    alpha, beta = seen["sides"]
    assert (alpha["model_id"], alpha["answer"], alpha["changed_files"]) == ("alpha-1", "Alpha made it.", ["greeting.txt"])
    assert (beta["model_id"], beta["answer"]) == ("beta-1", "Beta made it.")
    assert beta["input_tokens"] >= 20 and alpha["cost"] is None and alpha["seconds"] is not None
    assert not (project_dir / "greeting.txt").exists()  # neither side has written into the project

    chosen = client.post(f"/api/compares/{started['compare_id']}/choose", json={"run_id": beta["run_id"]})
    assert chosen.status_code == 200, chosen.text
    assert (project_dir / "greeting.txt").read_text() == "hello from beta\n"
    after = client.get(f"/api/compares/{started['compare_id']}").json()
    assert (after["status"], after["chosen_run_id"]) == ("chosen", beta["run_id"])
    again = client.post(f"/api/compares/{started['compare_id']}/choose", json={"run_id": alpha["run_id"]})
    assert again.status_code == 409
    assert (project_dir / "greeting.txt").read_text() == "hello from beta\n"


def test_discarded_both_leave_nothing(two, project_dir):
    client, providers = two([write("a.txt", "a\n"), text("a")], [write("b.txt", "b\n"), text("b")])
    _cid, started = compared(client, project_dir, providers)
    ready(client, started["compare_id"])
    assert client.post(f"/api/compares/{started['compare_id']}/discard").status_code == 200
    assert not (project_dir / "a.txt").exists() and not (project_dir / "b.txt").exists()
    assert client.get(f"/api/compares/{started['compare_id']}").json()["status"] == "discarded"


def test_a_comparison_is_started_and_decided_only_from_the_apps_own_page(two, project_dir):
    client, providers = two([text("a")], [text("b")])
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    sides = [{"provider_id": p["id"]} for p in providers]
    url = f"/api/conversations/{cid}/compare"
    assert client.post(url, json={"content": "x", "sides": sides},
                       headers={"Origin": "http://elsewhere.example"}).status_code == 403
    assert client.post(url, json={"content": "x", "sides": sides[:1]}).status_code == 422
    assert client.post(url, json={"content": "x", "sides": [*sides[:1], {"provider_id": "nope"}]}).status_code == 422
