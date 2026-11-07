"""A role's, a provider's and an agent's name hold nothing that does not print: no control
character, none that turns the direction of the text, none with no width. Agents are told
these names as they are, and address each other by them."""

import json

import pytest

from app.db.models import Provider, Role
from app.roles import check_name
from app.team import choose, describe, guide
from tests.test_chat_flow import text
from tests.test_spawn import begin, new_role, spawn

ZERO_WIDTH, RIGHT_TO_LEFT, ISOLATE, BOM = chr(0x200B), chr(0x202E), chr(0x2066), chr(0xFEFF)
BAD = [
    f"Co{ZERO_WIDTH}der", f"{RIGHT_TO_LEFT}redoC", "Co\x00der", "Co\x1bder", f"Co{ISOLATE}der",
    f"Coder{BOM}",
]
ROLE_WHY = "a role name cannot contain control or invisible characters"
PROVIDER_WHY = "a provider name cannot contain control or invisible characters"


def test_names_in_any_alphabet_are_fine_and_spacing_is_evened_out():
    assert check_name("  Çevirmen\t2\n") == "Çevirmen 2"
    assert check_name("Reviewer-β 名前") == "Reviewer-β 名前"


@pytest.mark.parametrize("name", BAD)
def test_a_name_with_a_character_that_does_not_print_is_refused(client, name):
    with pytest.raises(ValueError) as refused:
        check_name(name)
    assert str(refused.value) == ROLE_WHY
    role = {"name": name, "description": "", "instructions": "", "tools": ["read_file"]}
    made = client.post("/api/roles", json=role)
    assert (made.status_code, made.json()["detail"]) == (422, ROLE_WHY)
    fine = client.post("/api/roles", json={**role, "name": "Documenter"}).json()
    renamed = client.patch(f"/api/roles/{fine['id']}", json={"name": name})
    assert (renamed.status_code, renamed.json()["detail"]) == (422, ROLE_WHY)

    provider = {"name": name, "kind": "openai_compat", "base_url": "http://127.0.0.1:9/v1"}
    made = client.post("/api/providers", json=provider)
    assert (made.status_code, made.json()["detail"]) == (422, PROVIDER_WHY)
    fine = client.post("/api/providers", json={**provider, "name": "Fast"}).json()
    renamed = client.patch(f"/api/providers/{fine['id']}", json={"name": name})
    assert (renamed.status_code, renamed.json()["detail"]) == (422, PROVIDER_WHY)
    assert name not in [r["name"] for r in client.get("/api/roles").json()]
    assert name not in [p["name"] for p in client.get("/api/providers").json()]


def test_an_agent_cannot_create_a_role_with_such_a_name(make_client, wait_run, project_dir):
    client, model = make_client([
        new_role(f"Doc{ZERO_WIDTH}writer", ["read_file"]), text("done")])
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    (asked,) = [t for t in snap["tool_calls"] if t["name"] == "create_role"]
    assert (asked["status"], asked["result"]) == ("failed", f"error: {ROLE_WHY}")


def test_a_role_from_before_is_shown_clean_and_its_agents_are_named_clean(
    make_client, wait_run, project_dir
):
    stored = f"Doc{ZERO_WIDTH}{RIGHT_TO_LEFT}writer"
    client, model = make_client({
        "Lead": [spawn("Doc writer"), text("done")], "Doc writer": [text("wrote it")]})
    with client.app.state.session_factory() as session:
        session.add(Role(name=stored, description="Writes docs", instructions="",
                         tools=["read_file"]))
        session.commit()
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    offered = next(
        t for t in model.tool_args[0] if t["function"]["name"] == "spawn_agent")
    assert "\n- Doc writer — Writes docs" in offered["function"]["description"]
    # nothing an agent was sent holds the characters, and the agent is named without them
    sent = json.dumps([model.calls, model.tool_args], ensure_ascii=False)
    assert ZERO_WIDTH not in sent and RIGHT_TO_LEFT not in sent
    child = snap["agents"][1]
    assert (child["name"], child["role_name"], child["status"]) == (
        "Doc writer", "Doc writer", "completed")
    # the record is the user's: it is not rewritten
    assert stored in [r["name"] for r in client.get("/api/roles").json()]


def test_a_provider_from_before_is_shown_clean_in_the_guide_and_chosen_by_that_name():
    row = Provider(id="p", name=f"Fa{ZERO_WIDTH}st{RIGHT_TO_LEFT}", kind="openai_compat",
                   for_agents=True, default_model="m")
    entries = guide([row])
    assert entries[0].name == "Fa st"
    assert '- "Fa st" (OpenAI-compatible server, API).' in describe(entries)
    entry, model = choose(entries, "fa  st", None)
    assert (entry.provider_id, model) == ("p", "m")
