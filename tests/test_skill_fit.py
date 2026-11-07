"""K-skill-uyum: a skill's `allowed-tools`, mapped by rule to KOLONİ's groups of tools, keeps it
from an agent that lacks one; a skill switched off on the Tools page, or a model the catalogue
says makes no tool calls, is given to nobody - and the agent's record says what it had."""

import json
import sys
from types import SimpleNamespace

from app import catalog, skills
from tests.test_chat_flow import text
from tests.test_skill_scenarios import ORIGIN, add, give
from tests.test_spawn import begin, call, spawn, step

HEAD = "---\nname: {name}\ndescription: Does it.\n{more}---\n\nBODY\n"


def md(more="", name="tidy"):
    return HEAD.format(name=name, more=more)


def test_allowed_tools_map_to_groups_servers_and_unknown_names_by_rule():
    found = skills.needs(md(
        "allowed-tools: Bash(git add:*), Read, Grep, WebFetch, mcp__github__issues, "
        "mcp__playwright__click, browser_open, Task, Edit\n"))
    assert found == {"groups": ["shell", "read files", "web", "browser", "write files"],
                     "mcp": ["github"], "unknown": ["Task"]}
    # The Agent Skills form: space between them, a rule in brackets kept with its tool.
    assert skills.declared(md("allowed-tools: Bash(git status:*) Read\n")) == [
        "Bash(git status:*)", "Read"]
    assert skills.needs(md("allowed-tools:\n  - KillShell\n  - LS\n"))["groups"] == [
        "shell", "read files"]
    # No line: nothing is asked, nothing said.
    assert skills.needs(md()) == {"groups": [], "mcp": [], "unknown": []}


def test_what_an_agent_lacks_and_why_each_skill_is_left_out():
    shell = SimpleNamespace(name="ship", enabled=True, text=md("allowed-tools: Bash\n", "ship"))
    plain = SimpleNamespace(name="tidy", enabled=True, text=md())
    off = SimpleNamespace(name="old", enabled=False, text=md(name="old"))
    hub = SimpleNamespace(name="hub", enabled=True,
                          text=md("allowed-tools: mcp__github__x, Task\n", "hub"))
    given, left = skills.split([shell, plain, off, hub], {"read_file"}, set(), False)
    assert [one.name for one in given] == ["tidy"]
    assert left == {"ship": "no shell", "old": "off on the Tools page",
                    "hub": "no MCP server github"}
    given, left = skills.split([shell, hub], {"run_command"}, {"github"}, False)
    assert [one.name for one in given] == ["ship", "hub"] and left == {}
    # A model that makes no tool calls is given none.
    assert skills.split([plain], set(), set(), True) == (
        [], {"tidy": "its model makes no tool calls"})


def test_only_the_catalogue_s_own_word_says_a_model_makes_no_tool_calls():
    copy = {"anthropic": {"models": {"mute": {"tool_call": False}, "talks": {"tool_call": True},
                                     "said-nothing": {}}}}
    provider = SimpleNamespace(kind="anthropic", base_url=None)
    assert catalog.no_tool_calls(provider, "mute", copy)
    assert not catalog.no_tool_calls(provider, "talks", copy)
    assert not catalog.no_tool_calls(provider, "said-nothing", copy)
    assert not catalog.no_tool_calls(provider, "unknown", copy)


def _skill(tmp_path, name, more=""):
    folder = tmp_path / name
    folder.mkdir()
    (folder / "SKILL.md").write_text(md(more, name), encoding="utf-8")
    return folder


def test_a_skill_the_agent_cannot_run_or_switched_off_is_not_given_and_its_record_says_why(
    make_client, wait_run, project_dir, tmp_path
):
    client, model = make_client([
        spawn("Researcher", "look it up"),
        step(call("use_skill", {"name": "ship"})),
        text("done"),
        text("ok"),
    ])
    add(client, _skill(tmp_path, "ship", "allowed-tools: Bash\n"))
    old = add(client, _skill(tmp_path, "old"))
    add(client, _skill(tmp_path, "plain", "allowed-tools: Read, Task\n"))
    switched = client.patch(f"/api/skills/{old['id']}", json={"enabled": False}, headers=ORIGIN)
    assert switched.status_code == 200 and switched.json()["enabled"] is False
    listed = {one["name"]: one for one in client.get("/api/skills").json()}
    assert listed["ship"]["needs"] == {
        "groups": ["shell"], "mcp": [], "unknown": [], "tools": {"shell": ["run_command"]}}
    assert listed["plain"]["needs"]["unknown"] == ["Task"] and listed["plain"]["version"] is None
    give(client, "Researcher", "ship", "old", "plain")
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    told = json.dumps(model.calls[1])
    # The Researcher has no run_command: "ship" never comes, nor the one switched off.
    assert "plain" in told and "ship" not in told and "old:" not in told
    refused = next(t for t in snap["tool_calls"] if t["name"] == "use_skill")
    assert refused["status"] in ("failed", "denied")
    researcher = next(a for a in snap["agents"] if a["role_name"] == "Researcher")
    assert researcher["skills"] == {
        "given": ["plain"], "left_out": {"ship": "no shell", "old": "off on the Tools page"}, "in_brief": []}
    # (R125: its opener is told so with the result, not the card alone)
    spawned = next(t for t in snap["tool_calls"] if t["name"] == "spawn_agent")
    assert spawned["result"].endswith(
        "\n\nSkills: plain given; left out: ship (no shell), old (off on the Tools page).")
    # The Lead's role has none: nothing on its record.
    assert next(a for a in snap["agents"] if a["depth"] == 0)["skills"] is None


def test_a_skill_that_asks_for_a_server_switched_off_is_left_out(make_client, tmp_path):
    client, _ = make_client([text("x")])
    made = client.post("/api/mcp-servers", json={"name": "hub", "command": [sys.executable]},
                       headers=ORIGIN)
    assert made.status_code == 201, made.text
    add(client, _skill(tmp_path, "hubby", "allowed-tools: mcp__hub__issues\n"))
    give(client, "Researcher", "hubby")
    runner = client.app.state.runner

    def split():
        with runner._factory() as session:
            given, left_out = runner._skill_split(session, "Researcher", ["read_file"], ["hub"],
                                                  None, None)
            return [skill.name for skill in given], left_out

    assert split() == (["hubby"], {})
    off = client.patch(f"/api/mcp-servers/{made.json()['id']}", json={"enabled": False},
                       headers=ORIGIN)
    assert off.status_code == 200, off.text
    assert split() == ([], {"hubby": "no MCP server hub"})
